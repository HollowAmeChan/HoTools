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

E0-E5 的数据依赖和验收门禁是强约束。未通过上一阶段的合同和固定夹具验收，不进入依赖它的产品实现；尤其不能先把多个 `Object` 塞进旧 `MC2TaskSpec.sources`，再让旧的单对象静态构建、Center 和 writeback 路径猜测其含义。E6 是未来 GPU 分支，不是当前 CPU 统一域上线的前置条件；E7 中只依赖 E5 的 CPU 迁移清理可以先完成，GPU 专属清理留到 E6 真正立项后。

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

E0-E3 已完成：后端中立合同、单 source shadow、多 source 静态 compile 和单 source CPU reference 均有固定证据。它们仍未创建产品 fused task 或替换 Physics World owner。当前执行入口是 P0 原生阶段计时与 P1-B source observation cache，随后按本文件顺序进入粒子级覆盖合同和 E4 多 source fused CPU domain；不能把已编译的多个 source 翻译成多个旧 task 来冒充统一域。

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
| `partition_center_local_position` | f32[P,3] | setup static build 产生的 Center 本地基准。 |
| `partition_initial_local_gravity_direction` | f32[P,3] | Center 重力衰减的初始局地方向。 |
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
| `animated_base_world_rotations` | f32[N,4] | world-space unit xyzw；固定根 Center 朝向、Bone 输出和状态旋转共同使用。 |
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
| `cpu_native_kernel.py` | E3 显式 native kernel adapter；只允许 `data_path_only=True`，把 compiled/frame POD 交给独立 C++ owner，并以独立开关暴露已验证的 integration/Distance/Center frame-pose/Center evaluator slice；完整 solver 未就绪时拒绝 product step。 |
| `frame_compile.py` | 各 partition 冻结 frame snapshot 的纯校验与 logical index view 打包；不读取 Blender、不拥有历史或 backend。 |
| `shadow_pipeline.py` | E1 显式 opt-in 的 capture -> fragment -> compile 与旧静态结果对照、阶段计时；不解算、不写回、不拥有 backend。 |
| `domain_parameters.py` | resolved 参数 -> 热更新 parameter packet；不改变 topology layout。 |
| `frame_capture.py` 及 setup adapter | Blender 主线程逐 partition frame snapshot。 |
| `frame_compile.py` | snapshots -> domain frame packet；纯数据校验与 pack plan。 |
| `backends/contracts.py` | create/update/step/read/inspect/dispose 接口。 |
| `backends/cpu.py` | 新 CPU domain ABI 的薄适配；不读 Blender。 |
| `backends/gpu.py` | 将同一 IR 转成 GPU 资源和 dispatch；不改变 authoring 合同。 |
| `domain_output.py` | 纯 host domain output + output map -> target-local offset commands；不读 Blender、不发布事务。 |
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

### 当前主线与真实混合执行顺序

本轮架构工作的起点不是抽象地“重写 solver”，也不是先追求 CPU 极限性能，而是解决 MeshCloth 多代理自碰的结构性重复：多个 task 开启跨 task 碰撞时，既各自运行内部 self 流水，又复制 primitive 到 aggregate 再做一次 grid/candidate/contact。产品需要的是多个代理在同一个 MeshCloth 粒子域中自然互碰，而不是更快地维护两套碰撞流水。

因此因果链固定为：

```text
MeshCloth 多代理自碰重复
  -> 多 Object 编译为一个统一粒子域
  -> partition 参数、Center/Anchor/Teleport 与输出所有权显式化
  -> 同域 self collision 和多目标原子写回
  -> 后端中立 SoA、pass 依赖、容量和 IO 合同
  -> 未来 GPU persistent domain / dispatch
```

E 阶段描述功能门禁，P 阶段描述穿插其中的性能与后端工作；它们不是两条做完一条再做另一条的队列。真实实施顺序如下：

