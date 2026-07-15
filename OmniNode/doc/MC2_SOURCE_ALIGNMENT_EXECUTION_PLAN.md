# MC2 当前状态与执行计划

更新日期：2026-07-16

文档状态：**新 `physicsWorld.mc2` 的实施细节与执行计划**。总体完成度与验收结论以 `MC2_ACCEPTANCE_MAP.md` 为准。

源码基线：`D:\Unity_Fork\MagicaCloth2`，MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

本文回答 Host/Native 边界、实现细节与下一交付如何推进。总体完成度、对齐等级与验收阻塞见 `MC2_ACCEPTANCE_MAP.md`；字段级源码语义、顺序敏感行为与 oracle 规则见 `MC2_SOURCE_DATAFLOW_WORKSHEETS.md`。

## 不可变方向

1. MC2 只有一个 solver identity：`mc2`。MeshCloth、BoneCloth、BoneSpring 是三个 setup adapter，共用 context、粒子状态、step 与结果生命周期。
2. 新运行时只保留一个 C++ 数值实现。Python 负责 Blender snapshot、签名、静态构建、slot/context 生命周期、buffer packing、result publish、writeback plan 和 debug，不保留第二套 Python solver。
3. 用户输入 Mesh 永远视为 final proxy。solver 不做 selection crop、merge、reduction、optimization 或 render mapping，也不改变 vertex count/order/identity。
4. Mesh 动画输入固定采用“只读 BasePose 对象 + 源对象常驻 GN offset”。直接读取已接受物理写回的源对象 evaluated mesh 会形成反馈，永久禁止。
5. 每个声称 source-aligned 的字段都必须有固定源码 producer/consumer、明确输入域和 Tier A oracle。旧 solver parity、自洽测试、shape/count 测试只能证明 regression，不能证明 MC2 parity。
6. 旧 `physicsMC2MeshCloth` 与 `_native/src/mc2*` full-core/context 是待删除实现。它们可用于寻找公式、生命周期风险和性能经验，但不是新 ABI、兼容目标、运行依赖或验收 oracle。

## 文档职责

| 文档 | 唯一职责 |
|---|---|
| `MC2_ACCEPTANCE_MAP.md` | 按能力切片给出当前完成度、对齐等级、证据缺口与 V1-R 验收阻塞；这是总体状态的单一事实源。 |
| 本文 | Host/Native 契约、实现细节、工程禁区、下一交付和已决产品边界。 |
| `MC2_SOURCE_DATAFLOW_WORKSHEETS.md` | 固定 MC2 源码中的 producer/consumer、顺序敏感行为、数值陷阱和 oracle 规则。 |
| `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md` | 整个 Physics World 的跨 solver 摘要；MC2 完成度以验收总表为准。 |

发生冲突时按以下顺序判断：固定 MC2 源码行为、`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md` 的公共架构、本文的已决边界、当前代码与测试。旧实现和历史文档排在最后。

## 当前事实快照

状态标签只使用：`landed`（生产路径已接线）、`verified contract`（契约/oracle 已冻结但未接生产）、`scaffold`（生命周期地基）、`not implemented`。

