from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from hardware.dimension_stage import DimensionStage, DimensionStageConfig
from hardware.stage_safety import (
    AxisCalibration,
    StageCapabilities,
    StageSafetyError,
    UnsupportedStageOperation,
)


def gas_dll() -> Path:
    return Path(__file__).resolve().parents[2] / "positioner" / "GAS.dll"


class FakeFunction:
    """记录调用，并允许 Adapter 像 ctypes function 一样设置 argtypes。"""

    def __init__(
        self,
        name: str,
        calls: list[str],
        implementation: Callable[..., int] | None = None,
    ) -> None:
        self.name = name
        self.calls = calls
        self.implementation = implementation
        self.argtypes: list[object] = []
        self.restype: object | None = None

    def __call__(self, *args: object) -> int:
        self.calls.append(self.name)
        if self.implementation is not None:
            return self.implementation(*args)
        return 0


class FakeGasDll:
    def __init__(self, position_pulse: float = 1234.0, raw_status: int = 7) -> None:
        self.calls: list[str] = []

        def get_position(_axis: object, pointer: Any, *_: object) -> int:
            pointer._obj.value = position_pulse
            return 0

        def get_status(_axis: object, pointer: Any, *_: object) -> int:
            pointer._obj.value = raw_status
            return 0

        self.GA_OpenByIP = FakeFunction("GA_OpenByIP", self.calls)
        self.GA_Close = FakeFunction("GA_Close", self.calls)
        self.GA_GetPrfPos = FakeFunction(
            "GA_GetPrfPos", self.calls, get_position
        )
        self.GA_GetSts = FakeFunction("GA_GetSts", self.calls, get_status)
        self.GA_AxisOn = FakeFunction("GA_AxisOn", self.calls)
        self.GA_PrfTrap = FakeFunction("GA_PrfTrap", self.calls)
        self.GA_SetTrapPrmSingle = FakeFunction(
            "GA_SetTrapPrmSingle", self.calls
        )
        self.GA_SetPos = FakeFunction("GA_SetPos", self.calls)
        self.GA_SetVel = FakeFunction("GA_SetVel", self.calls)
        self.GA_Update = FakeFunction("GA_Update", self.calls)


class FakeDimensionStage(DimensionStage):
    def __init__(self, config: DimensionStageConfig, fake_dll: FakeGasDll) -> None:
        super().__init__(config)
        self.fake_dll = fake_dll

    def _load_library(self) -> Any:
        self._bind_confirmed_api(self.fake_dll)  # type: ignore[arg-type]
        return self.fake_dll


def fully_confirmed_capabilities() -> StageCapabilities:
    return StageCapabilities(
        position_read_supported=True,
        status_read_supported=True,
        motion_supported=True,
        stop_supported=True,
        home_supported=True,
        positive_limit_supported=True,
        negative_limit_supported=True,
        status_interpretation_supported=True,
    )


def complete_calibration() -> AxisCalibration:
    return AxisCalibration(
        axis_id=1,
        pulses_per_mm=1000.0,
        travel_min_mm=0.0,
        travel_max_mm=10.0,
        direction_sign=1,
        home_position_mm=0.0,
    )


def connection_values() -> dict[str, str]:
    # RFC 5737 TEST-NET，仅供 Fake DLL 单元测试，不会连接真实网络。
    return {"pc_ip": "192.0.2.10", "card_ip": "192.0.2.11"}


def test_vendor_library_loads_without_connecting_hardware() -> None:
    stage = DimensionStage(DimensionStageConfig(dll_path=gas_dll()))
    dll = stage._load_library()
    assert dll.GA_OpenByIP is not None
    assert dll.GA_GetPrfPos is not None
    assert dll.GA_GetSts is not None
    assert not stage.is_connected


def test_connection_requires_explicit_verified_ips() -> None:
    fake = FakeGasDll()
    stage = FakeDimensionStage(
        DimensionStageConfig(
            dll_path=gas_dll(), calibration=AxisCalibration(axis_id=1)
        ),
        fake,
    )
    with pytest.raises(StageSafetyError, match="显式配置"):
        stage.connect()
    assert fake.calls == []


def test_mm_pulse_conversion_is_explicit_and_direction_aware() -> None:
    positive = AxisCalibration(
        pulses_per_mm=2000.0, direction_sign=1, home_position_mm=5.0
    )
    negative = AxisCalibration(
        pulses_per_mm=2000.0, direction_sign=-1, home_position_mm=5.0
    )
    assert positive.mm_to_pulse(5.25) == 500
    assert positive.pulse_to_mm(500) == pytest.approx(5.25)
    assert negative.mm_to_pulse(5.25) == -500
    assert negative.pulse_to_mm(-500) == pytest.approx(5.25)


def test_incomplete_calibration_blocks_motion_before_motion_api() -> None:
    fake = FakeGasDll()
    stage = FakeDimensionStage(
        DimensionStageConfig(
            dll_path=gas_dll(),
            **connection_values(),
            calibration=AxisCalibration(axis_id=1),
            capabilities=fully_confirmed_capabilities(),
            allow_motion=True,
            healthy_raw_status_values=frozenset({7}),
        ),
        fake,
    )
    stage.connect()
    with pytest.raises(StageSafetyError, match="轴标定不完整"):
        stage.move_absolute_mm(1.0)
    assert "GA_SetPos" not in fake.calls
    assert "GA_Update" not in fake.calls


def test_range_violation_blocks_motion_before_motion_api() -> None:
    fake = FakeGasDll()
    stage = FakeDimensionStage(
        DimensionStageConfig(
            dll_path=gas_dll(),
            **connection_values(),
            calibration=complete_calibration(),
            capabilities=fully_confirmed_capabilities(),
            allow_motion=True,
            healthy_raw_status_values=frozenset({7}),
        ),
        fake,
    )
    stage.connect()
    with pytest.raises(StageSafetyError, match="高于允许上限"):
        stage.move_absolute_mm(10.1)
    assert "GA_SetPos" not in fake.calls
    assert "GA_Update" not in fake.calls


def test_unknown_capability_blocks_unsupported_operation() -> None:
    stage = DimensionStage(DimensionStageConfig(dll_path=gas_dll()))
    with pytest.raises(UnsupportedStageOperation, match="unknown"):
        stage.stop()
    with pytest.raises(UnsupportedStageOperation, match="unknown"):
        stage.home()


def test_read_only_session_never_calls_motion_functions() -> None:
    fake = FakeGasDll(position_pulse=321.5, raw_status=0x1234)
    stage = FakeDimensionStage(
        DimensionStageConfig(
            dll_path=gas_dll(),
            **connection_values(),
            calibration=AxisCalibration(axis_id=1),
            allow_motion=False,
        ),
        fake,
    )
    stage.load_library()
    stage.connect()
    assert stage.get_position_pulse() == 321.5
    assert stage.read_raw_status() == 0x1234
    stage.disconnect()
    assert fake.calls == ["GA_OpenByIP", "GA_GetPrfPos", "GA_GetSts", "GA_Close"]


def test_real_motion_is_opt_in_and_default_calibration_unknown() -> None:
    config = DimensionStageConfig(dll_path=gas_dll())
    assert config.allow_motion is False
    assert config.calibration.pulses_per_mm is None
    assert config.calibration.travel_min_mm is None


def test_invalid_axis_is_rejected_before_dll_call() -> None:
    with pytest.raises(ValueError, match="1..8"):
        AxisCalibration(axis_id=0)
