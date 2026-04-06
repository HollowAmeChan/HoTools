import bpy
from bpy.types import NodeTree, Node, NodeSocket, NodeLink
from .Base.DataPool import DataPool, poolNodeInfo
from .Base.OmniNode import OmniNode
import time

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

    def OmniInit(self):
        if not hasattr(self, "pool"):
            self.pool = DataPool(nodeTree=self)  # 新建数据池,全为空

    @staticmethod
    def ensure_tree_runtime(tree):
        if not hasattr(tree, "pool"):           tree.pool = DataPool(nodeTree=tree) 

    @classmethod
    def poll(self, context):
        return True

    def update(self):
        """原生回调,只有这一种原生回调__init__不在实例化时运行,只在注册时运行"""
        OmniNodeTree.ensure_tree_runtime(self)
        if hasattr(self, "OmniInit"):
            try:
                self.OmniInit()
            except Exception as e:
                print("OmniInit error:", e)

        if self.doing_initNode:  # 树状态-正在新建节点时不回调
            return
        if self.is_auto_update:  # 如果节点树自动更新，则运行整个节点树,只有运算的时候更新默认值
            print("树遍历运行:", self.name, "\t", time.ctime())
            self.run()
            # self.reportPool()

    def reportPool(self):
        print("==================", time.ctime(), "==================")
        pool: DataPool = self.pool
        for nodeinfo in pool:
            print(nodeinfo)

    def reBuildPool(self):
        self.pool = DataPool(nodeTree=self)  # 新建数据池,全为空

    def getRunLayer(self) -> tuple[set[NodeLink], set[OmniNode], list[list[OmniNode]], list[list[OmniNode | NodeLink]]]:
        """
        遍历节点图,分层输出相关信息
        outLinkSet:     涉及的link
        visitedNode:    涉及的节点
        outLayerList:   涉及的节点层
        outRunningList: 涉及的节点+link层 - 实际用来运行
        """
        nodes: list[OmniNode] = self.nodes
        tempLinkSet :set[NodeLink] = set()
        outLinkSet :set[NodeLink] = set()
        visitedNode :set[OmniNode] = set()

        # 搜索输出节点集合
        outNodeSet = set()
        for node in nodes:
            node.is_bug = False
            if node.is_output_node:
                outNodeSet.add(node)

        # dfs搜索出所有link
        def followLinks(node_in: OmniNode):
            for n_inputs in node_in.inputs:
                for node_links in n_inputs.links:
                    tempLinkSet.add(node_links)
                    outLinkSet.add(node_links)
                    followLinks(node_links.from_node)

        # 递归搜索所有输出节点的全部上游节点和link，存储
        outSet = set()
        for node in nodes[:]:
            if node.is_output_node:
                outSet.add(node)
                followLinks(node)

        # 分层输出运行节点
        outLayerList : list[list[OmniNode]] = []
        while len(tempLinkSet):
            parentSet = set()
            childrenSet = set()
            # 移除visited
            to_remove = set()
            for i in tempLinkSet:
                if i.from_node in visitedNode or i.to_node in visitedNode:
                    to_remove.add(i)
            tempLinkSet = tempLinkSet.difference(to_remove)

            for i in tempLinkSet:
                parentSet.add(i.from_node)
                childrenSet.add(i.to_node)
            layer = parentSet.difference(childrenSet)
            # 补充顶层
            if not layer:
                layer = outSet-visitedNode  # 防止重复运行 - 路线上有多个输出
            visitedNode = visitedNode.union(layer)
            outLayerList.append(list(layer))
        visitedNode.update(outNodeSet)  # 加入输出节点,防止输出节点被误判为孤立节点

        # 分层输出运行节点列表+link列表，直接用于顺序运行（已合批）
        outRunningList : list[list[OmniNode | NodeLink]] = []
        total = len(outLayerList)
        for time in range(total):
            thisLayer = outLayerList[time]
            if time == total-1:
                outRunningList.append(thisLayer)
                break
            nextLayer = outLayerList[time+1]

            outRunningList.append(thisLayer)
            linkLayer = []
            for node in thisLayer:
                for link in outLinkSet:
                    if link.from_node == node:
                        linkLayer.append(link)
            outRunningList.append(linkLayer)

        if len(outRunningList) == 0:
            outRunningList.append(list(outNodeSet))

        return outLinkSet, visitedNode, outLayerList, outRunningList

    def runRunLayer(self, outRunningList):
        pool : DataPool = self.pool
        for layer in outRunningList:
            layer: list[OmniNode | NodeLink]
            if layer == []:
                break
            if isinstance(layer[0], OmniNode):
                for node in layer:
                    for socket in node.inputs:# process前,如果还没有上游link输入数据就利用自身socket默认值填充pool输入，防止缺少输入导致错误
                        socket: NodeSocket
                        if not pool[node.name].inputs[socket.identifier]:
                            pool[node.name].inputs[socket.identifier] = socket.default_value

                    try:
                        errorlog = node.process()
                        # 如果 process() 返回异常对象，也捕获处理
                        if errorlog and isinstance(errorlog, Exception):
                            raise errorlog
                    except Exception as e:
                        node.is_bug = True
                        node.bug_text = e.__class__.__name__ + "\n" + str(e)
                        print(f"Error in node '{node.name}':", e)
                        break
            if isinstance(layer[0], NodeLink):
                link: NodeLink
                for link in layer:
                    from_node = link.from_node
                    to_node = link.to_node
                    from_socket = link.from_socket
                    to_socket = link.to_socket
                    # 这里直接查可能为空吗
                    pool_from_prop = pool[from_node.name].outputs[from_socket.identifier]
                    pool[to_node.name].inputs[to_socket.identifier] = pool_from_prop

    def debugRunLayer(self, linkSet, nodeSet, runningNodeLayer, runningLayer):
        """
        debug运行时报告运行的顺序
        """
        print("##########    REPORT    ##########")
        for i in runningNodeLayer:
            print([j.name for j in i], end="\t")
            print("")
        print("##########    LAYERS    ##########")
        for i in runningLayer:
            for j in i:
                if isinstance(j, NodeLink):
                    print(j.from_node.name, ":", j.from_socket.identifier,
                          "\t->\t",
                          j.to_node.name, ":", j.to_socket.identifier,)
                if isinstance(j, Node):
                    print(j.name, end="")
            print("")
        print("##########    LINKS     ##########")
        for i in linkSet:
            i: NodeLink
            print(i.from_node.name, ":", i.from_socket.identifier,
                  "\t->\t",
                  i.to_node.name, ":", i.to_socket.identifier,)
        print("##########    NODES     ##########")
        for i in nodeSet:
            print(i.name)
        print("##########   Pool Data  ##########")
        self.reportPool()
        print("##########     OVER     ##########")

    def run(self):
        linkSet = set()
        nodeSet = set()
        runningNodeLayer = []
        linkSet, nodeSet, runningNodeLayer, runningLayers = self.getRunLayer()
        self.debugRunLayer(linkSet, nodeSet, runningNodeLayer, runningLayers)
        pool = self.pool
        pool.clearPool()  # 重新把所有涉及到的节点创建标志符
        for node in nodeSet:
            pool.addNode(node)
        self.runRunLayer(runningLayers)


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
