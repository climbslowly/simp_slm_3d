# 逐光镊离线分析：Python / MATLAB

本入口扩展整体分析，增加参考平面逐峰检测、名义横向尺寸换算及离散Z观察。
不连接硬件，二维硬件测试继续暂缓；不把5层图像当成经过验证的连续三维光场。

## 实验信息与来源

完整参数见 `analysis/tweezer_parameters_20260928.json`。光学和相机信息来自操作者聊天补充，
不是原采集文件的硬件读回；程序不回写原始JSON/CSV。

| 项目 | 内容 |
|---|---|
| 光路 | SLM生成物镜→玻璃板1→焦点附近空气区域→玻璃板2→探测物镜→套筒透镜→相机；当前无原子 |
| 波长 | 1061nm |
| 两只物镜 | 同规格，EFL=7.7mm，NA=0.57，beam diameter=10mm，FOV>1.5mm |
| 设计WD | 12.15mm vacuum + 6.35mm silica + 1.5mm air；与实际介质区分记录 |
| 玻璃 | 两片各6.35mm，内表面间距约24mm，中间为空气 |
| 套筒透镜 | 150mm |
| 扫描 | 仅探测物镜Z，其余光学元件与相机固定；移动位置不改变EFL |
| 阵列 | 5000个，圆形区域中央挖直径100µm孔，设计间距5µm；未提供精确逐点目标坐标 |
| 位深 | SensorBitDepth=Bpp12；操作者认为PixelFormat为Mono12，原文件无格式硬件读回 |
| 相机 | Gain更正为18.062dB，BlackLevel=0，补偿Sensor，Gamma=1，水平/垂直Binning=1且Mode=Sum |
| 仍未知或缺少 | 自动增益/自动曝光状态；匹配设置的暗场/平场；实测横向与轴向标定（收到的暗场不匹配，见末节） |

