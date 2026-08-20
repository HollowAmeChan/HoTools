"""Object-level HoTools operators and menus."""

import bpy

from .lattice import HO_MT_HoObjectTools, HO_OT_QuickAddLattice
from .image_reference import OP_MeshToImageEmpty
from .align import OP_Align, OP_AlignRelative
from .placement import (
    OP_AutoPlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_PlaceObjectBottom,
    OP_SnapSelectedFaceOrthogonal,
)


def draw_in_VIEW3D_MT_object_convert(self, context):
    self.layout.operator(OP_MeshToImageEmpty.bl_idname)


def draw_in_VIEW3D_MT_object_context_menu(self, context):
    if getattr(context, "mode", None) == "OBJECT":
        self.layout.menu(
            HO_MT_HoObjectTools.bl_idname,
            text=HO_MT_HoObjectTools.bl_label,
        )

_CLASSES = (
    OP_Align,
    OP_AlignRelative,
    OP_AutoPlaceObjectBottom,
    OP_AutoSnapFaceOrthogonal,
    OP_PlaceObjectBottom,
    OP_SnapSelectedFaceOrthogonal,
    OP_MeshToImageEmpty,
    HO_OT_QuickAddLattice,
    HO_MT_HoObjectTools,
)

addon_keymaps = []


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_object_convert.append(draw_in_VIEW3D_MT_object_convert)
    bpy.types.VIEW3D_MT_object_context_menu.prepend(
        draw_in_VIEW3D_MT_object_context_menu
    )
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        for keymap_name in ("Object Mode", "Pose"):
            keymap = keyconfig.keymaps.new(
                name=keymap_name, space_type="EMPTY", region_type="WINDOW"
            )
            item = keymap.keymap_items.new(
                OP_Align.bl_idname, type="A", value="PRESS", alt=True, head=True
            )
            addon_keymaps.append((keymap, item))


def unregister():
    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()
    try:
        bpy.types.VIEW3D_MT_object_context_menu.remove(
            draw_in_VIEW3D_MT_object_context_menu
        )
    except Exception:
        pass
    try:
        bpy.types.VIEW3D_MT_object_convert.remove(draw_in_VIEW3D_MT_object_convert)
    except Exception:
        pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


def preference_keymaps():
    return addon_keymaps


__all__ = ["register", "unregister", "preference_keymaps"]
