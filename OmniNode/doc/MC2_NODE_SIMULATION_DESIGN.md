# MC2 节点模拟设计

本文规划 MC2 新一代节点数据流和 authoring 分层。它解决的不是某一个 socket 的命名，而是明确三个边界：

1. Physics World 的公开 `solver + list[task]` 契约；
2. MC2 内部 MeshCloth、BoneCloth、BoneSpring 三种 setup adapter 的收集和装配；
3. 单个代理的 source、profile、隐式覆盖、显式覆盖、partition 状态和输出映射。

本文是目标设计，不描述当前已经完成的行为。当前生产节点和 `MC2TaskSpec` 仍以 `MC2_BLUEPRINT.md` 及代码事实为准。

## 执行目录

1. 设计结论与节点职责
2. authoring 参数合并与 identity
3. 当前运行时事实和融合阻塞点
4. 统一粒子场流水线及逐阶段 IO
5. 后端中立中间表示与 CPU/GPU 边界
6. Python/native 文件职责重排
7. 分阶段执行计划与变更门禁
8. 验收目录、固定产物与性能门槛

本文中的执行顺序是强约束。未通过上一阶段的合同和固定夹具验收，不进入下一阶段实现；尤其不能先把多个 `Object` 塞进旧 `MC2TaskSpec.sources`，再让旧的单对象静态构建、Center 和 writeback 路径猜测其含义。

## 设计结论

`MC2模拟步`仍然是 Physics World 唯一公开的运行时 step，输入是统一的 `list[MC2TaskSpec]`。但 MC2 setup 的“任务节点”需要从 source 展开函数提升为 setup-domain collector：

```text
上游细分节点
  -> MC2PartitionEntry / sparse override
  -> MC2 MeshCloth任务 collector
  -> 一个融合后的 MC2TaskSpec
  -> MC2模拟步(world, list[MC2TaskSpec])
  -> result stream
  -> Physics Writeback
```

其中：

- `MC2PartitionEntry` 表示一个代理或一条骨骼细分链，不是 solver slot，也不拥有 native context。
- Profile 节点只生成默认材料/粒子配置；覆盖节点生成稀疏 patch，不在上游复制完整 runtime ABI。
- collector 负责收集、去重、冲突检查、参数分级、fusion compatibility 和最终 task identity。
- `MC2TaskSpec` 表示一个 setup simulation domain；一个 MeshCloth collector 的正常输出是一个 fused task，而不是每个 Object 一个 task。
- `MC2模拟步`只负责统一时间、全部 active task 的调度、native step 和结果事务，不知道每个 source 如何被 authoring 收集。

## 为什么必须拆分节点职能

当前 `MC2 MeshCloth任务`同时承担了：

- 展开 Object 列表；
- 选择 MeshCloth setup；
- 绑定默认 Profile；
- 绑定 Anchor、Teleport、Center 和 collision task 参数；
- 生成 source/task identity；
- 决定每个 source 是一个 task 还是一个 fused domain。

这导致节点表面写着“一个任务”，实际却把多个 Object 变成多个 `MC2TaskSpec`。它既不能表达隐式对象和显式覆盖，也让未来的粒子属性覆盖没有清晰的编译入口。

新设计把“描述代理”和“组装模拟域”分开。这样每一层只有一个问题：

```text
source node       我描述哪个代理？
profile node      这个代理的默认粒子材料是什么？
override node     哪些字段对哪些粒子/约束/分区不同？
collector         哪些代理属于同一个 setup domain？能否融合？
MC2模拟步        这些已编译 task 如何按统一时间推进？
writeback         结果应该写回哪个 Blender owner？
```

## 节点层级

### 1. `MC2 MeshCloth对象`

这是显式 source 节点，输入一个 Mesh Object，输出一个 `MC2MeshClothPartitionEntry`。它不创建 slot、不扫描整个 world、不直接写 `world.implicit_objects`。

建议输入：

| 输入 | 所有权 | 说明 |
|---|---|---|
| `对象` | source partition | 单个 Mesh Object，稳定 source identity 来自 Object/Data 双指针及持久 stable id。 |
| `Anchor` | source partition | 可选 frame owner，不改变 topology identity。 |
| `粒子配置` | profile default | 通常连接 `MC2 MeshCloth粒子配置`。 |
| `分区启用` | partition | 关闭时保留 entry 但 collector 不纳入 active domain。 |
| `分区名称/稳定ID` | identity | 默认由 Object/Data 产生；显式 ID 用于隐式/显式匹配和 debug。 |

该节点可输出 source 的默认分区信息和 `partition_id`，但不应暴露 task scheduler、native context、substep 或 world step 参数。

### 2. `MC2 MeshCloth覆盖`

这是 sparse override 节点。它接收一个或多个 `MC2MeshClothPartitionEntry`，输出同类型 entry，但只保存显式连接或显式设置的字段 patch。

覆盖目标分四类：

- particle：半径、阻尼、质量、摩擦、重力响应、Motion/Backstop 等最终粒子系数；
- constraint：Distance/Bending/Tether/Angle 的 rest、刚度和限制值；
- partition：Anchor、Center/Teleport策略、source级 collision group、输出映射；
- domain compatibility：只有明确允许的 setup/domain 字段，不能在覆盖节点偷偷改变 collector 的 context contract。

没有连接的字段必须保持 `unset`，不能把默认值写进 patch 后再假装用户覆盖。collector 才负责把 default + implicit + explicit patch 编译成 dense runtime arrays。

### 3. `MC2 MeshCloth隐式对象`

这是 implicit object producer，负责把 Blender Object 或 object scope 选择注册为 `world.implicit_objects` 中的 `mc2.mesh_cloth` entry。它只写 registry，不创建 solver slot。

entry 至少包含：

```text
tag = mc2.mesh_cloth
stable_id
source object/data identity
base profile reference or sparse profile patch
partition patch
producer / version / signature
enabled
```

该节点允许把对象面板、集合选择或其他上游域逻辑转成隐式 MeshCloth entry。它的输出是 world 更新状态和 entry 统计；collector 读取 registry 时不得依赖 producer 的 Python 对象顺序。

### 4. `MC2 MeshCloth隐式收集`

这是纯读取节点，把 `world.implicit_objects[tag=mc2.mesh_cloth]` 转成与显式 `MC2 MeshCloth对象` 相同的 `MC2MeshClothPartitionEntry` 类型。显式 source 和 implicit source 因而可以在同一个 collector 合并。

它不做最终融合，不生成 task identity，不拥有 native state。没有 implicit entry 时输出空列表和明确的零计数，而不是伪造一个空 task。

### 5. `MC2 MeshCloth任务`

这是新的 setup-domain collector，也是当前“MeshCloth任务”节点的替代语义。它接收显式/隐式 partition entry，输出 `list[MC2TaskSpec]` 和可观察的装配状态；正常兼容输入只有一个 fused task，只有 Auto 明确形成多个兼容组时才有多个列表项。

建议输入：

