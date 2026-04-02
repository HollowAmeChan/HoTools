from . import FunctionCore
import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem
from .NodeTree import TREE_ID
from .Function import DynamicBoneRig, Base, Math
from .GlslNode import GlslNode


class OmniNodeCategory(NodeCategory):  # 定义一个节点集合类
    @classmethod
    def poll(cls, context):
        return True


cls = []
# Function生成节点
node_cls_math = FunctionCore.loadRegisterFuncNodes(Math)
node_cls_base = FunctionCore.loadRegisterFuncNodes(Base)
node_cls_DynamicBoneRig = FunctionCore.loadRegisterFuncNodes(DynamicBoneRig)
cls.extend(node_cls_math)
cls.extend(node_cls_base)
cls.extend(node_cls_DynamicBoneRig)
# GlslNode生成节点
cls.extend(GlslNode.cls)


node_categories = [
    OmniNodeCategory("MATH", "Math", items=[
        NodeItem(i.bl_idname) for i in node_cls_math
    ]),
    OmniNodeCategory("BASE", "Base", items=[
        NodeItem(i.bl_idname) for i in node_cls_base
    ]),
    OmniNodeCategory("DYNAMICBONERIG", "DynamicBoneRig", items=[
        NodeItem(i.bl_idname) for i in node_cls_DynamicBoneRig
    ]),
    OmniNodeCategory("GlSL_TESTNODE", "GLSL-testNode", items=[
        NodeItem(i.bl_idname) for i in GlslNode.cls
    ])
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
