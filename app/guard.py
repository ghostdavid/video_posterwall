"""唯一的写盘出口，三层保护。

1) 目录边界：所有目标解析后必须位于用户所选的专辑文件夹内（含符号链接绕出检测）。
2) 分类白名单：
   - writable：只允许写 / 删 单集 .nfo、tvshow.nfo、poster.jpg
   - dirs：只允许创建用户设定的 Season NN 目录
   - media：只允许在这些预置路径之间移动媒体文件
3) 移动约束：源与目标文件名必须完全相同（禁止重命名）、目标不存在（禁止覆盖）、
   用 Path.replace 原地搬移（不读写字节，禁止修改内容）。

因此视频与图片原文件不可能被写入、改名或覆盖；程序也不写临时文件、
配置、日志、缓存到任何其他位置。
"""
from __future__ import annotations

from pathlib import Path


class WriteGuardError(RuntimeError):
    """目标路径越界、不在白名单内，或试图改名 / 覆盖媒体文件。"""


class WriteGuard:
    def __init__(
        self,
        root: Path,
        writable: set[str] | None = None,
        dirs: set[str] | None = None,
        media: set[str] | None = None,
    ):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise WriteGuardError(f"专辑文件夹不存在：{self.root}")
        self._writable = writable
        self._dirs = dirs
        self._media = media

    @staticmethod
    def _key(path: Path) -> str:
        return str(path).casefold()

    def _inside(self, path: Path, label: str) -> Path:
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WriteGuardError(
                f"拒绝写盘：{label} 超出所选专辑文件夹范围（{resolved}）"
            ) from exc
        return resolved

    def _check_set(self, resolved: Path, allowed: set[str] | None, label: str) -> None:
        if allowed is not None and self._key(resolved) not in allowed:
            raise WriteGuardError(f"拒绝写盘：{label} 不在允许清单内（{resolved}）")

    def read_bytes(self, path: Path) -> bytes:
        resolved = self._inside(path, "读取")
        self._check_set(resolved, self._writable, "读取")
        return resolved.read_bytes()

    def mkdir(self, path: Path) -> Path:
        target = self._inside(path, "创建目录")
        self._check_set(target, self._dirs, "创建目录")
        if not target.parent.is_dir():
            raise WriteGuardError(f"拒绝创建上级目录：{target.parent}")
        target.mkdir(exist_ok=True)
        return target

    def rmdir_if_empty(self, path: Path) -> None:
        target = self._inside(path, "删除空目录")
        self._check_set(target, self._dirs, "删除空目录")
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()

    def _prepare_write(self, path: Path, label: str) -> Path:
        target = self._inside(path, label)
        self._check_set(target, self._writable, label)
        if not target.parent.is_dir():
            raise WriteGuardError(f"目标目录不存在，拒绝创建：{target.parent}")
        return target

    def write_text(self, path: Path, text: str) -> Path:
        target = self._prepare_write(path, "写入文件")
        target.write_text(text, encoding="utf-8", newline="\n")
        return target

    def write_bytes(self, path: Path, data: bytes) -> Path:
        target = self._prepare_write(path, "写入文件")
        target.write_bytes(data)
        return target

    def unlink(self, path: Path) -> None:
        target = self._inside(path, "删除文件")
        self._check_set(target, self._writable, "删除文件")
        if target.is_file():
            target.unlink()

    def move(self, src: Path, dst: Path) -> Path:
        source = self._inside(src, "移动来源")
        target = self._inside(dst, "移动目标")
        self._check_set(source, self._media, "移动来源")
        self._check_set(target, self._media, "移动目标")
        if source.name != target.name:
            raise WriteGuardError(f"拒绝重命名：{source.name} -> {target.name}")
        if not source.is_file():
            raise WriteGuardError(f"移动来源不是文件：{source}")
        if target.exists():
            raise WriteGuardError(f"拒绝覆盖已有文件：{target}")
        if not target.parent.is_dir():
            raise WriteGuardError(f"目标季目录不存在：{target.parent}")
        # 同目录树内的原子搬移，不读取也不改写任何字节
        source.replace(target)
        return target
