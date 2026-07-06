# OmniNode 节点级懒求值设计

本文分析 OmniNode 当前执行模型的调度开销来源，并设计一套"输入未变则跳过节点"的懒求值机制（Lazy Node Evaluation），以降低复杂 nodetree 在连续帧中的固定 Python 开销。

同时本文附录分析了"将整个编译/执行/缓存系统迁移到 C++"的可行性。

## 当前执行模型的问题

### Per-node Python overhead

OmniExecutor 每帧对 CompiledGraph 的每条指令执行如下固定开销（与函数体内容无关）：

```python
for step_index, op in enumerate(compiled.instructions):
    # ① isinstance 顺序判断链（无跳转表）
    if isinstance(op, RuntimeTimingBeginCall): ...
    if isinstance(op, RuntimeTimingEndCall): ...
    if isinstance(op, tuple): ...        # CONST
    if isinstance(op, CacheReadCall): ...
    ...
    if isinstance(op, OpCall):
        step_start, stage = observer.step_begin(step_index, op)  # ② 计时桩
        args = []
        for inp in op.inputs:
            if isinstance(inp, list):
                args.append(flatten(registers[reg] for reg in inp))  # ③ multi-input list 分配
            else:
                args.append(registers[inp])
        result = op.func(*args)                    # ④ 实际函数调用
        for index, reg in enumerate(op.outputs):
            registers[reg] = result[index]         # ⑤ 输出解包
        observer.step_end(step_start, stage)       # ⑥ 计时桩
```

实测 per-node 开销（不含函数体）约 **2–7µs**。100 节点的 nodetree 每帧额外消耗 0.2–0.7ms 纯在调度上。

六处可优化的固定开销，按影响从大到小：

| # | 开销来源 | 约估/节点 | 优化方向 |
|---|---|---|---|
| ① | `isinstance` 顺序判断链（最多10次） | ~1–2µs | `op_type` 整数 + dict 派发，1次查表替代全部 |
| ② | `args = []` 每次调用新建 list | ~0.5µs | 编译时预分配 `_args_buffer`，原地覆写 |
| ③ | `isinstance(inp, list)` 热路径判断 | ~0.3µs/输入 | 编译时拆分 single/multi，运行时零判断 |
| ④ | 多输出 `enumerate(op.outputs)` 解包 | ~0.2µs | 单输出特化为 `op.output0: int` |
| ⑤ | `observer.step_begin/end`（计时桩） | ~0.5–2µs | timing 关闭时 early return，Tracy zone 按需 |
| ⑥ | `enumerate(compiled.instructions)` | ~0.1µs | 改为 `for op in compiled.instructions`，去掉 step_index |

### CONST 指令的隐患

每个未连接的 socket 在编译时产生一条 `("CONST", reg, value)` 指令，value 是编译时从 socket.default_value 固化的值。

- 普通数值 socket：编译时固化，运行时 `registers[reg] = value`，成本极低。
- **曲线类型 socket**：`default_value` 读取触发 Blender RNA 遍历曲线控制点列表。若曲线 socket 未连接，CONST 指令每帧都执行一次 RNA 曲线读取，成本显著高于预期。

### 执行器调度优化（与懒求值独立，可先于懒求值落地）

以下优化不依赖版本跟踪，可以单独实施。

**① op_type 整数 + dict 派发，替代 isinstance 链**

```python
# OmniIR.py：给每个指令类型一个类级别整数常量
OP_CONST        = 0
OP_CALL         = 1   # 最常见，排第 1 优先级
OP_SUBTREE      = 2
OP_BATCH        = 3
OP_CACHE_READ   = 4
OP_CACHE_WRITE  = 5
OP_CACHE_DELETE = 6
OP_CACHE_DUMP   = 7
OP_TIMING_BEGIN = 8
OP_TIMING_END   = 9

class OpCall:
    op_type = OP_CALL      # 类级别常量，不占实例内存

class SubtreeCall:
    op_type = OP_SUBTREE

class ConstInstruction:
    op_type = OP_CONST
# ... 其余各类同理
```

