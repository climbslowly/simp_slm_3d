from __future__ import annotations

import sys
from types import ModuleType

import numpy as np

import main


def test_matlab_export_contains_image_and_current_stage_metadata(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    def fake_savemat(path, payload, *, do_compression: bool) -> None:
        captured["path"] = path
        captured["payload"] = payload
        captured["do_compression"] = do_compression

    fake_scipy = ModuleType("scipy")
    fake_io = ModuleType("scipy.io")
    fake_io.savemat = fake_savemat  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scipy", fake_scipy)
    monkeypatch.setitem(sys.modules, "scipy.io", fake_io)

    image = np.arange(6, dtype=np.uint16).reshape(2, 3)
    metadata: dict[str, object] = {
        "capture_time_utc": "2026-09-20T00:00:00.000+00:00",
        "camera": {
            "serial_number": "40181166",
            "model_name": "boA8100-16cm",
            "transport_layer_type": "CXP",
            "exposure_us": 1000.0,
        },
        "stage": {"position_value": 123.0, "raw_status_decimal": 7},
    }

    main.write_matlab_file(tmp_path / "frame.mat", image, metadata)

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert np.array_equal(payload["image"], image)
    assert payload["camera_serial"] == "40181166"
    assert payload["transport_layer"] == "CXP"
    assert payload["stage_position_pulse"] == 123.0
    assert payload["stage_raw_status"] == 7
    assert captured["do_compression"] is True
