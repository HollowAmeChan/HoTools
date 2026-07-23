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
| MC2 | 三种setup统一域产品路径可用；E7-A行为迁移完成，执行最终依赖审计 | E0-E5-B、P0、P1-B、E4/P2均已闭环；DomainV1拥有partitioned StepBasic、whole-domain self/external、完整混合pass、scheduler/Center/Anchor历史和多目标logical output；Mesh与Bone公开节点只生成setup-neutral显式product request，动态槽位按setup/domain identity拥有状态，多request全部求解后一次发布；同Armature Bone结果合并，失败清除整批owner/result/feedback；Bone删除前全约束、混合输出、外碰、Center/Teleport、故障事务和Angle/Motion数值门禁已双ABI关闭 | 完成精确import/reachability/公开符号审计并冻结实际删除集合；再执行E7-CPU删除三种setup旧owner/hidden task/aggregate，随后执行E7-S兼容层专项简化；并行沉淀P6合同 |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

## 当前优先级

MC2 E4/P2复验（2026-07-23）：Blender 5.2/Python 3.13 的非self双source oracle继续在`1e-6`内通过。whole-domain self接入后端中立opaque engine后，1764粒子、4 source、35帧、5帧warmup同夹具中，Domain与manual join的primitive/candidate/contact完全一致；reset轨迹位级相等，连续轨迹peak max-abs为`3.9208e-4`、RMS为`1.6597e-5`，通过`5e-4/5e-5`累计self合同。持久scratch消除每子步临时分配后，owner层p50为`5.9297 ms`，旧aggregate为`7.5374 ms`，D/B=`0.78670`；manual join为`7.9362 ms`，D/C=`0.74717`。

MC2 E5验收（2026-07-23）：`domain_output.py`把一次logical output冻结为带共同事务id的多target批次，`results.py`允许同一domain slot发布多个不重复target，并在进入result stream前拒绝缺项/重号批次。`writeback.py`对整批对象/data/顶点数和单用户状态先做零写入预检，再准备受管GN结构、快照旧offset并提交；第二目标注入写失败时两个目标均恢复，记录`rollback_count=2`且不产生receipt。Blender 5.2真实两Mesh还覆盖了拓扑失效时result stream不替换、随后writeback零partial mutation。四个产品节点已把显式与隐式entry解析为一个Require-Fusion request；`MC2模拟步`连续120帧实际写回两目标并双跑逐float32相等，不允许与旧task混输。E5后P2复跑仍通过：D/B p50=`0.79823`，D/C=`0.80175`，self轨迹peak max-abs/RMS=`3.9207e-4/1.6597e-5`。

MC2双ABI补验（2026-07-23）：修复`build.bat`复用被测试改写的CMake runtime cache后，py311产物真实写入`_Lib/py311`并通过native `27/27`。Blender 4.5/py311确认加载当前cp311，属性/声明`11/11`、GN多目标事务、统一域产品节点、双source对照和120帧双跑全部通过；同一动态ABI runner在Blender 5.2确认加载当前cp313并全过。

MC2 E5-B验收（2026-07-23）：BoneCloth/BoneSpring公开节点已切到`MC2ProductRequestV1`，按Armature生成显式request；产品槽位由`setup_type + domain_signature`动态确定。多request先全部stage/solve再发布一次结果事务，同Armature不相交Bone结果合并，失败路径清除整批owner/result/feedback并恢复批前Bone反馈。旧Bone task构建器仅由显式`V0Oracle`入口可达。py311/Blender 4.5与py313/Blender 5.2均确认加载当前产物并通过native `28/28`、属性`11/11`、Mesh产品域、Bone产品多请求、重复900帧混合输出、Center World/Local/depth/Anchor组合和Bone角度/恢复力/碰撞/摩擦/Distance/Tether/Bending/self/旋转输出全约束soak。
MC2 参数热更新、外碰、Center、故障与Angle/Motion门禁（2026-07-23）：新增同布局 native 暂存域与可逆配置交换 ABI。纯参数值变化不再替换 live handle；暂存阶段完整重跑 Distance/Bending/Inertia/Friction/Self/External/Center/Teleport/Integration 配置校验，成功后只交换配置 SoA，保留帧、scheduler、Center/Teleport、粒子和输出历史；host cache 提交失败会交换回旧配置并清理暂存域。cp313/5.2 与临时开放的 cp311/4.5 均通过 owner、native kernel 和 compiled pipeline 对照；热更新轨迹与全新 second-domain 逐数组一致。三 setup 产品 mixed-output 又以 active-solve 计数锁定 Angle/Motion 在 301-600 帧关闭冻结、601 帧恢复增长，双版本摘要同为 `7538202a…0db8`。公开 Bone 产品碰撞门禁锁定组屏蔽零法线、接受 Sphere 的确定性响应、自身 owner 排除、BoneSpring Capsule 排除与 BoneCloth 摩擦有序 lag；Center/Teleport 门禁锁定 world/anchor inertia 两端点、local inertia、depth 轨迹分离、Reset=`5`、Keep=`3` 和每帧一次 frame shift；真实两域第二域故障门禁锁定 owner/result/feedback 整批回滚、PoseBone 零写入与同帧重试。最后的公开产品 Angle/Motion 门禁锁定 BoneCloth/BoneSpring Restoration 响应、父旋转级联 Limit 30°/15°、MaxDistance `0.03m` 与 Backstop `0.01m` 表面边界；两版均确认加载本工作树 ABI 并得到一致数值。E7-A 行为迁移已完成，剩余为最终精确依赖审计，不是数值或 native ABI 缺口。
MC2 E7-A 精确依赖审计（2026-07-23）：更新后的架构工具区分顶层 import-time 与函数内延迟 bridge，py311/py313 的 `--check --e7-product-check` 均通过。`product_solver` 产品运行图到五个旧模块的可达数为 `0`；公开 `nodes` 顶层图仍经旧 debug 链可达 `native_context`，另有 7 条 task/oracle 延迟 bridge。native 待删面为 68 个旧必需符号、2 个 fingerprint V0 alias、70 个 binding 和五个 context 翻译单元。E7-A 至此完成并冻结删除顺序；下一步进入 E7-CPU 的 product-only step/debug 切断提交。

1. 推进 Physics Bake 的 Bone component ownership、Object Action、Bake回绕暂停、Object/PC2 baseline、journal与topology signature，同时保持现有 Bone/PC2/Clear 留存合同。
2. 保持Rigid/Jolt schema、native ABI、debug renderer与fixture同步。
3. MC2统一域E5-B产品入口已切换；当前执行E7-A删除前资格审计，关闭后依次执行E7-CPU删除和E7-S兼容层专项简化；P6合同贯穿其间，任何setup都不得静默回退到旧task/V0。
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
