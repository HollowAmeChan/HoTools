# MC2 源码语义与危险行为参考

更新日期：2026-07-15

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
- triangle 用 canonical `PackInt3` 去重，不保留 winding；只有 canonical triangle 第一次插入成功时才登记该次中心到两条 link 的 `triangleEdgeSet`，后续重复发现不会补登记第三边。因此最终 `edgeSet - triangleEdgeSet` 可保留 residual line，不等于所有 triangle 三边都被删除。
- import topology之后仍要经过 selection/proxy conversion与 constraint `CreateData()`；不能把 import lines/triangles直接当 native constraint arrays。

启用 Bone Automatic/Sequential 前至少需要：过长边反转、loop/non-loop、分叉多对多、120 度边界、零长度和 residual line Tier A case。

当前已有 8 个 `ImportBoneType()` Tier A fixture，覆盖 Line分叉、Sequential loop/non-loop、Automatic过长边反转、同层分叉、零长度/residual line，以及119°/121°对拍证明 triangle条件严格为 `< 120°`；`bone_connection.py` 已按 transform/particle index生成不可变 root/level/line/triangle membership，并由 `MC2TopologySpec` 持有。mode 3 已进入参数与节点范围。另有 3 个真实 `ImportFrom -> attributes -> ConvertProxyMesh` Bone Line fixture冻结 final proxy、transform baseline、bind pose、normal adjustment与`vertexToTransformRotations`。Bone Line与强制Line的BoneSpring已闭环Blender selection、static/native、public result和PoseBone writeback；mesh-connection退化策略仍未闭环，因此Automatic/Sequential只能声明verified host contract。

### Connection-aware rotation顺序

权威入口：`SimulationCalcDisplayPosition()`、`SimulationPostProxyMeshUpdateLine()`、`SimulationPostProxyMeshUpdateTriangle()`、`SimulationPostProxyMeshUpdateTriangleSum()`、`SimulationPostProxyMeshUpdateWorldTransform()`、`SimulationPostProxyMeshUpdateLocalTransform()`。

1. display阶段先把模拟前的当前 base position/rotation写入 temp；Line rotation消费该 current base，不是固定 initial pose。
2. baseline按 raw root-to-child data顺序原地更新 rotation。child先由 parent rotation、local rotation和当前向量偏转求 world rotation，随后该 child作为自身 baseline项继续处理。
3. parent朝所有 child 的原始/当前平均向量旋转；Fixed/root使用 `rootRotation`，Move使用 `rotationalInterpolation`。最后每个 vertex再从 current base rotation按 `blendWeight` slerp。
4. `animationPoseRatio` 同时插值 child local position与rotation；ratio 1消费 current base parent-child pose，因此动画改变方向时不能继续使用initial local vector。
5. Line结果不是最终结果：triangle normal/tangent随后覆盖有triangle记录的 vertex rotation。`vertexToTriangles` packed high bits中bit 0翻转normal、bit 1翻转tangent；累加归一化后用 `LookRotation(cross(normal,tangent), normal)`，再右乘per-vertex normal adjustment。之后才乘 `vertexToTransformRotation`写world transform，最后按parent world pose和parent scale求Move transform local pose。

当前 3 个 `bone_rotation_line_*` Tier A fixture与 `bone_rotation.py` 已冻结正缩放三粒子Line域：全量root/Move旋转、不同root/Move插值加blend、`animationPoseRatio=1` current-base消费，以及world→parent-local输出。另有3个 `bone_rotation_triangle_*` fixture冻结triangle覆盖、normal/tangent flip records、normal adjustment与随后world/local输出。Line Bone static、native上传和PoseBone writeback已对BoneCloth/BoneSpring闭环；Bone frame adapter明确拒绝Armature/父链负或零scale及最终world shear，且准备失败保留旧运行状态。negative-scale数值支持、zero-distance/Invalid组合与mesh-connection三角静态仍未闭环。

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

