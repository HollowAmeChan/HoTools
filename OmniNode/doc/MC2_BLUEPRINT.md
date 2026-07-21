# MC2 实现蓝本

本文是 OmniNode `physicsWorld.mc2` domain 的稳定维护入口，说明当前已经运行的产品决策、数据流、所有权、数值边界和扩展约束。基准参考为 MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

## 写作边界

- **应该写**：当前真实支持域、故意产品差异、Python/C++职责、数据所有权、更新频率、事务、debug、性能门槛和扩展检查表。
- **不应该写**：迁移阶段、逐次修复、提交顺序、临时测试流水、已经删除实现的过程复盘或某次机器上的偶然性能数字。
- **内容路由**：跨solver公共结构写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；domain摘要写`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`；OmniNode编译/IR/cache机制写`../ARCHITECTURE.md`；MC2产品决策、debug合同和验收结论只写本文；历史只留Git。
- **更新原则**：代码、declaration、测试和本文冲突时，先确认真实行为并修正唯一owner，再同步本文；不能用计划替代事实。

相关文档：

- 物理世界公共架构：`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
- 各domain当前完成度：`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`
- OmniNode通用架构：`../ARCHITECTURE.md`
- MC2性能热点、多代理融合、native并行与GPU前置策略：`MC2_DEEP_OPTIMIZATION_STRATEGY.md`
- MC2新一代partition/覆盖/collector节点数据流：`MC2_NODE_SIMULATION_DESIGN.md`
- 人工验收反例与已吸收决策：见本文“Debug收尾与产品踩坑”及对应能力章节；不再维护独立推进文档。

代码事实源优先级：`mc2/declaration.py`、`mc2/capabilities.py`、生产solver/native owner、自动化测试、本文。

## 当前定位

MC2是统一Physics World中的布料/骨链solver vertical slice，支持：

- MeshCloth、BoneCloth、BoneSpring三种setup。
- 单次公开solver step处理全部active MC2 task。
- 每个task独立slot和native context，world-owned interaction context统一处理跨物体self collision。
- Mesh GN object-local offset与Bone PoseBone批量写回。
- Point/Edge外部碰撞、单物体和跨物体self collision。
- Center/Inertia、Tether、Distance、Angle、Triangle Bending、Motion/Backstop和post。
- 全隐式debug请求与native真实中间态快照。
- 官方MC2粒子预设到三个setup-specific profile节点真实输入的裁剪转换。

旧MC2节点package、旧数组solve、旧context/IO ABI、旧BoneCloth IO和兼容构建选项已经物理删除。不得恢复别名、fallback backend、shadow solver或旧节点adapter。

旧路径替代、生命周期、洁净度、单一文档和热点性能门禁已经关闭，`solver_acceptance_blocker=False`只表示旧solver删除后的维护态准入成立，不表示九个能力族的产品证据已经全部闭环。能力缺口继续由本文末尾的长时矩阵声明；未来扩展或补证据都不得重新打开已删除路径。

当前公开范围是restricted realtime。Bake/export、通用力场、Bone imported triangle和MC2 reduction/render mapping不属于已支持能力。

## 统一粒子域迁移状态

`MC2_NODE_SIMULATION_DESIGN.md` 定义了未来多 Mesh 统一粒子域的架构和 E0-E7 执行/验收目录。E0 后端中立合同已经冻结：`mc2/domain_ir.py` 定义只读 static/program/parameter/frame/output/index envelope，`mc2/domain_capabilities.py` 在资源分配前检查 CPU/GPU 声明，`mc2/test/fixtures/domain_pipeline/` 固定单 Mesh、双 Mesh 静态域和双帧输入。碰撞 `group/mask` 是可热更新的 `uint32` partition SoA；参数表结构另有 `parameter_layout_signature`，不与数值变化或 program topology layout 混淆。

E1 单 source shadow pipeline 已完成，但它是迁移期验证工具，不是第二个 solver：`source_capture.py` 对真实 Mesh 只做一次静态读取，`static_fragment.py` 和 `domain_compile.py` 只处理冻结 POD，`shadow_pipeline.py` 将新 compiled domain 与 V0 静态构建逐项比较并可采集阶段耗时。只有 `step_mc2` 的内部 `shadow_compile=True` 才会显式启用；默认关闭时不导入、不捕获、不编译、不分配对照数据。V0 context、solve、result 和 writeback 仍是产品唯一权威，shadow report 不进入 Physics World 持久 state。

E2 静态统一域编译核心已完成：有序 Mesh fragment 合并为一个 logical particle field，constraint/primitive 索引在 compiler 内重定位，多个 output target 显式映射；不同 partition 的 runtime 参数保留在统一 SoA，`collision_group/mask` 是可热更新的 uint32 过滤表。`compare_mc2_domain_compile_cache` 只给出 program/layout/parameter 的复用资格和 partition 增删/重排信息，不拥有缓存、task、slot 或 backend。E2 仍未改变当前每对象一个 V0 task 的生产行为，也未运行 fused simulation。

E3 的 CPU backend 生命周期边界已冻结为独立适配器：`cpu_backend.py` 先执行无资源 capability gate，再由显式 kernel 协议承接 domain allocation、frame、step、output 和 dispose；适配器拥有 physical index map 与每 partition history，但不读取 Blender、不导入 V0 context、不承担 Physics World slot 或 writeback。当前完成的是 ABI/lifecycle slice 和 fake-kernel 验收，不是数值 kernel。现有 `_native/src/mc2_context_*` 是 `PyObject*` 驱动的 `Mc2ContextV0` V0 ABI；新 CPU 实现必须新增独立 C++ domain owner/POD view/handle，不得把 compiled domain 伪装成 V0 输入。C++ CPU 实现及旧/新单 source tolerance 对照通过前，生产路径继续只走 V0。

E3 的 frame IO 也已保持独立：`frame_compile.py` 只接收冻结 partition snapshot，校验统一 frame/generation、顶点覆盖和 transform identity，再按 compiled logical index view 生成 `MC2DomainFramePacketV1`；它不读取 Blender，不保留跨帧状态，不把 object reference 传入 backend。

E0 的合同与 fixture 模块仍不被生产节点、Physics World、runtime cache 或 native ABI 导入，不创建 task、slot、backend owner 或 writeback。E1 的 `shadow_pipeline.py` 仅由 `solver.py` 在显式内部开关下懒加载，且只产出调用方持有的临时对照报告；架构审计继续禁止它改变 V0 context/solve/writeback 所有权。E1 完成只表示单 source 的 IO/schema 对照可供后续阶段复用，不表示统一粒子域已经进入产品运行时。

当前生产行为仍保持本蓝本的既有事实：每个 Mesh Object 生成一个单 source `MC2TaskSpec`、独立 static/frame adapter、独立 slot/context，并由 world-owned interaction 处理跨 task self collision。只有 E0 schema/fixture 与 E1 单 source shadow 验收完成，并且 E2-E5 逐阶段通过，才允许改变这条生产数据流。

## 一句话数据流

```text
Physics World Begin
  -> 粒子Profile + Mesh/Bone Task
  -> 规范化全部active MC2 tasks
  -> 只读Blender raw snapshots与native fingerprint
  -> staged static build / per-task slot context
  -> 一次all-task interaction step
  -> result transaction / implicit debug capture
  -> Physics Writeback
  -> Physics World Commit
```

运行时内部链路：

```text
profile + task combination
  -> task identity / setup adapter
  -> world.solver_slots[task_id]
  -> MC2NativeContextV0
  -> world-owned MC2InteractionV0
  -> hotools_native MC2 ABI
  -> private candidate
  -> GN offset / Bone transform / mc2_stats envelopes
  -> physicsWorld.writeback
