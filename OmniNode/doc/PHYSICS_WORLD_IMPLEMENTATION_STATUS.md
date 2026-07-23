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
| MC2 | 三种setup统一域产品路径可用；E7-A已关闭，E7-CPU分组删除中 | E0-E5-B、P0、P1-B、E4/P2均已闭环；DomainV1拥有partitioned StepBasic、whole-domain self/external、完整混合pass、scheduler/Center/Anchor历史和多目标logical output；Mesh与Bone公开节点只生成setup-neutral显式product request，动态槽位按setup/domain identity拥有状态，多request全部求解后一次发布；同Armature Bone结果合并，失败清除整批owner/result/feedback；Bone删除前全约束、混合输出、外碰、Center/Teleport、故障事务和Angle/Motion数值门禁已双ABI关闭；公开step、节点顶层导入、调试模块硬类型依赖及产品调试快照迁移已经关闭 | 按冻结清单删除三种setup旧Python owner、hidden task、普通aggregate、oracle bridge及70个native V0 binding、五个context翻译单元；删除后执行E7-S兼容层专项简化；最后恢复4.5/py311并完成双ABI收尾；并行沉淀P6合同 |
| Mesh XPBD | 旧路径 | 仅作简单布料参考 | 决定迁移或删除，不维持第二套布料语义 |

通用力场当前没有active能力。wind只是未来kind；MC2中的`wind_*`兼容字段不代表场输入、采样或native消费。

MC2 Bone 产品集成脚本收敛（2026-07-23）：`test_blender_mc2_bone_product.py` 已移除脚本内 V0 task/oracle、旧 solver/spec/context 与 aggregate 故障注入，改为只验证公开 BoneCloth/BoneSpring request、统一产品 owner、动态槽、约束调试和 Bone writeback。Blender 5.2/Python 3.13 明确加载当前工作树 `product_solver.py` 与 `_Lib/py313` 后全部通过。旧 `test_blender_mc2_v1_soak.py` 及其独占的 Blender 5.1 JSON 基线也已删除；其性能、长程/热更新、dispose/参数交换和 same-frame 职责分别由产品 hotspot、产品 mixed soak、product slot 与 frame-state 门禁承接。4.5/py311 继续冻结。该项不替代旧 mixed-output 中仍待迁移的精确 stabilization ramp、零子步、particle subset、debug layer 和非单位正尺度断言。

## Bone 删除前门禁更新（2026-07-23）

旧 `test_blender_mc2_bone_constraint_soak.py` 已从 2158 行 V0 soak 收缩为 product-only 兼容门面，所有旧符号只转发到公开 BoneCloth/BoneSpring 产品 runner，不再创建 V0 task、读取 `native_context` 或导入 mixed runner。Angle/Motion、外碰/摩擦、rotation controls 和 gravity axes/falloff runner 已在 Blender 5.2 / Python 3.13 完成 600 帧，约束 runner 完成 900 帧双跑；公共 helper 固定使用 `_Lib/py313`。BoneCloth/BoneSpring plan 已登记逐项迁移清单，当前删除前缺口收窄为 `bone_self_collision` 的 scope/cache/radius 以及精确 target/rest 边界，不能由兼容门面宣称等价。完成这些产品证据后才允许删除门面、旧 Python/native owner、hidden task、普通 aggregate 和 V0 binding；4.5/py311 继续冻结。

## 当前优先级

MC2 E7-CPU 产品稳定化与限速证据更正（2026-07-23）：产品 Center debug ABI 已增加请求驱动的 `velocity_weight` 与 `gravity_ratio`，`Reset` 在一次 frame-shift 事务中按 `stabilization_time_after_reset > 1e-6` 从零开始，帧内多个 substep 只累加一次；DomainV1 native 回归和 Blender 5.2 三 setup 双跑均精确通过 `1/6` 增量、20 帧饱和到 `1.0` 的 ramp。产品 mixed 900 帧热更新窗口新增独立 dynamics debug ABI，直接观察 post 后 `state_velocities`，MeshCloth/BoneCloth/BoneSpring 的低限峰值比分别为 `1.00000007/1.00000021/1.00000010`，并验证上限未越界、参数 SoA 已提交和双跑摘要一致。此前“产品 ABI 不暴露 velocity_weight、ramp 尚未迁移”的表述自本条起失效；旧 mixed-output main 仍只保留尚未迁移的 teleport 零子步、particle subset、debug layer 隔离和非单位正尺度断言。当前只使用 Blender 5.2/Python 3.13 与 `_Lib/py313`；不恢复 4.5/py311。

