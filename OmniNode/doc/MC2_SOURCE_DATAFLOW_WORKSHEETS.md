# MC2 源码语义、特化与差异记录

更新日期：2026-07-17

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
11. Mesh Final Proxy的triangle-direction连通层/80°阈值/整层翻转，以及edge union、vertex adjacency、每顶点triangle/flip、final normal/binormal和bind pose，由`mc2_static_build` C++结果唯一生产。solver prepare一次bulk读取`MC2MeshRawSnapshot`，fingerprint、Final Proxy与BasePose兼容拓扑token共享positions/normals/edges/triangles/polygon loop/loop UV/Pin weights；snapshot只活到本次prepare结束，不得存入slot。normal规范化与fallback tangent由native bulk kernel生产，staged line/triangle及方向优化保持ndarray，不得恢复逐vertex Python math或tuple往返。Mesh topology token由固定端序的数组流式SHA-256唯一产出，Final Proxy直接消费snapshot；旧BasePose token仅在读取对象的实际拓扑与预期匹配后原地迁移，不得以token不同直接绕过校验。生产Topology使用同一native fingerprint构造compact metadata，完整payload只属于显式oracle入口。staged context在构建前创建；Proxy七组vectors与frame producer三组vectors使用受限命名capsule，在完整校验后直接move且revision只增加一次，ZeroDistance最终attribute在move前写入同一owner。Finalizer adjacency/triangle/bind数组仅以ndarray transient存活到同次Distance/Center构建结束，生产slot随后只保留coverage/count metadata。P-06b已关闭，下一阶段进入Bone P-06d。
12. Mesh Baseline的Fixed并行frontier传播、parent cost/tie-break、children/baseline展平、ZeroDistance、root/depth与local pose，以及Bone共用的ZeroDistance/root/depth/local pose，由`mc2_static_build` C++结果唯一生产。Mesh与Bone staged十组vectors均使用受限命名capsule在完整校验后直接move进context，供同次Distance消费的transient随后立即丢弃parent/child/baseline/local-pose数据；生产slot不构造完整immutable baseline spec，只保留count/signature与全隐式debug曲线采样所需的只读`float32 depths`。无context Tier A入口仍返回完整spec。ZeroDistance最终attribute在Proxy move前写入owner，不再调用生产路径的补写复制。不得恢复已删除的Python producer、完整生产shadow或Bone私有转发。
13. Distance的vertical/horizontal分类、共享edge全部triangle pair、`0.9396926f` normal-dot、`0.3f`长度比、shear逆序插入、float32 rest与`+0.0`编码，由`mc2_static_build` C++结果唯一生产。Mesh与Bone staged路径均在固定dtype内容签名完成后，把名称/data pointer/size匹配的capsule vectors直接move进context，slot只保留record count/signature metadata；完整spec只属于无context Tier A/oracle。Python不得恢复triangle normal、edge map、shear循环、第二份阈值、生产packer上传或move后的ndarray读取。
14. Bending的反向triangle bucket顺序、ordered quad role、float32 dihedral/sign、`<120°`弯曲、`90°..179°` world-volume、sorted membership first-wins与marker `100`，由`mc2_static_build` C++结果唯一生产。Mesh路径在固定dtype内容签名完成后，把名称/data pointer/size均匹配的capsule vectors直接move进staged context，slot只保留record count/signature metadata；无context Tier A入口仍返回完整oracle spec。Python不得恢复angle/volume数值循环、edge map、第二份角度阈值或move后的ndarray读取。
15. Self primitive registration的Point/Edge/Triangle source顺序、Fix0/1/2、AllFix、Ignore、int3 particle role与平均baseline depth，由`mc2_static_build` C++结果唯一生产；Mesh与Bone staged路径均在内容签名完成后，把名称/data pointer/size匹配的capsule vectors直接move进context，slot只保留签名/count metadata。无context的Tier A入口仍返回完整oracle spec；跨物体membership、半径/厚度采样、grid/contact/intersection由world/native runtime按K-06/K-07合同处理。Python不得恢复`_primitive_flag`、primitive生产循环、生产depth tuple往返、packer上传或move后的ndarray读取。
16. Center static的Fixed边界筛选（排除Move及完全被非Move邻点包围的内部点）、fixed local中心、bind修正姿态平均与initial local gravity，由`mc2_static_build` C++结果唯一生产。Mesh与Bone staged路径先建立固定dtype内容签名，再把名称/data pointer/size匹配的capsule vectors直接move进context，slot只保留fixed count/signature metadata且`center_static_revision`只能增加一次；native/host rotation两类frame input均调用context内同一个Center pose producer。完整`MC2CenterStaticSpec`与packer仅保留无context Tier A oracle；Python不得恢复邻接筛选、姿态平均数值循环、生产tuple化或packer上传。

