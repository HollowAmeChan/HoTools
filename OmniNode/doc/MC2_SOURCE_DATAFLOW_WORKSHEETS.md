# MC2 源码语义、特化与差异记录

更新日期：2026-07-16

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文只保存会影响实现正确性的固定源码事实、危险顺序、Blender边界、故意差异和冲突处理。它不维护完成度、当前任务或测试流水；这些分别属于 `MC2_ACCEPTANCE_MAP.md`、`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md` 和 Git。

## 写作边界

- **应该写**：固定source producer/representation/consumer/lifetime、顺序敏感数值、Blender特化、拒绝域、故意差异，以及已确认会影响替代资格的冲突入口和最终处理结论。
- **不应该写**：当前完成百分比、下一提交计划、fixture数量流水、某次Blender帧号、临时调试输出、公共Physics World结构或普通实现说明。
- **内容路由**：完成度与证据摘要写`MC2_ACCEPTANCE_MAP.md`；尚未完成工作的顺序写`MC2_SOURCE_ALIGNMENT_EXECUTION_PLAN.md`；跨solver结构写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；测试实现放测试文件，历史过程只留Git。
- **保留门槛**：只有未来维护者可能再次踩到、且会改变语义/支持域/冲突决策的内容才进入本文；普通“已经接线”描述不进入。

## 使用规则

1. 同时确认 producer、representation、consumer 和 lifetime 后，行为才可登记为 source fact。
2. HoTools可以改变内存布局和调度形态，但必须保持consumer语义；刻意缩小输入域或canonicalize顺序时登记差异。
3. source的hash/container枚举顺序通常不是协议。只对不影响数值identity的集合排序；已影响runtime的record order必须原样冻结。
4. Unity manager direct index与native handle都是短生命周期句柄。fixture、task、result和ABI只使用stable identity。
5. 旧HoTools/HoCloth solver输出是Tier C regression，不是MC2 parity证据。
6. 文档与实现冲突时，验收表先降级，再扩充oracle；禁止用下游HoTools结果回填expected。
7. 固定MC2 source对齐与旧HoTools产品替代是两条证据链。旧实现中的输入解释、identity/排序、业务特化、缓存和写回行为必须单独核账；source oracle不能自动证明这些产品语义已经被保留。

## 故意差异登记

| ID | 主题 | 固定源码/Unity形态 | HoTools决策 | 保留原因与验收边界 |
|---|---|---|---|---|
| DEV-01 | Mesh输入 | selection crop、merge、reduction、optimization、render mapping | 用户Mesh就是单final proxy，vertex identity一一对应 | Blender产品边界；不宣称通用Selection/Mapping parity |
| DEV-02 | Packed ABI | 12/20-bit range、`ushort` target、manager direct index | checked `int32` range/index、stable identity | 防静默截断与跨帧句柄泄漏；raw fixture仍验证source上限 |
| DEV-03 | Hash等价项 | equal-cost/hash枚举顺序不稳定 | baseline equal-cost取最低final-proxy index；self grid同键保留输入顺序 | 只canonicalize非协议顺序；membership、run边界和数值record order不得改变 |
| DEV-04 | Bone triangle | `ImportBoneType()`产生全零UV，triangle tangent/basis可退化 | Automatic/Sequential最终含triangle时prepare阶段拒绝 | 不合成UV、不静默删triangle；Line安全域单独验收 |
| DEV-05 | Blender BasePose | Unity renderer/transform直接提供动画proxy | 双对象：只读BasePose + 源对象常驻GN offset | 隔离物理反馈；改拓扑modifier和loop UV seam不在支持域 |
| DEV-06 | Bone写回 | manager transform index与Unity Transform | stable armature/data identity + bone name，生成parent-local `matrix_basis` plan | result不泄漏manager index；真实写入由公共writeback执行 |
| DEV-07 | Job调度 | Unity Job/NativeSort/并行queue | C++单context和确定性queue canonicalization | 不复制job形态，只冻结共同数学producer/consumer顺序 |
| DEV-08 | 力场 | MC2私有Wind对象/manager | wind是未来Physics World通用力场的一种kind | 当前`wind_*`只是兼容参数面，无公共快照时按零外力 |
| DEV-09 | Signed transform | Unity Transform/TRS语义 | 只接受可分解为proper rotation + signed scale且无shear的域 | Armature自身负缩放可用；负缩放父级、零scale、shear和负PoseBone scale拒绝 |
| DEV-10 | 旧接口 | HoTools曾暴露`substeps/iterations`与旧full-core ABI | 保留必要节点兼容面，但新V0只消费声明过的scheduler/ABI | 兼容字段不代表能力；旧实现不得成为fallback或oracle |
| DEV-11 | BoneCloth横向连接 | MC2按transform/root列表、距离或列表相邻关系生成横向membership | HoTools保留按骨名、显式链分组和节点输入组合横向连接的产品语义 | 一个链参数节点对应一个profile+task横向组；同Armature多组保持独立context并合并为一次原子写回，最终连接仍必须由隐式debug直接显示 |
| DEV-12 | Component与step粒度 | MC2按component/team分别拥有manager调度单元 | HoTools只有一个公开MC2 solver step，一次处理全部active tasks；一个MC2 component映射为粒子参数profile与task的组合 | 节点图更简洁并允许跨task统一调度/交互；持久状态仍按task slot/context隔离，不能合并成隐藏全局状态 |

