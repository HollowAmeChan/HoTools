import bpy

from . import boolean
from .bone_chain import OP_CreatBoneChainByMeshFlow
from .hole_fill import OP_ModalFillMeshHole
from .edge_constraint import TransformEdgeConstrained
from .visual_boolean import OP_VisualBooleanCut
from .placement import (
    OP_AutoPlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_PlaceObjectBottom,
    OP_SnapSelectedFaceOrthogonal,
)
from .view import OP_AlignViewToAvgNormal


def reg_props():
    return

def ureg_props():
    return


class VIEW3D_MT_edit_mesh_hotools(bpy.types.Menu):
    """Mesh tools shown in the edit-mesh context menu."""

    bl_idname = "VIEW3D_MT_edit_mesh_hotools"
    bl_label = "Hotools Mesh"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            OP_AutoPlaceObjectBottom.bl_idname,
            icon='SNAP_FACE',
        )
        layout.operator(
            OP_PlaceObjectBottom.bl_idname,
            icon='TRIA_DOWN',
        )
        layout.operator(
            OP_AutoSnapFaceOrthogonal.bl_idname,
            icon='ORIENTATION_GLOBAL',
        )
        layout.operator(
            OP_SnapSelectedFaceOrthogonal.bl_idname,
            icon='ORIENTATION_GLOBAL',
        )
        layout.operator(
            OP_AlignViewToAvgNormal.bl_idname,
            icon='RESTRICT_RENDER_OFF',
        )
        layout.operator(OP_CreatBoneChainByMeshFlow.bl_idname, icon='ADD')
        layout.operator(OP_ModalFillMeshHole.bl_idname, icon='FACESEL')
        layout.operator(TransformEdgeConstrained.bl_idname, icon='MOD_EDGESPLIT')


def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    self.layout.menu(VIEW3D_MT_edit_mesh_hotools.bl_idname)


cls = [
    OP_AutoPlaceObjectBottom,
    OP_PlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_SnapSelectedFaceOrthogonal,
    OP_AlignViewToAvgNormal,
    OP_CreatBoneChainByMeshFlow,
    OP_ModalFillMeshHole,
    TransformEdgeConstrained,
    OP_VisualBooleanCut,
    VIEW3D_MT_edit_mesh_hotools,
]


addon_keymaps = []


def register():
    boolean.register()
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )

    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(
            name="Mesh",
            space_type='EMPTY',
            region_type='WINDOW',
        )
        keymap_item = keymap.keymap_items.new(
            TransformEdgeConstrained.bl_idname,
            type='R',
            value='PRESS',
            alt=True,
        )
        keymap_item.properties.transform_mode = 'ROTATE'
        keymap_item.properties.objmode = False
        addon_keymaps.append((keymap, keymap_item))
    reg_props()


def unregister():
    for keymap, keymap_item in addon_keymaps:
        keymap.keymap_items.remove(keymap_item)
    addon_keymaps.clear()

    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
    boolean.unregister()
    ureg_props()
