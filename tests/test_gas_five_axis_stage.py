from __future__ import annotations

import json
import ctypes
from pathlib import Path
from typing import Any, Callable

import pytest

from hardware.diagnostic_profile import load_hardware_diagnostic_profile
from hardware.dimension_stage import DimensionStage
from hardware.gas_five_axis_stage import GasFiveAxisStage
from hardware.stage_safety import StageSafetyError
from scan.spatial_scan import SpatialScanPlan


class FakeFunction:
    def __init__(self, implementation: Callable[..., int] | None = None) -> None:
        self.implementation = implementation
        self.arguments: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> int:
        self.arguments.append(args)
        return 0 if self.implementation is None else self.implementation(*args)


class FakeGasDll:
    def __init__(self) -> None:
        self.positions = {1: -57363.0, 2: 67778.0, 3: 36806.0, 4: 16478.0, 5: 32516.0}
        self.statuses = {axis: 0 for axis in self.positions}

        def get_position(axis: int, pointer: Any, *_: object) -> int:
            pointer._obj.value = self.positions[int(axis)]
            return 0

        def get_status(axis: int, pointer: Any, *_: object) -> int:
            pointer._obj.value = self.statuses[int(axis)]
            return 0

        def set_position(axis: int, target: int) -> int:
            self.positions[int(axis)] = float(target)
            return 0

        self.GA_GetPrfPos = FakeFunction(get_position)
        self.GA_GetSts = FakeFunction(get_status)
        self.GA_OpenByIP = FakeFunction()
        self.GA_Close = FakeFunction()
        self.GA_SetSoftLimit = FakeFunction()
        self.GA_LmtsOn = FakeFunction()
        self.GA_AxisOn = FakeFunction()
        self.GA_PrfTrap = FakeFunction()
        self.GA_SetTrapPrmSingle = FakeFunction()
        self.GA_SetPos = FakeFunction(set_position)
        self.GA_SetVel = FakeFunction()
        self.GA_Update = FakeFunction()
        self.GA_Stop = FakeFunction()


def make_profile(tmp_path: Path):
    payload = {
        "schema_version": 1,
        "dll_path": str(tmp_path / "GAS.dll"),
        "pc_ip": "192.0.2.10",
        "card_ip": "192.0.2.11",
        "camera": {"camera_index": 0},
        "axes": {
            str(axis): {
                "label": f"axis {axis}",
                "physical_mapping": "test",
                "pulses_per_mm": None,
                "travel_min_mm": None,
                "travel_max_mm": None,
                "direction_sign": None,
                "home_position_mm": None,
                "soft_limit_min_mm": None,
                "soft_limit_max_mm": None,
                "max_single_step_mm": None,
            }
            for axis in range(1, 6)
        },
    }
    path = tmp_path / "hardware_local.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_hardware_diagnostic_profile(path)


def connected_stage(tmp_path: Path) -> tuple[GasFiveAxisStage, FakeGasDll]:
    stage = GasFiveAxisStage(make_profile(tmp_path), allow_motion=True)
    fake = FakeGasDll()
    stage._dll = fake  # type: ignore[assignment]
    stage._connected = True
    return stage, fake


def test_vendor_defaults_map_planned_pulses_to_gui_coordinates(tmp_path: Path) -> None:
    stage, _fake = connected_stage(tmp_path)
    assert stage.get_camera_positions() == pytest.approx({"X": -5.7363, "Y": -6.7778})
    assert stage.get_positions() == pytest.approx({"X": 3.6806, "Y": -3.2516, "Z": 1.6478})
    assert stage.objective_bounds_mm == {
        "X": [-26.0, 26.0],
        "Y": [-26.0, 26.0],
        "Z": [-26.0, 26.0],
    }
    info = stage.device_info()
    assert info["axis_mapping"]["objective"]["Y"]["controller_axis"] == 5
    assert info["axis_mapping"]["objective"]["Y"]["controller_sign_for_gui_positive"] == -1


def test_real_connect_writes_soft_limits_and_enables_hard_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = make_profile(tmp_path)
    assert profile.dll_path is not None
    profile.dll_path.write_bytes(b"fake")
    fake = FakeGasDll()
    monkeypatch.setattr(ctypes, "CDLL", lambda _path: fake)
    monkeypatch.setattr(DimensionStage, "_bind_confirmed_api", staticmethod(lambda _dll: None))
    stage = GasFiveAxisStage(profile, allow_motion=True)
    stage.connect()
    try:
        assert len(fake.GA_SetSoftLimit.arguments) == 5
        assert fake.GA_SetSoftLimit.arguments[0] == (1, 260000, -260000)
        assert fake.GA_LmtsOn.arguments == [(axis, -1) for axis in range(1, 6)]
    finally:
        stage.disconnect()


def test_real_stage_uses_axis_mask_and_enforces_single_step(tmp_path: Path) -> None:
    stage, fake = connected_stage(tmp_path)
    current = stage.get_positions()
    target = dict(current)
    target["X"] += 0.01
    stage.move_absolute(target)
    assert fake.GA_Update.arguments[-1] == (4,)
    assert stage.is_moving() is False

    too_far = stage.get_positions()
    too_far["Z"] += 0.1001
    with pytest.raises(StageSafetyError, match="单步"):
        stage.move_absolute(too_far)


def test_triggered_limit_blocks_toward_limit_but_allows_retreat(tmp_path: Path) -> None:
    stage, fake = connected_stage(tmp_path)
    fake.statuses[3] = 0x20
    current = stage.get_positions()
    toward = dict(current)
    toward["X"] += 0.01
    with pytest.raises(StageSafetyError, match="正向限位"):
        stage.move_absolute(toward)

    retreat = dict(current)
    retreat["X"] -= 0.01
    stage.move_absolute(retreat)
    assert fake.GA_Update.arguments[-1] == (4,)


def test_relative_serpentine_scan_has_no_large_first_or_row_transition_step(
    tmp_path: Path,
) -> None:
    stage, _fake = connected_stage(tmp_path)
    origin = stage.get_positions()
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
        save_root=tmp_path,
        roi_xywh=(0, 0, 1, 1),
    )
    assert stage.plan_errors(plan.points) == []
    assert plan.points[0].targets_mm["Z"] == pytest.approx(origin["Z"])
