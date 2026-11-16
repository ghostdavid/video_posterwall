"""应用入口：创建 Qt 应用与主窗口。

运行时不创建任何配置、日志、缓存文件；sys.dont_write_bytecode 同时阻止
任何 .pyc 字节码落盘。所有需要的状态都保存在 MainWindow 的内存对象里。
"""
from __future__ import annotations

import sys
from pathlib import Path

from .constants import APP_NAME, APP_VERSION


def run() -> None:
    sys.dont_write_bytecode = True

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    icon_path = resource_root / "assets" / "app.ico"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
