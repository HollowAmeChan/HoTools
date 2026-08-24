"""Insert parallel manifold edges only inside the selected quad strip cells."""

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator

from .edge_flow import apply_edge_flow


def _edge_key(edge):
    return tuple(sorted((edge.verts[0].index, edge.verts[1].index)))


def _selected_edge_components(edges):
    remaining = {edge for edge in edges if edge.is_valid}
    components = []
    while remaining:
        seed = min(remaining, key=lambda edge: edge.index)
        remaining.remove(seed)
        component = {seed}
        frontier = [seed]
        while frontier:
            edge = frontier.pop()
            linked = {
                other
                for vertex in edge.verts
                for other in vertex.link_edges
                if other in remaining and other.is_valid
            }
            remaining.difference_update(linked)
            component.update(linked)
            frontier.extend(linked)
        components.append(component)
    return components


def _opposite_selected_edges(face):
    if not face.is_valid or len(face.verts) != 4:
        return None
    selected = [edge for edge in face.edges if edge.is_valid and edge.select]
    if len(selected) != 2:
        return None
    first, second = selected
    if any(vertex in first.verts for vertex in second.verts):
        return None
    return first, second


def _target_cells(bm):
    """Return each selected quad cell and its two unselected transverse edges."""
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    selected = [edge for edge in bm.edges if edge.is_valid and edge.select]
    if not selected:
        return []
    components = _selected_edge_components(selected)
    component_by_edge = {
        edge: number
        for number, component in enumerate(components)
        for edge in component
    }
    cells = []
    for face in sorted(bm.faces, key=lambda item: item.index):
        pair = _opposite_selected_edges(face)
        if pair is None:
            continue
        first, second = pair
        if component_by_edge.get(first) == component_by_edge.get(second):
            continue
        transverse = [
            edge for edge in face.edges
            if edge is not first
            and edge is not second
            and edge.is_valid
            and len(edge.link_faces) <= 2
        ]
        if len(transverse) != 2:
            continue
        # The target must be a quad, but its transverse edges may border a
        # triangle or an n-gon cap. Splitting such an edge only inserts a
        # vertex into that neighboring face and does not change the target
        # side strip into a non-quad. This is required for prisms and other
        # capped meshes whose side faces are valid quad cells.
        cells.append((face, first, second, transverse[0], transverse[1]))
    return cells


def _split_edge_at_cuts(edge, start, end, cuts):
    points = []
    current = edge
    previous_vertex = start
    previous = 0.0
    for cut_index in range(1, cuts + 1):
        target = cut_index / float(cuts + 1)
        local = (target - previous) / (1.0 - previous)
        next_edge, vertex = bmesh.utils.edge_split(
            current,
            previous_vertex,
            local,
        )
        points.append(vertex)
        current = next(
            linked
            for linked in vertex.link_edges
            if end in linked.verts
        )
        previous_vertex = vertex
        previous = target
    return points


def _aligned_points(face_ids, first_start_id, second_start_id,
                    second_end_id, second_points):
    """Orient the second cut list to match the first edge in this face."""
    try:
        start_index = face_ids.index(first_start_id)
    except ValueError:
        return second_points
    adjacent = {
        face_ids[(start_index - 1) % len(face_ids)],
        face_ids[(start_index + 1) % len(face_ids)],
    }
    corresponding = next(
        (vertex_id for vertex_id in adjacent
         if vertex_id in {second_start_id, second_end_id}),
        None,
    )
    if corresponding != second_start_id:
        return list(reversed(second_points))
    return second_points


def _find_face_for_split(first_vertex, second_vertex, boundary_ids):
    shared = set(first_vertex.link_faces) & set(second_vertex.link_faces)
    return next(
        (
            face for face in shared
            if face.is_valid
            and all(
                any(vertex.index == vertex_id for vertex in face.verts)
                for vertex_id in boundary_ids
            )
        ),
        None,
    )


