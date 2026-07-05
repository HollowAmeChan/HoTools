# OmniNode 架构约定

本文档记录 OmniNode 当前的工程边界、编译/执行模型、缓存系统、调试系统和 native 后端开发流程。它不是用户手册，而是维护代码时用来统一判断的架构说明。

最重要的设计前提：OmniNode 的默认节点模型是“由函数生成节点”。节点图是给用户和技术美术渐进组合、检查、调参的编辑界面，不是鼓励用户在图上连接复杂逻辑的通用可视化编程环境。复杂业务应优先封装成新的函数节点，因为做节点本身应该足够简单；只有会改变图结构、编译 IR、执行上下文或 runtime cache 语义的特殊能力，才应该做成 GraphNode。

## 一句话模型

OmniNode 是一个基于 Blender `NodeTree` 的轻量函数图系统：

- 默认业务节点由 `@omni(...)` 标记的 Python 函数生成，socket 来自函数签名，运行时表现为普通 `OpCall`。
- 编辑阶段使用 Blender `NodeTree`、`Node`、`NodeSocket`、`NodeLink` 描述图。
- 编译阶段把从输出节点可达的子图转换成 `CompiledGraph` 和一组简单 IR 指令。
- 执行阶段只跑 IR，不再遍历 Blender links。
- 节点图只表达组合和执行顺序；复杂操作应封装成新函数节点，而不是堆成复杂连线。
- GraphNode 是少数例外，只用于组、批处理、cache、调试或未来控制流等会影响编译/执行语义的节点。
- 全局或跨帧临时状态必须通过 GraphNode 中的 runtime cache 节点显式读写和清理。
- 读写已有 Blender 数据或已有数据块不属于临时 cache 约束。
- 少数性能热点可以提供 C++ backend 节点，但 Python 节点层仍负责 Blender 数据和节点接口。

## 性能结论和排查优先级

### 案例：VRM 弹簧骨缓存零拷贝优化（2026-07）

一次针对 `springBoneVRM_CPP` 每帧掉帧的精细测试，把帧调试器做成单一统一报告（见 Debug 章节「帧级统一计时」），并据此定位、消除了缓存层的全部冗余开销。

优化前后实测（同一角色，连续播放）：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 整帧 frame | 84.7ms | 31.4ms |
| FPS | 11.8 | 31.8 |
| handler（addon 内） | 59.5ms（最高 81ms） | 8.6ms |
| engine/redraw（引擎侧） | 22.8ms | 22.8ms（不变） |

handler 内优化前的耗时分布几乎全是缓存浪费，而真正的物理解算只有 ~6.5ms：

- `CACHE_READ` ~10.7ms：`read_cache` 每帧深拷贝一次缓存值。
- `CACHE_WRITE` ~13ms：`write_cache` 把 replace 值深拷贝成缓存私有副本。
- `[finish] snapshot` ~10ms：提交时 `_snapshot_value` 又深拷贝一次。
- `[finish] committed_ids` ~16ms：回收前重算「可达对象 id 集合」，且在提交循环里**每个 key 重算一次**，复杂度 O(K×N)。
- `[finish] dispose` ~8.5ms：递归回收旧值。

同一个大 state dict（9 条链的 joints + 数百条含 Matrix 的 write_records + numpy 数组）每帧被深拷贝三次、深度遍历多次，而它本质是「读 → 原地改 → 写回同一对象」的逐帧滚动状态。

三步修复：

1. `finish_run` 改两阶段提交：先应用所有变更到最终状态、收集待回收候选，再用一次 `_committed_value_ids()` 扫描统一回收。committed_ids 从 O(K×N) 降到 O(N)。
2. 消除提交期冗余深拷贝：`write_cache` 排入 pending 时已拷成私有副本，`finish_run` 直接采用，不再二次 `_snapshot_value`。
3. 零拷贝缓存 owner：把物理 state 包成 `OmniCacheOwnerDict`（实现了 `omni_cache_dispose` 协议的 dict 子类）。runtime 对带 dispose 协议的对象，`_snapshot_value` 直接返回本体（读/写/提交都不深拷贝），`_collect_cache_value_ids` / `_dispose_cache_value` 把它当不透明 owner 不再递归深入。读返回 committed 本体、节点原地改后按 replace 写回，提交时 `old is new`，dispose 与 committed_ids 整段跳过。具体写法见「7.1 Runtime cache 的资源值协议」的零拷贝加速一节。

贡献最大的是第 3 步。这套修复后，缓存五项全部从榜单消失，handler 内 81% 是真实物理计算。

### 诚实说明：引擎侧 engine/redraw 的固有成本

帧调试器报告里的 `engine/redraw = frame − handler` 是**反推值**，覆盖 `frame_change_post` 返回后 Blender 在 C 层做的事，Python 计时探不进去，addon 代码也改不动。上面案例里这部分是 22.8ms，零代码隔离实验拆解如下：

- **角色网格蒙皮变形 ~7ms**：armature modifier 每帧按新骨骼姿态重新变形整个角色网格。隐藏该网格可验证。这属于建模/绑定层（低模代理、降顶点数、GPU 蒙皮），不是 addon 能改的。
- **视口重绘 ~7ms**：关闭 3D 视口可验证。视口是必须绘制的，关不掉。
- **骨骼姿态求值 + 其它依赖 ~8ms**：depsgraph 重算 armature 全部骨骼的最终矩阵、约束、子物体。只要每帧改骨骼让物理生效，这个重算就省不掉。

结论：当 handler 已压到个位数毫秒、而 frame 仍受 engine/redraw 主导时，剩余开销是「每帧驱动骨骼/网格」方案的物理成本，**不应再到 addon 代码里找优化**。任何声称能从 Python 层压低这部分的改动都是盲改，给不出可验证的收益。能做的只有建模/绑定层（代理网格、降面）或接受现状。

判定何时停手：用帧调试器看 handler 占 frame 的比例。handler 占比已经很低（例如 < 30%）说明 addon 侧已榨干，瓶颈在引擎，优化重心应转移或收尾。

## 核心边界

### 1. 函数生成是默认节点模型

OmniNode 的默认扩展点是 `NodeTree/Function/*.py` 中的 Python 函数和 `@omni(...)` 元数据。`FunctionNodeCore.py` 解析函数签名，生成 socket、默认值、multi input 标记和继承 `OmniNode` 的节点类。编译器看到这类节点时生成 `OpCall`，执行器只调用 `_func(*args)` 并把返回值写回寄存器。

维护时应把这个模型当作默认答案：

- 业务逻辑、数据转换、Blender 数据读写、数值计算、solver 包装，默认都做成函数节点。
- 复杂节点内部可以拆 Python helper、复用模块、调用 native backend，但对节点图暴露的仍应是清晰的函数输入和返回值。
- 如果一个节点图开始依赖大量细碎连线表达固定业务流程，应优先把这段流程收敛成新的函数节点或明确的组接口。
- 不要仅因为“这个节点比较复杂”“需要很多 socket”“想要自定义 UI”就新增 GraphNode。