当前生产路径在 slot rebuild 的 staged context 中上传 N0 proxy 的 7 组数组与 Mesh baseline 的 10 组数组。native 重新检查 dtype、shape、finite、index 与 dense range 后才原子替换对应数组；任一上传失败不得安装新 context。Distance/Bending N1数组已由同一 staged context持有并在no-collision step中按源码顺序消费。

### Bone Baseline 与 Depth

Bone baseline起点不总是登记 root。源码会沿不移动子树寻找“自身不移动且至少一个直接 child为 Move”的 vertex，再只遍历 Move child。连续多个 Fixed是合法输入。

每个 Move沿 parent累计几何长度，到第一个非 Move parent为 root；所有 chain共享整个 proxy的最大累计长度做 depth归一化。按单链离散层数分别归一化不等价，零长度边只贡献 0。

`MC2ProxyFinalizerStaticSpec` 统一持有 proxy派生的邻接、逐顶点triangle records与bind pose；Mesh和Bone不得各自复制这些数组契约。`MC2BoneStaticSpec` 只组合final proxy、该通用finalizer、transform baseline、`normalAdjustmentRotations`和`vertexToTransformRotations`，并提供单一只读packer。3个Bone Line Tier A fixture覆盖旋转链、连续Fixed前缀与Transform-centered normal adjustment。生产Line限定域现从Blender rest bone snapshot构建parentless Fixed/其余Move selection，staged native context原子上传并持有上述数组、Distance与Center；该注册不等于Bone结果已发布。

正缩放Line native readback在最终位置step之后，以`state positions/rotations`为工作姿态、最后substep的step-basic pose为current base，按baseline range与IncludeLine flag执行已冻结的Line rotation顺序，再乘`vertexToTransformRotations`得到world transform rotation。Blender active World自动采样PoseBone frame；连续帧生成只读private candidate，same-frame不重复read或增加revision。该candidate尚未转换成public parent-local envelope，也未写PoseBone。

固定源码的 `ImportBoneType()` 将Bone UV初始化为零；mesh-connection存在triangle时，`TriangleTangent()`因此返回零向量，随后triangle normal/tangent basis可退化。产品策略已冻结：Automatic/Sequential最终membership无triangle时复用Line static/native；含triangle时准备阶段明确拒绝。不得用oracle内合成UV伪装成真实Bone import parity，也不得静默删除triangle。

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

当前 7 个 build fixture和 2 个 ordered runtime fixture已覆盖这些边界；`distance_static.py` 是生产 host builder。保序 `ranges/targets/rest_signed` 已上传 native context并再次校验 packed source limits、index、finite与 `+0.0` 编码。连续帧按 raw range order执行一次 projection，zero-rest覆盖顺序由 Tier A case验证；persistent velocity与 attenuation仍未接入，当前不得宣称完整 frame parity。

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

当前 13 个 static fixture与 3 个 runtime fixture已冻结阈值、double record、volume first-wins、Fixed/Move writeback、scratch average/clear和 negative scale消费。`bending_static.py` 已按 raw order实现 host builder、完整签名和只读 packer，并接入 Mesh slot static bundle；native context按 ordered role执行 directional dihedral/volume，以`1e6` fixed-point逐记录累加，Move粒子按count平均写回，随后无条件丢弃/清空整组scratch。合法空数组与未上传状态保持分离。

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

固定源码 reset具体写入 `next/old/base/animationOld/velocityReference/display position` 与 `old/base/animationOld rotation`，并清零 simulation/real velocity、dynamic/static friction和 collision normal。HoTools host reset还会预置首个 substep需要的 step-basic pose；slot创建时保持 `initialized=False/reset_count=0`。