新增差异必须先回答：source行为是什么、为什么不照搬、支持域缩小到哪里、用什么证据防止差异继续扩散。

## 1. Topology、Attribute 与 Baseline

### Bone Connection

权威入口：`RenderSetupData.BoneConnectionMode`、`VirtualMeshInputOutput.ImportBoneType()`、`DataUtility.PackInt2/PackInt3()`。

- authoring root顺序与stack traversal顺序不同；后登记root、后项child先出栈，最后一个render transform不进入particle vertex。不能用`(root index, chain local index)`推导MC2 vertex index。
- Line只连接canonical parent-child edge，BoneSpring强制Line。
- Automatic先做可能反转的nearest-chain排序：第一边接受；后续只有`minDist < lastDist * 1.5`才接受，并更新平均距离；过长时反转已形成root列表后从另一端继续。三个以上root用同阈值判断loop。
- Sequential保留authoring root顺序，同层相邻root做多对多连接；Loop额外连接首尾，NonLoop不连接。
- triangle来自同一vertex的link两两组合；零长度、夹角`>=120°`、横跨三个root、无main parent-child edge时拒绝。
- triangle只按canonical `PackInt3`去重，不保存winding。只有第一次插入时登记两条`triangleEdgeSet`，重复发现不会补第三边，所以可能保留residual line。
- import topology之后仍需selection/proxy conversion与constraint builders；import line/triangle不是N1 constraint array。
- 产品模式的Bone socket输入表示共用父骨；共用父骨不进入模拟，其direct children按Blender集合顺序成为各链链首。链内遇到分岔只跟随`children[0]`；需要其它分支时必须显式拆成另一输入组。显式`bones`列表则按给定名称顺序冻结链。
- 产品连接模式固定为0=仅纵向、1=按task链顺序连接相邻链、2=在模式1基础上首尾成环；只连接相同chain-local depth，短链不补点。task链顺序、连接模型和mode都进入拓扑签名，不能按空间距离重排。
- 一个Bone链参数节点/公开BoneCloth task调用对应一个`profile+task` component和一个横向组；同一Armature上的多个component不互建横向边、各自持有slot/context，但公开Bone写回按Armature合成一个原子batch。骨名重叠的component在world写事务前拒绝；跨Armature输入拆成多个task。
- 固定MC2 source的imported Bone triangle仍遵循DEV-04并拒绝；`hotools_product`横向拓扑产生的triangle属于故意产品模型，以chain index/depth生成稳定UV后进入Bone static/native。两种connection model必须保持独立签名和拒绝域。
- 产品差异边界：source fixture证明`mc2_source`规则，产品fixture冻结上述名称、分组、顺序、分岔、profile+task identity、多task失败原子性和合并写回；最终连接的viewport可见性由D-01单独关闭。

### Attribute 与 Final Proxy

`VertexAttribute` bit：Fixed=`0x01`、Move=`0x02`、InvalidMotion=`0x08`、DisableCollision=`0x10`、ZeroDistance=`0x20`、Triangle=`0x80`。既非Fixed也非Move才是Invalid。

- Blender triangle来自`loop_triangles`；edge是显式edges与triangle edges的canonical union。
- Triangle bit由finalization OR进去，Pin输入不能伪造。
- MC2统一相邻triangle方向并生成normal/tangent、vertex-to-triangle flip records；baseline消费final orientation。
- 每个vertex最多登记7个相邻triangle；80度surface layer、反向winding与loose line都是需要保留的source边界。
- line-only可用zero UV。含triangle时要求逐vertex唯一UV；共享vertex的loop UV不一致必须报错并要求split vertex。

### Mesh/Bone Baseline

权威入口：`CreateMeshBaseLine()`、`CreateTransformBaseLine()`、`CreateVertexRootAndDepth()`。

- Mesh无Fixed时parent全`-1`，child/baseline为空；从全部Fixed同时传播，Invalid不进入下一层。
- Move选parent：Fixed候选用距离cost，Move候选用current-parent-grandparent夹角cost。frontier内较早成功的Move可立即成为后续vertex的parent。
- local position用parent final normal/tangent rotation的逆变换，不是简单相减。baseline root quaternion为identity；不在baseline内的vertex保持zero quaternion。
- local length `<1e-8` 时回写ZeroDistance，因此baseline build会改变最终proxy signature。
- Bone baseline起点是“自身非Move且至少一个direct child为Move”的vertex，不一定是登记root；连续Fixed合法。
- Bone depth按到首个非Move parent的累计几何长度，再除以整个proxy的全局最大累计长度；不能按单链层数归一化。