这个约束的目标是降低用户操作复杂度。用户应该通过少量语义明确的节点完成渐进式编辑和调参，而不是被迫维护庞大的节点网络。

### 2. GraphNode 是 IR 级特殊节点

GraphNode 不是函数节点的替代写法，而是架构级例外。只有特殊需求会影响下面任一边界时，才应新增 GraphNode：

- 需要自定义编译 emitter，不能表达为单次 `_func(*args)`。
- 需要新增或改变 IR，例如 `SubtreeCall`、`BatchSubtreeCall`、`CacheReadCall`、`CacheWriteCall`。
- 需要改变执行上下文、组调用路径、batch item 命名空间、commit/rollback 边界。
- 需要作为编辑器结构节点参与编译归一化，例如组输入/输出、组引用、批处理、cache、调试、未来控制流。

不应该做成 GraphNode 的情况：

- 普通业务节点只是内部逻辑复杂。
- 只是为了少写一个函数生成节点。
- 只是为了把一组常用操作做成单节点。
- 只是为了 C++ 加速；native 加速仍应挂在函数节点语义后面，除非同时需要新的 IR。

新增 GraphNode 必须同时考虑 `GraphNode.py`、`OmniIR.py`、`OmniCompiler.py`、`OmniExecutor.py`、debug/timing 表达和缓存清理语义。如果不需要这些改动，通常就不该新增 GraphNode。

### 3. Blender 节点图只负责编辑表达

Blender 节点、socket、link 是编辑器数据结构，不是运行时执行结构。运行时不应该在执行过程中追踪 `NodeLink`，也不应该把 Blender 原生节点当作普通 OmniNode 调用。

维护时需要区分：

- OmniNode 自定义节点：继承 `OmniNode`，通常有 `_func`、`is_output_node`、`set_bug_state()` 等能力。
- Blender 原生编辑节点：例如 `NodeFrame`、`NodeReroute`，它们没有 OmniNode 的状态和 `_func`。

原生编辑节点必须在编译器里显式适配，不能让它们落入普通 `OpCall`。

### 4. 输出节点决定可执行子图

编译入口不是整棵图的所有节点，而是：

```text
tree.nodes 中 is_output_node == True 的节点
```

`CompilerContext._collect_reachable_graph()` 从这些输出节点反向 DFS，收集可达节点和 links，再交给 `OmniCompiler.topo_sort()` 做拓扑排序。没有连接到输出节点的节点不会执行。

这允许节点图里保留实验节点，但也意味着“看得见的节点”不等于“运行时会执行的节点”。

### 5. 寄存器是运行时数据边界

编译阶段使用 `(node.name, socket.identifier)` 作为 socket 输出到寄存器的映射键。

普通函数节点的规则：

- 输入 socket 编译为输入寄存器列表。
- 输出 socket 分配新寄存器。
- 执行时调用 `_func(*args)`，再把返回值写回输出寄存器。

默认值规则：

- 没有 link 的输入 socket 会编译成 `("CONST", reg, value)`。
- 如果 socket 没有安全的 `default_value`，当前返回 `None`。

### 6. 跨帧临时状态只能通过 GraphNode cache 节点

OmniNode 当前不对跨树 IO 做强约束。树输入/输出只是组节点接口的一种表达方式，不承担“全局参数系统”的职责。

真正需要严格约束的是全局或跨帧临时状态：如果某个状态不是已有 Blender 数据或已有数据块，而是 OmniNode 运行过程中产生、需要被后续运行继续读取的临时数据，就必须走 GraphNode 中的 runtime cache 节点。

Cache 读写/删除/调试节点做成 GraphNode 是有意设计，不是普通函数节点缺失能力：

- cache 操作会影响运行上下文、命名空间、提交/回滚和 batch/group 隔离，属于 IR 级语义。
- cache 的生命周期必须显式暴露给用户，用户需要能接入删除节点或清理操作，避免缓存 key 持续增长导致工程变慢。
- 同一子树被多个组引用、同一组被批处理多次执行时，cache 必须按 root tree、group 调用路径和 batch item 隔离；这不能交给函数节点的隐藏全局状态。
- 普通函数节点可以接收和返回 `_OmniCache` 类型的缓存值，但这只是当前 IR 中流动的值。跨帧持久化、读取、写入、删除必须由 cache GraphNode 完成。

树级输入/输出仍然通过下面的结构表达：

- `OmniNodeTree.group_inputs`
- `OmniNodeTree.group_outputs`
- `OmniGroupNodeInputs`
- `OmniGroupNodeOutputs`
- `OmniGroupNode` / `OmniBatchGroupNode`

编译时：

- `OmniGroupNodeInputs` 把树输入 UID 映射到 `CompiledGraph.input_regs`。
- `OmniGroupNodeOutputs` 把树输出 UID 映射到 `CompiledGraph.output_regs`。
- 父级 `OmniGroupNode` 按子树 `input_regs` 的 UID 顺序传入参数，再按 `output_regs` 收集输出。

维护约定：

- 普通函数节点可以读写明确传入的 Blender 对象、数据块或其属性。
- 读写已有数据不需要额外包装成 cache。
- 全局临时状态、跨帧模拟状态、运行时中间状态必须暴露为 cache 读写/删除节点，而不是藏在模块全局变量、节点实例字段、函数闭包或 C++ 全局状态里。
- 跨树 IO 目前只是组调用接口约定，不作为全局参数约束。

### 7. Runtime cache 是显式状态系统

Runtime cache 由 `OmniRuntimeState.py` 和 GraphNode 中的缓存节点共同维护：

- `OmniCacheReadNode`
- `OmniCacheWriteNode`
- `OmniCacheDeleteNode`
- `OmniCacheDumpNode`

关键边界：

- runtime cache 不是文件持久化数据，只在当前 Python 会话中可靠。
- 读节点只读取上一轮成功执行后提交的 committed cache。
- 写节点在 `启用` 为 `True` 时写入本轮 pending cache；关闭时只透传输入值，不覆盖已有缓存。
- 删除节点在 `启用` 为 `True` 时记录 pending delete；可以删除指定 key，也可以清空当前执行实例命名空间。
- dump 节点输出当前执行实例的 cache 快照；快照会叠加本轮 pending 写入和 pending 删除。
- root run 成功结束后 pending 才提交；执行失败时 pending 写入和删除都会丢弃。
- 命名空间由 root tree、group 调用路径、batch item 共同决定，同一子树被多个组实例调用时不会互相污染。
- cache 清理是用户可见的图操作或 operator 操作。新增跨帧状态节点时，必须让用户能明确删除对应 cache，不能制造只能靠重启 Blender 才释放的隐藏状态。

