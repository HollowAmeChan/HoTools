# Jolt 刚体写回性能边界

## 目的

本文记录 `PhysicsWorld` 公共刚体 Object 写回的实测边界，以及已经确认的优化取舍。写回属于物理世界公共事务，不能为了 Jolt 单独绕开统一写回协议。产品路线见 [Jolt Physics 产品化路线图](../../../doc/JOLT_PHYSICS_BACKGROUND_ANALYSIS.md)。

## 当前路径

Jolt 的 `get_body_states_numpy()` 在求解器发布阶段返回连续的 position/rotation 列。solver 将本帧列、逻辑 slot 条目和 `obj_ptr -> native row` 映射放入 `world.backend_resources["_rigid_transform_columns"]` 的瞬时缓存，并向 result stream 登记一个 `PhysicsResultBatch`。Collection 写回直接消费该列式快照，不再为了确认目标而预先物化逐 slot result；只有批预检或 native 反算失败时才通过公开结果回退。读取状态、debug 和导出调用 `consume_results()` 时仍获得原有逐 slot 纯数据结果。

Collection 写回分为两条路径：

- dense Collection：比较本帧输出与当前 delta，只对实际变化的列调用 `foreach_set`，只对变化对象调用 `update_tag()`；
- sparse Collection：保留原有三个 `foreach_set` 和逐目标通知。实测 sparse 的 changed-only/update_tag 筛选会变慢，因此不能泛化 dense 优化。

缓存只接受 frame 和 world generation 同时匹配的结果；不匹配时自动回退原有结果字典路径。公开结果协议、reset/dispose 的 touched 语义不变。

Native 反算内核还对常见的全零 rest Euler 和单位旋转增量走快速路径。一般 Euler、Quaternion、Axis-Angle 姿态仍走完整数学路径，native 不访问 Blender RNA。

## Blender 5.2 实测

测试方式：无头 Blender 5.2，合成 10,000 个刚体，零重力无接触，预热 2 帧、采样 5 帧。

| 阶段 | P50 |
| --- | ---: |
| Jolt native step | 约 0.9-1.3 ms |
| 写回（列缓存 + C++ 快速路径） | 约 19.9-24.5 ms |
| 列缓存接入前写回 | 约 36.5 ms |

剩余写回时间主要来自 Python 事务/索引准备和 Blender RNA 批量访问；`update_tag()` 不是 10k 刚体场景的主热点。下一步只有在接触密集工程的可选 timing 明确显示 `native_step_ms` 占主导时，才进入 Jolt solver 开关调优。

## 后续边界

1. 保持公共结果流和统一三种写回模式，不引入 Jolt 专用写回旁路。
2. 近期所有参与模拟和写回的实体仍是 Blender Objects。GN/modifier 结果先在显式创作操作中应用、Realize 并拆分为 Objects，随后复用本路径。
3. 下一步先建立稳定 Object body table：manifest revision 不变时复用 slot/object/native row 映射，稳定帧只批量提交运动学变换、热参数和命令。
4. 若需要继续降低 Blender 侧开销，应优先减少 Python 事务对象构造和重复索引；不要重新启用已验证变慢的 sparse 通知筛选。
5. 任何进一步优化都必须同时验证跳帧、reset、dispose、scope 重建和动态目标删除后的 delta 清理。
6. 直接 GN runtime instance 写回只有在 Object/depsgraph 被证明为剩余主瓶颈，并另行冻结 stable instance identity、约束/命令/bake 和公共 writeback 合同后才立项；当前文档不定义该路径。
