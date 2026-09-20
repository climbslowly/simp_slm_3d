"""仅供 GUI-M1 使用的线程安全三轴模拟位移台。"""

from __future__ import annotations

import math
import threading
import time


class MockXYZStage:
    axes = ("X", "Y", "Z")

    def __init__(self, *, speed_mm_s: float = 20.0) -> None:
        if not math.isfinite(speed_mm_s) or speed_mm_s <= 0:
            raise ValueError("Mock 速度必须是有限正数")
        self._speed = float(speed_mm_s)
        self._positions = {axis: 0.0 for axis in self.axes}
        self._starts = dict(self._positions)
        self._targets = dict(self._positions)
        self._motion_start = 0.0
        self._motion_end = 0.0
        self._connected = False
        self._lock = threading.RLock()
        self.move_command_count = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self.stop()
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MockXYZStage 尚未连接")

    def _update(self) -> None:
        now = time.monotonic()
        if now >= self._motion_end:
            self._positions = dict(self._targets)
            return
        duration = self._motion_end - self._motion_start
        fraction = 1.0 if duration <= 0 else (now - self._motion_start) / duration
        fraction = min(1.0, max(0.0, fraction))
        self._positions = {
            axis: self._starts[axis] + fraction * (self._targets[axis] - self._starts[axis])
            for axis in self.axes
        }

    def get_positions(self) -> dict[str, float]:
        self._require_connected()
        with self._lock:
            self._update()
            return dict(self._positions)

    def move_absolute(self, targets_mm: dict[str, float]) -> None:
        self._require_connected()
        if set(targets_mm) != set(self.axes):
            raise ValueError("三轴移动必须同时给出 X/Y/Z 目标")
        if not all(math.isfinite(float(value)) for value in targets_mm.values()):
            raise ValueError("目标位置必须是有限数值")
        with self._lock:
            self._update()
            if time.monotonic() < self._motion_end:
                raise RuntimeError("Mock 位移台忙，拒绝堆积新的移动命令")
            self._starts = dict(self._positions)
            self._targets = {axis: float(targets_mm[axis]) for axis in self.axes}
            distance = max(abs(self._targets[a] - self._starts[a]) for a in self.axes)
            self._motion_start = time.monotonic()
            self._motion_end = self._motion_start + distance / self._speed
            self.move_command_count += 1

    def move_axis_relative(self, axis: str, delta_mm: float) -> None:
        positions = self.get_positions()
        axis = axis.upper()
        if axis not in self.axes:
            raise ValueError("轴必须是 X、Y 或 Z")
        positions[axis] += float(delta_mm)
        self.move_absolute(positions)

    def is_moving(self) -> bool:
        self._require_connected()
        with self._lock:
            self._update()
            return time.monotonic() < self._motion_end

    def stop(self) -> None:
        if not self._connected:
            return
        with self._lock:
            self._update()
            self._targets = dict(self._positions)
            self._motion_end = time.monotonic()

    def device_info(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "mode": "MOCK",
            "position_source": "mock_simulated",
            "unit": "mm (simulation only)",
            "real_motion_enabled": False,
        }
