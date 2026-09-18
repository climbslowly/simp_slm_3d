# First Dimension Stage Hardware Bring-up SOP

本 SOP 只覆盖第一次接线后的只读 Phase A。本轮禁止进入真实运动 Phase B。

## Before power-on

1. 记录控制器和位移台铭牌，不根据外观猜型号。
2. 确认运动区域无障碍物、光学件不会因意外运动碰撞。
3. 找到物理急停或断电手段，并确保操作者能够立即触及。
4. 确认网线、供电、保护地和限位接线符合厂家手册。
5. 从 Windows 网络配置读取本机网卡 IP；不要直接沿用示例 `192.168.0.1`。
6. 从控制器配置/手册确认控制器 IP 和目标轴号。

## Phase A — read-only

允许动作只有：

1. 加载指定 GAS.dll；
2. 使用人工确认的 controller IP、host IP 建立连接；
3. 记录人工确认的轴号；
4. 调用 `GA_GetPrfPos` 读取 raw planned-position pulse；
5. 调用 `GA_GetSts` 读取 raw status；
6. 原样打印数值，不解释状态 bit；
7. 调用 `GA_Close` 断开。

唯一允许的程序入口是：

```powershell
cd C:\slm_3d\dimension_camera
$dllPath = Read-Host "Enter the VERIFIED GAS.dll path"
$controllerIp = Read-Host "Enter the VERIFIED controller IP"
$hostIp = Read-Host "Enter the VERIFIED PC adapter IP"
$axisId = [int](Read-Host "Enter the VERIFIED axis number")
.\.venv\Scripts\python.exe scripts\verify_stage_readonly.py `
  --dll $dllPath `
  --controller-ip $controllerIp `
  --host-ip $hostIp `
  --axis $axisId `
  --confirm-read-only
```

在运行前复核脚本路径和命令中不存在其他程序。不要运行 `positioner/` 下会循环运动的厂家示例。

Phase A 明确禁止：Reset、Zero、Encoder On/Off、Axis/Servo On、Home、Jog、Move、
`GA_Update`、Stop test，以及任何限位触发测试。

## Phase B — supervised minimal motion

本轮不进入 Phase B。只有以下内容全部有书面证据并录入 `StageCapabilities` / `AxisCalibration`
之后，才能另行设计受监督的最小运动方案：

- 控制器型号、固件版本与 DLL/SDK 版本匹配；
- 现场轴号；
- pulse/mm；
- pulse 正方向对应的物理方向；
- 机械 travel min/max；
- controller pulse=0 对应的物理 mm 坐标；
- 正负限位信号定义和当前状态；
- `GA_GetSts` bit 定义、运动完成和故障判据；
- Stop API 准确签名、停止模式与已验证的急停方案；
- Home API/流程（如果将使用）；
- 单轴/多轴 `GA_Update` mask；
- 第一次运动目标、速度、加速度和观察人员确认。

Phase B 应另写测试计划，不能通过修改 `allow_motion=True` 临时绕过 safety gate。

## Abort conditions

出现任一情况立即中止、保存终端输出并按现场安全流程断电/急停：

- 只读脚本运行期间发生任何机械运动、声音突变或使能变化；
- 控制器或驱动器显示 fault/alarm；
- 连接到的型号/IP/轴号与记录不一致；
- raw position/status 读取失败、变化异常或不可重复；
- 已知限位处于触发状态，或限位状态无法确认；
- DLL/固件/SDK 版本不匹配；
- 电机、驱动器、线缆异常发热或有异味；
- 操作者无法立即触及急停/断电装置；
- 任何人对单位、方向、行程或当前机械位置有疑问。

软件异常时不要用未知签名的 `GA_Stop` 做试验。Phase A 本身不应产生运动；若发生意外运动，
使用已经确认的物理安全手段，而不是临时猜测 API。

## Information to record

把以下内容连同日期、操作者和照片/截图一起保存：

- controller model、序列号、固件版本；
- stage model、motor/drive model；
- DLL/SDK 文件版本和 SHA256；
- controller IP、PC adapter IP、子网掩码；
- axis number；
- pulse/mm 及其资料页来源；
- 机械 travel min/max；
- direction sign 的物理定义；
- controller zero 与物理坐标的关系；
- 当前 raw planned position；
- 当前 raw status（十进制和十六进制）；
- `GA_GetSts` bit 定义来源；
- positive/negative limit 当前状态与定义来源；
- Stop/Home API 的准确签名和资料来源；
- Phase A 完整终端输出与任何错误码。
