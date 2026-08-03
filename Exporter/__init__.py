import bpy
from bpy.types import Panel

from . import AnimClipExport, BoneCollectionExporter, BoneConstraintExporter, FbxExporter


def reg_props():
    return


def ureg_props():
    return


cls = []


def register():
    FbxExporter.register()
    BoneConstraintExporter.register()
    BoneCollectionExporter.register()
    AnimClipExport.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    AnimClipExport.unregister()
    BoneCollectionExporter.unregister()
    BoneConstraintExporter.unregister()
    FbxExporter.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
