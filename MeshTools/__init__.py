import bpy

from . import boolean
from .bone_chain import OP_CreatBoneChainByMeshFlow
from .hole_fill import OP_ModalFillMeshHole
from .placement import OP_AutoPlaceObjectBottom, OP_PlaceObjectBottom
from .view import OP_AlignViewToAvgNormal


def reg_props():
    bpy.types.Scene.hotools_mesh_keep_origin_transform = (
        bpy.props.BoolProperty(
            name="保持原点变换",
            description="底面放置时保持物体原点的位置和旋转不变",
            default=True,
        )
    )

def ureg_props():
    if hasattr(
        bpy.types.Scene,
        "hotools_mesh_keep_origin_transform",
    ):
        del bpy.types.Scene.hotools_mesh_keep_origin_transform


class VIEW3D_MT_edit_mesh_hotools(bpy.types.Menu):
    """Mesh tools shown in the edit-mesh context menu."""

    bl_idname = "VIEW3D_MT_edit_mesh_hotools"
    bl_label = "Hotools Mesh"

    def draw(self, context):
        layout = self.layout
        keep_origin = context.scene.hotools_mesh_keep_origin_transform
        layout.prop(
            context.scene,
            "hotools_mesh_keep_origin_transform",
        )
        auto_operator = layout.operator(
            OP_AutoPlaceObjectBottom.bl_idname,
            icon='SNAP_FACE',
        )
        auto_operator.keep_origin_transform = keep_origin
        manual_operator = layout.operator(
            OP_PlaceObjectBottom.bl_idname,
            icon='TRIA_DOWN',
        )
        manual_operator.keep_origin_transform = keep_origin
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
        layout = self.layout
        layout.prop(
            context.scene,
            "hotools_mesh_keep_origin_transform",
        )
        operator = layout.operator(
            OP_AutoPlaceObjectBottom.bl_idname,
            icon='SNAP_FACE',
        )
        operator.keep_origin_transform = (
            context.scene.hotools_mesh_keep_origin_transform
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
