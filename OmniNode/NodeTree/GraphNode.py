# 本文件为functionnode以外的拓展类型node，用于实现高级功能

# TODO:目前的IO节点不支持自动变换type（以及socket.name）,导致非常难以使用。但是为了这个功能需要写巨量多的代码得不偿失
# TODO:缺少编译分支节点（未来再支持）
import bpy
from typing import Any
from .OmniNode import OmniNode
from .OmniNodeOperator import OmniGraphNodeIOItem,HO_UL_GraphNodeIO,OP_IOItemRemove,OP_IOItemAdd,OP_IOItemMove,OP_JumpToNodeTree
from bpy.props import BoolProperty, CollectionProperty, IntProperty

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


class OmniBatchGroupNode(OmniNode):
    bl_idname = "HO_OmniNode_BatchGroupNode"
    bl_label = "组批量"

    target_tree: bpy.props.PointerProperty(
        name="Group",
        type=OmniNodeTree,
        update=lambda self, context: self.syncGroupIO(),
        poll=OmniTreeFilter,
    )  # type: ignore
    batch_input_index: IntProperty(
        name="Batch Input Index",
        default=0,
        min=0,
        update=lambda self, context: self.syncGroupIO(),
    )  # type: ignore

    def build(self) -> None:
        self.omni_description = """
        批量运行一个组子树。
        只有一个输入口会被当作批输入并逐项喂给子树，
        其他输入口保持常值，每次运行都复用。
        """
        self.syncGroupIO()

    def _resolve_batch_input_index(self, tree: OmniNodeTree | None) -> int:
        if tree is None or len(tree.group_inputs) == 0:
            return -1

        selected_index = int(getattr(self, "batch_input_index", 0))
        return max(0, min(selected_index, len(tree.group_inputs) - 1))

    def syncGroupIO(self) -> None:
        tree = self.target_tree
        link_cache = cache_node_links(self)
        default_values = cache_nodesockets_defaultvalues(self)
        self.inputs.clear()
        self.outputs.clear()

        if tree is None:
            self._socket_is_multi = {}
            restore_node_links(self, link_cache)
            restore_nodesockets_defaultvalues(self, default_values)
            return

        batch_index = self._resolve_batch_input_index(tree)
        socket_is_multi = {}

        for index, io in enumerate(tree.group_inputs):
            is_batch = index == batch_index
            sock = self.inputs.new(
                type=runtime_socket_type_id(io.socket_type),
                name=io.name,
                identifier=io.uid,
                use_multi_input=is_batch,
            )
            if is_batch:
                sock.display_shape = "SQUARE"
            socket_is_multi[io.uid] = is_batch

        for io in tree.group_outputs:
            sock = self.outputs.new(
                type=runtime_socket_type_id(io.socket_type),
                name=io.name,
                identifier=io.uid,
            )
            sock.hide_value = True

        self._socket_is_multi = socket_is_multi

        if getattr(self, "batch_input_index", -1) != batch_index:
            self.batch_input_index = batch_index

        restore_node_links(self, link_cache)
        restore_nodesockets_defaultvalues(self, default_values)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        draw_tree_ref_selector(layout, self, "target_tree")
        tree = self.target_tree
        row = layout.row()
        row.enabled = tree is not None and len(tree.group_inputs) > 0
        
        if tree is not None and len(tree.group_inputs) > 0:
            resolved_index = self._resolve_batch_input_index(tree)
            if 0 <= resolved_index < len(tree.group_inputs):
                row.label(text=f"批入口: {tree.group_inputs[resolved_index].name}")
                row.prop(self, "batch_input_index", text="")


def _sync_cache_node_io(node: OmniNode, *, is_writer: bool) -> None:
    link_cache = cache_node_links(node)
    default_values = cache_nodesockets_defaultvalues(node)

    node.inputs.clear()
    node.outputs.clear()

    node.inputs.new(type="NodeSocketString", name="缓存名", identifier="cache_key")
    if is_writer:
        node.inputs.new(type="OmniNodeSocketAny", name="值", identifier="value")
        enable_sock = node.inputs.new(type="NodeSocketBool", name="启用", identifier="enable")
        try:
            enable_sock.default_value = True
        except Exception:
            pass
        node.outputs.new(type="OmniNodeSocketAny", name="值", identifier="value")
    else:
        node.inputs.new(type="OmniNodeSocketAny", name="默认值", identifier="fallback")
        node.outputs.new(type="OmniNodeSocketAny", name="值", identifier="value")
        node.outputs.new(type="NodeSocketBool", name="命中", identifier="hit")

    restore_node_links(node, link_cache)
    restore_nodesockets_defaultvalues(node, default_values)


