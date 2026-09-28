"""验证几何边去重、单帧暗图统计及退化数据处理，不使用真实相机。"""
import numpy as np
from analysis.review_tweezers import neighbor_edges, frame_stats, cv, correlation


def test_rotated_rectangular_grid_keeps_edges_not_diagonals():
    xy=np.array([[0,0],[10,0],[0,11],[10,11]],float)
    angle=np.deg2rad(-3)
    xy=xy@np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])
    e=neighbor_edges(xy,10,[.75,1.25])
    np.testing.assert_array_equal(e[:,:2],[[1,2],[1,3],[2,4],[3,4]])
    np.testing.assert_allclose(e[:,4],[10,11,11,10])
    np.testing.assert_array_equal(e[:,5],[1,2,2,1])
    assert len(set(map(tuple,e[:,:2])))==4


def test_dark_stats_preserve_dtype_and_zero_fraction():
    a=np.array([[0,0],[0,4]],dtype=np.uint8)
    v=frame_stats(a,1000,a.copy())
    np.testing.assert_allclose(v,[2,2,1,0,4,1,np.sqrt(3),.75,1000,1])
    b=a.copy();b[0,0]=1
    assert frame_stats(a,1000,b)[-1]==0
    assert frame_stats(a.astype(np.uint16),1763,a.astype(np.uint16))[2]==2


def test_undefined_statistics_are_not_reported_as_zero():
    assert np.isnan(cv(np.array([])))
    assert np.isnan(cv(np.array([-1,1])))
    assert np.isnan(correlation(np.ones(3),np.arange(3)))
    assert np.isclose(correlation(np.arange(3),np.arange(3)[::-1]),-1)