### 7.1 Runtime cache 的资源值协议

Runtime cache 可以保存普通 Python 值，也可以保存持有外部资源的 owner 对象，例如未来 Bullet / PhysX world、GPU buffer、native handle 或 solver session。资源型对象不需要强制 tag，也不需要专用 GraphNode；它只需要按需提供 duck-typed 生命周期方法：

```python
def omni_cache_dispose(self, reason: str) -> None:
    ...
```

`OmniRuntimeState` 在以下边界调用 dispose：

- committed value 被新 value 覆盖。
- Cache Delete 删除 key。
- 清空当前 namespace、root tree 或全部 runtime cache。
- root run 失败时丢弃本轮新建的 pending replace value。
- 插件注销或 operator 清理 runtime cache。

dispose 必须幂等。高封装解算器节点如果在内部判定 cache 脏、跳帧、拓扑变化或后端 world 无效，可以先自行 dispose 并重建；后续 runtime cache 再遇到替换或清理时重复调用 dispose 不应出错。

Cache Write 节点的 socket 不暴露写入模式，编译器仍然只生成同一种 `CacheWriteCall`。写入模式是函数节点返回值上的内部意图：

```python
from OmniNode.NodeTree.OmniRuntimeState import cache_replace, cache_mutate

return cache_replace(new_cache)
return cache_mutate(existing_cache)
```

- `_OmniCache` 的运行值契约定义在 `OmniNodeSocketMapping.py`：裸 Python value 是 cache payload，Cache Write 默认按 replace 写入。
- `cache_replace(value)` 表示显式把 cache key 绑定到新 owner；提交时旧 owner 会在必要时被 dispose。
- `cache_mutate(value)` 表示 committed owner 已经被原地更新；runtime 只校验 key 当前绑定的 committed value 是否就是这个对象，不做 merge、patch 或 copy。
- 函数模块如果只想依赖 socket marker，也可以用 `_OmniCache(value)` 或 `_OmniCache.replace(value)` 构造 replace intent，用 `_OmniCache.mutate(owner)` 构造 mutate intent；这几个入口会懒加载转发到 `OmniRuntimeState`。

项目内 `_OmniCache` 输出节点应显式返回 `_OmniCache(next_state)` 或 `_OmniCache.replace(next_state)` 表达 replace，作为后续节点参考写法。裸 payload 仍被 runtime 接受为 replace fallback，但不作为新节点推荐写法。资源 owner 需要表达原地更新时，返回 `_OmniCache.mutate(owner)`。Cache Write 执行时消费 intent，输出 socket 继续透传真实 value，不把 intent wrapper 暴露到下游节点。

runtime cache 不负责通用标脏、不负责重建判定，也没有成功提交回调。状态是否脏、是否要重建、如何把当前 Blender 输入同步到后端 world，都属于生产该 cache 的高封装函数节点职责。这样 Bullet 和 PhysX 可以使用同一套 cache 生命周期语义，但各自完全实现自己的后端构建、step、同步和销毁逻辑。

资源型 cache 如果需要 dump 可读性，可以提供：

```python
def omni_cache_debug_snapshot(self) -> dict:
    ...
```

dump 只把它作为调试视图，不参与运行语义。

#### 用 dispose 协议做零拷贝加速

默认的裸 Python value 缓存走**快照隔离**语义：`read_cache` 返回深拷贝、`write_cache` 存深拷贝、`finish_run` 提交时按需再拷贝并回收旧值。对小状态没问题，但对**每帧读改写的大状态**（物理 state：嵌套 dict、numpy 数组、几百条含 Matrix 的记录）会非常贵——同一坨结构每帧被深拷贝多次、深度遍历多次。VRM 弹簧骨案例里这部分占了 ~50ms。

关键机制：`_snapshot_value` 对实现了 `omni_cache_dispose` 的对象**直接返回本体、不深拷贝**；`_collect_cache_value_ids` 和 `_dispose_cache_value` 也把它当不透明 owner，不再递归深入内部。利用这一点，把缓存 payload 包成一个带 dispose 协议的 dict 子类即可全程零拷贝：

```python
class OmniCacheOwnerDict(dict):
    """普通 dict，但实现 omni_cache_dispose，让 runtime 走零拷贝路径。"""
    def omni_cache_dispose(self, reason):
        return  # 内部都是 Python 容器 / numpy / bpy 引用，交给 GC
```

它在所有 `isinstance(x, dict)` 检查下仍是 dict，业务代码无需改访问方式。逐帧滚动模式：

```python
# read 返回 committed 本体（零拷贝）
state = cache_state                  # 来自 cache read socket
state["frame"] = current_frame       # 原地改
state["chains"] = new_chains
return _OmniCache(_as_cache_owner(state))   # replace 写回同一本体
```

提交时 `old is new`，runtime 不产生 dispose 候选，committed_ids 扫描与 dispose 整段跳过。`Function/Physics.py` 用一个幂等 helper `_as_cache_owner(payload)` 在所有 `_OmniCache(...)` 产出边界把 payload 规范成 owner（普通 dict 浅包装成 `OmniCacheOwnerDict`，已是 owner 或 None 原样返回），可作参考写法。

注意事项（零拷贝会改变缓存语义，务必权衡）：

- **失去快照隔离**：committed 缓存变成共享可变。如果某帧解算中途抛异常，缓存会留下改了一半的状态（快照模式能隔离回滚）。对每帧整体重算、能自愈的物理通常可接受；对需要事务性的状态不要用零拷贝。
- **多读者别名**：若两个 cache read 节点读同一个 key，零拷贝下它们拿到同一对象本体，一个改另一个会看到。需要隔离时仍用裸 value（默认深拷贝）。
- **owner 身份要全程保持**：任何 `dict(state)` 浅重建会退化成普通 dict、丢掉零拷贝身份。要么在产出边界统一用 `_as_cache_owner(...)` 重新包装（幂等，推荐），要么避免重建。
- **`dict()` 浅拷贝便宜，深递归才贵**：每帧浅拷一个新 owner dict 只是几微秒，真正省下的是 `_snapshot_value` 的深递归和 dispose/committed_ids 的深扫描。只要顶层是 owner，内部子结构不会被递归深入。
- **范围最小化**：只在物理这类大状态节点的产出边界改，不要动全局 `cache_replace` / `read_cache` 默认行为，否则会破坏其它缓存使用者的隔离假设。

### 7.2 缓存失效边界：哪些数据必须每帧重建

缓存优化的核心风险是**缓存太狠导致该失效的数据没失效**。2026-07 的零拷贝优化后曾出现网格静态碰撞失效的回归（碰撞源列表被永久缓存，用户新增/修改碰撞体不生效），根因就是缓存 key 太粗、失效条件太宽。

