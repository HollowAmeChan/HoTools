from typing import Set
import bpy
import os
from bpy.props import BoolProperty, StringProperty, EnumProperty
from bpy.types import Context, Operator, PropertyGroup, UIList, UILayout
from . import OmniNodeSocket
import uuid

# 用于获取动态的全socket枚举
BLENDER_SOCKET_TYPES = {
    "NodeSocketFloat": "Float",
    "NodeSocketInt": "Int",
    "NodeSocketBool": "Bool",
    "NodeSocketString": "String",

    "NodeSocketVector": "Vector",
    "NodeSocketColor": "Color",
    "NodeSocketRotation": "Rotation",

    "NodeSocketGeometry": "Geometry",

    "NodeSocketObject": "Object",
    "NodeSocketImage": "Image",
    "NodeSocketCollection": "Collection",

    "NodeSocketMaterial": "Material",
    "NodeSocketTexture": "Texture",

    "NodeSocketShader": "Shader",

    "NodeSocketMatrix": "Matrix",
    # "NodeSocketMenu": "Menu",
}


def full_socket_type_items():
    items = []
    for idname, label in BLENDER_SOCKET_TYPES.items():
        items.append((idname, label, ""))
    for k in OmniNodeSocket.cls:
        items.append((k.bl_idname, k.bl_label, ""))
    return items


def sync_tree_io(tree):
    # 会同步tree内的所有特殊graph节点
    for node in tree.nodes:
        if node.bl_idname == "HO_OmniNode_GroupNode_Inputs":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_GroupNode_Outputs":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_GroupNode":
            node.syncGroupIO()
        elif node.bl_idname == "HO_OmniNode_GroupNode_Repeat":
            node.syncGroupIO()


def sync_all_related_tree_io(tree):
    """同步当前tree，以及所有引用这个tree的组节点。"""
    if not tree:
        return
    if getattr(tree, "bl_idname", None) != "OmniNodeTree":
        return

    sync_tree_io(tree)

    for other_tree in bpy.data.node_groups:
        if other_tree == tree:
            continue
        if getattr(other_tree, "bl_idname", None) != "OmniNodeTree":
            continue

        for node in other_tree.nodes:
            if node.bl_idname not in {"HO_OmniNode_GroupNode", "HO_OmniNode_GroupNode_Repeat"}:
                continue
            if getattr(node, "target_tree", None) != tree:
                continue
            node.syncGroupIO()


def OmniGraphNodeIOItem_update(self, context):
    """在所有需要同步group io的地方统一使用这个函数。"""
    tree = self.id_data
    sync_all_related_tree_io(tree)


class OmniGraphNodeIOItem(PropertyGroup):
    """IO输入输出组的ui绘制使用的列表单行"""
    name: StringProperty(name="IO", default="IO", update=OmniGraphNodeIOItem_update)  # type: ignore
    uid: StringProperty(name="UID", default="", options={'HIDDEN'})  # type: ignore
    socket_type: EnumProperty(  # type: ignore
        name="Socket Type",
        default=OmniNodeSocket.OmniNodeSocketAny.bl_idname,
        items=full_socket_type_items(),
        update=OmniGraphNodeIOItem_update,
    )
    # TODO: default_value无法同步需要设计
    # 目前直接不允许用户改默认值，强制要求用户给每个输入口子连节点


class HO_UL_GraphNodeIO(UIList):
    """IO输入输出组的ui绘制使用的列表"""

    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False)
        row.label(text="UID:" + item.uid)
        row.prop(item, "socket_type", text="")


class OP_IOItemAdd(Operator):
    bl_idname = "ho.omni_ioitemadd"
    bl_label = "Add IO"

    is_input: BoolProperty()  # type: ignore

    def generate_unique_uid(self, tree):
        existing = set()

        for item in tree.group_inputs:
            if item.uid:
                existing.add(item.uid)

        for item in tree.group_outputs:
            if item.uid:
                existing.add(item.uid)

        while True:
            uid = uuid.uuid4().hex
            if uid not in existing:
                return uid

    def execute(self, context):
        tree = context.space_data.node_tree

        if self.is_input:
            item = tree.group_inputs.add()
            item.name = "Input"
            item.uid = self.generate_unique_uid(tree)
            tree.group_inputs_index = len(tree.group_inputs) - 1
        else:
            item = tree.group_outputs.add()
            item.name = "Output"
            item.uid = self.generate_unique_uid(tree)
            tree.group_outputs_index = len(tree.group_outputs) - 1

        sync_all_related_tree_io(tree)
        return {'FINISHED'}


class OP_IOItemRemove(Operator):
    bl_idname = "ho.omni_ioitemremove"
    bl_label = "Remove IO"

    is_input: BoolProperty()  # type: ignore

    def execute(self, context):
        tree = context.space_data.node_tree

        if self.is_input:
            idx = tree.group_inputs_index
            if idx < 0 or idx >= len(tree.group_inputs):
                return {'CANCELLED'}
            tree.group_inputs.remove(idx)
            tree.group_inputs_index = max(0, idx - 1)
        else:
            idx = tree.group_outputs_index
            if idx < 0 or idx >= len(tree.group_outputs):
                return {'CANCELLED'}
            tree.group_outputs.remove(idx)
            tree.group_outputs_index = max(0, idx - 1)

        sync_all_related_tree_io(tree)
        return {'FINISHED'}


class NodeSetDefaultSize(Operator):
    bl_idname = "ho.nodesetdefaultsize"
    bl_label = "恢复node默认大小"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.size2default()
            return {'FINISHED'}
        except Exception:
            return {'FINISHED'}