MC2 E7-CPU 产品稳定化与限速证据更正（2026-07-23）：产品 Center debug ABI 已增加请求驱动的 `velocity_weight` 与 `gravity_ratio`，`Reset` 在一次 frame-shift 事务中按 `stabilization_time_after_reset > 1e-6` 从零开始，帧内多个 substep 只累加一次；DomainV1 native 回归和 Blender 5.2 三 setup 双跑均精确通过 `1/6` 增量、20 帧饱和到 `1.0` 的 ramp。产品 mixed 900 帧热更新窗口新增独立 dynamics debug ABI，直接观察 post 后 `state_velocities`，MeshCloth/BoneCloth/BoneSpring 的低限峰值比分别为 `1.00000007/1.00000021/1.00000010`，并验证上限未越界、参数 SoA 已提交和双跑摘要一致。此前“产品 ABI 不暴露 velocity_weight、ramp 尚未迁移”的表述自本条起失效；旧 mixed-output main 仍只保留尚未迁移的 teleport 零子步、particle subset、debug layer 隔离和非单位正尺度断言。当前只使用 Blender 5.2/Python 3.13 与 `_Lib/py313`；不恢复 4.5/py311。

MC2 E4/P2复验（2026-07-23）：Blender 5.2/Python 3.13 的非self双source oracle继续在`1e-6`内通过。whole-domain self接入后端中立opaque engine后，1764粒子、4 source、35帧、5帧warmup同夹具中，Domain与manual join的primitive/candidate/contact完全一致；reset轨迹位级相等，连续轨迹peak max-abs为`3.9208e-4`、RMS为`1.6597e-5`，通过`5e-4/5e-5`累计self合同。持久scratch消除每子步临时分配后，owner层p50为`5.9297 ms`，旧aggregate为`7.5374 ms`，D/B=`0.78670`；manual join为`7.9362 ms`，D/C=`0.74717`。

MC2 E5验收（2026-07-23）：`domain_output.py`把一次logical output冻结为带共同事务id的多target批次，`results.py`允许同一domain slot发布多个不重复target，并在进入result stream前拒绝缺项/重号批次。`writeback.py`对整批对象/data/顶点数和单用户状态先做零写入预检，再准备受管GN结构、快照旧offset并提交；第二目标注入写失败时两个目标均恢复，记录`rollback_count=2`且不产生receipt。Blender 5.2真实两Mesh还覆盖了拓扑失效时result stream不替换、随后writeback零partial mutation。四个产品节点已把显式与隐式entry解析为一个Require-Fusion request；`MC2模拟步`连续120帧实际写回两目标并双跑逐float32相等，不允许与旧task混输。E5后P2复跑仍通过：D/B p50=`0.79823`，D/C=`0.80175`，self轨迹peak max-abs/RMS=`3.9207e-4/1.6597e-5`。

MC2双ABI补验（2026-07-23）：修复`build.bat`复用被测试改写的CMake runtime cache后，py311产物真实写入`_Lib/py311`并通过native `27/27`。Blender 4.5/py311确认加载当前cp311，属性/声明`11/11`、GN多目标事务、统一域产品节点、双source对照和120帧双跑全部通过；同一动态ABI runner在Blender 5.2确认加载当前cp313并全过。

