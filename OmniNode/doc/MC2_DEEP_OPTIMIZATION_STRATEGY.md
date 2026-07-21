# MC2 深度优化策略

本文规划 OmniNode `physicsWorld.mc2` 的性能优化、MeshCloth 多代理融合、native 并行和未来 GPU 数据边界。它是实施前的策略文档，不把尚未落地的方案写成当前能力；稳定的现状合同仍由 `MC2_BLUEPRINT.md` 维护。

## 结论摘要

当前重资产的主要损耗不是 Blender 写回，也不是 Python 批次编组，而是三个相互独立的问题：

1. 每个热帧仍完整读取 Blender Mesh 静态数据并重新计算 fingerprint，稳定占用约 `16-18 ms`。
2. native 单线程求解在 1760 粒子、6 个 substep、495 个 collider 的样本中占用约 `25-39 ms`，但现有计时只看到整个 native group，尚不能判断约束、外碰和 self collision 各自比例。
3. 两个 MeshCloth task 开启跨 task self collision 后，native 求解增至约 `88-91 ms`。当前实现会先运行各 context 的内部 self 流水，再把所有 self primitive 复制进 aggregate context，重新建 grid、候选和 contact，最后散回；这不是低成本的跨岛接触。

因此实施顺序固定为：

```text
可靠测量
  -> 消除热帧静态全量扫描
  -> 多 Object 编译为一个 fused MeshCloth context
  -> backend-neutral 数据与 pass 合同
  -> native 纯计算边界与释放 GIL
  -> 可选的 context Batch 或 GPU backend 评估
  -> 数据布局、SIMD和目标 backend 验证
```

不能先用多线程掩盖重复工作。多线程也不能替代 fused context；它只能加速仍然必要的工作。

## CPU并行与GPU前置的路线决策

当前不把“粒子域 CPU Split Job”当作默认优化方向。它的潜在收益存在，但工程风险、数值风险和长期维护成本都明显高于 task 级并行；同时它为 GPU 准备的数据合同帮助有限，不能把面向 CPU worker 的抽象误当成 GPU 前置。

| 路线 | 初始难度 | 即时收益 | 数值/维护风险 | 决策 |
|---|---:|---:|---:|---|
| 静态观察缓存 | 中 | 高，直接回收 `16-18 ms` 热帧扫描 | 失效遗漏风险，可用保守审计控制 | 立即做 |
| 独立 context 粗粒度 Batch | 中 | 中，适合互不交互的 task | GIL、context所有权、共享 collider 快照 | 作为有限候选 |
| 粒子域 CPU Split Job | 高到很高 | 中，取决于可并行 kernel 占比 | 写冲突、迭代顺序、确定性、任务图和调试复杂度 | 暂缓，默认不做 |
| backend-neutral SoA/pass 合同 | 中到高 | CPU即时收益低 | 主要是边界设计风险 | 优先做，服务 CPU/GPU |
| 真正 GPU backend | 很高 | 足够大规模时可能很高 | 上传/同步、容量、驱动、数值差异、双后端维护 | 通过门槛后再做 |

这里的“GPU 前置”指清理数据和执行边界，不等于现在就实现 GPU solver。它的价值是让粒子、约束、partition、pass 依赖和结果所有权变得明确；未来 GPU 可以直接把这些合同映射成 dispatch，而不必继承 CPU worker 的类层次、grain 切分和线程同步模型。

### CPU Split Job 的收益上限粗算

使用 Amdahl 上限 `1 / ((1-P) + P/N)`，假设 8 个 worker、忽略调度和内存带宽损耗：

| 可安全并行比例 P | native理想加速 | 当前 `25-39 ms` 理想结果 | 判断 |
|---:|---:|---:|---|
| 40% | `1.51x` | 约 `16.5-25.7 ms` | 收益有限，不值得污染全部kernel。 |
| 60% | `2.11x` | 约 `11.8-18.5 ms` | 有价值，但要求多数热点已无共享写冲突。 |
| 80% | `3.33x` | 约 `7.5-11.7 ms` | 必须改造约束/self核心语义，工程风险最高。 |

真实结果还会低于该表，因为 worker barrier、cache line竞争、线程局部buffer合并、排序和小批次都会消耗预算；整帧收益又会被 Blender engine/redraw、静态观察和其他节点按 Amdahl 再次压低。因此在 native 内部阶段比例未知时，不能用“8核”推导接近 `8x` 的产品收益。

