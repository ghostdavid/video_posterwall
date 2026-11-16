"""加速后端：CPU 多线程 + 可选 CUDA GPU。

封面指纹（64 位 dHash）用于发现重复/损坏封面。GPU 后端把整批 9×8 灰度矩阵
一次性上传到显存做批量位比较；CPU 后端在线程池里逐张计算。
GPU 属于可选能力：未检测到 CUDA 运行时会自动回退到 CPU 多线程，功能不受影响。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendInfo:
    key: str
    label: str
    kind: str  # cpu | gpu
    device: str
    detail: str


def _external_site_candidates() -> list[str]:
    """冻结程序的 sys.path 不含外部 site-packages；只读补上常见位置。

    目的：本机若装有 CUDA 版 torch / cupy 就能被自动发现，无需任何用户配置。
    全程只做目录判断与 sys.path 追加，不创建文件。
    """
    candidates: list[str] = []
    for part in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        part = part.strip()
        if part and os.path.isdir(part) and part not in candidates:
            candidates.append(part)
    try:
        import site

        user_site = site.getusersitepackages()
        if isinstance(user_site, str) and os.path.isdir(user_site):
            candidates.append(user_site)
    except Exception:
        pass
    version = f"Python{sys.version_info.major}{sys.version_info.minor}"
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", ""), "C:/"):
        if not base:
            continue
        for tail in (
            f"Programs/Python/{version}/Lib/site-packages",
            f"{version}/Lib/site-packages",
        ):
            path = os.path.join(base, *tail.split("/"))
            if os.path.isdir(path) and path not in candidates:
                candidates.append(path)
    return candidates


def detect_backends() -> list[BackendInfo]:
    """自动探测本机 CUDA 运行时，无需用户指定任何路径。"""
    for path in _external_site_candidates():
        if path not in sys.path:
            sys.path.append(path)

    backends = [
        BackendInfo(
            key="cpu",
            label="CPU 多线程",
            kind="cpu",
            device=f"{os.cpu_count() or 1} 逻辑处理器",
            detail="始终可用，受线程数设置控制",
        )
    ]
    try:
        import torch  # type: ignore

        if getattr(torch, "cuda", None) is not None and torch.cuda.is_available():
            try:
                device = torch.cuda.get_device_name(0)
            except Exception:
                device = "CUDA 设备"
            backends.append(
                BackendInfo("torch_cuda", "GPU · PyTorch CUDA", "gpu", device,
                            f"PyTorch {getattr(torch, '__version__', '?')}")
            )
    except Exception:
        pass
    try:
        import cupy  # type: ignore

        if cupy.cuda.runtime.getDeviceCount() > 0:
            try:
                props = cupy.cuda.runtime.getDeviceProperties(0)
                name = props.get("name", "CUDA 设备")
                device = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
            except Exception:
                device = "CUDA 设备"
            backends.append(
                BackendInfo("cupy_cuda", "GPU · CuPy CUDA", "gpu", device,
                            f"CuPy {getattr(cupy, '__version__', '?')}")
            )
    except Exception:
        pass
    return backends


def choose_backend(requested: str, backends: list[BackendInfo]) -> str:
    keys = {b.key for b in backends}
    if requested == "cpu":
        return "cpu"
    if requested == "auto":
        for backend in backends:
            if backend.kind == "gpu":
                return backend.key
        return "cpu"
    return requested if requested in keys else "cpu"


def backend_label(key: str, backends: list[BackendInfo]) -> str:
    for backend in backends:
        if backend.key == key:
            return backend.label
    return "CPU 多线程"


class Fingerprinter:
    """把封面图转成 64 位感知哈希。"""

    def __init__(self, backend_key: str = "cpu"):
        self.backend_key = backend_key
        self.last_fallback = ""

    def grayscale_matrix(self, path: Path) -> list[list[int]] | None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        try:
            image = QImage(str(path))
            if image.isNull():
                return None
            image = image.scaled(
                9, 8,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            image = image.convertToFormat(QImage.Format.Format_Grayscale8)
            return [[image.pixelColor(x, y).red() for x in range(9)] for y in range(8)]
        except Exception:
            return None

    @staticmethod
    def _pack(rows: list[list[int]]) -> str:
        value = 0
        for row in rows:
            for bit in row:
                value = (value << 1) | (1 if bit else 0)
        return f"{value:016x}"

    def _hash_cpu(self, matrices: list[list[list[int]]]) -> list[str]:
        result = []
        for matrix in matrices:
            rows = [
                [1 if matrix[y][x + 1] > matrix[y][x] else 0 for x in range(8)]
                for y in range(8)
            ]
            result.append(self._pack(rows))
        return result

    def _hash_torch(self, matrices: list[list[list[int]]]) -> list[str]:
        import torch  # type: ignore

        tensor = torch.tensor(matrices, dtype=torch.float32, device="cuda")
        bits = (tensor[:, :, 1:] > tensor[:, :, :-1]).to(torch.uint8).cpu().tolist()
        return [self._pack(rows) for rows in bits]

    def _hash_cupy(self, matrices: list[list[list[int]]]) -> list[str]:
        import cupy  # type: ignore

        array = cupy.asarray(matrices, dtype=cupy.float32)
        bits = (array[:, :, 1:] > array[:, :, :-1]).get().tolist()
        return [self._pack(rows) for rows in bits]

    def hash_batch(self, matrices: list[list[list[int]]]) -> list[str]:
        self.last_fallback = ""
        if not matrices:
            return []
        key = self.backend_key
        if key == "torch_cuda":
            try:
                return self._hash_torch(matrices)
            except Exception as exc:
                self.last_fallback = f"PyTorch CUDA 不可用，已回退 CPU：{exc}"
        elif key == "cupy_cuda":
            try:
                return self._hash_cupy(matrices)
            except Exception as exc:
                self.last_fallback = f"CuPy CUDA 不可用，已回退 CPU：{exc}"
        return self._hash_cpu(matrices)


def duplicate_groups(hashes: list[str]) -> list[tuple[str, list[int]]]:
    buckets: dict[str, list[int]] = {}
    for index, value in enumerate(hashes):
        if value:
            buckets.setdefault(value, []).append(index)
    return [(value, indices) for value, indices in buckets.items() if len(indices) > 1]
