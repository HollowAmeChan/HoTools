# MC2 源码数据流 Worksheets

更新日期：2026-07-11

文档状态：**S1 源码审计记录**。本文记录固定 MC2 源码基线中的 producer、consumer、representation 和 lifecycle；它不直接冻结 HoTools class 或 native ABI。实施阶段与退出门槛见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

## 记录口径

| 状态 | 含义 |
|---|---|
| source fact | 已从固定 commit 的 producer 和 consumer 同时确认。 |
| equivalent candidate | HoTools 可采用不同表示，但必须证明消费者语义等价。 |
| intentional deviation | Blender/Physics World 输入域刻意不同，必须有明确边界和测试。 |
| unresolved | 尚不能冻结实现，禁止进入 capability、slot schema 或 native ABI。 |

源码使用的 `HashSet`、`NativeParallelHashSet`、`NativeParallelMultiHashMap` 枚举顺序不构成公开语义。涉及这些容器的 oracle 必须比较 canonicalized edge/triangle/constraint records，不能把一次运行中的数组顺序误当作协议。

## W1 BoneConnectionMode 到 Lines/Triangles

### Source entries

| 职责 | 文件与入口 |
|---|---|
| mode 定义 | `Runtime/Manager/Render/RenderSetupData.cs::BoneConnectionMode` |
| Bone setup 收集 | `RenderSetupData` 的 bone constructor 与 `ReadTransformInformation()` |
| Bone virtual mesh import | `Runtime/VirtualMesh/Function/VirtualMeshInputOutput.cs::ImportBoneType()` |
| edge/triangle canonicalization | `Runtime/Utility/Data/DataUtility.cs::PackInt2()` / `PackInt3()` |
| triangle angle 常量 | `Runtime/Define/SystemDefine.cs::ProxyMeshBoneClothTriangleAngle`，值为 `120.0f` |

### Input representation

`RenderSetupData` 同时维护两种不同顺序：

1. `rootTransformIdList` 严格保留 authoring `rootTransforms` 的登记顺序。
2. `transformList` 用栈遍历所有 root 子树并去重。root 依登记顺序压栈，因此后登记的 root 先出栈；child 按 `0..childCount-1` 压栈，因此后面的 child 先出栈。

`ImportBoneType()` 为 `TransformCount - 1` 个 transform 建顶点，最后一个 render transform 不进入粒子顶点。顶点索引来自 `transformList`，不能由 root 输入下标和 chain local index直接推导。

对 HoTools 的直接影响：当前 `task.sources` 逐链拼接只能作为自有稳定索引方案，不能声称复刻 MC2 vertex order。若选择保留 HoTools 顺序，所有 source oracle 必须先用 transform identity 做重映射，再比较拓扑集合。

### Line mode

`Line` 不进入 mesh connection 分支。每个顶点查询排除 center transform 后的 parent；存在 parent 时添加 canonical edge `PackInt2(parent, child)`。

额外 BoneSpring 行为发生在 topology import 阶段：

- 所有 vertex attribute 先加入 `DisableCollision(0x10)`；
- `collisionBoneIndexList` 中的骨骼被写回 `Invalid(0)`，使后续 selection attribute 能决定其碰撞状态。

该 attribute 处理不是 line topology 本身，但与 BoneSpring 输入域不可分离，不能在后续 collider step 临时猜测。

### Mesh modes 的公共前处理

非 `Line` mode 先建立 transform id -> vertex index 映射，然后确定：

| Mode | loopConnection | sequentialConnection | root 顺序 |
|---|---:|---:|---|
| AutomaticMesh(1) | 动态判定 | false | 最近邻算法重排 |
| SequentialLoopMesh(2) | true | true | authoring root 顺序 |
| SequentialNonLoopMesh(3) | false | true | authoring root 顺序 |

HoTools 当前只接受 0..2。mode 3 是否公开仍是产品决策，但 source contract 必须保留它与 mode 2 共用 sequential 规则、只关闭首尾连接这一事实。

### AutomaticMesh root 排序

源码算法不是普通 greedy nearest-neighbor：

1. 以 authoring root[0] 为当前链首。
2. 在未消费 root 中寻找离当前 root 最近者。
3. 第一条边直接接受，并把 `lastDist` 设为该距离。
4. 后续最近距离 `< lastDist * 1.5` 时接受，随后令 `lastDist = (lastDist + minDist) * 0.5`。
5. 距离过长时不接受候选，而是反转已经形成的 root 列表并把 `lastDist` 清零，下一轮从反转后的链尾继续。
6. 完成排序后，若 root 数量至少为 3，且首尾距离 `< lastDist * 1.5`，开启 loop。

因此 `lastDist` 是递推平滑距离，不是全部已接受边的算术平均。当前 B4 的“单向 greedy + 全部 link average”不等价。

### Parent/main-edge 与 level 数据

对排序后的每个 root，源码用 transform 子树 DFS 建立：

- `linkList[vertex]`：先加入 parent 和 child；
- `vertexLvList[vertex]`：root 为 0，child 逐级 +1；
- `vertexRootIndex[vertex]`：排序后 root 的序号；
- `lvIndexList[level]`：该 level 上所有 root/branch 的顶点；
- `mainEdgeSet`：全部 transform parent-child canonical edge。

这一步允许分叉链。同一 root、同一 level 可以有多个顶点，因此不能用每条 source 每层一个顶点的 zip 模型代替。

### Same-level link 生成

对每个 vertex，候选来自整个 `lvIndexList[level]`，按以下规则过滤：

1. 排除自身。
2. 非 loop 时排除排序后第一个与最后一个 root 之间的候选。
3. sequential mode 只允许相邻 root；loop 的首尾 root 也允许。
4. 先找最近候选并加入 link。
5. AutomaticMesh 再加入距离 `<= nearestDistance * 1.5` 的所有合法候选。
6. Sequential mode 把距离阈值设为无限，因此会加入相邻 root 同层的所有合法候选，不是逐链 zip 一对一连接。

`linkList` 本身可能非对称；后续 `PackInt2()` 和 edge set 会把无向边 canonicalize 并去重。

### Triangle 与 residual line 生成

对每个 vertex 的 link 两两组合形成候选三角形。候选只有同时满足以下条件才保留：

- 两条 link vector 长度平方都不小于 `1e-6`；
- 两向量夹角严格小于 `120` 度；
- 三个顶点最多跨两个 root，不允许横跨三个不同 root；
- 三条候选边中至少一条属于 transform parent-child `mainEdgeSet`。

triangle 用 `PackInt3()` 升序排序后放入 set，因此这里的 triangle index order 不保存 winding。形成 triangle 时，源码把从中心 vertex 指向两个 link vertex 的边记入 `triangleEdgeSet`。最终 `lines` 只保留 `edgeSet - triangleEdgeSet`，并非简单等于 parent-child + horizontal edge 全集。

### Lifetime and consumers

`lines` / `triangles` 是 virtual mesh import 产物。经过 selection、reduction（仅 MeshCloth）、optimization 后，`ConvertProxyMesh()` 从最终 line/triangle 重建 canonical `edges`、vertex adjacency 和 edge-to-triangle map。运行时 constraint builder 消费的是转换后的 proxy 数据，不直接消费 import 阶段的 `linkList`。

### HoTools mapping conclusion

| 项目 | 当前判断 |
|---|---|
| 一个 solver 三 setup | source fact + 已定架构。 |
| BoneSpring 强制 Line | source fact。 |
| HoTools 自有稳定 vertex order | intentional deviation candidate；必须 identity-remap oracle。 |
| Automatic/Sequential 的 link 与 triangle 规则 | 必须 exact port 或经 golden fixture 证明的 semantic equivalent。 |
| mode 3 | unresolved product surface；内部 enum/worksheet 不得丢失。 |
| import lines/triangles 是否直接作为最终 constraint topology | 不允许；仍需经过 proxy conversion 和 constraint `CreateData()`。 |

