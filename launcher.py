#!/usr/bin/env python3
"""源码运行与 PyInstaller 打包的统一入口。

    python launcher.py
    python -m PyInstaller video_posterwall.spec
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from app.main import run  # noqa: E402

if __name__ == "__main__":
    run()
