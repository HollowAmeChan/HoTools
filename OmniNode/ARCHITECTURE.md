# OmniNode 设计边界与文件职能

本文档记录 OmniNode 当前的核心设计约定、编译/执行边界，以及各文件的职责。它不是用户手册，而是维护代码时用来对齐系统认知的工程文档。

## 一句话模型

OmniNode 是一个基于 Blender `NodeTree` 的轻量函数图系统：

- 编辑阶段使用 Blender 节点、socket、link 作为图形化表达。
- 编译阶段把从输出节点可达的节点子图转成简单的寄存器指令序列。
- 执行阶段按指令顺序调用 Python 函数，并把结果写回寄存器。
- 组节点不是 Blender 原生 group 执行模型，而是 OmniNode 自己维护的子树调用。

## 设计边界

### 1. Blender 节点图只是编辑表示

Blender 的 `NodeTree.nodes`、`NodeSocket.links` 和 `NodeLink` 只用于描述图结构。真正的运行时不直接沿 Blender link 逐步执行，而是先由 `OmniCompiler` 编译成 `CompiledGraph`。

因此，维护时要区分两类节点：

- OmniNode 自己的运行节点：继承 `OmniNode`，通常有 `_func`、`is_output_node`、`set_bug_state()` 等属性。
- Blender 原生编辑节点：例如 `NodeFrame`、`NodeReroute`，它们没有 OmniNode 的 bug 状态属性，也没有 `_func`。

原生节点必须在编译器或编辑器工具里显式适配，不能假设它们具有 HoTools 自定义节点的属性。

### 2. 输出节点决定可达子图

编译入口不是全图所有节点，而是：

```text
tree.nodes 中 is_output_node == True 的节点
```

`OmniCompiler._compile_tree()` 从这些输出节点反向 DFS，收集可达节点和 links，再做拓扑排序。未连接到输出节点的节点不会执行。

这个设计让节点树可以容纳实验节点或临时节点，但也意味着“看得见的节点”不一定是运行时的一部分。

### 3. 寄存器是运行时数据边界

编译阶段使用 `(node.name, socket.identifier)` 作为 socket 输出到寄存器的映射键。

普通函数节点：

- 输入 socket 编译成输入寄存器列表。
- 输出 socket 分配新寄存器。
- 运行时调用 `_func(*args)`，再把结果写入输出寄存器。

默认值：

- 没有 link 的输入 socket 会编译成 `CONST` 指令。
- 如果 socket 没有 `default_value`，当前退回 `None`。

### 4. Multi input 的职责在目标 socket

`list[T]` 类型注解会被 `FunctionNodeCore.resolve_socket()` 识别为 multi input，并在 socket 创建时设置 `use_multi_input=True`。

编译时是否按列表收集输入，取决于目标节点的 `_socket_is_multi[sock.identifier]`，而不是来源节点。

因此，下面这种结构是合法且符合设计的：

```text
A -> Reroute1 -> SumVector.values
B -> Reroute2 -> SumVector.values
C ------------> SumVector.values
```

`SumVector.values` 是 multi socket，所以它会遍历所有输入 links。转接点只透传单根 link 的值，不负责合并。

注意：当前 multi link 的顺序由 `(from_node.name, from_socket.identifier)` 排序决定，不一定等于 Blender 视觉上的插入顺序。凡是依赖列表顺序的节点，都要意识到这个边界。

### 5. Blender 原生特殊节点

`NodeFrame`：

- 纯 UI 容器。
- 编译时应跳过。
- 不参与运行时指令。

`NodeReroute`：

- 纯透传节点。
- 编译时取第一个输入 socket 的寄存器。
- 把所有输出 socket 映射到同一个输入寄存器。
- 不生成运行时指令。
- 断开输入时当前允许传 `None`，让下游节点自己决定是否报错。

这个模型依赖拓扑排序保证上游先被编译，目前与系统整体设计一致。

### 6. 组节点是子树调用，不是 Blender 原生 group

OmniNode 的组节点由 `GraphNode.py` 中的类实现：

- `OmniGroupNode`：引用一个 `OmniNodeTree`，运行时进入子树。
- `OmniBatchGroupNode`：批量运行子树，把一个选中的输入作为 batch 输入。
- `OmniGroupNodeInputs` / `OmniGroupNodeOutputs`：子树输入/输出边界。

组节点编译时会递归调用 `OmniCompiler._compile_tree()`，并用 `compiling_stack` 检查子树循环引用。

### 7. Bind 是动态 UI 参数系统，不是普通函数节点

`OmniBindNode` 和 `OmniMenuBind.py` 负责把子树中的参数暴露到 UI，并在运行时缓存参数上下文。

Bind 的关键边界：

- 编译阶段收集 pending bind rules。
- 执行阶段捕获本次运行的真实 args 和 processor graph。
- 侧栏参数 UI 只是暴露当前 Python 会话中的缓存状态。
- 文件重载、插件重载、节点结构变化、未重新运行 tree 都可能让 bind runtime cache 过期。