### Required oracles

1. 三条 root 触发普通 nearest chain 与 loop 判定。
2. 四条 root 触发过长边反转，证明结果不同于单向 greedy。
3. SequentialLoop 与 SequentialNonLoop 仅首尾连接不同。
4. 分叉 root 在同 level 产生多对多候选，证明 zip 模型错误。
5. 120 度边界、零长度 link、跨三 root、无 main edge 四种 triangle rejection。
6. canonical triangle/edge 集合与 residual lines 分开比较。

## W2 SelectionData 到 Baseline/Root/Depth

### Source entries

| 职责 | 文件与入口 |
|---|---|
| authoring selection schema | `Runtime/Cloth/SelectionData.cs` |
| attribute bits | `Runtime/VirtualMesh/VertexAttribute.cs` |
| selection 来源与 build 顺序 | `Runtime/Cloth/ClothProcess.cs` |
| render mesh 裁剪 | `VirtualMeshInputOutput.cs::SelectionMesh()` |
| proxy attribute 映射 | `VirtualMeshProxy.cs::ApplySelectionAttribute()` |
| baseline/root/depth | `VirtualMeshProxy.cs::CreateMeshBaseLine()`、`CreateTransformBaseLine()`、`CreateVertexRootAndDepth()` |

### SelectionData representation

`SelectionData` 只包含：

- cloth component local space 的 `positions: float3[]`；
- 与 positions 等长的 `attributes: VertexAttribute[]`；
- 构建 selection 时 virtual mesh 的 `maxConnectionDistance`；
- `userEdit` 标记。

它不包含 parent、child、root、depth、baseline ranges 或 constraint records。

`VertexAttribute` 是 byte bit field：Fixed=`0x01`、Move=`0x02`、InvalidMotion=`0x08`、DisableCollision=`0x10`、ZeroDistance=`0x20`、Triangle=`0x80`。既没有 Fixed 也没有 Move 时为 Invalid；`IsDontMove()` 的判断是没有 Move bit，不等价于只检查 Fixed bit。

### Selection source precedence is a build pipeline

源码不是一个简单字段优先级表达式：

1. MeshCloth 可从 serialized selection、manual vertex attributes 或 paint map 生成 selection。
2. 多 render mesh 的 selection 会 merge；`maxConnectionDistance` 取最大值。
3. selection 先参与 `SelectionMesh()`，按 Move/Fixed 邻域裁剪 render triangle/vertex。
4. MeshCloth 之后还可能 merge、reduction、optimization，proxy vertex index 可变化。
5. BoneCloth/BoneSpring 无有效 selection 时，先全部设 Move，再把登记 root 设 Fixed；bone attribute dictionary 随后可覆盖任意 transform attribute。
6. 最终 selection 在 optimization 后通过空间搜索映射到 proxy vertex。

因此 Blender vertex group -> 当前 proxy index 的直接映射只有在“用户 mesh 已是最终 proxy、无 reduction、拓扑同构”的输入域内才可能成立，属于 HoTools intentional deviation，不是 MC2 通用行为。2026-07-11 产品决策已将这个输入域冻结为长期硬约束：用户负责制作低模代理，HoTools 对输入 mesh 原样计算，不迁移 MC2 的 selection crop、merge、reduction、optimization 或空间重映射。

### ApplySelectionAttribute semantics

搜索半径为：

```text
searchRadius = max(proxy.averageVertexDistance,
                   selection.maxConnectionDistance,
                   MinimumGridSize)
gridSize = searchRadius * 1.5
```

每个 proxy vertex 在半径内选最近 selection sample；找到的完整 bit field 用 OR 方式加入 proxy 已有 attribute。未找到时 `minAttr=Invalid(0)`，不会覆盖既有 flag。相同距离的候选因判断只排除 `dist > minDist`，后枚举者可以覆盖先枚举者；hash map 枚举顺序不应成为 HoTools 协议。

triangle bit 不是 selection 输入。`ConvertProxyMesh()` 在组织 vertex-to-triangle 时，把属于 triangle 的 proxy vertex OR 上 `Triangle(0x80)`。

### ConvertProxyMesh derived order

attribute 确定后，源码依次生成：

1. triangle/line 合成的 vertex adjacency 与 canonical `edges`；
2. `edgeToTriangles`、triangle normal/tangent 和 `Triangle` attribute bit；
3. fixed list 与 AABB；
4. Mesh 或 Bone baseline；
5. bind pose 与 edge flags；
6. baseline local pose；
7. `vertexRootIndices` 和 `vertexDepths`。

这证明 baseline/depth 必须依赖最终 proxy attribute 与 topology，不能作为 authoring selection 的字段。

### Mesh baseline

`CreateMeshBaseLine()` 的 source semantics：

- 收集所有 `IsFixed()` vertex；没有 fixed 时 parent 全为 -1、child arrays 为空，不创建 baseline；
- 从所有 fixed 同时开始按 adjacency 分层传播；Invalid vertex 不进入下一层候选；
- 移动 vertex 选择 parent 时，fixed parent 以距离为 cost；move parent 以“当前 -> parent”和“parent -> grandparent”的夹角为 cost；
- 同层候选按到已处理邻点的最短距离排序后再推进；
- 同一 frontier 内不是两阶段统一提交：较早处理且成功选到 parent 的 Move 会立即标为可选，后续相邻 Move 可以在同一 frontier 内选它为 parent；
- child map 从最终 parent 反建；每个有 child 的 fixed 分别作为 baseline 起点遍历子树。
- `CreateBaseLinePose()` 只遍历 `baseLineData`。参与 baseline 且无 parent 的 root 写 identity quaternion；不在任何 baseline 中的顶点保留 NativeArray clear-memory 的 zero quaternion，而不是 identity。
- parent-local position 不是简单的 `childPosition - parentPosition`：源码先用 `ToRotation(parentNormal, parentTangent)` 建 parent rotation，再用其逆旋转变换位置差；local rotation 同样是 `inverse(parentRotation) * childRotation`。
- parent-local position 长度 `< 1e-8` 时，源码把 `Flag_ZeroDistance(0x20)` OR 回最终 proxy attribute。因此 baseline build 会最终确定 proxy attribute/signature，不能把二者建成互不相关的输出。

普通 multi-source BFS 只能复刻 reachability，不能复刻 parent 选择和 baseline order。

源码在 equal cost 时由 `ExCostSortedList1.Add()` 保留第一个枚举项，但其 adjacency/child/frontier 来自 `NativeParallelMultiHashMap`，hash 枚举顺序不是稳定公共契约。HoTools 对 equal cost 固定按最低 final-proxy vertex index 破同值，并对 sibling/baseline traversal 使用同一 canonical index order；这是 intentional determinism boundary。非 equal-cost parent、root、depth、local pose 和 ZeroDistance 仍须逐数组与 Tier A 对拍。

### Bone baseline

`CreateTransformBaseLine()` 始终从 transform identity 建完整 `vertexParentIndices` 与 child map。baseline 起点不是无条件等于登记 root：源码沿固定/不移动子树向下搜索，找到“自身不移动且至少一个直接 child 为 Move”的顶点后才建立 baseline；baseline 只遍历 Move child。

这允许连续多个 Fixed 后再进入 Move，也允许 bone attribute dictionary 改变实际 baseline 起点。当前“每条 source 第一个顶点固定，其余移动”的模型只覆盖默认 selection 的最窄情况。

