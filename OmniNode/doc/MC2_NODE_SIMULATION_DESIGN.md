# MC2 节点模拟设计

本文定义 MC2 当前节点装配、authoring 分层、统一粒子域、编译对象和后端边界。稳定产品能力与数值语义见 `MC2_BLUEPRINT.md`；GPU 实施见 `MC2_GPU_BACKEND_DESIGN.md`；历史迁移阶段只留 Git。

## 设计结论

`MC2模拟步`是 Physics World 中 MC2 唯一公开运行时 step，输入是显式 `list[MC2ProductRequestV1]`。一个 request 明确表示一个 setup simulation domain；不存在 hidden task、普通 aggregate 或由模拟步猜测裸 Object 类型的路径。

```text
setup authoring
  -> 完整 partition
  -> setup collector
  -> 一个或多个显式 MC2ProductRequestV1
  -> MC2模拟步(world, requests)
  -> logical outputs
  -> Physics World 多目标事务
```

节点负责表达对象、粒子和区域参数；compiler 负责把它们编译成连续的 domain 数据；backend 只消费已冻结的 POD/SoA，不访问节点或 Blender authoring。

## MeshCloth 节点拓扑

```text
Object -> MC2 MeshCloth对象（读取面板完整属性） ─┐
                                                  ├─> MC2 MeshCloth域
Object -> MC2 MeshCloth自定义对象（socket完整属性）┘       -> Mesh分区
                                                          -> MC2 Mesh域收集
                                                          -> MC2模拟步.MC2域
```

### `MC2 MeshCloth对象`

输入一个或多个 Mesh Object，完整读取 `Object.hotools_mesh_collision`，输出 `MC2MeshObjectSpec`。spec 保留真实 Object 作为 capture/writeback owner，并冻结 BasePose、Pin、半径顶点组和统一 16 组碰撞属性。节点不创建 partition、request、slot 或 native owner。

### `MC2 MeshCloth自定义对象`

输入同样的 Mesh Object，并把同一组对象属性完整暴露为 socket。未连接字段使用 schema 默认值，但节点不读取或修改对象面板。选择该节点表示由 socket 完整定义对象属性；它不是 sparse patch，也不存在与面板的覆盖优先级。

两个对象节点输出同一种严格类型。相同 Object 与相同属性形成相同 source identity 和签名；面板来源或 socket 来源只用于诊断，不形成运行时分支。

### `MC2 MeshCloth域`

只接受包装后的 `MC2MeshObjectSpec`，拒绝裸 Object。域节点组合粒子 Profile、Anchor、Center/Teleport 等区域参数，为每个对象生成完整 `MC2PartitionEntry`。真实 Object 仍是 source；对象属性、粒子/约束参数、区域参数和碰撞策略在 partition 边界已有唯一 owner。

域节点输出 `Mesh分区`，不输出已经可执行的 domain。多个对象可以共享一个域节点，也可以由多个域节点产生分区后交给同一 collector。

### `MC2 Mesh域收集`

只接收一个或多个完整 Mesh 分区，按输入顺序校验 stable id 唯一性并生成一个 Require-Fusion `MC2ProductRequestV1`。它不接收 Physics World，不读取 `world.implicit_objects`，不提供默认 Profile/Anchor/区域参数/碰撞字段，也不拥有 backend state。

空输入、不完整分区、重复 stable id、非 MeshCloth 分区或无法融合的组合必须显式失败；collector 不拆成多个隐藏 request。

### `MC2模拟步`

接收一个或多个 collector 输出和 Physics World。时间缩放、模拟频率和每帧最大模拟次数只属于模拟步。成员关系由连线表达，节点执行由 Blender mute 表达；对象、域、collector 和模拟步不提供重复的参与类 `enabled`。

## BoneCloth 节点拓扑

`MC2 BoneCloth域` 和 `MC2 BoneSpring域` 是统一产品域的 setup adapter，不是独立 solver。它们复用 `MC2ProductRequestV1`、compiled domain、DomainV1 owner、scheduler、Center history 和公共结果事务，只保留 source capture、静态拓扑、frame input 和 Bone output 的差异。BoneCloth 采用与 MeshCloth 相同的强类型对象、完整分区和专用 collector 边界；BoneSpring 当前仍由自己的域节点直接生成 request。

