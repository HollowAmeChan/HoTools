from .OmniNodeSocket import (
    OmniNodeSocketText,
    OmniNodeSocketScene,
    OmniNodeSocketAny,
    OmniNodeSocketCache,
    OmniNodeSocketFloatCurve,
    OmniNodeSocketColorCurve,
    OmniNodeSocketBone,
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
    """
    Runtime cache socket 标记类型。

    这个类只用于 @omni 函数签名标注，让 FunctionNodeCore 生成
    OmniNodeSocketCache。不要把它实例化成真实 cache 值。

    运行值契约：
    - 裸 Python 值就是 cache payload，Cache Write 默认按 replace 写入。
      这是 dict/list/array 这类快照式状态的常规路径。
    - 值也可以是 OmniRuntimeState.OmniCacheWriteIntent，由
      cache_replace(value) 或 cache_mutate(value) 创建。
    - cache_replace(value) 表示显式替换 cache owner。
    - cache_mutate(owner) 表示 committed owner 已被原地更新，并且必须仍然是
      当前 cache key 绑定的同一个对象。
    - 如果函数模块只想依赖这个 socket marker，也可以用 _OmniCache(value)
      构造 replace intent，用 _OmniCache.mutate(owner) 构造 mutate intent。
    - 资源 owner 可以提供 omni_cache_dispose(reason)，也可以提供可选的
      omni_cache_debug_snapshot()；runtime cache 按 duck typing 调用。
    """
    def __new__(cls, value=None):
        from .OmniRuntimeState import cache_replace

        return cache_replace(value)

    @staticmethod
    def replace(value):
        from .OmniRuntimeState import cache_replace

        return cache_replace(value)

    @staticmethod
    def mutate(owner):
        from .OmniRuntimeState import cache_mutate

        return cache_mutate(owner)
class _OmniBone():
    def __init__():
        return
class _OmniFloatCurve():
    def __init__():
        return
class _OmniColorCurve():
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
    _OmniFloatCurve: OmniNodeSocketFloatCurve,
    _OmniColorCurve: OmniNodeSocketColorCurve,
    _OmniBone: OmniNodeSocketBone,
}
