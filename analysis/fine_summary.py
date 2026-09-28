"""从已核对的精细扫描结果生成可重复的结论统计，不重新读取201张原图。"""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.io import loadmat,savemat
from .fine_scan import axial_summary


def summarize(directory: Path) -> dict:
    """输入含fine.mat的目录，输出summary.mat/summary.json并返回字典。

    附加使用局部净峰值曲线复核核心积分给出的峰位趋势；两者来自相同照片，不视为独立实验。
    分位数采用排序后位置1+(N-1)*q的线性插值，与MATLAB显式实现一致。
    相关系数仅描述观察量的关联。CV按总体标准差计算，有效子集按主峰唯一且半高点完整筛选。
    """
    r=loadmat(directory/'fine.mat',simplify_cells=True);p=json.loads(r['parameters_json'])
    f,s,a=r['frames'],r['spots'],r['axial'];ref=int(r['reference_index'])-1;good=a[:,6]==1
    ri=int(np.flatnonzero(r['selected_indices']==ref+1)[0]);pr=r['probes'].copy();pr[:,:,2]=pr[:,:,0]
    peak_axial=axial_summary(f[r['selected_indices']-1,1],pr,ri);pg=peak_axial[:,6]==1
    z=(a[:,1]-f[ref,1])*1000;zp=(peak_axial[:,1]-f[ref,1])*1000
    def cv(x):return float(np.std(x)/np.mean(x))
    def corr(x,y):return float(np.corrcoef(x,y)[0,1]) if np.std(x)>0 and np.std(y)>0 else np.nan
    columns=['reference_point_id','reference_z_mm','candidates','valid_core_responses','valid_peak_responses',
        'reference_aperture_cv','reference_peak_cv','reference_core_cv_valid','own_max_core_cv_valid',
        'core_peak_z_vs_x_pearson','peak_peak_z_vs_x_pearson','core_width_vs_reference_core_pearson',
        'core_peak_z_vs_reference_core_pearson','roi_net_peak_to_peak_over_mean','nominal_um_per_pixel','ideal_rayleigh_um']
    stats=np.array([f[ref,0],f[ref,1],len(s),good.sum(),pg.sum(),cv(s[:,7]),cv(s[:,8]),cv(a[good,4]),cv(a[good,3]),
        corr(z[good],s[good,12]),corr(zp[pg],s[pg,12]),corr(a[good,2],a[good,4]),corr(z[good],a[good,4]),
        np.ptp(f[:,8])/np.mean(f[:,8]),p['nominal_um_per_pixel'],.61*p['wavelength_um']/p['objective_na']])
    quantiles=np.array([5,25,50,75,95.])
    widths=np.column_stack((quantiles,np.percentile(s[:,15]*p['nominal_um_per_pixel'],quantiles),
        np.percentile(s[:,16]*p['nominal_um_per_pixel'],quantiles),np.percentile(a[good,2],quantiles),np.percentile(peak_axial[pg,2],quantiles)))
    values,counts=np.unique(a[good,1],return_counts=True);histogram=np.column_stack((values,counts))
    result=dict(stats=stats,columns=np.array(columns,dtype=object),widths=widths,histogram=histogram,peak_axial=peak_axial,
                source=r['source'],parameters_json=r['parameters_json'])
    savemat(directory/'summary.mat',result,do_compression=True)
    document=dict(zip(columns,map(float,stats)));document['width_percentiles_columns']=['percentile','lateral_x_nominal_um','lateral_y_nominal_um','core_response_objective_um','peak_response_objective_um']
    document['width_percentiles']=widths.tolist();document['core_peak_z_histogram_mm_count']=histogram.tolist()
    (directory/'summary.json').write_text(json.dumps(document,indent=2),encoding='utf-8')
    print(json.dumps(document,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    summarize(parser.parse_args().directory)
