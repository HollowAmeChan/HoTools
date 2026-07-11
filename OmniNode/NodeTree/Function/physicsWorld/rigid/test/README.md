# Rigid/Jolt 语义测试

本目录实现 `../docs/JOLT_TEST_STRATEGY.md` 定义的可执行测试架构。

当前切片（`native_binding_v1`）：

- 严格加载 `hotools_jolt_fixture_v1` JSON；
- 按 fixture id 固定刚体创建顺序和命令顺序；
- 输出包含原始 float32 位模式的规范化刚体/contact trace；
- 提供自由落体、恒速运动和冲量解析 oracle；
- 验证阻尼、速度上限和六个 allowed DOF 位的刚体参数语义；
- 支持十一种已接入约束的 schema、state trace 和基础自由度/耦合关系 oracle；
- 验证 Fixed 相对变换、Point 锚点/旋转自由、Distance 区间收敛；
- 验证 Hinge 只绕局部 Z、Slider 只沿局部 Z、Cone swing/twist 语义；
- 验证 SwingTwist 的椭圆摆角和本地 Z 扭转限制彼此独立；
- 验证 SwingTwist 的 Pyramid 轴映射、摩擦力矩和独立 swing/twist motor；
- 验证 SixDOF 六轴 Free/Fixed/Limited、平移/旋转限位及公共 spec/adapter 映射；
- 解析验证 SixDOF 平移轴摩擦力和旋转轴摩擦力矩；
- 验证 SixDOF 平移速度 motor、旋转位置 motor、力限幅和 motor lambda，并覆盖公共 spec、生成约束与调试绘制映射；
- 按 Jolt 官方 FrequencyAndDamping 隐式欧拉公式逐帧验证 SixDOF 三平移轴 limit spring，并覆盖公共 spec 与生成约束映射；
- 验证 SixDOF 约束空间 XYZ 平移/旋转 current-value readback、result stream 和调试绘制；
- 解析验证 Pulley 固定加权绳长、ratio 有效质量速度投影与约束 lambda，并覆盖公共 spec、生成约束、result 与绳路调试；
- 验证 Gear 的 Hinge/Hinge 引用拓扑与反向角速度比、RackAndPinion 的 Hinge/Slider 引用拓扑与旋转/平移比；
- 按 Jolt `FrequencyAndDamping` 隐式欧拉公式复算 Distance/Hinge/Slider 弹簧；
- 解析验证 Hinge/Slider 摩擦，以及速度/位置电机的限幅和收敛轨迹；
- 验证不同质量或转动惯量的双动态体反作用与总动量守恒；
- 验证 contact/sensor 状态机、接触几何字段和传感器非阻挡运动；
- 验证 RayCast 最近命中、解析几何、sensor/ignore 过滤和安全 miss；
- 解析验证 restitution 正碰、平面库仑摩擦和双向 collision mask；
- 验证旋转约束 frame、shape offset/rotation 与高速 LINEAR_CAST CCD；
- 验证独立 A/B anchor、约束禁碰删除恢复及 draw size 非物理性；
- 使用全新世界执行逐位重放检查；
- 在十个全新进程中验证 canonical physical hash 稳定；
- 输出 JSONL trace、断言报告和机器可读 manifest；
- 使用匹配的 native 模块在 CPython 3.11 和 3.13 下运行。

当前切片（`adapter_binding_v1`）：

- 同一份 fixture 映射为生产 `RigidBodySpec` / `ConstraintSpec`；
- 经生产 `JoltAdapter` 调用 native ABI；
- 复用 S1 canonical trace 和 assertions；
- `compare_traces.py` 对 runner 间数值做结构化容差差分；
- `_native/tests/test_jolt_semantic_matrix.py` 对全部 P0 执行 S1/S2 parity。

当前切片（`blender_pipeline_v1`）：

- 后台 Blender 为全部 60 个 P0 fixture 创建真实 RNA 对象和约束；
- 跑 scope、world setting、命令、contact/query、solver result 和统一 writeback；
- 覆盖十一种约束、Quaternion 写回、same-frame、jump、reset 和 dispose；
- `BREAK-001/002` 分层验证原生 lambda 基线、HoTools 冲量阈值、断裂后释放和同帧重放；
- 每次运行内置 S1/S3 tolerant parity，不以自身输出作为正确性 oracle。

当前切片（跨 ABI 差分）：

- `run_cross_abi_semantics.py` 自动发现 CPython 3.11 与 3.13；
- 两套子运行固定加载 `_Lib/py311` 与 `_Lib/py313` 中匹配的 native 模块；
- 校验 fixture 集合、内容 hash、子运行状态和 canonical trace 容差；
- 输出 `hotools_jolt_cross_abi_report_v1` JSON 报告；
- `_native/tests/test_jolt_cross_abi_semantics.py` 提供代表 fixture smoke，缺少任一解释器时明确报告 SKIP。

当前切片尚未实现：

- 已批准 golden；
- 性能阈值冻结，目前只有首轮基线。

`CONE-003` 与 `SWING_TWIST-004` 使用非 Euler 奇异的 60 度旋转验证独立
A/B frame。`frame_swing_limit` 从每帧 body 姿态重建两侧 live twist 轴，
`rotation_world_axis_only` 验证任意世界轴旋转；两者都不依赖约束
`current_value` 作为自身 oracle。