```python
# OmniExecutor.py：编译时建表，运行时 1 次查表
_DISPATCH = {
    OP_CALL:         _exec_opcall,
    OP_CONST:        _exec_const,
    OP_SUBTREE:      _exec_subtree,
    OP_BATCH:        _exec_batch,
    OP_CACHE_READ:   _exec_cache_read,
    OP_CACHE_WRITE:  _exec_cache_write,
    OP_CACHE_DELETE: _exec_cache_delete,
    OP_CACHE_DUMP:   _exec_cache_dump,
    OP_TIMING_BEGIN: _exec_timing_begin,
    OP_TIMING_END:   _exec_timing_end,
}

# 热路径：1次 dict lookup，无顺序判断
for op in compiled.instructions:          # 去掉 enumerate，step_index 只 debug 用
    _DISPATCH[op.op_type](op, graph, ctx, observer)
```

**② `compiled.instructions` 改为 `tuple`**

编译完成后指令列表不再修改，`tuple` 比 `list` 迭代快约 5–10%，且表达不可变语义防止运行时误写：

```python
# OmniCompiler.py finish() 里：
self.graph.instructions = tuple(self.instructions)   # list → tuple
```

### 根本问题：无节点级跳过机制

每帧所有可达节点全部执行，没有"输入未变则跳过"的逻辑。对于参数类节点（stiffness、color、preset 等），只要用户不调参，每帧的执行结果完全相同，重复执行纯属浪费。

---

## 设计目标

1. 输入寄存器版本未变的节点，跳过执行，复用上次输出。
2. 声明 `always_run=True` 的节点（物理 solver、debug 输出、Cache Write 等）无论如何都执行。
3. 曲线 socket 的 CONST 指令只在内容变化时更新寄存器版本。
4. 子树（SubtreeCall）若所有输入未变且内部无 always_run 节点，整块跳过。
5. 不改变现有 `@omni(...)` 节点的编写方式，只在执行层和 IR 层增加版本跟踪。
6. 失效边界（cache clear、scope 变化、world restart）必须能可靠地使所有相关版本失效。

---

## 节点编写指南（Node Authoring）

本节面向编写 `@omni(...)` 函数节点的开发者。懒求值系统对节点编写者暴露两个能力：

### 能力一：`OMNI_NO_CHANGE` —— 主动声明输出未变

```python
from OmniNode.NodeTree.OmniIR import OMNI_NO_CHANGE
```

当节点函数自己知道"本次计算结果和上帧完全相同"时，返回 `OMNI_NO_CHANGE` 而不是重复返回同一个值。执行器看到这个 sentinel 后，不递增该输出寄存器的版本号，下游节点的 skip 判定不受影响。

```python
# 单输出
@omni(enable=True)
def cacheKeyNode(scene: bpy.types.Scene) -> str:
    key = f"{scene.frame_current}:{scene.name}"
    if key == _last_key:
        return OMNI_NO_CHANGE   # 帧号和场景名都没变，下游不需要重算
    _last_key = key
    return key

# 多输出：可以只对部分输出声明不变
@omni(enable=True)
def frameInfo(scene: bpy.types.Scene) -> tuple[int, float]:
    frame = scene.frame_current
    dt    = 1.0 / (scene.render.fps or 24)
    if frame == _last_frame:
        return OMNI_NO_CHANGE, OMNI_NO_CHANGE   # 帧号和dt都没变
    _last_frame = frame
    return frame, dt
```

**适合用的场景：**
- 节点内部有帧号/状态对比逻辑，能确定性地判断"结果未变"
- 输出是大对象（numpy array、dict），每帧重新构造成本高，但内容没变
- 作为懒求值的"主动配合"——比被动的版本跟踪更精确

**不适合用的场景：**
- 节点有副作用（写 bpy、写文件）——这类节点应标 `always_run=True`
- 无法确定结果是否真的没变时，直接返回值，让执行器的 identity 比较决定

---

### 能力二：`always_run=True` —— 声明必须每帧执行

```python
@omni(enable=True, always_run=True)
def springBoneVRM_CPP(cache_state: _OmniCache, ...) -> _OmniCache:
    ...
```

标注后，即使所有输入版本号均未变，该节点也不会被 skip，每帧强制执行。

**必须标注的节点类型：**

| 节点类型 | 原因 |
|---|---|
| 所有物理 solver | 每帧必须推进 Verlet / Jolt state |
| Cache Read / Write / Delete / Dump | GraphNode，runtime cache 语义要求每帧运行 |
| `is_output_node=True` 的节点 | 执行入口，不能跳过 |
| 有 Blender 副作用（写 bpy、调 ops）的节点 | 跳过会导致行为缺失 |

