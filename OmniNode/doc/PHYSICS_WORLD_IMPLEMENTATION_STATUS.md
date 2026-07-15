# OmniNode 物理世界当前实现状态

本文记录统一物理世界**当前已经成立的边界、尚未完成的能力和退出门槛**，不记录逐次提交、日期、Phase 流水或临时测试数字。历史过程由 Git 保存。

架构判断以 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 为唯一权威；OmniNode 编译、执行、缓存和懒求值机制见 `../ARCHITECTURE.md`。solver 自己的功能矩阵、backend 能力和测试说明应放在各 domain 的 `docs/` 或测试目录中。

MC2 的当前状态、Host/Native 契约和实施顺序见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`；固定源码中的顺序敏感行为、数值陷阱和 oracle 规则见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

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
| Rigid/Jolt | vertical slice 可用，P0 release 门禁已闭环 | body/constraint spec、约束引用拓扑、Jolt resource、scope hook、result/writeback、query/event/debug、dispose；S1/S2/S3 60 fixture、py311/py313 自动容差差分、两类 overflow、双 ABI 10,000 帧 soak、冻结性能门禁、首版 approved golden | Path、剩余高级 shape/query 的 binding、native、debug 和 fixture 同步 |
| MC2 | Mesh/Bone native collider + public result | 单一solver/三setup、staged native context、Point/Edge、BoneSpring soft-sphere、self primitive/grid、EE/PT half contact、固定4轮fixed-point solve/sum及跨帧分片Intersect反馈、source-aligned constraint/post顺序、Mesh GN与Bone PoseBone writeback均已闭环；详细数值域见MC2执行计划 | self collision sync/inter-cloth、Bone negative scale、Bone triangle output、wind、stats |
| Mesh XPBD | 旧路径 | 可作为简单布料参考 | 是否迁移或删除需单独决策 |

MC2 状态补充：Bone Line与强制Line的BoneSpring使用稳定bone identity发布parent-local`matrix_basis` plan；Bone task新增显式碰撞组mask。BoneSpring固定N2 override、Sphere-only快照与soft limit进入同一native slot路径。Bone负/零scale与world shear仍在snapshot前拒绝且不污染旧slot；单cloth self primitive/contact/solve/Intersect已闭环，sync/inter-cloth仍未完成。

MC2 Tether补充：V0已按源码顺序接入复用现有root/step-basic数据的native kernel；Python slot owner现按固定MC2调度默认启用，raw C gate仅用于隔离不同scope的oracle fixture。py313公式/顺序回归与Blender5.1新建、重建、真实子步solve count通过；独立Tier A Tether substep fixture仍待补齐。

MC2 Angle补充：V0已按源码顺序在首次Distance后、Bending前执行Restoration/Limit，复用现有baseline与step-basic数据并消费N2 use/curve/float槽和Center gravity-dot。native kernel已修正已转换Restoration stiffness重复乘0.2的问题；py313独立kernel/V0对拍及Blender5.1 Mesh/Bone生产子步通过。独立Tier A Angle substep fixture仍待补齐。

MC2 Motion补充：V0已按源码顺序在第二次Distance后、post前执行Max Distance/Backstop，并新增独立animated base子步缓冲，避免误用baseline step-basic。N2 use/curve/float/normal-axis、InvalidMotion与depth²语义已接入，MaxDistance=0显式锁定边界通过；py313 kernel/V0及Blender5.1 Fixed Mesh三子步通过。独立Tier A Motion substep fixture仍待补齐。

MC2 Collider补充：共享World current/previous snapshot覆盖primitive、组mask、自身排除与moving pose；Mesh和Bone production均按非same-frame原子上传。Point/Edge与BoneSpring路径不变。Self Collision首substep已完成primitive/grid、EE/PT候选与old-pose narrowphase，contact half ABI和后续substep更新已落地；每个substep固定4轮SolverContact/Sum使用int32 fixed-point聚合并实际投影粒子。跨帧Intersect按`frame % 2`从上一帧grid建立Edge–Triangle record，只在整帧final substep后复测当前位置并把Edge particle flag反馈给下一帧primitive。py313三帧时序与Blender5.1单/三子步生产链均已通过；当前FullMesh限制转为仅支持单cloth self域，sync/inter-cloth仍未接入。

## 统一 MC2 决策

MC2 只有一个 solver identity：`mc2`。

- `MeshCloth`、`BoneCloth`、`BoneSpring` 是三种 setup，不是三个 solver。
- setup adapter 负责 Blender 输入、拓扑构建和结果目标差异；step、cache、backend resource、碰撞快照和结果生命周期由 MC2 solver 共享。
- 新路径只提供一套 native context schema/implementation，每个 active slot持有自己的 context；不公开 Python/C++ backend选择，旧 package、旧资产和旧 solver parity不属于实现或验收范围。
- 当前新MC2 step已推进Mesh/Bone外部collider数值路径：Mesh从BasePose构建N3，Bone从PoseBone frame构建N3；两者消费共享World snapshot并分别发布GN或bone transform结果，不调用旧MC2 package。
- `gn_attribute` 已登记为 active shared result channel；`mc2_stats`与`bone_transform`仍只登记为 planned channel，不虚报 active 输出。
- MeshCloth 最终只发布对象局部顶点 offset；多阶段或多 solver 分量先在 `world.exchange` 归并，不创建 solver 私有 GN 属性。
- MeshCloth 的 Blender adapter 永久使用“双对象 + 常驻 GN”：BasePose 只读对象保留骨架/Shape Key 基础变形并移除物理 output，源对象末端 GN 只接收同 vertex identity 的 object-local offset。BlendShape 写回、单对象切换/移动 GN、同一对象读取前后两个 evaluated 阶段均已因 Blender 性能/求值限制排除。
- 新路径只验证新 schema、slot、native context、result stream 与共享 writeback；旧路径可以独立清理，不设置迁移/兼容门槛。

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
2. MC2 按 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md` 为Bone Line private candidate设计stable identity的parent-local public envelope、批次失败回滚与统一PoseBone writeback；Automatic/Sequential须先解决零UV triangle basis退化。
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
- 不为旧路径保留资产 adapter、兼容层或 shadow solver。

当前状态以代码中的 solver/component descriptor、declaration registry 和自动化测试为准；本文只在边界或未完成项发生变化时更新。
