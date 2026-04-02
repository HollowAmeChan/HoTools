import bpy
import mathutils
import inspect
import types
import typing
from .Base.OmniNode import OmniNode
from .NodeSocket import OmniNodeSocketText, OmniNodeSocketScene, OmniNodeSocketAny
from bpy.types import Node
from bpy.types import NodeSocketFloat, NodeSocketVector, NodeSocketColor, NodeSocketImage, NodeSocketBool, NodeSocketInt, NodeSocketObject, NodeSocketString, NodeSocketCollection


# 函数变量标签类型：blenderSocket类型
cls_dic = {
    # 签名中没写类型的全是_empty类
    inspect._empty: OmniNodeSocketAny,
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
    bpy.types.Image: NodeSocketImage,
    bpy.types.Collection: NodeSocketCollection,
    mathutils.Color: NodeSocketColor,
    # python类到blender socket类
    float: NodeSocketFloat,
    str: NodeSocketString,
    # Omni自定义接口
    bpy.types.Scene: OmniNodeSocketScene,
    typing.Any: OmniNodeSocketAny,
    bpy.types.Text: OmniNodeSocketText,

}


def meta(**metadata):
    '''
    META信息装饰器
    1.  对于输入参数可以传入一个字典，填入.inputs.new的参数
        a={"name":"111","type":"","identifier":"}
        目前只支持name修改,identifier不可修改
    2.  对于本身的一些设置,一般支持
        omni_description:str
        bl_label:str
        base_color:tuple[float,float,float]
        is_output_node:bool
        _OUTPUT_NAME:list[str]
    3.  由于使用了函数签名来生成，签名无法设置多输出的名字
        目前使用默认_OUTPUT+数字来生成identifier
        名称想要修改可以使用_OUTPUT_NAME这个列表,他将会顺序指定输出的名字
    '''
    def decorator(func):
        func.__meta = metadata
        return func
    return decorator

def resolve_output_types(annotation):
    # 无返回
    if annotation is inspect._empty or annotation is None:
        return []

    # Python 3.9+ tuple[]
    if isinstance(annotation, types.GenericAlias):
        return list(typing.get_args(annotation))

    # typing.Tuple / Union / Optional
    origin = typing.get_origin(annotation)
    if origin is tuple:
        return list(typing.get_args(annotation))

    if origin is typing.Union:
        # Optional[T] -> (T, NoneType)
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return args if args else [OmniNodeSocketAny]

    # 单返回
    return [annotation]

def get_socket_type_name(socket_cls):
    # 自定义 socket（有 bl_idname）
    if hasattr(socket_cls, "bl_idname"):
        return socket_cls.bl_idname

    # Blender 内置 socket（用类名）（没有 bl_idname）
    return socket_cls.__name__

def CheckMetaInfo(func) -> tuple[dict, dict[dict], dict[dict]]:
    NodeInfo = {}
    SocketInMetaDict = {}
    SocketOutMetaDict = {}

    # 节点属性信息生成与覆盖
    NodeInfo["bl_label"] = func.__name__
    NodeInfo["bl_idname"] = "HO_OmniNode_" + func.__name__
    NodeInfo["is_output_node"] = False
    NodeInfo["base_color"] = (0.5, 0.5, 0)
    NodeInfo["omni_description"] = ""
    NodeInfo["_OUTPUT_NAME"] = ["输出"]
    NodeInfo.update(func.__meta)

    # 节点输入输出接口信息
    signature = inspect.signature(func)
    params = signature.parameters
    outputs = signature.return_annotation

    # 解算输入输出信息
    # 内容类型inspect.Parameter，名字是.name，类型是.annotation
    inputParamsPair: list[inspect.Parameter] = []
    outputParamsType: list[type] = []

    inputParamsPair = list(params.values())
    outputParamsType = resolve_output_types(outputs)

    #   #没有meta的默认input信息
    if len(inputParamsPair) != 0:
        index = 0
        for i in inputParamsPair:
            identifier = i.name
            dic = {
                "type": get_socket_type_name(cls_dic.get(i.annotation, OmniNodeSocketAny)),
                "name": i.name,
                "identifier": identifier
            }
            SocketInMetaDict[identifier] = dic
            index += 1
        if hasattr(func, "__meta"):
            for i in SocketInMetaDict.keys():
                if i in func.__meta:
                    SocketInMetaDict[i].update(func.__meta[i])
    #   #没有meta的默认output信息
    if len(outputParamsType) != 0:
        index = 0
        for i in outputParamsType:
            try:
                name = NodeInfo["_OUTPUT_NAME"][index]
            except:
                name = "输出"
            identifier = "_OUTPUT"+str(index)
            dic = {
                "type": get_socket_type_name(cls_dic.get(i, OmniNodeSocketAny)),
                "name": name,
                "identifier": identifier
            }
            SocketOutMetaDict[identifier] = dic
            index += 1
        if hasattr(func, "__meta"):
            for i in SocketOutMetaDict.keys():
                if i in func.__meta:
                    SocketOutMetaDict[i].update(func.__meta[i])

    return NodeInfo, SocketInMetaDict, SocketOutMetaDict


def PutInitMetaInfo(node: OmniNode, NodeInfo, SocketInMetaDict, SocketOutMetaDict):
    node.base_color = NodeInfo.get("base_color")
    node.updateColor()
    node.is_output_node = NodeInfo.get("is_output_node")
    node.omni_description = NodeInfo.get("omni_description")
    # 生成输入
    for i in SocketInMetaDict.keys():
        node.inputs.new(**SocketInMetaDict[i])
    # 生成输出
    for i in SocketOutMetaDict.keys():
        node.outputs.new(**SocketOutMetaDict[i])
    return


def CreateNodeClass(func) -> OmniNode:
    NodeInfo, SocketInMetaDict, SocketOutMetaDict = CheckMetaInfo(func)

    class OmniNodeClassInstance(OmniNode, Node):
        bl_label = NodeInfo.get("bl_label")
        bl_idname = NodeInfo.get("bl_idname")

        def init(self, context):
            super().init(context)
            PutInitMetaInfo(self, NodeInfo, SocketInMetaDict,
                            SocketOutMetaDict)

            self["fatherTree"].doing_initNode = False  # 更新树状态-新建节点结束

        def process(self):
            super().process()
            self.processUsingPool(func)  # 程序化节点特有的调用

    OmniNodeClassInstance.__name__ = "HO_OmniProgramCreateNode_"+func.__name__
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
