import bpy
from bpy.types import NodeTree, Node, NodeSocket, NodeLink
from .OmniNode import OmniNode
from .OmniCompiler import OmniCompiler
from .OmniExecutor import OmniExecutor
import time
import traceback

TREE_ID = 'OMNINODE'  # 节点树系统注册进去的identifier
TREE_ID_NAME = 'OmniNodeTree'  # 节点树系统的标识符idname


class OmniNodeTree(NodeTree):  # 节点树
    bl_idname = TREE_ID_NAME
    bl_label = "Omni节点图"  # 界面显示名
    bl_icon = 'DRIVER'

    is_auto_update: bpy.props.BoolProperty(
        description="是否实时刷新", default=False)  # type: ignore
    doing_initNode: bpy.props.BoolProperty(
        description="阻止新建节点频繁回调", default=False)  # type: ignore

    @classmethod
    def poll(self, context):
        return True

    def update(self):
        """原生回调,只有这一种原生回调__init__不在实例化时运行,只在注册时运行"""
        if self.doing_initNode:  # 树状态-正在新建节点时不回调
            return
        if self.is_auto_update:  # 如果节点树自动更新，则运行整个节点树,只有运算的时候更新默认值
            print("树自动运行:", self.name, "\t", time.ctime())
            self.run()

    @staticmethod
    def isMultiSocket(node: OmniNode, socket: NodeSocket):
        if socket.identifier in getattr(node, "_SocketIsMultiDict", {}):
            return node._SocketIsMultiDict.get(socket.identifier, False)
        return False 
    @staticmethod
    def normalize_socket_value(v):
        """消除单值和多值的差异，统一输出列表"""
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]

    def run(self):
        for node in self.nodes:
            node.is_bug = False
            node.property_unset("bug_text")  # 清空bug 
        compiled = OmniCompiler.compile(self)
        print(compiled.node_order)# TODO:比较简陋的debug
        OmniExecutor.run(compiled)

cls = [OmniNodeTree]


def register():
    try:
        for i in cls:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in cls:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__+" unregister failed!!!")
