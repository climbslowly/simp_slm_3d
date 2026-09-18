import time

import pytest

from mock.mock_stage import MockStage


def test_mock_stage_moves_and_waits() -> None:
    stage = MockStage(speed_units_per_s=1000.0)
    stage.connect()
    stage.move_absolute(2.0)
    final = stage.wait_until_idle(
        target_position=2.0, tolerance=1e-6, timeout_s=1.0, poll_interval_s=0.001
    )
    assert final == pytest.approx(2.0)
    stage.move_relative(-0.5)
    stage.wait_until_idle(
        target_position=1.5, tolerance=1e-6, timeout_s=1.0, poll_interval_s=0.001
    )
    assert stage.get_position() == pytest.approx(1.5)


def test_stop_freezes_current_position() -> None:
    stage = MockStage(speed_units_per_s=1.0)
    stage.connect()
    stage.move_absolute(10.0)
    time.sleep(0.01)
    stage.stop()
    stopped = stage.get_position()
    time.sleep(0.01)
    assert stage.get_position() == pytest.approx(stopped)
    assert not stage.is_moving()