GPU 对 prediction、primitive生成、grid/candidate 和大规模约束 pass 可能获得远高于 CPU worker 的吞吐，但 1760 粒子是否足以摊薄 dispatch、上传和同步尚未证明。GPU 路线的优势首先是规模上限和数据并行模型更匹配，不是对当前资产预先承诺固定倍数。

### 为什么粒子域 CPU Split Job 是危险项

当前 native step 不是若干互不相关的数组循环，而是一个有明确顺序的可变状态流水：

```text
prediction
  -> Tether / Distance / Angle / Bending
  -> Point / Edge collision
  -> Distance pass 2 / Motion
  -> self primitive / grid / candidate / contact
  -> post / final intersection
```

主要风险有四类：

1. **共享写入**：Distance、Bending、Angle、Edge 和 self contact 都可能对同一粒子写 correction；“每个粒子一个 worker”本身不能保证无冲突。
2. **算法变化**：颜色组会改变约束应用顺序，Jacobi/线程局部累积会改变收敛速度、刚度手感和接触结果；这已经不是透明性能重构。
3. **隐藏状态**：当前计数、debug capture、contact history、intersection history 和可变 vector 容量都属于同一个 context，拆分后需要新的所有权和提交协议。
4. **长期抽象负担**：worker pool、job DAG、barrier、grain threshold、局部缓冲、deterministic merge 会扩散到每个 kernel 和 debug 映射，未来 GPU 并不会复用这些 CPU 调度对象。

所以“能不能并行”不是首要问题；首要问题是是否愿意为每个受影响 kernel 建立新的数值和所有权合同。当前答案是：除非分阶段 profiling 证明单线程 fused context 仍然无法达到目标，否则不承担这项复杂度。

### CPU 侧只保留一条低风险并行候选

在 `step_native` 完成纯 C++ 边界后，可以评估互不 interaction 的 context 级 Batch Job：

- 每个 context 独占自己的 native state，worker 之间不读写彼此的 context；
- collider snapshot、时间参数和世界只读数据在进入 worker 前准备好；
- 全部 worker 在 native 调用返回前 join；
- 一旦有跨 task interaction，该组回到 fused 或现有 barrier 路径；
- 任务数量少、粒子量小或 `static prepare` 占比高时自动保持串行。

这条路线能在不改 constraint kernel 语义的情况下获得有限收益，但无法解决用户当前最关键的跨 task aggregate 放大，所以优先级低于 fused context。

## 已确认的性能事实

### 代表资产

两份 2026-07-21 热点捕获使用同一类重资产：

- `tasks=2`，均为 MeshCloth。
- `particles=1760`。
- 时间线 `dt=33.333 ms`，共 6 个 substep、3 个 native batch。
- `colliders=495`。
- debug task 为 0，context 全部走 hot reuse，Mesh/Bone 写回不是热点。

关闭跨 task self collision 时：

| 阶段 | 观察范围 |
|---|---:|
| MC2 总计 | 约 `47-58 ms` |
| 静态准备 | 热帧约 `16.4-17.3 ms`，首窗口含一次 `44 ms` 峰值 |
| native 组求解 | 约 `25.3-38.5 ms`，后段峰值约 `44.8 ms` |
| 帧与调度准备 | 约 `1.2 ms` |
| 结果构建 | 约 `0.3-0.4 ms` |
| Physics Writeback | 约 `0.2-0.25 ms` |

两个 task 开启互碰且形成一个 owner pair 时：

| 阶段 | 观察范围 |
|---|---:|
| MC2 总计 | 约 `105-109 ms` |
| 静态准备 | 约 `16.0-16.4 ms` |
| native 组求解 | 约 `87.6-91.2 ms` |
| Python任务同步/配置 | 约 `0.13-0.15 ms` |
| 整帧 | 约 `134-144 ms`，约 `6.9-7.5 FPS` |

这组数据能证明跨 task native 路径是额外热点，不能证明 fused context 的精确收益。用户把多个代理真正放进同一模拟对象后的“帧数约翻倍”属于重要人工观察，必须在新增 fused 生产路径后用同一资产、同一帧段正式复测。

### 当前 List Object 语义不是融合