def _make_cell_specs(raw_cells):
    """Freeze the identifiers needed after transverse edges are split."""
    cells = []
    edge_lookup = {}
    seen_faces = set()
    for face, first, second, edge_a, edge_b in raw_cells:
        face_ids = tuple(vertex.index for vertex in face.verts)
        face_key = frozenset(face_ids)
        if face_key in seen_faces:
            raise ValueError("目标四边面重复")
        seen_faces.add(face_key)
        boundary_ids = tuple(vertex.index for vertex in first.verts)
        edge_a_key = _edge_key(edge_a)
        edge_b_key = _edge_key(edge_b)
        for edge_key, edge in ((edge_a_key, edge_a), (edge_b_key, edge_b)):
            previous = edge_lookup.get(edge_key)
            if previous is not None and previous is not edge:
                raise ValueError("共享横向边索引不一致")
            edge_lookup[edge_key] = edge
        cells.append({
            "face_ids": face_ids,
            "boundary_ids": boundary_ids,
            "edge_a_key": edge_a_key,
            "edge_b_key": edge_b_key,
            "edge_a_start": edge_a.verts[0].index,
            "edge_b_start": edge_b.verts[0].index,
            "edge_b_end": edge_b.verts[1].index,
        })
    return cells, edge_lookup


def _select_edge_keys(bm, edge_keys):
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    for edge in bm.edges:
        edge.select_set(edge.is_valid and _edge_key(edge) in edge_keys)


def _run_flow_on_new_edges(context, active, edge_keys, mix, iterations):
    """Run EdgeFlow against only the edges generated by this pass."""
    if mix <= 0.0 or not edge_keys:
        return
    bm = bmesh.from_edit_mesh(active.data)
    _select_edge_keys(bm, edge_keys)
    bmesh.update_edit_mesh(
        active.data,
        loop_triangles=False,
        destructive=False,
    )
    apply_edge_flow(
        context,
        mix=max(0.0, min(float(mix), 1.0)),
        iterations=iterations,
    )

