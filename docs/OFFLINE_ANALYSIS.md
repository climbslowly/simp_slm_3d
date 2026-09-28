# 离线单轴扫描分析：Python / MATLAB

本入口只读磁盘文件，不连接硬件。二维硬件测试继续暂缓。本版处理 GUI schema 1 的
`AXIS_RANGE` / `AXIS_LIST`，明确拒绝二维数据；不能把单轴测试外推成二维已验收。

## 1. 先运行位置—照片总览

在 PowerShell 中运行：

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe -m pip install -r requirements-analysis.txt
.\.venv\Scripts\python.exe -m analysis.offline_scan `
  output/gui_m1/20260928_135701_746_gui_real `
  --params analysis/parameters_20260928.json `
  --output output/offline_20260928/python --show
```

`--show` 打开照片滑条浏览器、总览、指标图和径向剖面；关闭这些窗口后程序结束。
不加 `--show` 则直接保存 PNG，适合批处理。滑条编号为采集顺序，从 1 开始，
标题同时显示原始 point_id 和绝对 XYZ。红框为信号 ROI，青框为采集时 ROI。
工具栏支持缩放/平移，但预览采用块均值降采样，不能用预览检查单像素坏点或细网格。
这类检查请直接读取 TIFF/MAT 原图。

在 MATLAB R2024b（本机已实跑，无额外工具箱）中运行：

```matlab
cd('C:\slm_3d\dimension_camera');
addpath('analysis');
r = analyze_scan( ...
    'output/gui_m1/20260928_135701_746_gui_real', ...
    'analysis/parameters_20260928.json', ...
    'output/offline_20260928/matlab', true);
```

第四个参数为 `false` 时仅保存图片。MATLAB 图像浏览器使用滑条切换点位。
程序用 `imread/imagesc`，不依赖 Image Processing Toolbox；路径规范化使用 MATLAB 自带 JVM。
其他 MATLAB 版本未实测。

输出目录必须在原始扫描目录之外。同一个输出目录重复运行会更新该目录里的派生结果，
需要保留参数试验时请更换输出目录。真实数据和派生图表均留在已忽略的 `output/` 下。

## 2. 输出文件和数组约定

| 文件 | 用途 |
|---|---|
| `position_images.png` | 所有计划点对应照片，共用固定灰度范围；缺图点仍保留标题和状态 |
| `metrics.png` | 背景/原 ROI、净计数和、清晰度、质心、二阶矩宽度、最大值曲线 |
| `radial_profiles.png` | 各帧以自身阈值质心为圆心的径向平均曲线 |
| `metrics.csv` | 每计划点一行，含绝对目标/规划位置、16个指标、状态和原图路径 |
| `results.mat` | 完整数值结果，Python/MATLAB 使用相同变量名 |
| `parameters.json` | 实际运行参数副本 |
| `audit.json` | Python 额外记录像素哈希、shape/dtype、TIFF/MAT一致性、原ROI复算误差和输入元数据哈希 |
| `comparison.json` | 对比脚本通过后记录的容差、数组维度和最大差异 |

MAT 中 `data` 为 `[N,24]`，前8列是 ID、顺序、目标XYZ、规划XYZ，后16列按
`columns` 命名。`radial` 为 `[N,B]`，`x_profile` 为 `[N,Wroi]`，
`y_profile` 为 `[N,Hroi]`。MATLAB 的 `data(:,5)` 对应 Python 的 `data[:,4]`。
`status` 与每行一一对应。失败、未采集、成功但缺 TIFF 分别保留为原状态、
`unacquired`、`missing_image`，指标为 NaN。存在但损坏/维度错误的图像直接报错。
成功帧只在 TIFF 存在时重新计算；不静默用 MAT 替换缺失 TIFF。

程序以 JSON 计划为基准，通过 point_id 关联 CSV，按 order_index 排序；不依赖文件名排序。
非等距或乱序 list 保留原采集顺序，画曲线时才按绝对扫描坐标排序。重复 point_id、
重复 order_index、计划外记录、成功点坐标冲突会报错，避免悄悄选错照片。

## 3. 坐标与原数据含义

- `targets_mm` / CSV `target_*_mm` 已是**绝对逻辑物镜坐标**，不要再加起点。
- `RELATIVE_TO_SCAN_START` 下的 `horizontal_values` 是输入偏移；汇总 MAT 的
  `horizontal_values_mm` 也可能仍是偏移，不能直接当绝对坐标。
- REAL 的 `actual_*_mm` 来源是 `GA_GetPrfPos planned position`，所以离线表中更名为
  `planned_*_mm`；目标与规划位置相等不证明机械定位误差为零。
- 逻辑物镜 X/Y/Z 对应控制器轴3/5/4，其中 Y 正向使用控制器负向；Z 正向是物理 +X、
  逆光传播方向。相机 XY 是固定定位轴，并非扫描轴。
- 图像为 `[行y,列x]`，x向右、y向下；这两个像素方向与物镜坐标的物理关系尚未标定。
- ROI `[x,y,w,h]` 是零基像素索引。Python：`image[y:y+h,x:x+w]`；
  MATLAB：`image(y+1:y+h,x+1:x+w)`。point_id 从1开始，order_index 从0开始。

## 4. 两种语言共用的算法

`analysis/parameters_20260928.json` 是针对这组图像人工检查后确定的固定参数，
不适用于任意相机尺寸；换数据时先检查图像和 ROI。本次信号 ROI `[2400,1200,3000,3200]`，
背景 ROI `[0,0,1024,1024]`。原采集 ROI 从配置读取，用作独立对照。