## 编译流程

主要在 `NodeTree/OmniCompiler.py`。

1. 清空 pending bind rules。
2. 从输出节点反向 DFS，收集可达节点与 links。
3. 对可达节点做拓扑排序。
4. 顺序编译每个节点：
   - `Group Inputs`：绑定树输入寄存器。
   - `Group Outputs`：绑定树输出寄存器。
   - `Group Node`：递归编译子树，发出 `SubtreeCall`。
   - `Batch Group Node`：递归编译子树，发出 `BatchSubtreeCall`。
   - `Bind Node`：收集绑定规则，必要时编译 processor tree。
   - `NodeFrame`：跳过。
   - `NodeReroute`：寄存器透传。
   - 普通函数节点：发出 `OpCall`。
5. 输出 `CompiledGraph`。

`CompiledGraph` 包含：

- `instructions`：运行时指令序列。
- `reg_count`：寄存器数量。
- `input_regs` / `output_regs`：组树边界寄存器。
- `node_order`：拓扑排序结果。
- `compile_trace` / `register_bridges` / `function_catalog`：调试信息。

## 执行流程

主要在 `NodeTree/OmniExecutor.py`。

执行器不再读 Blender node links，而是只执行 `CompiledGraph.instructions`：

- `("CONST", reg, value)`：写常量寄存器。
- `OpCall`：读取输入寄存器，调用 Python 函数，写输出寄存器。
- `SubtreeCall`：准备子树输入，递归执行子树，再收集子树输出。
- `BatchSubtreeCall`：展开 batch 输入，多次执行子树，并把每次输出收集成列表。

执行器假设编译器已经处理好图结构问题。像 `NodeReroute` 这类编辑器节点不应该出现在执行指令里。

## 文件职能

### `__init__.py`

OmniNode 模块入口。负责：

- 把 `lib` 加入 `sys.path`。
- 注册/注销绘制、操作符、NodeTree、socket、节点类别。

### `NodeTree/OmniNodeTree.py`

定义 `OmniNodeTree` 数据块类型。负责：

- 树级属性，如自动更新、debug compile、组输入/输出列表。
- `run()` 主流程：清理绘制和 bind runtime、清理 bug 状态、编译、执行、生成 bind runtime UI 项。
- Node editor 侧栏的树属性绘制。

维护注意：

- `run()` 会遍历 `self.nodes`，其中可能包含 Blender 原生节点。清理 bug 状态时必须检查属性存在。

### `NodeTree/OmniNode.py`

OmniNode 自定义节点基类。负责：

- bug 状态属性与颜色刷新。
- output node 标记与颜色。
- 默认尺寸、描述文本、基础按钮绘制。
- `build()` 生命周期入口。

维护注意：

- 只有继承该类的节点才保证有 `is_bug`、`bug_text`、`set_bug_state()`。

### `NodeTree/FunctionNodeCore.py`

函数节点生成器。负责：

- `@omni(...)` 装饰器。
- 从 Python 函数签名解析输入/输出 socket。
- 识别 `list[T]` 为 multi input。
- 动态创建继承 `OmniNode` 的节点类。

维护注意：

- 函数注解是节点 socket 类型的主要来源。
- `_socket_is_multi` 是编译阶段判断 multi input 的依据。

### `NodeTree/OmniNodeSocketMapping.py`

Python 类型到 Blender socket 类型的映射表。负责：

- 将函数注解映射到 `NodeSocketFloat`、`NodeSocketVector`、自定义 Omni socket 等。
- 提供 `runtime_socket_type_id()` 做 Blender 版本兼容。
- 定义若干 marker 类型，如 `_OmniFolderPath`、`_OmniRegex`、`_OmniDatablock`。

### `NodeTree/OmniNodeSocket.py`

自定义 socket 定义。负责：

- Scene、Text、ImageFormat、Regex、Glob、Datablock 等 socket。
- Modifier、MaterialSlot、UVLayer、ColorAttribute、VertexGroup 等运行时占位 socket。
- Bind 参数用的 `OmniNodeSocketParameter*` socket。

维护注意：

- 如果 socket 可能参与默认值编译，最好提供可安全读取的 `default_value`。

### `NodeTree/GraphNode.py`

非函数型高级节点。负责：

- 组引用节点。
- 组输入/输出边界节点。
- Bind 节点。
- Batch group 节点。
- 节点重建时的 link/default value 缓存与恢复工具。

维护注意：

- 组节点通过同步目标树的 `group_inputs` / `group_outputs` 来生成 socket。
- Batch group 的 multi input 是运行时规则，不是普通函数签名产生的 multi。

### `NodeTree/OmniCompiler.py`

编译器。负责：

- 从输出节点反向收集可达子图。
- 拓扑排序。
- 编译常量、函数调用、组调用、批量组调用、Bind。
- 适配 `NodeFrame` 和 `NodeReroute`。
- 生成调试 trace 和 register bridge。