17. Bone生产prepare使用短生命周期`MC2BoneRawSnapshot`一次读取names/parents/head-tail/rest matrices，native fingerprint、source/product connection和Bone static必须共享该snapshot。同一task内相同Armature只允许遍历一次name/parent，head/tail/matrix使用Blender `foreach_get`整体读取后按source骨名切片；`matrix_local`的列主序展平必须在snapshot边界转成现有row-major合同。生产`MC2SourceTopologySpec`只保留稳定`bone_names`和轻量Armature身份，不得冻结每骨dict；Bone frame直接消费`bone_names`，不得逐帧`_thaw`。完整payload仅保留给显式oracle/兼容入口，不得把snapshot或整Armature临时数组长存到slot。

18. Bone生产`update_bone_static`只接受native producer的8组registration owner：adjoining vertex/triangle ranges+data、bind position/rotation、normal adjustment rotation和vertex-to-transform rotation。前6组由Final Proxy producer的Bone owner mode产出，后2组由Bone rotation producer产出；Proxy 7组owner也必须先直接move，随后Baseline/constraint注册。缺owner必须失败，不得回退`pack_mc2_bone_registration_static`或`pack_mc2_proxy_static`复制；完整packer只保留给Tier A/oracle。

19. Bone rest matrix到transform quaternion/local normal/local tangent的正交化与旋转由`mc2_build_bone_rest_frames_v0` C++ bulk kernel唯一生产；Python static builder只组织identities/parents/heads并消费连续输出，不得恢复逐骨`matrix4_tuple_from_flat -> quaternion_from_matrix -> rotate_vector`转发。该kernel复用`mc2_static_build.cpp`现有`matrix_to_quaternion/normalize/rotate`语义，不得建立第二套四元数阈值。native小步验证固定使用`_native\build.bat 313 native`：该target不clean，且Jolt为`EXCLUDE_FROM_ALL`不参与编译。

20. finalized Bone normal/tangent到vertex-to-transform rotation的`conjugate(vertexOrientation) * transformRotation`由共享C++ bulk kernel唯一生产，必须复用同文件的orientation/quaternion实现。staged路径通过`mc2_build_bone_registration_rotations_v0`把normal adjustment与vertex-to-transform的float32 owner直接交给context；Python不得恢复逐vertex数值循环、生产packer或copy fallback。无context oracle仍可使用原输出buffer入口。

21. Bone children ranges/data与transform baseline flags/ranges/data由`mc2_build_bone_transform_baseline_derived_v0` C++ producer唯一生产。children存储顺序固定为同parent内vertex index降序，DFS stack反向弹出以保持source处理顺序；只有包含Move子点的Fixed节点开始baseline，Line flag仍由非Triangle成员派生。Python不得恢复`_source_children/_dense_ranges/_flatten/_build_transform_baselines`或平行派生树。下一步将pose-depth与该producer合并，让Baseline整组vector以owner capsule直接move进context。

22. Bone transform-baseline producer同次产出final attributes/root/depth/local pose，不得恢复第二次`_build_native_baseline_pose_depth`调用。生产注册顺序固定为Proxy owner、Baseline owner、Distance/Center/Self owner、Bone registration owner，`owned_static_take_count`固定为6。完整Bone tuple bundle当前只允许活到本次`update_bone_static`完成，随后压缩成`MC2BoneClothStaticMetadata`；slot只保留stable identities、Proxy attributes/edges/triangles、debug depths、count/signature与connection product metadata。结果写回必须直接消费`final_proxy.vertex_identities`。P-06d下一步必须用staged Bone native data消除同次prepare的完整tuple派生树，不得把owner已move误称为host transient已清零。

23. Finalizer、Baseline与Bone static内容签名必须使用`mc2_proxy_finalizer_static_v2`、`mc2_baseline_static_v2`、`mc2_bone_static_v4`固定标签与固定dtype连续字节流；显式spec和staged native data必须调用同一函数。不得恢复`json.dumps`、逐element字符串拼接、仅生产侧私有哈希或为签名重建tuple/list树。签名算法变化会自然触发slot/cache重建，不得把旧token误当跨schema持久合同。

24. Bone staged路径必须返回`MC2BoneNativeData`并复用Proxy/Finalizer/Baseline native data类型；完整四层immutable spec只属于无context Tier A/oracle。Distance/Center/Self在同次prepare直接消费native arrays，注册完成后只允许`MC2BoneClothStaticMetadata`进入slot。不得为类型兼容重建tuple spec、把owner arrays回读为完整Python树，或让result/debug重新依赖transient native data。

25. Bone production assembly必须直接拼接`MC2BoneRawSnapshot`的positions/matrices/parents并保持rest输出、attributes/roots与产品UV为连续数组；staged入口缺任一raw snapshot必须失败，不得回退冻结payload或`_flatten_bone_records`。逐骨list/tuple assembly、完整spec、packer与`_thaw`只允许出现在显式无context oracle。P-06d据此关闭，后续P-06e不得为重建复用重新引入这些host shadow。