### Connection-aware Bone Rotation

顺序固定为：current base写temp → Line baseline root-to-child原地更新 → Triangle normal/tangent覆盖 → TriangleSum → normal adjustment → `vertexToTransformRotation` → world到parent-local。

- Line child消费parent rotation、local rotation与当前向量偏转；parent朝全部child的原始/当前平均向量旋转。
- Fixed/root使用`rootRotation`，Move使用`rotationalInterpolation`；最后从current base rotation按`blendWeight` slerp。
- `animationPoseRatio=1`消费current animated parent-child pose，不是initial local vector。
- triangle flip record bit0翻normal、bit1翻tangent；聚合后使用`LookRotation(cross(normal,tangent), normal)`再乘normal adjustment。

## 2. Substep 数值顺序与 Constraint 陷阱

生产数学顺序固定为：

```text
Center/frame transform
  -> prediction + animated baseline
  -> Tether
  -> Distance
  -> Angle
  -> TriangleBending/Sum
  -> Point/Edge collider
  -> Distance (second pass)
  -> Motion
  -> Self Collision
  -> post
```

### Tether

- 位于prediction与首次Distance之间，消费Move、root/depth、step-basic vertex/root distance、next和velocity-reference。
- compression/stretch来自N2槽24/25；固定width=0.3、stiffness=1、velocity attenuation=0.7。
- 不得因没有独立static array而改变调度位置或把它并入Distance。

### Distance

权威入口：`DistanceConstraint.CreateData/Register/SolverConstraint`。

- source是per-vertex ordered ranges，不是无向pair；每段先vertical后horizontal。horizontal rest用负号编码，`abs(rest)<1e-8`统一写`+0.0`并丢失kind。
- 普通adjacency排除双方非Move或任一Invalid；shear只排除opposite双方非Move，不重复普通edge的Invalid过滤。
- shear遍历共享edge的全部triangle pair；要求`abs(normalDot)>=0.9396926`且对角/共享边长度比误差`<=0.3`。
- zero-distance分支覆盖当前`addPos`而不是累加，随后仍增加分母，所以`nonzero -> zero`与`zero -> nonzero`不同。禁止重排target/kind。
- packed source上限：每vertex count 4095、start 1048575、target 65535；HoTools在ABI边界显式拒绝溢出。
- `CONFLICT-01`已核清：旧worksheet曾称persistent velocity/attenuation未闭合；当前V0两次Distance均把`correction * float_values[26]`写入velocity-reference，post直接消费，Tier A `particle_step_constraints_post_001`跨两个子步验证下一步消费已提交velocity。旧结论作废，不得再次作为缺口引用。

### Angle

- 位于首次Distance与Bending之间，消费baseline parent/range/data、depth、step-basic pose、next与velocity-reference。
- Restoration/Limit由N2 int槽4/5控制，curve槽3/4；velocity attenuation、gravity falloff、limit stiffness来自float槽28..30。
- Restoration curve在`ClothParameters`转换时已经乘0.2，native不得二次缩放；仍需乘`simulationPower.w=(90/frequency)^1.8`。

### Triangle Bending

- ordered quad角色为`(opposite0, opposite1, edge.x, edge.y)`，禁止排序四点后写ABI。
- angle严格`<120°`生成dihedral；`90°..179°`还会紧接生成volume，同一triangle pair可有双record。
- volume marker=100，world volume乘1000；runtime再消费`scaleRatio * negativeScaleSign`。
- volume只按sorted four-vertex key去重并保留遍历中的首个未排序role；bending不参与该去重。
- fixed-point correction按participant count平均，只写Move；每次Sum后全部count/vector scratch无条件清零。

### Motion 与 Post

- Motion位于第二次Distance后、post前；Max Distance/Backstop始终相对插值后的animated base pose，不得消费已被baseline改写的step-basic。
- depth先平方再采样curve槽5/6；只处理Move且无InvalidMotion。显式启用时MaxDistance曲线值0表示锁到base，不是关闭。
- post提交old position、velocity、dynamic/static friction、collision normal与real velocity；参数热更新不得清这些history。

## 3. Center、Scheduler 与 Array Lifetime

Center数据必须分域：

| 域 | 内容 |
|---|---|
| static | center identity、fixed list、local center、initial local gravity |
| frame input | component/anchor pose、scale、collider/force-field snapshot |
| persistent | old component/frame/anchor pose、smoothing与teleport history |
| frame derived | current center、movement、negative-scale matrix |
| substep derived | inertia vector/rotation、angular velocity、scale ratio、gravity falloff |

- `centerFixedList`只保留至少一个邻点为Move或孤立的非Move vertex；local center是保留项平均值。
- anchor/force field是外部identity+snapshot，不是只有一个scalar即可成立的参数能力。
- register/allocation只分配range。reset必须使用当前帧world pose写position/rotation history，并清velocity/friction/collision；build-time rest不能替代reset。
- 每个substep重建next、velocity-reference、base pose与step-basic；post才提交persistent history。

