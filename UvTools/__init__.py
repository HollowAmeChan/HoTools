import bpy
import bmesh
from bpy.types import Panel

from  . import baker, operators, image, RTbaker

def reg_props():
    return

def ureg_props():
    return


class PL_BakeTools(Panel):
    bl_idname = "VIEW_PT_Hollow_BakeTools"
    bl_label = "烘焙"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        baker.drawBakePanel(layout, context)
        return


class PL_RTBakeTools(Panel):
    bl_idname = "VIEW_PT_Hollow_RTBakeTools"
    bl_label = "RT烘焙"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        RTbaker.drawRTBakePanel(layout, context)
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


cls = [PL_BakeTools, PL_RTBakeTools, PL_ImageTools]

def register():
    baker.register()
    RTbaker.register()
    operators.register()
    image.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    baker.unregister()
    RTbaker.unregister()
    operators.unregister()
    image.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
