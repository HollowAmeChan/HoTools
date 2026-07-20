# OmniNode 架构约定

本文档记录 OmniNode 当前的工程边界、编译/执行模型、缓存系统、调试系统和 native 后端开发流程。它不是用户手册，而是维护代码时用来统一判断的架构说明。

最重要的设计前提：OmniNode 的默认节点模型是“由函数生成节点”。节点图是给用户和技术美术渐进组合、检查、调参的编辑界面，不是鼓励用户在图上连接复杂逻辑的通用可视化编程环境。复杂业务应优先封装成新的函数节点，因为做节点本身应该足够简单；只有会改变图结构、编译 IR、执行上下文或 runtime cache 语义的特殊能力，才应该做成 GraphNode。

## 写作边界

- **应该写**：OmniNode通用节点模型、编译IR、执行上下文、runtime cache、调试机制、模块装卸和native开发边界。
- **不应该写**：Physics World专属阶段契约、某个solver完成度、物理公式、MC2源码差异、验收计划或提交流水。
- **内容路由**：Physics World公共结构写`doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；domain摘要写`doc/PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`；MC2稳定事实写`doc/MC2_BLUEPRINT.md`；通用Bake与外部几何缓存写`doc/PHYSICS_BAKE_NODE_BLUEPRINT.md`；历史只留Git。
- **示例原则**：solver示例只能用于说明通用框架机制，不得在本文承担该solver的状态或算法记录。

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

性能排查的第一动作是用帧调试器（见 Debug 章节「帧级统一计时」）看 `handler` 占 `frame` 的比例，而不是凭感觉改代码。据此把开销分成两类，各有明确的处理边界。

### addon 侧（handler）：缓存层是固定开销的常见来源

每帧固定开销里，真正的数值解算往往只占小头，缓存层的深拷贝/回收扫描才是大头。逐帧「读 → 原地改 → 写回同一对象」的滚动大状态（嵌套 dict、numpy 数组、大量含 Matrix 的记录）如果走默认快照隔离语义，会被每帧深拷贝多次、深度遍历多次。解法是让状态实现 dispose 协议走零拷贝路径——具体机制和实测收益见「7.1 Runtime cache 的资源值协议」的零拷贝加速一节。

### 引擎侧（engine/redraw）：固有成本，不该在 addon 里找优化

帧调试器报告里的 `engine/redraw = frame − handler` 是**反推值**，覆盖 `frame_change_post` 返回后 Blender 在 C 层做的事，Python 计时探不进去，addon 代码也改不动。它主要由三部分构成，都可用零代码隔离实验验证：

- **角色网格蒙皮变形**：armature modifier 每帧按新骨骼姿态重新变形整个角色网格（隐藏该网格可验证）。属于建模/绑定层（低模代理、降顶点数、GPU 蒙皮），不是 addon 能改的。
- **视口重绘**：关闭 3D 视口可验证。视口是必须绘制的，关不掉。
- **骨骼姿态求值 + depsgraph 依赖重算**：只要每帧改骨骼让物理生效，armature 全部骨骼的最终矩阵、约束、子物体重算就省不掉。

**判定何时停手**：当 handler 已压到个位数毫秒、占 frame 比例已低（例如 < 30%），说明 addon 侧已榨干，瓶颈在引擎。此时任何声称能从 Python 层压低 engine/redraw 的改动都是盲改，给不出可验证收益；能做的只有建模/绑定层（代理网格、降面）或接受现状。优化重心应转移或收尾。

### Mesh 物理动画输入与写回：双对象 + 常驻 GN 是固定架构

骨架/Shape Key 驱动的 Mesh 物理解算必须同时获得“本帧基础变形后的顶点”和“叠加物理后的显示顶点”。Blender 侧没有一个可接受性能的单对象 API 能稳定读取这两个修改器阶段。项目实测已经排除以下方案：

- BlendShape/Shape Key 逐帧写回：会产生不可接受的卡顿。
- 在单对象上逐帧开关或移动 GN 修改器来读取前后阶段：会触发大范围 depsgraph/软件内部回调和重算，产生不可接受的卡顿。
- 从同一源对象先后读取两个 evaluated 阶段：Blender 无法稳定、低成本地同时提供两个阶段的顶点快照，并且容易把物理结果反馈进下一帧输入。

唯一支持的 host 路径是双对象 + 常驻 GN：

```text
BasePose read object
  保留 Armature/Shape Key 等 topology-preserving 基础变形
  永久移除物理 GN output
  -> 每帧 evaluated positions/normals

Source/write object
  同一 final-proxy topology/vertex identity
  物理 GN modifier 常驻 topology-preserving 栈末端
  完整 PC2 播放时只允许受管 Mesh Cache modifier 位于其后
  -> 每帧只更新 POINT object-local offset attribute
