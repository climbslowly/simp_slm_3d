"""真实硬件诊断的可测试核心逻辑；CLI 入口位于 scripts/。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from .camera_base import CameraBase
from .diagnostic_profile import CameraDiagnosticSettings
from .dimension_stage import DimensionStage, DimensionStageConfig
from .stage_safety import AxisCalibration


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _unique_session(root: Path, suffix: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"{timestamp}_{suffix}"
    counter = 1
    while candidate.exists():
        candidate = root / f"{timestamp}_{suffix}_{counter:03d}"
        counter += 1
    candidate.mkdir()
    return candidate


def _image_digest(image: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(image)
    return hashlib.sha256(memoryview(contiguous).cast("B")).hexdigest()


def capture_camera_sequence(
    camera: CameraBase,
    settings: CameraDiagnosticSettings,
    *,
    output_root: Path,
    device_details: dict[str, object] | None = None,
) -> tuple[Path, dict[str, object]]:
    """连接一台相机，丢弃预热帧，再保存多帧和时序/重复帧报告。"""

    safe_serial = re.sub(r"[^A-Za-z0-9_-]", "_", camera.get_serial_number())
    session = _unique_session(output_root, f"camera_{safe_serial}_diagnostic")
    report: dict[str, object] = {
        "schema_version": 1,
        "operation": "camera_sequence_diagnostic",
        "started_utc": _utc_now(),
        "status": "running",
        "camera": {
            "serial_number": camera.get_serial_number(),
            **(device_details or {}),
        },
        "settings": {
            "requested_exposure_ms": settings.exposure_ms,
            "frames": settings.frames,
            "discard_frames": settings.discard_frames,
            "capture_timeout_ms": settings.capture_timeout_ms,
            "post_exposure_settle_ms": settings.post_exposure_settle_ms,
            "inter_frame_delay_ms": settings.inter_frame_delay_ms,
        },
        "discarded": [],
        "frames": [],
    }
    report_path = session / "camera_diagnostic.json"
    try:
        camera.connect()
        camera_info = report["camera"]
        assert isinstance(camera_info, dict)
        camera_info["model_name"] = camera.get_model_name()
        camera_info["original_exposure_us"] = camera.get_exposure_us()
        if settings.exposure_ms is not None:
            camera.set_exposure_us(settings.exposure_ms * 1000.0)
            if settings.post_exposure_settle_ms:
                time.sleep(settings.post_exposure_settle_ms / 1000.0)
        camera_info["actual_exposure_us"] = camera.get_exposure_us()

        discarded = report["discarded"]
        assert isinstance(discarded, list)
        for index in range(1, settings.discard_frames + 1):
            started = time.perf_counter()
            image = camera.grab_image(timeout_ms=settings.capture_timeout_ms)
            discarded.append(
                {
                    "index": index,
                    "capture_duration_ms": (time.perf_counter() - started) * 1000.0,
                    "shape": list(image.shape),
                    "dtype": str(image.dtype),
                    "sha256": _image_digest(image),
                }
            )

        frame_reports = report["frames"]
        assert isinstance(frame_reports, list)
        previous_digest: str | None = None
        for index in range(1, settings.frames + 1):
            if index > 1 and settings.inter_frame_delay_ms:
                time.sleep(settings.inter_frame_delay_ms / 1000.0)
            started_utc = _utc_now()
            started = time.perf_counter()
            image = camera.grab_image(timeout_ms=settings.capture_timeout_ms)
            duration_ms = (time.perf_counter() - started) * 1000.0
            digest = _image_digest(image)
            filename = f"frame_{index:04d}.tiff"
            tifffile.imwrite(session / filename, image)
            frame_reports.append(
                {
                    "index": index,
                    "capture_started_utc": started_utc,
                    "capture_duration_ms": duration_ms,
                    "filename": filename,
                    "shape": list(image.shape),
                    "dtype": str(image.dtype),
                    "min": float(np.min(image)),
                    "max": float(np.max(image)),
                    "mean": float(np.mean(image)),
                    "std": float(np.std(image)),
                    "sha256": digest,
                    "identical_to_previous": previous_digest == digest,
                }
            )
            previous_digest = digest

        report["status"] = "completed"
        report["completed_utc"] = _utc_now()
        report["identical_adjacent_pairs"] = sum(
            bool(item["identical_to_previous"]) for item in frame_reports
        )
        return session, report
    except Exception as exc:
        report["status"] = "error"
        report["completed_utc"] = _utc_now()
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            if camera.is_connected:
                camera.disconnect()
        finally:
            report_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )


StageFactory = Callable[[DimensionStageConfig], DimensionStage]


def read_stage_axes_snapshot(
    *,
    dll_path: Path,
    pc_ip: str,
    card_ip: str,
    axes: Iterable[int],
    stage_factory: StageFactory = DimensionStage,
) -> dict[str, object]:
    """逐轴建立只读会话，读取规划位置和未解释的 raw status。"""

    results: list[dict[str, object]] = []
    for axis_id in axes:
        stage = stage_factory(
            DimensionStageConfig(
                dll_path=dll_path,
                pc_ip=pc_ip,
                card_ip=card_ip,
                calibration=AxisCalibration(axis_id=axis_id),
                allow_motion=False,
            )
        )
        item: dict[str, object] = {"axis_id": axis_id, "status": "running"}
        try:
            stage.load_library()
            stage.connect()
            raw_status = stage.read_raw_status()
            item.update(
                {
                    "status": "ok",
                    "planned_position_raw_pulse": stage.get_position_pulse(),
                    "raw_status_decimal": raw_status,
                    "raw_status_hex": f"0x{raw_status & 0xFFFFFFFF:08X}",
                    "raw_status_interpretation": "UNKNOWN",
                }
            )
        except Exception as exc:
            item.update(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            )
        finally:
            try:
                stage.disconnect()
            except Exception as exc:
                item["disconnect_error"] = f"{type(exc).__name__}: {exc}"
        results.append(item)
    return {
        "schema_version": 1,
        "operation": "five_axis_read_only_snapshot",
        "captured_utc": _utc_now(),
        "pc_ip": pc_ip,
        "card_ip": card_ip,
        "motion_commanded": False,
        "axes": results,
    }


def write_timestamped_report(
    output_root: Path, suffix: str, payload: dict[str, object]
) -> Path:
    session = _unique_session(output_root, suffix)
    path = session / "report.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