| 输入 | 作用 |
|---|---|
| `显式分区` | 上游 `MC2 MeshCloth对象` 或覆盖节点输出。 |
| `隐式分区` | 上游 `MC2 MeshCloth隐式收集` 输出。 |
| `域默认配置` | 只给未覆盖的 partition/profile 字段提供 default。 |
| `融合策略` | 默认 Auto；Require Fusion 在不兼容时明确报错；Separate 只用于诊断/迁移，不得静默拆分。 |
| `域级自碰与过滤` | 统一 domain contract；粒子/分区差异通过下游属性数组表达。 |
| `启用` | 关闭 domain，但不删除上游 entry。 |

collector 输出：

- `MC2任务`：`list[MC2TaskSpec]`，正常为一个 fused task；多组时每一项都有独立 domain id；
- `任务名称`：稳定 domain task id；
- `分区数量`、`粒子数量`、`融合状态`；
- `冲突/不兼容报告`：包括 stable id、字段 owner 和阻止融合的具体原因。

collector 不接收 `时间缩放`、`模拟频率`、`每帧最大模拟次数`。这些属于 `MC2模拟步`，避免 setup domain 和 world scheduler 混在一个节点。

### 6. `MC2 BoneCloth任务` 与 `MC2 BoneSpring任务`

短期可以保留现有产品节点名称，但内部应逐步采用同一层级：

```text
BoneCloth链 entry -> BoneCloth collector -> MC2TaskSpec
BoneSpring链 entry -> BoneSpring collector -> MC2TaskSpec
```

三种 setup 共用 entry/patch/collector 的抽象和编译事务，但不共用拓扑 producer。BoneCloth 横向连接、BoneSpring line chain、MeshCloth final proxy 都由 setup adapter 各自生产；不能因为 node shape 统一就把 topology 语义抹平。

## 参数合并与优先级

同一个 source 的输入按以下顺序合并：

```text
collector domain defaults
  < implicit object declaration
  < explicit MC2对象 entry
  < explicit MC2覆盖 patch
  < collector-required normalization
  -> compiled partition/profile/constraint arrays
```

规则：

1. 同一个 stable id 的 implicit + explicit entry 可以合并；explicit 字段优先于 implicit 同名字段。
2. 两个不同显式 entry 同时覆盖同一字段，默认报冲突；只有明确的覆盖节点才能表达“后者覆盖前者”。
3. collector default 不能覆盖显式 unset 语义；`unset` 与“显式设置为默认值”必须可区分。
4. 合并结果必须保留来源链和字段 owner，供 debug/status 报告“这个参数来自哪里”。
5. collector 只生成 resolved intent；完整 particle/constraint runtime arrays 只能由 domain compiler 生成一次，不能由每个 node 或 partition fragment 各复制一份。

## TaskSpec 与 runtime 编译目标

`MC2TaskSpec` 是 collector 交给 `MC2模拟步` 的已归一化 domain intent，不是编译产物。它可以保留 Blender source/owner 引用供主线程 capture，但不得持有 dense particle arrays、constraint buffers、physical ranges、native handle 或 GPU 资源：

```text
MC2TaskSpec
  domain identity / setup type
  tuple[MC2PartitionSpec]
  resolved domain parameters
  fusion policy / compiler schema requirement
  enabled / provenance summary
```

`MC2PartitionSpec` 至少持有：

- stable partition id、source identity/reference；
- Object/Data/BasePose/Anchor/output owner 描述；
- resolved profile/task/setup 参数与字段 provenance；
- Center/Teleport policy 和独立 history key；
- collision group/mask、enabled 与 setup-specific capture options。

随后由 solver prepare 依次生成：

```text
MC2TaskSpec
  -> MC2DomainCapturePlan
  -> tuple[MC2PartitionStaticSnapshot]
  -> tuple[MC2PartitionStaticFragment]
  -> MC2CompiledDomain
  -> MC2BackendDomain
```

粒子/约束索引、参数 SoA、partition index view 和 output mapping 只存在于 `MC2CompiledDomain`。source 删除、重排、拓扑变化或兼容性变化通过 staged replacement 生成新的 compiled program/context，不能修改 live backend domain 的逻辑编号。

`partition_id` 是 authoring identity 和状态所有权，不是物理 buffer 地址。`particle range` 只是某次 domain compile 产生的布局视图。V1 编译器可以为了 CPU/GPU 顺序访问而让每个 Mesh partition 连续，但公开节点、缓存 key、结果协议和 debug 都不得假设 `partition_id == [start, stop)`。未来 GPU 后端可以重排、分块或压缩粒子，只要保留稳定的逻辑索引和输出映射。

## 当前运行时事实与阻塞点

当前生产流水线实际是“每个 Mesh Object 一个完整 slot/context”，不是多对象域：

```text
MC2 MeshCloth任务
  -> 展开 List[Object]
  -> 每个 Object 创建一个 MC2TaskSpec
  -> 每个 task 单独读取静态输入
  -> 每个 task 单独构建 proxy/baseline/constraint
  -> 每个 task 单独创建 native context 和 Center 状态
  -> 每个 task 单独求解
  -> 每个 task 生成一个 GN offset writeback
```

目前至少有五个明确的单对象假设，不能靠 collector 改名绕过：

| 边界 | 当前事实 | 融合所需变化 |
|---|---|---|
| 静态构建 | `build_mc2_mesh_cloth_static_for_task()` 要求恰好一个 Mesh source。 | 每个 source 先产出局部静态片段，再由 domain compiler 重定位索引并合并。 |
| 每帧输入 | `build_mc2_mesh_frame_input_for_task()` 只读一个 BasePose、一个 `source_world_linear`。 | 逐 partition 采集 frame snapshot，编译成统一动态输入和 transform table。 |
| Center/Teleport | `MC2FrameInputSpec`、slot 和 native context 只持有一套 component pose/Center history。 | Center/Teleport history 必须按 partition 拥有，domain 只负责统一调度。 |
| native context | 一个 context 接收一套静态 proxy、参数和动态输入。 | 新 ABI 接收 compiled domain program，并把 domain/partition/particle 参数分层。 |
| 结果与写回 | `MC2ResultCandidateV1` 只有一份 object-local offsets，Mesh result 要求一个 target。 | 输出先保持统一粒子场，再按稳定 output map 生成多个原子写回命令。 |

因此融合不是 `sources` 数组长度从 1 变成 N，而是引入一个独立的 domain compile/execute/output 流水线。旧 V0 context 在迁移期继续只接受单 source，不得被扩成含混的双模式对象。

E0 合同冻结已经完成：`partition_specs.py` 提供 immutable entry、sparse patch、显式/隐式 merge、字段 provenance 和纯 collector plan；`domain_ir.py` 提供 static snapshot、logical domain program、typed parameter/frame/output envelope 与 logical/physical index map；`domain_capabilities.py` 提供不加载后端的 allocation 前能力门。固定夹具覆盖单 Mesh、两个独立 Mesh 静态分区、两帧独立 transform/Anchor/Teleport、collision filter、output map 及 CPU/GPU capability 声明。E1 单 source shadow pipeline 已完成：真实 Mesh 只做一次静态 capture，纯 host fragment 和单域 compile 与旧静态构建逐项对照；它仍未创建 fused task、slot、runtime cache owner 或 native state。下一阶段是 E2 多 source 静态 domain compile，不是把这些对象直接翻译成多 source 旧 task。

