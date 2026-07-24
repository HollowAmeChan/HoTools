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
- 单次公开solver step处理全部显式`MC2ProductRequestV1`，并以一次结果事务发布。
- 每个显式domain使用由setup与domain signature确定的动态slot；DomainV1一次处理域内全部partition、自碰撞和输出。
- Mesh GN object-local offset与Bone PoseBone批量写回。
- Point/Edge外部碰撞、单物体和跨物体self collision。
- Center/Inertia、Tether、Distance、Angle、Triangle Bending、Motion/Backstop和post。
- 全隐式debug请求与native真实中间态快照。
- 官方MC2粒子预设到三个setup-specific profile节点真实输入的裁剪转换。

旧节点 package、旧数组 solve、旧 BoneCloth IO、`MC2TaskSpec`、Python V0 solver/context/interaction owner、普通 aggregate 入口、V0 native ABI、5 个 context 翻译单元及其 2 个专用头文件均已删除。生产树不再保留旧 owner fallback。

能力覆盖以 `mc2/test/capability_matrix.py` 为代码级清单。`verified` 必须由实际字段变化和数值不变量支持；finite、非空 debug 或 data-path 记录不能冒充响应等价。

当前公开范围是restricted realtime。Bake/export、通用力场、Bone imported triangle和MC2 reduction/render mapping不属于已支持能力。

## 统一粒子域当前状态

E0-E5-B、P0、P1-B 和 E4/P2 已完成。当前产品事实如下：

- `MC2ProductRequestV1` 是三种 setup 的唯一公开执行输入。
- Mesh collector 将多 Object 编译为一个统一域；Bone collector 按 Armature 建域，同 Armature 多链是 partition，跨 Armature 是多个显式 request。
- `DomainV1` 独立拥有 static/program/parameter/frame SoA、particle state、Center/Anchor/Teleport history、scheduler、whole-domain external/self 和完整 mixed pass。
- 全部 request 先求解，再由一次 logical output transaction 发布 GN offset 或 Bone transform；任一 request 失败则本批不部分写回。
- 调试是请求驱动的产品快照；debug-off 不分配记录缓冲、不 readback，也不改变 pass 顺序。
- `specs.py`、`solver.py`、`native_context.py`、`interaction_scope.py` 已物理删除；产品运行图、公开节点顶层图和 debug 图均无旧 owner 可达面。

E7-CPU 已完成：capability matrix 已清除全部旧 Mesh/Bone constraint runner 引用，9 个能力族均由产品数值闸门接管；topology/setup/frame 中立合同已归入真实职责模块；62 个 `mc2_context_v0_*`、6 个 `mc2_interaction_v0_*` binding、5 个 `mc2_context_*` 翻译单元、2 个专用头文件、API/CMake/required-symbol 残留和 7 个纯旧 ABI 测试已物理删除。混合静态构建测试只保留中立 kernel oracle。

## 一句话数据流

```text
Physics World Begin
  -> 三种 setup collector 生成显式 product requests
  -> request 预检、source capture、partition static fragment
  -> compiled domain/program/parameter/frame packet
  -> DomainV1 按固定 mixed pass 求解
  -> logical outputs 与请求驱动 debug snapshot
  -> 一次多目标结果事务
  -> Physics Writeback / Commit
```

运行时内部链路：

```text
product request
  -> setup/domain identity 与动态产品 slot
  -> capture plan + compiled DomainV1 program
  -> one native DomainV1 owner
  -> logical output map
  -> GN offset / Bone transform / product debug envelope
  -> physicsWorld.writeback transaction
```

同一个模拟步处理全部 active product requests。request 可以拥有独立 domain slot，但不能产生 hidden task、逐 source world step 或普通 aggregate fallback。

## 产品决策

### 按setup裁剪的粒子配置

公开authoring不再使用一个同时显示全部字段的“MC2粒子配置”节点，而是三个setup视图：

| 节点 | 显示字段 | 隐藏/固定字段 | 统一输出 |
|---|---|---|---|
| `MC2 MeshCloth粒子配置` | cloth重力、粒子速度/阻尼/半径、结构/Motion约束、普通碰撞、自碰开关 | Task修正字段、Spring/wind与BoneSpring soft-collision limit隐藏 | `MC2ParticleProfileSpec` |
| `MC2 BoneCloth粒子配置` | 与 cloth runtime 一致的粒子材料、结构/Motion约束、普通碰撞和域内 self | Task 修正字段、Mesh 专用跨 Object authoring、Spring/wind 与 BoneSpring soft-collision limit 隐藏 | `MC2ParticleProfileSpec` |
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

