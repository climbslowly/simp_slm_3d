"""真实位移台的能力声明、轴标定和单位转换。

这个模块只保存“已经知道什么”，不访问 DLL，也不控制硬件。未知信息必须保留为
``None``；不能为了让程序通过检查而填写推测值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntFlag


class StageSafetyError(RuntimeError):
    """真实运动未通过安全门时抛出的异常。"""


class UnsupportedStageOperation(NotImplementedError):
    """厂家资料尚未确认某项能力时抛出的异常。"""


class AxisStatusFlag(IntFlag):
    """ETH_GAS_N V7.3 手册 5.6 节定义的 32 位轴状态。"""

    ESTOP = 0x00000001
    SERVO_ALARM = 0x00000002
    POSITIVE_SOFT_LIMIT = 0x00000004
    NEGATIVE_SOFT_LIMIT = 0x00000008
    FOLLOW_ERROR = 0x00000010
    POSITIVE_HARD_LIMIT = 0x00000020
    NEGATIVE_HARD_LIMIT = 0x00000040
    RESERVED_IO_SMS_STOP = 0x00000080
    RESERVED_IO_EMG_STOP = 0x00000100
    ENABLED = 0x00000200
    RUNNING = 0x00000400
    ARRIVED = 0x00000800
    HOME_RUNNING = 0x00001000
    HOME_SUCCESS = 0x00002000
    HOME_SWITCH = 0x00004000
    INDEX = 0x00008000
    GEAR_START = 0x00010000
    GEAR_FINISH = 0x00020000


AXIS_STATUS_SAFETY_FAULTS: tuple[tuple[AxisStatusFlag, str], ...] = (
    (AxisStatusFlag.ESTOP, "急停状态有效"),
    (AxisStatusFlag.SERVO_ALARM, "驱动器报警"),
    (AxisStatusFlag.POSITIVE_SOFT_LIMIT, "正软限位触发"),
    (AxisStatusFlag.NEGATIVE_SOFT_LIMIT, "负软限位触发"),
    (AxisStatusFlag.FOLLOW_ERROR, "规划位置与实际位置跟随误差过大"),
    (AxisStatusFlag.POSITIVE_HARD_LIMIT, "正硬限位触发"),
    (AxisStatusFlag.NEGATIVE_HARD_LIMIT, "负硬限位触发"),
    (AxisStatusFlag.RESERVED_IO_SMS_STOP, "手册保留状态位 0x00000080 置位"),
    (AxisStatusFlag.RESERVED_IO_EMG_STOP, "手册保留状态位 0x00000100 置位"),
)


def decode_axis_status(raw_status: int) -> dict[str, object]:
    """把 raw status 解码为可审计字段，不把 HOME 信号等信息位当成故障。"""

    unsigned = raw_status & 0xFFFFFFFF
    active_flags = [flag.name for flag in AxisStatusFlag if unsigned & int(flag)]
    safety_faults = [
        message for flag, message in AXIS_STATUS_SAFETY_FAULTS if unsigned & int(flag)
    ]
    known_mask = 0
    for flag in AxisStatusFlag:
        known_mask |= int(flag)
    return {
        "raw_decimal": raw_status,
        "raw_hex": f"0x{unsigned:08X}",
        "active_flags": active_flags,
        "unknown_bits_hex": f"0x{unsigned & ~known_mask & 0xFFFFFFFF:08X}",
        "safety_faults": safety_faults,
        "enabled": bool(unsigned & AxisStatusFlag.ENABLED),
        "running": bool(unsigned & AxisStatusFlag.RUNNING),
        "arrived": bool(unsigned & AxisStatusFlag.ARRIVED),
        "home_running": bool(unsigned & AxisStatusFlag.HOME_RUNNING),
        "home_success": bool(unsigned & AxisStatusFlag.HOME_SUCCESS),
        "home_switch": bool(unsigned & AxisStatusFlag.HOME_SWITCH),
        "positive_limit_active": bool(
            unsigned
            & (AxisStatusFlag.POSITIVE_SOFT_LIMIT | AxisStatusFlag.POSITIVE_HARD_LIMIT)
        ),
        "negative_limit_active": bool(
            unsigned
            & (AxisStatusFlag.NEGATIVE_SOFT_LIMIT | AxisStatusFlag.NEGATIVE_HARD_LIMIT)
        ),
    }


def axis_status_motion_errors(raw_status: int) -> list[str]:
    """返回开始新运动前必须阻塞的实时状态。"""

    decoded = decode_axis_status(raw_status)
    errors = list(decoded["safety_faults"])
    if decoded["running"]:
        errors.append("轴已经处于规划运动状态")
    if decoded["home_running"]:
        errors.append("轴正在回零")
    if decoded["unknown_bits_hex"] != "0x00000000":
        errors.append(f"轴状态包含手册未定义位 {decoded['unknown_bits_hex']}")
    return errors


@dataclass(frozen=True)
class StageCapabilities:
    """厂家 API 能力状态。

    每个字段采用三态值：``True`` 表示有可靠证据确认，``False`` 表示官方资料明确
    不支持，``None`` 表示未知。DLL 中能查到同名 symbol 不足以把字段改成 True。
    """

    position_read_supported: bool | None = None
    encoder_position_read_supported: bool | None = None
    status_read_supported: bool | None = None
    soft_limit_read_supported: bool | None = None
    motion_supported: bool | None = None
    stop_supported: bool | None = None
    home_supported: bool | None = None
    positive_limit_supported: bool | None = None
    negative_limit_supported: bool | None = None
    multi_axis_start_supported: bool | None = None
    # 原始状态可以读取，不代表 bit 含义已经知道。真实运动需要两者都确认。
    status_interpretation_supported: bool | None = None

    def require(self, field_name: str, operation_name: str) -> None:
        if getattr(self, field_name) is not True:
            value = getattr(self, field_name)
            state = "unknown" if value is None else "unsupported"
            raise UnsupportedStageOperation(
                f"{operation_name} 不可用：能力 {field_name} 当前为 {state}"
            )


# 连接/基础运动来自厂家 Python 示例；状态、Stop、限位、编码器位置和启动 mask 来自
# 《博派科技 ETH_GAS_N 运动控制卡用户手册 V7.3》。Home API 虽已记录，但当前机构的
# 回零模式、方向和现场流程尚未验收，因此仍保持 unknown。
CURRENT_GAS_CAPABILITIES = StageCapabilities(
    position_read_supported=True,
    encoder_position_read_supported=True,
    status_read_supported=True,
    motion_supported=True,
    stop_supported=True,
    positive_limit_supported=True,
    negative_limit_supported=True,
    multi_axis_start_supported=True,
    status_interpretation_supported=True,
    soft_limit_read_supported=True,
)


@dataclass(frozen=True)
class AxisCalibration:
    """物理坐标（mm）与控制器坐标（pulse）的明确映射。

    ``home_position_mm`` 表示“控制器 pulse=0 对应的物理 mm 坐标”。
    ``direction_sign`` 只能为 +1 或 -1，分别表示 pulse 增加时物理坐标增加或减少。
    soft limit 是可选的二次收窄范围；机械 travel 范围仍是进入运动模式的必填项。
    """

    axis_id: int | None = None
    pulses_per_mm: float | None = None
    travel_min_mm: float | None = None
    travel_max_mm: float | None = None
    direction_sign: int | None = None
    home_position_mm: float | None = None
    soft_limit_min_mm: float | None = None
    soft_limit_max_mm: float | None = None

    def __post_init__(self) -> None:
        if self.axis_id is not None and not 1 <= self.axis_id <= 8:
            raise ValueError("axis_id 必须在 1..8 范围内")
        if self.pulses_per_mm is not None:
            if not math.isfinite(self.pulses_per_mm) or self.pulses_per_mm <= 0:
                raise ValueError("pulses_per_mm 必须是有限正数")
        if self.direction_sign not in (None, -1, 1):
            raise ValueError("direction_sign 只能为 +1、-1 或 None")
        for name in (
            "travel_min_mm",
            "travel_max_mm",
            "home_position_mm",
            "soft_limit_min_mm",
            "soft_limit_max_mm",
        ):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} 必须是有限数值或 None")
        if (
            self.travel_min_mm is not None
            and self.travel_max_mm is not None
            and self.travel_min_mm >= self.travel_max_mm
        ):
            raise ValueError("travel_min_mm 必须小于 travel_max_mm")
        if (
            self.soft_limit_min_mm is not None
            and self.soft_limit_max_mm is not None
            and self.soft_limit_min_mm >= self.soft_limit_max_mm
        ):
            raise ValueError("soft_limit_min_mm 必须小于 soft_limit_max_mm")
        if (
            self.travel_min_mm is not None
            and self.soft_limit_min_mm is not None
            and self.soft_limit_min_mm < self.travel_min_mm
        ):
            raise ValueError("soft_limit_min_mm 不能低于机械 travel_min_mm")
        if (
            self.travel_max_mm is not None
            and self.soft_limit_max_mm is not None
            and self.soft_limit_max_mm > self.travel_max_mm
        ):
            raise ValueError("soft_limit_max_mm 不能高于机械 travel_max_mm")
        effective_min = self.effective_min_mm
        effective_max = self.effective_max_mm
        if (
            effective_min is not None
            and effective_max is not None
            and effective_min >= effective_max
        ):
            raise ValueError("机械行程与 soft limits 没有形成有效运动范围")

    def missing_for_motion(self) -> list[str]:
        required = (
            "axis_id",
            "pulses_per_mm",
            "travel_min_mm",
            "travel_max_mm",
            "direction_sign",
            "home_position_mm",
        )
        return [name for name in required if getattr(self, name) is None]

    @property
    def effective_min_mm(self) -> float | None:
        values = [
            value
            for value in (self.travel_min_mm, self.soft_limit_min_mm)
            if value is not None
        ]
        return max(values) if values else None

    @property
    def effective_max_mm(self) -> float | None:
        values = [
            value
            for value in (self.travel_max_mm, self.soft_limit_max_mm)
            if value is not None
        ]
        return min(values) if values else None

    def conversion_errors(self) -> list[str]:
        required = ("pulses_per_mm", "direction_sign", "home_position_mm")
        return [name for name in required if getattr(self, name) is None]

    def mm_to_pulse(self, position_mm: float) -> int:
        """把明确的物理 mm 坐标转换为控制器 pulse/count。"""
        missing = self.conversion_errors()
        if missing:
            raise StageSafetyError("mm→pulse 转换缺少标定项：" + ", ".join(missing))
        if not math.isfinite(position_mm):
            raise ValueError("position_mm 必须是有限数值")
        assert self.pulses_per_mm is not None
        assert self.direction_sign is not None
        assert self.home_position_mm is not None
        return round(
            (position_mm - self.home_position_mm)
            * self.pulses_per_mm
            * self.direction_sign
        )

    def pulse_to_mm(self, position_pulse: float) -> float:
        """把控制器 pulse/count 转换为物理 mm 坐标。"""
        missing = self.conversion_errors()
        if missing:
            raise StageSafetyError("pulse→mm 转换缺少标定项：" + ", ".join(missing))
        if not math.isfinite(position_pulse):
            raise ValueError("position_pulse 必须是有限数值")
        assert self.pulses_per_mm is not None
        assert self.direction_sign is not None
        assert self.home_position_mm is not None
        return self.home_position_mm + position_pulse / (
            self.pulses_per_mm * self.direction_sign
        )

    def target_errors(self, position_mm: float) -> list[str]:
        """返回目标位置违反机械/软件范围的全部原因。"""
        errors: list[str] = []
        minimum = self.effective_min_mm
        maximum = self.effective_max_mm
        if minimum is None or maximum is None:
            errors.append("机械行程范围尚未完整配置")
            return errors
        if position_mm < minimum:
            errors.append(f"目标 {position_mm} mm 低于允许下限 {minimum} mm")
        if position_mm > maximum:
            errors.append(f"目标 {position_mm} mm 高于允许上限 {maximum} mm")
        return errors
