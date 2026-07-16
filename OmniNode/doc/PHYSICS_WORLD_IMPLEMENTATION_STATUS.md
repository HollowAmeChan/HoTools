# OmniNode 物理世界当前实现状态

更新日期：2026-07-16

本文只记录 Physics World 各 domain **当前成立的边界、主要未完成项和全局优先级**。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver专项状态由各自验收表维护；历史过程由Git保存。

MC2专项入口：完成度见`MC2_ACCEPTANCE_MAP.md`，未完成工作顺序见`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`，源码陷阱与故意差异见`MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 写作边界

- **应该写**：各domain的一页式当前状态、已经成立的系统边界、主要未完成项和Physics World全局优先级。
- **不应该写**：单个solver的能力明细、数值公式、fixture清单、实施步骤、源码差异、调试过程或逐提交历史。
- **内容路由**：公共结构规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；MC2明细分别写验收总表、执行计划和源码差异记录；OmniNode编译/缓存框架写`../ARCHITECTURE.md`；历史只留Git。
- **摘要原则**：domain行只回答“处于什么阶段、主要缺什么、去哪里看”，不在表后追加solver专项补充段落。

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

- `PhysicsWorldCache`统一持有frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams和backend resources。
- solver是`physicsWorld/<domain>/`下可发现模块；私有topology、native context和运行状态只存在于自己的slot。
- solver step发布result/exchange，不直接写Blender；Object、PoseBone和mesh offset由公共writeback应用。
- Cache Delete、runtime cache clear、成功重编译和插件注销必须释放world/slot/backend owner。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理RNA/UI根生命周期
  blender_registry.py        # domain注册journal、依赖和失败回滚
  registry.py                # component/solver发现与装卸
  gn_offset.py               # 共享GN顶点最终offset
  collision/                 # Object/Bone collider共享capability
  spring_vrm/                # VRM SpringBone
  rigid/                     # Rigid/Jolt
  mc2/                       # 一个solver，三种setup
    setups/
      mesh_cloth/
      bone_cloth/
      bone_spring/
  ui/
```

| 稳定Blender路径 | owner |
|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` |
| `Object.hotools_object_collision` | `physicsWorld.collision` |
| `Object.hotools_mesh_collision` | `physicsWorld.mc2.setups.mesh_cloth` |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` |
| `Scene.ho_*`物理UI字段 | `physicsWorld.ui` |

属性schema、PropertyGroup、binding和注册权只存在于Physics World；UI消费capability/resolver。world cache与solver slot不跨帧保存live PropertyGroup。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 主要未完成项/入口 |
|---|---|---|---|
| World core | 可用 | Begin/Commit、scope、slot/resource/result/exchange、channel registry、writeback、dispose、debug snapshot | 跨solver交互仍需真实业务闭环 |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共snapshot与capability | 继续消除solver私有重复resolver |
| 通用力场 | 未来兼容区 | ownership固定归Physics World；solver只消费公共数值快照 | channel/schema/采样布局和首个active vertical slice均未冻结 |
| SpringBone VRM | world-aware vertical slice完成 | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续能力扩展和性能维护 |
| Rigid/Jolt | vertical slice可用，P0门禁闭环 | body/constraint spec、resource、scope、result/writeback、query/event/debug、dispose、soak与golden | Path及剩余高级shape/query |
| MC2 | V1-R替代资格审计 | 单一公开solver step先同步全部active tasks并按substep批量推进；profile+task映射component，per-task slot/context隔离；Bone链组产品拓扑、同Armature多component原子写回、三setup、外部collider、单/跨cloth self、派生self半径、全隐式中间态debug、生产可达性、公共result/writeback与stats已成立；逐帧orientation/Bone pose/Center已由native自产自用；静态raw fingerprint/change分类及Mesh六类派生、Bone共用pose/depth已由C++生产；Mesh Proxy/frame/Baseline/Distance/Bending/Center/Self已全部直接move，生产slot无完整immutable static shadow且static注册复制边界已清零；单一Mesh raw snapshot已供fingerprint/Final Proxy/BasePose拓扑token共享，token已改为固定端序数组流式签名，fallback tangent由native生产，staged records保持ndarray，生产Topology无完整冻结树；P-06b/P-06c已关闭 | 下一步按P-06d迁移Bone static，再按P-06e/P-06f收口变化重建与总体审计；真实状态只看`MC2_ACCEPTANCE_MAP.md` |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

## 当前优先级

1. 保持Rigid/Jolt schema、native ABI、debug renderer与fixture同步。
2. 按`MC2_ACCEPTANCE_MAP.md`先完成MC2替代资格审计；未取得“允许删除”结论前保留旧实现作为语义、性能和依赖审计输入。
   P-06d/P-06e已关闭：Bone生产静态链使用单一raw snapshot、连续数组、6次owner move与compact metadata；Mesh/Bone config分别复制五/六类native static并Center-only重建。topology/geometry/Pin必须全量生产；UV-only全量重签/重建large约20.50ms，仍比旧CPP约657.63ms快约32x。P-06f进行中：已删除不再被solver调用的`InitialState/ParticleBuffer/frame sync`平行host状态链及setup/声明残留，particle history现在只有native context一个owner。
3. 用真实业务场景验证rigid→cloth、body transform→collider等跨solver exchange。
4. 决定Mesh XPBD迁移或删除。

## 公共验收门槛

新增或迁移solver至少满足：

- declaration可查询，公开channel可由debug snapshot观察。
- 连续帧、same-frame、首帧、跳帧/倒放、reset与失败回滚有后台测试。
- Cache Delete、clear、重编译和注销释放native/resource owner。
- solver不直接写bpy；result可被公共writeback、preview或export消费。
- schema/RNA/capability同源，`.blend`非默认值往返不漂移。
- backend、Python binding、节点surface、debug和fixture同步落地。
- 不保留旧路径asset adapter、runtime fallback或shadow solver。

具体字段和生命周期规则以公共contract与代码中的descriptor/declaration registry为准；本文只在domain边界或主要未完成项变化时更新。