### Root and depth

`CreateVertexRootAndDepth()` 对每个 Move vertex 沿 `vertexParentIndices` 累加几何边长，遇到第一个非 Move parent 时停止并记录为 root。随后用**整个 proxy mesh 的最大累计长度**归一化所有 vertex depth。

固定/Invalid vertex 的 root 为 -1、长度和 depth 为 0。不同 bone chain 共享同一个最大长度；按每条 source 的离散层数单独归一化不等价。零长度边允许存在，只贡献 0 长度。

### Lifetime and dirty boundary

- serialized/manual/paint selection：authoring/build input；
- mapped proxy attributes、baseline、root、depth：slot static data；
- selection 内容、最终 proxy topology 或 transform hierarchy 改变：需要重建这些静态数据；
-纯 solver parameter 改变：不得重建 selection/baseline；
- runtime particle state 不得反向修改 authoring selection。

### HoTools contract conclusion

候选 host contract 至少拆为：

1. `MC2AuthoringSelectionSpec`：Blender 输入与 source signature；
2. `MC2ProxyAttributeSpec`：映射后的 byte flags；
3. `MC2BaselineTopologySpec`：parent/child、baseline ranges/data、root indices、depth、local pose。

名称尚未冻结，但三者不能继续合并成当前 B4 `MC2SelectionSpec`。

### Required oracles

1. 无 Fixed、单 Fixed、多 Fixed、断开 island 的 Mesh baseline。
2. 同层存在两个可选 parent，分别触发 fixed distance cost 与 move angle cost。
3. Bone 连续两个 Fixed 后接 Move，验证 baseline 起点不是登记 root。
4. 两条几何长度不同但层数相同的 chain，验证全局 length normalization。
5. Triangle、DisableCollision 等附加 bit 与 Fixed/Move 的 OR 语义。
6. 无 Fixed/断开岛的 local rotation 保持 zero quaternion；baseline root 才是 identity。
7. rotated normal/tangent basis 下的 parent-local position/rotation，以及 zero-distance attribute/signature finalization。

MC2 的 selection sample 空间映射保留为 source fact，但按 D-02/D-03 不进入 HoTools implementation oracle：HoTools 只对 final-proxy 输入做同 index attribute 映射。

## W3 Proxy Topology 到 Distance/Bending Data

### Source entries

| 职责 | 文件与入口 |
|---|---|
| constraint build 调度 | `Runtime/Cloth/ClothProcess.cs`，proxy conversion 完成后依次调用各 `CreateData()` |
| Distance build/solver | `Runtime/Cloth/Constraints/DistanceConstraint.cs` |
| Bending build/solver | `Runtime/Cloth/Constraints/TriangleBendingConstraint.cs` |
| proxy adjacency | `VirtualMeshProxy.cs::ConvertProxyMesh()` |
| runtime registration | `Runtime/Manager/Simulation/SimulationManager.cs::RegisterConstraint()` |

### Shared producer boundary

constraint data 只从最终 `VirtualMesh` 派生。输入包括 canonical edges/triangles、vertex adjacency、edge-to-triangle map、final attributes、baseline parent、local/world rest position 与初始化变换。它不是 import topology 的同义词。

### Distance CreateData

输出表示是逐 vertex 压缩邻接表：

| Array | 类型 | 语义 |
|---|---|---|
| `indexArray` | `uint[vertexCount]` | 12-bit count + 20-bit start。每个 vertex 一项。 |
| `dataArray` | `ushort[N]` | 该 vertex 的目标 local vertex index。 |
| `distanceArray` | `float[N]` | rest distance；正数=vertical，负数=horizontal，0 保留 zero-distance 特例。 |

源码字段注释仍写“10-22”，但 `CreateData()`、`Pack12_20()` 与 solver 的 `Unpack12_20()` 实际一致使用 12-bit count + 20-bit start。HoTools 必须以执行代码为准，并把这类注释偏差纳入 ABI 测试。

生成步骤：

1. 从 proxy vertex adjacency 遍历每个有向邻接。
2. 两端都不 Move 时排除；任一端 Invalid 时排除。
3. 若 `target == parent[current]` 或 `current == parent[target]`，归入 vertical，否则归入 horizontal。
4. 对每条 edge-to-triangle 邻接，检查共享边两侧的 opposite vertices；两面法线点积绝对值至少为 `0.9396926`，且两条对角线长度比误差不超过 `0.3` 时，把 opposite pair 作为 horizontal shear，且双向加入。
5. 每个 vertex 的输出先 vertical 后 horizontal；horizontal rest distance 取负值。

当前 B4 的无向 `distance_pairs + kinds + positive rest_lengths` 会丢失：逐 vertex adjacency、signed encoding、invalid/fixed filtering、parent classification、shear，以及 solver 对每个 vertex 聚合 correction 的执行结构。

### Distance consumers and lifetime

`Register()` 把三个数组追加到 manager 全局数组，并在 TeamData 保存 `distanceStartChunk` 与 `distanceDataChunk`；`Exit()` 按 chunk 释放。solver 每个 step 对每个 vertex 读取自己的 count/start，遍历 target，按 rest sign 选择 horizontal stiffness，并只把平均 correction 写回当前 vertex。

HoTools 不需要复制全局 manager chunk，但 slot/native context 必须保留等价的 per-vertex range + target + signed rest 语义。若 native 改成 pair solver，必须用 oracle 证明更新顺序、单边写回和平均策略等价；默认不应假设等价。

### TriangleBending CreateData

输出主数组：

| Array | 类型 | 语义 |
|---|---|---|
| `trianglePairArray` | `ulong[M]` | 四个 ushort：v0/v1 为对角点，v2/v3 为共享边。 |
| `restAngleOrVolumeArray` | `float[M]` | dihedral rest angle 或放大 1000 倍的 rest volume。 |
| `signOrVolumeArray` | `sbyte[M]` | dihedral 方向为 -1/+1；`100` 表示 volume record。 |

生成步骤：

1. 遍历每条 proxy edge 的全部相邻 triangle pair。
2. 提取两个 opposite vertex，形成 `(opposite0, opposite1, edge0, edge1)`。
3. 四点都不 Move 时排除；任一点 Invalid 时排除。
4. 计算有方向 dihedral rest angle 和 sign。
5. `abs(angle) < 120°` 时加入 bending record。
6. `90° <= abs(angle) <= 179°` 时另加入 volume record；按四点排序后的 key 去重。
7. volume 用 world-space initial positions 计算并乘 `1000`；运行时再考虑 scale ratio 和 negative scale sign。

同一个 triangle pair 可能同时产生 bending 与 volume 两条 record，因此“一个邻接 pair 对应一个 bending constraint”不成立。

`ConstraintData` 还生成 `writeBufferCount/writeDataArray/writeIndexArray`，但固定 commit 的 `Register()` 和 Normal/Split runtime 搜索中没有消费它们。它们属于 source-generated but runtime-unused 数据；第一版 HoTools ABI 不应仅为字段同名而迁移，除非后续发现 prebuild/export consumer。

### Bending consumers and lifetime

`Register()` 只注册 triangle pair、rest、sign 三个同长数组，并在 TeamData 保存 `bendingPairChunk`。solver 按 record 解包四点，按 attribute/depth/friction 计算四点 correction，累加到 per-particle scratch；`SumConstraint()` 再对 Move particle 平均并清空 scratch。

因此 host static data 与 runtime scratch 必须分离。scratch count/vector 不属于 constraint topology spec，也不能跨帧持久化。

### HoTools contract conclusion

候选静态结构至少包含：

