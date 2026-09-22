"""离线检查每个轴距离真实运动还缺少哪些证据；不加载 DLL。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.diagnostic_profile import load_hardware_diagnostic_profile
from hardware.dimension_stage import DimensionStage, DimensionStageConfig


def readiness_for_axis(profile, axis_id: int) -> list[str]:
    if axis_id not in profile.axes:
        return [f"本地硬件配置没有轴 {axis_id}"]
    axis = profile.axes[axis_id]
    if profile.dll_path is None:
        connection_errors = ["dll_path 未配置"]
    else:
        connection_errors = []
    if not profile.pc_ip:
        connection_errors.append("pc_ip 未配置")
    if not profile.card_ip:
        connection_errors.append("card_ip 未配置")
    if axis.max_single_step_mm is None:
        connection_errors.append("max_single_step_mm 未配置")
    stage = DimensionStage(
        DimensionStageConfig(
            dll_path=profile.dll_path or Path("UNCONFIGURED_GAS.dll"),
            pc_ip=profile.pc_ip,
            card_ip=profile.card_ip,
            calibration=axis.calibration(),
            allow_motion=True,
            healthy_raw_status_values=(
                frozenset(axis.healthy_raw_status_values)
                if axis.healthy_raw_status_values
                else None
            ),
        )
    )
    return connection_errors + stage.motion_readiness_errors(check_live_status=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="真实运动离线 readiness audit；不加载 DLL、不连接、不移动"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("hardware_local.json")
    )
    parser.add_argument("--axis", type=int, action="append", help="可重复；默认检查全部轴")
    args = parser.parse_args()
    profile = load_hardware_diagnostic_profile(args.config)
    axes = args.axis or sorted(profile.axes)
    ready = True
    for axis_id in axes:
        errors = readiness_for_axis(profile, axis_id)
        print(f"axis {axis_id}:")
        if errors:
            ready = False
            for error in errors:
                print(f"  BLOCKED: {error}")
        else:
            print("  READY_FOR_SUPERVISED_MINIMAL_MOTION")
    print("hardware_accessed = False")
    raise SystemExit(0 if ready else 2)


if __name__ == "__main__":
    main()
