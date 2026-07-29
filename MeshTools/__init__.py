import bpy

from . import boolean
from .auto_placement import OP_AutoPlaceObjectBottom
from .bone_chain import OP_CreatBoneChainByMeshFlow
from .hole_fill import OP_ModalFillMeshHole
from .placement import OP_PlaceObjectBottom
from .view import OP_AlignViewToAvgNormal


def reg_props():
    return

def ureg_props():
    return


class VIEW3D_MT_edit_mesh_hotools(bpy.types.Menu):
    """Mesh tools shown in the edit-mesh context menu."""

    bl_label = "Hotools Mesh"

    def draw(self, context):
        layout = self.layout
        layout.operator(OP_AutoPlaceObjectBottom.bl_idname, icon='SNAP_FACE')
        layout.operator(OP_PlaceObjectBottom.bl_idname, icon='TRIA_DOWN')
        layout.operator(
            OP_AlignViewToAvgNormal.bl_idname,
            icon='RESTRICT_RENDER_OFF',
        )
        layout.operator(OP_CreatBoneChainByMeshFlow.bl_idname, icon='ADD')
        layout.operator(OP_ModalFillMeshHole.bl_idname, icon='FACESEL')


def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    self.layout.menu(VIEW3D_MT_edit_mesh_hotools.bl_idname)


def draw_in_VIEW3D_MT_object_context_menu(self, context):
    if (
        context.active_object is not None and
        context.active_object.type == 'MESH'
    ):
        self.layout.operator(
            OP_AutoPlaceObjectBottom.bl_idname,
            icon='SNAP_FACE',
        )


cls = [
    OP_AutoPlaceObjectBottom,
    OP_PlaceObjectBottom,
    OP_AlignViewToAvgNormal,
    OP_CreatBoneChainByMeshFlow,
    OP_ModalFillMeshHole,
    VIEW3D_MT_edit_mesh_hotools,
]


def register():
    boolean.register()
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    bpy.types.VIEW3D_MT_object_context_menu.prepend(
        draw_in_VIEW3D_MT_object_context_menu
    )
    reg_props()


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(
        draw_in_VIEW3D_MT_object_context_menu
    )
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
    boolean.unregister()
    ureg_props()
