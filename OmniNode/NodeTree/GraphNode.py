# 本文件为functionnode以外的拓展类型node，用于实现高级功能
import bpy
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd
from bpy.props import CollectionProperty,IntProperty


class OmniGroupNode(OmniNode):
    # TODO:参考Sverchok得知使用原生的逻辑会非常困难，因此放弃原生逻辑
    # https://blender.stackexchange.com/questions/58614/custom-nodetree-and-nodecustomgroup-and-bpy-ops-node-tree-path-parent
    bl_idname = "HO_OmniNode_GroupNode"
    bl_label = "组引用"

    def build(self, context):
        pass

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        return

class OmniGroupNodeInputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Inputs"
    bl_label = "组输入"

    def build(self, context):
        pass

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        return
    
class OmniGroupNodeOutputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Outputs"
    bl_label = "组输出"

    output_IO: CollectionProperty(type=OmniGraphNodeIOItem)# type: ignore
    active_index: IntProperty(default=0) # type: ignore

    last_debug_data = None

    @staticmethod
    def _func():
        pass
    
    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        # layout.label(text="Debug Output Node")

        row = layout.row()
        row.template_list(
                        HO_UL_GraphNodeIO.__name__,
                        "",
                        self,
                        "output_IO",
                        self,
                        "active_index",
                        rows=3
                        )
        col = row.column(align=True)
        add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
        add.node_name = self.name
        remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
        remove.node_name = self.name
        return
    
class OmniGroupNodeRepeat(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Repeat"
    bl_label = "组重复"

    def build(self, context):
        pass

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        return

CLS_GRAPH = [OmniGroupNode,OmniGroupNodeInputs,OmniGroupNodeOutputs,OmniGroupNodeRepeat]