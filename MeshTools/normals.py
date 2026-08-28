"""Mesh custom-normal editing operators."""

import math
import bmesh
import json
from collections import defaultdict

import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator
from mathutils import Vector


_NORMAL_CLIPBOARD_KEY = "hotools_vertex_normals"


def _normal_matrix(obj):
    return obj.matrix_world.to_3x3().inverted().transposed()


def _world_to_local_normal(obj, normal):
    """Transform a world-space normal into the mesh's local space."""
    return (obj.matrix_world.to_3x3().transposed() @ normal).normalized()


def _selected_vertex_indices(mesh):
    return {
        vertex.index
        for vertex in mesh.vertices
        if vertex.select and not vertex.hide
    }


class OP_CopyActiveVertexNormal(Operator):
    """Copy all split-normal corners belonging to the active edit-mode vertex."""

    bl_idname = "ho.copy_active_vertex_normal"
    bl_label = "复制活动顶点法线"
    bl_description = "将活动顶点的分裂法线复制到剪贴板（保留锐边）"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.index_update()
        active = bm.select_history.active
        if not isinstance(active, bmesh.types.BMVert) or active.hide:
            self.report({"WARNING"}, "请先激活一个顶点")
            return {"CANCELLED"}

        active_index = active.index
        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            mesh = obj.data
            normal_matrix = _normal_matrix(obj)
            corners = []
            for polygon in mesh.polygons:
                face_normal = (normal_matrix @ polygon.normal).normalized()
                for loop_index in polygon.loop_indices:
                    loop = mesh.loops[loop_index]
                    if loop.vertex_index != active_index:
                        continue
                    loop_normal = (normal_matrix @ loop.normal).normalized()
                    if loop_normal.length > 1e-8:
                        corners.append({
                            "normal": list(loop_normal),
                            "face_normal": list(face_normal),
                        })
            if not corners:
                self.report({"WARNING"}, "活动顶点没有可用法线")
                return {"CANCELLED"}

            payload = {
                _NORMAL_CLIPBOARD_KEY: 1,
                "corners": corners,
            }
            context.window_manager.clipboard = json.dumps(
                payload, separators=(",", ":")
            )
        finally:
            bpy.ops.object.mode_set(mode="EDIT")

        self.report({"INFO"}, f"已复制活动顶点的 {len(corners)} 个法线")
        return {"FINISHED"}


