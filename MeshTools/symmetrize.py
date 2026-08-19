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


def _mirror_vector(value, component):
    mirrored = value.copy()
    mirrored[component] = -mirrored[component]
    return mirrored


def _curve_point_selected(point, spline_type):
    if spline_type == 'BEZIER':
        return bool(point.select_control_point)
    return bool(point.select)


_SPLINE_SETTINGS = (
    'use_cyclic_u',
    'resolution_u',
    'order_u',
    'use_endpoint_u',
    'use_bezier_u',
    'use_smooth',
    'hide',
    'material_index',
    'radius_interpolation',
    'tilt_interpolation',
)


def _copy_spline_settings(source, target):
    for name in _SPLINE_SETTINGS:
        if hasattr(source, name) and hasattr(target, name):
            setattr(target, name, getattr(source, name))


def _mirror_curve_spline(curve, source_spline, source_points, source_indices, axis):
    """Create a separate reflected spline for a path with no target side."""
    spline_type = source_spline.type
    mirrored_spline = curve.splines.new(spline_type)
    ordered_indices = list(reversed(source_indices))
    if spline_type == 'BEZIER':
        mirrored_spline.bezier_points.add(len(ordered_indices) - 1)
        for target, source_index in zip(
            mirrored_spline.bezier_points,
            ordered_indices,
        ):
            source = source_points[source_index]
            target.co = _mirror_vector(source.co, axis)
            target.handle_left = _mirror_vector(source.handle_left, axis)
            target.handle_right = _mirror_vector(source.handle_right, axis)
            target.handle_left_type = source.handle_left_type
            target.handle_right_type = source.handle_right_type
            target.tilt = source.tilt
            target.radius = source.radius
            target.weight_softbody = source.weight_softbody
            target.select_control_point = source.select_control_point
            target.select_left_handle = source.select_left_handle
            target.select_right_handle = source.select_right_handle
            target.hide = source.hide
    else:
        mirrored_spline.points.add(len(ordered_indices) - 1)
        for target, source_index in zip(
            mirrored_spline.points,
            ordered_indices,
        ):
            source = source_points[source_index]
            target.co = _mirror_vector(source.co, axis)
            target.tilt = source.tilt
            target.radius = source.radius
            target.weight_softbody = source.weight_softbody
            target.select = source.select
            target.hide = source.hide
    # Blender clamps NURBS order to the number of controls currently in the
    # spline.  Apply settings only after all mirrored controls exist; applying
    # them to the newly-created one-point spline permanently loses the source
    # order (and endpoint behavior).
    _copy_spline_settings(source_spline, mirrored_spline)
    return mirrored_spline


def _curve_point_record(point, spline_type):
    if spline_type == 'BEZIER':
        return {
            'co': point.co.copy(),
            'handle_left': point.handle_left.copy(),
            'handle_right': point.handle_right.copy(),
            'handle_left_type': point.handle_left_type,
            'handle_right_type': point.handle_right_type,
            'tilt': point.tilt,
            'radius': point.radius,
            'weight_softbody': point.weight_softbody,
            'select_control_point': point.select_control_point,
            'select_left_handle': point.select_left_handle,
            'select_right_handle': point.select_right_handle,
            'hide': point.hide,
        }
    return {
        'co': point.co.copy(),
        'tilt': point.tilt,
        'radius': point.radius,
        'weight_softbody': point.weight_softbody,
        'select': point.select,
        'hide': point.hide,
    }


def _restore_curve_point(point, spline_type, record):
    point.co = record['co']
    if spline_type == 'BEZIER':
        point.handle_left_type = 'FREE'
        point.handle_right_type = 'FREE'
        point.handle_left = record['handle_left']
        point.handle_right = record['handle_right']
        point.handle_left_type = record['handle_left_type']
        point.handle_right_type = record['handle_right_type']
        point.select_control_point = record['select_control_point']
        point.select_left_handle = record['select_left_handle']
        point.select_right_handle = record['select_right_handle']
    else:
        point.select = record['select']
    point.tilt = record['tilt']
    point.radius = record['radius']
    point.weight_softbody = record['weight_softbody']
    point.hide = record['hide']


def _rebuild_curve_splines(curve, snapshots):
    active_index = next(
        (
            index
            for index, snapshot in enumerate(snapshots)
            if snapshot['active']
        ),
        None,
    )
    curve.splines.clear()
    active_spline = None
    for index, snapshot in enumerate(snapshots):
        points = snapshot['points']
        if not points:
            continue
        spline = curve.splines.new(snapshot['type'])
        if snapshot['type'] == 'BEZIER':
            spline.bezier_points.add(len(points) - 1)
            target_points = spline.bezier_points
        else:
            spline.points.add(len(points) - 1)
            target_points = spline.points
        for target, record in zip(target_points, points):
            _restore_curve_point(target, snapshot['type'], record)
        for name, value in snapshot['settings'].items():
            if hasattr(spline, name):
                setattr(spline, name, value)
        if index == active_index:
            active_spline = spline
    if active_spline is not None:
        curve.splines.active = active_spline