`MC2 MeshCloth任务`虽然接受多个 Object 输入，但 `mc2/nodes.py::_mesh_cloth_tasks()` 当前对每个 Object 分别调用 `make_mc2_task_spec(..., [source])`。因此：

```text
List[Object]
  -> N 个 MC2TaskSpec
  -> N 个 solver slot
  -> N 个 MC2NativeContextV0
```

它只是多输入的 authoring 便利，不是一个多 source task。该行为是未完成阶段的妥协，应由真正的 fused MeshCloth task 取代。

### 静态准备为何在热帧仍昂贵

`solver.py` 对每个 active task、每一帧调用 `prepare_static_inputs_for_task()`。Mesh 路径随后执行：

- `mesh.update()`；
- 全量读取 vertex position、normal 和 edge；
- `calc_loop_triangles()` 并读取 triangle/loop/polygon；
- 全量读取 active UV；
- 遍历顶点组取得 pin 和 radius multiplier；
- 调用 native 对上述 buffer 重新计算 static fingerprint。

fingerprint 相同时只避免后续 topology rebuild，没有避免本次 Blender 数据读取、分配和 hash。因此“context reuse”与“静态准备便宜”目前不是同一件事。

### 跨 task self collision 为何接近三倍求解

当前一个 substep 的相关路径为：

```text
context A: prediction + constraints + internal self grid/contact/solve
context B: prediction + constraints + internal self grid/contact/solve
interaction:
  copy A/B positions and old positions
  copy A/B point/edge/triangle primitives, AABB, thickness and inverse mass
  stable-sort aggregate primitives and rebuild aggregate grid
  generate candidates; inner loop rejects same-owner pairs
  build/solve cross-owner contacts
  scatter positions back to A/B
```

`self_owner_pair_allowed()` 确实拒绝 aggregate 内的同 owner contact，避免同一 task 被重复修正；但 aggregate 仍为所有 owner 的全部 primitive 建网格、排序并进入候选扫描。每个原 context 的内部 self grid 也已经单独运行。高成本来自重复空间结构、全量聚合复制、候选扫描与同步，而不是 Python 的 pair resolver。

## 产品架构决定

### MeshCloth 优先形成单一模拟域

多个会互相接触的 MeshCloth 代理应默认编译为一个 fused simulation context。一个公开 `MC2 MeshCloth任务` 表示一个布料模拟域，而不是“输入多少对象就产生多少隐藏 task”。

融合后的结构为：

```text
MC2 MeshCloth任务
  source partition 0 -> particle range / constraint ranges / output mapping
  source partition 1 -> particle range / constraint ranges / output mapping
  ...
  one native context
  one self broadphase/contact cache/intersection history
```

各 source 的 proxy topology 只做带 offset 的拼接。Distance、Bending、Tether、baseline 等结构约束不得跨 partition 自动生成；只有 self collision 可以在不同 partition 之间产生接触。这样既保留“多块独立布料”，又避免把它们当作多个完整 solver world。

### 不鼓励混合 setup 的粒子交互

产品主路径应清楚表达：

- MeshCloth 多代理：优先同一 fused MeshCloth task，通过统一 self collision 互碰。
- BoneCloth：保留自己的 task 内 self；不为“所有东西都能互碰”把它强行加入 Mesh aggregate。
- BoneSpring：继续不参与 cloth self/mutual collision。
- MeshCloth、BoneCloth、BoneSpring 可以在同一 Physics World 锁步运行，但“同 world”不等于“共享同一粒子碰撞域”。

用户应优先选择一种适合目标对象的 setup，而不是混合 setup 后依赖跨 task 碰撞拼装结果。确有不同 MeshCloth task 无法融合时，跨 task interaction 只作为有明确成本提示的兼容 fallback，不再是常规多代理工作流。

### Task、partition、particle、constraint 四级所有权

“把 task 参数全部变成粒子参数”会丢失状态所有权。融合需要四级数据，而不是只剩粒子数组：

| 层级 | 典型所有者 | 说明 |
|---|---|---|
| Context/Task | scheduler、substep、native context lifetime、统一 self broadphase、结果事务 | 决定一次如何推进整个模拟域，不能逐粒子变化。 |
| Source partition | Object/source identity、source transform、Anchor、Center history、Teleport state、输出对象与粒子范围 | 每个代理仍有自己的帧状态和写回目标；融合不等于共享一个 Object transform。 |
| Particle | depth、radius、mass/逆质量、damping、gravity response、friction、Motion/Backstop系数、collision group/mask、partition id | 由基础 profile、曲线和隐式覆盖编译成连续 SoA。 |
| Constraint | constraint type、端点/四元组、rest value、stiffness/compliance、owner partition、color/batch | Distance/Bending/Tether/Angle 的差异必须落在约束记录，不能只靠端点粒子参数猜测。 |

