# Dimension Camera

维度/GAS 位移台与 Basler pylon 相机的自动扫描项目。当前版本是 **Stage Bring-up V0.4 + GUI-M2**：
硬件 Adapter、Mock 设备、ScanPlan、扫描状态机、TIFF/JSON/CSV/MAT 保存和自动测试已经建立；
本轮增加了单位隔离、能力/标定模型、真实运动 safety gate、dry-run 和只读接入 SOP。
GUI 默认仍是 Mock；显式 REAL 启动时接入 Basler 相机和五轴 GAS 控制器，支持当前位置采集、
手动单步与空间扫描。真实模式使用控制器规划位置开环运行，不依赖当前无效的编码器 `0/1` 读数。

## 先说安全边界

- 默认入口只运行 Mock，不会连接或移动真实设备。
- `DimensionStage.connect()` 只调用 `GA_OpenByIP`，不会 Reset、清零、使能或移动。
- 真实 Adapter 的上层坐标始终是 mm；原始 pulse 只能通过明确命名的只读方法获取。
- `StageCapabilities` 的未知能力为 `None`，`AxisCalibration` 的未知标定也为 `None`。
- 真实运动必须显式设置 `allow_motion=True`，且完整通过能力、标定、范围和健康状态安全门。
- ETH_GAS_N V7.3 手册已确认轴启动 mask、状态 bit、Stop、反馈位置和软限位读取方式。
- Stop 已在 Adapter 中实现但尚未实机验收；增强只读诊断不会调用 Stop 或任何状态修改 API。
- Home API 已按手册实现，但 GUI 启动不自动 Home；它直接读取控制器当前规划位置。
- 厂家控制软件配置确认轴 1..5 为 `10000 pulse/mm`、坐标范围 `±26 mm`；真实 GUI 将其作为软件边界和控制器软限位。
- REAL 模式把单条命令限制为 `0.1 mm`，并启用硬限位输入、检查状态位和运动方向。
- 示例配置仍不会自行连接设备；实验电脑必须在被 Git 忽略的 `hardware_local.json` 中填写 DLL、IP 和相机序号。

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
物理编码器闭环。2026-09-27 现场只读结果中五轴反馈值仅为 `0/1`，没有跟随规划位置；
`GA_GetSoftLimit` 均返回完整 int32 上下界，当前没有可依赖的有限控制器软限位窗口。

### StageCapabilities 与 AxisCalibration

`hardware/stage_safety.py` 集中保存安全事实：

- `StageCapabilities` 使用 `True / False / None` 表示 confirmed / unsupported / unknown；
- `AxisCalibration` 保存 axis、pulse/mm、行程、方向、零点和可选软限位；
- mm/pulse 转换只能在 `pulses_per_mm`、方向和零点全部已知时执行；
- 真实运动按危险状态位逐项拦截，不使用完整 raw status 白名单；
- Stop、状态解释、反馈位置、软限位读取和轴启动 mask 已有手册依据；
- Home 是显式可选操作，不再是点位运动前置条件；GUI 不自动调用。

### 仍需用首次小步运动验收

- 设备枚举：示例只有固定 IP 连接，没有枚举 API；
- 已记录的轴号、GUI 逻辑方向与实际机构方向是否逐轴一致；
- `PulsPerRev=10000`、`Lead=1`、`Rate=1` 对应的 `10000 pulse/mm` 是否逐轴产生预期距离；
- 厂家配置的 `PosLimt=26` / `NegLimt=-26` 是否与每轴实际可用行程一致；
- 当前反馈计数模式为何只返回 `0/1`；它不再阻塞开环规划位置运行；
- 当前机构应采用的 Home 模式、方向、速度和最大搜索距离；
- Stop 的现场实际减速效果及独立物理急停方案；
- 每轴限位接线、触发极性，以及为何控制器软限位仍为完整 int32 范围；
- 五轴 `0.001 mm` 指令的实际距离、方向和返回起点能力。