| 层 | 当前状态 | 事实边界 |
|---|---|---|
| solver/task scaffold | landed foundation | `specs.py`、`topology.py`、`solver.py` 已有统一 task、slot reuse/rebuild/prune 和先 prepare 后写锁的事务边界；slot 已接入 native context 的 staged create/replace、热更新、reset/step/read 与 dispose。连续帧已执行 Pin 跟随与源码顺序的 Distance→Bending/Sum→第二次Distance。 |
| particle owner | landed foundation | `MC2ParticleBuffer.allocate()` 只分配并保持未初始化；`reset_from_frame()` 按源码同时覆盖 position/rotation history并清零 velocity/friction/collision。slot 唯一持有 native context V0；native reset已清零 velocity/friction/static-friction/collision-normal/real-velocity，连续 step按固定producer执行 Center depth inertia→position/velocity-reference shift→velocity rotation→velocityWeight→damping→gravity→predict→Tether→Distance→Angle→Bending/Sum→Point/Edge collider→第二次Distance→Motion→source-aligned post。Distance/Angle/Bending inverse mass消费上一阶段persistent friction，collider更新本步friction/normal，第二次Distance与post消费更新值；`particle_step_constraints_post_001` 以两个连续子步证明第二步消费第一步提交的persistent velocity。animated base pose同时进入 step-basic scratch；Mesh baseline在prediction后按parent-first local pose/scale重建并按animation pose ratio混合到substep animated pose，正缩放与X轴负缩放均由 Tier A 和 Blender Fixed World验收，Team options可独立热更新。 |
| Mesh N0 final proxy | landed | `final_proxy.py` 已实现 triangle/edge union、方向统一、vertex adjacency、vertex-to-triangle flip、normal/tangent、UV seam gate 和同 index Pin attribute，并由 Tier A fixture 覆盖；7 组冻结数组已由 staged native context 校验并持有。 |
| Mesh N0 baseline | landed | `mesh_baseline.py` 已实现 parent/child、baseline ranges/data、root/depth、local pose 和 ZeroDistance attribute finalization；equal-cost 使用 HoTools 确定性 index 规则并登记为 intentional deviation；10 组冻结数组已接入 native context。 |
| Mesh static slot bundle | landed | `static_build.py` 在 rebuild 时组合 finalizer、baseline、Distance、Bending 与 Center；完整 Mesh connectivity token、UV/Pin mask及 Center initial gravity direction进入 schema 3 static input signature，同 vertex count下的连接变化也会重建。任一 N0/N1 上传失败会释放 staged context并保留旧 slot。 |
| Bone Line N0 static bundle | production native/result | 3 个固定commit Tier A fixture执行真实 `ImportFrom -> attributes -> ConvertProxyMesh`，冻结普通旋转链、连续Fixed前缀与Transform-centered normal adjustment。`MC2ProxyFinalizerStaticSpec` 统一复用邻接、triangle records与bind pose契约；`MC2BoneStaticSpec` 组合final proxy、transform baseline、normal adjustment和`vertexToTransformRotations`。Blender rest topology按parentless Fixed/其余Move构建Line bundle，slot staged上传proxy/baseline/finalizer/Bone rotations/Distance/Center；native逐数组校验并原子持有，最终发布共享`bone_transform` batch并由统一writeback应用。 |
| Distance N1 | landed foundation | `distance_static.py` 已提供保序 host builder、immutable spec/signature 与显式 packer；7 个 build fixture、2 个顺序敏感 runtime fixture通过。`ranges/targets/rest_signed` 已由 native context 校验并持有，每个子步在Bending前后各执行一次ordered projection，按depth inverse mass与animation-pose rest length修正并同步 velocity-reference。 |
| TriangleBending N1 | landed foundation | `bending_static.py` 已提供 role-preserving host builder、immutable spec/signature 与 `int32/float32/int8` 只读 packer；ordered role quad/rest/marker 已上传 native。directional dihedral、volume、negative scale、fixed-point accumulate、Move-only average与scratch clear已由3个 Tier A runtime case逐数组验证。 |
| Tether N1 | production native | Tether无需新增static数组，复用Move attribute、root/depth与step-basic pose；V0已按prediction后/首次Distance前接入现有native kernel，compression/stretch消费N2槽24/25。Python slot owner按MC2固定调度默认启用，raw C gate仅用于约束范围隔离；py313公式/顺序case和Blender5.1新建、重建、真实子步计数通过。独立Tier A substep fixture仍需补齐。 |
| Angle N1 | production native | V0复用baseline parent/range/data、depth、step-basic pose和velocity-reference，按首次Distance后/Bending前执行Restoration与Limit。修正native kernel对已转换stiffness重复乘0.2的旧ABI偏差；N2 use位、curve槽3/4、float槽28..30及Center gravity-dot已接入。py313独立kernel/V0结果对拍，Blender5.1 Mesh与Bone真实子步计数通过；独立Tier A Angle substep fixture仍需补齐。 |
| Motion N1 | production native | V0新增每子步animated base position/rotation缓冲，按第二次Distance后/post前执行Max Distance与Backstop，不误用baseline改写后的step-basic。接入InvalidMotion属性、depth²、normal-axis、N2 use槽6/7、curve槽5/6和float槽31/32；显式use位保留MaxDistance=0的锁定语义，旧公开kernel继续按正值数组推断。py313 kernel/V0零距离case及Blender5.1 Fixed Mesh三子步通过；独立Tier A Motion substep fixture仍需补齐。 |
| Collider N0/N1 Point+Edge | production native restricted | `collider_frame.py`将共享World current/previous snapshot转换为MC2不可变帧数组，覆盖Sphere/Capsule/Plane/Box、16组mask、自身owner排除、moving center/segment回退和box signed Z；Mesh从对象属性、Bone task从显式`collided_by_groups`消费，不读取旧MC2模块或重扫Blender scene。V0原子上传后，Point按逐粒子、Edge按proxy edge投影，均持久化friction、collision normal与real velocity。Edge view显式区分固定源码`Move=0x02`与旧full-core`0x04` ABI；BoneSpring由setup-kind强制只收Sphere，Fixed也参与，使用animated base与curve槽7执行max-length clamp、0.85反弹衰减、friction距离倍率并同步velocity-reference。py313覆盖typed-empty、四primitive、失败不污染、Point/Edge与soft-sphere数值，Blender5.1覆盖Mesh/Bone production上传和真实子步。 |
| Self Collision N0/N1 FullMesh | production native restricted | `self_collision_static.py` 按源码Point→Edge→Triangle构建并原子上传primitive；首个实际substep在Motion后/post前更新inverse mass、16采样thickness×scale、swept AABB、Edge grid尺度、三类排序grid run及精确Unity hash。hash搜索建立EE/PT候选并执行AABB、Ignore、双方AllFix与共享particle过滤；候选按old pose最近点/法线和双方位移投影生成half contact。首substep只保留enable项，后续substep原地更新contact并保留PT初始sign。每个substep随后固定执行4轮SolverContact→SumContact：消费half contact与primitive inverse mass，按Fix/Intersect位过滤写入，以`1e6` int32 fixed-point累加、按参与次数平均、还原float并逐轮清零。跨帧Intersect在新frame首substep前消费上一帧primitive/grid，按`frame % 2`只检测对应Edge→Triangle分片；整帧最后一个substep后才清空并复测record，命中只标记Edge两端particle，下一帧UpdatePrimitive写回低3位。旧raw step 4/5参数默认final，生产owner显式传第6个`is_final_substep`。Edge最大尺寸接近0时grid/contact/intersect detection保持空。py313覆盖三帧record/flag反馈及非final门控；Blender5.1覆盖单子步与三子步一次性提交。当前限制仍是单cloth self域，sync/inter-cloth ownership与多体调度尚未接入。 |
| Inertia/Center | landed restricted production slice | `center_state.py` 已冻结 center fixed list/local center、initial local gravity、component/anchor frame pose、persistent reset与 substep derived分层；Center static、`center_step_inertia_001`、`particle_step_inertia_001`、正缩放 `particle_step_baseline_pose_001` 与X轴负缩放 `particle_step_baseline_pose_negative_scale_x_001` 均由 Tier A oracle覆盖。world-inertia、movement/rotation speed-limit、movement smoothing、time-scale shift与configured Keep/Reset teleport已在单位正缩放域接入 Host persistent、native粒子预步和solver；Keep/Reset另覆盖active X轴scale-sign transition的受限顺序。14个frame-shift fixture覆盖anchor/组合/smoothing/正与零time scale/scheduler skip count/Fixed Center、X轴scale-sign transition、Keep/Reset teleport及两种negative组合；Keep+negative冻结current Center history、transition pivot和negative→shift粒子顺序，Reset+negative证明reset优先且negative matrix不消费。`MC2TimeSchedulerState` 已对拍并由slot持有；生产solver现按每slot scheduler执行plan/advance，一次应用negative-scale/frame shift或configured reset、一次上传完整Center frame，再按ratio仅刷新interpolation并执行多子步，最后只发布一次candidate。Blender 50Hz、0.1秒、每帧上限3已闭环planned/update/skip=`5/3/2`、三个native step、两次interpolation update与4/36度skip shift；Keep frame 41与Reset frame 51覆盖单位正缩放三子步，Reset+negative frame 61覆盖reset优先，Keep+negative frame 71使用 `world_inertia=0.25`、30Hz/0.1秒覆盖negative→shift后继续三子步并提交运行帧Center history；same-frame/pause/idle均不伪造step。负缩放路径按源码构建component/Center TRS delta matrix，先变换Center persistent与native粒子history/velocity，再进入inertia shift/step；configured Reset同帧时跳过matrix消费，Keep同帧时使用transition后pivot。zero scale使用World `raw_dt`计算100% shift，只更新dynamic/candidate并应用shift，不执行native/Center step。Blender第4至9帧、Keep/Reset组合frame 41/51/61/71、自动BasePose负缩放frame 12及独立Fixed World覆盖生产组合；Fixed World同时验证正缩放baseline parent-first重建、三子步animated blend与animation pose ratio热关闭，frame 81进一步覆盖negative teleport后的三次baseline重建。Mesh BasePose frame snapshot 已携带 evaluated component pose；本地负缩放在无parent或正缩放父级下，只要world linear无shear，就会保留真实axis sign并重建无反射rotation。父级继承负缩放与shear输入在adapter边界显式拒绝。 |
| Mesh BasePose adapter | landed foundation | `base_pose.py`/`frame_input.py` 已验证双对象、无反馈、topology token、不可写 same-frame snapshot，并从 N0 triangles/UV/flip records派生 `float32[N,4] xyzw` world rotations。`physicsMC2Step` 在 active World中会从已配置 `mc2_base_pose_proxy` 自动读取/缓存 N3 snapshot，并使用 World dt；显式 `frame_inputs` 仍用于测试和受控调用。adapter可在无parent或仅含正缩放祖先、且world linear无shear的域恢复Blender matrix decomposition会吞掉的本地负缩放axis sign；父级继承负缩放与shear显式拒绝。rotation/reset数组已有 Tier A oracle；当前首版仍要求每个 vertex属于 triangle。 |
| Runtime parameters N2 | landed foundation | `runtime_parameters.py` 已冻结 V0 value ABI：47 个 `float32`、11 个 `int32`、9x16 个 curve samples；task/slot parameter signature已改用该运行时块，scheduler保持独立签名。solver settings显式提供源码全局 `simulation_frequency=90`与每帧上限3；旧`substeps/iterations`接口保留兼容。Mesh非线性曲线与BoneSpring完整覆写由2个固定commit Tier A dump逐数组验证；prediction、Tether/Distance/Angle/Motion、Point/Edge、BoneSpring collision-limit以及单cloth self mode/thickness/cloth mass已进入对应consumer；`wind_*`仅作为未来通用力场适配的兼容参数面保留，当前没有外部力场快照或native消费；self-collision sync mode同样只保存不伪装消费。 |
| Dynamic/reset N3/N4 | landed restricted production | `frame_state.py` 已冻结 frame identity与 first pose/same-frame/continuous/reverse/gap/generation/user reset transition；N3携带受检 `velocity_weight/gravity_ratio/scale_ratio/negative_scale_sign/frame_interpolation`。native context V0 已接 old/current animated pose、Fixed position/rotation interpolation、Move step-basic pose与Center inertia、prediction、Pin、Distance、Bending、post与read。Bone Line自动采样PoseBone frame；Armature自身非零负缩放会分解为proper component rotation与signed scale，位置保留完整world linear，反射通过Center/negative-scale ABI进入baseline，最终world rotation再按proper component rotation转回armature pose，禁止scale泄入`matrix_basis`。正缩放Line及X轴负缩放baseline已有Tier A覆盖，Blender5.1验证正→负→正连续帧、两次native transition、candidate/result/plan替换与PoseBone scale保持1。负缩放父级、零scale和最终world shear仍拒绝。含triangle的raw native输出继续执行Triangle normal/tangent与per-vertex TriangleSum override，三份Tier A fixture覆盖override/flip/normal adjustment。 |
| 新 native context/step | landed foundation | 新 V0 已完成 `create -> set setup-kind -> inspect -> update N0/N1/self primitives/parameters/dynamic/center dynamic/colliders -> update step interpolation -> reset -> step -> read/read bone/self primitive/intersect output -> free`，由slot独占并支持staged replacement、输入先验证、幂等释放、双ABI与soak。step执行Center/Move inertia、frame interpolation、animated step-basic、prediction、Tether→Distance→Angle→Bending→Point/Edge collider→第二次Distance→Motion→self primitive/contact/4轮solve→source-aligned post，并在final substep提交跨帧Intersect flag；BoneSpring soft-sphere复用同一Point stage并将Fixed/post语义切换为spring。两子步Tier A fixture闭环no-collision顺序，Point/Edge/soft-sphere/self FullMesh及Bone triangle output另由raw V0 case覆盖。当前不消费通用力场输入；wind适配等待Physics World公共力场快照契约。旧`_native`full-core不计入此项。 |
| result/writeback | production Mesh/Bone/stats transaction | Mesh native readback先复制为带 frame/generation/world generation/revision/native revision 的只读内部 candidate，始终保持`ready=False`；公共层验证active world frame/generation与单final-proxy target后，构造`ready=True`的共享`gn_attribute` object-local offset envelope。Bone Line/BoneSpring candidate额外冻结proper component world rotation；位置用完整Armature inverse转pose空间，rotation只用proper component inverse转换，防止非均匀/负component scale泄入PoseBone。随后以稳定armature/data pointer和bone name构造`bone_transform_batch` envelope，并按目标父矩阵生成`matrix_basis` live plan。每次active world调用还构造一个`mc2_stats_v0`聚合快照，固定输出setup/slot/native context/particle/reset/step/writeback计数及逐slot纯标量记录，不含native handle或Blender对象。Mesh/Bone/stats进入同一公共事务；发布失败恢复旧result streams且不替换旧Bone plan，统一writeback中途失败会整批恢复旧`matrix_basis`。`mc2_stats`已登记为active exclusive channel；stats存在不改变Step的真实写回ready语义。 |