---

### 两者的关系

```
输入未变 + 无 always_run
  → 执行器 skip（节点函数根本不调用）
  → 输出版本号不变（下游同样可 skip）

输入未变 + always_run=True
  → 执行器强制调用节点函数
  → 节点函数返回 OMNI_NO_CHANGE  → 输出版本号不变（下游可 skip）
  → 节点函数返回新值             → 输出版本号递增（下游重算）
```

`OMNI_NO_CHANGE` 的价值在于：`always_run` 节点执行了，但如果结果没变，可以主动阻止版本递增，避免下游一连串不必要的重算。

---

## 核心机制：寄存器版本跟踪

### 数据结构变更

```python
import array as _array

# 现在：每帧重新分配，从零开始
registers = [None] * compiled.reg_count

# 新方案：跨帧持久化（存储在 CompiledGraph 上，与树生命周期绑定）
class CompiledGraph:
    reg_values: list          # 跨帧寄存器值（任意 Python 对象），初始全 None，必须用 list
    reg_versions: array.array # 只存整数版本号，用 array.array('l', ...) 代替 list[int]
    reg_count: int
```

**为什么 `reg_versions` 用 `array.array` 而不是 `list`：**

- `array.array('l', ...)` 在内存中是连续的 C long 数组，每元素 8 字节，无 Python 对象开销。
- 两个 `array.array` 之间的 `==` 比较在 C 层批量执行，不创建任何 Python 对象。
- 单元素读写 `arr[i] = v` 直接操作 C 内存，比 list 略快（无 PyObject 引用计数）。

**不用 numpy 的原因：** `np.array[i]` 返回 numpy 标量对象（dtype boxing），对单元素随机读写反而比 `array.array` 慢，numpy 优势在批量向量化运算，不在这里的随机索引访问模式。

初始化：

```python
graph.reg_values   = [None] * reg_count
graph.reg_versions = _array.array('l', [0] * reg_count)
```

每次某个寄存器被写入时：

```python
def write_reg(graph, reg, value, force_bump=False):
    if force_bump or graph.reg_values[reg] is not value:
        graph.reg_values[reg] = value
        graph.reg_versions[reg] += 1
```

注意：版本比较用 `is not`（身份比较），而非 `==`（值比较）。对于 numpy array 等不可廉价比较的对象，身份比较已足够——如果 solver 每帧产生新 array，版本自然递增。

### 版本快照存储与 OpCall 完整新结构

```python
import array as _array

class OpCall:
    op_type = OP_CALL          # 类常量，用于 dict dispatch

    # ── 原有字段 ──────────────────────────────────────────
    func:   callable           # 直接持有可调用对象，无需每帧查找
    node:   object             # 对应 Blender 节点（debug/bug state 用）

    # ── 输入：编译时拆分 single / multi，运行时零 isinstance 判断 ──
    single_regs:    _array.array   # 'i'，单值输入的寄存器索引，按参数顺序展平
    multi_groups:   list           # list[_array.array('i')]，每个 multi-input socket 一组
    call_structure: _array.array   # 'b'（int8），每个参数位：0=single，1=multi
    # call_structure 长度 == 参数个数（不等于 flat_inputs 长度）

    # ── 输入（版本跟踪用）：所有输入寄存器展平为一维 ──
    flat_inputs:    _array.array   # 'i'，single + multi 全部展平，用于版本比对
    version_buffer: _array.array   # 'l'，与 flat_inputs 等长，每帧原地覆写
    last_snapshot:  _array.array   # 'l'，与 flat_inputs 等长，初值 -1（保证首帧不跳过）

    # ── 输出：单输出特化 ──────────────────────────────────
    n_outputs: int             # 编译时固化，0 / 1 / N
    output0:   int             # n_outputs==1 时直接用，避免列表开销
    outputs:   _array.array    # 'i'，n_outputs>1 时用

    # ── 预分配参数 buffer ─────────────────────────────────
    _args_buf: list            # 编译时按参数个数预分配，运行时原地覆写
    #  必须用 list（存任意对象），不能用 array.array

    # ── 标志 ──────────────────────────────────────────────
    has_always_run: bool       # True → 跳过检查，每帧强制执行
```

**各字段的容器选择说明：**

