"""维度/固高运动控制器 GAS.dll 的安全 Adapter。

坐标分为三层：上层扫描只使用物理坐标 mm；GAS 控制器使用 pulse/count；最底层
才是 ctypes DLL 调用。已按手册实现的 Stop、限位读取和状态 bit 仍保留实机验收边界；
尚未确认现场流程的 Home 不会被猜测执行。
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from .stage_base import StageBase
from .stage_safety import (
    CURRENT_GAS_CAPABILITIES,
    AxisStatusFlag,
    AxisCalibration,
    StageCapabilities,
    StageSafetyError,
    UnsupportedStageOperation,
    axis_status_motion_errors,
    decode_axis_status,
)


class DimensionStageError(RuntimeError):
    """GAS.dll 返回非零错误码或设备会话错误。"""


class StageAccessLevel(IntEnum):
    """真实设备访问级别；数值大小不能被当成自动升级权限。"""

    UNLOADED = -1
    DLL_LOADED = 0
    READ_ONLY_CONNECTED = 1
    MOTION_READY = 2


@dataclass(frozen=True)
class DimensionStageConfig:
    """真实位移台连接、标定和运动安全配置。

    ``healthy_raw_status_values`` 是旧配置兼容字段；当前安全门依据厂家手册逐位判断，
    不再要求 raw status 完整值与某个固定白名单完全相等。
    """

    dll_path: Path
    # GAS 官方示例与随附控制软件 ComParam.xml 均表明：GA_OpenByIP 的第一个
    # 参数是实验电脑网卡 IP（PCIP），第二个参数是运动卡 IP（CardIP）。
    pc_ip: str | None = None
    card_ip: str | None = None
    calibration: AxisCalibration = field(default_factory=AxisCalibration)
    capabilities: StageCapabilities = CURRENT_GAS_CAPABILITIES
    velocity_pulse_per_ms: float = 7.5
    acceleration_pulse_per_ms2: float = 1.0
    deceleration_pulse_per_ms2: float = 1.0
    smooth_time: float = 0.0
    allow_motion: bool = False
    position_tolerance_pulse: float = 1.0
    healthy_raw_status_values: frozenset[int] | None = None

    def __post_init__(self) -> None:
        positive_values = {
            "velocity_pulse_per_ms": self.velocity_pulse_per_ms,
            "acceleration_pulse_per_ms2": self.acceleration_pulse_per_ms2,
            "deceleration_pulse_per_ms2": self.deceleration_pulse_per_ms2,
            "position_tolerance_pulse": self.position_tolerance_pulse,
        }
        for name, value in positive_values.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是有限正数")


class DimensionStage(StageBase):
    """GAS.dll 单轴 Adapter，StageBase 暴露的坐标在本类中始终表示 mm。

    `connect()` 只打开通信会话。它不会 Reset、清零、使能、Home 或移动。
    不知道 pulse/mm 时仍可调用 `get_position_pulse()` 做只读 bring-up，但不能调用
    StageBase 的 `get_position()`，避免上层把 pulse 误认为 mm。
    """

    def __init__(self, config: DimensionStageConfig) -> None:
        self.config = config
        self._dll: ctypes.CDLL | None = None
        self._connected = False
        self._last_target_mm: float | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def access_level(self) -> StageAccessLevel:
        if not self._connected:
            return (
                StageAccessLevel.DLL_LOADED
                if self._dll is not None
                else StageAccessLevel.UNLOADED
            )
        if not self.motion_readiness_errors(check_live_status=False):
            return StageAccessLevel.MOTION_READY
        return StageAccessLevel.READ_ONLY_CONNECTED

    @property
    def software_min(self) -> float | None:
        """供现有 ScanController Preflight 读取，单位明确为 mm。"""
        return self.config.calibration.effective_min_mm

    @property
    def software_max(self) -> float | None:
        return self.config.calibration.effective_max_mm

    @staticmethod
    def _bind_confirmed_api(dll: ctypes.CDLL) -> None:
        """仅绑定厂家示例或 ETH_GAS_N V7.3 手册已确认签名的函数。"""
        dll.GA_OpenByIP.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        dll.GA_OpenByIP.restype = ctypes.c_int
        dll.GA_Close.argtypes = []
        dll.GA_Close.restype = ctypes.c_int
        dll.GA_GetPrfPos.argtypes = [
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        dll.GA_GetPrfPos.restype = ctypes.c_int
        dll.GA_GetSts.argtypes = [
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_long),
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        dll.GA_GetSts.restype = ctypes.c_int
        dll.GA_GetAxisEncPos.argtypes = [
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        dll.GA_GetAxisEncPos.restype = ctypes.c_int
        dll.GA_GetSoftLimit.argtypes = [
            ctypes.c_short,
            ctypes.POINTER(ctypes.c_long),
            ctypes.POINTER(ctypes.c_long),
        ]
        dll.GA_GetSoftLimit.restype = ctypes.c_int
        dll.GA_Stop.argtypes = [ctypes.c_long, ctypes.c_long]
        dll.GA_Stop.restype = ctypes.c_int
        dll.GA_AxisOn.argtypes = [ctypes.c_short]
        dll.GA_AxisOn.restype = ctypes.c_int
        dll.GA_PrfTrap.argtypes = [ctypes.c_short]
        dll.GA_PrfTrap.restype = ctypes.c_int
        dll.GA_SetTrapPrmSingle.argtypes = [
            ctypes.c_short,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_short,
        ]
        dll.GA_SetTrapPrmSingle.restype = ctypes.c_int
        dll.GA_SetPos.argtypes = [ctypes.c_short, ctypes.c_int64]
        dll.GA_SetPos.restype = ctypes.c_int
        dll.GA_SetVel.argtypes = [ctypes.c_short, ctypes.c_double]
        dll.GA_SetVel.restype = ctypes.c_int
        dll.GA_Update.argtypes = [ctypes.c_long]
        dll.GA_Update.restype = ctypes.c_int

    def _load_library(self) -> ctypes.CDLL:
        dll_path = self.config.dll_path.expanduser().resolve()
        if not dll_path.is_file():
            raise FileNotFoundError(f"找不到 GAS.dll：{dll_path}")
        dll = ctypes.CDLL(str(dll_path))
        self._bind_confirmed_api(dll)
        return dll

    def load_library(self) -> None:
        """Level 0：只加载 DLL，不连接控制器。"""
        if self._dll is None:
            self._dll = self._load_library()

    @staticmethod
    def _check(code: int, function_name: str) -> None:
        if code != 0:
            raise DimensionStageError(f"{function_name} 失败，GAS 错误码：{code}")

    def _require_connected(self) -> ctypes.CDLL:
        if not self._connected or self._dll is None:
            raise DimensionStageError("位移台尚未连接")
        return self._dll

    def _axis_id(self) -> int:
        axis_id = self.config.calibration.axis_id
        if axis_id is None:
            raise StageSafetyError("axis_id 未确认，不能访问轴数据")
        return axis_id

    def connect(self) -> None:
        """Level 1：建立只读会话；本方法不含任何运动或状态修改 API。"""
        if self._connected:
            return
        if not self.config.pc_ip or not self.config.card_ip:
            raise StageSafetyError(
                "pc_ip 和 card_ip 必须由现场确认后显式配置，禁止猜测网络参数"
            )
        self.load_library()
        assert self._dll is not None
        code = self._dll.GA_OpenByIP(
            self.config.pc_ip.encode("ascii"),
            self.config.card_ip.encode("ascii"),
            0,
            0,
        )
        self._check(code, "GA_OpenByIP")
        self._connected = True

    def disconnect(self) -> None:
        if not self._connected or self._dll is None:
            return
        try:
            self._check(self._dll.GA_Close(), "GA_Close")
        finally:
            self._connected = False
            self._last_target_mm = None

    def get_position_pulse(self) -> float:
        """读取控制器规划位置原值，单位 pulse/count；不要求 mm 标定。"""
        self.config.capabilities.require("position_read_supported", "读取规划位置")
        dll = self._require_connected()
        position_pulse = ctypes.c_double(0.0)
        self._check(
            dll.GA_GetPrfPos(
                self._axis_id(), ctypes.byref(position_pulse), 1, None
            ),
            "GA_GetPrfPos",
        )
        return position_pulse.value

    def get_encoder_position_pulse(self) -> float:
        """读取编码器/反馈计数位置原值；不改变当前编码器计数模式。"""

        self.config.capabilities.require(
            "encoder_position_read_supported", "读取编码器位置"
        )
        dll = self._require_connected()
        position_pulse = ctypes.c_double(0.0)
        self._check(
            dll.GA_GetAxisEncPos(
                self._axis_id(), ctypes.byref(position_pulse), 1, None
            ),
            "GA_GetAxisEncPos",
        )
        return position_pulse.value

    def get_encoder_position_mm(self) -> float:
        """用已确认标定将编码器/反馈计数位置转换为物理 mm。"""

        return self.config.calibration.pulse_to_mm(
            self.get_encoder_position_pulse()
        )

    def get_soft_limits_pulse(self) -> tuple[int, int]:
        """只读控制器当前配置的正、负软限位，单位 pulse。"""

        self.config.capabilities.require(
            "soft_limit_read_supported", "读取控制器软限位"
        )
        dll = self._require_connected()
        positive = ctypes.c_long(0)
        negative = ctypes.c_long(0)
        self._check(
            dll.GA_GetSoftLimit(
                self._axis_id(), ctypes.byref(positive), ctypes.byref(negative)
            ),
            "GA_GetSoftLimit",
        )
        return int(positive.value), int(negative.value)

    def get_position_mm(self) -> float:
        """读取控制器规划位置并用已确认标定转换为物理 mm。"""
        missing = self.config.calibration.conversion_errors()
        if missing:
            raise StageSafetyError(
                "读取 mm 位置缺少标定项：" + ", ".join(missing)
            )
        return self.config.calibration.pulse_to_mm(self.get_position_pulse())

    def get_position(self) -> float:
        """实现 StageBase；对真实 DimensionStage，该返回值明确为 mm。"""
        return self.get_position_mm()

    def read_raw_status(self) -> int:
        """读取 GA_GetSts 原值；需要解释时使用 read_status()/decode_axis_status。"""
        self.config.capabilities.require("status_read_supported", "读取 raw status")
        dll = self._require_connected()
        raw_status = ctypes.c_long(0)
        self._check(
            dll.GA_GetSts(self._axis_id(), ctypes.byref(raw_status), 1, None),
            "GA_GetSts",
        )
        return int(raw_status.value)

    def read_status(self) -> dict[str, object]:
        """读取并按 ETH_GAS_N V7.3 手册逐位解释轴状态。"""

        return decode_axis_status(self.read_raw_status())

    def motion_readiness_errors(self, *, check_live_status: bool) -> list[str]:
        """汇总 Level 2 的全部阻塞项；默认配置必然无法通过。"""
        errors: list[str] = []
        if not self.config.allow_motion:
            errors.append("allow_motion=False（真实运动未显式启用）")
        if self.config.capabilities.motion_supported is not True:
            errors.append("motion_supported 未确认")
        if self.config.capabilities.position_read_supported is not True:
            errors.append("position_read_supported 未确认")
        if self.config.capabilities.status_read_supported is not True:
            errors.append("status_read_supported 未确认")
        if self.config.capabilities.status_interpretation_supported is not True:
            errors.append("GA_GetSts 状态位含义尚未确认")
        if self.config.capabilities.stop_supported is not True:
            errors.append("Stop API 尚未确认并实现")
        if self.config.capabilities.home_supported is not True:
            errors.append("Home API/流程尚未确认并实现")
        if self.config.capabilities.positive_limit_supported is not True:
            errors.append("正限位读取 API 尚未确认并实现")
        if self.config.capabilities.negative_limit_supported is not True:
            errors.append("负限位读取 API 尚未确认并实现")
        missing = self.config.calibration.missing_for_motion()
        if missing:
            errors.append("轴标定不完整：" + ", ".join(missing))
        axis_id = self.config.calibration.axis_id
        if axis_id is not None and axis_id != 1:
            if self.config.capabilities.multi_axis_start_supported is not True:
                errors.append("非轴 1 的 GA_Update mask 尚未确认")
        if check_live_status:
            if not self._connected:
                errors.append("控制器尚未连接")
            else:
                raw_status = self.read_raw_status()
                errors.extend(axis_status_motion_errors(raw_status))
        return errors

    def _command_absolute_pulse(self, target_pulse: int) -> None:
        """GAS 控制器坐标层；只允许由通过安全门的 mm 方法调用。"""
        dll = self._require_connected()
        axis_id = self._axis_id()
        calls = (
            ("GA_AxisOn", lambda: dll.GA_AxisOn(axis_id)),
            ("GA_PrfTrap", lambda: dll.GA_PrfTrap(axis_id)),
            (
                "GA_SetTrapPrmSingle",
                lambda: dll.GA_SetTrapPrmSingle(
                    axis_id,
                    self.config.acceleration_pulse_per_ms2,
                    self.config.deceleration_pulse_per_ms2,
                    self.config.smooth_time,
                    0,
                ),
            ),
            ("GA_SetPos", lambda: dll.GA_SetPos(axis_id, target_pulse)),
            (
                "GA_SetVel",
                lambda: dll.GA_SetVel(axis_id, self.config.velocity_pulse_per_ms),
            ),
            # ETH_GAS_N V7.3：bit0..bit7 分别启动轴 1..8。
            ("GA_Update", lambda: dll.GA_Update(1 << (axis_id - 1))),
        )
        for name, call in calls:
            self._check(call(), name)

    def move_absolute_mm(self, position_mm: float) -> None:
        """Level 2：在所有能力、标定、范围和现场状态检查通过后开始运动。"""
        self._require_connected()
        errors = self.motion_readiness_errors(check_live_status=True)
        errors.extend(self.config.calibration.target_errors(position_mm))
        if not errors:
            try:
                current_mm = self.get_position_mm()
            except Exception as exc:
                errors.append(f"当前位置不可读：{exc}")
            else:
                errors.extend(
                    f"当前位置检查：{reason}"
                    for reason in self.config.calibration.target_errors(current_mm)
                )
        if errors:
            raise StageSafetyError("真实运动被安全门拒绝：\n- " + "\n- ".join(errors))
        target_pulse = self.config.calibration.mm_to_pulse(position_mm)
        self._command_absolute_pulse(target_pulse)
        self._last_target_mm = position_mm

    def move_absolute(self, position: float) -> None:
        """实现 StageBase；参数在真实 Adapter 中明确表示物理 mm。"""
        self.move_absolute_mm(position)

    def move_relative_mm(self, distance_mm: float) -> None:
        self.move_absolute_mm(self.get_position_mm() + distance_mm)

    def move_relative(self, distance: float) -> None:
        """实现 StageBase；参数在真实 Adapter 中明确表示物理 mm。"""
        self.move_relative_mm(distance)

    def is_moving(self) -> bool:
        if self._last_target_mm is None:
            return False
        raw_status = self.read_raw_status()
        decoded = decode_axis_status(raw_status)
        status_errors = list(decoded["safety_faults"])
        if decoded["home_running"]:
            status_errors.append("轴在点位运动期间进入了回零状态")
        if decoded["unknown_bits_hex"] != "0x00000000":
            status_errors.append(
                f"轴状态包含手册未定义位 {decoded['unknown_bits_hex']}"
            )
        if status_errors:
            raise StageSafetyError("运动状态异常：" + "; ".join(status_errors))
        if decoded["running"]:
            return True
        pulses_per_mm = self.config.calibration.pulses_per_mm
        if pulses_per_mm is None:
            raise StageSafetyError("pulses_per_mm 未确认，不能判断运动完成")
        tolerance_mm = self.config.position_tolerance_pulse / pulses_per_mm
        # 手册 11.6：RUNNING=0 且规划位置与目标差值小于 1 pulse 才算到位。
        return abs(self.get_position_mm() - self._last_target_mm) >= tolerance_mm

    def stop(self) -> None:
        self.config.capabilities.require("stop_supported", "Stop")
        dll = self._require_connected()
        mask = 1 << (self._axis_id() - 1)
        self._check(dll.GA_Stop(mask, 0), "GA_Stop")

    def emergency_stop(self) -> None:
        """调用控制器规划急停；不能替代独立物理急停或断电手段。"""

        self.config.capabilities.require("stop_supported", "Emergency Stop")
        dll = self._require_connected()
        mask = 1 << (self._axis_id() - 1)
        self._check(dll.GA_Stop(mask, mask), "GA_Stop")

    def home(self) -> None:
        self.config.capabilities.require("home_supported", "Home")
        raise UnsupportedStageOperation("Home API 签名尚未实现")

    def get_positive_limit_active(self) -> bool:
        self.config.capabilities.require("positive_limit_supported", "读取正限位")
        raw_status = self.read_raw_status()
        return bool(
            raw_status
            & int(
                AxisStatusFlag.POSITIVE_SOFT_LIMIT
                | AxisStatusFlag.POSITIVE_HARD_LIMIT
            )
        )

    def get_negative_limit_active(self) -> bool:
        self.config.capabilities.require("negative_limit_supported", "读取负限位")
        raw_status = self.read_raw_status()
        return bool(
            raw_status
            & int(
                AxisStatusFlag.NEGATIVE_SOFT_LIMIT
                | AxisStatusFlag.NEGATIVE_HARD_LIMIT
            )
        )

    def device_info(self) -> dict[str, object]:
        calibration = self.config.calibration
        return {
            "adapter": type(self).__name__,
            "pc_ip": self.config.pc_ip,
            "card_ip": self.config.card_ip,
            "axis_id": calibration.axis_id,
            "physical_unit": "mm",
            "controller_unit": "pulse",
            "pulses_per_mm": calibration.pulses_per_mm,
            "travel_min_mm": calibration.travel_min_mm,
            "travel_max_mm": calibration.travel_max_mm,
            "direction_sign": calibration.direction_sign,
            "home_position_mm": calibration.home_position_mm,
            "soft_limit_min_mm": calibration.soft_limit_min_mm,
            "soft_limit_max_mm": calibration.soft_limit_max_mm,
            "allow_motion": self.config.allow_motion,
            "access_level": self.access_level.name,
            "motion_readiness_errors": self.motion_readiness_errors(
                check_live_status=False
            ),
        }
