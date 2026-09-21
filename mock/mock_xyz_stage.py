"""GUI-M1 的线程安全五轴模拟位移台。

兼容原有物镜 ``X/Y/Z`` API，同时增加探测相机 ``X/Y``。这里的 X/Y/Z 是
光学逻辑坐标；控制器轴号及方向来自现场人工观察，Mock 本身不连接真实控制器。
"""

from __future__ import annotations

import math
import threading
import time


class MockXYZStage:
    """五轴 Mock；类名保留以兼容已有 GUI-M1 代码和历史测试。"""

    axes = ("X", "Y", "Z")
    camera_axes = ("X", "Y")
    _OBJECTIVE_KEYS = {"X": "objective_X", "Y": "objective_Y", "Z": "objective_Z"}
    _CAMERA_KEYS = {"X": "camera_X", "Y": "camera_Y"}

    # 轴身份和方向来自操作者使用官方控制软件的现场观察；标定、行程和安全 API 仍未知。
    AXIS_MAPPING = {
        "camera": {
            "X": {
                "controller_axis": 1, "optical_role": "transverse_x", "physical_axis": "Y",
                "controller_positive_physical_direction": "+Y",
                "controller_sign_for_gui_positive": 1,
            },
            "Y": {
                "controller_axis": 2, "optical_role": "transverse_y", "physical_axis": "Z",
                "controller_positive_physical_direction": "-Z",
                "controller_sign_for_gui_positive": -1,
            },
        },
        "objective": {
            "X": {
                "controller_axis": 3, "optical_role": "transverse_x", "physical_axis": "Y",
                "controller_positive_physical_direction": "+Y",
                "controller_sign_for_gui_positive": 1,
            },
            "Y": {
                "controller_axis": 5, "optical_role": "transverse_y", "physical_axis": "Z",
                "controller_positive_physical_direction": "-Z",
                "controller_sign_for_gui_positive": -1,
            },
            "Z": {
                "controller_axis": 4, "optical_role": "propagation_axis", "physical_axis": "X",
                "controller_positive_physical_direction": "+X",
                "controller_sign_for_gui_positive": 1,
                "controller_positive_optical_direction": "against_propagation",
                "controller_positive_mechanical_observation": "objective_forward",
            },
        },
    }

    def __init__(self, *, speed_mm_s: float = 20.0) -> None:
        if not math.isfinite(speed_mm_s) or speed_mm_s <= 0:
            raise ValueError("Mock 速度必须是有限正数")
        self._speed = float(speed_mm_s)
        keys = (*self._CAMERA_KEYS.values(), *self._OBJECTIVE_KEYS.values())
        self._positions = {key: 0.0 for key in keys}
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
            for axis in self._positions
        }

    def _group_positions(self, keys: dict[str, str]) -> dict[str, float]:
        self._require_connected()
        with self._lock:
            self._update()
            return {axis: self._positions[key] for axis, key in keys.items()}

    def get_positions(self) -> dict[str, float]:
        """返回物镜逻辑 X/Y/Z；保留原有扫描控制器接口。"""
        return self._group_positions(self._OBJECTIVE_KEYS)

    def get_camera_positions(self) -> dict[str, float]:
        return self._group_positions(self._CAMERA_KEYS)

    def get_all_positions(self) -> dict[str, dict[str, float]]:
        return {"camera": self.get_camera_positions(), "objective": self.get_positions()}

    def get_signal_positions(self) -> dict[str, float]:
        """生成 Mock 光斑的位置：物镜横向位置相对探测相机位置。"""
        self._require_connected()
        with self._lock:
            self._update()
            return {
                "X": self._positions["objective_X"] - self._positions["camera_X"],
                "Y": self._positions["objective_Y"] - self._positions["camera_Y"],
                "Z": self._positions["objective_Z"],
            }

    def _move_group_absolute(self, targets_mm: dict[str, float], keys: dict[str, str], group_name: str) -> None:
        self._require_connected()
        if set(targets_mm) != set(keys):
            expected = "/".join(keys)
            raise ValueError(f"{group_name}移动必须同时给出 {expected} 目标")
        if not all(math.isfinite(float(value)) for value in targets_mm.values()):
            raise ValueError("目标位置必须是有限数值")
        with self._lock:
            self._update()
            if time.monotonic() < self._motion_end:
                raise RuntimeError("Mock 位移台忙，拒绝堆积新的移动命令")
            self._starts = dict(self._positions)
            self._targets = dict(self._positions)
            for axis, key in keys.items():
                self._targets[key] = float(targets_mm[axis])
            distance = max(abs(self._targets[key] - self._starts[key]) for key in keys.values())
            self._motion_start = time.monotonic()
            self._motion_end = self._motion_start + distance / self._speed
            self.move_command_count += 1

    def move_absolute(self, targets_mm: dict[str, float]) -> None:
        """移动物镜逻辑 X/Y/Z。"""
        self._move_group_absolute(targets_mm, self._OBJECTIVE_KEYS, "物镜三轴")

    def move_camera_absolute(self, targets_mm: dict[str, float]) -> None:
        """移动探测相机逻辑 X/Y。"""
        self._move_group_absolute(targets_mm, self._CAMERA_KEYS, "相机两轴")

    def move_axis_relative(self, axis: str, delta_mm: float) -> None:
        positions = self.get_positions()
        axis = axis.upper()
        if axis not in self.axes:
            raise ValueError("物镜轴必须是 X、Y 或 Z")
        positions[axis] += float(delta_mm)
        self.move_absolute(positions)

    def move_camera_axis_relative(self, axis: str, delta_mm: float) -> None:
        positions = self.get_camera_positions()
        axis = axis.upper()
        if axis not in self.camera_axes:
            raise ValueError("相机轴必须是 X 或 Y")
        positions[axis] += float(delta_mm)
        self.move_camera_absolute(positions)

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
            "adapter": "MockFiveAxisStage",
            "mode": "MOCK",
            "position_source": "mock_simulated",
            "unit": "mm (simulation only)",
            "real_motion_enabled": False,
            "axis_mapping_id": "five_axis_operator_observed_v1",
            "axis_mapping_status": "operator_observed_axis_identity_and_direction",
            "direction_sign_verified": True,
            "direction_verification_method": "operator_observed_with_official_controller_software",
            "gui_coordinate_convention": "positive_gui_coordinates_follow_positive_physical_axes",
            "axis_mapping": self.AXIS_MAPPING,
            "camera_positions_mm_at_scan_start": self.get_camera_positions(),
            "objective_positions_mm_at_scan_start": self.get_positions(),
        }
