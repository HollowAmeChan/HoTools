# 本文件为functionnode以外的拓展类型node，用于实现高级功能
import bpy
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd
from bpy.props import CollectionProperty,IntProperty

from .OmniNodeTree import OmniNodeTree
from .OmniNodeOperator import OmniGraphNodeIOItem_update


class OmniGroupNode(OmniNode):
    # TODO:参考Sverchok得知使用原生的逻辑会非常困难，因此放弃原生逻辑
    # https://blender.stackexchange.com/questions/58614/custom-nodetree-and-nodecustomgroup-and-bpy-ops-node-tree-path-parent
    bl_idname = "HO_OmniNode_GroupNode"
    bl_label = "组引用"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=OmniGraphNodeIOItem_update
    ) # type: ignore

    def build(self):
        pass

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        layout.prop_search(
            self,
            "target_tree",
            bpy.data,
            "node_groups",
            text="Group"
        )
        #TODO:没有过滤，直接使用prop绘制会无法修改
        return

class OmniGroupNodeInputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Inputs"
    bl_label = "组输入"

    active_index: IntProperty(default=0) # type: ignore

    def build(self):
        pass

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

    @staticmethod
    def _func():
        pass
    
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

    def build(self):
        pass

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        return

CLS_GRAPH = [OmniGroupNode,OmniGroupNodeInputs,OmniGroupNodeOutputs,OmniGroupNodeRepeat]