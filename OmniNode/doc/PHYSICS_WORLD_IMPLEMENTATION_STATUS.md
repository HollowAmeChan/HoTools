# OmniNode 物理世界当前实现状态

本文只记录 Physics World 各 domain **当前成立的边界、主要未完成项和全局优先级**。公共结构规则见 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；solver稳定事实由各自蓝本维护；历史过程由Git保存。

MC2专项入口：稳定产品/实现/维护合同见`MC2_BLUEPRINT.md`；当前阶段只看本文MC2 domain行。

## 写作边界

- **应该写**：各domain的一页式当前状态、已经成立的系统边界、主要未完成项和Physics World全局优先级。
- **不应该写**：单个solver的能力明细、数值公式、fixture清单、实施步骤、源码差异、调试过程或逐提交历史。
- **内容路由**：公共结构规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；MC2稳定事实写`MC2_BLUEPRINT.md`；OmniNode编译/缓存框架写`../ARCHITECTURE.md`；历史只留Git。
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
  -> Physics Bake
  -> Physics World Commit
  -> Cache Write
```

- `PhysicsWorldCache`统一持有frame context、scope、collider snapshot、implicit object registry、solver slots、exchange、result streams和backend resources。
- solver是`physicsWorld/<domain>/`下可发现模块；私有topology、native context和运行状态只存在于自己的slot。
- solver step发布result/exchange，不直接写Blender；Object、PoseBone和mesh offset由公共writeback应用。
- Cache Delete、runtime cache clear、不兼容成功重编译和插件注销必须释放world/slot/backend owner；兼容重编译保留world，并由solver签名合同处理热更新或slot重建。

## 当前目录与所有权

```text
physicsWorld/
  blender.py                 # 物理RNA/UI根生命周期
  blender_registry.py        # domain注册journal、依赖和失败回滚
  registry.py                # component/solver发现与装卸
  gn_offset.py               # 共享GN顶点最终offset
  bake/                      # 通用Bake后端与session协调
    session.py               # 路径、target UUID、原子manifest
    bones.py                 # 精确Bone result -> 专用Action
    pc2.py                   # 逐帧PC2 writer、manifest与Mesh Cache播放
    clear.py                 # 用户控制的Action/cache/live清理与baseline
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
| World core | 可用 | Begin按Blender `fps/fps_base`统一生产raw_dt/dt；Begin/Commit、scope、slot/resource/result/exchange、channel registry、writeback、dispose、debug snapshot；共享GN ensure按builder结构contract判定代码差异，不只依赖整数schema，显式refresh可原位修复场景资源 | 统一时间验收矩阵仍需覆盖全部solver；跨solver交互仍需真实业务闭环 |
| Physics Bake | Bone + PC2 Mesh + Clear vertical slice可用 | `物理烘焙`与`清除物理Bake动画` OmniNode及“物理世界”正常添加菜单、world/目录/前缀同序直连、单条/batch Bone精确Action、源Action恢复、Bone首帧baseline回填、三类独立整数留存策略、真实GN writeback target逐帧PC2、每对象独立文件与并行IO、受管Mesh Cache开关、KEEP/精确truncate/delete、v2原子manifest、保存重开回放 | Bone component ownership、Object Action、Bake回绕暂停、Object/PC2 baseline、journal恢复、topology signature与多Mesh性能门槛；GN Bake经人工生产验收后已否决，总合同见`PHYSICS_BAKE_NODE_BLUEPRINT.md` |
| Collision | 可用 | Object/Bone schema、RNA、group mask、公共snapshot与capability | 继续消除solver私有重复resolver |
| 通用力场 | 未来兼容区 | ownership固定归Physics World；solver只消费公共数值快照 | channel/schema/采样布局和首个active vertical slice均未冻结 |
| SpringBone VRM | world-aware vertical slice完成 | 隐式骨链、native context、slot、碰撞、result、PoseBone writeback、debug、dispose | 后续能力扩展和性能维护 |
| Rigid/Jolt | vertical slice可用，P0门禁闭环 | body/constraint spec、resource、scope、result/writeback、query/event/debug、dispose、soak与golden | 清除`frame_context.dt <= 0`时私自回退`1/60`的时间合同偏差；Path及剩余高级shape/query |
| MC2 | 三种 setup 的统一域产品路径可用；处于 E7-CPU 删除前结构收口 | E0-E5-B、P0、P1-B、E4/P2 已闭环；`MC2ProductRequestV1`、DomainV1 whole-domain mixed pass、三 setup collector、多目标事务、产品 debug 和 Bone writeback 已成立；产品/公开节点/debug 到旧模块的可达性为零；Mesh Bending、Angle Limit、Distance/Tether、外部碰撞 scope、friction 与 whole-domain self 已全部由产品数值闸门接管；能力矩阵 9/9 verified | 迁出 `specs.py` 中立合同；删除旧 Python owner、普通 aggregate、68 个 V0 binding 和 5 个 context 翻译单元；执行 E7-S、P6 合同收口和最终双 ABI 验收 |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

