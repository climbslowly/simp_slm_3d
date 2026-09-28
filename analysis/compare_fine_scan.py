"""比较精细扫描两种语言的来源、参数、编号、全体曲线及宽度；不匹配时报错退出。"""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.io import loadmat


def compare(left: Path,right: Path) -> dict:
    """输入两个输出目录，返回逐数组最大误差字典；NaN位置必须一致。"""
    a,b=[loadmat(d/'fine.mat',simplify_cells=True) for d in [left,right]]
    p=json.loads(a['parameters_json']);assert p==json.loads(b['parameters_json'])
    assert Path(a['source']).resolve()==Path(b['source']).resolve()
    for key in ['frame_columns','probe_columns']:assert np.array_equal(a[key],b[key]),key
    report={'passed':True,'arrays':{}}
    for key in ['frames','previews','reference_index','spots','sensitivity','selected_indices','probes','registration','axial']:
        x,y=np.asarray(a[key]),np.asarray(b[key]);assert x.shape==y.shape,key
        np.testing.assert_allclose(x,y,atol=p['comparison_atol'],rtol=p['comparison_rtol'],equal_nan=True,err_msg=key)
        valid=np.isfinite(x)&np.isfinite(y)
        report['arrays'][key]={'shape':list(x.shape),'max_abs_error':float(np.max(np.abs(x[valid]-y[valid]))) if valid.any() else 0}
    sa,sb=[loadmat(d/'summary.mat',simplify_cells=True) for d in [left,right]]
    assert np.array_equal(sa['columns'],sb['columns'])
    for item in (sa,sb):
        assert json.loads(item['parameters_json'])==p
        assert Path(item['source']).resolve()==Path(a['source']).resolve()
    for key in ['stats','widths','histogram','peak_axial']:
        x,y=np.asarray(sa[key]),np.asarray(sb[key]);assert x.shape==y.shape,key
        np.testing.assert_allclose(x,y,atol=p['comparison_atol'],rtol=p['comparison_rtol'],equal_nan=True,err_msg=key)
        valid=np.isfinite(x)&np.isfinite(y)
        report['arrays']['summary_'+key]={'shape':list(x.shape),'max_abs_error':float(np.max(np.abs(x[valid]-y[valid]))) if valid.any() else 0}
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('python_output',type=Path);parser.add_argument('matlab_output',type=Path)
    args=parser.parse_args();report=compare(args.python_output,args.matlab_output)
    (args.python_output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