```text
Bone socket / chain -> MC2 BoneCloth对象（读取控制/根 Bone 面板） ─┐
                                                                  ├─> MC2 BoneCloth域
Bone socket / chain -> MC2 BoneCloth自定义对象（socket完整属性） ───┘       -> Bone分区
                                                                          -> MC2 Bone域收集
                                                                          -> MC2模拟步.MC2域
```

### `MC2 BoneCloth对象`

输入一个或多个控制 Bone 或显式 chain descriptor。每个输入先解析为同一 Armature 内的一组有序骨链，再从所选控制/根 Bone 的 `Bone.hotools_collision` 读取完整对象属性，输出 `MC2BoneClothObjectSpec`。对象 spec 冻结主碰撞组和被碰撞组，不创建 partition、request、slot 或 native owner。

### `MC2 BoneCloth自定义对象`

输入相同的 Bone source，并从 socket 完整定义主碰撞组和被碰撞组。它不读取或修改 `Bone.hotools_collision`，不是面板属性 patch。面板对象与自定义对象输出同一种严格类型；相同 source 和属性产生相同运行时签名，属性来源只用于诊断。

### `MC2 BoneCloth域`

只接受包装后的 `MC2BoneClothObjectSpec`，拒绝裸 Bone socket、二元组或 chain dict。域节点组合粒子 Profile、Anchor、Center/Teleport 参数、连接模式、旋转插值和根旋转，为每个对象生成完整 `MC2PartitionEntry`。对象级碰撞筛选从 object spec 冻结进 partition；域节点不再拥有 `被碰撞组` socket，也不直接输出 request。

### `MC2 Bone域收集`

只接受 `MC2 BoneCloth域` 输出的完整 BoneCloth 分区。collector 拒绝空输入、raw Bone、隐式分区、未解析字段、patch、重复 stable id 和其它 setup；它不读取 Physics World，也不补 Profile、Anchor、区域参数或碰撞默认值。同一 Armature 的分区按首次出现顺序融合为一个 Require-Fusion request；不同 Armature 按首次出现顺序产生多个可见 request，不在模拟步内部隐藏拆分。

### BoneSpring

BoneSpring 当前保持直接的 setup domain：

```text
Bone socket / chain descriptor
  -> MC2 BoneSpring域
  -> MC2ProductRequestV1
  -> MC2模拟步
  -> Bone output adapter
  -> BONE_TRANSFORM_CHANNEL 原子批次
```

| setup | 一个 product domain 的来源 | 稳定限制 |
|---|---|---|
| BoneCloth | 同一 Armature component 下的一条或多条中控骨链 | 支持 Line/Seq/SeqLoop；保留横向 triangle、旋转插值、根旋转和 triangle 最终覆盖；单 request 不跨 Armature。 |
| BoneSpring | 同一 Armature component 下的一条或多条根骨链 | 只允许 Line；外碰只消费 SPHERE；保留 Line 方向和 connected/disconnected 写回；单 request 不跨 Armature。 |
| 两者共同 | Armature world pose 与逐骨 pose snapshot | RestoreTransform/ReadTransform 屏障区分动画输入和上一帧写回；负缩放、失效骨、重叠链和 owner 冲突在 backend mutation 前失败。 |

不同 Armature 按首次出现顺序生成多个显式 request。同一 Armature 内的 partition 共享一个 domain；跨 Armature 不伪装成一个 task。

## 参数所有权

MeshCloth 和 BoneCloth 都在进入域之前完成唯一解析：

```text
面板对象适配器 ─┐
                 ├─> 完整 Mesh/BoneCloth object spec
自定义对象适配器 ┘
                    + 粒子 Profile
                    + 区域参数 / Anchor
                 -> 完整 Mesh/Bone partition
                 -> 纯 collector
                 -> compiled particle / constraint arrays
```

| 层级 | 拥有内容 |
|---|---|
| domain/context | scheduler、substep、backend lifetime、统一 broadphase、generation 和结果事务。 |
| partition | source/output identity、Object/Anchor frame、Center/Teleport history、区域参数和 logical index view。 |
| Mesh object spec | BasePose、Pin/radius group、对象碰撞属性及其来源。 |
| BoneCloth object spec | 已解析的 Armature/骨链 source、主碰撞组、被碰撞组及其来源。 |
| particle | depth、radius、mass/inverse mass、damping、gravity response、friction、Motion/Backstop 系数和 partition index。 |
| constraint | 类型、端点、rest、stiffness/compliance、owner partition 和 batch/color。 |