`Reset`把触发 partition 的粒子状态、rotation、velocity reference、StepBasic/动态历史、速度、摩擦和接触历史对齐本帧动画基准；`Keep`按判定基准姿态 delta 搬运该 partition 的 state、velocity reference、StepBasic、Motion base 和 rotation，并只旋转已有真实物理速度。两种模式都重定基 old dynamic/component 与 collider previous pose，避免第一 substep 沿传送路径重复插值；相关 external/self 历史失效后由 whole-domain pass 重建。判定发生在 scheduler 之前，zero-substep frame 也必须提交新的 task-reference 状态。

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

BoneCloth横向连接是 final proxy topology 的额外 producer：显式横边进入 Distance，横跨骨链的 triangle 进入 Bending；两者最终并入 `proxy.edges/triangles`，因此 Edge 外碰与 whole-domain self 会注册相应 Edge/Triangle primitive。Point 外碰只消费粒子位置/半径。每个中控骨只在自己的 partition 内生成横向 topology，不与其他 partition 自动生成结构约束。

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
| `自碰撞` | 启用 partition primitive 的 FullMesh EE/PT 接触、grid broadphase 和 intersection history | bool 稳定转换为 `self_collision_mode=2`；`M/C` 有效，`S` 强制关闭。 |
| `跨物体自碰撞` | 允许同一 MeshCloth domain 的不同 Object partition 互碰 | Mesh collector 将开关编译为 whole-domain filter；BoneCloth 不公开 Mesh 专用跨 Object authoring，但同 Armature 多 partition 仍由域内 self 合同处理。 |
| `自碰交互质量` | 改变 self primitive 的相对修正权重 | `cloth_mass` 在 primitive 构建时进入 inverse-mass；`M/C` 的同/跨 partition contact 使用同一权重规则。 |

MeshCloth与BoneCloth产品只公开一个半径模型：`particle_radius = profile.radius(depth) * object_radius_weight`，self thickness统一由profile radius按`0.25`派生。对象顶点组仍只调制实际particle radius，不另外创造self厚度输入；BoneSpring强制关闭自碰并拒绝派生模型。独立`self_collision_thickness`仍只属于source oracle，不得重新暴露第二套用户半径。

人工验收曾发现：无拓扑交叉、无非流形的单层Mesh中，红色self contact大量聚集并伴随持续微动。完成一环过滤与final intersection debug纠正后，实际模型中的洋红几何穿插完全消失；红色contact只剩在代理本身真实拥挤的区域，布料和接触区域均完全收敛且不再运动。该结果确认一环误碰是原扰动的主要根因，并完成D-04人工验收。红箭头表示有效接触法线，不等于非零持续修正；同一world-space曲面的密度分档、contact churn和RMS速度继续作为未来自动回归，不再作为当前发布阻断。

Whole-domain self 的拓扑排除以各 partition 的 final proxy edges 为事实源。static compile 一次性生成排序去重的一环邻接键；EE/PT candidate 和 Edge-Triangle intersection 拒绝共享 particle 或任一端点一环相邻的同 partition primitive。不同 partition 不共享结构邻接，只由 owner/group/mask 过滤。不得在没有新反例和局部厚度/边长证据时扩大固定 k-ring。

独立Edge-Triangle穿插检测按`frame % 2`在grid排序后索引为奇数/偶数的Edge之间跨帧时间分片，以降低每帧窄相成本；普通EE/PT厚度contact仍每个真实step执行。`self_intersect_records`在非final阶段保存当前分片经过grid/AABB与邻接过滤的broadphase record，final线段-三角形测试后原地剔除未命中项，并设置particle intersect flags；debug专用readback只允许读取final结果，所以洋红现只表示确认穿插。新帧候选生成开始时必须撤销上一帧final-ready，本帧final完成后才重新发布；内部历史flags可保留，但不能授权debug读新候选。真实命中仍会按分片隔帧显示，这种规律切换不得解释为浮点随机或普通contact停止；稳定两帧观察只能作为明确标注的renderer窗口。

#### 实际 step 的消费顺序

