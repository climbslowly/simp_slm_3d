import time

import pytest

from mock.mock_xyz_stage import MockXYZStage


def _wait(stage: MockXYZStage) -> None:
    deadline = time.monotonic() + 1.0
    while stage.is_moving() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert not stage.is_moving()


def test_five_axis_groups_are_independent_and_signal_is_relative() -> None:
    stage = MockXYZStage(speed_mm_s=1000.0)
    stage.connect()
    stage.move_camera_absolute({"X": 0.1, "Y": -0.2})
    _wait(stage)
    stage.move_absolute({"X": 0.4, "Y": 0.3, "Z": 0.5})
    _wait(stage)

    assert stage.get_camera_positions() == pytest.approx({"X": 0.1, "Y": -0.2})
    assert stage.get_positions() == pytest.approx({"X": 0.4, "Y": 0.3, "Z": 0.5})
    assert stage.get_signal_positions() == pytest.approx({"X": 0.3, "Y": 0.5, "Z": 0.5})


def test_reported_axis_mapping_is_explicitly_unverified() -> None:
    stage = MockXYZStage()
    stage.connect()
    info = stage.device_info()
    assert info["direction_sign_verified"] is False
    assert info["axis_mapping"]["camera"]["X"] == {
        "controller_axis": 1, "optical_role": "transverse_x", "physical_axis": "Y"
    }
    assert info["axis_mapping"]["objective"]["Z"] == {
        "controller_axis": 4, "optical_role": "propagation", "physical_axis": "X"
    }


def test_one_mock_controller_rejects_overlapping_group_moves() -> None:
    stage = MockXYZStage(speed_mm_s=0.01)
    stage.connect()
    stage.move_camera_absolute({"X": 1.0, "Y": 0.0})
    with pytest.raises(RuntimeError, match="忙"):
        stage.move_absolute({"X": 0.0, "Y": 0.0, "Z": 0.0})
    stage.stop()
