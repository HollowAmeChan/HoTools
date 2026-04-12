import bpy
import mathutils
import inspect
import types
import typing
from .OmniNode import OmniNode
from .OmniNodeSocket import OmniNodeSocketText, OmniNodeSocketScene, OmniNodeSocketAny,OmniNodeSocketImageFormat,OmniNodeSocketRegex,OmniNodeSocketGlob
from bpy.types import Node
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
    NodeSocketStringFilePath,
)

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

# 函数变量标签类型：blenderSocket类型
cls_dic = {
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
    bpy.types.Material: NodeSocketMaterial,
    bpy.types.Mesh: NodeSocketObject,
    bpy.types.Armature: NodeSocketObject,
    bpy.types.Texture: NodeSocketTexture,
    mathutils.Matrix: NodeSocketMatrix,
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




def omni(**omnidata):
    '''
    OMNI信息装饰器
    1.  可以配置的META信息包括:
        omni_description:str
        bl_label:str
        base_color:tuple[float,float,float]
        is_output_node:bool
        _INPUT_NAME:list[str]
        _OUTPUT_NAME:list[str]
        等
    2.  由于使用了函数签名来生成，签名无法设置多输出的名字
        目前使用默认_OUTPUT+数字来生成identifier
        名称想要修改可以使用_OUTPUT_NAME这个列表,他将会顺序指定输出的名字
    '''
    def decorator(func):
        func.__meta = omnidata
        return func
    return decorator

def resolve_socket(annotation):
    """统一解析 socket 类型 + multi 状态"""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    is_multi = origin in (list, typing.List)

    if is_multi and args:
        inner_type = args[0]
    else:
        inner_type = annotation

    socket_cls = cls_dic.get(inner_type, OmniNodeSocketAny)

    return socket_cls, is_multi

def get_socket_type_name(socket_cls):
    # 自定义 socket（有 bl_idname）
    if hasattr(socket_cls, "bl_idname"):
        return socket_cls.bl_idname

    # Blender 内置 socket（用类名）（没有 bl_idname）
    return socket_cls.__name__

def CheckMetaInfo(func) -> tuple[dict, dict[dict], dict[dict], dict[dict], dict[dict]]:
    NodeInfo = {}
    SocketInMetaDict = {}
    SocketOutMetaDict = {}
    SocketDefaultDict = {}
    SocketIsMulti = {}

    # -------------------------
    # Node info
    # -------------------------
    NodeInfo["bl_label"] = func.__name__
    NodeInfo["bl_idname"] = "HO_OmniNode_" + func.__name__
    NodeInfo["is_output_node"] = False
    NodeInfo["base_color"] = (0.5, 0.5, 0)
    NodeInfo["omni_description"] = ""
    NodeInfo["_INPUT_NAME"] = []
    NodeInfo["_OUTPUT_NAME"] = ["输出"]
    NodeInfo.update(func.__meta)

    # -------------------------
    # Signature
    # -------------------------
    signature = inspect.signature(func)
    params = signature.parameters
    outputs = signature.return_annotation

    inputParamsPair = list(params.values())
    outputParamsType = resolve_socket(outputs)

    # -------------------------
    # Inputs
    # -------------------------
    for index, param in enumerate(inputParamsPair):
        identifier = param.name

        default_value = None if param.default is inspect._empty else param.default
        SocketDefaultDict[identifier] = default_value

        name = (
            NodeInfo["_INPUT_NAME"][index]
            if index < len(NodeInfo["_INPUT_NAME"])
            else identifier
        )

        socket_cls, is_multi = resolve_socket(param.annotation)

        SocketIsMulti[identifier] = is_multi

        SocketInMetaDict[identifier] = {
            "type": get_socket_type_name(socket_cls),
            "name": name,
            "identifier": identifier,
            "use_multi_input": is_multi,
        }

    # -------------------------
    # Outputs
    # -------------------------
    origin = typing.get_origin(outputs)
    if origin in (tuple, typing.Tuple):
        outputParamsType = typing.get_args(outputs)
    else:
        outputParamsType = [outputs]

    for index, annotation in enumerate(outputParamsType):
        identifier = "_OUTPUT" + str(index)

        name = (
            NodeInfo["_OUTPUT_NAME"][index]
            if index < len(NodeInfo["_OUTPUT_NAME"])
            else "输出"
        )

        socket_cls, is_multi = resolve_socket(annotation)

        SocketIsMulti[identifier] = is_multi

        SocketOutMetaDict[identifier] = {
            "type": get_socket_type_name(socket_cls),
            "name": name,
            "identifier": identifier,
        }
    return (
        NodeInfo,
        SocketInMetaDict,
        SocketOutMetaDict,
        SocketDefaultDict,
        SocketIsMulti,
    )

def PutInitMetaInfo(node: OmniNode, NodeInfo, SocketInMetaDict, SocketOutMetaDict,SocketDefaultDict,SocketIsMulti):
    import json
    if NodeInfo.get("base_color"):
        node.base_color = NodeInfo.get("base_color")
    node.updateColor()
    node.is_output_node = NodeInfo.get("is_output_node")
    node.omni_description = NodeInfo.get("omni_description")
    # node.color_tag= NodeInfo.get("color_tag", "NONE")#blender的节点颜色标签，TODO:4.5暂时不能用，但是5.0以上已经修了
    node.bl_icon = NodeInfo.get("bl_icon", "NONE")#blender的节点图标

    # 生成输入
    for i in SocketInMetaDict.keys():
        sock = node.inputs.new(**SocketInMetaDict[i])

        default_value = SocketDefaultDict.get(i, None)
        if default_value is not None:
            try:
                sock.default_value = default_value
            except:
                pass
        if SocketIsMulti.get(i, False):
            sock.display_shape = "SQUARE"

    # 生成输出
    for i in SocketOutMetaDict.keys():
        sock = node.outputs.new(**SocketOutMetaDict[i])
        if SocketIsMulti.get(i, False):
            sock.display_shape = "SQUARE"
    return


def CreateNodeClass(func) -> OmniNode:
    NodeInfo, SocketInMetaDict, SocketOutMetaDict,SocketDefaultDict,SocketIsMulti = CheckMetaInfo(func)

    class OmniNodeClassInstance(OmniNode, Node):
        bl_label = NodeInfo.get("bl_label")
        bl_idname = NodeInfo.get("bl_idname")
        __name__ = "HO_OmniProgramCreateNode_"+func.__name__
        _SocketInMetaDict = SocketInMetaDict
        _SocketOutMetaDict = SocketOutMetaDict
        _SocketDefaultDict = SocketDefaultDict
        _SocketIsMultiDict = SocketIsMulti

        def init(self, context):
            super().init(context)
            PutInitMetaInfo(self, NodeInfo, SocketInMetaDict,
                            SocketOutMetaDict, SocketDefaultDict, SocketIsMulti)

            self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

        def process(self):
            super().process()
            return self.processUsingPool(func)  # 程序化节点特有的调用，返回可能的错误
        
    return OmniNodeClassInstance


def loadRegisterFuncNodes(func_module) -> list[Node]:
    cls = []
    for func_str in dir(func_module):
        func = getattr(func_module, func_str)

        if not callable(func):
            continue  # 跳过不可调用
        if not hasattr(func, "__meta"):
            continue  # 跳过没有meta信息的函数
        if not func.__meta.get("enable"):
            continue  # 只编译手动启用的函数（防止加载import包/库）
        cls.append(CreateNodeClass(func))
    return cls
