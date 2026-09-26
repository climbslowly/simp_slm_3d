# Dimension Camera

维度/GAS 位移台与 Basler pylon 相机的自动扫描项目。当前版本是 **Stage Bring-up V0.3 + GUI-M1**：
硬件 Adapter、Mock 设备、ScanPlan、扫描状态机、TIFF/JSON/CSV/MAT 保存和自动测试已经建立；
本轮增加了单位隔离、能力/标定模型、真实运动 safety gate、dry-run 和只读接入 SOP。
现已增加 **GUI-M1**：PySide6 + pyqtgraph 的离线 Mock 空间扫描、原始 TIFF 保存、联动浏览、
暂停/继续/停止和历史目录回读。真实硬件行为仍保持原安全边界，GUI-M1 不加载或连接真实设备。

## 先说安全边界

- 默认入口只运行 Mock，不会连接或移动真实设备。
- `DimensionStage.connect()` 只调用 `GA_OpenByIP`，不会 Reset、清零、使能或移动。
- 真实 Adapter 的上层坐标始终是 mm；原始 pulse 只能通过明确命名的只读方法获取。
- `StageCapabilities` 的未知能力为 `None`，`AxisCalibration` 的未知标定也为 `None`。
- 真实运动必须显式设置 `allow_motion=True`，且完整通过能力、标定、范围和健康状态安全门。
- ETH_GAS_N V7.3 手册已确认轴启动 mask、状态 bit、Stop、反馈位置和软限位读取方式。
- Stop 已在 Adapter 中实现但尚未实机验收；增强只读诊断不会调用 Stop 或任何状态修改 API。
- Home API 虽有手册定义，但当前机构的回零模式、方向和参数尚未验收，Python Home 继续禁用。
- 当前默认配置即使人为设置 `allow_motion=True`，仍会因回零流程、pulse/mm、零点和行程等未知而拒绝运动。

完整证据状态见 [Dimension Stage Evidence Matrix](docs/DIMENSION_STAGE_EVIDENCE.md)，
第一次接线步骤见 [First Hardware Bring-up SOP](docs/FIRST_HARDWARE_BRINGUP.md)。

## 当前环境检查（2026-09-16）

工作区根目录原先只有 `positioner/`。其中有四组 GAS.dll 厂家示例及四个旧 `venv`：

- 系统命令 `python` 指向 Microsoft Store 占位符，不能运行；
- 旧 `venv` 固定引用 `D:\Program Files\Python38\python.exe`，该解释器已经不存在；
- Codex bundled Python 3.12.14 可运行；
- bundled Python 中已有 `numpy`，起初没有 `pypylon`、`tifffile`、`PySide6`、`pyqtgraph`、`pytest`；
- `GAS.dll` 能被当前 64-bit Python 加载；没有连接真实控制器，也没有执行运动。

本轮随后已在 `dimension_camera/.venv` 独立安装 `numpy`、`tifffile`、`pypylon` 和 `pytest`。
用 pypylon 做了只读设备枚举，当前返回空列表（0 台在线相机）；没有打开相机。

建议为本项目建立独立环境，不要复用厂家示例中已经失效的 venv。

```powershell
cd C:\slm_3d\dimension_camera
C:\path\to\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

GUI 开发阶段再安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
```

需要运行完整自动测试时安装开发依赖；该文件同时包含 GUI 依赖和 `pytest`：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 已确认的位移台控制方式

现有代码不是 Python package，而是 Python `ctypes.CDLL` 直接加载 `GAS.dll`。厂家示例与
随附官方控制软件的连接参数为：

```text
实验电脑网卡 PCIP：192.168.0.200
运动控制卡 CardIP：192.168.0.1
轴：       1
位置单位： pulse（脉冲）
```

证据来自 `官方控制程序/system/ComParam.xml` 的 `PCIP` / `CardIP`，且厂家 Python 示例按
`GA_OpenByIP(PCIP, CardIP, 0, 0)` 的顺序调用。程序仍不设置隐式网络默认值，运行时必须由
操作者现场确认并显式输入。

V0.3 明确分离三层坐标：

```text
ScanPlan / StageBase: physical coordinate, mm
AxisCalibration:      mm <-> pulse/count conversion
GAS.dll:              controller coordinate, pulse/count
```