```

BasePose 是只读求值源，不是第二个 solver mesh，也不是 MC2 reduction/render mapping。两对象必须共享等价的静态 topology signature；动画只允许移动既有顶点。PC2 modifier 只负责用户选择的最终显示回放，不得进入 BasePose read object，也不得把缓存结果反馈成下一帧 solver 输入。任何 Mesh solver 迁入 Physics World 时都不得用 BlendShape、单对象 modifier toggle/reorder 或双阶段单对象读取替换这条路径，除非先有新的 Blender 版本证据和完整性能基准，并由架构决策明确推翻本约定。

受管 GN 数据块不能只用手写整数 schema 判断是否需要刷新。`physicsWorld.gn_offset` 从当前 builder 临时生成期望结构指纹，覆盖 group interface、节点类型、语义属性、socket 默认值和 links；原有 GN ensure 路径比较数据块保存的 contract digest，builder 代码变化会自动产生新 digest，即使开发者忘记提升 schema 也会进入实检并原位重建、修复保留 modifier 引用和 `live GN -> legacy GN cache -> PC2` 顺序。整数 schema 只保留旧版迁移和拒绝高版本降级的职责。插件 register 阶段不得扫描 `bpy.data` 或刷新旧场景资源；显式完整检查由 `refresh_managed_gn_node_groups()` 提供。刷新后必须 `update_tag` 组和全部使用对象并更新 view layer；同 schema 下改坏 attribute name、接口、节点或连线的 Blender 回归必须长期保留。

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

#### 统一物理世界里的隐式物理对象

统一物理世界是上述规则的一个具体应用：跨帧 owner 仍然只能通过 Cache Read / Physics World Begin / Physics World Commit / Cache Write 进入 runtime cache，但 world owner 内部可以提供公开 registry 给普通函数节点写入。

`world.implicit_objects` 用于“隐式写入会参与模拟的物理对象”：

```text
属性节点 / 生成节点
  输入：authoring data / rules
  输出：属性对象

对象注册节点
  输入：PhysicsWorldCache, 属性对象, enabled
  输出：PhysicsWorldCache, item_count, dirty_count, version
  行为：调用 world.append_implicit_object(...)