维护注意：

- 所有运行时不能识别的编辑器节点，都应该在这里被跳过、透传或明确报错。
- 不要让没有 `_func` 的普通节点落入 `OpCall`。

### `NodeTree/OmniExecutor.py`

执行器。负责：

- 分配寄存器数组。
- 执行 `CONST`、`OpCall`、`SubtreeCall`、`BatchSubtreeCall`。
- 处理 Bind runtime context。
- 生成 runtime debug trace。

维护注意：

- 执行器不应该理解 Blender link 结构。
- 如果需要支持新图结构，优先在编译器里归一化。

### `NodeTree/OmniDebug.py`

调试格式化工具。负责：

- 编译 trace 记录。
- register bridge 记录。
- runtime trace logger。
- 彩色终端标签和报告格式。

### `NodeTree/OmniMenuBind.py`

动态 Bind 参数系统。负责：

- 从 Bind node / compiled graph 收集参数规则。
- 序列化和规范化 bind value。
- 维护当前 Python 会话中的 live bind context。
- 绘制和更新侧栏 runtime 参数 UI。
- 支持 batch group 中的 bind 参数实例。

维护注意：

- 它管理的是“最近一次运行产生的可编辑参数上下文”，不是持久数据模型。

### `NodeTree/OmniNodeOperator.py`

编辑器操作符与辅助 UI。负责：

- OmniNode 树跳转与返回。
- 节点树创建/销毁。
- 节点重建。
- 菜单和 Node editor 相关操作。

维护注意：

- 操作符可能接触到选中的 Blender 原生节点。对 `build()`、bug state、socket 清理等操作要先判断能力。

### `NodeTree/OmniNodeDraw.py`

节点树绘制辅助。负责：

- bug 文本、overlay、绘制状态的同步和清理。

### `NodeTree/OmniNodeRegister.py`

节点注册和分类。负责：

- 注册 Graph 节点类。
- 从 `Function/` 下各模块加载 `@omni(enable=True)` 函数并生成节点类。
- 建立 Blender add node 菜单分类。

### `NodeTree/Function/*.py`

函数节点库。负责提供实际运行的 Python 函数。

常见模块：

- `Data.py`：输入/数据源节点。
- `DataTypeCast.py`：类型转换。
- `Math.py`：数学与向量运算。
- `Logic.py`：逻辑和列表工具。
- `Operator.py`：对象、集合、文件等操作。
- `Image.py`：图像处理。
- `Modifier.py`：修改器相关。
- `Material.py`：材质相关。
- `UV.py`：UV 操作。
- `VertexColor.py`：顶点色。
- `VertexGroup.py`：顶点组。
- `RigTooKit.py`：绑定/骨骼相关工具。
- `_Color.py`：节点分类颜色配置。

维护注意：

- 函数签名就是节点接口。改函数参数名会改变 socket identifier，可能影响旧链接。
- 返回 `tuple[...]` 会生成多输出 socket。
- 返回 `list[T]` 当前更多用于类型表达，multi input 主要看输入参数的 `list[T]`。
- Blender 原生 `bpy_prop_array` 不一定支持 mathutils 运算，函数内需要按需转换。

### `lib/`

随 OmniNode 携带的第三方库目录。`__init__.py` 会把它加入 `sys.path`。

## 增加新节点的建议

### 新增普通函数节点

1. 在 `NodeTree/Function/` 合适模块中写 Python 函数。
2. 加 `@omni(enable=True, ...)`。
3. 使用类型注解定义 socket 类型。
4. 需要 multi input 时使用 `list[T]`。
5. 如果函数依赖 Blender 特殊数据类型，函数内部自行做类型规整。

### 新增高级图节点

如果节点不是一个简单函数调用，例如组、批处理、Bind、缓存、控制流，应放在 `GraphNode.py` 或新的 graph-node 模块中，并在 `OmniCompiler.py` 中增加明确编译分支。

不要让高级节点伪装成普通 `_func` 节点，除非它真的只需要 `func(*args)`。

### 新增 Blender 原生节点适配

如果允许某个 Blender 原生节点进入 OmniNodeTree，需要回答三个问题：

1. 它是否参与运行时数据？
2. 它是否应该生成指令？
3. 它没有 OmniNode 属性时，编辑器工具是否会误操作它？

适配位置通常是：

- 编译语义：`OmniCompiler.py`
- 运行前/编辑器清理：`OmniNodeTree.py`、`OmniNodeOperator.py`
- UI/绘制：必要时在 `OmniNodeDraw.py`

## 当前已知边界

- Multi input 的输入顺序目前不是视觉顺序，而是编译器排序顺序。
- `NodeReroute` 断开输入时会向下游传 `None`。
- 默认值读取是尽力而为，不保证所有 Blender socket 都有 `default_value`。
- Bind runtime context 只在当前 Python 会话内可靠。
- 函数节点的 socket identifier 与函数参数名绑定，改名会影响已有树。