| 字段 | 类型 | 原因 |
|---|---|---|
| `single_regs` | `array.array('i')` | 只存 reg 索引（整数），C 连续数组 |
| `multi_groups` | `list[array.array('i')]` | 外层 list 因为个数不固定；内层 array 存 reg 索引 |
| `call_structure` | `array.array('b')` | int8 够用（0/1 标志），8× 紧凑 |
| `flat_inputs` | `array.array('i')` | 与 `version_buffer` / `last_snapshot` 等长，用于版本比对 |
| `version_buffer` | `array.array('l')` | C long，`==` 走 C 层批量比较 |
| `last_snapshot` | `array.array('l')` | 同上，`[:]=` 是 C memcpy |
| `outputs` | `array.array('i')` | 只存 reg 索引 |
| `_args_buf` | `list` | 存任意 Python 对象，必须用 list |

编译时初始化（不在热路径里）：

```python
# ── 拆分 single / multi ────────────────────────────────────
single_flat = []   # 顺序展平的 single reg
multi_flat  = []   # 顺序展平的 multi reg（用于 flat_inputs）
multi_grps  = []   # 每个 multi socket 的 reg 组
structure   = []   # 0=single，1=multi，与参数个数等长

for inp in input_regs:
    if isinstance(inp, list):
        structure.append(1)
        grp = _array.array('i', inp)
        multi_grps.append(grp)
        multi_flat.extend(inp)
    else:
        structure.append(0)
        single_flat.append(inp)

all_flat = single_flat + multi_flat   # 版本比对用的完整展平

op.single_regs    = _array.array('i', single_flat)
op.multi_groups   = multi_grps
op.call_structure = _array.array('b', structure)
op.flat_inputs    = _array.array('i', all_flat)
op.version_buffer = _array.array('l', [0]  * len(all_flat))
op.last_snapshot  = _array.array('l', [-1] * len(all_flat))
op._args_buf      = [None] * len(structure)

# ── 输出特化 ───────────────────────────────────────────────
op.n_outputs = len(output_regs)
if op.n_outputs == 1:
    op.output0 = output_regs[0]
    op.outputs = _array.array('i', [])     # 空占位
else:
    op.output0 = -1
    op.outputs = _array.array('i', output_regs)
```

---

## Skip 判定规则

热路径设计原则：**整个判定过程零内存分配**。用预分配的 `array.array` buffer 原地更新，`==` 走 C 层批量比较。

```python
def should_skip(op: OpCall, graph: CompiledGraph) -> bool:
    # 规则 1：always_run 节点永不跳过
    if op.has_always_run:
        return False

    # 规则 2：last_snapshot[0] == -1 表示从未执行过（首帧），不能跳过
    if op.last_snapshot[0] == -1:
        return False

    # 规则 3：原地填充 version_buffer，与 last_snapshot 批量比较（C 层，零分配）
    buf     = op.version_buffer
    snap    = op.last_snapshot
    inputs  = op.flat_inputs
    vers    = graph.reg_versions
    for i in range(len(inputs)):
        buf[i] = vers[inputs[i]]    # C int 赋值，无 PyObject 分配
    return buf == snap               # array.array C 层批量比较，返回 True/False


def record_snapshot(op: OpCall) -> None:
    """执行完成后，把 version_buffer 内容复制到 last_snapshot（C 层 memcpy）。"""
    op.last_snapshot[:] = op.version_buffer
```

执行逻辑（完整热路径，零内存分配）：

```python
def _exec_opcall(op: OpCall, graph: CompiledGraph, ctx, observer):
    # ── skip 判定 ────────────────────────────────────────
    if not op.has_always_run and op.last_snapshot[0] != -1:
        buf   = op.version_buffer
        snap  = op.last_snapshot
        ins   = op.flat_inputs
        vers  = graph.reg_versions
        for i in range(len(ins)):
            buf[i] = vers[ins[i]]       # C int 赋值，零分配
        if buf == snap:                  # C 层批量比较
            return                       # skip

    # ── 构建参数（原地覆写预分配 buffer）────────────────
    buf_a  = op._args_buf
    struct = op.call_structure
    vals   = graph.reg_values
    si     = 0        # single_regs 游标
    mi     = 0        # multi_groups 游标
    sregs  = op.single_regs
    mgrps  = op.multi_groups

    for i in range(len(struct)):
        if struct[i] == 0:
            buf_a[i] = vals[sregs[si]]            # 单值：直接赋
            si += 1
        else:
            buf_a[i] = [vals[r] for r in mgrps[mi]]   # multi：list comprehension
            mi += 1

    # ── 调用函数 ─────────────────────────────────────────
    result = op.func(*buf_a)

    # ── 写回输出寄存器 ───────────────────────────────────
    if op.n_outputs == 1:
        _write_reg(graph, op.output0, result)           # 单输出特化：无循环
    else:
        outs = op.outputs
        for i in range(op.n_outputs):
            _write_reg(graph, outs[i], result[i])

    # ── 记录版本快照（C memcpy）─────────────────────────
    op.last_snapshot[:] = op.version_buffer
```

