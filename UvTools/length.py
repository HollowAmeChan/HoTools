"""Fixed-endpoint UV chain spacing proportional to actual 3D edge lengths."""

import bpy

from Utils.mesh_uv import (UVPoint, collect_uv_islands, iter_edit_uv_meshes,
                           selected_uv_edge_loops, uv_edit_poll, write_uv_points)
from Utils.uv_chains import distribute_chain_by_lengths, trace_open_chains


def length_uniformization_plans(context):
    """Plan every chain before writing; keep endpoints and unrelated points exact."""
    plans, count = [], 0
    settings = context.scene.tool_settings
    for obj, bm, uv in iter_edit_uv_meshes(context):
        if settings.use_uv_select_sync and not settings.mesh_select_mode[1] and not (
                settings.uv_select_mode == 'EDGE' and getattr(bm, 'uv_select_sync_valid', False)):
            continue  # legacy/invalid sync needs actual mesh edge selection mode
        edges = selected_uv_edge_loops(bm, uv, settings)
        if not edges:
            continue
        # UV data is shared between instances. Prefer the active instance's
        # world-space metric rather than whichever name was visited first.
        active = context.active_object
        metric_obj = active if active is not None and active.data == obj.data else obj
        basis = metric_obj.matrix_world.to_3x3()
        for island in collect_uv_islands(obj, bm, uv, settings, visible_only=True, split_overlaps=True):
            loop_node = {loop: v for v, loops in enumerate(island.vertex_loops) for loop in loops}
            chosen = {tuple(sorted((loop_node[loop], loop_node[loop.link_loop_next])))
                      for face in island.faces for loop in face.loops if loop in edges}
            if not chosen:
                continue
            chains = trace_open_chains(chosen)
            for chain in chains:
                if len(chain) < 3:
                    continue  # a single edge has no interior point to redistribute
                vertices = [island.vertex_loops[node][0].vert for node in chain]
                lengths = [(basis @ (b.co-a.co)).length for a, b in zip(vertices, vertices[1:])]
                result = distribute_chain_by_lengths([island.coordinates[node] for node in chain], lengths)
                for node, coordinate in zip(chain[1:-1], result[1:-1]):
                    loops = island.vertex_loops[node]
                    plans.append((UVPoint(obj, bm, uv, loops, tuple(loops[0][uv].uv)), coordinate))
                count += 1
    if not count:
        raise ValueError('请选择至少包含两条边的 UV 开链')
    return plans, count


class OP_UVTools_UniformizeLength(bpy.types.Operator):
    bl_idname = 'ho.uvtools_uniformize_length'
    bl_label = 'UV线长度均化'
    bl_description = '保持所选UV开链两端不动，拉直并按对应3D网格边长比例分布中间点；支持多条开链，计入物体缩放'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def execute(self, context):
        settings = context.scene.tool_settings
        if not settings.use_uv_select_sync and settings.uv_select_mode != 'EDGE':
            self.report({'WARNING'}, '请在边选择模式选择需要长度均化的 UV 开链')
            return {'CANCELLED'}
        try:
            plans, _ = length_uniformization_plans(context)
            write_uv_points(plans)
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}