```text
Profile/Task authoring
  -> setup 归一化与 parameter SoA
  -> request collect / source capture / domain compile
  -> task reference + Center/Anchor/Teleport frame transaction
  -> StepBasic
  -> 每 substep:
       Center evaluator -> prediction
       -> Tether -> Distance A -> Angle -> Bending
       -> Point/Edge external -> Distance B -> Motion
       -> whole-domain self -> post/history
  -> logical output -> 多目标结果事务
```

Frame shift 每个 frame 只消费一次，其余 pass 按真实 substep 完整执行。Spring/wind 字段目前只为源码结构和预设解析兼容；三个产品节点都写入 `spring_enabled=False`，native 没有生产 consumer。BoneSpring 的响应来自固定 Distance、Angle、惯性和 soft-sphere 组合，不等于启用 `spring_*` 字段。

### Setup collector 与分域

- MeshCloth 多 Object 输入先形成有序 partition entries，再由一个 Require-Fusion product request 编译为统一域；每个 source 保留自己的 BasePose、Center/Anchor/Teleport 和 output target。
- BoneCloth/BoneSpring 按 Armature 建域；同 Armature 多链是显式 partition，跨 Armature 产生多个显式 request。同 Armature Bone 输出在结果层合并。
- 结构约束只在 partition 内生成；跨 partition 交互只来自 whole-domain self，并由双方 group/mask、topology neighbor 与 owner 规则过滤。
- BoneSpring 强制关闭 self、Bending、gravity 和 Motion/Backstop，外碰只接受 Sphere；这些是产品限制，不是待补 pass。
- collector 不允许静默拆 hidden task，也不允许不兼容时回退为普通 aggregate。

### 请求驱动 debug

Debug 是产品 owner 的一次观察事务：节点登记模式与 setup/domain 过滤，下一真实 frame/substep 由 production pass 旁路记录，被请求数据冻结为只读 snapshot，捕获后立即释放 native 临时缓冲。暂停或零 substep 不伪造新记录；same-frame 不重复推进。

- topology/attributes/output 来自 compiled program 与 logical output。
- Center/Teleport 来自 frame transaction 的逐 partition 真实输入和贡献。
- StepBasic、gravity、velocity、Distance/Tether/Bending/Angle/Motion 来自对应 production pass 的真实 target/rest/current/correction/partition 记录。
- external 与 whole-domain self 来自同一 collider/primitive/grid/candidate/contact/solve owner，Python 不重建候选或修正。
- debug-off 不分配记录、不 readback、不安装绘制 handler，也不改变 pass 顺序。

Renderer 只能筛选和绘制冻结 snapshot，不能读取当前 RNA、最终网格或另一模式的数据来反推中间态。每个模式有独立 request bit；只允许生命周期完全相同的数据共用 readback。
## Setup 与支持域

| Setup | 分域与拓扑 | 碰撞 | 输出 | 固定限制 |
|---|---|---|---|---|
| MeshCloth | 一个 request 内多 Mesh partition；每个 source 有 BasePose 与 output map | Point/Edge external；同/跨 partition whole-domain self | GN object-local offset batch | topology-preserving 动画；UV seam 按 triangle corner；不兼容输入明确拒绝 |
| BoneCloth | 一个 Armature domain 内多骨链 partition；Line/Seq/SeqLoop 与可选横向 triangle | Point/Edge external；域内 whole-domain self | Bone transform batch | 中控骨不入粒子；不同中控骨不自动横连；imported triangle 拒绝 |
| BoneSpring | 一个 Armature domain 内 Line 骨链 partition | Sphere-only soft collision；self 关闭 | Bone transform batch | gravity/Bending/Motion/self 关闭，Distance 固定 stiffness |

Bone imported triangle 当前拒绝，因为没有成立的 UV/tangent/basis producer。Center 支持无 shear、非零 scale；PoseBone object-space 必须 proper、shear-free 且正 scale。

## 身份、slot 与单步事务

```text
solver_id: mc2
request identity: setup_type + domain_signature
slot identity: dynamic product slot id
partition identity: stable source/Armature-chain id
output: logical target map -> gn_attribute / bone_transform
```

Profile 数值、同布局参数热更新与 scheduler 值不改变 request/domain identity；source 增删、重排或 topology 变化通过 staged replacement 建立新 program。

一次 step 固定为：