## 统一粒子场流水线

### 四层对象

流水线必须区分四种生命周期，避免一个 Python dataclass 同时持有 Blender 对象、编译数组、native handle 和写回状态：

| 层 | 核心对象 | 可以包含 | 禁止包含 |
|---|---|---|---|
| Authoring | `MC2PartitionEntry`、sparse patch、collector draft | Blender source 引用、用户参数、字段来源、stable id | 粒子下标、native handle、GPU buffer |
| Capture | `MC2PartitionStaticSnapshot` / `MC2PartitionFrameSnapshot` | 从 Blender 主线程冻结的 POD 数组、transform、source/output token | solver 状态、后端资源、隐式 Python 回调 |
| Compile | `MC2CompiledDomain` | 后端中立 SoA、逻辑索引、constraint records、partition table、output map | `bpy` 对象、节点实例、live depsgraph、native handle |
| Execute | `MC2BackendDomain` / frame output | CPU/GPU 资源、历史状态、当前 frame、统一输出 buffer | authoring merge、Blender 读取、直接写回 Blender |

Capture 是 Blender IO 边界，Compile 是数值布局边界，Execute 是后端边界。三者必须可分别测试和计时。

### 阶段 0：收集与归一化

输入：

- collector domain defaults；
- 显式与隐式 `MC2PartitionEntry`；
- sparse override；
- fusion policy。

输出：`MC2DomainDraft`，包含有序 partition 描述、字段 owner、兼容性报告和 domain identity，但不包含顶点数组。

该阶段只做纯 Python 数据处理，不读取 depsgraph，不调用 native，不分配 solver slot。相同输入必须产生相同 draft signature。

### 阶段 1：主线程 source capture

输入：`MC2DomainDraft` 和当前 Blender/depsgraph view。

每个 Mesh partition 独立采集：

- Object/Data identity 与 topology revision；
- local positions、normals、edges、triangles、UV；
- pin/radius 等 source attribute；
- BasePose owner 与静态输出 owner；
- source local/world bind transform；
- 仅用于写回的 object/data token。

输出：`tuple[MC2PartitionStaticSnapshot]`。Snapshot 必须是只读 POD；离开 capture 后的编译和后端不得再访问 `bpy.types.Object`。这既隔离 Blender 线程约束，也为离线测试、native 编译和 GPU 上传建立共同输入。

### 阶段 2：partition static build

每个 setup adapter 把单个 snapshot 转成 `MC2PartitionStaticFragment`：

- MeshCloth：final proxy、baseline、Distance、Bending、Tether/Angle、自碰 primitive；
- BoneCloth/BoneSpring：保留各自的 line/bone topology producer，不强行复用 Mesh 数据结构；
- 所有索引仍是 partition-local；
- fragment 不注册 native context，不产生全局 particle index，不决定 GPU buffer。

这一步允许复用现有 Mesh 单对象构建算法，但要把“构建静态数据”和“立即写入一个 native context”拆开。静态 fragment 由 topology/source fingerprint 缓存，热帧不重建。

### 阶段 3：domain compile

输入：有序 partition fragments、归一化参数和 fusion policy。

输出：唯一的 `MC2CompiledDomain`，至少包含：

```text
domain_header
partition_table
logical_particle_table
particle_static_soa
constraint_tables
collision_filter_tables
center_teleport_table
frame_input_layout
output_map
backend_capabilities_required
```

编译规则：

1. partition-local topology 索引在这里统一重定位；不同 Mesh 之间不生成 Distance/Bending/Tether 等结构约束。
2. self collision 读取整个 domain 的粒子/primitive 场，再由 collision group/mask 决定同 partition、跨 partition和禁碰关系。
3. 参数依次降级为 domain scalar、partition table、particle SoA、constraint SoA；不能为了兼容旧 ABI 把真实差异退化成多个 task。
4. `logical_particle_id = (partition_id, source_vertex_id)` 是稳定身份；physical index 只是本次 compiled layout。
5. `output_map` 显式记录 logical/physical particle 到 source vertex 和 writeback target 的映射。结果拆分不根据连续 range 猜测 owner。
6. V1 编译器可以生成每 partition 一个连续 span 作为优化，但 contract 使用 `MC2IndexView`；它允许连续 span、多个 span或显式 index buffer。
7. program 的 domain/layout signature 覆盖 topology、output mapping 和 backend requirement；parameter layout 由独立 signature 覆盖。两类结构变化分别 staged replacement 自己拥有的资源，纯参数值变化只做热更新。

### 坐标空间与索引合同

V1 先冻结以下 canonical space，不允许每个 backend 自己解释：

| 数据 | canonical space / identity |
|---|---|
| Mesh 静态 positions/normals/topology | source object-local；topology identity 不烘入每帧 Object transform。 |
| partition fragment 约束索引 | partition-local particle index。 |
| compiled constraint 索引 | logical domain particle index；physical compiler 必须显式重定位。 |
| frame animated base positions/normals | world-space，逐 partition capture。 |
| Center/Teleport component transform | 每 partition 的 world TRS，独立 history key。 |
| backend dynamic positions/统一输出 | world-space。 |
| Mesh writeback offsets | 每 target 使用自己的 `inverse(source_world_linear)` 把 `solved_world - animated_base_world` 转回 object-local。 |

非均匀缩放、负缩放和 Anchor 不得被静默烘入静态 topology signature；它们属于 frame/Center contract。若某类 constraint rest 值需要 source scale，fragment 必须记录其 `space_kind`，domain compiler 或 backend adapter 按 schema 明确转换，不能仅凭数组名称猜测单位。

索引转换只允许沿一条可审计链发生：

```text
source vertex id
  -> partition-local particle index
  -> logical domain particle id
  -> backend physical index
  -> logical output map
  -> target source element id
```

每一步都有 version/signature 和逆向 debug 查询。任何约束、碰撞 primitive 或写回记录绕开这条链保存裸 physical index，都视为架构违规。

### 阶段 4：backend allocation

`MC2CompiledDomain` 交给后端适配器：

```text
MC2CompiledDomain
  -> CPUBackend.create_domain(program)
  -> GPUBackend.create_domain(program)
```

CPU 和 GPU 必须消费同一逻辑 program，不共享内部存储实现。CPU 可以保留 host SoA 或转换成 SIMD 友好的块；GPU 可以重排为 SSBO/storage buffer、建立间接 dispatch 和临时工作区。转换后的 physical layout 由 backend 私有，不能回写进 authoring spec。

后端返回 `MC2BackendDomain`，只拥有：

- 资源句柄；
- physical layout revision；
- per-partition Center/Teleport history；
- self-contact cache 和其他跨帧状态；
- inspect/timing/debug 的显式只读接口。