关键冲突顺序：

1. component scale sign变化先构建`nowCenterTRS * inverse(oldCenterTRS)`，变换Center persistent与particle position/rotation/velocity history。
2. 再处理anchor/world inertia、movement/rotation limit、time-scale与skip造成的frame shift；shift必须绕正确的old component/transition pivot。
3. configured Reset优先于negative matrix消费：reset同帧跳过matrix并把全部history归当前animated pose。
4. configured Keep先消费negative matrix，再围绕transition后的pivot应用100% frame shift；不能与Reset共用顺序。
5. pause/zero time scale可更新dynamic、frame shift、candidate和Center history，但不伪造native substep。
6. scheduler先计算planned/update/skip，再按每个step interpolation刷新Fixed/animated pose；一帧只发布最终candidate。

数值特化：

- Move inertia深度为`depthInertia * (1 - depth^2)`；同一frame transform必须同时作用于particle position、rotation、velocity-reference和velocity。
- movement smoothing权重为`(1 - smoothing)^3 * 0.99 + 0.01`，persistent smoothing velocity只有native step成功后才能提交。
- teleport检测位于anchor adjustment之后、movement smoothing之前。Keep跳过smoothing并把平移/旋转shift ratio强制为1；Reset清零shift和smoothing velocity。
- time-scale cancellation在world-inertia shift之后继续消去剩余量；skip count产生的other-shift也属于frame shift，不能折进substep dt。
- fixed list可生成不同于component pose的current Center。result frame pose必须保留Fixed-derived Center，不能在输出阶段退回component pivot。

状态数组必须区分：persistent（old/display/velocity/friction/contact）、working（next/velocity-reference/base）、scratch（step-basic/count/vector）与frame surface（current proxy world pose）。static替换/reset清contact与intersect状态；value参数热更新保留history。

## 4. Collider 与 Self Collision

### 外部 Collider

- 帧输入唯一来自Physics World current/previous snapshot；按group mask过滤并排除自身owner。
- Point radius为`radiusCurve(depth) * scaleRatio`。普通setup只处理Move且非DisableCollision；BoneSpring允许有效Fixed/Move并消费animated base与collision-limit curve。
- Edge复用proxy edge并按source `Move=0x02`判断；不得沿用旧full-core `0x04`。
- BoneSpring只接受Sphere；其它primitive不得借普通Point/Edge能力进入soft-sphere路径。
- BoneSpring Sphere依次执行max-length clamp、按`limitedLength/radius`插值到0.85的反弹衰减、friction距离倍率3；平均push correction还要同步加入velocity-reference。
- collider阶段产生的friction/normal必须被第二次Distance与post继续消费。

### 单 Cloth Self Collision

- primitive注册顺序Point→Edge→Triangle；纯Line只有Edge。kind在flag 24..25，Fix0/1/2为`0x04000000/0x08000000/0x10000000`，AllFix=`0x20000000`，Ignore=`0x40000000`。
- 首个实际substep更新primitive inverse mass、thickness、swept AABB与grid。grid size是未扩张Edge最大长度的3倍；最大长度接近0时grid/contact/intersect保持空。
- grid按X→Y→Z与Unity.Mathematics 1.2.6 signed hash组织run；hash碰撞的不同grid保留独立run。
- broadphase只建唯一Edge-Edge和Point-Triangle候选；执行AABB、Ignore、双方AllFix和共享particle过滤。并行queue顺序不是identity，HoTools按candidate key canonicalize。
- EE在old pose求`s/t/normal`；old最近距离`<1e-9`时拒绝。PT在old pose求`uvw`，首substep要求point方向与old triangle normal的绝对dot不小于`cos(60°)`并冻结正反面sign。
- EE预测距离使用`<= thickness + thickness*SCR`，PT使用严格`<`；thickness、插值参数、normal与sign按IEEE binary16量化。
- 首substep只把enable项加入contact list；同frame后续substep不重建candidate，只更新现有contact，disable项仍留在list。
- 每substep固定4轮SolverContact→SumContact。correction乘`1e6`后按C# int cast向零截断并int32累加；按调用次数平均后乘`1e-6`还原，每轮清scratch。
- 新frame首substep前读取上一帧grid，只检测`index % 2 == frame % 2`的Edge→Triangle；整帧final substep后才复测当前位置并把命中写到Edge particle flag，下一帧映射到primitive低3位。
- static替换/reset必须清contact key、intersect record、particle flag与primitive低3位。

### 跨物体 Self Collision 与半径冲突

