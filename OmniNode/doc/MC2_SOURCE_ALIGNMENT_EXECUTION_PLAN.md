# MC2 源码对照与执行计划

更新日期：2026-07-11

文档状态：**当前 MC2 实施的权威执行计划**。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文回答“下一步先查什么、冻结什么契约、通过什么门槛后才能写代码”。物理世界长期架构由 `PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 定义，当前落地状态由 `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` 记录。`MC2_DESIGN_AND_WORKSHEET.md` 只保留旧 MeshCloth 迁移审计、公式参考和历史踩坑，不再决定新 `physicsWorld.mc2` 的实现顺序或数据结构。

## 核心结论

1. 新 MC2 不能继续按“先设计一个看起来合理的 spec，再补源码解释”的顺序推进。每个静态数组、运行时数组和重建条件都必须先定位 MC2 的生产者、消费者和生命周期。
2. `SelectionData`、`VertexAttribute`、baseline、depth、distance constraint 和 bending constraint 是不同阶段的数据。不能因为最终都表现为逐顶点或逐约束数组，就提前合并进一个 `SelectionSpec` 或简化的 topology spec。
3. `MeshCloth`、`BoneCloth`、`BoneSpring` 仍是一个 solver 的三种 setup；共享的是运行时粒子与约束求解模型，不代表三种 setup 的代理网格生成过程相同。
4. 新运行时只保留 C++ 解算实现。Python 负责 Blender 输入冻结、slot 生命周期、native buffer 打包、result stream、writeback plan 和 debug；旧 Python/C++ MeshCloth 只能作为对拍材料。
5. 任何“源码对齐”声明都必须同时带源码位置、输入域、已知偏差和测试 oracle。只有形状测试、self-consistency 测试或 Blender smoke test 不能证明对齐。

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
| 帧调度 | `SimulationManagerNormal.cs`、`SimulationManagerSplit.cs` | 每 step 的 team/collider/predict、baseline、tether、distance、angle、bending、collision、distance、motion、post 顺序明确。 | 旧 solver 有参考实现；新 solver 尚无 native context/step。 |
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

目标：用旧 MeshCloth 作为数值 oracle，完成一条真实 Physics World 输出链。

范围：单对象、用户提供低模 proxy、固定点、无 collider 的第一版；native result 发布对象局部 offset，统一 GN writeback 消费。随后按 tether/angle/bending/collider/self collision 的依赖顺序扩展。

退出门槛：首帧、连续帧、same-frame、参数热更新、topology/pin 重建、reset、dispose、写回失败回滚全部通过；代表场景与旧 solver 逐帧对拍。

### S6 BoneCloth 与 BoneSpring

目标：复用同一 native core，只增加 setup adapter、proxy topology 和 bone result mapping。

顺序：Bone Line -> BoneSpring 强制参数 -> BoneCloth Automatic/Sequential mesh。复杂 bone mesh mode 必须复用 S3 的源码 golden fixtures，不能另写近似连接器。

退出门槛：同一 context schema 覆盖三 setup；PoseBone writeback 只消费 result stream；BoneSpring 没有第二 solver identity 或第二套粒子状态。

### S7 完整能力与旧路径删除

范围：collider、self/inter collision、多对象/多 center、wind/inertia 完整语义、性能、debug、bake/export。每项仍按源码 worksheet -> 契约 -> oracle -> native -> integration 的顺序推进。

旧 solver 只有在新路径通过等价场景、生命周期、性能和写回验收后才能删除；不保留长期 shadow pipeline。

## 未决决策

| ID | 问题 | 当前状态 | 决策前禁止事项 |
|---|---|---|---|
| D-01 | 是否公开 MC2 的 SequentialNonLoopMesh(mode 3)？ | 未决。源码存在，当前 HoTools 仅 0..2。 | 不得把 0..2 称为完整 BoneConnectionMode。 |
| D-02 | Blender vertex group 是否直接映射 proxy vertex，还是先形成独立 SelectionData 再做空间映射？ | 未决。低模同拓扑时直接映射更便宜，但属于 HoTools 偏差。 | 不得把直接索引映射称为 MC2 SelectionData 等价实现。 |
| D-03 | 用户输入 mesh 是否永远视为最终 proxy？ | 倾向是。 | 不实现 MC2 reduction/render mapping；文档必须说明输入域。 |
| D-04 | Normal/Split 调度是否只迁移共同数学顺序？ | 倾向是。 | 不照搬 Unity Job/TeamManager 结构到 Python。 |
| D-05 | 第一版 native context 的最小 constraint 集合是什么？ | 等 S1 后确定。 | 不先冻结 ABI 或 capability 字段。 |

## 每阶段提交规则

1. 一次提交只关闭一个经过 worksheet 审查的阶段或子阶段。
2. 提交说明必须指出 MC2 source entry、HoTools deviation 和测试 oracle。
3. capability/declaration、slot 数据、native binding、debug 和测试作为同一交付单元更新。
4. 文档不得在测试只验证 shape/count 时写“完美对齐”或“高度对齐”。
5. 遇到源码不清楚的行为，先补最小复现或静态 oracle，不用猜测补齐。

## 下一步

下一轮不继续写 B4 solver 代码。先完成 S1 的前三张 worksheet：

1. Bone connection mode 到最终 lines/triangles 的完整生成规则；
2. SelectionData -> proxy attributes -> baseline parent/root/depth 的阶段边界；
3. proxy topology -> DistanceConstraint/TriangleBendingConstraint 数据数组。

三张表审查通过后，再决定当前 B4 工作区改动是拆分重写还是整体移除。