26. P-06e重建复用必须发生在native context之间：旧context保持只读，新staged context按change mask复制不变static并只运行受影响producer，全部成功后由Python原子替换slot；失败释放staged context并保留旧context/result。`config=8`当前只代表gravity direction并只允许重建Center；不得把native static回读为Python spec或为了复用恢复host shadow。Mesh/Bone config已实现：分别复制五/六类不变static，Center在native重算并内部生成与cold oracle一致的SHA-256，只返回fixed count/signature metadata；两者owner上传均为零。large Mesh config约`5.08ms`，同轮surface全量重建约`20.96ms`。

27. P-06e change matrix固定为：`topology`改变邻接/primitive/identity，全部static producer失效；`geometry`改变Proxy orientation/rest、Baseline、Distance/Bending/Center及Bone registration，全部数值producer失效；Mesh Pin `surface`改变Fixed/Move attributes并传播到Baseline/Distance/Bending/Center/Self；Bone surface恒定；`config`只改变Center。Mesh UV-only不改变数值约束，但当前Proxy/Finalizer/Baseline/Distance/Bending/Center/Self metadata通过Proxy signature形成完整身份链，因此保持全量重签/重建，除非未来新增独立UV子指纹及native重签合同。large UV-only约`20.50ms`，与Pin约`20.50ms`相同且仍比旧CPP重建快约`32x`，不阻塞替代。

28. 生产static注册只允许staged builder与named owner capsule路径。`MC2NativeContextV0`不得提供从完整Proxy/Baseline/Mesh bundle二次pack/upload的便利入口；Bone registration前必须已由同次builder完成Proxy/Baseline/Distance/Center/Self注册，缺metadata直接失败。显式oracle可保留纯packer函数验证dtype/content，但不得由context owner或生产solver调用。

29. Blender raw snapshot读取是允许保留的host热点边界：`foreach_get`/UV/Pin/Bone rest读取用于检测任意脚本、编辑模式与数据变化，连续数组随即交给native fingerprint/producer，不得在Python派生solver static。2026-07 depsgraph handler实测中，BasePose/GN正常逐帧求值与真实Mesh geometry/Pin/UV authoring都会产生Object/Mesh geometry update；Bone Pose与rest编辑也都会产生Armature geometry update，因此当前标志无法安全跳过snapshot。任何未来dirty tracker必须先增加能区分authoring与solver/evaluation更新的稳定revision合同，否则不得以性能为由漏检重建。

30. P-07/P-09所有权边界现为永久删除态：`mc2_kernels.cpp/.hpp`只持有新context需要的共享数值kernel，`mc2_context_v0.*`、`mc2_static_build.*`与`mc2_self_collision.cpp`属于新Physics World保留集合；`mc2_context.*`、`mc2_bonecloth_io.cpp`、旧数组/context/IO binding及legacy构建选项均已物理删除。`311 native`与`313 native`必须只构建`hotools_native`并通过新`_REQUIRED_SYMBOLS`、raw V0/static及纯MC2门禁，不得恢复旧公开ABI来满足链接。

31. P-08删除准入已成立：产品拓扑、跨物体self、单半径、全隐式debug、all-task transaction、生命周期、性能和独立构建均无开放决策。P-09只能删除第30条legacy集合和旧Python节点/package，不得删除或复制共享kernel，也不得在新runtime增加compat import、fallback ABI或旧节点adapter。删除前后的最后可比benchmark证据固定使用P-08同轮Blender 5.1结果。

32. P-09/P-10已关闭：旧Python Mesh/Bone package、旧native context/IO、11个legacy ABI及只服务旧路径的测试/benchmark已删除。官方11份MC2预设JSON迁入`physicsWorld/mc2/presets`并直接挂到`physicsMC2ParticleProfile`；转换器只写公共profile真实socket，`radius`映射源粒子半径，不写`self_collision_thickness`或第二套曲线。删除后`18/18` native/raw、`26/26`纯MC2、Blender 4.5属性契约`9/9`、Blender 5.1代表资产`8/7`及180帧soak通过；当前切入P-11逐文件职责与依赖审计。

33. P-12第一批纯整理已删除根package 106项和Mesh setup 11项无仓库消费者的lazy re-export，删除BasePose两个无人调用的固定spec转发，并把5个真实跨模块helper改为公开且带域名的合同名称；Center的纯`inverse quaternion`改名转发已改为直接调用共享`math3d`。生产代码由约16.8k降到约16.6k行，private import与re-export桶均为0，单调用函数由59降到56；依赖强连通分量仍为1，下一批只处理DTO/adapter反向边。`26/26`纯MC2与Blender 4.5属性/节点/生命周期`9/9`通过。

34. P-12第二批将setup adapter从持有`topology.py`函数对象改为持有稳定builder标识，并由topology owner本地解析；现有`debug_dict()["topology_builder"]`值和非法setup拒绝行为不变。setup注册不再反向import topology，该依赖环已消失；全局审计剩下的唯一强连通分量只由native boundary与其DTO producer构成。Python 3.11下`26/26`纯MC2通过，Blender 4.5下属性/节点合同`9/9`及注册/注销生命周期通过；后续以该组合为主门禁，3.13/5.1保留为兼容与soak补充。