新增或优化任何缓存前，必须先把数据按「失效频率」分类，并显式选择匹配的缓存 key。下表是物理解算器的分类基准：

| 数据类别 | 失效条件 | 正确的缓存策略 | 反例（错误做法） |
|---|---|---|---|
| **碰撞体位置**（`matrix_world`） | 每帧都可能变 | 每帧重建快照，key 含 `frame` | 缓存跨帧的世界坐标 |
| **碰撞源列表**（哪些物体/骨骼启用了碰撞） | 增删改碰撞体、切换可见性 | key 含 `frame`，每帧重新枚举一次 | ❌ 只用 `scene` 指针做 key（永不失效） |
| **网格拓扑**（顶点/边/面连通性） | 拓扑编辑 | SHA1 强签名 + 廉价数量签名（`light_key`）双重检测 | 每帧无条件重算连通性 |
| **rest / 静止位置** | 物体变换变化 | 变换签名变化时同步 | 缓存后不再跟随物体移动 |
| **顶点组权重**（pin / 碰撞半径） | 权重重绘 | 见下方设计约束：运行期不支持热改 | — |
| **逐帧模拟状态**（positions/velocity） | 每帧滚动 | 零拷贝原地 mutate，见 7.1 | 每帧深拷贝 |

判定缓存 key 是否正确的经验法则：**缓存 key 必须包含所有会导致结果变化的输入维度**。如果一个输入会变、但没进 key，就是一个「改了不生效」的潜在回归。scene 指针在整个会话内不变，因此**任何以 scene 指针为唯一 key 的缓存都等价于永久缓存**，只能用于真正会话级不变的数据。

per-frame 缓存的正确写法（同一帧内多次调用复用、跨帧自动失效）：

```python
cache_key = (scene_key, frame)
cached = cache.get(cache_key)
if cached is not None:
    return cached
result = rebuild(...)
cache.clear()                # 只保留当前帧，避免 key 随帧号无限增长
cache[cache_key] = result
return result
```

**顶点组权重的设计约束（有意的性能权衡）**：pin 顶点组和碰撞半径顶点组的权重 hash 只在拓扑数量变化时失效，权重值重绘**不会**自动触发 cache 重建。这是运行期不允许热修改权重的显式约定——需要改权重时，用户必须停止运行、修改、reset 或清缓存后重新运行。此约束写在 `physicsMC2/mesh_build.py` 的 `cached_vertex_group_weights_hash` 文档里。

### 7.3 配置真值来源必须唯一：SpringBone 链 root 的判定

和缓存失效边界并列的另一个物理侧原则：**同一个语义只能有一个真值来源**。当一份配置既能从 A 处推断、又能从 B 处标记时，A 和 B 迟早会不一致，其中一个会腐烂成误导性的死数据。

具体案例（2026-07）：VRM/基础 SpringBone 的「链 root」曾有两个来源——

- **解算侧**：`boneChainFromRoot`（“从根获取骨链”节点）输入的骨骼即 root，`bone_is_effectively_pinned` 靠 `bone_name == root_name` 判定硬 Pin，root_name 就是这个输入。
- **数据侧**：`Bone.hotools_collision.spring_root` 布尔标记，配套整套「设为 Root / 清空 / 选择」operator 和面板。

问题是解算器**从不读** `spring_root`，它只认节点输入的骨。`spring_root` 仅被 PhysicsTools 预览侧消费，用来离线猜哪根骨是 root 并画成 Pin 高亮。于是两套判定天然脱钩：节点里填了骨 A 当 root，但只要 A 没勾 `spring_root`，预览就显示不出它是 Pin。预览在“猜”一个解算器根本不参考的标记。

结论与已执行的处理：删除 `spring_root` 属性、三个 operator 和面板批量管理块，`_effective_bone_pin` 退化为只看 `pin`。root 的唯一真值来源就是“从根获取骨链”输入的骨骼。代价是预览不再离线高亮 root 的强制 Pin（预览本就无法离线得知解算器会拿哪根骨当 root），这是诚实的：**预览不该猜解算行为**。

维护约定：新增骨骼/物体级配置时，先问“这个语义是否已经能从别处（节点输入、已有数据、拓扑）确定”。能确定就不要再加一个并行标记；确实需要持久标记时，让它成为唯一来源，不要和运行时推断竞争。

### 8. 编译缓存和 runtime cache 是两套系统

`OmniNodeTree._COMPILED_TREE_CACHE` 缓存的是 `CompiledGraph`，目的是避免每帧重复编译图。

它和 runtime cache 完全不同：

- 编译缓存保存指令、寄存器、子树 IR、调试 trace。
- runtime cache 保存节点业务状态，例如物理位置、上一帧速度、软跟随状态。
- 清理编译缓存不会清理 runtime cache。
- 清理 runtime cache 不会让图重新编译。

当前入口：

- `tree.compile_cached(force=True)`：强制编译并更新编译缓存。
- `tree.run()`：强制编译，然后运行已编译结果。
- `tree.run_compiled()`：只运行已有编译缓存；没有缓存时报错。
- `tree.run_frame_cached()`：每帧运行入口，没有编译缓存时先编译一次，之后复用。
- `tree.clear_compile_cache()`：清理当前树编译缓存。

维护约定：

- 会改变节点、socket、link、树 IO 或特殊节点语义的操作，必须清理相关树的编译缓存。
- 每帧运行依赖编译缓存，所以调试“为什么改图后没有变化”时先检查是否需要重新编译或清缓存。
- 插件注销时会清空编译缓存。

### 9. C++ backend 只接管计算热点

native 后端不替代 OmniNode 编译器和执行器。它只为特定节点提供加速实现。

当前正式模式是平行节点：

- `网格物理-XPBD`：Python 标准实现，作为行为蓝本。
- `网格物理-XPBD-CPP`：C++ 后端实现，保持相同输入、输出、cache 语义和跳帧行为。

Python 侧职责：

- 校验 Blender 对象、mesh、shape key、vertex group、frame continuity。
- 批量读取和写回 Blender 数据。
- 管理 runtime cache。
- 决定是否重建 cache、是否跳帧保护、是否调用 native。

MC2 节点的 Python 侧分层约定：

- `physicsMC2/__init__.py` 只声明 OmniNode API：`@omni` metadata、socket 默认值、Python/CPP 平行节点 wrapper。
- `physicsMC2/runtime/controller.py` 是运行中控，负责 cache、BasePose、collider、跳帧冷启动、backend 调用和 GN delta 写回。
- `physicsMC2/runtime/restart.py` 只处理首帧、reset、非正向连续帧的冷启动状态，不写节点 metadata。
- `physicsMC2/runtime/timing.py` 只处理节点级 debug timing。
- `physicsMC2/backends/selector.py` 只做 backend 标签归一化和 solver 函数分派。
- `physicsMC2/solver.py` 只维护 Python reference / C++ full-core 的解算实现和 ABI 打包，不再承载节点入口或 cache 中控。

