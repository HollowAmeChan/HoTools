# OmniNode 物理世界当前实现状态

本文只记录各 domain 当前成立的边界、主要缺口和全局优先级。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver 的产品、算法、测试和后端设计由各自蓝本维护；历史过程只留 Git。

## 当前系统边界

```text
Cache Read
  -> Physics Object Scope
  -> Physics World Begin
  -> implicit object / explicit product build
  -> solver step(s)
  -> result stream / exchange
  -> Physics Writeback
  -> Physics Bake
  -> Physics World Commit
  -> Cache Write
```

- `PhysicsWorldCache` 统一持有 frame context、scope、snapshot、implicit object registry、solver slots、exchange、result streams 和 backend resources。
- Solver 是 `PhysicsWorld/<domain>/` 下的可发现模块；私有 topology、backend context 和跨帧状态只存在于自己的 slot/resource owner。
- Solver step 发布 result/exchange，不直接写 Blender；Object、PoseBone 和 mesh offset 由公共 writeback 应用。
- Cache Delete、runtime cache clear、不兼容重编译、load/undo 和插件注销必须沿公共 dispose 路径释放 world/slot/backend owner。
- 显式产品和 implicit object 是两种装配协议。一个 domain 必须先在自己的蓝本中冻结唯一 canonical 输入，再由不同 authoring adapter 映射过去，solver 不分别解析多套业务字段。

## 当前目录与所有权

```text
PhysicsWorld/
  blender.py                 # 物理 RNA/UI 根生命周期
  blender_registry.py        # domain 注册、依赖与失败回滚
  registry.py                # component/solver 发现与装卸
  world_time.py              # 公共秒数与采样时间入口
  bake/                      # 通用 Bake
  collision/                 # Object/Bone 公共碰撞能力
  field/                     # Field/Volume authoring、snapshot、native runtime
  simple_cloth/              # Mesh solver 共用对象/BasePose/GN 输出 owner
  spring_vrm/                # VRM SpringBone
  rigid/                     # Rigid/Jolt
  mc2/                       # MeshCloth / BoneCloth / BoneSpring
  xpbd/                      # Mesh XPBD / Bone XPBD 家族
  ui/
```