## 未来兼容区：通用力场

MC2 不再把 wind 设计成 solver 私有对象或私有场景扫描。未来由 Physics World 通用力场域收集、标识并逐帧求值力场，wind只是其中一种类型；MC2 adapter只消费公共纯数值快照并转换为native输入。

当前边界：

1. `wind_influence/frequency/turbulence/blend/synchronization/depth_weight/moving_wind`继续保留在N2兼容参数面，但不代表力场能力active，也不允许只凭这些scalar生成隐式wind。
2. MC2不得提前冻结通用力场的channel、schema、空间采样方式或对象生命周期；这些由公共力场vertical slice统一决定。
3. 公共力场快照落地后，MC2只新增显式声明、adapter pack/native consumer与对应oracle，不在MC2目录复制authoring resolver。
4. 在此之前，测试必须保持外部力场为零；现有no-wind fixture不能外推证明wind或其他力场能力。

## Host/Native 契约

新路径的数据流固定为：

```text
Blender authoring/frame input
  -> immutable host snapshots + signatures
  -> source-aligned N0/N1 static build
  -> slot-owned native context
  -> parameter/dynamic sync -> reset/step -> readback
  -> Physics World result stream
  -> external writeback
```

每个 active task 对应一个 Physics World slot 和一个 opaque native context。context 只能由 slot dispose 链释放；native 不保存 Blender/Python object、不返回 handle 给公开结果、不创建隐藏全局 owner。