## 当前实施顺序

2026-07-11 起暂停新增 Jolt feature surface，按以下门禁推进：

1. `DET-003` 与生产路径 `simulation_order_key`（2026-07-11 已完成）；
2. 共用 fixture 的 adapter parity runner 与 trace comparator（2026-07-11 已完成）；
3. 共用 fixture 的完整 P0 Blender semantic runner（2026-07-11 已完成）；
4. 跨 ABI、overflow、双 ABI 10,000 帧 soak 与首轮性能采样（2026-07-11 已完成）；
5. 恢复 Path、高级 shape/query 等能力扩展。

旧式 `backends/test_blender_rigid.py` 仍是有效链路回归；即使全部通过，也不能记作 `blender_pipeline_v1` semantic pass。

刚体容量门禁由 `_native/tests/test_jolt_rigid_native.py` 和
`backends/test_blender_rigid.py` 共同覆盖：`max_bodies` 溢出必须抛出可诊断的
Python `RuntimeError`，失败创建保持原子性，已接纳刚体继续推进，释放容量后可以
再次创建；生产 solver 只拒绝稳定排序后的超额 slot，并在 `rigid_solver_stats` 中
发布准确的 `sync_error_count`。

接触事件 overflow 门禁使用 130 个重叠动态 sensor 产生 8385 个 pair，验证固定
缓存只保留 8192 条、`contact_event_overflow` 准确记录 193 条，并由 Blender
生产链确认 adapter、contact/sensor result channel 和 solver stats 一致。`clear()`
后的首个低负载 step 不得重发旧世界的 removed 回调，下一轮事件输出和 overflow
计数必须恢复正常。

使用两个全新世界运行全部 P0 fixture：

```powershell
& 'C:\Users\hhh12\AppData\Local\Programs\Python\Python313\python.exe' `
  run_native_semantics.py --tag p0 --repeat 2
```

经生产 spec/adapter 路径运行全部 P0 fixture：

```powershell
& 'D:\Blender\Blender 4.5\4.5\python\bin\python.exe' `
  run_adapter_semantics.py --tag p0 --repeat 2
```

运行完整后台 Blender semantic matrix：

```powershell
& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  run_blender_semantics.py -- --repeat 2
```

使用 Blender 内置 Python 运行 py311 ABI：

```powershell
& 'D:\Blender\Blender 4.5\4.5\python\bin\python.exe' `
  run_native_semantics.py --tag p0 --repeat 2
```

自动运行 py311/py313 全矩阵并生成容差差分报告：

```powershell
& 'C:\Users\hhh12\AppData\Local\Programs\Python\Python313\python.exe' `
  run_cross_abi_semantics.py --tag p0 --repeat 2
```

跨 ABI 产物默认写入 `C:\tmp\hotools_jolt_cross_abi\<run-id>`；总报告为
`cross-abi-report.json`，两套原始 manifest/trace 分别保存在 `py311` 和 `py313` 子目录。

运行当前 ABI 的 10,000 帧堆叠与约束链稳定性门禁：

```powershell
python run_native_soak.py --frames 10000 --sample-every 1000
```

runner 每帧检查 finite、body/constraint 资源计数、位置边界和约束残差，只按
`--sample-every` 稀疏保存状态；报告默认写入
`C:\tmp\hotools_jolt_soak\<run-id>\soak-report.json`。普通 native discovery
只运行 300 帧 smoke，完整 10,000 帧属于 release 门禁。

运行后台 Blender 首轮性能矩阵：

```powershell
& 'D:\Blender\Blender 4.5\blender.exe' --background --factory-startup --python `
  benchmark_blender_rigid.py -- --warmup 10 --samples 30 `
  --body-counts 1,128,1024 --constraint-counts 32,256 --contact-counts 32,256
```

runner 采集 native step、Blender pipeline、writeback 的 P50/P95，并记录接触事件
数量与 Windows process working set 高水位。报告默认写入
`C:\tmp\hotools_jolt_benchmark\<run-id>\benchmark-report.json`，schema 为
`hotools_jolt_blender_benchmark_v1`。当前报告固定写入 `thresholds_frozen=false`；
需在相同机器、构建和后台条件下重复采样确认波动后，才能把本轮数据转成阻断阈值。

只运行当前约束切片：

```powershell
& 'D:\Blender\Blender 4.5\4.5\python\bin\python.exe' `
  run_native_semantics.py --tag constraint --repeat 2
```

测试产物默认写入 `C:\tmp\hotools_jolt_test\<run-id>`，并且绝不会自动更新
golden 基线。

刚体始终按 fixture id 排序创建。同一 frame/phase 的 timeline 命令按 JSON
数组中的显式顺序执行；改变此顺序属于有意修改输入，并会反映在 physical hash 中。

约束 fixture 要求 native 模块提供 `get_constraint_state` 以及独立 A/B anchor
参数。旧 ABI 会明确失败；`_native/tests/run_all.py` 中的约束矩阵则会报告 SKIP，
不会把 ABI 缺失误报成物理通过。

contact/query fixture 还要求 `get_contact_events` 与 `cast_ray`。原生测试入口会把
旧 ABI 明确报告为 SKIP，并继续保留基础刚体矩阵的独立结果。
