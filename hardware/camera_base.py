"""相机统一接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CameraInfo:
    serial_number: str
    model_name: str


class CameraBase(ABC):
    """Basler 相机和 Mock 相机共同遵守的最小接口。"""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        pass

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def get_serial_number(self) -> str:
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        pass

    @abstractmethod
    def set_exposure_us(self, exposure_us: float) -> None:
        pass

    @abstractmethod
    def get_exposure_us(self) -> float:
        pass

    @abstractmethod
    def grab_image(self, timeout_ms: int = 5000) -> np.ndarray:
        """抓取一帧原始图像；不能为了显示而转换为 8 bit。"""

    @abstractmethod
    def start_grabbing(self) -> None:
        pass

    @abstractmethod
    def stop_grabbing(self) -> None:
        pass

