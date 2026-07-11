# MC2 源码语义与危险行为参考

更新日期：2026-07-11

文档状态：**固定 MC2 源码的语义/踩坑参考，不维护项目进度或 HoTools ABI**。当前状态、契约和执行顺序统一见 `MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

## 使用规则

1. 只有同时确认 producer、consumer、representation 和 lifetime 的行为才可称为 source fact。
2. HoTools 可以采用不同内存布局，但必须证明消费者语义等价；刻意缩小输入域时登记 intentional deviation。
3. MC2 的 `HashSet`、`NativeParallelHashSet`、`NativeParallelMultiHashMap` 枚举顺序通常不是公开协议。静态 membership 可 canonicalize，但已证明影响 runtime 数值的 record order必须单独冻结。
4. source manager direct index只是一次注册的句柄。fixture、task、result和 ABI 使用稳定 identity，不持久化 Unity direct index或 Blender pointer。
5. 旧 HoTools solver输出属于 Tier C regression，只能帮助定位问题，不能证明 MC2 parity。

## 1. Bone Connection 与代理拓扑

权威入口：`RenderSetupData.BoneConnectionMode`、`VirtualMeshInputOutput.cs::ImportBoneType()`、`DataUtility.PackInt2/PackInt3()`。

### 顺序不是逐链拼接

`RenderSetupData` 同时维护 authoring root顺序与 stack traversal transform顺序。后登记 root先出栈，child也按后项先出栈；最后一个 render transform不进入粒子顶点。MC2 vertex index不能由 `(root index, chain local index)` 推导。

HoTools 若使用自己的确定性 index，oracle必须先按 transform identity remap，再比较拓扑与结果。

### ConnectionMode 事实

| Mode | 规则 |
|---|---|
| Line | 只连接 transform parent-child canonical edge。BoneSpring 强制该模式。 |
| AutomaticMesh | root 先执行带反转的 nearest-chain 排序，再决定 loop。 |
| SequentialLoopMesh | 保留 authoring root顺序，只允许相邻 root同层连接，包含首尾。 |
| SequentialNonLoopMesh | 与 SequentialLoop 相同，但不连接首尾。 |

Automatic 不是普通 greedy：第一条边直接接受；后续 `minDist < lastDist * 1.5` 才接受，并以 `(lastDist + minDist) * 0.5` 更新；过长时反转已形成 root列表、清空 `lastDist`，从另一端继续。三个以上 root还用同一阈值判断首尾 loop。

### 分叉与三角形

- 同一 root、同一 level可以有多个 vertex；Sequential 会连接相邻 root同层的全部合法候选，不是 `zip`。
- Automatic 除最近候选外，还加入距离不超过最近距离 1.5 倍的候选。
- triangle 候选来自一个 vertex 的 link两两组合；零长度 link、夹角不小于 120 度、横跨三个 root、没有任一 main parent-child edge时拒绝。
- triangle 用 canonical `PackInt3` 去重，不保留 winding；最终 lines是 `edgeSet - triangleEdgeSet`，不是所有 parent/horizontal edge的并集。
- import topology之后仍要经过 selection/proxy conversion与 constraint `CreateData()`；不能把 import lines/triangles直接当 native constraint arrays。

启用 Bone Automatic/Sequential 前至少需要：过长边反转、loop/non-loop、分叉多对多、120 度边界、零长度和 residual line Tier A case。

## 2. Selection、Final Proxy 与 Baseline

权威入口：`SelectionData.cs`、`VertexAttribute.cs`、`VirtualMeshProxy.ApplySelectionAttribute()`、`ConvertProxyMesh()`、`CreateMeshBaseLine()`、`CreateTransformBaseLine()`、`CreateVertexRootAndDepth()`。

### Attribute 与阶段边界

`VertexAttribute` 是 byte bit field：Fixed=`0x01`、Move=`0x02`、InvalidMotion=`0x08`、DisableCollision=`0x10`、ZeroDistance=`0x20`、Triangle=`0x80`。既无 Fixed也无 Move才是 Invalid；“不移动”不等于只检查 Fixed。

SelectionData只含 sample positions、attributes、max connection distance和 user-edit标记。parent、root、depth、baseline和 constraint records都在 proxy conversion之后生成，不能合并进 selection spec。

MC2 通用路径会做 selection crop、merge/reduction/optimization和空间最近邻映射。HoTools 刻意限定为“用户 Mesh 已是 final proxy”，因此 Pin/attribute按 input vertex index直接映射。这个输入域是产品边界，不是通用 SelectionData parity。

### Blender Final Proxy

- triangle来自 reference Mesh `loop_triangles`；n-gon triangulation不增加 vertex。
- edge集合是显式 Mesh edges与全部 triangle edges的 canonical union，不能只读 `mesh.edges`。
- triangle membership在 finalization时 OR `Triangle` bit；Pin输入不能伪造该 bit。
- MC2 会统一相邻 triangle方向、生成 triangle normal/tangent、vertex-to-triangle flip records，并覆盖 triangle vertex的 final normal/tangent；baseline消费的是 final orientation，不是原始 Blender vertex normal。
- 每个 vertex最多登记 7 个相邻 triangle；超过上限、80 度 surface layer边界、反向 winding和 loose line都需要 oracle。
- line-only Mesh可使用 zero UV。含 triangle的 Mesh要求逐顶点唯一 UV；共享一个 Blender vertex的多个 loop UV不一致时必须报错并要求用户 split vertex，禁止取首 loop、平均或自动拆点。

### Mesh Baseline

- 无 Fixed时 parent全为 -1、child/baseline为空。
- 从全部 Fixed同时传播；Invalid不进入下一层。
- Move选择 parent时，Fixed候选用距离 cost，Move候选用当前-parent-grandparent夹角 cost。
- frontier不是两阶段统一提交：较早成功的 Move可以立即成为同 frontier后续 vertex的 parent。
- equal cost的 source结果受 hash枚举影响；HoTools固定最低 final-proxy index作为确定性边界，必须只在 equal-cost case登记偏差。
- local position使用 parent final normal/tangent构造的 rotation逆变换，不是简单相减。
- 参与 baseline且无 parent的 root quaternion为 identity；不在 baseline中的 vertex保持 zero quaternion。
- local length小于 `1e-8` 时 OR `ZeroDistance` 回 final attribute，因此 baseline build会改变最终 proxy signature。

### Bone Baseline 与 Depth

Bone baseline起点不总是登记 root。源码会沿不移动子树寻找“自身不移动且至少一个直接 child为 Move”的 vertex，再只遍历 Move child。连续多个 Fixed是合法输入。

每个 Move沿 parent累计几何长度，到第一个非 Move parent为 root；所有 chain共享整个 proxy的最大累计长度做 depth归一化。按单链离散层数分别归一化不等价，零长度边只贡献 0。

## 3. Distance Constraint

权威入口：`DistanceConstraint.cs::CreateData()`、`Register()`、`SolverConstraint()`。

### Static 表示

源码输出每 vertex一段有向邻接：packed `uint[N] indexArray`（12-bit count + 20-bit start）、`ushort[D] target`、`float[D] rest`。HoTools ABI展开为 checked `int32[N,2] ranges + int32[D] targets + float32[D] rest_signed`。

必须显式拒绝 source会静默截断的输入：单 vertex记录数超过 4095、start超过 1048575、target超过 65535。

### Build 语义

1. 普通 adjacency两端都不 Move时排除；任一端 Invalid时排除。
2. parent relation为 vertical，其余为 horizontal。每个 source range先拼 vertical bucket，再拼 horizontal bucket。
3. shear遍历一条 edge相邻 triangles的全部 pair，不只第一对；共享边退化时跳过。
4. shear要求 `abs(normalDot) >= 0.9396926` 且对角/共享边长度比误差 `<= 0.3`，用全局 undirected connect set去重。
5. shear分支只排除 opposite两端都不 Move，没有重复普通 edge的 Invalid过滤。这是危险但真实的 source边界，不能擅自修正。
6. horizontal rest用负号编码；`abs(rest) < 1e-8` 时无论原类型都写 `+0.0`，原 kind丢失。

### 顺序是数值语义

zero-distance runtime分支把 `addPos` 直接覆盖为 midpoint correction，而不是累加；随后仍增加平均分母。后续 nonzero记录继续在覆盖值上累加。因此同一 range内 `nonzero -> zero` 与 `zero -> nonzero` 会产生不同结果。

结论：

- 不得把 per-vertex records改成无向 pair solver。
- 不得按 target/kind重排。
- canonical membership只能诊断 static集合，raw order与 runtime output共同验收顺序。
- zero-distance不使用 stiffness、mass、scale或 animation pose ratio，也不能新增会改变 kernel分支的 synthetic kind。

当前 7 个 build fixture和 2 个 ordered runtime fixture已覆盖这些边界；`distance_static.py` 是生产 host builder，但尚无新 native consumer。

## 4. Triangle Bending

权威入口：`TriangleBendingConstraint.cs::CreateData()`、`SolverConstraint()`、`SumConstraint()`。

### Static 表示与 role

主数组只有：ordered quad `(opposite0, opposite1, edge.x, edge.y)`、rest angle/volume、marker/sign。quad角色直接进入 runtime，禁止把四点排序后写 ABI。

- 四点都不 Move或任一点 Invalid时排除。
- dihedral angle严格 `< 120°` 时生成 bending record。
- `90° <= angle <= 179°` 时紧接着尝试 volume record；同一 triangle pair可连续生成两条记录。
- dihedral sign为 -1/+1，方向为 0时写 +1；volume marker固定 100。
- volume用 initial local-to-world后的 world positions计算并乘 1000；runtime再消费 `scaleRatio * negativeScaleSign`。
- volume只按 sorted four-vertex key全局去重，保留 traversal中第一个未排序 role；bending不参与该去重。
- `writeBufferCount/writeData/writeIndex` 在固定源码 runtime未被消费，不进入新 ABI。

### Runtime Scratch

correction通过固定点原子累加到 per-particle count/vector scratch；`SumConstraint()` 只给 Move particle按 contribution count平均写回，然后无条件清零所有 scratch。scratch不是 N1 static，也不能跨帧持久化。

当前 13 个 static fixture与 3 个 runtime fixture已冻结阈值、double record、volume first-wins、Fixed/Move writeback、scratch average/clear和 negative scale消费。`bending_static.py` 已按 raw order实现 host builder、完整签名和只读 packer，并接入 Mesh slot static bundle；尚无新 native consumer。

## 5. Center、Particle Reset 与 Array Lifetime

权威入口：`InertiaConstraint.CreateData()`、`TeamManager`、`SimulationPreTeamUpdate()`、`SimulationStepUpdateParticles()`、`SimulationStepPostTeam()`。

### Center 不是一个扁平参数块

`centerFixedList`只保留“至少一个邻点为 Move”或孤立的非 Move vertex；连接全部为非 Move的 fixed不会进入 center。local center是保留项平均值。initial local gravity还依赖 final normal/tangent与 bind rotations。

CenterData至少分为：

| 域 | 内容 |
|---|---|
| static registration | center identity、fixed list、local center、initial local gravity |
| frame input | component/anchor/sync pose、scale、wind/collider references |
| persistent | old component/frame/anchor pose、smoothing与 teleport history |
| frame derived | frame center、movement、negative-scale matrix |
| substep derived | step/inertia vector与 rotation、angular velocity、scale ratio、gravity falloff |

anchor identity不是 `ClothParameters` scalar。只有 `anchor_inertia` 而没有 anchor source/pose时，不能声称支持 anchor。

### Allocation 不等于 Reset

`RegisterProxyMesh()`只分配 manager ranges。真正 reset使用**当前帧 proxy world pose**：position类数组写当前 world position，rotation类写当前 world rotation，velocity/friction/collision history清零。build-time local rest不能替代 current-frame reset。

每个 substep会重新构建 next/velocity-reference/base pose与 step-basic scratch；post step提交 old position、velocity与摩擦；display再使用 committed state与 real velocity。必须区分：

- persistent：old pose、animation history、display、velocity/friction/collision history；
- working：next、velocity reference、base position/rotation；
- scratch：step basic、constraint count/vector/write buffers；
- frame surface：current proxy world pose。

参数热更新不得清 particle history。首次 registration、用户 reset、时间倒退、static/backend重建可以复用统一 reset transition，但必须保留不同 reason。

## 6. Output 与 Blender 无反馈边界

MC2 core结果首先是 world-space proxy display pose。line output重建 Bone rotations；triangle output由 positions/UV、flip flags与 normal adjustment生成 vertex rotations。Bone随后通过 stable transform mapping转 local pose。

MC2 render mapping会做 bind/weight逆蒙皮，但 HoTools明确不实现该路径。MeshCloth输出固定为：

```text
world_delta = display_world - animated_base_world_positions
object_local_offset = inverse_linear(source.matrix_world) * world_delta
```

危险边界：

- N0 reference Mesh与N3 evaluated BasePose是两个数据域；骨架可移动顶点，但不能改变 vertex identity/connectivity。
- BasePose对象保留 Armature/Shape Key等 topology-preserving基础变形，永久移除物理 GN output。
- 直接读取源对象 evaluated mesh会包含物理 offset并反馈到下一帧，永久禁止。
- same-frame snapshot必须不可写；consumer不能原地污染 cache。
- 会增加、删除、重排或重新连接 vertex的 modifier不属于支持输入域。
- Mesh result不产生 mapping mesh；Bone result不暴露 manager index；PoseBone/GN真实写入都在公共 writeback。

## 7. Runtime Parameters

权威入口：`ClothSerializeDataFunction.GetClothParameters()` 与 `CurveSerializeData.ConvertFloatArray()`。

- 每条 curve转换为 16 个 runtime float samples；禁用 curve时 16 项都是基础值。native消费 samples，不消费 AnimationCurve key/handle。
- BoneSpring在归一化阶段强制 gravity=0、tether compression=0.8、distance stiffness=0.5、关闭 max distance/backstop/self/sync collision，并使用自身 collider/spring规则。
- checked speed limit关闭时使用 `-1`；damping与 angle restoration samples有 0.2 系数；Distance velocity attenuation固定 0.3。
- bending method、self mode/sync mode、collision dynamic/static ratio等派生值必须显式存在，不能只保留一个 stiffness scalar。
- animation pose ratio属于 team dynamic input；substeps/iterations/time scale属于 HoTools scheduler；二者都不属于纯 `ClothParameters` value block。
- anchor、collider、sync partner、wind zone是外部 identity/snapshot。只有对应 scalar不代表能力完成。

参数热更新仅适用于 value arrays。外部引用、collision primitive topology、proxy/baseline/constraint arrays变化仍可能需要 registration或context rebuild。

## 8. Collider 与 Self Collision

这两项在新路径启用前仍需独立 worksheet/oracle，不得直接复用旧 full-core即宣称完成。

- self collision是 broadphase、PointTriangle、EdgeEdge、Intersect、contact convert/update/cache、分帧与 solver/sum的完整管线，不是单个投影函数。
- 厚度、质量、摩擦、候选集与 contact生命周期相互影响；增大 thickness可能同时放大重复命中和黏连。
- MC2 intersect会按固定 divisor分帧；一次性处理全部 intersect不保证稳定等价。
- inter-cloth需要对象所有权、质量、contact汇总、sync与多体调度；不能把其他 mesh vertex简单转换为 sphere collider。
- Normal/Split job形态可以不同，但共同数学 producer/consumer顺序必须被记录和验证。

## Oracle 规则

| Tier | 来源 | 允许证明 |
|---|---|---|
| A | 固定 MC2 commit的 Unity runtime/reflection dump | source parity |
| B | 可完整手算且逐项引用 producer的最小 case | 局部分支/contract shape |
| C | HoTools当前或旧实现输出 | regression only |

Tier A host固定为 `tools/mc2_unity_oracle`（Unity 6000.3，外部引用固定 MC2 checkout）。商业源码/binary不进入仓库。废弃 HoClothUnity与旧 solver输出不得升级为 Tier A。

比较规则：

1. identity、index、bit、count、parent/root与 marker精确相等。
2. float默认 abs/rel tolerance `1e-6`；NaN/Inf一律失败。
3. 只有明确登记的 hash-container输出允许 canonicalize。
4. Distance保留 per-source ordered range；Bending保留 ordered role quad。
5. `-0.0` 与 `0.0` 数值可相等，但 Distance zero kind loss必须单独验证。
6. expected必须来自上游 producer；禁止用下游 HoTools结果回填 expected。

当前可信覆盖：Mesh final proxy、9 个 Mesh baseline case、7 个 Distance build + 2 个 runtime-order case、13 个 Bending static + 3 个 runtime-scratch case。尚缺 Bone connection、N2完整参数、Center/reset、output rotation、collider/self-collision和完整 frame step的 Tier A闭环。
