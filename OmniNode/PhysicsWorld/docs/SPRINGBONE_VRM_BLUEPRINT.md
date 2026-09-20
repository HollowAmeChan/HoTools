# SpringBone VRM 实现蓝本

本文是 OmniNode `spring_vrm` domain 的稳定维护入口，说明当前已经运行的结构、所有权和扩展约束。它不记录迁移阶段、逐次修复和临时性能数字。

相关文档：

- 物理世界公共架构：`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
- 各 domain 当前完成度：`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`

代码事实源优先级：`spring_vrm/declaration.py`、solver/module descriptor、自动化测试、本文。代码与本文冲突时，应先修正 declaration 或实现，再同步本文。

## 当前定位

SpringBone VRM 是统一物理世界中第一条完成的 PoseBone solver vertical slice。当前状态是：

- 产品运行链路已完成并进入维护态。
- 只保留 C++ native context 实现，没有 Python solver、旧数组 ABI 或 inline writeback fallback。
- 旧节点图不提供自动迁移；稳定的 `Bone.hotools_collision` 数据路径继续保留。
- 功能扩展和性能维护可以继续进行，但不能恢复平行 backend 或绕过统一物理世界。
- py311/py313 使用同一套 context-only Native 直接测试，覆盖完整 collider、group/mask、错误输入和释放生命周期。

SpringBone 负责 VRM 风格的骨链尾端动力学。它不负责通用刚体、布料、关键帧烘焙，也不拥有共享 Bone/Object collision schema。

## 一句话数据流

```text
VRM骨链属性 -> VRM骨链任务 --------------------┐
                                                v
Physics World Begin -> [骨骼碰撞覆写属性 / 注册] -> SpringBone VRM模拟步
  -> bone_transform / spring_vrm_stats
  -> Physics Writeback
  -> Physics World Commit
```

骨链任务是 solver 的侧路输入，不读写 world。实际 world 必须沿同一个 `PhysicsWorldCache` owner 线性传递，不能分叉写入后再合并。

运行时内部链路：

```text
SpringBone VRM模拟步.vrm_chain_tasks
  -> SpringVRMChainSpec / SpringVRMSolverSpec
  -> world.solver_slots["spring_vrm:..."]
  -> SpringVRMNativeContext
  -> hotools_native spring_vrm context API
  -> bone_transform_batch envelope
  -> physicsWorld.writeback
  -> PoseBone.matrix_basis
