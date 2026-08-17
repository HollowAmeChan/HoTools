"""MESHmachine-style mesh symmetrize with HoTools modal HUD."""

from math import atan2, pi

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy_extras.view3d_utils import (
    region_2d_to_location_3d,
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
)
from mathutils import Vector

from Utils.hud import draw_mouse_hud_rows
from Utils.symmetrize import symmetrize
from Utils.viewport_draw import draw_point, draw_vector


AXIS_ITEMS = (
    ('X', 'X', '沿 X 轴对称'),
    ('Y', 'Y', '沿 Y 轴对称'),
    ('Z', 'Z', '沿 Z 轴对称'),
)
DIRECTION_ITEMS = (
    ('POSITIVE', '正向', '保留正向一侧并镜像到另一侧'),
    ('NEGATIVE', '负向', '保留负向一侧并镜像到另一侧'),
)
NORMAL_METHOD_ITEMS = (
    ('INDEX', '索引', '按顶点索引配对自定义法线'),
    ('LOCATION', '位置', '按顶点位置配对自定义法线'),
)
FIX_CENTER_ITEMS = (
    ('CLEAR', '清除', '清除中心接缝法线'),
    ('TRANSFER', '传递', '从原始网格传递中心法线'),
)

_DIRECTIONS = (
    'POSITIVE_X', 'POSITIVE_Y', 'NEGATIVE_X',
    'NEGATIVE_Y', 'POSITIVE_Z', 'NEGATIVE_Z',
)
_COLORS = (
    (1.0, 0.2, 0.2), (0.2, 1.0, 0.2), (1.0, 0.2, 0.2),
    (0.2, 1.0, 0.2), (0.2, 0.5, 1.0), (0.2, 0.5, 1.0),
)


