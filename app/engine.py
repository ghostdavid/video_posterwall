"""任务编排：扫描、生成、删除 NFO、撤销都在后台线程执行，通过 Qt 信号回传 UI。

所有中间结果（媒体信息、图片指纹、NFO 文本、JPEG 字节、撤销所需的原始字节）
只存在内存中；写盘只经 WriteGuard，按「创建季目录 → 封面 → NFO → 清理旧 NFO
→ 移动媒体」分阶段执行，保证目录先存在、移动前封面来源仍可读。
"""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .accel import Fingerprinter, backend_label, choose_backend, detect_backends, duplicate_groups
from .guard import WriteGuard
from .media_info import probe_cover, probe_video
from .models import Action, Album, JobSummary, Settings, UndoEntry
from .scanner import build_album


class Cancelled(Exception):
    """用户中止当前任务。"""


class EngineSignals(QObject):
    log = Signal(str)
    progress = Signal(int, int, str)
    scan_done = Signal(object)
    gen_done = Signal(object)
    delete_done = Signal(object)
    undo_done = Signal(object)
    cancelled = Signal(str)
    failed = Signal(str)


class Engine(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.signals = EngineSignals()
        self.backends: list = []
        self.backend_key = "cpu"
        self._cancel = threading.Event()
        self._busy = False
        self._undo: list[UndoEntry] = []

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def cancel(self) -> None:
        if self._busy:
            self._cancel.set()
            self.signals.log.emit("已请求停止，正在结束当前批次……")

    def _start(self, name: str, target) -> bool:
        if self._busy:
            self.signals.log.emit("已有任务在执行，请等待完成或先停止")
            return False
        self._busy = True
        self._cancel.clear()
        threading.Thread(target=self._wrap, args=(name, target), daemon=True).start()
        return True

    def _wrap(self, name: str, target) -> None:
        try:
            target()
        except Cancelled:
            message = f"{name} 已停止"
            self.signals.log.emit(message)
            self.signals.cancelled.emit(message)
        except Exception as exc:
            self.signals.log.emit(traceback.format_exc())
            self.signals.failed.emit(f"{name} 失败：{exc}")
        finally:
            self._busy = False

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    # ------------------------------------------------------------------ 扫描

    def scan(self, root: Path, settings: Settings) -> bool:
        return self._start("扫描", lambda: self._scan(root, settings))

    def _scan(self, root: Path, settings: Settings) -> None:
        self.signals.log.emit(f"开始扫描：{root}")
        album = build_album(root, settings)
        self.signals.log.emit(
            f"识别到 {len(album.episodes)} 个条目、{album.cover_count} 张配对封面、"
            f"{len(album.orphan_images)} 张孤立图片；剧集名：{album.show_name}；"
            f"设定 {album.season_count} 季"
        )
        for warning in album.warnings:
            self.signals.log.emit(f"[提示] {warning}")

        tasks = []
        for episode in album.episodes:
            if episode.video:
                tasks.append(partial(probe_video, episode.video))
            if episode.cover:
                tasks.append(partial(probe_cover, episode.cover))
        total = max(1, len(tasks))
        self.signals.progress.emit(0, total, "准备解析媒体信息")

        self.backends = detect_backends()
        self.backend_key = choose_backend(settings.backend, self.backends)
        album.backend_label = backend_label(self.backend_key, self.backends)
        for backend in self.backends:
            self.signals.log.emit(f"可用加速后端：{backend.label}（{backend.device}）")
        self.signals.log.emit(f"当前使用：{album.backend_label}")
        fingerprinter = Fingerprinter(self.backend_key)

        with ThreadPoolExecutor(max_workers=max(1, settings.threads)) as pool:
            futures = [pool.submit(task) for task in tasks]
            done = 0
            for future in as_completed(futures):
                self._check_cancel()
                try:
                    future.result()
                except Exception as exc:
                    self.signals.log.emit(f"单文件解析失败（已跳过详细信息）：{exc}")
                done += 1
                self.signals.progress.emit(done, total, f"解析视频/封面信息 {done}/{total}")

            targets = [
                (index, episode.cover.path)
                for index, episode in enumerate(album.episodes) if episode.cover
            ]
            matrices = list(pool.map(fingerprinter.grayscale_matrix, [path for _, path in targets]))
            for position, matrix in enumerate(matrices):
                if matrix is None:
                    album.episodes[targets[position][0]].issues.append("封面图无法解码")
            valid_positions = [i for i, matrix in enumerate(matrices) if matrix is not None]
            valid_matrices = [matrices[i] for i in valid_positions]
            hashes = fingerprinter.hash_batch(valid_matrices)
            for position, value in zip(valid_positions, hashes):
                album.episodes[targets[position][0]].fingerprint = value
            if fingerprinter.last_fallback:
                self.signals.log.emit(f"[提示] {fingerprinter.last_fallback}")
            self.signals.progress.emit(total, total, "封面指纹计算完成")

        for value, indices in duplicate_groups([e.fingerprint for e in album.episodes]):
            readable = "、".join(str(i + 1) for i in indices)
            album.warnings.append(f"第 {readable} 项的封面图内容完全相同（指纹 {value[:8]}）")

        self.signals.scan_done.emit({
            "album": album,
            "backends": self.backends,
            "backend_key": self.backend_key,
        })

    # ------------------------------------------------------------------ 动作执行

    @staticmethod
    def _apply(action: Action, guard: WriteGuard) -> UndoEntry | None:
        kind = action.kind
        if kind == "mkdir":
            if action.dst.exists():
                return None
            guard.mkdir(action.dst)
            return UndoEntry("dir", action.dst)
        if kind == "move":
            if action.src is None:
                raise ValueError("移动动作缺少来源文件")
            guard.move(action.src, action.dst)
            return UndoEntry("moved", action.dst, src=action.src)

        existed = action.dst.exists()
        # 读也走守卫：目标若不在可写白名单内，读取阶段就会失败而不会动文件
        original = guard.read_bytes(action.dst) if existed else None
        if kind == "write":
            guard.write_text(action.dst, str(action.data or ""))
        elif kind == "write_bytes":
            guard.write_bytes(action.dst, bytes(action.data or b""))
        elif kind == "delete":
            if existed:
                guard.unlink(action.dst)
                return UndoEntry("deleted", action.dst, original_bytes=original)
            return None
        else:
            raise ValueError(f"未知动作类型：{kind}")

        if existed:
            return UndoEntry("overwritten", action.dst, original_bytes=original)
        return UndoEntry("created", action.dst)

    def _run_actions(self, name: str, album: Album, actions: list[Action],
                     settings: Settings) -> JobSummary:
        guard = WriteGuard(
            album.root, album.writable_files, album.allowed_dirs, album.media_paths
        )
        total = max(1, len(actions))
        summary = JobSummary()
        collected: list[UndoEntry] = []
        succeeded: list[Path] = []
        self.signals.log.emit(
            f"开始{name}：{len(actions)} 条动作；媒体仅移动到季目录且不改名、不改内容"
        )
        self.signals.progress.emit(0, total, f"开始{name}")
        # 阶段之间可中止；已提交的阶段会完整收集结果，避免漏记撤销信息。
        for phase in sorted({a.phase for a in actions}):
            if self._cancel.is_set():
                summary.cancelled = True
                break
            group = [a for a in actions if a.phase == phase]
            with ThreadPoolExecutor(max_workers=max(1, settings.threads)) as pool:
                futures = {pool.submit(self._apply, action, guard): action for action in group}
                for future in as_completed(futures):
                    action = futures[future]
                    try:
                        entry = future.result()
                        if entry:
                            collected.append(entry)
                        summary.ok += 1
                        succeeded.append(action.dst)
                    except Exception as exc:
                        summary.failed += 1
                        summary.messages.append(f"{action.desc}：{exc}")
                        self.signals.log.emit(f"失败：{action.desc} -> {exc}")
                    processed = summary.ok + summary.failed
                    self.signals.progress.emit(processed, total, f"{name}进度 {processed}/{total}")
        for entry in collected:
            entry.root = album.root
            entry.writable = album.writable_files
            entry.dirs = album.allowed_dirs
            entry.media = album.media_paths
        self._undo.extend(collected)
        summary.extra = succeeded
        summary.skipped = len(actions) - summary.ok - summary.failed
        self.signals.log.emit(f"{name}结束：成功 {summary.ok}，失败 {summary.failed}")
        return summary

    # ------------------------------------------------------------------ 生成

    def generate(self, album: Album, settings: Settings) -> bool:
        return self._start("生成", lambda: self._generate(album, settings))

    def _generate(self, album: Album, settings: Settings) -> None:
        actions = [a for a in album.plan if a.enabled]
        summary = self._run_actions("生成", album, actions, settings)
        summary.skipped += len(album.plan) - len(actions)
        self.signals.gen_done.emit(summary)

    # ------------------------------------------------------------------ 删除所选 NFO

    def delete_nfos(self, album: Album, paths: list[Path], settings: Settings) -> bool:
        return self._start("删除 NFO", lambda: self._delete_nfos(album, paths, settings))

    def _delete_nfos(self, album: Album, paths: list[Path], settings: Settings) -> None:
        if not album.writable_files:
            from .planner import build_whitelists

            build_whitelists(album)
        allowed = album.writable_files or set()
        unique: dict[str, Path] = {}
        for path in paths:
            key = str(Path(path).resolve()).casefold()
            if key in allowed and Path(path).is_file():
                unique[key] = Path(path)
        rejected = len(paths) - len(unique)
        actions = [
            Action(phase=0, kind="delete", dst=path,
                   desc=f"删除单集 NFO：{path.name}")
            for path in unique.values()
        ]
        summary = self._run_actions("删除 NFO", album, actions, settings)
        summary.skipped += rejected
        succeeded = [str(Path(p).resolve()) for p in (summary.extra or [])]
        summary.extra = None
        self.signals.delete_done.emit({"summary": summary, "paths": succeeded})

    # ------------------------------------------------------------------ 撤销

    def undo(self) -> bool:
        return self._start("撤销", self._undo_run)

    def _undo_run(self) -> None:
        summary = JobSummary()
        if not self._undo:
            summary.messages.append("没有可撤销的本次操作")
            self.signals.undo_done.emit(summary)
            return
        entries = list(reversed(self._undo))
        remaining: list[UndoEntry] = []
        total = len(entries)
        for index, entry in enumerate(entries, start=1):
            if self._cancel.is_set():
                remaining.extend(entries[index - 1:])
                summary.cancelled = True
                break
            try:
                if entry.root is None:
                    raise ValueError("撤销记录缺少专辑路径")
                guard = WriteGuard(
                    entry.root, entry.writable, entry.dirs, entry.media
                )
                if entry.kind == "created":
                    guard.unlink(entry.path)
                elif entry.kind in ("overwritten", "deleted"):
                    guard.write_bytes(entry.path, entry.original_bytes or b"")
                elif entry.kind == "moved" and entry.src is not None:
                    guard.move(entry.path, entry.src)
                elif entry.kind == "dir":
                    guard.rmdir_if_empty(entry.path)
                else:
                    raise ValueError(f"未知撤销类型：{entry.kind}")
                summary.ok += 1
            except Exception as exc:
                remaining.append(entry)
                summary.failed += 1
                summary.messages.append(f"{entry.path.name}：{exc}")
                self.signals.log.emit(f"撤销失败：{entry.path} -> {exc}")
            self.signals.progress.emit(index, total, f"撤销进度 {index}/{total}")
        # 只移除成功撤销的记录，失败或中止的条目可在排除问题后重试。
        self._undo = list(reversed(remaining))
        message = f"撤销完成：成功 {summary.ok}，失败 {summary.failed}"
        self.signals.log.emit(message + ("，已中止" if summary.cancelled else ""))
        self.signals.undo_done.emit(summary)
