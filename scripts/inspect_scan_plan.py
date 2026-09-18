"""完全离线的 ScanPlan dry-run 命令行工具。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.stage_safety import AxisCalibration
from scan.scan_inspection import inspect_scan_plan
from scan.scan_plan import CameraSettings, ScanPlan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="离线检查扫描点、图片数、存储量和配置行程；绝不访问硬件"
    )
    parser.add_argument(
        "--positions-mm",
        required=True,
        help="逗号分隔的物理位置，例如 0,0.1,0.2,0.2",
    )
    parser.add_argument("--camera-count", type=int, default=1)
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--image-height", type=int)
    parser.add_argument("--image-width", type=int)
    parser.add_argument("--dtype", help="例如 uint16；需与图像宽高一起提供")
    parser.add_argument("--travel-min-mm", type=float)
    parser.add_argument("--travel-max-mm", type=float)
    parser.add_argument("--soft-limit-min-mm", type=float)
    parser.add_argument("--soft-limit-max-mm", type=float)
    parser.add_argument("--real-motion-enabled", action="store_true")
    args = parser.parse_args()

    if args.camera_count < 1:
        parser.error("--camera-count 必须至少为 1")
    positions = [value.strip() for value in args.positions_mm.split(",")]
    if not positions or any(not value for value in positions):
        parser.error("--positions-mm 格式无效")
    plan = ScanPlan(
        positions=[float(value) for value in positions],
        cameras=[
            CameraSettings(f"INSPECT-{index + 1}", exposure_us=1.0)
            for index in range(args.camera_count)
        ],
        frames_per_position=args.frames,
        repeats=args.repeats,
        save_root=Path("."),
        experiment_name="dry_run",
    )
    calibration = AxisCalibration(
        travel_min_mm=args.travel_min_mm,
        travel_max_mm=args.travel_max_mm,
        soft_limit_min_mm=args.soft_limit_min_mm,
        soft_limit_max_mm=args.soft_limit_max_mm,
    )
    image_shape = None
    image_arguments = (args.image_height, args.image_width, args.dtype)
    if any(value is not None for value in image_arguments):
        if any(value is None for value in image_arguments):
            parser.error("图像宽度、高度和 dtype 必须同时提供")
        assert args.image_height is not None
        assert args.image_width is not None
        image_shape = (args.image_height, args.image_width)
    inspection = inspect_scan_plan(
        plan,
        calibration=calibration,
        real_motion_enabled=args.real_motion_enabled,
        image_shape=image_shape,
        image_dtype=args.dtype,
    )
    print(json.dumps(inspection.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
