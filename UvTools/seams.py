"""Append seams from every selected mesh's own active UV layer."""

import bmesh
import bpy

from Utils.mesh_uv import uv_boundary_edges


def _seam_plans(context):
    """Read first; retain edit BMesh owners and never round-trip object meshes."""
    plans, seen = [], set()
    for obj in sorted(context.selected_objects, key=lambda item: item.name):
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        key = mesh.as_pointer()
        if key in seen or not mesh.is_editable:
            continue
        seen.add(key)
        if mesh.is_editmode:
            bm = bmesh.from_edit_mesh(mesh)
            uv = bm.loops.layers.uv.active
            if uv is not None:
                plans.append((mesh, bm, tuple(edge for edge in uv_boundary_edges(bm, uv) if not edge.seam)))
        elif mesh.uv_layers.active is not None:
            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                bm.edges.index_update()
                uv = bm.loops.layers.uv.get(mesh.uv_layers.active.name)
                if uv is not None:
                    edges = tuple(mesh.edges[edge.index] for edge in uv_boundary_edges(bm, uv)
                                  if not mesh.edges[edge.index].use_seam)
                    plans.append((mesh, None, edges))
            finally:
                bm.free()
    return plans


def _update_mesh(mesh):
    if mesh.is_editmode:
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        mesh.update()


class OP_UVTools_SeamsFromIslands(bpy.types.Operator):
    bl_idname = 'ho.uvtools_seams_from_islands'
    bl_label = 'UV岛边界标记缝合边'
    bl_description = '将所选网格各自活动UV层的全部岛边界标记为缝合边，用于复用UV分割；包含隐藏和未选中的面'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_MESH'} and any(
            obj.type == 'MESH' and obj.data.is_editable and obj.data.uv_layers.active is not None
            for obj in context.selected_objects)

    def execute(self, context):
        original, changed = [], []
        try:
            plans = _seam_plans(context)
            for mesh, bm, edges in plans:
                if not edges:
                    continue
                changed.append(mesh)
                attribute = 'seam' if bm is not None else 'use_seam'
                for edge in edges:
                    original.append((edge, attribute))
                    setattr(edge, attribute, True)
            for mesh in changed:
                _update_mesh(mesh)
        except Exception as exc:
            for edge, attribute in original:
                setattr(edge, attribute, False)
            for mesh in changed:
                _update_mesh(mesh)
            self.report({'ERROR'}, f'UV边界标记失败，已恢复：{exc}')
            return {'CANCELLED'}
        return {'FINISHED'}
