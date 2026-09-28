"""独立构造已知光点，检查检测、坐标与非正净信号的处理。"""
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.tweezer_scan import aperture_metrics, detect_spots, validate


def parameters():
    p=json.loads((Path(__file__).parents[1]/'analysis/tweezer_parameters_20260928.json').read_text())
    p['signal_roi_xywh']=[5,7,80,70]
    p['background_roi_xywh']=[0,0,5,5]
    p['spots'].update(gaussian_radius_px=3, gaussian_sigma_px=1, maximum_filter_halfwidth_px=4,
                      aperture_radius_px=3, background_annulus_inner_px=4,
                      background_annulus_outer_px=5, peak_threshold_counts=50,
                      sensitivity_thresholds_counts=[50,500,2000])
    return p


def test_peak_coordinates_and_count_not_forced_to_target():
    p=parameters();y,x=np.mgrid[:90,:100];image=np.full((90,100),10.)
    # 已知三个分离高斯点。target_count仍为5000，不能强行填充或取前5000。
    expected=np.array([[30,25],[60,25],[45,55]])
    for (cx,cy),amp in zip(expected,[1000,800,300]):
        image+=amp*np.exp(-((x-cx)**2+(y-cy)**2)/8)
    peaks,sensitivity=detect_spots(image,p)
    np.testing.assert_array_equal(peaks[:,:2],expected)
    np.testing.assert_array_equal(sensitivity[:,1],[3,2,0])
    assert peaks.shape==(3,3)


def test_aperture_preserves_negative_counts_and_subpixel_moments():
    p=parameters();im=np.full((50,50),10,dtype=np.uint16)
    im[20,20]=20;im[20,22]=40;im[21,20]=0
    m=aperture_metrics(im,np.array([[20.,20.]]),0,p)[0]
    assert m[2]==10
    assert m[3]==30  # 10+30-10，而不是无符号溢出或删除负值
    assert m[4]==30 and m[5]==0
    assert m[6]==pytest.approx(np.sqrt(.75)) and m[7]==0
    assert m[8]==21.5 and m[9]==20


def test_empty_signal_and_boundary_probes_are_not_zero_filled():
    p=parameters();im=np.full((50,50),10,dtype=np.uint16)
    m=aperture_metrics(im,np.array([[20,20],[1,1],[np.nan,5]]),1,p)
    assert m[0,3]==0 and np.isnan(m[0,6:]).all()
    assert np.isnan(m[1,2:]).all() and np.isnan(m[2]).all()


def test_clip_count_and_rounding_match_matlab_rule():
    p=parameters();im=np.full((50,50),10,dtype=np.uint16);im[20,20]=4095
    m=aperture_metrics(im,np.array([[19.5,19.5]]),1,p)[0]
    np.testing.assert_array_equal(m[:2],[20,20])
    assert m[5]==1


def test_reject_calibration_binning_and_annulus_conflicts():
    p=parameters();validate(p)
    p['operator_camera_settings']['binning_horizontal']=2
    with pytest.raises(ValueError,match='Binning'):validate(p)
    p=parameters();p['spots']['background_annulus_inner_px']=2
    with pytest.raises(ValueError,match='背景环'):validate(p)
