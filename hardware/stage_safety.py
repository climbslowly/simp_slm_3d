"""真实位移台的能力声明、轴标定和单位转换。

这个模块只保存“已经知道什么”，不访问 DLL，也不控制硬件。未知信息必须保留为
``None``；不能为了让程序通过检查而填写推测值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class StageSafetyError(RuntimeError):
    """真实运动未通过安全门时抛出的异常。"""


class UnsupportedStageOperation(NotImplementedError):
    """厂家资料尚未确认某项能力时抛出的异常。"""


@dataclass(frozen=True)
class StageCapabilities:
    """厂家 API 能力状态。

    每个字段采用三态值：``True`` 表示有可靠证据确认，``False`` 表示官方资料明确
    不支持，``None`` 表示未知。DLL 中能查到同名 symbol 不足以把字段改成 True。
    """

    position_read_supported: bool | None = None
    status_read_supported: bool | None = None
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


# 这些 True 只来自项目中现有厂家 Python 示例。状态位解释、Stop、Home、限位和
# 多轴启动均没有证据，因此保持 None。
CURRENT_GAS_CAPABILITIES = StageCapabilities(
    position_read_supported=True,
    status_read_supported=True,
    motion_supported=True,
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