固定 `particle_step_gravity_damping_001` Tier A case 直接调用 `SimulationStepUpdateParticles()`，隔离并冻结：animated pose先写 base/step-basic；Move velocity依次应用 velocityWeight、`1-damping*simulationPower.z`、gravity与scale后预测 next；Fixed直接写 base pose；velocity-reference按移动前位置记录；两组 vector、一组 count与一组 float scratch逐粒子清零。该 fixture不包含 inertia、wind、collision或外力，不能外推证明这些能力。

固定 `particle_step_inertia_001` Tier A case 在 gravity/damping/wind/collision/外力均为零的域内隔离 Center 到 Move particle 的消费顺序：`inertiaDepth = depthInertia * (1-depth^2)`；inertia vector/rotation 向完整 step vector/rotation 插值；旧粒子位置绕 `oldWorldPosition` 旋转后平移；同一 offset 加到 velocity-reference；velocity先按 inertia rotation旋转，再乘 velocityWeight并预测 next；animated base pose同时写入 step-basic。该 fixture负责单粒子 prediction 数学；`particle_step_constraints_post_001` 进一步执行两个连续子步并冻结 Center→prediction→Distance→Bending/Sum→第二次Distance→post 的完整no-collision顺序，第二步直接消费第一步提交的persistent velocity。

固定 `center_frame_shift_world_inertia_001` Tier A case 直调 `SimulationCalcCenterAndInertiaAndWind()`，在单位正缩放、无 fixed list、无 anchor、无 smoothing/速度限制/teleport/sync/culling/skip/stabilization 的域内隔离 `worldInertia`。component从原点移动到 `(10,0,0)`并绕Y旋转90度，`worldInertia=0.25`产生75%的 frame shift：`frameComponentShiftVector=(7.5,0,0)`、rotation为67.5度；oldFrame/now pose按旧 component pivot同时平移旋转。`center_frame_shift_speed_limit_001` 在同一输入上追加 `10 m/s` movement limit与 `90 deg/s` rotation limit，冻结 shift ratio从0.75提升到0.9、平移为9、旋转为81度且剩余 moving speed为10。`center_state.py` 的公开 Host 求值器直接消费两份 fixture并保留独立 float32 公式交叉检查；persistent 将 shift 后 history送入 Center step，native预步同步变换粒子 position/rotation/velocity-reference/velocity，Blender slot验收同时覆盖 movement/rotation limit。该闭环不能外推到 fixed list、anchor组合、smoothing、time-scale/skip或negative scale。

固定 `center_frame_shift_anchor_001` Tier A case 关闭 world inertia与其它外部效应，隔离 `anchorInertia=0.25`。old component位于 `(1,0,0)`，anchor从原点移动到 `(0,0,1)`并绕Y旋转90度，anchor记录的 component local point为 `(1,0,0)`；75% anchor cancellation产生约 `(-0.75,0,0)` shift与67.5度旋转，剩余 component moving speed约2.5。`center_frame_shift_anchor_world_limit_001` 在同一几何输入上追加 `worldInertia=0.25`、`0.5 m/s` movement limit与 `90 deg/s` rotation limit，冻结anchor预变换后继续应用world/limit的顺序：最终shift约 `(-0.95,0,0)`、旋转约84.3度、剩余速度0.5。两份 fixture均由独立 float32 公式与公开 Host求值器交叉验收。Host persistent保存old/current anchor pose与anchor-component-local position；anchor identity首次绑定或改变时只提交历史，稳定同一 identity的下一帧才应用shift，并复用现有native粒子frame-shift ABI。Blender第4帧建立anchor history，第5帧验证anchor/world/双限速组合。

固定 `center_frame_shift_smoothing_001` Tier A case 关闭world inertia与其它外部效应，隔离 `movementInertiaSmoothing=0.5`。初始 smoothing velocity为 `(2,0,0)`，component在0.1秒内从0移动到10；源码比重 `(1-0.5)^3*0.99+0.01=0.13375` 将persistent velocity更新为约15.1075，并产生8.48925的位置cancellation。Host input/result显式携带该速度，只有native step成功后才提交persistent；Blender第6帧从零速度验证8.025 m/s更新、0.86625 shift与0.13375 Center step。当前生产域限定为无fixed list、单位正缩放、无teleport、正time scale `(0,1]`、单substep且stabilization完成；不能外推到这些条件之外。