### 数据分层

| 层 | 内容 | 生命周期 |
|---|---|---|
| H0 identity | task/setup/source/target identity、ordered Bone root identity | host/session；不进入数值 kernel |
| H1 authoring snapshot | profile、curve authoring、Pin/selection、setup options、bone hierarchy、外部引用 identity | host immutable；用于重建/诊断 |
| N0 proxy static | final proxy positions/orientation/UV/attributes/edges/triangles、baseline parent/child/root/depth/local pose、output mapping | slot static |
| N1 constraint static | Distance/Bending/Inertia 等 source-aligned exact arrays | slot static |
| N2 runtime parameters | 16-sample curves、scalar/bool/enum、BoneSpring override、team options、scheduler block | hot update |
| N3 frame input | animated world pose、component pose、dt/frame continuity、collider/anchor snapshots | frame |
| N4 state/scratch | Center/particle history、step working arrays、constraint scratch | context persistent / substep |

静态 mapping、persistent state 与 scratch 不得因为内存上放在同一 context 就混成一个公开 spec。逐帧 evaluated pose 不得进入 N0 signature；反过来 N0 reference pose、UV 或 Pin mask变化也不能伪装成普通 dynamic update。

### 首版 ABI 规则

1. buffer 为连续 C-order 固定 dtype；禁止 object dtype、Python nested list 和隐式 dtype conversion 跨 ABI。
2. quaternion 统一 `xyzw`；Blender `wxyz` 只在 adapter 边界转换。
3. 坐标空间写进字段名；禁止 ABI 中出现无上下文的 `positions`、`rotations`、`scale`。
4. Unity packed 12/20、`ushort`、`ulong` 只保留在 raw fixture；ABI 使用 checked `int32` ranges/records。
5. create/update 在 mutation 前校验 schema version、backend key、shape、range、index、finite、unit quaternion 与 identity uniqueness。
6. static arrays 默认 immutable；dynamic update 原地写预分配 buffer；readback 写调用方提供的 output buffer。
7. debug dict 不是 ABI。debug 只能展示 context 实际消费的数据，不能从 authoring input 重算一份“看起来正确”的状态。

