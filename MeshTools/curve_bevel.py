import bpy
from bpy.props import FloatProperty, IntProperty
from bpy_extras import view3d_utils
from mathutils import Vector


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


def _point_coordinate(point):
    return Vector(point.co[:3])


def _selected_indices(spline):
    if spline.type == 'BEZIER':
        return {
            index
            for index, point in enumerate(spline.bezier_points)
            if point.select_control_point
        }
    return {
        index
        for index, point in enumerate(spline.points)
        if point.select
    }


def _quadratic_point(start, corner, end, factor):
    first = start.lerp(corner, factor)
    second = corner.lerp(end, factor)
    return first.lerp(second, factor)


def _snapshot_curve(curve):
    snapshots = []
    for spline in curve.splines:
        snapshot = {
            'type': spline.type,
            'active': spline == curve.splines.active,
            'settings': {
                name: getattr(spline, name)
                for name in _SPLINE_SETTINGS
                if hasattr(spline, name)
            },
        }
        if spline.type == 'BEZIER':
            snapshot['points'] = [
                {
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
                for point in spline.bezier_points
            ]
        else:
            snapshot['points'] = [
                {
                    'co': point.co.copy(),
                    'tilt': point.tilt,
                    'radius': point.radius,
                    'weight_softbody': point.weight_softbody,
                    'select': point.select,
                    'hide': point.hide,
                }
                for point in spline.points
            ]
        snapshots.append(snapshot)
    return snapshots


def _restore_curve(curve, snapshots):
    curve.splines.clear()
    active_spline = None
    for snapshot in snapshots:
        spline = curve.splines.new(snapshot['type'])
        if snapshot['active']:
            active_spline = spline
        points = snapshot['points']
        if snapshot['type'] == 'BEZIER':
            spline.bezier_points.add(len(points) - 1)
            for point, record in zip(spline.bezier_points, points):
                point.co = record['co']
                point.handle_left_type = 'FREE'
                point.handle_right_type = 'FREE'
                point.handle_left = record['handle_left']
                point.handle_right = record['handle_right']
                point.handle_left_type = record['handle_left_type']
                point.handle_right_type = record['handle_right_type']
                point.tilt = record['tilt']
                point.radius = record['radius']
                point.weight_softbody = record['weight_softbody']
                point.select_control_point = record['select_control_point']
                point.select_left_handle = record['select_left_handle']
                point.select_right_handle = record['select_right_handle']
                point.hide = record['hide']
        else:
            spline.points.add(len(points) - 1)
            for point, record in zip(spline.points, points):
                point.co = record['co']
                point.tilt = record['tilt']
                point.radius = record['radius']
                point.weight_softbody = record['weight_softbody']
                point.select = record['select']
                point.hide = record['hide']
        for name, value in snapshot['settings'].items():
            setattr(spline, name, value)
    if active_spline is not None:
        curve.splines.active = active_spline
    curve.update_tag()


def _selected_center(curve):
    coordinates = []
    for spline in curve.splines:
        points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        selected = _selected_indices(spline)
        coordinates.extend(
            _point_coordinate(points[index])
            for index in selected
        )
    return sum(coordinates, Vector()) / len(coordinates) if coordinates else Vector()


def _bevel_replacements(spline, width, segments):
    points = list(spline.bezier_points if spline.type == 'BEZIER' else spline.points)
    selected = _selected_indices(spline)
    replacements = {}
    count = len(points)
    for index in sorted(selected):
        if count < 3:
            continue
        if spline.use_cyclic_u:
            previous_index = (index - 1) % count
            next_index = (index + 1) % count
        else:
            if index == 0 or index == count - 1:
                continue
            previous_index = index - 1
            next_index = index + 1
        if previous_index == next_index:
            continue
        corner = _point_coordinate(points[index])
        previous = _point_coordinate(points[previous_index])
        following = _point_coordinate(points[next_index])
        incoming = previous - corner
        outgoing = following - corner
        incoming_length = incoming.length
        outgoing_length = outgoing.length
        if incoming_length <= 1e-8 or outgoing_length <= 1e-8:
            continue
        distance = min(width, incoming_length * 0.5, outgoing_length * 0.5)
        if distance <= 1e-8:
            continue
        start = corner + incoming.normalized() * distance
        end = corner + outgoing.normalized() * distance
        if segments == 1:
            coordinates = [start, end]
        else:
            coordinates = [
                _quadratic_point(start, corner, end, step / segments)
                for step in range(segments + 1)
            ]
        replacements[index] = coordinates
    return points, replacements


def _bevel_bezier_spline(spline, width, segments):
    points, replacements = _bevel_replacements(spline, width, segments)
    if not replacements:
        return False
    records = []
    for index, point in enumerate(points):
        generated = replacements.get(index)
        if generated is None:
            records.append({
                'co': point.co.copy(),
                'handle_left': point.handle_left.copy(),
                'handle_right': point.handle_right.copy(),
                'handle_left_type': point.handle_left_type,
                'handle_right_type': point.handle_right_type,
                'tilt': point.tilt,
                'radius': point.radius,
                'weight_softbody': point.weight_softbody,
                'selected': point.select_control_point,
                'select_left_handle': point.select_left_handle,
                'select_right_handle': point.select_right_handle,
                'hide': point.hide,
                'generated': False,
            })
            continue
        for coordinate in generated:
            records.append({
                'co': coordinate,
                'handle_left': coordinate.copy(),
                'handle_right': coordinate.copy(),
                'handle_left_type': 'VECTOR' if segments == 1 else 'AUTO',
                'handle_right_type': 'VECTOR' if segments == 1 else 'AUTO',
                'tilt': point.tilt,
                'radius': point.radius,
                'weight_softbody': point.weight_softbody,
                'selected': True,
                'select_left_handle': point.select_left_handle,
                'select_right_handle': point.select_right_handle,
                'hide': point.hide,
                'generated': True,
            })
    spline.bezier_points.add(len(records) - len(points))
    for point, record in zip(spline.bezier_points, records):
        point.co = record['co']
        point.tilt = record['tilt']
        point.radius = record['radius']
        point.weight_softbody = record['weight_softbody']
        point.select_control_point = record['selected']
        point.select_left_handle = record['select_left_handle']
        point.select_right_handle = record['select_right_handle']
        point.hide = record['hide']
        if record['generated']:
            point.handle_left_type = record['handle_left_type']
            point.handle_right_type = record['handle_right_type']
        else:
            point.handle_left_type = 'FREE'
            point.handle_right_type = 'FREE'
            point.handle_left = record['handle_left']
            point.handle_right = record['handle_right']
            point.handle_left_type = record['handle_left_type']
            point.handle_right_type = record['handle_right_type']
    return True


def _bevel_point_spline(spline, width, segments):
    points, replacements = _bevel_replacements(spline, width, segments)
    if not replacements:
        return False
    records = []
    for index, point in enumerate(points):
        generated = replacements.get(index)
        if generated is None:
            records.append((
                point.co.copy(),
                point.tilt,
                point.radius,
                point.weight_softbody,
                point.select,
                point.hide,
            ))
        else:
            records.extend(
                (
                    (*coordinate, point.co[3]),
                    point.tilt,
                    point.radius,
                    point.weight_softbody,
                    True,
                    point.hide,
                )
                for coordinate in generated
            )
    spline.points.add(len(records) - len(points))
    for point, record in zip(spline.points, records):
        coordinate, tilt, radius, weight_softbody, selected, hidden = record
        point.co = coordinate
        point.tilt = tilt
        point.radius = radius
        point.weight_softbody = weight_softbody
        point.select = selected
        point.hide = hidden
    return True


class OP_CurveBevel(bpy.types.Operator):
    bl_idname = 'ho.curve_bevel'
    bl_label = 'HoTools：曲线控制点倒角'
    bl_options = {'REGISTER', 'UNDO'}

    width: FloatProperty(
        name='宽度',
        description='沿相邻曲线段截取的倒角宽度',
        default=0.1,
        min=0.0,
        soft_min=0.001,
    )  # type: ignore
    segments: IntProperty(
        name='段数',
        description='倒角过渡段数，1 为直线倒角',
        default=1,
        min=1,
        max=32,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        if context.mode != 'EDIT_CURVE' or not context.active_object:
            return False
        if context.active_object.type != 'CURVE':
            return False
        return any(
            _bevel_replacements(spline, 1.0, 1)[1]
            for spline in context.active_object.data.splines
        )

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D' or not context.region_data:
            self.report({'WARNING'}, '曲线倒角只能在 3D 视图中使用')
            return {'CANCELLED'}
        self._curve_snapshot = _snapshot_curve(context.active_object.data)
        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._depth_location = (
            context.active_object.matrix_world
            @ _selected_center(context.active_object.data)
        )
        self.width = 0.0
        self.segments = max(1, self.segments)
        self._width_offset = 0.0
        self._precision_active = False
        self._preview_changed = False
        self._update_header(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            start = view3d_utils.region_2d_to_location_3d(
                context.region,
                context.region_data,
                self._start_mouse,
                self._depth_location,
            )
            current = view3d_utils.region_2d_to_location_3d(
                context.region,
                context.region_data,
                mouse,
                self._depth_location,
            )
            local_delta = (
                context.active_object.matrix_world.inverted_safe().to_3x3()
                @ (current - start)
            )
            mouse_width = local_delta.length
            if event.shift:
                if not self._precision_active:
                    self._precision_active = True
                    self._precision_mouse_width = mouse_width
                    self._precision_width = self.width
                self.width = max(
                    0.0,
                    self._precision_width
                    + (mouse_width - self._precision_mouse_width) * 0.1,
                )
            else:
                if self._precision_active:
                    self._precision_active = False
                    self._width_offset = self.width - mouse_width
                self.width = max(0.0, mouse_width + self._width_offset)
            self._update_preview(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELUPMOUSE' and event.value == 'PRESS':
            self.segments = min(32, self.segments + 1)
            self._update_preview(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELDOWNMOUSE' and event.value == 'PRESS':
            self.segments = max(1, self.segments - 1)
            self._update_preview(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'SPACE'} and event.value == 'PRESS':
            if not self._preview_changed:
                self._restore_original(context)
                self._finish(context)
                return {'CANCELLED'}
            self._finish(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._restore_original(context)
            self._finish(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def _update_preview(self, context):
        self._restore_original(context)
        self._preview_changed = self._apply(context)
        self._update_header(context)
        context.area.tag_redraw()

    def _restore_original(self, context):
        _restore_curve(context.active_object.data, self._curve_snapshot)

    def _update_header(self, context):
        context.area.header_text_set(
            f'曲线倒角    宽度: {self.width:.4f}    段数: {self.segments}'
        )

    def _finish(self, context):
        context.area.header_text_set(None)
        context.area.tag_redraw()
        if hasattr(self, '_curve_snapshot'):
            del self._curve_snapshot

    def _apply(self, context):
        if self.width <= 1e-8:
            return False
        active = context.active_object
        changed = False
        for spline in active.data.splines:
            if spline.type == 'BEZIER':
                changed |= _bevel_bezier_spline(spline, self.width, self.segments)
            else:
                changed |= _bevel_point_spline(spline, self.width, self.segments)
        if changed:
            active.data.update_tag()
        return changed

    def execute(self, context):
        return {'FINISHED'} if self._apply(context) else {'CANCELLED'}