| 顺序 | 合并阶段 | 当前交付 | 明确不做 |
|---:|---|---|---|
| 1 | E0-E2 + P1-A 前半 | 冻结 partition、capture、compile、logical/physical identity、参数 SoA 和 output map；已完成。 | 不创建 fused runtime，不改产品 task。 |
| 2 | E3 + P2 分区状态 + P3 + P6-A | 已完成单 source 纯 native CPU reference、每 partition Center/Anchor/Teleport、完整 pass 顺序和 V0 tolerance；同时冻结 GPU 可复用的数据/pass 基础边界。 | 不建 CPU worker/job DAG，不做产品切换。 |
| 3 | P0（当前入口） | 在完整 step 骨架上接入原生固定槽阶段计时，得到 constraint、collision、self 各段证据；计时关闭必须零时钟读取和零诊断分配。 | 不依据尚未拆开的总时长猜优化项。 |
| 4 | P1-B | 建立保守失效的 source observation cache，消除普通热帧静态全量扫描。它不改变数值语义，可在 E4 前独立验收。 | 不把不可靠 depsgraph 标志伪装成完整 revision。 |
| 5 | E4 + P2 + 证据驱动的 P5 | 执行多 source fused CPU domain，一次 whole-domain self 流水覆盖同/跨 partition；接入差异化粒子与约束参数。只做 P0 已证明的低风险布局/容量优化。 | 不保留普通多代理的 aggregate 双流水，不做粒子域 CPU 并发。 |
| 6 | E5 + P1-A 后半 | 先闭环多目标结果事务，再接产品 collector、隐式/显式覆盖和可读 fusion report；通过 soak 后切换 MeshCloth 主路径。 | 不静默回退为 `N Object -> N task`。 |
| 7 | E7-CPU | 删除已经被新 CPU 路径替代的 MeshCloth 隐式拆 task、aggregate 常规路径和 V0 兼容层；保留有证据需要的显式 fallback。 | 不等待 GPU 才清理已经失去所有权的 CPU 旧路径。 |
| 8 | P6-B（贯穿 2-7，最终收口） | 把已落地的 SoA、pass 读写集、buffer 容量/溢出、增量上传、CPU tolerance 和单向 writeback 汇成 GPU implementation package。 | 不因此创建 GPU runtime，也不让 CPU 为 GPU 准备发生不可解释退化。 |
| 9 | E6（未来独立里程碑） | 在统一域产品路径和规模基准稳定后，实现最小 GPU 原型并测 `2k/10k/50k/100k` 收益曲线，再决定完整覆盖顺序。GPU 是既定长期方向，但不是当前 E3-E5 的交付时限。 | 不以单个 1760 粒子样本或只报 kernel 时间宣称成功。 |

P4 CPU 并发不在默认实施序列。只有未来平台约束使 GPU 路线不可用、并且 P0 证明某个无写冲突 kernel 的收益足以覆盖长期维护成本时，才允许作为单独决策重新打开；当前实现不得为它预埋 worker object、grain threshold 或调度 DAG。

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

完成状态：E3 已满足退出条件，但只作为单 source CPU reference。`DomainV1` 拥有独立 lifecycle、frame/parameter SoA、partition Center/Anchor/Teleport history、完整 native pass 顺序和 post/history；共享 kernel 覆盖 Center pose/shift/evaluator、分区 inertia、integration、Tether、Distance、Angle、Bending、point/edge/self collision、Motion 与 post。Frame 校验、失败回滚、Reset/Keep、paused/catch-up、Fixed prediction 时序、scheduler power、单 target output 数学和 debug-off 零 readback 均由双 ABI 固定夹具锁定。`cpu_native_kernel.py` 的 reference endpoints 仍不是产品 step；V0 solver、slot、Physics World 和 writeback 在 E4/E5 通过前不导入该适配器。

