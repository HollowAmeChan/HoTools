from typing import Set
import bpy
import os
from bpy.props import BoolProperty, StringProperty
from bpy.types import Context,Operator


class NodeSetDefaultSize(Operator):
    bl_idname = "ho.nodesetdefaultsize"  # 注册到bpy.ops下
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
        except:
            return {'FINISHED'}


class NodeSetBiggerSize(Operator):
    bl_idname = "ho.nodesetbiggersize"  # 注册到bpy.ops下
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
        except:
            return {'FINISHED'}


class LayerRunning(Operator):
    bl_idname = "ho.layerrunning"
    bl_label = "树手动触发回调"
    reportInfo: BoolProperty(name="报告pool信息", default=True)  # type: ignore

    def execute(self, context: bpy.types.Context):  # TODO:最好用调用的方式
        if (not hasattr(context.space_data, "node_tree")) or (not context.space_data.node_tree):
            return {'FINISHED'}
        tree = context.space_data.node_tree
        if self.reportInfo:
            tree.reportPool()
        tree.OmniInit()
        tree.run()  # 无视是否自动更新
        return {'FINISHED'}


class OmniNodeRebuild(Operator):
    bl_idname = "ho.rebuild_node"
    bl_label = "重建节点"
    bl_description = "重建节点的输入输出socket，保持用户输入和连接不变，适用于修改了节点函数签名后更新节点"
    bl_options = {'REGISTER', 'UNDO'}

    node_tree_name: bpy.props.StringProperty() # type: ignore
    node_name: bpy.props.StringProperty() # type: ignore

    def execute(self, context):
        # -----------------------------
        # 0. 获取 node_tree 和 node
        # -----------------------------
        tree = bpy.data.node_groups.get(self.node_tree_name)
        if tree is None:
            self.report({'ERROR'}, f"NodeTree not found: {self.node_tree_name}")
            return {'CANCELLED'}

        node = tree.nodes.get(self.node_name)
        if node is None:
            self.report({'ERROR'}, f"Node not found: {self.node_name}")
            return {'CANCELLED'}

        # 必须有 build()
        if not hasattr(node, "build"):
            self.report({'ERROR'}, "Node has no build() method")
            return {'CANCELLED'}

        # -----------------------------
        # 1. cache 用户 default_value
        # -----------------------------
        input_value_cache = {}
        output_value_cache = {}
        is_output_node = None # TODO:不一定保留

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
        is_output_node = node.is_output_node

        # -----------------------------
        # 2. 收集 links
        # -----------------------------
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

        # -----------------------------
        # 3. 清理 sockets + links
        # -----------------------------
        for sock in list(node.inputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.inputs.remove(sock)

        for sock in list(node.outputs):
            for link in list(sock.links):
                tree.links.remove(link)
            node.outputs.remove(sock)

        # -----------------------------
        # 4. rebuild（核心）
        # -----------------------------
        node.build()
        node.is_output_node = is_output_node

        # -----------------------------
        # 5. 恢复 default_value（用户输入）
        # -----------------------------
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

        # -----------------------------
        # 6. reconnect input links
        # -----------------------------
        for from_node_name, from_socket_id, to_socket_id in input_links:
            from_node = tree.nodes.get(from_node_name)
            if not from_node:
                continue

            from_socket = from_node.outputs.get(from_socket_id)
            to_socket = node.inputs.get(to_socket_id)

            if from_socket and to_socket:
                tree.links.new(from_socket, to_socket)

        # -----------------------------
        # 7. reconnect output links
        # -----------------------------
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
    layout: bpy.types.UILayout = self.layout
    layout.operator(LayerRunning.bl_idname, text="运行OMNI树", icon="FILE_REFRESH")
    return

clss = [NodeSetDefaultSize, NodeSetBiggerSize, LayerRunning,
        OmniNodeRebuild]


def register():
    try:
        for i in clss:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__+" register failed!!!")
    bpy.types.NODE_MT_editor_menus.append(draw_in_NODE_MT_editor_menus)



def unregister():
    try:
        for i in clss:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__+" unregister failed!!!")
    bpy.types.NODE_MT_editor_menus.remove(draw_in_NODE_MT_editor_menus)