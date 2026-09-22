"""GUI 默认配置；损坏文件只报告，不覆盖。"""

from __future__ import annotations

import json
import math
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
    # None 表示未配置。真实硬件范围必须来自逐轴现场确认，不能用 Mock 默认值冒充。
    "objective_scan_bounds_mm": None,
}


def normalize_objective_bounds(value: object) -> dict[str, list[float]] | None:
    """校验配置文件中的物镜 GUI X/Y/Z 扫描边界，不猜测缺失轴。"""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"X", "Y", "Z"}:
        raise ValueError("objective_scan_bounds_mm 必须包含且只包含 X/Y/Z")
    normalized: dict[str, list[float]] = {}
    for axis in ("X", "Y", "Z"):
        bounds = value[axis]
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise ValueError(f"objective_scan_bounds_mm.{axis} 必须是 [min, max]")
        lower, upper = float(bounds[0]), float(bounds[1])
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            raise ValueError(f"objective_scan_bounds_mm.{axis} 必须是有限数值且 min < max")
        normalized[axis] = [lower, upper]
    return normalized


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
        merged["objective_scan_bounds_mm"] = normalize_objective_bounds(
            merged.get("objective_scan_bounds_mm")
        )
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