**性能对比（节点 5 输入，1 输出）：**

```python
# 旧执行路径
isinstance(op, tuple)           # 检查1：False
isinstance(op, CacheReadCall)   # 检查2：False
...（共 7 次 False）...
isinstance(op, OpCall)          # 检查8：True
args = []                        # 分配新 list
for inp in op.inputs:
    if isinstance(inp, list): ...   # 每个输入判断一次
    args.append(...)
result = op.func(*args)
for index, reg in enumerate(op.outputs):   # enumerate 创建迭代器
    registers[reg] = result[index]

# 新执行路径
_DISPATCH[op.op_type](...)       # 1 次 dict lookup
# skip 判定：5 次 C int 赋值 + 1 次 C 批量比较 → 可能直接返回
buf_a[0..4] = vals[sregs[0..4]] # 原地覆写，零分配
result = op.func(*buf_a)
_write_reg(graph, op.output0, result)  # 单输出直接赋值，无循环
op.last_snapshot[:] = op.version_buffer # C memcpy
```

---

## always_run 标记

```python
@omni(enable=True, always_run=True)
def springBoneVRM_CPP(cache_state, vrm_chain_settings, scene, ...):
    ...
```

需要标记 `always_run=True` 的节点类型：

| 节点类型 | 原因 |
|---|---|
| 所有物理 solver 节点 | 每帧必须推进 Verlet/Jolt state，即使参数不变 |
| Cache Read / Write / Delete / Dump | IR 级 GraphNode，runtime cache 语义要求每帧运行 |
| 所有 `is_output_node=True` 的节点 | 输出节点是执行入口，必须每帧运行 |
| debug 输出节点 | 用户开启时期望每帧看到最新状态 |
| 调用了 `bpy.ops` 或有副作用的节点 | 副作用节点跳过会导致语义错误 |

默认（不标注 `always_run`）：

| 节点类型 | 跳过条件 |
|---|---|
| 数值计算节点（Math、Lerp 等） | 所有输入版本不变时跳过 |
| 参数节点（PhysicsPreset、ChainSetting 等） | 用户未调参时跳过 |
| 数据读取节点（Armature、VertexGroup 等） | 依赖 Blender 数据，见下方特殊处理 |
| 类型转换节点（DataTypeCast） | 输入不变时跳过 |
| 组节点（SubtreeCall） | 见子树传播规则 |

---

## CONST 指令版本化（曲线 socket 特殊处理）

当前 CONST 指令：

```python
("CONST", reg, value)  # value 在编译时固化，每帧 registers[reg] = value
```

问题：曲线 socket 的 value 是编译时的 RNA 快照，如果用户在运行中调整曲线，CONST 指令无法感知变化（value 已经固化）。

新设计：

```python
class ConstInstruction:
    reg: int
    value: Any            # 当前固化值
    source_socket: Any    # 保持 socket 弱引用（用于热更新检测）
    value_hash: int | None  # 对 hashable 值计算 hash；曲线用内容 hash
    is_curve: bool        # 是否是曲线类型（需要特殊 hash 计算）
```

执行时：

```python
def execute_const(instr: ConstInstruction, graph: CompiledGraph):
    new_value = instr.value

    if instr.is_curve:
        # 每帧重新从 socket 读取曲线，计算轻量 hash（控制点数 + 关键点坐标摘要）
        new_hash = _curve_hash(instr.source_socket)
        if new_hash == instr.value_hash:
            return  # hash 不变，寄存器版本不递增
        instr.value = _read_curve(instr.source_socket)
        instr.value_hash = new_hash
        new_value = instr.value

    write_reg(graph, instr.reg, new_value)  # 只有版本实际变化时才递增
```