C++ 侧职责：

- 只处理已经整理好的数组和标量参数。
- 原地更新数值 buffer。
- 不直接访问 `bpy`。
- 不保存 Blender 对象指针。
- 不保存跨帧 solver 全局状态。

## 编译流程

主要文件：

```text
NodeTree/OmniCompiler.py
NodeTree/OmniIR.py
```

当前编译器已经拆成两层：

- `OmniCompiler`：公共入口、节点 idname 常量、拓扑排序和少量静态工具。
- `CompilerContext`：单次编译上下文，持有寄存器映射、指令列表、拓扑结果和 debug graph。

流程：

1. `OmniCompiler.compile(tree, debug=False)` 创建 `CompilerContext`。
2. `CompilerContext` 检查子树循环引用。
3. 从输出节点反向 DFS 收集可达子图；如果遇到 `node.mute == True`，该节点作为搜索屏障，节点本身和输入侧上游都不进入可执行子图。
4. 编译输入 socket 时只接受仍在可执行子图内的 link；从 muted/被剪枝节点来的可见连线按未连接处理，走目标 socket 默认值。
5. 拓扑排序。
6. 逐节点调用 emitter。
7. 输出 `CompiledGraph`。

特殊节点通过 `CompilerContext.SPECIAL_EMITTERS` 分派：

- `NodeFrame`：跳过。
- `NodeReroute`：寄存器透传，不生成运行时调用。
- `Group Inputs`：绑定 `CompiledGraph.input_regs`。
- `Group Outputs`：绑定 `CompiledGraph.output_regs`。
- `Group Node`：递归编译子树，生成 `SubtreeCall`。
- `Batch Group Node`：递归编译子树，生成 `BatchSubtreeCall`。
- `Cache Read/Write/Delete/Dump`：生成 cache 专用 IR。

普通函数节点生成 `OpCall`。如果节点没有 `_func` 且没有特殊 emitter，应明确报错，不允许静默跳过。

`CompiledGraph` 包含：

- `instructions`
- `reg_count`
- `input_regs`
- `output_regs`
- `tree_name`
- `tree_ref`
- `runtime_timing_tree_key`
- `node_order`
- `compile_trace`
- `register_bridges`
- `function_catalog`
- `debug_enabled`

`OmniIR.py` 只定义运行时 IR 类型：

- `CompiledGraph`
- `OpCall`
- `SubtreeCall`
- `BatchSubtreeCall`
- `CacheReadCall`
- `CacheWriteCall`
- `CacheDeleteCall`
- `CacheDumpCall`
- `RuntimeTimingBeginCall`
- `RuntimeTimingEndCall`

### Multi Input

`list[T]` 类型注解会被 `FunctionNodeCore.resolve_socket()` 识别为 multi input，并在 socket 创建时设置 `use_multi_input=True`。

编译时是否按列表收集输入，取决于目标节点的 `_socket_is_multi[sock.identifier]`，不是来源节点。

当前 multi link 顺序由 `(from_node.name, from_socket.identifier)` 排序决定，不保证等于 Blender 视觉插入顺序。依赖列表顺序的节点必须知道这个边界。

## 执行流程

主要文件：

```text
NodeTree/OmniExecutor.py
NodeTree/OmniRuntimeState.py
```

执行器不读取 Blender links，只执行 `CompiledGraph.instructions`。

主要职责：

- 分配寄存器数组。
- 接收子树输入并写入 `input_regs`。
- 执行 `CONST`、`OpCall`、`SubtreeCall`、`BatchSubtreeCall` 和 cache IR。
- 管理 root run 的 runtime cache context。
- 聚合 runtime trace 和 timing。

执行入口：

```python
OmniExecutor.run(compiled, debug=False)
```

执行时：

1. 创建 root `RuntimeCacheContext`。
2. 分配 `registers = [None] * compiled.reg_count`。
3. 按顺序执行 IR。
4. 出错时标记 run failed，并把错误写到节点 bug state。
5. root run 结束时提交或丢弃 pending cache。
6. 返回 `output_regs` 对应的结果字典。

`RuntimeObserver` 负责执行期观察，不负责业务逻辑：

- 完整 runtime trace。
- 每步 timing stage 名称。
- cache read/write/delete/dump 日志。
- subtree / batch subtree 进入和退出日志。

## Debug 系统

主要文件：

```text
NodeTree/OmniDebug.py
NodeTree/OmniNodeTree.py
NodeTree/OmniExecutor.py
```

当前有四类 debug。

### 1. Debug 编译

树属性：

```text
debug_compile
```

行为：

- 只在编译或重编译时输出。
- 输出编译 header、寄存器数量、拓扑顺序、树输入/输出、register bridge、runtime function catalog、compile trace。
- 子树会递归输出。

维护约定：

- 编译日志不能在每帧运行时反复打印，除非发生重新编译。
- 每帧运行使用 `run_frame_cached()` 时，应该复用已有 `CompiledGraph`。

### 2. Debug 运行

树属性：

```text
debug_runtime_trace
```

行为：

- 每次执行打印完整 IR 运行过程。
- 包含每一步输入、输出、cache 操作、子树调用和最终输出。
- 每帧运行时会非常频繁，只适合定位逻辑错误。

### 3. Debug 运行时长

树属性：

```text
debug_runtime_timing
debug_runtime_timing_interval
```

实现：

- 编译器总是插入 `RuntimeTimingBeginCall` 和 `RuntimeTimingEndCall`。
- 运行时只有当 `tree.debug_runtime_timing` 为 True 时才真正计时。
- 每个 IR step 会记录一个 stage。
- `OmniDebug.record_runtime_timing()` 把结果写入全局 profile。
- `OmniDebug.flush_runtime_timing()` 按输出间隔聚合打印，而不是每帧打印。

输出包含：

- interval
- samples
- hz
- total
- 最慢若干 step
- 被隐藏 step 的合计耗时

维护约定：

- timing 是观察工具，不应该改变节点行为。
- 新增 IR 类型时，应在 `OmniExecutor.timing_stage_name()` 中补清晰 stage 名称。

#### 帧级统一计时（frame 报告）

每帧运行（`run_frame_cached`）在开启 timing 时输出一份**单一统一报告**，把整条帧链路的所有叶子项放进同一份 `phases` 字典，从大到小排序，避免多个报告块和重复 total 互相打架。报告结构：

```text
OMNI DEBUG TIMING   |  Frame: <树名>
  [Summary]: samples=N  fps=..  frame=..ms
    handler       = ..ms  (..%)
    engine/redraw = ..ms  (..%)
  [Breakdown]:
    01. <最慢叶子项> = ..ms  (占 handler %)
    ...
    .. other_steps = ..ms
```

关键约定：