```

## 节点职责

| 节点 | 责任 | 明确不做 |
|---|---|---|
| `VRM骨链属性` | 从 Bone socket 生成规范化骨链参数 | 不写 world，不建 slot，不推进时间 |
| `VRM骨链任务` | 把一条或多条骨链属性整理成 solver 任务列表 | 不输入 world，不注册隐式对象，不建 slot |
| `骨骼碰撞覆写属性` | 生成共享 BoneCollisionProfile 的局部覆写 payload | 不修改 `Bone.hotools_collision` |
| `骨骼碰撞覆写注册` | 写入 `bone_collision.override` 隐式对象 | 不拥有 collision capability |
| `SpringBone VRM模拟步` | 直接消费全部骨链任务，维护 slot/context、推进 native、发布结果 | 不扫描整个 scene，不直接写 PoseBone |
| `SpringBone VRM可视化调试` | 请求并显示 backend 真实快照 | 不重新推导一套模拟状态 |

Solver 节点的 `substeps` 是 SpringBone 权威子步数，范围为 1-16。

## 模块所有权

| 文件 | 所有权 |
|---|---|
| `spring_vrm/names.py` | solver id、slot kind、result/debug 名称及碰撞覆写 tag |
| `spring_vrm/declaration.py` | 可查询的 solver 公共契约和已删除 surface |
| `spring_vrm/capabilities.py` | SpringBone 更新频率；共享碰撞能力只兼容重导出 |
| `spring_vrm/specs.py` | 稳定 chain/solver spec、slot identity、拓扑冲突校验 |
| `spring_vrm/implicit_objects.py` | 骨链属性构建；碰撞覆写的注册、stable id、signature |
| `spring_vrm/bone_collision.py` | BoneCollisionProfile 三层 resolver |
| `spring_vrm/solver.py` | slot 注册、step 调度、same-frame、prune、dispose |
| `spring_vrm/native.py` | Blender 帧输入打包、context 生命周期、碰撞数组、native step |
| `spring_vrm/results.py` | `bone_transform` 与 `spring_vrm_stats` 结果辅助函数 |
| `spring_vrm/debug.py` / `debug_draw.py` | slot/native 摘要和 viewport 快照 |
| `physicsWorld/writeback.py` | 批量写入 `PoseBone.matrix_basis` 及清理 |
| `physicsWorld/collision/` | `Bone.hotools_collision`、Object/Bone collision capability 和 RNA |

公共 `world.py`、UI 和其它 solver 不得读取 SpringBone native handle 或私有数组。

## Solver 身份与 slot

固定身份：

```text
solver_id: spring_vrm
slot_kind: spring_vrm
optional override tag: bone_collision.override
shared result: bone_transform
private stats result: spring_vrm_stats
```

骨链 spec 包含 armature object/data pointer、root、完整骨名序列、启用状态、刚度、阻尼和重力。每个 solver spec 按 armature 聚合多条不重叠骨链。

Slot id 由 `slot_kind + armature_ptr + armature_data_ptr + spec_hash` 组成。`spec_hash` 覆盖 backend、root、骨名序列和启用状态。刚度、阻尼、重力和 `substeps` 不进入 slot identity，可以在不重建 slot 的情况下更新。Slot id 用于区分运行期拓扑身份，不是持久资产 id。

同一 armature 内：

- 重复 root 明确报错。
- 两条链包含同一 simulated bone 明确报错。
- 输入 root 是不参与模拟的中控骨；`bones[1:]` 全部是 simulated bones。
- 中控骨可以是多串骨链的共同父级；其下分叉节点仍只是一根模拟骨，所有分支共享该父级的解算结果。
- simulated bones 只有 `Bone.hotools_collision.pin` 或对应覆写能够固定。
- 多条不重叠链共享 armature slot，各自持有 native chain context。

Slot 私有状态只包含 spec、`frame_state`、native contexts、`writeback_plan`、debug 请求和诊断。每帧结果不把 slot 当作跨 solver 总线。

## 任务与隐式对象契约

### VRM 骨链任务

`VRM骨链任务` 输出普通任务列表，直接进入 `SpringBone VRM模拟步.vrm_chain_tasks`。任务不写入 `world.implicit_objects`，也没有 registry version 或 stable id；spec/slot identity 仍由 armature、root、骨名序列和启用状态确定。

同一个模拟步一次处理输入中的全部 armature 和 chain。空任务输入表示当前没有 SpringBone 任务：solver 发布零统计、清理旧 SpringBone slot 并释放对应 native context。未连接的 OmniNode list socket 只在模拟步节点内部把精确的 `[0.0]` 哨兵解释为空列表。

### 骨骼碰撞覆写

`bone_collision.override` 是共享 collision capability 的运行时覆写层，不是 SpringBone 私有 schema。Stable id 由 armature object/data pointer 和 bone name 组成。

覆写只影响当前 world，不回写 Blender 数据。未显式提供的字段继续向下一层 fallback。

## BoneCollisionProfile

所有消费端使用同一解析优先级：

```text
1. world.implicit_objects["bone_collision.override"]
2. Bone.hotools_collision
3. physicsWorld.collision capability 默认值
```

| 字段 | SpringBone 消费方式 |
|---|---|
| `pin` | context 静态 pinned 数组；restart 后生效 |
| `collision_type` | `NONE` 禁用；`SPHERE/CAPSULE` 生成骨碰撞体 |
| `radius` | 模拟骨 hit radius 和外部骨碰撞体半径 |
| `length` | capsule 线段长度 |
| `offset` | 骨碰撞体局部偏移 |
| `primary_collision_group` | 外部骨碰撞体所属组 |
| `collided_by_groups` | 模拟骨接受碰撞的 mask |

Solver 不允许绕开 resolver 直接把 `Bone.hotools_collision` 当作唯一事实源。

## 更新频率

| 数据 | 策略 |
|---|---|
| frame、dt、姿态 head/tail、armature transform | `every_frame` |
| root、骨名序列、父级索引、连接关系 | topology dirty，重建 slot/context |
| 刚度、阻尼、重力 | task input dirty，下一次 step 刷新 |
| `pin`、初始轴向/旋转/长度 | `restart_only` |
| hit radius、mask、骨碰撞体字段 | capability/override/collider cache key 变化后刷新 |
| world Object/Bone colliders | World Begin 每帧构建 snapshot |
| native collider arrays | slot 内按 snapshot、chain、override revision 懒缓存 |
| writeback plan | topology 建立时分配，帧/generation 元数据每帧更新，缓冲区跨帧复用 |

修改 `pin` 不是热切换；需要触发 restart。新增字段时必须在 `declaration.py` 和 `capabilities.py` 中给出唯一、可测试的更新策略，不能只写“实时”。

## Native context

唯一公开计算链路：

```text
spring_vrm_create_context
free_spring_vrm_context
spring_vrm_update_dynamic
spring_vrm_reset_state
spring_vrm_step
spring_vrm_read_results
spring_vrm_read_debug    # 按请求
```

每条 chain 对应一个 `SpringVRMNativeContext`。拓扑建立时捕获静态数组并创建 C++ handle；每帧更新姿态、碰撞数组和参数；restart 在动态输入同步后、step 前重置 Verlet 状态。

Python 只负责 Blender/spec 适配、连续 numpy buffer、slot 生命周期、result 发布和 debug。数值算法不能在 Python 再实现一份。

Context 必须由 slot dispose 释放。以下路径都必须最终触发释放：

- active spec 中移除骨链或骨架；
- topology/spec identity 改变后 prune stale slot；
- world generation 替换；
- Cache Delete、runtime cache clear、不兼容成功重编译；
- addon 注销。

Dispose 必须幂等；debug snapshot 只能暴露计数和纯数据，不暴露 native handle。

## 时间语义

- 正常新帧：更新动态输入并推进 native。
- same-frame：不推进时间，重发已有 writeback plan。
- `dt <= 0`：视为暂停，不推进时间，重发结果。
- restart：先上传当前动态姿态、重置 current/previous tails，再发布当前 pose；该帧不继续推进 Verlet。
- 跳帧、倒放、scope/topology 变化由公共 frame/restart 语义驱动，SpringBone 不维护另一套时间判断。

## 碰撞输入

公共碰撞体只来自 `world.collider_snapshot`。SpringBone 支持 snapshot 中的 sphere、capsule、plane 和 box，并按 group/mask 过滤。

骨骼碰撞体通过 BoneCollisionProfile resolver 覆写 snapshot 中的 Bone entry；override 也可以从显式 `NONE` 增加碰撞体，或改为 `NONE` 删除碰撞体。同一 chain 自身的骨碰撞体被排除，避免自碰撞重复输入。

迁移前的“直接扫描 scene 可见对象”语义已删除。Collider 是否进入模拟由 Physics Object Scope 和 World Begin snapshot 决定。

## Result 与写回

| 通道 | 内容 | 消费者 |
|---|---|---|
| `bone_transform` | 每 slot 一个 `bone_transform_batch` envelope | 统一 Physics Writeback、debug、未来 export/bake |
| `spring_vrm_stats` | slot/chain/bone/collider 数、耗时、状态、错误、context 统计 | debug 和诊断 |

正常播放使用 `writeback_plan` 中跨帧复用的 PoseBone 引用、矩阵和 foreach buffer。逐骨 result 只在兼容读取、debug 或导出时按需展开。

SpringBone solver 不直接写 `PoseBone.matrix_basis`。`physicsWorld.writeback` 按 armature 批量应用结果，并在 world dispose/reset 清理由物理系统触碰过的姿态。

关键帧烘焙属于未来统一 writeback bake 节点，不属于 SpringBone 私有实现或当前验收阻塞项。

## Debug 与性能边界

Debug draw 使用 slot、native debug readback 和真实 result stream。没有请求时不得每帧执行 native debug readback；一次性请求在后续推进帧消费并清除，continuous 模式才允许持续采样。

稳定性和性能基线由以下 benchmark 脚本维护：

- `spring_vrm/test/benchmark_blender_spring_vrm.py`
- `spring_vrm/test/benchmark_blender_spring_vrm_scale_debug.py`

蓝本只保留不随机器变化的门槛：资源计数不能随帧数增长；正常播放不承担逐骨 dict 展开和无请求 debug readback；性能回退必须用独立 Blender 进程和固定 warmup/测量矩阵复核。

## 验收基线

SpringBone 于 2026-07-11 完成迁移和验收收口。当前没有发布阻断项。

| 层级 | 最终结果 | 覆盖 |
|---|---:|---|
| py311 Native context-only | `17/17` | 旧入口缺失、SPHERE/CAPSULE/PLANE/BOX、group/mask、错误 buffer、显式/GC 释放、零长度 |
| py313 Native context-only | `17/17` | 与 py311 同一矩阵 |
| Blender 4.5 集成 | `37/37` | 任务直连、空任务清理、slot、same-frame、暂停/跳帧、碰撞覆写、预设、debug、writeback、cache dispose |
| 稳定性 | 10,000 帧通过 | slot/context/handle/static/dynamic/result buffer 身份与数量不增长 |

删除前旧/context 数值对拍逐帧误差门槛为 `<= 2e-5`。删除后的性能门槛和最终实测：

| 场景 | 门槛 | 最终结果 |
|---|---:|---:|
| 128 骨、无 collider，新/旧总耗时 | `<= 1.15x` | `1.079x-1.099x` |
| 32 骨、32 collider，P50 新/旧 | `<= 1.25x` | `1.124x` |
| 128 骨、32 collider，P50 新/旧 | `<= 1.25x` | `1.103x` |

这些数字只用于防止迁移架构回退，不作为跨机器绝对耗时目标。重新验收时必须重建 py311/py313 native 模块，运行同一 Native 矩阵和 Blender 集成套件；性能测试使用上面的两个 benchmark 脚本。

## 已删除和不兼容边界

以下 surface 不得恢复：

- `springBoneVRMChainSetting`、`springBoneVRM`、`springBoneVRM_CPP`、`springBoneBase`
- `_SpringBoneVRM`、`_SpringBoneVRMCppBackend`、`_run_spring_bone_vrm_node`
- `solve_spring_bone_vrm_cpp` 35 参数 binding 和公开 `SpringBoneVrmChainView`
- solver 私有 cache/reset 节点和 inline PoseBone writeback
- `physicsSpringVRMChainRegister`、`spring_vrm.chain` 隐式对象路径

旧节点图出现 missing node 是已接受的产品边界；不增加别名、图迁移器或 shadow pipeline。

## 扩展检查表

修改 SpringBone 时按顺序检查：

1. 新输入属于直接 task、implicit object、world/frame input、slot 私有状态还是 exchange，所有权是否唯一。
2. `declaration.py` 的 consumes、produces、dirty key、update policy 是否同步。
3. 参数是否有明确的 every-frame、dirty、topology 或 restart 语义。
4. native binding、Python packer、debug readback 和 fixture 是否作为一个交付单元更新。
5. 是否仍只存在一套 C++ 数值实现。
6. 是否仍通过 result stream 和统一 writeback 输出。
7. stale slot、Cache Delete、不兼容重编译和 addon 注销是否释放新增资源；兼容重编译是否保留owner。
8. same-frame、暂停、倒放、restart 和错误输入是否有回归。
9. 多 armature、多 chain、重复 root/重叠骨和非均匀/镜像缩放是否未退化。
10. 更新蓝本中的稳定契约和验收基线；逐次修复过程只由 Git 保存。