设信号 ROI 为 I，背景 ROI 均值为 b，总体标准差为 s（除以像素数 N，非 N−1）。
所有计算先转 double/float64：

| 输出 | 计算与单位 | 解读边界 |
|---|---|---|
| image_min / image_max | 全图最小/最大原始计数 | 最大值可能受单像素异常影响 |
| candidate_clip_pixels | 全图 `I>=4095` 的像素数量 | 4095 是候选阈值，不声称已知现场有效位深 |
| acquisition_roi_mean | 原采集ROI均值，计数 | 原ROI未必覆盖有效信号 |
| background_mean / std | 背景空间均值/总体标准差，计数 | 不是暗场，也不是多次曝光得到的时间噪声 |
| signal_mean / signal_sum | 固定信号ROI原始均值/总和 | 总和单位是计数之和，不是标定光功率 |
| net_sum | `sum(I-b)`，保留负值 | 仅减一个常量背景，未做暗场/平场校正 |
| threshold_counts / count | `T=b+5*s`；统计严格 `I>T` 的像素数 | 阈值影响形状，不影响 net_sum |
| centroid_x/y_px | 对 `I>T` 像素以 `I-b` 为权重计算质心 | 使用全图零基像素坐标 |
| sigma_x/y_px | 同一权重的加权标准差，px | 二阶矩描述，不能称为高斯束腰/FWHM |
| gradient_energy | `mean(diff_x(I)^2)+mean(diff_y(I)^2)` | 计数²/像素²，受亮度、纹理、噪声影响 |

质心计算示例：`cx=sum(w*x)/sum(w)`，`sigma_x=sqrt(sum(w*(x-cx)^2)/sum(w))`。
无像素超过阈值时，质心/宽度/径向剖面为 NaN。

径向剖面：围绕该帧质心，以10px分箱，半径区间 `[0,10),[10,20),...,[1390,1400)`，
对箱内 `I-b` 求均值；横坐标为箱中心5、15、…1395px。只显示完整落在信号 ROI 内的环带，
无样本或不完整环带为 NaN，不插值、不平滑、不做高斯拟合。不同帧的圆心跟随质心，
用于比较形状；绝对漂移需看 centroid 曲线。

横向投影为 `mean(I-b, axis=0)`，纵向投影为 `mean(I-b, axis=1)`，均为计数。
图片固定显示60～600计数，高于600只影响显示变白，不改变任何计算；预览使用4×4块均值，
边缘不足4像素时按实际数量平均，两种语言使用相同规则。

## 5. Python 学习路径

建议依次阅读 `load_scan → crop → measure_frame → run → render`。主要函数均有中文
docstring，解释参数、返回值、维度、单位和边界条件。先尝试只分析一帧：

```python
from pathlib import Path
import json
import tifffile
from analysis.offline_scan import METRICS, measure_frame

root = Path('output/gui_m1/20260928_135701_746_gui_real')
p = json.loads(Path('analysis/parameters_20260928.json').read_text())
cfg = json.loads((root / 'scan_config.json').read_text())
image = tifffile.imread(root / 'Camera_40181166/point_000003_raw.tif')
metrics, radial, x_profile, y_profile = measure_frame(image, cfg['roi_xywh'], p)
print(image.shape, image.dtype)  # (5468, 8192), uint16
print(dict(zip(METRICS, metrics)))
```

想理解阈值影响，可复制参数文件，把 `threshold_sigma` 改为3或7，换输出目录重跑。
不要逐帧随意改变 ROI，否则积分信号难以直接比较。

## 6. 实际运行结果核对

两套程序都运行后，在 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe -m analysis.compare_results `
  output/offline_20260928/python output/offline_20260928/matlab
```

比较输入路径、参数、列名、状态，再比较全部指标、径向曲线、横纵投影及 NaN 位置。
规则为 `abs(a-b)<=1e-8+1e-10*abs(b)`；失败退出码非零。
本机 Python 与 MATLAB R2024b 已实跑这组五帧数据并通过。
具体原始数值、误差和解释保存于 `output/offline_20260928/REPORT.md` 与 `comparison.json`，
不将真实数据/结果提交仓库。

测试：`python -m pytest -q`。新增测试覆盖非对称 ROI/质心、无符号减法、无信号、
缺失/失败点、乱序关联、重复ID、坐标冲突、二维拒绝、预览边缘块和核对失败路径。
这些验证不连接硬件。

## 7. 相机资料与物理标定（2026-09-28 查询）

Basler 官方型号文档列出 boA8100-16cm 使用 onsemi XGS 45000 单色 CMOS、全局快门，
像元3.2×3.2µm，分辨率8192×5468，与本次原图一致。
[型号文档](https://docs.baslerweb.com/boa8100-16cm)

支持 Mono 8、Mono 10、Mono 12；型号能力不能反推出拍摄时选中的 PixelFormat。
本次日志只记录 `uint16` 容器，实际计数最大4095与12位数据相符，但现场格式仍未证实。
[Pixel Format 官方表](https://docs.baslerweb.com/pixel-format)

官方商城目前将高度列为5460，而产品文档为5468；程序遵循实际保存数组，绝不根据网页
裁掉8行。[商城规格](https://www.baslerweb.com/en/shop/boA8100-16cm/)

在未缩放/合并像素的前提下，传感器平面长度 `L_sensor=像素数×3.2µm`。
物方长度还需总成像倍率 M：`L_object=像素数×3.2µm/M`。物镜标称倍率不一定等于整个
光路实际倍率；未知时继续报告 px。Z 则沿用采集元数据中的 mm，不进行光学纵向倍率换算。
当前没有提供暗场、平场、倍率或像素方向标定，也没有从单次扫描估计重复性误差。