Center、Anchor 与 Teleport 不能简单下沉成粒子 float。它们是每个 source partition 的有历史状态系统；每个粒子只保存 `partition_id`，prediction 通过该 id 读取对应的 Center/Teleport 结果。

### 隐式粒子属性覆盖

未来的隐式覆盖应是编译步骤，不是 kernel 每次查询 Python/RNA：

```text
task base profile
  + source/profile override
  + vertex group / attribute override
  + depth curve sampling
  -> dense particle coefficients + dense constraint coefficients
  -> native static/config upload
```

第一版至少支持同一 fused task 内不同 source 使用不同 MeshCloth profile。编译器只为 kernel 真实消费的最终系数生成数组；没有差异的字段可保留 uniform 表达，出现覆盖时再物化 dense buffer。不得在 inner loop 中建立 variant/dict/字符串查找。

参数分类必须逐项完成：

- 可以直接粒子化：半径、阻尼、重力响应、摩擦、移动限速、Motion/Backstop最终系数、self质量权重。
- 必须约束化：Distance/Bending/Tether/Angle 的 rest、刚度、限制值和迭代批次。
- 必须 partition 化：Object/Anchor frame、Center惯性历史、Teleport模式/阈值/结果、源级启用状态、输出映射。
- 必须 context 化：时间推进、substep策略、统一 broadphase 生命周期、事务 generation。

如果某个字段不能在上述层级得到唯一 owner，就不能以“支持覆盖”为由先塞进 ABI。

### Fusion compatibility key

Task compiler 应先尝试融合，再根据明确的 compatibility key 自动拆组。第一版 compatibility key 至少包含：

- setup 必须都是 MeshCloth；
- 相同 scheduler/frequency/substep策略；
- 相同 self collision 算法模式与宽相实现；
- 相容的 collider scope 和 world transaction；
- ABI/schema 版本一致；
- 当前仍未下沉到 partition/particle/constraint 的 context-only 参数一致。

Object、profile、Anchor、Teleport阈值和输出目标不应永久成为禁止融合的理由；它们应由 partition 和隐式覆盖系统承载。暂未完成该承载时允许保守拆组，但必须在诊断中报告具体的不兼容字段，不能静默退回 N 个 task。

## 分阶段优化路线

### P0：补齐可行动的测量

现有热点开关应继续默认关闭，并在开启时增加 native 内部阶段计时。至少记录：

1. context begin / Center / prediction；
2. Tether、Distance pass 1、Angle、Bending；
3. Point/Edge external collision、Distance pass 2、Motion；
4. self primitive AABB/thickness 更新；
5. self grid sort/build；
6. candidate generation/dedup；
7. contact build/update；
8. 四轮 self contact solve；
9. final intersection detect/solve；
10. interaction aggregate copy/build/solve/scatter；
11. particle post 和结果准备。

计时采用 context 自有的固定槽或栈上记录，只有热点开关开启才读取时钟并发布；关闭时不得创建阶段 dict、格式化字符串或逐 contact 记录。控制台和节点浮层继续复用现有通用 timing renderer。

同时固定四组同资产对比：

| 组 | 目的 |
|---|---|
| A：两个 task，跨 task 关闭 | 现有独立 context 基线。 |
| B：两个 task，跨 task 开启 | 现有 aggregate 成本。 |
| C：手工 join 为一个 disconnected Mesh source | 当前单 context 的近似上限，但需注明 authoring/transform 差异。 |
| D：未来多 source fused context | 目标产品路径，必须与 A/B/C 同帧对比。 |

每组记录 warmup 后 p50、p95、峰值、candidate/contact 数、primitive 数、分阶段耗时、输出确定性摘要和人工视觉结果。只比较 FPS 不足以定位退化。

### P1：消除热帧静态全量扫描

这是最高置信度、最小数值风险的第一项实现工作。目标是普通连续帧不再执行 `mesh.update()`、`calc_loop_triangles()`、完整 `foreach_get`、顶点组遍历和全 buffer hash。