```

同一个模拟步必须处理全部active MC2对象。MC2不沿用source侧“每component分别执行solver”的调度模型；这里的component对应`粒子参数profile + task`组合，组合产生task identity、slot和context，但不产生独立world step。

## 产品决策

### 按setup裁剪的粒子配置

公开authoring不再使用一个同时显示全部字段的“MC2粒子配置”节点，而是三个setup视图：

| 节点 | 显示字段 | 隐藏/固定字段 | 统一输出 |
|---|---|---|---|
| `MC2 MeshCloth粒子配置` | cloth重力、粒子速度/阻尼/半径、结构/Motion约束、普通碰撞、自碰开关 | Task修正字段、Spring/wind与BoneSpring soft-collision limit隐藏 | `MC2ParticleProfileSpec` |
| `MC2 BoneCloth粒子配置` | 与cloth runtime一致的粒子材料、结构/Motion约束、普通碰撞和task内自碰 | Task修正字段、跨task自碰、Spring/wind与BoneSpring soft-collision limit隐藏 | `MC2ParticleProfileSpec` |
| `MC2 BoneSpring粒子配置` | 半径/阻尼/粒子限速、角度约束、soft-collision limit | Task修正字段、gravity、tether/distance、Motion、普通碰撞模式/摩擦、自碰撞及未被native消费的Spring/wind字段隐藏 | `MC2ParticleProfileSpec` |

三个节点只是同一immutable profile构造器的产品视图，不创建三套solver DTO、runtime ABI或native参数结构。Teleport、组件惯性、Normal Axis与自碰交互质量由独立immutable `MC2TaskParametersSpec`持有；Task按`setup_type`通过唯一`make_mc2_runtime_parameters(profile, setup_options, task_parameters)`入口完成float32采样和源码固定值归一化。三个Profile节点和task空配置默认都显式写入`spring_enabled=False`；当前native未读取`spring_power/spring_limit_distance/spring_normal_limit_ratio/spring_noise`，这些内部兼容字段在真实kernel落地前不得作为产品旋钮公开。

公开cloth Profile节点把自碰撞表达为bool，内部稳定转换成MC2 `self_collision_mode=0/2`，不允许int滑块产生无效模式1。官方JSON预设按owner拆成同名Profile部分与Task部分，并在各节点按真实输入裁剪；应用两个节点上的同名preset恢复完整源预设，不能向用户报告一批本setup不存在的“缺失项”。

所有非显然的int/枚举输入必须在OmniNode `input_init.description`中写出完整数值映射；模式范围、tooltip和参数校验必须一致。碰撞group mask使用`_OmniBitMask` socket，不退回普通0..65535整数输入。

### 粒子能力与属性语义

粒子配置描述可复用的粒子材料、逐深度分布和约束风格，不承载task整体运动修正、对象拓扑或模拟频率。MeshCloth、BoneCloth和BoneSpring节点最终都生成同一种immutable `MC2ParticleProfileSpec`；Task节点生成`MC2TaskParametersSpec`并与setup options一起归一化为固定float32 ABI。Profile或Task参数变化都走native parameter hot update，不重建proxy、baseline或self primitive topology；Pin、半径顶点组、骨链和网格拓扑变化才进入static/surface rebuild。

下表中的setup缩写为`M`=MeshCloth、`C`=BoneCloth、`S`=BoneSpring。“有效”表示当前生产路径存在真实consumer；“固定”表示字段仍存在于统一ABI，但该setup在runtime打包时覆盖为MC2源码固定值；“仅ABI”表示当前能构造或打包，但不改变生产解算结果，不能作为已完成功能理解。

本节各属性表同时是三种粒子配置节点长说明的语义基准。Profile与Task节点的`omni_description`现由各setup实际公开字段的label和`input_init.description`自动生成表格；注册测试逐字段约束短说明必须进入长说明，并验证setup字段裁剪。蓝本继续说明更完整的单位/范围、consumer、曲线/depth采样、无效条件和相关debug模式。socket tooltip只承担短摘要及枚举映射，字段或consumer变更不得只改其中一处。

#### 曲线、深度和参考姿态

- 每个“基础值 + 曲线”输入先相乘，再在归一化区间`0..1`按`i / 15`预采样为16个float32值；没有连接曲线时16项都等于基础值。kernel再按粒子的连续baseline depth插值取值，而不是逐帧求值Blender曲线。
- Mesh baseline parent仍从所有Fixed按MC2拓扑层规则扩张：Fixed邻接优先较短边，后续候选parent优先保持与祖父方向连续。源码depth沿parent chain累计真实边长并按task最大root length归一化；OmniMC2再计算沿真实proxy边到Fixed集合的多源最短表面距离并全局归一化，以`4:1`混合`parent depth:Fixed边界距离depth`，最后沿parent顺序做单调保护。该修正只作用于MeshCloth，用于降低非均匀减面导致的横向等深线偏移；BoneCloth/BoneSpring保持链深度。
- 实际非均匀减面模型已经人工确认该Mesh depth差异能明显抑制横向等高线偏移，并使旋转带动的远端响应更自然。当前`4:1`混合与`1.5`次深度惯性指数因此作为产品默认合同保留；它们暂不暴露socket，避免用户在不了解全部consumer时只针对单一动作过拟合。
- Depth仍是后续可调设计面，可继续评估混合比例、惯性指数、按root/component归一化、路径代价和显式depth顶点组。任何调整必须同时回归阻尼、半径、Distance/Angle、Motion/Backstop、自碰厚度、Center深度惯性和最终输出，不能把depth当成只控制惯性的独立参数。
- `阻尼`和`角度恢复刚度`在runtime转换时分别额外乘MC2源码比例`0.2`；其余公开曲线保持输入单位。这个缩放属于源码对齐，不是隐藏的额外迭代次数。
- `动画姿态`是当帧输入产生的`animated_base_positions/rotations`；`StepBasic`是由静态baseline、组件变换和“动画姿态比例”重建的约束参考。MaxDistance/Backstop使用前者，Angle Restoration/Angle Limit与结构约束使用后者，两者不能混写。
- Task上的`法线轴`映射为`0:+X, 1:+Y, 2:+Z, 3:-X, 4:-Y, 5:-Z`，由Motion Backstop把动画旋转转换成法线方向。
- BoneSpring强制关闭Motion，因此BoneSpring Task不显示`法线轴`；ABI使用Task参数默认值但不影响结果。

#### 输出、外力与速度

| 属性 | 用户看到的功能 | 当前实现与setup |
|---|---|---|
| `混合权重` | 在动画结果和物理解算结果之间混合；`0`偏向动画，`1`输出完整物理结果 | Center把它与Reset稳定权重及distance weight相乘；Bone输出真实消费（`C/S`有效）。Mesh offset输出当前未应用该权重（`M`仅ABI）。 |
| `重力方向`、`重力强度` | 指定world-space重力向量和加速度强度 | prediction阶段按`direction * gravity * gravity_ratio * scale_ratio`累加速度；`M/C`有效，`S`强制重力为0。 |
| `重力衰减` | 组件姿态改变时，按初始局部重力方向与当前world重力的夹角衰减重力 | Center计算`gravity_dot/gravity_ratio`后由prediction消费；不是按粒子深度衰减。`M/C`有效，`S`因重力为0不产生重力效果。 |
| `重置稳定时间` | Reset或Reset型Teleport后让速度/输出权重从0逐渐恢复，避免首步突跳 | 每个真实step按`dt / stabilization_time`恢复`velocity_weight`；三个setup有效，0表示立即恢复。 |
| `阻尼`、`阻尼曲线` | 按深度消减粒子已有速度 | prediction阶段以采样值和simulation power计算阻尼因子；三个setup有效。 |
| `粒子限速` | 限制约束和碰撞完成后的最终粒子速度，负值关闭 | post阶段由当前位置与velocity reference重建速度后限制；三个setup有效。它不限制组件Center速度。 |
| `动画姿态比例` | 控制结构rest pose在静态初始姿态和当帧动画姿态之间的比例 | native逐step重建StepBasic，并用于distance rest length和bone输出；三个setup有效。它不是最终输出混合权重。 |

`重力衰减`的现有节点tooltip“沿粒子深度衰减重力”与生产实现不一致；它不是生产行为，真实语义以上表和`center_gravity_dot`计算为准。

#### Center、惯性与Teleport

这些Task字段处理“角色或组件整体移动时，粒子世界状态应该跟随多少”，先于粒子prediction和约束执行。World/Anchor分量在`center_state.py`生成帧变换，Local/Depth分量在native Center step和prediction中消费。它们由`MC2TaskParametersSpec`唯一持有，不再属于Particle Profile。

| 属性 | 用户看到的功能 | 当前实现与setup |
|---|---|---|
| `Anchor惯性` | 消除平台、载具或角色整体运动等非物理输入；控制剩余多少运动成为粒子惯性 | 三个任务节点直接接受可选Blender Object。帧合同按`1 - anchor_inertia`计算Anchor frame shift；`0`完整跟随Anchor，`1`不施加Anchor增量。每帧读取约束求值后的Object世界变换，三个setup均有效。 |
| `World惯性` | 控制组件world平移和旋转有多少留给粒子形成拖尾 | Center frame shift用`1 - world_inertia`移动旧Center参考；`0`更跟随组件，`1`保留更多world惯性。三个setup有效。 |
| `惯性平滑` | 平滑组件world移动速度，降低抖动传入粒子 | Center保存`smoothing_velocity`并在帧开始平滑位移；三个setup有效。 |
| `World移动限速`、`World旋转限速` | 限制一次world Center补偿可产生的平移/旋转速度，负值关闭 | Center frame shift在计算world inertia后限幅；三个setup有效。 |
| `Local惯性` | 控制每个fixed step内组件局部移动/旋转传给粒子的比例 | native `evaluate_center_step()`生成`center_inertia_vector/rotation`；三个setup有效。 |
| `Local移动限速`、`Local旋转限速` | 限制Local惯性分量，负值关闭 | native Center step按`dt`换算速度后限幅；三个setup有效。 |
| `深度惯性` | 让靠近根部更跟随Center step、远端保留更多惯性变换 | MC2源码使用`1-depth²`；OmniMC2生产路径改为`1-depth^1.5`以减弱末端极值附近对depth偏差的放大，三个setup有效。这是明确产品差异，不得让source oracle静默改写。 |
| `离心力` | 预期把组件旋转产生的离心加速度写入粒子速度 | 当前公开节点和ABI保留字段，但生产solver/native context没有consumer；`M/C/S`均为仅ABI，不能依赖。 |
| `Teleport模式` | `0:None`不检测；`1:Reset`越阈值重置整个task；`2:Keep`整体搬运模拟形状并清除传送造成的不连续状态 | 判定基准是最终proxy顺序中的首个Fixed；无Fixed时回退模拟对象原点。触发作用于整个task；逐粒子实验实现及其debug数组已移除，Keep/Reset真实场景安全性已人工验证。 |
| `Teleport距离`、`Teleport旋转` | 设置判定基准帧姿态发生不连续跃迁的位移和旋转阈值 | 距离阈值乘当前组件scale ratio，旋转单位为度，两者为OR；三个setup使用相同task级触发语义。 |

MC2源码基线以Team Center整体判定Teleport。逐粒子比较动画基准曾作为OmniMC2产品实验实现，但人工验收确认它造成阈值/状态难以解释且不能可靠抑制高速穿模，现已决定回退到单基准、整task触发。OmniMC2产品差异明确为：每个新Physics World帧、fixed-step scheduler之前比较最终proxy顺序中首个Fixed粒子的旧/新动画world pose；没有Fixed时比较模拟对象原点，Bone task即Armature Object原点。位移或旋转任一越阈值即处理整个task，基准身份不得随帧改变。

`Reset`把整个task的粒子状态、rotation、velocity reference、StepBasic/动态历史、速度、摩擦和碰撞历史对齐本帧动画基准；`Keep`按判定基准姿态delta整体搬运state、velocity reference、StepBasic、Motion base和rotation，并只旋转已有真实物理速度。两种模式都把old dynamic/component姿态重定基到本帧、把collider old shape重定基为current shape，避免第一substep沿传送路径重复插值或扫掠；摩擦、碰撞法线、外碰debug contact、task内self、bone output和跨task interaction历史失效后由真实substep重建。触发发生在scheduler之前，zero-substep帧也立即发布新结果。后续新增setup、Teleport状态或collider插值路径时，必须继续覆盖首Fixed/对象原点、Reset/Keep、zero-substep、旧/新collider、task内self与跨task interaction历史。

真实高速平移/旋转与collider场景已人工确认Keep/Reset均安全，不再属于发布阻断。Teleport状态视图把旧到新判定基准的真实位移箭头和旋转测量弧按None绿色、Keep黄色、Reset红色着色，并保留同色终点；这些几何表达判定输入，不表示粒子速度。

Teleport判定姿态由task帧适配器按首个Fixed或对象原点统一提供；MeshCloth与Bone setup在应用整体Keep/Reset时仍需各自正确转换代理/骨骼世界空间。Anchor抵消、world frame shift与Teleport的先后顺序必须对照MC2 Team Center重审，不能把同一基准delta重复应用到粒子。

`distance_culling_enabled/length/fade_ratio`仍存在于统一profile和runtime ABI，但三个产品节点均不公开，当前生产step也没有按相机距离停算或淡出的consumer；它们不是当前产品能力。

#### 结构约束

| 属性 | 用户看到的功能 | 当前实现与setup |
|---|---|---|
| `Tether压缩` | 限制可移动粒子相对所属baseline root的最大压缩量，防止整片向根部塌缩 | 输入是“可压缩比例”，实际最短root距离为`rest * (1 - compression)`，不是`rest * compression`；第一次结构solve使用StepBasic root rest length投影。`M/C`有效，`S`固定为`0.8`，即最短保留`20%`。stretch limit固定为`0.03`，即最长`103%`，不公开。 |
| `距离刚度`、`距离刚度曲线` | 保持相邻粒子、网格边和BoneCloth横向边的rest length | 每步在碰撞前后各执行一次distance projection；静态rest由`proxy_local_positions`的边向量逐轴乘`center_initial_scale * scale_ratio`后求world长度，不能只乘相对scale ratio；再与动画rest按“动画姿态比例”混合。velocity attenuation固定为`0.3`。`M/C`有效，`S`使用固定刚度`0.5`。 |
| `弯曲刚度` | 抵抗相邻三角面沿共享边折叠；0关闭 | runtime把大于0映射为MC2 bending method 2，native按dihedral/volume记录执行。MeshCloth有效；BoneCloth仅在横向连接实际生成triangle时有效，Bone static会注册相同的Bending Tier A。BoneSpring强制Line topology，没有triangle，因此产品配置不暴露该字段且runtime归一化为0。静置时角差`<=1e-3 rad`、volume误差`<=max(1e-6, abs(rest)*2e-6)`视为已满足，避免float32法线/体积重算噪声逐帧积累。 |
| `角度恢复`、`角度恢复刚度`、`角度恢复曲线` | 把父子方向向StepBasic参考方向拉回，形成姿态记忆 | Angle kernel逐baseline投影；target来自StepBasic父子向量与当前parent position，不来自Motion BasePosition。方向dot落在`1 - 1e-7`以内时直接视为no-op，避免identity旋转仍做父子浮点重组而积累静置漂移。三个setup有效。 |
| `恢复速度衰减` | 角度恢复修正后，控制有多少修正同步进velocity reference，抑制持续摆动 | Angle kernel更新位置时同步修正velocity reference；三个setup有效。 |
| `恢复重力衰减` | MC2 Team Center旋转使初始重力方向偏离world重力时，降低角度恢复 | 内核使用`value * (1 - center_gravity_dot)`调节恢复，三个setup都上传并消费该值。Object Anchor使Center旋转产品可达；Mesh、BoneCloth和BoneSpring均有`0/1`有序响应长跑证据。 |
| `角度限制`、`限制角度`、`限制角度曲线` | 迭代收紧相邻粒子相对父级传播方向的弯折角 | 与角度恢复共用Angle pass，但目标由父粒子的模拟旋转和StepBasic局部方向逐级传播，不是Restoration target。MC2源码固定投影3次，因此它不是最终几何的硬裁剪；三个setup有效。 |
| `限制刚度` | 控制超出角度上限后每次投影的修正比例 | Angle kernel只在角度限制启用时消费。刚度1仍保留链式父子共同修正和后续约束造成的有限残差。 |

BoneCloth横向连接是final proxy topology的额外producer：显式横边进入Distance，横跨骨链的triangle进入Bending；两者最终并入`proxy.edges/triangles`，因此碰撞模式为Edge时横边和三角化产生的跨链斜边也参与外部碰撞，开启task内self collision时还会注册对应Edge/Triangle primitive。Point外碰只消费粒子位置/半径，不直接读取横向几何。每个中控骨仍独立生成横向topology，不改变粒子参数含义，也不会与其他中控骨合成同一task。

Bone输出先执行Line方向写回：`rotational_interpolation`直接调节有子粒子的Move父骨，结果会沿Line输出链传给后代；`root_rotation`只调节Fixed链根；`blend_weight`混合StepBasic与模拟方向。三者只改变最终骨骼旋转，不回写粒子位置或下一帧solver状态。随后参与横向triangle的顶点按最终表面normal/tangent重建proxy rotation并覆盖Line结果。这是MC2的输出顺序。产品保留该语义，节点meta必须明确两个旋转参数只对未被triangle覆盖的Line方向有效，不得在triangle之后追加第二次旋转混合。

#### Motion空间限制

| 属性 | 用户看到的功能 | 当前实现与setup |
|---|---|---|
| `最大距离`、`最大距离值`、`最大距离曲线` | 把粒子限制在当帧动画位置周围的球内 | Motion pass使用`animated_base_positions`为球心，并按`depth²`采样半径；`M/C`有效，`S`强制关闭。 |
| `Backstop`、`Backstop半径`、`Backstop距离`、`Backstop曲线` | 在动画姿态法线一侧放置排斥球，阻止布料穿向角色内部 | Motion pass用animated base rotation和`法线轴`构造球心/法线；距离曲线按`depth²`采样。`M/C`有效，`S`强制关闭。 |
| `Motion刚度` | 控制MaxDistance和Backstop位置修正强度 | 只在至少一个Motion开关启用时由Motion pass消费；`M/C`有效。`S`节点当前仍显示该字段，但因两种Motion均被强制关闭而无结果影响。 |

#### 普通碰撞、自碰撞与半径

| 属性 | 用户看到的功能 | 当前实现与setup |
|---|---|---|
| `粒子半径`、`半径曲线` | 定义粒子参与外部碰撞的厚度 | native按baseline depth采样；`M/C/S`有效。MeshCloth再乘对象面板的`radius_vertex_group`权重。 |
| `碰撞模式` | `0:None`关闭，`1:Point`按粒子点碰撞，`2:Edge`按final proxy边连续碰撞 | 外部collider上传后由Point或Edge pass消费；Mesh triangle边和BoneCloth横向/三角补边都属于final proxy边。`M/C`可调，`S`固定Point。 |
| `碰撞摩擦` | 碰撞接触后的切向速度衰减 | runtime同时写入dynamic/static friction，post用接触法线和速度处理；`M/C`可调，`S`固定为`0.5`。 |
| `碰撞限制距离`、`碰撞限制曲线` | 限制BoneSpring粒子被soft-sphere碰撞推离动画基准的最大距离 | BoneSpring Point collision使用animated base和深度曲线执行soft-sphere投影；仅`S`有效，cloth节点不公开且runtime置零。 |
| `自碰撞` | 启用同一task内部的FullMesh GE/PT接触、grid broadphase和intersection history | bool稳定转换为`self_collision_mode=2`；`M/C`有效，`S`强制关闭。 |
| `跨物体自碰撞` | 让同一Physics World中启用交互的MeshCloth task自动互碰，不要求指定对象列表 | MeshCloth节点把开关转换为`self_collision_sync_mode=2`；world coordinator只接纳`setup_kind == mesh_cloth`。BoneCloth节点不公开该字段，runtime对非Mesh setup强制归零，避免产生会被静默忽略的假配置。 |
| `自碰交互质量` | 改变self primitive的相对修正权重 | Task字段`cloth_mass`在self primitive构建时进入inverse-mass计算；`M/C`的task内self都消费，但只有`M`当前能在跨task接触中形成不同布料之间的质量比例。 |

MeshCloth与BoneCloth产品只公开一个半径模型：`particle_radius = profile.radius(depth) * object_radius_weight`，self thickness统一由profile radius按`0.25`派生。对象顶点组仍只调制实际particle radius，不另外创造self厚度输入；BoneSpring强制关闭自碰并拒绝派生模型。独立`self_collision_thickness`仍只属于source oracle，不得重新暴露第二套用户半径。

人工验收曾发现：无拓扑交叉、无非流形的单层Mesh中，红色self contact大量聚集并伴随持续微动。完成一环过滤与final intersection debug纠正后，实际模型中的洋红几何穿插完全消失；红色contact只剩在代理本身真实拥挤的区域，布料和接触区域均完全收敛且不再运动。该结果确认一环误碰是原扰动的主要根因，并完成D-04人工验收。红箭头表示有效接触法线，不等于非零持续修正；同一world-space曲面的密度分档、contact churn和RMS速度继续作为未来自动回归，不再作为当前发布阻断。

Task内self collision的拓扑排除以final proxy edges为事实源。self static上传时native一次性生成排序去重的一环粒子邻接键；EE/PT candidate和Edge-Triangle intersection都拒绝共享particle或任意端点一环相邻的primitive。该规则避免同一连续曲面的结构邻居互相排斥，不扩展到不同owner的跨task interaction，也不为debug增加逐帧生产。自动回归证明断开的远邻接触与真实穿插仍保留、一环三类误报被拒绝；实际密集单层模型进一步证明静置收敛，D-04已经人工关闭。不得在没有新反例和局部厚度/边长证据时继续扩大固定k-ring。

独立Edge-Triangle穿插检测按`frame % 2`在grid排序后索引为奇数/偶数的Edge之间跨帧时间分片，以降低每帧窄相成本；普通EE/PT厚度contact仍每个真实step执行。`self_intersect_records`在非final阶段保存当前分片经过grid/AABB与邻接过滤的broadphase record，final线段-三角形测试后原地剔除未命中项，并设置particle intersect flags；debug专用readback只允许读取final结果，所以洋红现只表示确认穿插。新帧候选生成开始时必须撤销上一帧final-ready，本帧final完成后才重新发布；内部历史flags可保留，但不能授权debug读新候选。真实命中仍会按分片隔帧显示，这种规律切换不得解释为浮点随机或普通contact停止；稳定两帧观察只能作为明确标注的renderer窗口。

#### 实际step中的消费顺序

```text
Profile/curve authoring + Task corrections
  -> setup归一化 + 16点float32采样
  -> parameter hot update
  -> Center/Anchor帧补偿 + 单基准整task Teleport状态转换
  -> prediction: Center inertia + damping + gravity
  -> Tether -> Distance -> Angle -> Bending
  -> Point/Edge外部碰撞 -> Distance(第二次) -> Motion
  -> task内self collision -> world跨task self interaction
  -> post friction/particle speed limit -> Mesh/Bone结果输出
