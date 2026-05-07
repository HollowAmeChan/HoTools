import bpy
from bpy.types import NodeTree
from bpy.props import CollectionProperty, IntProperty

from .OmniCompiler import OmniCompiler
from .OmniExecutor import OmniExecutor
from .OmniCompiler import SubtreeCall, BatchSubtreeCall
from .OmniDebug import OmniDebug
from . import OmniNodeDraw
from . import OmniMenuBind
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


class OmniNodeTree(NodeTree):
    bl_idname = TREE_ID_NAME
    bl_label = "Omni节点图"
    bl_icon = "NODETREE"

    is_auto_update: bpy.props.BoolProperty(
        description="是否实时刷新",
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

    def run(self):
        OmniNodeDraw.clear_tree(self)
        OmniMenuBind.OmniMenuBindRuntime.clear_runtime_items(self)

        if hasattr(self, "omni_bind_pending_rules"):
            self.omni_bind_pending_rules.clear()

        OmniMenuBind.clear_live_bind_contexts(self)

        for node in self.nodes:
            if hasattr(node, "clear_bug_state"):
                node.clear_bug_state()
            else:
                node.is_bug = False
                node.bug_text = ""

        debug_enabled = getattr(self, "debug_compile", False)
        compiled = OmniCompiler.compile(self, debug=debug_enabled)

        if debug_enabled:
            print("\n".join(OmniDebug.format_runtime_header(self.name)))
            print("\n".join(OmniDebug.format_compile_report(compiled, (SubtreeCall, BatchSubtreeCall))))
            print("\n".join(OmniDebug.format_runtime_separator(self.name)))

        result = OmniExecutor.run(compiled, debug=debug_enabled)

        if hasattr(self, "omni_bind_pending_rules") and len(self.omni_bind_pending_rules) > 0:
            OmniMenuBind.OmniMenuBindRuntime.build_runtime_items_from_pending(self)

        return result


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
    tree = context.space_data.node_tree

    if tree is None or getattr(tree, "bl_idname", "") != TREE_ID_NAME:
        return

    layout.prop(tree, "debug_compile", text="Debug编译/运行", toggle=True)

    if tree.is_auto_update:
        layout.alert = True
        layout.prop(tree,"is_auto_update", text="树自动更新", icon="DECORATE_LINKED")
        layout.alert = False
    else:
        layout.prop(tree,"is_auto_update", text="树自动更新", icon="UNLINKED")

    draw_OmniTreeInputs(layout, tree)
    draw_OmniTreeOutputs(layout, tree)
    OmniMenuBind.OmniMenuBindRuntime.draw_runtime_panel(layout, tree)


cls = [OmniNodeTree]


def register():
    OmniMenuBind.register()
    for item in cls:
        bpy.utils.register_class(item)
    OmniMenuBind.OmniMenuBindRuntime.ensure_tree_props(OmniNodeTree)
    bpy.types.NODE_PT_node_tree_properties.append(draw_in_NODE_PT_node_tree_properties)


def unregister():
    bpy.types.NODE_PT_node_tree_properties.remove(draw_in_NODE_PT_node_tree_properties)
    OmniMenuBind.OmniMenuBindRuntime.remove_tree_props(OmniNodeTree)
    for item in cls:
        bpy.utils.unregister_class(item)
    OmniMenuBind.unregister()
