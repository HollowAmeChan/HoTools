from . import FunctionCore
import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem
from .NodeTree import TREE_ID
from .Function import Data, Math,Operator, RigTooKit


class OmniNodeCategory(NodeCategory):  # 定义一个节点集合类
    @classmethod
    def poll(cls, context):
        return True


cls = []
# Function生成节点
node_cls_data = FunctionCore.loadRegisterFuncNodes(Data)
node_cls_math = FunctionCore.loadRegisterFuncNodes(Math)
node_cls_operator = FunctionCore.loadRegisterFuncNodes(Operator)
node_cls_rigtoolkit = FunctionCore.loadRegisterFuncNodes(RigTooKit)
cls.extend(node_cls_data)
cls.extend(node_cls_math)
cls.extend(node_cls_operator)
cls.extend(node_cls_rigtoolkit)


node_categories = [
    OmniNodeCategory("DATA", "Data", items=[
        NodeItem(i.bl_idname) for i in node_cls_data
    ]),
    OmniNodeCategory("MATH", "Math", items=[
        NodeItem(i.bl_idname) for i in node_cls_math
    ]),
    OmniNodeCategory("OPERATOR", "Operator", items=[
        NodeItem(i.bl_idname) for i in node_cls_operator
    ]),
    OmniNodeCategory("RIGTOOLKIT", "RigToolKit", items=[
        NodeItem(i.bl_idname) for i in node_cls_rigtoolkit
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