- `frame` 是每帧真实墙钟（`flush` 间隔 / samples）。`handler` 是 addon 内部实测耗时（`phases["total"]`）。`engine/redraw = frame − handler` 是**反推值**，代表 `frame_change_post` 返回后引擎在 C 层的开销（蒙皮、视口重绘、depsgraph），Python 探不进去。详见性能章节「引擎侧 engine/redraw 的固有成本」。
- 顶层执行器的 step 明细通过 `timing_collector` 直接并入 `phases`，不再单独成块。子树（嵌套 group/batch）仍走各自的独立报告。
- 为保证「所有叶子项相加 = total」，不写入会重复计数的聚合项（如 `[frame] execute`、`[run] step_loop`、`[run] finish_run`）；改用互不重叠的叶子项 + 一个 `[frame] unmeasured` 残差桶（total 减去所有已插桩项，覆盖 step 循环调度、计时器自身开销等未插桩缝隙）。
- `finish_run` 内部细分为 `[finish] committed_ids` / `[finish] snapshot` / `[finish] dispose` / `[finish] other`，四项相加等于 finish_run 总耗时，便于定位缓存提交阶段的开销。
- `frame_level=True` 标记区分帧级报告与子树报告；只有帧级报告显示 handler/engine 分离，子树报告显示会误导。

诊断引擎侧开销的零代码实验（用 frame/handler/engine 三个数做 A/B，不靠盲改代码）：

- 隐藏角色网格（armature modifier 的那个 mesh）→ engine 降多少就是**蒙皮变形**成本。
- 缩小或移出 3D 视口 → 降多少是**视口重绘**成本。
- 两者都扣掉、engine 仍剩的部分 → 是**骨骼姿态求值 + depsgraph**，每帧改骨骼就省不掉。

注意 `engine/redraw` 只在**连续播放/拖动**时准确；手动单帧点选有停顿时，空闲时间会掺进 frame 使 engine 虚高。

### 4. 节点级性能 debug

部分功能节点有自己的 `debug_output` 输入，例如：

```text
网格物理-XPBD
网格物理-XPBD-CPP
```

这类日志用于观察节点内部阶段，例如 validate、cache、transform、native、write。它和树级 runtime timing 互补：

- 树级 timing 看哪个 IR step 慢。
- 节点级 debug 看某个复杂节点内部哪一步慢。

### 5. Tracy 深度性能分析

适用场景：`debug_runtime_timing` 已经定位到慢在哪个 IR step，但需要更细粒度（微秒级、调用栈、多线程竞争）的可视化，或者需要同时观察 OmniNode 执行与 Blender C 层（depsgraph、蒙皮、视口）的交叉开销时，启用 Tracy 深度分析。

普通 Blender 构建下所有 Tracy 代码完全静默，不产生任何运行时开销。

#### 5.1 环境准备

编译环境：`D:\BlenderAdvance\`（Tracy 版 Blender 源码 + 构建产物）

**第一步：确认 Tracy Blender 已编译**

```text
D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\blender.exe
D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\bin\python.exe
```

**第二步：修复 Blender Python 缺失的头文件和库目录**

Tracy 版 Blender 的内嵌 Python 没有把 `Include/` 和 `libs/` 放在 python.exe 旁边，而是在预编译库目录里。需要各建一个目录链接（只做一次，重建 Blender 后需要重做）：

```powershell
# Python 头文件链接
New-Item -ItemType Junction `
  -Path   "D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\Include" `
  -Target "D:\BlenderAdvance\blender\lib\windows_x64\python\311\include"

# Python 库链接
New-Item -ItemType Junction `
  -Path   "D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\libs" `
  -Target "D:\BlenderAdvance\blender\lib\windows_x64\python\311\libs"
```

**第三步：安装编译工具并编译 `tracy_client`**

```powershell
$PYEXE = "D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\bin\python.exe"
$SCRIPTS = "D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\Scripts"

# 安装 cmake / ninja / scikit-build-core（只需一次）
& $PYEXE -m pip install cmake ninja scikit-build-core

# 把 cmake/ninja 加入 PATH 再编译
$env:PATH = "$SCRIPTS;$env:PATH"
Set-Location "D:\BlenderAdvance\tracy_src\python"
& $PYEXE -m pip install . --no-build-isolation
```

编译成功后验证：

```powershell
& $PYEXE -c "from tracy_client import ScopedZone, is_enabled; print('is_enabled:', is_enabled())"
# 输出：is_enabled: True
```

tracy_client 安装位置：`D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\4.5\python\Lib\site-packages\tracy_client\`

Tracy 源码位置：`D:\BlenderAdvance\tracy_src\`（版本 0.13.1）

Tracy GUI 工具：`D:\BlenderAdvance\tracy_gui\tracy-profiler.exe`（启动后等待连接）

#### 5.2 OmniTracy.py 封装原理

封装文件：`NodeTree/OmniTracy.py`

```python
# 尝试导入 tracy_client；失败则静默降级
try:
    from tracy_client import ScopedZone, is_enabled, frame_mark
    _TRACY_AVAILABLE = bool(is_enabled())
except Exception:
    _TRACY_AVAILABLE = False
```

公共 API：

| 函数 | 说明 |
|---|---|
| `tracy_enabled()` | 返回 Tracy 是否激活 |
| `omni_zone(name, color=0)` | 返回 Tracy zone 上下文管理器；不可用时返回 `_NullZone` 单例 |
| `omni_frame_mark(name="")` | 发送 Tracy 帧标记；不可用时空操作 |

`_NullZone` 是单例对象，`with omni_zone(...)` 在普通 Blender 里只有一次属性查找，开销可忽略。

#### 5.3 OmniExecutor 桩点位置

插桩在 `RuntimeObserver` 的以下方法里，不改变 `OmniExecutor` 主执行逻辑：

| 方法 | zone 行为 |
|---|---|
| `begin_tree(compiled)` | 开启 `OmniNode/Tree/{tree_name}`（树级 zone，整棵树生命周期）|
| `final_outputs(result)` | 关闭树级 zone |
| `step_begin(step_index, op)` | 开启 `OmniNode/{stage_name}`（步骤级 zone，单步生命周期）|
| `step_end(start_time, stage)` | 关闭步骤级 zone |
| `error(step_index, message)` | **异常路径补丁**：`break` 前强制关闭残留步骤 zone，防止 Tracy 栈错位 |

步骤 zone 名称格式（复用 `OmniExecutor.timing_stage_name()`）：

```text
OmniNode/step{N}:{NodeName}:{FuncName}         ← OpCall
OmniNode/step{N}:{NodeName}:SUBTREE:{TreeName} ← SubtreeCall
OmniNode/step{N}:{NodeName}:BATCH:{TreeName}   ← BatchSubtreeCall
OmniNode/step{N}:{NodeName}:CACHE_READ         ← CacheReadCall
OmniNode/step{N}:{NodeName}:CACHE_WRITE        ← CacheWriteCall
OmniNode/step{N}:CONST                         ← 常量指令
```

子树通过 `observer.child()` 各自得到独立 `RuntimeObserver`，Tracy 里子树的 zone 会嵌套在父树的 zone 内部，层次结构自然对应 OmniNode 组调用深度。

#### 5.4 Tracy profiler 里看到的层次结构

```text
OmniNode/Tree/TopTreeName
  OmniNode/step0:InputNode:read_scene
  OmniNode/step1:PhysicsNode:springBoneVRM_CPP
  OmniNode/step2:SubtreeGroup:SUBTREE:SubTreeName
    OmniNode/Tree/SubTreeName         ← 子树独立 zone
      OmniNode/step0:...
      OmniNode/step1:...
  OmniNode/step3:OutputNode:write_bone
