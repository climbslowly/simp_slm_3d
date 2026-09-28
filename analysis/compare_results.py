"""核对两套实际运行的结果：python -m analysis.compare_results python_dir matlab_dir。"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import loadmat


def compare(left: Path, right: Path) -> dict:
    """读取两个目录的 results.mat，返回逐数组最大绝对误差及通过状态。

    参数 left/right 为 Python/MATLAB 输出目录；数值数组须形状一致且 NaN 位置一致。
    使用共用参数中的 atol + rtol*abs(reference) 容差；状态、列名、源目录、参数
    必须一致。失败抛出 AssertionError，CLI 以非零状态退出，不能仅凭目测宣称一致。
    """
    a, b = [loadmat(d / "results.mat", simplify_cells=True) for d in (left, right)]
    pa, pb = [json.loads(v["parameters_json"]) for v in (a, b)]
    assert pa == pb, "参数不一致"
    assert Path(a["source"]).resolve() == Path(b["source"]).resolve(), "输入来源不一致"
    for key in ("columns", "status"):
        assert np.array_equal(a[key], b[key]), f"{key} 不一致"
    report = {"passed": True, "rtol": pa["comparison_rtol"], "atol": pa["comparison_atol"], "arrays": {}}
    for key in ("data", "radial", "x_profile", "y_profile"):
        x, y = np.asarray(a[key]), np.asarray(b[key])
        assert x.shape == y.shape, f"{key} 维度不一致"
        np.testing.assert_allclose(x, y, rtol=report["rtol"], atol=report["atol"], equal_nan=True, err_msg=key)
        finite = np.isfinite(x) & np.isfinite(y)
        report["arrays"][key] = {"shape": list(x.shape), "max_abs_error": float(np.max(np.abs(x[finite]-y[finite]))) if finite.any() else 0.0}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python_output", type=Path)
    parser.add_argument("matlab_output", type=Path)
    args = parser.parse_args()
    report = compare(args.python_output, args.matlab_output)
    (args.python_output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
