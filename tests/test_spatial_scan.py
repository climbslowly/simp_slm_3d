import math
from pathlib import Path

import pytest

from scan.spatial_scan import SpatialScanPlan, decimal_range


def common(tmp_path: Path) -> dict[str, object]:
    return {"save_root": tmp_path, "roi_xywh": (0, 0, 8, 8)}


def test_non_symmetric_grid_mapping_and_centers(tmp_path) -> None:
    plan = SpatialScanPlan.from_plane(
        plane="XY", horizontal_start="-0.4", horizontal_stop="0.4", horizontal_step="0.2",
        vertical_start="-0.2", vertical_stop="0.2", vertical_step="0.2", fixed_value_mm=1.25,
        **common(tmp_path),
    )
    assert plan.grid_shape == (3, 5)
    assert plan.total_points == 15
    assert plan.points[7].row == 1 and plan.points[7].col == 2
    assert plan.points[7].targets_mm == {"X": 0.0, "Y": 0.0, "Z": 1.25}


@pytest.mark.parametrize(
    ("plane", "horizontal", "vertical", "fixed"),
    [("XY", "X", "Y", "Z"), ("XZ", "X", "Z", "Y"), ("YZ", "Y", "Z", "X")],
)
def test_plane_axis_mapping(tmp_path, plane, horizontal, vertical, fixed) -> None:
    plan = SpatialScanPlan.from_plane(
        plane=plane, horizontal_start=1, horizontal_stop=2, horizontal_step=1,
        vertical_start=3, vertical_stop=4, vertical_step=1, fixed_value_mm=9, **common(tmp_path),
    )
    assert (plan.horizontal_axis, plan.vertical_axis, plan.fixed_axis) == (horizontal, vertical, fixed)
    assert plan.points[-1].targets_mm == {horizontal: 2.0, vertical: 4.0, fixed: 9.0}


def test_relative_serpentine_plane_uses_scan_start_as_origin(tmp_path) -> None:
    origin = {"X": 3.6806, "Y": -3.2516, "Z": 1.6478}
    plan = SpatialScanPlan.from_plane(
        plane="XY",
        horizontal_start=-0.1,
        horizontal_stop=0.1,
        horizontal_step=0.05,
        vertical_start=-0.1,
        vertical_stop=0.1,
        vertical_step=0.05,
        fixed_value_mm=0.0,
        relative_origin_mm=origin,
        serpentine=True,
        **common(tmp_path),
    )
    assert plan.coordinate_mode == "RELATIVE_TO_SCAN_START"
    assert plan.origin_positions_mm == origin
    assert plan.points[0].targets_mm == pytest.approx(
        {"X": 3.5806, "Y": -3.3516, "Z": 1.6478}
    )
    # 奇数行反向，避免从 +0.1 跳回 -0.1。
    assert [(point.row, point.col) for point in plan.points[5:10]] == [
        (1, 4), (1, 3), (1, 2), (1, 1), (1, 0)
    ]
    for previous, current in zip(plan.points, plan.points[1:]):
        assert max(
            abs(current.targets_mm[axis] - previous.targets_mm[axis])
            for axis in ("X", "Y", "Z")
        ) <= 0.05 + 1e-12


def test_range_endpoint_rule_and_invalid_values() -> None:
    assert decimal_range(0, 1, 0.3) == [0.0, 0.3, 0.6, 0.9]
    assert decimal_range(1, 0, -0.5) == [1.0, 0.5, 0.0]
    with pytest.raises(ValueError, match="step 不能"):
        decimal_range(0, 1, 0)
    with pytest.raises(ValueError, match="有限"):
        decimal_range(0, math.inf, 1)
    with pytest.raises(ValueError, match="符号"):
        decimal_range(0, 1, -1)


def test_single_axis_list_preserves_nonuniform_order(tmp_path) -> None:
    plan = SpatialScanPlan.from_axis_list(
        axis="Z", values=[0.0, 0.1, 0.35, -0.2], fixed_positions_mm={"X": 1, "Y": 2}, **common(tmp_path)
    )
    assert plan.scan_type == "AXIS_LIST"
    assert plan.horizontal_values == [0.0, 0.1, 0.35, -0.2]
    assert [point.targets_mm["Z"] for point in plan.points] == plan.horizontal_values


def test_configured_boundary_reports_every_out_of_range_axis(tmp_path) -> None:
    plan = SpatialScanPlan.from_plane(
        plane="XY", horizontal_start=-0.4, horizontal_stop=0.4, horizontal_step=0.4,
        vertical_start=-0.2, vertical_stop=0.2, vertical_step=0.2, fixed_value_mm=0.3,
        objective_bounds_mm={"X": [-0.3, 0.3], "Y": [-0.1, 0.1], "Z": [-0.2, 0.2]},
        **common(tmp_path),
    )
    errors = plan.boundary_errors()
    assert len(errors) == 3
    assert any("物镜 X" in error and "[-0.4, 0.4]" in error for error in errors)
    assert any("物镜 Y" in error for error in errors)
    assert any("物镜 Z" in error for error in errors)


def test_boundary_does_not_clamp_requested_points(tmp_path) -> None:
    plan = SpatialScanPlan.from_axis_list(
        axis="X", values=[-0.4, 0.0, 0.4], fixed_positions_mm={"Y": 0, "Z": 0},
        objective_bounds_mm={"X": [-0.3, 0.3], "Y": [-1, 1], "Z": [-1, 1]},
        **common(tmp_path),
    )
    assert [point.targets_mm["X"] for point in plan.points] == [-0.4, 0.0, 0.4]
    assert plan.boundary_errors()