- Distance: `vertex_ranges`, `target_indices`, `signed_rest_distances`；
- Bending: `vertex_quads`, `rest_angle_or_volume`, `sign_or_volume`；
- shared source identity: proxy/baseline/attribute signatures；
- debug-only canonical records，不能反过来替代 runtime layout。

当前 `MC2ConstraintTopologySpec` 应视为 rejected draft，不能演化为 native ABI。

### Required oracles

1. parent edge 与非-parent edge 的正负 rest encoding。
2. 全 fixed、Invalid endpoint 与 zero-distance filtering/保留规则。
3. 双三角方片满足 shear 条件与不满足法线/长度比条件。
4. 单 edge 两 triangle 的普通 dihedral record。
5. 120 度排除、90..179 度 volume、同一 pair 双 record。
6. negative scale 与 world-space volume rest 的运行时消费。
7. per-vertex Distance average 和 per-particle Bending sum scratch 的数值 oracle。

## W4 Inertia Static Data 与 Center Runtime State

### Source entries

| 职责 | 文件与入口 |
|---|---|
| fixed center 候选与局部中心 | `VirtualMeshProxy.cs::ProxyCreateFixedListAndAABB()` |
| 初始局部重力方向 | `InertiaConstraint.cs::CreateData()` |
| fixed list 注册 | `InertiaConstraint.cs::Register()` |
| center/anchor 帧输入 | `TeamManager.cs::AlwaysTeamUpdateJob`、`SimulationCalcCenterAndInertiaAndWind()` |
| substep center 更新 | `TeamManager.cs::SimulationStepTeamUpdate()` |
| 粒子消费 | `SimulationManagerNormal.cs::SimulationPreTeamUpdate()`、`SimulationStepUpdateParticles()`、`SimulationStepPostTeam()` |

### Build-time fixed center data

`ProxyCreateFixedListAndAABB()` 遍历最终 proxy attributes 和 vertex adjacency。一个非 Move vertex 只有在“至少一个邻点为 Move”或“没有邻点”时才进入 `centerFixedList`；连接全部为非 Move 的 fixed vertex 被视为与模拟无关而跳过。`localCenterPosition` 是保留 fixed vertex 的局部位置平均值，没有保留项时为零。

`InertiaConstraint.CreateData()` 对 `centerFixedList` 中每个 vertex 读取 local normal/tangent 和 `vertexBindPoseRotations`，累加统一后的 normal/tangent，再据此计算初始 center rotation。存在 fixed point 时，`initLocalGravityDirection` 为 `inverse(initialCenterRotation) * worldGravityDirection`；否则固定为 `(0,-1,0)`。因此它依赖 W2 的最终 attributes、adjacency、bind pose 和参数归一化结果，不能从“root fixed”布尔值单独推导。

注册时 `centerTransformIndex` 被替换为 Team/TransformManager 的 direct index，fixed list 被复制到 manager-owned range。以下是 slot static 候选，而不是粒子数组：

- center transform 的稳定 identity；
- `centerFixedList`；
- `localCenterPosition`；
- `initLocalGravityDirection`。

manager direct index 只是一次注册实例的句柄，不得写入可持久 fixture、task signature 或跨重建 ABI。

### Frame input and state

`CenterData` 不是一个静态 inertia 参数结构。它同时持有以下动态域：

| 域 | 代表字段 | 生命周期 |
|---|---|---|
| 外部姿势输入 | anchor/current component position、rotation、scale | 每帧采样 |
| 跨帧历史 | old anchor/component/frame pose、smoothing velocity | persistent |
| 当前帧派生 | frame center pose、component shift、moving speed/direction、negative-scale matrix | frame |
| substep 派生 | now/old world pose、step vector/rotation、inertia vector/rotation、angular velocity/axis | substep |
| 静态注册值 | center transform index、frame local center、initial local gravity direction | registration 后保留 |

center 姿势优先由 `centerFixedList` 对应 proxy world poses 的平均位置及 bind-adjusted normal/tangent 得到；没有 fixed list 时退回 component transform。同步 team 可替换 position/rotation 的 center transform，但源码明确不替换自身 scale。

anchor identity 不在 `ClothParameters` 中。`AlwaysTeamUpdateJob` 每帧从独立 transform map 写入 anchor pose，并设置 `Flag_Anchor/Flag_AnchorReset`；`anchorInertia` 只是这个外部姿势输入的影响系数。HoTools 当前 profile 只有 `anchor_inertia`，没有 anchor source identity，因此不能声称覆盖 MC2 anchor 功能。

### Frame/substep transitions

`SimulationCalcCenterAndInertiaAndWind()` 在每帧：

1. 采样 component pose 和 scale，处理同步与负 scale；
2. 从 fixed poses 或 component pose 求 frame center；
3. 处理 anchor、teleport、movement smoothing、world inertia shift 和速度上限；
4. 在 reset 时同时重置 old/current component、frame 和 step center；
5. 更新 frame moving speed/direction、local center、stabilization weight 和 wind zones。

`SimulationStepTeamUpdate()` 再按 `frameInterpolation` 插值 old/current frame center，产生 `stepVector`、`stepRotation`，应用 local inertia 与 local speed limit，得到 `inertiaVector`、`inertiaRotation`、angular velocity/axis、scale ratio、gravity falloff 和最终 blend weight。Normal/Split 的调度形态不同，但这组状态转移是共同数学语义。

### HoTools contract conclusion

| 项目 | 结论 |
|---|---|
| 一个扁平 `MC2InertiaStateSpec` | 拒绝；必须区分 static registration、frame persistent 和 substep derived。 |
| center direct index | host 私有句柄；ABI/fixture 使用稳定 identity。 |
| anchor | 独立动态 transform input；不是 profile scalar 的一部分。 |
| first native slice | 可暂不支持 anchor/sync/negative scale/wind，但必须作为显式 capability 缺口，不能默认为 identity 后称等价。 |
| current B3 | 没有 CenterData 状态机，不能支持 source-level inertia/reset。 |

### Required oracles

1. 无 fixed、孤立 fixed、fixed 邻接全 fixed、fixed 邻接 Move 四种 `centerFixedList`。
2. 两个 fixed 的 center position 与 bind-adjusted center rotation。
3. 无 fixed 和有 fixed 时的 `initLocalGravityDirection`。
4. component 平移/旋转、anchor on/off、Reset/Keep teleport 各自的 frame shift。
5. 两个 substep 的 center interpolation、local inertia 与 speed limit。
6. negative scale 与 sync center 单独列为后续 Tier A case。

## W5 Particle Registration、Reset 与 Array Lifetime

### Source entries

| 职责 | 文件与入口 |
|---|---|
| range 分配/释放 | `SimulationManager.cs::RegisterProxyMesh()` / `ExitProxyMesh()` |
| reset 与 frame shift | `SimulationManagerNormal.cs::SimulationPreTeamUpdate()` |
| substep predict/base pose | `SimulationStepUpdateParticles()` |
| position commit | `SimulationStepPostTeam()` |
| display history | `SimulationCalcDisplayPosition()` |

### Allocation is not initialization

`RegisterProxyMesh()` 只对每个 manager array 执行 `AddRange(vertexCount)` 并把 range 存入 `TeamData.particleChunk`。这一步建立容量和 owner，不赋予 rest pose、速度或 reset 语义。真正的语义初始化发生在该 team 带 `Flag_Reset` 进入 `SimulationPreTeamUpdate()` 时。

reset 输入来自当前帧 proxy 的 world-space `positions[vindex]` / `rotations[vindex]`，不是 build-time local rest arrays。reset 对每个 particle 精确写入：