固定 `center_frame_shift_keep_teleport_001` Tier A case 使用configured Keep模式、5单位平移阈值与180度旋转阈值，component在0.1秒内从原点移动到 `(10,0,0)`并绕Y旋转90度。源码在anchor adjustment之后、movement smoothing之前检测teleport；平移越阈触发Keep后跳过smoothing，并将world translation/rotation shift ratio都强制为1，得到10单位/Y90度shift、零moving direction/speed，同时保留初始smoothing velocity `(2,0,0)`。Host求值器显式返回Keep/Reset flags；独立Blender Keep World验证三native子步只应用一次frame shift并输出变换后的animated pose。

固定 `center_frame_shift_reset_teleport_001` 使用相同运动、阈值与smoothing输入，只将mode改为Reset。源码触发后令team Reset，跳过smoothing，将frame shift置零，把old frame/now/current Center history都替换为当前 `(10,0,0)` / Y90度并清零smoothing velocity；随后particle pre-step把全部粒子history/velocity/contact归到当前动画姿态，再继续本帧scheduler子步。生产solver用staged Center state复用native reset，只有native成功后才提交Host particle/Center reset count与 `configured_teleport` 原因；独立Blender Reset World验证连续frame 51触发第二次reset后仍执行三个native/Center step并发布当前animated pose。该基础生产验收限于单位正缩放、正time scale且update count大于0；Reset与active sign transition的扩展边界见下一fixture。

固定 `center_frame_shift_reset_negative_scale_x_001` 在同一帧先触发X轴scale-sign transition，再用30度旋转阈值触发configured Reset。源码保留negative-scale teleport标志和矩阵producer，但Reset令 `inertiaShift=false`，particle pre-step优先走完整reset分支，因此negative matrix不消费，所有position/rotation history、display、velocity-reference、velocity、friction与collision normal都归到当前animated pose/零值。Host oracle分别对拍negative transition与Reset Center结果；生产solver仅为mode 1 + active sign transition放宽单位缩放门禁，staged reset跳过native negative-matrix ABI。独立Blender frame 61验证negative count为0、第二次reset与三子步均完成。Keep的不同消费顺序由下一fixture单独冻结。

固定 `center_frame_shift_keep_negative_scale_x_001` 使用同一sign transition并改为configured Keep。源码先用Center negative matrix变换particle history，再以负缩放变换后的component position为pivot应用45度Keep frame shift；negative reset已先把Center old/now history归到当前65度frame，因此shift后old/now rotation为110度，frame rotation仍为65度。Host persistent在active transition时显式以current Center构造frame-shift history；solver按negative matrix→frame shift顺序调用native，并使用transition后的pivot。Blender frame 71使用 `world_inertia=0.25`、30Hz与0.1秒正时间执行三子步，验证negative/shift计数各1、scheduler update/skip=`3/0`、Center step三次、单candidate发布及运行帧history提交到当前45度frame。该闭环允许正缩放父级下、最终world linear无shear的单轴sign transition。

固定 `center_frame_shift_time_scale_001` Tier A case 使用 `simulationDeltaTime=0.05`、`frameDeltaTime=0.1`、`nowTimeScale=0.5` 与 `worldInertia=0.75`，冻结time-scale在world shift之后继续消去剩余量的顺序：shift ratio由0.25变为0.625，平移6.25、旋转56.25度，剩余moving speed按time scale归一为75。生产solver使用World与MC2 settings time scale乘积，native step消费缩放后的simulation dt，Center frame shift消费World保存的raw frame dt；Blender第7帧验证0.625 shift、0.375 Center step与45的归一化速度。