规则：

1. 面板对象和自定义对象二选一；collector 不解释属性来源或覆盖优先级。
2. Profile 写粒子/约束系数，域节点写区域参数，对象 spec 写显式对象属性；同一字段只能有一个 authoring owner。
3. compiler 只为 kernel 实际消费的最终参数生成 runtime array；节点不复制 packed ABI。
4. Center、Anchor 和 Teleport 是 partition 级有历史状态，不是逐粒子 float。
5. 时间、substep 和统一 broadphase 是 context 级策略，不能因局部参数差异隐式拆 domain。

碰撞只公开面板已有的 16 组合同：`primary_collision_group` 是对象主组，`collided_by_groups` 是允许碰撞到该对象的组。外碰使用冻结的 `collided_by_groups`；whole-domain self 才把自身主组并入有效 mask，并继续执行共享粒子和一环拓扑过滤。

## 四层运行对象

| 层 | 核心对象 | 可以包含 | 禁止包含 |
|---|---|---|---|
| Authoring | 对象 spec、完整 partition、collector plan | Blender source 引用、用户参数、字段来源、stable id | 粒子下标、native handle、GPU buffer |
| Capture | static/frame snapshot | 主线程冻结的 POD 数组、transform、source/output token | solver state、后端资源、隐式 Python callback |
| Compile | `MC2CompiledDomain` | 后端中立 SoA、logical index、constraint、partition table、output map | `bpy`、节点、live depsgraph、native handle |
| Execute | backend domain / frame output | CPU 或 GPU 私有资源、history、当前 frame、logical output | authoring merge、Blender 读取、直接 Blender 写回 |

Capture 是 Blender IO 边界，Compile 是逻辑数值布局边界，Execute 是后端边界。三者必须可独立测试和计时。

## Product request 与编译

`MC2ProductRequestV1` 是 collector 交给模拟步的已归一化 domain intent，不是编译产物。它持有 collector plan、有序 partition 和供主线程 capture 的 source/output 引用，但不持有 dense particle array、constraint buffer、physical range、native handle 或设备资源。

编译链：

```text
MC2ProductRequestV1
  -> MC2DomainCapturePlan
  -> tuple[MC2PartitionStaticSnapshot]
  -> tuple[MC2PartitionStaticFragment]
  -> MC2CompiledDomain
  -> backend allocation
```

`partition_id` 是 authoring identity 和状态所有权，不是 physical buffer 地址。particle span 只是某次 backend compile 的布局视图。CPU 可以保持连续 partition range；GPU 可以重排、分块或压缩，只要 logical identity、debug mapping 和 output map 不变。

source 墠删、重排、拓扑或 capability 变化通过 staged replacement 创建新 program/backend owner。参数值变化只更新参数包；frame 变化只更新 frame packet。禁止在 live backend domain 上原地改变 logical numbering。

## 统一粒子域流水线

### 收集与归一化

collector 校验 setup、stable identity、完整字段、输出 owner 和 Require-Fusion。输出只描述 domain intent，不读取 Mesh/Bone 数组。

### 主线程 static capture

从 Blender 冻结 topology、local position/normal、UV、vertex group、BasePose/Anchor identity 和 source/output token。snapshot 是只读 POD；离开 capture 后不得访问 live Object。

### Partition static build

- MeshCloth：final proxy、baseline、Distance、Bending、Tether/Angle 和 self primitive；
- BoneCloth/BoneSpring：各自的 line/bone topology producer；
- 所有索引仍是 partition-local；
- fragment 不创建 backend context，不决定 physical layout。

### Domain compile

compiler 按稳定 partition 顺序：

1. 分配 logical particle identity；
2. 重定位 constraint/primitive index；
3. 编译 partition、particle 和 constraint 参数；
4. 生成 output map 和 capability/过滤表；
5. 产生 program、parameter 和 layout signature。

结构约束只引用自身 partition。跨 partition 相互作用只由 whole-domain self 的双向 policy、owner/group/mask 决定。

### Backend allocation

```text
MC2CompiledDomain
  -> CPU backend.create_domain(program)
  -> GPU backend.create_domain(program)
```

CPU 和 GPU 消费同一 logical program，但不共享 physical layout、mutable state 或 solver 实现。CPU owner 的隔离是硬合同；详细规则见 `MC2_GPU_BACKEND_DESIGN.md`。