### Dirty、Reset 与 Rebuild

| 变化 | 动作 |
|---|---|
| task/setup/source/target identity | prune 旧 slot，创建新 slot/context |
| final proxy、UV、Pin/attribute、baseline、output mapping | rebuild context + reset |
| Distance/Bending/Inertia exact static arrays | rebuild context + reset；首版不做 partial patch |
| runtime value parameters | hot update，保留 particle/Center history |
| scheduler 值 | hot update；时间连续性由 frame context 独立判断 |
| world generation、backend/schema/layout | rebuild context + reset |
| same-frame | 不重复 step；复用上一真实 step result |
| user reset、倒放、跳帧策略触发 | 使用最近一次完整 N3 pose执行显式 reset |

`create` 失败时旧 context 仍保持可 dispose；`free` 必须 idempotent/noexcept。参数变化不能被记录为 reset。allocation 只建立容量，不代表 particle 已按当前帧 pose 初始化。

### Result 契约

MeshCloth native 输出 world-space display pose，host 转为同一 vertex identity 的 object-local final offset并发布 `GN_ATTRIBUTE_CHANNEL`。BoneCloth/BoneSpring 输出 world proxy pose，host 转为 stable bone identity 的 local transform并发布 `BONE_TRANSFORM_CHANNEL`。

