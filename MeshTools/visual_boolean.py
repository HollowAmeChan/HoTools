import bpy
import gpu
import numpy as np
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy_extras import view3d_utils

from . import boolean as boolean_tools
from Utils.viewport_draw import draw_polygons, draw_segments, restore_3d_state
from Utils.hud import begin_hud, draw_hud_lines, end_hud, measure_hud_lines


class OP_VisualBooleanCut(Operator):
    bl_idname = "ho.visual_boolean_cut"
    bl_label = "视图切割"
    bl_description = "锁定当前视图绘制切割轮廓，按 Enter 使用 CGAL 差集切割活动网格"
    bl_options = {'REGISTER', 'UNDO'}

    hit_radius = 16.0
    curve_samples = 8
    cutter_depth_factor = 1000.0
    @classmethod
    def poll(cls, context):
        return (
            context.area is not None
            and context.area.type == 'VIEW_3D'
            and context.object is not None
            and context.object.type == 'MESH'
            and context.mode == 'OBJECT'
        )

    def _tag_redraw(self, context):
        if context.area:
            context.area.tag_redraw()

    def _view_plane(self, context):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            raise RuntimeError("只能在三维视图中启动视图切割")

        obj = context.object
        world_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        plane_point = sum(world_corners, Vector((0.0, 0.0, 0.0))) / len(world_corners)
        center = (region.width * 0.5, region.height * 0.5)
        normal = view3d_utils.region_2d_to_vector_3d(region, rv3d, center)
        if normal.length < 1e-8:
            raise RuntimeError("无法读取当前视图方向")
        return plane_point, normal.normalized()

    def _screen_to_world(self, screen_point):
        origin = view3d_utils.region_2d_to_origin_3d(
            self.region,
            self.rv3d,
            screen_point,
        )
        direction = view3d_utils.region_2d_to_vector_3d(
            self.region,
            self.rv3d,
            screen_point,
        )
        denominator = direction.dot(self.plane_normal)
        if abs(denominator) < 1e-8:
            return self.plane_point.copy()
        distance = (self.plane_point - origin).dot(self.plane_normal) / denominator
        return origin + direction * distance

    def _screen_area(self, points):
        if len(points) < 3:
            return 0.0
        return 0.5 * sum(
            points[index].x * points[(index + 1) % len(points)].y
            - points[(index + 1) % len(points)].x * points[index].y
            for index in range(len(points))
        )

    def _right_offset_points(self, points):
        if len(points) < 2:
            return []
        extent = max(self.region.width, self.region.height) * 4.0
        offsets = []
        for index, point in enumerate(points):
            if index == 0:
                tangent = points[1] - points[0]
            elif index == len(points) - 1:
                tangent = points[-1] - points[-2]
            else:
                tangent = points[index + 1] - points[index - 1]
            if tangent.length < 1e-8:
                tangent = Vector((1.0, 0.0))
            tangent.normalize()
            right = Vector((tangent.y, -tangent.x))
            offsets.append(point + right * extent)
        return offsets

    def _smooth_points(self, points, closed):
        if len(points) < 3:
            return list(points)

        # 使用权重为 1 的三次均匀 NURBS 基函数生成预览折线。
        control = [point.copy() for point in points]
        degree = 3
        if closed:
            control.extend(point.copy() for point in points[:degree])
            segment_count = len(points)
            start_index = 0
        else:
            control = [control[0]] * degree + control + [control[-1]] * degree
            segment_count = len(points) - 1
            start_index = 0

        result = []
        for segment in range(segment_count):
            for sample in range(self.curve_samples):
                t = sample / self.curve_samples
                weights = (
                    (1.0 - t) ** 3 / 6.0,
                    (3.0 * t ** 3 - 6.0 * t ** 2 + 4.0) / 6.0,
                    (-3.0 * t ** 3 + 3.0 * t ** 2 + 3.0 * t + 1.0) / 6.0,
                    t ** 3 / 6.0,
                )
                point = Vector((0.0, 0.0))
                for offset, weight in enumerate(weights):
                    point += control[start_index + segment + offset] * weight
                result.append(point)
        if not closed:
            result.append(points[-1].copy())
        return result

    def _display_points(self):
        points = [point.copy() for point in self.points]
        if self.nurbs:
            points = self._smooth_points(points, self.closed)
        return points

    def _polygon_screen_points(self):
        points = self._display_points()
        if self.closed:
            return points
        return points + list(reversed(self._right_offset_points(points)))

    def _polygon_world_points(self, screen_points):
        return [self._screen_to_world(point) for point in screen_points]

    def _mesh_cutter(self, context, polygon_screen):
        if len(polygon_screen) < 3:
            raise RuntimeError("至少需要三个控制点")
        if abs(self._screen_area(polygon_screen)) < 1e-5:
            raise RuntimeError("切割轮廓面积过小")

        obj = context.object
        world_points = self._polygon_world_points(polygon_screen)
        if len(world_points) > 1 and (world_points[0] - world_points[-1]).length < 1e-7:
            world_points.pop()
        if len(world_points) < 3:
            raise RuntimeError("切割轮廓包含重复控制点")
        corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        dimensions = [
            (corners[index] - corners[0]).length
            for index in range(1, len(corners))
        ]
        object_size = max(dimensions + [1.0])
        depth = object_size * self.cutter_depth_factor

        # 前盖朝向视点，后盖朝向视图深处；以三维方向判断，避免依赖具体视角。
        polygon_normal = Vector((0.0, 0.0, 0.0))
        for index, point in enumerate(world_points):
            polygon_normal += point.cross(world_points[(index + 1) % len(world_points)])
        if polygon_normal.dot(-self.plane_normal) < 0.0:
            world_points.reverse()
        front = [point - self.plane_normal * depth for point in world_points]
        back = [point + self.plane_normal * depth for point in world_points]
        vertices = np.asarray(front + back, dtype=np.float64)
        count = len(world_points)
        faces = [list(range(count))]
        faces.append(list(range(2 * count - 1, count - 1, -1)))
        for index in range(count):
            next_index = (index + 1) % count
            faces.append([
                index,
                count + index,
                count + next_index,
                next_index,
            ])
        triangles = []
        for face in faces:
            for index in range(1, len(face) - 1):
                triangles.append((face[0], face[index], face[index + 1]))
        triangles = np.asarray(triangles, dtype=np.int32)
        signed_volume = 0.0
        for triangle in triangles:
            point_a, point_b, point_c = vertices[triangle]
            signed_volume += np.dot(point_a, np.cross(point_b, point_c))
        if signed_volume < 0.0:
            triangles = triangles[:, [0, 2, 1]]
        return vertices, triangles

    def _nearest_point(self, screen_point):
        if not self.points:
            return -1
        distances = [
            (point - screen_point).length_squared
            for point in self.points
        ]
        index = min(range(len(distances)), key=distances.__getitem__)
        return index if distances[index] <= self.hit_radius ** 2 else -1

    def _nearest_segment(self, screen_point):
        """返回可见线段上的最近点、控制段索引和屏幕距离平方。"""
        display = self._display_points()
        if len(display) < 2:
            return None

        segment_count = len(display) - 1
        if self.closed:
            segment_count = len(display)
        best = None
        for display_index in range(segment_count):
            point_a = display[display_index]
            point_b = display[(display_index + 1) % len(display)]
            delta = point_b - point_a
            length_squared = delta.length_squared
            if length_squared < 1e-8:
                factor = 0.0
            else:
                factor = max(
                    0.0,
                    min(1.0, (screen_point - point_a).dot(delta) / length_squared),
                )
            projected = point_a + delta * factor
            distance_squared = (screen_point - projected).length_squared
            if best is None or distance_squared < best[2]:
                best = (display_index, projected, distance_squared)

        if best is None or best[2] > self.hit_radius ** 2:
            return None

        if self.nurbs:
            control_index = best[0] // self.curve_samples
        else:
            control_index = best[0]
        return control_index, best[1], best[2]

    def _remove_control_point(self, index):
        if len(self.points) <= 3:
            self.message = "闭合轮廓至少保留三个控制点"
            return False
        self.points.pop(index)
        self.message = f"已移除控制点，剩余 {len(self.points)} 个"
        return True

    def _insert_on_segment(self, segment):
        if not self.points:
            return False
        insert_index = segment + 1
        if self.closed:
            insert_index = min(insert_index, len(self.points))
        else:
            insert_index = min(insert_index, len(self.points))
        self.points.insert(insert_index, self._pending_insert_point.copy())
        self.message = f"已在线段插入控制点，当前 {len(self.points)} 个"
        return True

    def _close_at(self, index):
        if index < 0 or index >= len(self.points) or len(self.points) < 3:
            return False
        if index:
            self.points = self.points[index:] + self.points[:index]
        self.closed = True
        self.message = "轮廓已闭合"
        return True

    def _draw_points(self, shader):
        if not self.points:
            return
        gpu.state.point_size_set(9.0)
        batch = batch_for_shader(shader, 'POINTS', {"pos": [
            self._screen_to_world(point) for point in self.points
        ]})
        shader.uniform_float("color", (1.0, 0.75, 0.10, 1.0))
        batch.draw(shader)
        gpu.state.point_size_set(1.0)

    def draw_preview(self):
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader.bind()
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(False)

        display = self._display_points()
        if len(display) >= 2:
            coords = []
            for index in range(len(display) - 1):
                coords.extend((
                    self._screen_to_world(display[index]),
                    self._screen_to_world(display[index + 1]),
                ))
            if self.closed:
                coords.extend((
                    self._screen_to_world(display[-1]),
                    self._screen_to_world(display[0]),
                ))
            elif self.hover_screen is not None:
                coords.extend((
                    self._screen_to_world(display[-1]),
                    self._screen_to_world(self.hover_screen),
                ))
            draw_segments(shader, coords, (0.15, 0.95, 1.0, 0.95), 3.0)

        if self.closed and len(display) >= 3:
            polygon = [
                [self._screen_to_world(point) for point in display]
            ]
            draw_polygons(
                shader,
                polygon,
                fill_color=(0.05, 0.55, 1.0, 0.12),
                line_color=None,
            )
        self._draw_points(shader)
        restore_3d_state()

    def draw_text(self):
        if self.closed:
            status = "已闭合，可按 Enter 切割"
        elif self.drag_index >= 0:
            status = "正在移动控制点"
        else:
            status = "绘制中：点击控制点闭合"
        if self.message:
            status = self.message

        lines = [
            ("状态: ", status),
            ("左键: ", "添加点 / 线段插点 / 点闭合或删除"),
            ("右键: ", "拖动控制点"),
            ("N键: ", f"NURBS {'开' if self.nurbs else '关'}"),
            ("A键: ", f"应用修改器 {'开' if self.apply_modifiers else '关'}"),
            ("C键: ", "清除全部控制点"),
            ("Enter: ", "执行 CGAL 差集"),
            ("Esc: ", "取消"),
        ]

        line_height = 22
        padding = 20
        font_id = begin_hud(shadow_alpha=0.65)
        hud_width = measure_hud_lines(font_id, lines)
        hud_height = (len(lines) - 1) * line_height + 18
        mouse_x = self.hover_screen.x if self.hover_screen else 0.0
        mouse_y = self.hover_screen.y if self.hover_screen else 0.0
        region_width = self.region.width
        region_height = self.region.height

        # HUD 默认显示在鼠标右上方，靠近边缘时自动翻到另一侧或上方。
        x = mouse_x + padding
        if x + hud_width > region_width - 8:
            x = mouse_x - hud_width - padding
        x = max(8.0, min(x, region_width - hud_width - 8.0))

        y_above = mouse_y + padding + hud_height
        y_below = mouse_y - padding
        if y_above <= region_height - 8.0:
            y = y_above
        elif y_below - hud_height >= 8.0:
            y = y_below
        else:
            y = max(hud_height + 8.0, min(y_above, region_height - 8.0))

        draw_hud_lines(
            font_id,
            x,
            y,
            lines,
            line_height=line_height,
            direction=-1,
            key_color=(1.0, 0.82, 0.18, 1.0),
        )
        end_hud(font_id)

    def _apply_cut(self, context):
        active = context.object
        if self.apply_modifiers and active.modifiers:
            self._apply_all_modifiers(context, active)

        polygon_screen = self._polygon_screen_points()
        cutter_vertices, cutter_faces = self._mesh_cutter(context, polygon_screen)
        active_world = active.matrix_world.copy()
        vertices_a, faces_a = boolean_tools._triangle_arrays(active, active_world)
        native = boolean_tools._load_native_boolean()
        result = native.boolean(
            vertices_a,
            faces_a,
            cutter_vertices,
            cutter_faces,
            2,
        )
        output_mesh = boolean_tools._build_boolean_mesh(
            active.data,
            result,
            active_world.inverted(),
        )
        source_mesh = active.data
        active.data = output_mesh
        if source_mesh.users == 0:
            bpy.data.meshes.remove(source_mesh)

    def _apply_all_modifiers(self, context, active):
        selected_objects = list(context.selected_objects)
        previous_active = context.view_layer.objects.active
        try:
            bpy.ops.object.select_all(action='DESELECT')
            active.select_set(True)
            context.view_layer.objects.active = active
            for modifier in list(active.modifiers):
                try:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                except RuntimeError as exc:
                    raise RuntimeError(
                        f"应用修改器「{modifier.name}」失败: {exc}"
                    ) from exc
        finally:
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in selected_objects:
                if obj.name in bpy.data.objects:
                    obj.select_set(True)
            if previous_active is not None and previous_active.name in bpy.data.objects:
                context.view_layer.objects.active = previous_active
            else:
                context.view_layer.objects.active = active

    def _finish_handlers(self, context):
        for name in ('_handle_3d', '_handle_text'):
            handle = getattr(self, name, None)
            if handle is not None:
                bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
                setattr(self, name, None)
        self._tag_redraw(context)

    def modal(self, context, event):
        if event.type in {'ESC'}:
            self._finish_handlers(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            self.hover_screen = Vector((event.mouse_region_x, event.mouse_region_y))
            if self.drag_index >= 0:
                self.points[self.drag_index] = self.hover_screen.copy()
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            point = Vector((event.mouse_region_x, event.mouse_region_y))
            hit = self._nearest_point(point)
            if hit >= 0:
                if self.closed:
                    self._remove_control_point(hit)
                elif not self._close_at(hit) and len(self.points) < 3:
                    self.message = "闭合轮廓至少需要三个控制点"
            elif not self.closed or len(self.points) >= 3:
                segment = self._nearest_segment(point)
                if segment is not None:
                    self._pending_insert_point = segment[1]
                    self._insert_on_segment(segment[0])
                elif not self.closed:
                    self.points.append(point)
                    self.message = f"已添加 {len(self.points)} 个控制点"
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'RIGHTMOUSE':
            point = Vector((event.mouse_region_x, event.mouse_region_y))
            if event.value == 'PRESS':
                hit = self._nearest_point(point)
                if hit >= 0:
                    self.drag_index = hit
                    self.message = "正在移动控制点"
                    return {'RUNNING_MODAL'}
                self._finish_handlers(context)
                return {'CANCELLED'}
            if event.value == 'RELEASE':
                self.drag_index = -1
                self.message = ""
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}

        if event.type == 'N' and event.value == 'PRESS':
            self.nurbs = not self.nurbs
            self.message = f"NURBS {'开启' if self.nurbs else '关闭'}"
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'A' and event.value == 'PRESS':
            self.apply_modifiers = not self.apply_modifiers
            self.message = (
                f"应用修改器{'开启' if self.apply_modifiers else '关闭'}"
            )
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'C' and event.value == 'PRESS':
            self.points = []
            self.closed = False
            self.drag_index = -1
            self.message = "已清除全部控制点"
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if len(self.points) < 2:
                self.message = "至少需要两个控制点"
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}
            try:
                self._apply_cut(context)
            except Exception as exc:
                self.message = f"切割失败: {exc}"
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}
            self._finish_handlers(context)
            self.report({'INFO'}, "视图切割完成")
            return {'FINISHED'}

        # 锁定视图期间吞掉视图导航事件，确保控制点仍在同一视平面。
        if event.type in {
            'MIDDLEMOUSE',
            'WHEELUPMOUSE',
            'WHEELDOWNMOUSE',
            'TRACKPADPAN',
            'TRACKPADZOOM',
            'NDOF_MOTION',
        }:
            return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        if not self.poll(context):
            return {'CANCELLED'}
        try:
            self.region = context.region
            self.rv3d = context.region_data
            self.plane_point, self.plane_normal = self._view_plane(context)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self.points = []
        self.closed = False
        self.nurbs = False
        self.apply_modifiers = False
        self.drag_index = -1
        self.hover_screen = Vector((event.mouse_region_x, event.mouse_region_y))
        self.message = ""
        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview, (), 'WINDOW', 'POST_VIEW'
        )
        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_text, (), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {'RUNNING_MODAL'}
