"""AABB unstacking and a one-tile baking offset, without changing island shape."""

import bpy
from bpy.props import EnumProperty, FloatProperty

from Utils.mesh_uv import UVPoint, collect_uv_islands, iter_edit_uv_meshes, uv_edit_poll, write_uv_points
from Utils.uv_math import unstack_offsets


class OP_UVTools_Unstack(bpy.types.Operator):
    bl_idname = 'ho.uvtools_unstack'
    bl_label = '取消堆叠 UV 岛'
    bl_description = ('取消堆栈：将所选可见 UV 岛按 AABB 横向或纵向排开；'
                      '跨象限模式保留首岛，其他所有岛统一平移 +1U，供烘焙使用')
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(name='排列模式', items=(
        ('HORIZONTAL', '横向排列', '首岛不动，其他岛按 AABB 向右依次排开'),
        ('VERTICAL', '纵向排列', '首岛不动，其他岛按 AABB 向上依次排开'),
        ('TILE', '跨象限', '首岛保留原位，其他岛保持相对位置统一平移 +1U，移出当前烘焙象限'),
    ), default='HORIZONTAL')  # type: ignore
    gap: FloatProperty(name='岛间距', default=.01, min=0, soft_max=.25,
                       description='横向或纵向排列时相邻 AABB 的 UV 间距')  # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def draw(self, context):
        self.layout.prop(self, 'mode', expand=True)
        if self.mode == 'TILE':
            self.layout.label(text='首岛保留原位，其他所有岛统一平移 +1U')
        else:
            self.layout.prop(self, 'gap')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=380)

    def execute(self, context):
        islands, preferred = [], None
        for obj, bm, uv in iter_edit_uv_meshes(context):
            active_face = bm.faces.active
            for island in collect_uv_islands(obj, bm, uv, context.scene.tool_settings, visible_only=True):
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
        if len(islands) < 2:
            self.report({'WARNING'}, '请至少选择两个可见 UV 岛')
            return {'CANCELLED'}
        try:
            offsets = unstack_offsets([island.coordinates for island in islands], self.mode, self.gap)
            plans = []
            for island, (dx, dy) in zip(islands, offsets):
                if dx == 0 and dy == 0:
                    continue
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
        first = islands[0]
        self.report({'INFO'}, f'取消堆叠 {len(islands)} 岛；首岛 {first.obj.name} / 面 {first.faces[0].index} 保留原位')
        return {'FINISHED'}
