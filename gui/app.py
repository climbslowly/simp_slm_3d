"""五轴扫描 GUI 启动入口；默认 Mock，REAL 模式必须显式确认。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Dimension Camera 五轴扫描 GUI")
    parser.add_argument("--config", type=Path, default=Path("configuration.json"))
    parser.add_argument("--open", type=Path, help="启动后打开已有 GUI-M1 扫描目录")
    parser.add_argument("--auto-scan", action="store_true", help="自动运行默认 5×3 Mock 扫描（测试/证据用）")
    parser.add_argument("--screenshot", type=Path, help="扫描完成后保存真实 Qt 窗口截图")
    parser.add_argument("--offscreen", action="store_true", help="使用 Qt offscreen 平台；截图不代表人工点击验证")
    parser.add_argument("--real", action="store_true", help="连接 hardware_local.json 中的真实五轴和 Basler 相机")
    parser.add_argument("--hardware-config", type=Path, default=Path("hardware_local.json"))
    parser.add_argument("--confirm-real-motion", action="store_true", help="允许 REAL GUI 发出受限运动命令")
    args = parser.parse_args()
    if args.confirm_real_motion and not args.real:
        parser.error("--confirm-real-motion 只能与 --real 一起使用")
    if args.real and not args.confirm_real_motion:
        parser.error("REAL GUI 必须同时提供 --confirm-real-motion")
    if args.real and args.auto_scan:
        parser.error("REAL GUI 禁止使用 --auto-scan")
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
    if args.real:
        from hardware.basler_camera import BaslerCamera, select_basler_camera
        from hardware.diagnostic_profile import load_hardware_diagnostic_profile
        from hardware.gas_five_axis_stage import GasFiveAxisStage

        profile = load_hardware_diagnostic_profile(args.hardware_config)
        if profile.camera.camera_index is None:
            parser.error("hardware_local.json 缺少 camera.camera_index")
        selected = select_basler_camera(profile.camera.camera_index)
        stage = GasFiveAxisStage(profile, allow_motion=True)
        camera = BaslerCamera(selected.serial_number)
        window = MainWindow(
            config_path=args.config,
            stage=stage,
            camera=camera,
            device_mode="REAL",
        )
    else:
        window = MainWindow(config_path=args.config)
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
