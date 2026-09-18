"""扫描计划数据结构及浮点安全的 Range 模式。"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class CameraSettings:
    serial_number: str
    exposure_us: float
    gain: float | None = None

    def __post_init__(self) -> None:
        if not self.serial_number.strip():
            raise ValueError("相机序列号不能为空")
        if not math.isfinite(self.exposure_us) or self.exposure_us <= 0:
            raise ValueError("相机曝光时间必须是有限正数")


@dataclass
class ScanPlan:
    positions: list[float]
    cameras: list[CameraSettings]
    save_root: Path
    experiment_name: str = "scan"
    frames_per_position: int = 1
    repeats: int = 1
    settling_time_s: float = 0.1
    position_tolerance: float = 0.001
    motion_timeout_s: float = 30.0
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.save_root = Path(self.save_root)
        self.positions = [float(value) for value in self.positions]
        if not self.positions:
            raise ValueError("扫描位置不能为空")
        if not all(math.isfinite(value) for value in self.positions):
            raise ValueError("所有扫描位置都必须是有限数值")
        if not self.cameras:
            raise ValueError("至少要选择一台相机")
        serials = [camera.serial_number for camera in self.cameras]
        if len(serials) != len(set(serials)):
            raise ValueError("相机序列号不能重复")
        if self.frames_per_position < 1 or self.repeats < 1:
            raise ValueError("frames_per_position 和 repeats 必须至少为 1")
        if self.settling_time_s < 0 or self.position_tolerance < 0:
            raise ValueError("settling_time_s 和 position_tolerance 不能为负数")
        if self.motion_timeout_s <= 0:
            raise ValueError("motion_timeout_s 必须大于 0")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.experiment_name):
            raise ValueError("experiment_name 只能包含字母、数字、下划线和连字符")

    @property
    def total_images(self) -> int:
        return (
            len(self.positions)
            * len(self.cameras)
            * self.frames_per_position
            * self.repeats
        )

    @classmethod
    def from_range(
        cls,
        *,
        start: float | str,
        stop: float | str,
        step: float | str,
        **kwargs: object,
    ) -> "ScanPlan":
        """用 Decimal 生成包含 stop 的位置，避免 0.30000000004 一类误差。"""
        start_d = Decimal(str(start))
        stop_d = Decimal(str(stop))
        step_d = Decimal(str(step))
        if step_d == 0:
            raise ValueError("step 不能为 0")
        if (stop_d - start_d) * step_d < 0:
            raise ValueError("step 的符号必须能从 start 走向 stop")

        positions: list[float] = []
        value = start_d
        if step_d > 0:
            while value <= stop_d:
                positions.append(float(value))
                value += step_d
        else:
            while value >= stop_d:
                positions.append(float(value))
                value += step_d
        return cls(positions=positions, **kwargs)

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["save_root"] = str(self.save_root)
        result["total_images"] = self.total_images
        return result