- 产品scope冻结为MeshCloth profile上的“跨物体自碰撞”开关：开启的active task自动加入同一world交互，不暴露`List[Object]`/ListObj socket。零group mask表示自动允许全部；非零mask复用公共1..16碰撞组并要求双方互相允许，因此仍可做可控分区。
- solver先同步全部task slot/context，再按相同substep dt/final gate锁步推进。每个task仍独占持久particle/self状态；world-owned `MC2InteractionV0`只在Motion之后、Post之前按owner拼接动态primitive，执行一次跨task grid/broadphase、EE/PT contact、4轮solve/sum和跨帧intersect，再把位置与intersect flag散回原context。相同owner永远由本地self阶段处理，聚合层不重复求解。
- scope identity由排序后的task identity、primary group和mask组成；动态加入、移除或分区变化清聚合contact/intersect history并增加scope revision，不销毁未变化的task context。只有sync开关开启、内部self关闭的Mesh仍更新primitive，但不构建本地contact。
- 四个10×10 cloth、400 vertices/2092 primitives基准中，自动全互碰与显式all-pairs图均为6 pairs、峰值14607 candidates/14223 contacts、约194096 bytes聚合buffer；自动mean 0.675ms/p95 0.858ms，ListObj-like all-pairs mean 0.685ms/p95 0.875ms并额外消耗约0.0045ms Python identity resolver。两者物理pair相同，ListObj没有数值或性能收益；稀疏图已由group/mask表达。4→3→4动态scope revision为1→2→3，实测重建帧约3.11/2.17/3.05ms。
- source模式继续保留独立`self_collision_thickness`以维持固定MC2 oracle；HoTools公开Mesh产品只有`radius × 顶点组`一个authoring真值，自碰厚度固定派生为`radius * 0.25`，公开Particle Profile不再暴露第二厚度/曲线输入。
- 18×18双层grid、3606 primitives基准中，source thickness 0.005与`radius 0.02 * 0.25`候选/接触完全相同（4932/3776），多次运行mean约1.1..1.3ms；直接把0.02 radius当self thickness会增至187385 candidates、146893 contacts和约24.1..24.3ms。因此不能直接合并为同数值半径。
- 外部collider只消费普通particle radius，不能覆盖self的Edge-Edge、Point-Triangle和跨帧intersection；不得用“把其它cloth转碰撞体”替代world self interaction。debug必须把普通半径与派生self envelope并列显示并标注固定比例，但不制造第二authoring字段。

self collision是primitive、grid、broadphase、EE/PT narrowphase、half contact、4轮solve/sum、跨帧intersect和cache生命周期的整体。sync/inter-cloth还需要多体ownership、质量汇总和调度，不能把另一张mesh转成sphere列表替代。

## 5. 隐式 Debug 可观测性

- MC2遵循SpringBone VRM蓝本：debug入口只表达请求、scope和显示过滤，自动发现world内匹配slot；不为Bone连接、Backstop、自碰等中间态增加用户接线socket。
- 请求在下一次真实推进帧由backend捕获，一次性请求消费后清除；continuous模式才持续采样。无请求时不得执行native debug readback、per-item dict展开或viewport几何构建。
- renderer只消费slot/native debug snapshot和真实result stream，禁止根据当前RNA、最终位置或Blender对象重新推导“看起来合理”的中间态。
- `physicsMC2DebugDraw`是唯一公开MC2调试入口：`always_run`节点自动发现world内匹配slot，只写一次性请求和语义过滤器；下一真实native advance冻结per-task context与world interaction状态，同帧、reset-only和无substep调用不消费请求。
- 冻结快照按Topology、Motion、Center、Collision、Self和Output分层。Topology直接保存Bone纵/横边、链组、Fixed/Move和final proxy；Center保存frame sync、step、frame shift、Keep/Reset Teleport、world/local抵消矩阵与negative-scale transition；Collision同时保存外部packed collider、普通radius和派生self thickness；Self保存primitive/grid/candidate/contact/intersection；Output保存native位置与writeback plan摘要。
- viewport renderer只消费上述只读数组和普通值，不读当前RNA、不从最终result反推过程。请求关闭时不调用任何debug read ABI；连续显示由节点每次执行重新请求下一推进帧，world dispose同步清除draw store。
- MC2最小语义层：Topology（Bone纵/横连接、链分组、Fixed/Move、final proxy）、Motion（MaxDistance/Backstop及法向轴）、Center/Inertia（teleport阈值/触发原因、world/local变换抵消、负缩放）、Collision（普通半径、外部collider、自碰厚度/primitive/grid/candidate/contact/intersection）和Output（candidate/writeback target）。每个影响空间边界或分支判定的参数必须有绘制、数值overlay或明确的“非空间量”诊断理由。

## 6. Output 与 Blender 边界

Mesh输出是world display pose相对同帧animated base的delta，再转换为source object-local offset：

```text
world_delta = display_world - animated_base_world_positions
object_local_offset = inverse_linear(source.matrix_world) * world_delta
```