引入主线程 source observation cache：

- 以 source/data identity、depsgraph revision、相关 RNA/property revision 和 world generation 组成观察令牌；
- 缓存 raw snapshot、fingerprint 和 frozen topology；
- depsgraph Mesh 更新、编辑模式提交、UV/拓扑/坐标/法线变化、pin/radius group变化、对象替换、undo/load、schema变化时失效；
- 提供显式“保守审计模式”，低频或手动重新扫描并比较 fingerprint，用于发现漏失效；
- 无法证明 revision 完整时宁可针对该 source 退回扫描，不能全局假定不变。

验收目标：代表资产热帧 `静态准备 p95 < 2 ms`，且 topology/config/surface/geometry 各类修改仍在同帧或明确下一安全帧重建。当前约 `16-18 ms` 是可直接回收的预算，但实现前不承诺最终绝对帧率。

### P2：实现 fused MeshCloth context

分为四个小交付，避免一次改完所有 ABI：

1. **静态拼接**：多 source 生成稳定 partition 表、particle/constraint range、带 offset 的 topology 和输出映射。
2. **分区帧状态**：每个 source 独立读取 Object/Anchor frame，维护 Center/Teleport 历史；粒子用 partition id 消费。
3. **统一 self**：一次 primitive update、一次 grid/candidate/contact/intersection 流水同时覆盖同 partition self 与跨 partition接触；topology neighbor 只来自真实结构边。
4. **差异化配置**：接入粒子/约束隐式覆盖，去掉“必须同 profile 才能融合”的临时限制。

第一版应保留 source 粒子连续区间，便于写回、debug、CPU cache locality 和未来 GPU dispatch。删除 source、重排输入或 topology 变化必须通过 staged replacement 建新 context，再原子发布，不能在 live context 上局部错位。

融合后普通多代理不再进入 `Mc2InteractionV0`。旧 interaction 可以暂时服务于无法融合的 Mesh context，但必须统计 fallback 次数、参与 context、复制字节和 aggregate 各阶段耗时，以便最终判断是否继续保留。

### P3：先建立纯 native 边界，暂不承诺粒子域并行

Blender 官方的“Python Threads are Not Supported”限制针对 Python 集成和并发访问 Blender 数据，并不等于插件自有 C++ buffer 不能多线程。可接受边界是：

```text
Blender主线程 + GIL:
  读取RNA/depsgraph -> 验证句柄/参数 -> 形成插件自有buffer
native纯计算区:
  不访问PyObject、不调用bpy/Blender API、不改变Blender-owned内存
  所有worker在函数返回前join
Blender主线程 + GIL:
  翻译错误/统计 -> 发布结果 -> 写回Blender
```

当前 `mc2_interaction_v0_step_group` 和 `mc2_context_v0_step` 通过 `call_pyobject_api` 调用，binding 没有释放 GIL；core 内部还直接 `PyErr_SetString`。因此不能只在现有 lambda 外包一层 `gil_scoped_release`。

前置重构：

1. wrapper 在持有 GIL 时解析 Python 参数和验证 handle；
2. core step 返回纯 C++ status/error enum，不直接调用 Python C API；
3. `step_native(...)` 只访问 context-owned C++ state；
4. binding 在纯计算区使用 `nb::gil_scoped_release`；
5. 重新取得 GIL 后把 status 转成 Python exception。

单独释放 GIL不会让一个单线程 step 自动变快；它只是安全 worker pool、并发独立 context 和避免阻塞其他 Python 线程的必要边界。完成这一步后默认仍保持单线程 context solve，直到 P0 的内部计时证明需要更激进的方案。

### P4：保守的 CPU 并发边界

原版 MagicaCloth2 v2.14+ 的公开性能说明采用混合调度：小 cloth 用一个组件一个 Batch Job；重 cloth 使用阶段内 Split Job；超过约 300 proxy vertex 或启用 self/mutual collision 时倾向 Split Job。这个事实证明原版有内部 Split Job，但不构成 OmniMC2 必须复制该复杂度的理由；我们只借鉴“按负载选择调度粒度”的原则，不照搬 Unity Job API。

OmniMC2 的目标调度：

