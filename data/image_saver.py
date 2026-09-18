"""扫描目录、原始 TIFF 和可追踪 metadata 的统一保存逻辑。"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

import numpy as np

from scan.scan_plan import ScanPlan


LOG_COLUMNS = [
    "timestamp",
    "scan_position_index",
    "target_position",
    "actual_position",
    "camera_serial",
    "camera_model",
    "frame_index",
    "repeat_index",
    "exposure_us",
    "filename",
    "status",
    "error_message",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ScanDataManager:
    """一次扫描对应一个实例，确保 CSV 文件及时 flush 并最终关闭。"""

    def __init__(self, plan: ScanPlan) -> None:
        self.plan = plan
        self.session_dir: Path | None = None
        self._log_file: IO[str] | None = None
        self._writer: csv.DictWriter | None = None

    def open(
        self,
        *,
        stage_info: dict[str, object],
        camera_info: list[dict[str, object]],
        software_version: str,
    ) -> Path:
        self.plan.save_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{timestamp}_{self.plan.experiment_name}"
        session_dir = self.plan.save_root / base_name
        suffix = 1
        while session_dir.exists():
            session_dir = self.plan.save_root / f"{base_name}_{suffix:03d}"
            suffix += 1
        session_dir.mkdir()
        self.session_dir = session_dir

        config = self.plan.to_dict()
        config.update(
            {
                "software_version": software_version,
                "start_time": utc_now(),
                "stage": stage_info,
                "camera_info": camera_info,
            }
        )
        (session_dir / "scan_config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._log_file = (session_dir / "scan_log.csv").open(
            "w", newline="", encoding="utf-8-sig"
        )
        self._writer = csv.DictWriter(self._log_file, fieldnames=LOG_COLUMNS)
        self._writer.writeheader()
        self._log_file.flush()
        return session_dir

    def save_image(
        self,
        image: np.ndarray,
        *,
        camera_serial: str,
        position_index: int,
        target_position: float,
        actual_position: float,
        frame_index: int,
        repeat_index: int,
    ) -> Path:
        if self.session_dir is None:
            raise RuntimeError("必须先调用 ScanDataManager.open()")
        try:
            import tifffile
        except ImportError as exc:
            raise RuntimeError("保存 TIFF 需要安装 tifffile") from exc

        safe_serial = re.sub(r"[^A-Za-z0-9_-]", "_", camera_serial)
        camera_dir = self.session_dir / f"Camera_{safe_serial}"
        camera_dir.mkdir(exist_ok=True)
        filename = (
            f"pos_{position_index:06d}"
            f"_target_{target_position:.6f}"
            f"_actual_{actual_position:.6f}"
            f"_repeat_{repeat_index:03d}"
            f"_frame_{frame_index:03d}.tif"
        )
        path = camera_dir / filename
        tifffile.imwrite(path, image)
        return path

    def append_log(self, row: dict[str, object]) -> None:
        if self._writer is None or self._log_file is None:
            raise RuntimeError("必须先调用 ScanDataManager.open()")
        unknown = set(row) - set(LOG_COLUMNS)
        if unknown:
            raise ValueError(f"日志中包含未知字段：{sorted(unknown)}")
        self._writer.writerow({name: row.get(name, "") for name in LOG_COLUMNS})
        self._log_file.flush()

    def close(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
        self._log_file = None
        self._writer = None

    def __enter__(self) -> "ScanDataManager":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

