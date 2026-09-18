from pathlib import Path

from hardware.stage_safety import AxisCalibration
from scan.scan_inspection import inspect_scan_plan
from scan.scan_plan import CameraSettings, ScanPlan


def test_dry_run_reports_positions_duplicates_images_and_storage() -> None:
    plan = ScanPlan(
        positions=[0.0, 0.1, 0.2, 0.2],
        cameras=[CameraSettings("A", 100), CameraSettings("B", 200)],
        frames_per_position=2,
        repeats=3,
        save_root=Path("unused"),
    )
    report = inspect_scan_plan(
        plan,
        calibration=AxisCalibration(travel_min_mm=-1.0, travel_max_mm=1.0),
        image_shape=(10, 20),
        image_dtype="uint16",
    )
    assert report.number_of_scan_points == 4
    assert report.first_position_mm == 0.0
    assert report.last_position_mm == 0.2
    assert report.minimum_position_mm == 0.0
    assert report.maximum_position_mm == 0.2
    assert report.step_values_mm == [0.0, 0.1]
    assert report.uniform_step_mm is None
    assert report.duplicate_positions_mm == [0.2]
    assert report.estimated_number_of_images == 4 * 2 * 2 * 3
    assert report.estimated_storage_bytes == 48 * 10 * 20 * 2
    assert report.axis_range_check == "within_range"
    assert report.real_motion_enabled is False


def test_dry_run_range_violation_is_reported_without_hardware() -> None:
    plan = ScanPlan(
        positions=[-0.1, 0.0, 1.1],
        cameras=[CameraSettings("A", 100)],
        save_root=Path("unused"),
    )
    report = inspect_scan_plan(
        plan,
        calibration=AxisCalibration(travel_min_mm=0.0, travel_max_mm=1.0),
    )
    assert report.axis_range_check == "out_of_range"
    assert len(report.axis_range_errors) == 2

