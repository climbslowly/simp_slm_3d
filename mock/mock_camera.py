"""生成二维 Gaussian 光斑和少量噪声的模拟相机。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import threading
import time

import numpy as np

from hardware.camera_base import CameraBase


class MockCamera(CameraBase):
    def __init__(
        self,
        serial_number: str = "MOCK-001",
        model_name: str = "Gaussian Spot Simulator",
        shape: tuple[int, int] = (256, 320),
        exposure_us: float = 1000.0,
        seed: int = 1,
        position_provider: Callable[[], float | Mapping[str, float]] | None = None,
        capture_delay_s: float = 0.0,
    ) -> None:
        if len(shape) != 2 or min(shape) <= 0:
            raise ValueError("shape 必须是两个正整数")
        if not np.isfinite(capture_delay_s) or capture_delay_s < 0:
            raise ValueError("capture_delay_s 必须是有限非负数")
        self._serial = serial_number
        self._model = model_name
        self._shape = shape
        self._exposure_us = float(exposure_us)
        self._rng = np.random.default_rng(seed)
        self._position_provider = position_provider
        self._capture_delay_s = float(capture_delay_s)
        self._connected = False
        self._grabbing = False

    @property
    def image_shape(self) -> tuple[int, int]:
        return self._shape

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._grabbing = False
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MockCamera 尚未连接")

    def get_serial_number(self) -> str:
        return self._serial

    def get_model_name(self) -> str:
        return self._model

    def set_exposure_us(self, exposure_us: float) -> None:
        self._require_connected()
        if not np.isfinite(exposure_us) or exposure_us <= 0:
            raise ValueError("曝光时间必须是有限正数")
        self._exposure_us = float(exposure_us)

    def get_exposure_us(self) -> float:
        self._require_connected()
        return self._exposure_us

    def grab_image_interruptible(
        self, stop_event: threading.Event, timeout_ms: int = 5000
    ) -> np.ndarray:
        deadline = time.monotonic() + self._capture_delay_s
        while time.monotonic() < deadline:
            if stop_event.wait(min(0.02, max(0.0, deadline - time.monotonic()))):
                raise InterruptedError("Mock 采集已取消")
        return self.grab_image(timeout_ms=timeout_ms)

    def grab_image(self, timeout_ms: int = 5000) -> np.ndarray:
        self._require_connected()
        if timeout_ms <= 0:
            raise ValueError("timeout_ms 必须大于 0")

        height, width = self._shape
        yy, xx = np.mgrid[0:height, 0:width]
        raw_position = self._position_provider() if self._position_provider else 0.0
        if isinstance(raw_position, Mapping):
            x_mm = float(raw_position.get("X", 0.0))
            y_mm = float(raw_position.get("Y", 0.0))
            z_mm = float(raw_position.get("Z", 0.0))
        else:
            x_mm, y_mm, z_mm = float(raw_position), 0.0, 0.0
        # 非对称且可复现：三轴分别影响横向、纵向和幅值，便于发现行列交换。
        center_x = width * (0.46 + 0.16 * np.sin(x_mm * 1.7 + z_mm * 0.2))
        center_y = height * (0.51 + 0.13 * np.cos(y_mm * 1.3 - z_mm * 0.4))
        sigma = min(height, width) * 0.09
        gaussian = np.exp(
            -((xx - center_x) ** 2 + (yy - center_y) ** 2) / (2 * sigma**2)
        )
        exposure_scale = min(self._exposure_us / 1000.0, 5.0)
        spatial_scale = 0.42 + 0.42 * np.exp(
            -((x_mm - 0.35) ** 2 / 0.22 + (y_mm + 0.2) ** 2 / 0.5)
        ) + 0.08 * np.sin(z_mm * 1.1)
        signal = gaussian * 50000.0 * exposure_scale * spatial_scale
        noise = self._rng.normal(loc=300.0, scale=80.0, size=self._shape)
        return np.clip(signal + noise, 0, 65535).astype(np.uint16)

    def start_grabbing(self) -> None:
        self._require_connected()
        self._grabbing = True

    def stop_grabbing(self) -> None:
        self._require_connected()
        self._grabbing = False
