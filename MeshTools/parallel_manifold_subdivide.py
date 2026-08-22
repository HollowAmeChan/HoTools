"""Insert parallel manifold edges only inside the selected quad strip cells."""

import bmesh
import bpy
from bpy.props import FloatProperty, IntProperty
from bpy.types import Operator


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
        if any(
            any(
                linked_face is not face
                and linked_face.is_valid
                and len(linked_face.verts) != 4
                for linked_face in edge.link_faces
            )
            for edge in transverse
        ):
            # Splitting a transverse edge also touches its neighboring face;
            # do not let a triangle/Ngon participate in a quad-only pass.
            continue
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
        max=32,
        soft_max=8,
    )  # type: ignore
    iterations: IntProperty(
        name="迭代次数",
        description="以等价切线数量合并执行，避免重复刷新拓扑",
        default=1,
        min=1,
        max=8,
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

    def _effective_cuts(self):
        cuts = max(1, min(int(self.cuts), 32))
        iterations = max(1, min(int(self.iterations), 8))
        total = 1
        for _ in range(iterations):
            total *= cuts + 1
            if total > 33:
                return 32
        return max(1, total - 1)

    def _run_pass(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()

        raw_cells = _target_cells(bm)
        if not raw_cells:
            self.report({"WARNING"}, "没有找到由选中并排边夹住的四边面")
            return {"CANCELLED"}, set()

        cells = []
        edge_lookup = {}
        for face, first, second, edge_a, edge_b in raw_cells:
            face_ids = tuple(vertex.index for vertex in face.verts)
            boundary_ids = tuple(vertex.index for vertex in first.verts)
            edge_a_key = _edge_key(edge_a)
            edge_b_key = _edge_key(edge_b)
            edge_lookup[edge_a_key] = edge_a
            edge_lookup[edge_b_key] = edge_b
            cells.append({
                "face_ids": face_ids,
                "boundary_ids": boundary_ids,
                "edge_a_key": edge_a_key,
                "edge_b_key": edge_b_key,
                "edge_a_start": edge_a.verts[0].index,
                "edge_b_start": edge_b.verts[0].index,
                "edge_b_end": edge_b.verts[1].index,
            })

        selected_original = {
            _edge_key(edge)
            for cell in raw_cells
            for edge in cell[1:3]
            if edge.is_valid
        }
        bmesh.update_edit_mesh(
            active.data,
            loop_triangles=False,
            destructive=False,
        )
        original_data = active.data.copy()
        cuts = self._effective_cuts()
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

            bm.edges.ensure_lookup_table()
            for edge in bm.edges:
                edge.select_set(False)
            for edge in bm.edges:
                if edge.is_valid and _edge_key(edge) in new_edge_keys:
                    edge.select_set(True)
            bm.normal_update()
            bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=True)

            # The custom local smoother is intentionally disabled.  EdgeFlow
            # runs only after topology is flushed and reacquires the edit BM.
            if self.flow_mix > 0.0:
                try:
                    bpy.ops.ho.set_edge_flow(
                        "EXEC_DEFAULT",
                        mix=max(0.0, min(float(self.flow_mix), 1.0)),
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    self.report({"WARNING"}, "新并排边已生成，但自动设置流形失败")

            bm = bmesh.from_edit_mesh(active.data)
            bm.edges.ensure_lookup_table()
            for edge in bm.edges:
                edge.select_set(
                    edge.is_valid and _edge_key(edge) in (selected_original | new_edge_keys)
                )
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