- N0 reference Mesh与N3 evaluated BasePose是不同域；BasePose保留Armature/Shape Key等不改拓扑变形，永久移除物理GN output。
- 读取已接受物理offset的source evaluated mesh会形成反馈，永久禁止。
- same-frame snapshot只读；结果只重发同revision，不重复step/read。
- topology mismatch不截断/填充，清零陈旧offset并记录diagnostics；下一有效结果再恢复。
- Mesh不产生mapping mesh；Bone不暴露manager index；solver/readback/debug都不直接写Blender。

Bone position转换使用完整Armature inverse；rotation使用proper component inverse，禁止非均匀/负scale泄入PoseBone `matrix_basis`。PoseBone object-space必须是proper、shear-free且正scale；不满足时在snapshot/writeback前拒绝。

## 7. Runtime Parameters 与外部身份

- 每条curve固定转换为16个float32 sample，位置为`i/15`；禁用curve时全部为基础值。native不消费AnimationCurve key/handle。
- float32舍入步骤属于语义；不能先用double合并表达式再一次转换。
- BoneSpring归一化强制gravity=0、tether compression=0.8、distance stiffness=0.5，并关闭max distance/backstop/self/sync collision。
- checked speed limit关闭时用`-1`；damping与Angle restoration sample包含源码0.2系数，Distance velocity attenuation固定0.3；bending method、self/sync mode、collision ratio等派生值必须显式存在。
- animation pose ratio属于team dynamic；frequency/max step/time scale属于scheduler；anchor、collider、sync partner、force field属于外部identity/snapshot。
- value arrays可以hot update；外部引用、primitive topology、proxy/baseline/constraint arrays变化需要registration或context rebuild。

## 8. MC2 Host/Native 边界特化

固定数据流：

```text
Blender authoring/frame input
  -> profile + task combinations
  -> one MC2 solver step: normalize all active tasks
  -> raw immutable Blender snapshots (prepare all before write)
  -> native fingerprint + N0/N1 producers
  -> per-task slot-owned native context
  -> N2/raw N3 sync -> native frame-derived production -> reset/step/readback
  -> one Physics World result transaction
  -> public writeback
```

| 层 | 内容 | 生命周期 |
|---|---|---|
| H0 identity | task/setup/source/target、ordered Bone root identity | host/session；不进入kernel |
| H1 authoring | profile、curve authoring、Pin/selection、bone hierarchy、外部identity | host immutable；重建/诊断 |
| H2 raw snapshot | Blender连续positions/normals/UV/index/attribute、Bone rest/pose matrix、component pose | prepare/frame；不保存派生solver数组 |
| N0 proxy static | fingerprint、final proxy、orientation、UV、attribute、baseline、output mapping | native context static |
| N1 constraint static | Distance/Bending/Inertia等精确数组 | slot static |
| N2 runtime parameters | curve samples、scalar/bool/enum、team options、scheduler | hot update |
| N3 frame input | animated pose、component/anchor/collider snapshot、dt与连续性 | frame |
| N4 state/scratch | Center/particle history、working arrays、constraint scratch | persistent/substep |

边界不变量：