MC2 E5-B验收（2026-07-23）：BoneCloth/BoneSpring公开节点已切到`MC2ProductRequestV1`，按Armature生成显式request；产品槽位由`setup_type + domain_signature`动态确定。多request先全部stage/solve再发布一次结果事务，同Armature不相交Bone结果合并，失败路径清除整批owner/result/feedback并恢复批前Bone反馈。旧Bone task构建器仅由显式`V0Oracle`入口可达。py311/Blender 4.5与py313/Blender 5.2均确认加载当前产物并通过native `28/28`、属性`11/11`、Mesh产品域、Bone产品多请求、重复900帧混合输出、Center World/Local/depth/Anchor组合和Bone角度/恢复力/碰撞/摩擦/Distance/Tether/Bending/self/旋转输出全约束soak。
MC2 参数热更新、外碰、Center、故障与Angle/Motion门禁（2026-07-23）：新增同布局 native 暂存域与可逆配置交换 ABI。纯参数值变化不再替换 live handle；暂存阶段完整重跑 Distance/Bending/Inertia/Friction/Self/External/Center/Teleport/Integration 配置校验，成功后只交换配置 SoA，保留帧、scheduler、Center/Teleport、粒子和输出历史；host cache 提交失败会交换回旧配置并清理暂存域。cp313/5.2 与临时开放的 cp311/4.5 均通过 owner、native kernel 和 compiled pipeline 对照；热更新轨迹与全新 second-domain 逐数组一致。三 setup 产品 mixed-output 又以 active-solve 计数锁定 Angle/Motion 在 301-600 帧关闭冻结、601 帧恢复增长，双版本摘要同为 `7538202a…0db8`。公开 Bone 产品碰撞门禁锁定组屏蔽零法线、接受 Sphere 的确定性响应、自身 owner 排除、BoneSpring Capsule 排除与 BoneCloth 摩擦有序 lag；Center/Teleport 门禁锁定 world/anchor inertia 两端点、local inertia、depth 轨迹分离、Reset=`5`、Keep=`3` 和每帧一次 frame shift；真实两域第二域故障门禁锁定 owner/result/feedback 整批回滚、PoseBone 零写入与同帧重试。最后的公开产品 Angle/Motion 门禁锁定 BoneCloth/BoneSpring Restoration 响应、父旋转级联 Limit 30°/15°、MaxDistance `0.03m` 与 Backstop `0.01m` 表面边界；两版均确认加载本工作树 ABI 并得到一致数值。E7-A 行为迁移已完成，剩余为最终精确依赖审计，不是数值或 native ABI 缺口。
MC2 E7-A 精确依赖审计（2026-07-23）：更新后的架构工具区分顶层 import-time 与函数内延迟 bridge，py311/py313 的 `--check --e7-product-check` 均通过。`product_solver` 产品运行图到五个旧模块的可达数为 `0`；公开 `nodes` 顶层图仍经旧 debug 链可达 `native_context`，另有 7 条 task/oracle 延迟 bridge。native 待删面为 68 个旧必需符号、2 个 fingerprint V0 alias、70 个 binding 和五个 context 翻译单元。E7-A 至此完成并冻结删除顺序；下一步进入 E7-CPU 的 product-only step/debug 切断提交。
MC2 E7-CPU 公开 step 切断（2026-07-23）：`physicsMC2Step` 已改为 product-only，不再回退 `step_mc2`；空 request 和成功后的 request 集合缩减由产品 solver 原子清理退出槽与旧结果。py311/py313 产品批事务 `5/5`，Blender 4.5/cp311 与 5.2/cp313 的产品节点、120 帧确定性和显式双 source oracle 对照均通过。下一组迁移 debug/debug_draw 的旧 context 依赖。
MC2 公开 import-time 解耦（2026-07-23）：`nodes` 改为仅在调试节点执行时加载 `debug_draw`，新增架构门禁后产品运行图与公开节点顶层图的旧模块可达数均为 `0`；两版 Blender 调试绘制 13 组断言全过。`debug/debug_draw` 内部旧 snapshot 依赖仍待下一组迁移。
MC2 调试旧类型解耦（2026-07-23）：旧 interaction resource key 已移到中立名称模块，`debug/debug_draw` 不再导入 `native_context` 或判断 `MC2NativeInteractionV0`，只通过捕获控制与冻结快照的窄只读方法协议观察资源。新增 `--e7-debug-import-check` 后，py311/py313 的产品运行图、公开节点顶层图和调试模块图到五个旧 Python owner 的可达数均为 `0`；Blender 4.5/cp311 与 5.2/cp313 调试绘制 13 组断言保持全过。旧 interaction 实例、V0 resource key 和兼容协议分支仍在，不得把本组解释成产品调试快照迁移完成；它们分别进入后续产品 owner 迁移与 E7-S 简化清单。
MC2 产品调试基础切片（2026-07-23）：公开请求器和 renderer 现可识别产品 slot，并在下一真实帧从编译 domain IR、同一次 logical output 和显式 native dynamics readback 生成只读 `mc2_product_debug_snapshot_v1`。首批覆盖 topology、attributes、velocity 和 Mesh output；Bone output 及 Center/Teleport、约束、外碰、whole-domain self 仍明确列为不支持，不做结果反推。py311/py313 产品槽 native 测试和 Blender 4.5/cp311、5.2/cp313 公开 Mesh 产品节点均通过；捕获期间旧 interaction resource 不存在，原有 120 帧与双 source 对照保持全过。
MC2 产品 Center/Teleport 调试（2026-07-23）：新增独立产品 readback ABI，直接冻结真实 Center evaluator 的逐 partition 分解量、限速结果、old/now frame pose、Teleport 阈值/测量与 Keep/Reset flags；snapshot 和 renderer 均按稳定 partition id 表达多 source，不压回旧单 task 模型。debug-off 和其他调试模式不调用该 ABI。py311/py313 DomainV1 native `22/22`、产品槽数值合同、Blender 4.5/5.2 公开产品节点与实际 renderer、120 帧、双 source 和旧 13 组调试回归均通过。剩余产品调试迁移为 Bone output、约束、外碰和 whole-domain self。
MC2 产品 Bone output 调试（2026-07-23）：compiled logical output map 与产品 writeback plan 现共同生成稳定 bone identity、motion mode 和 translation mask；connected 只绘制旋转结果，不再伪造位置写回。两版 Blender 同 Armature 两 partition 资产均锁定 8 个 connected 与 4 个 free 的精确计数和 base/target 关系。剩余产品调试迁移缩减为约束、外碰和 whole-domain self。
MC2 产品约束调试前置切片（2026-07-23）：`Depth` 直接消费 compiled program 的 baseline parent、分区 baseline root 与粒子参数 SoA 的生产 depth；`StepBasic` 只在显式请求时保留最后一次成功 whole-domain substep 已实际传给 Angle/Tether 的 native pose，捕获后立即释放，暂停帧则保持请求等待下一真实 substep；`Gravity` 按 partition 冻结真实 Center `gravity_ratio`，再按 `particle_partition_index` 展开本次 Integration 实际使用的方向、原始强度和有效强度。renderer 已支持逐粒子多分区重力，不再用首 source 代表全域。py311/py313 的产品槽 `13/13`、DomainV1 `22/22`、native 全量 `30/30` 均通过；Blender 4.5/cp311 与 5.2/cp313 的 MeshCloth、BoneCloth、BoneSpring 产品入口、120 帧/双 source 对照和旧调试绘制 13 组均通过并打印当前工作树源码/PYD，三类 E7 reachability 继续为零。剩余产品调试迁移仍为 Distance/Tether/Bending/Angle/Motion 的真实 pass 记录、外碰和 whole-domain self。

