"""位移台的统一抽象接口。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod


class StageBase(ABC):
    """所有真实或模拟位移台都要实现的最小接口。

    这里使用抽象基类（ABC），相当于给上层代码规定了一组“接线端子”。
    ScanController 不需要知道背后是 GAS.dll 还是真实设备之外的 Mock。
    """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """设备会话当前是否已经建立。"""

    @abstractmethod
    def connect(self) -> None:
        """建立设备会话，但不应隐式移动或清零。"""

    @abstractmethod
    def disconnect(self) -> None:
        """释放设备会话。"""

    @abstractmethod
    def get_position(self) -> float:
        """返回上层扫描坐标；真实 DimensionStage 明确为 mm，Mock 为 mock unit。"""

    @abstractmethod
    def move_absolute(self, position: float) -> None:
        """开始绝对位置运动；真实 DimensionStage 的参数明确为 mm。"""

    def move_relative(self, distance: float) -> None:
        """相对移动由“读取当前位置 + 绝对移动”组合而成。"""
        self.move_absolute(self.get_position() + distance)

    @abstractmethod
    def is_moving(self) -> bool:
        """返回设备是否仍在执行最近一次运动。"""

    @abstractmethod
    def stop(self) -> None:
        """立即停止运动；真实 Adapter 必须有已确认的厂家 API 才能实现。"""

    @abstractmethod
    def home(self) -> None:
        """执行回零；真实 Adapter 必须有已确认的厂家 API 才能实现。"""

    def wait_until_idle(
        self,
        *,
        target_position: float,
        tolerance: float,
        timeout_s: float,
        poll_interval_s: float = 0.02,
    ) -> float:
        """轮询运动状态和位置，确认到位后返回最终位置。

        settling time 不在这里处理。它表示机械到位后的额外稳定时间，应该由
        ScanController 在本方法成功返回以后单独等待。
        """
        if tolerance < 0:
            raise ValueError("tolerance 不能为负数")
        if timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("timeout_s 和 poll_interval_s 必须大于 0")

        deadline = time.monotonic() + timeout_s
        while True:
            actual = self.get_position()
            if not self.is_moving() and abs(actual - target_position) <= tolerance:
                return actual
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"位移台在 {timeout_s:.3f} s 内未到位："
                    f"target={target_position}, actual={actual}, tolerance={tolerance}"
                )
            time.sleep(poll_interval_s)
