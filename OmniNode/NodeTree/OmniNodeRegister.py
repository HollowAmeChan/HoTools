from . import FunctionNodeCore
import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem
from .OmniNodeTree import TREE_ID
from .Function import Data, Math,Operator, RigTooKit,Logic,DataTypeCast,Image,Modifier,Material,UV,VertexColor,VertexGroup,Debug,Cache,Physics
from .GraphNode import CLS_GRAPH

class OmniNodeCategory(NodeCategory):  # 定义一个节点集合类
    @classmethod
    def poll(cls, context):
        return True


cls = []
# Graph节点
node_cls_graph = []
node_cls_graph.extend(CLS_GRAPH)
cls.extend(node_cls_graph)
# Function生成节点
node_cls_data = FunctionNodeCore.loadRegisterFuncNodes(Data)
node_cls_math = FunctionNodeCore.loadRegisterFuncNodes(Math)
node_cls_operator = FunctionNodeCore.loadRegisterFuncNodes(Operator)
node_cls_modifier = FunctionNodeCore.loadRegisterFuncNodes(Modifier)
node_cls_material = FunctionNodeCore.loadRegisterFuncNodes(Material)
node_cls_uv = FunctionNodeCore.loadRegisterFuncNodes(UV)
node_cls_vertexcolor = FunctionNodeCore.loadRegisterFuncNodes(VertexColor)
node_cls_vertexgroup = FunctionNodeCore.loadRegisterFuncNodes(VertexGroup)
node_cls_rigtoolkit = FunctionNodeCore.loadRegisterFuncNodes(RigTooKit)
node_cls_logic = FunctionNodeCore.loadRegisterFuncNodes(Logic)
node_cls_datatypecast = FunctionNodeCore.loadRegisterFuncNodes(DataTypeCast)
node_cls_image = FunctionNodeCore.loadRegisterFuncNodes(Image)
node_cls_debug = FunctionNodeCore.loadRegisterFuncNodes(Debug)
node_cls_cache = FunctionNodeCore.loadRegisterFuncNodes(Cache)
node_cls_physics = FunctionNodeCore.loadRegisterFuncNodes(Physics)
cls.extend(node_cls_data)
cls.extend(node_cls_math)
cls.extend(node_cls_operator)
cls.extend(node_cls_modifier)
cls.extend(node_cls_material)
cls.extend(node_cls_uv)
cls.extend(node_cls_vertexcolor)
cls.extend(node_cls_vertexgroup)
cls.extend(node_cls_rigtoolkit)
cls.extend(node_cls_logic)
cls.extend(node_cls_datatypecast)
cls.extend(node_cls_image)
cls.extend(node_cls_debug)
cls.extend(node_cls_cache)
cls.extend(node_cls_physics)

node_categories = [
    OmniNodeCategory("GRAPH", "graph", items=[
        NodeItem(i.bl_idname) for i in node_cls_graph
    ]),
    OmniNodeCategory("DATA", "Data", items=[
        NodeItem(i.bl_idname) for i in node_cls_data
    ]),
    OmniNodeCategory("DATA_TYPECAST", "DataTypeCast", items=[
        NodeItem(i.bl_idname) for i in node_cls_datatypecast
    ]),
    OmniNodeCategory("MATH", "Math", items=[
        NodeItem(i.bl_idname) for i in node_cls_math
    ]),
    OmniNodeCategory("OPERATOR", "Operator", items=[
        NodeItem(i.bl_idname) for i in node_cls_operator
    ]),
    OmniNodeCategory("MODIFIER", "Modifier", items=[
        NodeItem(i.bl_idname) for i in node_cls_modifier
    ]),
    OmniNodeCategory("MATERIAL", "Material", items=[
        NodeItem(i.bl_idname) for i in node_cls_material
    ]),
    OmniNodeCategory("UV", "UV", items=[
        NodeItem(i.bl_idname) for i in node_cls_uv
    ]),
    OmniNodeCategory("VERTEXCOLOR", "VertexColor", items=[
        NodeItem(i.bl_idname) for i in node_cls_vertexcolor
    ]),
    OmniNodeCategory("VERTEXGROUP", "VertexGroup", items=[
        NodeItem(i.bl_idname) for i in node_cls_vertexgroup
    ]),
    OmniNodeCategory("IMAGE", "Image", items=[
        NodeItem(i.bl_idname) for i in node_cls_image
    ]),
    OmniNodeCategory("RIGTOOLKIT", "RigToolKit", items=[
        NodeItem(i.bl_idname) for i in node_cls_rigtoolkit
    ]),
    OmniNodeCategory("LOGIC", "Logic", items=[
        NodeItem(i.bl_idname) for i in node_cls_logic
    ]),
    OmniNodeCategory("DEBUG", "Debug", items=[
        NodeItem(i.bl_idname) for i in node_cls_debug
    ]),
    OmniNodeCategory("CACHE", "Cache", items=[
        NodeItem(i.bl_idname) for i in node_cls_cache
    ]),
    OmniNodeCategory("PHYSICS", "Physics", items=[
        NodeItem(i.bl_idname) for i in node_cls_physics
    ]),
]


def register():
    try:
        for i in cls:
            bpy.utils.register_class(i)
        nodeitems_utils.register_node_categories(TREE_ID, node_categories)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in cls:
            bpy.utils.unregister_class(i)
        nodeitems_utils.unregister_node_categories(TREE_ID)
    except Exception:
        print(__file__+" unregister failed!!!")