稳定设计约束：Angle 必须消费 baseline parent 与 line `start/count/data`、StepBasic pose 和逐粒子 restoration/limit，不能退化成二元 endpoint 表；Angle Restoration 乘 scheduler angle power，Angle Limit 不乘。Tether rest 每个 substep 来自 StepBasic；Mesh point collision 的 base position 与 BoneSpring soft sphere 分离；point/edge 互斥；self thickness 按双方总厚度解释。Center 粒子状态必须区分 position reference、state velocity 和 real velocity，Fixed 只在 prediction preparation 跟随动画。更细的踩坑与容差理由只保留在文末 E3 归档。

E3 native handoff 的执行顺序固定为：

1. 新增独立 `mc2_domain_cpu.hpp/.cpp` owner，只依赖后端中立的 `ProgramView`、`ParameterView`、`FrameView` 和 output view；不得 include `mc2_context_internal.hpp`，不得把 `PyObject*` 带入 kernel 核心。
2. owner allocation 一次复制或绑定经过 schema 校验的静态 SoA、constraint/primitive table 和 partition filter；所有数组记录 domain/layout signature 与 physical layout revision。
3. 每帧只接收 `MC2DomainFramePacketV1` 的 native view，先验证 domain/layout/frame/generation，再更新 per-partition Center/Teleport history；失败不能发布半更新 frame。
4. 全部数值 pass 在新 owner 内按固定顺序消费同一粒子状态，V0 context 只作为同输入 reference；禁止在 Python 侧复制 solver 公式或重排 pass。
5. native binding 只负责 ndarray -> POD view、handle 生命周期和 output envelope，不负责 authoring merge、Blender IO、slot 注册或 writeback。

E3 验收目录固定为以下四个已完成小段，后一段不得替代前一段：

| 小段 | 执行内容 | 必须留下的证据 | 明确不做 |
|---|---|---|---|
| E3-B frame-shift contract | 扩展 `MC2DomainFramePacketV1`/`FrameViewV1` 的 frame delta、simulation delta、time scale、skip count、running 状态和每 partition Center frame-shift 参数；增加独立 `Mc2CenterFrameShiftView`，输入/输出必须是 backend-neutral POD。 | ABI layout/signature 更新、非法输入整帧回滚、Reset/Keep/zero-substep 原子计数、同一 frame 的 old/current pose 对照。 | 不把 Python `center_state.py` 公式复制到 owner；不让 frame shift 读取 Blender 或 slot。 |
| E3-C Center ordering | 以同一 native kernel 固定 `anchor -> teleport 判定 -> Reset/Keep 分支 -> smoothing -> world inertia/speed limit -> frame pose shift -> Center evaluator` 顺序；所有历史在 scheduler 前提交，失败不发布半帧。 | `test_center_frame_shift_tier_a.py`、`test_center_anchor_shift_tier_a.py`、Teleport raw native tests 与 DomainV1 双 ABI 对照；debug-off readback 计数保持零。 | 不实现完整粒子 substep、collision 或 product slot 切换。 |
| E3-D single-source tolerance | 同一冻结 frame/parameter fixture 同时喂 V0 和 DomainV1，按 `step_reference_pipeline` 固定顺序比较 Center frame pose、shift、rotation、velocity history、integration、Tether StepBasic rest、Distance A、Angle、Bending、Distance B、Motion、Reset/Keep、paused/catch-up 和零子步结果。 | 固定 tolerance 摘要、有限性/确定性重复跑、端到端 V0 oracle；误差来源必须按 pass 标注，Tether 必须证明 rest 来源是 StepBasic，Angle/Motion 必须有分支级结果。 | 不用更新后的产品差异 fixture 掩盖旧/新差异；不在 tolerance 之前删除 V0。 |
| E3-E performance gate | 关闭所有 Center/debug 请求时确认无额外 frame-shift scratch、时钟读取或 readback；打开显式 slice 时只测该 slice。 | py311/py313 headless、Blender 4.5 debug-off soak、native allocation/readback counters。 | 不在 E3 内做 CPU worker/job DAG 或 GPU runtime。 |

