"""Basler pypylon Adapter。pypylon 采用延迟导入，Mock 测试无需安装它。"""

from __future__ import annotations

from typing import Any

import numpy as np

from .camera_base import CameraBase


class BaslerCameraError(RuntimeError):
    pass


def _load_pylon() -> Any:
    try:
        from pypylon import pylon
    except ImportError as exc:
        raise BaslerCameraError(
            "未安装 pypylon。请在项目环境运行：pip install pypylon"
        ) from exc
    return pylon


class BaslerCamera(CameraBase):
    """用序列号绑定一台 Basler 相机，避免依赖易变化的枚举顺序。"""

    def __init__(self, serial_number: str) -> None:
        if not serial_number.strip():
            raise ValueError("serial_number 不能为空")
        self._serial_number = serial_number.strip()
        self._camera: Any | None = None
        self._pylon: Any | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._camera is not None and self._camera.IsOpen())

    def connect(self) -> None:
        if self.is_connected:
            return
        pylon = _load_pylon()
        factory = pylon.TlFactory.GetInstance()
        selected = None
        for device in factory.EnumerateDevices():
            if device.GetSerialNumber() == self._serial_number:
                selected = device
                break
        if selected is None:
            raise BaslerCameraError(f"找不到序列号为 {self._serial_number} 的相机")
        camera = pylon.InstantCamera(factory.CreateDevice(selected))
        camera.Open()
        self._pylon = pylon
        self._camera = camera

    def disconnect(self) -> None:
        if self._camera is None:
            return
        try:
            if self._camera.IsGrabbing():
                self._camera.StopGrabbing()
            if self._camera.IsOpen():
                self._camera.Close()
        finally:
            self._camera = None
            self._pylon = None

    def _require_camera(self) -> Any:
        if not self.is_connected:
            raise BaslerCameraError("相机尚未连接")
        return self._camera

    def get_serial_number(self) -> str:
        return self._serial_number

    def get_model_name(self) -> str:
        camera = self._require_camera()
        return str(camera.GetDeviceInfo().GetModelName())

    def set_exposure_us(self, exposure_us: float) -> None:
        if exposure_us <= 0:
            raise ValueError("曝光时间必须大于 0 us")
        camera = self._require_camera()
        try:
            camera.ExposureTime.SetValue(float(exposure_us))
        except Exception as exc:
            raise BaslerCameraError(f"设置曝光时间失败：{exc}") from exc

    def get_exposure_us(self) -> float:
        return float(self._require_camera().ExposureTime.GetValue())

    def grab_image(self, timeout_ms: int = 5000) -> np.ndarray:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms 必须大于 0")
        camera = self._require_camera()
        result = camera.GrabOne(timeout_ms)
        try:
            if not result.GrabSucceeded():
                raise BaslerCameraError(
                    f"采图失败：code={result.GetErrorCode()}, "
                    f"message={result.GetErrorDescription()}"
                )
            # copy() 很重要：Release() 后 pypylon 管理的缓冲区会被复用。
            return np.asarray(result.Array).copy()
        finally:
            result.Release()

    def start_grabbing(self) -> None:
        camera = self._require_camera()
        if not camera.IsGrabbing():
            camera.StartGrabbing()

    def stop_grabbing(self) -> None:
        camera = self._require_camera()
        if camera.IsGrabbing():
            camera.StopGrabbing()

