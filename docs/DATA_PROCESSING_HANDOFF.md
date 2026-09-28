# 离线数据处理阶段交接

更新时间：2026-09-28。本文为下一次数据处理对话提供背景，具体实现以实际样例数据为准。

## 当前离线实现（2026-09-28 补充）

后续操作者确认：两只物镜同规格EFL=7.7mm/NA=0.57、150mm套筒镜、1061nm；
两片6.35mm玻璃内间距约24mm、空气模拟腔；仅扫描探测物镜Z。
目标5000点、5µm间距、100µm中央孔。Gain更正为18.062dB（不是0），
BlackLevel=0、Gamma=1、Binning两个方向均1/Sum。黑电平补偿仍未知。
新增逐阱程序、参数来源、运行方法及边界见 [TWEEZER_ANALYSIS.md](TWEEZER_ANALYSIS.md)。
原始文件不回写这些后补信息；逐阱Python/MATLAB已实际运行核对。

已接收并处理 `output/gui_m1/20260928_135701_746_gui_real` 的五点 Z 扫描。
Python 入口 `python -m analysis.offline_scan`，MATLAB 入口 `analysis/analyze_scan.m`；
共用参数、位置—照片总览、滑条浏览器、背景/强度/质心/宽度/梯度及径向剖面已完成。
两种语言已在本机实际运行，并通过 `analysis.compare_results` 数值核对。
中文学习说明、算法单位、相机官方资料和完整命令见 [OFFLINE_ANALYSIS.md](OFFLINE_ANALYSIS.md)。
原始数据、图表及本次具体发现留在被忽略的 `output/offline_20260928/`，不提交。
下文第2节的“尚未收到数据”为开始此阶段时的历史状态。
本轮仅支持离线单轴数据；二维硬件测试仍暂缓。

## 1. 项目现状

- 工作区：`C:\slm_3d\dimension_camera`；仓库：`https://github.com/climbslowly/simp_slm_3d.git`。
- 采集端使用 Basler 相机和 GAS 五轴控制器，GUI 基于 PySide6/pyqtgraph。
- 相机 XY 用于定位，物镜 XYZ 用于扫描。可生成单轴 range/list 与 XY/XZ/YZ 二维计划。
- 用户确认 Z range 实机运行正常，扫描拍摄联动和扫描后归位已验证；二维实机测试暂缓。
- 单帧采集不移动；正常扫描完成后以最多 `0.001 mm` 的子步返回起点。
  这里的 `0.001 mm` 是位移步长，不是速度。停止或出错时不自动复位。
- GUI 默认跟随最新图像，主动选 index 后固定；显示坐标已统一为绝对位置。
- 最近采集端功能提交：`d56e816`（绝对坐标显示、全 NaN 散点警告修复）。
  当时离线测试为 `73 passed`，GUI 的 13 项测试在 RuntimeWarning 视为错误时通过。
- 当前阶段只做离线处理；无需连接硬件，也不需要先完成二维测试。

## 2. 用户要求与待补信息

用户将提供一组已有数据，要求同时编写 Python 与 MATLAB 处理程序。
目前尚未收到该组数据，也未确定希望提取的最终物理量，不预设高斯拟合、PSF 重建、
反卷积等算法必然适用。

收到数据后，先确认：

1. 数据来自哪个采集入口，是完整 Z 扫描、二维扫描还是独立单帧。
2. 希望得到什么结果，例如 ROI 强度随 Z 的曲线、峰值位置、宽度或其他明确指标。
3. 若涉及物理尺寸，是否有像素尺寸、倍率和坐标标定；若涉及校正，是否有暗场/背景数据。
   缺少标定时保留像素或相机计数单位，不擅自转成物理量。
4. MATLAB 版本及可用工具箱，优先使用基础能力；实际依赖在实现时列出。

Python 的主要函数需有中文 docstring：作用、参数、返回值、数组形状、单位和边界条件。
关键步骤解释“为什么这样处理”，特别是图像切片、类型转换、坐标排序、掩码及拟合。
提供清晰入口和可直接运行的命令，并以这组数据写一个便于学习的完整示例。
MATLAB 使用相同输入约定、处理参数和算法，附注释与运行说明。

## 3. 当前 GUI 扫描目录

以下由 `data/spatial_session.py` 核对，用户样例可能来自旧版或其他入口，必须先检查实际内容。

```text
<扫描目录>/
  scan_config.json
  scan_log.csv
  scan_data.mat
  Camera_<serial>/
    point_000001_raw.tif
    point_000001_raw.mat
    ...
```