class NodeSetBiggerSize(Operator):
    bl_idname = "ho.nodesetbiggersize"
    bl_label = "加宽node"

    node_name: bpy.props.StringProperty()  # type: ignore

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        try:
            node = bpy.context.space_data.node_tree.nodes[self.node_name]
            node.width *= 2
            return {'FINISHED'}
        except Exception:
            return {'FINISHED'}


class LayerRunning(Operator):
    bl_idname = "ho.layerrunning"
    bl_label = "树手动触发回调"
    bl_options = {'REGISTER', 'UNDO'}
    reportInfo: BoolProperty(name="报告pool信息", default=True)  # type: ignore

    def execute(self, context: bpy.types.Context):
        if (not hasattr(context.space_data, "node_tree")) or (not context.space_data.node_tree):
            return {'FINISHED'}
        tree = context.space_data.node_tree
        tree.run()
        return {'FINISHED'}


class OmniNodeRebuild(Operator):
    # TODO: 诡异bug，重建以后会自动拥有bl_icon，此问题在pr中被反复讨论，是有关customgroupnode的？
    # https://projects.blender.org/blender/blender/pulls/130204
    bl_idname = "ho.rebuild_node"
    bl_label = "重建节点"
    bl_description = "重建节点的输入输出socket，保持用户输入和连接不变，适用于修改了节点函数签名后更新节点"
    bl_options = {'REGISTER'}

    node_tree_name: bpy.props.StringProperty()  # type: ignore
    node_name: bpy.props.StringProperty()  # type: ignore

    def execute(self, context):
        # 0. 获取 node_tree 和 node
        tree = bpy.data.node_groups.get(self.node_tree_name)
        if tree is None:
            self.report({'ERROR'}, f"NodeTree not found: {self.node_tree_name}")
            return {'CANCELLED'}

        node = tree.nodes.get(self.node_name)
        if node is None:
            self.report({'ERROR'}, f"Node not found: {self.node_name}")
            return {'CANCELLED'}

        if not hasattr(node, "build"):
            self.report({'ERROR'}, "Node has no build() method")
            return {'CANCELLED'}

        # 1. cache 用户 default_value
        input_value_cache = {}
        output_value_cache = {}

        for sock in node.inputs:
            try:
                input_value_cache[sock.identifier] = sock.default_value
            except Exception:
                pass

        for sock in node.outputs:
            try:
                output_value_cache[sock.identifier] = sock.default_value
            except Exception:
                pass

        # 2. 收集 links
        input_links = []
        for sock in node.inputs:
            for link in sock.links:
                input_links.append((
                    link.from_node.name,
                    link.from_socket.identifier,
                    sock.identifier,
                ))

        output_links = []
        for sock in node.outputs:
            for link in sock.links:
                output_links.append((
                    sock.identifier,
                    link.to_node.name,
                    link.to_socket.identifier,
                ))

        # 3. 清理 sockets + links
        for sock in list(node.inputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.inputs.remove(sock)

        for sock in list(node.outputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.outputs.remove(sock)

        # 4. rebuild
        node.build()
        node.is_bug = False
        node.property_unset("bug_text")

        # 5. 恢复 default_value
        for identifier, value in input_value_cache.items():
            sock = node.inputs.get(identifier)
            if sock:
                try:
                    sock.default_value = value
                except Exception:
                    pass

        for identifier, value in output_value_cache.items():
            sock = node.outputs.get(identifier)
            if sock:
                try:
                    sock.default_value = value
                except Exception:
                    pass

        # 6. reconnect input links
        for from_node_name, from_socket_id, to_socket_id in input_links:
            from_node = tree.nodes.get(from_node_name)
            if not from_node:
                continue

            from_socket = from_node.outputs.get(from_socket_id)
            to_socket = node.inputs.get(to_socket_id)

            if from_socket and to_socket:
                tree.links.new(from_socket, to_socket)

        # 7. reconnect output links
        for from_socket_id, to_node_name, to_socket_id in output_links:
            to_node = tree.nodes.get(to_node_name)
            if not to_node:
                continue

            from_socket = node.outputs.get(from_socket_id)
            to_socket = to_node.inputs.get(to_socket_id)

            if from_socket and to_socket:
                tree.links.new(from_socket, to_socket)

        return {'FINISHED'}


def draw_in_NODE_MT_editor_menus(self, context: Context):
    """OmniNode顶部运行按钮"""
    space = context.space_data
    if not space or space.type != 'NODE_EDITOR':
        return
    tree = space.node_tree
    if not tree:
        return
    if tree.bl_idname != "OmniNodeTree":
        return

    layout: bpy.types.UILayout = self.layout
    layout.operator(LayerRunning.bl_idname, text="运行OMNI树", icon="FILE_REFRESH")
    return


clss = [
    NodeSetDefaultSize,
    NodeSetBiggerSize,
    LayerRunning,
    OmniNodeRebuild,
    OmniGraphNodeIOItem,
    HO_UL_GraphNodeIO,
    OP_IOItemAdd,
    OP_IOItemRemove,
]


def register():
    try:
        for i in clss:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__ + " register failed!!!")
    bpy.types.NODE_MT_editor_menus.append(draw_in_NODE_MT_editor_menus)


def unregister():
    try:
        for i in clss:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__ + " unregister failed!!!")
    bpy.types.NODE_MT_editor_menus.remove(draw_in_NODE_MT_editor_menus)
