"""真实数据之外验证半高宽、轴向退化判定及已知位移配准，防止把图案亮度变化当成移动。"""
import json
from pathlib import Path
import numpy as np
from analysis.fine_scan import half_width, axial_summary, frame_metrics, registered_metrics
from analysis.tweezer_scan import aperture_metrics


def params():
    return json.loads((Path(__file__).parents[1]/'analysis/fine_parameters_20260928.json').read_text())


def test_half_width_interpolates_and_rejects_unbracketed_peak():
    x=np.array([-2,-1,0,1,2.]);y=np.array([0,1,4,1,0.])
    assert np.isclose(half_width(x,y),4/3)
    assert np.isnan(half_width(x,np.ones(5)))
    assert np.isnan(half_width(x,np.arange(5)))
    assert np.isnan(half_width(x,np.array([0,1,np.nan,1,0])))


def test_axial_summary_does_not_claim_plateau_focus():
    probes=np.zeros((5,2,5));probes[:,0,2]=[0,1,4,1,0];probes[:,1,2]=[0,1,4,4,0]
    z=np.arange(5)*.001
    a=axial_summary(z,probes,2)
    assert a[0,6]==1 and a[0,1]==.002 and np.isclose(a[0,2],4/3)
    assert a[1,6]==0 and a[1,7]==2


def test_frame_counts_do_not_cast_to_uint8():
    p=params();p.update(signal_roi_xywh=[2,2,3,3],background_roi_xywh=[0,0,2,2])
    im=np.zeros((6,6),dtype=np.uint8);im[3,3]=100
    v=frame_metrics(im,p)
    assert v.dtype==np.float64 and v[5]>255
    assert v[4]==100 and v[6]==3 and v[7]==3


def test_local_registration_recovers_shift_despite_brightness_redistribution():
    p=params();yy,xx=np.mgrid[:130,:130];centers=np.array([[35,35],[85,35],[35,85],[85,85]])
    def image(shift,amplitudes):
        out=np.zeros_like(xx,dtype=float)
        for (x,y),amp in zip(centers,amplitudes):
            out+=amp*np.exp(-((xx-x-shift[0])**2+(yy-y-shift[1])**2)/8)
        return out
    ref=image([0,0],[100]*4);m=aperture_metrics(ref,centers,0.1,p)
    peaks=np.column_stack((centers,np.ones(4)*100))
    # 大幅改变左右相对亮度会移动全图亮度质心，但四个局部峰只有同样的已知平移。
    shifted=image([2,-1],[50,150,50,150]);a,diag=registered_metrics(shifted,peaks,m,.1,p)
    np.testing.assert_allclose(diag[:2],[2,-1],atol=.01)
    assert diag[2]==4 and diag[3]<.01