- `scan_config.json`：计划点位、轴、曝光、ROI、扫描模式、设备来源和坐标约定。
- `scan_log.csv`：UTF-8 BOM，逐点状态、坐标、指标、时间与原图相对路径。
- 每帧 TIFF：原始二维灰度像素；GUI 伪彩不修改原始数据。
- 每帧 MAT：`image` 原始像素，以及 `target_xyz_mm`、`actual_xyz_mm`、`roi_xywh` 等元数据。
- 汇总 MAT：点位、状态、指标矩阵和文件路径，`raw_images_embedded=0`，不内嵌全部原图。
  单独提供汇总 MAT 足以分析已有指标，但不足以重新计算任意 ROI 或图像特征。
- 推荐提供完整扫描目录的 zip 并保留子目录。数据过大时，先提供 JSON、CSV、汇总 MAT
  和若干有代表性的原始帧；完整逐帧处理仍需要相应原图。
- `main.py` 单帧入口与硬件诊断脚本的导出格式有所不同，不能假定与 GUI 目录完全一致。

## 4. 坐标、索引与数据含义

- XYZ 顺序为逻辑物镜坐标；物镜逻辑 Z 是轴 4，正方向为物镜前伸、逆光传播方向。
  完整物理方向映射见 `docs/PROJECT_HANDOFF.md`。
- `target_x/y/z_mm` 和 `points[].targets_mm` 是绝对目标坐标，单位 mm。
- `actual_x/y/z_mm` 的意义必须结合 `position_source` 读取。当前 REAL 使用
  `GA_GetPrfPos` 规划位置，不等同于编码器测得的机械实际位置。
- `coordinate_mode=RELATIVE_TO_SCAN_START` 时，配置中的 `horizontal_values`、
  `vertical_values`、`fixed_value_mm` 是相对输入；`origin_positions_mm` 保存起点。
  绝对坐标 = 对应轴起点 + 相对输入。`ABSOLUTE` 模式下不能再次加起点。
- 当前汇总 MAT 的 `horizontal_values_mm`、`vertical_values_mm`、`fixed_value_mm`
  直接复制配置值，仍可能是相对值。优先使用逐点 `target_xyz_mm`，并结合 JSON 解读。
  GUI 改成绝对显示不意味着旧文件或上述 MAT 字段也被重写。
- `point_id` 从 1 开始；`order_index`、二维 `row/col` 从 0 开始。
  蛇形路径不能用 point_id 直接按普通逐行顺序 reshape，需按 `row/col` 填入矩阵。
- 图像数组为 `[行(y), 列(x)]`；`roi_xywh=[x,y,width,height]` 是零基像素索引。
  Python ROI：`image[y:y+height, x:x+width]`；MATLAB ROI：
  `image(y+1:y+height, x+1:x+width)`。
- 使用成功点计算；保留缺失/失败点状态，不能把缺失强度自动当成零。
  非等距或乱序 list 数据需保留点位与图像对应关系。
- 图像为相机计数，不默认等于校准后的光强；`uint16` 容器也不证明有效位深是 16 位。
  当前采集端按 dtype 计算饱和阈值，离线分析需核对实际有效位深与编码后再解释饱和率。
- 扣背景前转换为浮点数，避免无符号整数下溢；归一化、平滑和拟合须明确记录参数。

## 5. 实现与验证安排

1. 读取样例，列出帧数、成功/缺失点、坐标、曝光、图像 shape/dtype 与数据范围。
2. 结合分析目标，先跑通读图、ROI、绝对坐标曲线和结果导出，再增加需要的算法。
3. Python/MATLAB 使用同一组输入与参数，对比逐点指标和最终结果，说明浮点容差。
4. 保留原始文件，处理结果写入独立输出目录；保存所用参数与输入来源。
5. 若本机无 MATLAB，则说明尚未实跑，提供可在实验电脑执行的验证脚本，不声称通过。

可参考：`data/spatial_session.py`、`scan/spatial_scan.py`、
`tests/test_spatial_controller.py`、`tests/test_matlab_export.py`。
采集端已有 NumPy、SciPy、tifffile；新增分析依赖时同步说明并更新对应依赖文件。

## 6. 工作区与提交约定

- 开始先读 `docs/PROJECT_HANDOFF.md`、本文件及 `git status`。
- 不覆盖或提交本地 `configuration.json` 改动、`hardware_local.json`、厂商 DLL、真实数据。
- 注意 `data/` 本身是源码包，只有 `data/captures/` 已忽略；真实样例可放在已忽略的
  `output/` 下或仓库外，不能假定任意新数据目录均被忽略。
- 用精确文件清单提交代码、说明和必要测试；离线验证后推送并报告提交号。
- 二维硬件测试继续保持暂缓，除非用户明确恢复该任务。
