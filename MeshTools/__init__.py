import bpy

from . import boolean
from .align import OP_Align, OP_AlignRelative
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
from .fill_selection import OP_FillSelection
from .ring_select import OP_AddSelectSideRingLoops, OP_RemoveSelectSideRingLoops
from .visual_boolean import OP_VisualBooleanCut
from .placement import (
    OP_AutoPlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_PlaceObjectBottom,
    OP_SnapSelectedFaceOrthogonal,
)
from .view import OP_AlignViewToAvgNormal
from .edge_flow import (
    EDGE_FLOW_CLASSES,
    HO_OT_SetEdgeCurve,
    HO_OT_SetEdgeFlow,
    HO_OT_SetEdgeLinear,
)
from .ho_mesh import (
    HO_MESH_CLASSES,
    HO_OT_MeshCircleEven,
    HO_OT_MeshFlatten,
    HO_OT_MeshRelax,
)
from .curve_bevel import OP_CurveBevel
from .curve_repair import (
    HO_MT_curve,
    OP_RepairCurvePath,
    draw_in_VIEW3D_MT_edit_curve_context_menu,
)

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
        layout.separator()
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator(HO_OT_SetEdgeFlow.bl_idname, text='设置流', icon='MOD_CURVE')
        layout.operator(HO_OT_SetEdgeCurve.bl_idname, text='设置曲线', icon='CURVE_BEZCURVE')
        layout.operator(HO_OT_SetEdgeLinear.bl_idname, text='设置直线', icon='IPO_LINEAR')
        layout.separator()
        layout.operator(HO_OT_MeshFlatten.bl_idname, text='平化', icon='MESH_GRID')
        layout.operator(HO_OT_MeshRelax.bl_idname, text='松弛', icon='MOD_SMOOTH')
        layout.operator(HO_OT_MeshCircleEven.bl_idname, text='圆化（均匀间距）', icon='MESH_CIRCLE')

def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    self.layout.menu(VIEW3D_MT_edit_mesh_hotools.bl_idname)


cls = [
    OP_Align,
    OP_AlignRelative,
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
    OP_FillSelection,
    OP_AddSelectSideRingLoops,
    OP_RemoveSelectSideRingLoops,
    OP_VisualBooleanCut,
    OP_CurveBevel,
    OP_RepairCurvePath,
    HO_MT_curve,
    VIEW3D_MT_edit_mesh_hotools,
]
cls.extend(EDGE_FLOW_CLASSES)
cls.extend(HO_MESH_CLASSES)


addon_keymaps = []


def preference_keymaps():
    return addon_keymaps


def register():
    boolean.register()
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(
        draw_in_VIEW3D_MT_edit_mesh_context_menu
    )
    if hasattr(bpy.types, 'VIEW3D_MT_edit_curve_context_menu'):
        bpy.types.VIEW3D_MT_edit_curve_context_menu.append(
            draw_in_VIEW3D_MT_edit_curve_context_menu
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

        for keymap_name in ("Object Mode", "Pose"):
            keymap = keyconfig.keymaps.new(
                name=keymap_name,
                space_type='EMPTY',
                region_type='WINDOW',
            )
            keymap_item = keymap.keymap_items.new(
                OP_Align.bl_idname,
                type='A',
                value='PRESS',
                alt=True,
                head=True,
            )
            addon_keymaps.append((keymap, keymap_item))

        keymap = keyconfig.keymaps.new(
            name='Curve',
            space_type='EMPTY',
            region_type='WINDOW',
        )
        keymap_item = keymap.keymap_items.new(
            OP_Symmetrize.bl_idname,
            type='X',
            value='PRESS',
            alt=True,
            head=True,
        )
        keymap_item.properties.flick = True
        keymap_item.properties.objmode = False
        addon_keymaps.append((keymap, keymap_item))

        keymap_item = keymap.keymap_items.new(
            OP_CurveBevel.bl_idname,
            type='B',
            value='PRESS',
            ctrl=True,
            head=True,
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
    if hasattr(bpy.types, 'VIEW3D_MT_edit_curve_context_menu'):
        bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(
            draw_in_VIEW3D_MT_edit_curve_context_menu
        )
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
    boolean.unregister()
    ureg_props()
