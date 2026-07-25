"""HoAux registration and panel boundary."""

import bpy

from . import module_base, operations, panel, preview, properties


_CLASSES = properties.CLASSES + operations.CLASSES + panel.CLASSES


def draw_panel(layout, context):
    panel.draw_panel(layout, context)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    properties.register_rna()
    module_base.register_rna()


def unregister():
    preview.shutdown()
    module_base.unregister_rna()
    properties.unregister_rna()
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