- 多个互不交互的小 context：作为 Batch Job 并行。
- 一个较大的 fused MeshCloth context：默认仍按单线程 reference 顺序运行；只有独立 kernel 经过计时和数值验证后才局部并行。
- self collision 或未来仍存在的跨 context barrier：显式依赖栅栏，但不因此自动引入粒子级 job DAG。
- 小数组低于 grain threshold 时保持单线程，避免调度成本大于计算。

若最终采用 context 级 Batch Job，使用 native 持久 worker pool，线程数量按物理核心、平台和场景阈值配置。禁止每帧 `std::async`/创建线程；禁止 worker 存活后异步访问已释放 context；world dispose、undo/load 和 addon unregister 必须先排空队列。

### 可直接并行与有写冲突的阶段

| 阶段 | 并行可行性 | 要求 |
|---|---|---|
| prediction、阻尼/重力、particle post | 高 | 按粒子连续区间拆分，每粒子独占写。 |
| partition Center/Teleport 计算 | 高 | 每 partition 独占状态；完成后 prediction 才能开始。 |
| primitive AABB/thickness | 高 | 每 primitive 独占写，最后确定性 reduce 最大尺寸。 |
| grid key生成 | 高 | 每 primitive 独占写。 |
| grid sort/run build | 中 | 评估并行 radix/Morton；必须稳定或建立新的确定性合同。 |
| candidate窄相 | 中高 | 按 primitive/cell 分块，线程局部输出，稳定合并和去重。 |
| Point collision | 高 | 每粒子独占写时可直接拆分。 |
| Edge collision | 中 | 相邻 edge 会写共享粒子，需要颜色组或累积修正。 |
| Distance/Bending/Angle | 中低 | 约束共享粒子，不能直接 parallel-for 原地写。静态 graph coloring 最接近现有迭代语义；Jacobi 会改变收敛行为。 |
| self contact solve | 中高 | 当前本身采用定点量化的 correction sum/count 再统一写回，适合线程局部累积后确定性归并。 |
| Mesh/Bone结果准备 | 高 | 按 source range 并行生成插件自有结果；Blender写回仍在主线程。 |

任何把 Gauss-Seidel 原地约束循环改成 Jacobi 的方案都属于数值算法变化，必须单独评估迭代数、收敛、刚度手感和确定性，不能作为“纯性能重构”混入。

### P5：单线程算法与数据布局优化

native 分阶段计时完成后，优先检查以下代码形态：

- self grid 当前每 substep 对 point/edge/triangle 分别 `stable_sort`，并按排序结果逐一重排 flags、indices、depth、inverse mass、AABB、thickness、owner 和 grid 等多个 vector；评估排序 index/key 而不是反复物理搬运所有 SoA。
- aggregate 路径反复 clear/insert/copy；fused context 应直接删除这部分普通路径成本。
- candidate 临时 vector、去重 sort 和 self solve 的 sum/count buffer 应按容量复用，避免每 substep 重新分配/清零超出有效范围。
- grid hash/run 查找可比较稳定 radix sort、Morton key 和 cell range table；必须用真实 candidate 分布验证，不能只测空场景。
- uniform 参数保持标量，只有真实 override 才物化 dense array，控制缓存带宽。
- 检查 Release 编译、LTO、目标 SIMD 指令和浮点模式；不得以 fast-math 破坏 NaN/有限性、Teleport阈值或确定性合同。

这些项目很可能有收益，但在 native 内部计时出现前只属于候选，不预先指定优先级。

### P6：GPU 前置准备与决策门槛

fused context、连续 partition ranges、显式 particle/constraint SoA、明确的 pass 依赖和无 Python inner-loop 是 GPU 化的前置条件，但不代表应立即实现 GPU solver。这里的前置工作应避免引入 CPU 专用的 worker object、线程亲和性和每粒子 callback；它只定义数据、资源和阶段合同。

GPU前置交付应包括：

- backend-neutral 的粒子/约束/primitive SoA 及 source partition range；
- 每个 pass 的输入、输出、读写冲突和生命周期声明；
- candidate/contact/intersection buffer 的容量、溢出和统计合同；
- CPU scalar reference 使用同一份静态数据和系数，作为 GPU 结果对照；
- 结果发布与 Blender writeback 的单向边界，禁止 GPU kernel 直接接触 Blender/RNA；
- 能描述单线程 CPU、context Batch 和未来 GPU dispatch 的同一 execution plan，而不把某一种 backend 的调度对象暴露给产品节点。

