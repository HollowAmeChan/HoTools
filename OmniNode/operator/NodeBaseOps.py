from typing import Set
import bpy
import os
from bpy.props import BoolProperty, StringProperty
from bpy.types import Context


class NodeSetDefaultSize(bpy.types.Operator):
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


class NodeSetBiggerSize(bpy.types.Operator):
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


class LayerRunning(bpy.types.Operator):
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


class NodeRebuildSockets(bpy.types.Operator):
    bl_idname = "ho.noderebuildsockets"
    bl_label = "重建节点socket"
    bl_description = "用于插件更新后旧节点的修复,如果节点socket发生错误或者丢失,可以尝试使用这个功能重建socket"

    @classmethod
    def poll(cls, context):
        node = getattr(context, "active_node", None) or getattr(context, "node", None)
        return node is not None and hasattr(node, "rebuild")

    def execute(self, context):
        try:
            node = getattr(context, "active_node", None) or getattr(context, "node", None)
            if node is None:
                return {'CANCELLED'}
            node.rebuild()
            return {'FINISHED'}
        except Exception as e:
            print(f"Rebuild failed: {e}")
            return {'CANCELLED'}


clss = [NodeSetDefaultSize, NodeSetBiggerSize, LayerRunning,
        NodeRebuildSockets]


def register():
    try:
        for i in clss:
            bpy.utils.register_class(i)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in clss:
            bpy.utils.unregister_class(i)
    except Exception:
        print(__file__+" unregister failed!!!")