| Array | Reset value |
|---|---|
| `nextPos`、`oldPos`、`basePos`、`oldPosition`、`velocityPos`、`dispPos` | 当前 proxy world position |
| `oldRot`、`baseRot`、`oldRotation` | 当前 proxy world rotation |
| `velocity`、`realVelocity`、`collisionNormal` | zero vector |
| `friction`、`staticFriction` | `0` |

因此当前 B3 以 rest local pose 直接填满动态 buffer 只可视为临时 scaffold。正确 host contract 应先提供当帧 proxy world pose，再执行统一 reset transition。

### Non-reset frame and substep semantics

当发生 world inertia shift 或 negative-scale teleport 时，pre-team 分支只变换跨帧历史：`oldPos/oldRot`、`oldPosition/oldRotation`、`dispPos`、`velocity/realVelocity`。`nextPos` 和 `basePos` 不在这里作为持久 rest state 平移。

每个 substep 的 `SimulationStepUpdateParticles()`：

1. 以 `oldPos` 初始化预测位置和 velocity reference position；
2. 在 `oldPosition/oldRotation` 与当前 proxy pose 间按 frame interpolation 求 `basePos/baseRot`；
3. 同时写 `stepBasicPosition/Rotation`，再叠加 center inertia、velocity、gravity、wind 和 external force；
4. fixed particle 直接使用 base pose，BoneSpring fixed particle还可执行 spring；
5. 写 `velocityPos` 与 `nextPos`，并清空约束 scratch。

约束链消费 `nextPos` 后，`SimulationStepPostTeam()` 计算 velocity/real velocity、摩擦与速度限制，并以 `oldPos = nextPos` 提交本 step。display 阶段再从 committed position、real velocity 与时间插值求 `dispPos`，并更新 old animation pose history。

### Lifetime classification

| 数据 | 分类 |
|---|---|
| `oldPos`、`oldRot`、`oldPosition`、`oldRotation`、`dispPos`、velocity/friction/collision history | particle persistent state |
| `nextPos`、`velocityPos`、`basePos/baseRot` | context-owned working arrays；每 step 被明确重建/覆盖，不能作为 immutable initial spec |
| `stepBasicPosition/Rotation` | substep scratch；只为 baseline/angle 求解服务 |
| temp vector/count/float buffers 与 constraint write buffers | scratch；不得进入 task signature 或跨帧承诺 |
| proxy current positions/rotations | frame input/output surface；不属于 particle owner |

### HoTools contract conclusion

- 保留 slot 统一分配、dispose 和 topology-change rebuild 的 owner 设计。
- 把 reset 写成显式 transition；首次 registration、用户 reset、时间倒退和静态重建可触发同一 transition，但触发原因需独立记录。
- 参数热更新不得重新初始化 particle history；center/anchor source identity 或 topology/selection 改变需要重新评估是否 reset/rebuild。
- debug snapshot 要区分“allocation 后未 reset”和“已 reset”，不能仅凭 array shape 宣称状态有效。

### Required oracles

1. allocation 后、首次 reset 后的全部数组逐项 dump。
2. 两个连续 substep 的 base interpolation、next/old commit。
3. fixed、Move、BoneSpring fixed 三类 particle。
4. reset、Keep teleport、inertia shift、negative-scale teleport。
5. 参数热更新保持 history，topology rebuild 更换 range 并 reset。

## W6 Display、Bone Transform 与 Mesh Mapping Output

### Source entries and order

Normal 路径在 constraint step 完成后依次执行：

```text
SimulationCalcDisplayPosition
  -> SimulationPostProxyMeshUpdateLine
  -> SimulationPostProxyMeshUpdateTriangle
  -> SimulationPostProxyMeshUpdateTriangleSum
  -> SimulationPostProxyMeshUpdateWorldTransform
  -> SimulationPostProxyMeshUpdateLocalTransform
  -> PostMappingMeshUpdateBatchSchedule (mapping/render path)
```

Split 路径把这些工作拆成 job，但 producer/consumer 顺序相同。迁移目标是该数学顺序，不是 Unity job 切分。

### Proxy display pose

`SimulationCalcDisplayPosition()` 对 Move/BoneSpring particle 从 committed `oldPos` 和 `realVelocity` 做 future prediction，再按 team blend weight 与当前 proxy animation position 混合；fixed particle 始终保留原 proxy position。它同时保存 post-line 所需的原始 base position/rotation 到 temp buffers。结果仍是 world-space proxy position/rotation，不是 Blender object-local offset。

line output 使用 baseline、children、initial/current local pose、animation pose ratio、`rotationalInterpolation` 和 `rootRotation` 重建 Bone line rotations。triangle output 先从 position/UV 求 triangle normal/tangent，再按 vertex-to-triangle flip flags 累加，并乘 `normalAdjustmentRotations` 得到 proxy vertex rotation。存在 triangle 时该结果可覆盖 line-derived rotation。

### Bone output mapping

Bone proxy 的每个 vertex world rotation 先乘 `vertexToTransformRotations`（并处理 negative scale），与 world position 一起写 TransformManager。随后只有 `parent >= 0 && attribute.IsMove()` 的 transform 由 parent world pose/scale转换为 local position/rotation；root/fixed transform 保持动画输入路径的 local pose。

HoTools 的 `BONE_TRANSFORM_CHANNEL` 应发布稳定 bone identity 对应的最终 local transform/result，而不是 Unity manager direct index。`PoseBone.matrix_basis` 的计算和冲突合成属于 Physics World writeback adapter，不能反向进入 solver state。

### Mesh output mapping

MC2 的 MeshCloth 通用路径不是简单的 `proxy position - rest position`。`PostMappingMeshUpdateBatchSchedule()` 使用 mapping vertex 的 bind pose/weights 对 proxy world poses 做逆蒙皮，转换到 mapping mesh local space后写 render positions/normals/tangents，必要时还改 bone weights。

HoTools 已按 D-03 把用户 mesh 永久定义为“最终 proxy 且 identity mapping”。因此直接发布同一 vertex identity 的 object-local position offset；MC2 mapping/reduction/render mesh 输出不属于实现范围，也不进入未来 capability。

### Blender 动画基底与无反馈写回边界

这部分是 HoTools host adapter 契约，不是 MC2 reduction/render mapping。旧 MeshCloth 路径已经形成一条可工作的语义链：

1. `physicsWorld/mc2/setups/mesh_cloth/base_pose.py::create_base_pose_proxy()` 复制源对象和 Mesh data，保留 Armature、Shape Key 等原有基础变形栈，但从副本移除 MC2/GN 物理 delta output，并把副本作为 `HoPhysicsCache` 中的只读 BasePose 对象管理。
2. `physicsMC2MeshCloth/blender_io.py::read_evaluated_mesh_world_pose()` 对 BasePose 调用 `evaluated_get(depsgraph).to_mesh()`，读取当前帧位置/法线快照并立即 `to_mesh_clear()`；不直接持有 evaluated data。
3. `read_cached_base_pose_world_pose()` 用 `(source object pointer, BasePose pointer, frame)` 缓存一帧快照并返回副本。同一帧重复求值不会重复读取，也不会因本帧 writeback 改变 solver input。
4. `state.py::sync_state_to_base_pose_proxy()` 在 BasePose identity/frame 已同步时复用状态，否则把本帧 world positions/normals 更新为 `base_positions/base_normals`，再重建 base rotation/step basic pose。跳帧、倒放或 identity 变化由 runtime lifecycle 走 restart/rebuild，而不是把旧 pose 当新输入。
5. `delta_output.py::write_world_delta_attribute()` 计算 `display_world - base_world`，仅用源对象 `matrix_world` 逆线性部分转成 object-local vector；GN Set Position 修改器始终位于 Armature/基础变形之后。共享 `physicsWorld.gn_offset` 延续同一个“最终 object-local offset”语义。