35. P-12第三批将原`native.py`的扩展加载/符号资格与context host拆成单向依赖：`native.py`只定位、缓存和校验`hotools_native`，`native_context.py`才持有slot context、world interaction、ABI调用和按需debug readback。static producer只依赖loader，solver/debug显式依赖context host，不使用lazy import或兼容re-export。`audit_mc2_architecture.py --check`现为46个生产模块、约16.7k行、0依赖环、0 private import、0 legacy命中；`26/26`纯MC2、raw owner、Blender 4.5 Mesh `7/7`、Bone static/writeback、interaction 5项、全隐式debug 6项、属性合同`9/9`及生命周期均通过。

36. P-12第四批将未发布的`MC2ResultCandidateV1`及其构造校验并入`results.py`，删除没有独立生命周期的`candidate.py`；candidate仍是`ready=False`的事务内部阶段，数组copy/read-only、schema、native identity校验及Mesh/Bone promotion顺序不变。生产模块由46回到45，审计仍为0依赖环/0 private import/0 legacy命中；`26/26`纯MC2、Blender 4.5 Mesh `7/7`及Bone多task原子step/writeback通过。

37. P-12第五批将仅保存slot frame continuity/reset/lifecycle计数的`state.py`并入`frame_state.py`，删除两个互相引用的碎片；`collider_frame.py`经消费者审计后保留，因为它独立拥有World collider snapshot的owner排除、group/type过滤、shape规范化、previous-frame配对和连续数组签名，不是纯DTO。P-12收口时生产44个模块、约16.6k行、0依赖环、0 private import、0 lazy re-export桶、0 legacy命中；`26/26`纯MC2与Blender 4.5属性/节点/存储合同`9/9`通过。

38. P-13第一批将MC2 nanobind注册从通用module shell抽出到`mc2_bindings.cpp/.hpp`；`hotools_native.cpp`只保留module初始化、PropertyCurve 8个binding、SpringBone 7个binding和单一`bind_mc2` 调用，MC2 74个binding的顺序、名称、lambda和参数校验原样保留。`build.bat 311 native`仅增量生成`hotools_native.cp311-win_amd64.pyd`，无Jolt target；3.11全量native回归`26/26`，其中MC2 raw/native `18/18`。审计现统计6个相关C++单元约14.8k行：module shell 168行/15 bindings，MC2 binding owner 1670行/74 bindings，context仍7538行/50个Python入口。

39. P-13第二批将不依赖context state的Mesh/Bone static fingerprint从`mc2_context_v0.cpp`抽到`mc2_fingerprint.cpp`；两个公开ABI及其hash顺序原样移动，仅将`finite_floats`/`dict_string`边界校验本地化，不引入context内部header或状态访问。3.11 native-only增量构建无Jolt，MC2 raw/native `18/18`通过。审计现统计7个单元：context由7538降到7338行/47个Python入口，fingerprint为238行/3个Python返回入口；下一步才建立共享context state合同以拆分剩余执行owner。

40. P-13第三批将`Mc2ContextV0`、`Mc2InteractionParticipantV0`与`Mc2InteractionV0`三个唯一内部数据布局移入`mc2_context_internal.hpp`的`hotools::mc2_internal`命名空间；原context单元通过using消费同一类型，没有复制字段、新建host shadow或将Python对象存入state。context实现文件由7338降到7110行；3.11 native-only增量构建无Jolt，全量native `26/26`通过。该internal header是后续static/frame-step/interaction-debug translation unit的唯一state合同，不对binding或Python公开。

41. P-13第四批将context helper的匿名namespace命名为`hotools::mc2_internal`，公开`PyObject*` ABI仍位于`hotools`并通过内部namespace消费原函数；没有改变符号名、函数体或state布局。这一步让后续translation unit可以只声明实际共享helper，不需要复制buffer/state校验。3.11 native-only增量构建无Jolt，全量native `26/26`通过。

42. P-13第五批将九个只读/按需派生入口移入`mc2_context_readback.cpp`：粒子结果、Self primitive/grid/candidate/contact/intersection、Bone output、step-basic与Center step。`mc2_context_helpers.hpp`只公开该单元实际需要的capsule解析、live/shape校验、Bone派生和小型float字典helper；纯`mc2_context_internal.hpp`仍不依赖Python。context主单元由7110降到6605行/38个Python入口，readback为522行/9个入口。3.11 native-only增量构建无Jolt，全量native `26/26`与Blender 4.5全隐式debug 6项通过。

