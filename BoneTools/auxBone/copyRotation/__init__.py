"""copyR: explicitly authored rotation following on existing owner bones."""

import bpy

from .core import CopyRotationCore
from .operations import OP_CopyRGenerate, OP_CopyRRemove
from .panel import draw_panel
from .properties import PG_Hotools_CopyRSettings

CLASSES = (PG_Hotools_CopyRSettings, OP_CopyRGenerate, OP_CopyRRemove)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_copyr_settings = bpy.props.PointerProperty(type=PG_Hotools_CopyRSettings)


def unregister():
    if hasattr(bpy.types.Scene, "ho_copyr_settings"):
        del bpy.types.Scene.ho_copyr_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


__all__ = ["CopyRotationCore", "register", "unregister", "draw_panel"]
