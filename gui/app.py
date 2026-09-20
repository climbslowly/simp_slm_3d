"""GUI-M1 启动入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Dimension Camera GUI-M1 Mock 扫描")
    parser.add_argument("--open", type=Path, help="启动后打开已有 GUI-M1 扫描目录")
    parser.add_argument("--auto-scan", action="store_true", help="自动运行默认 5×3 Mock 扫描（测试/证据用）")
    parser.add_argument("--screenshot", type=Path, help="扫描完成后保存真实 Qt 窗口截图")
    parser.add_argument("--offscreen", action="store_true", help="使用 Qt offscreen 平台；截图不代表人工点击验证")
    args = parser.parse_args()
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtGui, QtWidgets
    from gui.main_window import MainWindow

    application = QtWidgets.QApplication(sys.argv[:1])
    # 某些离屏 Qt 平台不会自动枚举 Windows 字体，显式加载可读中文字体。
    font_id = QtGui.QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\simhei.ttf")
    if font_id >= 0:
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            application.setFont(QtGui.QFont(families[0], 9))
    window = MainWindow()
    if args.open:
        window.open_session(args.open)
    window.show()
    if args.auto_scan:
        def configure_and_start() -> None:
            window.scan_type.setCurrentText("XY")
            for control, value in zip(window.axis1, (-0.4, 0.4, 0.2)): control.setValue(value)
            for control, value in zip(window.axis2, (-0.2, 0.2, 0.2)): control.setValue(value)
            window.settling.setValue(1.0)
            window.start_scan()
        QtCore.QTimer.singleShot(0, configure_and_start)
    if args.screenshot:
        def save_and_quit(_directory: object) -> None:
            def capture() -> None:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(args.screenshot))
                window.close()
            QtCore.QTimer.singleShot(500, capture)
        window.scan_finished.connect(save_and_quit)
        if args.open and not args.auto_scan:
            QtCore.QTimer.singleShot(500, lambda: save_and_quit(args.open))
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
