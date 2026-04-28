from .OmniNodeSocket import OmniNodeSocketText, OmniNodeSocketScene, OmniNodeSocketAny,OmniNodeSocketImageFormat,OmniNodeSocketRegex,OmniNodeSocketGlob
import bpy
import mathutils
import inspect
import types
import typing
from bpy.types import (
    NodeSocketFloat,
    NodeSocketVector,
    NodeSocketColor,
    NodeSocketBool,
    NodeSocketInt,
    NodeSocketString,
    NodeSocketObject,
    NodeSocketCollection,
    NodeSocketImage,
    NodeSocketMaterial,
    NodeSocketTexture,
    NodeSocketGeometry,
    NodeSocketMatrix,
)

NodeSocketStringFilePath = getattr(bpy.types, "NodeSocketStringFilePath", NodeSocketString)

class _OmniFolderPath(str):
    def __init__():
        return
class _OmniImageFormat(str):
    def __init__():
        return
class _OmniRegex(str):
    def __init__():
        return
class _OmniGlob(str):
    def __init__():
        return
class _OmniColorRGBA():
    def __init__():
        return

# 函数变量标签类型：blenderSocket类型
SKT_DIC = {
    # 签名中没写类型的全是_empty类
    inspect._empty: OmniNodeSocketAny,
    typing.Any: OmniNodeSocketAny,
    # blender类转化
    NodeSocketFloat: NodeSocketFloat,
    NodeSocketVector: NodeSocketVector,
    NodeSocketColor: NodeSocketColor,
    NodeSocketImage: NodeSocketImage,
    NodeSocketBool: NodeSocketBool,
    NodeSocketInt: NodeSocketInt,
    NodeSocketObject: NodeSocketObject,
    NodeSocketString: NodeSocketString,
    NodeSocketCollection: NodeSocketCollection,
    bpy.types.FloatProperty: NodeSocketFloat,
    bpy.types.BoolProperty: NodeSocketBool,
    bpy.types.StringProperty: NodeSocketString,
    bpy.types.IntProperty: NodeSocketInt,
    bpy.types.Object: NodeSocketObject,
    bpy.types.Mesh:NodeSocketGeometry,
    bpy.types.Image: NodeSocketImage,
    bpy.types.Collection: NodeSocketCollection,
    mathutils.Color: NodeSocketColor,
    _OmniColorRGBA: NodeSocketColor,
    bpy.types.Material: NodeSocketMaterial,
    bpy.types.Mesh: NodeSocketObject,
    bpy.types.Armature: NodeSocketObject,
    bpy.types.Texture: NodeSocketTexture,
    mathutils.Matrix: NodeSocketMatrix,
    mathutils.Vector:NodeSocketVector,
    _OmniFolderPath: NodeSocketStringFilePath,
    # python类到blender socket类
    float: NodeSocketFloat,
    str: NodeSocketString,
    bool: NodeSocketBool,
    int: NodeSocketInt,
    # Omni自定义接口
    bpy.types.Scene: OmniNodeSocketScene,
    bpy.types.Text: OmniNodeSocketText,
    _OmniImageFormat: OmniNodeSocketImageFormat,
    _OmniRegex: OmniNodeSocketRegex,
    _OmniGlob: OmniNodeSocketGlob,
}
