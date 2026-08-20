import bpy

from . import boolean
from .bone_chain import OP_CreatBoneChainByMeshFlow
from .edge_constraint import OP_TransformEdgeConstrained
from .edge_flow import (
    EDGE_FLOW_CLASSES,
    HO_OT_SetEdgeCurve,
    HO_OT_SetEdgeFlow,
    HO_OT_SetEdgeLinear,
)
from .fill_selection import OP_FillSelection
from .ho_mesh import (
    HO_MESH_CLASSES,
    HO_OT_MeshCircleEven,
    HO_OT_MeshFlatten,
    HO_OT_MeshRelax,
)
from .hole_fill import OP_ModalFillMeshHole
from .select import (
    OP_EnhancedSelect,
    OP_SelectLoop,
    OP_SelectSharpChain,
)
from . import symmetrize
from .symmetrize import OP_Symmetrize
from .ring_select import OP_AddSelectSideRingLoops, OP_RemoveSelectSideRingLoops
from .visual_boolean import OP_VisualBooleanCut
from .view import OP_AlignViewToAvgNormal
from .custom_normals import (
    OP_CustomSplitNormals_Export,
    OP_CustomSplitNormals_Import,
)
from .normals import OP_MergeOverlapping_VertexNormals


def draw_in_DATA_PT_customdata(self, context):
    row = self.layout.row(align=True)
    row.operator(OP_CustomSplitNormals_Export.bl_idname)
    row.operator(OP_CustomSplitNormals_Import.bl_idname)


def draw_in_VIEW3D_MT_edit_mesh_merge(self, context):
    self.layout.operator(OP_MergeOverlapping_VertexNormals.bl_idname)


class VIEW3D_MT_edit_mesh_hotools(bpy.types.Menu):
    """Mesh editing context menu."""

    bl_idname = "VIEW3D_MT_edit_mesh_hotools"
    bl_label = "Hotools Mesh"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            OP_AlignViewToAvgNormal.bl_idname,
            icon='RESTRICT_RENDER_OFF',
        )
        layout.operator(OP_CreatBoneChainByMeshFlow.bl_idname, icon='ADD')
        layout.operator(OP_ModalFillMeshHole.bl_idname, icon='FACESEL')
        layout.separator()
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator(HO_OT_SetEdgeFlow.bl_idname, text='Set Edge Flow', icon='MOD_CURVE')
        layout.operator(HO_OT_SetEdgeCurve.bl_idname, text='Set Edge Curve', icon='CURVE_BEZCURVE')
        layout.operator(HO_OT_SetEdgeLinear.bl_idname, text='Set Edge Linear', icon='IPO_LINEAR')
        layout.separator()
        layout.operator(HO_OT_MeshFlatten.bl_idname, text='Flatten', icon='MESH_GRID')
        layout.operator(HO_OT_MeshRelax.bl_idname, text='Relax', icon='MOD_SMOOTH')
        layout.operator(HO_OT_MeshCircleEven.bl_idname, text='Even Circle', icon='MESH_CIRCLE')


def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    self.layout.menu(VIEW3D_MT_edit_mesh_hotools.bl_idname)


_SUPPLEMENTAL_CLASSES = (
    *EDGE_FLOW_CLASSES,
    *HO_MESH_CLASSES,
    OP_CustomSplitNormals_Export,
    OP_CustomSplitNormals_Import,
    OP_MergeOverlapping_VertexNormals,
)

CLASSES = [
    OP_AlignViewToAvgNormal,
    OP_CreatBoneChainByMeshFlow,
    OP_ModalFillMeshHole,
    OP_TransformEdgeConstrained,
    OP_Symmetrize,
    OP_EnhancedSelect,
    OP_SelectLoop,
    OP_SelectSharpChain,
    OP_FillSelection,
    OP_AddSelectSideRingLoops,
    OP_RemoveSelectSideRingLoops,
    OP_VisualBooleanCut,
    VIEW3D_MT_edit_mesh_hotools,
    *_SUPPLEMENTAL_CLASSES,
]
cls = CLASSES
addon_keymaps = []


def preference_keymaps():
    return addon_keymaps


def register():
    boolean.register()
    for operator_class in CLASSES:
        bpy.utils.register_class(operator_class)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    bpy.types.DATA_PT_customdata.append(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_edit_mesh_merge.append(draw_in_VIEW3D_MT_edit_mesh_merge)
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
            head=True,
        )
        keymap_item.properties.transform_mode = 'ROTATE'
        keymap_item.properties.objmode = False
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = keymap.keymap_items.new(
            OP_EnhancedSelect.bl_idname,
            type='LEFTMOUSE',
            value='PRESS',
            alt=True,
            head=True,
        )
        addon_keymaps.append((keymap, keymap_item))

        mesh_keymap = keymap
        keymap = keyconfig.keymaps.new(
            name='Window',
            space_type='EMPTY',
            region_type='WINDOW',
        )
        keymap_item = keymap.keymap_items.new(
            OP_FillSelection.bl_idname,
            type='RIGHTMOUSE',
            value='PRESS',
            ctrl=True,
            shift=True,
            head=True,
        )
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = keymap.keymap_items.new(
            OP_AddSelectSideRingLoops.bl_idname,
            type='NUMPAD_PLUS',
            value='PRESS',
            alt=True,
            head=True,
        )
        addon_keymaps.append((keymap, keymap_item))
        keymap_item = keymap.keymap_items.new(
            OP_RemoveSelectSideRingLoops.bl_idname,
            type='NUMPAD_MINUS',
            value='PRESS',
            alt=True,
            head=True,
        )
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = mesh_keymap.keymap_items.new(
            OP_Symmetrize.bl_idname,
            type='X',
            value='PRESS',
            alt=True,
            head=True,
        )
        keymap_item.properties.flick = True
        keymap_item.properties.objmode = False
        addon_keymaps.append((mesh_keymap, keymap_item))




def unregister():
    for keymap, keymap_item in addon_keymaps:
        keymap.keymap_items.remove(keymap_item)
    addon_keymaps.clear()

    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    bpy.types.DATA_PT_customdata.remove(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_edit_mesh_merge.remove(draw_in_VIEW3D_MT_edit_mesh_merge)
    for operator_class in reversed(CLASSES):
        bpy.utils.unregister_class(operator_class)
    boolean.unregister()
