"""安全命令行入口：Mock 扫描或真实硬件的当前位置单帧采集。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tifffile

from hardware.basler_camera import (
    BaslerCamera,
    BaslerDeviceInfo,
    enumerate_basler_cameras,
    select_basler_camera,
)
from hardware.dimension_stage import DimensionStage, DimensionStageConfig
from hardware.stage_safety import AxisCalibration
from mock.mock_camera import MockCamera
from mock.mock_stage import MockStage
from scan.scan_controller import ScanController
from scan.scan_plan import CameraSettings, ScanPlan


def run_mock_demo(output: Path) -> Path:
    stage = MockStage(initial_position=0.0, speed_units_per_s=50.0)
    stage.connect()
    camera = MockCamera(position_provider=stage.get_position)
    camera.connect()
    plan = ScanPlan.from_range(
        start="0.0",
        stop="0.4",
        step="0.2",
        cameras=[CameraSettings(camera.get_serial_number(), exposure_us=1000.0)],
        save_root=output,
        experiment_name="mock_demo",
        settling_time_s=0.01,
        position_tolerance=1e-6,
    )
    controller = ScanController(stage, {camera.get_serial_number(): camera})
    try:
        session_dir = controller.run(plan)
        assert session_dir is not None
        return session_dir
    finally:
        camera.disconnect()
        stage.disconnect()


def capture_current_position(
    *,
    output: Path,
    dll_path: Path,
    controller_ip: str,
    host_ip: str,
    axis_id: int,
    camera_device: BaslerDeviceInfo,
) -> tuple[Path, Path, Path, dict[str, object]]:
    """只读当前位置并采集一帧；绝不调用位移台的运动/使能 API。

    GAS 的已确认位置 API 返回的是规划位置原值（pulse/count）。在没有经过现场
    标定前，不能把它换算或标记成 mm，因此 metadata 会明确保留单位 pulse。
    """
    stage = DimensionStage(
        DimensionStageConfig(
            dll_path=dll_path,
            controller_ip=controller_ip,
            host_ip=host_ip,
            calibration=AxisCalibration(axis_id=axis_id),
            allow_motion=False,
        )
    )
    camera = BaslerCamera(camera_device.serial_number)
    try:
        stage.connect()
        position_pulse = stage.get_position_pulse()
        raw_status = stage.read_raw_status()

        camera.connect()
        image = camera.grab_image()
        camera_model = camera.get_model_name()
        exposure_us = camera.get_exposure_us()
    finally:
        camera.disconnect()
        stage.disconnect()

    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = output / f"{timestamp}_current_capture"
    suffix = 1
    while session_dir.exists():
        session_dir = output / f"{timestamp}_current_capture_{suffix:03d}"
        suffix += 1
    session_dir.mkdir()
    safe_serial = re.sub(r"[^A-Za-z0-9_-]", "_", camera_device.serial_number)
    stem = f"Camera_{safe_serial}_current_raw_pulse_{position_pulse:g}"
    image_path = session_dir / f"{stem}.tiff"
    numpy_path = session_dir / f"{stem}.npy"
    tifffile.imwrite(image_path, image)
    np.save(numpy_path, image, allow_pickle=False)
    metadata: dict[str, object] = {
        "capture_time_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "operation": "current_position_single_frame_capture",
        "stage": {
            "controller_ip": controller_ip,
            "axis_id": axis_id,
            "position_value": position_pulse,
            "position_unit": "pulse/count",
            "position_meaning": "GAS GA_GetPrfPos planned position; not encoder position",
            "raw_status_decimal": raw_status,
            "raw_status_hex": f"0x{raw_status & 0xFFFFFFFF:08X}",
            "raw_status_interpretation": "UNKNOWN",
            "motion_commanded": False,
        },
        "camera": {
            **camera_device.to_dict(),
            "model_name": camera_model,
            "exposure_us": exposure_us,
            "image_shape": list(image.shape),
            "image_dtype": str(image.dtype),
        },
        "files": {
            "tiff": image_path.name,
            "numpy": numpy_path.name,
        },
    }
    (session_dir / "capture_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return session_dir, image_path, numpy_path, metadata


def print_basler_camera_list() -> list[BaslerDeviceInfo]:
    """枚举并打印全部 pylon 可见设备，列表序号从 0 开始。"""
    devices = enumerate_basler_cameras()
    if not devices:
        print("未发现任何 pylon 相机。")
        print("请检查 USB/CXP 线缆、相机供电、采集卡驱动和 pylon/GenTL transport layer。")
        return devices
    print(f"发现 {len(devices)} 台 pylon 相机：")
    for device in devices:
        print(
            f"[{device.index}] model={device.model_name or 'UNKNOWN'} | "
            f"serial={device.serial_number or 'UNKNOWN'} | "
            f"transport={device.transport_layer_type or device.device_class or 'UNKNOWN'} | "
            f"interface={device.interface_id or 'UNKNOWN'}"
        )
    return devices


def main() -> None:
    parser = argparse.ArgumentParser(description="Dimension Camera 扫描控制")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--mock-demo",
        action="store_true",
        help="运行 Mock 位移台 + Mock 相机扫描闭环",
    )
    modes.add_argument(
        "--capture-current",
        action="store_true",
        help="只读真实位移台当前位置，并让指定 Basler 相机采集一帧；不移动位移台",
    )
    modes.add_argument(
        "--list-cameras",
        action="store_true",
        help="列出 pylon 当前可见的全部 USB/GigE/CXP 相机",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出目录；Mock 默认 output，真实单帧默认 data/captures",
    )
    parser.add_argument("--stage-dll", type=Path, help="现场确认的 GAS.dll 路径")
    parser.add_argument("--controller-ip", help="现场确认的控制器 IP")
    parser.add_argument("--host-ip", help="现场确认的本机网卡 IP")
    parser.add_argument("--axis", type=int, help="现场确认的轴号（1..8）")
    parser.add_argument(
        "--camera-index",
        type=int,
        help="--list-cameras 显示的相机序号（从 0 开始）",
    )
    parser.add_argument(
        "--confirm-current-capture",
        action="store_true",
        help="确认只执行位移台 connect/read/disconnect 与相机单帧采集",
    )
    args = parser.parse_args()
    if args.list_cameras:
        print_basler_camera_list()
        return
    if args.mock_demo:
        result = run_mock_demo(args.output or Path("output"))
        print(f"扫描完成：{result.resolve()}")
        return

    required = {
        "--stage-dll": args.stage_dll,
        "--controller-ip": args.controller_ip,
        "--host-ip": args.host_ip,
        "--axis": args.axis,
        "--camera-index": args.camera_index,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error("--capture-current 缺少参数：" + ", ".join(missing))
    if not args.confirm_current_capture:
        parser.error("必须显式提供 --confirm-current-capture")
    assert args.stage_dll is not None and args.controller_ip is not None
    assert args.host_ip is not None and args.axis is not None
    assert args.camera_index is not None
    camera_device = select_basler_camera(args.camera_index)
    session_dir, image_path, numpy_path, metadata = capture_current_position(
        output=args.output or Path("data/captures"),
        dll_path=args.stage_dll,
        controller_ip=args.controller_ip,
        host_ip=args.host_ip,
        axis_id=args.axis,
        camera_device=camera_device,
    )
    print(f"当前位置（规划位置原值）= {metadata['stage']['position_value']} pulse/count")
    print(f"单帧 TIFF = {image_path.resolve()}")
    print(f"NumPy 数组 = {numpy_path.resolve()}")
    print(f"采集 metadata = {(session_dir / 'capture_metadata.json').resolve()}")


if __name__ == "__main__":
    main()