result item 至少包含 frame、generation、slot id、setup type、target identity、revision、纯数值 buffer和状态；不得包含 native handle、manager direct index、Blender owner或 live property。solver/readback/debug 不直接写 Blender，writeback 只消费 result stream。

## 工程经验与禁区

这些结论来自旧实现实践，但对新路径仍有效；旧 class、cache schema 和 ABI 本身不迁移。

### Blender 与性能

- solver timing 很短但 fps 低时，优先检查 depsgraph、Outliner、场景对象数量和 UI；不要只继续优化 C++ kernel。
- 禁止私有 frame handler 或 scene-wide scan 刷新 BasePose。snapshot 只由当前 task、当前对象按需读取。
- 禁止逐帧写 Shape Key、移动/toggle GN modifier 或在同一对象上读取物理前后两个 evaluated 阶段；这些路径已证明会产生反馈、不稳定刷新或不可接受的重算。
- BasePose 与源对象必须保持相同 vertex identity/connectivity。逐帧只做轻量 token/count 校验，完整 topology hash只在静态创建/刷新时计算。

### Cache 与生命周期

- 长期 native resource 只能挂在 slot/context owner；不得平铺到模块全局、节点 dict 或第二套 cache。
- state 复制/替换必须显式转移或释放 runtime slots；不能让 topology cache、frame snapshot和 native context各自拥有不同 generation。
- 参数热更新保留 history；静态输入变化先完整只读构建，成功后再替换 slot，避免 world 半更新。
- debug/ABI view 按需构造，不能每帧重建大 dict/array tree。

### 数值与碰撞

