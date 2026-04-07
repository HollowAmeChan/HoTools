from typing import Any
from bpy.types import Node, NodeSocket, NodeTree
from .OmniNode import OmniNode
from ...lib.multimethod import multimethod  # 重载装饰器
import time


class poolNodeInfo:
    """
    查找值
    .inputs[socket.name]
    .outputs[socket.name]
    默认值都为None
    """
    inputs: dict
    outputs: dict
    nodename: str

    def __init__(self, node: OmniNode) -> None:
        skt: NodeSocket
        self.inputs = {}  # TODO:目前不支持下标索引，但是外面的info类可以，虽然实现了但是在bl环境就是弄不出来
        self.outputs = {}
        if not node:
            return
        self.nodename = node.name
        for skt in node.inputs:
            if skt.is_multi_input:
                self.inputs[skt.identifier] = []
            else:
                self.inputs[skt.identifier] = skt.default_value
        for skt in node.outputs:  # TODO:不应该更新,因为现在process直接传递到输出socket，但是这样完全不支持自定义属性
            self.outputs[skt.identifier] = skt.default_value

    def __str__(self) -> str:
        out = "---------------------------\n"
        out += "name:\t"+self.nodename+"\n"
        out += "inputs:\t\n"
        for key, value in self.inputs.items():
            out += f"\t{key}:\t {value}\n"
        out += "outputs:\t\n"
        for key, value in self.outputs.items():
            out += f"\t{key}:\t {value}\n"
        return out


class DataPool:
    """[node.name]查询node"""
    _pool: dict
    _tree: NodeTree

    def __init__(self, nodeTree: NodeTree) -> None:
        """初始化的pool为空,仅存所在树,如有需要使用addAllTreeNode添加所有节点到pool"""
        self._tree = nodeTree
        self._pool = {}

    def __str__(self) -> str:
        return str(self._pool)

    @multimethod
    def __getitem__(self, _: str) -> poolNodeInfo:  # 索引
        name = _
        nodeinfo = self._pool.get(name, None)
        return nodeinfo

    @multimethod
    def __getitem__(self, _: int) -> poolNodeInfo:  # 索引
        index = _
        t = 0
        if index >= len(self._pool):
            return None
        for key in self._pool:
            if index == t:
                nodeinfo = self._pool.get(key, None)
                return nodeinfo
            t += 1
        return None

    def __setitem__(self, key, value):  # 索引赋值 DataPool()[key] = value
        self._pool[key] = value

    def __iter__(self):  # for i in 迭代器
        return iter(self._pool.values())  # 返回指点的值而不是键
    
    def __len__(self):  # len(DataPool())
        return len(self._pool)

    def clearPool(self):
        self._pool.clear()

    def get(self, key: str, default=None) -> poolNodeInfo:
        """模仿字典的get"""
        try:
            value = self[key]
            return value
        except:
            return default

    def report(self):
        print("==================", time.ctime(), "==================")
        for nodeinfo in self:
            print(nodeinfo)

    def addNode(self, node):
        """向pool添加一个nodeinfo"""
        node: Node
        self._pool[node.name] = poolNodeInfo(node)
        return

    def addAllTreeNode(self, tree):
        """树的所有节点创建nodeinfo进入pool"""
        node: Node
        for node in tree.nodes:
            self[node.name] = poolNodeInfo(node)

    def delNode(self):
        return

    def getRunLayer(self):
        return

    def runRunLayer(self):
        return

    def Run(self):
        return