### 阶段 5：每帧 capture 与 pack

主线程逐 partition 读取 BasePose/evaluated pose，产生 `MC2PartitionFrameSnapshot`：

- partition id 与 frame/generation；
- animated base positions/normals 或 setup-specific pose；
- component transform；
- Anchor transform；
- partition 级 velocity/gravity/scale/teleport 输入。

纯编译函数把这些 snapshot 写入 `MC2DomainFramePacket`。Packet 使用 logical layout，并携带缺失、重复、topology mismatch 的完整校验结果。backend adapter 再把 packet pack/upload 到自己的 physical layout。

因此 Blender IO 次数仍与对象数量相关，但 solver 调度、碰撞 broadphase、self collision 和约束求解只面对一个 domain。GPU 后端还可以对静态 buffer 常驻，只上传每帧变化的 position/transform/少量参数。

### 阶段 6：统一求解

backend 的公开 step 只接收：

```text
step(domain_handle, frame_packet, scheduler_settings, collider_snapshot)
```

它不接收 Blender Object、节点或 sparse patch。每个 substep 内部对统一粒子场执行 integration、constraint、self collision、external collision 和 Center/Teleport；跨 Mesh 自碰因此是同一 broadphase/solver pass，不再经过跨 task pair context。

Center/Teleport 语义按 partition 执行，但结果作用于该 partition 的 `MC2IndexView`。Anchor 可以由多个 partition 共享同一个 transform snapshot，却不能因此共享历史状态。

### 阶段 7：输出拆分与原子写回

backend 输出 `MC2DomainFrameOutput`：统一 world position/rotation buffer、frame identity、physical layout revision 和有效性状态。输出 adapter 使用 compiled `output_map` 生成：

```text
tuple[MC2MeshWritebackCommand]
  target object/data token
  source vertex count
  logical/physical index view
  source world inverse linear
  object-local offsets
```

一个 fused domain 可以产生多个 Mesh writeback command。所有命令先校验 target、vertex count、frame/generation 和有限值，再作为一个 Physics World result transaction 发布；任一 target 失败时不能只写回部分对象。

GPU 方案允许两种输出路径：初期把统一 position buffer readback 后在 host 拆分；成熟后由 GPU scatter 直接产生每 target offset buffer。两者共享同一 output map 和事务语义，差别只在后端适配器。

## 后端中立 IO 合同

### `MC2CompiledDomain` 必须是 POD/SoA

为兼容统一粒子场和 GPU，compile 产物必须满足：

- 不含 `bpy`、Python callback、节点实例或 live depsgraph；
- 数组 dtype、shape、alignment、单位、坐标空间和读写权限显式；
- 所有关系通过整数表、span/index view 和稳定 signature 表达；
- domain/partition/particle/constraint 四级参数边界明确；
- CPU/GPU 转换可以完全在 native/backend 层完成；
- 可从固定 fixture 重建，不要求打开 `.blend`。

推荐的最小逻辑表：

| 表 | 关键字段 | 主要消费者 |
|---|---|---|
| partition table | stable id hash、setup kind、logical index view、frame owner index、output owner index | frame pack、Center/Teleport、debug |
| logical particle table | partition index、source vertex id、attribute flags | 参数编译、结果映射 |
| particle static SoA | bind position/rotation、normal、radius multiplier、depth | CPU/GPU solver |
| particle parameter SoA | mass/inertia、damping、radius、gravity、friction | CPU/GPU solver |
| partition uint parameter SoA | collision group/mask、离散 policy/flags | broadphase、partition policy |
| constraint tables | type-specific indices、rest、stiffness、flags | constraint kernels |
| collision tables | primitive indices、thickness、primitive flags | broadphase/narrowphase |
| output map | target index、source element id、logical index view、space contract | result/writeback |

### V1 IO schema 草案

E0 必须把 `MC2CompiledDomain` 再拆成“静态 program + 可热更新参数”。下面是需要冻结的最小 envelope；setup-specific payload 可以增加表，但不能绕开这些 identity、space 和生命周期字段。

#### `MC2DomainCapturePlanV1`

只在 Blender 主线程存活，不传入 native/GPU：

| 字段 | 类型/shape | 语义 |
|---|---|---|
| `domain_id` | string | collector 生成的稳定 domain identity。 |
| `setup_type` | enum | MeshCloth/BoneCloth/BoneSpring；一个 plan 只有一种 setup。 |
| `partition_specs` | tuple[P] | resolved source/profile/policy/provenance。 |
| `source_refs` | tuple[P] | live Blender Object/Data/BasePose/Anchor 引用，仅 capture 使用。 |
| `output_target_refs` | tuple[Q] | live Blender target 引用，仅生成 host writeback command。 |
| `fusion_policy` | enum | Auto/Require Fusion/Separate。 |
| `capture_schema` | u32 | 未知版本在读 Blender 前拒绝。 |

#### `MC2PartitionStaticSnapshotV1`（MeshCloth）

每个 partition 一份，只读 host POD：

| 字段 | dtype/shape | space | 生命周期 |
|---|---|---|---|
| `partition_id` | string + stable hash | identity | topology revision |
| `source_revision` | fixed signature | identity | topology revision |
| `local_positions` | f32[V,3] | object-local | topology/geometry revision |
| `local_normals` | f32[V,3] | object-local unit vector | geometry revision |
| `edges` | u32[E,2] | source vertex id | topology revision |
| `triangles` | u32[T,3] | source vertex id | topology revision |
| `triangle_loops` | u32[T,3] | loop id | topology/UV revision |
| `loop_vertices` | u32[L] | source vertex id | topology revision |
| `loop_uvs` | f32[L,2] | UV | UV revision |
| `pin_weights` | f32[V] | 0..1 | source attribute revision |
| `radius_multipliers` | f32[V] | 0..1 | source attribute revision |
| `source_bind_matrix` | f32[4,4] | object-local -> world bind reference | source revision |
| `source_element_ids` | u32[V] | stable source vertex id | topology revision |

Snapshot 不含 output target 指针。它只持有可序列化的 target identity token；live target ref 留在 capture plan/host transaction 层。

#### `MC2CompiledDomainProgramV1`

不可变、后端中立，变化时 staged replacement：

| 字段 | dtype/shape | 说明 |
|---|---|---|
| `schema_version` | u32 | 逻辑 program schema。 |
| `domain_signature` | 128/256-bit | 覆盖有序 partition、setup、topology、output map 和 capability。 |
| `layout_signature` | 128/256-bit | 覆盖所有 logical table shape/relationship，不覆盖热更新参数值。 |
| `setup_type` | enum | 决定 setup-specific static payload。 |
| `partition_ids` | tuple[P] | host/debug identity；GPU 使用编译后的 partition index。 |
| `partition_flags` | u32[P] | enabled、输出、碰撞和 setup flags。 |
| `partition_particle_views` | `MC2IndexView[P]` | logical particle membership；V1 可为 contiguous span。 |
| `particle_partition_index` | u32[N] | logical particle -> partition。 |
| `particle_source_element` | u32[N] | logical particle -> source vertex/bone element。 |
| `particle_bind_position` | f32[N,3] | setup 声明的 static space。 |
| `particle_bind_rotation` | f32[N,4] | xyzw；不需要的 setup 可为空。 |
| `particle_attribute_flags` | u32[N] | Fixed/Move/Ignore 等静态属性。 |
| `constraint_payloads` | typed SoA tables | Distance/Bending/Tether/Angle 等，索引为 logical particle。 |
| `self_collision_primitives` | typed index tables | whole-domain logical primitive。 |
| `output_targets` | metadata[Q] | target identity、element count、space contract；无 live Object。 |
| `output_map` | typed map[N or records] | logical particle -> target/source element。 |
| `required_capabilities` | bitset | backend allocation 前完整核对。 |

