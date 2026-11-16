# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 目录版（onedir）打包配置。

产物：dist/VideoPosterWall/VideoPosterWall.exe + 同目录依赖文件。
onedir 运行时不会像 onefile 那样解压到系统临时目录，符合「只在专辑文件夹写盘」的约束。
"""
import os

from PyInstaller.utils.hooks import collect_submodules

SPEC_ROOT = os.path.abspath(SPECPATH)
ICON_PATH = os.path.join(SPEC_ROOT, "assets", "app.ico")

a = Analysis(
    ["launcher.py"],
    pathex=[SPEC_ROOT],
    binaries=[],
    datas=[(ICON_PATH, "assets")],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        *collect_submodules("app"),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本地样例与构建输出不属于应用运行代码。
        "test", "dist",
        "tkinter", "matplotlib", "numpy", "PIL", "PyQt5", "PyQt6",
        "torch", "cupy", "cv2", "pytest", "IPython", "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_kwargs = dict(
    exclude_binaries=True,
    name="VideoPosterWall",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # GUI 程序，不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
if os.path.isfile(ICON_PATH):
    exe_kwargs["icon"] = ICON_PATH

exe = EXE(pyz, a.scripts, [], **exe_kwargs)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoPosterWall",
)
