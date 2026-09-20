import bpy
from bpy.types import Panel

from . import vertexGroupOperators


def reg_props():
    return 


def ureg_props():
   return 


def preference_keymaps():
    """偏好设置里可编辑的默认快捷键项，与其它工具模块保持同一接口。"""
    return vertexGroupOperators.preference_keymaps()


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


__all__ = ["register", "unregister", "preference_keymaps"]