def _curve_remove_opposite(obj, direction, threshold, partial):
    """Remove controls on the non-source side, matching mesh remove mode."""
    direction_name, axis = direction.split('_', 1)
    component = 'XYZ'.index(axis)
    source_sign = 1 if direction_name == 'POSITIVE' else -1
    snapshots = []
    affected = []
    changed = False

    for spline in list(obj.data.splines):
        spline_type = spline.type
        if spline_type == 'BEZIER':
            points = list(spline.bezier_points)
        elif spline_type in {'POLY', 'NURBS'}:
            points = list(spline.points)
        else:
            continue

        keep_records = []
        removed_indices = []
        for index, point in enumerate(points):
            value = float(point.co[component])
            selected = _curve_point_selected(point, spline_type)
            considered = not partial or selected
            if considered and abs(value) <= threshold:
                point.co[component] = 0.0
            should_remove = considered and value * source_sign < -threshold
            if should_remove:
                removed_indices.append(index)
                continue
            record = _curve_point_record(point, spline_type)
            if considered and abs(value) <= threshold:
                record['co'][component] = 0.0
            keep_records.append(record)

        if removed_indices:
            changed = True
            affected.extend((spline, index) for index in removed_indices)
        snapshots.append({
            'type': spline_type,
            'points': keep_records,
            'active': spline == obj.data.splines.active,
            'settings': {
                name: getattr(spline, name)
                for name in _SPLINE_SETTINGS
                if hasattr(spline, name)
            },
        })

    if changed:
        _rebuild_curve_splines(obj.data, snapshots)
    obj.data.update_tag()
    return {
        'curve': True,
        'affected': affected,
        'skipped': [],
        'remove_requested': True,
    }


def _mirror_curve_record(record, spline_type, component):
    mirrored = dict(record)
    mirrored['co'] = _mirror_vector(record['co'], component)
    if spline_type == 'BEZIER':
        mirrored['handle_left'] = _mirror_vector(record['handle_right'], component)
        mirrored['handle_right'] = _mirror_vector(record['handle_left'], component)
        mirrored['handle_left_type'] = record['handle_right_type']
        mirrored['handle_right_type'] = record['handle_left_type']
    return mirrored


def _prune_unpaired_curve_targets(obj, direction, threshold):
    """Remove target-side controls that have no source counterpart.

    Blender's default mesh symmetrize replaces the target side, so an extra
    target vertex is removed instead of being left as an unmatched duplicate.
    Curve collections have no point-level remove API; rebuild only when such
    extras exist, preserving all spline and point settings.
    """
    direction_name, axis = direction.split('_', 1)
    component = 'XYZ'.index(axis)
    source_sign = 1 if direction_name == 'POSITIVE' else -1
    snapshots = []
    changed = False
    for spline in list(obj.data.splines):
        spline_type = spline.type
        if spline_type == 'BEZIER':
            points = list(spline.bezier_points)
        elif spline_type in {'POLY', 'NURBS'}:
            points = list(spline.points)
        else:
            continue

        source_indices = [
            index for index, point in enumerate(points)
            if float(point.co[component]) * source_sign > threshold
        ]
        target_sources = {}
        for source_index in source_indices:
            target_index = len(points) - 1 - source_index
            if target_index == source_index:
                continue
            target = points[target_index]
            if float(target.co[component]) * source_sign <= threshold:
                target_sources[target_index] = source_index

        remove_indices = {
            index
            for index, point in enumerate(points)
            if float(point.co[component]) * source_sign < -threshold
            and index not in target_sources
        }
        if not remove_indices:
            snapshots.append({
                'type': spline_type,
                'points': [_curve_point_record(point, spline_type) for point in points],
                'active': spline == obj.data.splines.active,
                'settings': {
                    name: getattr(spline, name)
                    for name in _SPLINE_SETTINGS
                    if hasattr(spline, name)
                },
            })
            continue

        changed = True
        records = []
        source_records = {
            index: _curve_point_record(points[index], spline_type)
            for index in source_indices
        }
        for index, point in enumerate(points):
            if index in remove_indices:
                continue
            source_index = target_sources.get(index)
            if source_index is not None:
                records.append(
                    _mirror_curve_record(
                        source_records[source_index], spline_type, component
                    )
                )
            else:
                record = _curve_point_record(point, spline_type)
                if abs(float(point.co[component])) <= threshold:
                    record['co'][component] = 0.0
                records.append(record)
        snapshots.append({
            'type': spline_type,
            'points': records,
            'active': spline == obj.data.splines.active,
            'settings': {
                name: getattr(spline, name)
                for name in _SPLINE_SETTINGS
                if hasattr(spline, name)
            },
        })

    if changed:
        _rebuild_curve_splines(obj.data, snapshots)
    return changed


