import bpy
from bpy.types import Panel

from . import BoneCollectionExporter, FbxExporter, StlExporter


def reg_props():
    return


def ureg_props():
    return


cls = []


def register():
    FbxExporter.register()
    StlExporter.register()
    BoneCollectionExporter.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    BoneCollectionExporter.unregister()
    StlExporter.unregister()
    FbxExporter.unregister()

    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