因此这里存在两个不同的 cache/static 概念：N0 的 topology/vertex identity 是静态注册数据；BasePose cache 是逐帧 animated pose snapshot。骨架会移动顶点，但不应更换 vertex identity 或 N0 signature。直接读取源对象 evaluated mesh 会包含底部物理 GN offset，形成结果反馈，永久禁止。

双对象 + 常驻 GN 是唯一支持的 Blender host 路径，不是首版临时实现。既有性能测试已排除 BlendShape/Shape Key 逐帧写回（卡顿）、单对象切换或移动 GN 修改器（触发大面积 depsgraph/软件内部回调和重算），以及在同一 evaluated object 上读取物理前后两个阶段（Blender 无法稳定低成本同时提供）。因此新路径必须复用专用只读副本语义，不得把这些已失败方案作为“后续优化”重新引入。

相比旧路径只校验 vertex/loop/polygon count，新 adapter 还必须在创建/刷新时校验完整 N0 topology signature，并在每帧拒绝 evaluated vertex count 不一致。Armature、Shape Key 等拓扑保持型变形允许；会新增、删除、重排或重新连接顶点的修改器不属于 final-proxy identity 输入域。

### Output contract conclusion

| Setup | Core result | Adapter result | 首版可接受范围 |
|---|---|---|---|
| MeshCloth | world proxy display pose | object-local final vertex offset | 仅 final-proxy、identity mapping；normal/tangent 由既有 Blender 路径重算或另立 capability。 |
| BoneCloth | world proxy display pose | stable bone identity -> local transform | 保留 line/triangle rotation producer；writeback 外置。 |
| BoneSpring | 同一 proxy/particle core | stable bone identity -> local transform | fixed particle spring 是 solver 分支，不是第二套 output。 |

### Required oracles

1. blend weight 0/1 与 future prediction on/off 的 display position。
2. 单链、分叉 line 的 child average、root rotation 和 rotational interpolation。
3. triangle normal/tangent、flip flag 与 normal adjustment。
4. Bone world -> local transform，含 parent scale 与 fixed/root skip。
5. Mesh result 的 vertex identity/count/order 与输入 final proxy 完全一致，不产生 mapping mesh。
6. Armature 驱动 Mesh：BasePose evaluated positions 每帧变化；写回后再次读取同帧 BasePose 数值不变；下一帧输入只包含新动画基底，不包含上一帧物理 offset。
7. BasePose modifier stack 改变 topology 时显式失败；same-frame cache 返回独立只读/复制 snapshot，不允许 consumer 原地污染缓存。

## W7 ClothSerializeData 到 Runtime Parameters

### Producer boundary

`ClothSerializeDataFunction.GetClothParameters()` 是 value parameter 归一化入口，但不是完整 task 输入：root bones、connection mode、anchor Transform、collider list、self-collision sync partner、update/disable mode、animation pose ratio 和 render mapping 都通过其他 manager/setup 路径进入运行时。

`CurveSerializeData.ConvertFloatArray()` 将曲线在 MC2 规定的位置采样为 16 个 float (`float4x4`) 并乘基础值；禁用曲线时 16 项全为基础值。solver 消费的是这个 sample matrix，而不是 AnimationCurve key/handle payload。

### Conversion table

| 参数组 | Source conversion | HoTools 审计结论 |
|---|---|---|
| gravity/common | BoneSpring 强制 gravity=0；damping samples 乘 0.2；radius 保留 samples。 | override 方向正确；Blender Z-down 到 MC2/host 坐标转换必须单列，不能把默认向量相同视为完成。 |
| inertia scalars | checked speed limits disabled 时转 `-1`；其余直接复制。 | 标量覆盖基本完整；当前 spec 丢失 checked enable/value 的 authoring round-trip，但 effective `-1` 可等价。anchor Transform 缺失。 |
| tether | BoneSpring compression=0.8；其他用 authoring 值；stretch 固定 0.03。 | 当前 payload 匹配固定值。 |
| distance | BoneSpring stiffness 16 项全为 0.5；其他为 curve samples；velocity attenuation 固定 0.3。 | 常量正确；当前 payload 仍是未采样 curve 描述，不是 runtime representation。 |
| bending | stiffness>epsilon 时 method 强制 `DirectionDihedralAngle`，否则 None。 | 当前只存 stiffness；method 可确定性派生，但 ABI/debug 必须显式。 |
| angle | restoration samples 乘 0.2；enabled、velocity attenuation、gravity falloff、limit samples/stiffness 分开。 | 字段基本覆盖；同样缺 runtime 16-sample matrix。 |
| motion | BoneSpring 强制关闭 max distance/backstop，其余值复制。 | override 方向正确。 |
| collider | BoneSpring 强制 Point、limit-distance samples 和 friction=0.5；其他 mode 保留，dynamic/static friction 分别乘系统 ratio。 | 当前 commit 的两个 ratio 都是 1.0，数值暂时相同；契约仍应记录 conversion 常量，而不是硬编码“两个字段等于输入”。 |
| self collision | `selfMode` 与 `syncMode` 独立；BoneSpring 两者都 None；另有 sync partner identity 和 cloth mass。 | 当前只建一个 mode，遗漏 sync mode/partner，不能覆盖 inter-cloth collision。 |
| wind | 七个 scalar 直接复制；frame 阶段还依赖 wind-zone 输入和 center moving speed。 | scalar 覆盖；没有 wind-zone input/runtime state 时只是参数外壳。 |
| spring | 仅 BoneSpring 且 useSpring 时 power 非零；其他字段复制。 | 当前 override 方向正确。 |
| culling | `cullingSettings.Convert()` 进入 `ClothParameters.culling`。 | 当前 profile/payload 缺失；首版可 defer，但需 capability 标记。 |
| rotational output | `rotationalInterpolation/rootRotation` 进入 ClothParameters，但只被 Bone line post-output 消费。 | 放 setup options 合理；不是 constraint solver scalar。 |

### Current parameter scaffold gaps

1. `MC2CurveSpec` 适合作为 authoring snapshot，但 `MC2EffectiveParametersSpec.payload` 仍保留原始曲线描述；它不能直接作为 source-equivalent native input。S2 必须增加确定性的 16-sample runtime representation，并为采样算法建立 Tier A/B oracle。
2. `animation_pose_ratio` 当前在 profile/effective payload 中，但 MC2 把它存入 `TeamData`，不属于 `GetClothParameters()`；它是每 task/team 的动态 setup 输入。
3. `MC2SolverSettingsSpec(substeps, iterations, time_scale)` 是 HoTools 调度策略，不对应 `ClothParameters` 的字段。S2 必须把它和 source parameter signature 分开，并说明如何映射 MC2 update frequency/iteration semantics。
4. anchor identity、self-collision sync partner、collider identities 和 wind zones 都是外部引用，不能塞进纯 value profile，也不能因 scalar 已存在就宣称能力完成。
5. parameter hot update 只适用于 runtime value arrays；改变外部引用、collision primitive topology 或需要重新注册的 setup 数据仍可能触发 registration/static rebuild。

### Parameter oracle payload

Tier A dump 至少应输出归一化后的 `ClothParameters` 全字段，包括每个 16-float curve matrix、enum、bool、固定常量和 BoneSpring override；外部引用另以稳定 identity 表示。最小 case 为同一 authoring profile 分别以 MeshCloth、BoneCloth、BoneSpring 转换，并加入一条非线性 curve、disabled checked limit、self/sync mode 和 collider friction case。

