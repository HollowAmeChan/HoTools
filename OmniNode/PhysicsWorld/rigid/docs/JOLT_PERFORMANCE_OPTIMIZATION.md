# Jolt 刚体性能优化契约

本文档记录 `PhysicsWorld/rigid` 的性能测量边界和优化顺序。它服从
[`OmniNode/ARCHITECTURE.md`](../../../ARCHITECTURE.md) 与
[`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`](../../../doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md)：
Python 负责物理世界注册、调度和结果发布，native 负责 Jolt 运行时；native 工作线程不得访问 Blender RNA、依赖图或 Python 对象。

## 1. 默认路径

`physicsRigidSolver` 的“热点耗时调试”默认关闭。关闭时必须满足：

- 不读取 `perf_counter`；
- 不创建分段计时字典；
- 不改变 Jolt step、接触事件和结果流的业务顺序；
- 不改变缓存身份、重建条件或物理参数。

开启后，计时写入当前帧的 `rigid_solver_stats` 结果 `timing` 字段。该字段不是物理输入，也不能参与缓存键。

## 2. 计时 schema

`timing.schema` 固定为 `jolt_rigid_step_timing_v1`，`timing.unit` 固定为 `ms`。当前分段含义如下：

| 阶段 | 边界 |
| --- | --- |
| `settings_sync_ms` | Jolt 世界设置与隐式约束同步 |
| `body_sync_ms` | 刚体 slot 排序、运动学更新和批量注册 |
| `constraint_sync_ms` | 显式约束同步 |
| `command_apply_ms` | 当前帧刚体命令交换区消费 |
| `native_step_ms` | `JoltWorld.step` 调用边界，包含 Jolt 原生模拟 |
| `contact_snapshot_decode_ms` | 接触列式快照读取、句柄映射和 Python 事件字典构建 |
| `breakable_policy_ms` | 可断裂约束策略 |
| `transform_publish_ms` | 刚体 transform 结果发布 |
| `constraint_publish_ms` | 约束状态结果发布 |
| `contact_publish_ms` | 接触与传感器结果发布 |

`step_ms` 仍然是 native 返回的业务耗时；它与 `native_step_ms` 的差异用于识别 Python/native 边界测量误差，不应互相覆盖。

## 3. 测量顺序

优化必须按以下顺序推进：

1. 先在真实 OmniNode 节点流水线开启分段计时，采集至少 100 个连续帧和接触密集帧；
2. 先处理 `contact_snapshot_decode_ms`、结果发布和重复数据转换，再调整 Jolt 参数；
3. Python 到 C++ 的数据应尽量一次进入、在 native 持有并透传，避免逐刚体和逐接触往返；
4. 只有在数据通路收敛后，才评估 worker 数量、solver iterations、broad phase、睡眠和接触缓存等 Jolt 设置；
5. 每次优化同时记录 `step_ms`、各分段、刚体数、约束数、接触数和结果计数，避免只看单一峰值。

## 4. 真实工程基准

基准工程：`C:\Users\hhh12\Desktop\模拟.blend`，约 1500 个刚体，帧 100 后接触事件显著增加。

推荐使用 Blender 5.2 的无 GPU 后台模式运行测量脚本；若必须使用 4.5.8，则先验证 addon 注册和 OmniNode frame handler 已加载。脚本必须通过真实 `OmniNodeTree` 调用 solver，不得直接构造一个脱离节点流水线的 adapter 微基准作为结论。

每轮输出至少包括：

- 帧号、刚体数、约束数、接触事件数和溢出数；
- `step_ms` 与完整 `timing` 分段；
- 采样数量、平均值、P50、P95、最大值；
- 是否开启接触事件记录和 Jolt worker 数量。

## 4.1 当前真实基线（2026-08-08）

在 `模拟.blend` 中以 Blender 4.5.8 后台模式、真实 `OmniNodeTree` 执行 1–300 帧，并在第二轮用 `scene.frame_set()` 配合暂时移除自动 frame handler 的方式复核依赖图更新。当前结果为 1537 个刚体、0 个显式约束，样本帧没有产生接触事件，因此不能用这份文件证明接触快照是热点。

在复用帧内 slot 顺序后，常态帧大致为：native `0.4–3.4 ms`、刚体同步 `1.8–2.4 ms`、transform 发布 `4–6 ms`；仍有偶发的 transform 发布峰值约 `47–52 ms`，说明下一步应继续检查 Python 分配/垃圾回收和结果流批量表示，而不是先调整 Jolt solver 参数。首帧批量注册约 `9 ms`。

已补充 `get_body_states_numpy()` 列式 native ABI，并让 Python 适配器优先使用它；17 项 Jolt backend 回归在 Blender 4.5.8 与 5.2.0 均通过。短基准的常态 transform 发布没有明显变化，说明主要峰值不在 nanobind tuple 转换，后续应直接评估结果流的批量表示和 Python 分配峰值。

## 5. 后续候选

在有基线后再逐项验证：

- 接触快照从“逐事件 Python 字典”收敛为 native 所有的批量结果；
- transform、约束和接触结果减少重复转换；
- Jolt worker 数量与 Blender 主线程调度的配合；
- solver velocity/position iterations、sleep、broad phase 和 contact cache 设置。

所有候选都必须保留结果流语义、重置语义和调试可观测性；不能以绕过 PhysicsWorld 或直接写 Blender 对象换取局部 benchmark 数字。
## 4.2 5.2 synthetic contact baseline (2026-08-08)

Using Blender 5.2 background mode and the existing rigid benchmark with 1536 bodies:

- body-only: native P50 0.169 ms, pipeline P50 31.14 ms, writeback P50 16.19 ms;
- contact-heavy: native P50 2.942 ms, pipeline P50 43.48 ms, writeback P50 20.26 ms, about 2994 contact events.

This is evidence that the current published Jolt step is not the 100 ms hotspot in this fixture. Further work should profile result publication/writeback and the actual project settings before changing Jolt solver switches.

When hotspot timing is enabled, `transform_publish_ms` is additionally split into
`transform_clear_ms`, `transform_state_fetch_ms`, and `transform_result_loop_ms`.
These fields are diagnostic only and are absent from the default path.

The first Jolt switch evaluation is therefore deferred: the current native ABI only
exposes world capacity, worker count, solver iterations, gravity and contact recording.
Speculative contact distance, manifold reduction, large-island splitting and allocator
size remain advanced candidates, but none is enabled or changed until a contact-heavy
measurement shows that native `step_ms` is the limiting segment.
