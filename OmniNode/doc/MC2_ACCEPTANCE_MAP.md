# MC2 验收总表

更新日期：2026-07-16

基线：MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文是新 `physicsWorld.mc2` 的**完成度与验收结论单一事实源**。它按可交付能力切片，不按源码文件或提交记录展开。未完成工作顺序见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`，源码 producer/consumer、边界特化与 oracle 细节见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 写作边界

- **应该写**：每个能力切片的当前结论、支持域、已有证据、剩余差异、是否阻塞V1-R，以及结论变更日期。
- **不应该写**：实现过程、下一步操作细节、公式/源码逐行语义、踩坑展开、公共Physics World架构或提交历史。
- **内容路由**：未完成工作的顺序与退出条件写`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`；源码事实、特化、故意差异和冲突处理写`MC2_SOURCE_DATAFLOW_WORKSHEETS.md`；跨solver公共规则写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；历史过程只留Git。
- **更新原则**：只有代码和相应层级证据已经成立，才能更新本文结论；不能把计划、推测或邻近能力写成完成事实。

## 验收范围

当前目标是 `V1-R`（restricted realtime）：单一 MC2 solver、MeshCloth/BoneCloth/BoneSpring 三种 setup、单 final-proxy Mesh、MC2 source Bone Line与HoTools ordered-chain BoneCloth产品拓扑、外部 Point/Edge collider、单 cloth self collision、实时 Mesh/Bone writeback。

以下不阻塞 `V1-R`：Bake、通用力场、Bone imported triangle、MC2 reduction/render mapping。它们必须保持明确的未支持状态，不能由现有能力外推为已完成。跨物体self collision已进入产品替代范围，由K-06阻塞删除准入。

上述source范围不等于旧HoTools产品替代范围。删除旧实现还必须通过P-04..P-08；旧实现中实际可用但超出当前source restricted范围的能力，只有在明确产品决策、可见拒绝行为和迁移说明成立后，才允许作为故意缩域处理。

## 状态口径

| 状态 | 含义 |
|---|---|
| `完全对齐` | 声明域内已有直接 Tier A 证据，且 Host、native、Blender 生产链全部闭环。 |
| `限定域对齐` | 明确限制输入域后满足“完全对齐”；限制外不宣称支持。 |
| `实现完成/证据缺口` | 生产链已接通，但缺独立 Tier A 或仍有源码语义待核账。 |
| `产品收尾` | 数值能力已具备，尚缺真实资产、稳定性、性能或旧路径清理验收。 |
| `待审计` | 已有实现或局部证据，但尚未完成产品语义、生产可达性、性能或独立性核账，不能据此宣称可替代旧实现。 |
| `未来扩展` | 不在 `V1-R` 范围，当前必须保持 inactive。 |
| `拒绝` | 已知输入域不成立，在进入 native 前显式报错。 |

“完全对齐”只描述表中写明的范围，不表示完整复制 Unity object、job、render mapping 或 editor 层。

## 总览

| ID | 能力切片 | 当前结论 | 已有证据 | 剩余差异/退出条件 | 阻塞 V1-R |
|---|---|---|---|---|---|
| C-01 | 单solver step / 多task / task-owned context | 完全对齐 | task规整去重、全量只读prepare、一次world写事务、per-task slot/context、staged replace、dispose/soak | MC2 component映射为profile+task组合；一次step处理全部active tasks，各task状态隔离且任一prepare失败不产生半更新 | 否 |
| C-02 | 帧生命周期、same-frame、reset、失败回滚 | 完全对齐 | py313 lifecycle + Blender 5.1 首帧/连续帧/倒放/重建 | 无 | 否 |
| C-03 | scheduler、多子步、一次提交 | 完全对齐 | Tier A scheduler + py313 + Blender 5.1 单/三子步 | 无 | 否 |
| C-04 | N2 参数 ABI 与热更新 | 限定域对齐 | 两组 Tier A 参数 dump、slot 热更新 | wind 与 sync 字段仅兼容占位，不计 active 能力 | 否 |
| C-05 | Center/Inertia、anchor、teleport、signed component | 限定域对齐 | Tier A Center/step fixtures + py313 + Blender 5.1 | 仅支持已声明的无 shear、非零 scale 域 | 否 |
| S-01 | Mesh final proxy、UV/Pin、拓扑签名 | 限定域对齐 | Tier A static fixtures + staged native upload + Blender 5.1 | 单 final proxy；UV seam 与拓扑变化按契约拒绝/重建 | 否 |
| S-02 | Mesh baseline 与双对象 BasePose | 限定域对齐 | Tier A baseline/rotation + py313 + Blender 5.1 GN链 | 每 vertex 属于 triangle；禁止反馈与改拓扑 modifier | 否 |
| S-03 | Bone connection 与产品拓扑 | 限定域对齐 | 8组Tier A source connection + HoTools链序/成环/拒绝fixture + Blender 5.1多链static/native/atomic writeback | `mc2_source`保持Line/imported-triangle拒绝域；`hotools_product`支持按名称/链组/节点顺序的纵横连接与稳定UV triangle；viewport显示由D-01跟踪 | 否 |
| S-04 | BoneCloth Line 与 BoneSpring setup | 限定域对齐 | shared static/native/result 链、N2 override、Blender 5.1 | BoneSpring 固定 Line、Sphere-only；不扩张到 triangle | 否 |
| S-05 | Bone imported triangle | 拒绝 | 固定源码证明全零 UV 导致 tangent/basis 退化 | 未来若改变产品策略，必须先建立真实 producer/oracle | 否 |
| N-01 | prediction、Pin、constraint 顺序与 post | 完全对齐 | Tier A 双子步顺序 + native V0 + Blender 5.1 | 无 | 否 |
| N-02 | Tether | 完全对齐 | 直接Tier A runtime + py313 native + Blender 5.1 production solve | stretch/compression、Fixed/missing-root gate与velocity-reference attenuation均闭环 | 否 |
| N-03 | Distance | 完全对齐 | 7组static、2组ordered runtime、Tier A双子步frame与native双阶段执行 | correction按0.3 attenuation进入velocity-reference，post消费并跨子步提交 | 否 |
| N-04 | Angle | 完全对齐 | 直接Tier A runtime + py313 native/V0 + Blender 5.1 Mesh/Bone solve | 双baseline、Fixed root、Restoration+Limit、falloff/attenuation与scratch clear均闭环 | 否 |
| N-05 | Triangle Bending | 完全对齐 | 3组 Tier A runtime + static role/order + native fixed-point sum | 无 | 否 |
| N-06 | Motion | 完全对齐 | 直接Tier A runtime + py313 native/V0 + Blender 5.1 Fixed Mesh | MaxDistance、Backstop、depth²采样、rotated axis、Fixed/InvalidMotion与0.95 attenuation闭环 | 否 |
| K-01 | 外部 Point/Edge collider | 限定域对齐 | py313 四 primitive/数值 + Blender 5.1 Mesh/Bone | 当前声明域不含完整 Unity collider component lifecycle | 否 |
| K-02 | BoneSpring soft sphere | 限定域对齐 | py313 数值 + Blender 5.1 production | 只接受 Sphere 与 spring 专用 limit 语义 | 否 |
| K-03 | Self primitive/grid/hash/broadphase | 限定域对齐 | raw/Tier A static + py313 hash/candidate + Blender 5.1 | 单 cloth FullMesh 域 | 否 |
| K-04 | Self EE/PT contact、4轮 solve/sum | 限定域对齐 | half contact、手算 fixed-point、后续 substep fixtures | 单 cloth FullMesh 域 | 否 |
| K-05 | Self 跨帧 Intersect | 限定域对齐 | py313 三帧反馈 + Blender 5.1 final-substep gate | 单 cloth、固定分片调度 | 否 |
| K-06 | 跨物体self collision scope | 待审计 | 单次solver step可见全部active tasks，但当前primitive/contact仍归各task context且只闭环单cloth；sync参数尚无生产consumer | 比较集中式跨task broadphase的自动互碰、显式ListObj partner graph及必要时group/mask分区，冻结pair ownership、动态增删、调度和节点API | 是 |
| K-07 | 普通碰撞半径与self thickness产品模型 | 待审计 | 普通`radius`当前服务外部collider接触；`self_collision_thickness`服务self primitive/contact，二者consumer不同 | 审计双半径是否必要、是否派生自同一顶点组+数值半径、能否合并或由collider替代；以物理覆盖、性能和debug可读性决定 | 是 |
| O-01 | Mesh result transaction 与 GN writeback | 完全对齐 | candidate/envelope、发布回滚、拓扑失败恢复、Blender 5.1 | 无 | 否 |
| O-02 | Bone result transaction 与 PoseBone writeback | 限定域对齐 | stable identity、parent-local plan、批次回滚、signed component及同Armature多component合并 Blender 5.1 | component骨名必须不重叠；同目标按全部target pose重算parent-local plan并一次写回 | 否 |
| O-03 | `mc2_stats_v0` | 完全对齐 | schema、聚合、稳定排序、事务回滚 | stats 不得替代真实 writeback ready 语义 | 否 |
| D-01 | 全隐式中间态debug | 待审计 | 当前`mc2/debug.py`仅`framework_only`；slot有摘要，native已有部分self readback但未形成完整viewport链 | 对齐SpringBone VRM的request-driven next-frame capture；覆盖连接、约束、碰撞/自碰、teleport、变换抵消、Center和writeback，且无请求时零readback | 是 |
| P-01 | V1-R 直接 oracle 闭环 | 完全对齐 | static/runtime主体及Distance/Tether/Angle/Motion direct runtime均有Tier A | 无 | 否 |
| P-02 | 真实生产资产验收 | 完全对齐 | V1-R结构化manifest + Blender 5.1五脚本门禁，覆盖六资产/三setup | Mesh、Bone source Line、BoneCloth产品链、BoneSpring soft sphere及final-proxy/component拒绝域均可重复执行 | 否 |
| P-03 | 新链路混合 soak 与绝对性能门禁 | 完全对齐 | Blender 5.1三setup混合180帧：2次hot update/rebuild/reset/same-frame、6 context释放 | 170样本mean 4.44ms、p95 5.02ms、max 6.43ms；这里只证明新链路稳定且低于自身ceiling，不代表优于旧实现 | 否 |
| P-04 | 旧产品语义与新实现替代审计 | 完全对齐 | profile+task component、全量prepare/失败原子性、per-task context、HoTools链组产品拓扑、同Armature多component合并写回及Blender 5.1生产fixture | 跨物体self collision与半径模型分别由K-06/K-07决策；隐式可视化由D-01关闭，不再回退产品语义 | 否 |
| P-05 | 新实现生产可达性、代码与math审计 | 待审计 | 代表性资产和soak证明主链可运行；当前Python模块存在大量参数转发、过细职责和重复/同名math包装候选 | 逐功能区核对真实入口、状态所有权、异常/释放、死代码；在不改变行为前提下合并垃圾转发、文件碎片和重复helper，并证明生产结果不变 | 是 |
| P-06 | 新旧性能对比与C++边界审计 | 待审计 | 只有新实现绝对耗时baseline | 同资产同配置比较构建、逐帧各阶段、debug开销、内存与分配；加入跨物体self collision两种scope原型，证明不退化且有明确优势，按实测决定Python批量化或C++迁移 | 是 |
| P-07 | 文件与ABI独立化 | 待审计 | 新Physics World Python路径当前未直接import旧package，但旧节点仍注册，旧native ABI及测试仍共存 | 新生产链、测试和构建对待删除package/context/公开ABI零依赖；共享kernel必须转为新owner而非悬挂在旧接口下 | 是 |
| P-08 | 替代资格总门禁 | 待审计 | P-01..P-03只证明source主体、新资产门禁和新链soak | P-04..P-07、K-06/K-07和D-01全部关闭，并形成“产品语义可替代、交互模型清晰、debug可观测、性能有优势、架构可维护、允许删除”的明确结论 | 是 |
| P-09 | 旧 MC2 路径删除 | 产品收尾 | 尚未准入删除 | 仅在P-08放行后独立删除旧节点/package/full-core/context/shadow pipeline；删除后全门禁通过 | 是 |
| P-10 | declaration 验收开关 | 产品收尾 | `mc2` 已注册并发布三类结果 | P-01..P-09及全部阻塞能力行关闭后将`solver_acceptance_blocker`改为`False` | 是 |
| X-01 | Bake/export | 未来扩展 | `supports_bake=False` | 独立冻结 bake 时间轴、缓存与导出契约 | 否 |
| X-02 | 通用力场（含 wind） | 未来扩展 | N2 仅保留兼容字段 | 等待 Physics World 公共力场快照，再接 adapter/native/oracle | 否 |

## 当前验收结论

`V1-R` 的直接数值oracle、代表性生产资产、新链路混合soak及BoneCloth产品语义已经闭环，但这些证据尚不足以证明新实现可以替代旧HoTools产品。当前必须继续完成 **跨物体self collision与半径模型、全隐式debug、完整代码/运行链与纯整理、新旧性能、C++边界和文件独立性审计**；在替代资格总门禁放行前不得删除旧实现，`solver_acceptance_blocker=True` 保持正确。

当前开放阻塞：

1. `K-06/K-07`：决定跨物体self collision scope及统一、派生或分离的半径模型。
2. `D-01`：完成与SpringBone VRM同型、但分层更丰富的全隐式中间态debug。
3. `P-05`：完整生产可达性审计与不改变行为的Python转发/math/文件整理。
4. `P-06`：新旧同场性能、自碰撞scope原型及Python/C++边界决策。
5. `P-07/P-08`：文件级独立化与替代资格总门禁。
6. `P-09/P-10`：获得准入后删除旧实现并关闭acceptance blocker。

## 更新规则

1. 任何改变能力完成度、支持域或验收阻塞的 MC2 提交，必须同步更新本表对应行。
2. 新测试只有在证明该行所需层级时才能改变结论；shape/count、自洽测试或旧 solver 输出不能把状态升级为“完全对齐”。
3. 现有文档互相冲突时，本表先降级为“实现完成/证据缺口”，再以固定 MC2 source 与新 oracle 核账；不得选择较乐观的描述直接结案。
4. 长篇执行记录不再承载总体完成度。完成项从“当前切入点”移出后，只在本表保留结论与证据摘要。
5. 每次验收冲刺先关闭本表的阻塞行，不因未来扩展项增加而改变 `V1-R` 范围。