不知道 pulse/mm 时，Phase A 仍可调用 `get_position_pulse()` 读取原值，但 `get_position()`
不会把 pulse 冒充成 mm，而会因标定不完整明确报错。

### 从现有示例确认的 API

| 能力 | 厂家 API | 证据与当前处理 |
|---|---|---|
| 连接 | `GA_OpenByIP(pc_ip, card_ip, 0, 0)` | 官方配置和示例共同确认；返回 0 成功 |
| 断开 | `GA_Close()` | 示例实际调用 |
| 轴选择 | 每个轴 API 的第一个参数，如 `GA_GetPrfPos(1, ...)` | 示例确认轴号 1；文档注释写轴范围 1..8 |
| 读规划位置 | `GA_GetPrfPos(axis, double*, 1, 0)` | 示例说明单位 pulse |
| 绝对目标 | `GA_SetPos(axis, c_int64(target))` | 示例确认，随后需 `GA_Update(1)` 启动轴 1 |
| 点位速度 | `GA_SetVel(axis, c_double(value))` | 示例说明为 pulse/ms |
| 点位模式 | `GA_PrfTrap(axis)` | 示例实际调用 |
| 点位参数 | `GA_SetTrapPrmSingle(axis, acc, dec, smooth, 0)` | 示例实际调用 |
| 使能 | `GA_AxisOn(axis)` | 示例实际调用 |
| 状态 | `GA_GetSts(axis, long*, 1, 0)` | V7.3 手册定义状态位和到位判据；程序保留 raw 值并逐位解释 |
| 编码器/反馈计数位置 | `GA_GetAxisEncPos(axis, double*, 1, 0)` | V7.3 手册定义；增强只读诊断记录原始 pulse，不改变编码器模式 |
| 读取软限位 | `GA_GetSoftLimit(axis, long*, long*)` | V7.3 手册定义；只读当前控制器配置，不设置限位 |
| 停止 | `GA_Stop(mask, option)` | V7.3 手册定义；option 对应位 0=平滑停、1=急停，尚未实机触发验收 |
| 复位 | `GA_Reset()` | 示例存在，但连接时调用可能改变设备状态，本项目不自动调用 |
| 关闭编码器 | `GA_EncOff(axis)` | 示例存在，本项目不自动改变反馈模式 |
| 位置清零 | `GA_ZeroPos(axis, 1)` | 示例存在，本项目不自动清零 |

`GA_GetSts` 的 bit 已按 V7.3 手册解释。急停、报警、跟随误差、正负软/硬限位及被置位的
保留状态位均会阻止运动；`HOME_SWITCH (0x4000)` 只是零位输入，不等于报警或回零成功。手册给出的点位完成
判据为 `RUNNING=0` 且规划位置距目标小于 1 pulse。`GA_GetPrfPos` 仍表示规划位置，
`GA_GetAxisEncPos` 表示编码器/反馈计数位置；在未确认现场反馈模式前不声称它一定来自独立
物理编码器闭环。

### StageCapabilities 与 AxisCalibration

`hardware/stage_safety.py` 集中保存安全事实：

- `StageCapabilities` 使用 `True / False / None` 表示 confirmed / unsupported / unknown；
- `AxisCalibration` 保存 axis、pulse/mm、行程、方向、零点和可选软限位；
- mm/pulse 转换只能在 `pulses_per_mm`、方向和零点全部已知时执行；
- 真实运动按危险状态位逐项拦截，不使用完整 raw status 白名单；
- Stop、状态解释、反馈位置、软限位读取和轴启动 mask 已有手册依据；
- 自动 Home 仍因现场流程未验收而抛出 unsupported。

### 尚未确认，禁止在真实设备上猜测

- 设备枚举：示例只有固定 IP 连接，没有枚举 API；
- 目标物理轴与官方 GUI 逻辑轴号的对应关系；
- `PulsPerRev=10000`、`Lead=1`、`Rate=1` 的准确换算公式，以及 pulse 正方向；
- 目标轴应采用哪一组 `PosLimt` / `NegLimt` 行程；
- 当前反馈计数模式是否使用独立物理编码器；
- 当前机构应采用的 Home 模式、方向、速度和最大搜索距离；
- Stop 的现场实际减速效果及独立物理急停方案；
- 每轴限位接线、触发极性和软限位配置与机械行程是否一致；
- 轴 2..5 的 pulse/mm、零点和安全单步。