| 稳定 Blender 路径 | owner |
|---|---|
| `Bone.hotools_collision` | `PhysicsWorld.collision` |
| `Object.hotools_object_collision` | `PhysicsWorld.collision` |
| `Object.hotools_mesh_collision` | `PhysicsWorld.simple_cloth` |
| `Object.hotools_field` | `PhysicsWorld.field` |
| `Object.hotools_rigid_body` | `PhysicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `PhysicsWorld.rigid` |
| `Object.hotools_rigid_fracture` | `PhysicsWorld.rigid`，计划中 |
| `Object.hotools_rigid_fracture_piece` | `PhysicsWorld.rigid`，计划中 |
| `Scene.ho_*` 物理 UI 字段 | `PhysicsWorld.ui` |

Property schema、PropertyGroup、binding 和注册权只存在于 Physics World。World cache 与 solver slot 不跨帧保存 live PropertyGroup。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 当前缺口/入口 |
|---|---|---|---|
| World core | 可用 | 公共时间、Begin/Commit、scope、slot/resource/result/exchange、writeback、dispose、debug snapshot | seek/cache sample time 恢复；跨 solver owner/交互仲裁 |
| Physics Bake | Bone + PC2 Mesh + Clear vertical slice 可用 | 公共 Bake 节点、Action/PC2、manifest、播放和清理 | `PHYSICS_BAKE_NODE_BLUEPRINT.md` |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共 snapshot/capability | 继续消除 solver 私有 resolver |
| Simple Cloth | 可用 | 公共 Object/BasePose/GN output owner；solver step 不创建 Blender 资源 | 新 Mesh solver 复用该边界，不复制资源生命周期 |
| Field | authoring、静态预览、native runtime、MC2 CPU 消费可用 | 标准 evaluator、显式时间/作用域/participation、staged lifecycle | Volume 权重、seek/cache 时间、未来 consumer；见 `PHYSICS_FIELD_VOLUME_BLUEPRINT.md` |
| SpringBone VRM | world-aware vertical slice 可用 | 隐式骨链、native context、碰撞、result、PoseBone writeback、debug、dispose | 维护与按需能力扩展 |
| Rigid/Jolt | 可用基线，破碎资产未实现 | 7 种基础 shape、11 种约束、Object scope、列式结果/Collection 批写回、激活命令、contact/sensor/query/debug、双 ABI fixture/golden/soak | 当前缺破碎 Source/Piece 属性、GN 产物事务、linked Collection resolver 和初始 `DontActivate`；第一出口是球撞墙局部破碎 `.blend`；见 `JOLT_PHYSICS_BACKGROUND_ANALYSIS.md` 与 `PhysicsWorld/rigid/docs/RIGID_FRACTURE_BLUEPRINT.md` |
| MC2 | 三 setup CPU 产品可用，Field 消费 active | 共享 Domain/Field runtime、结果事务、Mesh/Bone 写回；CPU 为 reference | 独立 GPU backend 与低层 mutation rollback 仍按专项蓝本推进 |
| Mesh XPBD | XPBD 家族内生产链可用 | Simple Cloth authoring、共享 family step/native/collision/debug、GN result/writeback | 最终 ABI/能力/性能矩阵冻结；见 `MESH_XPBD_BLUEPRINT.md` |
| Bone XPBD | experimental vertical slice 可用 | 显式端点、Pin、独立 slot/context、Pose writeback | 数值探针、约束/scale/Field 和公共 Bone owner；见 `BONE_XPBD_BLUEPRINT.md` |

## 当前优先级

1. Rigid/Jolt 先补普通刚体的初始 `DontActivate`，再实现破碎 Source/Piece 属性、默认 GN、显式刷新、manifest、原子替换和 cache 失效。
2. 实现 rigid fracture resolver：Source 永不与 Piece 双注册，只展开 linked Collection 中 owner/revision 匹配的普通 Mesh Objects，并复用现有 Jolt/result/writeback。
3. 交付球撞墙局部破碎 `.blend` 和后台 oracle；碰撞前 Piece 静止、命中后局部激活、锚定外圈不动、reset 可重放。
4. 在 Object 模型内继续收敛稳定 body table、批量注册/热同步和公共 Collection 写回；性能同时覆盖 native、body sync、pipeline、writeback 和 depsgraph。
5. 随后规划 `RigidBodyPropertiesV1`、业务 Socket、局部传播、可断约束和世界 Contact/CCD/Sleep/Cache 设置。近期不增加 Path、Vehicle、Soft Body 或 Ragdoll。
6. `FULL_MESH_STATIC`、作者 mesh 的 `CONVEX_HULL` 和 GN runtime instance 模拟均在第一条 Object 破碎链通过后独立立项。
7. 其它成熟 domain 以回归、生命周期和公共 owner 合同维护为主，不复制 Jolt 的 Object authoring 设施。

## 公共验收门槛

- 架构：依赖方向、私有边界、注册根、结果通道、backend owner 和 native binding 无未解释违规。
- 生命周期：创建、热更新、staged replacement、失败回滚、dispose、undo/load 和 unregister 不泄漏资源。
- 事务：多个 request/target 在 mutation 前完整验证，失败时零部分写回或部分场景资产提交。
- Debug：关闭时无额外 record/readback；开启时只观察真实 production pass。
- Native：CPU-only 构建和加载不依赖可选 GPU runtime；双 ABI 按 domain 门槛验证。
- Blender：隔离默认备份模块，确认加载当前工作树源码和对应 native 产物。

## 文档维护

本文的 domain 行只回答“当前是什么状态、缺什么、去哪里看”。单个 solver 的字段表、fixture 数量、实施批次、性能数字、删除清单和提交结果不得追加到本文。
