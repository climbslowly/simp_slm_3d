"""5000光镊样例的离线逐点分析。输出相机观察量，不重建未知的复电场。

运行：python -m analysis.tweezer_scan SCAN --params PARAMS --output OUTPUT
先调用已有整体分析，然后独立检测参考平面的局部峰；不根据目标数量筛选峰。
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy.ndimage import convolve1d, maximum_filter
from scipy.io import savemat
from scipy.spatial import cKDTree

from . import offline_scan as base

SPOT_COLUMNS = ["spot_id", "peak_x_px", "peak_y_px", "smoothed_peak_counts",
                "centroid_x_px", "centroid_y_px", "nominal_x_um", "nominal_y_um",
                "local_background_counts", "aperture_net_sum", "peak_net_counts",
                "clip_pixels", "sigma_x_px", "sigma_y_px", "nearest_neighbor_px",
                "nearest_neighbor_nominal_um"]
PROBE_COLUMNS = ["anchor_x_px", "anchor_y_px", "local_background_counts",
                 "aperture_net_sum", "peak_net_counts", "clip_pixels", "sigma_x_px", "sigma_y_px"]


def validate(p: dict) -> None:
    """检查物理换算和逐点算法参数；不允许把缺失标定当作实测值。无返回值。"""
    base.validate_parameters(p)
    s, o, c = p["spots"], p["optics"], p["operator_camera_settings"]
    if s["algorithm_version"] != 1:
        raise ValueError("不支持的逐点算法版本")
    for key in ["gaussian_sigma_px", "peak_threshold_counts", "moment_threshold_sigma"]:
        if not np.isfinite(s[key]) or s[key] <= 0:
            raise ValueError(f"{key} 必须是有限正数")
    for key in ["reference_point_id", "gaussian_radius_px", "maximum_filter_halfwidth_px",
                "aperture_radius_px", "background_annulus_inner_px", "background_annulus_outer_px"]:
        if not np.isfinite(s[key]) or s[key] < 1 or s[key] != int(s[key]):
            raise ValueError(f"{key} 必须是正整数")
    if not s["aperture_radius_px"] < s["background_annulus_inner_px"] < s["background_annulus_outer_px"]:
        raise ValueError("信号圆必须与背景环分离")
    for key in ["tube_lens_efl_mm", "detection_objective_efl_mm", "sensor_pixel_pitch_um", "target_pitch_um"]:
        if not np.isfinite(o[key]) or o[key] <= 0:
            raise ValueError(f"{key} 必须是有限正数")
    if c["binning_horizontal"] != 1 or c["binning_vertical"] != 1:
        raise ValueError("本版的单一像素比例要求1×1 Binning")


def detect_spots(image: np.ndarray, p: dict) -> tuple[np.ndarray, np.ndarray]:
    """在固定信号ROI内寻找局部峰，返回 peaks[K,3]=(x,y,平滑计数) 和灵敏度表[T,2]。

    image 为 [H,W] 原始灰度；坐标全图零基px。归一化的一维高斯核半径为4px、
    sigma=1.2px（均可由JSON配置），先横向后纵向卷积；边界零填充。
    21×21局部最大值且严格大于阈值才算候选。搜索排除背景环触及ROI边界的中心。
    按y、x排序分配检测编号，不是SLM目标编号。5000仅作报告比较，不截取前5000。
    平坦峰若产生多个相等局部最大值则保留候选，最近邻距离会暴露重复检测。
    """
    s = p["spots"]
    roi = base.crop(image, p["signal_roi_xywh"]).astype(float)
    q = np.arange(-s["gaussian_radius_px"], s["gaussian_radius_px"]+1, dtype=float)
    kernel = np.exp(-q*q/(2*s["gaussian_sigma_px"]**2))
    kernel /= kernel.sum()
    smooth = convolve1d(roi, kernel, axis=1, mode="constant", cval=0)
    smooth = convolve1d(smooth, kernel, axis=0, mode="constant", cval=0)
    is_max = smooth == maximum_filter(smooth, size=2*s["maximum_filter_halfwidth_px"]+1,
                                     mode="constant", cval=-np.inf)
    margin = max(s["background_annulus_outer_px"], s["maximum_filter_halfwidth_px"], s["gaussian_radius_px"])
    is_max[:margin] = False; is_max[-margin:] = False
    is_max[:, :margin] = False; is_max[:, -margin:] = False
    sensitivity = np.array([[t, np.count_nonzero(is_max & (smooth > t))]
                            for t in s["sensitivity_thresholds_counts"]], dtype=float)
    y, x = np.where(is_max & (smooth > s["peak_threshold_counts"]))
    x0, y0 = p["signal_roi_xywh"][:2]
    return np.column_stack((x+x0, y+y0, smooth[y, x])), sensitivity


def aperture_metrics(image: np.ndarray, centers: np.ndarray, noise: float, p: dict) -> np.ndarray:
    """对K个中心测量圆孔与背景环，返回[K,10]，边界不完整的中心返回NaN。

    centers[K,2]为全图零基(x,y)，可为浮点；先用floor(c+0.5)对齐整数像素。
    返回列：整数anchor_x/y、环内背景中位数、圆孔sum(I-b)、圆孔max(I)-b、
    圆孔clip像素数、x/y加权标准差(px)、x/y亚像素质心(px)。
    积分保留负数；质心/二阶矩仅用I-b>3*noise的像素，权重I-b。
    noise为大背景ROI的总体标准差（计数）。二阶矩是截断孔径内的描述量，不称束腰。
    离焦时邻阱光进入孔径/背景环，本函数给出混合信号，不能视为独立光镊功率。
    """
    s = p["spots"]
    r = s["background_annulus_outer_px"]
    dy, dx = np.mgrid[-r:r+1, -r:r+1]
    rr = dx*dx+dy*dy
    aperture = rr <= s["aperture_radius_px"]**2
    annulus = (rr >= s["background_annulus_inner_px"]**2) & (rr <= r*r)
    out = np.full((len(centers), 10), np.nan)
    for i, (cx, cy) in enumerate(centers):
        if not np.all(np.isfinite([cx, cy])):
            continue
        x, y = np.floor(np.array([cx, cy])+0.5).astype(int)
        out[i, :2] = x, y
        if x-r < 0 or y-r < 0 or x+r >= image.shape[1] or y+r >= image.shape[0]:
            continue
        patch = image[y-r:y+r+1, x-r:x+r+1].astype(float)
        b = float(np.median(patch[annulus]))
        net = patch-b
        values = patch[aperture]
        out[i, 2:6] = b, net[aperture].sum(), values.max()-b, np.count_nonzero(values >= p["candidate_clip_count"])
        weight = np.where(aperture & (net > s["moment_threshold_sigma"]*noise), net, 0.0)
        mass = weight.sum()
        if mass > 0:
            mx, my = np.sum(weight*dx)/mass, np.sum(weight*dy)/mass
            out[i, 6:10] = (np.sqrt(np.sum(weight*(dx-mx)**2)/mass),
                            np.sqrt(np.sum(weight*(dy-my)**2)/mass), x+mx, y+my)
    return out


def write_csv(path: Path, columns: list[str], array: np.ndarray) -> None:
    """将二维数值数组按列名写CSV；NaN保留，UTF-8 BOM方便Excel阅读。"""
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f); writer.writerow(columns); writer.writerows(array)


def run(scan: Path, parameter_file: Path, output: Path) -> dict:
    """串联原分辨率检测与5平面观察，返回结果字典并导出MAT/CSV/PNG。

    输入scan只读；参数含用户补充光路及相机设置。横向µm仅由名义EFL换算；
    z保留探测物镜规划位置，不能用横向倍率去除Z，也不拟合未采样的轴向峰。
    先运行整体程序得到每帧背景、整体漂移。以参考帧5000个候选为固定编号，
    其他帧只平移探测孔径（按整幅阈值质心变化），不在离焦散斑中重新认领光镊。
    observed_stack[N,H/s,W/s]为固定相机ROI的块均值背景扣除栈，未配准、未归一化。
    """
    p = json.loads(parameter_file.read_text(encoding="utf-8-sig")); validate(p)
    scan, output = scan.resolve(), output.resolve()
    overview = base.run(scan, parameter_file, output / "overview")
    cfg, records = base.load_scan(scan)
    if cfg["horizontal_axis"] != "Z":
        raise ValueError("逐阱轴向分析需要探测物镜Z扫描")
    matches = np.flatnonzero(overview["data"][:, 0] == p["spots"]["reference_point_id"])
    if len(matches) != 1 or overview["status"][matches[0]] != "ok":
        raise ValueError("参考点必须有成功保存的TIFF")
    ref = int(matches[0])
    image = tifffile.imread(base.safe_file(scan, records[ref]["log"]["filename"]))
    peaks, sensitivity = detect_spots(image, p)
    if len(peaks) < 2:
        raise ValueError("少于2个候选峰，检查ROI/阈值")
    m = aperture_metrics(image, peaks[:, :2], overview["data"][ref, 13], p)
    o = p["optics"]; magnification = o["tube_lens_efl_mm"]/o["detection_objective_efl_mm"]
    pixel_um = o["sensor_pixel_pitch_um"]/magnification
    center = np.mean(m[:, 8:10], axis=0)
    if not np.all(np.isfinite(m[:, 8:10])):
        raise ValueError("参考峰有不可用质心，请检查阈值/孔径")
    nearest = cKDTree(m[:, 8:10]).query(m[:, 8:10], k=2)[0][:, 1]
    spots = np.column_stack((np.arange(1,len(peaks)+1), peaks, m[:, 8:10],
        (m[:, 8:10]-center)*pixel_um, m[:, 2:8], nearest, nearest*pixel_um))
    detail = base.crop(image, p["spots"]["detail_roi_xywh"]).copy()
    n, k = len(records), len(peaks)
    probes = np.full((n,k,len(PROBE_COLUMNS)), np.nan)
    rh,rw = p["signal_roi_xywh"][3],p["signal_roi_xywh"][2]; stride=p["preview_stride"]
    stack = np.full((n,(rh+stride-1)//stride,(rw+stride-1)//stride), np.nan)
    for i, record in enumerate(records):
        if overview["status"][i] != "ok": continue
        frame = image if i == ref else tifffile.imread(base.safe_file(scan, record["log"]["filename"]))
        shift = overview["data"][i, 18:20]-overview["data"][ref, 18:20]
        centers = peaks[:, :2]+shift
        measured = aperture_metrics(frame, centers, overview["data"][i, 13], p)
        probes[i] = measured[:, :8]
        stack[i] = base.make_preview(base.crop(frame,p["signal_roi_xywh"]),stride)-overview["data"][i,12]
    frame_info = overview["data"][:, [0,4,7,18,19]].copy()
    frame_info[:, 3:5] -= overview["data"][ref,18:20]
    calibration = np.array([magnification,pixel_um,o["target_pitch_um"]/pixel_um,center[0],center[1]])
    result = dict(spots=spots, probes=probes, observed_stack=stack, frame_info=frame_info,
        calibration=calibration, sensitivity=sensitivity, spot_columns=np.array(SPOT_COLUMNS,dtype=object),
        probe_columns=np.array(PROBE_COLUMNS,dtype=object), status=overview["status"],
        parameters_json=json.dumps(p,sort_keys=True),source=str(scan))
    savemat(output/"tweezers.mat",result,do_compression=True)
    write_csv(output/"reference_spots.csv",SPOT_COLUMNS,spots)
    write_csv(output/"frame_info.csv",["point_id","target_z_mm","planned_z_mm","global_dx_px","global_dy_px"],frame_info)
    write_csv(output/"threshold_sensitivity.csv",["threshold_counts","candidate_count"],sensitivity)
    rows=np.column_stack((np.repeat(frame_info[:,0],k),np.tile(spots[:,0],n),probes.reshape(n*k,-1)))
    write_csv(output/"aperture_probes.csv",["point_id","spot_id",*PROBE_COLUMNS],rows)
    # 排除12位顶值影响的候选，仍将全部原始测量保留在CSV中。
    valid=(spots[:,11]==0)&(spots[:,9]>0)&(spots[:,10]>0)
    summary={"reference_point_id":p["spots"]["reference_point_id"],"detected_candidates":k,
             "target_count":o["target_count"],"nominal_magnification":magnification,
             "nominal_um_per_pixel":pixel_um,"uniformity_subset_count":int(valid.sum()),
             "aperture_net_sum_cv_population":float(np.std(spots[valid,9])/np.mean(spots[valid,9])),
             "raw_peak_net_cv_population":float(np.std(spots[valid,10])/np.mean(spots[valid,10])),
             "nearest_neighbor_median_px":float(np.median(nearest)),
             "nearest_neighbor_median_nominal_um":float(np.median(nearest)*pixel_um),
             "clipped_spot_count":int(np.count_nonzero(spots[:,11])),
             "limitations":["candidate IDs are not SLM target IDs", "nominal lateral calibration only",
                            "cross-Z probes mix neighboring defocused traps", "no axial interpolation or fitted z waist",
                            "no dark/flat correction; camera gain is 18.062 dB as reported"]}
    (output/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    render(result,detail,p,output)
    return result


def render(r: dict, detail: np.ndarray, p: dict, out: Path) -> None:
    """生成逐阱空间图、检测局部图、离散XZ/YZ切片。单位和限制直接写在标题中。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    spots=r["spots"]
    fig,axes=plt.subplots(1,3,figsize=(16,5))
    for ax,col,title in zip(axes,[10,9,15],["Raw peak minus local background / counts",
            "Local aperture net sum / counts","Nearest neighbor / nominal um"]):
        sc=ax.scatter(spots[:,6],spots[:,7],c=spots[:,col],s=3,cmap="viridis")
        ax.set(xlabel="Camera x / nominal object um",ylabel="Camera y / nominal object um",title=title)
        ax.set_aspect("equal");ax.invert_yaxis();fig.colorbar(sc,ax=ax,shrink=.7)
    fig.suptitle(f"Reference point {p['spots']['reference_point_id']}: {len(spots)} detected candidates; "
                 f"gain {p['operator_camera_settings']['gain_db']} dB reported")
    fig.tight_layout();fig.savefig(out/"spot_maps.png",dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,7));x,y,w,h=p["spots"]["detail_roi_xywh"]
    ax.imshow(detail,cmap="gray",vmin=p["spots"]["detail_display_counts"][0],vmax=p["spots"]["detail_display_counts"][1],
              extent=[x-.5,x+w-.5,y+h-.5,y-.5],interpolation="nearest")
    ax.scatter(spots[:,4],spots[:,5],s=45,facecolors="none",edgecolors="tomato")
    ax.set(xlim=(x,x+w),ylim=(y+h,y),xlabel="x / pixel",ylabel="y / pixel",title="Independent peak detection (no forced target count)")
    fig.tight_layout();fig.savefig(out/"spot_detail.png",dpi=150);plt.close(fig)
    # 选择距参考阵列中心最近的候选，切片穿过其相机像素坐标，不追随全局漂移。
    i=int(np.argmin(np.sum(spots[:,6:8]**2,axis=1)));stride=p["preview_stride"]
    rx,ry,_,_=p["signal_roi_xywh"]
    ix=int((spots[i,4]-rx)//stride);iy=int((spots[i,5]-ry)//stride)
    order=np.argsort(r["frame_info"][:,1],kind="stable");z=r["frame_info"][order,1]
    fig,axes=plt.subplots(1,2,figsize=(13,5))
    for ax,values,start,origin,name in [(axes[0],r["observed_stack"][order,iy,:],rx,r["calibration"][3],"x"),
              (axes[1],r["observed_stack"][order,:,ix],ry,r["calibration"][4],"y")]:
        pos=(start+(np.arange(values.shape[1])+.5)*stride-.5-origin)*r["calibration"][1]
        if len(z)>1 and np.all(np.diff(z)>0):
            mesh=ax.pcolormesh(pos,z,values,shading="nearest",cmap="inferno",vmin=0,vmax=p["display_counts"][1]-p["display_counts"][0])
            ax.set_yticks(z)
            fig.colorbar(mesh,ax=ax,label="Block mean minus background / counts")
        else:
            for j in range(len(z)): ax.plot(pos,values[j],label=f"{z[j]:.4f} mm")
            ax.legend()
        ax.set_xlabel(f"Camera {name} / nominal object um");ax.set_ylabel("Objective target Z / mm")
    fig.suptitle("Five sampled planes; fixed camera cuts; cell colors do not imply intermediate measurements")
    fig.tight_layout();fig.savefig(out/"sampled_xz_yz.png",dpi=150);plt.close(fig)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan",type=Path);parser.add_argument("--params",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();run(args.scan,args.params,args.output)
    print(f"Tweezer observations saved: {args.output.resolve()}")