Basler官方确认此型号Gain单位为dB，采用模拟和数字增益组合。
[Gain文档](https://docs.baslerweb.com/gain)
同增益、同曝光下可比较计数，但不能直接换算光功率；不把图像简单除以某个增益倍数。
暗场必须匹配18.062dB设置。Binning=1没有合并像素。

名义倍率 M=150/7.7=19.48051948；物方采样3.2/M=0.1642666667µm/px；
5µm设计间距对应30.43831169px。输出使用nominal标记，不能冒充实测标定。
像素x向右/y向下；Z继续使用探测物镜位置，不能除以横向倍率。

## 运行

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe -m pip install -r requirements-analysis.txt
.\.venv\Scripts\python.exe -m analysis.tweezer_scan `
  output/gui_m1/20260928_135701_746_gui_real `
  --params analysis/tweezer_parameters_20260928.json `
  --output output/tweezers_20260928/python
```

```matlab
cd('C:\slm_3d\dimension_camera'); addpath('analysis');
r = analyze_tweezers( ...
  'output/gui_m1/20260928_135701_746_gui_real', ...
  'analysis/tweezer_parameters_20260928.json', ...
  'output/tweezers_20260928/matlab');
```

MATLAB R2024b已实测，使用基础功能，无额外工具箱。两个入口各自先生成`overview/`，
包含原来的位置—照片总览。交互照片浏览继续使用`OFFLINE_ANALYSIS.md`中的入口。

```powershell
.\.venv\Scripts\python.exe -m analysis.compare_tweezers `
  output/tweezers_20260928/python output/tweezers_20260928/matlab
```

比较全部数值及对应关系，容差atol=1e-8、rtol=1e-10，NaN位置须一致，失败退出码非零。
MATLAB保存原始参数JSON文本，避免把未知null重新编码成空列表。

## 两种语言一致的算法

1. **参考帧**：point_id=3，是整体检查的清晰候选，不代表每个阱都在此处达到最佳焦点。
2. **找峰**：在固定信号ROI内，sigma=1.2px、半径4px的归一化高斯核先横后纵卷积，
   边界零填充。取21×21窗口的局部最大值且平滑计数严格大于400。排除不能容纳背景环的ROI边缘。
   高斯平滑只用于找峰，测量使用原始像素。阈值位于低幅候选与主要光点之间，另输出
   250/300/400/500/600计数下的候选数量。**不取最亮前5000个，也不补齐到5000**。
   平坦峰的多个相等候选保留，需通过最近邻距离识别重复检测。
3. **编号**：按零基y、x递增排序。MATLAB显式排序以消除find列优先顺序的差异。
   spot_id是检测编号，尚未与SLM目标坐标匹配。
4. **局部测量**：信号圆半径11px，背景环12～14px。背景b取环内中位数，
   积分sum(I-b)保留负值，净峰max(I)-b，顶值数量按I>=4095统计。
   先转float64/double，避免uint16下溢。
5. **形状**：只对信号圆内I-b>3s像素以I-b为权重，算亚像素质心和sigma_x/y，
   s来自大背景ROI总体标准差。这是有限孔径、阈值化二阶矩，不是高斯拟合束腰。
6. **空间**：参考质心的算术平均作为几何原点，乘名义µm/px。
   最近邻距离使用全部候选；Python用空间索引，MATLAB分块全配对，数值应一致。
7. **跨Z孔径**：参考峰位置加整幅阈值质心变化，再按floor(c+0.5)取整放置相同孔径。
   不从离焦散斑重新认领光镊。全局位移只是粗配准估计，形状变化也会影响它。
   离焦时邻阱会进入圆孔/背景环，因此这些计数是混合信号，不能当成独立光镊功率。
8. **离散栈**：固定相机ROI按4×4块均值降采样、扣大背景均值，保存[N,Hs,Ws]。
   所有层保留同一计数尺度，不逐帧归一化；栈未配准、未反卷积。
   XZ/YZ切线穿过参考平面最靠近阵列中心的检测点，固定在相机坐标。
   Python用逐层色块、MATLAB用逐层曲线；图形形式不同，底层数组一致。

## 输出和中文学习路径

| 输出 | 内容 |
|---|---|
| `reference_spots.csv` | [K,16]，编号、整数峰XY、平滑峰、质心XY、名义XY、背景、积分、净峰、顶值数、sigmaXY、最近邻px/名义µm |
| `aperture_probes.csv` | 每个(point_id,spot_id)一行，含孔径中心、背景、积分、净峰、顶值数、sigmaXY |
| `frame_info.csv` | point_id、目标Z、规划Z、粗全局dx/dy |
| `threshold_sensitivity.csv` | 阈值—候选数量 |
| `tweezers.mat` | spots[K,16]、probes[N,K,8]、observed_stack[N,Hs,Ws]、frame_info[N,5]、calibration[1,5]、sensitivity[T,2] |
| `spot_maps.png` / `spot_detail.png` | 全阵列逐峰强度/间距图、原分辨率局部检测叠图 |
| `sampled_xz_yz.png` | 实际离散层的截线显示 |
| `summary.json` | Python输出共同参考平面的统计 |
| `comparison.json` | 两种语言实际执行的核对结果 |

calibration五项：名义倍率、名义µm/px、设计间距对应px、参考几何中心x/y像素。
缺图/失败点的probes和stack为NaN；参考帧缺失直接报错。
建议依次阅读Python的`detect_spots → aperture_metrics → run → render`；
主要函数有中文docstring，解释输入、输出、单位和边界条件。

## 统计边界与下一步

变异系数采用总体标准差/均值（ddof=0），分别对局部积分和净峰计算。
去掉含顶值或非正信号的候选，CSV仍保留全部候选；这不是其他定义的“均匀度”，
也不是经标定的阱深/振动频率不均匀度。
当前只有固定5000点阵列、每Z一帧，不能推断各阱精确焦点、轴向宽度、时间稳定性，
或数量/优化算法与质量之间的因果关系。
后续优先补匹配增益的暗场与完整相机设置；校准横向尺度与Z对应关系；
根据光斑尺度和粗扫结果制定加密Z采样。比较不同阵列时记录功率、SLM图案、
目标坐标、间距、占据视场和算法设置，并区分固定总功率与固定单阱功率。
真实结果只保存在被忽略的`output/tweezers_20260928/REPORT.md`。

## 暗场与现有结论复查（2026-09-28 晚）

操作者补充 `BslBlackLevelCompensationMode=Sensor`、BlackLevel=0。
Sensor表示传感器内部进行黑电平补偿，不意味着背景和读出噪声为零。
SensorBitDepth与输出PixelFormat是不同参数；Bpp12并不保证文件保存12位信息。
官方说明：[Black Level](https://docs.baslerweb.com/black-level)、
[Pixel Format](https://docs.baslerweb.com/pixel-format)。

晚间暗场实际为uint8、曝光1000µs；原扫描uint16、曝光1763µs。
TIFF与MAT均已核对，不能直接扣除、乘16或按曝光比例缩放后当作匹配暗场。
单张暗场的空间标准差也不能解释为时间读出噪声。
当前先继续用参考图的局部背景环，不要求立即补拍。

Python和MATLAB复查程序分别读取各自已有的逐阱结果及参考原图。
旧结果内嵌的参数保留当时未知值；新增Sensor信息保存在复查参数里，不篡改历史结果。
复查内容包括：暗图统计、有效光点强度CV、径向分组、近邻边和不同积分孔径。
CV统一为总体标准差/均值，Pearson相关只描述共同变化，不证明因果。
方向间距按近邻中位数的0.75～1.25倍找无向边，每对只统计一次；按dx/dy主方向
分成两组，适用于本次近轴向方格阵列，不能直接推广到任意旋转或无规则阵列。
角度由相机x向右、y向下的图像坐标定义；长度µm仍为名义EFL换算。
最近邻会偏向两条格距中较短的一条，所以不能只用最近邻中位数概括两个方向。
径向分组按[左边界,右边界)，中心是全部候选质心平均；最内/最外分组少量点
可能受尺度、孔边界和中心定义影响，不把它们当成中央孔漏光或严格环形照明模型。

在仓库根目录运行（先有此前逐阱结果）：

```powershell
.\.venv\Scripts\python.exe -m analysis.review_tweezers output/tweezers_20260928/python output/gui_m1/20260928_180538_974_gui_real_current_capture --params analysis/review_parameters_20260928.json --output output/review_20260928/python
```

MATLAB：

```matlab
addpath('analysis');
review_tweezers('output/tweezers_20260928/matlab', ...
    'output/gui_m1/20260928_180538_974_gui_real_current_capture', ...
    'analysis/review_parameters_20260928.json','output/review_20260928/matlab');
```

核对：

```powershell
.\.venv\Scripts\python.exe -m analysis.compare_review output/review_20260928/python output/review_20260928/matlab
```

输出 `review.mat`、`dark_audit.json`、`summary.csv`、`radial.csv`、`axes.csv`、
`apertures.csv`。Python额外绘制`current_findings.png`。
`review.mat`中的stats两行为参考光图/暗图，列为：H、W、每像素字节数、最小、最大、
均值、总体标准差、零像素比例、曝光µs、TIFF/MAT相同标志。
edges列为两个1基候选编号、dx/dy(px)、长度(px)、方向组1/2。
所有数值与暗场判定均实际核对，atol=1e-8、rtol=1e-10。
本次结论见本机 `output/review_20260928/REPORT.md`，真实数据和报告不提交Git。