MC2 产品 Angle/Motion 原生调试记录（2026-07-23）：`DomainV1` 新增按掩码显式开启、成功后冻结、捕获后释放的约束调试会话；debug-off 不分配或保留任何记录。Motion pass 直接记录 MaxDistance/Backstop 的实际 origin、目标球心、半径、correction、valid、particle 与 partition；Angle Limit/Restoration 在三轮迭代内直接记录 parent/child origin、实际目标点与目标向量、弧度、限值、双方 correction、child/parent 与 partition，不再由 Python 从最终姿态重建目标。产品只在最终真实 substep 开启记录，失败立即清空，暂停帧继续等待。renderer 优先消费原生 target，旧 V0 snapshot 仅保留兼容回退。py311/py313 的 DomainV1 `22/22`、产品槽 `13/13`、native 全量 `30/30`、架构门禁和 Blender 4.5/5.2 的 MeshCloth、BoneCloth、BoneSpring、120 帧/双 source、旧 13 组 renderer 均通过；5.2 验收已清除默认 HoTools 备份模块并明确加载本工作树 cp313。该记录会话现已继续覆盖 Distance/Tether/Bending。

MC2 产品 Distance/Tether/Bending 原生调试记录（2026-07-23）：约束会话掩码扩展为 `Distance=4`、`Tether=8`、`Bending=16`，仍只在最终真实 substep 按请求分配。Distance 直接记录 A/B 两个真实 phase 的有向 owner/target、两端当时位置、实际 rest、current length、有效 stiffness、平均后的单记录 correction、hit 与双方 partition；Tether 记录 vertex/root、两端位置、StepBasic 实际 rest、上下限、分支、有效 stiffness、correction 与双方 partition；Bending 记录 dihedral/volume 稳定 record、四角色位置与 partition、实际 current/rest/stiffness、四角色平均贡献和 hit。Python 只做只读筛选与状态分类。native 单测已锁定 Distance/Tether 按粒子汇总 correction 等于 pass 位移；Blender 5.2/cp313 的多 source Mesh renderer 与 BoneCloth 非零横向 Bending 产品资产均通过并打印当前源码/PYD。按用户要求，py311/Blender 4.5 从本组开始冻结，直到旧代码最终删除收尾才恢复双 ABI 复验。下一组是产品 external collision，随后是 whole-domain self。

MC2 产品外部碰撞原生调试记录（2026-07-23）：约束会话新增 `ExternalCollision=32`，只在最终真实子步明确请求 `Collision`、`Collision Contacts` 或 `Radii` 时分配。Point/Edge production kernel 直接发布 primitive/collider 身份、参与粒子、当时 origin、接触点/法线和按 production 平均规则归一后的逐角色 correction；按粒子汇总逐角色 correction 必须等于该 external pass 的真实位移。Domain 同时冻结逐 partition collision mode/mask、逐粒子 radius，以及 point/edge 前后的摩擦状态；产品 snapshot 直接配对同一帧已发布的 whole-domain collider POD，不读取旧 task/context。renderer 已支持同一域中 point/edge 混合分区并按 `particle_partition_index` 过滤图元。cp313 native 全量、产品槽 `13/13`、CPU backend `5/5`、三类 E7 可达性审计和 Blender 5.2 的旧 renderer `13/13` 均通过；BoneCloth/BoneSpring 真实 Sphere 资产确认 contact 只指向允许的 collider，且源码和原生产物来自当前工作树 `_Lib/py313`。Blender 5.2 启动时已清除默认 HoTools 备份模块。py311/Blender 4.5 继续冻结，不因本组恢复；下一组严格进入产品 whole-domain self 调试记录。

MC2 产品统一域自碰调试记录（2026-07-23）：约束会话新增 `WholeDomainSelf=64`，产品只在最终真实子步明确请求 primitive、grid、candidate 或 contact 时触发。中立 `Mc2WholeDomainSelfEngine` 直接冻结生产 primitive flags/indices、AABB、厚度、逆质量、owner group/mask、网格桶、候选、接触身份/类型/法线/参数，以及四轮求解按共享粒子计数归一后的双侧 correction；所有 correction 的向量和必须等于该 self pass 的真实总位移。旧 `show_self_contacts` 所需的线段/三角形穿插诊断也已迁入中立引擎，保持隔帧 edge phase、owner 过滤、拓扑邻接过滤和最终五粒子确认，并且只在调试请求时运行。产品快照直接生成 contact/intersection 时间状态，renderer 不再读取旧 context。py313 原生 CPU `28/28`、产品槽 `13/13` 和 Blender 5.2 产品节点、120帧确定性、双V0对照及实际 renderer 全部通过；5.2 明确清除默认 HoTools 备份并加载当前 `_Lib/py313`。产品调试迁移至此关闭，下一步按审计清单删除旧 Python/native owner、hidden task、普通 aggregate 与 oracle bridge，再执行 E7-S 简化。py311/Blender 4.5 在删除完成、进入最终收尾前保持硬冻结。