```

边界：

- 这类节点仍是普通 `@omni` 函数节点，不新增 GraphNode，不改变 IR。
- 它们只能修改当前寄存器里传递的 `PhysicsWorldCache` owner；跨帧持久化仍由最终 Cache Write 提交。
- 它们不能写模块全局状态、不能直接写 solver slot、不能保存 native handle、不能写 Blender。
- 它们不走 `world.exchange`；`exchange` 只用于当前图执行内的命令、事件和临时共享数据。
- `implicit_objects` 的持久范围是“当前根树的兼容 runtime namespace”：普通帧和 `Physics World Begin` 不清空；成功重编译后，框架比较新旧 namespace 的 cache producer 合同。合同一致时保留 world owner，由 solver 自己处理参数热更新或局部重建；删除、替换、静音或改接注册/solver/Cache producer 导致合同时，定向释放对应 namespace。动态 cache key 或旧图没有 manifest 时保守释放，因此不需要额外的 source lease / mark-and-sweep。
- 注册节点默认不写 `always_run=True`。输入版本未变化时沿用已经提交的 registry，不为证明对象仍存在而每帧重复注册。
- 后续 solver 迁移时，VRM 骨链对象、MC2 设置对象、Jolt 刚体世界设置、Jolt 批量生成约束等都应使用 `implicit_objects`，solver step 在 prepare 阶段读取声明的 tag。跨模块识别名称必须来自 solver 子模块的权威 `names.py`（例如 `spring_vrm/names.py`、`rigid/names.py`），中央 `physicsWorld/names.py` 只作为公共索引和兼容重导出，不能在注册节点和 solver 内各写一份字符串。

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

案例（VRM 弹簧骨零拷贝）：`springBoneVRM_CPP` 每帧掉帧时，一个大 state dict（9 条链 joints + 数百条含 Matrix 的 write_records + numpy 数组）本质是「读 → 原地改 → 写回同一对象」的逐帧滚动状态，却被快照隔离每帧深拷贝三次、深度遍历多次。用帧调试器定位到缓存五项吃掉约 50ms（`CACHE_READ` 深拷 + `CACHE_WRITE` 深拷 + 提交期 `_snapshot_value` 再深拷 + `committed_ids` 在提交循环里 O(K×N) 重算可达 id + `dispose` 递归回收），真实物理只有 ~6.5ms。三步修复：（1）`finish_run` 改两阶段提交，`committed_ids` 从 O(K×N) 降到 O(N)；（2）`write_cache` 入 pending 时已拷私有副本，提交不再二次 `_snapshot_value`；（3）上述零拷贝 owner 协议，读写提交全程 `old is new`，dispose/committed_ids 整段跳过。贡献最大的是第 3 步，修复后缓存五项全部从耗时榜消失，handler 内 81% 是真实物理计算。这印证前述原则：零拷贝真正省的是深递归与深扫描，而不是浅拷贝本身。

### 7.2 缓存失效边界：哪些数据必须每帧重建

缓存优化的核心风险是**缓存太狠导致该失效的数据没失效**。一个典型反例：碰撞源列表（哪些物体/骨骼启用碰撞）若只用 `scene` 指针做 key，就等价于永久缓存，用户新增/修改碰撞体不生效——根因是缓存 key 太粗、失效条件太宽。

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

**MC2 静态失效契约**：新 `physicsWorld.mc2` 把 Blender raw snapshot 分为 topology、geometry、surface、config 四类短指纹，并由 slot-owned native context 保存和比较。Pin 权重与UV属于surface，rest坐标属于geometry，连接/父子关系属于topology，影响静态构建的重力方向属于config；变化触发staged slot/context重建，而不是热修改native particle state。其它solver若采用不同失效策略，必须在自己的capability/dirty key中明确声明，不能复用旧`physicsMC2`的缓存假设。

### 7.3 配置真值来源必须唯一

和缓存失效边界并列的另一个框架级原则：**同一个语义只能有一个真值来源**。当一份配置既能从 A 处推断、又能从 B 处标记时，A 和 B 迟早会不一致，其中一个会腐烂成误导性的死数据。运行时推断（节点输入、已有数据、拓扑）和持久标记（Blender 属性）尤其容易脱钩：解算器只认前者，某个预览/UI 却去消费后者，于是二者天然分叉。

维护约定：新增骨骼/物体/节点级配置时，先问“这个语义是否已经能从别处（节点输入、已有数据、拓扑）确定”。能确定就不要再加一个并行标记；确实需要持久标记时，让它成为唯一来源，不要和运行时推断竞争。预览也不该去猜解算行为——猜不到就诚实地不显示，而不是引入一个解算器不读的旁路标记。

> 该原则在物理世界模块中的长期约束见 `doc/PHYSICS_SIMULATION_PIPELINE_CONTRACT.md`；各 domain 当前覆盖情况见 `doc/PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`。

### 8. 编译缓存和 runtime cache 是两套系统，重编译按合同核对运行态

`OmniNodeTree._COMPILED_TREE_CACHE` 缓存的是 `CompiledGraph`，目的是避免每帧重复编译图。

它和 runtime cache 保存不同的数据：

- 编译缓存保存指令、寄存器、子树 IR、调试 trace。
- runtime cache 保存节点业务状态，例如物理位置、上一帧速度、软跟随状态。
- 清理 runtime cache 不会让图重新编译。

一次真正的编译成功后，`compile_cached()` 会让新旧 `CompiledGraph` 的 runtime-cache compatibility manifest 逐 namespace 对账。manifest 记录稳定 node runtime UID、group/batch 路径、Cache Read/Write/Delete key 合同，以及 Cache Write owner 的上游结构签名：

- 新旧合同均可证明且签名相同，保留该 namespace 已提交的 owner；数值/default CONST 不进入结构签名，调参后由 owner 内部的 parameter/static fingerprint 决定热更新或重建。
- producer 被删除、替换、静音、改接，group 路径改变，或 owner 上游结构发生变化时，只释放不兼容 namespace。
- 动态 cache key、旧版无 manifest 或任何无法证明的情况都保守释放，不猜测兼容。
- batch namespace 使用稳定 item identity 和同 identity 的 occurrence，不以列表 index 作为身份；列表重排不会串状态，重复 identity 仍相互隔离。

保留的是显式 runtime cache owner，不是旧 `CompiledGraph` 的寄存器值。新图始终拥有全新的寄存器数组，旧图的 `reg_values` 会在替换时显式置空。

边界必须严格区分：

- 编译缓存命中时没有发生编译，不清 runtime cache；因此 `run_frame_cached()` 的正常逐帧路径不会重置物理。
- 编译失败时旧 runtime cache 和旧 `CompiledGraph` 都保留，用户可以修正图后继续，不产生“编译没成功但状态丢了”的半成功结果。
- `tree.clear_compile_cache()` 本身只移除 `CompiledGraph`；因为下一次编译没有旧 manifest 可供证明，已有 runtime namespace 会在那次成功编译时保守释放。
- 手动清 runtime cache 不清编译缓存；它只要求已有图在下一次运行时重建业务状态。
- 清理根树 runtime cache 会覆盖该根树下的组树和批量子树 namespace，但不影响其他根树。

当前入口：

- `tree.compile_cached(force=True)`：强制编译并更新编译缓存。
- `tree.run()`：强制编译，然后运行已编译结果。
- `tree.run_compiled()`：只运行已有编译缓存；没有缓存时报错。
- `tree.run_frame_cached()`：每帧运行入口，没有编译缓存时先编译一次，之后复用。
- `tree.clear_compile_cache()`：清理当前树编译缓存。

维护约定：

- 会改变节点、socket、link、树 IO 或特殊节点语义的操作，必须清理相关树的编译缓存。
- 每帧运行依赖编译缓存，所以调试“为什么改图后没有变化”时先检查是否需要重新编译。成功重编译只负责框架可证明的 namespace 兼容性；兼容 owner 内的参数、拓扑、generation 与 native slot 更新仍由各业务 owner 的既有签名合同负责。
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

统一 MC2 的 Python 侧分层约定：

- `physicsWorld/mc2/` 只有一个 solver identity；MeshCloth、BoneCloth、BoneSpring 位于 `setups/`，不建立 Python/C++ 平行节点或 backend selector。
- MC2只有一个公开solver step；一次调用规整全部active tasks、先同步所有slot，再按substep批量推进，最后统一readback/result transaction。MC2 component不映射为独立节点/step，而映射为粒子参数profile与task的组合；task各自拥有slot/native context，prepare全通过后才进入world写事务。
- setup adapter 负责 Blender authoring/frame snapshot、静态 builder 输入和结果目标映射；它不拥有 solver 时间或第二套粒子状态。
- `physicsWorld/mc2/solver.py` 负责 slot/context 生命周期、frame policy、native 调用和 result publication，不直接写 Blender。
- native context 由对应 MC2 slot 唯一持有，所有持久资源随 slot dispose；旧 `physicsMC2` full-core/context 在替代资格门禁关闭前只作产品语义、性能和依赖审计输入，取得准入后再独立删除。
- 单task MC2 self primitive、grid run、broadphase candidate、half contact cache、fixed-point sum scratch、intersect record与particle flag属于slot-owned native context；跨物体阶段由`world.backend_resources["mc2_interaction_v0"]`持有临时聚合buffer、owner/group过滤和跨帧intersection history。它只协调开启产品开关的Mesh task，在Motion与Post之间运行并散回，不接管task persistent state，也不能借外部collider表达。
- HoTools Mesh产品只公开一个`radius × 顶点组`半径真值；外部碰撞消费普通radius，self envelope固定派生为`radius * 0.25`。source oracle可在低层setup继续使用独立thickness，但不得重新暴露为产品节点输入。
- MC2 debug沿用SpringBone VRM的全隐式请求模型：debug入口自动发现world内MC2 slots，后端按请求在下一推进帧产出语义化snapshot，solver renderer负责分层显示；不新增一套供用户连接中间数组的节点图surface。
- MC2产品决策、支持域、实现所有权、数值陷阱和维护门禁统一见`doc/MC2_BLUEPRINT.md`；当前阶段只看`doc/PHYSICS_WORLD_IMPLEMENTATION_STATUS.md`。

C++ 侧职责：

- 只处理已经整理好的数组和标量参数。
- 原地更新数值 buffer。
- 不直接访问 `bpy`。
- 不保存 Blender 对象指针。
- 不保存隐藏的跨帧全局状态；需要持久化的数值状态只能存在于 slot-owned native context。

### 为什么不把编译器/执行器整体迁到 C++

已评估并否决。根本障碍：`op.func(*args)` 永远是 Python 回调（GIL 和调用边界不消失）；编译器必须读 Blender `NodeTree`/`Node`/`Socket`/`Link`（全是 RNA，只能 Python 访问）；cache 值是任意 Python 对象（`bpy.types.Object`、numpy、`OmniCacheOwnerDict`）无法进 C++ 容器。把执行器 for 循环搬到 C++ 每帧只省 isinstance 和 list 分配（~50–150µs/100 节点），而函数体本身通常 0.5–10ms，收益比极低、成本极高。

正确分层是固定结论：**Python 管调度和 Blender 边界，C++ 管经测量确认的数值与批处理热点**（solver kernel、persistent native context、collider/矩阵批量转换）。一次性构建不因“能迁移”就进入C++；只有代表性大资产证明它是瓶颈时才调整边界。

Python模块按真实owner和生命周期拆分，不按“每个dataclass/参数阶段一个转发文件”机械拆分。内部wrapper若只做同名参数转发、同名math调用或无附加校验/所有权/缓存语义的re-export，应删除并让调用方直达唯一实现；兼容别名只允许出现在明确的公开边界，并带删除计划。纯整理必须用既有fixture、生产资产和性能baseline证明行为未变，不能顺带改变默认值、更新频率或支持域。

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
3. 从输出节点反向 DFS 收集可达子图；如果遇到 `node.mute == True`，先读取节点类上的 `_omni_mute_passthrough` 映射，把 muted 输出追溯到对应 muted 输入，再继续搜索该输入的上游。
4. 编译输入 socket 时只接受仍在可执行子图内的 link，以及编译器生成的 muted passthrough 虚拟 link；没有透传映射或透传输入未连接时，仍按未连接处理并走目标 socket 默认值。
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
2. `compiled.ensure_reg_arrays()` 确保持久化寄存器数组存在，`registers = compiled.reg_values`（跨帧复用，不再每帧 `[None] * reg_count`）。
3. 按顺序执行 IR，写寄存器统一走 `_write_reg`（身份比较，变化才递增版本号）。
4. 出错时标记 run failed，并把错误写到节点 bug state。
5. root run 结束时提交或丢弃 pending cache。
6. 返回 `output_regs` 对应的结果字典。

`RuntimeObserver` 负责执行期观察，不负责业务逻辑：

- 完整 runtime trace。
- 每步 timing stage 名称。
- cache read/write/delete/dump 日志。
- subtree / batch subtree 进入和退出日志。

### 节点级懒求值

执行器实现了"输入未变则跳过节点"的懒求值：连续帧里只有输入真正变化的节点才重新执行，参数类节点（数值、preset 等）在用户不调参时被跳过，复用上帧输出。物理 solver 等每帧必须推进的节点通过 `always_run` 绕过跳过。

运行机制：

- **寄存器版本跟踪**：`CompiledGraph` 持有跨帧的 `reg_values`（任意 Python 值，`list`）和 `reg_versions`（整数版本号，`array.array`，C 层批量比较）。`OmniExecutor._write_reg` 用身份比较（`is not`），值变化才递增版本号。`OMNI_NO_CHANGE` sentinel 让 always_run 节点主动声明"本输出未变"，执行了但不递增版本，避免下游连锁重算。
- **skip 判定**：`_should_skip_opcall` 把当前输入寄存器版本填进预分配 buffer，与上次执行的 `last_snapshot` 做 C 层批量比较；相等则跳过函数调用。`_should_skip_subtree` 基于父树寄存器对整棵子树做同样判定。热路径零内存分配。
- **always_run**：`@omni(always_run=True)` 由 `FunctionNodeCore` 识别，`OmniCompiler` emit OpCall 时写入 `has_always_run`（默认取 `is_output_node`）；编译期 `_compute_has_always_run` 递归标注 `CompiledGraph.has_always_run_node`。物理 solver、Cache 节点、输出节点、debug 节点必须标 always_run。
- **共享子树防污染**：编译期 `_compute_ref_counts` 统计每棵子树被 SubtreeCall/BatchSubtreeCall 引用的次数，`inner_lazy_eval = (ref_count == 1)`。被多个组实例引用的共享子树只做整块 skip、不做内部逐节点 skip，避免不同调用路径共用一份 `reg_values` 时版本快照互相污染。
- **op_type 派发**：IR 类型带 `op_type` 类常量，执行器按整数码分派而非 isinstance 顺序链。

CONST 的语义边界（不是缺口，是设计）：

- 未连接的输入 socket 编译成裸 tuple `("CONST", reg, value)`，`value` 在编译期从 `socket.default_value` 固化。运行时只做 `registers[reg] = value`，不重读 RNA、版本恒为 0，下游可安全 skip。曲线 socket 同样在编译期固化 payload，不产生每帧 RNA 遍历开销。
- **改 socket 默认值需手动重编译才生效**，这对所有 socket（数值、曲线等）统一成立，是有意契约：编辑期改值 → 用户点编译 → `CompiledGraph` 重建、CONST 重新固化。运行时不去嗅探 socket 默认值变化，因此没有"运行中改曲线自动失效下游"这一路径，也不需要为此加特化 IR。若将来确实需要"运行中难判脏的 socket 值"自动失效，应设计成 socket 级的通用脏签名协议 + 一条通用 IR，而不是给曲线打补丁。
- 成功重编译会重建寄存器版本数组，并按 runtime compatibility manifest 保留兼容 owner、释放不兼容 namespace。参数节点和隐式对象注册节点在新图第一次运行时重新执行；后续输入未变时继续由懒求值跳过。编译缓存命中不触发对账。

维护约定：

- 有 Blender 副作用（写 bpy、调 ops）或每帧必须推进状态的节点，必须标 `always_run=True`，否则会被错误跳过。
- 失效边界必须可靠：重编译时 `CompiledGraph` 整体重建，旧版本数组显式置空；runtime cache 只按 manifest 对账，不能因寄存器范围相同就推断 owner 兼容。只清编译缓存时先释放旧 `reg_values`，runtime cache 在下一次成功编译因缺少旧 manifest 而保守释放。`reg_values` 跨帧持有 bpy 引用，重编译或删树时必须显式置空防悬空引用。

## Debug 系统

主要文件：

```text
NodeTree/OmniDebug.py
NodeTree/OmniTiming.py
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

