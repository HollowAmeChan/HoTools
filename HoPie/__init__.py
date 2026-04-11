import bpy
import bmesh
from bpy.types import Panel


def reg_props():
    return

def ureg_props():
    return


cls = []

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
