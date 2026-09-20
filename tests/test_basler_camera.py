from __future__ import annotations

from types import SimpleNamespace

import pytest

from hardware import basler_camera
from hardware.basler_camera import BaslerCameraError


class FakeDevice:
    def __init__(self, serial: str, model: str, tl_type: str) -> None:
        self.values = {
            "GetSerialNumber": serial,
            "GetModelName": model,
            "GetVendorName": "Basler",
            "GetTLType": tl_type,
            "GetDeviceClass": f"Basler{tl_type}",
            "GetInterfaceID": f"interface-{tl_type}",
            "GetFriendlyName": f"{model} ({serial})",
            "GetFullName": f"full-{serial}",
        }

    def __getattr__(self, name: str):
        if name not in self.values:
            raise AttributeError(name)
        return lambda: self.values[name]


class FakeFactory:
    def EnumerateDevices(self) -> list[FakeDevice]:
        return [
            FakeDevice("USB-001", "ace USB", "Usb"),
            FakeDevice("CXP-002", "boost CXP", "GenTL"),
        ]


def install_fake_pylon(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = FakeFactory()
    fake_pylon = SimpleNamespace(
        TlFactory=SimpleNamespace(GetInstance=lambda: factory)
    )
    monkeypatch.setattr(basler_camera, "_load_pylon", lambda: fake_pylon)


def test_enumeration_includes_usb_and_cxp_transport_layers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_pylon(monkeypatch)
    devices = basler_camera.enumerate_basler_cameras()
    assert [device.index for device in devices] == [0, 1]
    assert devices[0].serial_number == "USB-001"
    assert devices[0].transport_layer_type == "Usb"
    assert devices[1].serial_number == "CXP-002"
    assert devices[1].transport_layer_type == "GenTL"


def test_select_camera_uses_displayed_index(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_pylon(monkeypatch)
    selected = basler_camera.select_basler_camera(1)
    assert selected.serial_number == "CXP-002"
    with pytest.raises(BaslerCameraError, match="超出范围"):
        basler_camera.select_basler_camera(2)