## 当前优先级

MC2 当前处于 E7-CPU 删除前结构收口阶段。统一 MC2ProductRequestV1、DomainV1 whole-domain 执行、三种 setup collector、事务写回和请求驱动调试已经成立；产品运行图、公开节点顶层图和调试图到旧模块的可达性审计为零；9 个能力族的产品数值门禁全部通过，但旧 owner、测试门面和 native V0 ABI 仍然存在。

后续只按以下逻辑批次推进：

1. capability matrix 已不再引用旧 Mesh/Bone constraint runner；Mesh Bending、Angle Limit、Distance/Tether、Collider scope、Friction 和 whole-domain self 均由 Blender 5.2 产品 runner 提供真实数值响应。
2. BoneCloth/BoneSpring 的独立数值与包装限制前置签字已经关闭，不重复实施；将 topology/setup 仍需要的中立合同迁出 `mc2/specs.py`，随后删除 Python V0 owner、hidden task、普通 aggregate 和兼容 bridge。
3. 删除 68 个 native V0 binding 和 5 个 `mc2_context_*` 翻译单元；每个逻辑批次同时更新测试、审计和唯一蓝本，不按单 runner 提交。
4. 删除完成后立即执行 E7-S，逐项清理迁移期 fallback、双 schema/result 翻译、旧 resource key、无调用 forwarder 和误导命名。
5. 并行只冻结 P6 的 backend-neutral data/pass/buffer/IO 合同。不实施 P4 CPU 并发，不实现 E6 GPU，不允许为未来 GPU 引入无法解释的 CPU 回归。
6. 旧代码删除、E7-S 和 P6 合同复核完成后，才恢复 Python 3.11 / Blender 4.5 做最终双 ABI 与 Blender 收尾验收。

当前开发和常规验收只使用 Python 3.13 / Blender 5.2，并确认实际工作树源码与 _Lib/py313 native 产物一致。4.5/py311 在旧代码删除收尾前保持冻结。

## 公共验收门槛

- 架构审计：依赖环、私有边界、产品/公开节点/调试旧模块可达性和 native binding 合同均无未解释违规。
- 纯 Python：DomainV1、共享 kernel、product collector、事务写回和能力矩阵的独立断言通过。
- Blender 5.2：--factory-startup 产品节点、三 setup、多 source whole-domain、multi-target rollback、debug snapshot 和 600/900 帧确定性通过。
- 删除阶段：旧 Python/native 面完全不可达后，才运行最终 4.5/py311 双 ABI；P6 只验合同，不以 GPU 实现作为本阶段验收项。

## 文档维护规则

本文只保留稳定边界、当前缺口和全局优先级。单次提交、单次 runner、临时性能数字和调试过程只留在 Git、测试输出或 benchmark 结果中；MC2 详细合同和删除清单统一维护在 MC2_BLUEPRINT.md。
