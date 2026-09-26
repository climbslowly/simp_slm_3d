"""轴 1..5 增强只读快照；不调用任何运动、使能、清零或 Home API。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.diagnostic_profile import load_hardware_diagnostic_profile
from hardware.diagnostics import read_stage_axes_snapshot, write_timestamped_report


def _parse_axes(text: str) -> list[int]:
    axes = [int(item.strip()) for item in text.split(",") if item.strip()]
    if not axes or len(set(axes)) != len(axes):
        raise argparse.ArgumentTypeError("轴列表必须非空且不能重复")
    if any(axis < 1 or axis > 8 for axis in axes):
        raise argparse.ArgumentTypeError("轴号必须在 1..8")
    return axes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dimension/GAS 多轴增强只读快照；不调用任何状态修改或运动 API"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("hardware_local.json")
    )
    parser.add_argument(
        "--axes", type=_parse_axes, default=[1, 2, 3, 4, 5], help="例如 1,2,3,4,5"
    )
    parser.add_argument("--confirm-read-only", action="store_true")
    args = parser.parse_args()
    if not args.confirm_read_only:
        parser.error("必须显式提供 --confirm-read-only")

    profile = load_hardware_diagnostic_profile(args.config)
    dll_path, pc_ip, card_ip = profile.require_stage_connection()
    report = read_stage_axes_snapshot(
        dll_path=dll_path,
        pc_ip=pc_ip,
        card_ip=card_ip,
        axes=args.axes,
    )
    report_path = write_timestamped_report(
        profile.output_dir, "stage_readonly_snapshot", report
    )
    for item in report["axes"]:
        if item["status"] == "ok":
            interpretation = item["status_interpretation"]
            assert isinstance(interpretation, dict)
            print(
                f"axis {item['axis_id']}: planned={item['planned_position_raw_pulse']} pulse, "
                f"encoder={item.get('encoder_position_raw_pulse', 'READ_ERROR')} pulse, "
                f"raw_status={item['raw_status_decimal']} ({item['raw_status_hex']}), "
                f"flags={interpretation['active_flags']}"
            )
            soft_limits = item.get("controller_soft_limits_raw_pulse")
            if soft_limits is not None:
                print(f"  controller_soft_limits_raw_pulse={soft_limits}")
            if interpretation["safety_faults"]:
                print(f"  SAFETY_FAULTS={interpretation['safety_faults']}")
            for error in item.get("optional_read_errors", []):
                print(f"  OPTIONAL_READ_ERROR: {error}")
        else:
            print(f"axis {item['axis_id']}: ERROR {item['error']}")
    print("raw_status interpretation = ETH_GAS_N V7.3 section 5.6")
    print("motion_commanded = False")
    print("state_changing_api_called = False")
    print(f"report = {report_path.resolve()}")


if __name__ == "__main__":
    main()
