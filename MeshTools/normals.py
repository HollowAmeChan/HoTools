"""Mesh custom-normal editing operators."""

import math
from collections import defaultdict

import bpy
from bpy.props import FloatProperty
from bpy.types import Operator
from mathutils import Vector


class OP_MergeOverlapping_VertexNormals(Operator):
    bl_idname = "ho.merge_overlapping_vertexnormals"
    bl_label = "合并最近顶点法线(仅法线)"
    bl_description = "支持多物体同时编辑，仅合并法线不合并 mesh"
    bl_options = {"REGISTER", "UNDO"}
    distancs: FloatProperty(name="间距", default=0.0001, min=0.0) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        distance = self.distancs
        if distance <= 0:
            self.report({"WARNING"}, "间距必须大于 0")
            return {"CANCELLED"}
        objects = [obj for obj in context.objects_in_mode_unique_data if obj.type == "MESH"]
        if not objects:
            return {"CANCELLED"}
        bpy.ops.object.mode_set(mode="OBJECT")
        items, any_selected = [], False
        mesh_state = {}
        for obj in objects:
            normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
            mesh = obj.data
            had_custom_normals = mesh.has_custom_normals
            # Keep the evaluated split normals so the per-corner differences
            # around sharp edges can be preserved when the vertex normal moves.
            split_normals = [loop.normal.copy() for loop in mesh.loops]
            if any(vertex.select and not vertex.hide for vertex in obj.data.vertices):
                any_selected = True
            for vertex in obj.data.vertices:
                if not vertex.hide:
                    items.append({"obj": obj, "vi": vertex.index, "selected": vertex.select,
                                  "co": obj.matrix_world @ vertex.co,
                                  "normal_local": vertex.normal.copy(),
                                  "normal_world": (normal_matrix @ vertex.normal).normalized()})
            mesh_state[obj] = (split_normals, had_custom_normals)
        if any_selected:
            items = [item for item in items if item["selected"]]
        if len(items) < 2:
            bpy.ops.object.mode_set(mode="EDIT")
            return {"FINISHED"}
        parent = list(range(len(items)))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left, right):
            left, right = find(left), find(right)
            if left != right:
                parent[right] = left

        grid, distance_squared = defaultdict(list), distance * distance
        for index, item in enumerate(items):
            co = item["co"]
            cell = tuple(math.floor(value / distance) for value in co)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for other in grid.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                            if (co - items[other]["co"]).length_squared <= distance_squared:
                                union(index, other)
            grid[cell].append(index)
        groups = defaultdict(list)
        for index in range(len(items)):
            groups[find(index)].append(index)
        target_normals = defaultdict(dict)
        for group in groups.values():
            if len(group) < 2:
                continue
            average = sum((items[index]["normal_world"] for index in group), Vector())
            if average.length <= 1e-8:
                continue
            average.normalize()
            for index in group:
                item = items[index]
                target_normals[item["obj"]][item["vi"]] = (
                    item["obj"].matrix_world.to_3x3().transposed() @ average
                ).normalized()
        for obj, normal_map in target_normals.items():
            mesh = obj.data
            split_normals, had_custom_normals = mesh_state[obj]
            # Zero vectors retain Blender's automatically calculated normals
            # for untouched corners when the mesh did not already have a
            # custom-normal layer.
            normals = split_normals if had_custom_normals else [Vector() for _ in mesh.loops]
            vertex_normals = {item["vi"]: item["normal_local"]
                              for item in items if item["obj"] == obj}
            loops_by_vertex = defaultdict(list)
            for loop in mesh.loops:
                loops_by_vertex[loop.vertex_index].append(loop.index)
            for vertex_index, normal in normal_map.items():
                source = vertex_normals.get(vertex_index)
                if source is None or source.length <= 1e-8 or normal.length <= 1e-8:
                    continue
                # Rotate the whole normal fan by the same amount. Smooth
                # corners follow the merged vertex normal, while corners on
                # opposite sides of a sharp edge keep their original split.
                rotation = source.rotation_difference(normal)
                for loop_index in loops_by_vertex[vertex_index]:
                    normals[loop_index] = (rotation @ split_normals[loop_index]).normalized()
            mesh.normals_split_custom_set(normals)
            mesh.update()
        bpy.ops.object.mode_set(mode="EDIT")
        return {"FINISHED"}

__all__ = ["OP_MergeOverlapping_VertexNormals"]