E3-B 的字段进入顺序也固定：先更新 domain IR 与 frame compiler，再更新 native ABI/binding，随后才接 DomainV1；任何只改 binding 或只改 Python 的临时兼容字段都不得进入提交。E3-C 的历史提交必须把 Center frame、anchor、teleport 和 smoothing 的 old/current state 作为一个事务交换，不能由 renderer 或 debug snapshot 重建。

E3 native 合入门禁已经满足：新 owner 能在无 Blender 对象的 C++/headless fixture 中 create/update/step/read/dispose；创建或 frame 校验失败时资源计数归零；单 source 与 V0 的位置/旋转、Center/Teleport、完整约束/碰撞和 post history 在固定 tolerance 内一致；debug-off 不触发额外 readback。`cpu_backend.py` 仍只作为 E4/E5 的 reference backend，直到产品 collector、whole-domain self 与多目标事务完成。

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

### E6：未来 GPU backend 原型与收益门禁

E6 是确定的长期方向，但作为独立后续里程碑排期；它不阻塞 E3-E5 的统一域产品交付，也不要求当前立即实现 GPU solver。当前阶段只完成 P6-A/P6-B 的后端中立准备：同一 `MC2CompiledDomain`、frame/output contract、pass 读写集、buffer 容量/溢出、增量上传边界和 CPU reference tolerance。

未来进入 E6 时，先实现 integration + Distance + whole-domain self-collision 的最小代表原型，保留 CPU reference 对照；通过规模曲线和传输成本决定剩余 pass 的覆盖顺序，而不是一开始复制完整 CPU solver。

退出条件：

- 25 ms 级纯数值代表场景有明确接近或达到 5 ms 的证据，或者规模收益曲线证明粒子量提升一个数量级仍优于 CPU；
- upload/readback 单独计时，不能只报告 kernel 时间；
- 结果误差、确定性范围、设备丢失和 CPU fallback 合同明确；
- 若收益不足，不污染生产 node/data contract，可完整撤下 backend。

### E7：迁移收尾

E7 按所有权分两次收口。E5 通过长期资产回归后立即执行 E7-CPU：完成 BoneCloth/BoneSpring collector 迁移评估、删除 MeshCloth 旧隐式拆 task 路径、更新蓝本和声明、清理已被统一 CPU domain 替代的 V0 兼容层；这部分不等待 E6。未来 GPU 产品化后再执行 E7-GPU，删除原型适配、临时 readback/fallback 和已经被正式 backend owner 取代的资源路径。任何旧实现都只能在替代路径有长期证据后删除。

最终状态不是“旧单 task solver + 新 fused solver”长期双轨。单 Object 是统一 domain 只有一个 partition 的退化情况；C++ 数值层只拥有一个 whole-domain program、一个 particle state owner 和一条 pass sequence。MeshCloth、BoneCloth、BoneSpring 可以保留不同的 capture/static fragment/result adapter，但不得各自复制粒子积分、约束、碰撞、Center 状态机或 backend 生命周期。若某个 setup 尚未达到全功能等价，它留在迁移清单中并阻止对应旧 owner 删除，不能据此把双模式宣布为目标架构。

E7-CPU 的删除对象至少包括：

- 旧 `MC2NativeContextV0` 的产品 owner、创建/update/step/read/dispose binding，以及只为该 owner 存在的 Python adapter；
- 普通 MeshCloth 多代理的 `Mc2InteractionV0` aggregate copy/build/solve/scatter 路径；只有经产品明确保留且无法融合的兼容 fallback 才能独立存在，并必须有调用计数和移除条件；
- `List[Object] -> N hidden task`、单对象专用 slot/cache identity 和绕过 compiled domain/output map 的写回分支；
- 已被共享 kernel 或 DomainV1 接管的重复 Center、integration、constraint、collision、debug readback 实现；
- 迁移期 `data_path_only`、slice 开关、shadow solve adapter 和双路径结果翻译层。