1. evaluated pose不进入N0签名；静态mapping不能伪装成动态参数；allocation不等于reset。
2. 公开MC2 step一次处理全部active tasks；MC2 component identity由profile+task组合表达。每个active task唯一持有slot与opaque context，context只由slot dispose链释放。
3. 全部task先完成只读prepare；任一task失败时不得进入world写事务。进入写事务后按task同步并统一发布result transaction，不能把每个task伪装成独立solver step。
4. static使用完整staged build后原子替换；失败保留旧context/result。value/scheduler hot update保留history。
5. same-frame不重复step；reset、倒放、跳帧与generation变化保留不同reason。
6. ABI只接收连续C-order固定dtype、finite、checked range/index和`xyzw` quaternion。
7. result/debug不含bpy对象、manager index或native handle；solver不inline writeback。
8. create失败不破坏旧slot；free幂等；发布/writeback失败恢复上一完整事务。
9. 大数组派生producer与consumer必须同属native context：Frame orientation、Bone pose rotation和Center不得回到Python；Final Proxy/Baseline/constraint static按P-06分步迁移。Python只传raw Blender snapshot，除公开result与显式debug外不读回native中间态。
10. 静态dirty分类由slot-owned native context持有`topology=1 / geometry=2 / surface=4 / config=8`四位mask。Mesh raw输入覆盖object/mesh identity、edges、loop triangles、loop→vertex、positions/normals、UV与Pin权重；Bone raw输入覆盖Armature identity、requested/resolved names、parents、head/tail与rest matrix。纯Pose和same-frame为零；gravity direction只置config；旧context没有指纹时必须安全全重建。Python只组合每个task的短摘要并组织staged transaction，不再保存平行的contract key或signature字符串。
11. Mesh Final Proxy的triangle-direction连通层/80°阈值/整层翻转，以及edge union、vertex adjacency、每顶点triangle/flip、final normal/binormal和bind pose，由`mc2_static_build` C++结果唯一生产。solver prepare一次bulk读取`MC2MeshRawSnapshot`，fingerprint与Final Proxy共享positions/normals/edges/triangles/loop UV/Pin weights；snapshot只活到本次prepare结束，不得存入slot。normal规范化与fallback tangent由native bulk kernel生产，staged line/triangle及方向优化保持ndarray，不得恢复逐vertex Python math或tuple往返。Mesh topology token由读取Final Proxy的owner一次验证并随结果上交；生产Topology使用同一native fingerprint构造compact metadata，完整payload只属于显式oracle入口。staged context在构建前创建；Proxy七组vectors与frame producer三组vectors使用受限命名capsule，在完整校验后直接move且revision只增加一次，ZeroDistance最终attribute在move前写入同一owner。Finalizer adjacency/triangle/bind数组仅以ndarray transient存活到同次Distance/Center构建结束，生产slot随后只保留coverage/count metadata。下一步只迁移BasePose兼容topology token，不能恢复第二次RNA读取。
12. Mesh Baseline的Fixed并行frontier传播、parent cost/tie-break、children/baseline展平、ZeroDistance、root/depth与local pose，以及Bone共用的ZeroDistance/root/depth/local pose，由`mc2_static_build` C++结果唯一生产。Mesh staged十组vectors使用受限命名capsule在完整校验后直接move进context，供同次Distance消费的transient随后立即丢弃parent/child/baseline/local-pose ndarray；生产slot不构造完整immutable baseline spec，只保留count/signature与全隐式debug曲线采样所需的只读`float32 depths`。无context Tier A/Bone兼容入口仍返回完整spec。ZeroDistance最终attribute在Proxy move前写入owner，不再调用生产路径的补写复制；P-06d继续收口Bone过渡输出。不得恢复已删除的Python producer、完整生产shadow或Bone私有转发。
13. Distance的vertical/horizontal分类、共享edge全部triangle pair、`0.9396926f` normal-dot、`0.3f`长度比、shear逆序插入、float32 rest与`+0.0`编码，由`mc2_static_build` C++结果唯一生产。Mesh路径在固定dtype内容签名完成后，把名称/data pointer/size均匹配的capsule vectors直接move进staged context，slot只保留record count/signature metadata；Bone与无context Tier A兼容入口仍返回完整spec供P-06d上传/oracle。Python不得恢复triangle normal、edge map、shear循环、第二份阈值或move后的ndarray读取。
14. Bending的反向triangle bucket顺序、ordered quad role、float32 dihedral/sign、`<120°`弯曲、`90°..179°` world-volume、sorted membership first-wins与marker `100`，由`mc2_static_build` C++结果唯一生产。Mesh路径在固定dtype内容签名完成后，把名称/data pointer/size均匹配的capsule vectors直接move进staged context，slot只保留record count/signature metadata；无context Tier A入口仍返回完整oracle spec。Python不得恢复angle/volume数值循环、edge map、第二份角度阈值或move后的ndarray读取。
15. Self primitive registration的Point/Edge/Triangle source顺序、Fix0/1/2、AllFix、Ignore、int3 particle role与平均baseline depth，由`mc2_static_build` C++结果唯一生产；Mesh路径在内容签名完成后，把名称/data pointer/size均匹配的capsule vectors直接move进staged context，slot只保留签名/count metadata。无context的Tier A/Bone兼容入口仍返回完整oracle spec；跨物体membership、半径/厚度采样、grid/contact/intersection由world/native runtime按K-06/K-07合同处理。Python不得恢复`_primitive_flag`、primitive生产循环或move后的ndarray读取。
16. Center static的Fixed边界筛选（排除Move及完全被非Move邻点包围的内部点）、fixed local中心、bind修正姿态平均与initial local gravity，由`mc2_static_build` C++结果唯一生产。Mesh路径先建立固定dtype内容签名，再把名称/data pointer/size匹配的capsule vectors直接move进staged context，slot只保留fixed count/signature metadata且`center_static_revision`只能增加一次；native/host rotation两类frame input均调用context内同一个Center pose producer。完整`MC2CenterStaticSpec`与packer仅保留无context Tier A oracle和Bone P-06d兼容上传；Python不得恢复邻接筛选或姿态平均数值循环。

## 9. Oracle 与冲突处理

| Tier | 来源 | 允许证明 |
|---|---|---|
| A | 固定MC2 commit的Unity runtime/reflection dump | source parity |
| B | 可完整手算且逐项引用producer的最小case | 局部分支或contract shape |
| C | HoTools当前/旧实现输出 | regression only |

Tier A host固定为`tools/mc2_unity_oracle`（Unity 6000.3，外部固定MC2 checkout）；商业源码/binary不入仓库。

比较规则：

