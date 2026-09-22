"""真实相机多帧、耗时与重复帧诊断；不访问位移台。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hardware.basler_camera import BaslerCamera, select_basler_camera
from hardware.diagnostic_profile import (
    CameraDiagnosticSettings,
    load_hardware_diagnostic_profile,
)
from hardware.diagnostics import capture_camera_sequence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="真实 Basler 相机多帧诊断；不加载 GAS.dll，不访问位移台"
    )
    parser.add_argument(
        "--config", type=Path, default=Path("hardware_local.json")
    )
    parser.add_argument("--camera-index", type=int, help="覆盖本地配置中的相机序号")
    parser.add_argument(
        "--confirm-camera-only",
        action="store_true",
        help="确认本程序只连接相机、采集图像并断开",
    )
    args = parser.parse_args()
    if not args.confirm_camera_only:
        parser.error("必须显式提供 --confirm-camera-only")

    profile = load_hardware_diagnostic_profile(args.config)
    configured = profile.camera
    camera_index = (
        args.camera_index
        if args.camera_index is not None
        else configured.camera_index
    )
    if camera_index is None:
        parser.error("请在 hardware_local.json 或 --camera-index 中指定相机序号")
    settings = CameraDiagnosticSettings(
        camera_index=camera_index,
        exposure_ms=configured.exposure_ms,
        frames=configured.frames,
        discard_frames=configured.discard_frames,
        capture_timeout_ms=configured.capture_timeout_ms,
        post_exposure_settle_ms=configured.post_exposure_settle_ms,
        inter_frame_delay_ms=configured.inter_frame_delay_ms,
    )
    selected = select_basler_camera(camera_index)
    camera = BaslerCamera(selected.serial_number)
    session, report = capture_camera_sequence(
        camera,
        settings,
        output_root=profile.output_dir,
        device_details=selected.to_dict(),
    )
    print(f"camera = {selected.model_name} / {selected.serial_number}")
    print(f"saved_frames = {len(report['frames'])}")
    print(f"discarded_frames = {len(report['discarded'])}")
    print(f"identical_adjacent_pairs = {report['identical_adjacent_pairs']}")
    print(f"output = {session.resolve()}")


if __name__ == "__main__":
    main()
