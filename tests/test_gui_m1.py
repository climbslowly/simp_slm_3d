import json
import os
import time
import warnings
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6 import QtCore, QtWidgets

from PySide6 import QtTest
import pytest

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
        assert set(window.camera_position_labels) == {"X", "Y"}
        label_texts = [label.text() for label in window.findChildren(QtWidgets.QLabel)]
        assert any("轴3+" in text and "物理+Y" in text for text in label_texts)
        assert any("轴1+" in text and "物理+Y" in text for text in label_texts)
        assert any("轴5-" in text and "物理+Z" in text for text in label_texts)
        assert any("轴4+" in text and "逆光" in text for text in label_texts)
        assert window.camera_move_button.text().startswith("相机移动")
        window._set_raw_colormap("gray")
        assert window.raw_item.getColorMap().name == "gray"
        before = window.stage.move_command_count
        window._plan = window._plan_from_controls()
        window._records[1] = {"point_id": 1}
        # 主图浏览逻辑本身不能提交运动。
        assert window.stage.move_command_count == before
        window.stage.move_absolute({"X": 0.125, "Y": -0.25, "Z": 0.375})
        while window.stage.is_moving():
            time.sleep(0.001)
        QtTest.QTest.qWait(300)
        assert window.position_labels["X"].text() == "0.1250 mm"
        assert window.position_labels["Y"].text() == "-0.2500 mm"
        assert window.position_labels["Z"].text() == "0.3750 mm"
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


