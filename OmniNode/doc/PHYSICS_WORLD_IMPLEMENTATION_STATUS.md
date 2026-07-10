# OmniNode 物理世界当前实现状态

本文记录统一物理世界**当前已经成立的边界、尚未完成的能力和退出门槛**，不记录逐次提交、日期、Phase 流水或临时测试数字。历史过程由 Git 保存。

架构判断以 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 为唯一权威；OmniNode 编译、执行、缓存和懒求值机制见 `../ARCHITECTURE.md`。solver 自己的功能矩阵、backend 能力和测试说明应放在各 domain 的 `docs/` 或测试目录中。

## 当前系统边界

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> implicit object / spec build
  -> solver step(s)
  -> result stream / exchange
  -> Physics Writeback
  -> Physics World Commit
  -> Cache Write
```

- `PhysicsWorldCache` 统一持有 frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams 和 backend resources。
- solver 是 `physicsWorld/<domain>/` 下可发现的模块，descriptor 声明 nodes、capabilities、declaration、debug draw modes、property registration 和 scope hooks。
- solver 私有 topology、native context、数组和运行状态只存在于自己的 slot；其它 solver、UI 和 debug 不读取私有 handle。
- solver step 发布 result/exchange，不直接写 Blender；Object、PoseBone 和 mesh delta 的实际写入归统一 writeback。
- Cache Delete、runtime cache clear、成功重编译和插件注销都必须释放 world/slot/backend owner。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理 RNA/UI 唯一根生命周期
  blender_registry.py        # domain 注册 journal、依赖和失败回滚
  registry.py                # component/solver 发现与装卸
  gn_offset.py               # 单一共享 GN 顶点最终 offset 输出
  collision/                 # Object/Bone collider 共享 capability
  spring_vrm/                # VRM SpringBone solver
  rigid/                     # Rigid/Jolt solver
  mc2/                       # 一个 MC2 solver，三种 setup
    setups/
      mesh_cloth/            # MeshCollision RNA、BasePose、mesh delta adapter
      bone_cloth/            # 骨链输入与通用 bone_transform 写回契约
      bone_spring/           # 骨链输入与通用 bone_transform 写回契约
  ui/                        # Scene UI state、panel、operator、preview
```

稳定 Blender 存储路径：

| 路径 | owner |
|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` |
| `Object.hotools_object_collision` | `physicsWorld.collision` |
| `Object.hotools_mesh_collision` | `physicsWorld.mc2.setups.mesh_cloth` |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` |
| `Scene.ho_*` 物理 UI 字段 | `physicsWorld.ui` |

`PhysicsTools` 已删除。属性 schema、PropertyGroup class、binding 和注册权全部位于 Physics World；UI 只消费 capability/resolver。`PhysicsWorldCache` 和 solver slot 不跨帧保存 live `PropertyGroup`。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 主要未完成项 |
|---|---|---|---|
| World core | 可用 | Begin/Commit、scope、collider snapshot、slot/resource/result/exchange、独占/共享/planned channel registry、共享 GN 最终 offset 写回、dispose、debug snapshot | 跨 solver 交互仍需真实业务闭环 |
| Collision | 可用 | Object/Bone schema、RNA、group mask、snapshot、共享 capability | 继续消除 solver 私有重复 resolver |
| SpringBone VRM | 已完成 world-aware vertical slice | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续只做能力扩展和性能维护 |
| Rigid/Jolt | vertical slice 可用，功能扩展中 | body/constraint spec、Jolt resource、scope hook、result/writeback、query/event/debug、dispose | 高级约束/shape/query 的 binding、native、debug 和 fixture 同步 |
| MC2 | 统一框架已建立 | 唯一 solver id；三种 setup adapter 契约；稳定 task id/source signature；共享 GN 最终 offset/bone writeback channel；MeshCloth Blender adapter 已归位 | 新 world-aware kernel/slot/result 尚未接入；完整后端迁移暂缓 |
| 旧 MC2 MeshCloth/BoneCloth | 当前仍可运行 | 现有数值核心与 scene parity 作为迁移依据 | 迁入统一 MC2 后删除旧 package，不做长期桥接 |
| MC2 BoneSpring | 未实现 | setup identity 和任务框架已声明 | topology adapter、参数 spec、native step、PoseBone result/writeback |
| Mesh XPBD | 旧路径 | 可作为简单布料参考 | 是否迁移或删除需单独决策 |