MC2 E7-CPU基础数值oracle迁移（2026-07-23）：删除前由py313同输入V0/DomainV1已通过对照采集最小JSON golden，新增不导入`native_context/specs/solver`的`test_domain_reference_golden.py`。它直接锁定Integration、完整无碰撞pass、Post history、StepBasic、Angle/Motion、5种Center事务及点/边/self collision的float32位置/旋转/速度、native shift、Teleport flags、暂停零子步和逐字段原容差；Center使用Domain自有history，碰撞输入来自真实compiled primitive/parameter tables，均不冻结旧包装schema。完整Domain golden `10/10`，原`test_e3_v0_tolerance.py`已删除。

MC2 产品 Center World 长跑迁移（2026-07-23）：新增 `test_blender_mc2_product_center_controls_soak.py::center_world_controls`，只通过 `MC2ProductRequestV1`、统一 product collector 与 DomainV1 owner 运行 MeshCloth、BoneCloth、BoneSpring。3 个 setup、follow/hold/smooth/limited/rotation_limited 五组控制、每组双跑 600 帧全部通过，覆盖有限性、确定性、世界平移惯性排序、平滑、平移/旋转限速、Center shift/step 计数及产品槽无 `native_context`、`spec`、`_debug_draw_snapshot`。capability matrix 已将 `center_world_controls` 切换到该 runner；Local、Depth、Anchor 仍待各自产品 runner 证明。当前只使用 Blender 5.2/Python 3.13 与 `_Lib/py313`，4.5/py311 保持冻结。

MC2 产品 Center Local 长跑迁移（2026-07-23）：同一 runner 的 `center_local_controls` 对三种 setup 各执行四组控制、双跑 600 帧，显式读取产品 Center debug ABI 的 partition inertia/step 分量，锁定 `local_inertia=0/1` 的端点、BoneCloth/BoneSpring 的 Local movement 限制响应、MeshCloth 的零误报以及产品槽边界和确定性。capability matrix 已同步切换 Local 条目；Depth、Anchor 仍待产品 runner。仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 产品 Center Anchor 长跑迁移（2026-07-23）：`center_anchor_controls` 对三种 setup 的 Anchor inertia `0/1` 各双跑 600 帧，显式验证 Anchor shift 端点：`0` 跟随平台产生约 `0.03m` 的累计 shift，`1` 保持零 shift；产品槽边界和双跑确定性均通过。capability matrix 已切换 Anchor 条目；Depth 仍待产品 runner。仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 产品 Center Depth 长跑迁移（2026-07-23）：`center_depth_controls` 对三种 setup 的 `depth_inertia=0/1` 各双跑 600 帧，从 compiled particle parameter SoA 读取真实 depth、从 DomainV1 program 读取 Move mask，并在有运动方差的 592/599 帧验证 candidate 差值的深度排序与确定性；相关性为 MeshCloth `0.9989`、BoneCloth `0.8796`、BoneSpring `0.9940`。产品实际差值方向与旧 V0 `1-depth²` 公式相反，matrix 固定产品自身 `depth²` 排序合同，不把旧符号带入产品路径。Center World/Local/Depth/Anchor 条目现均已切换到 product runner；仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 产品通用 mixed-output 长跑迁移（2026-07-23）：capability matrix 的通用 mixed-output 证据已切换为 `test_blender_mc2_product_mixed_output_soak.py::test_three_setup_product_mixed_output_900_frame_deterministic_soak`。该 runner 以 MeshCloth、BoneCloth、BoneSpring 三种 setup 同域运行，连续 900 帧双跑，覆盖 product request、统一 scheduler、GN/Bone 写回、同布局参数热更新以及 Angle/Motion active-solve 计数，摘要双跑逐字节一致为 `7538202abf1026ea3a1b932d82fa38781cabc84f2c4752c4f808885d9adf0db8`。旧 mixed-output main 中的 stabilization ramp 精确断言和 teleport 细节不在本证据范围，仍由后续独立产品门禁迁移；因此不能据此提前删除旧 owner。仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 产品 Center Teleport 长跑迁移（2026-07-23）：`center_teleport_controls` 已接入 capability matrix，三种 setup 分别运行 Reset/Keep 两种产品参数、600 帧双跑；它通过显式 Center debug ABI 锁定触发 flag、Keep/Reset 互斥、Reset 帧 real velocity 清零、owner/domain 不重建、输出有限性与逐帧写回，双跑数组完全一致。夹具使用与旧语义相同的单帧 2m 跳变，避免把连续小步误当 teleport 测量。旧 mixed-output main 的 object zero-substep、particle subset、debug layer 隔离和非单位正尺度细节仍未迁移，继续作为删除前缺口；仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 产品 Center stabilization 参数迁移（2026-07-23）：`center_stabilization_controls` 在三种 setup 上以 Reset 后 `stabilization_time_after_reset=0.2`、`blend_weight=0.6` 与基线 `0.0` 配置各跑 600 帧双跑；它从 compiled parameter SoA 验证真实产品参数值，并锁定 Reset 后轨迹有限且确定。随后 DomainV1 在一次性 frame-shift 事务中按旧合同将 Reset 权重置零，产品 Center debug ABI 公开只读 `velocity_weight` 与 `gravity_ratio`，20 个产品帧严格验证 `dt/stabilization_time` ramp 及 blend 乘积。仅使用 Blender 5.2/Python 3.13，4.5/py311 继续冻结。