#### 编译流程可视化

树属性：

```text
show_compile_flow
compile_flow_cycle_duration
```

`show_compile_flow` 是独立于命令行 `debug_compile` 的编辑器动画开关。编译器在 `CompiledGraph.compile_flow` 中保存实际编译结果的轻量快照，绘制层不得重新遍历 Blender links 猜测数据流。快照包含：

- 最终 topo 中会运行的节点及顺序；输出节点作为终点保留。
- 编译输入真正消费的 source socket、target socket 与寄存器号。
- mute passthrough 展开后的直连边与经过的 muted node 路径。
- `always_run` 节点标记；cache op 和包含 always-run 子树的 group 同样按常驻运行处理。

动画语义固定如下：

- 一个周期从上游到下游按 topo 顺序播放；同级节点的编号就是实际稳定排序。
- 普通节点和普通 link 统一使用白色；link 流光在目标节点点亮前沿 source → target 前进，并在流光头显示 `rN`。
- muted 节点不获得运行序号，因为它不生成执行 op；但透传流光必须穿过该节点，并触发低亮白色边缘呼吸，表示“跳过执行、保留寄存器透传”。
- 只有 `always_run` 节点和由其产生的 link 使用循环彩色呼吸，表示它不受普通 lazy skip 控制；色相轮转频率固定为 `0.65` 圈/秒，不受 topo 播放周期影响。
- 动画只用于解释已缓存的编译结果，不代表当前帧真实执行/skip 状态；真实耗时由“节点运行计时”负责。