1. 规范化、去重并验证全部显式 product requests。
2. 对每个 request 完成 source observation、capture、fragment、compile 与 frame/collider prepare。
3. 全部 request prepare 成功后 stage owner/slot；任一失败不裁剪旧 live 集合。
4. 按 request 执行 DomainV1；每个 owner 内按 partition 使用独立 Center/Anchor/Teleport 与参数 SoA。
5. 全部 output/feedback/writeback plan 验证成功后一次发布结果事务。
6. 任一 request 或 target 失败时，本批 owner/result/feedback/PoseBone/GN 写回均不部分提交；同帧重试从批前状态开始。
7. 成功后 prune 本帧未再出现的产品 slot，并幂等 dispose。

## 数据层与所有权

| 层 | 内容 | Owner 与生命周期 |
|---|---|---|
| identity/authoring | setup、domain、partition、source/target、profile、curve、Bone hierarchy | immutable Python request/plan |
| raw snapshot | Mesh positions/normals/loop UV/Pin，Bone rest/pose，component/Anchor pose | Mesh observation cache 或短生命周期 Bone adapter |
| compiled static | logical identity、topology、constraint/primitive tables、parameter layout、output map | frozen fragment/program |
| frame packet | animated pose、component/Anchor/collider、dt、task reference | 每 frame immutable packet |
| native state | particle、Center/Teleport/scheduler history、constraint/self scratch | DomainV1 owner |
| result/debug | logical output、事务 command、请求式冻结 snapshot | 产品 result/debug owner，只读 |

Python 不持有第二份 particle history 或 native static 派生树。跨边界大数组只允许 raw input、compiled upload、公开 output 和显式 debug readback。
## Static fingerprint与变化重建

Domain static observation 使用四位 dirty mask：

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
| config | 当前为gravity direction | 当前为gravity direction | 复用不变 static，只重建 Center 配置 |
| frame pose | 不进入static fingerprint | 不进入static fingerprint | N3同步，不重建 |

UV-only不改变粒子数、拓扑或GN写回长度，但会改变C++按triangle corner UV构建的切线与orientation static；metadata通过Proxy signature形成完整身份链，因此仍全量重签/重建。Mesh frame producer必须把同一份final triangle-corner UV作为native static保留并用于逐帧orientation，禁止退化成每顶点单UV；否则UV seam处的动态朝向与静态基准不一致，Angle Restoration会在零重力初始姿态产生伪恢复力。未来只有在增加独立UV子指纹与native重签合同时才能缩小范围。

旧 Domain owner 在 stage 期间保持只读；新 program/owner 复用可证明不变的 static 并运行受影响 producer，全部成功后才替换 slot。禁止把 native static 回读成 Python spec 实现复用。

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

不得用逐帧Shape Key写回、单对象modifier开关/重排或单对象双阶段读取替代。Mesh source observation由MC2拥有，token包含原始source/data identity、MC2 depsgraph revision、相关RNA轻量签名和world generation；普通热帧复用只读snapshot/fingerprint。观察器不得调用`mesh.update()`，update由真实写入owner提交。GN offset写回通过通用成功receipt在下一安全depsgraph批次排除自身更新；同批authoring歧义由默认低频或显式强制全扫审计检测。Bone在Armature/Pose revision矩阵成立前继续保守全扫。

### Bone snapshot与写回

同一 Armature domain 每帧只遍历一次 name/parent，head/tail/rest matrix 使用 bulk 读取并按稳定 bone name 切片。Blender 列主序矩阵在 snapshot 边界转换为 row-major 合同。

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
  -> Point/Edge external collision
  -> Distance phase B
  -> Motion
  -> whole-domain self fixed-point solve
  -> post/history
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

## Collider 与 whole-domain self

Physics World 每 frame 为一个 request 捕获一份 collider POD。collector 一次排除域内 owner，保留 collider stable id、shape、current/previous pose、group/mask 和 material；partition 的 collision mode、group/mask、radius/friction 由 DomainV1 参数 SoA 消费。非法 shape/mode 或数组长度在 native mutation 前拒绝。

Whole-domain self 在同一 owner 内一次更新 primitive、grid、candidate、contact、四轮 solve 和 intersection history。同 partition 与跨 partition 使用同一算法；结构一环邻接只过滤真实 topology 邻居，跨 partition 只由 owner/group/mask 决定。BoneSpring 不注册 self primitive。

