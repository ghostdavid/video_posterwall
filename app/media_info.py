"""只读探测视频与封面图信息。

视频：纯内置解析 MP4 / Matroska / AVI 文件头，不依赖任何外部程序；
      解析不到时至少给出文件大小与扩展名。
封面：使用 Qt 的 QImageReader 只读取图片头，不解码整图、不生成任何缓存文件。
"""
from __future__ import annotations

import struct
from pathlib import Path

from .models import FileInfo

_MP4_CONTAINERS = {
    b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"dinf", b"udta",
}
_MP4_EXTS = {".mp4", ".m4v", ".mov", ".3gp", ".m4b"}
_MKV_EXTS = {".mkv", ".webm", ".mk3d"}
_AVI_EXTS = {".avi", ".divx"}

_MKV_MASTERS = {
    0x18538067,  # Segment
    0x1549A966,  # Info
    0x1654AE6B,  # Tracks
    0xAE,        # TrackEntry
    0xE0,        # Video
}


# --------------------------------------------------------------------------- MP4 / MOV

def _atoms(buf: bytes, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        size = struct.unpack_from(">I", buf, pos)[0]
        kind = buf[pos + 4:pos + 8]
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack_from(">Q", buf, pos + 8)[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def _walk_mp4_atoms(buf: bytes, start: int, end: int, depth: int = 0):
    if depth > 6:
        return
    for kind, s, e in _atoms(buf, start, end):
        yield kind, s, e
        if kind in _MP4_CONTAINERS:
            yield from _walk_mp4_atoms(buf, s, e, depth + 1)


def _probe_mp4(path: Path, out: dict) -> None:
    total = path.stat().st_size
    moov = None
    with path.open("rb") as handle:
        pos = 0
        while pos + 8 <= total:
            handle.seek(pos)
            header = handle.read(16)
            if len(header) < 8:
                break
            box_size = struct.unpack_from(">I", header, 0)[0]
            kind = header[4:8]
            header_len = 8
            if box_size == 1:
                if len(header) < 16:
                    break
                box_size = struct.unpack_from(">Q", header, 8)[0]
                header_len = 16
            elif box_size == 0:
                box_size = total - pos
            if box_size < header_len or pos + box_size > total:
                break
            if kind == b"moov":
                handle.seek(pos + header_len)
                moov = handle.read(min(box_size - header_len, 16 * 1024 * 1024))
                break
            pos += box_size
    if not moov:
        return
    out.setdefault("fmt", "MP4")
    try:
        for kind, s, e in _walk_mp4_atoms(moov, 0, len(moov)):
            if kind == b"mvhd" and s + 24 <= e:
                version = moov[s]
                if version == 1:
                    timescale, duration = struct.unpack_from(">IQ", moov, s + 20)
                else:
                    timescale, duration = struct.unpack_from(">II", moov, s + 12)
                if timescale > 0 and duration > 0:
                    out["duration"] = duration / timescale
            elif kind == b"stsd" and s + 44 <= e:
                entry = s + 8  # version/flags + entry_count
                if entry + 36 <= e:
                    fmt = moov[entry + 4:entry + 8].decode("latin-1", "replace").strip("\x00")
                    width, height = struct.unpack_from(">HH", moov, entry + 32)
                    if 0 < width < 20000 and 0 < height < 20000:
                        out["width"], out["height"] = width, height
                        if fmt:
                            out["codec"] = fmt
    except (struct.error, ValueError, IndexError):
        pass


# --------------------------------------------------------------------------- Matroska / WebM

def _vint_length(first: int) -> int:
    mask = 0x80
    for length in range(1, 9):
        if first & mask:
            return length
        mask >>= 1
    return 0


def _ebml_size(buf: bytes, pos: int) -> tuple[int | None, int, bool]:
    if pos >= len(buf):
        return None, 0, False
    length = _vint_length(buf[pos])
    if not length or pos + length > len(buf):
        return None, 0, False
    value = buf[pos] & ((1 << (8 - length)) - 1)
    for offset in range(1, length):
        value = (value << 8) | buf[pos + offset]
    unknown = value == (1 << (7 * length)) - 1
    return value, length, unknown


def _ebml_elements(buf: bytes, start: int, end: int):
    pos = start
    while pos + 2 <= end:
        id_len = _vint_length(buf[pos])
        if not id_len or pos + id_len >= end:
            return
        element_id = int.from_bytes(buf[pos:pos + id_len], "big")
        size, size_len, unknown = _ebml_size(buf, pos + id_len)
        if size is None:
            return
        content_start = pos + id_len + size_len
        content_end = end if unknown else min(end, content_start + size)
        yield element_id, content_start, content_end, unknown
        if unknown or content_end <= pos:
            return
        pos = content_end


def _probe_mkv(path: Path, out: dict) -> None:
    with path.open("rb") as handle:
        buf = handle.read(min(path.stat().st_size, 8 * 1024 * 1024))
    scale = 1_000_000.0
    duration_raw: float | None = None
    out.setdefault("fmt", "Matroska")

    def walk(start: int, end: int, depth: int = 0) -> None:
        nonlocal scale, duration_raw
        if depth > 6:
            return
        for element_id, cs, ce, _unknown in _ebml_elements(buf, start, end):
            try:
                if element_id == 0x2AD7B1 and ce > cs:  # TimecodeScale
                    scale = float(int.from_bytes(buf[cs:ce], "big")) or scale
                elif element_id == 0x4489 and ce >= cs + 4:  # Duration
                    payload = buf[cs:ce]
                    duration_raw = (
                        struct.unpack_from(">d", payload)[0] if len(payload) >= 8
                        else struct.unpack_from(">f", payload)[0]
                    )
                elif element_id == 0xB0 and ce > cs:  # PixelWidth
                    out["width"] = int.from_bytes(buf[cs:ce], "big")
                elif element_id == 0xBA and ce > cs:  # PixelHeight
                    out["height"] = int.from_bytes(buf[cs:ce], "big")
                elif element_id == 0x86 and ce > cs:  # CodecID
                    out["codec"] = buf[cs:ce].decode("utf-8", "replace").strip("\x00")
                elif element_id in _MKV_MASTERS:
                    walk(cs, ce, depth + 1)
            except (struct.error, ValueError, IndexError):
                continue

    walk(0, len(buf))
    if duration_raw and duration_raw > 0:
        seconds = duration_raw * scale / 1e9
        if seconds < 10 and duration_raw > 60:
            seconds = float(duration_raw)  # 少数文件直接以秒写入
        if 1 <= seconds < 86400:
            out["duration"] = seconds


# --------------------------------------------------------------------------- AVI

def _probe_avi(path: Path, out: dict) -> None:
    with path.open("rb") as handle:
        buf = handle.read(min(path.stat().st_size, 512 * 1024))
    index = buf.find(b"avih")
    out.setdefault("fmt", "AVI")
    if index < 0 or index + 44 > len(buf):
        return
    start = index + 4
    try:
        microseconds = struct.unpack_from("<I", buf, start)[0]
        frames = struct.unpack_from("<I", buf, start + 16)[0]
        width = struct.unpack_from("<I", buf, start + 32)[0]
        height = struct.unpack_from("<I", buf, start + 36)[0]
        if 0 < width < 20000 and 0 < height < 20000:
            out["width"], out["height"] = width, height
        if microseconds and frames:
            out["duration"] = frames * microseconds / 1_000_000
    except (struct.error, ValueError):
        pass


# --------------------------------------------------------------------------- 对外接口

def probe_video(info: FileInfo) -> FileInfo:
    try:
        container: dict = {}
        ext = info.ext.lower()
        if ext in _MP4_EXTS:
            _probe_mp4(info.path, container)
        elif ext in _MKV_EXTS:
            _probe_mkv(info.path, container)
        elif ext in _AVI_EXTS:
            _probe_avi(info.path, container)
        else:
            container["fmt"] = ext.lstrip(".").upper() or "VIDEO"
            container["note"] = "此格式未内置解析，仅显示基础信息"
        data = container
    except (OSError, ValueError, struct.error) as exc:
        info.note = f"视频头解析失败：{exc}"
        data = {"fmt": info.ext.lstrip(".").upper() or "VIDEO"}

    for field in ("width", "height", "duration", "codec", "fmt"):
        value = data.get(field)
        if value:
            setattr(info, field, value)
    if data.get("note") and not info.note:
        info.note = str(data["note"])
    return info


def probe_cover(info: FileInfo) -> FileInfo:
    from PySide6.QtGui import QImage, QImageReader

    try:
        reader = QImageReader(str(info.path))
        reader.setAutoDetectImageFormat(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            info.width, info.height = size.width(), size.height()
        raw = reader.format()
        try:
            fmt = bytes(raw).decode("ascii", "replace")
        except (TypeError, ValueError):
            fmt = raw.data().decode("ascii", "replace") if hasattr(raw, "data") else ""
        info.fmt = (fmt or info.ext.lstrip(".")).upper()
        if info.width is None:
            image = QImage(str(info.path))
            if not image.isNull():
                info.width, info.height = image.width(), image.height()
        if info.width is None:
            info.note = "Qt 无法解析该图片，可能是格式不受支持或文件损坏"
    except Exception as exc:  # Qt 组件异常不应中断整批扫描
        info.note = f"图片解析失败：{exc}"
        info.fmt = info.ext.lstrip(".").upper()
    return info


def image_to_jpeg_bytes(path: Path, quality: int = 92) -> bytes:
    """在内存中把任意受支持的图片转成 JPEG 字节，用于生成 poster.jpg。

    只读源图片，不写任何中间文件；源图片本身不会被修改。
    """
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"无法读取图片：{path}")
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ValueError("无法创建内存缓冲区")
    try:
        if not image.save(buffer, "JPG", quality):
            raise ValueError(f"无法把图片转换为 JPEG：{path}")
        return bytes(buffer.data())
    finally:
        buffer.close()