- 不把旧 full-core 的“效果接近”当作 source parity。尤其 Distance record order、Bending role、Center/reset 和 self-collision contact lifecycle都不是可凭结果外观猜测的细节。
- self collision 不是单个 point-triangle/edge-edge 投影函数；broadphase、contact 去重/缓存、intersect 分帧、质量和摩擦共同决定稳定性。厚度增大也会增加重复命中和黏连风险。
- 互碰不是把另一个 mesh 的顶点展开成 sphere collider。它需要对象所有权、质量、接触汇总和多体调度，必须独立设计。
- 不复制 Unity TeamManager/job/chunk 结构；只迁移经过 oracle确认的数学状态转移和执行顺序。

## 最近完成切片

最近完成的交付是 **Bone Line/BoneSpring signed component transform闭环**。当前工作已转入 `MC2_ACCEPTANCE_MAP.md` 所列 `V1-R` 验收阻塞清理：

1. Bone connection import membership已由8个 Tier A fixture、mode 0..3参数面和不可变host builder闭环，包含119°/121°的严格120°拒绝边界；正缩放Line与triangle override各由3个Tier A fixture闭环到world/local。Line限定域已接Blender rest/static、staged native N0、自动frame snapshot、native post rotation和private candidate。稳定armature/data pointer与bone name现已形成`bone_transform_batch` public envelope，整批world pose先转armature pose再按目标父矩阵生成`matrix_basis`，统一writeback已接通；solver仍不得inline写PoseBone，也不得同时扩张Automatic/Sequential。
2. private candidate 已同时持有同 vertex identity 的 world pose和 object-local offset并保持 `ready=False`；公共 Mesh result transaction、发布失败回滚、统一 GN writeback交接、节点自动 N3 snapshot与写回失败恢复验收均已完成。
3. Mesh/Bone candidate 与公共 envelope 已分别验证 frame/frame generation/world generation/revision；same-frame不得重复 read/step/revision，只重发同一 revision。Bone live plan仅在公共result transaction成功后替换，发布失败保留上一计划。
4. static 上传或 rebuild 失败必须保留旧 slot/context；Bone finalizer、baseline与Bone-only rotations必须作为同一 staged bundle原子替换。参数热更新继续保留粒子 history。
5. BoneSpring强制复用Line topology/static/native/result路径；N2固定覆写已在真实slot验证gravity=0、tether compression=0.8、distance stiffness=0.5并关闭max distance/self collision。BoneCloth与BoneSpring保持不同setup/static/task签名，不共享slot。
6. Bone frame adapter允许Armature自身非零负缩放，但父链必须保持正非零scale且最终world linear无shear。adapter用axis sign恢复proper component rotation与signed world scale，Bone world rotation不再由反射矩阵`to_quaternion()`猜测；PoseBone object-space linear也必须可分解为proper、shear-free rotation与正scale。Bone candidate冻结component rotation，写回时rotation与position分开转换。零scale、父级继承负缩放、负PoseBone scale和shear仍在snapshot边界明确拒绝。

Bone mesh-connection源边界已决：`ImportBoneType()`写入全零UV，因此Automatic/Sequential仅在最终membership不含triangle时复用Line static/native；一旦含triangle，准备阶段在分配或替换native context前明确拒绝并报告triangle tangent/basis退化。禁止在fixture里注入合成UV掩盖该事实。

退出条件：Bone public envelope的frame/generation/revision、stable identity、parent-local转换、发布失败保留旧plan、writeback执行中途整批恢复旧`matrix_basis`与统一PoseBone writeback均已通过；solver仍不得inline写bpy。

## 历史分层交付顺序

以下保留实现阶段的依赖顺序和退出条件，不再表示当前优先级；当前顺序只看 `MC2_ACCEPTANCE_MAP.md` 的阻塞行。

### 1. N3 Frame Input 与 Reset（已完成生命周期地基）

- 从 BasePose 同一 snapshot 生成 world positions、normals 和 per-vertex rotations。
- 明确 `create/register` 只分配 owner，首次有效 current-frame world pose 才执行 reset。
- same-frame 只更新/复用 snapshot，不重复 step；跳帧、倒放、用户 reset 和 generation 变化有稳定 reason。
- static mapping、persistent particle history、step working arrays 与 scratch 分组，禁止继续混放在 initial-state spec。

退出条件：allocation-before-reset、首次 reset、连续帧、same-frame、time discontinuity、参数热更新保留 history 的数组级测试通过。

