# 本文件为functionnode以外的拓展类型node，用于实现高级功能
import bpy
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd
from bpy.props import CollectionProperty,IntProperty

from .OmniNodeTree import OmniNodeTree
from .OmniNodeOperator import OmniGraphNodeIOItem_update

def OmniTreeFilter(self, tree):
    return isinstance(tree, OmniNodeTree)

def cache_node_links(node):
    """缓存某个 node 所有 links"""
    node_tree = node.id_data
    cache = []

    for link in node_tree.links:
        if link.from_node == node or link.to_node == node:
            cache.append({
                "from_node": link.from_node,
                "from_sock": link.from_socket.identifier,
                "to_node": link.to_node,
                "to_sock": link.to_socket.identifier,
            })
            # to_sock.identifier在这里绝对不会重名，因为生成时就做了处理
    return cache

def restore_node_links(node, cache):
    """根据 identifier 重建 links"""
    tree = node.id_data

    def find_socket(n, identifier, is_output):
        sockets = n.outputs if is_output else n.inputs
        for s in sockets:
            if getattr(s, "identifier", None) == identifier:
                return s
        return None

    for item in cache:
        from_node = item["from_node"]
        to_node = item["to_node"]

        from_sock = find_socket(from_node, item["from_sock"], True)
        to_sock = find_socket(to_node, item["to_sock"], False)

        if from_sock and to_sock:
            try:
                tree.links.new(from_sock, to_sock)
            except RuntimeError:
                pass  # 已存在或非法连接

class OmniGroupNode(OmniNode):
    # 参考Sverchok得知使用原生的逻辑会非常困难，因此放弃原生逻辑
    # https://blender.stackexchange.com/questions/58614/custom-nodetree-and-nodecustomgroup-and-bpy-ops-node-tree-path-parent
    bl_idname = "HO_OmniNode_GroupNode"
    bl_label = "组引用"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=OmniGraphNodeIOItem_update,
        poll=OmniTreeFilter,
    ) # type: ignore

    def build(self):
        self.syncGroupIO()
        self._socket_is_multi = None
        pass

    @staticmethod
    def _func(*arg):
        pass

    def syncGroupIO(self):
        tree = self.target_tree
        if not tree:return

        link_cache = cache_node_links(self)
        self.inputs.clear()
        self.outputs.clear()

        # Group 输入 → 当前 node.inputs
        for io in tree.group_inputs:
            sock = self.inputs.new(type=io.socket_type, name=io.name,identifier=io.uid)
            sock.hide_value = True
        # Group 输出 → 当前 node.outputs
        for io in tree.group_outputs:
            sock = self.outputs.new(type=io.socket_type, name=io.name,identifier=io.uid)
            sock.hide_value = True

        restore_node_links(self, link_cache)

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")
        layout.template_ID(self, "target_tree")
        return

class OmniGroupNodeInputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Inputs"
    bl_label = "组输入"

    active_index: IntProperty(default=0) # type: ignore

    def build(self):
        self.syncGroupIO()
        self._socket_is_multi = None
        pass
    
    @staticmethod
    def _func(*arg):
        pass

    def syncGroupIO(self):
        tree = self.id_data
        link_cache = cache_node_links(self)
        self.outputs.clear()
        for io in tree.group_inputs:
            sock = self.outputs.new(type=io.socket_type,name=io.name,identifier=io.uid)
            sock.hide_value = True
        restore_node_links(self, link_cache)

    def draw_buttons(self, context, layout):
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")
        tree = self.id_data

        row = layout.row()
        row.template_list(
            HO_UL_GraphNodeIO.__name__,
            "",
            tree,
            "group_inputs",
            tree,
            "group_inputs_index",
            rows=3
        )

        col = row.column(align=True)

        add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
        add.is_input = True

        remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
        remove.is_input = True
    
class OmniGroupNodeOutputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Outputs"
    bl_label = "组输出"

    output_IO: CollectionProperty(type=OmniGraphNodeIOItem)# type: ignore
    active_index: IntProperty(default=0) # type: ignore
    
    def build(self):
        self.syncGroupIO()
        self._socket_is_multi = None
        self.is_output_node = True #特别注意
        pass

    @staticmethod
    def _func(*arg):
        pass

    def syncGroupIO(self):
        tree = self.id_data
        link_cache = cache_node_links(self)
        self.inputs.clear()

        for io in tree.group_outputs:
            sock = self.inputs.new(type=io.socket_type,name=io.name,identifier=io.uid)
            sock.hide_value = True
        restore_node_links(self, link_cache)
    
    def draw_buttons(self, context, layout):
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")
        tree = self.id_data

        row = layout.row()
        row.template_list(
            HO_UL_GraphNodeIO.__name__,
            "",
            tree,
            "group_outputs",
            tree,
            "group_outputs_index",
            rows=3
        )

        col = row.column(align=True)

        add = col.operator(OP_IOItemAdd.bl_idname, icon="ADD", text="")
        add.is_input = False

        remove = col.operator(OP_IOItemRemove.bl_idname, icon="REMOVE", text="")
        remove.is_input = False
    
class OmniGroupNodeRepeat(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Repeat"
    bl_label = "组重复"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=OmniGraphNodeIOItem_update,
        poll=OmniTreeFilter,
    ) # type: ignore

    def build(self):
        self.syncGroupIO()
        self._socket_is_multi = None
        pass

    @staticmethod
    def _func(*arg):
        pass

    def syncGroupIO(self):
        tree = self.target_tree
        if not tree:return

        link_cache = cache_node_links(self)
        self.inputs.clear()
        self.outputs.clear()

        # Group 输入 → 当前 node.inputs
        for io in tree.group_inputs:
            sock = self.inputs.new(type=io.socket_type, name=io.name,identifier=io.uid)
            sock.hide_value = True
        # Group 输出 → 当前 node.outputs
        for io in tree.group_outputs:
            sock = self.outputs.new(type=io.socket_type, name=io.name,identifier=io.uid)
            sock.hide_value = True
        restore_node_links(self, link_cache)

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        # 顶掉父级的绘制
        if self.is_bug:
            layout.label(text=f"{self.bug_text}")
        layout.template_ID(self, "target_tree")
        return

CLS_GRAPH = [OmniGroupNode,OmniGroupNodeInputs,OmniGroupNodeOutputs,OmniGroupNodeRepeat]