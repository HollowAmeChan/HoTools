"""Curve-focused public API."""

import bpy

from .bevel import OP_CurveBevel
from .repair import (
    HO_MT_curve,
    OP_RepairCurvePath,
    draw_in_VIEW3D_MT_edit_curve_context_menu,
)
from .symmetrize import OP_Symmetrize

_CLASSES = (OP_CurveBevel, OP_RepairCurvePath, HO_MT_curve, OP_Symmetrize)
addon_keymaps = []


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    if hasattr(bpy.types, "VIEW3D_MT_edit_curve_context_menu"):
        bpy.types.VIEW3D_MT_edit_curve_context_menu.append(
            draw_in_VIEW3D_MT_edit_curve_context_menu
        )
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(
            name="Curve", space_type="EMPTY", region_type="WINDOW"
        )
        symmetrize_item = keymap.keymap_items.new(
            OP_Symmetrize.bl_idname, type="X", value="PRESS", alt=True, head=True
        )
        symmetrize_item.properties.flick = True
        addon_keymaps.append((keymap, symmetrize_item))
        item = keymap.keymap_items.new(
            OP_CurveBevel.bl_idname, type="B", value="PRESS", ctrl=True, head=True
        )
        addon_keymaps.append((keymap, item))


def unregister():
    for keymap, item in addon_keymaps:
        keymap.keymap_items.remove(item)
    addon_keymaps.clear()
    if hasattr(bpy.types, "VIEW3D_MT_edit_curve_context_menu"):
        bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(
            draw_in_VIEW3D_MT_edit_curve_context_menu
        )
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


def preference_keymaps():
    return addon_keymaps


__all__ = [
    "OP_CurveBevel",
    "HO_MT_curve",
    "OP_RepairCurvePath",
    "OP_Symmetrize",
    "register",
    "unregister",
    "preference_keymaps",
]