拿到控制器型号和官方 API 手册后，应优先补齐这些项目。

## Basler 相机控制方式

`hardware/basler_camera.py` 使用官方 `pypylon`，并采用延迟导入：没有 Basler 环境时，
Mock 测试仍能运行。相机身份始终使用序列号，不使用 Camera 0/1 枚举下标。

已封装：枚举、按序列号连接/断开、型号/序列号、曝光读写、单帧抓取、开始/停止连续抓取。
`grab_image()` 在释放 pypylon grab result 前复制 numpy 数组，以免底层缓冲区复用后图像被改写。

尚未在本机验证真实采图：项目 `.venv` 已安装 pypylon，但枚举结果为 0 台在线相机。
像素格式、Gain、触发模式暂未主动改变，
所以保存的是相机当前配置产生的原始数组。

## 目录结构与数据流

```text
main.py (当前为 Mock CLI；未来 GUI)
  -> ScanController
      -> StageBase / DimensionStage / MockStage
      -> CameraBase / BaslerCamera / MockCamera
      -> ScanDataManager
          -> uint8/uint16 原始 TIFF
          -> scan_config.json
          -> scan_log.csv
```

GUI 通过与 Qt 无关的扫描控制器访问设备：既有单轴流程使用 `ScanController`，GUI-M1
空间 Mock 流程使用 `SpatialScanController`。同步的 `controller.run(plan)` 放在 PySide6
`QThread` worker 中，GUI 主线程只处理输入和显示。

## 立即运行 Mock 完整闭环

安装核心依赖后：

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe main.py --mock-demo --output output
```

它会运行三个位置：移动、轮询到位、稳定等待、生成 uint16 Gaussian 光斑、保存 TIFF、
写 JSON 和 CSV。输出类似：

```text
output/20260916_143210_mock_demo/
  scan_config.json
  scan_log.csv
  Camera_MOCK-001/
    pos_000001_target_0.000000_actual_0.000000_repeat_001_frame_001.tif
    ...
```

## 运行 GUI-M1（仅 Mock）

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe -m gui.app
```

重新打开已有 GUI-M1 扫描目录：

```powershell
.\.venv\Scripts\python.exe -m gui.app --open "output\gui_m1\<scan_directory>"
```

GUI-M1 现按五轴机构拆成两组光学逻辑坐标：

| GUI 坐标正方向 | 控制器命令 | 控制器 `+` 的物理方向 | 光学备注 |
|---|---:|---|---|
| 探测相机 `X+`（物理 `+Y`） | 轴1 `+` | `+Y` | transverse x |
| 探测相机 `Y+`（物理 `+Z`） | 轴2 `−` | `−Z` | transverse y |
| 探测物镜 `X+`（物理 `+Y`） | 轴3 `+` | `+Y` | transverse x |
| 探测物镜 `Y+`（物理 `+Z`） | 轴5 `−` | `−Z` | transverse y |
| 探测物镜 `Z+`（物理 `+X`） | 轴4 `+` | `+X` | 逆光传播、物镜向前 |

当前扫描计划只使用物镜逻辑 XYZ；相机 XY 是扫描前的固定定位轴，扫描运行时被锁定。
轴身份和正负方向来自操作者使用官方控制软件的现场观察，按
`operator_observed_with_official_controller_software` 写入 `scan_config.json`、CSV 和 MAT。
这不是 Python 自动运动或编码器闭环验证；轴2～5的 pulse/mm、各轴零点/行程、限位接线和
可靠停止效果仍未现场确认，真实运动入口继续关闭。Mock 图像用“物镜横向位置 − 相机位置”
模拟相对位移，不代表真实光学响应。

### 可配置扫描软件边界

`configuration.json` 可选配置物镜 GUI 坐标的逐轴扫描边界：

```json
"objective_scan_bounds_mm": {
  "X": [-1.0, 1.0],
  "Y": [-1.0, 1.0],
  "Z": [-0.5, 0.5]
}
```

数值必须由实验电脑现场确认后填写；仓库默认值为 `null`，避免把任意 Mock 数字冒充真实
安全范围。配置后，扫描计划任一目标点超限都会在“扫描前估算”中显示红色错误并禁用开始按钮，
控制器 preflight 也会再次拒绝。程序**不会自动截断或替换目标值**，因为静默改变实验轨迹会使
保存的计划与操作者原始意图不一致。该检查只是软件预检，不能替代控制器限位、物理限位或急停。

