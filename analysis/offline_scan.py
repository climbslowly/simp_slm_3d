"""离线单轴扫描学习入口。运行示例见 docs/OFFLINE_ANALYSIS.md。

图像统一为 image[y, x]；坐标用零基像素、位移用 mm、灰度用相机计数。
整个模块只读扫描文件，不导入相机或位移台驱动。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy.io import loadmat, savemat

METRICS = [
    "image_min", "image_max", "candidate_clip_pixels", "acquisition_roi_mean",
    "background_mean", "background_std", "signal_mean", "signal_sum",
    "net_sum", "threshold_count", "centroid_x_px", "centroid_y_px",
    "sigma_x_px", "sigma_y_px", "gradient_energy", "threshold_counts",
]
COORDS = ["point_id", "order_index", "target_x_mm", "target_y_mm", "target_z_mm",
          "planned_x_mm", "planned_y_mm", "planned_z_mm"]


def crop(image: np.ndarray, roi: list[int]) -> np.ndarray:
    """按零基 [x,y,width,height] 截取二维 ROI，返回 [height,width] 视图。

    参数 image 为 [H,W] 灰度数组，单位为计数；roi 单位为像素。
    不静默裁剪越界 ROI，避免两种语言分析不同区域；尺寸须为正整数。
    """
    r = np.asarray(roi)
    if r.shape != (4,) or not np.all(np.isfinite(r)) or np.any(r != np.floor(r)):
        raise ValueError("ROI 必须是四个有限整数 [x,y,width,height]")
    x, y, w, h = map(int, r)
    if image.ndim != 2 or min(x, y) < 0 or min(w, h) < 2 or x+w > image.shape[1] or y+h > image.shape[0]:
        raise ValueError(f"ROI {roi} 超出二维图像 {image.shape} 或宽高小于2")
    return image[y:y+h, x:x+w]


def validate_parameters(p: dict) -> None:
    """校验两种语言共用的参数字典；失败抛出 ValueError，无返回值。"""
    if p["algorithm_version"] != 1:
        raise ValueError("不支持的 algorithm_version")
    for key in ["threshold_sigma", "candidate_clip_count", "radial_bin_px", "radial_max_px", "preview_stride"]:
        if not np.isfinite(p[key]) or p[key] <= 0:
            raise ValueError(f"{key} 必须为有限正数")
    if p["preview_stride"] != int(p["preview_stride"]):
        raise ValueError("preview_stride 必须为整数")
    if p["radial_max_px"] % p["radial_bin_px"] != 0:
        raise ValueError("radial_max_px 必须是 radial_bin_px 的整数倍")
    limits = np.asarray(p["display_counts"])
    if limits.shape != (2,) or not np.all(np.isfinite(limits)) or limits[0] >= limits[1]:
        raise ValueError("display_counts 必须递增")


def measure_frame(image: np.ndarray, acquisition_roi: list[int], p: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """测量一帧，不拟合或归一化原始信号。

    参数：image [H,W] 原始灰度；acquisition_roi 是采集时零基 ROI；
    p 为共用 JSON 参数。返回：(metrics [16], radial [B], x_profile [Wroi],
    y_profile [Hroi])，各指标顺序见 METRICS。
    背景为背景 ROI 均值 b，标准差用总体定义（ddof=0）。扣背景前转 float64。
    net_sum=sum(I-b) 保留负值，单位计数之和；形状测量仅取 I>b+k*std 的像素，
    权重为 I-b，抑制大片背景噪声对质心/二阶矩的偏置。sigma 为加权标准差(px)，
    不是高斯束腰。梯度能量=mean(diff_x^2)+mean(diff_y^2)，单位计数²/像素²，
    同时受亮度和噪声影响。径向曲线对质心附近环带内 I-b 求均值，单位计数；
    第 j 个环带为 [j*dr,(j+1)*dr)，不完整环带及无信号帧返回 NaN。
    """
    signal = crop(image, p["signal_roi_xywh"]).astype(np.float64)
    bg = crop(image, p["background_roi_xywh"]).astype(np.float64)
    b, noise = float(bg.mean()), float(bg.std(ddof=0))
    net = signal - b
    threshold = b + p["threshold_sigma"] * noise
    mask = signal > threshold
    weights = np.where(mask, net, 0.0)
    x0, y0, w, h = p["signal_roi_xywh"]
    xs, ys = np.arange(w, dtype=float)+x0, np.arange(h, dtype=float)+y0
    wx, wy = weights.sum(axis=0), weights.sum(axis=1)
    total = weights.sum()
    cx = cy = sx = sy = float("nan")
    bins = int(p["radial_max_px"] / p["radial_bin_px"])
    radial = np.full(bins, np.nan)
    if total > 0:
        cx, cy = float(wx @ xs / total), float(wy @ ys / total)
        sx = float(np.sqrt(wx @ (xs-cx)**2 / total))
        sy = float(np.sqrt(wy @ (ys-cy)**2 / total))
        # 广播得到 [Hroi,Wroi] 半径数组，不使用 MATLAB 的列优先线性索引。
        radius = np.hypot(ys[:, None]-cy, xs[None, :]-cx)
        ib = np.floor(radius / p["radial_bin_px"]).astype(np.int64)
        valid = ib < bins
        sums = np.bincount(ib[valid], weights=net[valid], minlength=bins)
        counts = np.bincount(ib[valid], minlength=bins)
        np.divide(sums, counts, out=radial, where=counts > 0)
        complete_radius = min(cx-x0, x0+w-1-cx, cy-y0, y0+h-1-cy)
        radial[(np.arange(bins)+1)*p["radial_bin_px"] > complete_radius] = np.nan
    gradient = np.mean(np.diff(signal, axis=1)**2) + np.mean(np.diff(signal, axis=0)**2)
    metrics = np.array([image.min(), image.max(), np.count_nonzero(image >= p["candidate_clip_count"]),
                        crop(image, acquisition_roi).mean(), b, noise, signal.mean(), signal.sum(),
                        net.sum(), mask.sum(), cx, cy, sx, sy, gradient, threshold], dtype=float)
    return metrics, radial, net.mean(axis=0), net.mean(axis=1)


def load_scan(directory: Path) -> tuple[dict, list[dict]]:
    """读取 JSON 和 UTF-8 BOM CSV，按 point_id 连接，再按 order_index 排序。

    参数 directory 为扫描目录；返回 config 字典和 N 个计划点记录。
    targets_mm 已是绝对位置，不重复添加 origin。保留未采集/失败点，重复 ID、
    计划外记录及 CSV/JSON 坐标冲突报错。本版仅分析单轴扫描，明确拒绝二维。
    """
    config = json.loads((directory / "scan_config.json").read_text(encoding="utf-8-sig"))
    if config.get("schema_version") != 1 or config.get("scan_type") not in ("AXIS_RANGE", "AXIS_LIST"):
        raise ValueError("本版仅支持 schema_version=1 的 AXIS_RANGE/AXIS_LIST")
    with (directory / "scan_log.csv").open(encoding="utf-8-sig", newline="") as f:
        logs = list(csv.DictReader(f))
    by_id = {}
    for row in logs:
        key = int(row["point_id"])
        if key in by_id:
            raise ValueError(f"日志重复 point_id={key}")
        by_id[key] = row
    points = sorted(config["points"], key=lambda r: r["order_index"])
    ids = [int(r["point_id"]) for r in points]
    if len(set(ids)) != len(ids) or set(by_id) - set(ids):
        raise ValueError("计划重复 ID 或日志包含计划外 ID")
    if len({r["order_index"] for r in points}) != len(points):
        raise ValueError("重复 order_index")
    records = []
    for point in points:
        row = by_id.get(point["point_id"], {"status": "unacquired"})
        if row.get("status") == "ok":
            expected = [point["targets_mm"][a] for a in "XYZ"]
            actual = [float(row[f"target_{a}_mm"]) for a in "xyz"]
            if not np.allclose(expected, actual, rtol=0, atol=1e-9):
                raise ValueError("CSV 与 JSON 目标坐标不一致")
        records.append({**point, "log": row})
    return config, records


def safe_file(directory: Path, relative: str) -> Path:
    """将 Windows/POSIX 相对路径解析到扫描目录内；越界时报错。"""
    path = (directory / relative.replace("\\", "/")).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("图像路径越出扫描目录")
    return path


def make_preview(image: np.ndarray, stride: int) -> np.ndarray:
    """将 [H,W] 原图按 stride×stride 块均值降采样为 [ceil(H/s),ceil(W/s)]。

    只用于显示，单位仍是计数；边缘不足一块时按实际像素数平均。
    使用块均值而非隔点抽样，减轻周期结构在总览图中的混叠。
    """
    h, w = image.shape
    out = np.zeros(((h+stride-1)//stride, (w+stride-1)//stride), dtype=float)
    for dy in range(stride):
        for dx in range(stride):
            part = image[dy::stride, dx::stride]
            out[:part.shape[0], :part.shape[1]] += part
    ny = np.minimum(stride, h-np.arange(0, h, stride))
    nx = np.minimum(stride, w-np.arange(0, w, stride))
    return out / (ny[:, None]*nx[None, :])


def run(directory: Path, parameter_file: Path, output: Path, show: bool = False) -> dict:
    """运行完整离线分析并导出结果，返回可供学习调用的结果字典。

    输入目录只读；output 必须位于输入目录之外。show=True 打开带滑条的照片浏览器。
    每次只保留一张全尺寸 TIFF，预览用块均值；所有数值始终用原分辨率计算。
    输出数值 data 为 [N,24]，radial 为 [N,B]；失败点指标为 NaN。
    """
    directory, output = directory.resolve(), output.resolve()
    if output == directory or output.is_relative_to(directory):
        raise ValueError("输出须放在原始扫描目录之外")
    p = json.loads(parameter_file.read_text(encoding="utf-8-sig"))
    validate_parameters(p)
    config, records = load_scan(directory)
    n, bins = len(records), int(p["radial_max_px"] / p["radial_bin_px"])
    data = np.full((n, len(COORDS)+len(METRICS)), np.nan)
    radial = np.full((n, bins), np.nan)
    xp = np.full((n, p["signal_roi_xywh"][2]), np.nan)
    yp = np.full((n, p["signal_roi_xywh"][3]), np.nan)
    statuses, previews, audit = [], [], []
    for i, record in enumerate(records):
        row = record["log"]
        data[i, :5] = [record["point_id"], record["order_index"], *[record["targets_mm"][a] for a in "XYZ"]]
        data[i, 5:8] = [float(row.get(f"actual_{a}_mm") or "nan") for a in "xyz"]
        status, preview = row["status"], None
        info = {"point_id": record["point_id"], "position_source": row.get("position_source", "unavailable")}
        if status == "ok":
            path = safe_file(directory, row["filename"])
            if not path.is_file():
                status = "missing_image"
            else:
                image = tifffile.imread(path)
                if image.ndim != 2 or not np.issubdtype(image.dtype, np.integer):
                    raise ValueError("需要二维整数灰度 TIFF")
                data[i, 8:], radial[i], xp[i], yp[i] = measure_frame(image, config["roi_xywh"], p)
                preview = make_preview(image, p["preview_stride"])
                info.update(shape=list(image.shape), dtype=str(image.dtype),
                            pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                            acquisition_mean_error=float(data[i, 11]-float(row["roi_mean"])))
                mat_path = safe_file(directory, row.get("mat_filename") or "missing.mat")
                if mat_path.is_file():
                    frame = loadmat(mat_path)
                    info["tiff_mat_equal"] = bool(np.array_equal(image, frame["image"]))
                    if not info["tiff_mat_equal"] or int(frame["point_id"].item()) != record["point_id"] or not np.allclose(frame["target_xyz_mm"].ravel(), data[i, 2:5], rtol=0, atol=1e-9):
                        raise ValueError("逐帧 MAT 与 TIFF/坐标不一致")
                    del frame
                else:
                    info["tiff_mat_equal"] = None
                del image
        statuses.append(status)
        previews.append(preview)
        audit.append(info)
    output.mkdir(parents=True, exist_ok=True)
    columns = COORDS + METRICS
    result = dict(data=data, radial=radial, x_profile=xp, y_profile=yp,
                  columns=np.array(columns, dtype=object), status=np.array(statuses, dtype=object),
                  parameters_json=json.dumps(p, sort_keys=True), source=str(directory))
    savemat(output / "results.mat", result, do_compression=True)
    with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([*columns, "status", "filename", "position_source"])
        for values, status, record in zip(data, statuses, records):
            writer.writerow([*values, status, record["log"].get("filename", ""), record["log"].get("position_source", "")])
    (output / "parameters.json").write_text(json.dumps(p, indent=2), encoding="utf-8")
    (output / "audit.json").write_text(json.dumps({"source": str(directory), "frames": audit,
        "scan_config_sha256": hashlib.sha256((directory / "scan_config.json").read_bytes()).hexdigest(),
        "scan_log_sha256": hashlib.sha256((directory / "scan_log.csv").read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    render(result, previews, config, p, output, show)
    return result


def render(result: dict, previews: list, config: dict, p: dict, output: Path, show: bool) -> None:
    """生成位置—照片总览、指标曲线、径向剖面；可选滑条浏览，无数值返回。

    previews 每项为 [ceil(H/stride),ceil(W/stride)]，只用于显示。
    所有照片使用相同灰度范围，红框为分析 ROI，青框为原采集 ROI。
    曲线按绝对扫描坐标排序（照片/表格仍按采集顺序），不对缺失点插值。
    """
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.widgets import Slider

    data = result["data"]
    axis = config["horizontal_axis"]
    axis_col = 2 + "XYZ".index(axis)
    n = len(data)
    def draw(ax, i):
        ax.clear()
        if previews[i] is not None:
            h, w = config["camera_info"]["shape"]
            ax.imshow(previews[i], cmap="gray", vmin=p["display_counts"][0], vmax=p["display_counts"][1],
                      extent=[-0.5, w-0.5, h-0.5, -0.5])
            for roi, color in [(p["signal_roi_xywh"], "tomato"), (config["roi_xywh"], "cyan")]:
                x, y, rw, rh = roi
                ax.add_patch(Rectangle((x-.5, y-.5), rw, rh, fill=False, edgecolor=color))
        ax.set_title(f"point {int(data[i,0])} | {axis}={data[i,axis_col]:.4f} mm\n"
                     f"XYZ=({data[i,2]:.4f}, {data[i,3]:.4f}, {data[i,4]:.4f})\n{result['status'][i]}", fontsize=9)
        ax.set_xlabel("x / pixel (zero-based)")
        ax.set_ylabel("y / pixel")
    fig, axes = plt.subplots(int(np.ceil(n/3)), min(n, 3), figsize=(15, 4.3*int(np.ceil(n/3))), squeeze=False)
    for i, ax in enumerate(axes.flat):
        if i < n:
            draw(ax, i)
        else:
            ax.axis("off")
    fig.suptitle(f"Position - camera images | common display {p['display_counts']} counts\n"
                 "Red: signal ROI; cyan: acquisition ROI | planned coordinates, not encoder measurements")
    fig.tight_layout(rect=[0, 0, 1, .94])
    fig.savefig(output / "position_images.png", dpi=160)
    order = np.argsort(data[:, axis_col], kind="stable")
    z = data[order, axis_col]
    fig2, axes2 = plt.subplots(2, 3, figsize=(14, 8))
    for ax, names, label in zip(axes2.flat,
        [["acquisition_roi_mean", "background_mean"], ["net_sum"], ["gradient_energy"],
         ["centroid_x_px", "centroid_y_px"], ["sigma_x_px", "sigma_y_px"], ["image_max"]],
        ["counts", "counts (sum)", "counts^2 / pixel^2", "pixel", "pixel", "counts"]):
        for name in names:
            ax.plot(z, data[order, (COORDS+METRICS).index(name)], "o-", label=name)
        ax.set_xlabel(f"Absolute objective {axis} / mm")
        ax.set_ylabel(label)
        ax.legend(fontsize=8)
        ax.grid(alpha=.3)
    fig2.tight_layout()
    fig2.savefig(output / "metrics.png", dpi=150)
    fig3, ax3 = plt.subplots(figsize=(9, 5))
    radii = (np.arange(result["radial"].shape[1])+.5)*p["radial_bin_px"]
    for i in order:
        ax3.plot(radii, result["radial"][i], label=f"point {int(data[i,0])}: {data[i,axis_col]:.4f} mm")
    ax3.set(xlabel="Radius from thresholded centroid / pixel", ylabel="Annular mean minus background / counts")
    ax3.legend()
    ax3.grid(alpha=.3)
    fig3.tight_layout()
    fig3.savefig(output / "radial_profiles.png", dpi=150)
    if show:
        browser, ax = plt.subplots(figsize=(10, 8))
        browser.subplots_adjust(bottom=.18)
        draw(ax, 0)
        if n > 1:
            slider = Slider(browser.add_axes([.2, .05, .6, .04]), "Acquisition index", 1, n, valinit=1, valstep=1)
            def update(value):
                draw(ax, int(value)-1)
                browser.canvas.draw_idle()
            slider.on_changed(update)
        plt.show()
    plt.close("all")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan", type=Path)
    parser.add_argument("--params", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    run(args.scan, args.params, args.output, args.show)
    print(f"Offline analysis saved: {args.output.resolve()}")
