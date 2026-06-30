import bpy
from bpy.types import NodeTree
from bpy.props import BoolProperty, CollectionProperty, IntProperty
from bpy.app.handlers import persistent

from .OmniCompiler import OmniCompiler
from .OmniExecutor import OmniExecutor
from .OmniIR import SubtreeCall, BatchSubtreeCall
from .OmniDebug import OmniDebug
from . import OmniNodeDraw
from .OmniNodeOperator import (
    HO_UL_GraphNodeIO,
    OP_IOItemAdd,
    OP_IOItemRemove,
    OP_IOItemMove,
    OmniGraphNodeIOItem,
)

import time

TREE_ID = "OMNINODE"
TREE_ID_NAME = "OmniNodeTree"

# tree key -> CompiledGraph. Keeps compile artifacts for multiple OmniNodeTree datablocks.
_COMPILED_TREE_CACHE = {}
_FRAME_HANDLER_RUNNING = False


def _tree_cache_key(tree):
    if tree is None:
        return "tree:<none>"

    try:
        return f"tree:{int(tree.as_pointer())}"
    except Exception:
        return f"tree:{id(tree)}"


def clear_tree_compile_cache(tree):
    _COMPILED_TREE_CACHE.pop(_tree_cache_key(tree), None)


def _cached_compiled_graph(tree):
    return _COMPILED_TREE_CACHE.get(_tree_cache_key(tree))


def _is_omni_node_tree(tree):
    return tree is not None and getattr(tree, "bl_idname", None) == TREE_ID_NAME


@persistent
def _omni_frame_change_post(scene, depsgraph=None):
    global _FRAME_HANDLER_RUNNING
    if _FRAME_HANDLER_RUNNING:
        return

    _FRAME_HANDLER_RUNNING = True
    try:
        for tree in list(bpy.data.node_groups):
            if not _is_omni_node_tree(tree):
                continue
            if not getattr(tree, "is_execution_enabled", True):
                continue
            if not getattr(tree, "is_frame_run_enabled", False):
                continue
            try:
                tree.run_frame_cached()
            except Exception as exc:
                try:
                    tree.is_frame_run_enabled = False
                except Exception:
                    pass
                print(f"[OmniNode Frame Run] disabled '{getattr(tree, 'name', '<tree>')}': {exc}")
    finally:
        OmniDebug.flush_runtime_timing()
        _FRAME_HANDLER_RUNNING = False


def _ensure_frame_handler():
    handlers = bpy.app.handlers.frame_change_post
    if _omni_frame_change_post not in handlers:
        handlers.append(_omni_frame_change_post)


def _remove_frame_handler():
    handlers = bpy.app.handlers.frame_change_post
    while _omni_frame_change_post in handlers:
        handlers.remove(_omni_frame_change_post)


class OmniNodeTree(NodeTree):
    bl_idname = TREE_ID_NAME
    bl_label = "Omni节点图"
    bl_icon = "NODETREE"

    is_execution_enabled: BoolProperty(
        name="启用",
        description="关闭后只能编译，不能手动运行、运行已编译结果、自动更新或每帧运行",
        default=True,
    )  # type: ignore
    is_auto_update: bpy.props.BoolProperty(
        description="是否实时刷新",
        default=False,
    )  # type: ignore
    is_frame_run_enabled: BoolProperty(
        name="每帧运行",
        description="帧变化后自动运行。没有编译缓存时会先编译一次，之后直接运行缓存的编译结果。",
        default=False,
    )  # type: ignore
    debug_compile: bpy.props.BoolProperty(
        name="Debug编译",
        description="打印完整编译过程和寄存器桥，只在编译或重编译时输出。",
        default=False,
    )  # type: ignore
    debug_runtime_trace: bpy.props.BoolProperty(
        name="Debug运行",
        description="打印每次运行的完整指令执行过程。每帧运行时会非常频繁。",
        default=False,
    )  # type: ignore
    debug_runtime_timing: bpy.props.BoolProperty(
        name="Debug运行时长",
        description="启用编译期运行时长插桩，并按输出间隔聚合打印。",
        default=False,
    )  # type: ignore
    debug_runtime_timing_interval: bpy.props.FloatProperty(
        name="输出间隔",
        description="运行时长统计输出间隔，单位为秒。",
        default=1.0,
        min=0.05,
        soft_max=10.0,
    )  # type: ignore
    doing_initNode: bpy.props.BoolProperty(
        description="阻止新建节点频繁回调",
        default=False,
    )  # type: ignore
    group_inputs: CollectionProperty(type=OmniGraphNodeIOItem)  # type: ignore
    group_inputs_index: IntProperty(default=0)  # type: ignore
    group_outputs: CollectionProperty(type=OmniGraphNodeIOItem)  # type: ignore
    group_outputs_index: IntProperty(default=0)  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def update(self):
        if self.doing_initNode:
            return
        if self.is_execution_enabled and self.is_auto_update:
            print("树自动运行:", self.name, "\t", time.ctime())
            self.run()
        if not self.use_fake_user:
            self.use_fake_user = True

    def interface_update(self, context):
        print(self.name, " interface_update")

    def _clear_run_state(self, full=True):
        # full=True: 编译时全树清理（overlay + 所有节点 bug 状态）。
        # full=False: 执行时仅清理当前真正带 bug 标记的节点，
        #             正常帧没有 bug 节点时几乎零开销，避免每帧全树刷新。
        if full:
            OmniNodeDraw.clear_tree(self)

        for node in self.nodes:
            if not full and not getattr(node, "is_bug", False):
                continue
            if hasattr(node, "clear_bug_state"):
                node.clear_bug_state()
            elif hasattr(node, "is_bug") and hasattr(node, "bug_text"):
                node.is_bug = False
                node.bug_text = ""

    def compile_cache_status_label(self):
        return "已缓存" if _cached_compiled_graph(self) is not None else "无缓存"

    def _ensure_execution_enabled(self):
        if not getattr(self, "is_execution_enabled", True):
            raise RuntimeError(f"OmniNodeTree '{self.name}' is disabled")

    def compile_cached(self, force=False):
        cache_key = _tree_cache_key(self)
        compiled = _COMPILED_TREE_CACHE.get(cache_key)

        if not force and compiled is not None:
            return compiled

        self._clear_run_state()
        debug_enabled = getattr(self, "debug_compile", False)
        compiled = OmniCompiler.compile(self, debug=debug_enabled)

        _COMPILED_TREE_CACHE[cache_key] = compiled

        if debug_enabled:
            print("\n".join(OmniDebug.format_runtime_header(self.name)))
            print("\n".join(OmniDebug.format_compile_report(compiled, (SubtreeCall, BatchSubtreeCall))))
            print("\n".join(OmniDebug.format_runtime_separator(self.name)))

        return compiled

    def clear_compile_cache(self):
        clear_tree_compile_cache(self)

    def _run_compiled_graph(self, compiled, phases=None):
        self._ensure_execution_enabled()

        t = time.perf_counter()
        self._clear_run_state(full=False)
        if phases is not None:
            phases["[frame] clear_state"] = time.perf_counter() - t

        # 不再单独计 [frame] execute 聚合项：OmniExecutor.run 已把
        # begin_run/finish_run 及顶层 step 明细作为叶子项并入 phases，
        # 所有叶子项相加即等于 total，避免重复计数。
        debug_enabled = getattr(self, "debug_runtime_trace", False)
        result = OmniExecutor.run(compiled, debug=debug_enabled, phases=phases)

        return result

    def run_compiled(self):
        self._ensure_execution_enabled()
        compiled = _cached_compiled_graph(self)
        if compiled is None:
            raise RuntimeError(f"OmniNodeTree '{self.name}' has not been compiled")

        try:
            return self._run_compiled_graph(compiled)
        finally:
            if not _FRAME_HANDLER_RUNNING:
                OmniDebug.flush_runtime_timing()

    def run_frame_cached(self):
        self._ensure_execution_enabled()

        if not bool(getattr(self, "debug_runtime_timing", False)):
            compiled = self.compile_cached(force=False)
            return self._run_compiled_graph(compiled)

        # 统一帧计时：从 handler 入口到回写的整条链路，
        # 外层 phase（compile_check / clear_state / begin_run / finish_run）
        # 与执行器内部 step 明细并入同一份报告，所有叶子项之和即为 total。
        phases = {}
        frame_start = time.perf_counter()

        t = time.perf_counter()
        compiled = self.compile_cached(force=False)
        phases["[frame] compile_check"] = time.perf_counter() - t

        try:
            return self._run_compiled_graph(compiled, phases=phases)
        finally:
            total = time.perf_counter() - frame_start
            # 残差桶：total 减去所有已插桩叶子项之和，
            # 代表未被插桩的缝隙（step 循环调度、计时器自身开销等），
            # 保证所有项相加精确等于 total。
            measured = sum(phases.values())
            residual = total - measured
            if residual > 0.0:
                phases["[frame] unmeasured"] = residual
            phases["total"] = total
            try:
                interval = float(getattr(self, "debug_runtime_timing_interval", 1.0))
            except Exception:
                interval = 1.0
            OmniDebug.record_runtime_timing(
                self.name,
                f"frame:{int(self.as_pointer())}",
                phases,
                interval=interval,
                frame_level=True,
            )

    def run(self):
        self._ensure_execution_enabled()
        self.compile_cached(force=True)
        return self.run_compiled()