GUI-M1 的二维 raster 约定为 `heatmap[row, col] = [纵轴, 横轴]`，图像变换把像素中心对齐到
计划坐标。主图的零值、未采集 `NaN` 和错误日志互不混淆；选点只浏览数据，不提交移动。
每次扫描结束生成 `scan_data.mat`，其中包含坐标、状态、ROI 指标矩阵和 TIFF 相对路径；
原始像素仍只保存在 TIFF，避免重复占用空间。旧目录可用 `scripts/export_scan_mat.py` 补导出。
完整人工验收步骤见 [GUI_M1_ACCEPTANCE.md](GUI_M1_ACCEPTANCE.md)。

## 只读验证真实位移台

只有人工确认电脑网卡 IP、控制器 IP、轴号后，才运行唯一的 Phase A 入口：

```powershell
cd C:\slm_3d\dimension_camera
$dllPath = Read-Host "Enter the VERIFIED GAS.dll path"
$pcIp = Read-Host "Enter the VERIFIED PC adapter IP (PCIP)"
$cardIp = Read-Host "Enter the VERIFIED motion card IP (CardIP)"
$axisId = [int](Read-Host "Enter the VERIFIED axis number")
.\.venv\Scripts\python.exe scripts\verify_stage_readonly.py `
  --dll $dllPath `
  --pc-ip $pcIp `
  --card-ip $cardIp `
  --axis $axisId `
  --confirm-read-only
```

这个单轴兼容入口只执行 `DLL load -> connect -> GA_GetPrfPos -> GA_GetSts raw -> disconnect`。
推荐的五轴增强只读入口是下文硬件诊断章节中的 `snapshot_stage_axes.py`，它额外读取反馈
位置、软限位并解释状态位。两个入口都不包含 Reset、Zero、Enable、Home、Move、Stop 或
限位触发测试。操作前完整阅读
[FIRST_HARDWARE_BRINGUP.md](docs/FIRST_HARDWARE_BRINGUP.md)。

## 当前位移台位置 + 单帧相机采集（不扫描、不移动）

先列出 pylon 当前通过所有已安装 transport layer 找到的相机：

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe main.py --list-cameras
```

列表同时显示序号、型号、序列号、transport layer 和 interface ID。统一枚举不限定 USB；
安装了匹配的采集卡驱动和 GenTL producer 后，CXP 相机也会出现在列表中。若 CXP 相机没有
出现，需要先检查相机供电、CXP 线缆、采集卡驱动以及 pylon/GenTL transport layer。

记下列表开头的相机序号（从 0 开始）。在已确认控制器 IP、电脑网卡 IP、轴号和 GAS.dll
路径后，按序号选择相机，执行一次当前位置记录和单帧采集：

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe main.py --capture-current `
  --stage-dll "C:\slm_3d\positioner\GAS.dll" `
  --pc-ip "<confirmed-pc-adapter-ip>" `
  --card-ip "<confirmed-motion-card-ip>" `
  --axis <confirmed-axis-id> `
  --camera-index <camera-list-index> `
  --confirm-current-capture
```

如果此时只想验证相机、暂不连接位移台，则使用相机单帧模式。例如列表中的 CXP 相机是 `[3]`：

```powershell
.\.venv\Scripts\python.exe main.py --capture-camera `
  --camera-index 3 `
  --confirm-camera-capture