## Result 与写回

DomainV1 只发布 logical output，不写 Blender。`domain_output.py` 按 output map 生成有序 immutable commands：Mesh 转 object-local offset，Bone 生成 connected/disconnected 运动计划。同 Armature Bone commands 在结果层合并。

Physics World writeback 先验证全部 target identity、topology、data pointer 和 command 数量，再快照、提交；任一点失败按逆序恢复并且不发布 receipt。结果事务、slot generation、frame identity 和 debug snapshot 必须一致，旧 topology 的 output map 一律拒绝。

## Debug 可观测性

产品 snapshot 的最小身份是 `schema/domain/slot/frame/generation/request/partition`。所有 ndarray 冻结只读；capture 后 native request bit 与临时容量清零。普通帧的 debug readback 计数必须保持零。

Constraint、external 和 self 的 correction 记录必须按 production 相同的共享粒子平均/定点量化规则求和回真实 pass 位移。Python 只派生 near/active/status 与绘制预算；任何无法按记录还原 production 修正的模式只能标为 data-path，不得宣称数值等价。
## Python 模块所有权

| 层 | 唯一职责 |
|---|---|
| authoring | `nodes.py`、`parameters.py`、`runtime_parameters.py` 定义公开字段、immutable 参数和 setup 有效值/固定值/禁用值。 |
| collect/capture | `product_authoring.py`、`product_collect.py`、setup capture/static adapter 生成显式 request、partition snapshot 和 frozen fragment。 |
| compile | `domain_ir.py`、`domain_collect.py`、`domain_compile.py` 拥有 logical identity、parameter SoA、constraint/primitive relocation 和 output map。 |
| execute | `product_slot.py`、`product_frame.py`、`cpu_backend.py`、`cpu_native_kernel.py` 管理 DomainV1 lifecycle、frame packet、scheduler 和 staged state。 |
| result/writeback | `domain_output.py`、`results.py` 和 Physics World 公共 writeback 生成 logical output 并原子发布 GN/Bone 结果。 |
| debug | 产品 debug request/snapshot/renderer 只观察显式请求的冻结状态，不拥有第二套求解公式。 |

旧 `specs.py`、`solver.py`、`native_context.py` 和 `interaction_scope.py` 已删除。topology、static build、frame capture 和参数合同由表中真实职责模块直接拥有；架构审计必须阻止这些文件或同名 owner 被重新引入。

## C++ 与 native ABI 所有权

- `mc2_domain_cpu.*` 拥有 DomainV1 lifecycle、persistent state、frame/parameter update、完整 mixed pass 和 output/readback。
- `mc2_kernels.*`、`mc2_static_build.*`、`mc2_self_collision.*` 等中立单元只处理插件自有 POD/SoA，不访问 Python、Blender 或旧 context 类型。
- `mc2_domain_cpu_bindings.cpp` 只负责 nanobind 验证、buffer view、错误翻译和显式 readback；pure native step 不持有 `PyObject*`。
- 旧 `mc2_context_*` 翻译单元、专用头文件及其 68 个 binding 已删除；架构审计把旧 binding、TU 和头文件零残留作为硬门禁。
- Python host 只持有 opaque handle、编译合同和可复用 output/debug buffer，不保存第二份 C++ state。

当前架构审计基线为：4 个中立 C++ PyObject API 定义无所有权违规；101 个注册 binding、21 个加载器必需 MC2 symbol 无缺失；产品/公开节点/debug 到旧模块的可达性为零；native 旧面为 0 binding / 0 翻译单元 / 0 专用头文件。运行时 py313 产物导出 71 个 `mc2_*` symbol，旧 context/interaction symbol 为零。减少的一项是没有任何消费者的 `mc2_build_bone_registration_rotations_v0` 复合导出；数字变化必须由明确产品 ABI 变更解释。

## 当前 E7-CPU 状态

统一产品域与 E7-CPU 旧面删除已经成立，当前任务进入 E7-S 结构复核。代码级能力矩阵共有 9 个能力族，全部 `verified`；全部证据已清除旧 Mesh/Bone constraint runner 引用。

已关闭的删除资格：