43. P-13第六批将world-owned interaction的5个公开入口移入`mc2_context_interaction.cpp`：create/inspect/all-context step-group/按需debug/free。`Mc2ContextStepStateV0`归入纯internal state header，interaction只通过helper header调用同一per-slot step/self内核；没有创建第二份particle或contact state。context主单元由6605降到6167行/33个Python入口，interaction为444行/5个入口。3.11 native-only增量构建无Jolt，全量native `26/26`、Blender 4.5跨物体交互5项与全隐式debug 6项通过。

44. P-13第七批将context内的clone-config、Proxy/Finalizer/Baseline/Bone/frame-producer以及Distance/Bending/Self/Center static 10个入口整体移入`mc2_context_static.cpp`。该单元直接消费唯一context state与`mc2_static_build` owner vectors；`copy_values`/`validated_owned_values`模板归入helper header以保持真实capsule move校验，没有增加Python packer或host round-trip。context主单元由6167降到4892行/23个Python入口，static为1258行/10个入口。3.11 native-only增量构建无Jolt，全量native `26/26`、Blender 4.5 Mesh `7/7`与Bone static/writeback通过。

45. P-13第八批将Center dynamic/参数、raw Mesh/Bone frame producer、collider upload、reset/setup flags与per-context step整体移入`mc2_context_frame_step.cpp`。共享`Vec3`类型与已有vector/quaternion/matrix helper签名进入internal合同，数学实现仍只在core一份；无Python粒子history或frame repack回路。context主单元由4892降到3852行/7个Python返回入口，frame-step为1051行/16个入口。3.11 native-only增量构建无Jolt，全量native `26/26`及Blender 4.5 Mesh `7/7`、Bone frame、负缩放component、跨物体interaction通过。

46. P-13最终批次将实现文件`mc2_context_v0.cpp`改名为`mc2_context_core.cpp`，并将跨translation-unit公开声明改名为`mc2_api.hpp`；`v0`继续只存在于公开符号和state类型中表示schema版本，不再作为实现文件的迁移标签。core是context生命周期、inspect/fingerprint分类与共享数值编排helper的唯一owner；static、frame-step、interaction和readback单元只消费同一internal state/helper合同。Python 3.11 native-only增量构建只输出`hotools_native.cp311-win_amd64.pyd`且无Jolt，native `26/26`及Blender 4.5 Mesh `7/7`、Bone frame、负缩放component、跨物体interaction 5项通过，P-13关闭。

### 8.1 P-11代码事实与职责审计

审计入口为`tools/audit_mc2_architecture.py`。它使用Python AST解析生产模块和相对import，用强连通分量报告依赖环，并报告跨模块私有import、`_EXPORTS`桶、单调用函数；C++部分固定统计相关translation unit、内部include、`m.def`和`PyObject*`入口。`--check`把生产依赖环和legacy命中作为失败条件，P-12/P-14必须让它通过。

删除后基线事实：生产Python为45个模块、约16.8k行；存在1个16模块依赖强连通分量、5个跨模块私有访问、根package 106项和Mesh setup 11项lazy re-export。单调用函数共59个，其中属性getter、dataclass factory和产品节点是合法边界；确认需要清理的是Center math改名转发、未使用BasePose delta转发、Mesh baseline签名转发及重复matrix/tuple helper。C++相关5个translation unit约14.7k行；`hotools_native.cpp`约1.7k行并注册89个跨域binding，`mc2_context_v0.cpp`约7.5k行且含50个Python入口；生产legacy命中为0。

删除后基线的依赖强连通分量由以下边形成：原`native.py`在模块顶层读取Center/Distance/Self/frame DTO，对应static producer反向import `native_module`；`topology`运行时读取`setups` adapter，而三个adapter又读取topology builder。P-12已用稳定builder标识断开adapter反向边，并将纯native loader与context host分层；当前生产import DAG无环，不存在lazy import掩盖环或兼容re-export。

