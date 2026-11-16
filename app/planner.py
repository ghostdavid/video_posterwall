"""生成写盘计划（只在内存计算，不落盘）。

用户可设定季数、把每个视频划分到某一季、在季内排序（排第一即第 1 集），
并为每一季指定封面。计划会：
  * 在专辑根目录创建 Season 01 … Season NN 目录；
  * 每个季目录写入 season.nfo，并写季封面：季目录内 seasonNN-poster.jpg
    （用户要求的命名）+ poster.jpg（Jellyfin / Emby 实际读取的季主图命名）；
  * 把视频与配对封面**移动**到所属季目录，文件名不变、内容不改写、不覆盖；
  * 在季目录写含 <season>/<episode> 的同名 NFO，并清理原位置的旧 NFO；
  * 生成 / 更新 / 删除 tvshow.nfo 与专辑根 poster.jpg。

所有动作都受 WriteGuard 的分类白名单约束；媒体文件不可能被写入、改名或覆盖。
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .media_info import image_to_jpeg_bytes
from .models import (
    POSTER_NAME,
    SEASON_NFO_NAME,
    TVSHOW_NAME,
    Action,
    Album,
    Settings,
    season_dir_name,
    season_poster_name,
)
from .nfo import build_episode_nfo, build_season_nfo, build_tvshow_nfo

PHASE_MKDIR = 0
PHASE_POSTER = 1
PHASE_NFO = 2
PHASE_CLEANUP = 3
PHASE_MOVE = 4

_JPEG_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif"}


def _key(path: Path) -> str:
    return str(Path(path).resolve()).casefold()


def poster_bytes(path: Path) -> bytes:
    """取得 JPEG 字节：本身是 JPEG 就原样读取，其他格式在内存转码。"""
    source = Path(path)
    if source.suffix.lower() in _JPEG_EXTS:
        return source.read_bytes()
    return image_to_jpeg_bytes(source)


def _read_nfo(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else None
    except OSError:
        return None


def build_whitelists(album: Album) -> dict[int, Path]:
    """构造分类白名单，供 WriteGuard 使用。"""
    root = album.root
    season_dirs = {
        number: root / season_dir_name(number)
        for number in album.seasons
    }
    album.allowed_dirs = {_key(path) for path in season_dirs.values()}
    writable = {_key(root / TVSHOW_NAME), _key(root / POSTER_NAME)}
    for number, directory in season_dirs.items():
        writable.add(_key(directory / SEASON_NFO_NAME))
        # Jellyfin / Emby 在季目录内读取 poster.jpg 作为季主图
        writable.add(_key(directory / POSTER_NAME))
        # 用户要求的季封面命名，也放在季目录内
        writable.add(_key(directory / season_poster_name(number)))
        # 旧版本曾把季封面写在专辑根目录；保留白名单以便清理旧文件
        writable.add(_key(root / season_poster_name(number)))
    media: set[str] = set()
    for episode in album.episodes:
        nfo_name = Path(episode.video.path).with_suffix(".nfo").name
        writable.add(_key(root / nfo_name))
        for directory in season_dirs.values():
            writable.add(_key(directory / nfo_name))
        # 原位置可在任意递归子目录，清理与手动删除须覆盖真实已有 NFO。
        if episode.existing_nfo_path is not None:
            writable.add(_key(episode.existing_nfo_path))
        for item in (episode.video, episode.cover):
            if item is None:
                continue
            media.add(_key(item.path))
            for directory in season_dirs.values():
                media.add(_key(directory / item.path.name))
    album.writable_files = writable
    album.media_paths = media
    return season_dirs


def season_poster_source(album: Album, settings: Settings, number: int,
                         season_dir: Path) -> Path | None:
    """决定某季封面来源：用户指定 > 沿用已有 > 本季首个有封面的条目。

    返回 None 表示用户明确清除了该季封面，或本季没有可用封面。
    """
    if number in settings.season_poster_remove:
        return None
    chosen = settings.season_posters.get(number)
    if chosen is not None:
        return Path(chosen)
    for existing in (
        season_dir / season_poster_name(number),
        season_dir / POSTER_NAME,
        # 旧版本写在专辑根目录的季封面：作为来源迁移到季目录
        album.root / season_poster_name(number),
    ):
        if existing.is_file():
            return existing
    for episode in album.episodes:
        if episode.season == number and episode.cover:
            return episode.cover.path
    return None


def build_plan(album: Album, settings: Settings) -> list[Action]:
    root = album.root
    album.season_count = max(1, settings.season_count)
    season_dirs = build_whitelists(album)
    actions: list[Action] = []
    seen: set[str] = set()

    # 列表顺序即季内播放顺序；同季内第 N 个出现就是第 N 集
    counters: dict[int, int] = defaultdict(int)
    for episode in album.episodes:
        episode.season = min(max(1, episode.season), album.season_count)
        counters[episode.season] += 1
        episode.episode_no = counters[episode.season]
        episode.season_dir = season_dirs[episode.season]
        nfo_name = Path(episode.video.path).with_suffix(".nfo").name
        episode.nfo_path = episode.season_dir / nfo_name
        # 目标位置已有 NFO 优先；否则合并随视频位于原位置的 NFO。
        existing = _read_nfo(episode.nfo_path) or episode.existing_nfo_text
        episode.planned_nfo = build_episode_nfo(
            episode, show_name=album.show_name, existing=existing
        )
        episode.status = "待处理"

    def add(phase: int, kind: str, dst: Path, *, src: Path | None = None,
            data: str | bytes | None = None, desc: str = "") -> Action | None:
        dst = Path(dst)
        marker = _key(dst)
        enabled = True
        reason = ""
        if kind == "move":
            if src is None or _key(src) == marker:
                return None
            if dst.exists():
                enabled, reason = False, "目标季目录已有同名文件，为保护文件不覆盖"
            elif marker in seen:
                enabled, reason = False, "计划内有多个文件将移动到此路径"
            elif marker not in album.media_paths or _key(src) not in album.media_paths:
                enabled, reason = False, "移动路径不在允许清单内"
        elif kind == "delete":
            if not dst.exists():
                return None
            if marker in seen:
                enabled, reason = False, "计划内目标重复"
        elif kind == "mkdir":
            if marker in seen:
                enabled, reason = False, "重复目录"
        else:  # write / write_bytes
            if marker in seen:
                enabled, reason = False, "计划内目标路径重复"
            elif marker not in album.writable_files:
                enabled, reason = False, "目标不在允许写入的文件清单内"
            elif dst.is_file():
                desired = (
                    str(data or "").encode("utf-8") if kind == "write"
                    else bytes(data or b"")
                )
                try:
                    if dst.read_bytes() == desired:
                        return None
                except OSError:
                    pass
        seen.add(marker)
        action = Action(
            phase=phase, kind=kind, dst=dst, src=src, data=data,
            desc=desc, enabled=enabled, skip_reason=reason,
        )
        actions.append(action)
        return action

    # 阶段 0：创建用户设定的所有季目录
    for number, directory in season_dirs.items():
        add(PHASE_MKDIR, "mkdir", directory,
            desc=f"创建第 {number} 季目录 {directory.name}")

    # 阶段 1：整辑封面与季封面都必须在移动媒体前生成
    album_poster_exists = (root / POSTER_NAME).is_file()
    album_will_have_poster = album_poster_exists and not settings.poster_remove
    if settings.poster_source:
        try:
            payload = poster_bytes(Path(settings.poster_source))
            add(PHASE_POSTER, "write_bytes", root / POSTER_NAME, data=payload,
                desc=f"生成专辑封面 {POSTER_NAME}（来源：{Path(settings.poster_source).name}）")
            album_will_have_poster = True
        except (OSError, ValueError) as exc:
            warning = f"专辑封面转换失败，本次不生成 {POSTER_NAME}：{exc}"
            if warning not in album.warnings:
                album.warnings.append(warning)
    elif settings.poster_remove and album_poster_exists:
        add(PHASE_POSTER, "delete", root / POSTER_NAME,
            desc=f"删除已有专辑封面 {POSTER_NAME}")
    album.tvshow_nfo = build_tvshow_nfo(
        album.show_name,
        poster=POSTER_NAME if album_will_have_poster else None,
        existing=_read_nfo(root / TVSHOW_NAME),
        season_count=album.season_count,
    )

    album.season_nfos = {}
    album.season_planned_poster = {}
    for number, directory in season_dirs.items():
        in_folder_named = directory / season_poster_name(number)
        in_folder_poster = directory / POSTER_NAME
        old_root = root / season_poster_name(number)
        source = season_poster_source(album, settings, number, directory)
        removing = number in settings.season_poster_remove
        if source is not None:
            try:
                payload = poster_bytes(source)
                # 用户要求的命名：Season NN/seasonNN-poster.jpg
                add(PHASE_POSTER, "write_bytes", in_folder_named, data=payload,
                    desc=f"第 {number} 季封面 {directory.name}/{in_folder_named.name}")
                # Jellyfin / Emby 的季主图：季目录内 poster.jpg
                add(PHASE_POSTER, "write_bytes", in_folder_poster, data=payload,
                    desc=f"第 {number} 季封面（Jellyfin/Emby 读取）"
                         f"{directory.name}/{in_folder_poster.name}")
                album.season_planned_poster[number] = True
            except (OSError, ValueError) as exc:
                album.season_planned_poster[number] = False
                warning = f"第 {number} 季封面转换失败：{exc}"
                if warning not in album.warnings:
                    album.warnings.append(warning)
        else:
            album.season_planned_poster[number] = False
            if removing:
                for stale in (in_folder_named, in_folder_poster):
                    if stale.is_file():
                        add(PHASE_POSTER, "delete", stale,
                            desc=f"删除第 {number} 季封面 {stale.parent.name}/{stale.name}")
        # 旧版本写在专辑根目录的 seasonNN-poster.jpg：迁移到季目录后清掉，
        # 避免 Jellyfin 继续从根目录读取旧季封面。
        if old_root.is_file():
            add(PHASE_POSTER, "delete", old_root,
                desc=f"清理旧位置季封面 {old_root.name}")
        # 季 NFO 里的封面引用只在封面确实会存在时写入
        has_art = album.season_planned_poster[number] or (
            not removing and (in_folder_named.is_file() or in_folder_poster.is_file())
        )
        album.season_nfos[number] = build_season_nfo(
            number, show_name=album.show_name,
            poster=POSTER_NAME if has_art else None,
            existing=_read_nfo(directory / SEASON_NFO_NAME),
        )

    # 阶段 2：写 NFO（目标季目录已在阶段 0 创建）
    add(PHASE_NFO, "write", root / TVSHOW_NAME, data=album.tvshow_nfo,
        desc=("更新已有" if (root / TVSHOW_NAME).is_file() else "新建")
             + f"{TVSHOW_NAME}（剧集名：{album.show_name}）")
    for number, directory in season_dirs.items():
        add(PHASE_NFO, "write", directory / SEASON_NFO_NAME,
            data=album.season_nfos[number],
            desc=f"第 {number} 季元数据 {directory.name}/{SEASON_NFO_NAME}")
    nfo_actions: list[Action | None] = []
    for episode in album.episodes:
        nfo_actions.append(add(
            PHASE_NFO, "write", episode.nfo_path, data=episode.planned_nfo,
            desc=f"{episode.code} 单集 NFO：{episode.title}（"
                 f"季 {episode.season} / 第 {episode.episode_no} 集）",
        ))

    # 先确定媒体冲突，再决定能否改目标 NFO、清理原 NFO。
    video_moves: list[Action | None] = []
    for episode in album.episodes:
        target_dir = episode.season_dir
        video_moves.append(add(
            PHASE_MOVE, "move", target_dir / episode.video.path.name,
            src=episode.video.path,
            desc=f"第 {episode.season} 季：移动视频 {episode.video.name}（不改名）",
        ))
        if episode.cover:
            add(PHASE_MOVE, "move", target_dir / episode.cover.path.name,
                src=episode.cover.path,
                desc=f"第 {episode.season} 季：移动封面 {episode.cover.name}（不改名）")

    # 阶段 3：仅清理已能安全生成目标 NFO 且视频可移动的条目。
    for index, episode in enumerate(album.episodes):
        old = episode.existing_nfo_path
        has_old = bool(old and old.exists() and _key(old) != _key(episode.nfo_path))
        retained = "；原 NFO 保留" if has_old else ""
        nfo_action, video_move = nfo_actions[index], video_moves[index]
        if video_move is not None and not video_move.enabled:
            reason = f"媒体未移动：{video_move.skip_reason}"
            if nfo_action is not None:
                nfo_action.enabled = False
                nfo_action.skip_reason = reason
            episode.status = reason + retained
            continue
        if nfo_action is not None and not nfo_action.enabled:
            episode.status = f"NFO 未生成：{nfo_action.skip_reason}" + retained
            continue
        if has_old:
            add(PHASE_CLEANUP, "delete", old,
                desc=f"清理原位置的旧 NFO：{old.name}")

    album.plan = sorted(actions, key=lambda a: (a.phase, str(a.dst).casefold()))
    return album.plan
