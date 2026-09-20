"""真实位移台只读验证：加载 DLL -> 连接 -> 读 raw 值 -> 断开。

此脚本不会 Reset、清零、使能、Home、Stop 或移动。使用前必须确认 IP 与轴号。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 当脚本以 ``python scripts/verify_stage_readonly.py`` 直接运行时，Python 默认只把
# scripts/ 放入模块搜索路径。显式加入项目根目录，用户无需先安装本项目为 package。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.dimension_stage import DimensionStage, DimensionStageConfig
from hardware.stage_safety import AxisCalibration


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dimension/GAS 第一次接入只读检查；绝不调用运动 API"
    )
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--pc-ip", required=True, help="实验电脑专用网卡 IP（PCIP）")
    parser.add_argument("--card-ip", required=True, help="运动控制卡 IP（CardIP）")
    parser.add_argument("--axis", required=True, type=int)
    parser.add_argument(
        "--confirm-read-only",
        action="store_true",
        help="确认只执行 DLL load、connect、raw position/status read、disconnect",
    )
    args = parser.parse_args()
    if not args.confirm_read_only:
        parser.error("必须显式提供 --confirm-read-only")
    stage = DimensionStage(
        DimensionStageConfig(
            dll_path=args.dll,
            pc_ip=args.pc_ip,
            card_ip=args.card_ip,
            calibration=AxisCalibration(axis_id=args.axis),
            allow_motion=False,
        )
    )
    try:
        stage.load_library()
        print(f"access_level = {stage.access_level.name}")
        print(f"GAS.dll loaded = {args.dll.resolve()}")
        stage.connect()
        print(f"access_level = {stage.access_level.name}")
        print(f"pc_ip = {args.pc_ip}")
        print(f"card_ip = {args.card_ip}")
        print(f"axis_id = {args.axis}")
        print("controller model = UNKNOWN (no confirmed query API)")
        print("firmware = UNKNOWN (no confirmed query API)")
        position_pulse = stage.get_position_pulse()
        raw_status = stage.read_raw_status()
        print(f"planned_position_raw_pulse = {position_pulse}")
        print(f"raw_status_decimal = {raw_status}")
        print(f"raw_status_hex = 0x{raw_status & 0xFFFFFFFF:08X}")
        print("raw_status interpretation = UNKNOWN; no bits were interpreted")
    finally:
        stage.disconnect()


if __name__ == "__main__":
    main()