```

该模式只连接选中的相机、抓取一帧后断开，不访问位移台。

该模式的位移台调用严格为 `GA_OpenByIP -> GA_GetPrfPos -> GA_GetSts -> GA_Close`；没有
Reset、清零、使能、Home、Stop 或 Move。相机保持现有配置，只执行一帧抓取，不修改曝光、
像素格式或触发设置。

结果默认保存在 `data/captures/<timestamp>_current_capture/`，该输出子目录已在 `.gitignore`
中排除，不会上传到 GitHub。项目原有的 `data/` Python 源码包仍正常同步：

- `Camera_<serial>_current_raw_pulse_<value>.tiff`：原始单帧 TIFF；
- `Camera_<serial>_current_raw_pulse_<value>.npy`：NumPy 原生数组，可用
  `numpy.load(path, allow_pickle=False)` 快速读取；
- `Camera_<serial>_*.mat`：MATLAB 数据文件。MATLAB 中可使用
  `data = load('文件名.mat'); image = data.image;` 直接获得原始图像矩阵；
- `capture_metadata.json`：原始规划位置、raw status、相机型号/序列号、当前曝光、图像尺寸和数据类型。

注意：`GA_GetPrfPos` 已确认的单位是 `pulse/count`，且语义是**规划位置**，不是已验证的编码器
实际位置。没有完成 pulse/mm 标定前，程序不会显示或写入虚假的 mm 位置。这个旧版单点
采集入口的 metadata 仍只保存 raw status；需要状态解码时使用增强五轴只读快照。

## 完全离线的 scan dry-run

真实相机多帧时序/旧帧诊断、五轴只读快照、运动 readiness audit 和受安全门约束的
单轴最小运动入口，见 [真实硬件分层诊断](docs/HARDWARE_DIAGNOSTICS.md)。实验电脑的
现场值写入被 Git 忽略的 `hardware_local.json`，不要改写仓库中的示例文件来保存现场值。

### Git 协作约定

凡是需要在实验电脑验证的代码、脚本、测试或文档，本机安全离线测试通过后应提交并推送，
同时报告 commit hash 和实验电脑更新命令。提交必须使用精确文件清单，不包含本机
`configuration.json` 的现场改动、`hardware_local.json`、`output/`、真实实验数据、厂商
DLL 或未脱敏配置。远端出现非快进或冲突时禁止强推，应先保留现场状态并处理差异。

以下命令只检查数据，不加载 GAS.dll、不连接设备、不创建扫描目录：

```powershell
.\.venv\Scripts\python.exe scripts\inspect_scan_plan.py `
  --positions-mm 0,0.1,0.2,0.2 `
  --camera-count 2 --frames 3 --repeats 1 `
  --image-height 2048 --image-width 2448 --dtype uint16 `
  --travel-min-mm 0 --travel-max-mm 10
```

输出包含扫描点数、首末/最小/最大位置、步长集合、重复位置、总图片数、原始像素数据的
预计存储量、配置行程检查和 real-motion 开关状态。存储估算不包含 TIFF header/metadata，
因此是近似的原始 payload 大小。

## ScanPlan 教学示例

```python
from pathlib import Path
from scan.scan_plan import CameraSettings, ScanPlan

plan = ScanPlan.from_range(
    start="0.0",
    stop="1.0",
    step="0.1",
    cameras=[CameraSettings("12345678", exposure_us=500.0)],
    save_root=Path("output"),
    frames_per_position=2,
    repeats=1,
)
```

为什么用字符串和 `Decimal` 生成 Range？二进制浮点数不能精确表示很多十进制小数，
直接反复加 `0.1` 可能出现 `0.30000000000000004`。内部最终仍统一为 `list[float]`，
但边界生成是可预测的。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

当前测试覆盖 Range/List 配置、多维图片总数、Mock 位移与停止、Mock uint16 光斑、两相机
完整扫描、TIFF/JSON/CSV/MAT、mm/pulse 转换、标定缺失、越界、未知能力、Fake DLL 只读调用序列、
dry-run 位置/存储/行程检查、相机多帧诊断、五轴只读快照与运动 readiness audit，以及
GUI-M1 空间计划、软件边界、保存回读、取消语义和离屏 Qt 构造。以最新提交的实际测试结果为准。

## 下一步（进入真实硬件 GUI 前）

1. 按 SOP 执行 Phase A 只读 bring-up，保存 raw position/status 和设备铭牌信息；
2. 提供匹配版本的 GAS `.h`、SDK/API manual、官方 sample project、controller manual；
3. 提供 stage manual，确认 pulse/mm、方向、行程、零点、限位与急停方案；
4. 运行增强只读快照，核对规划/反馈位置、软限位和逐位状态；
5. 用官方 GUI 的已知安全位移逐轴确认 pulse/mm、零点和行程；
6. 另行评审 Phase B 最小运动与 Stop 验收；本版本不能通过只改 `allow_motion` 绕过安全门；
7. 核心硬件闭环验证后，在现有 GUI-M1 上进入 GUI-M2 真实相机接入；真实位移仍保持禁用。