```

BatchSubtreeCall 的每个批次项也会产生独立的子树 zone，批次间可以通过 zone 时间轴对比。

#### 5.5 使用流程

1. 启动 `tracy-profiler.exe`，等待连接。
2. 启动 Tracy 版 Blender（`D:\BlenderAdvance\build_windows_x64_vc17_Release\bin\Release\blender.exe`）。
3. 加载工程、开启每帧运行、在 Blender 里播放动画。
4. Tracy profiler 自动捕获，停止播放后在 profiler 里分析 zone 耗时、调用层次和帧时间线。
5. 用 `Ctrl+F` 按 zone 名称过滤，例如搜索 `OmniNode/` 可以只看 OmniNode 相关 zone。

#### 5.6 与内建 debug_runtime_timing 的分工

| 工具 | 适用场景 |
|---|---|
| `debug_runtime_timing` | 日常跟踪哪个 IR step 慢；生产版 Blender 可用；输出间隔聚合，副作用小 |
| Tracy zone | 需要微秒精度、可视化帧时间线、同时观察 OmniNode 与 Blender C 层交叉开销时 |

两者可以同时开启。`debug_runtime_timing` 的计时本身开销极小，但如果要精确对比 Tracy 数据，建议关闭 `debug_runtime_timing` 以减少 Python 层的计时器干扰。

#### 5.7 维护注意事项

- **新增 IR 类型时**：`OmniExecutor.timing_stage_name()` 里补好名称，Tracy zone 名称会自动跟随，无需额外修改。
- **子树 observer 不继承父 zone**：`child()` 方法只传 `debug`、`depth`、`trace`，`_tracy_tree_zone` 和 `_tracy_step_zone` 各自独立，不会意外跨层关闭。
- **错误路径**：执行器 `break` 时不会调 `step_end`，`error()` 回调负责关闭残留 zone，新增 IR 执行分支时如果也有 `break` 路径，必须确保在 `break` 前调用 `observer.error()`。
- **Tracy 版 Blender 重建后**：`Include` 和 `libs` Junction 可能丢失，需要重新创建（见 5.1 第二步）。
- **普通 Blender 构建**：`OmniTracy.py` 导入失败时完全静默，`_TRACY_AVAILABLE = False`，所有 `omni_zone()` 调用返回 `_NullZone` 单例，不影响正常运行。

## native 后端开发流程

主文档位置：

```text
_native/README.md
README.md
```

架构约定：

- `_native/` 只放 C++ 源码、CMake 工程、测试和 benchmark。
- `_Lib/py311/HotoolsPackage` 放 Blender 4.1+ / Python 3.11 ABI 的 runtime 产物。
- `_Lib/py313/HotoolsPackage` 放 Blender 5.1+ / Python 3.13 ABI 的 runtime 产物。
- Python 侧通过 `import hotools_native` 加载 native 模块。

开发新 native 节点建议流程：

1. 先保留或补全 Python 蓝本节点。
2. 新增平行 C++ 节点，命名上加明确后缀，例如 `-CPP`。
3. 两个节点保持相同输入、输出、cache 语义、跳帧规则和错误边界。
4. Python 层把 Blender 数据整理成数组，不让 C++ 直接碰 `bpy`。
5. C++ 桥接层只暴露窄接口。
6. C++ solver 层只处理数值计算。
7. 用节点级 debug 输出对比 Python / C++ 行为和耗时。
8. 补 native smoke test / benchmark。
9. 编译到对应 `HotoolsPackage`。
10. 用 Blender Python import 验证，再在 Blender 中 smoke test 节点。

常用构建命令见 `_native/README.md`。核心入口是：

```powershell
& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  --preset vs2022-py311

& "D:\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" `
  --build --preset vs2022-py311-release
```

native smoke test：

```powershell
```

导入验证：

```powershell
& "D:\Blender\Blender 4.5\4.5\python\bin\python.exe" -c "import sys; sys.path.insert(0, r'C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools\_Lib\py311\HotoolsPackage'); import hotools_native; print(hotools_native)"
```

发布约定：

- release zip 由 GitHub Actions 生成。
- `_native` 源码目录不进用户安装包。
- `_Lib/*/HotoolsPackage` 里的最终 native runtime 产物必须进入用户安装包。
- `.gitignore` 只管本地误提交，release workflow 的 exclude 才决定安装包内容。

## 文件职责

### `__init__.py`

OmniNode 模块入口。负责注册/注销 NodeTree、socket、节点、操作符、绘制辅助和侧边栏面板等模块。OmniNode 不再维护自己的子 `lib` 目录，第三方依赖应接到 HoTools 顶层公共库。

### `NodeTree/OmniNodeTree.py`

定义 `OmniNodeTree` 数据块。

职责：

- 树级属性：自动更新、每帧运行、debug 开关、组输入/输出。
- 编译缓存管理。
- `run()` / `run_compiled()` / `run_frame_cached()`。
- frame change handler。
- Node editor 树属性面板。

### `NodeTree/OmniIR.py`

运行时 IR 定义。该文件不应该依赖 Blender link 结构，也不应该包含执行逻辑。

### `NodeTree/OmniCompiler.py`

编译器。负责从 Blender 图生成 `CompiledGraph`。

维护重点：

- 所有编辑器特殊节点都应在这里归一化。
- 新增 GraphNode 时，应增加明确 emitter；普通业务节点不应在这里开分支。
- 不要让没有 `_func` 的节点进入普通函数调用。

### `NodeTree/OmniExecutor.py`

执行器。负责按 IR 顺序运行。

维护重点：

- 执行器不理解 Blender link。
- 新增 IR 类型时，应同时补执行逻辑、trace 输出和 timing stage 名称。
- 运行时临时状态不要放进执行器，应走 GraphNode cache 或函数节点返回值。

### `NodeTree/OmniRuntimeState.py`

runtime cache 系统。负责 committed cache、pending write、pending delete、namespace、snapshot、提交和失败回滚。

### `NodeTree/OmniDebug.py`

debug 格式化和聚合工具。