| Python文件 | 当前唯一主要职责 | 审计结论/处理 |
|---|---|---|
| `mc2/__init__.py` | component/solver registry manifest | 保留manifest；删除无仓库消费者的106项lazy export兼容桶 |
| `names.py` | 稳定solver/setup/channel标识 | 保留，不吸收行为 |
| `capabilities.py` | solver能力与更新频率声明 | 保留，与declaration各自单一职责 |
| `declaration.py` | registry公开solver声明 | 保留，不import runtime owner |
| `nodes.py` | 产品节点surface与task/profile组装 | 保留；只调用公开authoring API |
| `presets.py` | 官方MC2 JSON到粒子profile socket转换 | 保留；不得写第二套self半径 |
| `parameters.py` | 纯profile/setup/settings/effective参数合同 | 保留；冻结编解码不得被其他模块私有import |
| `specs.py` | task identity、source identity与task list规范化 | 保留；`_source_token`改为公开共享identity合同 |
| `runtime_parameters.py` | profile到固定native参数ABI采样/打包 | 保留；消除对`parameters._thaw`的private访问 |
| `scheduler.py` | 单次all-task step共享的固定步长调度 | 保留 |
| `solver.py` | all-task prepare/sync/step/result原子事务 | 保留为唯一orchestrator；static prepare/rebuild热点按P-13直接迁入C++ owner，不再增加Python中间层 |
| `native.py` | `hotools_native`路径定位、进程级加载缓存与MC2符号资格校验 | 只保留loader/qualification；不import DTO、context host或solver |
| `native_context.py` | slot context与world interaction的Python handle生命周期、ABI调用与按需readback | 唯一context host；依赖producer DTO但producer只反向依赖`native.py` loader，不形成环 |
| `frame_state.py` | particle frame合同、slot continuity/lifecycle计数与frame transition plan | 已合并原`state.py`；不持有particle history或native handle |
| `collider_frame.py` | shared World collider snapshot过滤、shape规范化、previous-frame配对与连续数组合同 | 保留独立adapter owner；不持有collision solve算法 |
| `interaction_scope.py` | 自动跨物体self交互task-pair ownership | 保留独立产品策略，不引入ListObject兼容路径 |
| `results.py` | 私有candidate、公共result envelope、Bone/Mesh promotion、事务发布和stats读取 | 唯一result owner；不向外发布`ready=False`的candidate |
| `debug.py` | 隐式debug请求、按需native capture与冻结快照 | 保留，不import bpy renderer |
| `debug_draw.py` | Blender viewport renderer与过滤器 | 保留；只消费冻结快照，不反推RNA/最终结果 |
| `topology.py` | Blender Mesh/Bone raw snapshot、native fingerprint和轻量topology | 保留单次authoring读取边界；公开共享identity/thaw或消除调用，不暴露private helper |
| `static_data.py` | Proxy/Finalizer/Baseline显式Tier A合同、内容签名和packer | 保留为oracle/合同owner；生产不得回退完整packer |
| `mesh_baseline.py` | Mesh baseline staged producer/metadata | 保留；删除仅转发`mc2_baseline_content_signature`的壳 |
| `distance_static.py` | Distance Tier A与staged metadata | 保留独立数值域 |
| `bending_static.py` | Bending Tier A与staged metadata | 保留独立数值域 |
| `self_collision_static.py` | Self primitive Tier A与staged metadata | 保留；厚度只由公共radius派生 |
| `center_state.py` | Center static DTO、frame/reset/negative-scale oracle和persistent state | 当前混合3种职责且最大；P-12先移除math转发，P-13随native迁移拆分执行owner，不复制Center状态 |
| `bone_connection.py` | MC2与HoTools产品横向连接topology合同 | 保留产品差异点，不能折回通用MC2分支 |
| `bone_rotation.py` | Bone Line/Triangle rotation Tier A合同 | 保留独立oracle数值域 |
| `bone_static.py` | Bone proxy/baseline/registration staged data与显式oracle | 保留；公开共享attribute helper，消除private import |
| `setups/__init__.py` | 三setup adapter registry | 保留；不得import完整static/runtime模块 |
| `setups/contracts.py` | 轻量adapter DTO | 保留；topology builder依赖改为稳定标识或无环公开合同 |
| `setups/bone_cloth/__init__.py` | BoneCloth adapter声明 | 保留package入口，不增加重导出桶 |
| `setups/bone_cloth/static_build.py` | BoneCloth/BoneSpring staged static assembly | 保留setup专属owner；消除`topology._thaw`private访问 |
| `setups/bone_frame_input.py` | BoneCloth/BoneSpring共享Blender pose frame adapter | 保留；直接消费公开raw/topology合同 |
| `setups/bone_spring/__init__.py` | BoneSpring adapter声明 | 仅17行；P-12并入setup registry或保留最小package时不得再包一层转发 |
| `setups/mesh_cloth/__init__.py` | MeshCloth adapter声明 | 保留adapter；删除11项lazy export桶 |
| `setups/mesh_cloth/base_pose.py` | BasePose proxy对象和delta modifier生命周期 | 保留；删除无人调用的固定spec转发函数 |
| `setups/mesh_cloth/delta_output.py` | Mesh结果delta attribute/modifier写回 | 保留写回owner；矩阵转换与frame adapter共用单一公开helper |
| `setups/mesh_cloth/frame_input.py` | Mesh双对象Blender frame snapshot | 保留；不持有solver history |
| `setups/mesh_cloth/final_proxy.py` | Mesh raw到final proxy staged producer/metadata | 保留；tuple helper只允许oracle分支并与Bone共用 |
| `setups/mesh_cloth/static_build.py` | Mesh staged static assembly/registration顺序 | 保留setup专属owner |
| `setups/mesh_cloth/schema.py` | 无bpy持久RNA字段单一schema | 保留，不能并入properties导致纯声明加载bpy |
| `setups/mesh_cloth/properties.py` | schema到Blender PropertyGroup注册 | 保留，只消费schema |
| `setups/mesh_cloth/capabilities.py` | schema到component capability映射 | 保留，与properties共享schema而不互相import |