```

Spring/wind字段目前只为源码数据结构和预设解析兼容而保留；三个产品节点都写入`spring_enabled=False`，native也没有生产Spring/wind kernel consumer。BoneSpring的“弹簧感”来自固定distance、angle、惯性和soft-sphere组合；Line topology不生产Triangle Bending，也不等于启用了这些`spring_*`字段。

实现owner固定如下：公开字段与tooltip在`mc2/nodes.py`，immutable Profile/Task authoring值与源码固定常量在`mc2/parameters.py`，Task装配在`mc2/specs.py`，setup归一化和16点ABI在`mc2/runtime_parameters.py`，Object Anchor帧适配在`mc2/anchor.py`，World/Anchor帧补偿在`mc2/center_state.py`，粒子预测与task内约束在native context/`_native/src/mc2_context_core.cpp`，跨task协调在`_native/src/mc2_context_interaction.cpp`。Teleport由native `apply_task_teleport`读取首个Fixed或对象原点的旧/新world pose并只返回一个任务级结果；Reset/Keep由solver统一提交，debug仅在显式请求时消费该小结果，不生产逐粒子阈值或状态数组。新增或删除参数必须同时核对唯一owner、三个setup视图和能力测试矩阵，不能在Profile与Task复制同一可编辑值。

四个已验收执行节点使用正式名称`MC2 MeshCloth任务`、`MC2 BoneCloth任务`、`MC2 BoneSpring任务`和`MC2模拟步`；维护态产品节点不得继续带“（框架）”后缀。

三个任务节点都有一个可选`Object`类型`Anchor`输入，不增加独立Anchor节点、Any socket或通用隐式对象协议。用户需要骨骼Anchor时创建Empty并用Blender约束跟随骨骼。`MC2TaskSpec`保存Object活引用；即使任务节点被lazy skip，always-run模拟步的frame adapter仍每帧读取depsgraph求值后的世界位置和旋转。Anchor身份或运动不进入task id、topology/config signature和native static build；替换、移除或首次连接Anchor时Center无冲击重新定基，普通运动只更新帧状态。Anchor不是Pin、碰撞体、Teleport判定源或可写回对象。

### MeshCloth对象输入

公开MeshCloth任务使用多输入`list[bpy.types.Object]` Object socket，不使用`Any`。每个输入必须是Mesh Object，并各自产生一个只含单source的task；一个task不得包含多个Mesh，因为MeshCloth static/frame adapter以单final-proxy topology、单BasePose读对象和单写回目标为原子边界。节点输入多个Mesh时，全部task仍由同一个MC2模拟步统一推进，跨对象self collision由world-owned interaction处理。

`Object.hotools_mesh_collision`由物理对象面板的“简单布料”入口公开。持久字段至少包含启用状态、BasePose只读对象、半径顶点组、Pin启用/Pin顶点组和碰撞组；Pin等对象级authoring不得藏在节点临时值或solver私有缓存中。

`Object.hotools_mesh_collision.mc2_base_pose_proxy`指定每个source/write对象对应的只读BasePose对象；BasePose不是第二个task source，也不作为额外公开socket重复输入。automatic frame path在全部static/frame只读快照之前执行轻量门卫：只检查active MeshCloth source是否为live Mesh、属性组是否存在以及proxy pointer是否为空。仅空指针进入创建，生成独立Object与独立Mesh并归档到`HoPhysicsCache`；已有代理直接跳过，禁止逐帧调用完整ensure、拓扑签名计算、Mesh复制或刷新。

### BoneCloth横向连接

BoneCloth横向连接是HoTools产品差异，不是需要抹平的MC2兼容分支：

- 公开BoneCloth任务只接受多输入`_OmniBone`“中控骨”socket；每根中控骨的直接子骨分别成为有序链root，中控骨自身不进入模拟粒子。
- 公开BoneSpring任务只接受多输入`_OmniBone`“根骨”socket；每根root自身进入固定Line骨链，并递归收集其后代。
- BoneCloth每个中控骨生成一个task；该中控骨的直接子链只在本task内横连。多个中控骨即使属于同一Armature，也不得合并成一个横向topology。
- BoneSpring仍按Armature owner分组生成task；一个节点可输入多个骨架，但不同骨架绝不共享一个topology/context。
- 任务节点不得用`Any`或泛化“骨链”标签隐藏这两个不同的选择语义；显式chain字典只属于内部spec、oracle和测试边界。
- `mc2_source`保持MC2 Line连接语义。
- `hotools_product`按稳定骨名、链组和节点输入顺序生成纵向与横向连接，并生成稳定UV triangle。
- 显式横边约束同深度粒子；横向triangle还会补出跨链斜边。final proxy把这些边和面同时交给Distance/Bending、Edge外碰与task内self primitive producer，不能把横向连接理解为只改变布料形状。
- 同Armature可有多个不重叠component，结果在一次写回事务中合并。
- 组件骨名重叠明确拒绝，不能依赖后写覆盖。
- viewport debug必须显示真实纵横连接，不能要求用户从模拟结果猜拓扑。

### 跨物体self collision

产品节点只暴露self collision开关与group/mask，不暴露ListObject socket。当前跨task产品域是MeshCloth；BoneCloth只有task内self collision，BoneSpring关闭self collision：

- 全部启用跨物体self collision的active MeshCloth task自动进入同一world interaction scope；native interaction以`setup_kind == mesh_cloth`为硬边界。
- Physics Object Scope不暴露MC2 Mesh碰撞开关；MC2 setup collector从同一对象范围隐式发现task，通用scope开关只筛选公共Object/Bone collider和其他solver domain。
- mask为零表示自动全互碰。
- mask非零时双方group/mask必须握手匹配。
- task动态增删由interaction scope逐帧同步；Python不维护partner列表或pair resolver。
- world-owned interaction context锁步处理跨owner grid、broadphase、EE/PT contact、四轮solve和跨帧intersection history。

指定对象列表会把world已知membership重复搬回节点图，并增加Python pair解析和动态图失效路径，因此不是当前产品合同。未来若要增加排除/分区表达，应扩展稳定group/scope语义，不应恢复ListObject兼容模型。

### 单一模拟步设置面

Physics World中只存在一个公开MC2模拟步，因此不暴露独立的“MC2模拟设置”节点或settings DTO socket。`time_scale`、`simulation_frequency`和`max_simulation_count_per_frame`直接属于模拟步；函数节点只有在输出被图执行需要时才规范化内部`MC2SolverSettingsSpec`。设置签名变化只更新slot settings revision和scheduler输入，不进入static fingerprint，也不重建native context。

`MC2模拟步`必须声明`always_run=True`。World对象和task identity跨帧复用不代表时间输入未变化；每次图执行都必须进入solver，由`frame_context`与slot continuity决定reset、same-frame、pause或fixed-step推进，不能让OmniNode值缓存替代物理时间判定。

MC2的`time_scale`是solver局部倍率，不是场景时间源。基础时间只来自当前`PhysicsWorldCache.frame_context`：Physics World按Blender `render.fps / fps_base`产生`raw_dt`，应用世界倍率得到`dt`，MC2再按`mc2_dt = frame_context.dt * mc2_time_scale`消费。MC2不得自行读取Scene帧率或用固定帧时长替代world时间；局部倍率只影响MC2，不改写world，也不改变同一world中Rigid和SpringBone的基础尺度。

MC2 fixed-frequency scheduler以world `raw_dt`和“世界倍率 × MC2局部倍率”累计等价的`mc2_dt`，再按`simulation_frequency`离散并受`max_simulation_count_per_frame`限制。固定频率和catch-up上限是积分/调度策略，不是第二套时间。世界或MC2局部倍率为0时可以更新frame input与pause所需的Center历史，但native simulation step不得前进；same-frame不得重复累计。

旧`substeps`与`iterations`字段已经删除：它们从未被生产solver消费。MC2的实际更新次数由固定频率scheduler决定；约束与self collision迭代顺序属于源码对齐的native内核固定语义，不能用无效的通用迭代旋钮覆盖。

### 单一半径模型

公开Mesh产品只存在一个粒子radius输入，按顶点组采样：

```text
particle_radius = profile.radius * vertex_weight
self_thickness = particle_radius * 0.25
```

独立self thickness输入和曲线不对产品公开。MC2 source oracle可以保留独立thickness以核对源码，但不能进入生产节点或profile。

数值半径只来自公开particle profile；Mesh对象只保存可选`radius_vertex_group`乘数。该权重进入raw snapshot、surface fingerprint和native proxy static，权重变化必须重建context；留空时全顶点乘数为1，指定不存在的组明确拒绝。对象RNA不再保存第二个radius、自碰开关、self thickness或cloth mass；通用碰撞预览也不重算粒子球，真实普通半径与self厚度统一由MC2隐式debug快照显示。

Self primitive不能由外部collider替代：外部collider只表达cloth对外部Point/Edge等形状的碰撞，不能覆盖cloth内部或跨cloth的EE/PT、grid、contact cache和intersection history。派生较小self thickness也是明确的性能决策；直接复用完整particle radius会显著放大grid candidate/contact数量。

### 全隐式debug

Debug沿用SpringBone VRM蓝本的隐式请求模型，但覆盖更多阶段：

- 用户不连接任何中间态socket。
- debug节点自动发现world内MC2 slots并登记一次性或continuous请求。
- MeshCloth、BoneCloth和BoneSpring任务节点都输出可直连debug过滤输入的`任务名称`字符串；值是精确`task_id`，多task按换行分隔。任务节点首轮真实求值必须把任务与名称同时写入OmniNode持久寄存器，后续lazy skip复用该缓存值。
- 请求只在下一次真实native advance时捕获；same-frame保留请求但不伪造快照。
- renderer只消费冻结只读快照，不读取当前RNA反推过程。
- 无请求时不得执行中间态native readback，`debug_readback_count`保持零。

空间debug模式必须按实际消费语义拆分，不允许继续用一个“Motion”开关混画不同基准：

| 模式 | 冻结数据源 | 表达 |
|---|---|---|
| StepBasic参考姿态 | C++ context的`step_basic_positions`与真实topology edges | Distance、Angle和bone输出共同消费的结构参考姿态；用于和动画Motion BasePosition区分 |
| 粒子深度 | C++ context已有的`baseline_depths/root_indices/parent_indices`按请求readback | 蓝到橙的0..1色带显示真实曲线采样坐标；粉色=Fixed，紫色=无根Move，黄色=ZeroDistance，白线=至少含一个Move的跨root边，橙线=局部突跳，纯红点/线=parent或深度不变量异常。`深度粒子索引`以紫色显示选中粒子的完整parent路径；累计长度和归一化分母数值仍待后续实现 |
| 有效重力 | runtime重力方向/强度与C++ `gravity_ratio/scale_ratio` | 每个Move粒子重复一组组件级箭头：灰色为`gravity * scale_ratio`，绿色为再乘`gravity_ratio`的实际有效重力，长度均乘`0.02`；不表示逐粒子衰减 |
| 粒子速度 | C++ post后的`state_velocities`与`particle_real_velocities` | 青色为下一步积分速度，橙色为本步实际位移速度，长度均乘`0.03`；黄色连接两者终点表示差值，积分速度命中粒子限速时标红 |
| Distance误差 | C++ `distance_ranges/targets/rest_signed` + 当前位置 + StepBasic | 绿色接近有效rest，红色拉长，蓝色压缩；有效rest包含scale与animation pose ratio，重复无向pair只画一次 |
| Tether状态 | C++ `baseline_roots` + StepBasic root两点直线rest length + runtime压缩/拉伸限制 | 低饱和灰线只表达root到Move的栓绳关系；蓝/橙点表达压缩/拉伸侧接近或触发，深色箭头表达本步真实回拉修正；不画范围圆环，避免被误解为水平摆动限制。rest不是parent链累计长度，也不是depth |
| Bending约束 | C++ `bending_quads/rest/marker` + 请求时记录结果 | 只显示本步真实触发的记录：低饱和共享边用于定位，紫点=二面角、青点=体积，红箭头来自该记录各role的真实修正；未触发的全量quad不占据视口 |
| Motion BasePosition | C++ context的`animated_base_positions/rotations`按请求readback | MaxDistance与Backstop真正使用的中心和法线轴；不得用StepBasic替代 |
| MaxDistance/Backstop | Motion BasePosition + native逐记录触发状态 | 只在接近或触发时显示低亮度粒子到目标关系线及对应范围；蓝=MaxDistance、橙=Backstop，小点=接近，大点与红箭头=本步真实触发 |
| Angle Restoration target | C++基于`step_basic`父子向量和当前parent position输出的target + 逐迭代记录状态 | 三轮记录按child合并为最严重状态，只为接近/触发粒子显示低饱和目标线；浅粉小点=接近，亮粉大点与红箭头=真实触发，不铺满全部恢复目标 |
| Angle限制范围 | C++按最终状态请求时重建的父旋转级联target + 按depth采样的`angle_limit` + 逐迭代记录状态 | 三轮记录按child合并，只为接近/触发粒子显示局部低亮度锥；黄点=接近，橙点与红箭头=真实触发；它使用Limit层级方向，不复用Restoration target |
| Final Output Offset | 已冻结result candidate与writeback plan | Mesh实际object-local offset对应的world线段；Bone只显示实际允许平移的target，connected rotation-only骨不伪造位移 |
| Task External Colliders | 每个runtime item实际上传的`MC2ColliderFrameSpec` | 已经过source排除、group mask、setup type过滤的collider key/type/shape；task过滤必须只画该task参与集合 |
| 实际接触 | task Point/Edge外碰记录 + world interaction跨owner contact | 外碰只显示命中的真实半径球/变半径胶囊、对应collider和白色接触点；黄色箭头将实际推动固定放大8倍。跨task只纳入enabled且owner不同的EE/PT contact，并为两侧primitive分别显示四轮solve真实累计贡献；同task self不重复绘制 |
| 自碰几何单元 | self static/dynamic的Point/Edge/Triangle primitive | 紫色点、边和三角形轮廓；回答“哪些几何真的进入自碰检测”，缺失时优先检查self static构建 |
| 自碰空间网格 | native broadphase的primitive grid坐标与`grid_size` | 灰色占用格；回答“primitive怎样分桶”，格子过大或过密用于定位半径、厚度和primitive尺度问题 |
| 自碰候选配对 | grid broadphase输出的candidate primitive pair | 黄色primitive中心连线；只表示可能相交，允许包含false positive，数量爆炸是性能诊断信号而非接触数量 |
| 自碰接触结果 | narrowphase contact、enabled flag、两侧实际correction与intersection history | 细淡红线为启用接触存在提示，黄色箭头为两侧真实推动并固定放大8倍，灰色为未启用接触，洋红为穿插记录；这是四项中唯一表达最终窄相/解算结果的模式 |

上述模式都只在请求后的下一次真实advance捕获。正常帧不得遍历或复制这些debug数组。每个slot的self几何、网格、候选、接触使用四个独立请求位；共同的primitive索引只读一次，未请求阶段不得分配或复制对应数组。跨task interaction使用同一组四位mask，基础position/index/owner只在任一self模式或“实际接触”的跨task分支请求时读取，grid/candidate/contact/intersection按位复制；“实际接触”只请求contact，不得顺带读取grid或candidate。所有显示位默认关闭；没有显式模式时，节点只取消旧请求、清理自己的绘制快照，不安装绘制处理器，也不请求基础位置或readback。

Debug节点长描述必须由与可见输入顺序一致的单一条目表生成。每项首先回答用户判断所需的五类事实：用途、当前状态怎样读、怎样算正常/异常、哪些公开参数精确影响它、哪些上游运动/约束/碰撞可能使它变化或触发；再说明必要的数据源、图元、颜色、捕获时机和不应作出的推断，不能只复述代码做了什么。Blender注册回归必须断言条目标签与`_INPUT_NAME`完整逐项相等、无重复，且五类标题逐项存在；新增或改名socket时必须同步更新说明。

Motion BasePosition、Angle Restoration target、Angle Limit target、粒子速度、Distance/Tether、Bending static、Bending record结果与外碰实际接触分别使用独立C++ readback入口；Python按显示开关精确分配并冻结数组。Angle Limit的层级目标只在该模式请求时由C++重建；外碰contact只在下一真实substep前收到显式请求后由Point/Edge kernel记录。“实际接触”同时独立请求world interaction contact并用owner identity筛出跨task结果，不得要求用户额外开启自碰4。Topology、parameter、motion、center、collision和output等Python payload也必须按实际绘制依赖构造；interaction participant过滤字典只在self或跨task实际接触请求等待消费时生成。关闭对应模式时不得调用该入口，也不得因其它debug模式顺带生产或复制这些数组。

### Debug state与绘制能力扩充规范

Debug扩充必须先区分三类state，禁止因命名都含`debug`而混为同一职责：

- **Solver state**是解算本身无论是否显示都必须生产的数据，例如self grid/contact cache。Debug只能按请求读取，不能复制一份Python shadow。
- **Oracle state**是Tier A或源码对齐测试需要的完整内部数组。它可以保留全量native ABI，但生产viewport不得调用；接口名与调用点必须能和`read_debug_*`区分。
- **Viewport debug state**只服务绘制。若该派生量不是solver必需状态，只能在对应显示位已请求后生产；热点派生在C++请求式生成，Python只负责精确分配、冻结和组装，不得每帧预生成。

新增或扩充一种绘制能力前，设计记录必须填写以下契约；缺一项不得合入：

| 项 | 必须明确的内容 |
|---|---|
| 用户模式 | 独立socket/开关名称及用户要回答的物理问题 |
| 请求身份 | 独立request bit；不得用笼统`debug_enabled`替代 |
| Producer/owner | C++ context、interaction或Python静态payload中的唯一生产者 |
| State分类 | Solver、Oracle或Viewport派生；说明为何不能复用另一类接口 |
| 生产时机 | substep中间态默认在请求后的下一次真实substep冻结；Teleport这类scheduler前帧判定必须显式声明为new-frame producer，可在zero-substep帧冻结；same-frame一律不得伪造 |
| 精确依赖 | 该模式需要的共享base与阶段数组；不得顺带生产兄弟模式数据 |
| 数据预算 | 顶点/primitive/contact数量级、分配字节和readback次数上界 |
| 空值语义 | 物理量为零或无记录时允许空批次，但snapshot必须能区分“已请求且为空”和“未请求” |
| Renderer语义 | 图元、颜色、深度测试、单位、缩放和`max_items`截断规则 |
| 验收证据 | 隔离模式、真实捕获帧、未请求键缺失、非零几何语义、关闭debug零开销 |

生产契约固定如下：

1. Debug节点只登记请求，不立即读取当前state；capture只消费下一次具有substep的冻结结果。全部显示位关闭或节点禁用时必须取消尚未消费的slot/interaction请求，空模式集不得触发基础positions/rotations readback。
2. 未请求时不得遍历、重建、分配、`memcpy`、创建participant字典或增加native `debug_readback_count`。共享base只能在至少一个真实依赖模式请求时生产一次。底层稀疏filter中缺失的模式键一律等价于`False`；节点默认也必须全部关闭，不能把UI默认值下沉为readback API的隐式生产。纯Center与纯Output只消费已有Python冻结状态，context native readback增量必须为零。
3. 每个模式拥有独立位。只有数据域和生命周期完全相同的数组才允许共用readback；“实现方便”不是把Motion、self四阶段或多种约束打包的理由。world interaction内部的`show_self`只能由四个显式self阶段位派生，调用者不负责也不得用该聚合位替代具体请求；“实际接触”的跨task分支使用独立`show_interaction_contacts`派生位，只复用contact readback数据域。
4. Renderer只消费snapshot中明确存在的键。不得从最终网格、当前RNA或另一模式的target反推缺失中间态；Angle Limit借用Restoration target属于明确禁止的越界。
5. Oracle全量接口不得进入`MC2_REQUIRED_NATIVE_SYMBOLS`或viewport调用链；生产Debug使用最小`read_debug_*`接口。若测试需要完整scratch，必须保留在oracle层而不是扩大生产readback。
6. Snapshot一经捕获必须只读并带精确frame/generation/task identity。新请求未遇到真实substep时继续显示旧快照，但验收必须检查`captured_frame`，不得把旧快照算作新模式覆盖。
7. 隔离验收必须逐模式执行“登记请求 -> 等待该模式声明的真实生产阶段 -> 捕获 -> 绘制”。substep模式等待真实advance；scheduler前帧判定模式等待新的world frame。未请求阶段键必须不存在；有非零物理量时必须出现该模式自己的batch语义，零量只验证精确空readback，不得伪造图元。
8. 性能验收至少比较debug全关、单模式和最重组合三档的readback次数、分配规模与capture耗时；debug全关必须保持零额外生产。任何常驻C++ debug buffer都需要单独产品决策，不得由可视化需求默认引入。

约束pass结果使用五个独立请求位，生产顺序固定为`Tether -> Distance A -> Angle -> Bending -> Distance B -> Motion`。C++仅为被请求的pass保存pre-position和实际position delta；共享readback只传输ready位对应的稀疏pass，单Tether请求不携带另外五个空槽，请求清零时释放buffer容量。Python按canonical pass顺序恢复模式结果并冻结只读数组，renderer按模式语义绘制关系线、接近点和真实修正箭头；调试节点另提供按task的状态/接近/触发计数文本，不把计数猜测成几何数量。

五类约束均已进入记录级。Tether记录身份是稳定`vertex/root`，其pass correction天然等于该记录结果；Python按请求派生上下限、ratio、signed error与near/active五态。Distance记录身份是每个phase的有向`record_index/owner/target`；debug请求时C++在临时位置副本重放A/B phase，保存phase前origin、有效rest/current length和经owner记录数平均后的贡献，真实context仍由未改写production函数唯一写入。每个`phase+owner`的记录贡献和必须等于pass粒子correction。Bending记录身份是稳定`record_index + quad四角色`及dihedral/volume类型；请求时C++用生产公式影子重放，将role修正经过相同`int32`量化并除以该vertex的参与记录数，按vertex汇总必须等于Bending pass correction。Motion记录身份是稳定`branch + vertex`，branch固定为MaxDistance/Backstop；影子kernel按真实先后顺序把刚度后总修正拆为两个可加贡献，按vertex求和必须等于Motion pass correction。Angle记录身份是`branch + iteration + baseline_data_index + parent/child`；影子kernel严格保留三轮Limit/Restoration交错顺序，分别记录当轮current/limit和双角色贡献，两分支按vertex联合求和必须等于Angle pass correction，不得用两个独立重放替代。以上均由native与Blender runner锁定，且debug-off不分配记录buffer。

MC2 viewport表达遵守公共物理debug图元语义：fixed/move粒子、Motion BasePosition、Angle Restoration target、self point primitive、Center位点和最终输出端点使用屏幕尺寸圆点；Motion法线、角度恢复修正、Center shift、接触法线和最终输出offset使用箭头；纵横拓扑、triangle、candidate和shape轮廓仍使用普通线。位置点不得再用三轴十字伪装成旋转basis。Blender debug runner当前以Mesh fixture逐个隔离28个开关；substep模式等待下一次真实substep，Teleport两层等待下一new-frame判定，二者都必须捕获匹配帧，禁止复用旧快照冒充覆盖。有非零几何量的模式要求自己的batch颜色语义，速度等零量允许空批次但必须存在该模式的独立只读readback。它已覆盖topology、attributes、step/gravity/velocity/distance/tether/bending、motion/angle、center、Teleport阈值/状态、collision/radius、四种self和output分支，并以只有`show_self_candidates=True`的稀疏请求锁定未声明StepBasic/Motion/Angle键缺失及精确readback增量。BoneCloth/BoneSpring的其余几何语义仍按能力矩阵补齐。

### Debug收尾与产品踩坑

#### 通用生命周期

Debug不是solver的第二输出通道，而是一次请求驱动的观测事务：

```text
无显式模式
  -> 取消旧slot/interaction请求
  -> 不安装draw handler，不调用native debug setter，不读中间态

