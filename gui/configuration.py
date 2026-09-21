"""GUI 默认配置；损坏文件只报告，不覆盖。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


DEFAULT_CONFIG: dict[str, object] = {
    "schema_version": 1,
    "device_mode": "MOCK",
    "exposure_ms": 1.0,
    "manual_step_mm": 0.1,
    "camera_manual_step_mm": 0.1,
    "scan_type": "XY",
    "horizontal_start": -0.4,
    "horizontal_stop": 0.4,
    "horizontal_step": 0.2,
    "vertical_start": -0.2,
    "vertical_stop": 0.2,
    "vertical_step": 0.2,
    "fixed_value_mm": 0.0,
    "settling_ms": 20.0,
    "roi_xywh": [80, 64, 160, 128],
    "metric": "mean",
    "output_dir": "output/gui_m1",
    "colormap": "viridis",
}


def load_config(path: Path) -> tuple[dict[str, object], str | None]:
    if not path.exists():
        return dict(DEFAULT_CONFIG), None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded.get("schema_version") != 1:
            raise ValueError("schema_version 不是 1")
        if loaded.get("device_mode") != "MOCK":
            raise ValueError("GUI-M1 只允许 MOCK device_mode")
        merged = dict(DEFAULT_CONFIG)
        merged.update(loaded)
        return merged, None
    except Exception as exc:
        return dict(DEFAULT_CONFIG), f"配置文件损坏，已保留原文件并使用安全 Mock 默认值：{exc}"


def save_config_atomic(path: Path, config: dict[str, object]) -> None:
    safe = dict(config)
    safe["schema_version"] = 1
    safe["device_mode"] = "MOCK"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(safe, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise
