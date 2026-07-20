import array as _array

# ─── 指令类型整数码（用于 dict 派发，替代 isinstance 顺序判断）────────────────
OP_CONST        = 0
OP_CALL         = 1   # 最常见，排第 1
OP_SUBTREE      = 2
OP_BATCH        = 3
OP_CACHE_READ   = 4
OP_CACHE_WRITE  = 5
OP_CACHE_DELETE = 6
OP_CACHE_DUMP   = 7
OP_TIMING_BEGIN = 8
OP_TIMING_END   = 9


# ─── 输出不标脏 sentinel ──────────────────────────────────────────────────────
class _OmniNoChange:
    """
    节点函数返回此单例，表示对应输出与上帧相同。
    执行器不递增该输出寄存器的版本号，下游 skip 判定不受影响。

    导入：
        from OmniNode.NodeTree.OmniIR import OMNI_NO_CHANGE

    单输出：
        return OMNI_NO_CHANGE

    多输出（可部分不变）：
        return OMNI_NO_CHANGE, new_value
        return val_a, OMNI_NO_CHANGE

    约束：
    - 只能用于普通函数节点（OpCall）的返回值，不能用于 cache 值。
    - 首帧执行时忽略，强制写入 None。
    - always_run=True 的节点执行后仍可返回，版本同样不递增。
    """
    __slots__ = ()
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "OMNI_NO_CHANGE"

    def __bool__(self):
        raise TypeError("不能对 OMNI_NO_CHANGE 做布尔判断，请用 `is OMNI_NO_CHANGE` 检查")


OMNI_NO_CHANGE = _OmniNoChange()


# ─── CompiledGraph ─────────────────────────────────────────────────────────────
class CompiledGraph:
    """单棵 OmniNode 树的编译结果。"""

    def __init__(self):
        self.instructions    = []       # 编译完成后改为 tuple（不可变）
        self.reg_count       = 0
        self.input_regs      = {}       # {uid: reg_index}
        self.output_regs     = {}       # {uid: reg_index}
        self.tree_name       = ""
        self.tree_ref        = None
        self.runtime_timing_tree_key = None
        self.node_order      = []
        self.compile_trace   = []
        self.register_bridges = []
        self.function_catalog = []
        self.debug_enabled   = False
        self.runtime_cache_contract = None
        self.runtime_namespace_children = ()
        self.runtime_output_contracts = {}

        # ── 懒求值：跨帧持久化寄存器 ──────────────────────────────────────────
        # reg_values  存任意 Python 对象，必须用 list（不能用 array.array）
        # reg_versions 只存整数版本号，用 array.array 做 C 层批量比较
        self.reg_values   = None   # list[Any]，首次执行时分配
        self.reg_versions = None   # array.array('l', ...)，首次执行时分配

        # ── 懒求值：编译期标注 ─────────────────────────────────────────────────
        self.has_always_run_node = False  # 子树内是否含 always_run 节点
        self.inner_lazy_eval     = True   # ref_count==1 才允许子树内部 skip
        self.ref_count           = 0      # 被多少个 SubtreeCall / BatchSubtreeCall 引用

    def ensure_reg_arrays(self):
        """首次执行（或重编译后）分配或重置持久化寄存器数组。"""
        if self.reg_values is None or len(self.reg_values) != self.reg_count:
            self.reg_values   = [None] * self.reg_count
            self.reg_versions = _array.array('l', [0] * self.reg_count)

    def clear_reg_arrays(self):
        """重编译 / dispose 时清空，释放 bpy 引用防悬空。"""
        self.reg_values   = None
        self.reg_versions = None


# ─── OpCall ────────────────────────────────────────────────────────────────────
class OpCall:
    op_type = OP_CALL

    def __init__(self, func, inputs, outputs, node, has_always_run=False):
        self.func    = func      # 直接持有可调用对象
        self.inputs  = inputs    # list[int | list[int]]（兼容旧结构）
        self.outputs = outputs   # list[int]
        self.node    = node

        # ── 懒求值字段 ──────────────────────────────────────────────────────────
        self.has_always_run = has_always_run  # True → 每帧强制执行，不 skip

        # 所有输入寄存器展平（含 multi-input），用于版本比对
        # 编译时由 OmniCompiler 调用 _init_lazy_fields() 初始化
        self.flat_inputs    = None   # array.array('i', ...)
        self.version_buffer = None   # array.array('l', ...)，每帧原地覆写
        self.last_snapshot  = None   # array.array('l', ...)，-1 表示首帧未执行

    def _init_lazy_fields(self):
        """编译完成后初始化 skip 比对数组（由 OmniCompiler 调用）。"""
        flat = []
        for inp in self.inputs:
            if isinstance(inp, list):
                flat.extend(inp)
            else:
                flat.append(inp)
        n = len(flat)
        self.flat_inputs    = _array.array('i', flat)
        self.version_buffer = _array.array('l', [0]  * n)
        self.last_snapshot  = _array.array('l', [-1] * n)  # -1 → 首帧不 skip


# ─── SubtreeCall ───────────────────────────────────────────────────────────────
class SubtreeCall:
    op_type = OP_SUBTREE

    def __init__(self, compiled_graph, inputs, outputs, node):
        self.compiled_graph = compiled_graph
        self.inputs  = inputs
        self.outputs = outputs
        self.node    = node

        # SubtreeCall 级别的 skip 快照（基于父树输入寄存器，始终安全）
        self.flat_inputs    = None
        self.version_buffer = None
        self.last_snapshot  = None

    def _init_lazy_fields(self):
        flat = []
        for inp in self.inputs:
            if isinstance(inp, list):
                flat.extend(inp)
            else:
                flat.append(inp)
        n = len(flat)
        self.flat_inputs    = _array.array('i', flat)
        self.version_buffer = _array.array('l', [0]  * n)
        self.last_snapshot  = _array.array('l', [-1] * n)


# ─── BatchSubtreeCall ──────────────────────────────────────────────────────────
class BatchSubtreeCall:
    op_type = OP_BATCH

    def __init__(self, compiled_graph, inputs, outputs, node, batch_input_index):
        self.compiled_graph   = compiled_graph
        self.inputs           = inputs
        self.outputs          = outputs
        self.node             = node
        self.batch_input_index = batch_input_index


# ─── Cache 系列 ────────────────────────────────────────────────────────────────
class CacheReadCall:
    op_type = OP_CACHE_READ

    def __init__(self, cache_key_input, outputs, node):
        self.cache_key_input = cache_key_input
        self.outputs = outputs
        self.node    = node


class CacheWriteCall:
    op_type = OP_CACHE_WRITE

    def __init__(self, cache_key_input, value_input, enabled_input, outputs, node):
        self.cache_key_input = cache_key_input
        self.value_input     = value_input
        self.enabled_input   = enabled_input
        self.outputs         = outputs
        self.node            = node


class CacheDeleteCall:
    op_type = OP_CACHE_DELETE

    def __init__(self, trigger_input, cache_key_input, delete_all_input, enabled_input, outputs, node):
        self.trigger_input   = trigger_input
        self.cache_key_input = cache_key_input
        self.delete_all_input = delete_all_input
        self.enabled_input   = enabled_input
        self.outputs         = outputs
        self.node            = node


class CacheDumpCall:
    op_type = OP_CACHE_DUMP

    def __init__(self, trigger_input, label_input, outputs, node, print_to_console):
        self.trigger_input  = trigger_input
        self.label_input    = label_input
        self.outputs        = outputs
        self.node           = node
        self.print_to_console = print_to_console


# ─── Timing 桩 ─────────────────────────────────────────────────────────────────
class RuntimeTimingBeginCall:
    op_type = OP_TIMING_BEGIN

    def __init__(self, tree_name, tree_ref):
        self.tree_name = tree_name
        self.tree_ref  = tree_ref


class RuntimeTimingEndCall:
    op_type = OP_TIMING_END

    def __init__(self, tree_name, tree_ref):
        self.tree_name = tree_name
        self.tree_ref  = tree_ref
