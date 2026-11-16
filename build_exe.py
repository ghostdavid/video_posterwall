#!/usr/bin/env python3
"""构建 Windows 11 目录版 exe。

    python build_exe.py
    python build_exe.py --clean
    python build_exe.py --distpath D:/out/dist --workpath D:/out/build

若工作区所在盘符对构建进程只读（例如 VirtualBox 共享文件夹的盘符映射），
可通过 --distpath / --workpath 指定可写路径。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="打包剧集海报墙生成器（onedir）")
    parser.add_argument("--distpath", default=str(ROOT / "dist"), help="产物目录")
    parser.add_argument("--workpath", default=str(ROOT / "build"), help="构建缓存目录")
    parser.add_argument("--clean", action="store_true", help="清理 PyInstaller 缓存后构建")
    args = parser.parse_args()

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", args.distpath,
        "--workpath", args.workpath,
    ]
    if args.clean:
        command.append("--clean")
    command.append(str(ROOT / "video_posterwall.spec"))

    print("构建命令：", " ".join(command), flush=True)
    result = subprocess.call(command, cwd=str(ROOT))
    if result == 0:
        print(f"\n构建完成：{Path(args.distpath) / 'VideoPosterWall' / 'VideoPosterWall.exe'}")
        print("分发时请复制整个 VideoPosterWall 目录，不要只复制 exe 文件。")
    else:
        print("\n构建失败，请查看上方 PyInstaller 输出。")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
