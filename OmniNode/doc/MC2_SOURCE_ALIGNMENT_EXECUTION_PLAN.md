# MC2 源码对照与执行计划

更新日期：2026-07-11

文档状态：**当前 MC2 实施的权威执行计划**。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

S1 的逐字段 producer/consumer 记录见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

S2 的 host/native 边界草案见 `MC2_HOST_NATIVE_CONTRACT_DRAFT.md`。其中 draft 字段和 open decisions 必须经人工审查，不能直接当作已实现 ABI。

本文回答“下一步先查什么、冻结什么契约、通过什么门槛后才能写代码”。物理世界长期架构由 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 定义，当前落地状态由 `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` 记录。`MC2_DESIGN_AND_WORKSHEET.md` 只保留旧 MeshCloth 迁移审计、公式参考和历史踩坑，不再决定新 `physicsWorld.mc2` 的实现顺序或数据结构。

## 核心结论

1. 新 MC2 不能继续按“先设计一个看起来合理的 spec，再补源码解释”的顺序推进。每个静态数组、运行时数组和重建条件都必须先定位 MC2 的生产者、消费者和生命周期。
2. `SelectionData`、`VertexAttribute`、baseline、depth、distance constraint 和 bending constraint 是不同阶段的数据。不能因为最终都表现为逐顶点或逐约束数组，就提前合并进一个 `SelectionSpec` 或简化的 topology spec。
3. `MeshCloth`、`BoneCloth`、`BoneSpring` 仍是一个 solver 的三种 setup；共享的是运行时粒子与约束求解模型，不代表三种 setup 的代理网格生成过程相同。
4. 新运行时只保留 C++ 解算实现。Python 负责 Blender 输入冻结、slot 生命周期、native buffer 打包、result stream、writeback plan 和 debug；旧 Python/C++ MeshCloth 不属于兼容目标、验收 oracle 或运行依赖。
5. 任何“源码对齐”声明都必须同时带源码位置、输入域、已知偏差和测试 oracle。只有形状测试、self-consistency 测试或 Blender smoke test 不能证明对齐。

## 2026-07-11 实施检查点

当前 Python/host 侧已经关闭 MeshCloth N0 静态构建的第一条可信链路：

- `tools/mc2_unity_oracle` 已用固定 MC2 checkout 导出 `VirtualMeshProxy.cs::ConvertProxyMesh()` Tier A fixtures；商业 MC2 源码仍只作为外部只读对照，不进入仓库。
- `physicsWorld/mc2/setups/mesh_cloth/final_proxy.py` 已实现 final-proxy finalization：triangle direction、edge union、vertex-to-vertex 顺序、vertex-to-triangle flip records、final normal/tangent、bind pose、UV seam gate 和 pin attribute 直接 index 映射。
- `physicsWorld/mc2/mesh_baseline.py` 已消费 final proxy 并生成 baseline parent/child、baseline ranges/data、root/depth、local pose 和 `ZeroDistance` attribute 补写。
- `physicsWorld/mc2/setups/mesh_cloth/static_build.py` 已把 Blender Mesh final proxy -> `MC2ProxyStaticSpec` -> `MC2BaselineStaticSpec` 组合为 slot static bundle；`step_mc2()` 在真实 Mesh task rebuild 时缓存 `slot.data["mesh_static"]`，但仍不创建 native context、不 step、不发布 result。
- Blender Mesh adapter 已验证 n-gon triangulation 不新增 vertex、vertex group pin 使用同一 vertex index、loop-domain UV seam 必须由用户拆 proxy vertex、Armature/BasePose 双对象 + 常驻 GN 路径不反馈物理 offset。

这意味着“是否能从 Blender Mesh 得到可信 N0 static bundle”已经落地；尚未落地的是 N1 constraint static、N2 runtime parameter ABI、N3 dynamic rotation/frame adapter、native context 生命周期和 result/writeback 闭环。后续不应再回头扩展旧 B4 selection/constraint 近似模型。

## 文档与事实优先级

发生冲突时按以下顺序判断：

