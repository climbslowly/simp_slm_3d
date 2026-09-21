"""为已有 GUI-M1 扫描目录补生成 scan_data.mat；完全离线，不访问硬件。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.spatial_session import export_spatial_session_mat


def main() -> None:
    parser = argparse.ArgumentParser(
        description="由 GUI-M1 的 scan_config.json + scan_log.csv 汇总生成 scan_data.mat"
    )
    parser.add_argument("scan_directory", type=Path)
    args = parser.parse_args()
    result = export_spatial_session_mat(args.scan_directory)
    print(f"MATLAB 汇总文件：{result.resolve()}")
    print("原始像素未重复写入 MAT；请按 image_relative_path 读取同目录 TIFF。")


if __name__ == "__main__":
    main()
