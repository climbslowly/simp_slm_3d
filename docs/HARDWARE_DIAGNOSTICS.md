# 真实硬件分层诊断

这些程序属于当前工程，不是另一套 GUI。它们先把真实相机和位移台分别验证，避免在
GUI 线程、扫描状态机和两个硬件同时参与时难以定位故障。

## 1. 创建实验电脑本地配置

在 PowerShell 中执行：

```powershell
cd C:\slm_3d\dimension_camera
Copy-Item .\hardware_profile.example.json .\hardware_local.json
notepad .\hardware_local.json
```

`hardware_local.json` 已被 `.gitignore` 排除，不会随普通 `git add` 上传。轴 1..5 的标定空值
会采用随厂家控制软件提供的 `SysParam.xml` 数值；连接路径、IP 和相机序号仍必须在实验电脑填写。

相机参数含义：

- `exposure_ms=null`：保留相机当前曝光；填正数时才写入新曝光；
- `discard_frames`：应用曝光并等待后，主动抓取但不保存的预热/旧帧数量；
- `capture_timeout_ms`：每次 `GrabOne` 的超时；
- `post_exposure_settle_ms`：修改曝光后的等待；
- `inter_frame_delay_ms`：保存帧之间的额外等待；
- `frames`：保存的诊断帧数，不包含丢弃帧。

位移台轴 1..5 默认采用厂家控制软件的 `10000 pulse/mm`、`±26 mm` 和控制器零点坐标，
`max_single_step_mm=0.1` 是本项目首次验收限制。旧配置中的 `healthy_raw_status_values` 仅为
向后兼容保留，当前安全门依据 ETH_GAS_N V7.3 手册逐位判断状态。

## 2. 相机多帧诊断（不访问位移台）

先沿用已有入口列出设备：

```powershell
.\.venv\Scripts\python.exe main.py --list-cameras
```

把序号写入 `camera.camera_index`，再执行：

```powershell
.\.venv\Scripts\python.exe scripts\diagnose_camera_sequence.py `
  --config .\hardware_local.json `
  --confirm-camera-only
```

结果保存在 `output/hardware_diagnostics/<时间>_camera_*_diagnostic/`。每个保留帧为原始
TIFF，`camera_diagnostic.json` 记录曝光、抓帧耗时、shape、dtype、强度统计、SHA256
以及相邻帧是否完全相同。相同帧不必然表示缓存错误（静态场景也可能重复），需要结合
场景变化、相机触发模式和时间戳判断。

## 3. 五轴只读快照（不运动）

填写已经确认的 `dll_path`、`pc_ip` 和 `card_ip` 后执行：

```powershell
.\.venv\Scripts\python.exe scripts\snapshot_stage_axes.py `
  --config .\hardware_local.json `
  --axes 1,2,3,4,5 `
  --confirm-read-only
```

程序对每个轴只执行 DLL load、connect，并读取：

- `GA_GetPrfPos`：规划位置，单位 pulse；
- `GA_GetAxisEncPos`：编码器/反馈计数位置，单位 pulse；
- `GA_GetSts`：轴状态，并按 ETH_GAS_N V7.3 手册 5.6 节逐位解释；
- `GA_GetSoftLimit`：控制器当前配置的正负软限位，单位 pulse。

报告还给出规划位置与反馈计数位置之差。新增读取失败时会记录
`optional_read_errors`，不会丢失已经成功取得的状态。脚本不调用 AxisOn、Home、Move、
Stop、Zero、清报警、设置限位或任何其他状态修改 API；报告中的
`motion_commanded` 和 `state_changing_api_called` 都应为 `false`。

状态位中 `ESTOP`、`SERVO_ALARM`、正负软/硬限位、`FOLLOW_ERROR` 和被置位的手册保留位
属于安全阻塞项。
`HOME_SWITCH` 只表示零位输入当前有效，不等于 `HOME_SUCCESS`，也不应单独解释为故障。
首次增强快照重点检查：五轴读取是否全部成功、是否出现安全阻塞位、反馈与规划位置是否一致、
以及控制器软限位是否与现场配置吻合。

2026-09-27 的现场快照中，五轴反馈计数均为 `0/1`，没有跟随数万 pulse 的规划位置；这说明
当前反馈模式尚不能作为实际位置闭环证据。五轴软限位均为
`+2147483647/-2147483648`，等于完整 32 位有符号整数范围，不构成有限安全窗口。不要把这两组
读数写入标定或用于解除运动安全门。

## 4. 真实运动离线安全审计

```powershell
.\.venv\Scripts\python.exe scripts\check_motion_readiness.py `
  --config .\hardware_local.json
```

此命令不加载 DLL、不连接设备、不移动。轴 1..5 的空值会依据厂家控制软件
`SysParam.xml` 补为 `10000 pulse/mm`、`±26 mm`、控制器零点 `0 mm` 和本项目首次验收单步
上限 `0.1 mm`。Home 不再是点位运动前置条件。如果连接路径和 IP 已配置，审计应显示
`READY_FOR_SUPERVISED_MINIMAL_MOTION`；仍有 `BLOCKED` 时不要进入 REAL GUI。

完整 `pytest` 中有一项可选的厂家 DLL 加载检查。开发机仓库上级若没有
`positioner/GAS.dll`，该检查会显示为 `skipped`；Fake DLL 测试仍会覆盖签名绑定和调用顺序。
真实 DLL 的路径继续由 `hardware_local.json` 单独配置。

## 5. 单轴最小运动入口

只做预检：

```powershell
.\.venv\Scripts\python.exe scripts\verify_stage_minimal_motion.py `
  --config .\hardware_local.json `
  --axis 3 `
  --delta-mm 0.001
```

静态预检通过后仍不会连接或移动。若使用这个独立入口执行运动，还必须显式提供
`--execute-supervised-motion` 与 `--confirm-physical-stop-ready`，并在终端再次手工输入精确
目标确认文字。

## 6. 现有 GUI 的 REAL 模式

```powershell
.\.venv\Scripts\python.exe -m gui.app `
  --real `
  --hardware-config .\hardware_local.json `
  --confirm-real-motion
```

启动后先核对五轴当前位置，再点击“当前位置采集一张”；该操作不产生位移。第一次运动把
物镜和相机手动步长都改成 `0.001 mm`，每次只点一个方向一次。REAL 模式不使用编码器反馈，
不自动 Home；它在连接时写入 `±260000 pulse` 软限位、启用正负硬限位，并在每条命令前检查
`±26 mm` 软件范围、`0.1 mm` 单步上限和状态位。

扫描计划中的起/止/步长和列表均为相对于点击开始时当前位置的偏移。例如 `-0.1, 0.1,
0.05` 表示围绕当前点扫描。二维扫描使用蛇形路径，正常完成后按 `0.001 mm` 小步返回开始
位置。每个点保存一对 TIFF/逐帧 MAT，目录根部另有汇总 `scan_data.mat`。界面底部错误可以
选中复制，也可以点击“复制错误”。

## 结果判读与上报

请保留 `output/hardware_diagnostics/` 中对应测试目录，并记录：

- 实验电脑、相机/控制器型号和测试日期；
- 使用的 Git commit；
- 命令行完整输出；
- 相机报告中的抓帧耗时和重复帧计数；
- 五轴规划/反馈 pulse、控制器软限位、解码后的状态及可选读取错误；
- readiness audit 的全部 `BLOCKED` 项。

这些本地输出已被 Git 忽略；需要分析时单独发送相关 JSON、截图或压缩包。
