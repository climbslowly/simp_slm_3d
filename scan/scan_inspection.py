"""ScanPlan 的纯数据 dry-run；不会导入或访问任何硬件 API。"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import reduce
from operator import mul

import numpy as np

from hardware.stage_safety import AxisCalibration
from scan.scan_plan import ScanPlan


@dataclass(frozen=True)
class ScanInspection:
    number_of_scan_points: int
    first_position_mm: float
    last_position_mm: float
    minimum_position_mm: float
    maximum_position_mm: float
    uniform_step_mm: float | None
    step_values_mm: list[float]
    duplicate_positions_mm: list[float]
    estimated_number_of_images: int
    estimated_storage_bytes: int | None
    image_shape: tuple[int, ...] | None
    image_dtype: str | None
    axis_range_check: str
    axis_range_errors: list[str]
    real_motion_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _decimal_steps(positions: list[float]) -> list[Decimal]:
    return [
        Decimal(str(right)) - Decimal(str(left))
        for left, right in zip(positions, positions[1:])
    ]


def inspect_scan_plan(
    plan: ScanPlan,
    *,
    calibration: AxisCalibration | None = None,
    real_motion_enabled: bool = False,
    image_shape: tuple[int, ...] | None = None,
    image_dtype: str | np.dtype[object] | None = None,
) -> ScanInspection:
    """检查扫描规模、位置序列、范围和原始图像体积，不创建目录或连接设备。"""
    positions = plan.positions
    counts = Counter(Decimal(str(position)) for position in positions)
    duplicates = sorted(float(value) for value, count in counts.items() if count > 1)
    decimal_steps = _decimal_steps(positions)
    unique_steps = sorted(set(decimal_steps))
    uniform_step = float(unique_steps[0]) if len(unique_steps) == 1 else None

    storage_bytes: int | None = None
    dtype_name: str | None = None
    if image_shape is not None or image_dtype is not None:
        if image_shape is None or image_dtype is None:
            raise ValueError("估算存储空间时 image_shape 和 image_dtype 必须同时提供")
        if not image_shape or any(size <= 0 for size in image_shape):
            raise ValueError("image_shape 必须由正整数构成")
        dtype = np.dtype(image_dtype)
        dtype_name = dtype.name
        pixels_per_image = reduce(mul, image_shape, 1)
        storage_bytes = plan.total_images * pixels_per_image * dtype.itemsize

    if calibration is None:
        range_status = "not_configured"
        range_errors = ["未提供 AxisCalibration，无法检查物理行程"]
    elif calibration.effective_min_mm is None or calibration.effective_max_mm is None:
        range_status = "unknown"
        range_errors = ["AxisCalibration 的 travel/soft limit 范围不完整"]
    else:
        range_errors = []
        for position in positions:
            range_errors.extend(calibration.target_errors(position))
        # 多个扫描点可能产生重复错误，报告时去重但保留顺序。
        range_errors = list(dict.fromkeys(range_errors))
        range_status = "within_range" if not range_errors else "out_of_range"

    return ScanInspection(
        number_of_scan_points=len(positions),
        first_position_mm=positions[0],
        last_position_mm=positions[-1],
        minimum_position_mm=min(positions),
        maximum_position_mm=max(positions),
        uniform_step_mm=uniform_step,
        step_values_mm=[float(value) for value in unique_steps],
        duplicate_positions_mm=duplicates,
        estimated_number_of_images=plan.total_images,
        estimated_storage_bytes=storage_bytes,
        image_shape=image_shape,
        image_dtype=dtype_name,
        axis_range_check=range_status,
        axis_range_errors=range_errors,
        real_motion_enabled=real_motion_enabled,
    )

