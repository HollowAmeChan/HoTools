import bpy

from .bake_smoothnormal import HO_OT_bake_smoothnormal_os
from .properties import get_scene_settings


def draw_in_DATA_PT_mesh_attributes(self, context):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return

    settings = get_scene_settings(context.scene)
    box = self.layout.box()
    row = box.row(align=True)
    row.prop(settings, "smoothnormal_attribute_name", text="")
    row.operator(
        HO_OT_bake_smoothnormal_os.bl_idname,
        text="烘焙对象空间平滑法线",
        icon="NORMALS_VERTEX",
    )

def register():
    bpy.types.DATA_PT_mesh_attributes.append(draw_in_DATA_PT_mesh_attributes)


def unregister():
    bpy.types.DATA_PT_mesh_attributes.remove(draw_in_DATA_PT_mesh_attributes)
