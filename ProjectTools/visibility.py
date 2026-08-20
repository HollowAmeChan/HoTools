"""Scene and view-layer visibility operations."""

import bpy
from bpy.types import Operator


class OP_sync_render_visibility(Operator):
    bl_idname = "ho.sync_render_visibility"
    bl_label = "同步渲染/视图层显示"
    bl_description = "将所有启用物体的渲染与视图层显示同步"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        for layer_collection in context.view_layer.layer_collection.children:
            if not layer_collection.exclude:
                layer_collection.collection.hide_render = layer_collection.hide_viewport
        for obj in context.scene.objects:
            obj.hide_render = obj.hide_get()
        return {"FINISHED"}

__all__ = ["OP_sync_render_visibility"]
