"""Mesh custom-normal editing operators."""

import math
from collections import defaultdict

import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator
from mathutils import Vector


class OP_MergeOverlapping_VertexNormals(Operator):
    bl_idname = "ho.merge_overlapping_vertexnormals"
    bl_label = "吸附最近顶点法线"
    bl_description = "将活动物体顶点法线吸附到非活动物体的最近顶点法线"
    bl_options = {"REGISTER", "UNDO"}
    # Keep the existing property name for compatibility with saved operator settings.
    distancs: FloatProperty(name="间距", default=0.0001, min=0.0)  # type: ignore
    only_selected: BoolProperty(name="仅选中顶点", default=False)  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        distance = self.distancs
        if distance <= 0:
            self.report({"WARNING"}, "间距必须大于 0")
            return {"CANCELLED"}

        active = context.active_object
        objects = [obj for obj in context.objects_in_mode_unique_data if obj.type == "MESH"]
        source_objects = [obj for obj in objects if obj != active]
        if not source_objects:
            self.report({"WARNING"}, "没有处于编辑模式的非活动网格物体")
            return {"CANCELLED"}

        selected_target_indices = {
            vertex.index for vertex in active.data.vertices
            if vertex.select and not vertex.hide
        }
        bpy.ops.object.mode_set(mode="OBJECT")

        source_items = []
        for obj in source_objects:
            normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
            source_corners = defaultdict(list)
            for polygon in obj.data.polygons:
                face_normal_world = (normal_matrix @ polygon.normal).normalized()
                for loop_index in polygon.loop_indices:
                    loop = obj.data.loops[loop_index]
                    source_corners[loop.vertex_index].append(
                        ((normal_matrix @ loop.normal).normalized(), face_normal_world)
                    )
            for vertex in obj.data.vertices:
                if vertex.hide:
                    continue
                corners = source_corners.get(vertex.index, ())
                if not corners:
                    continue
                source_items.append({
                    "co": obj.matrix_world @ vertex.co,
                    "corners": corners,
                })
        if not source_items:
            bpy.ops.object.mode_set(mode="EDIT")
            self.report({"WARNING"}, "没有可用的匹配顶点")
            return {"CANCELLED"}

        distance_squared = distance * distance
        source_grid = defaultdict(list)
        for index, item in enumerate(source_items):
            cell = tuple(math.floor(value / distance) for value in item["co"])
            source_grid[cell].append(index)

        mesh = active.data
        normals = (
            [loop.normal.copy() for loop in mesh.loops]
            if mesh.has_custom_normals else [Vector() for _ in mesh.loops]
        )
        target_normal_matrix = active.matrix_world.to_3x3().inverted().transposed()
        loops_by_vertex = defaultdict(list)
        face_normals_by_loop = {}
        for polygon in mesh.polygons:
            face_normal_world = (target_normal_matrix @ polygon.normal).normalized()
            for loop_index in polygon.loop_indices:
                face_normals_by_loop[loop_index] = face_normal_world
        for loop in mesh.loops:
            loops_by_vertex[loop.vertex_index].append(loop.index)

        matched = 0
        for vertex in mesh.vertices:
            if vertex.hide or (
                self.only_selected and vertex.index not in selected_target_indices
            ):
                continue
            world_co = active.matrix_world @ vertex.co
            cell = tuple(math.floor(value / distance) for value in world_co)
            nearest_index = None
            nearest_distance = distance_squared
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for source_index in source_grid.get(
                            (cell[0] + dx, cell[1] + dy, cell[2] + dz), ()
                        ):
                            candidate_distance = (
                                world_co - source_items[source_index]["co"]
                            ).length_squared
                            if candidate_distance <= nearest_distance:
                                nearest_distance = candidate_distance
                                nearest_index = source_index
            if nearest_index is None:
                continue
            source_corners = source_items[nearest_index]["corners"]
            for loop_index in loops_by_vertex[vertex.index]:
                target_face_normal = face_normals_by_loop.get(loop_index)
                source_normal_world = (
                    source_corners[0][0]
                    if target_face_normal is None
                    else max(
                        source_corners,
                        key=lambda corner: corner[1].dot(target_face_normal),
                    )[0]
                )
                desired = (target_normal_matrix @ source_normal_world).normalized()
                if desired.length > 1e-8:
                    normals[loop_index] = desired
            matched += 1

        if matched:
            mesh.normals_split_custom_set(normals)
            mesh.update()
        bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, f"已吸附 {matched} 个活动物体顶点的法线")
        return {"FINISHED"}


__all__ = ["OP_MergeOverlapping_VertexNormals"]
