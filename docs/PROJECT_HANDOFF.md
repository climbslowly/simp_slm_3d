# Dimension Camera 项目交接摘要

更新时间：2026-09-26
功能基线：Stage Bring-up V0.3 + GUI-M1；开始新对话时以实际 `main` 最新提交为准。

本文件供新的 Codex 对话快速恢复上下文。开始工作前仍应读取实际代码、`git status`、
`README.md` 和本文件引用的安全文档；本摘要不能替代当前工作区事实或真实硬件验证。

## 1. 项目位置与 Git 状态

- 本机工作区：`C:\slm_3d\dimension_camera`
- 仓库：`https://github.com/climbslowly/simp_slm_3d.git`
- 当前分支：`main`
- 当前功能基线已包含增强五轴只读诊断；具体提交以 `git log --oneline -1` 为准。
- 交接完成时本地 `main` 与 `origin/main` 一致；新对话必须用实际 Git 状态复核。
- 交接时本机 `configuration.json` 有一项未提交的本地改动：增加
  `"objective_scan_bounds_mm": null`。这是本机配置，不要擅自覆盖或提交。
- `hardware_local.json`、`output/`、`data/captures/` 均被 Git 忽略。

提交协作规则：凡需实验电脑验证的代码、脚本、测试或文档，本机安全离线测试通过后应
使用精确文件清单提交并推送，同时报告 commit hash、测试结果和实验电脑更新命令。不得
提交本机 `configuration.json` 的现场改动、`hardware_local.json`、实验输出、真实数据、
厂商 DLL 或未脱敏配置；出现非快进或冲突时禁止强推。

## 2. 已完成的软件能力

### GUI-M1（Mock，已由用户人工验收）

- PySide6 + pyqtgraph 原生桌面 GUI；启动命令：

  ```powershell
  .\.venv\Scripts\python.exe -m gui.app
  ```

- 五轴界面分为探测相机 XY 与探测物镜 XYZ。
- 空间扫描只使用物镜 XYZ；相机 XY 是扫描前固定定位轴。
- 支持单轴及 XY/XZ/YZ Mock raster、原始 TIFF、CSV、JSON、`scan_data.mat`。
- 支持主图/原图/point_id 联动、历史目录重新打开、ROI 指标、行列剖面。
- 支持暂停、继续、停止和运行中安全关闭。
- `gray` 伪彩已改为内置黑白色表，不再查找不存在的 pyqtgraph 文件。
- 软件扫描边界 `objective_scan_bounds_mm` 会在 GUI 与控制器 preflight 两层阻止超限；
  不会静默截断或改写用户计划。
- GUI 仍明确、强制为 Mock：`gui/main_window.py` 当前创建 `MockCamera` 与
  `MockXYZStage`，不会加载 GAS.dll 或连接 Basler 相机。

人工验收步骤见 `GUI_M1_ACCEPTANCE.md`。

### 真实相机基础能力

- `hardware/basler_camera.py` 已封装 Basler 枚举、按序列号连接、曝光读写和原始单帧抓取。
- `main.py --capture-camera`：只连接选定相机、拍一帧并保存 TIFF/NPY/MAT/JSON。
- `main.py --capture-current`：只读一个真实轴的规划位置/raw status，同时拍一帧；不移动。
- 历史现场结果：实验电脑已成功完成真实相机单帧采集；CXP 枚举成功不等于所有采集与
  触发模式均已验证。

### 分层硬件诊断（基线 `d7e39bf`，2026-09-26 已取得首轮现场结果）

- `scripts/diagnose_camera_sequence.py`：相机多帧、丢弃帧、耗时、SHA256 和重复帧诊断；
  不访问位移台。
- `scripts/snapshot_stage_axes.py`：轴 1～5 增强只读规划/反馈 pulse、软限位和状态；不运动。
- `scripts/check_motion_readiness.py`：完全离线列出真实运动阻塞项。
- `scripts/verify_stage_minimal_motion.py`：受完整安全门约束的单轴最小运动入口；当前应在
  连接硬件前因 Home 现场流程和逐轴标定等项目未完成而拒绝。
- 仓库只保存 `hardware_profile.example.json`；实验电脑复制为被忽略的
  `hardware_local.json` 保存现场参数。
- 完整命令与判读规则见 `docs/HARDWARE_DIAGNOSTICS.md`。

## 3. 已确认的五轴映射

以下来自操作者使用官方控制软件的现场观察，已经写入 GUI-M1 元数据，但不等于 Python
自动运动或编码器闭环验证：

| GUI 坐标正方向 | 控制器命令 | 控制器 `+` 的物理方向 | 说明 |
|---|---:|---|---|
| 探测相机 `X+`（物理 `+Y`） | 轴1 `+` | `+Y` | transverse x |
| 探测相机 `Y+`（物理 `+Z`） | 轴2 `−` | `−Z` | transverse y |
| 探测物镜 `X+`（物理 `+Y`） | 轴3 `+` | `+Y` | transverse x |
| 探测物镜 `Y+`（物理 `+Z`） | 轴5 `−` | `−Z` | transverse y |
| 探测物镜 `Z+`（物理 `+X`） | 轴4 `+` | `+X` | 逆光传播、物镜前伸 |

轴 1 已通过读数/官方 GUI 对照确认 `10000 pulse/mm`。轴 2～5 不能据此直接外推；仍需
逐轴确认 pulse/mm、控制器零点、机械行程和允许的软件范围。

## 4. 真实运动安全状态