显式模式
  -> 节点登记按task/setup过滤的request bits
  -> 下一次真实substep设置对应native位
  -> C++只生产被请求的记录/贡献，production state仍由正常solver唯一写入
  -> 真实step完成后复制最小readback并冻结只读snapshot
  -> capture收尾立即清除native debug位
  -> Python只派生状态摘要，renderer只消费冻结snapshot
```

same-frame、无substep和未匹配task/setup不伪造新快照；旧快照可以继续显示，但必须带原始`frame/generation/task_id`。切换task过滤、setup过滤、模式集合、generation或不连续帧时，旧时间层历史必须清除，不能把观察空档制造成新增/失效事件。

#### 三类state与唯一职责

| 层 | 唯一职责 | 关闭时的合同 |
|---|---|---|
| Solver state | 生产求解本身必需的state，例如self grid/contact cache、最终位置和速度 | 不因为viewport而复制第二份Python history |
| Native viewport/oracle state | 在独立request bit下记录pass前origin、真实correction、contact/intersection和按记录归因数据 | 未请求不分配记录buffer、不遍历记录、不做shadow replay |
| Python snapshot/renderer | 冻结只读数组、计算near/active/status、按语义绘制 | 不读当前RNA、最终网格或另一模式target反推中间态；不写solver state |

C++ production kernel是唯一位置、速度和接触状态写入者。C++ debug记录只观察同一substep的真实pass，并在请求时运行必要的记录归因；Distance、Bending、Motion、Angle的影子记录必须与production公式、量化和共享粒子平均保持求和等价，但不得替代或二次提交production solve。Python不得实现第二个solver。

#### 最终性能门禁

- **debug全关**：没有native debug readback、没有约束记录buffer、没有contact/intersection明细、没有interaction participant debug字典；主循环只检查是否存在pending request。默认节点没有模式时不安装draw handler。
- **单模式**：只付出该模式需要的C++记录、共享base和readback；`max_items=10000`只限制renderer绘制预算，不会降低native记录成本，因此性能测试必须同时看记录数量和绘制数量。
- **最重组合**：允许按需付出多个模式的记录/readback，但共享positions、primitive indices和interaction owner数据每帧只复制一次；未打开的兄弟模式键必须缺失。
- native setter只在请求状态改变时跨Python/C++调用；capture完成后立即清除，避免普通substep反复设置debug位。
- self contact debug的逐贡献归因只在`self_contact_debug_requested`时构造；关闭时仍执行真实self求解，但不构造debug临时记录。
- `MC2模拟步`拥有默认关闭的`热点时长调试`socket。关闭时向solver传入`timing=None`，不读取分步墙钟、不创建聚合字典、不复制诊断上下文，也不在节点浮层显示内部阶段。开启后MC2逐次切分“输入与任务、静态准备、帧与调度准备、模拟求解、结果构建、调试捕获、结果发布”七个连续阶段：同一次测量既写入world自有的约1秒控制台聚合器，也在当前节点恰好取得通用`OmniNodeTiming`低频采样session时写入浮层。文字与阶段边界由MC2拥有，通用renderer只提供空槽、排序与绘制；MC2不读取树RNA、不调用绘制模块。控制台格式沿用NodeTree聚合耗时报告的Summary/Scope/State/Slow Stages结构，列出阶段均值、占比和窗口峰值，并把任务类型、粒子量、dt、实际substep/native batch、collider/interaction任务范围、创建/重建/更新/复用、Reset/Teleport、debug capture和写回情况放在同一窗口。控制台另列`Solve Detail`嵌套段，只对真实可分割的Python调度边界统计“批次编组、任务同步与调试配置、native组求解”；它明确以`模拟求解`为分母且不与外层七段相加。native当前没有公开约束/碰撞各自时长，禁止用推测值冒充内部阶段。该socket只控制观察，不进入settings、static fingerprint或slot重建判定。

当前自动证据包括：native MC2 context全套debug/生命周期回归、Blender隔离28模式、debug-off零readback、默认节点惰性、过滤切换取消旧request、未请求键缺失和冻结snapshot只读性；热点benchmark另行分开raw/frame/group/result/writeback/debug capture。绝对毫秒只作为同机同资产回归，不作为跨机器合同。

#### 已吸收的真实反例与决策

- **Teleport**：逐粒子判定实验导致高速穿模和不可解释的局部状态，已回退为首个Fixed、无Fixed则对象原点的整task判定；Reset/Keep重定基动画、collider、速度与接触历史，debug只显示一个task结果。
- **自碰**：broadphase候选、普通contact和final Edge-Triangle intersection曾被画成同一种红/洋红结果；现按四个self模式和时间层分开，final intersection只读确认命中，一环邻接过滤属于production topology规则而不是debug补丁。
- **真实接触**：原来用法线或固定长度箭头冒充推动强度；现只显示kernel真实半径形状、接触点和真实correction，跨task只纳入enabled且owner不同的EE/PT记录，显示倍率不进入solver。
- **Tether**：范围圆环把牵引误读为水平摆动限制；rest明确为StepBasic粒子到baseline root的世界直线距离，不是parent累计长度或depth，灰线只说明牵引关系，蓝/橙点和箭头才说明接近/实际拉回。
- **拓扑/碰撞显示**：按数组前缀截断会整块隐藏后续Mesh分量；当前按连通分量公平抽样。拓扑和候选属于高级审计，不能盖住结果视图。
- **产品差异**：Baseline depth按OmniMC2产品定义和consumer矩阵验证，旧MC2源码测试矩阵只能作为参考，不能把深度差异误报成回归。

这些结论、性能合同和最终实现状态取代阶段性人工验收文档；具体历史提交仍由Git保留。

## Setup与支持域

| Setup | 输入/拓扑 | 碰撞 | 输出 | 限制 |
|---|---|---|---|---|
| MeshCloth | Object多输入 -> 每个Mesh一个单source task；每个source配套BasePose双对象 | Point/Edge外部碰撞，单/跨物体self | GN object-local offset | topology-preserving动画；UV seam按triangle corner读取，不拆粒子；不兼容拓扑明确拒绝 |
| BoneCloth | 每个Bone socket中控骨 -> 一个task；其直接子骨组成独立HoTools product ordered-chain组 | Point/Edge外部碰撞，task内self；当前无跨task self | Bone transform batch | 中控骨不入粒子；不同中控骨禁止横连；imported triangle拒绝；同Armature组件骨名不得重叠 |
| BoneSpring | Bone socket根骨 -> 包含root的固定Line骨链 | soft sphere，Sphere-only | Bone transform batch | gravity/self/max-distance/backstop按BoneSpring归一化关闭或固定 |

Bone imported triangle当前明确拒绝，因为现有producer没有成立的UV/tangent/basis输入。新增支持前必须建立真实authoring producer、Tier A oracle、产品节点和debug表达。

Center signed component支持无shear、非零scale域。PoseBone object-space必须proper、shear-free且正scale；不满足时在snapshot/writeback前拒绝。

## 身份、slot与单步事务

固定身份：

```text
solver_id: mc2
slot_kind: mc2
slot_id: task_id
setups: mesh_cloth / bone_cloth / bone_spring
shared results: gn_attribute / bone_transform
private stats: mc2_stats_v0
world interaction resource: mc2_interaction_v0
```

Task identity覆盖setup、source/target身份和产品拓扑。BoneCloth中控骨边界也是task/横向topology边界。Profile参数、热更新数值与scheduler设置不创建第二个task；它们通过dirty/update策略更新同一slot。

一次step的事务顺序固定为：

1. 规范化、去重并验证全部active tasks。
2. 为每个task读取短生命周期raw snapshot，计算fingerprint并完成全部只读prepare。
3. 任一prepare失败时释放本轮staged context，不进入world写事务，不改变旧slot/result。
4. 进入一次world写事务，顺序安装或替换已经完整staged的per-task slot/context；此处不声称native状态可回滚。
5. 同步全部frame/collider/Center输入，再由world interaction context按substep批量推进。
6. readback形成私有candidate；全部公共result和writeback plan验证成功后一次发布。
7. 公共发布失败恢复进入发布前的result streams；stale slot只在成功路径prune并幂等dispose。

只读prepare失败保持旧slot/context/result不变。进入native mutation后若任一同步、group step、readback、结果合并或发布抛错，则不伪装成可回滚：统一销毁全部MC2 slot与world interaction，清除本帧MC2结果并设置`replace_required=True`，下次调用从完整重建开始；其他solver的slot和result不受影响。

同帧重复执行不推进native，不增加candidate revision，只复用当前完整结果。倒放、跳帧、world generation变化、用户reset和首次有效pose保持不同reset reason。

## 数据层与所有权

| 层 | 内容 | Owner与生命周期 |
|---|---|---|
| H0 identity | task/setup/source/target、ordered Bone root identity | Python spec/session；不进入kernel |
| H1 authoring | profile、curve、Pin/selection、bone hierarchy、外部identity | Python immutable authoring；用于重建/诊断 |
| H2 raw snapshot | Mesh positions/normals/loop UV/triangle loop index/Pin，Bone rest/pose matrix，component pose | Blender adapter短生命周期；交给native后丢弃 |
| N0 proxy static | fingerprint、final proxy、orientation、attribute、baseline、output mapping | per-task native context static |
| N1 constraint static | Distance/Bending/Center/Self/Bone registration owner vectors | C++ producer直接move到context |
| N2 runtime parameters | curve samples、scalar/bool/enum、team options | hot update；固定ABI |
| N3 frame input | animated pose、component/anchor/collider snapshot、dt | 每帧同步；不持有particle history |
| N4 state/scratch | particle/Center history、constraint scratch、self grid/contact/intersection | native context/interaction context自产自用 |
| R result/debug | public result buffer、显式请求的冻结debug snapshot | Python result/debug owner；只读 |

Python不得持有第二份particle history或native static派生树。跨边界大数组只允许：Blender raw输入、公开result、显式debug readback。Frame orientation、Bone pose rotation、Center、Final Proxy、Baseline和constraint static的派生/消费都在C++完成。

## Static fingerprint与变化重建

Native context持有四位dirty mask：

```text
topology = 1
geometry = 2
surface  = 4
config   = 8
```

| 变化 | Mesh | Bone | 处理 |
|---|---|---|---|
| topology | 邻接、primitive、identity全失效 | 骨名/父级/连接/identity全失效 | staged全量重建 |
| geometry | rest/orientation及全部constraint输入失效 | head/tail/rest matrix及registration失效 | staged全量重建 |
| surface | Pin/UV进入fingerprint；Pin传播到全部相关producer | 当前恒定 | Mesh保守全量重签/重建 |
| config | 当前为gravity direction | 当前为gravity direction | context间复制不变static，只重建Center |
| frame pose | 不进入static fingerprint | 不进入static fingerprint | N3同步，不重建 |

UV-only不改变粒子数、拓扑或GN写回长度，但会改变C++按triangle corner UV构建的切线与orientation static；metadata通过Proxy signature形成完整身份链，因此仍全量重签/重建。Mesh frame producer必须把同一份final triangle-corner UV作为native static保留并用于逐帧orientation，禁止退化成每顶点单UV；否则UV seam处的动态朝向与静态基准不一致，Angle Restoration会在零重力初始姿态产生伪恢复力。未来只有在增加独立UV子指纹与native重签合同时才能缩小范围。

旧context保持只读，新staged context复制可复用static并运行受影响producer；全部成功后才替换slot。禁止把native static回读成Python spec实现复用。

## Blender边界

### Mesh双对象

Mesh动画固定使用BasePose读取对象与Source/写回对象：

```text
BasePose read object
  -> 保留Armature/Shape Key等topology-preserving基础变形
  -> 永久移除物理GN output
  -> evaluated positions/normals

