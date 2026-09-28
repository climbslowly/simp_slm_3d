# 1 µm Z扫描：学习与复现

适用本次 `output/gui_m1/20260928_181545_717_gui_real`：201点、uint8、曝光1000µs，
Z=1.5478～1.7478mm，目标步距0.001mm。只读文件，不访问硬件。
必须使用 `fine_parameters_20260928.json`，不能沿用12位粗扫描400计数的找峰阈值。

## 运行

仓库根目录，Python（需要 requirements-analysis.txt）：

```powershell
.\.venv\Scripts\python.exe -m analysis.fine_scan output/gui_m1/20260928_181545_717_gui_real --params analysis/fine_parameters_20260928.json --output output/fine_20260928/python
.\.venv\Scripts\python.exe -m analysis.fine_summary output/fine_20260928/python
```

MATLAB R2024b，无额外工具箱：

```matlab
addpath('analysis');
analyze_fine_scan('output/gui_m1/20260928_181545_717_gui_real', ...
    'analysis/fine_parameters_20260928.json','output/fine_20260928/matlab');
summarize_fine_scan('output/fine_20260928/matlab');
```

核对（先完成两边的主程序和汇总）：

```powershell
.\.venv\Scripts\python.exe -m analysis.compare_fine_scan output/fine_20260928/python output/fine_20260928/matlab
```

主程序逐帧读取大TIFF和对应MAT，需要几分钟，但不一次载入所有原始图像。
汇总程序只读已经导出的fine.mat，生成summary.mat/JSON。Python和MATLAB均生成
位置—照片总览、全程曲线、焦点响应图；Python另有固定原始像素裁剪的近焦照片对比。
结果保留在output，不进入Git。原采集文件、配置及硬件状态不改变。

## 量的定义

- **像素采样**：相机像元3.2µm；名义倍率150/7.7=19.4805；物方0.164267µm/px。
  这不是光学分辨率。理想满孔径Rayleigh参考值0.61×1.061/0.57=1.13546µm。
  相干光场、像差及入瞳填充会影响实际分辨，未做点源/双点分辨率标定。
- **横向FWHM**：每个光点中心附近3行平均为横剖面，3列平均为纵剖面，扣局部环背景，
  在±11px范围找主峰半高点并线性插值。这是当前观察光斑宽度，不是高斯束腰或系统PSF。
- **Z位置**：保留GA_GetPrfPos规划位置单位mm；没有编码器实测，也未标定真实物方Z比例。
  不把横向倍率用于除Z。1µm是命令采样间隔，不是位移精度或轴向光学分辨率。
- **核心信号**：每个光点以半径3px（29个像素）的圆孔积分减局部背景。
  轴向FWHM描述此观察量随探测物镜Z的主峰宽度；不称真实光镊轴向尺寸或瑞利长度。
- **CV**：总体标准差/均值，不是最大最小值均匀度公式；始终标明使用核心积分、11px积分还是净峰值。

像元：[Basler规格](https://docs.baslerweb.com/boa8100-16cm)。
光学分辨参考及相干/像差影响：[Nikon Resolution](https://www.microscopyu.com/microscopy-basics/resolution)。

## 算法和主要函数

1. `run` / `analyze_fine_scan`：按point_id关联JSON和CSV，顺序按order_index；
   要求完整成功、Z单调、曝光固定的本次8位扫描。核对每帧TIFF/MAT像素、曝光和目标XYZ。
   统计所有201帧的固定ROI背景、净积分、梯度和亮度质心；16×16块均值只作预览。
2. 选固定ROI梯度能量最大的帧为参考。沿用逐阱程序的高斯平滑（sigma=1.2px，半径4）
   和21×21局部最大值规则，本次阈值10计数，并检查6/8/10/12/14/16/20。
   不强制选5000个。不对所有201个离焦平面重新识别和编号。
3. `registered_metrics`：仅对参考位置前后10µm内的21帧，按原参考编号估计共同平移。
   每次在圆孔内算局部阈值化质心，用“当前质心−参考质心”的中位数估计dx/dy，迭代3次。
   参与点要求净峰大于参考峰10%，至少半数光点可用。保留每帧质心残差RMS检查近焦配准。
   **不能直接用整图亮度质心变化配准精细扫描**：离焦改变亮度分布，会误移孔径，伪造窄峰。
4. `aperture_metrics`计算半径11px信号圆与12～14px背景环，背景取中位数，积分保留负数。
   `core_and_profiles`进一步测核心积分和参考帧横向剖面；不做逐帧亮度归一化。
5. `half_width`：在主峰两侧寻找最近的半高交点、线性插值；不完整则NaN，不补零。
   `axial_summary`保留采样网格上的峰位；峰必须唯一、正且两侧可测才进入主要统计。
   并列最大值标为无效，不随意当成亚µm焦点。主峰FWHM不排除更低的旁峰。
6. `fine_summary` / `summarize_fine_scan`：重复用局部净峰值曲线估计峰位/宽度作为
   指标敏感性复核；输出Pearson相关、CV、分位数和离散峰位计数。两种指标来自相同图像，
   不是独立实验，也不提供因果或统计重复性证据。

Python数组图像为[y,x]，全图位置为零基像素；MATLAB读图时+1，导出仍保持零基。
用于解释的参数在JSON；Python主要函数docstring说明数组、单位、返回值及关键步骤。

## 结果文件

`fine.mat`主要数组：

| 变量 | 本次形状 | 含义 |
|---|---|---|
| frames | 201×12 | 列名frame_columns；位置、曝光、背景、最大值、顶值数、ROI净和、梯度、质心 |
| previews | 201×200×188 | 同一ROI的块均值预览，仍为原始计数 |
| spots | 5000×17 | 列名见spots.csv；参考检测位置、孔径测量、核心信号、横向FWHM |
| probes | 21×5000×5 | 局部净峰、11px净积分、3px核心积分、实测局部质心x/y |
| registration | 21×4 | dx、dy、可用点数、质心配准残差RMS；位移/残差均px |
| axial | 5000×8 | 编号、主峰Z(mm)、核心响应FWHM(物镜µm)、最大/参考核心信号、两者比、有效标志、并列数 |
| selected_indices | 21 | 对应frames的1基行号，不是零基Python索引 |

summary.mat的widths列：分位数%、横向x/y名义µm、核心/净峰响应宽度（物镜µm）。
summary.json可直接阅读。比较器核对两语言来源、参数、编号、列名、所有测量/汇总数组和
NaN位置，atol=1e-8、rtol=1e-10；不一致则退出失败。

## 当前限制

名义倍率未独立标定；真实光镊场与探测系统响应未分离。8位图的低端量化/零值截断、
单次顺序扫描的时间变化、相机自动设置未保存、缺少平场会影响定量解释。
晚间暗图与本次的曝光/保存dtype相同，但增益等历史节点仍无回读；本版沿用局部背景，
没有声称完成严格暗场或光功率校准。近焦半高点之外的远离焦单阱孔径仍会混入邻阱光。
当前输出是观测响应及相关性基准，不能由此推断原子俘获率、阱深或数量改变的效果。
