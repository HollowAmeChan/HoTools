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

因此 Blender vertex group -> 当前 proxy index 的直接映射只有在“用户 mesh 已是最终 proxy、无 reduction、拓扑同构”的受限输入域内才可能成立，属于 HoTools intentional deviation，不是 MC2 通用行为。

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
- child map 从最终 parent 反建；每个有 child 的 fixed 分别作为 baseline 起点遍历子树。

普通 multi-source BFS 只能复刻 reachability，不能复刻 parent 选择和 baseline order。

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
5. selection sample 与 proxy index 不同但空间相同，验证空间映射。
6. Triangle、DisableCollision 等附加 bit 与 Fixed/Move 的 OR 语义。

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
- direct vertex-group mapping 的受限输入域；
- packed 12/20、ushort/ulong 是否原样成为 native ABI，还是转为显式 32-bit ranges；
- source hash-container 顺序的 canonical debug/fixture 格式；
- Inertia、particle registration/reset 与 output mapping 的后续 worksheet。

## Golden Fixture Contract v0

### Oracle authority

fixture 按可信度分三级：

| Tier | 来源 | 可关闭的结论 |
|---|---|---|
| A | 在固定 commit 的 MC2/Unity 运行中导出中间数组。 | source parity；可以作为实现验收 oracle。 |
| B | 对最小输入手工推导完整数组，并逐项引用 producer 分支。 | 可关闭局部分支；不能覆盖 Unity 容器顺序或未观察上下文。 |
| C | HoTools 当前实现输出或旧 solver snapshot。 | 只能做 regression，不得证明 MC2 parity。 |

首选 Tier A。没有可运行 Unity dump 时，可先用 Tier B 冻结极小 case，但必须保留 `oracle_tier`，以后不能静默升级为 Tier A。

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

fixture contract 只定义数据交换与比较方式；当前阶段不创建伪造的 expected 数值。实际 fixture 必须来自 Tier A dump 或有完整手算证明的 Tier B。

## B1-B3 Reverse Audit

审计对象是 `5739ed3` 所在代码基线之前已经提交的 MC2 scaffold；未提交 B4 不作为既成接口。

### B1 Task/Parameter contracts

| 当前项 | 结论 | 后续动作 |
|---|---|---|
| `task_id = setup + order-independent source identity` | 保留。参数变化不应更换 slot identity。 | 增加 identity collision/Blender pointer reuse 测试。 |
| ordered source signature 进入 topology signature | 保留。Sequential mode 明确依赖 root order。 | oracle 比较时与 vertex order 分开记录。 |
| profile/setup/effective parameter 分层 | 方向保留。 | 仍需独立参数 worksheet 逐字段审计，当前不得整体标 source-aligned。 |
| `MC2SetupOptionsSpec.connection_mode in 0..2` | 不完整。 | D-01 决定 mode 3 surface；内部 source enum 不得遗失。 |
| `parameter_signature` 通过 default settings 构造 | 表达绕行但当前 payload 不含 settings，结果仍只覆盖 profile/setup。 | S2 改为直接、显式的 profile/setup signature，避免未来 payload 加入 settings 后静默改变 task contract。 |
| `MC2EffectiveParametersSpec.settings_signature` 与 payload 分离 | 可保留调度签名，但命名容易误导。 | 参数 worksheet 决定 settings 是否属于 effective solver input metadata。 |

### B2 Topology/slot

| 当前项 | 结论 | 后续动作 |
|---|---|---|
| `MC2TopologySpec` | 实际是 authoring/source snapshot，不是 MC2 final proxy topology。 | S2 重命名或拆成 source topology 与 proxy topology，禁止原样进入 native ABI。 |
| Mesh positions/normals/edges/fan triangles | HoTools 用户提供 proxy 的输入候选。Blender n-gon fan、loose edge、未求值 object data 都不是 MC2 通用 import 语义。 | 明确“最终 proxy、triangulated evaluated mesh”的输入前置条件或补 evaluated-mesh adapter。 |
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

W1、W2、W3 已完成第一轮 producer/consumer 审计；golden fixture v0 与 B1-B3 reverse audit 已记录。下一步不是实现，而是：

1. 决定并搭建 Tier A MC2/Unity 中间数组 dump 入口；
2. 决定 B4 工作区草案整体移除还是仅保留 lifecycle 相关测试；
3. 完成 Inertia、particle registration/reset 和 output mapping worksheet；
4. 参数字段 worksheet 完成后，再进入 S2 契约冻结。
