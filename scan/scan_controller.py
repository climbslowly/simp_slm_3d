"""与 GUI 无关的扫描状态机和核心执行流程。"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from data.image_saver import ScanDataManager, utc_now
from data.metadata import describe_camera
from hardware.camera_base import CameraBase
from hardware.stage_base import StageBase
from hardware.stage_safety import AxisCalibration
from scan.scan_inspection import ScanInspection, inspect_scan_plan
from scan.scan_plan import ScanPlan
from scan.scan_state import ScanState

SOFTWARE_VERSION = "0.2.0"


@dataclass
class ScanCallbacks:
    """未来 GUI 可把 Qt signal 包装成这些普通 Python 回调。"""

    on_state_changed: Callable[[ScanState], None] | None = None
    on_position_changed: Callable[[int, float, float], None] | None = None
    on_image_acquired: Callable[[str, int, np.ndarray], None] | None = None
    on_progress_changed: Callable[[int, int], None] | None = None


class ScanController:
    def __init__(
        self,
        stage: StageBase,
        cameras: Mapping[str, CameraBase],
        callbacks: ScanCallbacks | None = None,
    ) -> None:
        self.stage = stage
        self.cameras = dict(cameras)
        self.callbacks = callbacks or ScanCallbacks()
        self.state = ScanState.IDLE
        self._pause_requested = threading.Event()
        self._stop_requested = threading.Event()
        self._resume_condition = threading.Condition()

    def _set_state(self, state: ScanState) -> None:
        self.state = state
        if self.callbacks.on_state_changed is not None:
            self.callbacks.on_state_changed(state)

    def pause(self) -> None:
        self._pause_requested.set()

    def resume(self) -> None:
        self._pause_requested.clear()
        with self._resume_condition:
            self._resume_condition.notify_all()

    def request_stop(self) -> None:
        """正常停止：不打断当前硬件小步骤，完成后不再进入下一步。"""
        self._stop_requested.set()
        self.resume()

    def emergency_stop(self) -> None:
        """紧急停止预留接口；真实 Adapter 未确认 API 时会明确拒绝。"""
        self._stop_requested.set()
        self.stage.stop()

    def _pause_point(self) -> bool:
        if self._stop_requested.is_set():
            return False
        if not self._pause_requested.is_set():
            return True
        self._set_state(ScanState.PAUSED)
        with self._resume_condition:
            while self._pause_requested.is_set() and not self._stop_requested.is_set():
                self._resume_condition.wait(timeout=0.1)
        return not self._stop_requested.is_set()

    def _stage_info(self) -> dict[str, object]:
        describe = getattr(self.stage, "device_info", None)
        if callable(describe):
            return dict(describe())
        return {"adapter": type(self.stage).__name__}

    def preflight(self, plan: ScanPlan) -> list[str]:
        """返回全部问题，GUI 可一次性完整展示，而不是逐个试错。"""
        errors: list[str] = []
        if not self.stage.is_connected:
            errors.append("位移台未连接")
        for settings in plan.cameras:
            camera = self.cameras.get(settings.serial_number)
            if camera is None:
                errors.append(f"未注册相机：{settings.serial_number}")
            elif not camera.is_connected:
                errors.append(f"相机未连接：{settings.serial_number}")

        software_min = getattr(self.stage, "software_min", None)
        software_max = getattr(self.stage, "software_max", None)
        config = getattr(self.stage, "config", None)
        calibration = getattr(config, "calibration", None)
        if calibration is None and (software_min is not None or software_max is not None):
            calibration = AxisCalibration(
                travel_min_mm=software_min,
                travel_max_mm=software_max,
            )
        inspection = inspect_scan_plan(plan, calibration=calibration)
        if inspection.axis_range_check == "out_of_range":
            errors.extend(inspection.axis_range_errors)
        elif inspection.axis_range_check == "unknown":
            # 保留第一阶段对“只配置单侧 Mock 限位”的支持。
            if software_min is not None:
                bad = [position for position in plan.positions if position < software_min]
                if bad:
                    errors.append(f"扫描位置低于软件下限 {software_min}：{bad[:3]}")
            if software_max is not None:
                bad = [position for position in plan.positions if position > software_max]
                if bad:
                    errors.append(f"扫描位置高于软件上限 {software_max}：{bad[:3]}")

        # DimensionStage 提供这个安全门；MockStage 没有，因而现有 Mock 流程不受影响。
        readiness = getattr(self.stage, "motion_readiness_errors", None)
        if callable(readiness):
            errors.extend(
                f"真实运动安全门：{reason}"
                for reason in readiness(check_live_status=False)
            )

        try:
            plan.save_root.mkdir(parents=True, exist_ok=True)
            # 使用系统生成的唯一临时文件，避免覆盖目录中恰好同名的用户文件。
            with tempfile.NamedTemporaryFile(dir=plan.save_root, prefix=".dc_probe_"):
                pass
        except OSError as exc:
            errors.append(f"保存目录不可写：{exc}")
        return errors

    def dry_run(
        self,
        plan: ScanPlan,
        *,
        image_shape: tuple[int, ...] | None = None,
        image_dtype: str | np.dtype[object] | None = None,
    ) -> ScanInspection:
        """复用 ScanPlan 检查逻辑，不连接设备、不创建目录、不调用 Preflight 写探针。"""
        config = getattr(self.stage, "config", None)
        calibration = getattr(config, "calibration", None)
        if calibration is None:
            minimum = getattr(self.stage, "software_min", None)
            maximum = getattr(self.stage, "software_max", None)
            if minimum is not None or maximum is not None:
                calibration = AxisCalibration(
                    travel_min_mm=minimum,
                    travel_max_mm=maximum,
                )
        allow_motion = bool(getattr(config, "allow_motion", False))
        return inspect_scan_plan(
            plan,
            calibration=calibration,
            real_motion_enabled=allow_motion,
            image_shape=image_shape,
            image_dtype=image_dtype,
        )

    def run(self, plan: ScanPlan) -> Path | None:
        """同步执行扫描；GUI 必须从 QThread worker 调用本方法。"""
        if self.state not in {
            ScanState.IDLE,
            ScanState.COMPLETED,
            ScanState.STOPPED,
            ScanState.ERROR,
        }:
            raise RuntimeError(f"当前状态 {self.state.name} 不能开始新扫描")
        problems = self.preflight(plan)
        if problems:
            raise ValueError("Preflight 失败：\n- " + "\n- ".join(problems))

        self._stop_requested.clear()
        self._pause_requested.clear()
        completed_images = 0
        data_manager = ScanDataManager(plan)
        session_dir: Path | None = None
        try:
            camera_info = [
                describe_camera(self.cameras[item.serial_number]) for item in plan.cameras
            ]
            session_dir = data_manager.open(
                stage_info=self._stage_info(),
                camera_info=camera_info,
                software_version=SOFTWARE_VERSION,
            )

            for repeat_index in range(1, plan.repeats + 1):
                for position_index, target in enumerate(plan.positions, start=1):
                    if not self._pause_point():
                        break
                    self._set_state(ScanState.MOVING)
                    self.stage.move_absolute(target)
                    self._set_state(ScanState.WAITING_FOR_POSITION)
                    # 正常 Stop 不会放弃对运动完成的监测；到位后才退出。
                    actual = self.stage.wait_until_idle(
                        target_position=target,
                        tolerance=plan.position_tolerance,
                        timeout_s=plan.motion_timeout_s,
                    )
                    if self.callbacks.on_position_changed is not None:
                        self.callbacks.on_position_changed(position_index, target, actual)
                    if self._stop_requested.is_set():
                        break

                    self._set_state(ScanState.SETTLING)
                    if self._stop_requested.wait(plan.settling_time_s):
                        break

                    for frame_index in range(1, plan.frames_per_position + 1):
                        for settings in plan.cameras:
                            if not self._pause_point():
                                break
                            camera = self.cameras[settings.serial_number]
                            camera.set_exposure_us(settings.exposure_us)
                            self._set_state(ScanState.ACQUIRING)
                            try:
                                image = camera.grab_image()
                                if self.callbacks.on_image_acquired is not None:
                                    self.callbacks.on_image_acquired(
                                        settings.serial_number, position_index, image
                                    )
                                self._set_state(ScanState.SAVING)
                                image_path = data_manager.save_image(
                                    image,
                                    camera_serial=settings.serial_number,
                                    position_index=position_index,
                                    target_position=target,
                                    actual_position=actual,
                                    frame_index=frame_index,
                                    repeat_index=repeat_index,
                                )
                                status = "ok"
                                error_message = ""
                            except Exception as exc:
                                image_path = Path("")
                                status = "error"
                                error_message = str(exc)
                                data_manager.append_log(
                                    {
                                        "timestamp": utc_now(),
                                        "scan_position_index": position_index,
                                        "target_position": target,
                                        "actual_position": actual,
                                        "camera_serial": settings.serial_number,
                                        "camera_model": camera.get_model_name(),
                                        "frame_index": frame_index,
                                        "repeat_index": repeat_index,
                                        "exposure_us": settings.exposure_us,
                                        "filename": "",
                                        "status": status,
                                        "error_message": error_message,
                                    }
                                )
                                raise
                            data_manager.append_log(
                                {
                                    "timestamp": utc_now(),
                                    "scan_position_index": position_index,
                                    "target_position": target,
                                    "actual_position": actual,
                                    "camera_serial": settings.serial_number,
                                    "camera_model": camera.get_model_name(),
                                    "frame_index": frame_index,
                                    "repeat_index": repeat_index,
                                    "exposure_us": settings.exposure_us,
                                    "filename": os.path.relpath(image_path, session_dir),
                                    "status": status,
                                    "error_message": error_message,
                                }
                            )
                            completed_images += 1
                            if self.callbacks.on_progress_changed is not None:
                                self.callbacks.on_progress_changed(
                                    completed_images, plan.total_images
                                )
                        if self._stop_requested.is_set():
                            break
                    if self._stop_requested.is_set():
                        break
                if self._stop_requested.is_set():
                    break

            if self._stop_requested.is_set():
                self._set_state(ScanState.STOPPING)
                self._set_state(ScanState.STOPPED)
            else:
                self._set_state(ScanState.COMPLETED)
            return session_dir
        except Exception:
            self._set_state(ScanState.ERROR)
            raise
        finally:
            data_manager.close()