## Cross-Worksheet Findings

### 已确认的阶段边界

```text
Blender authoring input
  -> authoring selection / bone setup
  -> imported virtual mesh (positions, lines, triangles)
  -> optional selection crop / merge / reduction / optimization
  -> mapped proxy attributes
  -> ConvertProxyMesh
       edges / adjacency / triangle map
       baseline / root / depth / local pose
  -> Distance/Bending/Inertia CreateData
  -> slot-owned native static data
  -> particle persistent state + frame/substep scratch
  -> solver result
  -> Physics World result stream / writeback
```

当前 B4 同时跨越 authoring selection、proxy attribute、baseline 和 constraint data 四个阶段，重写时必须按上图拆开。

### 可以保留的既有地基

- task/source identity 与 slot dispose owner；
- topology/selection 改变导致静态重建、纯参数改变优先热更新的方向；
- Python 不保存隐藏全局 solver state；
- native context 由同一 MC2 slot 持有；
- MeshCloth/BoneCloth/BoneSpring 共用 solver identity。

### 尚未冻结

- HoTools vertex canonical order 与 MC2 transform order 的映射方式；
- mode 3 是否进入节点 surface；
- packed 12/20、ushort/ulong 是否原样成为 native ABI，还是转为显式 32-bit ranges；
- source hash-container 顺序的 canonical debug/fixture 格式；
- 第一版明确支持的 center/anchor/sync/negative-scale 子集；
- source update frequency/iteration 与 HoTools scheduler settings 的映射。

Mesh 输入边界已冻结：原始/reference Mesh data 提供 N0 静态 final-proxy topology 与 vertex identity；移除物理 GN output 的 BasePose evaluated snapshot 提供 N3 当前动画 pose。两者必须具有相同 topology signature，不再列为未决项。

## Golden Fixture Contract v0

### Oracle authority

fixture 按可信度分三级：

| Tier | 来源 | 可关闭的结论 |
|---|---|---|
| A | 在固定 commit 的 MC2/Unity 运行中导出中间数组。 | source parity；可以作为实现验收 oracle。 |
| B | 对最小输入手工推导完整数组，并逐项引用 producer 分支。 | 可关闭局部分支；不能覆盖 Unity 容器顺序或未观察上下文。 |
| C | HoTools 当前实现输出或旧 solver snapshot。 | 只能做 regression，不得证明 MC2 parity。 |

首选 Tier A。没有可运行 Unity dump 时，可先用 Tier B 冻结极小 case，但必须保留 `oracle_tier`，以后不能静默升级为 Tier A。

`D:\Unity_Project\HoClothUnity` 是已废弃且未完成调试的工程，基本不可用。它的适配代码只能作为 Tier C 历史参考，不得作为 fixture host、运行结果来源或 parity 证据，也不在该工程中继续增加 dump 工具。Tier A 需要新建一个最小、可复现、只直接引用固定 MC2 commit 的 Unity 验证工程；工程创建本身是独立交付，不能与 HoTools solver 实现混在同一提交。

该 host 已落地为 `tools/mc2_unity_oracle`：Unity `6000.3.15f1` minimal batch project 只通过 `file:D:/Unity_Fork/MagicaCloth2` 引用外部固定 checkout，runner 在启动前强制校验 commit。MC2 是商业源码，根目录与 project-local `.gitignore` 都禁止 vendored/embedded MC2 package；仓库只保存自有 exporter、resolved package lock 和导出的最小数值 fixture，不复制 MC2 source/binary。exporter 直接反射调用固定 assembly 中的 `CreateMeshBaseLine()`、`CreateBaseLinePose()`、`CreateVertexRootAndDepth()`，不是在 Unity host 里重写算法。

### File shape

每个 case 使用一个 UTF-8 JSON 文件，逻辑结构如下：

```json
{
  "schema_version": 1,
  "case_id": "bone_automatic_reverse_001",
  "source": {
    "repository": "MagicaCloth2",
    "commit": "418f89ff31a45bb4b2336641ad5907a1110eabea",
    "oracle_tier": "A",
    "producer": [
      "Runtime/VirtualMesh/Function/VirtualMeshInputOutput.cs::ImportBoneType"
    ]
  },
  "input": {
    "setup_type": "bone_cloth",
    "connection_mode": 1,
    "vertex_identity": [],
    "positions": [],
    "parents": [],
    "root_order": [],
    "attributes": []
  },
  "expected": {
    "imported_mesh": {},
    "proxy": {},
    "distance": {},
    "bending": {}
  },
  "comparison": {
    "float_abs_tolerance": 1e-6,
    "float_rel_tolerance": 1e-6,
    "unordered_fields": []
  }
}
```

`vertex_identity` 是 fixture 的稳定主键。Bone 使用 `(armature fixture id, transform path)`；Mesh 使用输入 vertex id。MC2 array index 与 HoTools array index 都必须先映射到 identity，再比较 topology/constraint records。

### Stage payloads

| Stage | 必需字段 |
|---|---|
| `imported_mesh` | vertex order/identity、local positions、canonical lines、canonical triangles。 |
| `proxy` | byte attributes、canonical edges/triangles、parent、child ranges/data、baseline ranges/data、root、depth。 |
| `distance` | vertex ranges、target identity、signed rest distance。 |
| `bending` | ordered quad identity `(v0,v1,v2,v3)`、rest angle/volume、sign/volume marker。 |
| `inertia_static` | center transform identity、center fixed identity、local center、initial local gravity direction。 |
| `parameters` | 完整 `ClothParameters` value fields；所有 curve 均为 16-float runtime samples。 |
| `particle_reset` | reset 输入 proxy world pose、逐 array reset 后数值与 reset reason。 |
| `output` | proxy display world pose，以及按 setup 分开的 mapping mesh local pose或 bone local transform。 |

edge/triangle set 使用 identity 排序后的 canonical record；Distance 保留“source vertex -> ordered target list”分组语义；Bending quad 不能把四点全排序，因为 opposite/shared-edge 角色属于算法输入。

### Comparison rules

1. integer、bit flag、record count、parent/root identity 必须精确相等。
2. position/distance/angle/volume 使用 fixture 自带容差；默认 abs/rel 都为 `1e-6`。
3. 只有明确登记在 `unordered_fields` 的 hash-container 输出允许 canonicalize。
4. `-0.0` 与 `0.0` 数值相等，但 Distance 的 horizontal 类型不能依赖 `-0.0`；zero-distance 必须单列类型 oracle。
5. NaN/Inf 一律视为 fixture 或实现错误。
6. 每个 expected stage 都带 producer；不能用下游 HoTools 输出回填上游 expected。

### Initial case set

| Case id | Tier target | 关闭的分支 |
|---|---|---|
| `bone_line_single_chain_001` | A | Line parent-child edge、default root Fixed。 |
| `bone_automatic_reverse_001` | A | Automatic 过长边反转。 |
| `bone_sequential_branch_001` | A | 同层多分支、多对多 link。 |
| `mesh_baseline_multi_fixed_001` | A | Mesh parent distance/angle cost。 |
| `bone_depth_unequal_length_001` | B -> A | 全 proxy 几何长度归一化。 |
| `distance_square_shear_001` | A | vertical/horizontal/shear、signed rest。 |
| `bending_dihedral_volume_001` | A | 同一 triangle pair 的 bending/volume 双 record。 |

已落盘的 `proxy_static_triangle_contract_001` 是 Tier B **contract-shape fixture**：它手工记录单 fixed 三角形的 proxy/baseline 数组，用于冻结分层、dtype、shape、range 和 validation；其中 `vertex_local_positions` 是理想化 contract 值，不是 `ToRotation()` 后的 source oracle。它没有运行 MC2 builder，不能关闭上述任何 source parity case，也不能从 Tier B 静默升级为 Tier A。

