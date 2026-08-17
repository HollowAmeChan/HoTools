import bpy

from . import boolean
from .align import Align, AlignRelative
from .bone_chain import OP_CreatBoneChainByMeshFlow
from .hole_fill import OP_ModalFillMeshHole
from .edge_constraint import OP_TransformEdgeConstrained
from .symmetrize import OP_Symmetrize
from .select import (
    OP_EnhancedSelect,
    OP_SelectLoop,
    OP_SelectSharpChain,
    OP_SelectVertexGroup,
)
from .visual_boolean import OP_VisualBooleanCut
from .placement import (
    OP_AutoPlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_PlaceObjectBottom,
    OP_SnapSelectedFaceOrthogonal,
)
from .view import OP_AlignViewToAvgNormal

TransformEdgeConstrained = OP_TransformEdgeConstrained


def reg_props():
    return

def ureg_props():
    return


class VIEW3D_MT_edit_mesh_hotools(bpy.types.Menu):
    """编辑模式右键菜单"""

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

def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    self.layout.menu(VIEW3D_MT_edit_mesh_hotools.bl_idname)


cls = [
    Align,
    AlignRelative,
    OP_AutoPlaceObjectBottom,
    OP_PlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_SnapSelectedFaceOrthogonal,
    OP_AlignViewToAvgNormal,
    OP_CreatBoneChainByMeshFlow,
    OP_ModalFillMeshHole,
    OP_TransformEdgeConstrained,
    OP_Symmetrize,
    OP_EnhancedSelect,
    OP_SelectLoop,
    OP_SelectSharpChain,
    OP_SelectVertexGroup,
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
            OP_TransformEdgeConstrained.bl_idname,
            type='R',
            value='PRESS',
            alt=True,
        )
        keymap_item.properties.transform_mode = 'ROTATE'
        keymap_item.properties.objmode = False
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = keymap.keymap_items.new(
            OP_EnhancedSelect.bl_idname,
            type='LEFTMOUSE',
            value='PRESS',
            alt=True,
        )
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = keymap.keymap_items.new(
            OP_Symmetrize.bl_idname,
            type='X',
            value='PRESS',
            alt=True,
        )
        keymap_item.properties.flick = True
        keymap_item.properties.objmode = False
        addon_keymaps.append((keymap, keymap_item))

        for keymap_name in ("Object Mode", "Pose"):
            keymap = keyconfig.keymaps.new(
                name=keymap_name,
                space_type='EMPTY',
                region_type='WINDOW',
            )
            keymap_item = keymap.keymap_items.new(
                Align.bl_idname,
                type='A',
                value='PRESS',
                alt=True,
            )
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