删除采用“测试迁移”而不是“测试删除”。现有证据按下表复用：

| 现有资产 | 双跑期用途 | 删除 V0 后的归属 |
|---|---|---|
| `test_center_*_tier_a.py` 与 `fixtures/tier_a/center_*` | 同一 fixture 对照 Python/Tier A oracle、V0 和 DomainV1 的 Center/Anchor/Teleport/负缩放结果。 | 直接验证共享纯 native Center kernel 与 per-partition domain history。 |
| `test_particle_step_tier_a.py`、`test_distance_tier_a.py`、`test_bending_tier_a.py` 及 Motion/Tether/Angle fixture | 锁定 pass 顺序、系数、exact/tolerance 与边界条件；旧/新 backend 使用同一输入。 | 继续锁定共享 kernel 和 whole-domain step，不保留 V0 runner。 |
| `_native/tests/test_mc2_*_native.py` | 每提取一个 kernel，原测试先同时证明 V0 wrapper 与新 owner 调到同一实现。 | 改为直接 kernel/DomainV1 测试；只测试已删除 ABI 的 case 同提交移除。 |
| `test_domain_ir.py`、`test_domain_compile.py`、`test_frame_compile.py`、`test_cpu_backend.py`、`test_cpu_native_kernel.py` | 证明 schema、identity、失败原子性、生命周期和单/双 partition 隔离。 | 成为统一 owner 的长期合同测试。 |
| `capability_matrix.py`、`acceptance_assets_v1.json`、Mesh/Bone constraint/mixed-output/self-interaction Blender soak | 在同版本资产、帧段和参数下分别运行 V0 与新路径，比较确定性摘要、有限性、阶段计数和允许误差。 | 后端切换移除后仍原样运行，证明产品能力没有因迁移缩窄。 |
| `test_mc2_domain_cpu_native.py` 与 E2 双 Mesh fixture | 覆盖单 partition 退化、双 partition 状态隔离、同/跨 partition self、过滤和输出映射。 | 扩展为统一粒子域的核心回归套件。 |

删除提交的硬门禁：py311/py313 全部纯 Python/native 测试通过；Blender 4.5 capability matrix 无缺项；D-01 至 D-10 与代表 soak 的同输入结果在已声明 tolerance 内；单/双 partition、Reset/Keep、Anchor、参数热更新、碰撞、自碰、final intersection、debug-off 零 readback、多目标原子失败均有自动证据；统一路径性能不因 GPU-ready 数据边界发生无法由实际工作量解释的显著退化。最后增加架构审计，禁止生产代码重新出现 V0 owner/binding、hidden task 展开或普通 aggregate 路径。仅“新测试通过”但旧路径仍被产品导入，不算 E7 完成。

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
  test_cpu_native_kernel.py          # E3 Python/native data-path 已有
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
### E3 阶段归档：统一 native reference 的特殊处理与决策

E3 的目标是证明统一 DomainV1 能按 V0 的真实流水线完成单 source reference，不把“某个 slice 能运行”误报成产品 solver 已等价。固定顺序为：

`Center frame-shift -> Center evaluator -> Center particle inertia/prediction preparation -> integration -> StepBasic/Tether -> Distance A -> Angle -> Bending -> point collision -> edge collision -> Distance B -> Motion -> self collision -> post/history`。

本阶段已经有 py311/py313 的 V0 对照证据：StepBasic 姿态、Tether 到 Motion 的连续两帧、Mesh point collision、Mesh edge collision、Mesh self collision、无碰撞完整事务、各碰撞分支 post 后的 `real_velocities` 历史，以及带 Fixed 根、非零 depth inertia、Tether、Distance A/B 和 post/history 的 Center 两帧事务。每个碰撞槽都必须显式传入 mapping 或 `None`；self collision 还必须携带上一状态位置。point 与 edge 是 V0 的互斥模式，不能把两者同时打开当作“完整模式”。

特殊处理与踩坑点：

