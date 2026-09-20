import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from PySide6 import QtTest

from gui.configuration import DEFAULT_CONFIG, load_config
from gui.main_window import MainWindow
from mock.mock_camera import MockCamera
from mock.mock_xyz_stage import MockXYZStage
from scan.spatial_controller import SpatialScanController
from scan.spatial_scan import SpatialScanPlan


def test_gui_constructs_mock_only_without_hardware(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        assert "MOCK" in window.windowTitle()
        assert window.stage.is_connected and window.camera.is_connected
        before = window.stage.move_command_count
        window._plan = window._plan_from_controls()
        window._records[1] = {"point_id": 1}
        # 主图浏览逻辑本身不能提交运动。
        assert window.stage.move_command_count == before
    finally:
        window.close(); app.processEvents()


def test_close_running_scan_waits_for_worker(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    window.output_edit.setText(str(tmp_path / "scan"))
    window.camera._capture_delay_s = 0.2
    window.start_scan()
    QtTest.QTest.qWait(60)
    assert window._thread is not None
    assert window.close()
    app.processEvents()
    assert window.controller.state.name in {"STOPPED", "COMPLETED"}


def test_corrupt_configuration_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "configuration.json"
    path.write_text("{broken", encoding="utf-8")
    config, error = load_config(path)
    assert config["device_mode"] == DEFAULT_CONFIG["device_mode"] == "MOCK"
    assert error and path.read_text(encoding="utf-8") == "{broken"


def test_gui_reopens_saved_raw_image(tmp_path: Path) -> None:
    stage = MockXYZStage(speed_mm_s=1000); stage.connect()
    camera = MockCamera(shape=(32, 40), position_provider=stage.get_positions); camera.connect()
    plan = SpatialScanPlan.from_plane(
        plane="XY", horizontal_start=0, horizontal_stop=0, horizontal_step=1,
        vertical_start=0, vertical_stop=0, vertical_step=1, fixed_value_mm=0,
        save_root=tmp_path / "data", roi_xywh=(1, 1, 10, 10), settling_time_s=0,
    )
    directory = SpatialScanController(stage, camera).run(plan)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        window.open_session(directory)
        assert window.raw_item.image is not None
        assert window._selected_point_id == 1
    finally:
        window.close(); app.processEvents()
