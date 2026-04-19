# 本文件为functionnode以外的拓展类型node，用于实现高级功能
import bpy
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd
from bpy.props import CollectionProperty,IntProperty

from .OmniNodeTree import OmniNodeTree
from .OmniNodeOperator import OmniGraphNodeIOItem_update

def OmniTreeFilter(self, tree):
    return isinstance(tree, OmniNodeTree)

class OmniGroupNode(OmniNode):
    # 参考Sverchok得知使用原生的逻辑会非常困难，因此放弃原生逻辑
    # https://blender.stackexchange.com/questions/58614/custom-nodetree-and-nodecustomgroup-and-bpy-ops-node-tree-path-parent
    bl_idname = "HO_OmniNode_GroupNode"
    bl_label = "组引用"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=OmniGraphNodeIOItem_update,
        poll=OmniTreeFilter,
    ) # type: ignore

    def build(self):
        self.syncGroupIO()
        pass

    @staticmethod
    def _func(self):
        pass

    def syncGroupIO(self):
        tree = self.target_tree
        if not tree:return

        self.inputs.clear()
        self.outputs.clear()

        # Group 输入 → 当前 node.inputs
        for io in tree.group_inputs:
            sock = self.inputs.new(type=io.socket_type, name=io.name,identifier=io.identifier)
            sock.hide_value = True
        # Group 输出 → 当前 node.outputs
        for io in tree.group_outputs:
            sock = self.outputs.new(type=io.socket_type, name=io.name,identifier=io.identifier)
            sock.hide_value = True

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        layout.template_ID(self, "target_tree")
        return

class OmniGroupNodeInputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Inputs"
    bl_label = "组输入"

    active_index: IntProperty(default=0) # type: ignore

    def build(self):
        self.syncGroupIO()
        pass
    
    @staticmethod
    def _func(self):
        pass

    def syncGroupIO(self):
        tree = self.id_data
        self.outputs.clear()
        for io in tree.group_inputs:
            sock = self.outputs.new(type=io.socket_type,name=io.name,identifier=io.identifier)
            sock.hide_value = True

    def draw_buttons(self, context, layout):
        tree = self.id_data

        row = layout.row()
        row.template_list(
            "HO_UL_GraphNodeIO",
            "",
            tree,
            "group_inputs",
            tree,
            "group_inputs_index",
            rows=3
        )

        col = row.column(align=True)

        add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
        add.is_input = True

        remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
        remove.is_input = True
    
class OmniGroupNodeOutputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Outputs"
    bl_label = "组输出"

    output_IO: CollectionProperty(type=OmniGraphNodeIOItem)# type: ignore
    active_index: IntProperty(default=0) # type: ignore
    
    def build(self):
        self.syncGroupIO()
        pass

    @staticmethod
    def _func(self):
        pass

    def syncGroupIO(self):
        tree = self.id_data
        self.inputs.clear()

        for io in tree.group_outputs:
            sock = self.inputs.new(type=io.socket_type,name=io.name,identifier=io.identifier)
            sock.hide_value = True
    
    def draw_buttons(self, context, layout):
        tree = self.id_data

        row = layout.row()
        row.template_list(
            "HO_UL_GraphNodeIO",
            "",
            tree,
            "group_outputs",
            tree,
            "group_outputs_index",
            rows=3
        )

        col = row.column(align=True)

        add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
        add.is_input = False

        remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
        remove.is_input = False
    
class OmniGroupNodeRepeat(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Repeat"
    bl_label = "组重复"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=OmniGraphNodeIOItem_update,
        poll=OmniTreeFilter,
    ) # type: ignore

    def build(self):
        self.syncGroupIO()
        pass

    @staticmethod
    def _func(self):
        pass

    def syncGroupIO(self):
        tree = self.target_tree

        self.inputs.clear()
        self.outputs.clear()

        # Group 输入 → 当前 node.inputs
        for io in tree.group_inputs:
            sock = self.inputs.new(type=io.socket_type, name=io.name,identifier=io.identifier)
            sock.hide_value = True
        # Group 输出 → 当前 node.outputs
        for io in tree.group_outputs:
            sock = self.outputs.new(type=io.socket_type, name=io.name,identifier=io.identifier)
            sock.hide_value = True

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        layout.template_ID(self, "target_tree")
        return

CLS_GRAPH = [OmniGroupNode,OmniGroupNodeInputs,OmniGroupNodeOutputs,OmniGroupNodeRepeat]