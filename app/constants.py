"""全局常量：可识别的媒体扩展名、命名规则与默认值。"""
from __future__ import annotations

import os
import re

APP_NAME = "剧集海报墙生成器"
APP_VERSION = "2026.11.16"

VIDEO_EXTS = frozenset({
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".3gp", ".rmvb", ".rm",
    ".vob", ".divx", ".f4v", ".asf", ".ogv", ".m4b", ".mk3d",
})

IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".bmp", ".gif",
    ".tif", ".tiff", ".tbn", ".avif", ".heic", ".heif", ".ico",
})

# 同一文件名出现多张图片 / 多个视频时的挑选优先级（越小越优先）
_IMAGE_ORDER = (
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".tbn",
    ".avif", ".heic", ".heif", ".bmp", ".gif", ".tif", ".tiff", ".ico",
)
_VIDEO_ORDER = (
    ".mp4", ".mkv", ".m4v", ".mov", ".avi", ".wmv", ".flv", ".webm",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".rmvb", ".rm",
    ".3gp", ".divx", ".f4v", ".asf", ".ogv", ".m4b", ".mk3d",
)
IMAGE_PRIORITY = {ext: i for i, ext in enumerate(_IMAGE_ORDER)}
VIDEO_PRIORITY = {ext: i for i, ext in enumerate(_VIDEO_ORDER)}

_SEASON_DIR_RE = re.compile(r"^season\s*(\d+)$", re.IGNORECASE)


def season_from_dir(name: str) -> int | None:
    """从 Season NN 目录名解析季号；不是季目录则返回 None。"""
    match = _SEASON_DIR_RE.match(name.strip())
    return int(match.group(1)) if match else None


def is_season_dir(name: str) -> bool:
    return season_from_dir(name) is not None


def default_threads() -> int:
    return max(1, min(8, os.cpu_count() or 4))


def max_threads() -> int:
    return max(4, (os.cpu_count() or 4) * 2)
