import bpy
import bmesh
from bpy.types import Panel

from  . import baker,operators,image

def reg_props():
    return

def ureg_props():
    return


class PL_UvTools(Panel):
    bl_idname = "VIEW_PT_Hollow_UvTools"
    bl_label = "UV工具"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        baker.drawBakePanel(layout, context)
        return


class PL_ImageTools(Panel):
    bl_idname = "VIEW_PT_Hollow_ImageTools"
    bl_label = "图像工具"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        image.drawImagePanel(layout, context)
        return


cls = [PL_UvTools, PL_ImageTools]

def register():
    baker.register()
    operators.register()
    image.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    baker.unregister()
    operators.unregister()
    image.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