曲线 hash 计算（轻量）：

```python
def _curve_hash(socket) -> int:
    try:
        curve = socket.default_value
        pts = curve.curves[0].points
        # 控制点数 + 首尾关键点坐标摘要
        n = len(pts)
        if n == 0:
            return hash((0,))
        return hash((n, round(pts[0].location[0], 4), round(pts[0].location[1], 4),
                     round(pts[-1].location[0], 4), round(pts[-1].location[1], 4)))
    except Exception:
        return 0
```

---

## 子树传播规则（SubtreeCall 懒跳过）

SubtreeCall 可以整块跳过，条件更严格：

```python
def should_skip_subtree(call: SubtreeCall, graph: CompiledGraph) -> bool:
    # 子树内有任何 always_run 节点，不跳过
    if call.compiled_graph.has_always_run_node:  # 编译时标注
        return False

    # 所有输入版本未变
    return call.last_input_snapshot == _subtree_input_versions(call, graph)
```

`has_always_run_node` 在编译时计算：

```python
def _compute_has_always_run(compiled_graph: CompiledGraph) -> bool:
    for op in compiled_graph.instructions:
        if isinstance(op, OpCall) and op.has_always_run:
            return True
        if isinstance(op, SubtreeCall) and op.compiled_graph.has_always_run_node:
            return True
    return False
```

---

## 失效边界（关键：必须可靠）

版本跟踪引入了跨帧状态，必须在以下边界强制失效：

### 失效类型 1：全量失效（bump all register versions）

触发条件：

- `tree.clear_compile_cache()` 重新编译 → CompiledGraph 对象被替换，旧版本数组随对象丢弃。
- `OmniRuntimeState.clear_all()` → 所有跨帧状态归零。
- 插件注销。

行为：CompiledGraph 对象重建，`reg_values` 和 `reg_versions` 重置为空，所有 `last_input_snapshot` 归 None。

### 失效类型 2：选择性失效（bump specific registers）

触发条件：

- **Blender 节点图拓扑变化**（用户增删节点/连线）：重新编译，全量失效。
- **socket 默认值被用户在编辑器里手动修改**：对应 CONST 指令的 hash 在下帧检测到变化，自动递增版本。
- **scope 变化、world generation 变化**：物理 solver 节点标注 `always_run=True`，不受跳过影响，直接每帧运行。

### 失效类型 3：运行时 API 主动失效

```python
compiled_graph.invalidate_reg(reg)        # 使某寄存器版本递增，强制下游重算
compiled_graph.invalidate_all_regs()      # 全量失效
```

用于：Cache Delete 后需要让 Cache Read 的输出失效，使下游物理节点感知到 cache 被清空。

---

## 缓存输出的存储位置与共享子树隐患

### 跳过节点的输出存在哪里

当一个节点被 skip 时，它的输出来自上一帧写入的 `CompiledGraph.reg_values`：

```
帧 N  ：Node A 执行 → reg_values[output_A] = result_A
帧 N+1：Node A 被 skip（输入版本未变）
         → reg_values[output_A] 仍是 result_A
         → 下游 Node B 执行，读 reg_values[input_B] → 得到正确缓存值 ✓
```

对**根树（Root Tree）**而言这是安全的：每棵根树有唯一一个 `CompiledGraph` 实例，`reg_values` 是它私有的跨帧存储，不会被其他执行路径污染。

---

### 共享子树的污染隐患（关键）

当根树中有**多个 Group 节点引用同一棵子树**时，该子树只有一个 `CompiledGraph` 对象，`reg_values` 和 `reg_versions` 也只有一份：

```
根树：Group_A ──→ SubTree_X ←── Group_B
                       ↑
             compiled_graph.reg_values（共享！）
```

单帧内的执行顺序（拓扑排序）：

```
1. Group_A 执行 SubTree_X：
   SubTree_X.reg_values 被 Group_A 的输入写满
   SubTree_X 内 OpCall 的 last_snapshot 记录 Group_A 版本

2. Group_B 执行同一个 SubTree_X：
   内部 OpCall 比对 last_snapshot（Group_A 的快照）
   与当前 reg_versions（同样来自 Group_A 的写入）
   → 如果版本号碰巧相等 → 错误 skip ✗
   → SubTree_X 输出了 Group_A 语境下的旧结果给 Group_B 的下游 ✗
```