class OP_PasteVertexNormals(Operator):
    """Paste copied split-normal corners to every selected edit-mode vertex."""

    bl_idname = "ho.paste_vertex_normals"
    bl_label = "粘贴法线到选中点"
    bl_description = "将剪贴板中的顶点法线粘贴到所有选中顶点（保留锐边）"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.index_update()
        selected_indices = {
            vertex.index
            for vertex in bm.verts
            if vertex.select and not vertex.hide
        }
        if not selected_indices:
            self.report({"WARNING"}, "没有选中的顶点")
            return {"CANCELLED"}

        try:
            payload = json.loads(context.window_manager.clipboard)
            if payload.get(_NORMAL_CLIPBOARD_KEY) != 1:
                raise ValueError
            corners = payload["corners"]
            if not corners:
                raise ValueError
            source_corners = [
                (
                    Vector(item["normal"]).normalized(),
                    Vector(item["face_normal"]).normalized(),
                )
                for item in corners
            ]
        except (AttributeError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.report({"WARNING"}, "剪贴板中没有 HoTools 顶点法线数据")
            return {"CANCELLED"}

        bpy.ops.object.mode_set(mode="OBJECT")
        try:
            mesh = obj.data
            target_normal_matrix = _normal_matrix(obj)
            target_face_normals = {}
            loops_by_vertex = defaultdict(list)
            for polygon in mesh.polygons:
                face_normal = (target_normal_matrix @ polygon.normal).normalized()
                for loop_index in polygon.loop_indices:
                    target_face_normals[loop_index] = face_normal
                    loop = mesh.loops[loop_index]
                    loops_by_vertex[loop.vertex_index].append(loop_index)

            normals = [loop.normal.copy() for loop in mesh.loops]
            pasted = 0
            for vertex_index in selected_indices:
                loop_indices = loops_by_vertex.get(vertex_index, ())
                for loop_index in loop_indices:
                    target_face_normal = target_face_normals.get(loop_index)
                    if target_face_normal is None:
                        source_normal = source_corners[0][0]
                    else:
                        source_normal = max(
                            source_corners,
                            key=lambda corner: corner[1].dot(target_face_normal),
                        )[0]
                    desired = _world_to_local_normal(obj, source_normal)
                    if desired.length > 1e-8:
                        normals[loop_index] = desired
                if loop_indices:
                    pasted += 1

            if pasted:
                mesh.normals_split_custom_set(normals)
                mesh.update()
        finally:
            bpy.ops.object.mode_set(mode="EDIT")

        if not pasted:
            self.report({"WARNING"}, "选中顶点没有可粘贴的法线")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已粘贴到 {pasted} 个选中顶点")
        return {"FINISHED"}


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


class OP_MergeNearestVertexNormals(Operator):
    """Merge normals of overlapping vertices across all edit-mode mesh objects."""

    bl_idname = "ho.merge_nearest_vertex_normals"
    bl_label = "合并最近顶点法线"
    bl_description = "支持多物体同时编辑，仅合并法线不合并网格"
    bl_options = {"REGISTER", "UNDO"}
    distancs: FloatProperty(name="间距", default=0.0001, min=0.0)  # type: ignore

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
        items = []
        any_selected = False
        mesh_state = {}
        for obj in objects:
            mesh = obj.data
            normal_matrix = _normal_matrix(obj)
            split_normals = [loop.normal.copy() for loop in mesh.loops]
            had_custom_normals = mesh.has_custom_normals
            any_selected |= any(vertex.select and not vertex.hide for vertex in mesh.vertices)
            for vertex in mesh.vertices:
                if vertex.hide:
                    continue
                items.append({
                    "obj": obj,
                    "vi": vertex.index,
                    "selected": vertex.select,
                    "co": obj.matrix_world @ vertex.co,
                    "normal_local": vertex.normal.copy(),
                    "normal_world": (normal_matrix @ vertex.normal).normalized(),
                })
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

        grid = defaultdict(list)
        distance_squared = distance * distance
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
                target_normals[item["obj"]][item["vi"]] = _world_to_local_normal(
                    item["obj"], average
                )

        merged_groups = 0
        for group in groups.values():
            if len(group) >= 2:
                merged_groups += 1
        for obj, normal_map in target_normals.items():
            mesh = obj.data
            split_normals, had_custom_normals = mesh_state[obj]
            normals = split_normals if had_custom_normals else [Vector() for _ in mesh.loops]
            vertex_normals = {
                item["vi"]: item["normal_local"]
                for item in items
                if item["obj"] == obj
            }
            loops_by_vertex = defaultdict(list)
            for loop in mesh.loops:
                loops_by_vertex[loop.vertex_index].append(loop.index)
            for vertex_index, normal in normal_map.items():
                source = vertex_normals.get(vertex_index)
                if source is None or source.length <= 1e-8 or normal.length <= 1e-8:
                    continue
                rotation = source.rotation_difference(normal)
                for loop_index in loops_by_vertex[vertex_index]:
                    normals[loop_index] = (rotation @ split_normals[loop_index]).normalized()
            mesh.normals_split_custom_set(normals)
            mesh.update()

        bpy.ops.object.mode_set(mode="EDIT")
        self.report({"INFO"}, f"已合并 {merged_groups} 组顶点法线")
        return {"FINISHED"}


__all__ = [
    "OP_CopyActiveVertexNormal",
    "OP_MergeNearestVertexNormals",
    "OP_MergeOverlapping_VertexNormals",
    "OP_PasteVertexNormals",
]