def test_boundary_configuration_is_validated_and_preserved(tmp_path: Path) -> None:
    path = tmp_path / "configuration.json"
    payload = dict(DEFAULT_CONFIG)
    payload["objective_scan_bounds_mm"] = {"X": [-1, 1], "Y": [-2, 2], "Z": [-3, 3]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    config, error = load_config(path)
    assert error is None
    assert config["objective_scan_bounds_mm"]["Z"] == [-3.0, 3.0]


def test_plane_scan_path_configuration_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "configuration.json"
    payload = dict(DEFAULT_CONFIG)
    payload["plane_scan_path"] = "Z_SHAPED"
    path.write_text(json.dumps(payload), encoding="utf-8")
    config, error = load_config(path)
    assert error is None
    assert config["plane_scan_path"] == "Z_SHAPED"

    payload["plane_scan_path"] = "DIAGONAL"
    path.write_text(json.dumps(payload), encoding="utf-8")
    config, error = load_config(path)
    assert error and config["plane_scan_path"] == "SERPENTINE"


def test_gui_disables_start_when_plan_exceeds_configured_boundary(tmp_path: Path) -> None:
    path = tmp_path / "configuration.json"
    payload = dict(DEFAULT_CONFIG)
    payload["objective_scan_bounds_mm"] = {"X": [-0.1, 0.1], "Y": [-0.1, 0.1], "Z": [-0.1, 0.1]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=path)
    try:
        window._refresh_estimate()
        assert not window.start_button.isEnabled()
        assert "安全边界阻止扫描" in window.plan_summary.text()
        assert "物镜 X" in window.plan_summary.text()
    finally:
        window.close(); app.processEvents()


def test_gui_accepts_explicit_real_device_injection(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    stage = MockXYZStage(speed_mm_s=1000.0)
    camera = MockCamera(shape=(32, 40))
    window = MainWindow(
        config_path=tmp_path / "configuration.json",
        stage=stage,
        camera=camera,
        device_mode="REAL",
    )
    try:
        assert "REAL" in window.windowTitle()
        assert stage.is_connected and camera.is_connected
        assert window._plan_from_controls().experiment_name == "gui_real"
    finally:
        window.close(); app.processEvents()


def test_gui_builds_relative_serpentine_plan_and_copies_errors(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    stage = MockXYZStage(speed_mm_s=1000.0)
    stage.connect()
    stage.move_absolute({"X": 3.6806, "Y": -3.2516, "Z": 1.6478})
    while stage.is_moving():
        time.sleep(0.001)
    camera = MockCamera(shape=(32, 40))
    camera.connect()
    window = MainWindow(
        config_path=tmp_path / "configuration.json",
        stage=stage,
        camera=camera,
        device_mode="REAL",
    )
    try:
        window.scan_type.setCurrentText("XY")
        for controls in (window.axis1, window.axis2):
            for widget, value in zip(controls, (-0.1, 0.1, 0.05)):
                widget.setValue(value)
        for widget, value in zip(window.roi_spins, (0, 0, 10, 10)):
            widget.setValue(value)
        window.fixed.setValue(0.0)
        plan = window._plan_from_controls()
        assert plan.points[0].targets_mm == pytest.approx(
            {"X": 3.5806, "Y": -3.3516, "Z": 1.6478}
        )
        assert plan.return_to_start and plan.return_step_mm == 0.001
        assert not window.controller.preflight(plan, image_shape=camera.image_shape)
        window._plan = plan
        assert window._absolute_axis_values("X", plan.horizontal_values) == pytest.approx(
            [point.targets_mm["X"] for point in plan.points[:5]]
        )
        assert window._absolute_axis_values("Y", plan.vertical_values) == pytest.approx(
            [-3.3516, -3.3016, -3.2516, -3.2016, -3.1516]
        )
        assert window._absolute_fixed_value() == pytest.approx(1.6478)

        window.plane_scan_path.setCurrentText("Z形（每行同向）")
        z_shaped = window._plan_from_controls()
        assert z_shaped.plane_path_mode == "Z_SHAPED"
        assert [point.col for point in z_shaped.points[5:10]] == [0, 1, 2, 3, 4]

        window._on_failed("可复制的测试错误")
        window.copy_error_button.click()
        assert app.clipboard().text() == "可复制的测试错误"
    finally:
        window.close(); app.processEvents()


def test_gui_z_range_is_relative_and_keeps_xy_fixed(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    stage = MockXYZStage(speed_mm_s=1000.0)
    stage.connect()
    stage.move_absolute({"X": 3.6806, "Y": -3.2516, "Z": 1.6478})
    while stage.is_moving():
        time.sleep(0.001)
    camera = MockCamera(shape=(32, 40))
    camera.connect()
    window = MainWindow(
        config_path=tmp_path / "configuration.json",
        stage=stage,
        camera=camera,
        device_mode="REAL",
    )
    try:
        window.scan_type.setCurrentText("Z range")
        for widget, value in zip(window.axis1, (-0.1, 0.1, 0.05)):
            widget.setValue(value)
        plan = window._plan_from_controls()
        assert plan.plane_path_mode is None
        assert [point.targets_mm["Z"] for point in plan.points] == pytest.approx(
            [1.5478, 1.5978, 1.6478, 1.6978, 1.7478]
        )
        assert {point.targets_mm["X"] for point in plan.points} == {3.6806}
        assert {point.targets_mm["Y"] for point in plan.points} == {-3.2516}

        window._plan = plan
        window._metric_data = np.full(plan.total_points, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            window._render_main()
        assert window.curve.xData is None or window.curve.xData.size == 0

        window._metric_data[1] = 42.0
        window._render_main()
        assert window.curve.xData == pytest.approx([plan.points[1].targets_mm["Z"]])
        assert window.main_plot.getAxis("bottom").labelText == "Z 绝对位置 (mm)"
    finally:
        window.close(); app.processEvents()


def test_gui_reopens_saved_raw_image(tmp_path: Path) -> None:
    stage = MockXYZStage(speed_mm_s=1000); stage.connect()
    stage.move_absolute({"X": 1.25, "Y": -2.5, "Z": 0.75})
    while stage.is_moving():
        time.sleep(0.001)
    origin = stage.get_positions()
    camera = MockCamera(shape=(32, 40), position_provider=stage.get_positions); camera.connect()
    plan = SpatialScanPlan.from_plane(
        plane="XY", horizontal_start=0, horizontal_stop=0, horizontal_step=1,
        vertical_start=0, vertical_stop=0, vertical_step=1, fixed_value_mm=0,
        relative_origin_mm=origin, save_root=tmp_path / "data",
        roi_xywh=(1, 1, 10, 10), settling_time_s=0,
    )
    directory = SpatialScanController(stage, camera).run(plan)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        window.open_session(directory)
        assert window.raw_item.image is not None
        assert window._selected_point_id == 1
        assert window._plan.coordinate_mode == "RELATIVE_TO_SCAN_START"
        assert window._absolute_axis_values("X", window._plan.horizontal_values) == pytest.approx([1.25])
        assert window._absolute_axis_values("Y", window._plan.vertical_values) == pytest.approx([-2.5])
        assert window._absolute_fixed_value() == pytest.approx(0.75)
    finally:
        window.close(); app.processEvents()


def test_gui_mock_camera_move_does_not_change_objective(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        original = window.stage.get_positions()
        result = window.controller.manual_move_camera({"X": 0.2, "Y": -0.1})
        assert result == {"X": 0.2, "Y": -0.1}
        assert window.stage.get_positions() == original
    finally:
        window.close(); app.processEvents()


def test_move_to_target_button_dispatches_objective_targets(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        targets = {"X": 0.01, "Y": -0.02, "Z": 0.03}
        for axis, value in targets.items():
            window.target_spins[axis].setValue(value)

        dispatched: list[tuple[dict[str, float], str]] = []

        def capture_move(values: dict[str, float], *, group: str) -> None:
            dispatched.append((values, group))

        window._start_move = capture_move  # type: ignore[method-assign]
        window.move_button.click()
        assert dispatched == [(targets, "objective")]
    finally:
        window.close(); app.processEvents()


def test_new_scan_resets_to_follow_latest_and_displays_each_new_frame(tmp_path: Path) -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(config_path=tmp_path / "configuration.json")
    try:
        plan = SpatialScanPlan.from_axis_list(
            axis="Z",
            values=[0.0, 0.001],
            fixed_positions_mm={"X": 0.0, "Y": 0.0, "Z": 0.0},
            save_root=tmp_path / "data",
            roi_xywh=(0, 0, 2, 2),
            settling_time_s=0.0,
        )
        window._plan = plan
        window._metric_data = np.full((2,), np.nan)

        # 模拟前一次采集留下了较大的 point_id；新计划重设控件不能被当成用户选点。
        window.view_mode.setCurrentText("跟随最新")
        for widget in (window.point_slider, window.point_spin):
            blocker = QtCore.QSignalBlocker(widget)
            widget.setRange(1, 5)
            widget.setValue(5)
            del blocker
        window._reset_point_browser(plan.total_points)
        assert window.view_mode.currentText() == "跟随最新"
        assert window.point_slider.value() == window.point_spin.value() == 1

        def record(point_id: int) -> dict[str, object]:
            return {
                "point_id": point_id,
                "metric_value": float(point_id),
                "roi_x": 0,
                "roi_y": 0,
                "roi_width": 2,
                "roi_height": 2,
                "target_x_mm": 0.0,
                "target_y_mm": 0.0,
                "target_z_mm": (point_id - 1) * 0.001,
                "filename": f"point_{point_id}.tiff",
            }

        first = np.full((2, 2), 11, dtype=np.uint16)
        second = np.full((2, 2), 22, dtype=np.uint16)
        window._on_point_saved(record(1), first)
        window._on_point_saved(record(2), second)

        assert window._selected_point_id == 2
        assert window.point_slider.value() == window.point_spin.value() == 2
        assert np.array_equal(window.raw_item.image, second)

        # 用户主动固定某点后保持该帧；切回跟随时立即跳到最新帧。
        window._records.clear()
        window._images.clear()
        window._metric_data[:] = np.nan
        window._reset_point_browser(plan.total_points)
        window._on_point_saved(record(1), first)
        window._user_select_point(1)
        window._on_point_saved(record(2), second)
        assert window.view_mode.currentText() == "固定选择"
        assert window._selected_point_id == 1
        assert np.array_equal(window.raw_item.image, first)

        window.view_mode.setCurrentText("跟随最新")
        assert window._selected_point_id == 2
        assert np.array_equal(window.raw_item.image, second)
    finally:
        window.close(); app.processEvents()