固定 `center_frame_shift_zero_time_scale_001` Tier A case 使用 `simulationDeltaTime=0`、`frameDeltaTime=0.1`、`nowTimeScale=0`，冻结暂停帧100%平移/旋转cancellation、零moving direction/speed。生产solver在该帧只update native dynamic、apply frame shift、read candidate并提交paused Center history，不调用native step或生成Center step result；Blender第8帧验证dynamic/candidate revision前进而native/Center step count不变。

固定 `center_frame_shift_skip_count_001` Tier A case 反射执行 `AlwaysTeamUpdatePostJob.Execute()` 与 `SimulationStepTeamUpdate()`，再将同一 `TeamData` 送入 `SimulationCalcCenterAndInertiaAndWind()`：`frameDeltaTime=0.1`、`simulationDeltaTime=0.02`、每帧上限3产生planned/update/skip=`5/3/2`、裁剪后time=`0.0600000024`，三个step interpolation为`0.3333333/0.6666666/0.99999994`。skip consumer得到0.4 other-shift ratio，在 `worldInertia=1` 时平移4、旋转36度、剩余moving speed 60。`scheduler.py` 已以float32状态机对拍六个持久时间字段、计数和step ratios，并由slot持有。native V0验证一次完整Center frame上传后用三个ratio逐步刷新interpolation，Fixed step-basic位置约为3/6/9且每步Center位移约为3；Blender生产solver以50Hz和每帧上限3复现5/3/2、三次step、两次interpolation update及4/36度shift，并只发布最终candidate。

固定 `center_frame_shift_negative_scale_x_001` Tier A case 让component scale从正值切换到 `(-2,1.5,0.75)`，同时直调 `SimulationCalcCenterAndInertiaAndWind()` 与 `SimulationPreTeamUpdate()`，冻结 `negativeScaleDirection/change/sign/triangleSign/quaternionValue`、`nowCenterTRS * inverse(oldCenterTRS)` matrix，以及Center old-component/anchor/smoothing和粒子old/animation-old/display/velocity/real-velocity的矩阵变换。Host按float32 TRS顺序生成component与Center matrix；native V0对现有position/rotation/velocity-reference/velocity history执行同序变换；solver固定在inertia shift前调用。Blender显式第9帧和自动BasePose第12帧验证X轴sign transition、N3 scale ratio/sign、native计数与Center history提交；configured Reset与Keep同帧组合均已有正时间多子步验收，其中Keep frame 71同时设置非默认world inertia。Blender component-transform契约进一步验证正缩放非均匀父级下的X轴负缩放可重建为精确shear-free TRS；父级继承负缩放因轴符号歧义显式拒绝，非均匀父缩放叠加子旋转产生的shear同样拒绝。仍不声称覆盖完整MC2 real/display双history集合。

固定 `center_frame_shift_fixed_center_001` Tier A case 保持component从0移动到10并旋转90度，同时用单个Fixed粒子将current Center frame设为 `(12,2,0)` / 90度。world inertia仍按component产生7.5与67.5度shift，但result frame pose必须保留Fixed-derived Center而非component。Host input现显式区分两套姿态；Blender独立Fixed World使用单Pin顶点验证Center fixed static/native count、component shift和经bind-pose修正的Fixed Center rotation。