这些项目通过 REAL GUI 的分级验收继续记录，不再等待额外厂家文件。

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

## 运行 GUI

```powershell
cd C:\slm_3d\dimension_camera
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe -m gui.app
```

真实五轴和 Basler 相机使用实验电脑的 `hardware_local.json`：

```powershell
.\.venv\Scripts\python.exe -m gui.app `
  --real `
  --hardware-config .\hardware_local.json `
  --confirm-real-motion
```

REAL 模式启动时读取五轴规划位置，不执行 Reset、Zero 或 Home；随后写入 `±260000 pulse`
控制器软限位并调用 `GA_LmtsOn(axis, -1)` 启用正负硬限位。GUI 的“当前位置采集一张”不会
产生位移；第一次运动应只使用 `0.001 mm` 手动步长。限位触发时程序拒绝继续朝限位方向，
但允许反向退回。

重新打开已有扫描目录：

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
REAL 模式使用厂家配置的开环规划位置；它不声称完成编码器闭环验证。限位接线和可靠停止效果
仍需通过首次 GUI 单步验收。Mock 图像用“物镜横向位置 − 相机位置”
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
每个扫描点同时生成 `point_XXXXXX_raw.tif` 和 `point_XXXXXX_raw.mat`；逐帧 MAT 的 `image`
变量直接包含原始像素。扫描目录根部另有 `scan_data.mat`，汇总坐标、状态、ROI 指标矩阵、
TIFF 和逐帧 MAT 的相对路径。旧目录可用 `scripts/export_scan_mat.py` 补导出汇总 MAT。

GUI 中的起点、终点、步长、位置列表和固定轴值都表示“相对于点击开始时物镜位置的偏移”。
二维路径可在 GUI 或 `configuration.json` 的 `plane_scan_path` 中选择：`SERPENTINE` 为逐行
往返的蛇形，`Z_SHAPED` 为每行同向的 Z 形。Z 形换行回跳不采图，并自动拆成不超过真实
Adapter 单命令上限的小步。正常扫描完成后，物镜按每条最多
`0.001 mm` 的小步返回扫描开始位置；停止或故障后不会自动继续运动。错误文本可直接选中，
也可点击“复制错误”写入剪贴板。

按钮语义：物镜区“移动到绝对目标（会运动）”会在 REAL 模式下调用 `GA_SetPos/GA_Update`；
“当前位置采集一张（不移动）”只在当前坐标曝光和保存，不会提交新的位移。

REAL Adapter 不再只依赖 `RUNNING` 位或规划位置判断运动结束。每条命令会依据梯形速度、加速度
和 pulse 距离计算最短完成时间，并增加 `20 ms` 通信余量；扫描后复位完成还会校验三轴规划
位置是否回到起点。GUI 的“实时规划位置”在空闲时每 `250 ms` 读取一次，运动等待期间约每
`100 ms` 更新一次。该值仍是 `GA_GetPrfPos` 开环规划位置，不是编码器实测位置。

`X/Y/Z range` 均使用相对坐标。例如当前位置 Z 为 `1.6478 mm` 时，Z range 输入
`-0.1 / 0.1 / 0.05`，采集目标依次为 `1.5478、1.5978、1.6478、1.6978、1.7478 mm`；
X/Y 保持扫描开始值，完成后 Z 返回 `1.6478 mm`。
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

## 下一步（REAL GUI 分级验收）

1. REAL GUI 启动后先核对五轴显示位置，并点击“当前位置采集一张”。
2. 把手动步长改为 `0.001 mm`，逐轴单击一次并观察方向与停止行为。
3. 每轴完成 `+0.001/-0.001 mm` 往返，核对规划位置回到起点。
4. 验收 Stop 后再执行 2～3 点、步长不超过 `0.1 mm` 的单轴扫描。
5. 最后再进入小范围二维扫描；Home 仅在确实需要重建控制器零点时单独使用。