### Frame capture 与 pack

每帧主线程冻结 source/Anchor transform、BasePose frame、Bone pose、Teleport/reset、partition 时间参数和公共 collider snapshot。纯 compiler 生成 `MC2DomainFramePacket`，backend 再 pack/upload 到私有布局。

Blender IO 次数仍可能与对象数相关，但 solver 调度、碰撞和约束只面对一个 domain。静态 buffer 不随普通 frame 重传。

### 固定求解顺序

```text
StepBasic prepare
  -> TaskReference / Teleport
  -> Center frame shift
  -> Center
  -> Center inertia
  -> Integration
  -> Tether
  -> Distance A
  -> Angle
  -> Bending
  -> external Point / Edge
  -> Distance B
  -> Motion
  -> whole-domain self
  -> post / history
```

所有 setup 的能力差异由 compiled tables 和 capability 决定，不通过第二条 pass sequence 实现。

Teleport是external collision之前完成的partition历史事务。MeshCloth以每个partition首个Fixed的animated world pose为参考，无Fixed才回退Source对象原点；骨骼驱动要成立，BasePose必须保留同一基础变形链。Keep/Reset触发帧除粒子与whole-domain self历史外，还必须让本域external Point/Edge把collider当前姿态视为old姿态，禁止公共上一帧快照产生跨瞬移扫掠。调试触发色只证明TaskReference判定，不替代最终GN/Bone写回验收。

### 输出与原子写回

backend 只产生 logical output。host 根据 output map 构造 GN object-local offset 或 Bone transform command；全部 target、element count、generation 和有限值在发布前验证。任一 request 或 target 失败时，本批结果零部分发布。

GPU 初期可以回读统一 logical buffer 后由 host 拆分；成熟实现可以在 device 生成按 target 排列的 output，但必须进入同一个 command envelope 和事务。

## 后端中立数据合同

`MC2CompiledDomain` 必须满足：

- 不含 `bpy`、Python callback、节点实例或 live depsgraph；
- dtype、shape、alignment、单位、坐标空间、读写权限和生命周期显式；
- 关系由整数表、index view 和稳定 signature 表达；
- domain/partition/particle/constraint 四级参数边界明确；
- 可以由固定 fixture 重建，不要求打开 `.blend`；
- NumPy 只是 host carrier，不是最终 ABI。

最小逻辑表：

| 表 | 关键字段 | 主要消费者 |
|---|---|---|
| partition table | stable id、setup、logical view、frame/output owner index | frame、Center/Teleport、debug |
| logical particle table | partition index、source element、flags | parameter compile、output map |
| particle static/parameter SoA | bind pose、normal、depth、mass、radius、damping、gravity、friction | solver |
| partition parameter SoA | transform policy、Center/Teleport、collision group/mask | frame、broadphase |
| constraint tables | type-specific indices、rest、stiffness、flags | constraint pass |
| collision tables | primitive indices、thickness、primitive flags | broadphase/narrowphase |
| output map | target index、source element、logical view、space | result/writeback |

## P6 机器合同

当前 backend contract schema 固定以下内容：

- program、parameter、frame/collider buffer 的 role、dtype、components、logical count、容量、生命周期和传输策略；
- 16 个有序 production pass 的依赖、reads、writes 和独立 `request_writes`；
- program、parameter、frame 和 collider 的最小连续 dirty span；
- candidate/contact/intersection 的组合硬上限和 count-grow-emit 事务；
- 最终 substep 只读回一次 logical output；
- debug buffer 只由显式 request 产生，不能成为 production state/output；
- identity、topology、filter、Pin participation、candidate/contact key/count 等 exact 项；
- 共享 fixture 的逐 pass tolerance 与全局 position/rotation/velocity cap。

该合同描述数据和行为，不分配 backend 资源，不要求 CPU 使用 GPU physical layout。GPU 的 count-scan-emit、sort、reduction、queue 和 device buffer 都属于 provider 私有实现。

## Fusion 与显式分域

Mesh collector 固定 Require-Fusion：同一个 collector 的所有完整 Mesh partition 必须形成一个 domain，失败时给出具体不兼容项，不存在 Auto/Separate 产品回退。

Bone setup 可以因 Armature owner 不同产生多个显式 request，但每个 request 和分组原因都在节点输出中可见。模拟步只调度这些显式 request，不再二次拆组。

需要拒绝的情况至少包括：

