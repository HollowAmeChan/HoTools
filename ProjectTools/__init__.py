"""Project and Blender-session tools."""

import bpy

from .application import OP_RestartBlender
# from .application import draw_in_TOPBAR_MT_editor_menus
from .visibility import OP_sync_render_visibility


def draw_in_OUTLINER_MT_context_menu(self, context):
    self.layout.operator(OP_sync_render_visibility.bl_idname, icon="RESTRICT_RENDER_OFF")

_CLASSES = (OP_RestartBlender, OP_sync_render_visibility)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.OUTLINER_MT_context_menu.append(draw_in_OUTLINER_MT_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.append(draw_in_TOPBAR_MT_editor_menus)


def unregister():
    try:
        bpy.types.OUTLINER_MT_context_menu.remove(draw_in_OUTLINER_MT_context_menu)
    except Exception:
        pass
    # try:
    #     bpy.types.TOPBAR_MT_editor_menus.remove(draw_in_TOPBAR_MT_editor_menus)
    # except Exception:
    #     pass
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


def preference_keymaps():
    return []


__all__ = ["register", "unregister", "preference_keymaps"]
