# 本文件为functionnode以外的拓展类型node，用于实现高级功能

# TODO:目前的IO节点不支持自动变换type（以及socket.name）,导致非常难以使用。但是为了这个功能需要写巨量多的代码得不偿失
# TODO:缺少编译分支节点（未来再支持）
import bpy
from typing import Any
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd,OP_IOItemMove,OP_JumpToNodeTree
from bpy.props import CollectionProperty,IntProperty
from . import OmniMenuBind

from .OmniNodeTree import OmniNodeTree,draw_OmniTreeInputs,draw_OmniTreeOutputs
from .OmniNodeOperator import OmniGraphNodeIOItem_update
from .OmniNodeSocketMapping import runtime_socket_type_id

def OmniTreeFilter(self: Any, tree: Any) -> bool:
    return isinstance(tree, OmniNodeTree)


def draw_tree_ref_selector(layout: bpy.types.UILayout, node: bpy.types.Node, prop_name: str) -> None:
    row = layout.row(align=True)
    jump = row.row(align=True)
    jump.enabled = getattr(node, prop_name, None) is not None
    op = jump.operator(OP_JumpToNodeTree.bl_idname, text="", icon="FORWARD")
    op.node_name = node.name
    op.tree_attr = prop_name
    row.template_ID(node, prop_name)

def cache_node_links(node: OmniNode) -> list[dict[str, Any]]:
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

def restore_node_links(node: OmniNode, cache: list[dict[str, Any]]) -> None:
    """根据 identifier 重建 links"""
    tree = node.id_data

    def find_socket(n: bpy.types.Node, identifier: str, is_output: bool) -> bpy.types.NodeSocket | None:
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

def cache_nodesockets_defaultvalues(node: OmniNode) -> list[dict[str, Any]]:
    def snapshot_default_value(value: Any) -> Any:
        if isinstance(value, (str, bool, int, float)) or value is None:
            return value

        try:
            return tuple(value)
        except Exception:
            pass

        try:
            return value.copy()
        except Exception:
            return value

    cache: list[dict[str, Any]] = []

    for is_output, sockets in ((False, node.inputs), (True, node.outputs)):
        for sock in sockets:
            try:
                cache.append({
                    "identifier": sock.identifier,
                    "is_output": is_output,
                    "value": snapshot_default_value(sock.default_value),
                })
            except Exception:
                pass

    return cache

def restore_nodesockets_defaultvalues(node: OmniNode, cache: list[dict[str, Any]]) -> None:
    def restore_default_value(sock: bpy.types.NodeSocket, cache_entry: dict[str, Any]) -> None:
        value = cache_entry["value"]

        try:
            current_value = sock.default_value
        except Exception:
            return

        if isinstance(current_value, (str, bool, int, float)) or current_value is None:
            sock.default_value = value
            return

        try:
            current_len = len(current_value)
            value_len = len(value)
        except Exception:
            sock.default_value = value
            return

        if current_len != value_len:
            return

        sock.default_value = value

    for item in cache:
        sockets = node.outputs if item["is_output"] else node.inputs
        sock = sockets.get(item["identifier"])
        if not sock:
            continue

        try:
            restore_default_value(sock, item)
        except Exception:
            pass

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

    def build(self) -> None:
        self.syncGroupIO()
        self._socket_is_multi = None
        pass

    def syncGroupIO(self) -> None:
        tree = self.target_tree
        if not tree:return

        link_cache = cache_node_links(self)
        default_values = cache_nodesockets_defaultvalues(self)
        self.inputs.clear()
        self.outputs.clear()

        # Group 输入 → 当前 node.inputs
        for io in tree.group_inputs:
            sock = self.inputs.new(type=runtime_socket_type_id(io.socket_type), name=io.name,identifier=io.uid)
            # sock.hide_value = True
        # Group 输出 → 当前 node.outputs
        for io in tree.group_outputs:
            sock = self.outputs.new(type=runtime_socket_type_id(io.socket_type), name=io.name,identifier=io.uid)
            sock.hide_value = True

        restore_node_links(self, link_cache)
        restore_nodesockets_defaultvalues(self,default_values)

    def draw_buttons(self, context, layout: bpy.types.UILayout):
        draw_tree_ref_selector(layout, self, "target_tree")
        return

class OmniGroupNodeInputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Inputs"
    bl_label = "组输入"

    active_index: IntProperty(default=0) # type: ignore

    def build(self) -> None:
        self.syncGroupIO()
        self._socket_is_multi = None
        pass

    def syncGroupIO(self) -> None:
        tree = self.id_data
        link_cache = cache_node_links(self)
        self.outputs.clear()
        for io in tree.group_inputs:
            sock = self.outputs.new(type=runtime_socket_type_id(io.socket_type),name=io.name,identifier=io.uid)
            sock.hide_value = True
        restore_node_links(self, link_cache)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        draw_OmniTreeInputs(layout, self.id_data)
    
class OmniGroupNodeOutputs(OmniNode):
    bl_idname = "HO_OmniNode_GroupNode_Outputs"
    bl_label = "组输出"

    output_IO: CollectionProperty(type=OmniGraphNodeIOItem)# type: ignore
    active_index: IntProperty(default=0) # type: ignore
    
    def build(self) -> None:
        self.syncGroupIO()
        self._socket_is_multi = None
        self.is_output_node = True #特别注意
        pass

    def syncGroupIO(self) -> None:
        tree = self.id_data
        link_cache = cache_node_links(self)
        self.inputs.clear()

        for io in tree.group_outputs:
            sock = self.inputs.new(type=runtime_socket_type_id(io.socket_type),name=io.name,identifier=io.uid)
            sock.hide_value = True
        restore_node_links(self, link_cache)
    
    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        draw_OmniTreeOutputs(layout, self.id_data)


class OmniBindNode(OmniNode):
    bl_idname = "HO_OmniNode_Bind"
    bl_label = "Bind"
    processor_tree: bpy.props.PointerProperty(
        name="Processor Tree",
        type=OmniNodeTree,
        update=lambda self, context: self.syncProcessorIO(),
        poll=OmniTreeFilter,
    ) # type: ignore

    def build(self) -> None:
        self.omni_description = """
        将树转化为面板调用实时刷新的处理系统
        用于轻量树，以及运行后调整生成物的属性
        不要分配大型任务给这个节点，除非你知道自己在做什么
        """
        self.syncProcessorIO()

    def syncProcessorIO(self) -> None:
        link_cache = cache_node_links(self)
        default_values = cache_nodesockets_defaultvalues(self)
        self.inputs.clear()
        self.outputs.clear()

        if self.processor_tree is not None:
            for io in self.processor_tree.group_inputs:
                self.inputs.new(
                    type=runtime_socket_type_id(io.socket_type),
                    name=io.name,
                    identifier=io.uid,
                )

            for io in self.processor_tree.group_outputs:
                socket = self.outputs.new(
                    type=runtime_socket_type_id(io.socket_type),
                    name=io.name,
                    identifier=io.uid,
                )
                socket.hide_value = True

        restore_node_links(self, link_cache)
        restore_nodesockets_defaultvalues(self, default_values)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        draw_tree_ref_selector(layout, self, "processor_tree")


CLS_GRAPH = [OmniGroupNode, OmniGroupNodeInputs, OmniGroupNodeOutputs, OmniBindNode]