def draw_OmniTreeInputs(layout, tree):
    layout.label(text="Omni树输入:")
    row = layout.row()
    row.template_list(
        HO_UL_GraphNodeIO.__name__,
        "",
        tree,
        "group_inputs",
        tree,
        "group_inputs_index",
        rows=3,
    )
    col = row.column(align=True)
    add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
    add.is_input = True
    remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
    remove.is_input = True
    moveUp = col.operator(OP_IOItemMove.bl_idname, icon="TRIA_UP", text="")
    moveUp.is_input = True
    moveUp.is_Down = False
    moveDown = col.operator(OP_IOItemMove.bl_idname, icon="TRIA_DOWN", text="")
    moveDown.is_input = True
    moveDown.is_Down = True

def draw_OmniTreeOutputs(layout, tree):
    layout.label(text="Omni树输出:")
    row = layout.row()
    row.template_list(
        HO_UL_GraphNodeIO.__name__,
        "",
        tree,
        "group_outputs",
        tree,
        "group_outputs_index",
        rows=3,
    )
    col = row.column(align=True)
    add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
    add.is_input = False
    remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
    remove.is_input = False
    moveUp = col.operator(OP_IOItemMove.bl_idname, icon="TRIA_UP", text="")
    moveUp.is_input = False
    moveUp.is_Down = False
    moveDown = col.operator(OP_IOItemMove.bl_idname, icon="TRIA_DOWN", text="")
    moveDown.is_input = False
    moveDown.is_Down = True


def draw_in_NODE_PT_node_tree_properties(self, context: bpy.types.Context):
    layout: bpy.types.UILayout = self.layout
    tree: OmniNodeTree = context.space_data.node_tree

    if tree is None or getattr(tree, "bl_idname", "") != TREE_ID_NAME:
        return

    layout.prop(tree, "is_execution_enabled", text="", toggle=True,icon_only=True)
    layout.prop(tree, "debug_compile", text="Debug编译", toggle=True)
    layout.prop(tree, "debug_runtime_trace", text="Debug运行", toggle=True)
    layout.prop(tree, "debug_runtime_timing", text="Debug运行时长", toggle=True)
    layout.prop(tree, "debug_runtime_timing_interval", text="输出间隔")
    layout.label(text=tree.compile_cache_status_label())

    execution_enabled = bool(getattr(tree, "is_execution_enabled", True))
    frame_row = layout.row()
    frame_row.enabled = execution_enabled
    frame_row.prop(tree, "is_frame_run_enabled", text="每帧运行", toggle=True)

    auto_row = layout.row()
    auto_row.enabled = execution_enabled
    if tree.is_auto_update:
        auto_row.alert = True
        auto_row.prop(tree, "is_auto_update", text="树自动更新", icon="DECORATE_LINKED")
    else:
        auto_row.prop(tree, "is_auto_update", text="树自动更新", icon="UNLINKED")

    draw_OmniTreeInputs(layout, tree)
    draw_OmniTreeOutputs(layout, tree)


cls = [OmniNodeTree]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    _ensure_frame_handler()
    bpy.types.NODE_PT_node_tree_properties.append(draw_in_NODE_PT_node_tree_properties)


def unregister():
    bpy.types.NODE_PT_node_tree_properties.remove(draw_in_NODE_PT_node_tree_properties)
    _remove_frame_handler()
    _COMPILED_TREE_CACHE.clear()
    for item in cls:
        bpy.utils.unregister_class(item)
