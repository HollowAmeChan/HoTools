"""AABB unstacking and a one-tile baking offset, without changing island shape."""

import bpy
from bpy.props import EnumProperty, FloatProperty
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from Utils.mesh_uv import UVPoint, collect_uv_islands, iter_edit_uv_meshes, uv_edit_poll, write_uv_points
from Utils.uv_math import unstack_offsets
from Utils.uv_overlap import overlap_workspaces


def _island_triangles(island):
    triangles = []
    for face in island.faces:
        points = [Vector((*loop[island.uv_layer].uv, 0.0)) for loop in face.loops]
        triangles.extend(tuple((points[index].x, points[index].y) for index in triangle)
                         for triangle in tessellate_polygon([points]))
    return triangles


class OP_UVTools_Unstack(bpy.types.Operator):
    bl_idname = 'ho.uvtools_unstack'
    bl_label = '取消堆叠 UV 岛'
    bl_description = ('按实际重叠将所选 UV 岛划分工作区，再按区分别取消堆叠；'
                      '每区保留首岛，横向/纵向按 AABB 排开，跨象限将区内其余岛统一平移 +1U')
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name='排列模式', items=(
        ('HORIZONTAL', '横向排列', '每区首岛不动，区内其他岛按 AABB 向右依次排开'),
        ('VERTICAL', '纵向排列', '每区首岛不动，区内其他岛按 AABB 向上依次排开'),
        ('TILE', '跨象限', '每区首岛保留原位，区内其他岛保持相对位置统一平移 +1U'),
    ), default='HORIZONTAL')  # type: ignore
    gap: FloatProperty(name='岛间距', default=.01, min=0, soft_max=.25,
                       description='横向或纵向排列时相邻 AABB 的 UV 间距')  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def draw(self, context):
        self.layout.prop(self, 'mode', expand=True)
        self.layout.label(text='按重叠工作区分别处理，每区保留首岛')
        if self.mode == 'TILE':
            self.layout.label(text='各区首岛保留原位，区内其余岛统一平移 +1U')
        else:
            self.layout.prop(self, 'gap')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def execute(self, context):
        islands, preferred = [], None
        for obj, bm, uv in iter_edit_uv_meshes(context):
            active_face = bm.faces.active
            for island in collect_uv_islands(obj, bm, uv, context.scene.tool_settings,
                                             visible_only=True, split_overlaps=True):
                if not island.selected:
                    continue
                islands.append(island)
                if obj.data == context.active_object.data and active_face in island.faces:
                    preferred = island
        islands.sort(key=lambda island: (
            island is not preferred,
            island.obj.data != context.active_object.data,
            island.key,
        ))
        if not islands:
            self.report({'WARNING'}, '没有选中的可见 UV 岛')
            return {'CANCELLED'}
        try:
            workspaces = overlap_workspaces(_island_triangles(island) for island in islands)
            plans, moved = [], 0
            for workspace in workspaces:
                members = [islands[index] for index in workspace]
                offsets = unstack_offsets([island.coordinates for island in members], self.mode, self.gap)
                for island, (dx, dy) in zip(members, offsets):
                    if dx == 0 and dy == 0:
                        continue
                    moved += 1
                    for loops in island.vertex_loops:
                        for loop in loops:
                            # Keep each actual corner's value, including sub-tolerance
                            # differences: baking mode is strictly a translation.
                            coordinate = tuple(loop[island.uv_layer].uv)
                            point = UVPoint(island.obj, island.bm, island.uv_layer, (loop,), coordinate)
                            plans.append((point, (coordinate[0]+dx, coordinate[1]+dy)))
            write_uv_points(plans)
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'{len(islands)} 岛 / {len(workspaces)} 工作区，取消堆叠移动 {moved} 岛；各区首岛保留原位')
        return {'FINISHED'}
