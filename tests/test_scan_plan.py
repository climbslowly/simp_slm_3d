from pathlib import Path

import pytest

from scan.scan_plan import CameraSettings, ScanPlan


def settings() -> dict[str, object]:
    return {
        "cameras": [CameraSettings("MOCK-1", 1000.0)],
        "save_root": Path("output"),
    }


def test_range_is_decimal_safe_and_includes_stop() -> None:
    plan = ScanPlan.from_range(start=0, stop=0.3, step=0.1, **settings())
    assert plan.positions == [0.0, 0.1, 0.2, 0.3]


def test_descending_range() -> None:
    plan = ScanPlan.from_range(start=0.3, stop=0, step=-0.1, **settings())
    assert plan.positions == [0.3, 0.2, 0.1, 0.0]


def test_range_rejects_wrong_direction() -> None:
    with pytest.raises(ValueError, match="符号"):
        ScanPlan.from_range(start=0, stop=1, step=-0.1, **settings())


def test_total_images_keeps_dimensions_separate() -> None:
    plan = ScanPlan(
        positions=[0, 1, 2],
        cameras=[CameraSettings("A", 100), CameraSettings("B", 200)],
        frames_per_position=2,
        repeats=3,
        save_root=Path("output"),
    )
    assert plan.total_images == 3 * 2 * 2 * 3

