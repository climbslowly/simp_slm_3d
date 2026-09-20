"""Basler pypylon Adapter。pypylon 采用延迟导入，Mock 测试无需安装它。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .camera_base import CameraBase


class BaslerCameraError(RuntimeError):
    pass


@dataclass(frozen=True)
class BaslerDeviceInfo:
    """pylon 统一枚举返回的一台相机。

    ``transport_layer_type`` 可用于区分 USB、GigE 和通过 GenTL 暴露的 CXP
    设备。这里的 ``index`` 只供本次命令行选择，真正连接仍使用稳定的序列号。
    """

    index: int
    serial_number: str
    model_name: str
    vendor_name: str
    transport_layer_type: str
    device_class: str
    interface_id: str
    friendly_name: str
    full_name: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_pylon() -> Any:
    try:
        from pypylon import pylon
    except ImportError as exc:
        raise BaslerCameraError(
            "未安装 pypylon。请在项目环境运行：pip install pypylon"
        ) from exc
    return pylon


def _device_text(device: Any, getter_name: str) -> str:
    """兼容不同 pylon transport layer 可能缺失的设备信息字段。"""
    getter = getattr(device, getter_name, None)
    if getter is None:
        return ""
    try:
        value = getter()
    except Exception:
        return ""
    return "" if value is None else str(value)


def enumerate_basler_cameras() -> list[BaslerDeviceInfo]:
    """枚举 pylon 当前可见的全部设备，不限定 USB/GigE/CXP 接口。

    pylon 的 ``TlFactory.EnumerateDevices()`` 会查询所有已经安装并注册的 transport
    layer。CXP 相机能否出现取决于对应采集卡、驱动和 GenTL producer 是否已安装。
    """
    pylon = _load_pylon()
    factory = pylon.TlFactory.GetInstance()
    devices: list[BaslerDeviceInfo] = []
    for index, device in enumerate(factory.EnumerateDevices()):
        devices.append(
            BaslerDeviceInfo(
                index=index,
                serial_number=_device_text(device, "GetSerialNumber"),
                model_name=_device_text(device, "GetModelName"),
                vendor_name=_device_text(device, "GetVendorName"),
                transport_layer_type=_device_text(device, "GetTLType"),
                device_class=_device_text(device, "GetDeviceClass"),
                interface_id=_device_text(device, "GetInterfaceID"),
                friendly_name=_device_text(device, "GetFriendlyName"),
                full_name=_device_text(device, "GetFullName"),
            )
        )
    return devices


def select_basler_camera(index: int) -> BaslerDeviceInfo:
    """按刚刚显示的零起始序号选择相机，并验证其序列号可用于稳定连接。"""
    devices = enumerate_basler_cameras()
    if not devices:
        raise BaslerCameraError(
            "未发现任何 pylon 相机；请检查相机供电、线缆、采集卡、pylon 驱动和 GenTL transport layer"
        )
    if index < 0 or index >= len(devices):
        raise BaslerCameraError(
            f"相机序号 {index} 超出范围；当前有效范围为 0..{len(devices) - 1}"
        )
    selected = devices[index]
    if not selected.serial_number:
        raise BaslerCameraError(
            f"序号 {index} 的设备没有报告序列号，当前安全连接方式无法唯一绑定该设备"
        )
    return selected


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