- setup type 不一致；
- scheduler/context-only 策略不兼容；
- self/filter 或 topology producer 不兼容；
- ABI/schema/capability 不兼容；
- output owner 无法唯一映射；
- partition 所需的 Center/Teleport/frame 合同不成立。

Object、Profile、Anchor、Teleport 阈值和输出目标本身由 partition/SoA 承载，不是禁止融合的理由。

## Debug 与可观察性

collector 状态解释“装配了什么”：partition 顺序、stable id、字段来源、Require-Fusion 结果、domain signature 和 output owner。它不读取 native 中间态。

MC2 debug 解释“解算发生了什么”：只在显式请求后的下一真实 step，从 production pass 旁路记录冻结 snapshot。debug-off 不分配记录、不 readback、不安装绘制 handler，也不改变 pass 顺序。

logical particle/partition identity 必须贯穿 CPU/GPU physical 重排、debug 和 writeback。renderer 只能筛选已冻结 snapshot，不能读取当前 RNA 或最终网格反推中间态。

## 文件职责

文件按 Physics World 原子职责拆分，数量不是目标：

| 类别 | 职责 |
|---|---|
| identity/capability | 稳定 id、setup registry、能力和 compatibility 判定 |
| immutable contract | request、partition、program、parameter、frame、result DTO |
| compile stage | capture、static fragment、domain compile、parameter/frame pack |
| runtime owner | slot、scheduler、backend lifecycle、history、failure rollback |
| solver execution | 固定 pass、logical output、产品批次 |
| native bridge | buffer view、ABI 验证、错误翻译、显式 readback |
| Blender/product boundary | RNA、节点、Object/Bone capture、writeback adapter |
| observation | debug request/snapshot、热点计时和架构审计 |

只有 owner、生命周期和依赖方向一致时才合并文件。零调用方不自动等于可删；独立合同、注册根、测试 oracle 或外部装载入口必须按真实职责判断。历史文件名、模块数量、forwarder 数和逐批删除记录不写入本文。

## 验收矩阵

| 边界 | 必须证明 |
|---|---|
| authoring | 面板对象与自定义对象同类型；域拒绝裸 Object；collector 不补默认值或读取 world。 |
| capture | 离开主线程后不访问 Blender；topology/attribute/owner 失效准确。 |
| compile | 多 partition logical identity、结构约束隔离、参数分级和 output map 正确。 |
| frame | 独立 transform、Center/Teleport/Anchor history、reset/rewind 和 collider scope。 |
| CPU backend | 完整固定 pass、三 setup 能力、whole-domain self、失败原子性和长期 reference。 |
| GPU backend | CPU owner 无改动；相同 logical program、工作量 exact、逐 pass tolerance、独立资源和失败回滚。 |
| result | 多 target、坐标空间、generation、topology replacement 和零部分写回。 |
| observation | debug/timing 关闭态零额外工作；开启态只观察 production 数据。 |
| 性能 | 固定工作量 P50/P95、内存、上传/readback 和规模曲线；不只报告 kernel。 |

固定 fixture 保存 POD、schema、signature 和 tolerance，不保存 Blender 指针。CPU/GPU 共用同一组 compiled-domain/frame fixture，不维护两套“正确答案”。Blender 产品验收覆盖三 setup、多 source、mixed output、失败回滚、debug、reset/rewind 和长期 soak。

## 开发环境

日常 native/GPU 开发和 Blender 验收使用 Python 3.13 / Blender 5.2，并明确排除 5.2 默认加载的 HoTools 备份，确认绑定当前工作树 `_Lib/py313`。共享合同、loader 或打包发生变化时验证 py311/py313 的 CPU-only 路径；E6 阶段出口执行完整双 ABI 收尾。GPU 支持矩阵按 provider 和设备单独记录，不借 CPU ABI 通过声称 GPU 已支持。

## 禁止恢复

- 裸 Object 直连域、域绕过 collector、collector 读取 Physics World 或 implicit registry；
- Mesh sparse patch、面板与 socket 双来源优先级、collector defaults；
- hidden task、普通 aggregate、逐 source world step 或单目标非事务写回；
- 第二套 Python solver、setup 私有 mixed pass 或从最终结果反推 debug；
- CPU/GPU 共享 mutable state，或为 GPU 重构 CPU hot loop；
- backend 在 substep 中访问 Blender、逐 substep readback 或失败后静默跨 backend 续跑。
