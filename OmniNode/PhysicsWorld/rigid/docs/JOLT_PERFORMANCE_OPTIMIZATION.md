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
| `contact_snapshot_stage_ms` | O(1) 读取 native 接触/传感器事件数量并登记本帧快照 |
| `contact_snapshot_decode_ms` | solver 热路径不再解码，固定为 0；真实解码只发生在结果消费者读取时 |
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

## 6. Native 惰性批结果（2026-08-09）

Jolt transform 与 contact/sensor 已改用 Physics World 通用 `PhysicsResultBatch`：

- transform 每帧只从 native 取得一次列式数组，solver 在结果流登记一个批 owner；Collection 写回直接消费同一列并在 `hotools_native.compute_rigid_delta_columns_v2` 中反算 delta，不创建逐刚体结果字典；读取状态、调试或通用结果节点实际消费时才展开公开 dict。
- contact listener 在 C++ 侧维护本步事件数、sensor 数和 overflow 数。solver 只读取三个 O(1) 计数并登记 native 快照；`get_contact_events_numpy()`、handle 到 slot 映射和逐事件 dict 只在 contact/sensor 消费者真实读取时执行，两个通道共享一次解码缓存。
- same-frame 无待处理工作时可重发同一批快照；同帧结构或命令发生变化时旧接触批立即失效。restart/dispose 仍沿公共 Physics World 生命周期清理。

Blender 5.2 后台、1536 个动态刚体接触地面的 25 帧探索基准（约 2988–2994 条接触事件）：pipeline P50 `30.68 ms`，writeback P50 `7.99 ms`，native step P50 `2.88 ms`。改动前同一类基线分别约为 `43.48 ms`、`20.26 ms`、`2.94 ms`。

开启热点计时的独立复核中，`transform_publish_ms` P50 为 `1.00 ms`，`contact_snapshot_stage_ms` P50 为 `0.0066 ms`，`contact_publish_ms` P50 为 `0.0077 ms`，`contact_snapshot_decode_ms` 为 `0`。这说明 Jolt 模拟步节点内原先主要的逐项 Python 物化已经从默认路径移除；剩余 pipeline 时间主要位于 Physics World Begin/Commit、Blender frame/depsgraph 和写回，而不是 Jolt result publication。
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

## 7. 下一阶段：原生稳定刚体表与批同步（暂停）

当前优化停在 Native 惰性批结果完成之后。本节只记录下一阶段的设计方向，当前不修改 ABI、不改 Python/C++ 实现，也不重新编译 native 模块；恢复工作前应先重新核对本文、Physics World 流水线契约和 OmniNode 总体架构。

### 7.1 现状与目标

在 1537 个刚体的稳定帧测量中，`transform_publish_ms` 已降至约 `1.00 ms`，接触快照注册与发布已接近可忽略；Jolt 模拟步内部剩余较明确的 Python 热点是 `body_sync_ms`，P50 约 `1.94 ms`。下一阶段的目标是让稳定帧不再由 Python 扫描并逐个同步全部刚体，而是由 native 长期持有一张与 Physics World slot 对齐的稳定刚体表：

- 冷启动或结构变化时一次性提交完整刚体表；
- 稳定帧只批量提交运动学位姿、运行时脏属性和命令；
- 输出行与稳定表保持一致，避免每帧重建 `slot_id -> native row` 映射；
- 将 Python/C++ 往返次数收敛为少量批调用，同时保留现有结果流、重置和同帧重发语义。

### 7.2 权责边界

- Python 继续负责 Blender RNA 读取、Physics World 注册、帧调度、稳定 slot 身份和结构脏判定。
- C++ 只持有 POD/列式镜像数据、稳定行索引和 Jolt handle；native 工作线程不得访问 Blender RNA、依赖图或 Python 对象。
- Jolt 不直接写回 Blender。所有变换仍经公共 Physics World 结果流和三种统一写回模式发布。
- `generation`、restart、dispose、跳帧重置、same-frame 重发和缓存失效语义不得改变。
- 静态、动态、运动学类型互换原则上视为结构替换；刚体替换时必须在同一事务中处理引用它的 Jolt 约束。

### 7.3 建议实施阶段

1. **稳定表 ABI**：以稳定 slot/内部 handle 建立 native body row，记录表版本和行 generation；删除、替换或重建时使旧行立即失效。
2. **稳定帧批输入**：用一次调用提交运动学位置、旋转和时间步；用另一次调用提交运行时脏属性或命令。无结构变化时不得在 Python 侧全量扫描刚体 slot。
3. **结构事务**：新增、删除、类型变化和形状重建统一形成结构补丁或完整重建，并保证依赖约束与 body handle 同步更新。
4. **结果映射复用**：只在表版本变化时重建 `object_ptr/slot_id/native row` 映射；稳定帧直接复用既有列和映射。
5. **验证后再评估 Jolt 开关**：只有 `body_sync_ms` 收敛且真实接触密集工程证明 native step 成为主要瓶颈后，才继续测试 Jolt 特殊优化设置。

### 7.4 待确认问题

- 脏数据由对象范围收集器直接产出，还是由 solver 保留上一帧 manifest 后比较，需要以 Physics World 所有权边界和实际测量决定。
- 结构补丁与全表重建的切换阈值尚未确定，不能仅凭刚体数量静态决定。
- 命令交换区是否在第一阶段并入统一批输入，取决于它是否仍构成可测热点。
- 删除与替换必须同时验证 row generation，防止旧 handle、旧约束或延迟结果访问已释放刚体。
- 稳定表必须保持确定性排序，不能因哈希容器遍历顺序改变模拟和结果发布顺序。

### 7.5 暂定验收线

- 约 1500 个稳定刚体时，`body_sync_ms` 暂定目标为 P50 不高于 `0.5 ms`、P95 不高于 `1.0 ms`；冷注册成本单独计量，不得隐藏进稳定帧数据。
- native trace、刚体/约束/接触结果计数和确定性不得退化。
- py311、py313 的 Jolt backend 测试均通过，完整 rigid 回归不得新增失败。
- 最终使用 `C:\Users\hhh12\Desktop\模拟.blend` 复核 100 帧后的接触密集阶段；若工程节点签名已经陈旧，应先显式迁移或重新编译节点树，不能把兼容失败混入性能结论。

本阶段到此暂停。恢复前不创建稳定表接口、不改 solver 热路径，也不编译覆盖 `.pyd`。
