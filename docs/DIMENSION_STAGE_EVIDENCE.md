# Dimension Stage Hardware Evidence Matrix

最后更新：2026-09-26，软件版本：bring-up v0.3 + GUI-M1。

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
| Disconnect | confirmed-source / unverified-hardware | 厂家 Python 示例调用 `GA_Close()` | Phase A finally 中允许 |
| Axis selection | operator-observed | 相机 X/Y = 轴1/2；物镜 X/Y/Z = 轴3/5/4 | 写入 GUI-M1 元数据；真实运动仍禁止 |
| Planned-position read signature | confirmed-source / unverified-hardware | `Python-正转20000个脉冲-延时5秒-反转20000个脉冲/jason.py`: `GA_GetPrfPos(axis, double*, 1, 0)` | 可读取 raw pulse，不转成 mm |
| Encoder/feedback count position | documented / unverified-hardware | V7.3 手册 5.6：`GetAxisEncPos(axis, double*, count, clock)`；本机 `GAS.dll` 导出 `GA_GetAxisEncPos` | 允许增强 Phase A 只读；不擅自声称一定是独立物理编码器闭环 |
| `GA_GetSts` signature | confirmed-source / unverified-hardware | 同一厂家示例：`GA_GetSts(axis, long*, 1, 0)` | 可读取并打印 raw value |
| `GA_GetSts` bit meanings | documented | V7.3 手册 5.6 列出 ESTOP、报警、软/硬限位、跟随误差、使能、运行、到位、Home 等 bit | 允许只读解码；危险位阻止运动 |
| Controller healthy-state rule | partially confirmed-source | 手册定义危险位；11.6 给出 `RUNNING=0` 且规划位置距目标小于 1 pulse 的到位判据 | 已实现按位检查；仍需实机验证动态变化 |
| `GA_AxisOn` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_PrfTrap` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetTrapPrmSingle` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetPos` | confirmed-source only | 厂家示例传入 `c_int64` pulse target | Phase A 禁止调用 |
| `GA_SetVel` | confirmed-source only | 厂家示例说明单位 pulse/ms | Phase A 禁止调用 |
| Axis 1 `GA_Update(1)` | confirmed-source only | 厂家示例仅演示轴 1 | Phase A 禁止调用 |
| Multi-axis start mask | documented | V7.3 手册 5.4：bit0..bit7 对应轴 1..8；轴 n mask=`1 << (n-1)` | Adapter 已实现；真实运动仍受其他安全门阻止 |
| Axis 1 pulse/mm | confirmed by read/GUI comparison | `-57363 pulse` 对应官方绝对坐标 `-5.73630 mm`；官方 `+` 后读数为 `-57362 pulse` | 记录为轴1 `10000 pulse/mm`；不外推到其他轴 |
| Axis 2..5 pulse/mm | candidate, not yet accepted | 官方 GUI 配置写有 `PulsPerRev=10000`、`Lead=1`、`Rate=1`，但未逐轴完成读数对照 | motion forbidden |
| Direction sign | operator-observed | 轴1 `+→+Y`；轴2 `+→-Z`；轴3 `+→+Y`；轴4 `+→+X`（逆光、物镜向前）；轴5 `+→-Z` | 作为 GUI/数据坐标映射；不解除 motion safety gate |
| Mechanical travel | axis mapping unknown | 官方 GUI 配置含逐轴 `PosLimt` / `NegLimt`，轴 1..6 为 +26/-26 mm；其他轴不同 | 必须先确认实际扫描轴号，再采用对应范围 |
| Controller zero ↔ physical mm | unknown | 没有 Home/坐标定义资料 | motion forbidden |
| Software limits | documented / unverified-hardware | V7.3 手册 5.7：`GetSoftLimit(axis, positive*, negative*)`，单位 pulse；DLL 导出 `GA_GetSoftLimit` | 允许增强 Phase A 只读，不写入限位 |
| Positive/negative limit state | documented / confirmed-hardware-read-only pending enhanced rerun | `GetSts` 的 `0x04/0x08/0x20/0x40` 分别为正负软/硬限位触发 | 允许只读解码；任一位触发即阻止运动 |
| Stop API | documented / implemented-local | V7.3 手册 5.6：`Stop(mask, option)`；mask bit 对应轴，option=0 平滑停、1 急停；DLL 导出 `GA_Stop` | Adapter 已实现，尚未实机触发验证；不能替代物理急停 |
| Home API/procedure | API documented, workflow unverified | V7.3 手册 5.14 给出 HomeStart/Stop/参数/状态；当前机构的模式、方向和参数未验收 | 先用官方 GUI 完成受监督回零；Python Home 保持禁用 |
| Axis 3 `0x00004000` snapshot | confirmed-hardware-read-only | 2026-09-26 五轴快照；手册定义为 `HOME_SWITCH` | 表示零位输入有效，不等于报警或 HOME_SUCCESS |
| `GA_Reset` | confirmed-source, state-changing | 厂家示例调用，但会改变控制器状态 | Phase A 禁止调用 |
| `GA_ZeroPos` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |
| `GA_EncOff` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |

## 当前代码对应关系

- `StageCapabilities` 用 `True / False / None` 区分 confirmed / unsupported / unknown。
- `AxisCalibration` 未知字段默认 `None`，不会把示例数字当成现场标定。
- `DimensionStage.load_library()` 是 Level 0。
- `connect()`、规划/反馈位置读取、软限位读取、状态读取/解码和 `disconnect()` 是 Level 1。
- `stop()`/`emergency_stop()` 已按手册实现，但增强只读脚本不会调用；尚未完成实机停止验收。
- `move_absolute_mm()` 是 Level 2，当前默认配置必然被 safety gate 拒绝。
- `get_position()` 对真实 Adapter 明确表示 mm；标定未知时会报错，不会返回伪装成 mm 的 pulse。

## 需要补充的厂家资料

请优先提供与现场控制器版本匹配的：

1. 与当前 `GAS.dll 1.0.0.1` 对应的 GAS SDK `.h` 头文件或版本说明；
2. 控制器型号、固件手册及通讯配置说明；
3. 位移台/电机型号与 stage manual（行程、方向、pulse/mm 或丝杠/细分参数）；
4. 接线图，特别是正负限位、原点、急停输入；
5. 五轴增强只读快照，以及官方 GUI 已知位移前后的 pulse 对照。
