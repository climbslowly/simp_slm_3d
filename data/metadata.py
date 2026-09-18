"""Metadata 辅助函数。"""

from __future__ import annotations

from hardware.camera_base import CameraBase


def describe_camera(camera: CameraBase) -> dict[str, object]:
    return {
        "serial_number": camera.get_serial_number(),
        "model_name": camera.get_model_name(),
        "exposure_us": camera.get_exposure_us(),
    }

