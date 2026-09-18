"""无需真实硬件即可运行测试和教学演示的 Mock 设备。"""

from .mock_camera import MockCamera
from .mock_stage import MockStage

__all__ = ["MockCamera", "MockStage"]