职责：

- 编译报告格式化。
- runtime trace 标签和颜色。
- runtime timing profile 聚合和周期输出。

### `NodeTree/GraphNode.py`

IR 级特殊节点定义。这里的节点不是普通业务函数节点的替代方案，只放需要改变编译、执行上下文、组/批处理语义或 runtime cache 语义的节点。

当前包含：

- 组引用节点。
- 组输入/输出节点。
- 批量组节点。
- runtime cache 读写/删除/调试节点。
- 节点重建时的 link/default value 缓存恢复工具。

### `NodeTree/FunctionNodeCore.py`

函数节点生成器。

职责：

- `@omni(...)` 装饰器。
- 从 Python 函数签名生成 socket。
- 识别 `list[T]` multi input。
- 动态创建继承 `OmniNode` 的节点类。

维护重点：

- 函数参数名会影响 socket identifier。
- 改函数签名可能影响旧树链接。
- 新增业务节点应优先走这里的函数生成路径，而不是手写 GraphNode。

### `NodeTree/OmniNodeSocketMapping.py`

Python 类型到 Blender socket 类型的映射表，包含 `_OmniCache`、`_OmniBone`、`_OmniVertexGroup` 等 marker 类型。

### `NodeTree/OmniNodeSocket.py`

自定义 socket 定义。负责 Scene、Text、Regex、Glob、Datablock、Cache、Bone、Modifier、MaterialSlot、VertexGroup、ShapeKey 等 socket。

### `NodeTree/OmniNodeOperator.py`

编辑器操作符和辅助 UI。

职责：

- 创建/销毁 Omni 树。
- 跳转组树。
- 编译、运行已编译结果、清理编译缓存、清理运行缓存。
- 节点重建。
- 菜单和 Node editor 操作。

### `NodeTree/OmniNodeDraw.py`

节点图绘制辅助。负责 bug 文本、overlay、绘制状态同步和清理。

### `OmniNodePanel.py`

VIEW_3D 侧边栏里的 OmniNode 批量管理面板。

职责：

- 列出所有 `OmniNodeTree`。
- 默认只提供每树一行的“编译运行”和“每帧运行”开关。
- 用一个布尔开关折叠高级操作。
- 高级模式下提供编译、运行已编译结果、清理编译缓存、清理运行缓存和状态显示。
- 面板只负责批量入口 UI，具体操作复用 `NodeTree/OmniNodeOperator.py` 中支持 `tree_name` 参数的内部 operator。

### `NodeTree/OmniNodeRegister.py`

节点注册和分类。负责注册 Graph 节点，从 `Function/` 加载 `@omni(enable=True)` 函数并生成节点类，建立 Blender add node 菜单分类。

### `NodeTree/Function/*.py`

函数节点库。提供实际业务逻辑。

维护重点：

- 普通函数节点应保持“输入参数 -> 返回值”的模型，复杂逻辑也应尽量在函数内部或 helper 中收敛。
- 需要临时跨帧状态时，暴露 `_OmniCache` 输入/输出，并要求用户接 cache 读写/删除节点；函数内部不得保存隐藏跨帧状态。
- 需要 C++ 加速时，优先新增平行节点，不要让原 Python 蓝本丢失。

## 新增功能的建议

### 新增功能决策顺序

新增节点或能力时，先按下面顺序判断：

1. 能否表达为“输入参数 -> 返回值”的业务逻辑？能就新增普通函数节点。
2. 是否只是多个已有节点的复用流程？优先做组树或把流程封装成新的函数节点，不要让用户维护复杂连线。
3. 是否需要跨帧临时状态？函数节点只暴露 `_OmniCache` 值，跨帧读写、删除、dump 必须接 GraphNode cache 节点。
4. 是否需要改变编译 IR、执行上下文、组/批处理命名空间、commit/rollback 或调试插桩？只有这种情况才新增 GraphNode。

### 新增普通函数节点

1. 在 `NodeTree/Function/` 合适模块中写 Python 函数。
2. 加 `@omni(enable=True, ...)`。
3. 用类型注解定义 socket 类型。
4. multi input 使用 `list[T]`。
5. 复杂业务直接封装在函数或 helper 中，不要要求用户用大量细节点重建固定流程。
6. 需要临时跨帧状态时，使用 `_OmniCache` 输入/输出，并在节点描述里说明 cache 读写和删除接法。

### 新增高级图节点

只适用于组、批处理、cache、控制流、调试指令等不适合表达为单次 `_func(*args)`、并且会影响编译 IR 或执行上下文的节点。

新增前必须确认：

- 不是因为业务逻辑复杂才手写节点。
- 不是因为想把常用流程包装成一个节点。
- 不是因为需要 native 加速。
- 确实需要新的 emitter、IR、执行逻辑或 runtime cache 语义。

需要同步修改：

- `GraphNode.py` 定义节点 UI 和 socket。
- `OmniIR.py` 定义必要 IR。
- `OmniCompiler.py` 增加 emitter。
- `OmniExecutor.py` 增加执行逻辑。
- `OmniDebug.py` 或 `RuntimeObserver` 增加 trace/timing 表达。

### 新增 native 加速节点

优先按平行节点做：

- Python 蓝本节点：定义行为。
- C++ 节点：复用同一套 Python 数据准备、cache、写回，只替换计算热点。

不要把 native 后端做成隐式全局开关。显式节点名更利于调试、对比和回退。

## 当前已知边界

- Multi input 顺序目前不是视觉插入顺序，而是编译器排序顺序。
- `NodeReroute` 断开输入时会向下游传 `None`。
- 默认值读取是尽力而为，不保证所有 Blender socket 都有 `default_value`。
- runtime cache 只在当前 Python 会话内可靠。
- 编译缓存不会自动代表 runtime 状态，也不会替代 cache 节点。
- 每帧运行依赖已编译 `CompiledGraph`；拓扑变化后需要重新编译或清理编译缓存。
- 函数节点 socket identifier 与函数参数名绑定，改名会影响已有树。
- C++ backend 不保存跨帧状态，跨帧状态仍由 Python runtime cache 管理。

### 空物体挂载边界

OmniNode 可以通过 `Object.ho_omni_root_tree` 挂到空物体上。这个挂载只作为资产入口和
Blender ID 强引用，用于追加或链接工作流；它不创建独立运行实例。

运行语义仍然保持树级：

- `OmniNodeTree` 是执行单位。
- `OmniNodeTree.is_frame_run_enabled` 仍然是树属性。
- 编译缓存仍然按树数据块隔离。
- runtime cache 仍然按 root tree 隔离。
- 一个空物体挂载只指向一棵 root `OmniNodeTree`。

如果多个空物体指向同一棵 `OmniNodeTree`，UI 只把按对象名稳定排序后的第一个当作有效挂载。
其它空物体只视为重复引用，不应表现为独立运行实例。
