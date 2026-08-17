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
    ('X', 'X', 'Symmetrize along X'),
    ('Y', 'Y', 'Symmetrize along Y'),
    ('Z', 'Z', 'Symmetrize along Z'),
)
DIRECTION_ITEMS = (
    ('POSITIVE', 'Positive', 'Keep the positive side'),
    ('NEGATIVE', 'Negative', 'Keep the negative side'),
)
NORMAL_METHOD_ITEMS = (
    ('INDEX', 'Index', 'Pair custom normals by vertex index'),
    ('LOCATION', 'Location', 'Pair custom normals by vertex location'),
)
FIX_CENTER_ITEMS = (
    ('CLEAR', 'Clear', 'Clear the center seam normals'),
    ('TRANSFER', 'Transfer', 'Transfer center seam normals'),
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


class Symmetrize(bpy.types.Operator):
    bl_idname = 'ho.symmetrize'
    bl_label = 'Symmetrize'
    bl_description = 'Symmetrize the active mesh using an Alt-X radial flick'
    bl_options = {'REGISTER', 'UNDO'}

    objmode: BoolProperty(name='Object Mode', default=False)
    flick: BoolProperty(name='Flick', default=True)
    axis: EnumProperty(name='Axis', items=AXIS_ITEMS, default='X')
    direction: EnumProperty(name='Direction', items=DIRECTION_ITEMS, default='POSITIVE')
    threshold: FloatProperty(name='Threshold', default=0.0001, min=0.0)
    partial: BoolProperty(name='Selected Only', default=False)
    remove: BoolProperty(name='Remove Other Side', default=False)
    remove_redundant_center: BoolProperty(name='Remove Redundant Center', default=True)
    is_custom_normal: BoolProperty(default=False, options={'HIDDEN'})
    mirror_custom_normals: BoolProperty(name='Mirror Custom Normals', default=True)
    custom_normal_method: EnumProperty(
        name='Custom Normal Pairing', items=NORMAL_METHOD_ITEMS, default='INDEX'
    )
    fix_center: BoolProperty(name='Fix Center Seam', default=False)
    fix_center_method: EnumProperty(
        name='Center Fix Method', items=FIX_CENTER_ITEMS, default='CLEAR'
    )
    clear_sharps: BoolProperty(name='Clear Center Sharps', default=True)

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
        row.prop(self, 'partial', text='Selected Only', toggle=True)
        row.prop(self, 'remove', text='Remove' if self.remove else 'Symmetrize', toggle=True)
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
