import csv
import json
import threading
import time

import numpy as np
import tifffile
from scipy.io import loadmat

from data.spatial_session import SpatialSession, roi_metrics
from mock.mock_camera import MockCamera
from mock.mock_xyz_stage import MockXYZStage
from scan.scan_state import ScanState
from scan.spatial_controller import SpatialCallbacks, SpatialScanController
from scan.spatial_scan import SpatialScanPlan


def make_devices(*, speed=1000.0, capture_delay=0.0):
    stage = MockXYZStage(speed_mm_s=speed); stage.connect()
    camera = MockCamera(shape=(32, 40), seed=7, position_provider=stage.get_signal_positions, capture_delay_s=capture_delay); camera.connect()
    return stage, camera


def make_plan(tmp_path, *, settling=0.0):
    return SpatialScanPlan.from_plane(
        plane="XY", horizontal_start=-0.4, horizontal_stop=0.4, horizontal_step=0.2,
        vertical_start=-0.2, vertical_stop=0.2, vertical_step=0.2, fixed_value_mm=0,
        save_root=tmp_path, settling_time_s=settling, roi_xywh=(5, 4, 20, 16), motion_timeout_s=2,
    )


def test_complete_5_by_3_scan_save_reload_and_metric(tmp_path) -> None:
    stage, camera = make_devices()
    records = []
    controller = SpatialScanController(stage, camera, SpatialCallbacks(on_point_saved=lambda record, image: records.append(record)))
    session_dir = controller.run(make_plan(tmp_path))
    assert controller.state is ScanState.COMPLETED
    assert session_dir is not None
    assert len(list(session_dir.glob("Camera_*/*.tif"))) == 15
    assert (session_dir / "scan_data.mat").is_file()
    with (session_dir / "scan_log.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 15 and {row["status"] for row in rows} == {"ok"}
    assert [(int(row["row"]), int(row["col"])) for row in rows] == [(r, c) for r in range(3) for c in range(5)]
    session = SpatialSession.open(session_dir)
    image = session.load_image(8)
    recomputed = roi_metrics(image, (5, 4, 20, 16), "mean")
    assert np.isclose(recomputed["metric_value"], float(session.successful_records[7]["metric_value"]))
    config = json.loads((session_dir / "scan_config.json").read_text(encoding="utf-8"))
    assert config["device_mode"] == "MOCK" and config["stage"]["real_motion_enabled"] is False
    assert config["stage"]["axis_mapping"]["objective"]["Y"]["controller_axis"] == 5
    assert config["stage"]["direction_sign_verified"] is True
    assert config["stage"]["axis_mapping"]["camera"]["Y"]["controller_sign_for_gui_positive"] == -1
    assert {row["camera_x_mm"] for row in rows} == {"0.0"}
    assert {row["camera_y_mm"] for row in rows} == {"0.0"}
    assert {row["axis_mapping_id"] for row in rows} == {"five_axis_operator_observed_v1"}
    matlab = loadmat(session_dir / "scan_data.mat", squeeze_me=True)
    assert int(matlab["mat_export_version"]) == 2
    assert matlab["scan_id"] == config["scan_id"]
    assert matlab["target_xyz_mm"].shape == (15, 3)
    assert matlab["actual_xyz_mm"].shape == (15, 3)
    assert matlab["camera_xy_mm"].shape == (15, 2)
    assert np.allclose(matlab["camera_xy_mm"], 0.0)
    assert matlab["axis_mapping_id"] == "five_axis_operator_observed_v1"
    assert np.array_equal(matlab["objective_controller_axis_order"], [3, 5, 4])
    assert np.array_equal(matlab["objective_controller_sign_for_gui_positive"], [1, -1, 1])
    assert np.array_equal(matlab["camera_controller_axis_order"], [1, 2])
    assert np.array_equal(matlab["camera_controller_sign_for_gui_positive"], [1, -1])
    assert matlab["objective_z_positive_optical_direction"] == "against_propagation"
    assert matlab["metric_value"].shape == (15,)
    assert matlab["metric_grid"].shape == (3, 5)
    assert np.isclose(matlab["metric_grid"][1, 2], float(rows[7]["metric_value"]))
    assert int(matlab["successful_point_count"]) == 15
    assert int(matlab["missing_success_image_count"]) == 0
    assert np.all(matlab["image_file_exists"] == 1)
    assert int(matlab["raw_images_embedded"]) == 0


def _stop_in_state(tmp_path, wanted: ScanState, *, speed=1000.0, settling=0.0, capture_delay=0.0):
    stage, camera = make_devices(speed=speed, capture_delay=capture_delay)
    seen = threading.Event()
    result: dict[str, object] = {}
    controller = SpatialScanController(stage, camera, SpatialCallbacks(on_state=lambda state: seen.set() if state is wanted else None))
    plan = make_plan(tmp_path, settling=settling)
    thread = threading.Thread(target=lambda: result.setdefault("directory", controller.run(plan)))
    thread.start(); assert seen.wait(2); controller.request_stop(); thread.join(2)
    assert not thread.is_alive() and controller.state is ScanState.STOPPED
    directory = result["directory"]
    assert (directory / "scan_data.mat").is_file()
    matlab = loadmat(directory / "scan_data.mat", squeeze_me=True)
    assert int(matlab["successful_point_count"]) < plan.total_points
    return stage.move_command_count


def test_stop_interrupts_move_settle_and_capture(tmp_path) -> None:
    assert _stop_in_state(tmp_path / "move", ScanState.WAITING_FOR_POSITION, speed=0.05) == 1
    assert _stop_in_state(tmp_path / "settle", ScanState.SETTLING, settling=1.0) == 1
    assert _stop_in_state(tmp_path / "capture", ScanState.ACQUIRING, capture_delay=1.0) == 1


def test_pause_resume_and_pause_then_stop(tmp_path) -> None:
    stage, camera = make_devices(capture_delay=0.02)
    first = threading.Event()
    controller = SpatialScanController(stage, camera, SpatialCallbacks(on_progress=lambda done, total: first.set() if done == 1 else None))
    thread = threading.Thread(target=lambda: controller.run(make_plan(tmp_path)))
    thread.start(); assert first.wait(2); controller.request_pause()
    deadline = time.monotonic() + 2
    while controller.state is not ScanState.PAUSED and time.monotonic() < deadline: time.sleep(0.01)
    assert controller.state is ScanState.PAUSED
    moves = stage.move_command_count; time.sleep(0.08); assert stage.move_command_count == moves
    controller.resume(); time.sleep(0.05); controller.request_pause()
    deadline = time.monotonic() + 2
    while controller.state is not ScanState.PAUSED and time.monotonic() < deadline: time.sleep(0.01)
    controller.request_stop(); thread.join(2)
    assert controller.state is ScanState.STOPPED and not thread.is_alive()


def test_zero_signal_is_distinct_from_unacquired() -> None:
    image = np.zeros((4, 5), dtype=np.uint16)
    assert roi_metrics(image, (0, 0, 5, 4), "mean")["metric_value"] == 0.0
    grid = np.full((2, 2), np.nan); grid[0, 0] = 0.0
    assert grid[0, 0] == 0 and np.isnan(grid[0, 1])
