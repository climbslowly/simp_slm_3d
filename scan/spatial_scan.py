"""GUI-M1 的空间扫描计划；仅描述数据，不访问设备。"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


AXES = ("X", "Y", "Z")
PLANE_AXES = {"XY": ("X", "Y"), "XZ": ("X", "Z"), "YZ": ("Y", "Z")}
MAX_GUI_POINTS = 100_000


def decimal_range(start: float | str, stop: float | str, step: float | str) -> list[float]:
    """生成不偷偷调整步长、仅在恰好可达时包含终点的十进制序列。"""
    try:
        start_d, stop_d, step_d = map(lambda value: Decimal(str(value)), (start, stop, step))
    except InvalidOperation as exc:
        raise ValueError("起点、终点和步长必须是有限数值") from exc
    if not all(value.is_finite() for value in (start_d, stop_d, step_d)):
        raise ValueError("起点、终点和步长必须是有限数值")
    if step_d == 0:
        raise ValueError("step 不能为 0")
    if (stop_d - start_d) * step_d < 0:
        raise ValueError("step 的符号必须能从 start 走向 stop")
    values: list[float] = []
    value = start_d
    compare = (lambda current: current <= stop_d) if step_d > 0 else (lambda current: current >= stop_d)
    while compare(value):
        values.append(float(value))
        if len(values) > MAX_GUI_POINTS:
            raise ValueError(f"单轴点数超过 GUI-M1 上限 {MAX_GUI_POINTS}")
        value += step_d
    return values


@dataclass(frozen=True)
class SpatialPoint:
    point_id: int
    order_index: int
    row: int | None
    col: int | None
    targets_mm: dict[str, float]


@dataclass
class SpatialScanPlan:
    scan_type: str
    points: list[SpatialPoint]
    save_root: Path
    exposure_us: float = 1000.0
    settling_time_s: float = 0.02
    motion_timeout_s: float = 5.0
    roi_xywh: tuple[int, int, int, int] = (80, 64, 160, 128)
    metric: str = "mean"
    experiment_name: str = "gui_mock"
    camera_serial: str = "MOCK-GUI-001"
    horizontal_axis: str | None = None
    vertical_axis: str | None = None
    horizontal_values: list[float] = field(default_factory=list)
    vertical_values: list[float] = field(default_factory=list)
    fixed_axis: str | None = None
    fixed_value_mm: float | None = None

    def __post_init__(self) -> None:
        self.save_root = Path(self.save_root)
        if not self.points:
            raise ValueError("扫描计划不能为空")
        if len(self.points) > MAX_GUI_POINTS:
            raise ValueError(f"扫描点数超过 GUI-M1 上限 {MAX_GUI_POINTS}")
        if not math.isfinite(self.exposure_us) or self.exposure_us <= 0:
            raise ValueError("曝光时间必须是有限正数")
        if not math.isfinite(self.settling_time_s) or self.settling_time_s < 0:
            raise ValueError("稳定等待时间必须是有限非负数")
        if not math.isfinite(self.motion_timeout_s) or self.motion_timeout_s <= 0:
            raise ValueError("运动超时必须是有限正数")
        if self.metric not in {"mean", "sum"}:
            raise ValueError("指标只能是 mean 或 sum")
        x, y, width, height = self.roi_xywh
        if min(x, y) < 0 or min(width, height) <= 0:
            raise ValueError("ROI 必须位于非负像素坐标且宽高为正")
        expected_ids = list(range(1, len(self.points) + 1))
        if [point.point_id for point in self.points] != expected_ids:
            raise ValueError("point_id 必须从 1 连续递增")
        for point in self.points:
            if set(point.targets_mm) != set(AXES):
                raise ValueError("每个空间点必须包含 X/Y/Z 三个目标")
            if not all(math.isfinite(value) for value in point.targets_mm.values()):
                raise ValueError("空间目标必须是有限数值")

    @property
    def total_points(self) -> int:
        return len(self.points)

    @property
    def is_plane(self) -> bool:
        return self.horizontal_axis is not None and self.vertical_axis is not None

    @property
    def grid_shape(self) -> tuple[int, int] | None:
        if not self.is_plane:
            return None
        return (len(self.vertical_values), len(self.horizontal_values))

    @classmethod
    def from_plane(
        cls,
        *,
        plane: str,
        horizontal_start: float | str,
        horizontal_stop: float | str,
        horizontal_step: float | str,
        vertical_start: float | str,
        vertical_stop: float | str,
        vertical_step: float | str,
        fixed_value_mm: float,
        **kwargs: object,
    ) -> "SpatialScanPlan":
        plane = plane.upper()
        if plane not in PLANE_AXES:
            raise ValueError("平面必须是 XY、XZ 或 YZ")
        horizontal_axis, vertical_axis = PLANE_AXES[plane]
        fixed_axis = next(axis for axis in AXES if axis not in {horizontal_axis, vertical_axis})
        horizontal = decimal_range(horizontal_start, horizontal_stop, horizontal_step)
        vertical = decimal_range(vertical_start, vertical_stop, vertical_step)
        if len(horizontal) * len(vertical) > MAX_GUI_POINTS:
            raise ValueError(f"扫描点数超过 GUI-M1 上限 {MAX_GUI_POINTS}")
        points: list[SpatialPoint] = []
        for row, vertical_value in enumerate(vertical):
            for col, horizontal_value in enumerate(horizontal):
                targets = {axis: float(fixed_value_mm) for axis in AXES}
                targets[horizontal_axis] = horizontal_value
                targets[vertical_axis] = vertical_value
                points.append(
                    SpatialPoint(
                        point_id=len(points) + 1,
                        order_index=len(points),
                        row=row,
                        col=col,
                        targets_mm=targets,
                    )
                )
        return cls(
            scan_type=plane,
            points=points,
            horizontal_axis=horizontal_axis,
            vertical_axis=vertical_axis,
            horizontal_values=horizontal,
            vertical_values=vertical,
            fixed_axis=fixed_axis,
            fixed_value_mm=float(fixed_value_mm),
            **kwargs,
        )

    @classmethod
    def from_axis_range(
        cls,
        *,
        axis: str,
        start: float | str,
        stop: float | str,
        step: float | str,
        fixed_positions_mm: dict[str, float],
        **kwargs: object,
    ) -> "SpatialScanPlan":
        return cls.from_axis_list(
            axis=axis,
            values=decimal_range(start, stop, step),
            fixed_positions_mm=fixed_positions_mm,
            scan_type="AXIS_RANGE",
            **kwargs,
        )

    @classmethod
    def from_axis_list(
        cls,
        *,
        axis: str,
        values: list[float],
        fixed_positions_mm: dict[str, float],
        scan_type: str = "AXIS_LIST",
        **kwargs: object,
    ) -> "SpatialScanPlan":
        axis = axis.upper()
        if axis not in AXES:
            raise ValueError("单轴必须是 X、Y 或 Z")
        if not values or not all(math.isfinite(float(value)) for value in values):
            raise ValueError("单轴位置列表必须包含有限数值")
        points: list[SpatialPoint] = []
        for index, value in enumerate(values):
            targets = {name: float(fixed_positions_mm.get(name, 0.0)) for name in AXES}
            targets[axis] = float(value)
            points.append(SpatialPoint(index + 1, index, None, index, targets))
        return cls(
            scan_type=scan_type,
            points=points,
            horizontal_axis=axis,
            horizontal_values=[float(value) for value in values],
            **kwargs,
        )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["save_root"] = str(self.save_root)
        result["roi_xywh"] = list(self.roi_xywh)
        result["total_points"] = self.total_points
        result["grid_shape"] = list(self.grid_shape) if self.grid_shape else None
        return result
