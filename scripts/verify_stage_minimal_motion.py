"""受监督的单轴最小相对运动入口；未通过完整安全门时拒绝连接和运动。"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.diagnostic_profile import load_hardware_diagnostic_profile
from hardware.dimension_stage import DimensionStage, DimensionStageConfig
from hardware.stage_safety import StageSafetyError
from scripts.check_motion_readiness import readiness_for_axis


def main() -> None:
    parser = argparse.ArgumentParser(
        description="受监督单轴最小运动；默认仅预检，完整安全门未通过时绝不连接"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("hardware_local.json")
    )
    parser.add_argument("--axis", required=True, type=int)
    parser.add_argument("--delta-mm", required=True, type=float)
    parser.add_argument("--motion-timeout-s", type=float, default=10.0)
    parser.add_argument("--execute-supervised-motion", action="store_true")
    parser.add_argument("--confirm-physical-stop-ready", action="store_true")
    args = parser.parse_args()

    if not math.isfinite(args.delta_mm) or args.delta_mm == 0:
        parser.error("--delta-mm 必须是有限非零数")
    if not math.isfinite(args.motion_timeout_s) or args.motion_timeout_s <= 0:
        parser.error("--motion-timeout-s 必须是有限正数")
    profile = load_hardware_diagnostic_profile(args.config)
    if args.axis not in profile.axes:
        parser.error(f"hardware_local.json 中没有轴 {args.axis}")
    axis = profile.axes[args.axis]
    errors = readiness_for_axis(profile, args.axis)
    if axis.max_single_step_mm is not None and abs(args.delta_mm) > axis.max_single_step_mm:
        errors.append(
            f"请求步长 {args.delta_mm} mm 超过 max_single_step_mm="
            f"{axis.max_single_step_mm} mm"
        )
    if errors:
        print("真实运动被安全门拒绝：")
        for error in errors:
            print(f"  BLOCKED: {error}")
        print("hardware_accessed = False")
        raise SystemExit(2)
    if not args.execute_supervised_motion:
        print("静态安全预检通过；未提供 --execute-supervised-motion，因此未连接硬件。")
        return
    if not args.confirm_physical_stop_ready:
        parser.error("执行运动还必须提供 --confirm-physical-stop-ready")

    dll_path, pc_ip, card_ip = profile.require_stage_connection()
    stage = DimensionStage(
        DimensionStageConfig(
            dll_path=dll_path,
            pc_ip=pc_ip,
            card_ip=card_ip,
            calibration=axis.calibration(),
            allow_motion=True,
            healthy_raw_status_values=frozenset(axis.healthy_raw_status_values),
        )
    )
    try:
        stage.connect()
        current = stage.get_position_mm()
        target = current + args.delta_mm
        live_errors = stage.motion_readiness_errors(check_live_status=True)
        live_errors.extend(axis.calibration().target_errors(target))
        if live_errors:
            raise StageSafetyError(
                "现场安全预检失败：\n- " + "\n- ".join(live_errors)
            )
        expected = f"MOVE AXIS {args.axis} TO {target:.6f} MM"
        print(f"current_mm = {current:.6f}")
        print(f"target_mm = {target:.6f}")
        print(f"physical_mapping = {axis.physical_mapping}")
        typed = input(f"若现场人员和物理停止手段均已就位，请完整输入：{expected}\n> ")
        if typed != expected:
            raise SystemExit("确认文字不匹配；未发送运动命令")
        stage.move_absolute_mm(target)
        assert axis.pulses_per_mm is not None
        tolerance = stage.config.position_tolerance_pulse / axis.pulses_per_mm
        actual = stage.wait_until_idle(
            target_position=target,
            tolerance=tolerance,
            timeout_s=args.motion_timeout_s,
        )
        print(f"actual_mm = {actual:.6f}")
        print("result = completed")
    finally:
        stage.disconnect()


if __name__ == "__main__":
    main()
