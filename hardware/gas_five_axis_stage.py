"""单会话五轴 GAS 位移台，供真实 GUI 使用。

GUI 坐标直接来自控制器规划位置。启动时只读取当前位置，不自动回零；软件范围、单步上限、
控制器软限位和硬限位状态共同约束每条运动命令。
"""

from __future__ import annotations

import ctypes
import math
import threading
import time
from collections.abc import Iterable

from .diagnostic_profile import HardwareDiagnosticProfile
from .dimension_stage import DimensionStage, DimensionStageError
from .stage_safety import AxisCalibration, AxisStatusFlag, StageSafetyError, decode_axis_status


class GasFiveAxisStage:
    axes = ("X", "Y", "Z")
    camera_axes = ("X", "Y")
    AXIS_MAPPING = {
        "camera": {"X": 1, "Y": 2},
        "objective": {"X": 3, "Y": 5, "Z": 4},
    }

    def __init__(
        self,
        profile: HardwareDiagnosticProfile,
        *,
        allow_motion: bool,
        velocity_pulse_per_ms: float = 3.0,
        acceleration_pulse_per_ms2: float = 0.5,
    ) -> None:
        self.profile = profile
        self.allow_motion = bool(allow_motion)
        self.velocity = float(velocity_pulse_per_ms)
        self.acceleration = float(acceleration_pulse_per_ms2)
        if not math.isfinite(self.velocity) or self.velocity <= 0:
            raise ValueError("velocity_pulse_per_ms 必须是有限正数")
        if not math.isfinite(self.acceleration) or self.acceleration <= 0:
            raise ValueError("acceleration_pulse_per_ms2 必须是有限正数")
        required_axes = {1, 2, 3, 4, 5}
        if not required_axes.issubset(profile.axes):
            missing = sorted(required_axes - set(profile.axes))
            raise ValueError(f"真实五轴配置缺少轴：{missing}")
        self._calibrations = {
            axis_id: profile.axes[axis_id].calibration() for axis_id in required_axes
        }
        self._max_steps = {
            axis_id: profile.axes[axis_id].max_single_step_mm
            for axis_id in required_axes
        }
        for axis_id, calibration in self._calibrations.items():
            missing = calibration.missing_for_motion()
            if missing:
                raise ValueError(f"轴 {axis_id} 标定不完整：{', '.join(missing)}")
            if self._max_steps[axis_id] is None:
                raise ValueError(f"轴 {axis_id} 缺少 max_single_step_mm")
        self._dll: ctypes.CDLL | None = None
        self._connected = False
        self._active_targets_pulse: dict[int, int] = {}
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    @staticmethod
    def _check(code: int, function_name: str) -> None:
        if code != 0:
            raise DimensionStageError(f"{function_name} 失败，GAS 错误码：{code}")

    def _require_connected(self) -> ctypes.CDLL:
        if not self._connected or self._dll is None:
            raise DimensionStageError("五轴 GAS 位移台尚未连接")
        return self._dll

    def connect(self) -> None:
        if self._connected:
            return
        dll_path, pc_ip, card_ip = self.profile.require_stage_connection()
        path = dll_path.expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"找不到 GAS.dll：{path}")
        dll = ctypes.CDLL(str(path))
        DimensionStage._bind_confirmed_api(dll)
        self._check(
            dll.GA_OpenByIP(pc_ip.encode("ascii"), card_ip.encode("ascii"), 0, 0),
            "GA_OpenByIP",
        )
        self._dll = dll
        self._connected = True
        try:
            # 真实 GUI 明确获准后，将项目软件范围同步为控制器软限位并启用硬限位输入。
            if self.allow_motion:
                for axis_id in sorted(self._calibrations):
                    calibration = self._calibrations[axis_id]
                    assert calibration.effective_min_mm is not None
                    assert calibration.effective_max_mm is not None
                    pulses = (
                        calibration.mm_to_pulse(calibration.effective_min_mm),
                        calibration.mm_to_pulse(calibration.effective_max_mm),
                    )
                    self._check(
                        dll.GA_SetSoftLimit(axis_id, max(pulses), min(pulses)),
                        "GA_SetSoftLimit",
                    )
                    self._check(dll.GA_LmtsOn(axis_id, -1), "GA_LmtsOn")
            # 连接完成必须能读回五轴位置和状态；不执行 Home/Zero/Reset。
            self.get_all_positions()
            for axis_id in sorted(self._calibrations):
                self._read_status(axis_id)
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        if self._dll is None or not self._connected:
            return
        stop_error: Exception | None = None
        try:
            if self._active_targets_pulse:
                try:
                    self.stop()
                except Exception as exc:
                    stop_error = exc
            self._check(self._dll.GA_Close(), "GA_Close")
        finally:
            self._active_targets_pulse.clear()
            self._connected = False
            self._dll = None
        if stop_error is not None:
            raise stop_error

    def _read_position_pulse(self, axis_id: int) -> float:
        dll = self._require_connected()
        value = ctypes.c_double(0.0)
        self._check(dll.GA_GetPrfPos(axis_id, ctypes.byref(value), 1, None), "GA_GetPrfPos")
        return float(value.value)

    def _read_status(self, axis_id: int) -> int:
        dll = self._require_connected()
        value = ctypes.c_long(0)
        self._check(dll.GA_GetSts(axis_id, ctypes.byref(value), 1, None), "GA_GetSts")
        return int(value.value)

    def _position_mm(self, axis_id: int) -> float:
        return self._calibrations[axis_id].pulse_to_mm(
            self._read_position_pulse(axis_id)
        )

    def _group_positions(self, group: str) -> dict[str, float]:
        return {
            logical_axis: self._position_mm(axis_id)
            for logical_axis, axis_id in self.AXIS_MAPPING[group].items()
        }

    def get_positions(self) -> dict[str, float]:
        return self._group_positions("objective")

    def get_camera_positions(self) -> dict[str, float]:
        return self._group_positions("camera")

    def get_all_positions(self) -> dict[str, dict[str, float]]:
        return {"camera": self.get_camera_positions(), "objective": self.get_positions()}

    def _target_errors(
        self, axis_id: int, target_mm: float, current_mm: float, raw_status: int
    ) -> list[str]:
        calibration = self._calibrations[axis_id]
        errors = calibration.target_errors(target_mm)
        max_step = self._max_steps[axis_id]
        assert max_step is not None
        if abs(target_mm - current_mm) > max_step + 1e-12:
            errors.append(
                f"单步 {abs(target_mm-current_mm):.6f} mm 超过轴 {axis_id} 上限 {max_step} mm"
            )
        decoded = decode_axis_status(raw_status)
        flags = AxisStatusFlag(raw_status & 0xFFFFFFFF)
        always_block = (
            AxisStatusFlag.ESTOP
            | AxisStatusFlag.SERVO_ALARM
            | AxisStatusFlag.FOLLOW_ERROR
            | AxisStatusFlag.RESERVED_IO_SMS_STOP
            | AxisStatusFlag.RESERVED_IO_EMG_STOP
        )
        if flags & always_block:
            errors.extend(decoded["safety_faults"])
        if decoded["running"]:
            errors.append("轴已经在运动")
        if decoded["home_running"]:
            errors.append("轴正在回零")
        if decoded["unknown_bits_hex"] != "0x00000000":
            errors.append(f"轴状态含未知位 {decoded['unknown_bits_hex']}")
        current_pulse = calibration.mm_to_pulse(current_mm)
        target_pulse = calibration.mm_to_pulse(target_mm)
        delta_pulse = target_pulse - current_pulse
        positive_limit = AxisStatusFlag.POSITIVE_SOFT_LIMIT | AxisStatusFlag.POSITIVE_HARD_LIMIT
        negative_limit = AxisStatusFlag.NEGATIVE_SOFT_LIMIT | AxisStatusFlag.NEGATIVE_HARD_LIMIT
        if flags & positive_limit and delta_pulse > 0:
            errors.append("正向限位已触发，拒绝继续正向运动")
        if flags & negative_limit and delta_pulse < 0:
            errors.append("负向限位已触发，拒绝继续负向运动")
        return errors

    def _move_group_absolute(self, group: str, targets_mm: dict[str, float]) -> None:
        if not self.allow_motion:
            raise StageSafetyError("真实 GUI 运动未显式启用")
        mapping = self.AXIS_MAPPING[group]
        if set(targets_mm) != set(mapping):
            raise ValueError(f"{group} 移动必须同时给出 {'/'.join(mapping)} 目标")
        if not all(math.isfinite(float(value)) for value in targets_mm.values()):
            raise ValueError("目标位置必须是有限数值")
        with self._lock:
            if self.is_moving():
                raise StageSafetyError("位移台正在运动，拒绝堆积新命令")
            dll = self._require_connected()
            prepared: list[tuple[int, int]] = []
            errors: list[str] = []
            for logical_axis, axis_id in mapping.items():
                target_mm = float(targets_mm[logical_axis])
                current_mm = self._position_mm(axis_id)
                raw_status = self._read_status(axis_id)
                errors.extend(
                    f"{group}.{logical_axis}/轴{axis_id}: {reason}"
                    for reason in self._target_errors(axis_id, target_mm, current_mm, raw_status)
                )
                target_pulse = self._calibrations[axis_id].mm_to_pulse(target_mm)
                if abs(target_pulse - self._read_position_pulse(axis_id)) >= 1.0:
                    prepared.append((axis_id, target_pulse))
            if errors:
                raise StageSafetyError("真实运动被安全门拒绝：\n- " + "\n- ".join(errors))
            if not prepared:
                return
            mask = 0
            for axis_id, target_pulse in prepared:
                self._check(dll.GA_AxisOn(axis_id), "GA_AxisOn")
                self._check(dll.GA_PrfTrap(axis_id), "GA_PrfTrap")
                self._check(
                    dll.GA_SetTrapPrmSingle(
                        axis_id, self.acceleration, self.acceleration, 0.0, 0
                    ),
                    "GA_SetTrapPrmSingle",
                )
                self._check(dll.GA_SetPos(axis_id, target_pulse), "GA_SetPos")
                self._check(dll.GA_SetVel(axis_id, self.velocity), "GA_SetVel")
                mask |= 1 << (axis_id - 1)
            self._active_targets_pulse = dict(prepared)
            try:
                self._check(dll.GA_Update(mask), "GA_Update")
            except Exception:
                self._active_targets_pulse.clear()
                raise

    def move_absolute(self, targets_mm: dict[str, float]) -> None:
        self._move_group_absolute("objective", targets_mm)

    def move_camera_absolute(self, targets_mm: dict[str, float]) -> None:
        self._move_group_absolute("camera", targets_mm)

    def is_moving(self) -> bool:
        if not self._active_targets_pulse:
            return False
        running = False
        arrived = True
        for axis_id, target_pulse in self._active_targets_pulse.items():
            raw_status = self._read_status(axis_id)
            decoded = decode_axis_status(raw_status)
            flags = AxisStatusFlag(raw_status & 0xFFFFFFFF)
            always_block = (
                AxisStatusFlag.ESTOP
                | AxisStatusFlag.SERVO_ALARM
                | AxisStatusFlag.FOLLOW_ERROR
                | AxisStatusFlag.RESERVED_IO_SMS_STOP
                | AxisStatusFlag.RESERVED_IO_EMG_STOP
            )
            current_pulse = self._read_position_pulse(axis_id)
            delta_pulse = target_pulse - current_pulse
            directional_block = (
                bool(flags & (AxisStatusFlag.POSITIVE_SOFT_LIMIT | AxisStatusFlag.POSITIVE_HARD_LIMIT))
                and delta_pulse > 0
            ) or (
                bool(flags & (AxisStatusFlag.NEGATIVE_SOFT_LIMIT | AxisStatusFlag.NEGATIVE_HARD_LIMIT))
                and delta_pulse < 0
            )
            if (
                flags & always_block
                or directional_block
                or decoded["home_running"]
                or decoded["unknown_bits_hex"] != "0x00000000"
            ):
                raise StageSafetyError(f"轴 {axis_id} 运动状态异常：{decoded}")
            running = running or bool(decoded["running"])
            arrived = arrived and abs(current_pulse - target_pulse) < 1.0
        if not running and arrived:
            self._active_targets_pulse.clear()
            return False
        return True

    def stop(self) -> None:
        if not self._connected:
            return
        active_axes = tuple(self._active_targets_pulse)
        mask = sum(1 << (axis_id - 1) for axis_id in active_axes)
        if mask:
            self._check(self._require_connected().GA_Stop(mask, 0), "GA_Stop")
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if not any(
                    decode_axis_status(self._read_status(axis_id))["running"]
                    for axis_id in active_axes
                ):
                    break
                time.sleep(0.01)
            else:
                raise StageSafetyError("GA_Stop 后 2 秒内运动状态未清除")
        self._active_targets_pulse.clear()

    @property
    def objective_bounds_mm(self) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        for logical_axis, axis_id in self.AXIS_MAPPING["objective"].items():
            calibration = self._calibrations[axis_id]
            assert calibration.effective_min_mm is not None
            assert calibration.effective_max_mm is not None
            result[logical_axis] = [calibration.effective_min_mm, calibration.effective_max_mm]
        return result

    def plan_errors(self, points: Iterable[object]) -> list[str]:
        previous = self.get_positions()
        errors: list[str] = []
        for index, point in enumerate(points, start=1):
            targets = getattr(point, "targets_mm")
            for logical_axis, axis_id in self.AXIS_MAPPING["objective"].items():
                target = float(targets[logical_axis])
                errors.extend(
                    f"point {index} / {logical_axis}: {reason}"
                    for reason in self._calibrations[axis_id].target_errors(target)
                )
                max_step = self._max_steps[axis_id]
                assert max_step is not None
                if abs(target - previous[logical_axis]) > max_step + 1e-12:
                    errors.append(
                        f"point {index} / {logical_axis}: 相邻命令步长 "
                        f"{abs(target-previous[logical_axis]):.6f} mm 超过 {max_step} mm"
                    )
            previous = {axis: float(targets[axis]) for axis in self.axes}
        return errors

    def device_info(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "mode": "REAL_OPEN_LOOP",
            "position_source": "GA_GetPrfPos planned position",
            "encoder_required": False,
            "automatic_home": False,
            "soft_limits_written_on_connect": self.allow_motion,
            "hard_limits_enabled_on_connect": self.allow_motion,
            "max_single_step_mm": self._max_steps,
            "axis_mapping": self.AXIS_MAPPING,
            "positions_at_query": self.get_all_positions(),
        }