- StepBasic 不是 Angle 的附属输入。早期 Angle 偏差来自缺少 baseline local pose 和 parent-first 重建，不是 Angle 投影公式；因此 compiled IR 显式保存 baseline local positions/rotations，由 native 共享 kernel 生成 StepBasic。
- Tether 是否启用不能由“拓扑表存在”推断。测试曾用 V0 的 test-only disable gate，而 Domain 按拓扑无条件执行，造成假性差异；正式 collector/parameter packet 必须携带显式 enablement 和 provenance。
- MeshCloth point collision 使用零 base position；animated base pose 仅属于 BoneSpring soft-sphere 语义。V0 对照必须注册 source radius multipliers，不能让测试 harness 静默回退为全 1。
- self collision 的厚度是两个 primitive side 的总和；双三角 fixture 要传 `0.04` 而不是单侧 `0.02`。V0 持久接触参数使用半精度量化，Domain 共享 kernel 保持 float32，因此位置容差固定为 `1e-4`；post 用 `dt` 求速度会放大这项量化差，self 的速度历史单独使用 `1e-3` 绝对容差，point/edge 不放宽。
- Distance inverse mass 必须从 depth 与 collision friction 生成，Fixed 粒子为零；Distance/Bending 的 simulation power 是每次 pass 的显式输入，不能在 Python 侧复制缩放 buffer。
- scheduler 统一负责从 `simulation_delta_time` 生成 V0 的 Y/Z/W power（Distance/Bending、integration、Angle），并通过 `MC2SubstepPlan` 一次交接 dt、frame interpolation、final 标记和 powers；单 context、interaction group 与 Domain reference 不得各自复制 `90 * dt` 公式。该生产者只交接 substep 数值，不拥有 setup 的碰撞模式或粒子参数。
- Angle 的 endpoint 形态必须按 V0 分开：integration、Distance/Bending 接收独立 scalar power；Angle Restoration 的逐粒子强度乘 `powers.angle`，Angle Limit 是当前 bound，直接使用按 depth 采样的逐粒子限制值，不乘该 power。早期 handoff 曾把两者一起缩放，开启 Limit 的 full V0 tolerance 暴露了偏差；`reference_step.py` 现已拆开，并以 full Angle Limit + Motion/Backstop 分支锁定。
- `animation_pose_ratio` 会影响 StepBasic、Tether 和 Angle，但不属于既有 V0 native 固定 float 数组。它作为 host/domain 元数据参与 effective parameter signature，并进入 compiled partition SoA；不得为接通 Domain 而扩写或重排 V0 ABI，也不得在 reference harness 中继续写死为 0。
- E3 Center 两帧 fixture 先发现 DomainV1 只保存 `center_shift_vectors/history`，没有把 shift 应用到粒子位置、velocity reference、state velocity 和 rotation；随后又发现 owner 把 state velocity 与 post 的 position reference 混为一个数组。最终提取共享 `apply_particle_frame_shift_mc2`，并在 Domain 中显式分离 `state_velocities`、`velocity_reference_positions` 与 `real_velocities`；分区 Center inertia 通过 `particle_partition_index` 一次遍历统一 SoA，不按 partition 重扫粒子。
- Fixed 粒子不能在 `update_frame` 时提前切到新动画位置，否则随后执行 Center frame-shift 会产生双重位移。它在普通帧保持持久状态，直到 prediction preparation 才跟随 StepBasic 并清零 state velocity；Reset 分区仍在 frame 事务中立即重置。`prepare_prediction_state` 同时服务 Center inertia 路径和独立 integration slice，避免 Python 复制顺序逻辑。
- Center 组合夹具必须保留真实 pin 根。把 pin 移除会让所有 Move 粒子发生刚体式平移，Distance 即使启用也无需修正，不能作为约束证据。最终夹具使用非零 depth inertia、Fixed 根、Tether 和两次 Distance，且断言 inertia 与 Distance 都产生实际位移；normal、Keep、Reset、catch-up 均继续比较 post/history，paused 因零子步只比较 frame-shift 事务。Keep/Reset flags 固定为 `3/5`。
- MC2 源码 oracle 与产品 effective 参数必须分层保存。BoneSpring 源码 fixture 仍忠实保留序列化的 bending stiffness/method，产品因 Line topology 没有 triangle 而将两者归零；测试以显式 product override 记录这项有意差异，禁止篡改源码 fixture 或让旧矩阵倒逼无效 pass 回归。
- `reference_step.py` 只把 scheduler 的 substep plan、frame 权重和 compiled 参数表编译成 native reference settings；它暂时严格限制单 partition，动态 collider mapping 由 Physics World 提供，参数 mode 不匹配时在 native 前拒绝，不能静默关闭碰撞。
- DomainV1 `prepare_step_basic_pose()` 默认从 compiled partition SoA 读取 `animation_pose_ratio`；显式传值只用于 reference fixture/诊断 override。多 partition 在统一的 per-partition StepBasic 调用合同落地前不得把不同 ratio 压成单值。
- E3-E 的 native 计数证据要求 `inspect()` 和 debug-off data-path 不调用 `mc2_domain_cpu_v1_read`；只有显式 `read_debug_state()` 或 `read_output()` 才允许 readback。该计数在 py311/py313 adapter 测试中保持 0/1/2 的明确序列。
- 产品节点入口的 Blender 合同测试已证明：`热点时长调试=False` 时不创建 MC2 timing session；即使 socket 为 True，只要模拟步 `启用=False` 也不创建 session。通用 OmniNode 计时端口关闭时同样不读取 `perf_counter`，而 solver 的阶段 checkpoint、求解明细和聚合上下文只在显式 session 存在时执行。关闭态因此只有常数级布尔判断，不创建 profile、不读取计时时钟、不构造分步诊断。
- 旧 reference 只做到位置提交，漏掉了 V0 post 的速度/摩擦历史。现在 post 是显式事务尾段，写入 real velocity、velocity history 和 old position；没有 post 证据就不能声称完整 V0 等价。
- 测试应通过 `step_reference_pipeline_full` 验证顺序，不得用手写 integration 后再单独调用碰撞 endpoint 伪造完整流水线。
- full reference 在首个 native pass 前校验 `collision_mode`、`self_collision_enabled` 与实际 mapping 是否一致，并拒绝同时提供 point/edge；这条拒绝必须保持 `step_count` 和粒子状态不变，避免错误的 mode handoff 先执行半条流水线。
- `inspect()` 只返回 metadata；`real_velocities/world_normals` 只能由显式 `read_debug_state()` 请求。任何 debug-off 或普通结果路径都不得为了可观察性隐式 readback。
- `domain_output.py` 已证明 logical 粒子按 `output_target_index/output_source_element` 拆分，并按各 partition 的 world linear 逆变换生成 object-local offsets；它只生成不可变 command，E5 才负责多 target 原子发布。
- 单 partition 退化时，Domain writeback command 与 V0 `MC2ResultCandidateV1` 对同一 frame linear/world positions 生成逐 float32 相同的 object-local offsets；这关闭 E3 输出数学等价，不代表 E5 多 target 发布事务已完成。

E3 已关闭：单 source DomainV1 的完整 pass 顺序、Center 跨帧 normal/Keep/Reset/catch-up、零子步暂停、非零 inertia + Tether + Distance 组合、post/history、scheduler/参数 handoff、单 target writeback 数学、debug-off readback 和热点计时关闭态均已有固定证据。该结论只证明 CPU reference 的单 source 全功能等价，不代表多 source 已在同一 owner 中运行，也不授权切换 Physics World 产品 owner。下一执行入口是 P0 与 P1-B，再完成粒子级覆盖合同并进入 E4 whole-domain self；多 target 原子发布仍属于 E5。后续每完成一个大阶段，只在本节增加整理后的决策与踩坑结论，不记录逐提交过程。
