"""硬件抽象层：上层扫描代码只依赖这里定义的统一接口。"""

from .camera_base import CameraBase, CameraInfo
from .stage_safety import AxisCalibration, StageCapabilities
from .stage_base import StageBase

__all__ = [
    "AxisCalibration",
    "CameraBase",
    "CameraInfo",
    "StageBase",
    "StageCapabilities",
]