class OmniCacheReadNode(OmniNode):
    bl_idname = "HO_OmniNode_CacheRead"
    bl_label = "缓存读取"

    def build(self) -> None:
        self.omni_description = """
        从当前执行实例的 committed runtime cache 中读取值。
        缓存名是字符串输入，留空时使用本节点自己的运行时ID。
        如果缓存不存在，输出默认值并将命中输出设为False。
        """
        self.syncCacheIO()

    def syncCacheIO(self) -> None:
        _sync_cache_node_io(self, is_writer=False)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        pass


class OmniCacheWriteNode(OmniNode):
    bl_idname = "HO_OmniNode_CacheWrite"
    bl_label = "缓存写入"

    def build(self) -> None:
        self.omni_description = """
        把输入值写入当前执行实例的 pending runtime cache。
        缓存名是字符串输入，留空时使用本节点自己的运行时ID。
        如果缓存名每帧变化，会持续产生新的 cache 项；需要时请配合缓存删除节点清理。
        只有整棵root tree本轮执行成功后，pending cache才会提交。
        """
        self.syncCacheIO()

    def syncCacheIO(self) -> None:
        _sync_cache_node_io(self, is_writer=True)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        pass


def _sync_cache_delete_node_io(node: OmniNode) -> None:
    link_cache = cache_node_links(node)
    default_values = cache_nodesockets_defaultvalues(node)

    node.inputs.clear()
    node.outputs.clear()

    node.inputs.new(type="OmniNodeSocketAny", name="触发", identifier="trigger")
    node.inputs.new(type="NodeSocketString", name="缓存名", identifier="cache_key")
    delete_all_sock = node.inputs.new(type="NodeSocketBool", name="删除全部", identifier="delete_all")
    try:
        delete_all_sock.default_value = False
    except Exception:
        pass
    enable_sock = node.inputs.new(type="NodeSocketBool", name="启用", identifier="enable")
    try:
        enable_sock.default_value = True
    except Exception:
        pass

    node.outputs.new(type="OmniNodeSocketAny", name="触发", identifier="trigger")
    node.outputs.new(type="NodeSocketInt", name="删除数量", identifier="count")
    node.outputs.new(type="NodeSocketBool", name="完成", identifier="done")

    restore_node_links(node, link_cache)
    restore_nodesockets_defaultvalues(node, default_values)


class OmniCacheDeleteNode(OmniNode):
    bl_idname = "HO_OmniNode_CacheDelete"
    bl_label = "缓存删除"

    def build(self) -> None:
        self.omni_description = """
        删除当前执行实例中的 runtime cache。
        删除全部输入为 True 时会删除当前 root/group/batch 实例命名空间中的全部 cache。
        删除全部为 False 时按缓存名删除；缓存名为空不会删除指定项。
        删除操作和写入一样只在本轮 root tree 成功执行后提交。
        """
        self.is_output_node = False
        self.syncCacheIO()

    def syncCacheIO(self) -> None:
        _sync_cache_delete_node_io(self)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        pass


def _sync_cache_dump_node_io(node: OmniNode) -> None:
    link_cache = cache_node_links(node)
    default_values = cache_nodesockets_defaultvalues(node)

    node.inputs.clear()
    node.outputs.clear()

    node.inputs.new(type="OmniNodeSocketAny", name="触发", identifier="trigger")
    node.inputs.new(type="NodeSocketString", name="标记", identifier="label")

    node.outputs.new(type="OmniNodeSocketAny", name="触发", identifier="trigger")
    node.outputs.new(type="NodeSocketString", name="文本", identifier="text")
    node.outputs.new(type="NodeSocketInt", name="数量", identifier="count")

    restore_node_links(node, link_cache)
    restore_nodesockets_defaultvalues(node, default_values)


class OmniCacheDumpNode(OmniNode):
    bl_idname = "HO_OmniNode_CacheDump"
    bl_label = "缓存调试"

    print_to_console: BoolProperty(
        name="打印到控制台",
        default=True,
    )  # type: ignore

    def build(self) -> None:
        self.omni_description = """
        打印并输出当前执行实例命名空间中的 runtime cache 快照。
        快照包含 committed cache，并叠加本轮 pending 写入和 pending 删除。
        触发输入只用于建立依赖和执行顺序，不参与快照内容。
        标记输入会作为控制台和文本输出的标题，方便区分多个调试节点。
        """
        self.is_output_node = False
        self.syncCacheIO()

    def syncCacheIO(self) -> None:
        _sync_cache_dump_node_io(self)

    def draw_buttons(self, context: bpy.types.Context, layout: bpy.types.UILayout) -> None:
        layout.prop(self, "print_to_console")


CLS_GRAPH = [
    OmniGroupNode,
    OmniGroupNodeInputs,
    OmniGroupNodeOutputs,
    OmniBatchGroupNode,
    OmniCacheReadNode,
    OmniCacheWriteNode,
    OmniCacheDeleteNode,
    OmniCacheDumpNode,
]
