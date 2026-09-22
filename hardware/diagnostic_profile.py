"""本地硬件诊断配置。

仓库只保存不含现场值的示例文件；实验电脑使用的 ``hardware_local.json``
由 .gitignore 排除，避免把 IP、行程和现场标定误当成通用默认值。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .stage_safety import AxisCalibration


def _finite_optional(value: object, name: str) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} 必须是有限数值或 null")
    return result


@dataclass(frozen=True)
class CameraDiagnosticSettings:
    camera_index: int | None = None
    exposure_ms: float | None = None
    frames: int = 5
    discard_frames: int = 1
    capture_timeout_ms: int = 5000
    post_exposure_settle_ms: float = 20.0
    inter_frame_delay_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.camera_index is not None and self.camera_index < 0:
            raise ValueError("camera.camera_index 不能为负数")
        if self.exposure_ms is not None and (
            not math.isfinite(self.exposure_ms) or self.exposure_ms <= 0
        ):
            raise ValueError("camera.exposure_ms 必须是有限正数或 null")
        if self.frames < 1:
            raise ValueError("camera.frames 必须至少为 1")
        if self.discard_frames < 0:
            raise ValueError("camera.discard_frames 不能为负数")
        if self.capture_timeout_ms <= 0:
            raise ValueError("camera.capture_timeout_ms 必须大于 0")
        for name, value in (
            ("post_exposure_settle_ms", self.post_exposure_settle_ms),
            ("inter_frame_delay_ms", self.inter_frame_delay_ms),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"camera.{name} 必须是有限非负数")


@dataclass(frozen=True)
class AxisDiagnosticSettings:
    axis_id: int
    label: str
    physical_mapping: str
    pulses_per_mm: float | None = None
    travel_min_mm: float | None = None
    travel_max_mm: float | None = None
    direction_sign: int | None = None
    home_position_mm: float | None = None
    soft_limit_min_mm: float | None = None
    soft_limit_max_mm: float | None = None
    max_single_step_mm: float | None = None
    healthy_raw_status_values: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.max_single_step_mm is not None and (
            not math.isfinite(self.max_single_step_mm)
            or self.max_single_step_mm <= 0
        ):
            raise ValueError(
                f"axes.{self.axis_id}.max_single_step_mm 必须是有限正数或 null"
            )
        # 复用正式运动标定校验，确保示例/现场配置与 Adapter 规则一致。
        self.calibration()

    def calibration(self) -> AxisCalibration:
        return AxisCalibration(
            axis_id=self.axis_id,
            pulses_per_mm=self.pulses_per_mm,
            travel_min_mm=self.travel_min_mm,
            travel_max_mm=self.travel_max_mm,
            direction_sign=self.direction_sign,
            home_position_mm=self.home_position_mm,
            soft_limit_min_mm=self.soft_limit_min_mm,
            soft_limit_max_mm=self.soft_limit_max_mm,
        )


@dataclass(frozen=True)
class HardwareDiagnosticProfile:
    source_path: Path
    dll_path: Path | None
    pc_ip: str | None
    card_ip: str | None
    output_dir: Path
    camera: CameraDiagnosticSettings
    axes: dict[int, AxisDiagnosticSettings]

    def require_stage_connection(self) -> tuple[Path, str, str]:
        missing = [
            name
            for name, value in (
                ("dll_path", self.dll_path),
                ("pc_ip", self.pc_ip),
                ("card_ip", self.card_ip),
            )
            if value is None or value == ""
        ]
        if missing:
            raise ValueError("本地硬件配置缺少：" + ", ".join(missing))
        assert self.dll_path is not None
        assert self.pc_ip is not None
        assert self.card_ip is not None
        return self.dll_path, self.pc_ip, self.card_ip


def load_hardware_diagnostic_profile(path: Path) -> HardwareDiagnosticProfile:
    source = path.expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("hardware profile schema_version 必须是 1")

    base = source.parent
    raw_dll = payload.get("dll_path")
    dll_path = None if raw_dll in (None, "") else Path(str(raw_dll)).expanduser()
    if dll_path is not None and not dll_path.is_absolute():
        dll_path = (base / dll_path).resolve()
    raw_output = payload.get("output_dir", "output/hardware_diagnostics")
    output_dir = Path(str(raw_output)).expanduser()
    if not output_dir.is_absolute():
        output_dir = (base / output_dir).resolve()

    raw_camera = payload.get("camera", {})
    if not isinstance(raw_camera, dict):
        raise ValueError("camera 必须是 JSON object")
    camera = CameraDiagnosticSettings(
        camera_index=raw_camera.get("camera_index"),
        exposure_ms=_finite_optional(raw_camera.get("exposure_ms"), "camera.exposure_ms"),
        frames=int(raw_camera.get("frames", 5)),
        discard_frames=int(raw_camera.get("discard_frames", 1)),
        capture_timeout_ms=int(raw_camera.get("capture_timeout_ms", 5000)),
        post_exposure_settle_ms=float(raw_camera.get("post_exposure_settle_ms", 20.0)),
        inter_frame_delay_ms=float(raw_camera.get("inter_frame_delay_ms", 0.0)),
    )

    raw_axes = payload.get("axes", {})
    if not isinstance(raw_axes, dict) or not raw_axes:
        raise ValueError("axes 必须是非空 JSON object")
    axes: dict[int, AxisDiagnosticSettings] = {}
    for raw_axis_id, raw_axis in raw_axes.items():
        if not isinstance(raw_axis, dict):
            raise ValueError(f"axes.{raw_axis_id} 必须是 JSON object")
        axis_id = int(raw_axis_id)
        if axis_id in axes:
            raise ValueError(f"轴 {axis_id} 重复")
        healthy = raw_axis.get("healthy_raw_status_values", [])
        if not isinstance(healthy, list):
            raise ValueError(
                f"axes.{axis_id}.healthy_raw_status_values 必须是数组"
            )
        direction = raw_axis.get("direction_sign")
        axes[axis_id] = AxisDiagnosticSettings(
            axis_id=axis_id,
            label=str(raw_axis.get("label", f"axis {axis_id}")),
            physical_mapping=str(raw_axis.get("physical_mapping", "UNKNOWN")),
            pulses_per_mm=_finite_optional(
                raw_axis.get("pulses_per_mm"), f"axes.{axis_id}.pulses_per_mm"
            ),
            travel_min_mm=_finite_optional(
                raw_axis.get("travel_min_mm"), f"axes.{axis_id}.travel_min_mm"
            ),
            travel_max_mm=_finite_optional(
                raw_axis.get("travel_max_mm"), f"axes.{axis_id}.travel_max_mm"
            ),
            direction_sign=None if direction is None else int(direction),
            home_position_mm=_finite_optional(
                raw_axis.get("home_position_mm"), f"axes.{axis_id}.home_position_mm"
            ),
            soft_limit_min_mm=_finite_optional(
                raw_axis.get("soft_limit_min_mm"), f"axes.{axis_id}.soft_limit_min_mm"
            ),
            soft_limit_max_mm=_finite_optional(
                raw_axis.get("soft_limit_max_mm"), f"axes.{axis_id}.soft_limit_max_mm"
            ),
            max_single_step_mm=_finite_optional(
                raw_axis.get("max_single_step_mm"),
                f"axes.{axis_id}.max_single_step_mm",
            ),
            healthy_raw_status_values=tuple(int(item) for item in healthy),
        )

    return HardwareDiagnosticProfile(
        source_path=source,
        dll_path=dll_path,
        pc_ip=payload.get("pc_ip"),
        card_ip=payload.get("card_ip"),
        output_dir=output_dir,
        camera=camera,
        axes=axes,
    )