MC2 E7-CPU 产品证据收口（2026-07-23）：产品 mixed-output 900 帧双跑在第 301--600 帧显式请求 dynamics debug，直接读取 post 后的 `state_velocities`，验证 MeshCloth `0.08`、BoneCloth `0.09`、BoneSpring 专用 `0.03` 限速均逐帧不越界且峰值达到 98% 以上；限速参数表、峰值和全部输出摘要参与确定性比较。新增独立 `read_dynamics_debug` binding，不给普通 `read_output` 增加状态复制；`inspect` 仍保持零 readback。capability matrix 已删除旧 mixed runner 对 stabilization ramp 和 bounded velocity 的职责，旧 Python owner 仅保留尚未迁移的 zero-substep、particle subset、debug layer、非单位正尺度等细节。

MC2 E7-CPU 同帧与零子步 Teleport 收口（2026-07-23）：统一产品执行器现只在 `frame_context.same_frame=True`、slot 已完成同一帧且 native domain 仍复用时短路物理推进，但仍重新发布同一批产品结果；MeshCloth、BoneCloth、BoneSpring 的输出、Center shift/step 计数和 Teleport flags 均保持不变。产品帧在 `update_count=0` 时会显式执行一次 native `step_center_frame_shift`，只提交 Center/Anchor/Teleport 与 Reset/Keep 历史，不伪造物理子步；Reset 精确回到当帧 animated base、状态速度清零，Keep 对全部粒子应用精确 frame shift。`center_teleport_controls` 已在 Blender 5.2/cp313 以三种 setup、两种模式、双跑 600 帧通过，并把 `same_frame_stable`、三 setup Reset/Keep 检出、零子步立即应用、Reset 姿态精确和 Keep 位移精确五项能力从旧 mixed runner 迁走。产品 slot 单元测试 `13/13`、capability matrix `3/3` 和架构审计均通过。零子步初始化历史修复使产品 mixed 900 帧摘要有解释地更新为 `af7cccaac676963da5d10db28c4925f13859da437b866285bfaa42ebbfe16031`，双跑仍逐字节一致，三种限速峰值不变。此前“zero-substep 尚未迁移”的表述自本条起失效；旧 mixed runner 现在仍承担 task 单参考、Keep 速度/Reset step 与 self 历史、particle subset、Bone root、debug layer 隔离和非单位正尺度等未迁证据。4.5/py311 继续冻结。

MC2 E7-CPU Teleport 附加证据迁移（2026-07-23）：同一产品 runner 现分别以 MeshCloth `0.75`、BoneCloth `0.5`、BoneSpring `1.5` 的正 uniform scale 验证缩放阈值下的 Reset/Keep；并在独立帧请求 Teleport 阈值层和状态层，确认产品 snapshot 只填充 Teleport payload，Center 与 Output 保持空，捕获后不保留持久调试状态。逐帧 GN/Bone writeback 仍在同一双跑中验证。capability matrix 已将 `teleport_nonunit_positive_scale`、`teleport_debug_layers_isolated` 和 `real_writeback_each_frame` 三项附加职责移出旧 mixed runner。旧 runner 当前剩余职责收窄为 task 单参考、Keep 速度/Reset step 与 self 历史、particle subset 和 Bone root Teleport。

1. 推进 Physics Bake 的 Bone component ownership、Object Action、Bake回绕暂停、Object/PC2 baseline、journal与topology signature，同时保持现有 Bone/PC2/Clear 留存合同。
2. 保持Rigid/Jolt schema、native ABI、debug renderer与fixture同步。
3. MC2统一域E7-A已关闭，产品调试快照及 mixed/stabilization 两条独立数值证据已迁完；当前按冻结清单继续执行 E7-CPU：先迁移仍有独立价值的旧测试细节，再迁出中立合同并删除 Python owner/hidden task/aggregate/oracle，最后删除 70 个 V0 binding 与五个 context 翻译单元。删除后立即执行 E7-S 兼容层专项简化，再进入 P6 合同和最终双 ABI。全过程只使用 Python 3.13/Blender 5.2，任何 setup 都不得静默回退到旧 task/V0。
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
# 当前状态补充（2026-07-23）