class OP_ParallelManifoldSubdivide(Operator):
    bl_idname = "ho.parallel_manifold_subdivide"
    bl_label = "并排流形细分"
    bl_description = "只在选中的并排四边面内插入边，并调用 EdgeFlow 平滑"
    bl_options = {"REGISTER", "UNDO"}

    cuts: IntProperty(
        name="细分数量",
        description="在目标并排面之间插入的边数",
        default=1,
        min=1,
        soft_max=8,
    )  # type: ignore
    iterations: IntProperty(
        name="迭代次数",
        description="以等价切线数量合并执行，避免重复刷新拓扑",
        default=1,
        min=1,
        soft_max=8,
    )  # type: ignore
    flow_mix: FloatProperty(
        name="流形程度",
        description="调用 EdgeFlow 设置新并排边流形的混合强度",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )  # type: ignore
    flow_iterations: IntProperty(
        name="流形迭代",
        description="新并排边调用流形平滑的迭代次数",
        default=1,
        min=1,
        soft_max=16,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        active = getattr(context, "active_object", None)
        mode = getattr(context, "mode", None) or getattr(active, "mode", None)
        return (
            getattr(active, "type", None) == "MESH"
            and mode in {"EDIT_MESH", "EDIT"}
        )

    def draw(self, context):
        self.layout.prop(self, "cuts")
        self.layout.prop(self, "iterations")
        self.layout.prop(self, "flow_mix")
        self.layout.prop(self, "flow_iterations")

    def _effective_cuts(self):
        cuts = max(1, int(self.cuts))
        iterations = max(1, int(self.iterations))
        return cuts * iterations

    def _preflight(self, context):
        """Validate the complete local operation before touching topology."""
        active = getattr(context, "active_object", None)
        if getattr(active, "type", None) != "MESH":
            return None, "当前活动对象不是网格"
        mode = getattr(context, "mode", None) or getattr(active, "mode", None)
        if mode not in {"EDIT_MESH", "EDIT"}:
            return None, "请在网格编辑模式下运行"

        try:
            bm = bmesh.from_edit_mesh(active.data)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            bm.verts.index_update()
            bm.edges.index_update()
            raw_cells = _target_cells(bm)
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            return None, "无法读取当前编辑网格：%s" % error

        if not raw_cells:
            return None, "没有找到由选中并排边夹住的四边面"

        try:
            cells, edge_lookup = _make_cell_specs(raw_cells)
        except ValueError as error:
            return None, str(error)

        if not cells:
            return None, "没有可处理的目标面"
        cuts = self._effective_cuts()
        valid_vertex_indices = set(range(len(bm.verts)))
        for cell in cells:
            if len(cell["face_ids"]) != 4 or len(set(cell["face_ids"])) != 4:
                return None, "目标面不是有效四边面"
            if len(set(cell["boundary_ids"])) != 2:
                return None, "目标并排边端点无效"
            if not set(cell["face_ids"]).issuperset(cell["boundary_ids"]):
                return None, "选中并排边不属于目标面"
            for vertex_id in (
                *cell["face_ids"],
                *cell["boundary_ids"],
                cell["edge_a_start"],
                cell["edge_b_start"],
                cell["edge_b_end"],
            ):
                if vertex_id not in valid_vertex_indices:
                    return None, "目标边引用了无效顶点"

        for edge_key, edge in edge_lookup.items():
            if not edge.is_valid:
                return None, "横向边在预检查期间已失效"
            if len(edge.verts) != 2 or edge_key != _edge_key(edge):
                return None, "横向边端点索引不稳定"
            if len(edge.link_faces) not in {1, 2}:
                return None, "存在非流形横向边"
            start, end = edge.verts
            if (end.co - start.co).length_squared <= 1.0e-12:
                return None, "存在零长度横向边"
            if any(not face.is_valid for face in edge.link_faces):
                return None, "横向边包含失效邻接面"

        for face, first, second, _edge_a, _edge_b in raw_cells:
            for edge in (first, second):
                if not edge.is_valid or len(edge.link_faces) not in {1, 2}:
                    return None, "选中的并排边不是有效流形边"
            if not face.is_valid or len(face.verts) != 4:
                return None, "目标面在预检查期间已失效"

        return {
            "active": active,
            "bm": bm,
            "raw_cells": raw_cells,
            "cells": cells,
            "edge_lookup": edge_lookup,
            "selected_original": {
                _edge_key(edge)
                for cell in raw_cells
                for edge in cell[1:3]
                if edge.is_valid
            },
            "cuts": cuts,
        }, None

    def _run_pass(self, context):
        preflight, reason = self._preflight(context)
        if preflight is None:
            self.report({"WARNING"}, "预检查失败：%s" % reason)
            return {"CANCELLED"}, set()
        active = preflight["active"]
        bm = preflight["bm"]
        cells = preflight["cells"]
        edge_lookup = preflight["edge_lookup"]
        selected_original = preflight["selected_original"]
        cuts = preflight["cuts"]
        bmesh.update_edit_mesh(
            active.data,
            loop_triangles=False,
            destructive=False,
        )
        original_data = active.data.copy()
        new_edge_keys = set()
        try:
            # Split each transverse edge once. Shared edges are reused by all
            # qualifying cells; connector face splits remain target-local.
            split_cache = {}
            for cell in cells:
                for edge_key in (cell["edge_a_key"], cell["edge_b_key"]):
                    if edge_key in split_cache:
                        continue
                    edge = edge_lookup[edge_key]
                    bm.verts.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    # Preserve the edge's actual BMesh orientation.  Using
                    # the sorted key here reverses some shared cube edges and
                    # leaves their face loops in the wrong order for cuts > 1.
                    start_id = edge.verts[0].index
                    end_id = edge.verts[1].index
                    start = bm.verts[start_id]
                    end = bm.verts[end_id]
                    split_cache[edge_key] = (
                        start_id,
                        end_id,
                        _split_edge_at_cuts(edge, start, end, cuts),
                    )

            bm.verts.ensure_lookup_table()
            bm.verts.index_update()
            split_cache = {
                key: (start_id, end_id, [vertex.index for vertex in points])
                for key, (start_id, end_id, points) in split_cache.items()
            }

            # Split from the outside toward the center. face_split then always
            # sees the remaining target strip as one quad/ngon and produces a
            # quad strip, never a diagonal triangulation.
            for cell in cells:
                _start_a, _end_a, points_a = split_cache[cell["edge_a_key"]]
                _start_b, _end_b, points_b = split_cache[cell["edge_b_key"]]
                points_b = _aligned_points(
                    cell["face_ids"],
                    cell["edge_a_start"],
                    cell["edge_b_start"],
                    cell["edge_b_end"],
                    points_b,
                )
                near_boundary = cell["edge_a_start"] in cell["boundary_ids"]
                pairs = list(zip(points_a, points_b))
                if near_boundary:
                    pairs.reverse()
                for vertex_a_id, vertex_b_id in pairs:
                    bm.verts.ensure_lookup_table()
                    bm.edges.ensure_lookup_table()
                    vertex_a = bm.verts[vertex_a_id]
                    vertex_b = bm.verts[vertex_b_id]
                    target_face = _find_face_for_split(
                        vertex_a,
                        vertex_b,
                        cell["boundary_ids"],
                    )
                    if target_face is None:
                        raise RuntimeError("目标面在局部细分期间失效")
                    bmesh.utils.face_split(target_face, vertex_a, vertex_b)
                    edge = next(
                        (
                            item for item in vertex_a.link_edges
                            if item.is_valid and vertex_b in item.verts
                        ),
                        None,
                    )
                    if edge is not None:
                        new_edge_keys.add(_edge_key(edge))

            if not new_edge_keys:
                raise RuntimeError("细分没有生成新的并排边")

            bm.verts.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            for first_id, second_id in new_edge_keys:
                first_vertex = bm.verts[first_id]
                second_vertex = bm.verts[second_id]
                connector_faces = (
                    set(first_vertex.link_faces)
                    & set(second_vertex.link_faces)
                )
                if any(
                    face.is_valid and len(face.verts) != 4
                    for face in connector_faces
                ):
                    raise RuntimeError("局部细分生成了非四边目标面")

            bm.normal_update()
            bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=True)

            if self.flow_mix > 0.0:
                try:
                    _run_flow_on_new_edges(
                        context,
                        active,
                        new_edge_keys,
                        self.flow_mix,
                        self.flow_iterations,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    self.report({"WARNING"}, "新并排边已生成，但自动设置流形失败")

            bm = bmesh.from_edit_mesh(active.data)
            _select_edge_keys(bm, selected_original | new_edge_keys)
            bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=False)
            if original_data.users == 0:
                bpy.data.meshes.remove(original_data)
            return {"FINISHED"}, selected_original | new_edge_keys
        except Exception as error:
            try:
                bm = bmesh.from_edit_mesh(active.data)
                bm.clear()
                bm.from_mesh(original_data)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=True)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            if original_data.users == 0:
                try:
                    bpy.data.meshes.remove(original_data)
                except (RuntimeError, ReferenceError):
                    pass
            self.report({"WARNING"}, "并排流形细分失败：%s" % error)
            return {"CANCELLED"}, set()

    def execute(self, context):
        active = getattr(context, "active_object", None)
        if getattr(active, "type", None) != "MESH":
            return {"CANCELLED"}
        # A second pass would have to rediscover cells after the first pass
        # changed their topology.  Equivalent cuts are calculated up front so
        # the whole invocation remains one local topology transaction.
        result, _selected = self._run_pass(context)
        return result


__all__ = ["OP_ParallelManifoldSubdivide"]