## 统一 MC2 决策

MC2 只有一个 solver identity：`mc2`。

- `MeshCloth`、`BoneCloth`、`BoneSpring` 是三种 setup，不是三个 solver。
- setup adapter 负责 Blender 输入、拓扑构建和结果目标差异；step、cache、backend resource、碰撞快照和结果生命周期由 MC2 solver 共享。
- 新路径只提供一个共享 native context，不公开 Python/C++ backend 选择；旧 package 中的两套实现仅作为迁移与 parity 参考。
- 当前新 MC2 step 是明确的 framework no-op：不创建 slot、不发布结果、不调用旧 MC2 package。
- no-op 阶段的 `mc2_stats`、`gn_attribute`、`bone_transform` 只登记为 planned channel，不虚报 active 输出。
- MeshCloth 最终只发布对象局部顶点 offset；多阶段或多 solver 分量先在 `world.exchange` 归并，不创建 solver 私有 GN 属性。
- 在新路径完成 parity、same-frame、跳帧/reset、dispose 和写回验收前，旧 MeshCloth/BoneCloth package 继续承担当前运行实现。

## 固定契约

### Solver declaration

每个 solver 必须由 registry 可查询，并声明：

- `solver_id` / `slot_kind`
- `consumes` / `produces`
- `persistent_state` / `dirty_keys`
- `same_frame_policy` / `update_policy`
- `implicit_objects` / `capabilities`
- `writeback` / `export`

`writeback.solver_inline_writeback=False` 是硬约束。

### 属性与注册

- capability/schema 是字段、默认值、范围、enum、RNA metadata 和 resolver 的单一事实源。
- 同一 `(bpy owner, property name)` 只能有一个 binding。
- `physicsWorld.blender` 始终随 HoTools 注册；物理属性和 UI 不依赖 OmniNode 功能开关。
- component/solver 按依赖注册、逆序注销；domain 失败只回滚自己的 journal。
- 稳定 RNA 路径的改名必须是独立、版本化的数据迁移。

### Runtime

- same-frame 默认不重复推进模拟时间；是否只 sync 或重发结果由 solver declaration 明确。
- 跳帧、倒放、reset、scope/topology 变化的重建语义必须可测试。
- 持久 authoring 对象进入 `world.implicit_objects`；帧级跨 solver 数据进入 `world.exchange`；写回进入 result stream。
- debug 只展示 backend 实际消费的 spec 和实际发布的 state，不重新推导另一套物理结果。

## 当前优先级

1. 保持 Rigid/Jolt schema、native ABI、专用 debug renderer 和 fixture 同步，避免能力只落一层。
2. MC2 先完成一个最窄 world-aware vertical slice，再迁移 MeshCloth/BoneCloth kernel；BoneSpring 在共享核心稳定后补齐。
3. 用真实业务场景验证 rigid → cloth、body transform → collider 或其它跨 solver exchange。
4. 决定 Mesh XPBD 的迁移或删除，不维持无期限的第二套布料语义。

## 验收门槛

新增或迁移 solver 至少满足：

- declaration 校验通过，公开通道可被 debug snapshot 观察。
- 连续帧、same-frame、首帧、跳帧/倒放、reset 和失败回滚有后台测试。
- Cache Delete、clear runtime cache、重编译和插件注销释放 native/resource owner。
- solver 不直接写 bpy；result 可被统一 writeback、preview 或 export 消费。
- schema/RNA/capability 同源，`.blend` 非默认值往返不漂移。
- backend 能力、Python binding、节点 surface、debug 和 fixture 同步落地。
- 新路径通过验收后删除旧路径，不保留永久 adapter 或 shadow solver。

当前状态以代码中的 solver/component descriptor、declaration registry 和自动化测试为准；本文只在边界或未完成项发生变化时更新。
