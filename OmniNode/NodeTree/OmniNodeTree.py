import bpy
from bpy.types import NodeTree
from bpy.props import BoolProperty, CollectionProperty, IntProperty
from bpy.app.handlers import persistent

from .OmniCompiler import OmniCompiler
from .OmniExecutor import OmniExecutor
from .OmniCompiler import SubtreeCall, BatchSubtreeCall
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
        name="Debug Compile",
        description="打印完整编译过程、寄存器桥和运行顺序",
        default=False,
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
        if self.is_auto_update:
            print("树自动运行:", self.name, "\t", time.ctime())
            self.run()
        if not self.use_fake_user:
            self.use_fake_user = True

    def interface_update(self, context):
        print(self.name, " interface_update")

    def _clear_run_state(self):
        OmniNodeDraw.clear_tree(self)

        for node in self.nodes:
            if hasattr(node, "clear_bug_state"):
                node.clear_bug_state()
            elif hasattr(node, "is_bug") and hasattr(node, "bug_text"):
                node.is_bug = False
                node.bug_text = ""

    def compile_cache_status_label(self):
        return "编译缓存: 已缓存" if _cached_compiled_graph(self) is not None else "编译缓存: 无缓存"

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

    def _run_compiled_graph(self, compiled):
        self._clear_run_state()
        debug_enabled = getattr(self, "debug_compile", False)
        result = OmniExecutor.run(compiled, debug=debug_enabled)

        return result

    def run_compiled(self):
        compiled = _cached_compiled_graph(self)
        if compiled is None:
            raise RuntimeError(f"OmniNodeTree '{self.name}' has not been compiled")

        return self._run_compiled_graph(compiled)

    def run_frame_cached(self):
        compiled = self.compile_cached(force=False)
        return self._run_compiled_graph(compiled)

    def run(self):
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

    layout.prop(tree, "debug_compile", text="Debug编译/运行", toggle=True)
    layout.label(text=tree.compile_cache_status_label())
    layout.prop(tree, "is_frame_run_enabled", text="每帧运行", toggle=True)

    if tree.is_auto_update:
        layout.alert = True
        layout.prop(tree,"is_auto_update", text="树自动更新", icon="DECORATE_LINKED")
        layout.alert = False
    else:
        layout.prop(tree,"is_auto_update", text="树自动更新", icon="UNLINKED")

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
