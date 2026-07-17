# MC2 实现蓝本

本文是 OmniNode `physicsWorld.mc2` domain 的稳定维护入口，说明当前已经运行的产品决策、数据流、所有权、数值边界和扩展约束。基准参考为 MagicaCloth2 2.18.1，commit `418f89ff31a45bb4b2336641ad5907a1110eabea`。

## 写作边界

- **应该写**：当前真实支持域、故意产品差异、Python/C++职责、数据所有权、更新频率、事务、debug、性能门槛和扩展检查表。
- **不应该写**：迁移阶段、逐次修复、提交顺序、临时测试流水、已经删除实现的过程复盘或某次机器上的偶然性能数字。
- **内容路由**：跨solver公共结构写`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；domain摘要写`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`；OmniNode编译/IR/cache机制写`../ARCHITECTURE.md`；历史只留Git。
- **更新原则**：代码、declaration、测试和本文冲突时，先确认真实行为并修正唯一owner，再同步本文；不能用计划替代事实。

相关文档：

- 物理世界公共架构：`PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`
- 各domain当前完成度：`PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`
- OmniNode通用架构：`../ARCHITECTURE.md`

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

产品、正确性、生命周期、洁净度、文档和热点性能门禁均已关闭，`solver_acceptance_blocker=False`。MC2当前进入维护态；未来扩展不重新打开已删除路径。

当前公开范围是restricted realtime。Bake/export、通用力场、Bone imported triangle和MC2 reduction/render mapping不属于已支持能力。

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
| `MC2 MeshCloth粒子配置` | cloth重力、惯性、约束、普通碰撞、自碰撞 | Spring/wind字段隐藏且`spring_enabled=False`；BoneSpring soft-collision limit隐藏 | `MC2ParticleProfileSpec` |
| `MC2 BoneCloth粒子配置` | 与cloth runtime一致的重力、惯性、约束、普通碰撞、自碰撞 | Spring/wind字段隐藏且`spring_enabled=False`；BoneSpring soft-collision limit隐藏 | `MC2ParticleProfileSpec` |
| `MC2 BoneSpring粒子配置` | 惯性、Teleport、半径/阻尼、角度约束、soft-collision limit | gravity、tether/distance、max-distance、backstop、普通碰撞模式/摩擦、自碰撞及未被native消费的Spring/wind字段隐藏 | `MC2ParticleProfileSpec` |

三个节点只是同一immutable profile构造器的产品视图，不创建三套solver DTO、runtime ABI或native参数结构。Task按`setup_type`继续通过唯一`make_mc2_runtime_parameters()`入口完成float32采样和源码固定值归一化。三个产品节点和task空配置默认都显式写入`spring_enabled=False`；当前native未读取`spring_power/spring_limit_distance/spring_normal_limit_ratio/spring_noise`，这些内部兼容字段在真实kernel落地前不得作为产品旋钮公开。

公开cloth节点把自碰撞表达为bool，内部稳定转换成MC2 `self_collision_mode=0/2`，不允许int滑块产生无效模式1。官方JSON预设在每个节点上按实际输入字段裁剪后应用，不能向用户报告一批本setup不存在的“缺失项”。

所有非显然的int/枚举输入必须在OmniNode `input_init.description`中写出完整数值映射；模式范围、tooltip和参数校验必须一致。碰撞group mask使用`_OmniBitMask` socket，不退回普通0..65535整数输入。

四个已验收执行节点使用正式名称`MC2 MeshCloth任务`、`MC2 BoneCloth任务`、`MC2 BoneSpring任务`和`MC2模拟步`；维护态产品节点不得继续带“（框架）”后缀。

### MeshCloth对象输入

公开MeshCloth任务使用多输入`list[bpy.types.Object]` Object socket，不使用`Any`。每个输入必须是Mesh Object，并各自产生一个只含单source的task；一个task不得包含多个Mesh，因为MeshCloth static/frame adapter以单final-proxy topology、单BasePose读对象和单写回目标为原子边界。节点输入多个Mesh时，全部task仍由同一个MC2模拟步统一推进，跨对象self collision由world-owned interaction处理。

`Object.hotools_mesh_collision.mc2_base_pose_proxy`继续指定每个source/write对象对应的只读BasePose对象；BasePose不是第二个task source，也不作为额外公开socket重复输入。

### BoneCloth横向连接

BoneCloth横向连接是HoTools产品差异，不是需要抹平的MC2兼容分支：

- 公开BoneCloth任务只接受多输入`_OmniBone`“中控骨”socket；每根中控骨的直接子骨分别成为有序链root，中控骨自身不进入模拟粒子。
- 公开BoneSpring任务只接受多输入`_OmniBone`“根骨”socket；每根root自身进入固定Line骨链，并递归收集其后代。
- 两类Bone任务都按Armature owner分组生成task；一个节点可输入多个骨架，但不同骨架绝不共享一个topology/context。
- 任务节点不得用`Any`或泛化“骨链”标签隐藏这两个不同的选择语义；显式chain字典只属于内部spec、oracle和测试边界。
- `mc2_source`保持MC2 Line连接语义。
- `hotools_product`按稳定骨名、链组和节点输入顺序生成纵向与横向连接，并生成稳定UV triangle。
- 同Armature可有多个不重叠component，结果在一次写回事务中合并。
- 组件骨名重叠明确拒绝，不能依赖后写覆盖。
- viewport debug必须显示真实纵横连接，不能要求用户从模拟结果猜拓扑。

### 跨物体self collision

产品节点只暴露self collision开关与group/mask，不暴露ListObject socket：

- 全部启用self collision的active task自动进入同一world interaction scope。
- Physics Object Scope不暴露MC2 Mesh碰撞开关；MC2 setup collector从同一对象范围隐式发现task，通用scope开关只筛选公共Object/Bone collider和其他solver domain。
- mask为零表示自动全互碰。
- mask非零时双方group/mask必须握手匹配。
- task动态增删由interaction scope逐帧同步；Python不维护partner列表或pair resolver。
- world-owned interaction context锁步处理跨owner grid、broadphase、EE/PT contact、四轮solve和跨帧intersection history。

指定对象列表会把world已知membership重复搬回节点图，并增加Python pair解析和动态图失效路径，因此不是当前产品合同。未来若要增加排除/分区表达，应扩展稳定group/scope语义，不应恢复ListObject兼容模型。

### 单一模拟步设置面

Physics World中只存在一个公开MC2模拟步，因此不暴露独立的“MC2模拟设置”节点或settings DTO socket。`time_scale`、`simulation_frequency`和`max_simulation_count_per_frame`直接属于模拟步；函数节点只有在输出被图执行需要时才规范化内部`MC2SolverSettingsSpec`。设置签名变化只更新slot settings revision和scheduler输入，不进入static fingerprint，也不重建native context。

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
- 请求只在下一次真实native advance时捕获；same-frame保留请求但不伪造快照。
- renderer只消费冻结只读快照，不读取当前RNA反推过程。
- 无请求时不得执行中间态native readback，`debug_readback_count`保持零。

## Setup与支持域

| Setup | 输入/拓扑 | 碰撞 | 输出 | 限制 |
|---|---|---|---|---|
| MeshCloth | Object多输入 -> 每个Mesh一个单source task；每个source配套BasePose双对象 | Point/Edge外部碰撞，单/跨物体self | GN object-local offset | topology-preserving动画；UV seam按triangle corner读取，不拆粒子；不兼容拓扑明确拒绝 |
| BoneCloth | Bone socket中控骨 -> 各直接子骨的HoTools product ordered chain | Point/Edge外部碰撞，单/跨物体self | Bone transform batch | 中控骨不入粒子；imported triangle拒绝；同Armature组件骨名不得重叠 |
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

Task identity覆盖setup、source/target身份和产品拓扑。Profile参数、热更新数值与scheduler设置不创建第二个task；它们通过dirty/update策略更新同一slot。

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

UV-only不改变粒子数、拓扑或GN写回长度，但会改变C++按triangle corner UV构建的切线与orientation static；metadata通过Proxy signature形成完整身份链，因此仍全量重签/重建。未来只有在增加独立UV子指纹与native重签合同时才能缩小范围。

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

不得用逐帧Shape Key写回、单对象modifier开关/重排或单对象双阶段读取替代。Raw snapshot读取是允许保留的host边界，因为当前depsgraph标志不能可靠区分authoring变化与求值更新；未来dirty tracker必须先提供稳定revision合同。

### Bone snapshot与写回

同task内同一Armature只遍历一次name/parent，head/tail/rest matrix使用bulk读取并按稳定bone name切片。Blender列主序矩阵在snapshot边界转换为row-major合同。

结果先生成全部target pose，再按完整目标集合重算parent-local `matrix_basis` plan；同Armature多个不重叠component合并后一次写回。Solver不直接写PoseBone。

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
| Topology | Mesh edge/triangle、Bone纵向/横向连接、stable identities |
| Attribute | Fixed/Move/ZeroDistance、Pin与depth |
| Motion | MaxDistance、Backstop方向/半径、limit命中 |
| Center | anchor、frame shift、teleport判定、negative-scale、world transform抵消 |
| Collision | collider shape、group/mask、contact/limit |
| Self | primitive、grid/hash、candidate、contact、intersection flags/history |
| Output | basic step、final particle/Bone输出、result identity |

Snapshot捕获来自`mc2_context_readback.cpp`和world interaction debug ABI。Renderer只能过滤/绘制冻结数据，不能根据当前节点参数、RNA或最终网格反推中间态。

## Python模块所有权

| 文件 | 唯一主要职责 |
|---|---|
| `__init__.py` | component/solver registry manifest；不重导出runtime API |
| `names.py` | solver/setup/channel稳定标识 |
| `capabilities.py` | 能力与更新频率声明 |
| `declaration.py` | 可查询solver公共合同、dirty keys、结果和legacy policy |
| `nodes.py` | 三种setup-specific profile authoring视图、产品节点surface与task组装 |
| `presets.py` | 官方JSON预设到统一profile词汇转换；节点侧按真实输入裁剪 |
| `parameters.py` | profile/setup/settings/effective参数合同 |
| `specs.py` | task/source identity与task list规范化 |
| `runtime_parameters.py` | profile到固定native N2 ABI采样/打包 |
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
| `mc2_api.hpp` | 47个context/interaction/fingerprint C ABI唯一声明表 |
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

Python生产资格清单当前要求59个MC2符号；module注册74个MC2符号，其中额外入口服务Tier A/raw oracle。`mc2_api.hpp`的47个context/interaction/fingerprint ABI都必须恰好一个C++定义并存在于生产资格清单。

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

large热帧热点：Mesh raw snapshot约2.47ms、frame prepare约0.83ms、group step约0.60ms；Bone frame prepare约2.07ms、result build约1.60ms、raw snapshot约1.18ms、writeback约0.73ms。说明当前优化优先级在Blender snapshot/frame/result适配，不在native group step。数字不作为跨机器绝对目标；重新基线必须使用同一环境、fixture和脚本。

## 验收与自动审计

`tools/audit_mc2_architecture.py --check`是维护门禁，当前要求：

- 0 Python import环、private import、lazy re-export、未分类单调用函数。
- 0生产测试反向依赖、raw readback边界违规、持久State ndarray shadow。
- 0 legacy生产命中。
- 47个C ABI单一定义。
- 74注册/59生产要求符号无缺失或重复。
- 纯native owner零Python依赖。

测试分层：

| 层 | 当前基线 |
|---|---|
| Python纯MC2 | 26个脚本，覆盖参数、static、Center、scheduler、result事务与oracle |
| Python 3.11 native | `run_all.py` 26/26；MC2 context/static/raw与生命周期专项 |
| Blender 4.5 | Mesh final-proxy `8/8`、Bone static/frame/product、负缩放、交互5项、debug、属性和生命周期 |
| Blender 4.5维护态soak | 180帧；mean/P95/max `2.7426/3.3693/3.6732ms`，2次hot update/rebuild/reset/same-frame和6次context释放 |
| Blender 5.1补充 | 8个代表资产/7个生产脚本、180帧三setup混合soak |

维护时按风险选择分层，但native owner、binding或state变化必须同时跑Python 3.11 native和对应Blender 4.5生产链。

当前没有MC2发布阻断项。

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