Program 中的 `logical particle index` 在该 program 生命周期内稳定。backend 生成的 physical index 不写回 program；backend 若重排，必须私有保存 logical <-> physical 双向表。

#### `MC2DomainParameterPacketV1`

layout 不变时允许原地上传/更新：

| 字段 | dtype/shape | 更新粒度 |
|---|---|---|
| `layout_signature` | fixed signature | 必须匹配 program。 |
| `parameter_layout_signature` | fixed signature | 覆盖参数表名称、字段顺序、dtype 和 shape，不覆盖值。 |
| `parameter_signature` | fixed signature | 去重和 debug。 |
| `domain_scalars` | typed fixed struct | domain 热更新。 |
| `partition_parameters` | f32 SoA[P] | Center/Teleport 等连续参数。 |
| `partition_uint_parameters` | u32 SoA[P] | `collision_group`、`collision_mask` 等离散策略；位语义禁止转成 float。 |
| `particle_parameters` | typed SoA[N] | radius、mass/inertia、damping、gravity、friction 等。 |
| `constraint_parameters` | typed SoA per table | rest/stiffness/limit/damping 等。 |

仅数值变化只改变 `parameter_signature` 并原地上传；参数字段、dtype 或 shape 变化改变 `parameter_layout_signature`，要求参数存储 staged replacement，但不伪造 topology 变化。logical membership、topology、output map 或 capability 变化才产生新 program/backend domain。CPU/GPU 都必须报告 parameter upload/update 成本。

E0 envelope 的 producer/owner/consumer 固定如下；NumPy 数组在这些 envelope 内一律 C-contiguous、只读，不允许任何层借此取得跨层可变所有权：

| Envelope | Producer | 生命周期 owner | 主要消费者 |
|---|---|---|---|
| static snapshot | setup capture adapter | partition static cache，source revision | domain compiler |
| compiled program | domain compiler | compiled-domain cache，program revision | capability gate、backend allocation、output mapper |
| parameter packet | parameter compiler | 单次 staged update / parameter revision | backend parameter upload |
| frame packet | frame compiler | Physics World 单帧事务 | backend update/step、output conversion |
| physical index map | backend allocation | backend domain state/revision | output adapter、debug identity |
| frame output | backend read/step result | Physics World result transaction | domain output、统一 writeback |

#### `MC2DomainFramePacketV1`

每帧只读输入：

| 字段 | dtype/shape | space/语义 |
|---|---|---|
| `domain_signature` / `layout_signature` | fixed signature | 防止旧 frame 写入新 domain。 |
| `frame` / `generation` | i64/u64 | Physics World identity。 |
| `animated_base_world_positions` | f32[N,3] | world-space logical particle order。 |
| `animated_base_world_normals` | f32[N,3] 或空 | world-space；setup 可选。 |
| `partition_world_position` | f32[P,3] | component world translation。 |
| `partition_world_rotation` | f32[P,4] | unit xyzw。 |
| `partition_world_scale` | f32[P,3] | signed scale。 |
| `partition_world_linear` | f32[P,3,3] | exact source world linear matrix，用于非均匀/负缩放回写和可逆性校验。 |
| `anchor_world_position/rotation` | f32[P,3]/f32[P,4] | 无 Anchor 时由 flags 标记。 |
| `partition_frame_flags` | u32[P] | reset/keep/disable/anchor-present 等。 |
| `velocity_weight/gravity_ratio` | f32[P] | partition 级 frame control。 |

Scheduler 的 `dt/frequency/max_steps/time_scale` 属于 step call，不复制进每粒子 frame packet。external collider snapshot 属于 Physics World frame scope，由 step 作为独立只读输入传入。

#### `MC2DomainFrameOutputV1`

backend 统一输出：

| 字段 | dtype/shape | 说明 |
|---|---|---|
| domain/layout/frame/generation identity | fixed header | 必须与 program/frame 完全匹配。 |
| `world_positions` | f32[N,3] | logical order view，或携带 physical->logical map 的 backend view。 |
| `world_rotations_xyzw` | f32[N,4] 或空 | Bone/setup 需要时提供。 |
| `validity_flags` | u32 | finite、complete、teleport/reset、readback 状态。 |
| `backend_revision` | u64 | 防止读取已替换资源。 |
| `timing_token` | optional handle | 只有热点开关开启时可解析，关闭时不得构造详情。 |

Output 本身不含 object-local offsets。`domain_output.py` 在 host 侧用 frame packet 的每 partition transform 和 program output map 生成多个 writeback command；GPU direct-scatter 也必须产生等价 command envelope。

### 不把 NumPy 当成架构 ABI

Python 侧可以用只读 NumPy 数组表达 capture/compile fixture，但 NumPy 只是 host carrier，不是最终 ABI。native ABI 应按“typed buffer view + schema/version + shape/stride contract”接收数据；GPU 后端可从相同 schema 创建 device buffer。这样不会把 Python 版本、NumPy owner 或 C contiguous 假设扩散进 solver 内核。

### 编译与执行缓存

缓存分三层：

1. `PartitionStaticFragmentCache`：按单 source topology/surface fingerprint 复用；
2. `CompiledDomainCache`：program 按有序 fragments、output map 和 backend capability 复用；参数存储在其下按 `parameter_layout_signature` 独立复用或替换；
3. `BackendDomainState`：跨帧 mutable 状态，只能由对应 backend handle 拥有。

热帧只允许执行 frame capture、frame pack、step、必要 readback 和结果发布。任何静态 fingerprint 全量重算、拓扑重建或参数 dense compile 都必须在 profiler 中单列，不能藏进“模拟求解”。

## 文件职责重排

目标文件边界如下，名称可在实现时微调，但职责不能重新混合：

