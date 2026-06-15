from .OmniNodeSocket import (
    OmniNodeSocketText,
    OmniNodeSocketScene,
    OmniNodeSocketAny,
    OmniNodeSocketCache,
    OmniNodeSocketBone,
    OmniNodeSocketBoneChain,
    OmniNodeSocketImageFormat,
    OmniNodeSocketRegex,
    OmniNodeSocketGlob,
    OmniNodeSocketDatablock,
    OmniNodeSocketModifierType,
    OmniNodeSocketModifier,
    OmniNodeSocketMaterialSlot,
    OmniNodeSocketUVLayer,
    OmniNodeSocketColorAttribute,
    OmniNodeSocketVertexGroup,
    OmniNodeSocketShapeKey,
)
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
    # NodeSocketMatrix, #4.1不存在，高版本存在，等5.xLTS
)

NodeSocketStringFilePath = getattr(bpy.types, "NodeSocketStringFilePath", NodeSocketString)


def runtime_socket_type_id(socket_type: str) -> str:
    """
    用于版本兼容
    所有运行中使用socket type的地方都最好使用这个函数查找
    """
    if socket_type == "NodeSocketStringFilePath" and not hasattr(bpy.types, "NodeSocketStringFilePath"):
        return "NodeSocketString"
    return socket_type

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
class _OmniCache(str):
    def __init__():
        return
class _OmniBone():
    def __init__():
        return
class _OmniBoneChain():
    def __init__():
        return
class _OmniColorRGBA():
    def __init__():
        return
class _OmniDatablock():
    def __init__():
        return
class _OmniModifierType(str):
    def __init__():
        return
class _OmniModifier():
    def __init__():
        return
class _OmniMaterialSlot():
    def __init__():
        return
class _OmniUVLayer():
    def __init__():
        return
class _OmniColorAttribute():
    def __init__():
        return
class _OmniVertexGroup():
    def __init__():
        return
class _OmniShapeKey():
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
    # mathutils.Matrix: NodeSocketMatrix, #4.1不存在，高版本存在，等5.xLTS
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
    bpy.types.Modifier: OmniNodeSocketModifier,
    bpy.types.MaterialSlot: OmniNodeSocketMaterialSlot,
    bpy.types.MeshUVLoopLayer: OmniNodeSocketUVLayer,
    bpy.types.Attribute: OmniNodeSocketColorAttribute,
    bpy.types.VertexGroup: OmniNodeSocketVertexGroup,
    bpy.types.ShapeKey: OmniNodeSocketShapeKey,
    _OmniDatablock: OmniNodeSocketDatablock,
    _OmniModifier: OmniNodeSocketModifier,
    _OmniMaterialSlot: OmniNodeSocketMaterialSlot,
    _OmniUVLayer: OmniNodeSocketUVLayer,
    _OmniColorAttribute: OmniNodeSocketColorAttribute,
    _OmniVertexGroup: OmniNodeSocketVertexGroup,
    _OmniShapeKey: OmniNodeSocketShapeKey,
    _OmniModifierType: OmniNodeSocketModifierType,
    _OmniImageFormat: OmniNodeSocketImageFormat,
    _OmniRegex: OmniNodeSocketRegex,
    _OmniGlob: OmniNodeSocketGlob,
    _OmniCache: OmniNodeSocketCache,
    _OmniBone: OmniNodeSocketBone,
    _OmniBoneChain: OmniNodeSocketBoneChain,
}
