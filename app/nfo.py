"""生成并合并本地 NFO，保留已有刮削元数据。

本地可确定的标题、季集、时长和文件信息会更新；演员、简介、评分、外部 ID、
远程图片等已有内容原样保留。新文件只创建有实际值的字段，不批量生成空节点。
本地封面使用 art/poster；相对路径不写入仅适合绝对 URI 的 thumb。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .models import POSTER_NAME, Episode, season_poster_name

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _load_root(existing: str | None, tag: str) -> ET.Element:
    if existing:
        try:
            root = ET.fromstring(existing)
            if root.tag == tag:
                return root
        except ET.ParseError:
            pass
    return ET.Element(tag)


def _set_text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    element = parent.find(tag)
    if element is None:
        element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def _set_poster(root: ET.Element, poster: str | None, managed_names: set[str]) -> None:
    """更新本地封面引用，不清除已有的远程或非托管图片。"""
    art = root.find("art")
    node = art.find("poster") if art is not None else None
    if poster:
        if art is None:
            art = ET.SubElement(root, "art")
        _set_text(art, "poster", poster)
        return
    if node is None:
        return
    current = (node.text or "").strip().replace("\\", "/").casefold()
    if current in managed_names:
        art.remove(node)
        if not list(art):
            root.remove(art)


def _child(parent: ET.Element, tag: str) -> ET.Element:
    element = parent.find(tag)
    return element if element is not None else ET.SubElement(parent, tag)


def _serialize(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return XML_DECLARATION + ET.tostring(root, encoding="unicode") + "\n"


def _update_named_seasons(root: ET.Element, season_count: int) -> None:
    found: set[int] = set()
    for node in list(root.findall("namedseason")):
        try:
            number = int(node.get("number", ""))
        except ValueError:
            continue
        if number > season_count and number != 0:
            root.remove(node)
        elif number > 0:
            node.text = f"第 {number} 季"
            found.add(number)
    for number in range(1, season_count + 1):
        if number not in found:
            node = ET.SubElement(root, "namedseason", number=str(number))
            node.text = f"第 {number} 季"


def build_tvshow_nfo(
    show_name: str, poster: str | None = None, existing: str | None = None,
    season_count: int = 1,
) -> str:
    root = _load_root(existing, "tvshow")
    for tag, value in (("title", show_name), ("showtitle", show_name),
                       ("sorttitle", show_name)):
        _set_text(root, tag, value)
    _update_named_seasons(root, season_count)
    _set_poster(root, poster, {POSTER_NAME})
    return _serialize(root)


def build_season_nfo(
    season: int, *, show_name: str, poster: str | None = None,
    existing: str | None = None,
) -> str:
    root = _load_root(existing, "season")
    title = f"第 {season} 季"
    for tag, value in (
        ("seasonnumber", season),
        ("title", title),
        ("seasonname", title),
        ("showtitle", show_name),
        ("sorttitle", f"{show_name} {season:02d}"),
    ):
        _set_text(root, tag, value)
    _set_poster(root, poster, {POSTER_NAME, season_poster_name(season)})
    return _serialize(root)


def _update_fileinfo(root: ET.Element, episode: Episode) -> None:
    info = episode.video
    if info is None:
        return
    _set_text(root, "original_filename", info.path.name)

    stream: dict[str, object] = {}
    if info.codec:
        stream["codec"] = info.codec
    if info.width and info.height:
        stream.update(
            aspect=f"{info.width / info.height:.2f}".rstrip("0").rstrip("."),
            width=info.width,
            height=info.height,
            resolution=info.height,
        )
    if info.duration:
        stream["durationinseconds"] = int(round(info.duration))
    if not stream:
        return
    video = _child(_child(_child(root, "fileinfo"), "streamdetails"), "video")
    for tag, value in stream.items():
        _set_text(video, tag, value)


def build_episode_nfo(
    episode: Episode, *, show_name: str, existing: str | None = None
) -> str:
    root = _load_root(existing, "episodedetails")
    for tag, value in (
        ("title", episode.title),
        ("showtitle", show_name),
        ("season", episode.season),
        ("episode", episode.episode_no),
    ):
        _set_text(root, tag, value)
    if episode.video and episode.video.duration:
        _set_text(root, "runtime", max(1, int(round(episode.video.duration / 60))))
    _update_fileinfo(root, episode)
    return _serialize(root)


def parse_nfo(text: str) -> dict[str, str]:
    """解析详情页常用字段；解析失败不抛异常。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return {"_error": f"XML 解析失败：{exc}"}
    fields: dict[str, str] = {"_root": root.tag}
    tags = (
        "title", "originaltitle", "showtitle", "season", "episode", "seasonnumber",
        "seasonname", "sorttitle", "runtime", "plot", "original_filename", "thumb",
    )
    for tag in tags:
        element = root.find(tag)
        if element is not None and element.text:
            fields[tag] = element.text.strip()
    art = root.find("art")
    if art is not None:
        for tag in ("poster", "thumb", "fanart"):
            element = art.find(tag)
            if element is not None and element.text:
                fields[f"art.{tag}"] = element.text.strip()
    video = root.find("fileinfo/streamdetails/video")
    if video is not None:
        for tag in ("codec", "width", "height", "durationinseconds"):
            element = video.find(tag)
            if element is not None and element.text:
                fields[f"video.{tag}"] = element.text.strip()
    return fields
