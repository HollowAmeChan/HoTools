"""Topology stacking: copy every matching UV vertex onto a group's master."""

from collections import Counter
from math import isfinite
from struct import pack, unpack

import bmesh
import bpy
from bpy.props import FloatProperty

from Utils.mesh_uv import collect_uv_islands, iter_edit_uv_meshes
from Utils.uv_topology import IslandTopology, MatchBudgetExceeded, TopologyError, match_islands


def _keep_stack_islands_separate(plans, islands, gap):
    """Preserve native Blender UV components when mesh vertices are shared.

    Blender has no independent UV vertex connectivity flag: coincident corners
    on a shared mesh vertex reconnect. Only collision-prone islands receive a
    tiny uniform translation, keeping their internal topology/shape unchanged.
    Unrelated geometry continues to stack with bit-exact coordinates.
    """
    proposed = {id(island): coordinates for island, coordinates in plans}
    by_vertex = {}
    for island in islands:
        coordinates = proposed.get(id(island), island.coordinates)
        for node, (loops, coordinate) in enumerate(zip(island.vertex_loops, coordinates)):
            by_vertex.setdefault(loops[0].vert, {})[(id(island), node)] = coordinate

    def rounded(coordinates):
        return tuple(tuple(unpack('f', pack('f', value))[0] for value in point) for point in coordinates)

    def collides(island, coordinates):
        for loops, point in zip(island.vertex_loops, coordinates):
            for (other_island, node), other in by_vertex[loops[0].vert].items():
                if other_island != id(island) and max(abs(point[a]-other[a]) for a in (0, 1)) <= 1.05e-4:
                    return True
        return False

    result, separated = [], 0
    for island, coordinates in plans:
        coordinates = rounded(coordinates)
        if collides(island, coordinates):
            step = max(gap, max(abs(v) for point in coordinates for v in point) * 2**-21)
            found = None
            for radius in range(1, 65):
                for dx, dy in ((radius*step, 0), (-radius*step, 0), (0, radius*step), (0, -radius*step)):
                    candidate = rounded(tuple((x+dx, y+dy) for x, y in coordinates))
                    if all(all(isfinite(v) for v in point) for point in candidate) and not collides(island, candidate):
                        found = candidate
                        break
                if found is not None:
                    break
            if found is None:
                raise ValueError('相邻堆叠岛过多，无法保持断开；请增大最小分离量')
            coordinates = found
            separated += 1
        for node, (loops, coordinate) in enumerate(zip(island.vertex_loops, coordinates)):
            by_vertex[loops[0].vert][(id(island), node)] = coordinate
        result.append((island, coordinates))
    return result, separated


class OP_UVTools_TopologyStack(bpy.types.Operator):
    bl_idname = 'ho.uvtools_topology_stack'
    bl_label = '拓扑堆叠'
    bl_description = ('将所选 UV 所在的同形状、同点数且拓扑对应的完整岛分组，'
                      '把所有顶点强制对齐到主岛；自动识别镜像并保留原岛断开，活动面所在岛优先作为主岛')
    bl_options = {'REGISTER', 'UNDO'}

    shape_tolerance: FloatProperty(
        name='形状容差',
        description='统一尺寸并匹配旋转/镜像后，边界点最大偏差占主岛边界包围盒对角线的比例；内部点按拓扑强制对齐',
        default=0.05, min=0.0, max=0.5, subtype='FACTOR',
    )  # type: ignore
    separation_distance: FloatProperty(
        name='最小分离量', default=.000125, min=.000125, soft_max=.001, precision=6,
        description='仅对共享网格顶点且会粘连的岛作微量整体偏移，保持原 UV 岛独立；其他岛精确重合',
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH'
                and getattr(context.area, 'type', None) == 'IMAGE_EDITOR'
                and getattr(context.area, 'ui_type', None) == 'UV'
                and context.active_object is not None
                and context.active_object.type == 'MESH')

    def execute(self, context):
        settings = context.scene.tool_settings
        candidates, rejected, all_islands = [], Counter(), []
        preferred = None
        for obj, bm, uv in iter_edit_uv_meshes(context):
            active_face = bm.faces.active
            for island in collect_uv_islands(obj, bm, uv, settings):
                all_islands.append(island)
                if not island.selected:
                    continue
                if not island.complete:
                    rejected['隐藏或未完整显示'] += 1
                    continue
                try:
                    topology = IslandTopology(island.coordinates, island.polygons)
                except TopologyError as exc:
                    rejected[str(exc)] += 1
                    continue
                candidates.append((island, topology))
                if obj.data == context.active_object.data and active_face in island.faces:
                    preferred = island
        candidates.sort(key=lambda pair: (
            pair[0] is not preferred,
            pair[0].obj.data != context.active_object.data,
            pair[0].key,
        ))
        if len(candidates) < 2:
            detail = '；'.join(f'{reason} {count} 岛' for reason, count in rejected.items())
            self.report({'WARNING'}, '需要至少两个可匹配的完整 UV 岛' + ('；' + detail if detail else ''))
            return {'CANCELLED'}

        plans, groups, reflected, unmatched = [], [], 0, 0
        while candidates:
            master, master_topology = candidates.pop(0)
            remaining, group_count = [], 0
            for island, topology in candidates:
                try:
                    match = match_islands(topology, master_topology, self.shape_tolerance)
                except MatchBudgetExceeded as exc:
                    # Nothing has been written yet, so cancellation is atomic.
                    self.report({'WARNING'}, str(exc))
                    return {'CANCELLED'}
                if match is None:
                    remaining.append((island, topology))
                    continue
                plans.append((island, tuple(master.coordinates[index] for index in match.mapping)))
                reflected += match.reflected
                group_count += 1
            if group_count:
                groups.append(master)
            else:
                unmatched += 1
            candidates = remaining
        if not plans:
            self.report({'WARNING'}, '没有同形状、同点数且拓扑对应的岛；可在操作面板调整形状容差')
            return {'CANCELLED'}

        try:
            plans, separated = _keep_stack_islands_separate(plans, all_islands, self.separation_distance)
        except (ValueError, OverflowError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}

        changed = {}
        original = [(loop, island.uv_layer, tuple(loop[island.uv_layer].uv))
                    for island, _ in plans for loops in island.vertex_loops for loop in loops]
        try:
            for island, coordinates in plans:
                changed[island.obj.data.as_pointer()] = island.obj.data
                for loops, coordinate in zip(island.vertex_loops, coordinates):
                    for loop in loops:
                        loop[island.uv_layer].uv = coordinate
            for mesh in changed.values():
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        except Exception as exc:
            for loop, uv_layer, coordinate in original:
                loop[uv_layer].uv = coordinate
            for mesh in changed.values():
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            self.report({'ERROR'}, f'拓扑堆叠已回滚：{exc}')
            return {'CANCELLED'}
        detail = '；'.join(f'{reason} {count} 岛' for reason, count in rejected.items())
        first = groups[0]
        self.report({'INFO'}, f'拓扑堆叠 {len(plans)} 岛 / {len(groups)} 组，镜像匹配 {reflected} 岛；'
                    f'首组主岛 {first.obj.name} / 面 {first.faces[0].index}；未匹配 {unmatched} 岛；分离修正 {separated} 岛'
                    + ('；' + detail if detail else ''))
        return {'FINISHED'}
