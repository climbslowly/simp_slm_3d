# Dimension Stage Hardware Evidence Matrix

最后更新：2026-09-16，软件版本：bring-up v0.2。

## 证据规则

只有厂家官方 API 文档、配套头文件、官方 C/C++ 示例、官方 Python 示例，或本项目已验证的
厂家示例能够确认 GAS API。DLL export/symbol lookup 只能说明某个名字存在，**不能确认参数、
返回值、线程模型或硬件语义**。

状态含义：

- `confirmed-source`：调用形式在当前厂家示例中出现，但不等于已连接本机硬件验证；
- `confirmed-local`：已经完成不接触真实硬件的本机验证；
- `unverified-hardware`：需要真实控制器只读验证；
- `unknown`：没有足够证据，禁止调用或解释。

## Matrix

| Item | Status | Evidence | Safe action now |
|---|---|---|---|
| 64-bit DLL load | confirmed-local | `tests/test_dimension_stage.py`; `positioner/GAS.dll` SHA256 `349014A5F16E9C2DEE28978453AD718DCE52EF52708D7E375AFF7D5D30AF2ED3` 已由 64-bit Python 加载 | allowed, Level 0 |
| Controller connection | confirmed-source / unverified-hardware | 厂家 Python 示例调用 `GA_OpenByIP(bytes, bytes, 0, 0)` | 仅在 Phase A 显式执行 |
| Controller/host IP | unknown for field hardware | `192.168.0.200/192.168.0.1` 只来自示例 | 必须由现场人工输入，无程序默认值 |
| Disconnect | confirmed-source / unverified-hardware | 厂家 Python 示例调用 `GA_Close()` | Phase A finally 中允许 |
| Axis selection | partly confirmed | 示例把轴号作为第一个参数，且注释给出 1..8；现场轴号未知 | 用户必须显式填写，禁止默认认定 |
| Planned-position read signature | confirmed-source / unverified-hardware | `Python-正转20000个脉冲-延时5秒-反转20000个脉冲/jason.py`: `GA_GetPrfPos(axis, double*, 1, 0)` | 可读取 raw pulse，不转成 mm |
| Actual encoder position | unknown | 当前资料没有已确认的实际编码器位置 API | do not claim/read |
| `GA_GetSts` signature | confirmed-source / unverified-hardware | 同一厂家示例：`GA_GetSts(axis, long*, 1, 0)` | 可读取并打印 raw value |
| `GA_GetSts` bit meanings | unknown | 示例只打印 raw value，没有 bit 定义 | do not interpret |
| Controller healthy-state rule | unknown | 缺少状态位文档和健康条件 | motion forbidden |
| `GA_AxisOn` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_PrfTrap` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetTrapPrmSingle` | confirmed-source only | 厂家轴 1 运动示例 | Phase A 禁止调用 |
| `GA_SetPos` | confirmed-source only | 厂家示例传入 `c_int64` pulse target | Phase A 禁止调用 |
| `GA_SetVel` | confirmed-source only | 厂家示例说明单位 pulse/ms | Phase A 禁止调用 |
| Axis 1 `GA_Update(1)` | confirmed-source only | 厂家示例仅演示轴 1 | Phase A 禁止调用 |
| Multi-axis start mask | unknown | 没有轴 2..8 mask 的官方资料 | motion forbidden for non-axis-1 |
| pulse/mm | unknown | 当前目录没有台体/电机标定资料 | all physical motion forbidden |
| Direction sign | unknown | 没有确认 pulse 正方向对应的物理方向 | motion forbidden |
| Mechanical travel | unknown | 没有 stage manual/铭牌行程记录 | motion forbidden |
| Controller zero ↔ physical mm | unknown | 没有 Home/坐标定义资料 | motion forbidden |
| Software limits | unknown | 虽能观察到相关 DLL symbol，但无可靠签名/语义 | do not call |
| Positive/negative hardware limit | unknown | 无输入 bit 或 API 定义 | do not call; motion forbidden |
| Stop API | unknown | symbol lookup 不是签名证据 | do not call; motion forbidden |
| Home API/procedure | unknown | 当前厂家示例没有 Home 流程 | do not call; motion forbidden |
| `GA_Reset` | confirmed-source, state-changing | 厂家示例调用，但会改变控制器状态 | Phase A 禁止调用 |
| `GA_ZeroPos` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |
| `GA_EncOff` | confirmed-source, state-changing | 厂家示例调用 | Phase A 禁止调用 |

## 当前代码对应关系

- `StageCapabilities` 用 `True / False / None` 区分 confirmed / unsupported / unknown。
- `AxisCalibration` 未知字段默认 `None`，不会把示例数字当成现场标定。
- `DimensionStage.load_library()` 是 Level 0。
- `connect()`、`get_position_pulse()`、`read_raw_status()`、`disconnect()` 是 Level 1。
- `move_absolute_mm()` 是 Level 2，当前默认配置必然被 safety gate 拒绝。
- `get_position()` 对真实 Adapter 明确表示 mm；标定未知时会报错，不会返回伪装成 mm 的 pulse。

## 需要补充的厂家资料

请优先提供与现场控制器版本匹配的：

1. GAS SDK `.h` 头文件及对应 DLL 版本说明；
2. GAS API manual，特别是 `GA_GetSts`、Stop、limit、Home；
3. 官方 C/C++ sample project（包含工程配置和结构体定义）；
4. 控制器型号、固件手册及通讯配置说明；
5. 位移台/电机型号与 stage manual（行程、方向、pulse/mm 或丝杠/细分参数）；
6. 接线图，特别是正负限位、原点、急停输入。