- Mesh Distance/Tether 已验证固定 stretch/velocity attenuation 参数、rest/range、拉伸/压缩分支和刚度响应变化。
- Mesh self 已验证跨 partition scope、candidate/contact/cache 上界和单一半径模型一致性。
- Mesh Bending、Angle Limit、collider scope 和 friction 已由 Blender 5.2 产品 runner 提供确定性数值证据，不再依赖旧 runner。
- BoneCloth 的 dihedral/signed-volume 与 BoneSpring 的 Bending/self/Motion/gravity 固定或关闭输入隔离均已由独立产品 runner 签字；Bone 包装计划的数值前置项已经关闭。

## E7-CPU 删除顺序

1. 产品数值门禁与全部旧 constraint runner 迁移已经签字关闭，不再重复实施。
2. 中立 topology/setup/frame 合同迁移与 Python V0 oracle、solver/context/interaction owner、hidden task、普通 aggregate 入口和纯旧 runner 删除已经完成。
3. 68 个 V0 binding、5 个 `mc2_context_*` 翻译单元、2 个专用头文件、`mc2_api.hpp` 声明、CMake/object dependency、required-symbol 和直接 V0 native tests 已删除；4 个中立 frame/static API 与产品 DomainV1 ABI 保留。
4. py313 native 已 clean rebuild；架构审计、全部保留 raw ABI smoke、55 项 Python 产品/能力测试以及 Blender 5.2 property registry、source observation、product debug、BoneCloth/BoneSpring 产品集成均通过，验收明确加载当前工作树产物。
5. 执行 E7-S，再收口 P6；最后恢复 4.5/py311 做双 ABI 与 Blender 收尾。

逻辑批次必须覆盖完整所有权面，同时包含代码、测试、审计和唯一蓝本更新；不再按单 runner 或单个断言提交。

## E7-S 复核清单