| 模块 | 唯一职责 |
|---|---|
| `partition_specs.py` | authoring entry、sparse patch、merge provenance；不读 Blender、不建 task。 |
| `domain_collect.py` | entry -> `MC2DomainDraft`、fusion compatibility 与装配报告。 |
| `setups/mesh_cloth/source_capture.py` | Blender 主线程静态 source capture。 |
| `setups/mesh_cloth/static_fragment.py` | 单 partition Mesh 拓扑/约束 fragment 构建；不注册 context。 |
| `domain_ir.py` | 后端中立 compiled domain、index view、output map 数据合同。 |
| `domain_capabilities.py` | allocation 前schema/setup/capability/容量检查；不加载或拥有backend。 |
| `domain_compile.py` | 有序 fragment 的 partition-local -> logical 索引重定位、分级参数 SoA、collision/output table 编译与纯 cache-reuse 报告。 |
| `cpu_backend.py` | E3 单 source CPU domain 生命周期适配器；能力门、frame/step/output identity、physical->logical 归一化、partition history 与 dispose 所有权；kernel 通过窄协议注入。 |
| `frame_compile.py` | 各 partition 冻结 frame snapshot 的纯校验与 logical index view 打包；不读取 Blender、不拥有历史或 backend。 |
| `shadow_pipeline.py` | E1 显式 opt-in 的 capture -> fragment -> compile 与旧静态结果对照、阶段计时；不解算、不写回、不拥有 backend。 |
| `domain_parameters.py` | resolved 参数 -> 热更新 parameter packet；不改变 topology layout。 |
| `frame_capture.py` 及 setup adapter | Blender 主线程逐 partition frame snapshot。 |
| `frame_compile.py` | snapshots -> domain frame packet；纯数据校验与 pack plan。 |
| `backends/contracts.py` | create/update/step/read/inspect/dispose 接口。 |
| `backends/cpu.py` | 新 CPU domain ABI 的薄适配；不读 Blender。 |
| `backends/gpu.py` | 将同一 IR 转成 GPU 资源和 dispatch；不改变 authoring 合同。 |
| `domain_output.py` | domain output + output map -> 多 target writeback commands。 |
| `solver.py` | staged prepare/execute/publish 事务编排，不构造 Mesh 拓扑细节。 |
| `results.py` | 公共 result envelope 与事务校验，不推断 source 切片。 |
| `native_context.py` | 旧 V0 单 source context 兼容层；新 domain backend 不继续堆入该类。 |

迁移时优先新增清晰模块并让旧路径调用新合同，最后删除旧职能。不要在 `solver.py` 中临时拼接数组，也不要继续让 `static_build.py` 一边构建数据一边初始化 native context。

## 明确的数据流

### 显式模式

```text
Object
  -> MC2 MeshCloth对象
  -> MC2 MeshCloth覆盖（可选，可串多个但冲突要显式）
  -> MC2 MeshCloth任务.显式分区
```

### 隐式模式

```text
Physics World Begin
  -> MC2 MeshCloth隐式对象（写 world.implicit_objects）
  -> MC2 MeshCloth隐式收集（读 registry）
  -> MC2 MeshCloth覆盖（可选）
  -> MC2 MeshCloth任务.隐式分区
```

### 统一运行时

```text
MeshCloth collector -> [MC2TaskSpec]
BoneCloth collector  -> [MC2TaskSpec]
BoneSpring collector -> [MC2TaskSpec]
                           \
                            -> MC2模拟步(world, all tasks)
                                -> capture plan / static snapshots
                                -> partition fragments / compiled domain
                                -> CPU or GPU backend domain step
                                -> domain output / multi-target result streams
                                -> Physics Writeback
```

collector 可以在图上有多个，但每个 collector 的一个输出项代表一个明确 domain。`MC2模拟步`不再猜测某个 list item 是 Object、partition 还是 task；非法 entry 在 collector 边界拒绝。

## Fusion 与分组规则

一个 MeshCloth collector 默认只产出一个 fused domain。以下情况必须显式报告并按策略处理：

- setup type 不同；
- scheduler/context-only 参数不兼容；
- self collision 算法或过滤合同不兼容；
- ABI/schema 或 topology producer 不兼容；
- source output owner 无法唯一映射；
- partition 需要的 Center/Teleport contract 尚未被当前 compiler 支持。

`Auto` 可以把 entry 分到多个兼容组，但必须输出多个明确的 domain result 和分组报告，不能仍然把它伪装成一个 task。`Require Fusion` 遇到任意不兼容直接失败，适合性能验收和 GPU 规模基准。`Separate` 只用于迁移诊断，不能成为普通用户的隐式回退。

## Debug 与用户可见状态

新节点必须让用户能回答：

- 这个 Object 是否被收集？来自显式还是隐式 entry？
- 它属于哪个 MeshCloth domain/partition？
- 哪些 profile/task/constraint 字段被覆盖，来源是谁？
- domain 是否成功融合？如果没有，具体哪个字段阻止？
- 最终 backend domain、logical particle index view、physical layout revision 和 writeback owner 是什么？

collector 的状态输出是轻量编译摘要，不读取 native 中间态；MC2 debug node 继续读取 solver slot 的冻结 native snapshot。两者不能混合：前者解释“装配了什么”，后者解释“解算发生了什么”。

## 分阶段执行计划

### E0：合同冻结与固定夹具

范围：只改文档、纯 dataclass/schema、fixture generator 和合同测试，不改生产节点或 native ABI。

交付物：

- 四层对象和逐阶段 IO schema；
- 两个独立 Mesh partition 的固定静态 snapshot；
- 两帧 frame snapshot，包含不同 transform、Anchor 和 Teleport 条件；
- 期望 logical particle identity、constraint local indices、collision filters 和 output map；
- CPU/GPU backend capability 表。

退出条件：仅从 fixture 就能构建并完整校验 `MC2CompiledDomain` 的目标 schema；任何字段都能说明 producer、owner、坐标空间、生命周期和消费者。

禁止事项：不得修改 `MC2TaskSpec` 生产语义，不得给旧 topology 直接添加含义未冻结的 `particle_range`，不得注册新产品节点。

实现状态（2026-07-21）：E0 已完成。`schema_v1/manifest.json` 串联单 Mesh、双 Mesh 静态与双帧 fixture；合同测试可仅从这些 POD 重建并校验 logical identity、结构约束分区隔离、typed collision filters、output map、signed transform、独立 Keep/Reset、logical/physical 重排和 CPU/GPU capability 拒绝。Python 3.11/3.13 共用同一 oracle。架构审计同时禁止 E0 模块读取 Blender/Physics World/native owner，并禁止任何生产消费者在 E1 前提前导入 E0 合同。

### E1：单 source shadow pipeline

范围：让一个 Mesh source 同时经过旧 V0 路径和新的 capture -> fragment -> compile 流水线，但求解和写回仍使用旧路径。

交付物：

- `source_capture.py`、`static_fragment.py`、`domain_ir.py`、`domain_compile.py` 的最小实现；
- shadow compile timing；
- 旧静态构建与新 compiled domain 的 topology/constraint/parameter 对照报告。

退出条件：代表资产上的单 source 粒子数、结构约束、自碰 primitive、半径、深度和参数数组逐项一致；shadow 关闭时没有额外 capture/compile 成本。