**SubtreeCall 级别的整块 skip 是安全的**，原因是：SubtreeCall 的 skip 判断基于**父树**的 reg_values（输入是否变化），父树和子树的 reg_values 是两个独立对象，Group_A 写子树 reg_values 不会污染父树中 Group_B 的输出寄存器缓存。

不安全的只是：**子树内部节点的逐节点 skip**。

---

### 解法：编译期检测共享，分级处理

```python
class CompiledGraph:
    ref_count:        int   # 被多少个 SubtreeCall 引用，编译时统计
    inner_lazy_eval:  bool  # ref_count == 1 才允许内部节点 skip
```

编译器在 `finish()` 里统计：

```python
def _compute_ref_counts(root_graph: CompiledGraph):
    """递归统计每个 compiled_graph 被引用的次数。"""
    counts = {}
    def walk(g):
        for op in g.instructions:
            if isinstance(op, (SubtreeCall, BatchSubtreeCall)):
                child = op.compiled_graph
                counts[id(child)] = counts.get(id(child), 0) + 1
                walk(child)
    walk(root_graph)
    return counts

# finish() 里：
for child_graph, count in ref_count_map.items():
    child_graph.ref_count = count
    child_graph.inner_lazy_eval = (count == 1)
```

执行时：

```python
def _exec_subtree(call: SubtreeCall, parent_graph, ctx, observer):
    # ── SubtreeCall 级别 skip（始终安全，基于父树 reg_values）──
    if _should_skip_subtree_outer(call, parent_graph):
        return   # 父树的输出寄存器保留上帧缓存值 ✓

    child = call.compiled_graph
    if child.inner_lazy_eval:
        # 子树内部节点可以逐节点 skip（非共享子树）
        _run_subtree_with_inner_lazy(call, child, parent_graph, ctx, observer)
    else:
        # 共享子树：整体执行，不做内部 skip（避免跨路径版本污染）
        _run_subtree_full(call, child, parent_graph, ctx, observer)
```

---

### 各种情况的存储位置汇总

| 情况 | 输出缓存位置 | 是否安全 |
|---|---|---|
| 根树节点被 skip | 根树 `CompiledGraph.reg_values` | ✓ 私有，不共享 |
| SubtreeCall 整块被 skip | 父树 `CompiledGraph.reg_values`（父树输出寄存器） | ✓ 父树私有 |
| 非共享子树内部节点被 skip | 子树 `CompiledGraph.reg_values` | ✓ 单一引用，无污染 |
| 共享子树内部节点 | 不做内部 skip，每次整体执行 | ✓ 绕开问题 |
| SubtreeCall 快照（`last_snapshot`） | 存在 `SubtreeCall` 对象上（属于父树） | ✓ 父树内唯一 |

---



| 文件 | 改动类型 | 影响 |
|---|---|---|
| `OmniIR.py` | 新增 `OP_*` 整数常量；OpCall 替换为新字段结构（`single_regs`、`call_structure`、`output0`、`_args_buf`、版本跟踪字段）；CompiledGraph 增加 `reg_values`、`reg_versions`、`has_always_run_node`；`instructions` 改为 `tuple` | IR 结构，向前不兼容 |
| `OmniExecutor.py` | 主循环改为 `_DISPATCH[op.op_type](...)` 表驱动；拆出各 handler 函数；`_execute_core` 使用持久化 `graph.reg_values`；`write_reg` 封装版本递增 | 核心执行路径 |
| `OmniCompiler.py` | `emit_function_call` 初始化 OpCall 新字段；`instructions.append` → 最后 `tuple(instructions)`；CONST 改为 `ConstInstruction` 对象；编译时计算 `has_always_run_node` | 编译输出 |
| `OmniNodeTree.py` | `run_frame_cached` 不再每帧重建 registers，改用 `graph.reg_values`；`clear_compile_cache` 时显式将 `graph.reg_values` 置 None 防悬空引用 | 树级状态 |
| `FunctionNodeCore.py` | `@omni(always_run=True)` 参数支持；生成 OpCall 时写入 `has_always_run` | 装饰器 |
| 所有 solver 节点 | 添加 `always_run=True` 标记 | 逐个标注 |

**高风险点**：

