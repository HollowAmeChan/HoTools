import bpy
import bmesh
from bpy.types import Panel

from  . import baker,operators

def reg_props():
    return

def ureg_props():
    return


cls = []



def register():
    baker.register()
    operators.register()
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    baker.unregister()
    operators.unregister()
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