def _curve_symmetrize(obj, direction, threshold, partial, remove):
    """Mirror curve controls across an object-local axis.

    Curve splines have ordered controls instead of mesh vertices with edges.
    Reversing that order gives the counterpart of a control on the other side
    of a symmetric open or cyclic spline. Existing counterparts are updated
    in place; unmatched target-side controls are removed, and a path with only
    one side receives a reflected spline copy.
    """
    if remove:
        return _curve_remove_opposite(obj, direction, threshold, partial)

    direction_name, axis = direction.split('_', 1)
    component = 'XYZ'.index(axis)
    source_sign = 1 if direction_name == 'POSITIVE' else -1
    affected = []
    skipped = []
    opposite_only_splines = []

    if not partial:
        _prune_unpaired_curve_targets(obj, direction, threshold)

    for spline in list(obj.data.splines):
        spline_type = spline.type
        if spline_type == 'BEZIER':
            points = list(spline.bezier_points)
        elif spline_type in {'POLY', 'NURBS'}:
            points = list(spline.points)
        else:
            continue

        snapshots = []
        source_indices = []
        opposite_count = 0
        for index, point in enumerate(points):
            value = float(point.co[component])
            if abs(value) <= threshold:
                point.co[component] = 0.0
                if spline_type == 'BEZIER':
                    left = point.handle_left.copy()
                    right = point.handle_right.copy()
                    left_type = point.handle_left_type
                    point.handle_left = _mirror_vector(right, component)
                    point.handle_right = _mirror_vector(left, component)
                    point.handle_left_type = point.handle_right_type
                    point.handle_right_type = left_type
                continue
            if value * source_sign <= 0.0:
                if value * source_sign < -threshold:
                    opposite_count += 1
                continue
            if partial and not _curve_point_selected(point, spline_type):
                continue
            source_indices.append(index)
            target_index = len(points) - 1 - index
            if target_index == index:
                continue
            target = points[target_index]
            target_value = float(target.co[component])
            if target_value * source_sign > threshold:
                skipped.append((spline, index))
                continue
            if spline_type == 'BEZIER':
                snapshots.append(
                    (
                        index,
                        target_index,
                        point.co.copy(),
                        point.handle_left.copy(),
                        point.handle_right.copy(),
                        point.handle_left_type,
                        point.handle_right_type,
                    )
                )
            else:
                snapshots.append((index, target_index, point.co.copy()))

        if source_indices and opposite_count == 0:
            _mirror_curve_spline(
                obj.data,
                spline,
                points,
                source_indices,
                component,
            )
            affected.extend((spline, index) for index in source_indices)
            continue

        # Match Blender mesh.symmetrize: when a spline exists entirely on the
        # target side, the default operation removes it because there is no
        # source-side path from which to generate a counterpart.  Partial mode
        # must leave unselected splines untouched, just like mesh symmetrize.
        if not partial and not source_indices and opposite_count:
            opposite_only_splines.append(spline)
            affected.extend((spline, index) for index, point in enumerate(points)
                            if float(point.co[component]) * source_sign < -threshold)
            continue

        for snapshot in snapshots:
            if spline_type == 'BEZIER':
                (
                    _,
                    target_index,
                    source_co,
                    source_left,
                    source_right,
                    source_left_type,
                    source_right_type,
                ) = snapshot
                target = points[target_index]
                target.co = _mirror_vector(source_co, component)
                target.handle_left = _mirror_vector(source_right, component)
                target.handle_right = _mirror_vector(source_left, component)
                target.handle_left_type = source_right_type
                target.handle_right_type = source_left_type
            else:
                _, target_index, source_co = snapshot
                target = points[target_index]
                target.co = _mirror_vector(source_co, component)
            affected.append((spline, target_index))

    for spline in opposite_only_splines:
        obj.data.splines.remove(spline)

    obj.data.update_tag()
    return {
        'curve': True,
        'affected': affected,
        'skipped': skipped,
        'remove_requested': bool(remove),
    }


class OP_Symmetrize(bpy.types.Operator):
    bl_idname = 'ho.symmetrize'
    bl_label = '对称化'
    bl_description = '使用 Alt-X 径向操作对当前网格或曲线进行对称化'
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
        active = context.active_object
        if active is None:
            return False
        mesh_mode = active.type == 'MESH' and context.mode in {'EDIT_MESH', 'OBJECT'}
        curve_mode = active.type == 'CURVE' and context.mode == 'EDIT_CURVE'
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and (mesh_mode or curve_mode)
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
        if context.active_object and context.active_object.type == 'CURVE':
            return
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
        if active.type == 'CURVE':
            self.result = _curve_symmetrize(
                active,
                direction=f'{self.direction}_{self.axis}',
                threshold=self.threshold,
                partial=self.partial,
                remove=self.remove,
            )
            return {'FINISHED'}

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
