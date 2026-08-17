"""MESHmachine-style symmetrize with the HoTools shortcut workflow."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d,
    region_2d_to_location_3d,
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
)
from mathutils import Vector

from Utils.symmetrize import symmetrize


AXIS_ITEMS = (
    ('X', 'X', '沿 X 轴对称化'),
    ('Y', 'Y', '沿 Y 轴对称化'),
    ('Z', 'Z', '沿 Z 轴对称化'),
)
DIRECTION_ITEMS = (
    ('POSITIVE', '正向', '保留正向一侧'),
    ('NEGATIVE', '负向', '保留负向一侧'),
)
NORMAL_METHOD_ITEMS = (
    ('INDEX', '索引', '按顶点索引配对自定义法线'),
    ('LOCATION', '位置', '按顶点位置配对自定义法线'),
)
FIX_CENTER_ITEMS = (
    ('CLEAR', '清除', '清除中心接缝法线'),
    ('TRANSFER', '传递', '传递中心接缝法线'),
)


def _flick_direction(operator, context):
    """Match MESHmachine by comparing the flick with projected object axes."""
    origin_2d = location_3d_to_region_2d(
        context.region,
        context.region_data,
        operator.init_mouse_3d,
        default=Vector((context.region.width / 2, context.region.height / 2)),
    )
    projected_axes = {}
    for direction, axis in operator.axes.items():
        axis_2d = location_3d_to_region_2d(
            context.region,
            context.region_data,
            operator.init_mouse_3d + axis,
            default=origin_2d,
        )
        delta = axis_2d - origin_2d
        if delta.length > 1e-6:
            projected_axes[direction] = delta.normalized()
    if not projected_axes or operator.flick_vector.length < 1e-6:
        return 'NEGATIVE_X'
    return min(
        (
            (direction, abs(operator.flick_vector.xy.angle_signed(axis)))
            for direction, axis in projected_axes.items()
        ),
        key=lambda item: item[1],
    )[0]


def _symmetrize_direction(flick_direction):
    direction, axis = flick_direction.split('_')
    return ('NEGATIVE' if direction == 'POSITIVE' else 'POSITIVE', axis)


def _object_axes(matrix):
    basis = matrix.to_quaternion()
    return {
        'POSITIVE_X': basis @ Vector((1, 0, 0)),
        'NEGATIVE_X': basis @ Vector((-1, 0, 0)),
        'POSITIVE_Y': basis @ Vector((0, 1, 0)),
        'NEGATIVE_Y': basis @ Vector((0, -1, 0)),
        'POSITIVE_Z': basis @ Vector((0, 0, 1)),
        'NEGATIVE_Z': basis @ Vector((0, 0, -1)),
    }


class OP_Symmetrize(bpy.types.Operator):
    bl_idname = 'ho.symmetrize'
    bl_label = '对称化'
    bl_description = '使用 Alt-X 径向操作对当前网格进行对称化'
    bl_options = {'REGISTER', 'UNDO'}

    objmode: BoolProperty(name='对象模式', default=False)  # type: ignore
    flick: BoolProperty(name='径向操作', default=True)  # type: ignore
    axis: EnumProperty(name='轴', items=AXIS_ITEMS, default='X')  # type: ignore
    direction: EnumProperty(name='方向', items=DIRECTION_ITEMS, default='POSITIVE')  # type: ignore
    threshold: FloatProperty(name='阈值', default=0.0001, min=0.0)  # type: ignore
    partial: BoolProperty(name='仅选定', default=False)  # type: ignore
    remove: BoolProperty(name='删除另一侧', default=False)  # type: ignore
    remove_redundant_center: BoolProperty(name='删除冗余中心', default=True)  # type: ignore
    is_custom_normal: BoolProperty(default=False, options={'HIDDEN'})  # type: ignore
    mirror_custom_normals: BoolProperty(name='镜像自定义法线', default=True)  # type: ignore
    custom_normal_method: EnumProperty(
        name='自定义法线配对', items=NORMAL_METHOD_ITEMS, default='INDEX'
    )  # type: ignore
    fix_center: BoolProperty(name='固定中心接缝', default=False)  # type: ignore
    fix_center_method: EnumProperty(
        name='中心修复方法', items=FIX_CENTER_ITEMS, default='CLEAR'
    )  # type: ignore
    clear_sharps: BoolProperty(name='清除中心锐边', default=True)  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and context.active_object is not None
            and context.active_object.type == 'MESH'
            and context.mode in {'EDIT_MESH', 'OBJECT'}
        )

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.prop(self, 'partial', text='仅选定', toggle=True)
        row.prop(self, 'remove', text='删除' if self.remove else '对称化', toggle=True)
        row = layout.row(align=True)
        row.prop(self, 'axis', expand=True)
        row.prop(self, 'direction', expand=True)
        layout.prop(self, 'threshold')
        if not self.remove and not self.partial:
            if self.is_custom_normal:
                layout.prop(self, 'mirror_custom_normals')
                if self.mirror_custom_normals:
                    layout.prop(self, 'custom_normal_method', expand=True)
                    layout.prop(self, 'fix_center')
                    if self.fix_center:
                        layout.prop(self, 'fix_center_method', expand=True)
                        layout.prop(self, 'clear_sharps')
            else:
                layout.prop(self, 'remove_redundant_center')

    def modal(self, context, event):
        context.area.tag_redraw()
        self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))

        if event.type == 'MOUSEMOVE':
            self.passthrough = False
            self.flick_vector = self.mousepos - self.init_mouse
            if self.flick_vector.length:
                self.flick_direction = _flick_direction(self, context)
                self.direction, self.axis = _symmetrize_direction(self.flick_direction)
            if self.flick_vector.length > self.flick_distance:
                return self.execute(context)

        elif event.type in {'X', 'D'} and event.value == 'PRESS':
            self.remove = not self.remove
        elif event.type in {'S', 'P'} and event.value == 'PRESS':
            self.partial = not self.partial
        elif event.type in {'LEFTMOUSE', 'SPACE'} and event.value == 'PRESS':
            self.direction, self.axis = _symmetrize_direction(self.flick_direction)
            return self.execute(context)
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            return {'CANCELLED'}
        elif event.type == 'MIDDLEMOUSE' or (
            event.alt and event.type in {'LEFTMOUSE', 'RIGHTMOUSE'}
        ) or event.type.startswith('NDOF'):
            self.passthrough = True
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if not self.flick:
            return self.execute(context)

        active = context.active_object
        self.scale = context.preferences.system.ui_scale
        self.flick_distance = 75.0 * self.scale
        self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))
        view_origin = region_2d_to_origin_3d(
            context.region, context.region_data, self.mousepos
        )
        view_dir = region_2d_to_vector_3d(
            context.region, context.region_data, self.mousepos
        )
        self.origin = view_origin + view_dir * 10.0
        self.init_mouse = self.mousepos.copy()
        self.init_mouse_3d = region_2d_to_location_3d(
            context.region, context.region_data, self.init_mouse, self.origin
        )
        self.flick_vector = Vector((0.0, 0.0))
        self.flick_direction = 'NEGATIVE_X'
        self.axes = _object_axes(active.matrix_world)
        self.passthrough = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        active = context.active_object
        self.is_custom_normal = bool(getattr(active.data, 'has_custom_normals', False))
        was_object_mode = context.mode == 'OBJECT'
        if was_object_mode:
            bpy.ops.object.mode_set(mode='EDIT')
        self.result = symmetrize(
            active,
            direction=f'{self.direction}_{self.axis}',
            threshold=self.threshold,
            partial=self.partial,
            remove=self.remove,
            remove_redundant_center=self.remove_redundant_center,
            mirror_custom_normals=self.mirror_custom_normals,
            custom_normal_method=self.custom_normal_method,
            fix_center=self.fix_center,
            fix_center_method=self.fix_center_method,
            clear_sharps=self.clear_sharps,
        )
        if was_object_mode:
            bpy.ops.object.mode_set(mode='OBJECT')
        return {'FINISHED'}