| C++文件 | 当前事实 | 维护边界 |
|---|---|---|
| `hotools_native.cpp` | 168行通用module shell；只注册PropertyCurve/SpringBone 15个binding并调用`bind_mc2` | 已收口；不得恢复MC2参数细节或context状态 |
| `mc2_bindings.cpp/.hpp` | 1670行，唯一注册MC2 74个nanobind ABI，持有typed adapter的边界校验/转换 | 保留单一`bind_mc2`入口；不持有context状态或数值kernel |
| `mc2_context_internal.hpp` | `Mc2ContextV0`、interaction participant/aggregate的唯一内部数据布局 | 只定state，不定义ABI/helper/数值行为；不对binding或Python公开 |
| `mc2_context_helpers.hpp` | 跨context单元最小helper声明，依赖纯state与Python buffer边界 | 只公开真实跨单元消费者，禁止变成无分层的全量internal API |
| `mc2_api.hpp` | MC2 context/interaction/fingerprint公开C ABI的唯一声明表 | 只声明稳定ABI；`v0`表示schema版本，不表示旧实现或兼容层 |
| `mc2_context_core.cpp` | 3852行；持有context lifecycle/inspect/fingerprint classification 6个公开入口、1个内部inspect构造器与跨context单元共享的数值编排helper | 保留唯一core/lifecycle owner；不得复制state、数值helper或引入Python host shadow |
| `mc2_context_frame_step.cpp` | 1051行，Center/parameter/frame/collider/reset及per-context step 16个ABI | 已收口；只修改唯一context dynamic state，不与static owner或readback混合 |
| `mc2_context_interaction.cpp` | 444行，world-owned interaction的create/inspect/step-group/debug/free 5个ABI | 已收口；通过共享step/self helper消费per-slot context，不复制数值state |
| `mc2_context_readback.cpp` | 522行，唯一持有结果及隐式debug中间态的9个按需readback ABI | 已收口；只读state或构建Bone输出缓存，不执行step/static update |
| `mc2_context_static.cpp` | 1258行，clone-config及Proxy/Baseline/Bone/constraint/Center static的10个ABI | 已收口；直接接管`mc2_static_build` owner vectors，不建立host spec回路 |
| `mc2_fingerprint.cpp` | 238行，唯一生产Mesh/Bone static topology/geometry/surface fingerprint | 已收口；保持无context state依赖，不与static owner vectors混合 |
| `mc2_kernels.cpp/.hpp` | 约2.9k行，持有particle/inertia/distance/angle/collision/post数值kernel | 以热点与共同数据依赖决定是否拆分；不为缩短文件盲拆，不持有Python ABI/context |
| `mc2_static_build.cpp/.hpp` | 约1.6k行，唯一生产Proxy/Baseline/Bone/Distance/Bending/Center/Self owner vectors | 保留唯一static producer；继续context内自产自用，不回读host完整spec |
| `mc2_self_collision.cpp` | 约0.9k行，self grid/candidate/contact/intersection数值 | 保留独立热点owner；交互membership由world/context输入，不读取产品节点 |

| 声明/决策 | 实现owner | 主要证明 |
|---|---|---|
| 单次step处理全部task，组件是profile+task组合 | `solver.step_mc2`、`MC2NativeInteractionV0.step_group` | property registry、interaction V0资产、180帧soak |
| 三setup共享同一solver/context模型 | `specs`、`setups`、`nodes`、`native` | 26/26纯MC2、Mesh/Bone代表资产 |
| 首帧/变化重建按topology/geometry/surface/config分类 | `topology`、`solver._sync_mc2_slot`、native staged context | property geometry分类、BasePose/Bone static、soak rebuild计数 |
| BoneCloth横向连接是HoTools产品特化 | `bone_connection.build_hotools_bone_connection`、Bone setup options | product connection Tier A与Bone product资产 |
| 跨物体self为自动world scope，半径单一派生 | `interaction_scope`、`runtime_parameters`、native interaction/self | interaction scope纯测试、interaction V0资产、debug资产 |
| debug全隐式且按需readback | `debug`、`debug_draw`、native debug buffers | debug draw代表资产、soak无常态capture |
| 公共结果与写回事务不泄漏candidate | `results/solver`、Mesh/Bone writeback adapter | result candidate纯测试、representative assets |
| native context/interaction唯一生命周期owner | `native_context`、`solver`、PhysicsWorld slot/resource | raw owner 18/18、property lifecycle、180帧释放6个context |
| 官方MC2预设只写新粒子profile真实socket | `presets`、`nodes.physicsMC2ParticleProfile` | Blender property registry 11预设逐一构造 |

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
| MeshCloth | `task -> single raw mesh snapshot -> native四类fingerprint/change mask -> native Final Proxy/Baseline/Distance/Bending/Center/Self producer -> staged native context`；Proxy/frame/Baseline/Distance/Bending/Center/Self均已move，Finalizer/Baseline/Final Proxy仅在同次构建保留transient，生产slot只留必要metadata；fingerprint、Proxy与BasePose token共享snapshot，生产Topology无完整冻结树，P-06b/P-06c已关闭 | BasePose只上传world positions/component pose；native context内部生产triangle orientation与Center，collider/runtime/scheduler同步到slot context | stable Mesh vertex identity -> GN delta result | prepare失败保留旧slot/result；重建先staging后替换；slot prune/world dispose释放context与BasePose cache owner |
| BoneCloth | `task -> single Bone raw snapshot -> native四类fingerprint/change mask -> host product/source connection -> MC2BoneNativeData -> native constraint producers -> staged context`；Proxy/Baseline/Distance/Center/Self/Bone registration共6次直接move，生产完整spec树已删除，注册后压缩为metadata | 只上传Armature component pose、PoseBone head与raw 3x3 pose matrix；native生产world rotation与Center | stable Bone name -> 同Armature合并后的parent-local原子writeback plan | 跨Armature拆task；同Armature骨名重叠在发布前拒绝；任一component失败则整批不发布，slot/world释放context |
| BoneSpring | 与BoneCloth共享Bone Line static链，但setup adapter与归一化参数固定Spring支持域 | 同Bone frame链；只消费Sphere soft collider，关闭self/sync与不支持约束 | stable Bone name -> Bone transform transaction | 非Line、非Sphere或越出归一化支持域在prepare拒绝，不进入native/writeback |
| World common | `build_task_specs -> native fingerprint/classify -> topology/static -> per-task slot/context`；world唯一持有interaction context | 全task frame sync后按scheduler substep批量推进；跨物体self由world interaction context锁步；debug仅在下一真实advance按请求冻结 | Mesh/Bone/stats先形成candidate，再由公共transaction发布 | staged create/update/read任一步失败都dispose新资源并保留旧事务；stale slot、Cache Delete、clear、重编译和unregister沿owner链幂等释放 |