Source/write object
  -> 相同final-proxy topology/identity
  -> 物理GN modifier常驻栈末端
  -> POINT object-local offset attribute
```

新Mesh source不要求用户预先执行手工刷新：第一次进入active automatic MC2 frame时隐式创建缺失的BasePose缓存，首帧即可完成static/frame构建。手工创建/刷新operator只用于显式修复或替换已分配代理，不属于正常逐帧路径。

不得用逐帧Shape Key写回、单对象modifier开关/重排或单对象双阶段读取替代。Raw snapshot读取是允许保留的host边界，因为当前depsgraph标志不能可靠区分authoring变化与求值更新；未来dirty tracker必须先提供稳定revision合同。

### Bone snapshot与写回

同task内同一Armature只遍历一次name/parent，head/tail/rest matrix使用bulk读取并按稳定bone name切片。Blender列主序矩阵在snapshot边界转换为row-major合同。

Bone Transform朝向与final proxy顶点朝向是两个不同基底。横向triangle会在final proxy阶段按真实表面重建每顶点normal/tangent，因此不能把PoseBone Transform世界旋转直接当作proxy旋转。静态注册固定保存
`vertex_to_transform = inverse(proxy_rotation) * transform_rotation`；每帧raw Bone producer必须使用
`proxy_rotation = transform_rotation * inverse(vertex_to_transform)`，Bone结果阶段再使用
`transform_rotation = proxy_rotation * vertex_to_transform`写回。Blender/Unity轴转换只允许发生在统一snapshot边界，禁止用Y/Z换轴补偿这条局部基底合同。验收必须覆盖带roll、对象级旋转和横向triangle的多链BoneCloth：从初始姿态开始，在零重力且Angle Restoration开启时连续步进不得产生StepBasic或PoseBone漂移。

结果先生成全部target pose，再按完整目标集合重算parent-local `matrix_basis` plan；同Armature多个不重叠component合并后一次写回。Solver不直接写PoseBone。

MC2源码的BoneCloth帧顺序是`RestoreTransform -> Animator更新 -> ReadTransform -> Simulation -> WriteTransform`：注册时的局部姿态在早更新恢复，动画随后可覆盖它，晚更新读取动画结果，粒子结果最后才映射并写回Transform。Blender侧不得把上帧MC2物理写回再次当作本帧动画pose，也不得在solver节点执行时倒写场景模拟早更新。MC2 Bone frame adapter私有保存逻辑source basis和按Blender规则规范化的上次输出basis；连接骨会清零Blender不接受的局部平移。当前basis仍匹配该输出时，仅在内存中用source basis重建frame input；当前basis已被本帧关键帧、driver或用户输入覆盖时直接读取当前pose。统一writeback只执行plan，不拥有或回填这份反馈状态；SpringBone不消费它。

### Bone Transform位移语义

Unity蒙皮骨是`SkinnedMeshRenderer`引用的普通`Transform`，父子关系不包含Blender式的连接约束。MC2源码先把代理粒子的world position/rotation写入TransformData，再为Move粒子计算相对父级的`localPosition`和`localRotation`，最终同时写回这两项；它不写`localScale`。因此MC2允许父子关节原点间距随Distance等约束发生有限伸缩，但这不是缩放单根骨，也不是无限制解除距离约束。

Blender Bone结果适配器固定遵守以下产品合同：

- `use_connect=True`的子骨使用`rotation_only_connected`。结果plan在进入统一writeback前显式把`matrix_basis`平移归零，子骨head继续由父骨tail决定；禁止依赖Blender写入时静默丢弃平移。
- `use_connect=False`的骨使用`position_rotation`。粒子位置映射保留在`matrix_basis`平移中，允许父子骨原点间距变化；视觉上可能出现父骨tail与子骨head分离，蒙皮连续性由权重决定。
- Solver和writeback都不得自动修改`use_connect`。自动断连会改变骨架拓扑、动画与约束含义，必须由作者在建模阶段决定。
- B-Bone只负责单根骨内部的分段弯曲/形变，不参与本合同，也不是MC2关节位移的替代实现。
- BoneCloth与BoneSpring共用该Blender Bone结果边界。每条record必须携带`motion_mode`；plan、公共Bone结果与隐式debug output必须分别给出`rotation_only_connected_count`、`position_rotation_count`和逐骨`writeback_motion_modes`，便于审计实际生效模式。

验收必须同时覆盖连接骨平移在plan阶段已归零，以及断连骨的非零粒子平移能够真实保留到`PoseBone.matrix_basis`；只验证旋转或依赖viewport观测不算完成。

## 数值顺序不变量

每个substep的核心顺序固定为：

```text
Center / inertia preparation
  -> particle prediction
  -> Tether
  -> Distance phase A
  -> Angle
  -> Triangle Bending
  -> Distance phase B / collision / self interaction
  -> fixed-point sum / post
  -> final-substep intersection history commit
