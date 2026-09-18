"""安全命令行入口：默认只运行完全隔离真实硬件的 Mock 扫描。"""

from __future__ import annotations

import argparse
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Dimension Camera 扫描控制")
    parser.add_argument(
        "--mock-demo",
        action="store_true",
        help="运行 Mock 位移台 + Mock 相机闭环（当前默认且唯一的安全运行模式）",
    )
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    if not args.mock_demo:
        parser.error("当前入口不会默认连接真实硬件；请显式使用 --mock-demo")
    result = run_mock_demo(args.output)
    print(f"扫描完成：{result.resolve()}")


if __name__ == "__main__":
    main()
