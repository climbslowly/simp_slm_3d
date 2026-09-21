"""GUI-M1 空间扫描的原始 TIFF、日志与按需回读。"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tifffile

from scan.spatial_scan import SpatialPoint, SpatialScanPlan


SPATIAL_LOG_COLUMNS = [
    "timestamp_utc", "scan_id", "point_id", "order_index", "row", "col",
    "scan_type", "target_x_mm", "target_y_mm", "target_z_mm",
    "actual_x_mm", "actual_y_mm", "actual_z_mm", "position_source",
    "camera_x_mm", "camera_y_mm", "camera_position_source",
    "camera_source", "camera_serial", "camera_model", "exposure_us",
    "pixel_format", "roi_x", "roi_y", "roi_width", "roi_height",
    "metric_name", "metric_value", "roi_mean", "roi_sum", "image_max",
    "saturation_fraction", "saturation_threshold", "filename", "status", "error_message",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _float_or_nan(value: object) -> float:
    if value in (None, ""):
        return float("nan")
    return float(value)


def _string_column(values: list[object]) -> np.ndarray:
    """用 MATLAB cell column 保存变长字符串，避免补空格的 char matrix。"""
    return np.asarray([str(value) for value in values], dtype=object).reshape(-1, 1)


def _relative_image_path(value: object) -> Path:
    """日志统一允许 Windows/Unix 分隔符，回读时仍限制在扫描目录下。"""
    parts = [part for part in str(value).replace("\\", "/").split("/") if part]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"无效的原图相对路径：{value}")
    return Path(*parts)


def roi_metrics(image: np.ndarray, roi_xywh: tuple[int, int, int, int], metric: str) -> dict[str, float | int]:
    if image.ndim != 2:
        raise ValueError("GUI-M1 仅支持二维灰度原始数组")
    x, y, width, height = roi_xywh
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > image.shape[1] or y + height > image.shape[0]:
        raise ValueError(f"ROI {roi_xywh} 超出原图范围 width={image.shape[1]}, height={image.shape[0]}")
    roi = image[y:y + height, x:x + width]
    roi_mean = float(np.mean(roi, dtype=np.float64))
    roi_sum = float(np.sum(roi, dtype=np.float64))
    image_max = int(np.max(image))
    if image.dtype == np.uint8:
        threshold: int | None = 255
    elif image.dtype == np.uint16:
        # Mock 明确生成完整 uint16 表示；真实相机有效位深未知时必须改为 unavailable。
        threshold = 65535
    else:
        threshold = None
    saturation = float(np.mean(image >= threshold)) if threshold is not None else float("nan")
    return {
        "metric_value": roi_mean if metric == "mean" else roi_sum,
        "roi_mean": roi_mean,
        "roi_sum": roi_sum,
        "image_max": image_max,
        "saturation_fraction": saturation,
        "saturation_threshold": threshold if threshold is not None else -1,
    }


class SpatialDataManager:
    def __init__(self, plan: SpatialScanPlan, *, scan_id: str) -> None:
        self.plan = plan
        self.scan_id = scan_id
        self.session_dir: Path | None = None
        self._file = None
        self._writer: csv.DictWriter | None = None

    def open(self, *, stage_info: dict[str, object], camera_info: dict[str, object]) -> Path:
        self.plan.save_root.mkdir(parents=True, exist_ok=True)
        base = self.plan.save_root / f"{self.scan_id}_{self.plan.experiment_name}"
        session = base
        suffix = 1
        while session.exists():
            session = self.plan.save_root / f"{base.name}_{suffix:03d}"
            suffix += 1
        session.mkdir()
        self.session_dir = session
        config = self.plan.to_dict()
        config.update({
            "schema_version": 1,
            "software_version": "GUI-M1",
            "scan_id": self.scan_id,
            "start_time_utc": utc_now(),
            "device_mode": "MOCK",
            "stage": stage_info,
            "camera_info": camera_info,
            "position_meaning": "mock_simulated; not encoder feedback",
        })
        _atomic_json(session / "scan_config.json", config)
        self._file = (session / "scan_log.csv").open("w", newline="", encoding="utf-8-sig")
        self._writer = csv.DictWriter(self._file, fieldnames=SPATIAL_LOG_COLUMNS)
        self._writer.writeheader()
        self._file.flush()
        return session

    def save_success(
        self,
        *,
        point: SpatialPoint,
        actual_mm: dict[str, float],
        image: np.ndarray,
        camera_model: str,
        camera_positions_mm: dict[str, float],
    ) -> dict[str, object]:
        if self.session_dir is None or self._writer is None or self._file is None:
            raise RuntimeError("数据会话尚未打开")
        metrics = roi_metrics(image, self.plan.roi_xywh, self.plan.metric)
        safe_serial = re.sub(r"[^A-Za-z0-9_-]", "_", self.plan.camera_serial)
        camera_dir = self.session_dir / f"Camera_{safe_serial}"
        camera_dir.mkdir(exist_ok=True)
        final_path = camera_dir / f"point_{point.point_id:06d}_raw.tif"
        handle, temporary_name = tempfile.mkstemp(prefix=".partial_", suffix=".tif", dir=camera_dir)
        os.close(handle)
        try:
            tifffile.imwrite(temporary_name, image)
            os.replace(temporary_name, final_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        x, y, width, height = self.plan.roi_xywh
        row: dict[str, object] = {
            "timestamp_utc": utc_now(), "scan_id": self.scan_id,
            "point_id": point.point_id, "order_index": point.order_index,
            "row": "" if point.row is None else point.row,
            "col": "" if point.col is None else point.col,
            "scan_type": self.plan.scan_type,
            **{f"target_{axis.lower()}_mm": point.targets_mm[axis] for axis in ("X", "Y", "Z")},
            **{f"actual_{axis.lower()}_mm": actual_mm[axis] for axis in ("X", "Y", "Z")},
            "position_source": "mock_simulated", "camera_source": "mock",
            "camera_x_mm": camera_positions_mm["X"], "camera_y_mm": camera_positions_mm["Y"],
            "camera_position_source": "mock_simulated",
            "camera_serial": self.plan.camera_serial, "camera_model": camera_model,
            "exposure_us": self.plan.exposure_us, "pixel_format": str(image.dtype),
            "roi_x": x, "roi_y": y, "roi_width": width, "roi_height": height,
            "metric_name": self.plan.metric, **metrics,
            "filename": os.path.relpath(final_path, self.session_dir),
            "status": "ok", "error_message": "",
        }
        self._writer.writerow(row)
        self._file.flush()
        # 私有运行时字段不写入 CSV，仅让 GUI 在扫描进行中按需回读旧图。
        row["_session_dir"] = str(self.session_dir)
        return row

    def append_status(self, *, point: SpatialPoint, status: str, message: str) -> None:
        if self._writer is None or self._file is None:
            return
        row = {
            "timestamp_utc": utc_now(), "scan_id": self.scan_id,
            "point_id": point.point_id, "order_index": point.order_index,
            "row": "" if point.row is None else point.row,
            "col": "" if point.col is None else point.col,
            "scan_type": self.plan.scan_type,
            **{f"target_{axis.lower()}_mm": point.targets_mm[axis] for axis in ("X", "Y", "Z")},
            "position_source": "unavailable", "camera_source": "mock",
            "camera_serial": self.plan.camera_serial, "exposure_us": self.plan.exposure_us,
            "status": status, "error_message": message,
        }
        self._writer.writerow(row)
        self._file.flush()

    def append_error(self, *, point: SpatialPoint, message: str) -> None:
        self.append_status(point=point, status="error", message=message)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = None
        self._writer = None

    def export_mat(self) -> Path:
        """关闭 CSV 后生成扫描级 MAT；TIFF 仍是唯一原始像素副本。"""
        self.close()
        if self.session_dir is None:
            raise RuntimeError("数据会话尚未打开")
        return export_spatial_session_mat(self.session_dir)


@dataclass
class SpatialSession:
    directory: Path
    config: dict[str, object]
    records: list[dict[str, str]]

    @classmethod
    def open(cls, directory: Path) -> "SpatialSession":
        directory = Path(directory)
        config_path, log_path = directory / "scan_config.json", directory / "scan_log.csv"
        if not config_path.is_file() or not log_path.is_file():
            raise ValueError("所选目录缺少 scan_config.json 或 scan_log.csv")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("schema_version") != 1:
            raise ValueError("不是 GUI-M1 空间扫描目录或 schema_version 不受支持")
        with log_path.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        return cls(directory, config, records)

    @property
    def successful_records(self) -> list[dict[str, str]]:
        return [record for record in self.records if record.get("status") == "ok" and record.get("filename")]

    def load_image(self, point_id: int) -> np.ndarray:
        record = next((item for item in self.successful_records if int(item["point_id"]) == point_id), None)
        if record is None:
            raise KeyError(f"point_id={point_id} 没有成功保存的原图")
        path = self.directory / _relative_image_path(record["filename"])
        return tifffile.imread(path)


def export_spatial_session_mat(directory: Path) -> Path:
    """把 scan_config + scan_log 汇总为 MATLAB v5 文件，不复制 TIFF 像素栈。"""
    try:
        from scipy.io import savemat
    except ImportError as exc:
        raise RuntimeError(
            "导出 scan_data.mat 需要 scipy；请安装 requirements.txt"
        ) from exc

    session = SpatialSession.open(Path(directory))
    config = session.config
    points = config.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("scan_config.json 缺少有效 points")
    total = len(points)
    point_id = np.empty((total, 1), dtype=np.int64)
    order_index = np.empty((total, 1), dtype=np.int64)
    row = np.full((total, 1), np.nan, dtype=np.float64)
    col = np.full((total, 1), np.nan, dtype=np.float64)
    target_xyz = np.full((total, 3), np.nan, dtype=np.float64)
    actual_xyz = np.full((total, 3), np.nan, dtype=np.float64)
    camera_xy = np.full((total, 2), np.nan, dtype=np.float64)
    metric_value = np.full((total, 1), np.nan, dtype=np.float64)
    roi_mean = np.full((total, 1), np.nan, dtype=np.float64)
    roi_sum = np.full((total, 1), np.nan, dtype=np.float64)
    image_max = np.full((total, 1), np.nan, dtype=np.float64)
    saturation_fraction = np.full((total, 1), np.nan, dtype=np.float64)
    statuses: list[object] = ["unacquired"] * total
    errors: list[object] = [""] * total
    timestamps: list[object] = [""] * total
    filenames: list[object] = [""] * total
    image_file_exists = np.zeros((total, 1), dtype=np.uint8)
    position_sources: list[object] = ["unavailable"] * total

    id_to_index: dict[int, int] = {}
    for index, raw_point in enumerate(points):
        if not isinstance(raw_point, dict):
            raise ValueError("scan_config.json 的 point 结构无效")
        current_id = int(raw_point["point_id"])
        if current_id in id_to_index:
            raise ValueError(f"scan_config.json 含重复 point_id={current_id}")
        id_to_index[current_id] = index
        point_id[index, 0] = current_id
        order_index[index, 0] = int(raw_point["order_index"])
        row[index, 0] = _float_or_nan(raw_point.get("row"))
        col[index, 0] = _float_or_nan(raw_point.get("col"))
        targets = raw_point.get("targets_mm")
        if not isinstance(targets, dict):
            raise ValueError(f"point_id={current_id} 缺少 targets_mm")
        target_xyz[index, :] = [float(targets[axis]) for axis in ("X", "Y", "Z")]

    for record in session.records:
        current_id = int(record["point_id"])
        if current_id not in id_to_index:
            raise ValueError(f"scan_log.csv 含计划外 point_id={current_id}")
        index = id_to_index[current_id]
        statuses[index] = record.get("status", "")
        errors[index] = record.get("error_message", "")
        timestamps[index] = record.get("timestamp_utc", "")
        filenames[index] = record.get("filename", "")
        if filenames[index]:
            image_file_exists[index, 0] = int(
                (session.directory / _relative_image_path(filenames[index])).is_file()
            )
        position_sources[index] = record.get("position_source", "unavailable")
        actual_xyz[index, :] = [
            _float_or_nan(record.get(f"actual_{axis}_mm")) for axis in ("x", "y", "z")
        ]
        camera_xy[index, :] = [
            _float_or_nan(record.get(f"camera_{axis}_mm")) for axis in ("x", "y")
        ]
        metric_value[index, 0] = _float_or_nan(record.get("metric_value"))
        roi_mean[index, 0] = _float_or_nan(record.get("roi_mean"))
        roi_sum[index, 0] = _float_or_nan(record.get("roi_sum"))
        image_max[index, 0] = _float_or_nan(record.get("image_max"))
        saturation_fraction[index, 0] = _float_or_nan(
            record.get("saturation_fraction")
        )

    grid_shape = config.get("grid_shape")
    metric_grid = np.empty((0, 0), dtype=np.float64)
    if isinstance(grid_shape, list) and len(grid_shape) == 2:
        metric_grid = np.full(tuple(int(value) for value in grid_shape), np.nan)
        for index in range(total):
            if np.isfinite(row[index, 0]) and np.isfinite(col[index, 0]):
                metric_grid[int(row[index, 0]), int(col[index, 0])] = metric_value[index, 0]

    roi_xywh = config.get("roi_xywh", [])
    successful_count = sum(status == "ok" for status in statuses)
    payload: dict[str, object] = {
        "mat_export_version": np.int32(1),
        "scan_id": str(config.get("scan_id", "")),
        "scan_type": str(config.get("scan_type", "")),
        "device_mode": str(config.get("device_mode", "")),
        "position_meaning": str(config.get("position_meaning", "")),
        "coordinate_axis_order": _string_column(["X", "Y", "Z"]),
        "point_id": point_id,
        "order_index": order_index,
        "row": row,
        "col": col,
        "target_xyz_mm": target_xyz,
        "actual_xyz_mm": actual_xyz,
        "camera_xy_mm": camera_xy,
        "position_source": _string_column(position_sources),
        "status": _string_column(statuses),
        "error_message": _string_column(errors),
        "timestamp_utc": _string_column(timestamps),
        "image_relative_path": _string_column(filenames),
        "image_file_exists": image_file_exists,
        "metric_name": str(config.get("metric", "")),
        "metric_value": metric_value,
        "metric_grid": metric_grid,
        "roi_mean": roi_mean,
        "roi_sum": roi_sum,
        "image_max": image_max,
        "saturation_fraction": saturation_fraction,
        "roi_xywh": np.asarray(roi_xywh, dtype=np.int64).reshape(1, -1),
        "horizontal_axis": str(config.get("horizontal_axis") or ""),
        "vertical_axis": str(config.get("vertical_axis") or ""),
        "horizontal_values_mm": np.asarray(
            config.get("horizontal_values", []), dtype=np.float64
        ).reshape(1, -1),
        "vertical_values_mm": np.asarray(
            config.get("vertical_values", []), dtype=np.float64
        ).reshape(1, -1),
        "fixed_axis": str(config.get("fixed_axis") or ""),
        "fixed_value_mm": _float_or_nan(config.get("fixed_value_mm")),
        "total_point_count": np.int64(total),
        "successful_point_count": np.int64(successful_count),
        "missing_success_image_count": np.int64(
            sum(
                statuses[index] == "ok" and image_file_exists[index, 0] == 0
                for index in range(total)
            )
        ),
        "raw_images_embedded": np.uint8(0),
        "raw_image_format": "TIFF",
        "config_json": json.dumps(config, ensure_ascii=False),
        "mat_created_time_utc": utc_now(),
    }
    output = session.directory / "scan_data.mat"
    handle, temporary_name = tempfile.mkstemp(
        prefix=".scan_data_", suffix=".mat", dir=session.directory
    )
    os.close(handle)
    try:
        savemat(
            temporary_name,
            payload,
            do_compression=True,
            long_field_names=True,
        )
        os.replace(temporary_name, output)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return output
