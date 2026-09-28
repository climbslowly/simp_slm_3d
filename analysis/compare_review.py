"""核对独立执行的Python/MATLAB复查：参数、来源、列和所有数值必须相同。"""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.io import loadmat


def compare(left: Path, right: Path) -> dict:
    """输入两输出目录；返回逐数组最大误差报告，不匹配抛异常（CLI失败退出）。"""
    a,b=[loadmat(d/'review.mat',simplify_cells=True) for d in (left,right)]
    p=json.loads(a['parameters_json'])
    for key in ['parameters_json','original_parameters_json']:
        assert json.loads(a[key])==json.loads(b[key]),key
    for key in ['source','dark_source']:
        assert Path(a[key]).resolve()==Path(b[key]).resolve(),key
    assert np.array_equal(a['summary_columns'],b['summary_columns'])
    audits=[json.loads((d/'dark_audit.json').read_text(encoding='utf-8')) for d in (left,right)]
    assert audits[0]==audits[1],'暗场可比性判定不一致'
    report={'passed':True,'arrays':{}}
    for key in ['stats','summary','radial','edges','axes','apertures']:
        x,y=np.asarray(a[key]),np.asarray(b[key]);assert x.shape==y.shape,key
        np.testing.assert_allclose(x,y,atol=p['comparison_atol'],rtol=p['comparison_rtol'],equal_nan=True,err_msg=key)
        finite=np.isfinite(x)&np.isfinite(y)
        report['arrays'][key]={'shape':list(x.shape),'max_abs_error':float(np.max(np.abs(x[finite]-y[finite]))) if finite.any() else 0}
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('python_output',type=Path);parser.add_argument('matlab_output',type=Path)
    args=parser.parse_args();report=compare(args.python_output,args.matlab_output)
    (args.python_output/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