1. 固定 commit 的 MC2 源码行为。
2. `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 的 HoTools 长期架构硬约束。
3. 本文已经审查通过的映射和阶段门槛。
4. `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` 的当前代码状态。
5. 旧实现、旧文档和现有测试中的历史假设。

“HoTools 刻意偏离 MC2”可以成立，但必须登记为显式决策，不能写成源码等价。

## 2026-07-10 工作区审查结论

当前提交基线已经包含参数契约、topology/slot 生命周期和 particle buffer 框架。工作区另有一批未提交的 B4 selection/constraint topology 实现。现有 Blender 后台测试 9/9 通过，但 B4 **不满足提交条件**。

| 区域 | 审查结论 | 处理方式 |
|---|---|---|
| 已提交参数契约 | 可作为审计起点，尚不能整体标记为 source-aligned。 | 保留；在 S1 做字段级生产者/消费者复核。 |
| 已提交 topology/slot | slot 生命周期方向与 Physics World 契约一致；静态 topology 的内容仍是 HoTools 预备格式。 | 保留生命周期；不得把当前数组集合冻结成 native ABI。 |
| 已提交 initial state/particle buffer | buffer owner/dispose 方向可保留；字段、初始化时机和 reset 语义仍需逐项对照 particle registration/reset job。 | S2 前只视为 framework scaffold。 |
| 未提交 B4 selection | 把 MC2 的 SelectionData/VertexAttribute 与后续 baseline parent/depth 合并到同一 spec，阶段边界不成立。 | 不提交；等待 S1/S2 契约审查后重写或拆分。 |
| 未提交 B4 BoneCloth mesh connection | AutomaticMesh 缺少 MC2 的反转续排逻辑；同层连接与三角形生成被简化成 source 顺序 zip。 | 不提交；先建立源码 golden cases。 |
| 未提交 B4 distance/bending | Mesh 边全部标为 structural，缺 parent-based vertical/horizontal 分类、shear 生成、属性过滤；bending 只保存邻接四元组，缺 rest angle/volume/sign/filter。 | 不提交；按 `CreateData()` 实际输出重新设计。 |

这批未提交代码暂时保留在工作区作为审查材料，不把它当作后续阶段的既成接口。

## MC2 源码执行地图

下面是开始实现前必须掌握的主路径。函数名以固定源码 commit 为准。

| 阶段 | MC2 权威入口 | 已确认事实 | HoTools 当前状态 |
|---|---|---|---|
| 参数归一化 | `Runtime/Cloth/ClothSerializeDataFunction.cs::GetClothParameters()` | BoneSpring 覆盖与通用 cloth 参数在进入运行时前完成。 | 已有 effective parameter scaffold，待字段级复核。 |
| setup 输入 | `Runtime/Manager/Render/RenderSetupData.cs` | Bone connection mode 实际包含 Line、AutomaticMesh、SequentialLoopMesh、SequentialNonLoopMesh。 | 当前公开 0..2；是否支持 mode 3 尚未决策。 |
| Bone 代理拓扑 | `Runtime/VirtualMesh/Function/VirtualMeshInputOutput.cs::ImportFrom(RenderSetupData, ...)` | Line 直接用父子边；mesh mode 先排序 root，再按层级、距离和 root 邻接规则建 link，最后按角度和 main-edge 条件成面。 | B2/B4 是简化模型，不可称为等价。 |
| authoring selection | `Runtime/Cloth/SelectionData.cs`、`Runtime/VirtualMesh/VertexAttribute.cs` | SelectionData 持有 positions、attributes、maxConnectionDistance；Fixed/Move 只是 attribute bit 的一部分。 | 当前没有独立的 authoring selection 数据模型。 |
| selection 映射 | `VirtualMeshProxy.cs::ApplySelectionAttribute()` | SelectionData 通过空间搜索映射到 proxy vertex，不携带 baseline parent/depth。 | B4 直接按 Blender 顶点索引映射，属于 HoTools adapter，必须显式标记偏差。 |
| baseline | `VirtualMeshProxy.cs::CreateMeshBaseLine()`、`CreateTransformBaseLine()` | Mesh parent 由 fixed 起点、层级传播、距离/夹角成本生成；Bone parent 来自 Transform 层级。 | B4 Mesh 使用普通 BFS；不等价。 |
| root/depth | `VirtualMeshProxy.cs::CreateVertexRootAndDepth()` | depth 是到 fixed root 的累计几何长度除以全体最大长度；同时生成 vertexRootIndices。 | B4 Bone 按每条 source 的离散层数归一化；不等价。 |
| Distance 数据 | `Runtime/Cloth/Constraints/DistanceConstraint.cs::CreateData()` | parent edge 为 vertical，其余邻接为 horizontal；过滤 invalid/全 fixed；相邻三角形还可能生成 shear；horizontal rest distance 用负号编码。 | B4 只有 pair/kind/rest length 简化表。 |
| Bending 数据 | `TriangleBendingConstraint.cs::CreateData()` | 邻接三角形先形成四点，再按属性与角度分类为 dihedral/volume，并存 rest value、sign 和 write mapping。 | B4 只有 triangle adjacency pair。 |
| 其它静态数据 | `InertiaConstraint.cs::CreateData()`、proxy mesh 的 baseline/local pose/root arrays | center/fixed、local pose、root 等数据参与后续 inertia、angle、tether 和 display。 | 尚未形成完整新契约。 |
| 帧调度 | `SimulationManagerNormal.cs`、`SimulationManagerSplit.cs` | 每 step 的 team/collider/predict、baseline、tether、distance、angle、bending、collision、distance、motion、post 顺序明确。 | 新 solver 尚无 native context/step；只以固定 MC2 source 与独立 fixture 为 oracle。 |
| 输出 | `VirtualMeshManager.SimulationPostProxyMeshUpdate*()` | line/triangle/world/local transform 输出路径不同。 | 新 solver 尚不发布 result。 |

## 对照记录格式

S1 开始后，每个要迁移的数据块都按同一个 worksheet 记录：

| 字段 | 要求 |
|---|---|
| MC2 producer | 精确到文件、函数/Job、生成条件。 |
| MC2 consumers | 列出所有读取点，不能只看一个 constraint。 |
| lifetime | authoring、build-time、slot static、frame、substep 或 scratch。 |
| setup domain | MeshCloth、BoneCloth、BoneSpring 或共享。 |
| representation | 类型、shape、单位、坐标空间、编码规则、排序稳定性。 |
| HoTools mapping | exact port、semantic equivalent、intentional deviation、deferred 四选一。 |
| dirty/rebuild | 哪些输入变化导致热更新、静态重建或 slot 重建。 |
| oracle | 最小输入、预期数组/数值、来源和容差。 |

没有完整记录的字段不得加入公开 capability、declaration persistent state 或 native ABI。

## 执行阶段

### S0 文档与工作区冻结

目标：停止继续扩展未经审查的 B4 代码，建立单一计划入口。

交付物：

- 本文成为 MC2 当前执行计划。
- 旧 MC2 文档降级为历史/公式参考。
- 实现状态文档与已提交 B3 scaffold 一致。
- B4 代码保持未提交并有明确审查结论。

退出门槛：文档职责无冲突；`git diff --check` 通过；不产生新的 solver 代码提交。

### S1 源码数据流审计

目标：从 setup 输入一直追踪到 constraint data 和运行时 consumer，不先设计 HoTools class。

当前进度：W1-W7 已完成第一轮审计，覆盖 Bone connection、Selection/baseline、Distance/Bending、Inertia center、particle registration/reset、output mapping 和 value parameter conversion；golden fixture v0 与 B1-B3 reverse audit 已同步扩展。尚缺可信 Tier A 运行宿主，以及 self-collision/collider/完整 frame order 等后续能力 worksheet。

顺序：

1. 参数：`ClothSerializeData -> ClothParameters`。
2. setup：RenderSetupData、bone transform 收集、mesh import。
3. proxy：selection apply、selection mesh、ConvertProxyMesh。
4. baseline：parent/child、baseline list、local pose、root/depth。
5. constraints：distance、bending、inertia、self collision 静态数据。
6. registration/reset：TeamData chunk、particle arrays、首次帧与 reset。
7. frame step：Normal 与 Split 两条调度路径的语义交集。
8. output：Mesh offset、Bone transform、display position/rotation。

退出门槛：所有计划进入第一版 native context 的数组都有 worksheet；Normal/Split 的差异已分类为数学语义或调度优化；未决问题进入决策表。

### S2 HoTools 契约审查

目标：在不写 solver loop 的前提下，冻结 host/native 边界。

必须拆开的数据域：

- authoring selection：Blender pin/paint 输入及其稳定签名；
- proxy vertex attributes：映射后的 MC2 bit flags；
- proxy topology：positions、edges、triangles、transform identity；
- baseline topology：parent/child、baseline ranges、root indices、depth；
- constraint data：MC2 实际使用的 packed/index/rest/sign/write arrays；
- particle persistent state：跨帧状态；
- frame/substep scratch：不得进入持久 spec；
- output mapping/writeback plan：不进入数值核心。

退出门槛：descriptor/capability/slot/native ABI 草案通过人工审查；每个字段有 producer 和 consumer；坐标空间与 dispose owner 明确；不得用 `dict` 模糊跨层契约。

### S3 静态构建与源码 oracle

目标：先证明 proxy/baseline/constraint data 与源码规则一致，再接解算。

MeshCloth 的 N0 builder 只消费用户 final-proxy 的静态 Mesh data：vertex identity、参考姿态、edge、triangle 与 attribute。Armature、Shape Key 等拓扑保持型基础变形产生的逐帧位置不进入 N0，也不得改变 topology signature；它们由 S5 的 Blender frame adapter 进入 N3。

最小 golden cases：

- MeshCloth：单三角形、双三角形方片、无 Fixed、一个 Fixed、多个 Fixed、断开岛。
- Bone Line：单链、分叉链、连续多个 Fixed、零长度父子边、不同链长。
- Bone AutomaticMesh：触发连续最近邻、触发过长边反转、闭环和非闭环。
- Bone Sequential：两链、三链 loop、不同层数、同层多分支。
- Distance：vertical/horizontal、shear、全 fixed/invalid 过滤、zero distance。
- Bending：普通 dihedral、超过阈值、volume 区间、退化三角形。

测试必须比较完整有序数组或规范化后的等价集合，不能只比较 count。

退出门槛：golden fixtures 覆盖三种 setup；B4 工作区代码已按新契约重写或删除；Blender 测试之外存在不依赖 UI 的静态数组测试。

### S4 Native context 最小闭环

目标：建立唯一 C++ context，但只接已审查通过的最小数组集合。

第一条闭环：create -> inspect -> reset -> step(no collision) -> read result -> dispose。先用内存 fixture，不接 Blender 写回。

要求：

- context 由 MC2 slot 唯一持有；
- topology/selection 变化重建，参数变化优先热更新；
- native 不读取 `bpy`，不保存 Python object；
- Python 不实现第二套 runtime solver；
- debug snapshot 只读 context 实际消费的数据。

退出门槛：连续帧、same-frame、reset、跳帧/倒放、异常回滚、dispose 测试通过；ABI 有版本和 shape 校验。

### S5 MeshCloth vertical slice

目标：以固定 MC2 source、独立 Tier A fixture 和新 Physics World 生命周期测试完成一条真实输出链。

范围：单对象、用户提供低模 proxy、固定点、无 collider 的第一版；native result 发布对象局部 offset，统一 GN writeback 消费。Mesh frame adapter 复用已验证的 BasePose 语义：为源对象维护同拓扑只读副本，保留 Armature/Shape Key 等基础变形，移除物理 GN offset；每帧从该副本的 evaluated mesh 读取动画基底，禁止直接从已含物理写回的源对象读取。随后按 tether/angle/bending/collider/self collision 的依赖顺序扩展。

退出门槛：首帧、连续帧、same-frame、参数热更新、topology/pin 重建、reset、dispose、写回失败回滚全部通过；至少有一个 Armature 驱动 final-proxy 用例证明动画基底逐帧变化、物理 offset 位于修改器栈末端且不会反馈进下一帧输入；数值行为由固定 MC2 source 的 Tier A fixture/最小场景验证，不要求与旧 solver 对拍。

### S6 BoneCloth 与 BoneSpring

目标：复用同一 native core，只增加 setup adapter、proxy topology 和 bone result mapping。

顺序：Bone Line -> BoneSpring 强制参数 -> BoneCloth Automatic/Sequential mesh。复杂 bone mesh mode 必须复用 S3 的源码 golden fixtures，不能另写近似连接器。

退出门槛：同一 context schema 覆盖三 setup；PoseBone writeback 只消费 result stream；BoneSpring 没有第二 solver identity 或第二套粒子状态。

### S7 完整能力与旧路径清理

范围：collider、self/inter collision、多对象/多 center、wind/inertia 完整语义、性能、debug、bake/export。每项仍按源码 worksheet -> 契约 -> oracle -> native -> integration 的顺序推进。

旧 solver/旧资产兼容不作为新路径交付门槛；可独立删除，不保留 adapter、资产迁移层或 shadow pipeline。新路径只检查新 schema、新 slot、新 native context 和统一 writeback 形成的生态。

## 未决决策

| ID | 问题 | 当前状态 | 决策前禁止事项 |
|---|---|---|---|
| D-01 | 是否公开 MC2 的 SequentialNonLoopMesh(mode 3)？ | 未决。源码存在，当前 HoTools 仅 0..2。 | 不得把 0..2 称为完整 BoneConnectionMode。 |
| D-02 | Blender vertex group 是否直接映射 proxy vertex，还是先形成独立 SelectionData 再做空间映射？ | **已决**：按输入 vertex index 直接映射 attribute。 | 这是 final-proxy 输入契约，不实现 MC2 SelectionData 空间重映射，也不将其称为通用 MC2 SelectionData 等价实现。 |
| D-03 | 用户输入 mesh 是否永远视为最终 proxy？ | **已决**：是。用户负责制作低模代理，solver 对输入 mesh 原样计算。 | 禁止 SelectionMesh、merge、reduction、optimization 和 render mapping；vertex count/order/topology 不得被 solver 改写。 |
| D-04 | Normal/Split 调度是否只迁移共同数学顺序？ | 倾向是。 | 不照搬 Unity Job/TeamManager 结构到 Python。 |
| D-05 | 第一版 native context 的最小 constraint 集合是什么？ | 等 S1 后确定。 | 不先冻结 ABI 或 capability 字段。 |
| D-06 | Tier A fixture host 放在哪里？ | **已决并落地**：`tools/mc2_unity_oracle`，Unity `6000.3.15f1`；只以外部 local package 引用固定 MC2 checkout。HoClothUnity 已废弃并排除。 | 不修改/运行 HoClothUnity 作为 oracle，不把其输出升级为 Tier A；MC2 商业源码永久忽略且不得提交。 |
| D-07 | Curve runtime representation 如何冻结？ | source 使用 16-float `float4x4` samples；HoTools 当前只保存 authoring curve payload。 | 不把当前 effective payload 直接作为 native ABI。 |
| D-08 | 骨架驱动 MeshCloth 的逐帧输入和 GN 写回如何隔离？ | **已决且唯一支持**：双对象 + 常驻 GN。静态拓扑来自 final-proxy Mesh data；逐帧 pose 来自永久移除物理 GN output 的同拓扑 BasePose evaluated snapshot；同帧 display/base 差值转 object-local offset 后在源对象修改器栈末端应用。 | 禁止 BlendShape 写回、单对象切换/移动 GN、读取已含物理 offset 的源对象 evaluated mesh、把动画 pose 写入 N0，或接受会改变 vertex identity/count/order/topology 的基础修改器。 |
| D-09 | Blender loop-domain UV 如何进入 MC2 逐顶点 UV？ | **已决**：不做拓扑转换。含 triangle 的 Mesh 要求同一 vertex 的所有 loop UV 在冻结容差内一致；不一致时报错，用户自行 split 代理顶点。line-only Mesh 可使用 zero UV。 | 禁止选择首 loop、平均 UV、自动拆点、改变 vertex count/order，或跳过 triangle normal/tangent finalization。 |

## 每阶段提交规则

1. 一次提交只关闭一个经过 worksheet 审查的阶段或子阶段。
2. 提交说明必须指出 MC2 source entry、HoTools deviation 和测试 oracle。
3. capability/declaration、slot 数据、native binding、debug 和测试作为同一交付单元更新。
4. 文档不得在测试只验证 shape/count 时写“完美对齐”或“高度对齐”。
5. 遇到源码不清楚的行为，先补最小复现或静态 oracle，不用猜测补齐。

## 下一步

不继续写 B4 solver 代码，不接旧物理、不接废弃 HoClothUnity、不提交 MC2 商业源码。当前 Mesh N0 final proxy、baseline 和 slot static cache 已完成，下一步优先整理并冻结后续文档契约：

1. N1 DistanceConstraint static：从固定 MC2 source 和现有 W3 worksheet 整理 per-vertex signed layout、vertical/horizontal/shear 生成规则、过滤规则和最小 Tier A fixture 清单。
2. N1 TriangleBending static：整理 ordered quad role、dihedral/volume 分类、rest value/sign/write mapping，不把当前简化 adjacency pair 当 ABI。
3. N2 runtime parameter ABI：把 `ClothParameters`、BoneSpring override、16-sample curve representation 和 HoTools scheduler settings 拆成明确 schema，先写字段表和 dirty policy，不写 C++ binding。
4. N3 Mesh dynamic adapter：在既有 BasePose evaluated snapshot 基础上，按 W2 local-pose 规则派生 `proxy_animation_world_rotations`，并明确 frame cache、restart 和 topology mismatch 行为。
5. Native context 前的最后门槛：更新 `MC2_HOST_NATIVE_CONTRACT_DRAFT.md` 的 S2 checklist，让每个即将进入 ABI 的字段都有 producer、consumer、shape、坐标空间、dirty/rebuild 和 oracle。

只有上述 N1/N2/N3 文档契约收口后，才进入 S4 native context 最小闭环；S4 的第一步也只允许 create/inspect/reset/read debug，不直接做完整 solver step。
