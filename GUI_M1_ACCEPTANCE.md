# GUI-M1 验收说明

GUI-M1 是现有 Dimension Camera 工程中的离线 Mock 桌面界面。它不会加载 GAS.dll、不会枚举或连接 Basler 相机，也不开放真实运动。界面分为探测相机 XY 和探测物镜 XYZ，共五个 `mock_simulated` 逻辑轴；停止按钮不是物理急停。

当前界面采用现场人工观察确认的映射：相机 `X+` 使用轴1 `+`（物理 `+Y`），相机
`Y+` 使用轴2 `−`（物理 `+Z`）；物镜 `X+` 使用轴3 `+`（物理 `+Y`），物镜 `Y+`
使用轴5 `−`（物理 `+Z`），物镜 `Z+` 使用轴4 `+`（物理 `+X`、逆光传播、物镜向前）。
映射身份和方向证据会随扫描写入配置、CSV 和 MAT，但这仍不是 Python 实机运动验证。

## 安装与启动

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe -m gui.app
```

打开已保存扫描：

```powershell
.\.venv\Scripts\python.exe -m gui.app --open "C:\path\to\scan_directory"
```

## 人工验收步骤

1. 启动后确认顶部橙色栏明确显示 `MOCK / 模拟数据`，真实位移入口不可用。
2. 在“探测相机 XY”中分别执行单步和绝对定位，确认只更新相机位置，物镜位置不变；再移动物镜，确认相机位置不变。注意这只是 Mock 逻辑验证。
3. 保持默认物镜 XY 参数：X `-0.4 → 0.4, step 0.2`，Y `-0.2 → 0.2, step 0.2`，确认估算为 15 点和 15 幅图。
4. 点击“开始 Mock 扫描”。扫描期间确认参数、物镜 XYZ、相机 XY 和打开目录按钮都锁定；暂停后应在当前点安全保存完毕进入“已暂停”，继续后恢复，停止后不再开始新点。
5. 扫描完成后确认输出目录含 `scan_config.json`、`scan_log.csv`、`scan_data.mat` 和 `Camera_MOCK-GUI-001` 下的 15 个 TIFF。CSV 应含固定的 `camera_x_mm` / `camera_y_mm`，MAT 应含 `camera_xy_mm`；原始像素不在 MAT 重复嵌入。
6. 点击热图点，再拖动 point_id 滑块或数字框；三者应选中同一个 point_id、目标坐标和文件名。浏览选点不得改变左侧模拟位置。
7. 将查看模式改成“固定选择”，再运行扫描；新帧不能覆盖主动选择的历史图。改回“跟随最新”后显示最新成功点。
8. 改变图像伪彩/显示范围，确认日志中的指标及 TIFF 文件不变。ROI 是相机像素坐标，不是平台 mm 坐标。
9. 关闭程序，再用“打开已有扫描目录”或 `--open` 重开上一步目录；确认热图、剖面、原图和点信息可浏览。
10. 分别试用物镜 XY/XZ/YZ、单轴 range 和单轴 list；反向扫描需使用负步长，不可整除终点时程序不改变步长强行包含终点。
11. 扫描运行中关闭窗口，确认程序先停止工作线程再退出；已完成点仍可重新打开。

## 已知限制与下一阶段阻塞项

- 仅一个 Mock 扫描相机、每点一帧、每轮一次、普通 raster。
- 未实现多帧平均、多相机监控、serpentine、自动对焦、三维体扫描、自动断点续扫和 EXE 打包。
- Mock 的 `uint16` 饱和阈值明确为 65535；未来真实相机必须从像素格式/有效位深读取，不能照搬 dtype 上限。
- 真相机的自动曝光/增益、缓存旧帧和“到位后新曝光”尚未验证。
- 真实运动仍由原有 safety gate 禁止。五轴身份和方向虽已现场观察确认，开放前仍必须确认状态位、可靠停止、编码器/规划位置语义、逐轴标定和安全范围。
- 五轴身份和方向已由操作者通过官方软件观察确认；轴2～5的 pulse/mm、零点和安全行程仍待逐轴记录。
- 本次自动化只验证 Mock 软件闭环，不构成实机相机、控制器、限位、急停或机械安全验证。

## MATLAB 读取

```matlab
data = load('scan_data.mat');
imagesc(data.horizontal_values_mm, data.vertical_values_mm, data.metric_grid);
axis xy;
axis image;
colorbar;

% 原始图仍从 TIFF 按需读取，避免 MAT 再复制一份完整像素栈。
relativePath = string(data.image_relative_path{1});
image = imread(fullfile(pwd, relativePath));
```

`image_file_exists` 标记导出 MAT 时对应 TIFF 是否存在；`missing_success_image_count`
应为 0。若只复制 JSON/CSV 而没有复制相机子目录，指标仍可导出，但无法由该目录读取原图。

旧的 GUI-M1 目录可离线补导出：

```powershell
.\.venv\Scripts\python.exe scripts\export_scan_mat.py "C:\path\to\scan_directory"
```
