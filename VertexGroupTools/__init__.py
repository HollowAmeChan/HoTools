import bpy
from bpy.types import Panel

from . import vertexGroupOperators


def reg_props():
    return 


def ureg_props():
   return 


cls = []


def register():
    vertexGroupOperators.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    vertexGroupOperators.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