## E7-CPU 产品边界门禁（2026-07-24）

`nodes.py` 的 Bone V0 oracle 已不再有任何调用者；公开 BoneCloth/BoneSpring 节点只生成 `MC2ProductRequestV1`，旧约束与 mixed runner 已降为 product-only 兼容门面。新增 AST 架构门禁，逐文件检查 `nodes.py`、`product_solver.py`、`product_collect.py` 和 `product_bone_collect.py` 不得导入 `specs`、`solver`、`native_context`、`interaction_scope` 或 `shadow_pipeline`。Blender 5.2 / Python 3.13 的 BoneCloth 约束 900 帧双跑仍通过，摘要保持 `5b16bbe0110606bfd1cb0a5364f925d93cdad4b2793bc89006a10bf0a3c0389e`。这只是旧 owner 删除前的第一批切断，不代表 `specs.py`、`solver.py`、context 或 native V0 binding 已删除；后续仍按 Bone plan 迁移三项真实缺口，再分步删除旧测试、owner、hidden task、aggregate 和 binding。4.5 / py311 继续冻结。

同一删除批次已移除纯 E1 `shadow_pipeline.py` 和 `test_blender_mc2_domain_shadow.py`；`solver.py` 不再接受 `shadow_compile` 开关。原 shadow 对照职责由 Domain golden、product mixed soak 和纯静态 partition 测试承接，`acceptance_assets_v1.json` 已改指当前 Blender 5.2 产品 runner。旧 V0 `solver.py`、`native_context.py`、`interaction_scope.py`、`specs.py` 仍因长跑数值缺口保留，不能把本批 shadow 删除误解为旧 owner 全部删除。

E7-CPU native 别名清理（2026-07-24）：`mc2_mesh_static_fingerprint_v0` 与 `mc2_bone_static_fingerprint_v0` 仅是 v1 的迁移别名，产品、native context 和公开节点均无消费者；已删除 C++ 实现、API 声明、nanobind 注册，并把旧 native 测试改为直接验证 v1 形状。Blender 5.2 当前源码审计显示 legacy surface 从 `70 bindings` 降为 `68 bindings`，仍有 `5 个 context TU`；随后已按 `vs2022-py313-native` 刷新 `_Lib/py313`，运行时核验 v1 存在且两个 v0 别名均不存在。4.5/py311 仍冻结，不在本阶段构建。下一步先完成旧 solver/debug 测试迁移，再按清单删除剩余 binding/TU。

本轮进一步确认 `specs.py` 没有应迁出的中立合同：它只包含 `MC2TaskSpec`、构造器和旧 V0 去重函数。`MC2TopologySpec`、`MC2StaticInputFingerprint`、参数和帧输入合同分别由 `topology.py`、`parameters.py`、`frame_state.py` 持有；resolved partition 的 topology/setup 路径不再导入 `specs.py`。新增门禁锁定这一边界，避免为了形式迁移重新制造第二套 schema。

MC2 DomainV1 的 task-reference Teleport 已接入统一产品执行顺序：task pass 先于 Center，随后才进入固定的 Center、约束、碰撞、self 和 post/history 流水线。Reset/Keep 的 native 数据合同、whole-domain self 一次失效和零 substep 行为已由 Python 3.13 native、ProductSlot、DomainOwner、E3 golden 及 Blender 5.2 产品验收锁定。

产品证据已经从旧 mixed runner 进一步拆开：单 source 三 setup 负责 BoneCloth/BoneSpring 的 root reference、Reset/Keep、速度和写回；MeshCloth 两 source product runner 负责真正的 partition scope 隔离。MeshCloth source 的动画变化使用 BasePose proxy，避免静态 source fingerprint 变化造成域替换。Capability matrix 的 `particle_subset_scope_exact` 仅声明 MeshCloth 适用，Bone 包装的“一 Armature 一统一域”限制保持显式。

当前门禁：Python 3.13 native `30/30`、ProductSlot `13/13`、DomainOwner `9/9`、Domain E3 golden `10/10`、capability matrix `3/3`，Blender 5.2 单 source Teleport 与 Mesh 两 source 分区隔离双跑均通过。BoneCloth/BoneSpring 删除前 plan 已补齐，下一阶段先迁移旧 runner helper，再做 E7-A/E7-S。4.5 / Python 3.11 暂停编译和验收，待 E7-CPU 删除旧 owner 前的最终收尾再恢复双 ABI；P4 不实施，E6 GPU 不提前启动。

## E7-CPU 当前收口（2026-07-24）

