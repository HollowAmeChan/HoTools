"""Mesh-to-image-reference object conversion."""

import bpy
from bpy.types import Operator

from mathutils import Vector


def get_first_image_from_material(obj):
    if not obj.data.materials:
        return None
    material = obj.data.materials[0]
    if not material or not material.use_nodes:
        return None
    return next(
        (node.image for node in material.node_tree.nodes
         if node.type == "TEX_IMAGE" and node.image),
        None,
    )


def longest_edge_world(obj, face):
    matrix = obj.matrix_world
    vertices = obj.data.vertices
    return max(
        ((matrix @ vertices[face.vertices[index]].co) -
         (matrix @ vertices[face.vertices[(index + 1) % len(face.vertices)]].co)).length
        for index in range(len(face.vertices))
    )


class OP_MeshToImageEmpty(Operator):
    bl_idname = "ho.mesh_to_image_empty"
    bl_label = "面片转参考图"
    bl_description = "将面片转为 Image Empty，复用原物体变换，尺寸基于面片世界空间最长边"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(obj.type == "MESH" for obj in context.selected_objects)

    def execute(self, context):
        objects = context.selected_objects
        if not objects:
            self.report({"ERROR"}, "未选择物体")
            return {"CANCELLED"}
        for obj in list(objects):
            if obj.type != "MESH" or not obj.data.polygons:
                continue
            image = get_first_image_from_material(obj)
            if image is None:
                continue
            face = next((poly for poly in obj.data.polygons if poly.select), obj.data.polygons[0])
            empty = bpy.data.objects.new(f"REF_{image.name}", None)
            empty.empty_display_type = "IMAGE"
            empty.data = image
            empty.matrix_world = obj.matrix_world.copy()
            empty.empty_display_size = longest_edge_world(obj, face)
            empty.scale = (1, 1, 1)
            context.collection.objects.link(empty)
            bpy.data.objects.remove(obj, do_unlink=True)
        return {"FINISHED"}

__all__ = ["OP_MeshToImageEmpty"]
