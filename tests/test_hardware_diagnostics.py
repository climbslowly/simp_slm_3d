from __future__ import annotations

import json
from pathlib import Path

import pytest

from hardware.diagnostic_profile import (
    CameraDiagnosticSettings,
    load_hardware_diagnostic_profile,
)
from hardware.diagnostics import capture_camera_sequence, read_stage_axes_snapshot
from mock.mock_camera import MockCamera
from scripts.check_motion_readiness import readiness_for_axis


def profile_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "dll_path": None,
        "pc_ip": None,
        "card_ip": None,
        "output_dir": "output/hardware_diagnostics",
        "camera": {
            "camera_index": 0,
            "exposure_ms": 2.0,
            "frames": 3,
            "discard_frames": 2,
            "capture_timeout_ms": 1234,
            "post_exposure_settle_ms": 0,
            "inter_frame_delay_ms": 0,
        },
        "axes": {
            "1": {
                "label": "camera X",
                "physical_mapping": "axis1+ -> physical +Y",
                "pulses_per_mm": 10000,
                "travel_min_mm": None,
                "travel_max_mm": None,
                "direction_sign": 1,
                "home_position_mm": None,
                "soft_limit_min_mm": None,
                "soft_limit_max_mm": None,
                "max_single_step_mm": None,
                "healthy_raw_status_values": [],
            }
        },
    }


def test_hardware_profile_is_local_and_validated(tmp_path: Path) -> None:
    path = tmp_path / "hardware_local.json"
    path.write_text(json.dumps(profile_payload()), encoding="utf-8")
    profile = load_hardware_diagnostic_profile(path)
    assert profile.camera.frames == 3
    assert profile.camera.capture_timeout_ms == 1234
    assert profile.axes[1].calibration().pulses_per_mm == 10000
    assert profile.output_dir == tmp_path / "output" / "hardware_diagnostics"


def test_invalid_camera_timing_is_rejected() -> None:
    with pytest.raises(ValueError, match="capture_timeout_ms"):
        CameraDiagnosticSettings(capture_timeout_ms=0)


def test_camera_sequence_discards_then_saves_raw_frames(tmp_path: Path) -> None:
    camera = MockCamera(shape=(12, 16), seed=2)
    settings = CameraDiagnosticSettings(
        camera_index=0,
        exposure_ms=2.0,
        frames=3,
        discard_frames=2,
        capture_timeout_ms=100,
        post_exposure_settle_ms=0,
        inter_frame_delay_ms=0,
    )
    session, report = capture_camera_sequence(
        camera, settings, output_root=tmp_path
    )
    assert report["status"] == "completed"
    assert len(report["discarded"]) == 2
    assert len(report["frames"]) == 3
    assert report["camera"]["actual_exposure_us"] == pytest.approx(2000.0)
    assert not camera.is_connected
    assert len(list(session.glob("frame_*.tiff"))) == 3
    on_disk = json.loads((session / "camera_diagnostic.json").read_text("utf-8"))
    assert on_disk["identical_adjacent_pairs"] == 0


class FakeReadOnlyStage:
    def __init__(self, config) -> None:
        self.config = config
        self.connected = False

    def load_library(self) -> None:
        pass

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_position_pulse(self) -> float:
        return float(self.config.calibration.axis_id * 100)

    def read_raw_status(self) -> int:
        return 0x4000 if self.config.calibration.axis_id == 3 else 0

    def get_encoder_position_pulse(self) -> float:
        return float(self.config.calibration.axis_id * 100 - 1)

    def get_soft_limits_pulse(self) -> tuple[int, int]:
        return (260000, -260000)


def test_five_axis_snapshot_is_read_only_and_decodes_status(tmp_path: Path) -> None:
    report = read_stage_axes_snapshot(
        dll_path=tmp_path / "GAS.dll",
        pc_ip="192.0.2.10",
        card_ip="192.0.2.11",
        axes=[1, 2, 3, 4, 5],
        stage_factory=FakeReadOnlyStage,
    )
    assert report["motion_commanded"] is False
    assert [item["planned_position_raw_pulse"] for item in report["axes"]] == [
        100.0,
        200.0,
        300.0,
        400.0,
        500.0,
    ]
    assert report["schema_version"] == 2
    assert report["state_changing_api_called"] is False
    assert [item["encoder_position_raw_pulse"] for item in report["axes"]] == [
        99.0,
        199.0,
        299.0,
        399.0,
        499.0,
    ]
    assert report["axes"][2]["status_interpretation"]["active_flags"] == [
        "HOME_SWITCH"
    ]
    assert all(
        item["controller_soft_limits_raw_pulse"]
        == {"positive": 260000, "negative": -260000}
        for item in report["axes"]
    )


def test_motion_readiness_audit_blocks_unknown_safety_evidence(tmp_path: Path) -> None:
    path = tmp_path / "hardware_local.json"
    path.write_text(json.dumps(profile_payload()), encoding="utf-8")
    profile = load_hardware_diagnostic_profile(path)
    errors = readiness_for_axis(profile, 1)
    assert "dll_path 未配置" in errors
    assert not any("Stop API" in error for error in errors)
    assert any("Home API" in error for error in errors)
    assert any("机械行程" in error or "轴标定" in error for error in errors)
