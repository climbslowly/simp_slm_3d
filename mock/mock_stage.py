"""具有真实时间延迟的单轴模拟位移台。"""

from __future__ import annotations

import math
import threading
import time

from hardware.stage_base import StageBase


class MockStage(StageBase):
    def __init__(
        self,
        initial_position: float = 0.0,
        speed_units_per_s: float = 100.0,
        software_min: float | None = None,
        software_max: float | None = None,
    ) -> None:
        if speed_units_per_s <= 0:
            raise ValueError("speed_units_per_s 必须大于 0")
        self._position = float(initial_position)
        self._start_position = self._position
        self._target_position = self._position
        self._motion_start = 0.0
        self._motion_end = 0.0
        self._speed = float(speed_units_per_s)
        self.software_min = software_min
        self.software_max = software_max
        self._connected = False
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def _require_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("MockStage 尚未连接")

    def _update_position(self) -> None:
        now = time.monotonic()
        if now >= self._motion_end:
            self._position = self._target_position
            return
        if self._motion_end <= self._motion_start:
            return
        fraction = (now - self._motion_start) / (self._motion_end - self._motion_start)
        fraction = max(0.0, min(1.0, fraction))
        self._position = self._start_position + fraction * (
            self._target_position - self._start_position
        )

    def get_position(self) -> float:
        self._require_connected()
        with self._lock:
            self._update_position()
            return self._position

    def move_absolute(self, position: float) -> None:
        self._require_connected()
        if not math.isfinite(position):
            raise ValueError("目标位置必须是有限数值")
        if self.software_min is not None and position < self.software_min:
            raise ValueError("目标位置低于 MockStage 软件下限")
        if self.software_max is not None and position > self.software_max:
            raise ValueError("目标位置高于 MockStage 软件上限")
        with self._lock:
            self._update_position()
            self._start_position = self._position
            self._target_position = float(position)
            self._motion_start = time.monotonic()
            duration = abs(self._target_position - self._start_position) / self._speed
            self._motion_end = self._motion_start + duration

    def is_moving(self) -> bool:
        self._require_connected()
        with self._lock:
            self._update_position()
            return time.monotonic() < self._motion_end

    def stop(self) -> None:
        self._require_connected()
        with self._lock:
            self._update_position()
            self._target_position = self._position
            self._motion_end = time.monotonic()

    def home(self) -> None:
        self.move_absolute(0.0)

    def device_info(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "unit": "mock_unit",
            "software_min": self.software_min,
            "software_max": self.software_max,
        }

