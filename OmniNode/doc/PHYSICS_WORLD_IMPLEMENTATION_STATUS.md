# OmniNode 物理世界当前实现状态

更新日期：2026-07-20

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
| MC2 | 生产V0可用；统一粒子域E4进行中 | 既有产品数值/debug验收保持闭环；E0-E3、P0、P1-B、粒子级覆盖、partitioned StepBasic、compiled whole-domain self/external及native-owned完整pass已完成；collector draft可从Physics World公共snapshot一次生成whole-domain immutable collider POD，排除全部域内owner但不按任一partition mask预筛选，并由native逐partition过滤；完整Tier A fragment已有逐partition重力感知的两阶段事务缓存，并持有帧旋转native-ready topology/adjacency/corner UV；纯host fused CPU owner已将cache commit与native staged replacement合并并直接代理frame/full step/output，失败保留旧domain/cache；产品collector bridge逐source单次消费P1-B observation并冻结draft/E0快照/BasePose topology identity；固定whole-domain world slot已关闭同/跨generation同步、dispose及多BasePose/Anchor logical frame + whole-domain collider原子发布合同，Mesh旋转与V0共用native核心；A5-04已按particle owner隔离Tether/Angle/Motion/Post参数并复用native Center输出，六轴Motion与旧标量oracle均有双ABI证据；slot-owned scheduler/timing/Anchor staged state已具备失败回滚与发布后提交；Center frame shift按frame一次性消费，多substep不会重复位移；staged slot 已真实执行完整 compiled frame，并只在 native 成功后提交 scheduler，但`product_enabled=False`且不进入普通V0 step | 下一入口是 Blender 多source oracle与性能验收，然后闭环E5多目标事务和产品collector；当前`HEAD`二进制也可复现旧V0 raw native测试的Windows access violation，必须在oracle前独立关闭；通过后执行E7-CPU清理 |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

## 当前优先级

MC2 E4 revalidation (2026-07-22): Blender 5.2/Python 3.13 now passes the real two-source, three-frame V0/Domain oracle at `1e-6`, including initialization-only frame timing and partitioned Distance velocity history. The Domain registry is GIL-serialized to avoid Blender/MSVC mutex startup crashes. The remaining E4 gate is the same-fixture P2 performance comparison; then E5 multi-target transactions/product collector, followed by E7-CPU cleanup after full acceptance.

1. 推进 Physics Bake 的 Bone component ownership、Object Action、Bake回绕暂停、Object/PC2 baseline、journal与topology signature，同时保持现有 Bone/PC2/Clear 留存合同。
2. 保持Rigid/Jolt schema、native ABI、debug renderer与fixture同步。
3. MC2保持生产V0可用；E4统一slot、真实compiled子步、scheduler advance原子性和Blender 5.2多source数值oracle已完成，当前只关闭同fixture性能门禁，再推进E5多目标事务与产品collector；不得越过Physics World边界或提前删除V0 owner。
4. 用真实业务场景验证rigid→cloth、body transform→collider等跨solver exchange。
5. 决定Mesh XPBD迁移或删除。

## 公共验收门槛

新增或迁移solver至少满足：

- declaration可查询，公开channel可由debug snapshot观察。
- 连续帧、same-frame、首帧、跳帧/倒放、reset与失败回滚有后台测试。
- Cache Delete、clear、不兼容重编译和注销释放native/resource owner；兼容重编译不得误释放。
- solver不直接写bpy；result可被公共writeback、preview或export消费。
- schema/RNA/capability同源，`.blend`非默认值往返不漂移。
- backend、Python binding、节点surface、debug和fixture同步落地。
- 不保留旧路径asset adapter、runtime fallback或shadow solver。

具体字段和生命周期规则以公共contract与代码中的descriptor/declaration registry为准；本文只在domain边界或主要未完成项变化时更新。
