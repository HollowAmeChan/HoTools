"""Insert parallel manifold edges between connected selected edge loops."""

import bmesh
import bpy
from bpy.types import Operator
from bpy.props import FloatProperty, IntProperty


def _selected_edge_components(edges):
    """Return connected components of selected edges, joined at shared verts."""
    remaining = set(edges)
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        frontier = [seed]
        while frontier:
            edge = frontier.pop()
            linked = {
                other
                for vertex in edge.verts
                for other in vertex.link_edges
                if other in remaining
            }
            remaining.difference_update(linked)
            component.update(linked)
            frontier.extend(linked)
        components.append(component)
    return components


def _opposite_selected_edges(face):
    selected = [edge for edge in face.edges if edge.select]
    if len(selected) != 2:
        return None
    first, second = selected
    if any(vertex in first.verts for vertex in second.verts):
        return None
    return first, second


class OP_ParallelManifoldSubdivide(Operator):
    bl_idname = "ho.parallel_manifold_subdivide"
    bl_label = "并排流形细分"
    bl_description = "在相连的并排选中边之间插入边，并自动设置新边流形"
    bl_options = {"REGISTER", "UNDO"}

    cuts: IntProperty(
        name="细分数量",
        description="在两条并排边之间插入的边数",
        default=1,
        min=1,
        soft_max=8,
    ) # type: ignore
    flow_mix: FloatProperty(
        name="流形程度",
        description="新边应用流形计算结果的程度",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        active = getattr(context, "active_object", None)
        return (
            getattr(context, "mode", None) == "EDIT_MESH"
            and getattr(active, "type", None) == "MESH"
        )

    def draw(self, context):
        self.layout.prop(self, "cuts")
        self.layout.prop(self, "flow_mix")

    def execute(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        selected_edges = [edge for edge in bm.edges if edge.select]
        if not selected_edges:
            self.report({"WARNING"}, "请先选择相连的并排边")
            return {"CANCELLED"}

        components = _selected_edge_components(selected_edges)
        component_by_edge = {
            edge: index
            for index, component in enumerate(components)
            for edge in component
        }

        # Each qualifying quad is a strip cell bounded by two selected,
        # opposite edges from different connected edge components. Splitting
        # its other two edges creates the new parallel edge in that cell.
        cross_edges = set()
        for face in bm.faces:
            if len(face.verts) != 4:
                continue
            pair = _opposite_selected_edges(face)
            if pair is None:
                continue
            first, second = pair
            if component_by_edge.get(first) == component_by_edge.get(second):
                continue
            cross_edges.update(
                edge for edge in face.edges
                if edge is not first and edge is not second
            )

        if not cross_edges:
            self.report(
                {"WARNING"},
                "没有找到相连的并排四边面选区",
            )
            return {"CANCELLED"}

        original_edges = set(bm.edges)
        cross_segments = [
            (edge.verts[0].co.copy(), edge.verts[1].co.copy())
            for edge in cross_edges
        ]
        result = bmesh.ops.subdivide_edges(
            bm,
            edges=list(cross_edges),
            cuts=self.cuts,
            use_grid_fill=True,
        )
        new_verts = {
            element for element in result.get("geom_split", ())
            if isinstance(element, bmesh.types.BMVert)
        }

        def source_edge_index(vertex):
            point = vertex.co
            for index, (start, end) in enumerate(cross_segments):
                direction = end - start
                length_squared = direction.length_squared
                if length_squared <= 1.0e-12:
                    continue
                factor = (point - start).dot(direction) / length_squared
                if factor < -1.0e-5 or factor > 1.0 + 1.0e-5:
                    continue
                projected = start + direction * factor
                if (projected - point).length <= 1.0e-5:
                    return index
            return None

        source_by_vertex = {
            vertex: source_edge_index(vertex)
            for vertex in new_verts
        }
        new_edges = {
            edge for edge in bm.edges
            if edge not in original_edges
            and all(vertex in new_verts for vertex in edge.verts)
            and source_by_vertex.get(edge.verts[0]) !=
            source_by_vertex.get(edge.verts[1])
        }
        if not new_edges:
            self.report({"WARNING"}, "细分没有生成新的并排边")
            return {"CANCELLED"}

        for edge in bm.edges:
            edge.select_set(False)
        for edge in new_edges:
            edge.select_set(True)
        bm.normal_update()
        bmesh.update_edit_mesh(active.data, loop_triangles=False, destructive=True)

        try:
            bpy.ops.ho.set_edge_flow("EXEC_DEFAULT", mix=self.flow_mix)
        except (AttributeError, RuntimeError, TypeError):
            self.report({"WARNING"}, "新并排边已生成，但自动设置流形失败")
        return {"FINISHED"}


__all__ = ["OP_ParallelManifoldSubdivide"]