1. identity、index、bit、count、parent/root、marker精确相等。
2. float默认abs/rel tolerance `1e-6`；NaN/Inf一律失败。
3. 只有DEV-03或同等级明确登记的非协议容器顺序允许canonicalize。
4. Distance保留per-source ordered range；Bending保留ordered role quad。
5. `-0.0`与`0.0`数值可相等，但Distance zero kind loss单独验证。
6. fixture必须标明隔离掉的能力，不能从no-collision/no-wind case外推对应能力已完成。
7. 发现代码、执行计划与本文冲突时：记录冲突→验收表降级→定位source producer/consumer→补最小Tier A→修代码或本文→最后升级验收表。

## 10. 生产可达性与 Python 代码边界审计

公开生产入口只有节点侧收集参数后调用一次 `step_mc2`。该调用先把全部 active 输入规范化为 `profile + task` 组合，再为每个组合维护独立 slot/native context；它不是 MC2 的逐 component 公开 step。所有 task 的 topology、static、frame input 和 staged context 必须先只读准备成功，随后才进入统一 substep 推进与一次 Physics World result transaction。

| 路径 | 静态生产链 | 逐帧生产链 | 输出 | 异常与释放 |
|---|---|---|---|---|
| MeshCloth | `task -> raw mesh arrays -> native四类fingerprint/change mask -> native Final Proxy/Baseline/Distance/Bending/Center/Self producer -> staged native context`；Proxy/frame/Baseline/Distance/Bending/Center/Self均已move，Finalizer/Baseline/Final Proxy仅在同次构建保留transient，生产slot只留必要metadata；P-06b/P-06c剩余工作是把Blender bulk snapshot直接接入native producer并删除Python提取/冻结冗余 | BasePose只上传world positions/component pose；native context内部生产triangle orientation与Center，collider/runtime/scheduler同步到slot context | stable Mesh vertex identity -> GN delta result | prepare失败保留旧slot/result；重建先staging后替换；slot prune/world dispose释放context与BasePose cache owner |
| BoneCloth | `task -> raw Bone rest/hierarchy arrays -> native四类fingerprint/change mask -> host product/source connection -> native共用Final Proxy/baseline pose-depth/Distance producer -> 过渡host Bone static -> native context`；P-06b/P-06d继续收口owner | 只上传Armature component pose、PoseBone head与raw 3x3 pose matrix；native生产world rotation与Center | stable Bone name -> 同Armature合并后的parent-local原子writeback plan | 跨Armature拆task；同Armature骨名重叠在发布前拒绝；任一component失败则整批不发布，slot/world释放context |
| BoneSpring | 与BoneCloth共享Bone Line static链，但setup adapter与归一化参数固定Spring支持域 | 同Bone frame链；只消费Sphere soft collider，关闭self/sync与不支持约束 | stable Bone name -> Bone transform transaction | 非Line、非Sphere或越出归一化支持域在prepare拒绝，不进入native/writeback |
| World common | `build_task_specs -> native fingerprint/classify -> topology/static -> per-task slot/context`；world唯一持有interaction context | 全task frame sync后按scheduler substep批量推进；跨物体self由world interaction context锁步；debug仅在下一真实advance按请求冻结 | Mesh/Bone/stats先形成candidate，再由公共transaction发布 | staged create/update/read任一步失败都dispose新资源并保留旧事务；stale slot、Cache Delete、clear、重编译和unregister沿owner链幂等释放 |

状态所有权固定如下：world拥有跨task interaction和发布事务；slot拥有单个`profile + task`的runtime identity、scheduler、center调度history与native context；particle position/rotation/history只存在于native context，不再有生产`MC2ParticleBuffer` shadow；immutable authoring/raw snapshot没有释放职责，frame snapshot和result candidate只活到本次公开step提交。测试可保留host buffer作为oracle，但生产import必须为零。

生产/参考路径分类：

- `nodes/declaration/capabilities/specs/topology/setups`是authoring、注册、identity与Blender snapshot边界；`solver/state/scheduler/native/interaction_scope/results/debug`是公共runtime；static builder和`parameters/runtime_parameters`是host packing边界。三setup的代表性Blender资产均从这些入口到达真实native与writeback。
- `bone_rotation.py`是固定MC2 source的host oracle，只由Tier A测试直接调用；生产Bone输出由native `read_bone_output`消费。它不能作为生产fallback，也不能用其测试通过宣称生产能力。
- `schema/properties/capabilities`分别拥有字段描述、RNA注册和UI/registry声明；setup adapter、BasePose、frame input与delta output分别拥有setup dispatch、缓存身份、evaluated snapshot和GN写回资源。它们虽然较小，但不是可删除的参数转发文件。

P-05纯整理删除了math抽离后仅保留旧私有函数名的import aliases，并删除只固定`setup_type="mesh_cloth"`、没有校验/身份/事务职责的`build_mc2_mesh_final_proxy`包装；内部调用现在直达`math3d`规范函数或`build_mc2_final_proxy`唯一实现。保留的本地math helper负责输入域、float32舍入或稳定错误信息；保留的setup/Blender wrapper必须至少增加task/source解析、cache identity、snapshot、资源生命周期或事务职责。整理不改变参数、默认值、更新频率、支持域、ABI或数值顺序。
