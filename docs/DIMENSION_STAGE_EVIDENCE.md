# Dimension Stage Hardware Evidence Matrix

最后更新：2026-09-27，软件版本：bring-up v0.4 + GUI-M2。

## 证据规则

只有厂家官方 API 文档、配套头文件、官方 C/C++ 示例、官方 Python 示例，或本项目已验证的
厂家示例能够确认 GAS API。DLL export/symbol lookup 只能说明某个名字存在，**不能确认参数、
返回值、线程模型或硬件语义**。

状态含义：

- `confirmed-source`：调用形式在当前厂家示例中出现，但不等于已连接本机硬件验证；
- `confirmed-local`：已经完成不接触真实硬件的本机验证；
- `confirmed-hardware-read-only`：已在实验电脑连接真实控制器并完成只读验证；
- `operator-observed`：操作者通过厂家官方控制软件现场观察确认，尚非 Python 自动运动验证；
- `unverified-hardware`：需要真实控制器只读验证；
- `unknown`：没有足够证据，禁止调用或解释。

## Matrix

| Item | Status | Evidence | Safe action now |
|---|---|---|---|
| 64-bit DLL load | confirmed-local | `tests/test_dimension_stage.py`; `positioner/GAS.dll` SHA256 `349014A5F16E9C2DEE28978453AD718DCE52EF52708D7E375AFF7D5D30AF2ED3` 已由 64-bit Python 加载 | allowed, Level 0 |
| Controller connection | confirmed-hardware-read-only | 厂家 Python 示例调用 `GA_OpenByIP(bytes, bytes, 0, 0)`；实验电脑只读连接成功 | 仅允许 Phase A 只读入口 |
| PCIP / CardIP | documented in supplied official package | `ComParam.xml` 为 PCIP `192.168.0.200`、CardIP `192.168.0.1`；Python 示例以此顺序传给 `GA_OpenByIP` | 仍由现场人工确认输入，无程序默认值 |
| Disconnect | confirmed-hardware-read-only | 厂家 Python 示例调用 `GA_Close()`；2026-09-27 五轴会话均正常结束 | Phase A finally 中允许 |
| Axis selection | operator-observed | 相机 X/Y = 轴1/2；物镜 X/Y/Z = 轴3/5/4 | REAL GUI 使用该映射，首次单步仍需逐轴观察 |
| Planned-position read signature | confirmed-hardware-read-only | 厂家示例给出 `GA_GetPrfPos(axis, double*, 1, 0)`；2026-09-27 五轴均成功读取 | 可读取 raw pulse，不转成 mm |
| Encoder/feedback count position | confirmed-hardware-read-only / semantics unresolved | V7.3 手册 5.6 给出签名；2026-09-27 五轴读取值为 `0/1`，而规划位置为数万 pulse | API 调用有效，但当前反馈模式不反映规划位置；禁止把它当作已验证实际位置 |
| `GA_GetSts` signature | confirmed-hardware-read-only | 厂家示例给出签名；2026-09-27 五轴读取成功 | 可读取并按手册解释；动态状态仍需后续验收 |
| `GA_GetSts` bit meanings | documented | V7.3 手册 5.6 列出 ESTOP、报警、软/硬限位、跟随误差、使能、运行、到位、Home 等 bit | 允许只读解码；危险位阻止运动 |
| Controller healthy-state rule | partially confirmed-source | 手册定义危险位；11.6 给出 `RUNNING=0` 且规划位置距目标小于 1 pulse 的到位判据 | 已实现按位检查；仍需实机验证动态变化 |
| `GA_AxisOn` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_PrfTrap` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetTrapPrmSingle` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetPos` | confirmed-source only | 厂家示例传入 `c_int64` pulse target | Phase A 禁止调用 |
| `GA_SetVel` | confirmed-source only | 厂家示例说明单位 pulse/ms | Phase A 禁止调用 |
| Axis 1 `GA_Update(1)` | confirmed-source only | 厂家示例仅演示轴 1 | Phase A 禁止调用 |
| Multi-axis start mask | documented / implemented | V7.3 手册 5.4：bit0..bit7 对应轴 1..8；轴 n mask=`1 << (n-1)` | REAL GUI 合并同组变更轴后一次 Update |
| Axis 1 pulse/mm | confirmed by read/GUI comparison | `-57363 pulse` 对应官方绝对坐标 `-5.73630 mm`；官方 `+` 后读数为 `-57362 pulse` | `10000 pulse/mm` |
| Axis 2..5 pulse/mm | vendor-configured / pending motion observation | 官方控制软件轴 1..5 均为 `PulsPerRev=10000`、`Lead=1`、`Rate=1` | REAL GUI 采用 `10000 pulse/mm`；首次 `0.001 mm` 单步逐轴验收 |
| Direction sign | operator-observed | 轴1 `+→+Y`；轴2 `+→-Z`；轴3 `+→+Y`；轴4 `+→+X`（逆光、物镜向前）；轴5 `+→-Z` | 作为 REAL GUI/数据坐标映射 |
| Mechanical/software range | vendor-configured | 官方控制软件轴 1..5 的 `PosLimt/NegLimt` 均为 `+26/-26 mm` | 项目软件边界；REAL 连接时同步写入控制器软限位 |
| Controller zero ↔ GUI mm | vendor-configured open-loop | 官方 GUI 与轴1 `pulse/10000` 对照一致；启动读取当前规划位置，不自动 Home | 用于开环 GUI 坐标；不声称编码器实际位置 |
| Software limits | implemented / pending motion validation | 现场初始值为完整 int32 范围；REAL 连接调用 `GA_SetSoftLimit` 写入按方向换算的 `±260000 pulse` | 软件预检和控制器软限位双层保护 |
| Positive/negative limit state | documented / enabled in REAL mode | `GetSts` 的 `0x04/0x08/0x20/0x40` 分别为正负软/硬限位；REAL 连接调用 `GA_LmtsOn(axis,-1)` | 朝已触发方向阻止运动，允许反向退回；极性/触发仍需实机验收 |
| Stop API | documented / implemented-local | V7.3 手册 5.6：`Stop(mask, option)`；mask bit 对应轴，option=0 平滑停、1 急停；DLL 导出 `GA_Stop` | Adapter 已实现，尚未实机触发验证；不能替代物理急停 |
| Home API/procedure | documented / implemented-optional | V7.3 手册 5.14；实现 SetPrmSingle/Start/GetSts/Stop | GUI 不自动 Home；仅在明确需要重建零点时显式调用 |
| Axis 3 `0x00004000` snapshot | confirmed-hardware-read-only, repeated | 2026-09-26 与 2026-09-27 五轴快照；手册定义为 `HOME_SWITCH` | 表示零位输入有效，不等于报警或 HOME_SUCCESS |
| `GA_Reset` | confirmed-source, state-changing | 厂家示例调用，但会改变控制器状态 | Phase A 禁止调用 |
| `GA_ZeroPos` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |
| `GA_EncOff` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |

## 当前代码对应关系

- `StageCapabilities` 用 `True / False / None` 区分 confirmed / unsupported / unknown。
- `AxisCalibration` 未知字段默认 `None`，不会把示例数字当成现场标定。
- `DimensionStage.load_library()` 是 Level 0。
- `connect()`、规划/反馈位置读取、软限位读取、状态读取/解码和 `disconnect()` 是 Level 1。
- `stop()`/`emergency_stop()` 已按手册实现，但增强只读脚本不会调用；尚未完成实机停止验收。
- `GasFiveAxisStage` 用单一控制器会话接入 REAL GUI，并在连接时写软限位、启用硬限位。
- REAL GUI 默认最大单条命令 `0.1 mm`，计划预检同时检查首点和相邻点步长。
- Home API 已实现但不自动调用；开环点位运动直接读取启动时规划坐标。
- `get_position()` 对真实 Adapter 明确表示 mm；标定未知时会报错，不会返回伪装成 mm 的 pulse。

## 下一步现场证据

现有厂家资料已用于实现。剩余证据由 REAL GUI 分级验收取得：当前位置采集、逐轴
`0.001 mm` 往返、Stop、限位方向和小范围扫描。