native V0 已在该限定域内持久化 velocity：reset清零，world/anchor frame-shift预步均绕旧 component pivot同步变换 state position/rotation、velocity-reference与velocity，prediction再按上述顺序更新；每个子步按源码执行Distance→Bending/Sum→第二次Distance，Distance使用depth inverse mass，并按animation pose ratio在`abs(rest) * scaleRatio`与step-basic动画长度间插值；每次Distance correction按 `distance_velocity_attenuation` 同步移动 velocity-reference，post由 `(next - velocityReference) / dt * velocityWeight` 提交下一步 velocity。动态 ABI 已持有 old/current animated pose并按 `frameInterpolation` 为 Fixed 粒子执行 position lerp/quaternion slerp；Move 会先生成 animated base/step-basic scratch，再按 `particle_step_inertia_001` 将 Center inertia作用到 position、velocity-reference与velocity，随后执行 damping/gravity prediction。baseline step-basic 已按源码在 prediction 后、constraint 前 parent-first 重建：Move child消费 parent step-basic、静态 local pose、`initialScale * scaleRatio` 与 negative-scale direction/quaternion，root/Fixed只处理负缩放 rotation，最后按 `animationPoseRatio` 混合到 old/current animated pose的 `frameInterpolation` 结果；ratio大于0.99时跳过重建。固定 `particle_step_baseline_pose_001`、`particle_step_baseline_pose_negative_scale_x_001` 分别冻结正缩放与X轴负缩放；native root/Fixed分支按源码使用 `R*S` 的 up/forward列恢复rotation，Blender Fixed World frame 81验证negative teleport一次、三子步baseline重建与animated blend。Team options使用独立热更新 ABI并保留粒子/Center history。wind/collision/friction仍未实现，不得用默认零值伪装成完整 parity。Center fixed/local center/initial local gravity三组静态数组已由 native 校验并持有；Mesh solver adapter 已从 evaluated component/BasePose frame snapshot按 fixed-point或component分支逐帧提供显式 Center dynamic，并提交 source-aligned frame shift与 `center_step_inertia_001` 对齐的 inertia/scale/gravity/weight history。

Tether源码顺序位于prediction与首次Distance之间，直接消费现有Move attribute、per-vertex root index、step-basic vertex/root距离、next position与velocity-reference；compression/stretch分别来自N2 float槽24/25，固定width=0.3、compression/stretch stiffness=1、velocity attenuation=0.7。V0已复用原生`project_tether_mc2` kernel；raw C context保留显式gate用于隔离既有Distance→Bending→Distance oracle，而Python slot owner按固定MC2调度默认启用。两粒子Tier B case验证1.35伸长回到1.03和源码顺序，Blender5.1集成覆盖新建、重建与真实子步solve count。独立Tier A Tether substep fixture仍需生成，不能改写既有不同scope的fixture。

Angle源码顺序位于首次Distance与Bending之间，直接消费baseline parent/range/data、depth、step-basic position/rotation、next position与velocity-reference。Restoration/Limit由N2 int槽4/5控制，分别采样curve槽3/4；velocity attenuation、gravity falloff、limit stiffness来自float槽28..30。N2的Restoration curve已在`ClothParameters`转换阶段乘0.2，native kernel不得再次缩放；V0现使用该已转换值，继续乘源码`simulationPower.w=(90/frequency)^1.8`，并将`lerp(1-falloff, 1, gravityDot)`等价映射到kernel输入。raw step四参数ABI默认w=1，Python production owner显式传入w。无碰撞域friction为零，因此Move/Fixed inverse mass分别为1/0。py313隔离case对拍独立kernel且证明位置发生修正，Blender5.1 Mesh/Bone生产子步记录solve count；独立Tier A Angle substep fixture仍待生成。

Motion源码顺序位于第二次Distance之后、post之前，Max Distance与Backstop始终相对插值后的animation base position/rotation计算，不能使用Angle/Baseline已经改写的step-basic。V0因此在prediction开始时独立保存animated base缓冲。Motion由N2 int槽6/7控制，depth先平方再采样curve槽5/6，backstop radius与stiffness来自float槽31/32，法线轴来自int槽0；仅Move且未设置`Flag_InvalidMotion(0x08)`的粒子参与。显式Max Distance启用时曲线值0表示锁到base pose，不是关闭；raw公共kernel仍保留逐顶点正值推断兼容。py313零距离case验证gravity prediction后被锁回base且顺序位于post前，Blender5.1 Fixed Mesh记录三个production solve；独立Tier A Motion substep fixture仍待生成。

