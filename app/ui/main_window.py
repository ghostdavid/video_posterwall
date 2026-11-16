"""主窗口：季标题行与子视频缩进、季封面设置、可视化详情、二次确认写盘。

写盘约束：只创建 Season NN 目录、把视频与封面移动到所属季目录（不改名、不改内容），
以及生成 / 修改 / 删除 单集 .nfo、各季 season.nfo、tvshow.nfo、专辑/季封面。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..accel import BackendInfo, detect_backends
from ..constants import APP_NAME, APP_VERSION, default_threads, max_threads
from ..engine import Engine
from ..models import (
    POSTER_NAME,
    SEASON_NFO_NAME,
    Album,
    JobSummary,
    Settings,
    season_dir_name,
    season_poster_name,
)
from ..planner import build_plan
from ..show_name import describe_examples, parse_show_name
from .widgets import ElidedLabel, EpisodeTable, PosterPreview

COLUMNS = [
    "✓", "季", "集", "单集标题", "视频文件", "视频信息",
    "封面图", "封面信息", "NFO / 元数据", "目标路径", "状态",
]

IMAGE_FILTER = "图片文件 (*.jpg *.jpeg *.jpe *.jfif *.png *.webp *.bmp *.gif *.tif *.tiff *.tbn *.avif);;所有文件 (*)"
HEADER_BG = QColor("#e2ecf9")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1520, 900)
        self.setMinimumSize(960, 640)

        self.engine = Engine()
        self.album: Album | None = None
        self._backends: list[BackendInfo] = []
        self._row_map: list[tuple[str, int]] = []
        self._row_checkboxes: dict[int, QCheckBox] = {}
        self._row_season_combos: dict[int, QComboBox] = {}
        self._checked_ids: set[int] = set()
        self._refreshing = False
        self._saved_layout: list[tuple[str, int]] | None = None
        self._selected_season: int | None = None
        self.poster_source: Path | None = None
        self.poster_remove = False
        self.season_posters: dict[int, Path] = {}
        self.season_poster_remove: set[int] = set()

        self._build_ui()
        self._connect_signals()
        self._sync_backend_combo([], "auto")
        self.gpu_label.setText("GPU 后端未检测；选择文件夹自动扫描或点击「检测 GPU」后探测")
        self._update_poster_view()
        self._set_busy(False)
        self._log("就绪。请先选择视频专辑文件夹（会自动递归扫描所有子目录）。")
        self._log(f"剧集名规则：{describe_examples()}")

    # ------------------------------------------------------------------ 构建界面

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        outer.addWidget(self._build_settings_group())
        outer.addLayout(self._build_action_row())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_table_panel())
        self.splitter.addWidget(self._build_tabs())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(5)
        self.splitter.setStyleSheet(
            "QSplitter::handle{background:#c8d2de;}"
            "QSplitter::handle:hover{background:#1f5aa6;}"
        )
        outer.addWidget(self.splitter, 1)
        outer.addLayout(self._build_progress_row())
        self._content_horizontal: bool | None = None
        QTimer.singleShot(0, self._adapt_layout)

    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("专辑与生成设置")
        box.setToolTip("递归扫描所有子目录；媒体只移动，不改名、不改内容、不覆盖")
        layout = QGridLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("选择包含视频与同名封面的专辑文件夹")
        self.folder_edit.setMinimumWidth(120)
        self.btn_pick = QPushButton("选择文件夹…")
        self.btn_scan = QPushButton("重新载入")
        self.btn_scan.setToolTip("重新扫描并保留当前的季划分与季内顺序")
        layout.addWidget(QLabel("专辑目录："), 0, 0)
        layout.addWidget(self.folder_edit, 0, 1, 1, 7)
        layout.addWidget(self.btn_pick, 0, 8, 1, 2)
        layout.addWidget(self.btn_scan, 0, 10, 1, 2)

        self.show_label = ElidedLabel("剧集名：—")
        self.show_label.setStyleSheet("font-weight:600;color:#1f5aa6;")
        self.spin_seasons = QSpinBox()
        self.spin_seasons.setRange(1, 99)
        self.spin_seasons.setToolTip("同季内第 N 个视频即为第 N 集")
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, max_threads())
        self.spin_threads.setValue(default_threads())
        for spin in (self.spin_seasons, self.spin_threads):
            spin.setFixedWidth(64)
        self.combo_backend = QComboBox()
        self.combo_backend.setMinimumWidth(140)
        self.combo_backend.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.btn_detect = QPushButton("检测 GPU")
        layout.addWidget(self.show_label, 1, 0, 1, 4)
        layout.addWidget(QLabel("季数："), 1, 4)
        layout.addWidget(self.spin_seasons, 1, 5)
        layout.addWidget(QLabel("工作线程："), 1, 6)
        layout.addWidget(self.spin_threads, 1, 7)
        layout.addWidget(QLabel("加速后端："), 1, 8)
        layout.addWidget(self.combo_backend, 1, 9, 1, 2)
        layout.addWidget(self.btn_detect, 1, 11)

        self.poster_preview = PosterPreview("无")
        self.poster_preview.setFixedSize(52, 68)
        self.poster_info = ElidedLabel()
        self.btn_poster_from_row = QPushButton("用选中条目封面")
        self.btn_poster_custom = QPushButton("自定义选图…")
        self.btn_poster_clear = QPushButton("清除封面")
        self.gpu_label = ElidedLabel()
        self.gpu_label.setStyleSheet("color:#5a6572;")
        layout.addWidget(QLabel("专辑封面："), 2, 0)
        layout.addWidget(self.poster_preview, 2, 1)
        layout.addWidget(self.poster_info, 2, 2, 1, 2)
        layout.addWidget(self.btn_poster_from_row, 2, 4, 1, 2)
        layout.addWidget(self.btn_poster_custom, 2, 6, 1, 2)
        layout.addWidget(self.btn_poster_clear, 2, 8)
        layout.addWidget(self.gpu_label, 2, 9, 1, 3)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 2)
        layout.setColumnStretch(3, 2)
        layout.setColumnStretch(9, 1)
        return box

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.btn_generate = QPushButton("开始生成")
        self.btn_generate.setStyleSheet(
            "QPushButton{background:#1f5aa6;color:white;padding:6px 18px;font-weight:600;}"
            "QPushButton:disabled{background:#c8d2de;color:#66707c;}"
        )
        self.btn_undo = QPushButton("撤销本次操作")
        self.btn_stop = QPushButton("停止")
        row.addWidget(self.btn_generate)
        row.addWidget(self.btn_undo)
        row.addWidget(self.btn_stop)
        row.addStretch(1)
        return row

    def _build_table_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumSize(0, 0)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        toolbar = QHBoxLayout()
        self.btn_select_all = QPushButton("全选")
        self.btn_select_none = QPushButton("清空选择")
        self.btn_move_up = QPushButton("上移")
        self.btn_move_down = QPushButton("下移")
        self.btn_move_up.setToolTip("与同一季的上一个视频交换顺序")
        self.btn_move_down.setToolTip("与同一季的下一个视频交换顺序")
        self.btn_delete_nfo = QPushButton("删除所选 NFO")
        self.btn_delete_nfo.setStyleSheet("QPushButton{color:#a12b28;font-weight:600;}")
        for button in (self.btn_select_all, self.btn_select_none, self.btn_move_up,
                       self.btn_move_down, self.btn_delete_nfo):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = EpisodeTable()
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTriggers.NoEditTriggers)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(28)
        header.setStretchLastSection(False)
        self.table.fit_columns()
        layout.addWidget(self.table, 1)
        return panel

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setMinimumSize(0, 0)

        detail = QWidget()
        detail.setMinimumWidth(0)
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(6, 6, 6, 6)
        detail_layout.setSpacing(6)
        self.detail_caption = ElidedLabel("选中一行查看详情")
        self.detail_caption.setStyleSheet("font-weight:600;font-size:13px;color:#1f5aa6;")
        self.detail_cover = PosterPreview("选中季或视频条目后预览封面")
        self.detail_cover.setMinimumHeight(140)
        self.detail_cover.setMaximumHeight(240)

        self.detail_table = QTableWidget(0, 2)
        self.detail_table.setHorizontalHeaderLabels(["字段", "值"])
        self.detail_table.setEditTriggers(QAbstractItemView.EditTriggers.NoEditTriggers)
        self.detail_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.detail_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.verticalHeader().setDefaultSectionSize(28)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(48)
        self.detail_table.setColumnWidth(0, 132)
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setMinimumSize(0, 180)
        self.detail_table.setWordWrap(False)

        self.season_cover_group = QGroupBox("季封面设置")
        self.season_cover_group.setToolTip(
            "在季目录同时生成 seasonNN-poster.jpg 与 poster.jpg"
        )
        season_layout = QVBoxLayout(self.season_cover_group)
        self.season_cover_combo = QComboBox()
        self.season_cover_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.season_cover_combo.setMinimumContentsLength(8)
        season_buttons = QHBoxLayout()
        self.btn_season_from_combo = QPushButton("用条目封面")
        self.btn_season_custom = QPushButton("自定义选图…")
        self.btn_season_clear = QPushButton("清除季封面")
        for button in (self.btn_season_from_combo, self.btn_season_custom,
                       self.btn_season_clear):
            season_buttons.addWidget(button)
        season_buttons.addStretch(1)
        season_layout.addWidget(self.season_cover_combo)
        season_layout.addLayout(season_buttons)
        self.season_cover_group.setEnabled(False)
        self.season_cover_group.setVisible(False)

        detail_layout.addWidget(self.detail_caption)
        detail_layout.addWidget(self.detail_cover)
        detail_layout.addWidget(self.season_cover_group)
        detail_layout.addWidget(QLabel("元数据信息"))
        detail_layout.addWidget(self.detail_table, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:0;}")
        scroll.setWidget(detail)
        tabs.addTab(scroll, "详情")

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(3000)
        log_layout.addWidget(self.log_text)
        tabs.addTab(log_page, "运行日志")
        self.tabs = tabs
        return tabs

    def _build_progress_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setMinimumWidth(120)
        self.status_label = ElidedLabel("就绪")
        row.addWidget(QLabel("进度："))
        row.addWidget(self.progress, 1)
        row.addWidget(self.status_label, 2)
        return row

    def _adapt_layout(self) -> None:
        horizontal = self.width() >= 1180
        if self._content_horizontal == horizontal:
            return
        self._content_horizontal = horizontal
        self.splitter.setOrientation(
            Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        )
        total = self.splitter.width() if horizontal else self.splitter.height()
        if total > 0:
            first = total * 3 // 5
            self.splitter.setSizes([first, max(200, total - first)])
        self.table.fit_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adapt_layout()

    # ------------------------------------------------------------------ 信号

    def _connect_signals(self) -> None:
        self.btn_pick.clicked.connect(self._on_pick)
        self.btn_scan.clicked.connect(lambda _checked=False: self._on_scan("重新载入"))
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_undo.clicked.connect(self._on_undo)
        self.btn_stop.clicked.connect(self.engine.cancel)
        self.btn_detect.clicked.connect(self._on_detect_gpu)
        self.btn_poster_from_row.clicked.connect(self._on_poster_from_row)
        self.btn_poster_custom.clicked.connect(self._on_poster_custom)
        self.btn_poster_clear.clicked.connect(self._on_poster_clear)
        self.spin_seasons.valueChanged.connect(self._on_season_count_changed)
        self.btn_select_all.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_select_none.clicked.connect(lambda: self._set_all_checked(False))
        self.btn_move_up.clicked.connect(lambda: self._move_row(-1))
        self.btn_move_down.clicked.connect(lambda: self._move_row(1))
        self.btn_delete_nfo.clicked.connect(self._on_delete_nfos)
        self.btn_season_from_combo.clicked.connect(self._on_season_cover_from_combo)
        self.btn_season_custom.clicked.connect(self._on_season_cover_custom)
        self.btn_season_clear.clicked.connect(self._on_season_cover_clear)

        self.table.itemSelectionChanged.connect(self._on_row_selected)
        signals = self.engine.signals
        signals.log.connect(self._log)
        signals.progress.connect(self._on_progress)
        signals.scan_done.connect(self._on_scan_done)
        signals.gen_done.connect(self._on_gen_done)
        signals.delete_done.connect(self._on_delete_done)
        signals.undo_done.connect(self._on_undo_done)
        signals.cancelled.connect(self._on_cancelled)
        signals.failed.connect(self._on_failed)

    # ------------------------------------------------------------------ 设置与状态

    def _read_settings(self) -> Settings:
        return Settings(
            threads=self.spin_threads.value(),
            backend=self.combo_backend.currentData() or "auto",
            season_count=self.spin_seasons.value(),
            poster_source=self.poster_source,
            poster_remove=self.poster_remove,
            season_posters=dict(self.season_posters),
            season_poster_remove=set(self.season_poster_remove),
        )

    def _sync_backend_combo(self, backends: list[BackendInfo], current: str) -> None:
        self._backends = backends
        self.combo_backend.blockSignals(True)
        self.combo_backend.clear()
        self.combo_backend.addItem("自动（优先 GPU）", "auto")
        self.combo_backend.addItem("CPU 多线程", "cpu")
        for backend in backends:
            if backend.kind == "gpu":
                self.combo_backend.addItem(f"{backend.label} · {backend.device}", backend.key)
        index = self.combo_backend.findData(current)
        self.combo_backend.setCurrentIndex(index if index >= 0 else 0)
        self.combo_backend.blockSignals(False)

    def _set_busy(self, busy: bool) -> None:
        ready = not busy
        has_album = self.album is not None
        self.btn_pick.setEnabled(ready)
        self.btn_scan.setEnabled(ready)
        self.btn_generate.setEnabled(ready and has_album)
        self.btn_detect.setEnabled(ready)
        self.btn_poster_from_row.setEnabled(ready and has_album)
        self.btn_poster_custom.setEnabled(ready)
        self.btn_poster_clear.setEnabled(ready)
        self.spin_seasons.setEnabled(ready)
        self.spin_threads.setEnabled(ready)
        self.combo_backend.setEnabled(ready)
        self.btn_select_all.setEnabled(ready and has_album)
        self.btn_select_none.setEnabled(ready and has_album)
        self.btn_move_up.setEnabled(ready and has_album)
        self.btn_move_down.setEnabled(ready and has_album)
        self.btn_delete_nfo.setEnabled(ready and has_album)
        self.btn_undo.setEnabled(ready and self.engine.can_undo)
        self.btn_stop.setEnabled(busy)
        self.season_cover_group.setEnabled(ready and self._selected_season is not None)
        for control in (*self._row_checkboxes.values(), *self._row_season_combos.values()):
            control.setEnabled(ready)

    def _capture_layout(self) -> list[tuple[str, int]] | None:
        if self.album is None:
            return None
        return [
            (episode.video.path.name.casefold(), episode.season)
            for episode in self.album.episodes if episode.video
        ]

    def _restore_layout(self, layout: list[tuple[str, int]] | None) -> None:
        if not layout or self.album is None:
            return
        order = {name: index for index, (name, _) in enumerate(layout)}
        seasons: dict[str, int] = {}
        for name, season in layout:
            seasons.setdefault(name, season)
        maximum = self.spin_seasons.value()
        for episode in self.album.episodes:
            key = episode.video.path.name.casefold() if episode.video else ""
            if key in seasons:
                episode.season = min(max(1, seasons[key]), maximum)
        self.album.episodes.sort(
            key=lambda e: (
                e.season,
                order.get(e.video.path.name.casefold() if e.video else "", 1 << 30),
                e.order,
            )
        )
        for index, episode in enumerate(self.album.episodes):
            episode.order = index

    def _fix_poster_sources(self) -> None:
        """媒体移动到季目录后，按文件名把封面来源重新指向新路径。"""
        if self.album is None:
            return
        lookup: dict[str, Path] = {}
        for episode in self.album.episodes:
            if episode.cover:
                lookup.setdefault(episode.cover.path.name.casefold(), episode.cover.path)
        if self.poster_source and not self.poster_source.is_file():
            replacement = lookup.get(self.poster_source.name.casefold())
            if replacement:
                self.poster_source = replacement
                self._log(f"专辑封面来源已跟随移动到：{replacement}")
        for number, source in list(self.season_posters.items()):
            if not source.is_file():
                replacement = lookup.get(source.name.casefold())
                if replacement:
                    self.season_posters[number] = replacement
                    self._log(f"第 {number} 季封面来源已跟随移动到：{replacement}")

    # ------------------------------------------------------------------ 封面

    def _existing_poster(self) -> Path | None:
        if self.album:
            candidate = self.album.root / POSTER_NAME
            if candidate.is_file():
                return candidate
        return None

    def _effective_season_poster(self, number: int) -> Path | None:
        if self.album is None:
            return None
        if number in self.season_poster_remove:
            return None
        chosen = self.season_posters.get(number)
        if chosen is not None:
            return chosen if chosen.is_file() else None
        directory = self.album.root / season_dir_name(number)
        for name in (season_poster_name(number), POSTER_NAME):
            existing = directory / name
            if existing.is_file():
                return existing
        old_root = self.album.root / season_poster_name(number)
        if old_root.is_file():
            return old_root
        for episode in self.album.episodes:
            if episode.season == number and episode.cover:
                return episode.cover.path
        return None

    def _season_poster_text(self, number: int) -> str:
        if number in self.season_poster_remove:
            return "已清除（生成时删除季封面）"
        if number in self.season_posters:
            return f"自定义：{self.season_posters[number].name}"
        if self.album:
            directory = self.album.root / season_dir_name(number)
            named = directory / season_poster_name(number)
            if named.is_file():
                return f"沿用已有 {named.name}"
            if (directory / POSTER_NAME).is_file():
                return f"沿用已有 {POSTER_NAME}"
            old_root = self.album.root / season_poster_name(number)
            if old_root.is_file():
                return f"沿用已有 {old_root.name}（生成时迁移到季目录）"
        for episode in (self.album.episodes if self.album else []):
            if episode.season == number and episode.cover:
                return f"默认：本季首个条目的封面（{episode.cover.name}）"
        return "本季暂无可用封面"

    def _set_preview(self, label: PosterPreview, path: Path | None, empty: str) -> None:
        label.set_image(path, empty)

    def _update_poster_view(self) -> None:
        if self.poster_source:
            self.poster_info.setText(
                f"已选：{self.poster_source.name}（生成时转换为 {POSTER_NAME}）"
            )
            candidate: Path | None = self.poster_source
        elif self.poster_remove and self._existing_poster():
            self.poster_info.setText(f"已清除：生成时删除已有 {POSTER_NAME}")
            candidate = None
        else:
            existing = self._existing_poster()
            if existing:
                self.poster_info.setText(f"沿用已有 {POSTER_NAME}（未设置更改）")
                candidate = existing
            else:
                self.poster_info.setText(f"未设置专辑封面（不生成 {POSTER_NAME}）")
                candidate = None
        self._set_preview(self.poster_preview, candidate, "无")

    def _current_episode_index(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_map):
            return None
        kind, value = self._row_map[row]
        return value if kind == "episode" else None

    def _set_poster(self, path: Path, label: str) -> None:
        self.poster_source = path
        self.poster_remove = False
        self._update_poster_view()
        self._log(f"专辑封面来源：{label} -> {path}")
        self._rebuild_plan()

    def _on_poster_from_row(self) -> None:
        index = self._current_episode_index()
        if self.album is None or index is None:
            QMessageBox.information(self, "提示", "请先在表格中选中一个子视频行")
            return
        episode = self.album.episodes[index]
        if episode.cover is None:
            QMessageBox.information(self, "提示", "该条目没有同名封面图，可用「自定义选图…」")
            return
        self._set_poster(episode.cover.path, f"{episode.title} · {episode.cover.name}")

    def _on_poster_custom(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "选择专辑封面图片", self.folder_edit.text() or "", IMAGE_FILTER
        )
        if chosen:
            self._set_poster(Path(chosen), f"自定义 · {Path(chosen).name}")

    def _on_poster_clear(self) -> None:
        self.poster_source = None
        self.poster_remove = True
        self._update_poster_view()
        self._log(f"已清除专辑封面；生成时若存在 {POSTER_NAME} 会将其删除")
        self._rebuild_plan()

    # ------------------------------------------------------------- 季封面设置

    def _on_season_cover_from_combo(self) -> None:
        if self._selected_season is None:
            return
        path = self.season_cover_combo.currentData()
        if not isinstance(path, Path):
            QMessageBox.information(self, "提示", "该季没有可选的条目封面，请用「自定义选图…」")
            return
        number = self._selected_season
        self.season_posters[number] = path
        self.season_poster_remove.discard(number)
        self._log(f"第 {number} 季封面：{path.name}")
        self._rebuild_plan()
        self._refresh_table()

    def _on_season_cover_custom(self) -> None:
        if self._selected_season is None:
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"选择第 {self._selected_season} 季封面图片",
            self.folder_edit.text() or "", IMAGE_FILTER,
        )
        if chosen:
            number = self._selected_season
            self.season_posters[number] = Path(chosen)
            self.season_poster_remove.discard(number)
            self._log(f"第 {number} 季封面（自定义）：{Path(chosen).name}")
            self._rebuild_plan()
            self._refresh_table()

    def _on_season_cover_clear(self) -> None:
        if self._selected_season is None:
            return
        number = self._selected_season
        self.season_posters.pop(number, None)
        self.season_poster_remove.add(number)
        self._log(f"已清除第 {number} 季封面；生成时删除该季封面文件")
        self._rebuild_plan()
        self._refresh_table()

    # ------------------------------------------------------------------ 季与排序

    def _on_season_count_changed(self, value: int) -> None:
        if self.album is None or self._refreshing or self.engine.busy:
            return
        for episode in self.album.episodes:
            episode.season = min(episode.season, value)
        self.season_posters = {n: p for n, p in self.season_posters.items() if n <= value}
        self.season_poster_remove = {n for n in self.season_poster_remove if n <= value}
        self.album.episodes.sort(key=lambda e: (e.season, e.order))
        for index, episode in enumerate(self.album.episodes):
            episode.order = index
        self._rebuild_plan()
        self._refresh_table()
        self._log(f"季数设为 {value}；超出范围的季已归到第 {value} 季")

    def _on_season_combo(self, combo: QComboBox) -> None:
        if self._refreshing or self.album is None or self.engine.busy:
            return
        row = next((r for r, c in self._row_season_combos.items() if c is combo), None)
        if row is None or row >= len(self._row_map):
            return
        kind, index = self._row_map[row]
        if kind != "episode":
            return
        new_season = combo.currentData()
        if not isinstance(new_season, int):
            return
        QTimer.singleShot(0, lambda: self._change_season(index, new_season))

    def _change_season(self, index: int, new_season: int) -> None:
        episodes = self.album.episodes
        if index < 0 or index >= len(episodes) or episodes[index].season == new_season:
            return
        moving = episodes.pop(index)
        moving.season = new_season
        last_same = max(
            (i for i, item in enumerate(episodes) if item.season == new_season), default=-1
        )
        if last_same >= 0:
            insert_at = last_same + 1
        else:
            insert_at = next(
                (i for i, item in enumerate(episodes) if item.season > new_season),
                len(episodes),
            )
        episodes.insert(insert_at, moving)
        for i, item in enumerate(episodes):
            item.order = i
        self._rebuild_plan()
        self._refresh_table()
        self._select_episode(moving)

    def _select_episode(self, target) -> None:
        index = next((i for i, e in enumerate(self.album.episodes) if e is target), None)
        if index is None:
            return
        row = next(
            (r for r, (kind, value) in enumerate(self._row_map)
             if kind == "episode" and value == index), None
        )
        if row is not None:
            self.table.selectRow(row)

    def _move_row(self, delta: int) -> None:
        if self.album is None or self.engine.busy:
            return
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_map):
            return
        kind, index = self._row_map[row]
        if kind != "episode":
            self.status_label.setText("请选中某个子视频行再调整顺序")
            return
        episode_rows = [r for r, (k, _) in enumerate(self._row_map) if k == "episode"]
        position = episode_rows.index(row)
        target_position = position + delta
        if target_position < 0 or target_position >= len(episode_rows):
            return
        target_row = episode_rows[target_position]
        _, target_index = self._row_map[target_row]
        episodes = self.album.episodes
        if episodes[target_index].season != episodes[index].season:
            self.status_label.setText("只能在同一季内调整顺序")
            return
        moving = episodes[index]
        episodes[index], episodes[target_index] = episodes[target_index], episodes[index]
        for i, item in enumerate(episodes):
            item.order = i
        self._rebuild_plan()
        self._refresh_table()
        self._select_episode(moving)

    # ------------------------------------------------------------------ 槽函数

    def _on_pick(self) -> None:
        options = QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks
        chosen = QFileDialog.getExistingDirectory(
            self, "选择视频专辑文件夹", self.folder_edit.text() or "", options
        )
        if not chosen:
            return
        root = Path(chosen)
        self.folder_edit.setText(str(root))
        show_name, source = parse_show_name(root.name)
        self.show_label.setText(f"剧集名：{show_name}　（{source}）")
        self.album = None
        self._saved_layout = None
        self._selected_season = None
        self.poster_source = None
        self.poster_remove = False
        self.season_posters = {}
        self.season_poster_remove = set()
        self.table.setRowCount(0)
        self._row_map = []
        self._row_checkboxes = {}
        self._row_season_combos = {}
        self._clear_details()
        self._update_poster_view()
        self._set_busy(False)
        self._log(f"已选择文件夹：{root}")
        self._log(f"解析剧集名：{show_name}（{source}）")
        self._on_scan("选择文件夹后自动扫描")

    def _on_scan(self, reason: str = "重新载入") -> None:
        text = self.folder_edit.text().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先选择视频专辑文件夹")
            return
        root = Path(text)
        if not root.is_dir():
            QMessageBox.warning(self, "提示", f"文件夹不存在或不可访问：\n{root}")
            return
        if self.engine.busy:
            return
        self._saved_layout = self._capture_layout()
        self._checked_ids.clear()
        self.album = None
        self.table.setRowCount(0)
        self._row_map = []
        self._row_checkboxes = {}
        self._row_season_combos = {}
        self._clear_details()
        self._set_busy(True)
        self._log(f"{reason}（递归扫描所有子目录，线程数 {self.spin_threads.value()}，"
                 f"{self.spin_seasons.value()} 季）…")
        if not self.engine.scan(root, self._read_settings()):
            self._set_busy(False)

    def _on_detect_gpu(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            backends = detect_backends()
        finally:
            QApplication.restoreOverrideCursor()
        self._sync_backend_combo(backends, self.engine.backend_key)
        gpu = [b for b in backends if b.kind == "gpu"]
        if gpu:
            self.gpu_label.setText("GPU 可用：" + "；".join(f"{b.label} / {b.device}" for b in gpu))
        else:
            self.gpu_label.setText("未检测到 CUDA 后端，已自动回退 CPU 多线程；GPU 为可选能力")

    def _on_generate(self) -> None:
        if self.album is None or self.engine.busy:
            return
        settings = self._read_settings()
        self._rebuild_plan()
        album = self.album
        enabled = [a for a in album.plan if a.enabled]
        counts = Counter(a.kind for a in enabled)
        moves = counts.get("move", 0)
        skipped = len(album.plan) - len(enabled)
        summary = [
            f"剧集名：{album.show_name}，季数：{album.season_count}，条目：{len(album.episodes)}",
            "",
            f"创建季目录 {counts.get('mkdir', 0)} 个",
            f"写入/更新 NFO {counts.get('write', 0)} 个（含各季 season.nfo 与单集 NFO）",
            f"写入专辑/季封面 {counts.get('write_bytes', 0)} 个",
            f"移动视频与封面 {moves} 个（不改名、不改内容、不覆盖）",
            f"删除/清理文件 {counts.get('delete', 0)} 个，跳过 {skipped} 条动作",
            "",
            f"所有写入仅限：{album.root}",
            "原内容保存在内存中，可用「撤销本次操作」恢复。",
        ]
        answer = QMessageBox.question(
            self, "确认生成", "\n".join(summary),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._log("用户取消写盘")
            return
        if moves:
            warning = QMessageBox.warning(
                self, "二次确认：即将移动媒体文件",
                f"本次将把 {moves} 个视频/封面文件从当前位置移动到 Season NN 目录。\n\n"
                "文件不会被改名，内容不会被修改，也不会覆盖已有文件，"
                "但目录结构会发生变化。\n\n确定继续执行吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if warning != QMessageBox.StandardButton.Yes:
                self._log("用户在二次确认中取消")
                return
        self._set_busy(True)
        self._log(f"开始生成：{len(enabled)} 条动作，线程数 {settings.threads}")
        if not self.engine.generate(album, settings):
            self._set_busy(False)

    def _on_undo(self) -> None:
        if self.engine.busy:
            return
        answer = QMessageBox.question(
            self, "确认撤销",
            "将把本次移动的视频与封面移回原位，恢复被覆盖 / 删除的 NFO 与封面，"
            "删除本次新建的文件与空的季目录。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        if not self.engine.undo():
            self._set_busy(False)

    # ------------------------------------------------------------------ 勾选与删除 NFO

    def _set_all_checked(self, checked: bool) -> None:
        for checkbox in self._row_checkboxes.values():
            try:
                checkbox.setChecked(checked)
            except RuntimeError:
                continue

    def _on_episode_checked(self, key: int, checked: bool) -> None:
        if checked:
            self._checked_ids.add(key)
        else:
            self._checked_ids.discard(key)

    def _checked_episode_indices(self) -> list[int]:
        if self.album is None:
            return []
        return [
            index for index, episode in enumerate(self.album.episodes)
            if id(episode) in self._checked_ids
        ]

    def _on_delete_nfos(self) -> None:
        if self.album is None or self.engine.busy:
            return
        indices = self._checked_episode_indices()
        if not indices:
            QMessageBox.information(self, "提示", "请先在表格第一列勾选要处理的子视频")
            return
        candidates: dict[str, Path] = {}
        for index in indices:
            episode = self.album.episodes[index]
            for path in (episode.existing_nfo_path, episode.nfo_path):
                if path and path.is_file():
                    candidates[str(path.resolve()).casefold()] = path
        paths = list(candidates.values())
        if not paths:
            QMessageBox.information(self, "提示", "所选条目当前没有可删除的 NFO 文件")
            return
        names = "、".join(p.name for p in paths[:8])
        if len(paths) > 8:
            names += f" 等共 {len(paths)} 个"
        answer = QMessageBox.question(
            self, "确认删除 NFO",
            f"将删除以下单集 NFO 文件：\n{names}\n\n"
            "视频和图片原文件不受影响。删除后可用「撤销本次操作」恢复。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True)
        self._log(f"准备删除 {len(paths)} 个单集 NFO")
        if not self.engine.delete_nfos(self.album, paths, self._read_settings()):
            self._set_busy(False)

    # ------------------------------------------------------------------ 引擎回调

    def _on_scan_done(self, payload: dict) -> None:
        self.album = payload["album"]
        self._sync_backend_combo(payload["backends"], payload["backend_key"])
        gpu = [b for b in self._backends if b.kind == "gpu"]
        self.gpu_label.setText(
            f"当前后端：{self.album.backend_label}；"
            + (f"检测到 {len(gpu)} 个 CUDA 后端" if gpu else "未检测到 CUDA 后端，使用 CPU 多线程")
        )
        self._restore_layout(self._saved_layout)
        self._saved_layout = None
        self._fix_poster_sources()
        self._update_poster_view()
        self._rebuild_plan()
        self._refresh_table()
        self._set_busy(False)
        self.status_label.setText(
            f"扫描完成：{len(self.album.episodes)} 个条目 / {self.album.season_count} 季"
        )

    def _on_gen_done(self, summary: JobSummary) -> None:
        self._set_busy(False)
        message = (
            f"成功 {summary.ok} 条，失败 {summary.failed} 条，跳过 {summary.skipped} 条"
            + ("（已中止）" if summary.cancelled else "")
        )
        self.status_label.setText(message)
        self._log(f"生成结束：{message}")
        if summary.messages:
            self._log("失败明细：\n  " + "\n  ".join(summary.messages[:12]))
        detail = (
            "部分动作未执行或失败，请查看运行日志。"
            if summary.failed or summary.cancelled else "所有计划动作已完成。"
        )
        QMessageBox.information(self, "生成结果", f"{message}\n\n{detail}\n将自动刷新列表。")
        self._schedule_reload("生成后自动刷新")

    def _on_delete_done(self, payload: dict) -> None:
        summary: JobSummary = payload["summary"]
        deleted = {p.casefold() for p in payload["paths"]}
        if self.album:
            for episode in self.album.episodes:
                for path in (episode.existing_nfo_path, episode.nfo_path):
                    if path and str(path.resolve()).casefold() in deleted:
                        episode.existing_nfo_text = None
                        episode.existing_nfo_path = None
                        episode.nfo_fields = {}
                        episode.status = "NFO 已删除"
            self._rebuild_plan()
            self._refresh_table()
        self._set_busy(False)
        message = (
            f"删除完成：成功 {summary.ok}，失败 {summary.failed}，跳过 {summary.skipped}"
            + ("（已中止）" if summary.cancelled else "")
        )
        self.status_label.setText(message)
        self._log(message)

    def _on_undo_done(self, summary: JobSummary) -> None:
        self._set_busy(False)
        message = f"撤销完成：成功 {summary.ok}，失败 {summary.failed}"
        if summary.cancelled:
            message += "（已中止）"
        if self.engine.can_undo:
            message += "；未完成的记录可重试"
        self.status_label.setText(message)
        if summary.messages:
            self._log("撤销失败明细：\n  " + "\n  ".join(summary.messages[:12]))
        self._schedule_reload("撤销后自动刷新")

    def _schedule_reload(self, reason: str, attempt: int = 0) -> None:
        if self.engine.busy and attempt < 20:
            QTimer.singleShot(100, lambda: self._schedule_reload(reason, attempt + 1))
            return
        self._on_scan(reason)

    def _on_cancelled(self, message: str) -> None:
        self._set_busy(False)
        self.status_label.setText(message)

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self._log(message)
        QMessageBox.critical(self, "任务失败", message)

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        self.status_label.setText(message)

    # ------------------------------------------------------------------ 表格

    def _rebuild_plan(self) -> None:
        if self.album is not None:
            build_plan(self.album, self._read_settings())

    def _refresh_table(self) -> None:
        if self.album is None:
            return
        self._refreshing = True
        self.table.blockSignals(True)
        # 清空旧行及内嵌控件，避免季行残留子视频控件。
        self.table.setRowCount(0)
        self._row_checkboxes.clear()
        self._row_season_combos.clear()
        episodes = self.album.episodes
        grouped: dict[int, list[int]] = {number: [] for number in self.album.seasons}
        for index, episode in enumerate(episodes):
            grouped[episode.season].append(index)
        rows: list[tuple[str, int]] = []
        for number, indices in grouped.items():
            rows.append(("season", number))
            rows.extend(("episode", index) for index in indices)
        self.table.setRowCount(len(rows))
        self._row_map = rows
        seasons = self.spin_seasons.value()
        bold = QFont()
        bold.setBold(True)

        for row, (kind, value) in enumerate(rows):
            if kind == "season":
                number = value
                count = len(grouped[number])
                directory = self.album.root / season_dir_name(number)
                poster = self._effective_season_poster(number)
                values = [
                    # 季行的「季」列留空：季号由季标题固定，只有子视频行能改季
                    "", "", "", f"第 {number} 季",
                    f"共 {count} 集", "季标题行",
                    Path(poster).name if poster else "—",
                    self._season_poster_text(number),
                    f"{directory.name}/{SEASON_NFO_NAME}",
                    f"{directory.name}/",
                    "季级元数据",
                ]
                for column, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setBackground(HEADER_BG)
                    item.setFont(bold)
                    item.setToolTip(text)
                    # 季行只读：不允许编辑任何单元格
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    )
                    self.table.setItem(row, column, item)
                continue

            index = value
            episode = episodes[index]
            video, cover = episode.video, episode.cover
            existing = "无"
            if episode.has_nfo:
                existing = (
                    f"{episode.existing_nfo_path.name if episode.existing_nfo_path else 'NFO'}"
                    + "：" + " / ".join(
                        f"{key}={episode.nfo_fields[key]}"
                        for key in ("title", "season", "episode", "thumb")
                        if key in episode.nfo_fields
                    )
                )
            nfo_target = (
                f"{episode.nfo_path.parent.name}/{episode.nfo_path.name}"
                if episode.nfo_path else "—"
            )
            values = [
                "", "", str(episode.episode_no), "　　└ " + episode.title,
                video.name if video else "—",
                video.summary() + (f"（{video.note}）" if video and video.note else "") if video else "—",
                cover.name if cover else "—",
                cover.summary() + (f"（{cover.note}）" if cover and cover.note else "") if cover else "—",
                existing, nfo_target,
                f"{episode.status}｜{episode.issue_text}"
                + (f"｜指纹 {episode.fingerprint[:8]}" if episode.fingerprint else ""),
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(text)
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
                self.table.setItem(row, column, item)

            checkbox = QCheckBox()
            checkbox.setChecked(id(episode) in self._checked_ids)
            checkbox.toggled.connect(
                lambda checked, key=id(episode): self._on_episode_checked(key, checked)
            )
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder_layout.addWidget(checkbox)
            self.table.setCellWidget(row, 0, holder)
            self._row_checkboxes[row] = checkbox

            season_combo = QComboBox()
            season_combo.blockSignals(True)
            for number in range(1, seasons + 1):
                season_combo.addItem(f"{number}", number)
            season_combo.setCurrentIndex(max(0, min(seasons - 1, episode.season - 1)))
            season_combo.blockSignals(False)
            season_combo.currentIndexChanged.connect(
                lambda _i, combo=season_combo: self._on_season_combo(combo)
            )
            self.table.setCellWidget(row, 1, season_combo)
            self._row_season_combos[row] = season_combo

        self.table.blockSignals(False)
        self._refreshing = False
        self._refresh_current_detail()

    # ------------------------------------------------------------------ 详情可视化

    def _set_detail_rows(self, rows: list[tuple[str, str]]) -> None:
        self.detail_table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for row, (field, value) in enumerate(rows):
            field_item = QTableWidgetItem(field)
            field_item.setFont(bold)
            field_item.setToolTip(field)
            value_item = QTableWidgetItem(value)
            value_item.setToolTip(value)
            self.detail_table.setItem(row, 0, field_item)
            self.detail_table.setItem(row, 1, value_item)

    def _clear_details(self) -> None:
        self._selected_season = None
        self.detail_caption.setText("选中一行查看详情")
        self._set_preview(
            self.detail_cover, None,
            "选中季标题行预览季封面，选中子视频行预览该条目封面",
        )
        self._set_detail_rows([])
        self.season_cover_combo.clear()
        self.season_cover_group.setEnabled(False)
        self.season_cover_group.setVisible(False)

    def _refresh_current_detail(self) -> None:
        row = self.table.currentRow()
        if self.album is None or row < 0 or row >= len(self._row_map):
            self._clear_details()
            return
        kind, value = self._row_map[row]
        if kind == "season":
            self._show_season_details(value)
        else:
            self._show_episode_details(value)

    def _on_row_selected(self) -> None:
        if not self._refreshing:
            self._refresh_current_detail()

    def _show_season_details(self, number: int) -> None:
        self._selected_season = number
        album = self.album
        directory = album.root / season_dir_name(number)
        count = sum(1 for e in album.episodes if e.season == number)
        poster = self._effective_season_poster(number)
        self.detail_caption.setText(f"第 {number} 季 · 季级元数据")
        self._set_preview(
            self.detail_cover, poster,
            "该季暂无封面；可在本页下方设置",
        )
        nfo_path = directory / SEASON_NFO_NAME
        self._set_detail_rows([
            ("类型", "季"),
            ("季标题 / title", f"第 {number} 季"),
            ("季名称 / seasonname", f"第 {number} 季"),
            ("季编号 / seasonnumber", str(number)),
            ("排序 / sorttitle", f"{album.show_name} {number:02d}"),
            ("所属剧集 / showtitle", album.show_name),
            ("本季条目数", f"{count} 个"),
            ("季目录", str(directory)),
            ("season.nfo", str(nfo_path)),
            ("season.nfo 状态", "磁盘上已存在" if nfo_path.is_file() else "待生成"),
            ("季封面（本工具命名）", str(directory / season_poster_name(number))),
            ("季封面（Jellyfin/Emby 读取）", str(directory / POSTER_NAME)),
            ("季封面来源", self._season_poster_text(number)),
            ("season.nfo 封面引用",
             "写入 poster.jpg" if album.season_planned_poster.get(number) else "不写入"),
        ])
        self.season_cover_group.setTitle(f"第 {number} 季封面设置")
        self.season_cover_group.setVisible(True)
        self.season_cover_combo.blockSignals(True)
        self.season_cover_combo.clear()
        for episode in album.episodes:
            if episode.season == number and episode.cover:
                self.season_cover_combo.addItem(
                    f"第 {episode.episode_no} 集 · {episode.title}（{episode.cover.name}）",
                    episode.cover.path,
                )
        if not self.season_cover_combo.count():
            self.season_cover_combo.addItem("本季没有可用的条目封面", None)
        self.season_cover_combo.blockSignals(False)
        self.season_cover_group.setEnabled(not self.engine.busy)

    def _show_episode_details(self, index: int) -> None:
        self._selected_season = None
        self.season_cover_combo.clear()
        self.season_cover_group.setEnabled(False)
        self.season_cover_group.setVisible(False)
        album = self.album
        episode = album.episodes[index]
        video, cover = episode.video, episode.cover
        self.detail_caption.setText(
            f"第 {episode.season} 季 · 第 {episode.episode_no} 集 · {episode.title}"
        )
        self._set_preview(
            self.detail_cover, cover.path if cover else None,
            "该条目没有同名封面图",
        )
        runtime = (
            f"{max(1, int(round(video.duration / 60)))} 分钟"
            if video and video.duration else "—"
        )
        fields = episode.nfo_fields
        self._set_detail_rows([
            ("类型", "单集"),
            ("单集标题 / title", episode.title),
            ("所属剧集 / showtitle", album.show_name),
            ("季 / season", str(episode.season)),
            ("集 / episode", str(episode.episode_no)),
            ("时长 / runtime", runtime),
            ("封面（本地同名图，Jellyfin 自动识别）", cover.name if cover else "无"),
            ("视频文件", video.name if video else "—"),
            ("视频信息", video.summary() if video else "—"),
            ("封面信息", cover.summary() if cover else "—"),
            ("目标季目录", str(episode.season_dir or "—")),
            ("NFO 文件", str(episode.nfo_path or "—")),
            ("磁盘上已有 NFO", str(episode.existing_nfo_path or "无")),
            ("已有 NFO 标题", fields.get("title", "—")),
            ("已有 NFO 季 / 集",
             f"{fields.get('season', '—')} / {fields.get('episode', '—')}"),
            ("已有 NFO 封面", fields.get("thumb", "—")),
            ("状态", f"{episode.status}；{episode.issue_text}"),
        ])

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{stamp}] {message}")

    def closeEvent(self, event) -> None:
        if self.engine.busy:
            answer = QMessageBox.question(
                self, "仍有任务在运行",
                "后台任务尚未结束，现在关闭窗口可能留下未完成的写盘结果。仍要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.engine.cancel()
        event.accept()
