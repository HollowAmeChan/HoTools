import bpy
from bpy.types import Panel
from ..operator.NodeBaseOps import LayerRunning, LoadGlslFile2BlenderTextData


class HollowPanel(Panel):
    bl_idname = "VIEW_PT_OminiNodePanel"
    bl_label = "OmniNode"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"  # 指定面板显示在指定类型下的区域
    bl_category = "HollowAddon"  # 在区域内的归类（VIEW_3D-UI下就是T面板的类）

    def draw(self, context):
        layout = self.layout
        layout.operator(LayerRunning.bl_idname)
        layout.operator(LoadGlslFile2BlenderTextData.bl_idname)

    @classmethod
    def poll(cls, context):
        if bpy.context.space_data.node_tree:
            return bpy.context.space_data.node_tree.bl_idname == "OmniNodeTree"
        else:
            return False


clss = [
    HollowPanel
]


def register():
    for i in clss:
        bpy.utils.register_class(i)


def unregister():
    for i in clss:
        bpy.utils.unregister_class(i)