真实运动目前仍禁止。不要通过设置 `allow_motion=True`、修改 capability 或伪造配置绕过。

已确认：

- `GA_OpenByIP(PCIP, CardIP, 0, 0)` 连接顺序；
- `GA_GetPrfPos` 可读规划位置 raw pulse；
- `GA_GetSts` 状态位定义；轴 3 首轮 `0x4000` 是 `HOME_SWITCH`，不是报警或回零成功；
- `GA_GetAxisEncPos` 反馈计数读取和 `GA_GetSoftLimit` 软限位读取签名；
- `GA_Stop(mask, option)` 签名和缓停/急停 bit 语义；
- `GA_Update` 的轴 n mask 为 `1 << (n-1)`；
- 厂家轴 1 示例出现 AxisOn、PrfTrap、SetTrap、SetPos、SetVel、`GA_Update(1)`；
- 实验电脑完成过控制器只读连接；五轴身份/方向完成过官方 GUI 人工观察。

仍阻塞：

- 反馈计数是否来自独立物理编码器，以及与规划位置的实机动态对照；
- Stop 的实机效果和经过验证的独立物理停止方案；
- 当前机构的 Home 模式、方向、参数与流程；
- 正负限位接线/极性的现场核对；
- 轴 2～5 pulse/mm，以及全部轴的零点、行程、软限位和最小安全步长。

证据矩阵见 `docs/DIMENSION_STAGE_EVIDENCE.md`；第一次只读接入 SOP 见
`docs/FIRST_HARDWARE_BRINGUP.md`。

## 5. 配置与采集时序现状

GUI-M1 已有：

- `exposure_ms`：Mock 曝光；
- `settling_ms`：模拟到位后的稳定等待；
- `objective_scan_bounds_mm`：物镜 GUI XYZ 软件扫描边界，默认 `null`。

真实相机诊断配置（`hardware_local.json`）另有：

- `capture_timeout_ms`；
- `post_exposure_settle_ms`；
- `discard_frames`；
- `inter_frame_delay_ms`；
- `frames`。

这些真实相机参数目前仅用于独立诊断脚本，尚未接入当前 GUI 扫描控制器。Basler
`grab_image()` 使用 `GrabOne()` 并在释放 pypylon result 前复制数组；真实系统仍需通过
多帧诊断判断曝光修改、旧帧、触发模式和取帧延迟。

## 6. 自动验证与不可声称的验证

在增强只读诊断版本上，本机结果为：

```text
54 passed
compileall passed
git diff --check passed（只有 Windows LF/CRLF 提示）
```

这些测试使用 Mock/Fake 设备。它们不证明：

- 真实五轴可以安全运动；
- Stop、限位和状态 bit 的真实控制器动态行为已经验收；
- CXP/USB 相机所有触发和缓存模式正确；
- GUI 已经接入真实相机或真实位移台。

## 7. 实验电脑建议执行顺序

1. 更新并确认提交：

   ```powershell
   git pull --ff-only origin main
   git log --oneline -1
   ```

   预期为远端 `main` 最新提交。如果实验电脑有本地 `configuration.json` 改动，先只
   stash 该文件，pull 后再 `stash pop`；不要丢弃现场配置。

2. 安装/更新依赖并运行离线测试：

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
   .\.venv\Scripts\python.exe -m pytest -q
   ```

3. 创建本地硬件配置：

   ```powershell
   Copy-Item .\hardware_profile.example.json .\hardware_local.json
   notepad .\hardware_local.json
   ```

4. 先执行真实相机多帧诊断，不访问位移台。
5. 再执行五轴只读快照，不运动。
6. 执行离线 motion readiness audit；当前出现 `BLOCKED` 和退出码 2 是预期结果。
7. 不执行真实运动；将 JSON 报告、终端输出和必要截图提供给下一轮分析。

具体命令不要从本摘要猜测，直接复制 `docs/HARDWARE_DIAGNOSTICS.md` 中的版本。

## 8. 推荐的下一开发阶段

优先顺序：

1. 运行增强五轴只读快照，取得规划/反馈 pulse、软限位和解码后的状态。
2. 根据快照补齐逐轴 pulse/mm、零点、行程、限位接线和 Stop 实机证据。
3. GUI-M2：在保留 Mock 默认模式和真实运动禁用的前提下，把已有 `BaslerCamera` 接入
   当前 GUI，完成设备选择、曝光写入/读回、预览和单点保存。
4. 独立脚本完成受监督的单轴最小运动验收后，再把验证过的五轴 Adapter 接入 GUI。
5. 最后按“单点移动拍摄 → 2～3 点小范围扫描 → 小型二维扫描”逐级验收。

## 9. 给新对话的建议开场

可以把下面文字作为新对话第一条消息：

> 请继续当前 `C:\slm_3d\dimension_camera` 项目。先读取
> `docs/PROJECT_HANDOFF.md`、`README.md`、`docs/HARDWARE_DIAGNOSTICS.md` 和实际 Git
> 状态；不要覆盖本机 `configuration.json` 或提交 `hardware_local.json`/`output/`。
> 当前功能基线为 Stage Bring-up V0.3 + GUI-M1，请以实际 `main` 最新提交为准；GUI-M1 Mock 已验收，真实
> 运动仍禁止。请以我随后提供的实验电脑
> 诊断结果为准继续工作，不把 Mock/Fake 测试当成实机验证。凡需实验电脑验证的改动，
> 本机离线测试通过后提交并推送，并报告 commit hash 和更新命令。
