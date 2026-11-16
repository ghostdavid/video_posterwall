"""主窗口使用的自适应控件。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QTableWidget


class ElidedLabel(QLabel):
    """空间不足时省略文本，完整内容保留在工具提示中。"""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._update_text()

    def _update_text(self) -> None:
        metrics = self.fontMetrics()
        super().setText(metrics.elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width())
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_text()


class PosterPreview(QLabel):
    """随自身尺寸缩放图片，不按原图尺寸撑大布局。"""

    def __init__(self, empty_text: str = "无封面") -> None:
        super().__init__()
        self._image = QImage()
        self._empty_text = empty_text
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(72, 96)
        self.setStyleSheet(
            "QLabel{background:#f3f6fa;border:1px solid #d8e0ea;"
            "border-radius:4px;color:#7a8492;}"
        )
        self._render()

    def set_image(self, path: Path | None, empty_text: str = "无封面") -> None:
        self._empty_text = empty_text
        self._image = QImage(str(path)) if path and path.is_file() else QImage()
        if path and self._image.isNull():
            self._empty_text = "图片无法预览（格式不受支持或文件损坏）"
        self._render()

    def _render(self) -> None:
        if self._image.isNull():
            self.setPixmap(QPixmap())
            super().setText(self._empty_text)
            return
        super().setText("")
        available = self.size() - QSize(8, 8)
        if available.width() <= 0 or available.height() <= 0:
            return
        pixmap = QPixmap.fromImage(self._image)
        self.setPixmap(pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()


class EpisodeTable(QTableWidget):
    """按权重分配多余宽度；空间不足时保留横向滚动。"""

    MIN_WIDTHS = (32, 48, 36, 110, 90, 100, 82, 90, 96, 100, 110)
    WEIGHTS = (0, 0, 0, 4, 2, 3, 2, 2, 2, 3, 3)

    def __init__(self) -> None:
        super().__init__(0, len(self.MIN_WIDTHS))
        self._fitting = False
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

    def fit_columns(self) -> None:
        if self._fitting:
            return
        self._fitting = True
        try:
            widths = list(self.MIN_WIDTHS)
            extra = max(0, self.viewport().width() - sum(widths))
            total_weight = sum(self.WEIGHTS)
            used = 0
            for index, weight in enumerate(self.WEIGHTS):
                if not weight:
                    continue
                addition = extra * weight // total_weight
                widths[index] += addition
                used += addition
            widths[-1] += extra - used
            for index, width in enumerate(widths):
                self.setColumnWidth(index, width)
        finally:
            self._fitting = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_columns()
