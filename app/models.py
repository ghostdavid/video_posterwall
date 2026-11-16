"""内存数据模型。所有扫描结果、预览内容、撤销记录都只保存在内存中。

写盘约束（用户明确要求）：
  * 允许创建 Season NN 目录、把视频与配对封面**移动**到对应季目录；
    移动时文件名必须保持不变、内容不得改写，也不得覆盖已有文件。
  * 允许生成 / 修改 / 删除 单集 .nfo、tvshow.nfo、专辑根 poster.jpg，
    以及每个季的 season.nfo 与季封面（季目录内 seasonNN-poster.jpg + poster.jpg）。
  * 除此之外不写任何文件；视频和图片原文件不可被写入、改名或覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

POSTER_NAME = "poster.jpg"
TVSHOW_NAME = "tvshow.nfo"
SEASON_NFO_NAME = "season.nfo"


def season_dir_name(season: int) -> str:
    return f"Season {season:02d}"


def season_poster_name(season: int) -> str:
    """季目录内的季封面命名，例如 Season 03/season03-poster.jpg。

    这是用户要求的命名；Jellyfin / Emby 实际读取的同目录文件是 poster.jpg，
    因此生成时会同时写两份（见 planner.py）。
    """
    return f"season{season:02d}-poster.jpg"


def format_size(size: int) -> str:
    if size < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def format_duration(seconds: Optional[float]) -> str:
    if not seconds or seconds <= 0:
        return "—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


@dataclass
class FileInfo:
    path: Path
    size: int = 0
    mtime: float = 0.0
    ext: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    codec: Optional[str] = None
    fmt: Optional[str] = None
    note: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def dimension_text(self) -> str:
        return f"{self.width}×{self.height}" if self.width and self.height else "—"

    @property
    def size_text(self) -> str:
        return format_size(self.size)

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration)

    def summary(self) -> str:
        parts = [self.ext.lstrip(".").upper() or "文件", self.size_text]
        if self.width and self.height:
            parts.append(self.dimension_text)
        if self.duration:
            parts.append(self.duration_text)
        if self.codec:
            parts.append(self.codec)
        if self.fmt and self.fmt.upper() != self.ext.lstrip(".").upper():
            parts.append(self.fmt)
        return " · ".join(parts)


@dataclass
class Episode:
    order: int  # 列表中的当前位置，由用户季内排序决定
    video: Optional[FileInfo]
    title: str = ""
    season: int = 1
    episode_no: int = 1  # 该季内的第几集，由列表顺序计算
    cover: Optional[FileInfo] = None
    alt_covers: list[FileInfo] = field(default_factory=list)
    season_dir: Optional[Path] = None
    nfo_path: Optional[Path] = None          # 本次要生成的 NFO 目标
    existing_nfo_path: Optional[Path] = None  # 磁盘上已有的 NFO
    existing_nfo_text: Optional[str] = None
    nfo_fields: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""
    issues: list[str] = field(default_factory=list)
    planned_nfo: str = ""
    status: str = "待处理"

    @property
    def has_nfo(self) -> bool:
        return self.existing_nfo_text is not None

    @property
    def code(self) -> str:
        return f"S{self.season:02d}E{self.episode_no:02d}"

    @property
    def issue_text(self) -> str:
        return "；".join(self.issues) if self.issues else "正常"


@dataclass
class Action:
    """一条待执行的写盘动作；目标必须落在 Album 的各类白名单内。"""

    phase: int
    kind: str  # mkdir | write_bytes | write | delete | move
    dst: Path
    src: Optional[Path] = None
    data: str | bytes | None = None
    desc: str = ""
    enabled: bool = True
    skip_reason: str = ""


@dataclass
class Album:
    root: Path
    show_name: str
    name_source: str = ""
    season_count: int = 1
    episodes: list[Episode] = field(default_factory=list)
    orphan_images: list[FileInfo] = field(default_factory=list)
    ignored_files: int = 0
    tvshow_nfo: str = ""
    season_nfos: dict[int, str] = field(default_factory=dict)
    season_planned_poster: dict[int, bool] = field(default_factory=dict)
    plan: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backend_label: str = "CPU 多线程"
    writable_files: set[str] = field(default_factory=set)
    allowed_dirs: set[str] = field(default_factory=set)
    media_paths: set[str] = field(default_factory=set)

    @property
    def seasons(self) -> list[int]:
        return list(range(1, self.season_count + 1))

    @property
    def cover_count(self) -> int:
        return sum(1 for e in self.episodes if e.cover)

    @property
    def planned_writes(self) -> int:
        return sum(1 for a in self.plan if a.enabled)


@dataclass
class Settings:
    threads: int = 8
    backend: str = "auto"
    season_count: int = 1
    poster_source: Optional[Path] = None
    poster_remove: bool = False
    season_posters: dict[int, Path] = field(default_factory=dict)
    season_poster_remove: set[int] = field(default_factory=set)


@dataclass
class UndoEntry:
    kind: str  # created | overwritten | deleted | moved | dir
    path: Path
    src: Optional[Path] = None
    original_bytes: Optional[bytes] = None
    # 每条记录自带所属专辑的守卫参数，切换专辑后仍可正确撤销
    root: Optional[Path] = None
    writable: Optional[set[str]] = None
    dirs: Optional[set[str]] = None
    media: Optional[set[str]] = None


@dataclass
class JobSummary:
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    messages: list[str] = field(default_factory=list)
    cancelled: bool = False
    extra: Any = None
