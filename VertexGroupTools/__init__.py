import bpy
from bpy.types import Panel

from . import vertexGroupOperators,advancedList


def reg_props():
    return 


def ureg_props():
   return 


cls = []


def register():
    advancedList.register()
    vertexGroupOperators.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    advancedList.unregister()
    vertexGroupOperators.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