1. **持久化寄存器的悬空引用**：`reg_values` 跨帧持有 bpy 对象引用。重编译或树删除时必须显式 `graph.reg_values = None`，否则已释放的 Blender 对象被 Python 持有会导致崩溃或脏读。

2. **子树 compiled_graph 共享问题**：多个组实例引用同一子树时，`compiled_graph` 是共享对象，但 `last_snapshot` 是各调用路径独立的。必须将版本快照字段（`last_snapshot`、`version_buffer`）从 OpCall 对象移到 per-call-path 的执行上下文，否则两个组实例互相覆盖快照导致跳过判断错误。

3. **call_structure 与 flat_inputs 的索引对齐**：`call_structure` 长度是参数个数，`flat_inputs` 长度是所有 reg 展平后的总数（可能更多）。构建时必须保证展平顺序与 `_exec_opcall` 里的游标逻辑严格对应。

---

## 性能收益预估

以 100 节点 nodetree、每帧 30fps、参数稳定（物理运行中）为例。

**调度优化（不依赖懒求值，独立收益）：**

| 优化点 | 节省/节点 | 100节点合计 |
|---|---|---|
| isinstance链 → dict dispatch | ~1–2µs | ~0.1–0.2ms |
| instructions list → tuple | — | ~0.05ms |
| args 预分配 buffer | ~0.5µs | ~0.05ms |
| single/multi 拆分（消除热路径 isinstance） | ~0.3µs | ~0.03ms |
| 单输出特化（消除 enumerate） | ~0.2µs | ~0.02ms |
| **调度优化合计** | | **~0.25–0.35ms/帧** |

**懒求值（skip 机制，在调度优化基础上）：**

| 场景 | 当前每帧开销 | 懒求值后 | 收益 |
|---|---|---|---|
| 参数节点（50个，全部稳定） | ~150–350µs | ~5µs（skip 判定开销） | ~-97% |
| 物理 solver（5个，always_run） | 不变 | 不变 | 0% |
| 曲线 socket（10个，不变帧） | ~200–500µs（RNA 读取） | ~20µs（hash 检查） | ~-90% |
| SubtreeCall（20个纯参数节点） | ~60–140µs | ~5µs（整块跳过） | ~-90% |
| **懒求值合计** | **~0.4–0.7ms/帧** | **~0.03ms/帧** | **~-93%** |

**总收益（两者叠加）：** 原本 0.6–1.0ms 的纯调度开销降到 0.05ms 以下。物理 solver 本身执行时间（~6ms）不变。


---

## 附录：C++ 整体迁移的可行性分析

### 结论

**不值得迁移，有根本性障碍。**

### 根本障碍

| 障碍 | 说明 |
|---|---|
| `op.func(*args)` 永远是 Python 回调 | 即使 executor 的 for 循环在 C++，每个 OpCall 仍需回调 Python，CPython GIL + 调用边界不消失 |
| 编译器必须读 Blender NodeTree | NodeTree / Node / Socket / Link 全是 Blender RNA 对象，只有 Python 可访问 |
| Cache 值是任意 Python 对象 | `bpy.types.Object`、numpy array、`OmniCacheOwnerDict` 无法放进 C++ 容器 |
| Blender socket default_value | 曲线、对象、场景 socket 的值只能从 Python RNA 读取 |

### 搬 C++ 的收益估算

假设把 executor for 循环搬到 C++，每帧节省的只是 isinstance 判断和 list 分配（约 50–150µs/100节点），而实际函数体执行时间通常在 0.5–10ms。收益比例极低，实现成本极高。

### 正确的分层策略

```text
Python 层（永久保留）：
  编译器（读 Blender 节点图）
  Cache Read/Write/Delete（runtime cache 语义依赖 Python）
  Blender 数据读写（bpy 访问）
  节点注册、UI、socket 定义

懒求值版本跟踪（可用 C 实现 reg_versions 数组加速，但 Python 够用）：
  register版本号数组：list[int] 操作已经足够快
  skip 判定：tuple 比较

C++ 正确的位置（现有策略继续）：
  物理计算热路径（solver kernel）
  persistent native context（static arrays + state）
  数值密集型中间转换（collider array 打包、骨骼矩阵批量计算）
```

结论：**Python 管调度和 Blender 边界，C++ 管数值计算**，这个分层是正确的，不需要整体迁移。