- 一次 request 对应一个 DomainV1 owner、一个 frame transaction 和一个 logical output envelope。
- 六个顶层 setup 产品钩子已经按 owner/lifecycle 归位为四个 setup 模块，Python 生产模块由 72 个变为 70 个；文件数量不是 KPI，符合 Physics World 原子化标准的依赖根、合同、独立阶段和 owner 保持独立。
- 后续依赖审计已删除无调用方的 Mesh 旧 `static_build.py` owner 和两个 task frame adapter，并把只有 Tier A 测试消费的 Bone rotation reference 移出生产根；当前生产模块为 68 个。
- forwarder 分类门禁同时拒绝未分类入口和已经失效的历史豁免；当前 77 项与生产 AST 双向一致，未分类和过期豁免均为 0。
- 68 个生产模块已按 Physics World 原子职责完整归入 9 类：package shell 5、identity/capability 8、immutable contract 7、compile stage 17、runtime owner 6、solver execution 5、native bridge 2、Blender/product boundary 14、observation 4；缺失、残留、重复归类和既定 merge source 均为 0。后续新合并点仍按证据独立处理，不把该清单当作冻结文件布局。
- Bone Line/Triangle 纯 Python rotation 算法现在明确属于 `mc2/test/bone_rotation_reference.py` 的 Unity Tier A oracle；能力门禁禁止同名生产模块回流，正式产品继续只走 native DomainV1 post/writeback。
- 零入站生产模块只允许 package manifest 及其字符串装载的 declaration、nodes、Blender properties 四个外部入口；当前未解释与过期豁免均为 0。
- manifest 的八个真实外部入口可达全部 68 个生产模块；不可达模块和失效根均为 0，互相引用的死子图不能再留在生产树。
- solver declaration 已删除 `legacy_policy`，backend 描述只保留当前唯一 collector/DomainV1 事实；下划线连接的旧迁移词与 native E3 旧注释已纳入精确禁词。
- E3 reference 已删除 `data_path_only`、七个 scheduler slice selector 与伪造 readiness inspect 字段；base step 和七个显式 pass 现在各有唯一入口。产品 compiled pipeline 未改，Blender 5.2 mixed-output 900 帧 digest 不变。
- 固定多 pass 前缀入口已从 `step_reference_slices` 正名为 `step_reference_pass_prefix`；生产 Python 不再使用 slice/data-path 描述当前执行职责。
- 旧 `capture_requested_mc2_debug`、`mc2_interaction_v0` resource key 及 renderer 兼容分支已删除；产品调试只读 fused product snapshot。
- 旧 result candidate、单目标 Mesh/Bone result、stats aggregate/schema 与 MC2 自有 stats channel 已删除；产品事务只发布 GN 与 Bone shared results。
- 四个约束 static builder 与 Bone 产品静态装配器已经收敛为只返回完整后端中立 spec；对应 staged metadata、compact 转换和可选 `native_context` 参数已删除。剩余 Mesh proxy/baseline 与 Bone native-owned 壳继续单独审计。
- 后续审计已确认剩余 native-owned proxy/finalizer/baseline/Bone DTO 仅服务旧 context 注册并完成删除；生产 Python 树不再包含 `native_context`、`native_owner_kind`、registration capsule 或 compact 转换，native 中立派生 API 与完整 static spec 合同继续保留。
- 后续 E7-S 若发现新的合并点，必须先证明 owner、生命周期与依赖方向一致，再同步更新架构审计；禁止用转发 shim 保留阶段文件或旧 import 路径。
- E7-S 采用循环小批次而非一次性目录重排：每批先审计职责和调用图，再完成保留/合并/删除、门禁更新、产品验收与独立提交。允许中途继续发现可合并职责，但不得合并符合 Physics World solver 原子化标准的独立合同、阶段、owner 或边界模块。
- forwarder 豁免只保留当前真实存在且符合原子职责的薄访问器；旧模块、旧 adapter、旧 metadata 方法或已具备实际逻辑的函数必须从豁免中移除，防止历史白名单遮蔽后续 E7-S 新债务。
- Bone frame 反馈状态与 hotspot timing profile 是当前 Physics World 内存资源，不是持久 schema；资源键已无兼容分支地改为职责名 `mc2.bone.frame_state` 与 `mc2.hotspot_timing.profile`，旧 `v0` 键由架构门禁禁止回流。
- `mc2_bone_writeback_plan_v0` 是当前唯一且仍被公共 `bone_transform_batch.plan_schema` 消费的版本化结果合同，不存在双 schema 翻译，因此保留；Bone frame 失败回滚已封装回 setup owner，产品 solver 不直接操作其资源键。
- 生产代码的 `V0/_v0` 机器审计只豁免 `mc2_center_static_v0` 内容签名与 `mc2_bone_writeback_plan_v0` 结果 schema；CPU/reference/Center/product 中的迁移期叙述已清除，新出现的非合同 `V0` 命名直接阻断架构门禁。
- 精确迁移词 `legacy/fallback/shadow/compat/compatibility` 在生产树中为 0；preset 的缺省参数已按真实语义命名为 `default`。backend capability 的 `CompatibilityReport/compatible` 是能力判定类型和字段，不是迁移兼容分支。
- Mesh domain draft 类型别名、draft/collider 两个 setup 名称 wrapper 与产品 solver 私有 slot-id wrapper 已删除；collector、collider capture 与 slot identity 直接使用统一合同，生产模块仍为 69 个，已分类 forwarder 由 84 降为 81。
- 仅供测试使用的单 fragment compiler wrapper 也已删除；fixture 显式使用单元素 fragment/effective 集合，分类 forwarder 进一步降为 80。
- 无生产消费者的 final-proxy 三角覆盖派生属性与 setup registry 复制函数已删除；原始 records、registry 和按类型 getter 保持权威，分类 forwarder 降为 78。
- Mesh 专用 owner/result/slot-kind Python 纯别名已删除，测试直接使用统一产品类型；持久 slot ID、slot kind 字符串和 schema identity 不在同一批次改名。
- 仅由旧测试消费的四个 Mesh fused 默认 slot wrapper/alias 已删除；slot sync、frame publish、substep 与 capture 只保留要求显式 slot identity 的统一产品入口。Mesh output batch/transaction 仍有产品消费者，后续只改为准确的 `mesh_product` 命名，不改变行为。
- Mesh output batch/transaction 已改为 `mesh_product` 命名，Python slot 常量为 `MC2_MESH_PRODUCT_SLOT_ID`；底层 `mc2.domain.mesh.product.v1` identity、事务和数值行为保持不变。
- 当前运行参数产品值对象统一命名为 `MC2RuntimeParameters`，旧 `MC2RuntimeParametersV0` 不保留别名；packed ABI 版本仍为 0，字段布局和 parameter signature 不变。
- compiled-domain 只保留 `fragments` 与 `effective_parameter_signatures` 集合；E1 单 partition 的 `fragment`/`effective_parameter_signature` compatibility/shadow 视图及其中间属性已删除。
- 12 个 static/frame 中立 native helper 已去除 `_v0/_v1` 后缀并随 py313 pyd 重编译；旧 binding 名由架构门禁禁止，正式 DomainV1 ABI 的 `v1` 标识保持不变。
- 三份 Bone 兼容 runner 已物理删除，验收资产直接指向真实 Bone 产品、BoneSpring restrictions 与 Bone constraint runner；旧文件名只允许出现在禁止回流断言中。
- Mesh final-proxy/BasePose 两份兼容 runner 和串行转发 mixed-output/Center 的混合门面也已删除，验收资产直接指向真实 Mesh、mixed-output 与 Center 产品 runner；6 个旧 runner 统一由不存在性门禁禁止回流。
- 删除 fallback、shadow、普通 aggregate、双 schema/result 翻译和已无调用方的 overload/forwarder。
- compatibility 只保留有资产格式、公开 ABI 或跨版本持久化依据的边界，并按真实职责命名。
- debug 只按请求读取 production snapshot；不能恢复逐帧 readback或从最终结果反推中间态。
- 失败、重入、空请求、拓扑失效、slot prune 和 multi-target writeback 保持原子与幂等。
- 简化前后复跑架构、DomainV1、产品 Blender 与同工作量性能门禁；差异必须可解释。

