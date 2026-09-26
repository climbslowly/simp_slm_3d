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

`hardware_local.json` 已被 `.gitignore` 排除，不会随普通 `git add` 上传。示例中的
`null` 表示尚未由现场确认，不能为了通过检查而填写估计值。

相机参数含义：

- `exposure_ms=null`：保留相机当前曝光；填正数时才写入新曝光；
- `discard_frames`：应用曝光并等待后，主动抓取但不保存的预热/旧帧数量；
- `capture_timeout_ms`：每次 `GrabOne` 的超时；
- `post_exposure_settle_ms`：修改曝光后的等待；
- `inter_frame_delay_ms`：保存帧之间的额外等待；
- `frames`：保存的诊断帧数，不包含丢弃帧。

位移台每轴的 `travel_*`、`home_position_mm` 和 `max_single_step_mm` 必须来自现场记录或
厂家资料。旧配置中的 `healthy_raw_status_values` 仅为向后兼容保留，当前安全门已经依据
ETH_GAS_N V7.3 手册逐位判断状态。`direction_sign` 和文字映射来自已经记录的人工方向观察，
但它们不能替代逐轴 pulse/mm、行程和零点验证。

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

## 4. 真实运动离线安全审计

```powershell
.\.venv\Scripts\python.exe scripts\check_motion_readiness.py `
  --config .\hardware_local.json
```

此命令不加载 DLL、不连接设备、不移动。每个 `BLOCKED` 都是进入受监督最小运动前必须
解决的项目。状态位、Stop 签名、限位解释和轴启动 mask 已有手册依据；当前仍会因自动
Home 流程未验收、逐轴标定/零点/行程和 `max_single_step_mm` 不完整而返回退出码 2。
这是预期结果，不是测试程序故障。

## 5. 单轴最小运动入口

只做预检：

```powershell
.\.venv\Scripts\python.exe scripts\verify_stage_minimal_motion.py `
  --config .\hardware_local.json `
  --axis 3 `
  --delta-mm 0.001
```

当前版本应在访问硬件前被安全门拒绝。只有完整逐轴标定、机械/软件范围、零点、现场回零
流程和 `max_single_step_mm` 全部确认后，程序才可能进入执行分支。
不要通过改脚本或伪造配置绕过 `BLOCKED`。未来获准执行时还必须显式提供
`--execute-supervised-motion` 与 `--confirm-physical-stop-ready`，并在终端再次手工输入精确
目标确认文字。

## 结果判读与上报

请保留 `output/hardware_diagnostics/` 中对应测试目录，并记录：

- 实验电脑、相机/控制器型号和测试日期；
- 使用的 Git commit；
- 命令行完整输出；
- 相机报告中的抓帧耗时和重复帧计数；
- 五轴规划/反馈 pulse、控制器软限位、解码后的状态及可选读取错误；
- readiness audit 的全部 `BLOCKED` 项。

这些本地输出已被 Git 忽略；需要分析时单独发送相关 JSON、截图或压缩包。
