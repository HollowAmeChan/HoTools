# OmniNode 物理世界当前实现状态

本文只记录 Physics World 各 domain 当前成立的边界、主要缺口和全局优先级。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver 的详细产品、算法和后端设计由各自蓝本维护；历史过程只留 Git。

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

- `PhysicsWorldCache` 统一持有 frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams 和 backend resources。
- solver 是 `physicsWorld/<domain>/` 下的可发现模块；私有 topology、backend context 和跨帧状态只存在于自己的 slot。
- solver step 发布 result/exchange，不直接写 Blender；Object、PoseBone 和 mesh offset 由公共 writeback 应用。
- Cache Delete、runtime cache clear、不兼容重编译和插件注销必须释放 world/slot/backend owner；兼容重编译按 solver 签名合同决定复用、热更新或 staged replacement。
- 显式产品域和通用 implicit object 是两种合法装配方式。一个 solver 选择其中一种后，不得在运行时混用两套字段解析。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理 RNA/UI 根生命周期
  blender_registry.py        # domain 注册、依赖与失败回滚
  registry.py                # component/solver 发现与装卸
  gn_offset.py               # 共享 GN 顶点最终 offset
  bake/                      # 通用 Bake 后端与 session
  collision/                 # Object/Bone collider 共享 capability
  spring_vrm/                # VRM SpringBone
  rigid/                     # Rigid/Jolt
  mc2/                       # 一个 solver，三种 setup
    setups/
      mesh_cloth/
      bone_cloth/
      bone_spring/
  mesh_xpbd/                 # 独立基础纯 Mesh XPBD
  ui/
```

| 稳定 Blender 路径 | owner |
|---|---|
| `Bone.hotools_collision` | `physicsWorld.collision` |
| `Object.hotools_object_collision` | `physicsWorld.collision` |
| `Object.hotools_mesh_collision` | `physicsWorld.mc2.setups.mesh_cloth` |
| `Object.hotools_rigid_body` | `physicsWorld.rigid` |
| `Object.hotools_rigid_constraint` | `physicsWorld.rigid` |
| `Scene.ho_*` 物理 UI 字段 | `physicsWorld.ui` |

属性 schema、PropertyGroup、binding 和注册权只存在于 Physics World。world cache 与 solver slot 不跨帧保存 live PropertyGroup。

## Domain 状态

| Domain | 当前状态 | 已成立边界 | 主要缺口/入口 |
|---|---|---|---|
| World core | 可用 | 统一时间、Begin/Commit、scope、slot/resource/result/exchange、writeback、dispose、debug snapshot | 补齐全部 solver 的统一时间矩阵；建立真实跨 solver 交互闭环 |
| Physics Bake | Bone + PC2 Mesh + Clear vertical slice 可用 | 公共 Bake 节点、Action/PC2、manifest、播放和清理 | 见 `PHYSICS_BAKE_NODE_BLUEPRINT.md` |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共 snapshot 与 capability | 继续消除 solver 私有重复 resolver |
| 通用力场 | 未来兼容区 | ownership 固定归 Physics World，solver 只消费公共数值快照 | channel/schema/采样布局和首个 active vertical slice 未冻结 |
| SpringBone VRM | world-aware vertical slice 可用 | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续能力扩展和性能维护 |
| Rigid/Jolt | vertical slice 可用 | body/constraint、scope、result/writeback、query/event/debug、dispose、soak 与 golden | 统一零 dt 行为；Path 和高级 shape/query |
| MC2 | 三 setup 统一域 CPU 产品可用；BoneCloth 阶段里程碑完成；E6 GPU 设计已立项 | MeshCloth 与 BoneCloth 均采用面板/自定义对象、完整域分区和 setup collector；BoneCloth 面板对象逐 Bone 消费半径与外碰接受掩码，控制 Bone 仅选链；终端粒子、connected/disconnected 双写回、显式 product request、DomainV1 mixed pass、whole-domain self、多目标事务、产品 debug、Mesh/Bone writeback；Teleport粒子/自碰/外碰历史闭环；CPU 是独立长期 reference | 按 `MC2_GPU_BACKEND_DESIGN.md` 新增隔离 GPU provider，不改 CPU solver |
| Mesh XPBD | 重写合同已建立；运行时尚未接通 | 独立基础纯 Mesh solver、严格 XPBD、纯 nanobind context、公共碰撞/GN 写回边界见 `MESH_XPBD_BLUEPRINT.md` | 完成 native 数值核和 World vertical slice 后做生产验收，再删除旧双节点/私有 cache 与写回 |

通用力场当前没有 active 能力。任何 solver 中遗留的 wind 名称不代表公共场输入已经存在。

## 当前优先级

1. MC2 进入 E6，但只允许新增独立 GPU backend。CPU DomainV1 的算法、状态、ABI、加载和性能是冻结基线，GPU 工作不能以任何理由造成 CPU 回归。
2. E6 先建立可选 provider、CPU-only 加载隔离和固定 fixture 闭环，再实现 whole-domain self 与完整 mixed pass；不能从产品节点直接开始拼 GPU 分支。
3. GPU 成功必须以产品整帧、上传/同步/readback、工作量等价、设备失败和规模曲线判断，不能只报告 kernel 时间。
4. Rigid/Jolt 优先清除私自 dt fallback，并继续补公共时间合同。
5. Bake 与通用力场继续按公共能力推进，不进入 MC2 或其它 solver 私有 owner。
6. Mesh XPBD 按 `MESH_XPBD_BLUEPRINT.md` 以独立 solver 重写；新 vertical slice 验收前不删除旧路径，也不把合同注册误报为运行可用。

## 公共验收门槛

- 架构审计：依赖方向、私有边界、注册根、结果通道、backend owner 和 native binding 无未解释违规。
- 生命周期：创建、热更新、staged replacement、失败回滚、dispose、undo/load 和插件注销不泄漏资源。
- 事务：多个 solver/request/target 在 mutation 前完整验证，失败时零部分写回。
- Debug：关闭时无额外 record/readback；开启时只观察真实 production pass。
- Native：CPU-only 构建和加载不依赖任何可选 GPU runtime；双 ABI 按各 solver 阶段门槛验证。
- Blender：隔离默认备份模块，确认加载当前工作树源码和对应 native 产物。

## 文档维护

本文的 domain 行只回答“当前处于什么状态、缺什么、去哪里看”。单个 solver 的能力明细、fixture、实施批次、性能数字、删除清单和提交结果不得追加到本文。