## P6 合同边界

P6 只冻结未来 backend 可直接消费的合同，不创建 GPU runtime：

- Data：稳定 domain/partition/source/logical particle identity，拓扑/参数/primitive SoA，版本、容量和溢出规则。
- Compile：capture -> static fragment -> domain compile -> backend allocation；静态数据只在失效范围上传。
- Frame：task reference/Center/Anchor/Teleport -> frame packet -> StepBasic，frame shift 每帧只消费一次。
- Substep：Center evaluator -> prediction -> Tether -> Distance A -> Angle -> Bending -> external Point/Edge -> Distance B -> Motion -> whole-domain self -> post/history。
- IO：一个 request 对应一个 domain output；多个 target 由一次结果事务发布，失败整批回滚。
- Debug/measurement：请求式旁路记录与 production 求和等价，但不成为常驻 staging 或 backend ABI。

P6 不改变 CPU pass 顺序、调度或内存所有权，不实施 P4 CPU 并发，也不能用未来 GPU 解释 CPU 回归。E6 只有在 E7-S、P6、最终双 ABI 和规模基准稳定后才可独立开工。

## 构建与验收边界

- 常规开发、native 编译和 Blender 验收只使用 Python 3.13 / Blender 5.2。
- Blender 5.2 必须清除默认 HoTools 备份模块，并确认加载当前工作树 `_Lib/py313`。
- 4.5/py311 在旧面删除和 E7-S 基本完成前冻结；不得启动、编译或触碰用户的 4.5 进程。
- 纯 Python 覆盖 schema、compile、DomainV1、transaction 和 capability matrix；Blender 5.2 覆盖三 setup、多 source、多 target、debug、长程确定性与失败回滚。
- architecture audit 必须保持依赖环、私有边界、生产测试反向依赖、raw readback、persistent ndarray、产品旧模块可达性和 binding contract 全部无未解释违规。
- benchmark 只使用产品 DomainV1，固定资产、warmup、substep、collider 和工作量计数，分开 capture/pack/solve/readback/output/publish；绝对毫秒不作为跨机器合同。

## 明确不支持与不得恢复

当前不支持 Bake/export 时间轴、通用力场、Bone imported triangle、MC2 reduction/render mapping、shear/零 scale 或不满足 PoseBone proper transform 的输入。

不得恢复旧节点别名、full-array solve、逐 source world step、hidden task、普通 aggregate fallback、solver 内联 GN/PoseBone writeback、无请求 debug readback、Python shadow solver、第二套 self thickness 或未被 native 消费的公开字段。

## 文档维护

本文只记录稳定产品合同、当前缺口和删除/扩展门槛。节点与统一域设计写入 `MC2_NODE_SIMULATION_DESIGN.md`，性能与 P6/E6 策略写入 `MC2_DEEP_OPTIMIZATION_STRATEGY.md`，Physics World 摘要写入 `PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`。单次提交、runner、临时性能数字和调试过程只留在 Git、测试或 benchmark 输出。