坐标合同：该动画使用 Node Editor `POST_VIEW` 绘制。`location_absolute` 是未缩放的节点位置，进入 GPU batch 前必须乘 `preferences.system.ui_scale`；实时 UI 中非零的 `node.dimensions` 已经是最终绘制宽高，必须原样加到缩放后的位置，禁止再次缩放。只有后台测试或首帧尚未完成布局、`dimensions == (0, 0)` 时，才使用 `node.width/height * ui_scale` 作为 fallback。socket 近似偏移和 Bezier 最小控制柄仍需乘 `ui_scale`。Frame 子节点直接使用 `location_absolute`，不得再次叠加父级位置。

性能约定：动画关闭时不得注册 redraw timer。开启后使用单一全局 handler 和单一 24 FPS timer；关闭最后一个可视化树、清除编译缓存或注销插件时必须停止 timer。编译器只生成字符串/整数 tuple 快照，不得为动画保留额外 node/socket 强引用。

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
show_runtime_timing
runtime_timing_sample_interval
```

实现：

- 编译器总是插入 `RuntimeTimingBeginCall` 和 `RuntimeTimingEndCall`。
- `debug_runtime_timing` 是命令行聚合报告开关；`show_runtime_timing` 是节点顶部计时开关。
- 命令行开启时每帧计时并聚合；仅开启节点显示时，只有采样到期的帧才真正启用 step 计时。
- 每个 IR step 会记录一个 stage。
- `OmniRuntimeTiming.record()` 把样本写入独立的 consumer profile。
- 命令行按 `debug_runtime_timing_interval` 聚合；节点叠加按 `runtime_timing_sample_interval` 抽取单帧样本，默认 3 秒。
- `OmniDebug` 只格式化命令行报告，`OmniNodeDraw.DrawRuntimeTiming` 只消费节点聚合结果。

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
- 节点显示把本次样本中同一节点对应的多个 IR step 求和，不跨帧求平均；绿色为不超过 1ms，黄色为 1-8ms，红色为 8ms 及以上。

#### 计时频率与性能硬契约

先区分“编译插桩”和“运行计时”：`CompilerContext.finish()` 每次编译都把 `RuntimeTimingBeginCall` / `RuntimeTimingEndCall` 写进 IR，但编译阶段不调用计时器。执行器真正遇到 Begin 标记时，才根据下面的运行时条件决定是否创建 `timing_stages` 并对每个 step 调用 `time.perf_counter()`。

| 运行状态 | 根树入口频率门控 | 本次执行逐 step 计时 | 节点叠加重绘 |
| --- | --- | --- | --- |
| 两个计时开关都关闭 | 不读取 overlay 墙钟 | 否 | 否 |
| 仅 `show_runtime_timing=True`，尚未到采样时刻 | 整次根执行共享一次 `perf_counter`，各树只比较 deadline | 否 | 否 |
| 仅 `show_runtime_timing=True`，采样到期 | 该次执行取得一次采样权 | 是，只计当前这一帧/次执行 | 执行完成后一次 |
| `debug_runtime_timing=True` | 不论节点采样是否到期 | 是，每一次树执行都计时 | 仅节点采样到期时一次 |

频率定义与调用顺序必须保持如下语义：

1. 节点采样使用 `time.perf_counter()` 的墙钟间隔，不使用帧号，不存在后台 timer。同一次根执行创建一个共享 gate timestamp，根树及全部子树复用，因此无论子树被调用多少次，频率门控最多读取一次墙钟。启用后第一次实际执行立即采样；之后只有到期后的下一次实际树执行才采样。树不运行就不会采样或重绘。
2. `runtime_timing_sample_interval` 只控制节点叠加采样，默认 3 秒。修改间隔、重新开启显示或完整重编译会重置 deadline，使下一次执行立即采样。
3. `debug_runtime_timing_interval` 只控制命令行报告多久 flush/print，**不降低命令行计时频率**。只要 `debug_runtime_timing=True`，每次执行、每个 IR step 都会计时。
4. 两个开关同时开启时，命令行消费者已经要求每次执行逐 step 计时；3 秒节点采样只限制节点名映射、显示数据替换和 `tag_redraw`，不能消除命令行计时成本。
5. 每帧路径由 `run_frame_cached()` 在根树入口决定一次 overlay 采样，并把 bool 原样传进根 `RuntimeObserver`，禁止在同一次根执行的 Begin 标记再次读取墙钟。手动 `run_compiled()` 没有外层 frame collector，由 Begin 标记决定一次；两条路径都必须保证每次根执行最多一次墙钟门控。
6. 子树 observer 不继承父树的 overlay 采样权，但必须继承同一次根执行的 gate timestamp。每个子树数据块依据自身的 `show_runtime_timing` 和采样 deadline 独立比较；同一子树在一个间隔内被多次调用时，只有第一个到期调用取得样本，后续调用不再读取墙钟。
7. 取得计时权的执行在 Begin 记录树起点，每个普通 IR step 在 `step_begin/step_end` 各读取一次时钟，End 计算 total。Begin/End 标记自身不作为 step 显示；节点顶部只显示映射到该节点的 step 在本次样本内的合计。
8. overlay profile 永远只保留最后一份单次样本，`sample_count` 固定为 1；禁止恢复跨帧累加或平均。`DrawRuntimeTiming.update_tree()` 只在该样本发布时替换数据并调用一次 `tag_redraw`。
9. 未取得计时权且命令行计时关闭时，内建 timing 路径不得调用逐 step `perf_counter`，也不得为 phases、stage 或节点映射分配字典。IR 中只保留两个轻量标记分支。Tracy 是独立 profiler；开启 Tracy 后产生的 zone 成本不属于这里的“计时关闭”保证。

以后修改 timing 必须同时满足以下禁止项：

- 禁止把 `tag_redraw` 放进每帧执行路径或 `record()` 路径；它只能由到期 overlay snapshot 的发布触发。
- 禁止用 `debug_runtime_timing_interval` 冒充采样频率；它是输出频率，不是测量频率。
- 禁止让节点显示为了平滑而跨帧平均、EMA 或持续收集所有帧。
- 禁止新增 timing consumer 却不在本节声明它是“每次执行”还是“低频采样”，以及它是否要求逐 step 时钟。
- 修改门控、profile 或绘制发布时，必须保留 `tests/test_runtime_timing.py` 的默认 3 秒、deadline、根/子树共享单次墙钟、单样本替换和 schedule reset 回归，并运行 Blender 集成测试。

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

1. 明确运行时是否属于统一物理世界迁移。
2. Python 层把 Blender 数据整理成 spec / buffer，不让 C++ 直接碰 `bpy`。
3. C++ 桥接层只暴露窄接口。
4. C++ solver 层只处理数值计算。
5. 用 reference case、native smoke test 和 benchmark 验证行为和耗时。
6. 编译到对应 `HotoolsPackage`。
7. 用 Blender Python import 验证，再在 Blender 中 smoke test 节点。

统一物理世界下的新迁移 solver 采用 C++ 单实现策略：不再新增平行 Python solver 节点，也不再按 backend 暴露 `xxx` / `xxx_CPP` 两套节点。Python 运行时只负责 spec、slot 生命周期、buffer 打包、result stream、writeback plan 和调试可视化。旧实现只允许在删除前作产品语义、生产行为、性能和依赖审计材料，不能作为source oracle；SpringBone 已完成对拍并删除旧 Python runtime 与 35 参数 native ABI。

MC2共享数值实现由`_native/src/mc2_kernels.cpp/.hpp`持有；文件名和owner不得再依附旧full-core接口。旧数组solve、旧context、旧BoneCloth IO及其构建选项已经物理删除。`build.bat 311 native`与`build.bat 313 native`只构建新Physics World的V0 context、static build、self collision和共享kernel，不得恢复legacy源码或公开ABI。

MC2的P-08替代资格总门禁已经放行。P-09删除阶段以“旧Python节点/package、旧native context/IO删除，共享kernel与新V0/static/self保留”为机械边界；不得借删除提交重写新solver语义或引入兼容adapter。

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
- `.gitignore` 只管本地误提交；`.releaseignore` 决定安装包内容，release workflow 在压缩前校验测试文件没有混入。

## 文件职责

### `__init__.py`

OmniNode 模块入口。负责注册/注销 NodeTree、socket、节点、操作符、绘制辅助和侧边栏面板等模块。OmniNode 不再维护自己的子 `lib` 目录，第三方依赖应接到 HoTools 顶层公共库。

### `tests/`

OmniNode 核心测试目录。编译器、执行器、runtime state、注册合同、timing 等跨模块测试统一放在这里；`NodeTree/` 运行时代码目录禁止直接放置 `test_*.py`。

solver/domain 自有测试继续由对应模块拥有，例如 `NodeTree/Function/physicsWorld/test/`、`rigid/test/` 和 `spring_vrm/test/`，不得为了目录表面统一而拆散 fixtures、runner 与被测实现。测试脚本必须从 `__file__` 推导仓库路径，禁止写开发机绝对路径。具体运行方式见 `tests/README.md`。

### `NodeTree/OmniNodeTree.py`

定义 `OmniNodeTree` 数据块。

职责：

- 树级属性：自动更新、每帧运行、debug 开关、组输入/输出。
- 编译缓存管理。
- `run()` / `run_compiled()` / `run_frame_cached()`。
- frame change handler。
- Node editor 树属性面板。

### `NodeTree/OmniIR.py`

运行时 IR 定义。该文件不应该依赖 Blender link 结构，也不应该包含执行逻辑。`CompiledGraph.compile_flow` 只承载编译器生成的不可变字符串/整数可视化快照，不参与执行。

### `NodeTree/OmniCompiler.py`

编译器。负责从 Blender 图生成 `CompiledGraph`。

维护重点：

- 所有编辑器特殊节点都应在这里归一化。
- 新增 GraphNode 时，应增加明确 emitter；普通业务节点不应在这里开分支。
- 不要让没有 `_func` 的节点进入普通函数调用。
- 编译流程可视化必须在实际分配/消费寄存器的位置记录 link；特殊 emitter 不得绕过 `compile_flow` 合同后让绘制层补猜。

### `NodeTree/OmniExecutor.py`

执行器。负责按 IR 顺序运行。

维护重点：

- 执行器不理解 Blender link。
- 新增 IR 类型时，应同时补执行逻辑、trace 输出和 timing stage 名称。
- 运行时临时状态不要放进执行器，应走 GraphNode cache 或函数节点返回值。

### `NodeTree/OmniRuntimeState.py`

runtime cache 系统。负责 committed cache、pending write、pending delete、namespace、snapshot、提交和失败回滚。

### `NodeTree/OmniDebug.py`

debug 格式化工具。

职责：

- 编译报告格式化。
- runtime trace 标签和颜色。
- runtime timing 命令行报告格式化。

### `NodeTree/OmniTiming.py`

独立的运行时计时聚合器。

职责：

- 判断命令行和节点叠加两个消费者是否要求采样。
- 维护命令行聚合窗口，并调度节点叠加的低频单帧采样。
- 输出不依赖 Blender 绘制或终端格式的 timing snapshot。

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
- 生成 `_omni_mute_passthrough`，供 `OmniCompiler` 在 `node.mute == True` 时做编译期透传。默认只自动匹配唯一同类型、非 multi 的输入/输出；多输入同类型等有歧义节点应显式设置 `mute_passthrough`。

`mute_passthrough` 支持：

- `False`：禁用该节点的 muted 透传，保留旧屏障语义。
- `True` 或 `"auto"`：使用唯一同类型自动匹配。
- `{"_OUTPUT0": "value"}`：按“输出 identifier -> 输入 identifier”显式声明。
- `[("value", "_OUTPUT0")]`：按 Blender internal link 的“输入 -> 输出”方向显式声明。

自动匹配只适用于语义明确的普通值节点。`Any/object`、multi input、物理生命周期、任务/配置生成器以及多输出副作用节点必须显式声明 `mute_passthrough` 或 `False`，不得让相同socket类型替代业务语义。多输出节点逐输出审计：对象、名称、路径等原样返回值都要映射；计数、命中、查询结果和新建datablock没有合法输入时保持未映射。物理世界域的全部公开函数节点必须显式声明mute合同，避免`object_scope -> world`一类Any误配。`tests/test_blender_mute_passthrough_contract.py`同时验证注册映射和真实muted图编译。

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

Node Editor overlay 集中实现。bug/description、socket preview、运行计时和编译流程动画都在这里维护各自 payload、handler、状态同步和清理。编译流程动画的相位数学属于绘制实现，不单独拆模块；动画关闭时不得保留 timer 或持续 redraw。

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

物理解算器节点按 solver manifest 原子化注册：

- 顶层只显示“解算器”，其下为每个 solver 的折叠子菜单。
- `Function/physicsWorld/<solver>/__init__.py` 的 `SOLVER_MODULE` 必须通过 `solver_id`、`menu_name` 和 `nodes` 声明菜单身份、显示名和节点模块。
- `Function/physicsWorld/registry.py::iter_solver_node_groups()` 保留 solver 所有权并输出分组；`OmniNodeRegister.py` 不得根据节点标签猜测 solver，也不得维护内置 solver 名单。
- Blender 4.5 的 `nodeitems_utils.NodeCategory` 只支持一层分类。solver 子层由动态 `bpy.types.Menu` 实现，父分类通过 `NodeItemCustom` 调用 `layout.menu(...)`。
- 动态 solver 菜单必须先于 node categories 注册；注销时必须先注销 node categories，再注销 solver 菜单和节点类。

### `NodeTree/Function/*.py`

函数节点库。提供实际业务逻辑。

维护重点：

- 普通函数节点应保持“输入参数 -> 返回值”的模型，复杂逻辑也应尽量在函数内部或 helper 中收敛。
- `input_init.description` 写入 Blender `NodeSocket.description` 后最多保留 64 个 UTF-8 字节；公开 socket 描述必须控制在 60 字节以内。枚举优先写短值映射，需要分行时使用显式换行，不得依赖 tooltip 自动换行。
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
## 2026-07-07 追加：物理世界 solver 声明入口

`physicsWorld/declarations.py` 是 solver 声明 registry 的过渡汇总层；`physicsWorld/names.py` 只保留跨 solver 通用常量和子模块名称的兼容重导出。solver 自有名称、能力、声明和 debug mode 的权威定义应位于各自子模块。

`physicsWorld/registry.py` 是 solver 子模块描述符的装载入口。公共 `world.py` 只能通过 registry 调用 `scope_restart_handlers` / `scope_collectors` 等通用 hook；`declarations.py` 也通过 registry 汇总内建 solver declaration。公共层不能直接导入 rigid/Jolt、SpringBone 或未来 cloth domain 的私有实现。

component/solver 描述符还可以声明 `blender_properties`。字段 schema、默认值、范围和 UI 元数据归 capability 所有，domain 的 `properties.py` 生成 Blender class/binding 声明，registry 负责统一 register/unregister。共享 `PG_Hotools_BoneCollision` 位于 `physicsWorld.collision.properties`，持久路径仍为 `Bone.hotools_collision`；面板、操作器和预览位于 `physicsWorld.ui`，只消费该 capability。

`physicsWorld/names.py` 与根级 `physicsWorld/__init__.py` 对 solver 自有名称、能力和声明只保留兼容惰性重导出；导入公共包不应主动装载 rigid/Jolt 私有模块。

约定：domain 内 `declaration.py` 只重导出或补充 audit；`PhysicsWorldCache.omni_cache_debug_snapshot()` 输出 `solver_declarations`；新 solver 先补声明再接节点/native。

硬约束：`writeback.solver_inline_writeback=False`，solver 内不直接写 Blender 数据。

当前内置声明：`spring_vrm`、`rigid_jolt`。

## 2026-07-10 追加：Rigid/Jolt 约束调试与用户文档

`physicsWorld/rigid/debug_draw.py` 只维护 world 快照采样、颜色分组和 Blender viewport handler。不同约束的自由度、axis、limit、motor target 与 current value 由 `physicsWorld/rigid/constraint_debug/` 中的逐类型 renderer 持有；当前 registry 覆盖 Fixed、Point、Distance、Hinge、Slider、Cone。

约束 renderer 的输入只能是 Jolt adapter 实际消费的 `ConstraintSpec` 和 `rigid_constraint_state` result，不读取 native handle，不从 live Blender transform 重新猜测 solver 状态。输出只能是纯 tuple 线段快照。未知类型必须退化为通用 anchor frame，并写入 `unknown_constraint_types` audit。

Rigid/Jolt 面向用户的约束指南位于 `physicsWorld/rigid/docs/`。文档必须明确区分 Jolt 原生能力与 HoTools 已接入能力；新增约束类型时，spec/binding、动态 result、专用 renderer、文档和测试视为同一个交付单元。