### 2. Native Context 最小闭环（已完成生命周期地基）

首条 API 只允许：`create -> inspect -> update_parameters -> update_dynamic -> reset -> step(no collision) -> read -> free`。

- 每个 slot 唯一持有一个 opaque context；create 失败不能破坏旧 slot。
- native 不保存 `bpy`/Python object，不暴露 backend handle，不使用隐藏全局 context。
- static key 改变 rebuild + reset；parameter/scheduler 热更新保留 history。
- ABI 先做 schema/version/dtype/shape/finite/index 校验，再修改 context。
- Python 不实现平行 solver 作为 fallback；调试只读取 context 实际消费的数据。

退出条件：双 ABI、连续帧、same-frame、reset、异常回滚、idempotent free 和 leak/soak 测试通过。

### 3. MeshCloth Vertical Slice

第一版范围：单 final-proxy Mesh、Pin、无 collider。输出为同 vertex identity 的 object-local offset，经公共 GN writeback 应用。

验收必须覆盖首帧、连续帧、same-frame、参数热更新、UV/Pin/static rebuild、Armature 驱动 BasePose、topology mismatch、reset、dispose 和写回失败。数值只以固定 MC2 Tier A fixture验收，不要求与旧 solver 对拍。

扩展顺序：Distance -> Bending -> Tether/Angle/Motion -> Center/Inertia -> collider -> self collision。每项仍遵循 worksheet -> contract -> oracle -> host/native -> integration。

### 4. Bone Setup

顺序：Bone Line -> BoneSpring override已完成；下一步是BoneCloth Automatic/Sequential产品边界。Bone connection 必须先有“Bone Connection 与代理拓扑”对应 Tier A fixture；不能复用旧逐链 zip 近似。输出只发布稳定 bone identity 的 local transform，由公共 writeback 写 PoseBone。

### 5. 旧路径删除

新路径达到对应能力后，直接删除旧节点、Python reference、native full-core/context、兼容 cache 与 shadow pipeline。允许迁移的只有经过新契约和 oracle 重新证明的数值规则；不保留旧资产 adapter 或运行时 fallback。

## 已决产品边界

| ID | 决策 |
|---|---|
| D-01 | 用户 Mesh 是 final proxy；Pin/attribute 按 input vertex index 映射。 |
| D-02 | 不实现 MC2 reduction/render mapping；result 与输入 vertex identity 一一对应。 |
| D-03 | Blender Mesh 动态输入唯一支持双对象 BasePose + 常驻 GN offset。 |
| D-04 | loop-domain UV seam 不自动拆点；同 vertex 多 loop UV 不一致时明确报错。 |
| D-05 | Unity packed 12/20、ushort/ulong 只保留在 raw oracle；ABI 展开为显式 checked int32 arrays。 |
| D-06 | Tier A host 为 `tools/mc2_unity_oracle`；废弃 HoClothUnity 与旧 solver均为 Tier C。 |
| D-07 | Normal/Split 只迁移共同数学语义，不复制 Unity manager/job 调度结构。 |
| D-08 | Bone connection mode 3 的内部语义必须保留，并由 BoneCloth 节点整数模式 0..3 公开表达；BoneSpring继续强制 Line。 |
| D-09 | Bone Automatic/Sequential仅支持最终membership无triangle的Line安全域；`ImportBoneType()`零UV遇triangle时明确拒绝，不合成UV、不静默降级。 |
| D-10 | Bone生产frame支持Armature自身非零signed scale，但负缩放父级、零scale与world linear shear明确拒绝；proper component rotation与signed scale必须分解保存，不用`Matrix.to_quaternion()`吞掉反射手性，也不允许scale泄入PoseBone写回。 |

## 提交与声明规则

1. 一次提交只关闭一个 contract/oracle/implementation slice。
2. 提交说明指出 source producer、intentional deviation 和验证层级。
3. spec、packer、dirty policy、capability、debug 和测试作为同一交付单元更新。
4. `supported` 只用于真实生产链路；仅有 fixture/spec 使用 `verified contract`，只有对象壳使用 `scaffold`。
5. 遇到不明确行为先扩展 oracle，不从旧 solver 或直觉补齐。
