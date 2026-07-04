import bpy
from bpy.types import Panel

from . import FbxExporter, BoneCollectionExporter, AnimClipExport


def reg_props():
    return


def ureg_props():
    return


cls = []


def register():
    FbxExporter.register()
    BoneCollectionExporter.register()
    AnimClipExport.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    FbxExporter.unregister()
    BoneCollectionExporter.unregister()
    AnimClipExport.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