Collider帧输入现由`collider_frame.py`唯一从`PhysicsWorldCache.collider_snapshot`与`previous_collider_snapshot`派生。契约输出`int32` type/group-bit、current/old center与segment、`float32` radius，全部C-contiguous且只读；Plane归一化normal，Box以axis X/Y和signed half-Z编码，Sphere/Capsule要求正半径。packer按Mesh `collided_by_groups`过滤1..16组并排除source owner，空输入保持稳定typed arrays。该N0只完成host frame contract，尚未声明native collision production；下一步必须上传该spec并连同particle radius、friction、collision normal与post一起验证。

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

当前 private candidate 已用同帧只读 source world linear完成该空间转换并保持 `ready=False`。`physicsMC2Step` 会从 source上已配置的 `mc2_base_pose_proxy` 自动读取 active World frame/generation与dt，same-frame复用只读 snapshot；公共层再验证 task/slot与单 Mesh target，发布 `ready=True` 的共享 `gn_attribute` envelope。same-frame只重发同 revision，批次发布失败恢复旧 result streams，真实 Blender 写入仍只由公共 writeback执行。目标 topology不匹配时 writeback记录 slot/diagnostics错误并清零旧 offset，下一有效 result成功写入后清除错误。

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
- sample位置固定为 `i / 15`，线性槽顺序对应 `float4x4.c0.xyzw -> c3.xyzw`。value、curve sample与 0.2 系数按 MC2 的逐步 `float32` 运算舍入，不能先用 double合并表达式再转换。
- BoneSpring在归一化阶段强制 gravity=0、tether compression=0.8、distance stiffness=0.5、关闭 max distance/backstop/self/sync collision，并使用自身 collider/spring规则。
- checked speed limit关闭时使用 `-1`；damping与 angle restoration samples有 0.2 系数；Distance velocity attenuation固定 0.3。
- bending method、self mode/sync mode、collision dynamic/static ratio等派生值必须显式存在，不能只保留一个 stiffness scalar。
- animation pose ratio属于 team dynamic input；`simulation_frequency/max_simulation_count_per_frame/time_scale`属于scheduler block，旧 `substeps/iterations` 只保留HoTools兼容接口且当前V0未消费；这些都不属于纯 `ClothParameters` value block。
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

当前可信覆盖：Mesh final proxy、9 个 Mesh baseline case、7 个 Distance build + 2 个 runtime-order case、13 个 Bending static + 3 个 runtime-scratch case、8 个 Bone connection import case、3 个 Bone Line static bundle case及其Blender slot/native注册、3 个 Bone Line rotation/output case及native/Host组合对拍、3 个 Bone triangle rotation/output case、2 个 N2完整参数 dump、1 个 N3 rotation/reset dump、1 个 Center static dump、1 个 Center substep dump、14 个 Center frame-shift dump（world inertia、speed limits、anchor、anchor/world/limits组合、smoothing、configured Keep/Reset teleport、Keep/Reset与negative-scale顺序、正/零time scale、scheduler skip count、fixed center、X轴negative-scale teleport）、1 个 native step-interpolation多子步case、1 个 Blender production scheduler 5/3/2闭环、1 个 parented negative-scale Blender transform contract和 5 个 particle-step dump（gravity/damping、Center inertia、正缩放baseline step-basic、X轴负缩放baseline step-basic、constraint/post两子步完整闭环）。父级继承负缩放与shear已定义为显式拒绝边界；Bone Line/BoneSpring已闭环public parent-local envelope/PoseBone writeback，Automatic/Sequential无triangle安全域已接通且含triangle零UV域明确拒绝；Bone负/零scale与world shear已建立显式拒绝和失败不污染边界，仍缺negative-scale数值支持及collider/self-collision。
