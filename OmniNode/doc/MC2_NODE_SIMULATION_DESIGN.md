# MC2 节点模拟设计

本文规划 MC2 新一代节点数据流和 authoring 分层。它解决的不是某一个 socket 的命名，而是明确三个边界：

1. Physics World 的公开 `solver + list[task]` 契约；
2. MC2 内部 MeshCloth、BoneCloth、BoneSpring 三种 setup adapter 的收集和装配；
3. 单个代理的 source、profile、隐式覆盖、显式覆盖、partition 状态和输出映射。

本文是目标设计，不描述当前已经完成的行为。当前生产节点和 `MC2TaskSpec` 仍以 `MC2_BLUEPRINT.md` 及代码事实为准。

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
5. merge 后的完整 profile/runtime array只能在 collector/compiler 边界生成一次，不能每个 node 都复制一份。

## TaskSpec 与 runtime 编译目标

新的 `MC2TaskSpec` 目标形态应从“sources + 一个 profile/task_parameters”扩展为：

```text
MC2TaskSpec
  domain identity / setup type
  tuple[MC2PartitionSpec]
  domain parameters
  fused topology ranges
  compiled particle coefficients
  compiled constraint coefficients
  output/writeback plan
```

`MC2PartitionSpec` 至少持有：

- source identity、raw snapshot key、partition id；
- Object/Data/Anchor frame owner；
- Center/Teleport history key；
- particle range、constraint range、output mapping；
- sparse source/profile/task overrides；
- collision group/mask 与 enabled 状态。

编译器输出的 partition ranges 必须稳定排序，且与 debug、result、writeback 使用同一索引表。source 删除、重排、拓扑变更或兼容性变化通过 staged replacement 生成新的 task/context，不能在 live context 中原地重编号。

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
                                -> solver prepare
                                -> per-task/fused native context
                                -> result streams
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
- 最终 native context、particle range、writeback owner 是什么？

collector 的状态输出是轻量编译摘要，不读取 native 中间态；MC2 debug node 继续读取 solver slot 的冻结 native snapshot。两者不能混合：前者解释“装配了什么”，后者解释“解算发生了什么”。

## 实施优先级

1. 新增 immutable `MC2PartitionEntry`、sparse patch、merge report 和纯 Python compiler，不改变当前 native ABI。
2. 为 MeshCloth 增加显式对象节点、覆盖节点和 collector；先支持单 source collector，确保数据流和结果合同打通。
3. 接入 implicit registry，验证显式/隐式同源合并、冲突和 staged replacement。
4. 扩展 `MC2TaskSpec`/topology builder 为 partition ranges，collector 先生成一个 source-concatenated fused spec。
5. 将 fused spec 接到 native context，保持单线程 reference 和现有 debug/writeback。
6. 将 BoneCloth/BoneSpring 的 source adapter 迁移到同一 entry/collector 框架，保留 setup-specific topology。
7. 删除 MeshCloth 旧的 `List[Object] -> N 个 task` 隐式拆分路径，更新声明、测试和蓝本。

在第 1-4 步完成前，不应实施 GPU backend、粒子域 CPU Split Job 或隐式 task 自动融合；否则 node contract、runtime ABI 和性能实验会同时变动，无法判断收益来源。

## 验收矩阵

| 场景 | 必须证明 |
|---|---|
| 一个显式 Mesh Object | 一个 partition、一个 collector domain、一个 task、一次写回。 |
| 多个显式 Mesh Object | 多个 partition、一个 fused task、无跨 source 结构约束串线。 |
| implicit + explicit 同源 | stable id 合并一次，字段优先级和来源可观察。 |
| 同字段双显式覆盖 | 明确冲突，不静默 last-writer。 |
| 一个 source 禁用 | entry 保留、active domain 不含它、其他 partition identity 不漂移。 |
| topology/source 删除 | staged replacement，旧 context 正确 dispose，新 domain 原子发布。 |
| Mesh/Bone/BoneSpring 混合 | 三种 collector 输出不同 setup task，统一 step，不错误融合 setup。 |
| Require Fusion 不兼容 | 在 collector 边界报告具体字段，不创建隐藏 aggregate fallback。 |
| debug/status | 装配摘要与 native 中间态分层，debug-off 不产生额外 native readback。 |

## 与现有契约的关系

该设计遵循 Physics World 的既有边界：spec build 可以由独立节点或 solver 内部完成；solver step 仍一次接收多个规范化 task；solver 不写 Blender，结果通过 result stream 交给统一 writeback。新节点只是把 MC2 setup 内部原来混在 task 函数中的 spec build/collect/compile 职能显式化，不新增第二个 world step，也不把 MeshCloth、BoneCloth、BoneSpring 拆成三个 Physics World solver。
