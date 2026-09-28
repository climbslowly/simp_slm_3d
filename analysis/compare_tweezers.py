"""对比两种语言的逐阱结果（包括全部候选、失效NaN和未配准观测栈）。"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from .compare_results import compare


def compare_tweezers(left: Path, right: Path) -> dict:
    """输入两套输出目录，返回误差报告；任一身份/维度/数值冲突抛出AssertionError。

    先比较基础整体结果，再比较spots[K,16]、probes[N,K,8]、观测栈[N,Hs,Ws]等。
    不排序掩盖对应关系错误，严格按两边实际导出的编号比较。
    """
    report={"overview":compare(left/"overview",right/"overview"),"passed":True,"arrays":{}}
    a,b=[loadmat(d/"tweezers.mat",simplify_cells=True) for d in (left,right)]
    p=json.loads(a["parameters_json"])
    assert p==json.loads(b["parameters_json"]),"参数不一致"
    assert Path(a["source"]).resolve()==Path(b["source"]).resolve(),"来源不一致"
    for key in ["spot_columns","probe_columns","status"]:
        assert np.array_equal(a[key],b[key]),f"{key}不一致"
    for key in ["spots","probes","observed_stack","frame_info","calibration","sensitivity"]:
        x,y=np.asarray(a[key]),np.asarray(b[key])
        assert x.shape==y.shape,f"{key}维度不一致"
        np.testing.assert_allclose(x,y,atol=p["comparison_atol"],rtol=p["comparison_rtol"],equal_nan=True,err_msg=key)
        valid=np.isfinite(x)&np.isfinite(y)
        report["arrays"][key]={"shape":list(x.shape),"max_abs_error":float(np.max(np.abs(x[valid]-y[valid]))) if valid.any() else 0.0}
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("python_output",type=Path)
    parser.add_argument("matlab_output",type=Path);args=parser.parse_args()
    report=compare_tweezers(args.python_output,args.matlab_output)
    (args.python_output/"comparison.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