Mesh baseline Tier A 已落盘 9 个由上述 host 生成的 case：无/单/多 Fixed、断开岛、fixed distance、Move angle、same-frontier parent、ZeroDistance，以及 equal-cost low-first/high-first。前 8 个按完整 parent/root/depth/attribute/local-pose 数组对拍；child sibling 与 baseline sibling traversal 只按预先登记的 hash-container unordered rule canonicalize。high-first 不纳入 parity 数量，它专门证明 source 在 equal cost 时保留 first-enumerated；HoTools lowest-index 规则因此是有 fixture 证据的 intentional determinism boundary。

fixture contract 只定义数据交换与比较方式；当前阶段不创建伪造的 expected 数值。实际 fixture 必须来自 Tier A dump 或有完整手算证明的 Tier B。

## B1-B3 Reverse Audit

审计对象是 `5739ed3` 所在代码基线之前已经提交的 MC2 scaffold；未提交 B4 不作为既成接口。

### B1 Task/Parameter contracts

| 当前项 | 结论 | 后续动作 |
|---|---|---|
| `task_id = setup + order-independent source identity` | 保留。参数变化不应更换 slot identity。 | 增加 identity collision/Blender pointer reuse 测试。 |
| ordered source signature 进入 topology signature | 保留。Sequential mode 明确依赖 root order。 | oracle 比较时与 vertex order 分开记录。 |
| profile/setup/effective parameter 分层 | 方向保留。 | 仍需独立参数 worksheet 逐字段审计，当前不得整体标 source-aligned。 |
| `MC2CurveSpec` 原始 curve payload | 可保留 authoring snapshot，但不是 runtime `float4x4`。 | effective/native 参数增加确定性的 16-sample 表示；先有 oracle 再实现。 |
| `MC2SolverSettingsSpec` 混入 effective metadata | 属于 HoTools scheduler，不属于 `ClothParameters`。 | source parameter signature 与 scheduler signature 分离。 |
| anchor/sync/collider/wind 外部引用 | 当前 value profile 无法表达。 | 进入独立 input identity/snapshot，不塞入纯 scalar profile。 |
| `MC2SetupOptionsSpec.connection_mode in 0..2` | 不完整。 | D-01 决定 mode 3 surface；内部 source enum 不得遗失。 |
| `parameter_signature` 通过 default settings 构造 | 表达绕行但当前 payload 不含 settings，结果仍只覆盖 profile/setup。 | S2 改为直接、显式的 profile/setup signature，避免未来 payload 加入 settings 后静默改变 task contract。 |
| `MC2EffectiveParametersSpec.settings_signature` 与 payload 分离 | 可保留调度签名，但命名容易误导。 | 参数 worksheet 决定 settings 是否属于 effective solver input metadata。 |

### B2 Topology/slot

| 当前项 | 结论 | 后续动作 |
|---|---|---|
| `MC2TopologySpec` | 实际是 authoring/source snapshot，不是 MC2 final proxy topology。 | S2 重命名或拆成 source topology 与 proxy topology，禁止原样进入 native ABI。 |
| Mesh positions/normals/edges/fan triangles | HoTools 用户提供 final proxy 的 N0 输入；静态 topology/reference pose 与 N3 evaluated animation pose 分层。Blender n-gon fan、loose edge仍不是 MC2 通用 import 语义。 | N0 adapter 冻结 triangulated Mesh data 与完整 topology signature；N3 复用无物理 output 的 BasePose evaluated snapshot，只允许 topology-preserving deformation。 |
| 每个 Bone source 独立 DFS 后串接 | vertex order 与 MC2 `RenderSetupData` 栈顺序不同，且提前按 source 分区。 | 保留 identity snapshot；proxy builder 必须跨全部 roots 统一生成并用 identity remap 测试。 |
| 拒绝重叠 bone source | 比 MC2 constructor 更严格，但可作为 HoTools 输入校验。 | 登记 intentional deviation，并给出错误信息/测试。 |
| topology signature 包含真实 source payload | 保留。 | 未来加入 authoring selection 和 proxy builder version 的独立静态签名。 |
| slot owner/dispose/prune | 与 Physics World 生命周期一致。 | 保留，并让未来 native context 接入同一 `_dispose` 链。 |
| topology change rebuild、parameter/settings update reuse | 方向正确。 | selection/proxy/baseline signature 必须纳入静态重建判定。 |

### B3 Initial state/particle buffer

| 当前项 | 结论 | 后续动作 |
|---|---|---|
| world-space rest position/rotation | 可作为 registration/reset 输入候选。 | 用 particle registration/reset worksheet 校验首次帧和 reset 的精确来源。 |
| `parent_indices/depths/fixed_mask` 放在 initial state | 阶段错误。它们分别来自 baseline、root/depth 和 proxy attribute。 | 从 initial pose 拆出，改由审计后的 static specs 提供。 |
| Bone depth 按离散 parent 层数归一化 | 与源码不等价。 | 使用累计几何长度和全 proxy 最大长度。 |
| 默认 root fixed | 只覆盖无有效 Bone selection 的 fallback。 | authoring selection/bone attribute override 必须先于 baseline。 |
| particle persistent arrays | next/old/base/velocity/display 等 owner 方向可保留。 | reset worksheet 逐数组确认初始化和帧间语义。 |
| `step_basic_positions/rotations` 放在 particle buffer | 物理内存可复用，但语义上属于 substep scratch。 | native context 中单独分组，不进入持久状态签名或跨帧行为承诺。 |
| static `parent/depth/fixed/source mapping` 存进 particle buffer | 混合了 static mapping 与 dynamic state。 | static arrays 由 proxy/baseline spec 持有；context 可借用或复制，但生命周期与 dirty key 分开。 |
| buffer 随 topology/world generation 重建 | 保留。 | selection/proxy signature 变化也重建；纯 profile/settings 更新复用动态状态。 |

### Reverse-audit conclusion

B1-B3 不需要整体回滚。可保留的是 identity/signature 地基、slot 生命周期、动态 particle owner 和参数热更新方向；必须重构的是 source topology 命名、selection/baseline 阶段、initial state 字段归属，以及 persistent/scratch 分组。

在 S2 前不修改这些已提交代码，避免一边审计一边再次冻结新接口。未提交 B4 也不得作为修补 B3 的兼容层。

## S1 Status

W1-W7 已完成第一轮 producer/consumer/lifetime 审计；golden fixture v0 与 B1-B3 reverse audit 已同步扩展。S1 已关闭主要静态构建、center、particle reset、output 和 value parameter 主链，但还没有达到 source parity：

1. Mesh baseline 已有可信 Tier A host；Bone connection、Distance/Bending、parameters 和 runtime frame stages 仍需继续扩展同一 host 的 exporter/case，不能因 Mesh slice 完成就整体宣称 Tier A 覆盖。
2. self-collision 静态 primitive/write mapping、collider registration 与完整 frame solver order 仍需在对应能力启用前补 worksheet。
3. Normal/Split 的共同数学顺序已在 particle/output 主链确认，完整 constraint 调度对照仍需单独记录。
4. 当前 B4 工作区草案仍保持未提交；进入 S2 前先据 W1-W7 决定拆分重写或整体移除。
5. S2 首批冻结对象应限于 authoring/source identity、final proxy/baseline/Distance/Bending/Inertia static、16-sample value parameters、particle reset transition 和 setup-specific output mapping；deferred 能力必须显式标记。