本轮已将 whole-domain self 的产品证据登记到 capability matrix：MeshCloth 使用三 setup mixed-output 900 帧 runner，BoneCloth 使用独立的 product self-contract runner。两条证据都锁定 finite、deterministic 与 `whole_domain_self_step_active`；BoneCloth 还直接检查 derived-radius、cloth mass 和 owner 的 self-step 计数。self capability 仍明确标记为 `gap`，因为跨任务 scope、contact cache 有界性和 radius consistency 尚未有独立产品断言，不能由旧 V0 soak 代替。

当前旧 Python 测试仍有 `native_context`、`specs`、`solver` 的直接断言，主要集中在 debug-draw、property-registry 和 base-pose/Center 的长跑细节；Bone static/frame、Mesh final-proxy 以及 base-pose proxy 输入隔离已分别迁移到 product-only runner。剩余断言必须逐项迁移为 DomainV1/ProductSlot/产品 readback 证据后，才能删除 `solver.py`、`native_context.py`、`interaction_scope.py`、`specs.py` 及剩余 V0 binding/TU。产品运行时的 E7 reachability 仍为零，故下一批只处理测试所有权和独立断言，不改变 Physics World/OmniNode 边界。

本轮已先处理 Bone frame 入口：旧 N3 顶层脚本改为调用公开 Bone product soak 的兼容门面，并增加静态门禁禁止回引 V0 owner。缩放、负缩放继承和剪切 pose 等原 N3 的独立输入断言没有被伪造为“已迁移”，仍列入下一批 product frame runner 的明确任务。

Bone rotation output 的产品证据也已接入：BoneCloth/BoneSpring 各跑 600 帧，显式检查 `rotational_interpolation`、`root_rotation` 的编译参数、fixed/move/leaf 目标集合、位置不变性和旋转输出差异；5.2 双 setup 摘要分别为 `527f1c71e3bcc37dab771bc7bd2a3ef0d52b2956aff1f1cdff3e6a999ecd53b8` 与 `0a87b35a5fddc7b12318b200d21ec328810e66877dda1ad2566884126f25355b`。Bone gravity axes/falloff 也已由 BoneCloth product runner 锁定；BoneSpring 按节点合同不消费世界重力。self collision 的 scope/cache/radius gap 仍单独保留。

Bone frame transform 的独立断言也已迁移到 product partition：验证 world pose、只读 frame packet、负 scale、零 scale、父级负 scale 和 shear-free 拒绝；旧 N3 facade 现在只转发 `test_bone_product_frame_transform_contract`，不再以约束 soak 冒充 frame 输入等价。
MC2 Bone static 旧 Blender 入口已完成 product-only 收口：静态拓扑/fragment/collector 断言转由 `mc2/test/test_bone_product_static.py` 与 `test_blender_mc2_bone_product.py` 承担，并保留批量 Bone writeback 失败回滚断言；旧入口只保留兼容门面，不再创建 V0 task 或读取 `native_context`。Blender 5.2/py313 验收通过。剩余旧测试所有权仍集中在 base-pose、final-proxy、debug-draw、property-registry 和长跑数值细节，未提前删除旧 owner。
Mesh final-proxy 旧 Blender 入口已完成 product-only 收口：Tier A proxy/UV/Pin oracle 由 `mc2/test/test_mesh_final_proxy.py` 承担，实际 Blender base-pose、MeshCloth product program、GN 写回、同槽参数更新和静态输入变化由 `test_blender_mc2_mesh_product_static.py` 承担；旧入口只保留兼容门面。5.2/py313 已通过，统一 owner 在静态输入变化时保持槽位稳定，未继承旧 V0 native handle 替换断言。
Mesh base-pose 旧 Blender 入口已完成 product-only 收口：Armature 驱动的缓存 proxy 隔离、拓扑 token 修复、只读 frame snapshot、负 scale 与首帧 MeshCloth 产品写回由 `test_blender_mc2_mesh_product_base_pose.py` 承担；旧入口只保留兼容门面。5.2/py313 已通过。旧 base-pose 文件中依赖 V0 owner 的 Center/Reset/Keep 长跑细节仍由后续产品 runner 逐项承接，不能由本次输入合同迁移提前宣称全部等价。

Mesh gravity 产品证据已迁移到 `test_blender_mc2_mesh_product_constraint_soak.py::test_mesh_product_gravity_axes_falloff`：Blender 5.2/py313 以公开 collector、动态产品槽和 DomainV1 owner 完成 600 帧双跑，校验 gravity 方向/强度/falloff 的参数 SoA、有限性、确定性及 X/Z 方向轨迹差异。capability matrix 已切换该 runner；Mesh Angle/rest 精确断言仍保留为旧 runner 的下一项迁移任务，4.5/py311 继续冻结。

Mesh Angle Restoration 的 attenuation 与 gravity-falloff 产品证据已接入：`test_blender_mc2_mesh_product_angle_motion.py` 在 Blender 5.2/py313 各完成 600 帧双跑，直接校验编译参数、有限性、确定性和响应差异，capability matrix 已移除对应旧 runner 引用。target/rest 精确 debug 断言仍保留在删除前清单中，未由响应差异测试替代。
