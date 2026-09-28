"""复查已有逐阱结果、暗场可比性和孔径敏感性；不连接硬件，不自动扣暗场。

示例见 docs/TWEEZER_ANALYSIS.md。与 review_tweezers.m 共用 JSON 和输出列定义。
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import numpy as np
import tifffile
from scipy.io import loadmat, savemat
from scipy.spatial import cKDTree

from .offline_scan import load_scan, safe_file
from .tweezer_scan import aperture_metrics, write_csv


def cv(x: np.ndarray) -> float:
    """返回一维数组的总体标准差/均值（无量纲）；空数组或零均值返回NaN。"""
    return float(np.std(x)/np.mean(x)) if len(x) and np.mean(x) != 0 else float('nan')


def correlation(x: np.ndarray, y: np.ndarray) -> float:
    """返回两个等长一维数组的Pearson相关系数；常数/不足2点返回NaN，不推断因果。"""
    return float(np.corrcoef(x, y)[0, 1]) if len(x)>1 and np.std(x)>0 and np.std(y)>0 else float('nan')


def neighbor_edges(xy: np.ndarray, pitch: float, ratios: list[float]) -> np.ndarray:
    """返回无向近邻边[E,6]：(点序号1,点序号2,dx,dy,长度,方向组)。

    xy[K,2]为零基像素质心，pitch为最近邻中位数(px)。仅保留距离在
    [ratios[0]*pitch, ratios[1]*pitch]的边，每对只计一次，序号从1开始。
    |dx|>=|dy|归为1组，否则2组。此分组仅适用于本次接近相机轴向的方格阵列，
    不强制理想格点，不用目标5µm反推标尺；有序输出便于Python/MATLAB逐项核对。
    """
    ij=cKDTree(xy).query_pairs(pitch*ratios[1], output_type='ndarray')
    ij=ij[np.lexsort((ij[:,1],ij[:,0]))]
    d=xy[ij[:,1]]-xy[ij[:,0]]; length=np.linalg.norm(d,axis=1)
    keep=length>=pitch*ratios[0]
    group=np.where(np.abs(d[:,0])>=np.abs(d[:,1]),1,2)
    return np.column_stack((ij+1,d,length,group))[keep]


def frame_stats(image: np.ndarray, exposure: float, mat_image: np.ndarray) -> np.ndarray:
    """返回[10]：高/宽(px)、每像素字节数、最小/最大/均值/总体标准差(原始计数)、
    零像素比例、曝光(µs)、TIFF与MAT完全相同标志。空间标准差不是时间读出噪声。
    """
    return np.array([*image.shape,image.dtype.itemsize,image.min(),image.max(),image.mean(),
                     image.std(),np.mean(image==0),exposure,np.array_equal(image,mat_image)],float)


def run(result_dir: Path, dark_scan: Path, parameter_file: Path, output: Path) -> dict:
    """复核已有tweezers.mat与参考原图；导出MAT/CSV及图表，返回字典。

    旧结果内嵌参数决定孔径背景与光学比例，新的JSON只决定复查分组/半径与后补设置。
    输入不变；暗场只审计，不混用8位与12位计数。不以一个暗帧估计时间噪声。
    radial[B,6]含左右边界、数目、均值、均值/全体均值、CV；bins左闭右开。
    aperture[A,4]含半径、圆内像素数、有效数目、净积分CV；每种孔径排除顶值光点。
    """
    result_dir,dark_scan,output=map(Path,(result_dir,dark_scan,output))
    result_dir=result_dir.resolve();dark_scan=dark_scan.resolve();output=output.resolve()
    r=loadmat(result_dir/'tweezers.mat',simplify_cells=True)
    p=json.loads(r['parameters_json']);q=json.loads(parameter_file.read_text(encoding='utf-8-sig'))
    assert q['algorithm_version']==1
    assert 0<q['neighbor_distance_ratios'][0]<q['neighbor_distance_ratios'][1]
    assert np.all(np.diff(q['radial_edges_nominal_um'])>0)
    assert all(isinstance(v,int) and 0<v<p['spots']['background_annulus_inner_px'] for v in q['aperture_radii_px'])
    scan=Path(r['source']).resolve()
    for src in (scan,dark_scan,result_dir):
        if output==src or output.is_relative_to(src):
            raise ValueError('输出必须在输入目录外，保护原始数据和旧结果')
    _,records=load_scan(scan);_,dark_records=load_scan(dark_scan)
    record=next(v for v in records if v['point_id']==p['spots']['reference_point_id'])
    dark_ok=[v for v in dark_records if v['log'] and v['log']['status']=='ok']
    if len(dark_ok)!=1: raise ValueError('本复查入口要求恰好一个成功暗帧')
    record=record['log'];dr=dark_ok[0]['log']
    raw=tifffile.imread(safe_file(scan,record['filename']))
    dark=tifffile.imread(safe_file(dark_scan,dr['filename']))
    stats=np.vstack([frame_stats(im,float(log['exposure_us']),loadmat(safe_file(root,log['mat_filename']))['image'])
                     for im,log,root in [(raw,record,scan),(dark,dr,dark_scan)]])
    s=r['spots'];good=(s[:,11]==0)&(s[:,9]>0)&(s[:,10]>0);t=s[good]
    radius=np.linalg.norm(t[:,6:8],axis=1)
    summary=np.array([len(s),len(t),cv(t[:,9]),cv(t[:,10]),np.median(s[:,14]),cv(s[:,14]),
        correlation(radius,t[:,9]),correlation(t[:,9],t[:,10]),np.median(t[:,12]),np.median(t[:,13])])
    summary_columns=['candidates','valid_spots','integral_cv','peak_cv','nn_median_px','nn_cv',
                     'radius_integral_pearson','integral_peak_pearson','median_sigma_x_px','median_sigma_y_px']
    radial=[]
    for lo,hi in zip(q['radial_edges_nominal_um'][:-1],q['radial_edges_nominal_um'][1:]):
        a=t[(radius>=lo)&(radius<hi),9];mean=float(a.mean()) if len(a) else np.nan
        radial.append([lo,hi,len(a),mean,mean/t[:,9].mean(),cv(a)])
    edges=neighbor_edges(s[:,4:6],np.median(s[:,14]),q['neighbor_distance_ratios'])
    axes=[]
    for group in (1,2):
        e=edges[edges[:,5]==group];v=e[:,2:4].copy();v[v[:,group-1]<0]*=-1
        angle=np.degrees(np.arctan2(v[:,1].mean(),v[:,0].mean())) if len(v) else np.nan
        med=np.median(e[:,4]) if len(e) else np.nan
        axes.append([group,len(e),med,med*r['calibration'][1],cv(e[:,4]),angle])
    noise=loadmat(result_dir/'overview/results.mat',simplify_cells=True)['data']
    noise=float(noise[noise[:,0]==p['spots']['reference_point_id'],13][0])
    apertures=[]
    for radius_px in q['aperture_radii_px']:
        cp=copy.deepcopy(p);cp['spots']['aperture_radius_px']=radius_px
        m=aperture_metrics(raw,s[:,1:3],noise,cp);ok=(m[:,5]==0)&(m[:,3]>0)&(m[:,4]>0)
        yy,xx=np.mgrid[-radius_px:radius_px+1,-radius_px:radius_px+1]
        apertures.append([radius_px,np.count_nonzero(xx*xx+yy*yy<=radius_px**2),ok.sum(),cv(m[ok,3])])
    reasons=[]
    if raw.dtype!=dark.dtype: reasons.append('different stored pixel dtype/count encoding')
    if raw.shape!=dark.shape: reasons.append('different image shape')
    if float(record['exposure_us'])!=float(dr['exposure_us']): reasons.append('different exposure')
    if record['camera_serial']!=dr['camera_serial']: reasons.append('different camera serial')
    reasons.append('gain/pixel-format/compensation historical readback not recorded')
    audit={'dark_correction_applied':False,'direct_subtraction_supported':False,'reasons':reasons,
           'science_dtype':str(raw.dtype),'dark_dtype':str(dark.dtype),
           'dark_successful_frames':1,'reported_settings':q}
    result=dict(stats=stats,summary=summary,summary_columns=np.array(summary_columns,dtype=object),
        radial=np.array(radial),edges=edges,axes=np.array(axes),apertures=np.array(apertures),
        source=str(scan),dark_source=str(dark_scan),result_source=str(result_dir),
        parameters_json=json.dumps(q,sort_keys=True),original_parameters_json=r['parameters_json'])
    output.mkdir(parents=True,exist_ok=True)
    savemat(output/'review.mat',result,do_compression=True)
    (output/'dark_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    write_csv(output/'summary.csv',summary_columns,summary[None,:])
    write_csv(output/'radial.csv',['r_start_nominal_um','r_end_nominal_um','count','mean_net_sum','relative_mean','cv'],result['radial'])
    write_csv(output/'axes.csv',['group','edge_count','median_px','median_nominal_um','cv','angle_deg'],result['axes'])
    write_csv(output/'apertures.csv',['radius_px','area_px','valid_count','integral_cv'],result['apertures'])
    render(result,t,dark,output)
    return result


def render(r: dict, spots: np.ndarray, dark: np.ndarray, output: Path) -> None:
    """绘制本次实际数据的空间亮度、分布、径向关系、两方向间距、孔径敏感性和暗场计数。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(2,3,figsize=(15,9));a=ax.ravel()
    intensity=spots[:,9]/spots[:,9].mean()
    sc=a[0].scatter(spots[:,6],spots[:,7],c=intensity,s=3,vmin=.5,vmax=1.5,cmap='viridis')
    a[0].set(xlabel='x / nominal um',ylabel='y / nominal um',title='Local net integral / mean');a[0].invert_yaxis();a[0].set_aspect('equal');fig.colorbar(sc,ax=a[0])
    a[1].hist(intensity,bins=50);a[1].set(xlabel='Net integral / mean',ylabel='Spot count',title=f'Brightness CV = {100*r["summary"][2]:.2f}%')
    radius=np.linalg.norm(spots[:,6:8],axis=1)
    a[2].hexbin(radius,intensity,gridsize=45,mincnt=1,cmap='Greys')
    radial=r['radial']
    # 用该组实际光点的平均半径作横坐标；不能把孔边缘的点画进中央无光孔。
    mean_r=[radius[(radius>=lo)&(radius<hi)].mean() if n else np.nan for lo,hi,n,*_ in radial]
    a[2].plot(mean_r,radial[:,4],'o-',color='tomato')
    a[2].set(xlabel='Radius / nominal um',ylabel='Net integral / mean',title=f'Radial Pearson r = {r["summary"][6]:.3f}')
    for g,label in [(1,'Near x axis'),(2,'Near y axis')]:
        e=r['edges'];a[3].hist(e[e[:,5]==g,4],bins=40,alpha=.6,label=label)
    a[3].legend();a[3].set(xlabel='Edge length / px',ylabel='Unique edge count',title='Directional spacing (no target matching)')
    a[4].plot(r['apertures'][:,0],r['apertures'][:,3]*100,'o-');a[4].set(xticks=r['apertures'][:,0],ylim=(0,30),xlabel='Aperture radius / px',ylabel='Integral CV / %',title='Same local background annulus: 12-14 px')
    hist=np.bincount(dark.ravel());a[5].bar(np.arange(len(hist)),hist/dark.size);a[5].set(yscale='log',xlabel='Stored dark counts (uint8)',ylabel='Pixel fraction',title='Dark: different dtype and exposure; not subtracted')
    fig.suptitle('Current-data review: nominal lateral scale; no dark/flat correction')
    fig.tight_layout();fig.savefig(output/'current_findings.png',dpi=155);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result_dir',type=Path);parser.add_argument('dark_scan',type=Path)
    parser.add_argument('--params',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=run(args.result_dir,args.dark_scan,args.params,args.output)
    print(json.dumps(dict(zip(r['summary_columns'],r['summary'])),indent=2))