GPU 之前必须成立：

- 所有运行参数已经落入 context/partition/particle/constraint 明确层级；
- 约束拥有稳定 batch/color，dispatch 间依赖明确；
- self broadphase/candidate/contact buffer 有上限、溢出策略和可观测统计；
- CPU/GPU 上传只发送变化范围，不每帧重传完整静态 topology；
- Blender写回不要求 GPU 每 substep 同步到 CPU；
- CPU reference 与 GPU tolerance/确定性等级已经定义。

真正 GPU backend 只有在 CPU fused、静态缓存和单线程 reference 仍无法达到目标资产预算，且 profiling 显示足够大的可并行 kernel 占比、可接受的上传/同步比例时才立项。GPU 仍需自己的冲突处理（例如约束 coloring、Jacobi 或分阶段 reduction），但这应作为 GPU 数值设计单独评估，而不是先在 CPU 侧建一套长期 job 抽象。否则 PCIe/driver 同步、双实现维护和调试成本可能高于收益。

## 性能与正确性门禁

每个优化提交必须同时满足：

- debug 全关时继续零明细记录、零 readback、零字符串格式化；热点计时关闭时不读取逐阶段时钟。
- static cache 不漏 Mesh/UV/vertex group/Anchor/Object/topology/undo/load 失效。
- fused context 中各 source 不产生结构约束串线，写回严格落回原 Object。
- 同 partition self、跨 partition contact、collision group/mask和final intersection均有自动证据。
- 每 partition Teleport/Center/Anchor互不污染；一个代理触发 Reset/Keep 不得无条件重置其他 partition，除非产品明确选择 context-wide策略。
- 单线程 reference 长期保留；多线程结果按明确的 exact 或 tolerance 合同验收。
- benchmark 固定 Blender版本、资产、帧段、warmup、substep、collider scope、self模式和编译配置，报告 p50/p95 而不是单帧最好值。
- 优化前后同时记录粒子、primitive、candidate、contact、constraint 和复制字节数量，防止用悄悄减少工作量伪造加速。

阶段目标以相对收益为主：

| 阶段 | 成功条件 |
|---|---|
| P0 | native solve 的 90% 以上时间能归入稳定阶段，计时关闭无可测回归。 |
| P1 | 代表资产热帧静态准备 p95 低于 `2 ms`，失效矩阵通过。 |
| P2 | 多 source fused 与手工 join 的求解成本同量级，且保留独立配置/变换/写回；明显快于跨 task aggregate。 |
| P3/P4 | 独立 context 的 2/4 worker Batch 只有在实测超过串行且小任务不退化时才启用；fused context 默认保持 reference 语义。 |
| P5 | 每项优化由内部阶段计时证明，输出合同不变。 |
| P6 | backend-neutral 数据/pass 合同先闭环；只有 CPU 路线仍不达标且可并行占比、上传和同步预算都支持时才立项 GPU backend。 |

## 建议的实施提交序列

1. `perf(mc2): add native solve stage counters`
2. `perf(mc2): cache observed static source snapshots`
3. `refactor(mc2): introduce mesh source partition specs`
4. `feat(mc2): build fused multi-source mesh contexts`
5. `feat(mc2): add partition center teleport and writeback`
6. `feat(mc2): compile particle and constraint overrides`
7. `refactor(mc2): define backend-neutral execution passes`
8. `refactor(mc2): isolate pure native step from Python errors`
9. `perf(mc2): prototype gpu-compatible particle and broadphase buffers`
10. `perf(mc2): add optional native context batch scheduler`
11. `perf(mc2): evaluate optional cpu particle split kernels`

每个提交都应可独立基准、回归和回滚。fused context 与多线程不得合并成一个无法区分收益和数值变化的大提交。

## 外部依据

- Blender Python API, `Python Threads are Not Supported`: <https://docs.blender.org/api/current/info_gotchas_threading.html>
- MagicaCloth2, `Performance`: <https://magicasoft.jp/en/mc2_performance/>

Blender 文档只支持“不得从并发 Python/worker 访问 Blender API”的边界，不直接保证任意 native 多线程实现安全。MagicaCloth2 页面支持 Split Job/Batch Job 混合策略及重 cloth/self collision 采用内部拆分的方向，但 OmniMC2 仍需按自身 C++ 数据依赖、Blender生命周期和确定性合同重新实现。