```

维护时必须保持：

- float32舍入位置是语义的一部分，不能先用double合并后一次转换。
- curve固定采样16点，位置`i/15`；disabled curve全部为基础值。
- Distance velocity-reference attenuation固定`0.3`，Motion固定`0.95`。
- Bending反向triangle bucket、ordered quad role、角度/volume门槛和first-wins marker顺序稳定。
- Self primitive按Point/Edge/Triangle source顺序注册，grid/hash、candidate type、contact cache和final-substep intersection history顺序稳定。
- Fixed、Move、ZeroDistance和root/baseline传播不能由集合无序迭代改变。
- Quaternion统一使用`xyzw`跨ABI；Blender `wxyz`只在adapter边界转换。

完整公式和逐项oracle保存在测试fixture与C++唯一实现中，不在本文复制第二份可漂移伪源码。

## Collider与self collision

外部collider只来自`world.collider_snapshot`，MC2在frame adapter中按source、shape和group/mask过滤并上传连续数组。Mesh/BoneCloth支持声明域内Point/Edge语义；BoneSpring只接受Sphere并使用soft sphere limit。

Self collision分层：

1. Static producer生成Point/Edge/Triangle primitive、particle role、Fix/Ignore和baseline depth。
2. Per-context frame阶段更新primitive AABB和局部状态。
3. World interaction context合并全部参与task的primitive membership。
4. Native完成grid/hash、broadphase、EE/PT contact、四轮solve/sum。
5. 只在final substep提交跨帧intersection history。

Python不生成pair list、contact候选或partner映射。Group/mask与动态membership属于world interaction owner。

## Result与写回

| 通道 | 内容 | 消费者 |
|---|---|---|
| `gn_attribute` | Mesh final object-local offset envelope | 统一GN writeback、debug、未来export |
| `bone_transform` | 同Armature合并后的Bone batch envelope | 统一PoseBone writeback、debug |
| `mc2_stats_v0` | 稳定排序的slot/native/reset/step/collider/self计数 | 诊断和debug |

Native readback先形成私有`MC2ResultCandidateV1`。Candidate始终`ready=False`，不能进入公共result stream；只有target identity、frame/generation、topology和writeback plan全部验证后才提升为`ready=True`公共envelope。

公开发布是跨channel原子事务。Stats不能替代真实writeback ready语义。Result、stats和debug不得暴露bpy owner、manager index或native handle。

## Debug可观测性

语义层至少覆盖：

| 域 | 必须可见的真实状态 |
|---|---|
| Topology | Mesh edge/triangle、Bone纵向/横向连接、横向triangle补边、stable identities |
| Attribute | Fixed/Move/ZeroDistance、Pin；逐粒子depth、parent、root归属和异常连续性 |
| Motion | MaxDistance、Backstop方向/半径；Restoration静态父子目标与Limit父旋转级联目标必须分开 |
| Center | anchor、frame shift、teleport判定、negative-scale、world transform抵消 |
| Collision | collider shape、group/mask、Point/Edge模式；Edge模式实际消费的最终proxy段与端点插值半径 |
| Self | primitive、grid/hash、candidate、contact、intersection flags/history |
| Output | basic step、final particle/Bone输出、result identity |

Snapshot捕获来自`mc2_context_readback.cpp`和world interaction debug ABI。Renderer只能过滤/绘制冻结数据，不能根据当前节点参数、RNA或最终网格反推中间态。

Topology视图以去重后的final proxy edge为唯一常规线段来源：MeshCloth没有BoneCloth纵向/横向分类，全部final edge使用普通拓扑色；BoneCloth才按connection分类着色。triangle边若已存在于final edge中不得再次描边，只有triangle引用了final edge表中缺失的边时才用triangle色显示异常。C++ final proxy以集合合并triangle边和显式line，Distance邻接也拒绝重复target，因此viewport重叠不得解释为solver中的双重连接。

`粒子深度`是已接通并完成首轮人工视觉复验的高级中间态。`baseline_depths/root_indices/parent_indices`属于solver已有context状态，只有该模式显式请求时才通过独立native readback复制到冻结快照；关闭时不读取，也不新建常驻副本。当前renderer已用0到1色带表达Move最终生产depth，并独立编码Fixed、root边界、局部逆序/突跳、Move无可达Fixed和ZeroDistance；`max_items`只限制绘制数量，不得改变parent/root有效性判断。Mesh色带包含`4:1`的Fixed边界表面距离修正，Bone色带仍是parent-chain depth；实际非均匀减面模型已确认该修正能抑制横向等高线偏移并改善旋转带动。无Fixed时baseline保持`root=-1/depth=0`，不借用Teleport的物体原点回退。`深度粒子索引`只为指定粒子高亮完整parent路径；累计路径长度、两种原始depth分量和归一化分母的数值标注仍是后续能力。

`Center`显示组件/Anchor、frame shift与惯性量；只有显式请求`show_center`时才冻结任务帧中的Anchor身份、位置和组件连线，不要求C++生产额外数组。状态输出必须先报告World帧惯性最终位移、Local fixed-step有效惯性、对象/Anchor/平滑/World各来源贡献和移动/旋转限速结果，视口分层向量只作为第二步来源审计。World路径发布raw component delta、实际Anchor shift、smoothing shift、World inertia/限速后shift与最终合成量，最终vector必须等于三个实际层之和；Local路径使用native `step_vector/inertia_vector`，Depth粒子混合遵守`1-depth^1.5`产品合同。现有逐粒子Teleport阈值球/状态点随实验实现一并废弃；目标debug只表达一组判定基准的类型/index、旧/新姿态、距离/角度阈值、实际测量和task级None/Keep/Reset状态。snapshot仍必须在scheduler前判定完成后捕获，zero-substep帧可观察；仅显式请求时生产，renderer不能从最终位置反推。

`碰撞情况`是外碰的单一用户视图，只在当前模式与collider scope真实有效时绘制双方。Point模式用绿色半透明低模球显示实际可移动且未Ignore的粒子碰撞形状；Edge模式用橙色半透明低模胶囊显示全部有效final proxy段按两端粒子半径线性插值得到的布料碰撞形状，并只保留一根中心线；蓝色半透明实体显示本帧实际上传的Sphere/Capsule/Plane/Box collider，并保持正常深度测试以便判断真实遮挡和穿插。所有同色实体合并为单一indexed triangle batch，公共utils保留原线框API并旁路提供实体API。`max_items`默认10000，预算按final proxy连通分量公平分配并在分量内均匀抽样；预算不少于分量数时每个非连通分量至少保留一个形状，禁止再用数组前缀截断让后序分量整块消失。该视图不区分Edge来自Mesh、纵向骨链、显式横边还是triangle补边；producer来源属于拓扑审计，用户碰撞视图只表达最终什么形状与什么形状相碰。独立`粒子半径`仅用于参数审计，不表示该粒子在当前碰撞模式与scope中必然参与外碰。

`实际接触`的外碰时间层只比较连续显式捕获帧中的真实kernel记录，稳定身份为`primitive kind + primitive index + collider index`。结果视图只重建命中Point的真实粒子半径球或命中Edge的两端真实半径胶囊，并只绘制对应active collider；它不重复`碰撞情况`中的全部可参与形状。白色小点仅表示kernel接触位置，不再把粒子中心混成同色圆点；新增接触点为黄色，上一捕获帧失效为灰色。黄色箭头使用kernel实际correction并固定乘8作为显示倍率，不设置最短箭头或归一化，因此方向和接触间相对强度保持不变，但箭头长度不是1:1 world位移。冻结snapshot同时发布active/new/persistent/lost/churn计数及失效记录的上一位置/法线。首个样本只建立基线；帧不连续、generation变化、task/setup过滤变化或关闭模式必须清空历史，因此观察空档不能制造事件。该身份差分属于按需debug派生，不改变C++ solver、接触缓存或debug-off零明细生产合同。

Self contact的黄色推动箭头来自生产solver内部按需记录的`contact × side × xyz`贡献。四轮solve中每个role correction先执行与生产相同的`int32 × 1e6`量化，再除以该轮同一粒子收到的全部contact贡献数，最后按contact两侧primitive分别累计；因此记录值按vertex/side还原后等于实际写入位置的修正。renderer与外碰统一将该值固定乘8后绘制，不设置最短长度，显示比例不进入solver。该buffer只在`自碰4`或跨task`实际接触`等待捕获时分配，请求关闭立即清空。contact normal仍保留在只读snapshot供审计，但renderer不把它的方向或thickness缩放冒充推动强度。

Self时间层是冻结snapshot上的Python派生，不改变native cache。enabled contact以`contact type + 无向primitive pair`为稳定身份并比较连续捕获帧；淡红为基线/持续，橙色为新增，灰色为刚失效，disabled cache不进入active/churn。final intersection以`无向Edge + 无序Triangle`为身份；由于生产按Edge奇偶分片，它只与同奇偶相位的前两帧比较，洋红为基线/持续、亮粉为新增、暗紫为刚失效。失效记录保存上一捕获帧的primitive中心或五个particle坐标，renderer不得用当前移动后的几何伪造旧位置。两类状态分别发布active/new/persistent/lost/churn、previous frame和observation stride；帧不连续、generation、proxy/participant scope或模式变化必须重建基线。

## Python模块所有权

| 文件 | 唯一主要职责 |
|---|---|
| `__init__.py` | component/solver registry manifest；不重导出runtime API |
| `names.py` | solver/setup/channel稳定标识 |
| `capabilities.py` | 能力与更新频率声明 |
| `declaration.py` | 可查询solver公共合同、dirty keys、结果和legacy policy |
| `nodes.py` | 三种setup-specific Profile视图、Task修正输入、产品节点surface与task组装 |
| `presets.py` | 官方JSON预设到统一词汇转换；Profile/Task节点按owner和真实输入裁剪 |
| `parameters.py` | Profile/Task parameters/setup/settings/effective参数合同 |
| `specs.py` | task/source identity与task list规范化 |
| `partition_specs.py` | backend-neutral partition entry、稀疏patch、字段来源、显式/隐式合并与collector plan；当前不创建task/slot/native state |
| `domain_ir.py` | E0后端中立POD合同：static snapshot、logical domain program、热更新parameter packet、frame packet、output envelope与logical/physical index map；不读Blender/Physics World，不拥有backend资源 |
| `domain_capabilities.py` | E0资源分配前的后端schema/setup/capability/容量门禁；只读domain program，不加载或分配backend |
| `domain_compile.py` | E1单source与E2多source静态fragment到compiled domain的纯数据编译；不创建task、slot或backend |
| `shadow_pipeline.py` | E1显式影子对照与阶段计时；不解算、不写回、不拥有backend，禁止演变为shadow solver |
| `cpu_backend.py` | E3后端生命周期适配器与kernel协议；只拥有编译域的后端句柄、physical map和分区history，不接管V0 slot/Physics World |
| `frame_compile.py` | E3 frame snapshot到logical domain packet的纯编译；不读取Blender，不拥有backend/history |
| `runtime_parameters.py` | Profile + Task parameters到固定native N2 ABI采样/打包 |
| `scheduler.py` | all-task step共享的固定步长调度 |
| `solver.py` | prepare、slot同步、all-task step和result事务唯一orchestrator |
| `native.py` | 扩展路径定位、加载缓存与59个生产符号资格校验 |
| `native_context.py` | slot context/world interaction Python handle、ABI调用、按需readback与dispose |
| `frame_state.py` | frame输入合同、slot continuity计数与transition plan；不持有particle history |
| `collider_frame.py` | world collider snapshot过滤、shape规范化、previous-frame配对与连续数组 |
| `interaction_scope.py` | 自动跨物体self task membership/group-mask策略 |
| `results.py` | private candidate、public envelope、Mesh/Bone promotion和发布事务 |
| `debug.py` | 隐式请求、按需capture与冻结快照 |
| `debug_draw.py` | Blender viewport renderer与过滤器 |
| `topology.py` | Blender Mesh/Bone raw snapshot、native fingerprint和轻量topology |
| `static_data.py` | Proxy/Finalizer/Baseline显式Tier A合同、签名和oracle packer |
| `mesh_baseline.py` | Mesh baseline staged producer/metadata |
| `distance_static.py` | Distance Tier A与staged metadata |
| `bending_static.py` | Bending Tier A与staged metadata |
| `self_collision_static.py` | Self primitive Tier A与staged metadata |
| `center_state.py` | Center DTO、frame/reset/negative-scale oracle和轻量persistent合同 |
| `bone_connection.py` | MC2 source与HoTools产品横向连接topology合同 |
| `bone_rotation.py` | Bone Line/Triangle rotation Tier A oracle；不被生产solver当fallback |
| `bone_static.py` | Bone proxy/baseline/registration staged data与显式oracle |
| `setups/__init__.py` | 三setup adapter registry |
| `setups/contracts.py` | 轻量adapter DTO与稳定builder标识 |
| `setups/bone_frame_input.py` | BoneCloth/BoneSpring共享pose frame adapter |
| `setups/bone_cloth/__init__.py` | BoneCloth adapter声明 |
| `setups/bone_cloth/static_build.py` | BoneCloth/BoneSpring staged static assembly |
| `setups/bone_spring/__init__.py` | BoneSpring adapter声明和固定归一化策略 |
| `setups/mesh_cloth/__init__.py` | MeshCloth adapter声明 |
| `setups/mesh_cloth/base_pose.py` | BasePose proxy与delta modifier生命周期 |
| `setups/mesh_cloth/delta_output.py` | 共享GN delta attribute/modifier/writeback工具 |
| `setups/mesh_cloth/frame_input.py` | Mesh双对象frame snapshot |
| `setups/mesh_cloth/final_proxy.py` | Mesh raw到final proxy staged producer/metadata |
| `setups/mesh_cloth/static_build.py` | Mesh staged static assembly与registration顺序 |
| `setups/mesh_cloth/schema.py` | 无bpy持久RNA字段schema |
| `setups/mesh_cloth/properties.py` | schema到Blender PropertyGroup注册 |
| `setups/mesh_cloth/capabilities.py` | schema到component capability映射 |

生产import DAG必须保持无环、无跨模块private import、无lazy re-export桶、无测试反向依赖。单调用函数必须在`tools/audit_mc2_architecture.py`分类；新增未分类转发使门禁失败。

## C++所有权

| 文件 | 唯一主要职责 |
|---|---|
| `hotools_native.cpp` | 通用module shell；只注册PropertyCurve/SpringBone并调用`bind_mc2` |
| `mc2_bindings.cpp/.hpp` | MC2 74个nanobind注册与边界adapter |
| `mc2_api.hpp` | 58个context/interaction/fingerprint C ABI唯一声明表 |
| `mc2_context_internal.hpp` | context、step与interaction唯一纯C++ state布局 |
| `mc2_context_helpers.hpp` | context translation units真实共享的最小helper声明 |
| `mc2_context_core.cpp` | context lifecycle、inspect、fingerprint分类与共享数值编排helper |
| `mc2_context_static.cpp` | clone-config与Proxy/Baseline/Bone/constraint/Center static ABI |
| `mc2_context_frame_step.cpp` | Center/parameter/frame/collider/reset与per-context step ABI |
| `mc2_context_interaction.cpp` | world interaction create/inspect/group-step/debug/free ABI |
| `mc2_context_readback.cpp` | result与隐式debug中间态按需readback ABI |
| `mc2_fingerprint.cpp` | Mesh/Bone topology/geometry/surface static fingerprint |
| `mc2_static_build.cpp/.hpp` | Proxy/Baseline/Bone/Distance/Bending/Center/Self owner-vector producer |
| `mc2_kernels.cpp/.hpp` | particle/inertia/Tether/Distance/Angle/collision/post数值kernel |
| `mc2_self_collision.cpp` | self grid/broadphase/contact/intersection数值owner |

`mc2_context_internal.hpp`、kernels、static build和self collision不得依赖Python/nanobind。`v0`保留在公开ABI和state类型中表示schema版本，不表示legacy实现。

## Native ABI与生命周期

Python生产资格清单当前要求63个MC2符号；`mc2_bindings.cpp`注册85个入口，其中额外入口服务Tier A/raw oracle。`mc2_api.hpp`的58个context/interaction/fingerprint ABI都必须恰好一个C++定义；其中生产接口必须存在于资格清单，oracle全量readback明确排除在生产资格之外。

Context创建流程必须在设置setup/tether失败时立即free。Static upload先完整验证buffer/capsule，再move并增加revision；失败不部分修改context。Dispose/free幂等，以下路径都必须释放：

- active task移除或scope prune；
- topology/static重建成功后的旧context替换；
- staged prepare/rebuild失败；
- world generation替换、Cache Delete、runtime clear；
- addon注销。

Python host只保存opaque handle和可复用输出/debug buffer，不保存C++ state副本。Debug/inspect不暴露handle。

## 构建与性能边界

日常MC2 C++验证固定使用：

```text
_native\build.bat 311 native
```

该命令使用已有`vs2022-py311-native`构建目录，只生成`hotools_native.cp311-win_amd64.pyd`且不构建Jolt。普通调用保持增量；由于当前MSBuild不会可靠追踪项目内共享header，`build.bat`仅在`mc2_context_internal.hpp`比构建戳更新时对`hotools_native`目标执行一次`--clean-first`，随后恢复增量。Jolt是独立`EXCLUDE_FROM_ALL`目标；只有明确修改/验证Jolt时才选择对应module。

Python 3.11 + Blender 4.5是主门禁。Python 3.13 + Blender 5.1用于ABI兼容、代表资产和长帧soak补充。

稳定性能原则：

- native中间态自产自用，禁止为了沿用Python spec而回读。
- 正常帧不做无请求debug readback、逐项dict展开或完整static repack。
- config rebuild只复制不变static并重建Center。
- authoring raw snapshot保留，除非新的Blender revision合同能可靠避免漏检。
- benchmark必须分开raw snapshot/fingerprint、static cold/change、frame prepare、all-task group step、result/writeback和debug request。
- 比较必须固定Blender版本、资产、帧序列、warmup和功能配置；绝对毫秒不能跨机器当合同。

维护态热点脚本：

- `physicsWorld/test/benchmark_blender_mc2_hotspots.py`
- `physicsWorld/test/benchmark_blender_mc2_interaction_scope.py`
- `physicsWorld/test/benchmark_blender_mc2_self_radius.py`

主脚本在Blender 4.5.0 / Python 3.11.11中构造small/medium/large Mesh与Bone固定资产，分段测量raw snapshot、topology/fingerprint、static build/clone、frame prepare、all-task group step、result build/publish、writeback和debug capture。每个场景覆盖cold、hot、config、Mesh Pin surface/Bone rest geometry change及Python分配峰值，并断言所有阶段真实命中。

粗粒度ceiling只用于发现数量级回退：

| Case | cold | hot P95 | static change | debug | Python allocation peak |
|---|---:|---:|---:|---:|---:|
| small | 40ms | 12ms | 40ms | 30ms | 4MB |
| medium | 80ms | 20ms | 80ms | 50ms | 8MB |
| large | 160ms | 40ms | 160ms | 100ms | 16MB |

2026-07-17同进程连续两轮均通过。第二轮large结果：

| Domain | cold | hot mean/P95 | config | surface/geometry change | debug | allocation peak |
|---|---:|---:|---:|---:|---:|---:|
| Mesh 1600粒子 | 19.87ms | 4.79/5.26ms | 4.27ms | 19.41ms | 5.34ms | 464KB |
| Bone 384粒子 | 18.24ms | 6.40/7.04ms | 6.21ms | 19.01ms | 6.87ms | 531KB |

上述large fixture热帧热点：Mesh raw snapshot约2.47ms、frame prepare约0.83ms、group step约0.60ms；Bone frame prepare约2.07ms、result build约1.60ms、raw snapshot约1.18ms、writeback约0.73ms。这组微型维护fixture只证明对应输入规模的适配成本，不能外推为重资产的native优先级。2026-07-21代表资产捕获在1760粒子、6 substep、495 collider下测得热帧静态准备约16-18ms、native group约25-39ms；两个MeshCloth task开启一个跨task pair后native group约88-91ms。稳定事实是必须同时分解静态观察和native内部阶段，具体优化顺序、fused MeshCloth设计与并行门槛见`MC2_DEEP_OPTIMIZATION_STRATEGY.md`。数字不作为跨机器绝对目标；重新基线必须使用同一环境、fixture和脚本。

## 验收与自动审计

`tools/audit_mc2_architecture.py --check`是维护门禁，当前要求：

- 0 Python import环、private import、lazy re-export、未分类单调用函数。
- 0生产测试反向依赖、raw readback边界违规、持久State ndarray shadow。
- 0 legacy生产命中。
- 58个C ABI单一定义。
- 85注册/63生产要求符号无缺失或重复。
- 纯native owner零Python依赖。

测试分层：

| 层 | 当前基线 |
|---|---|
| Python纯MC2 | 26个脚本，覆盖参数、static、Center、scheduler、result事务与oracle |
| Python 3.11 native | `run_all.py` 26/26；MC2 context/static/raw与生命周期专项。完整particle-frame测试保留JSON中的MC2 source oracle，同时以独立常量锁定`1-depth^1.5`的Omni产品输出；Fixed仍与source一致，Move必须显式不同，禁止用更新source fixture掩盖产品差异 |
| Blender 4.5 | Mesh final-proxy `8/8`、Bone static/frame/product、负缩放、交互5项、debug、属性和生命周期。Bone产品测试要求横向triangle生成非零Bending record、static/native signature一致，并覆盖旋转Armature的零重力静置与显式topology/output debug请求；BoneSpring runtime强制Bending关闭 |
| Blender 4.5约束专项soak | runner覆盖重力三轴/衰减、Distance/Tether、Bending、Angle Restoration/Limit、Motion/Backstop、外碰/摩擦、task内与跨task self、Center，以及任务级首Fixed Teleport、interaction同帧失效与下一帧重建。Mesh 1200/1800帧与Bone 900帧场景均重复验证确定性；旧逐粒子subset schema与不可达断言已删除。真实高速collider另一侧的人工穿模复验已经通过。 |
| Blender 4.5混合输出soak | MeshCloth、BoneCloth、BoneSpring同world锁步900帧并完整重复；任务级Teleport覆盖三setup的Keep/Reset、首Fixed/对象原点、平移/旋转阈值、reset/apply计数与稳定化恢复，旧逐粒子subset阶段已删除。三context热更新；Mesh local offset与Bone connected/disconnected写回掩码；601帧Reset后验证三setup的`stabilization_time_after_reset=0.2`恢复斜率及`blend_weight=0.6`精确乘积；501至550帧把`particle_speed_limit`原位热更新为`0.05m/s`，逐帧显式readback C++ post后的`state_velocities`，三个setup均须真实达到限幅边界且不得越界，不能用混有Center位移补偿的world position差伪装内部速度；551帧恢复参数且context identity不变；完整场景重复两次并把限幅峰值写入确定性摘要。原生任务级Keep另以非零速度逐值锁定平移后速度不被清零。 |
| Blender 4.5 Center World soak | MeshCloth、BoneCloth、BoneSpring分别在完全跟随、完全保留World惯性、`0.8`平滑、`0.2m/s`移动限速及`90deg/s`输入配`30deg/s`旋转限速五个产品场景运行600帧，整套重复两次；稳定的3-substep/0-skip帧要求平移shift按跟随、限速、保留严格排序，限速后的未补偿速度精确受`0.2m/s`约束，平滑速度与shift均产生独立非零响应，旋转补偿精确为每帧`2deg`；catch-up帧保留在有限性和确定性摘要中但不冒充单字段证据。所有context的`debug_readback_count`保持0。修复后的World移动/旋转限速均可独立激活Center frame gate。 |
| Blender 4.5 Center Local soak | Mesh fixed row与BoneCloth/BoneSpring Root在组件内产生平移/旋转，四个产品场景各运行600帧并完整复跑；`local_inertia=0/1`要求native Center step的平移/旋转inertia ratio精确为`1/0`且vector/quaternion端点一致；`0.2m/s`移动限速分别验证真实超限帧精确受限和BoneCloth `0.15m/s`未超限段保持ratio 0；`30deg/s`旋转限速使用native `angular_velocity`验证。所有场景不请求debug，readback计数为0。 |
| Blender 4.5 Center Depth soak | 三setup以相同组件内Center平移动画对比`depth_inertia=0/1`，每场景600帧并完整复跑；首个完整prediction帧的逐粒子差值必须与`1-depth²`高度正相关且近根均值显著大于远端，后续约束重分配只进入有限性与整轨迹确定性摘要；两场景native `particle_inertia_count`均须非零，不用最终收敛形状伪装首阶段Depth语义。 |
| Blender 4.5 Bone角度soak | BoneCloth/BoneSpring各900帧并重复两次，逐帧粒子位置/旋转及首末帧Restoration target摘要必须一致；Spring、Distance、Bending和碰撞全部关闭，Restoration/Limit在301/601帧关闭与重开，context不重建且关闭区间solve count冻结；BoneCloth强制同时包含connected旋转写回与disconnected位移旋转写回。identity方向直接跳过投影后，零力静置最大误差分别为`4nm`与`0.581µm`，门槛为`0.1µm/1µm`；target vector逐点等于StepBasic父子向量，target position逐点等于当前parent加该向量。另以根动画和重力激励对两种setup分别执行恢复速度衰减`0/1`各600帧，首步位置一致，下一步响应与前30帧累计运动均须按低衰减更大排序，并逐帧执行BoneCloth connected/disconnected写回 |
| Blender 4.5 Bone Motion soak | BoneCloth 900帧并重复两次，逐帧粒子位置/旋转及最终Motion Base摘要必须一致；同时包含connected/disconnected写回，前半程MaxDistance、451帧同context热开Backstop，逐帧相对动画基准距离不超过`0.031m`，最终debug Motion BasePosition逐点等于动画输入 |
| Blender 4.5 Bone外碰soak | BoneCloth Edge与BoneSpring固定Point各900帧并重复两次，逐帧粒子位置/旋转及最终过滤key摘要必须一致；真实Sphere轻微压入并产生非零响应，451帧同context热更新半径/soft limit。每帧另注入source自有、mask不匹配和BoneSpring不支持的碰撞体，native与最终debug都只允许目标Sphere。BoneCloth逐帧覆盖connected/disconnected写回并以链总长约束跨度和回转范围；BoneSpring最大偏移`0.0102m`且受`collision_limit_distance`约束 |
| Blender 4.5外碰摩擦soak | MeshCloth与BoneCloth分别以低`0.0`/高`0.5`摩擦持续接触静态Plane 600帧，并由动画根沿切向匀速驱动；高摩擦的后300帧平均切向滞后必须分别比低摩擦至少增加`0.005m`/`0.02m`。BoneCloth逐帧同时验证connected/disconnected写回；BoneSpring摩擦固定`0.5`，不作为可变字段分支 |
| Blender 4.5 Bone Distance/Tether soak | BoneCloth外拉/内压各450帧并重复两次完整轨迹；阶段内在226/676帧原地热更新Distance刚度，451帧重力方向改变按config-static合同重建context。root比值实际跨过固定stretch阈值`1.03`和`1 - compression = 0.35`，逐帧检查固定粒子、纵向边有界及connected/disconnected写回 |
| Blender 4.5维护态soak | 180帧；mean/P95/max历史基线`2.7426/3.3693/3.6732ms`，2次hot update/rebuild/reset/same-frame和6次context释放；每个真实帧要求三setup各自产生新candidate且frame/generation精确，same-frame要求复用 |
| Blender 5.1补充 | 8个代表资产/7个生产脚本、180帧三setup混合soak |

维护时按风险选择分层，但native owner、binding或state变化必须同时跑Python 3.11 native和对应Blender 4.5生产链。

长时能力矩阵由`mc2/test/capability_matrix.py`作为代码级单一清单，但字段owner不等于行为覆盖。每个能力族分别声明产品要求的setup/字段/不变量，以及现有runner真正执行的帧数、setup、变化字段和断言；门禁解析runner文件与真实函数符号，并按集合差自动要求`status=gap`或`verified`。字段与专项不变量分别按`field@setup`、`invariant@setup`闭环，Mesh证据与Bone证据不得通过简单并集拼成三setup全覆盖；仅对部分setup成立的字段必须通过`field_setups`明确产品域。只有要求集合全部被实际证据覆盖时才能写`verified`，不得用runner名称、运行帧数、字段打包或`finite`字符串代替行为证据。`distance_culling_*`、`use_distance_culling`和仅有独立kernel但未接入context step的`centrifugal_acceleration`归入`source_abi_no_production_consumer_hidden`，不能占用active覆盖。

代码级九个能力族当前均为`verified`。2026-07-20人工验收给出的逐粒子Teleport高速穿模、自碰单层持续微动/疑似误报和debug无法表达真实触发等反例，均已转化为本文稳定合同并完成对应人工或自动复验。兼容重编译缓存由OmniNode通用manifest合同实现并自动验证；MC2不再维护独立验收推进文档。

Teleport单基准整task回退、自碰静置、Mesh深度、碰撞结果、参数归属、参数说明、无consumer离心力隐藏、兼容重编译缓存和结果导向debug均已闭环。后续工作属于按本文性能门禁与扩展检查表维护，不再以迁移或验收项目继续推进。

## 明确不支持与不得恢复

当前不支持：

- Bake/export时间轴与缓存合同。
- 通用力场；`wind_*`字段只是inactive兼容字段，不代表采样或native消费。
- Bone imported triangle。
- MC2 reduction/render mapping。
- 任意shear、零scale或不满足PoseBone proper transform的输入。

不得恢复：

- 已删除旧Mesh/Bone MC2节点package与旧节点别名。
- 旧full-array solve、旧context、旧BoneCloth IO和legacy构建选项。
- Python particle/static shadow、完整生产packer fallback或逐task独立solver step。
- ListObject self partner socket、第二套self thickness产品参数。
- solver inline GN/PoseBone writeback。
- debug中间态socket、无请求逐帧readback或renderer反推状态。

## 扩展检查表

修改MC2时按顺序检查：

1. 新输入属于profile、task identity、raw snapshot、native static、frame、interaction还是result/debug，owner是否唯一。
2. 是否仍是一次公开step处理全部active tasks，component是否仍由profile+task组合表达。
3. 新参数是否有明确的hot、frame、config、surface、geometry或topology更新语义。
4. static producer与consumer是否都在C++，是否避免host round-trip和第二份state。
5. Bone产品横向连接、自动self scope和单半径决策是否未被通用化逻辑抹掉。
6. self变化是否同时覆盖membership、group/mask、grid/contact/intersection history和性能。
7. debug是否仍全隐式、按请求、来自真实native中间态并可观察新增参数。
8. result是否仍先candidate后公共envelope，并通过统一writeback发布。
9. create/update/step/read/free、staged replace、publish和writeback失败是否保持回滚/幂等。
10. ABI、Python host、C++ owner、Tier A/raw fixture和Blender生产测试是否作为一个交付单元更新。
11. `311 native`是否只构建hotools_native且无Jolt；是否需要兼容门禁才额外跑313/5.1。
12. 修改共享context布局后，首次`311 native`是否触发单目标重建、第二次是否恢复增量。
13. 自动架构审计是否仍为全零违规；新增合法单调用边界是否显式分类。
14. 更新本文中的稳定事实；逐次修复和临时数字只由Git/benchmark输出保存。