状态所有权固定如下：world拥有跨task interaction和发布事务；slot拥有单个`profile + task`的runtime identity、scheduler、center调度history与native context；particle position/rotation/history只存在于native context。早期`MC2InitialStateSpec -> MC2ParticleBuffer -> sync_mc2_frame_input`平行host状态链及setup `initial_state_builder`已整体删除，测试也不再维护第二份数组oracle；immutable authoring/raw snapshot没有释放职责，frame snapshot和result candidate只活到本次公开step提交。

生产/参考路径分类：

- `nodes/declaration/capabilities/specs/topology/setups`是authoring、注册、identity与Blender snapshot边界；`solver/state/scheduler/native/interaction_scope/results/debug`是公共runtime；static builder和`parameters/runtime_parameters`是host packing边界。三setup的代表性Blender资产均从这些入口到达真实native与writeback。
- `bone_rotation.py`是固定MC2 source的host oracle，只由Tier A测试直接调用；生产Bone输出由native `read_bone_output`消费。它不能作为生产fallback，也不能用其测试通过宣称生产能力。
- `schema/properties/capabilities`分别拥有字段描述、RNA注册和UI/registry声明；setup adapter、BasePose、frame input与delta output分别拥有setup dispatch、缓存身份、evaluated snapshot和GN写回资源。它们虽然较小，但不是可删除的参数转发文件。

P-05纯整理删除了math抽离后仅保留旧私有函数名的import aliases，并删除只固定`setup_type="mesh_cloth"`、没有校验/身份/事务职责的`build_mc2_mesh_final_proxy`包装；内部调用现在直达`math3d`规范函数或`build_mc2_final_proxy`唯一实现。保留的本地math helper负责输入域、float32舍入或稳定错误信息；保留的setup/Blender wrapper必须至少增加task/source解析、cache identity、snapshot、资源生命周期或事务职责。整理不改变参数、默认值、更新频率、支持域、ABI或数值顺序。

## 11. 维护态文档与职责事实

MC2迁移完成后的唯一专项维护入口固定为`MC2_BLUEPRINT.md`，结构对齐`SPRINGBONE_VRM_BLUEPRINT.md`。蓝本只陈述当前运行事实、节点/文件职责、数据所有权、产品决策、性能边界、已删除边界和扩展检查表；阶段编号、逐提交性能数字、临时冲突和修复流水只由Git保存。

蓝本中的文件职责表必须从最终生产import/include/call图生成并人工核对，不能按期望目录反推。每个保留Python文件和C++ translation unit只能有一个主要owner；辅助职责必须指向该owner。以下情况不允许被描述成独立职责：

- 只重命名函数或重导出符号；
- 只把同一组参数再次转发给同层函数；
- 只为迁移期旧spec/旧ABI做shape转换；
- 生产runtime依赖的oracle/test入口；
- context已持有状态在Python或另一translation unit中的平行shadow。

验收表、执行计划和本文在P-15前继续承担迁移期职责；合并提交必须同时删除三份旧入口并原子更新Physics World status、公共contract、OmniNode architecture和代码注释中的文档路由，不能长期保留多个“权威”MC2文档。
