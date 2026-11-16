"""只读扫描专辑文件夹，按「同名不同后缀」把视频与封面图配成条目。

默认递归扫描所选文件夹下的**所有子目录**；会识别已存在的 Season NN 目录并
据此初始化季号，方便重复运行。程序自己管理的封面图不参与单集封面配对。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from .constants import (
    IMAGE_EXTS,
    IMAGE_PRIORITY,
    VIDEO_EXTS,
    VIDEO_PRIORITY,
    season_from_dir,
)
from .models import POSTER_NAME, TVSHOW_NAME, Album, Episode, FileInfo, Settings
from .nfo import parse_nfo
from .show_name import parse_show_name

_SEASON_POSTER_RE = re.compile(r"^season\d+-poster\.(jpg|jpeg|png|webp)$", re.IGNORECASE)


def natural_key(text: str) -> str:
    """自然排序键：数字按数值比较，避免「第10话」排在「第2话」前面。"""
    return "|".join(
        f"{int(part):012d}" if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", text)
    )


def is_managed_image(path: Path, root: Path) -> bool:
    """是否为程序生成的整辑封面 / 季封面（不参与视频封面配对）。"""
    name = path.name.casefold()
    if name == POSTER_NAME.casefold():
        if path.parent == root:
            return True
        if season_from_dir(path.parent.name) is not None:
            return True
    if _SEASON_POSTER_RE.match(name):
        # 旧版本放在专辑根目录，新版本放在季目录内；两处都不参与配对
        if path.parent == root or season_from_dir(path.parent.name) is not None:
            return True
    return False


def iter_media_files(root: Path) -> Iterator[Path]:
    """递归遍历所有子目录（跳过隐藏目录），返回文件。"""
    stack: list[Path] = [root]
    visited: set[str] = set()
    while stack:
        folder = stack.pop()
        try:
            marker = str(folder.resolve()).casefold()
        except OSError:
            continue
        if marker in visited:
            continue
        visited.add(marker)
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for item in entries:
            try:
                if item.is_dir():
                    if not item.name.startswith("."):
                        stack.append(item)
                elif item.is_file():
                    yield item
            except OSError:
                continue


def _safe_stat(path: Path) -> tuple[int, float]:
    try:
        stat = path.stat()
        return stat.st_size, stat.st_mtime
    except OSError:
        return 0, 0.0


def build_album(root: Path, settings: Settings) -> Album:
    """只读扫描，得到内存中的专辑模型；不写任何文件。"""
    show_name, source = parse_show_name(root.name)
    album = Album(
        root=root, show_name=show_name, name_source=source,
        season_count=max(1, settings.season_count),
    )

    videos: dict[tuple[str, str], list[FileInfo]] = defaultdict(list)
    images: dict[tuple[str, str], list[FileInfo]] = defaultdict(list)
    season_of_dir: dict[str, int] = {}

    for path in iter_media_files(root):
        ext = path.suffix.lower()
        if ext not in VIDEO_EXTS and ext not in IMAGE_EXTS:
            album.ignored_files += 1
            continue
        if ext in IMAGE_EXTS and is_managed_image(path, root):
            album.ignored_files += 1
            continue
        size, mtime = _safe_stat(path)
        info = FileInfo(path=path, size=size, mtime=mtime, ext=ext)
        parent_key = str(path.parent).casefold()
        season_of_dir.setdefault(parent_key, season_from_dir(path.parent.name) or 1)
        key = (parent_key, path.stem.casefold())
        (videos if ext in VIDEO_EXTS else images)[key].append(info)

    ordered_keys = sorted(videos, key=lambda k: (natural_key(k[1]), k[0].casefold()))
    for index, key in enumerate(ordered_keys):
        candidates = sorted(
            videos[key], key=lambda f: (VIDEO_PRIORITY.get(f.ext, 99), f.name.casefold())
        )
        video = candidates[0]
        covers = sorted(
            images.get(key, []),
            key=lambda f: (IMAGE_PRIORITY.get(f.ext, 99), f.name.casefold()),
        )
        cover = covers[0] if covers else None
        issues: list[str] = []
        if len(candidates) > 1:
            names = "、".join(f.name for f in candidates[1:])
            issues.append(f"同名视频有多个，已采用 {video.name}，忽略 {names}")
        if cover is None:
            issues.append("缺少同名封面图")
        if len(covers) > 1:
            names = "、".join(f.name for f in covers[1:])
            issues.append(f"同名封面有多张，已采用 {cover.name}，忽略 {names}")

        season = min(season_of_dir.get(key[0], 1), album.season_count)
        existing_path = video.path.with_suffix(".nfo")
        existing_text = None
        nfo_fields: dict[str, str] = {}
        if existing_path.is_file():
            try:
                existing_text = existing_path.read_text(encoding="utf-8", errors="replace")
                nfo_fields = parse_nfo(existing_text)
            except OSError as exc:
                issues.append(f"已有 NFO 读取失败：{exc}")

        album.episodes.append(
            Episode(
                order=index,
                video=video,
                title=video.path.stem,
                season=season,
                cover=cover,
                alt_covers=covers[1:],
                existing_nfo_path=existing_path if existing_text is not None else None,
                existing_nfo_text=existing_text,
                nfo_fields=nfo_fields,
                issues=issues,
            )
        )

    # 默认按季分组，组内保持自然排序；之后用户可在界面里调整季与季内顺序
    album.episodes.sort(key=lambda e: (e.season, e.order))
    for index, episode in enumerate(album.episodes):
        episode.order = index

    for key, files in images.items():
        if key not in videos:
            album.orphan_images.extend(files)

    if not album.episodes:
        album.warnings.append("文件夹及其子目录中没有识别到视频文件")
    if album.orphan_images:
        album.warnings.append(f"有 {len(album.orphan_images)} 张图片没有同名视频，已跳过")
    if "没有【】" in source:
        album.warnings.append(f"剧集名取自整个文件夹名：{show_name}（建议用【剧集名】命名）")
    if (root / TVSHOW_NAME).is_file():
        album.warnings.append("专辑根目录已存在 tvshow.nfo，生成时会更新它")
    return album
