# OmniNode 架构约定

本文档记录 OmniNode 当前的工程边界、编译/执行模型、缓存系统、调试系统和 native 后端开发流程。它不是用户手册，而是维护代码时用来统一判断的架构说明。

## 一句话模型

OmniNode 是一个基于 Blender `NodeTree` 的轻量函数图系统：

- 编辑阶段使用 Blender `NodeTree`、`Node`、`NodeSocket`、`NodeLink` 描述图。
- 编译阶段把从输出节点可达的子图转换成 `CompiledGraph` 和一组简单 IR 指令。
- 执行阶段只跑 IR，不再遍历 Blender links。
- 全局临时状态必须通过 runtime cache 节点显式读写。
- 读写已有 Blender 数据或已有数据块不属于临时 cache 约束。
- 少数性能热点可以提供 C++ backend 节点，但 Python 节点层仍负责 Blender 数据和节点接口。

## 核心边界

### 1. Blender 节点图只负责编辑表达

Blender 节点、socket、link 是编辑器数据结构，不是运行时执行结构。运行时不应该在执行过程中追踪 `NodeLink`，也不应该把 Blender 原生节点当作普通 OmniNode 调用。

维护时需要区分：

- OmniNode 自定义节点：继承 `OmniNode`，通常有 `_func`、`is_output_node`、`set_bug_state()` 等能力。
- Blender 原生编辑节点：例如 `NodeFrame`、`NodeReroute`，它们没有 OmniNode 的状态和 `_func`。

原生编辑节点必须在编译器里显式适配，不能让它们落入普通 `OpCall`。

### 2. 输出节点决定可执行子图

编译入口不是整棵图的所有节点，而是：

```text
tree.nodes 中 is_output_node == True 的节点
```

`CompilerContext._collect_reachable_graph()` 从这些输出节点反向 DFS，收集可达节点和 links，再交给 `OmniCompiler.topo_sort()` 做拓扑排序。没有连接到输出节点的节点不会执行。

这允许节点图里保留实验节点，但也意味着“看得见的节点”不等于“运行时会执行的节点”。

### 3. 寄存器是运行时数据边界

编译阶段使用 `(node.name, socket.identifier)` 作为 socket 输出到寄存器的映射键。

普通函数节点的规则：

- 输入 socket 编译为输入寄存器列表。
- 输出 socket 分配新寄存器。
- 执行时调用 `_func(*args)`，再把返回值写回输出寄存器。

默认值规则：

- 没有 link 的输入 socket 会编译成 `("CONST", reg, value)`。
- 如果 socket 没有安全的 `default_value`，当前返回 `None`。

### 4. 全局临时状态只能通过 Cache 节点

OmniNode 当前不对跨树 IO 做强约束。树输入/输出只是组节点接口的一种表达方式，不承担“全局参数系统”的职责。

真正需要严格约束的是全局临时状态：如果某个状态不是已有 Blender 数据或已有数据块，而是 OmniNode 运行过程中产生、需要被后续运行继续读取的临时数据，就必须走 runtime cache 节点。

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
- 全局临时状态、跨帧模拟状态、运行时中间状态必须暴露为 cache 读写节点，而不是藏在模块全局变量、节点实例字段或 C++ 全局状态里。
- 跨树 IO 目前只是组调用接口约定，不作为全局参数约束。

### 5. Runtime cache 是显式状态系统

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

### 6. 编译缓存和 runtime cache 是两套系统

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

### 7. C++ backend 只接管计算热点

native 后端不替代 OmniNode 编译器和执行器。它只为特定节点提供加速实现。

当前正式模式是平行节点：

- `网格物理-XPBD`：Python 标准实现，作为行为蓝本。
- `网格物理-XPBD-CPP`：C++ 后端实现，保持相同输入、输出、cache 语义和跳帧行为。

Python 侧职责：

- 校验 Blender 对象、mesh、shape key、vertex group、frame continuity。
- 批量读取和写回 Blender 数据。
- 管理 runtime cache。
- 决定是否重建 cache、是否跳帧保护、是否调用 native。

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
3. 从输出节点反向 DFS 收集可达子图。
4. 拓扑排序。
5. 逐节点调用 emitter。
6. 输出 `CompiledGraph`。

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

### 4. 节点级性能 debug

部分功能节点有自己的 `debug_output` 输入，例如：

```text
网格物理-XPBD
网格物理-XPBD-CPP
```

这类日志用于观察节点内部阶段，例如 validate、cache、transform、native、write。它和树级 runtime timing 互补：

- 树级 timing 看哪个 IR step 慢。
- 节点级 debug 看某个复杂节点内部哪一步慢。

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
& "D:\Blender\Blender 4.5\4.5\python\bin\python.exe" _native\tests\test_mesh_xpbd_native.py
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

OmniNode 模块入口。负责把 `lib` 和版本化 native package 路径加入 `sys.path`，并注册/注销 NodeTree、socket、节点、操作符、绘制辅助等模块。

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
- 新增高级图节点时，应增加明确 emitter。
- 不要让没有 `_func` 的节点进入普通函数调用。

### `NodeTree/OmniExecutor.py`

执行器。负责按 IR 顺序运行。

维护重点：

- 执行器不理解 Blender link。
- 新增 IR 类型时，应同时补执行逻辑、trace 输出和 timing stage 名称。
- 运行时临时状态不要放进执行器，应走 runtime cache 或函数节点返回值。

### `NodeTree/OmniRuntimeState.py`

runtime cache 系统。负责 committed cache、pending write、pending delete、namespace、snapshot、提交和失败回滚。

### `NodeTree/OmniDebug.py`

debug 格式化和聚合工具。

职责：

- 编译报告格式化。
- runtime trace 标签和颜色。
- runtime timing profile 聚合和周期输出。

### `NodeTree/GraphNode.py`

高级图节点定义。

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

### `NodeTree/OmniNodeRegister.py`

节点注册和分类。负责注册 Graph 节点，从 `Function/` 加载 `@omni(enable=True)` 函数并生成节点类，建立 Blender add node 菜单分类。

### `NodeTree/Function/*.py`

函数节点库。提供实际业务逻辑。

维护重点：

- 普通函数节点应保持“输入参数 -> 返回值”的模型。
- 需要临时跨帧状态时，暴露 `_OmniCache` 输入/输出，并要求用户接缓存读写节点。
- 需要 C++ 加速时，优先新增平行节点，不要让原 Python 蓝本丢失。

## 新增功能的建议

### 新增普通函数节点

1. 在 `NodeTree/Function/` 合适模块中写 Python 函数。
2. 加 `@omni(enable=True, ...)`。
3. 用类型注解定义 socket 类型。
4. multi input 使用 `list[T]`。
5. 需要临时跨帧状态时，使用 `_OmniCache` 输入/输出，并在节点描述里说明缓存读写接法。

### 新增高级图节点

适用于组、批处理、cache、控制流、调试指令等不适合表达为单次 `_func(*args)` 的节点。

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