def _flick_direction(vector):
    if vector.length < 1e-6:
        return 'NEGATIVE_X'
    angle = atan2(vector.y, vector.x) % (2 * pi)
    sector = int((angle + pi / 6) // (pi / 3)) % 6
    return _DIRECTIONS[sector]


def _flick_axes(matrix):
    basis = matrix.to_3x3()
    return {
        'POSITIVE_X': basis @ Vector((1, 0, 0)),
        'NEGATIVE_X': basis @ Vector((-1, 0, 0)),
        'POSITIVE_Y': basis @ Vector((0, 1, 0)),
        'NEGATIVE_Y': basis @ Vector((0, -1, 0)),
        'POSITIVE_Z': basis @ Vector((0, 0, 1)),
        'NEGATIVE_Z': basis @ Vector((0, 0, -1)),
    }


class Symmetrize(bpy.types.Operator):
    bl_idname = "ho.symmetrize"
    bl_label = "对称化"
    bl_description = "沿指定轴对称化网格，可保留部分选择或删除另一侧"
    bl_options = {'REGISTER', 'UNDO'}

    objmode: BoolProperty(name="对象模式", default=False)
    flick: BoolProperty(name="翻转操作", default=True)
    axis: EnumProperty(name="轴", items=AXIS_ITEMS, default='X')
    direction: EnumProperty(name="方向", items=DIRECTION_ITEMS, default='POSITIVE')
    threshold: FloatProperty(name="阈值", default=0.0001, min=0.0)
    partial: BoolProperty(name="仅选定", default=False)
    remove: BoolProperty(name="删除另一侧", default=False)
    remove_redundant_center: BoolProperty(name="删除冗余中心", default=True)
    is_custom_normal: BoolProperty(default=False, options={'HIDDEN'})
    mirror_custom_normals: BoolProperty(name="镜像自定义法线", default=True)
    custom_normal_method: EnumProperty(
        name="自定义法线配对方法", items=NORMAL_METHOD_ITEMS, default='INDEX'
    )
    fix_center: BoolProperty(name="固定中心接缝", default=False)
    fix_center_method: EnumProperty(
        name="固定中心方法", items=FIX_CENTER_ITEMS, default='CLEAR'
    )
    clear_sharps: BoolProperty(name="清除中心锐化", default=True)

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
        row.prop(self, 'remove', text='删除' if self.remove else '对称', toggle=True)
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

    def _draw_hud(self):
        if self.passthrough:
            return
        color = (1.0, 0.25, 0.25, 1.0) if self.remove else (1.0, 1.0, 1.0, 1.0)
        rows = [
            (0, "模式: ", "删除" if self.remove else "对称", color),
            (24, "方向: ", f"{self.direction} {self.axis}"),
            (48, "仅选定: ", "开" if self.partial else "关"),
            (72, "左键/空格: ", "确认"),
            (96, "右键/Esc: ", "取消"),
            (120, "S/P: ", "切换仅选定"),
            (144, "X/D: ", "切换删除"),
        ]
        draw_mouse_hud_rows((self.mousepos.x, self.mousepos.y), rows)

    def _draw_view(self):
        if self.passthrough:
            return
        for direction, axis, color in zip(self.axes, self.axes.values(), _COLORS):
            positive = direction.startswith('POSITIVE')
            draw_vector(
                axis.normalized() * self.zoom * 0.5,
                origin=self.init_mouse_3d,
                color=color,
                width=2 if positive else 1,
                alpha=0.95 if positive else 0.3,
            )
        draw_point(
            self.init_mouse_3d + self.axes[self.flick_direction] * self.zoom * 0.6,
            color=(1.0, 0.85, 0.2),
            size=5,
        )

    def _get_zoom(self, context):
        center = Vector((context.region.width / 2, context.region.height / 2))
        offset = center + Vector((self.flick_distance, 0))
        try:
            a = region_2d_to_location_3d(
                context.region, context.region_data, center, self.origin
            )
            b = region_2d_to_location_3d(
                context.region, context.region_data, offset, self.origin
            )
            return max((a - b).length, 1e-5)
        except Exception:
            return 1.0

    def modal(self, context, event):
        context.area.tag_redraw()
        self.mousepos = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'MOUSEMOVE':
            self.passthrough = False
            self.flick_vector = self.mousepos - self.init_mouse
            if self.flick_vector.length:
                self.flick_direction = _flick_direction(self.flick_vector)
                self.direction, self.axis = self.flick_direction.split('_')
            if self.flick_vector.length > self.flick_distance:
                self.finish()
                return self.execute(context)
        elif event.type in {'X', 'D'} and event.value == 'PRESS':
            self.remove = not self.remove
        elif event.type in {'S', 'P'} and event.value == 'PRESS':
            self.partial = not self.partial
        elif event.type in {'LEFTMOUSE', 'SPACE'} and event.value == 'PRESS':
            self.finish()
            self.direction, self.axis = self.flick_direction.split('_')
            return self.execute(context)
        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.finish()
            return {'CANCELLED'}
        elif event.type == 'MIDDLEMOUSE' or event.alt:
            self.passthrough = True
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def finish(self):
        for name in ('HUD', 'VIEW3D'):
            handler = getattr(self, name, None)
            if handler:
                bpy.types.SpaceView3D.draw_handler_remove(handler, 'WINDOW')
                setattr(self, name, None)

    def invoke(self, context, event):
        if not self.flick:
            return self.execute(context)
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
        self.zoom = self._get_zoom(context)
        self.init_mouse = self.mousepos.copy()
        self.init_mouse_3d = region_2d_to_location_3d(
            context.region, context.region_data, self.init_mouse, self.origin
        )
        self.flick_vector = Vector((0.0, 0.0))
        self.flick_direction = 'NEGATIVE_X'
        self.axes = _flick_axes(context.active_object.matrix_world)
        self.passthrough = False
        self.area = context.area
        self.HUD = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (), 'WINDOW', 'POST_PIXEL'
        )
        self.VIEW3D = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_view, (), 'WINDOW', 'POST_VIEW'
        )
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
