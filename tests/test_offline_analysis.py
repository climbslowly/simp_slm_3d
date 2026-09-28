import csv
import json

import numpy as np
import pytest
import tifffile
from scipy.io import savemat

from analysis import offline_scan as offline
from analysis.compare_results import compare


def parameters():
    return dict(algorithm_version=1, signal_roi_xywh=[1, 2, 6, 4],
                background_roi_xywh=[0, 0, 2, 2], threshold_sigma=5,
                candidate_clip_count=4095, radial_bin_px=1, radial_max_px=2,
                preview_stride=2, display_counts=[0, 100],
                comparison_atol=1e-8, comparison_rtol=1e-10)


def test_asymmetric_roi_centroid_and_unsigned_subtraction():
    image = np.full((8, 10), 10, dtype=np.uint16)
    image[3, 2] = 20
    image[3, 4] = 40
    image[5, 6] = 0
    metrics, radial, xp, yp = offline.measure_frame(image, [0, 0, 2, 2], parameters())
    m = dict(zip(offline.METRICS, metrics))
    assert m['net_sum'] == 30  # 10 + 30 - 10：不能 uint16 下溢
    assert m['centroid_x_px'] == 3.5
    assert m['centroid_y_px'] == 3
    assert m['sigma_x_px'] == pytest.approx(np.sqrt(.75))
    assert m['sigma_y_px'] == 0
    assert m['threshold_count'] == 2
    assert xp.shape == (6,) and yp.shape == (4,) and radial.shape == (2,)


def test_no_signal_and_invalid_roi():
    image = np.full((8, 10), 10, dtype=np.uint16)
    metrics, radial, _, _ = offline.measure_frame(image, [0, 0, 2, 2], parameters())
    assert np.isnan(metrics[10:14]).all() and np.isnan(radial).all()
    assert metrics[8] == 0
    with pytest.raises(ValueError, match='ROI'):
        offline.crop(image, [8, 0, 3, 2])
    with pytest.raises(ValueError, match='ROI'):
        offline.crop(image, [.5, 0, 2, 2])


def test_preview_includes_partial_edge_blocks():
    a = np.arange(15).reshape(3, 5)
    np.testing.assert_array_equal(offline.make_preview(a, 2), [[3, 5, 6.5], [10.5, 12.5, 14]])


def make_scan(root):
    root.mkdir()
    points = [dict(point_id=pid, order_index=i, targets_mm=dict(X=2, Y=3, Z=z))
              for i, (pid, z) in enumerate([(7, 4.2), (3, 4.0), (9, 4.1), (11, 4.3)])]
    cfg = dict(schema_version=1, scan_type='AXIS_LIST', points=points[::-1],
               roi_xywh=[0, 0, 2, 2], horizontal_axis='Z', camera_info={'shape': [8, 10]})
    (root/'scan_config.json').write_text(json.dumps(cfg), encoding='utf-8')
    rows = []
    for pt, status in zip(points[:3], ['ok', 'ok', 'error']):
        row = dict(point_id=pt['point_id'], status=status, filename=f"{pt['point_id']}.tif", roi_mean=10,
                   **{f'{prefix}_{a.lower()}_mm': pt['targets_mm'][a] for prefix in ['target', 'actual'] for a in 'XYZ'})
        rows.append(row)
    with (root/'scan_log.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows[::-1])
    tifffile.imwrite(root/'7.tif', np.full((8, 10), 10, dtype=np.uint16))
    return cfg


def test_join_by_id_missing_and_failed_points(tmp_path, monkeypatch):
    root = tmp_path/'raw'; make_scan(root)
    param = tmp_path/'p.json'; param.write_text(json.dumps(parameters()))
    monkeypatch.setattr(offline, 'render', lambda *args: None)
    result = offline.run(root, param, tmp_path/'result')
    np.testing.assert_array_equal(result['data'][:, 0], [7, 3, 9, 11])
    np.testing.assert_array_equal(result['data'][:, 4], [4.2, 4.0, 4.1, 4.3])
    assert result['status'].tolist() == ['ok', 'missing_image', 'error', 'unacquired']
    assert np.isnan(result['data'][1:, 8:]).all()
    with pytest.raises(ValueError, match='输出'):
        offline.run(root, param, root/'derived')


@pytest.mark.parametrize('kind', ['duplicate', 'coordinate', 'plane'])
def test_reject_ambiguous_input(tmp_path, kind):
    root=tmp_path/'raw'; cfg=make_scan(root)
    if kind == 'duplicate':
        cfg['points'].append(cfg['points'][0])
    elif kind == 'coordinate':
        cfg['points'][-1]['targets_mm']['Z']=100
    else:
        cfg['scan_type']='PLANE_RASTER'
    (root/'scan_config.json').write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        offline.load_scan(root)


def test_compare_rejects_numeric_or_status_mismatch(tmp_path):
    a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    payload=dict(data=np.array([[1., np.nan]]), radial=np.array([[1.,2.]]),
                 x_profile=np.array([[3.,4.]]), y_profile=np.array([[5.,6.]]),
                 columns=np.array(['a','b'],dtype=object), status=np.array(['ok'],dtype=object),
                 source=str(tmp_path), parameters_json=json.dumps(parameters()))
    savemat(a/'results.mat',payload); savemat(b/'results.mat',payload)
    assert compare(a,b)['passed']
    payload['data'][0,0]=2
    savemat(b/'results.mat',payload)
    with pytest.raises(AssertionError): compare(a,b)
    payload['data'][0,0]=1; payload['status']=np.array(['error'],dtype=object)
    savemat(b/'results.mat',payload)
    with pytest.raises(AssertionError): compare(a,b)