实现状态（2026-07-21）：E1 已完成。`run_mc2_mesh_shadow_compile` 只接受已捕获的 source snapshot，依次生成纯 host fragment、compiled domain，并与现有完整静态构建比较 topology、Distance/Bending/Tether、self primitive、粒子属性、depth/radius 和 effective parameter signature。`step_mc2(..., shadow_compile=True)` 是迁移期内部显式开关；默认值为 `False`，关闭时不导入 shadow 模块、不读取 Mesh、不分配对照数组。开启时只追加调用方提供的临时 report，V0 context/solve/writeback 仍是唯一产品路径；不兼容报告在 slot 安装前失败并沿用既有清理事务。Python 3.11/3.13 单元测试与 Blender 4.5 无头真实 Mesh 验收均通过。

### E2：多 source 静态 domain compile

范围：只实现多 partition 静态合并，不创建 fused native context，不运行模拟。

交付物：

- partition-local -> logical domain index 重定位；
- domain/partition/particle/constraint 参数分级；
- whole-domain self collision primitives 与 group/mask；
- 多 target output map；
- deterministic compile signature 和缓存命中报告。

退出条件：两个 Mesh 编译成一个 domain；无跨 source Distance/Bending/Tether 记录；跨 partition self-collision 仅由过滤表决定；输入顺序、显式稳定顺序和 source 删除的 identity 行为符合合同。

实现状态（2026-07-21）：E2 已完成静态编译部分。`compile_mc2_mesh_static_fragments` 保留调用方的显式 fragment 顺序，为每个 partition 生成连续但仅作为 `MC2IndexView` 的物理视图，并将所有 constraint/primitive 索引按偏移重定位；结构表的 endpoint owner 校验确保不存在跨 source Distance/Bending/Tether。输出 target、logical source element 和 partition owner 全部显式写入 program。每个 partition 的 runtime floats、uint32 group/mask、particle curve 采样和 constraint 参数独立进入统一 SoA，空的 domain scalar 表表示当前字段没有可安全提升到 world-scope 的值。`compare_mc2_domain_compile_cache` 只生成复用资格报告，不持有缓存或 backend；可区分 exact、layout/program 复用、纯参数值更新、重排和 source 删除。E2 仍不创建 native context，不运行模拟。

### E3：新 CPU backend 单 source 等价

范围：建立新的 domain backend ABI，先只运行一个 partition。旧 `MC2NativeContextV0` 保留作为 reference，不在原类上叠加双模式。

交付物：

- `create_domain/update_frame/step/read_output/inspect/dispose`；
- partition 级 Center/Teleport state table，即使当前只有一个 partition；
- 单 source 双路径数值对照和 staged failure rollback。

退出条件：D-01 至 D-10 已验收行为不回退；相同输入下旧/新 CPU 输出误差在既定 tolerance 内；debug-off 无新增 readback；dispose/reset/rewind 无泄漏和悬空状态。

实现状态（2026-07-21）：E3 的 backend ABI/lifecycle slice 已完成，真实数值 kernel 尚未接入产品。`frame_compile.py` 先把按 partition 捕获的只读 frame snapshot 校验为同一 frame/generation，再按 compiled logical index view 生成统一 packet；`MC2CPUBackendDomainV1` 在 allocation 前调用 capability gate，创建后只持有 compiled program、私有 physical index map、每 partition history 和 kernel handle；`update_frame`/`step`/`read_output` 严格检查 domain/layout/frame/generation identity，physical output 会在 adapter 内归一化为 logical output，`dispose` 幂等且 kernel 创建失败会回滚。fake-kernel 双版本测试覆盖能力拒绝、history、physical reorder、frame pack 和资源释放。现有 `_native/src/mc2_context_*` 仍是 `PyObject*` 驱动的 `Mc2ContextV0` V0 ABI，不能作为新域 kernel 的隐式实现；下一步必须新增独立 C++ domain owner/POD view/handle，不得给 V0 context 叠加第二种输入。单 source 数值 oracle 对照通过前，V0 solver、slot、Physics World 和 writeback 不导入该适配器。

### E4：多 source fused CPU execution

范围：让 E2 compiled domain 在一个 CPU backend context 中执行，打开同域跨 partition self collision。

交付物：

- 多 partition frame capture/compile；
- 每 partition Center/Teleport/Anchor 历史；
- 一个 broadphase/self-collision domain；
- 统一 output buffer。

退出条件：两个原本独立的 MeshCloth 对象在一个 context 中稳定碰撞；关闭跨 partition filter 后退化为互不碰撞但仍共享 context；不同粒子参数通过 SoA 生效，不要求拆 task。

### E5：多目标结果事务与产品节点

范围：先完成多 target output adapter 和原子 writeback，再把 collector 接到产品节点；不能反过来。

交付物：

- 一个 domain 输出多个 GN offset commands；
- target validation 与全批 rollback；
- 显式对象/覆盖/collector 节点；
- implicit registry producer/reader；
- 用户可读装配报告。

退出条件：多 Mesh 每帧各自写回正确 Object local offsets；任一 target 失效时整批不发布；collector 显示真实 fusion 状态，不存在静默 `N Object -> N task` 回退。

### E6：GPU backend 原型与收益门禁

范围：复用同一 `MC2CompiledDomain` 和 frame/output contract，实现最小 GPU backend；不先追求全部算法覆盖。

优先原型：integration + Distance + whole-domain self-collision 的代表热点，保留 CPU reference 对照。

退出条件：

- 25 ms 级纯数值代表场景有明确接近或达到 5 ms 的证据，或者规模收益曲线证明粒子量提升一个数量级仍优于 CPU；
- upload/readback 单独计时，不能只报告 kernel 时间；
- 结果误差、确定性范围、设备丢失和 CPU fallback 合同明确；
- 若收益不足，不污染生产 node/data contract，可完整撤下 backend。

### E7：迁移收尾

完成 BoneCloth/BoneSpring collector 迁移评估、删除 MeshCloth 旧隐式拆 task 路径、更新蓝本和声明、清理 V0 兼容层。只有新路径通过长期资产回归后才允许删除旧实现。

## 验收目录

验收资产按流水线边界组织，不按某个临时类名组织。计划目录如下；E0 先建立 schema/fixture，后续阶段只补证据，不另起一套测试体系：

```text
mc2/test/
  fixtures/domain_pipeline/
    schema_v1/manifest.json        # E0 已有
    single_mesh/                   # E0 已有
    two_mesh_static/               # E0 已有
    two_mesh_frames/               # E0 已有
    output_maps/
    backend_reference/
  test_domain_ir.py                # E0 已有
  test_domain_contract.py
  test_domain_collect.py
  test_partition_capture.py       # E1 已有
  test_partition_static_fragment.py # E1 已有
  test_domain_compile.py           # E1/E2 已有
  test_shadow_pipeline.py          # E1 已有
  test_cpu_backend.py               # E3 ABI/lifecycle 已有
  test_frame_compile.py              # E3 frame pack 已有
  test_domain_frame_packet.py
  test_domain_backend_cpu.py
  test_domain_output.py
  test_domain_failure_atomicity.py
  benchmark_domain_pipeline.py
  acceptance_assets_v2.json
```

Blender 主线程验收：`physicsWorld/test/test_blender_mc2_domain_shadow.py`（E1，真实 Mesh/World/Task，验证 opt-in report 与旧静态路径一致）。

