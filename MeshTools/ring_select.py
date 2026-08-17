"""Add/remove parallel edge rings."""

import bmesh
import bpy
from bpy.types import Operator


def _quad_opposite_edge(edge, face):
    if len(face.edges) != 4:
        return None
    for other in face.edges:
        if other is not edge and not any(vertex in edge.verts for vertex in other.verts):
            return other
    return None


class OP_AddSelectSideRingLoops(Operator):
    bl_idname = 'ho.addselect_sideringloops'
    bl_label = '增加并排环线'
    bl_description = '选择当前环线两侧并排的环线'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
            and context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        active = context.active_object
        bpy.ops.mesh.loop_multi_select(ring=False)
        bm = bmesh.from_edit_mesh(active.data)
        bm.edges.ensure_lookup_table()
        selected_edges = [edge for edge in bm.edges if edge.select]
        if not selected_edges:
            return {'CANCELLED'}
        side_edges = set()
        for edge in selected_edges:
            for face in edge.link_faces:
                opposite = _quad_opposite_edge(edge, face)
                if opposite is not None:
                    side_edges.add(opposite)
        for edge in side_edges:
            edge.select_set(True)
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}


class OP_RemoveSelectSideRingLoops(Operator):
    bl_idname = 'ho.removeselect_sideringloops'
    bl_label = '减少并排环线'
    bl_description = '移除没有形成完整并排关系的环线边'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None
            and context.active_object.type == 'MESH'
            and context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        active = context.active_object
        bm = bmesh.from_edit_mesh(active.data)
        bm.edges.ensure_lookup_table()
        selected_edges = {edge for edge in bm.edges if edge.select}
        if not selected_edges:
            return {'CANCELLED'}
        ring_neighbors = {edge: set() for edge in selected_edges}
        for edge in selected_edges:
            for face in edge.link_faces:
                opposite = _quad_opposite_edge(edge, face)
                if opposite in selected_edges:
                    ring_neighbors[edge].add(opposite)
        for edge, neighbors in ring_neighbors.items():
            if len(neighbors) <= 1:
                edge.select_set(False)
        bmesh.update_edit_mesh(active.data)
        return {'FINISHED'}
