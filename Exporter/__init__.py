import bpy
from bpy.types import Panel

from . import FbxExporter,BoneConstraintExporter


def reg_props():
    return


def ureg_props():
    return




cls = []


def register():
    FbxExporter.register()
    BoneConstraintExporter.register()

    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    FbxExporter.unregister()
    BoneConstraintExporter.unregister()

    
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()