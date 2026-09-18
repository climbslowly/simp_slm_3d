"""Basler 多相机枚举与生命周期管理。"""

from __future__ import annotations

from collections.abc import Iterable

from .basler_camera import BaslerCamera, _load_pylon
from .camera_base import CameraBase, CameraInfo


class CameraManager:
    def __init__(self, cameras: Iterable[CameraBase] = ()) -> None:
        self._cameras = {camera.get_serial_number(): camera for camera in cameras}

    @staticmethod
    def enumerate_basler() -> list[CameraInfo]:
        """枚举设备但不打开相机。"""
        pylon = _load_pylon()
        devices = pylon.TlFactory.GetInstance().EnumerateDevices()
        return [
            CameraInfo(
                serial_number=str(device.GetSerialNumber()),
                model_name=str(device.GetModelName()),
            )
            for device in devices
        ]

    def connect_serials(self, serial_numbers: Iterable[str]) -> None:
        """按序列号连接；若中途失败，已打开的相机保持在 manager 中便于统一释放。"""
        for serial in serial_numbers:
            camera = self._cameras.get(serial)
            if camera is None:
                camera = BaslerCamera(serial)
                self._cameras[serial] = camera
            camera.connect()

    def add(self, camera: CameraBase) -> None:
        serial = camera.get_serial_number()
        if serial in self._cameras:
            raise ValueError(f"相机序列号重复：{serial}")
        self._cameras[serial] = camera

    def get(self, serial_number: str) -> CameraBase:
        try:
            return self._cameras[serial_number]
        except KeyError as exc:
            raise KeyError(f"CameraManager 中没有相机 {serial_number}") from exc

    def connected_cameras(self) -> dict[str, CameraBase]:
        return {
            serial: camera
            for serial, camera in self._cameras.items()
            if camera.is_connected
        }

    def disconnect_all(self) -> None:
        errors: list[Exception] = []
        for camera in self._cameras.values():
            try:
                camera.disconnect()
            except Exception as exc:  # 释放其余相机比立刻退出更重要
                errors.append(exc)
        if errors:
            raise RuntimeError(f"断开相机时发生 {len(errors)} 个错误：{errors}")

