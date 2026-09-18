import csv
import json

import tifffile

from mock.mock_camera import MockCamera
from mock.mock_stage import MockStage
from scan.scan_controller import ScanController
from scan.scan_plan import CameraSettings, ScanPlan
from scan.scan_state import ScanState


def test_mock_scan_writes_images_config_and_log(tmp_path) -> None:
    stage = MockStage(speed_units_per_s=1000.0)
    stage.connect()
    cameras = [
        MockCamera(serial_number="MOCK-A", shape=(32, 40), seed=1),
        MockCamera(serial_number="MOCK-B", shape=(32, 40), seed=2),
    ]
    for camera in cameras:
        camera.connect()
    plan = ScanPlan(
        positions=[0.0, 0.1],
        cameras=[
            CameraSettings("MOCK-A", 500.0),
            CameraSettings("MOCK-B", 1000.0),
        ],
        frames_per_position=2,
        repeats=1,
        save_root=tmp_path,
        experiment_name="test_scan",
        settling_time_s=0.0,
        position_tolerance=1e-6,
        motion_timeout_s=1.0,
    )
    controller = ScanController(
        stage, {camera.get_serial_number(): camera for camera in cameras}
    )
    result = controller.run(plan)

    assert result is not None
    assert controller.state is ScanState.COMPLETED
    images = sorted(result.glob("Camera_*/*.tif"))
    assert len(images) == plan.total_images == 8
    assert tifffile.imread(images[0]).dtype.name == "uint16"
    config = json.loads((result / "scan_config.json").read_text(encoding="utf-8"))
    assert config["total_images"] == 8
    with (result / "scan_log.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 8
    assert {row["status"] for row in rows} == {"ok"}
    assert len({row["filename"] for row in rows}) == 8


def test_preflight_rejects_missing_camera(tmp_path) -> None:
    stage = MockStage()
    stage.connect()
    plan = ScanPlan(
        positions=[0],
        cameras=[CameraSettings("ABSENT", 1000)],
        save_root=tmp_path,
    )
    controller = ScanController(stage, {})
    assert "未注册相机：ABSENT" in controller.preflight(plan)

