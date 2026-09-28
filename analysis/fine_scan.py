"""1µm探测物镜Z扫描：流式总览、参考光点、近焦响应及关联。中文示例见FINE_SCAN.md。

不把相机观察到的轴向响应称为光镊真实三维势阱；没有轴向物方标定或探测PSF反卷积。
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import tifffile
from scipy.io import loadmat, savemat
from . import offline_scan as base
from .tweezer_scan import detect_spots, aperture_metrics, write_csv

FRAME_COLUMNS=['point_id','target_z_mm','planned_z_mm','exposure_us','background_mean','background_std',
               'image_max','clip_pixels','roi_net_sum','gradient_energy','centroid_x_px','centroid_y_px']
PROBE_COLUMNS=['local_peak','aperture_net_sum','core_net_sum','centroid_x_px','centroid_y_px']


def half_width(x: np.ndarray, y: np.ndarray) -> float:
    """返回一维非负峰的零背景半高宽，单位与x一致；未被两侧半高交点包围返回NaN。

    x[L]严格递增，y[L]为已经扣除背景的信号，可有负数。选择首个全局最大值，
    从峰向两侧找最近的y<=峰/2位置并线性插值。不拟合高斯，不把缺少交点当成零宽度。
    多峰曲线只描述主峰连通半高区间，不能自动证明只有一个物理焦点。
    """
    if len(x)<3 or not np.all(np.isfinite(y)) or not np.all(np.diff(x)>0): return np.nan
    i=int(np.argmax(y));h=y[i]/2
    if h<=0 or i==0 or i==len(y)-1:return np.nan
    left=np.flatnonzero(y[:i]<=h);right=np.flatnonzero(y[i+1:]<=h)
    if not len(left) or not len(right):return np.nan
    l=int(left[-1]);rr=int(right[0]+i+1)
    xl=x[l]+(h-y[l])*(x[l+1]-x[l])/(y[l+1]-y[l])
    xr=x[rr-1]+(h-y[rr-1])*(x[rr]-x[rr-1])/(y[rr]-y[rr-1])
    return float(xr-xl)


def frame_metrics(image: np.ndarray, p: dict) -> np.ndarray:
    """image[H,W]原始计数；返回[8]背景均值/总体标准差、最大值、截顶像素数、
    ROI净积分、梯度能量、全图零基x/y质心(px)。质心仅使用I-b>5σ像素。
    使用行列和降低内存，不一次载入201张原始大图。梯度只在固定ROI计算。
    """
    bg=base.crop(image,p['background_roi_xywh']);b=float(bg.mean());noise=float(bg.std())
    roi=base.crop(image,p['signal_roi_xywh']).astype(float);net=roi-b
    w=np.where(net>p['threshold_sigma']*noise,net,0);mass=w.sum()
    x0,y0,_,_=p['signal_roi_xywh']
    cx=np.dot(w.sum(axis=0),np.arange(w.shape[1])+x0)/mass if mass else np.nan
    cy=np.dot(w.sum(axis=1),np.arange(w.shape[0])+y0)/mass if mass else np.nan
    return np.array([b,noise,image.max(),np.count_nonzero(image>=p['candidate_clip_count']),net.sum(),
                     np.mean(np.diff(roi,axis=1)**2)+np.mean(np.diff(roi,axis=0)**2),cx,cy])


def core_and_profiles(image: np.ndarray, anchors: np.ndarray, backgrounds: np.ndarray, p: dict,
                      profiles: bool=False) -> tuple[np.ndarray,np.ndarray]:
    """对K个整数中心计算半径3px核心净积分；可同时计算横/纵剖面FWHM。

    anchors[K,2]是全图零基(x,y)，backgrounds[K]为每个光点的背景环中位数。
    返回core[K]计数和widths[K,2]像素。横/纵剖面分别平均中心附近3行/3列，
    在±11px范围内找半高交点。此宽度描述观察光斑，不是独立标定的系统分辨率或束腰。
    """
    cr=p['core_radius_px'];yy,xx=np.mgrid[-cr:cr+1,-cr:cr+1];mask=xx*xx+yy*yy<=cr*cr
    dx,dy=xx[mask],yy[mask];core=np.full(len(anchors),np.nan);widths=np.full((len(anchors),2),np.nan)
    rad=p['spots']['aperture_radius_px'];line=np.arange(-rad,rad+1,dtype=float)
    for i,(cx,cy) in enumerate(anchors):
        if not np.all(np.isfinite([cx,cy,backgrounds[i]])):continue
        x,y=int(cx),int(cy)
        if x-rad<0 or y-rad<0 or x+rad>=image.shape[1] or y+rad>=image.shape[0]:continue
        core[i]=np.sum(image[y+dy,x+dx].astype(float)-backgrounds[i])
        if profiles:
            hx=image[y-1:y+2,x-rad:x+rad+1].mean(axis=0)-backgrounds[i]
            hy=image[y-rad:y+rad+1,x-1:x+2].mean(axis=1)-backgrounds[i]
            widths[i]=half_width(line,hx),half_width(line,hy)
    return core,widths


def axial_summary(z_mm: np.ndarray, probes: np.ndarray, reference_index: int) -> np.ndarray:
    """输入z[N](物镜mm)与probes[N,K,5]；返回[K,8]。

    列为：1基编号、主峰Z(mm)、核心响应FWHM(物镜µm)、主峰核心计数、共同参考面核心计数、
    最大值/参考值、有效标志、离散全局最大值并列数。有效要求有限、正峰、半高宽可测且峰唯一。
    Z峰位置保留实际1µm采样网格，不伪造亚步距精度；FWHM线性插值只是描述采样曲线。
    """
    out=np.full((probes.shape[1],8),np.nan)
    for j in range(probes.shape[1]):
        y=probes[:,j,2];i=int(np.argmax(y));width=half_width(z_mm*1000,y)
        peak=float(y[i]);ref=float(y[reference_index]);ties=int(np.count_nonzero(y==peak))
        valid=np.all(np.isfinite(y)) and np.isfinite(width) and peak>0 and ties==1
        out[j]=j+1,z_mm[i],width,peak,ref,peak/ref if ref>0 else np.nan,float(valid),ties
    return out


def registered_metrics(image: np.ndarray,peaks: np.ndarray,reference: np.ndarray,noise: float,p: dict):
    """根据相同编号光点的局部质心进行刚性配准，返回测量[K,10]与诊断[4]。

    peaks[K,3]为参考检测峰，reference[K,10]为参考孔径测量，noise为当前背景计数标准差。
    诊断是dx/dy(px)、用于检查的点数、配准后质心残差RMS(px)。用中位数降低异常点影响。
    净峰超过参考的10%且质心有限才参与；三次迭代后测量核心积分的中心由全体共同平移决定。
    """
    shift=np.zeros(2)
    for _ in range(3):
        trial=aperture_metrics(image,peaks[:,:2]+shift,noise,p)
        ok=np.all(np.isfinite(trial[:,8:10]),axis=1)&(trial[:,4]>.10*reference[:,4])
        if np.count_nonzero(ok)<len(peaks)/2:raise ValueError('可配准光点不足，需缩小近焦窗口')
        shift=np.median(trial[ok,8:10]-reference[ok,8:10],axis=0)
    a=aperture_metrics(image,peaks[:,:2]+shift,noise,p)
    ok=np.all(np.isfinite(a[:,8:10]),axis=1)&(a[:,4]>.10*reference[:,4])
    residual=a[ok,8:10]-reference[ok,8:10]-shift
    return a,np.array([*shift,ok.sum(),np.sqrt(np.mean(np.sum(residual**2,axis=1)))])


def run(scan: Path, parameter_file: Path, output: Path) -> dict:
    """只读扫描，先处理全部帧，再围绕最清晰平面分析±10µm内的光点响应。

    图像位移通过三次迭代的逐点质心差中位数估计，输出配准残差。
    整幅阈值质心会随离焦改变，不能用作精细的刚性配准量。
    没有暗场/平场扣除，跨旧扫描不把不同曝光/编码的计数直接比较。
    Python与MATLAB读取同一参数，分别计算并输出fine.mat供逐数组核对。
    """
    scan,output=scan.resolve(),output.resolve()
    if output==scan or output.is_relative_to(scan):raise ValueError('输出不能位于原始扫描内')
    p=json.loads(parameter_file.read_text(encoding='utf-8-sig'));base.validate_parameters(p)
    assert p['algorithm_version']==1 and p['focus_half_window_um']>0 and p['nominal_um_per_pixel']>0
    assert 0<p['core_radius_px']<=p['spots']['aperture_radius_px']<p['spots']['background_annulus_inner_px']<p['spots']['background_annulus_outer_px']
    cfg,records=base.load_scan(scan);assert cfg['horizontal_axis']=='Z'
    if any(r['log']['status']!='ok' for r in records):raise ValueError('精细分析要求完整成功扫描，不能跳过缺帧插值')
    output.mkdir(parents=True,exist_ok=True);rows=[];previews=[];audit=[]
    for i,r in enumerate(records):
        log=r['log'];im=tifffile.imread(base.safe_file(scan,log['filename']))
        fm=loadmat(base.safe_file(scan,log['mat_filename']),simplify_cells=True)
        assert np.array_equal(im,fm['image']) and fm['point_id']==r['point_id'],'TIFF/MAT不一致'
        assert im.dtype==np.uint8 and im.ndim==2,'本次参数要求8位二维图'
        assert float(fm['exposure_us'])==float(log['exposure_us'])
        np.testing.assert_allclose(fm['target_xyz_mm'],[r['targets_mm'][a] for a in 'XYZ'],atol=1e-9,rtol=0)
        rows.append([r['point_id'],r['targets_mm']['Z'],float(log['actual_z_mm']),float(log['exposure_us']),*frame_metrics(im,p)])
        previews.append(base.make_preview(base.crop(im,p['signal_roi_xywh']),p['preview_stride']))
        audit.append({'point_id':r['point_id'],'dtype':str(im.dtype),'shape':list(im.shape),'tiff_mat_identical':True})
        if i%25==0:print(f'Overview {i+1}/{len(records)}',flush=True)
    (output/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    frames=np.array(rows);previews=np.array(previews);assert np.all(np.diff(frames[:,1])>0)
    assert np.ptp(frames[:,3])==0,'曝光改变需单独分析'
    return analyze_focus(scan,records,frames,previews,p,output)


def analyze_focus(scan: Path,records: list,frames: np.ndarray,previews: np.ndarray,p: dict,output: Path) -> dict:
    """用已核验的全扫描指标、预览数组及相同原图分析近焦响应；供run调用。

    frames[N,12]与previews[N,h,w]必须来自同一扫描和参数，不能混入旧12位扫描。
    局部配准保留净峰>参考净峰10%的点，三次中位数迭代；至少一半点有效。
    """
    ref=int(np.argmax(frames[:,9]));image=tifffile.imread(base.safe_file(scan,records[ref]['log']['filename']))
    peaks,sensitivity=detect_spots(image,p);assert len(peaks)>1
    m=aperture_metrics(image,peaks[:,:2],frames[ref,5],p)
    core,widths=core_and_profiles(image,m[:,:2],m[:,2],p,True)
    # spots列：ID,x/y峰位置,平滑峰,m的10列,核心积分,横/纵FWHM。
    spots=np.column_stack((np.arange(1,len(peaks)+1),peaks,m,core,widths))
    selected=np.flatnonzero(np.abs((frames[:,1]-frames[ref,1])*1000)<=p['focus_half_window_um']+1e-7)
    probes=np.full((len(selected),len(peaks),5),np.nan);registration=[]
    for j,i in enumerate(selected):
        im=image if i==ref else tifffile.imread(base.safe_file(scan,records[i]['log']['filename']))
        a,diag=registered_metrics(im,peaks,m,frames[i,5],p)
        registration.append(diag)
        c,_=core_and_profiles(im,a[:,:2],a[:,2],p)
        probes[j]=np.column_stack((a[:,4],a[:,3],c,a[:,8:10]))
    axial=axial_summary(frames[selected,1],probes,int(np.flatnonzero(selected==ref)[0]))
    result=dict(frames=frames,previews=previews,reference_index=ref+1,spots=spots,sensitivity=sensitivity,
                selected_indices=selected+1,probes=probes,registration=np.array(registration),axial=axial,source=str(scan),
                parameters_json=json.dumps(p,sort_keys=True),frame_columns=np.array(FRAME_COLUMNS,dtype=object),
                probe_columns=np.array(PROBE_COLUMNS,dtype=object))
    savemat(output/'fine.mat',result,do_compression=True)
    write_csv(output/'frames.csv',FRAME_COLUMNS,frames)
    write_csv(output/'axial.csv',['spot_id','peak_z_mm','core_response_fwhm_um','peak_core','reference_core','ratio','valid','peak_ties'],axial)
    write_csv(output/'spots.csv',['spot_id','peak_x_px','peak_y_px','smoothed_peak','anchor_x_px','anchor_y_px','local_background',
        'aperture_net_sum','peak_net','clip_pixels','sigma_x_px','sigma_y_px','centroid_x_px','centroid_y_px','core_net_sum','fwhm_x_px','fwhm_y_px'],spots)
    render(result,p,output)
    render_detail(scan,records,result,output)
    return result


def render(r: dict,p: dict,out: Path) -> None:
    """输出真实Z位置对应照片、总体趋势和逐点近焦响应；颜色及物理单位保持一致。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    f=r['frames'];ref=int(r['reference_index'])-1;z=(f[:,1]-f[ref,1])*1000
    indices=np.unique([0,len(f)-1,*[int(np.argmin(np.abs(z-v))) for v in [-10,-5,-2,0,2,5,10]]])
    fig,axs=plt.subplots(3,3,figsize=(11,11))
    for ax,i in zip(axs.ravel(),indices):
        ax.imshow(r['previews'][i],cmap='inferno',vmin=0,vmax=10);ax.set_title(f'ID {int(f[i,0])}; Z={f[i,1]:.4f} mm');ax.axis('off')
    for ax in axs.ravel()[len(indices):]:ax.axis('off')
    fig.suptitle('Same count scale; 16x16 block means for whole-array view')
    fig.tight_layout();fig.savefig(out/'position_images.png',dpi=140);plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(12,8))
    for ax,col,label in zip(axs.ravel(),[9,8,10,11],['Gradient energy / counts^2','ROI net sum / counts','Centroid x / px','Centroid y / px']):
        ax.plot(z,f[:,col]);ax.axvline(0,color='gray',ls=':');ax.set(xlabel='Objective Z relative to sharpest sample / um',ylabel=label)
    fig.tight_layout();fig.savefig(out/'scan_metrics.png',dpi=150);plt.close(fig)
    good=r['axial'][:,6]==1;s=r['spots'];a=r['axial'];xy=(s[:,12:14]-s[:,12:14].mean(axis=0))*p['nominal_um_per_pixel']
    fig,axs=plt.subplots(2,2,figsize=(12,9))
    sc=axs[0,0].scatter(xy[good,0],xy[good,1],c=(a[good,1]-f[ref,1])*1000,s=4,cmap='coolwarm',vmin=-2,vmax=2)
    axs[0,0].set(xlabel='x / nominal um',ylabel='y / nominal um',title='Core-response peak Z / objective um');axs[0,0].invert_yaxis();axs[0,0].set_aspect('equal');fig.colorbar(sc,ax=axs[0,0])
    axs[0,1].hist(a[good,2],bins=40);axs[0,1].set(xlabel='Core-response FWHM / objective um',ylabel='Spot count',title='Observed response, not deconvolved trap width')
    zp=z[r['selected_indices']-1];valid_ids=np.flatnonzero(good)
    # 用全体响应宽度分位点附近的五条曲线展示，避免峰位相同时重复挑同一个光点。
    for quantile in [0,.25,.5,.75,1]:
        i=valid_ids[np.argmin(np.abs(a[good,2]-np.quantile(a[good,2],quantile)))]
        axs[1,0].plot(zp,r['probes'][:,i,2]/a[i,3],'.-',label=f'ID {i+1}')
    axs[1,0].legend();axs[1,0].set(xlabel='Objective Z offset / um',ylabel='Core integral / own maximum',title='Five representative observed axial responses')
    for j,label in [(15,'x'),(16,'y')]:axs[1,1].hist(s[:,j]*p['nominal_um_per_pixel'],bins=40,alpha=.5,label=label)
    axs[1,1].legend();axs[1,1].set(xlabel='Observed lateral FWHM / nominal um',ylabel='Spot count',title='3-row/column averaged cross-sections at reference')
    fig.suptitle(f'Observed near-focus response: {good.sum()} valid / {len(good)} candidates; Z peaks on sampled grid')
    fig.tight_layout();fig.savefig(out/'focus_maps.png',dpi=150);plt.close(fig)


def render_detail(scan: Path,records: list,r: dict,out: Path) -> None:
    """用同一相机坐标300×300px原始裁剪展示Z变化；不平滑、不逐帧拉伸亮度。

    本次显示ROI=[3700,2250,300,300]，只影响报告图片，不参与测量或峰检测。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    f=r['frames'];ref=int(r['reference_index'])-1;z=(f[:,1]-f[ref,1])*1000
    fig,axs=plt.subplots(2,3,figsize=(11,8))
    for ax,offset in zip(axs.ravel(),[-4,-2,0,1,2,4]):
        i=int(np.argmin(np.abs(z-offset)));im=tifffile.imread(base.safe_file(scan,records[i]['log']['filename']))
        ax.imshow(im[2250:2550,3700:4000],cmap='inferno',vmin=0,vmax=100,interpolation='nearest')
        ax.set_title(f'ID {int(f[i,0])}; Z={f[i,1]:.4f} mm');ax.axis('off')
    fig.suptitle('Same raw 300 x 300 px crop; common 0-100 counts; no frame normalization')
    fig.tight_layout();fig.savefig(out/'near_focus_images.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('scan',type=Path)
    parser.add_argument('--params',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.scan,args.params,args.output)