固定 JSON/NPZ fixture 只保存 POD、schema version、signature 和 tolerance，不保存 Blender 指针。需要真实 Blender IO 的 capture/writeback 验收由 `acceptance_assets_v2.json` 指向版本化 `.blend` 资产，并输出机器可读报告。CPU/GPU 共用同一组 compiled-domain/frame fixtures；后端不得各自维护不同的“正确答案”。

### A0：合同与 schema

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A0-01 | 四层对象无职责穿透 | schema 审计证明 compiled/execute 对象不含 `bpy`、节点或 depsgraph。 |
| A0-02 | 每个数组字段定义完整 | dtype、shape、单位、坐标空间、owner、mutable/lifetime 表。 |
| A0-03 | logical identity 与 physical layout 分离 | 相同 logical domain 用两种 physical 排列编译，output map 仍产生相同逻辑结果。 |
| A0-04 | ABI 版本拒绝策略 | 未知 schema/capability 在 allocation 前失败，不创建半初始化 handle。 |

### A1：authoring 与 collector

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A1-01 | implicit + explicit 同源 | stable id 只合并一次，字段优先级和 provenance 可观察。 |
| A1-02 | sparse unset | 未设置字段继承 default，显式默认值与 unset 可区分。 |
| A1-03 | 冲突 | 双显式冲突给出 partition、字段和 producer，不静默 last-writer。 |
| A1-04 | 禁用与顺序 | 禁用 entry 保留，active draft 排除；其他 stable identity 不漂移。 |
| A1-05 | fusion policy | Require Fusion 明确失败；Auto 的每个分组和原因可见；无隐藏 fallback。 |

### A2：静态 capture 与 fragment

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A2-01 | Blender IO 边界 | capture 后销毁/替换 live object 引用，纯 fragment 测试仍可运行。 |
| A2-02 | 单 source 等价 | proxy/baseline/constraint/self primitive 与现有单对象路径一致。 |
| A2-03 | 局部索引 | 每个 fragment 的约束索引只引用本 partition 粒子。 |
| A2-04 | 缓存失效 | topology/surface/profile 各自只使声明的缓存层失效。 |
| A2-05 | 热帧零静态扫描 | 无拓扑变化时不重读 Mesh 静态数组、不重建 fragment。 |

### A3：domain compile 与统一粒子场

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A3-01 | 多 Mesh 合并 | 两个 partition 编译成一个 domain、一个 logical particle field。 |
| A3-02 | 结构约束隔离 | 跨 partition Distance/Bending/Tether 记录数严格为零。 |
| A3-03 | 自碰覆盖 | whole-domain primitive 表含两个 partition，group/mask 精确控制跨 partition pair。 |
| A3-04 | 参数分级 | 两个 partition 使用不同 radius/damping/mass，dense SoA 正确且不拆 domain。 |
| A3-05 | output map 双射 | 每个 source vertex 恰好映射一个 logical particle 和一个 target element。 |
| A3-06 | physical 重排 | contiguous 与重排 layout 产生相同 output mapping 和 debug identity。 |
| A3-07 | staged replacement | source 增删/拓扑变化生成新 program；旧 program 不原地重编号。 |
| A3-08 | 参数热更新 | 只改 radius/damping/stiffness 时 layout/program signature 不变，仅 parameter signature 和对应 buffer 更新。 |

### A4：frame、Center 与 Teleport

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A4-01 | 独立 transform | 两个 Mesh 不同平移/旋转/非均匀缩放时 frame packet 正确。 |
| A4-02 | 独立 Center history | 一个 partition 移动不污染另一个 partition 的惯性/平滑状态。 |
| A4-03 | 独立 Teleport | 一个 partition Keep/Reset 时另一个连续运行；状态和速度均安全。 |
| A4-04 | Anchor 共享与隔离 | 可共享 Anchor snapshot，但每 partition history key 独立。 |
| A4-05 | rewind/reset | generation、倒帧、跳帧和 user reset 对全部 partition 原子生效。 |

### A5：CPU backend 与数值行为

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A5-01 | 单 source reference | 新 backend 对现有 D-01 至 D-10 资产无行为回退。 |
| A5-02 | fused self collision | 两个 Mesh 在一个 domain 内真实接触，不经过跨 task interaction context。 |
| A5-03 | filter off | 禁止跨 partition pair 后两者不互碰，域内各自自碰仍正常。 |
| A5-04 | 参数差异 | 不同粒子参数对各自 partition 生效，性能不退化为逐 task dispatch。 |
| A5-05 | failure atomicity | allocation/update/step/read 任一点注入失败，旧 live domain 或完整失效状态可恢复。 |

### A6：结果与写回

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A6-01 | 多 target | 一个 domain 每帧产生多个目标明确的 GN writeback command。 |
| A6-02 | 坐标空间 | 每个 target 使用自己的 source transform 转 object-local offsets。 |
| A6-03 | 原子事务 | 任一 target/data/vertex count 失效时零对象被部分写回。 |
| A6-04 | topology replacement | Object Data 替换后旧 output map 被拒绝，新 map 原子发布。 |
| A6-05 | debug 对齐 | debug partition/particle identity 与实际 writeback target/element 一致。 |

### A7：性能与 GPU 可迁移性

| 编号 | 验收项 | 固定证据 |
|---|---|---|
| A7-01 | debug-off 零拖累 | 无 debug snapshot/readback/格式化；只保留常数级开关判断。 |
| A7-02 | 热帧阶段计时 | capture、pack/upload、solve、readback、output split、publish 独立聚合。 |
| A7-03 | 融合收益 | 同资产 `2 task + cross-task` 对比 `1 fused domain`，记录 P50/P95 和粒子规模。 |
| A7-04 | 内存曲线 | compiled host、CPU backend、GPU resident、scratch、readback 分项随粒子数增长。 |
| A7-05 | GPU backend 可替换 | 不改节点和 authoring fixture 即可切换 CPU/GPU，并得到相同 output contract。 |
| A7-06 | 规模收益曲线 | 优先证明粒子量提升后的增长斜率，而不是只优化小场景最低延迟。 |

### A8：产品可观察性

用户必须能从 collector 状态看见：收集了哪些对象、来自显式还是隐式、为何融合/分组、哪些参数被谁覆盖、最终使用哪个 backend/domain。MC2 debug 只展示运行中状态；两者关闭时均不触发额外 native readback。任何只输出数学数组名称、却不能说明“是否正常、谁触发、受哪个具体参数影响”的状态都不算验收通过。

## 与现有契约的关系

该设计遵循 Physics World 的既有边界：spec build 可以由独立节点或 solver 内部完成；solver step 仍一次接收多个规范化 task；solver 不写 Blender，结果通过 result stream 交给统一 writeback。新节点只是把 MC2 setup 内部原来混在 task 函数中的 spec build/collect/compile 职能显式化，不新增第二个 world step，也不把 MeshCloth、BoneCloth、BoneSpring 拆成三个 Physics World solver。
