"""与 Qt 无关的 GUI-M1 Mock 空间扫描执行器。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from data.spatial_session import SpatialDataManager
from mock.mock_camera import MockCamera
from mock.mock_xyz_stage import MockXYZStage
from scan.scan_state import ScanState
from scan.spatial_scan import SpatialPoint, SpatialScanPlan


@dataclass
class SpatialCallbacks:
    on_state: Callable[[ScanState], None] | None = None
    on_position: Callable[[dict[str, float]], None] | None = None
    on_point_saved: Callable[[dict[str, object], np.ndarray], None] | None = None
    on_progress: Callable[[int, int], None] | None = None


class SpatialScanController:
    def __init__(self, stage: MockXYZStage, camera: MockCamera, callbacks: SpatialCallbacks | None = None) -> None:
        self.stage = stage
        self.camera = camera
        self.callbacks = callbacks or SpatialCallbacks()
        self.state = ScanState.IDLE
        self._pause = threading.Event()
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self._run_lock = threading.Lock()

    def _set_state(self, state: ScanState) -> None:
        self.state = state
        if self.callbacks.on_state:
            self.callbacks.on_state(state)

    def request_pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()
        with self._condition:
            self._condition.notify_all()

    def request_stop(self) -> None:
        self._stop.set()
        self.resume()
        # GUI-M1 只有 MockStage；这里用于让模拟移动等待能立即退出，不代表真实急停。
        if self.stage.is_connected:
            self.stage.stop()

    def _pause_before_next_point(self) -> bool:
        if self._stop.is_set():
            return False
        if not self._pause.is_set():
            return True
        self._set_state(ScanState.PAUSED)
        with self._condition:
            while self._pause.is_set() and not self._stop.is_set():
                self._condition.wait(0.05)
        return not self._stop.is_set()

    def preflight(self, plan: SpatialScanPlan, *, image_shape: tuple[int, int]) -> list[str]:
        errors: list[str] = []
        if not self.stage.is_connected:
            errors.append("Mock 位移台未连接")
        if not self.camera.is_connected:
            errors.append("Mock 相机未连接")
        x, y, width, height = plan.roi_xywh
        if x + width > image_shape[1] or y + height > image_shape[0]:
            errors.append(f"ROI {plan.roi_xywh} 超出原图范围 {image_shape[1]}×{image_shape[0]}")
        try:
            plan.save_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=plan.save_root, prefix=".gui_m1_probe_"):
                pass
            usage = shutil.disk_usage(plan.save_root)
            estimated = plan.total_points * image_shape[0] * image_shape[1] * 2
            if usage.free < estimated + 1_000_000:
                errors.append("保存目录剩余空间不足以容纳未压缩原始数据估算")
        except OSError as exc:
            errors.append(f"保存目录不可写：{exc}")
        return errors

    def _wait_for_motion(self, point: SpatialPoint, timeout_s: float) -> dict[str, float]:
        self._wait_until_idle(timeout_s, operation=f"point_id={point.point_id} 模拟移动")
        return self.stage.get_positions()

    def _wait_until_idle(self, timeout_s: float, *, operation: str) -> None:
        deadline = time.monotonic() + timeout_s
        while self.stage.is_moving():
            if self._stop.wait(0.02):
                self.stage.stop()
                raise InterruptedError(f"{operation}等待期间停止")
            if time.monotonic() >= deadline:
                self.stage.stop()
                raise TimeoutError(f"{operation}超时")

    def run(self, plan: SpatialScanPlan) -> Path | None:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("已有扫描或手动移动正在使用 Mock 设备")
        manager: SpatialDataManager | None = None
        current_point: SpatialPoint | None = None
        try:
            problems = self.preflight(plan, image_shape=self.camera.image_shape)
            if problems:
                raise ValueError("Preflight 失败：\n- " + "\n- ".join(problems))
            self._stop.clear()
            self._pause.clear()
            self.camera.set_exposure_us(plan.exposure_us)
            scan_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            manager = SpatialDataManager(plan, scan_id=scan_id)
            session = manager.open(
                stage_info=self.stage.device_info(),
                camera_info={
                    "source": "mock", "serial_number": self.camera.get_serial_number(),
                    "model_name": self.camera.get_model_name(), "exposure_us": self.camera.get_exposure_us(),
                    "pixel_format": "Mono16 simulated", "shape": list(self.camera.image_shape),
                },
            )
            completed = 0
            for point in plan.points:
                current_point = point
                if not self._pause_before_next_point():
                    break
                self._set_state(ScanState.MOVING)
                self.stage.move_absolute(point.targets_mm)
                self._set_state(ScanState.WAITING_FOR_POSITION)
                actual = self._wait_for_motion(point, plan.motion_timeout_s)
                if self.callbacks.on_position:
                    self.callbacks.on_position(actual)
                if self._stop.is_set():
                    break
                self._set_state(ScanState.SETTLING)
                if self._stop.wait(plan.settling_time_s):
                    manager.append_status(point=point, status="cancelled", message="稳定等待期间收到停止请求")
                    break
                self._set_state(ScanState.ACQUIRING)
                image = self.camera.grab_image_interruptible(self._stop)
                if self._stop.is_set():
                    break
                self._set_state(ScanState.SAVING)
                record = manager.save_success(
                    point=point, actual_mm=actual, image=image,
                    camera_model=self.camera.get_model_name(),
                    camera_positions_mm=self.stage.get_camera_positions(),
                )
                completed += 1
                if self.callbacks.on_point_saved:
                    self.callbacks.on_point_saved(record, image)
                if self.callbacks.on_progress:
                    self.callbacks.on_progress(completed, plan.total_points)
            manager.export_mat()
            self._set_state(ScanState.STOPPED if self._stop.is_set() else ScanState.COMPLETED)
            return session
        except InterruptedError:
            if manager is not None and current_point is not None:
                manager.append_status(point=current_point, status="cancelled", message="运行中的 Mock 操作已取消")
                manager.export_mat()
            self._set_state(ScanState.STOPPED)
            return manager.session_dir if manager else None
        except Exception as exc:
            if manager is not None and current_point is not None:
                manager.append_error(point=current_point, message=str(exc))
                try:
                    manager.export_mat()
                except Exception as mat_exc:
                    raise RuntimeError(
                        f"扫描失败：{exc}；同时无法导出 scan_data.mat：{mat_exc}"
                    ) from exc
            self._set_state(ScanState.ERROR)
            raise
        finally:
            if manager is not None:
                manager.close()
            self._run_lock.release()

    def manual_move(self, targets_mm: dict[str, float], *, timeout_s: float = 5.0) -> dict[str, float]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("扫描或另一移动正在运行，拒绝新移动命令")
        try:
            self._stop.clear()
            point = SpatialPoint(1, 0, None, None, dict(targets_mm))
            self.stage.move_absolute(targets_mm)
            return self._wait_for_motion(point, timeout_s)
        finally:
            self._run_lock.release()

    def manual_move_camera(self, targets_mm: dict[str, float], *, timeout_s: float = 5.0) -> dict[str, float]:
        """只移动探测相机 Mock XY；空间扫描仍只使用物镜逻辑 XYZ。"""
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("扫描或另一移动正在运行，拒绝新移动命令")
        try:
            self._stop.clear()
            self.stage.move_camera_absolute(targets_mm)
            self._wait_until_idle(timeout_s, operation="相机两轴模拟移动")
            return self.stage.get_camera_positions()
        finally:
            self._run_lock.release()
