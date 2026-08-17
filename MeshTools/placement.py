from dataclasses import dataclass
import math

import bmesh
import bpy
import gpu
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_ray_tri

from Utils.viewport_draw import (
    draw_polygons,
    foreground_uniform_color_shader,
    restore_3d_state,
)
from Utils.hud import draw_mouse_hud


def polygon_area_vector(points):
    if len(points) < 3:
        return Vector((0.0, 0.0, 0.0))
    origin = points[0]
    result = Vector((0.0, 0.0, 0.0))
    for index in range(1, len(points) - 1):
        result += (
            (points[index] - origin).cross(points[index + 1] - origin)
            * 0.5
        )
    return result


def rotation_between_vectors(source, target):
    source = source.normalized()
    target = target.normalized()
    dot = max(-1.0, min(1.0, source.dot(target)))

    if dot >= 1.0 - 1e-10:
        return Matrix.Identity(4)
    if dot <= -1.0 + 1e-10:
        reference = (
            Vector((1.0, 0.0, 0.0))
            if abs(source.x) < 0.9
            else Vector((0.0, 1.0, 0.0))
        )
        axis = source.cross(reference).normalized()
        return Matrix.Rotation(math.pi, 4, axis)

    axis = source.cross(target)
    angle = math.atan2(axis.length, dot)
    return Matrix.Rotation(angle, 4, axis.normalized())


def nearest_world_axis(world_normal):
    normal = world_normal.normalized()
    axis_index = max(range(3), key=lambda index: abs(normal[index]))
    axis = Vector((0.0, 0.0, 0.0))
    axis[axis_index] = 1.0 if normal[axis_index] >= 0.0 else -1.0
    return axis


def world_axis_label(axis):
    axis_index = max(range(3), key=lambda index: abs(axis[index]))
    sign = "+" if axis[axis_index] >= 0.0 else "-"
    return f"{sign}{'XYZ'[axis_index]}"


def ground_alignment_matrix(world_matrix, plane_points, world_normal):
    normal = world_normal.normalized()
    rotation = rotation_between_vectors(
        normal,
        Vector((0.0, 0.0, -1.0)),
    )

    pivot = sum(plane_points, Vector((0.0, 0.0, 0.0))) / len(plane_points)
    pivot_rotation = (
        Matrix.Translation(pivot) @
        rotation @
        Matrix.Translation(-pivot)
    )
    rotated_points = [
        pivot + rotation.to_3x3() @ (point - pivot)
        for point in plane_points
    ]
    ground_translation = Matrix.Translation(
        Vector((0.0, 0.0, -min(point.z for point in rotated_points)))
    )
    return ground_translation @ pivot_rotation @ world_matrix


def orthogonal_alignment_matrix(world_matrix, world_normal):
    rotation = rotation_between_vectors(
        world_normal,
        nearest_world_axis(world_normal),
    )
    pivot = world_matrix.translation.copy()
    return (
        Matrix.Translation(pivot) @
        rotation @
        Matrix.Translation(-pivot) @
        world_matrix
    )


def apply_world_matrix(obj, target_world_matrix, view_layer):
    obj.matrix_world = target_world_matrix
    view_layer.update()

    if obj.parent is None or obj.constraints:
        return

    actual_world_matrix = obj.matrix_world.copy()
    basis_matrix = obj.matrix_basis.copy()
    obj.matrix_parent_inverse = (
        obj.matrix_parent_inverse @
        basis_matrix @
        actual_world_matrix.inverted_safe() @
        target_world_matrix @
        basis_matrix.inverted_safe()
    )
    view_layer.update()


def ensure_single_user_mesh(obj, context):
    if obj.data.users <= 1:
        return

    was_edit_mode = context.mode == 'EDIT_MESH'
    if was_edit_mode:
        bpy.ops.object.mode_set(mode='OBJECT')
    obj.data = obj.data.copy()
    if was_edit_mode:
        context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')


def apply_mesh_transform(obj, local_matrix, context):
    ensure_single_user_mesh(obj, context)

    if context.mode == 'EDIT_MESH':
        bm = bmesh.from_edit_mesh(obj.data)
        shape_layers = list(bm.verts.layers.shape.values())
        for layer in shape_layers:
            for vert in bm.verts:
                vert[layer] = local_matrix @ vert[layer]
        bmesh.ops.transform(
            bm,
            matrix=local_matrix,
            verts=list(bm.verts),
            use_shapekey=False,
        )
        bmesh.update_edit_mesh(
            obj.data,
            loop_triangles=False,
            destructive=False,
        )
        return

    mesh = obj.data
    if mesh.shape_keys is not None:
        for key_block in mesh.shape_keys.key_blocks:
            for point in key_block.data:
                point.co = local_matrix @ point.co
    else:
        for vertex in mesh.vertices:
            vertex.co = local_matrix @ vertex.co
    mesh.update()


def apply_target_world_matrix(
    obj,
    target_world_matrix,
    context,
    keep_origin_transform=True,
):
    original_world_matrix = obj.matrix_world.copy()
    if keep_origin_transform:
        local_matrix = (
            original_world_matrix.inverted_safe() @
            target_world_matrix
        )
        apply_mesh_transform(obj, local_matrix, context)
        context.view_layer.update()
        return

    if context.mode == 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='OBJECT')
    apply_world_matrix(obj, target_world_matrix, context.view_layer)


def place_object_on_ground(
    obj,
    plane_points,
    world_normal,
    context,
    keep_origin_transform=True,
):
    target_world_matrix = ground_alignment_matrix(
        obj.matrix_world.copy(),
        plane_points,
        world_normal,
    )
    apply_target_world_matrix(
        obj,
        target_world_matrix,
        context,
        keep_origin_transform,
    )


def snap_object_rotation_to_axis(
    obj,
    world_normal,
    context,
    keep_origin_transform=True,
):
    target_world_matrix = orthogonal_alignment_matrix(
        obj.matrix_world.copy(),
        world_normal,
    )
    apply_target_world_matrix(
        obj,
        target_world_matrix,
        context,
        keep_origin_transform,
    )


def selected_face_world_geometry(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.normal_update()

    selected_faces = [
        face for face in bm.faces
        if face.select and not face.hide
    ]
    if not selected_faces:
        return None, None, "未选择任何面"

    world_matrix = obj.matrix_world.copy()
    normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
    normal_sum = Vector((0.0, 0.0, 0.0))
    selected_world_points = {}

    for face in selected_faces:
        world_points = []
        for vert in face.verts:
            point = world_matrix @ vert.co
            world_points.append(point)
            selected_world_points[vert] = point

        world_normal = normal_matrix @ face.normal
        if world_normal.length_squared <= 1e-16:
            continue

        world_area = polygon_area_vector(world_points).length
        if world_area <= 1e-12:
            continue
        normal_sum += world_normal.normalized() * world_area

    if normal_sum.length_squared <= 1e-16:
        return (
            None,
            None,
            "所选面退化或法线互相抵消，无法确定方向",
        )

    return (
        list(selected_world_points.values()),
        normal_sum.normalized(),
        None,
    )


class OP_PlaceObjectBottom(Operator):
    bl_idname = "ho.placeobjectbottom"
    bl_label = "选择底面放置"
    bl_description = "使用选择的面作为底面，旋转物体使底面贴合水平面摆放"
    bl_options = {'REGISTER', 'UNDO'}

    keep_origin_transform: BoolProperty(
        name="保持原点变换",
        description="保持物体原点的位置和旋转不变，直接变换网格数据",
        default=True,
    )  # type: ignore

    def draw(self, context):
        self.layout.prop(self, "keep_origin_transform")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        obj = context.active_object
        points, world_normal, error = selected_face_world_geometry(obj)
        if error is not None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        place_object_on_ground(
            obj,
            points,
            world_normal,
            context,
            self.keep_origin_transform,
        )

        return {'FINISHED'}


class OP_SnapSelectedFaceOrthogonal(Operator):
    bl_idname = "ho.snap_selected_face_orthogonal"
    bl_label = "选择面吸附正交旋转"
    bl_description = "将所选面的综合法向旋转到最接近的世界正交轴，不改变位置"
    bl_options = {'REGISTER', 'UNDO'}

    keep_origin_transform: BoolProperty(
        name="保持原点变换",
        description="保持物体原点的位置和旋转不变，直接旋转网格数据",
        default=True,
    )  # type: ignore

    def draw(self, context):
        self.layout.prop(self, "keep_origin_transform")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        obj = context.active_object
        _points, world_normal, error = selected_face_world_geometry(obj)
        if error is not None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        snap_object_rotation_to_axis(
            obj,
            world_normal,
            context,
            self.keep_origin_transform,
        )
        return {'FINISHED'}


MAX_SURFACE_SAMPLES = 20000


@dataclass
class HullFaceCandidate:
    points: list
    normal: Vector
    area: float


def evaluated_surface_data(obj, depsgraph, use_evaluated_mesh=True):
    evaluated_obj = None
    if use_evaluated_mesh:
        evaluated_obj = obj.evaluated_get(depsgraph)
        mesh = evaluated_obj.to_mesh()
        world_matrix = evaluated_obj.matrix_world
    else:
        mesh = obj.data
        world_matrix = obj.matrix_world

    try:
        world_vertices = [
            world_matrix @ vertex.co
            for vertex in mesh.vertices
        ]
        if not world_vertices:
            return [], [], 0.0

        min_corner = Vector((
            min(point.x for point in world_vertices),
            min(point.y for point in world_vertices),
            min(point.z for point in world_vertices),
        ))
        max_corner = Vector((
            max(point.x for point in world_vertices),
            max(point.y for point in world_vertices),
            max(point.z for point in world_vertices),
        ))
        diagonal = (max_corner - min_corner).length

        polygon_count = len(mesh.polygons)
        sample_step = max(
            1,
            math.ceil(polygon_count / MAX_SURFACE_SAMPLES),
        )
        patches = []
        for polygon_index in range(0, polygon_count, sample_step):
            polygon = mesh.polygons[polygon_index]
            points = [
                world_vertices[vertex_index]
                for vertex_index in polygon.vertices
            ]
            if len(points) < 3:
                continue
            patch_area_vector = polygon_area_vector(points)
            patch_area = patch_area_vector.length
            if patch_area <= 1e-12:
                continue
            patches.append({
                "points": points,
                "center": sum(
                    points,
                    Vector((0.0, 0.0, 0.0)),
                ) / len(points),
                "normal": patch_area_vector.normalized(),
                "area": patch_area * sample_step,
            })

        return world_vertices, patches, diagonal
    finally:
        if evaluated_obj is not None:
            evaluated_obj.to_mesh_clear()


def convex_hull_candidates(world_vertices, coplanar_angle):
    if len(world_vertices) < 4:
        return []

    bm = bmesh.new()
    try:
        for point in world_vertices:
            bm.verts.new(point)
        bm.verts.ensure_lookup_table()

        min_corner = Vector((
            min(point.x for point in world_vertices),
            min(point.y for point in world_vertices),
            min(point.z for point in world_vertices),
        ))
        max_corner = Vector((
            max(point.x for point in world_vertices),
            max(point.y for point in world_vertices),
            max(point.z for point in world_vertices),
        ))
        bmesh.ops.remove_doubles(
            bm,
            verts=list(bm.verts),
            dist=max(1e-9, (max_corner - min_corner).length * 1e-10),
        )
        if len(bm.verts) < 4:
            return []

        hull_result = bmesh.ops.convex_hull(
            bm,
            input=list(bm.verts),
            use_existing_faces=False,
        )
        interior_verts = [
            element
            for element in hull_result.get("geom_interior", ())
            if isinstance(element, bmesh.types.BMVert) and element.is_valid
        ]
        if interior_verts:
            bmesh.ops.delete(bm, geom=interior_verts, context='VERTS')

        bm.normal_update()
        if bm.edges and coplanar_angle > 0.0:
            bmesh.ops.dissolve_limit(
                bm,
                angle_limit=coplanar_angle,
                use_dissolve_boundaries=False,
                verts=list(bm.verts),
                edges=list(bm.edges),
                delimit=set(),
            )
            bm.normal_update()

        hull_verts = [vert for vert in bm.verts if vert.is_valid]
        if not hull_verts:
            return []
        hull_center = sum(
            (vert.co for vert in hull_verts),
            Vector((0.0, 0.0, 0.0)),
        ) / len(hull_verts)

        candidates = []
        for face in bm.faces:
            if not face.is_valid or len(face.verts) < 3:
                continue
            points = [vert.co.copy() for vert in face.verts]
            candidate_area = polygon_area_vector(points).length
            if candidate_area <= 1e-12:
                continue
            center = sum(
                points,
                Vector((0.0, 0.0, 0.0)),
            ) / len(points)
            normal = face.normal.normalized()
            if (center - hull_center).dot(normal) < 0.0:
                normal.negate()
                points.reverse()
            candidates.append(HullFaceCandidate(
                points=points,
                normal=normal,
                area=candidate_area,
            ))
        return candidates
    except (RuntimeError, ValueError):
        return []
    finally:
        bm.free()


def fallback_surface_candidates(surface_patches):
    if not surface_patches:
        return []

    object_center = sum(
        (patch["center"] for patch in surface_patches),
        Vector((0.0, 0.0, 0.0)),
    ) / len(surface_patches)
    result = []
    for patch in sorted(
        surface_patches,
        key=lambda item: item["area"],
        reverse=True,
    ):
        normal = patch["normal"].copy()
        if (patch["center"] - object_center).dot(normal) < 0.0:
            normal.negate()
        if any(
            normal.dot(candidate.normal) > 0.997 and
            abs(
                (patch["center"] - candidate.points[0]).dot(normal)
            ) < 1e-6
            for candidate in result
        ):
            continue
        result.append(HullFaceCandidate(
            points=[point.copy() for point in patch["points"]],
            normal=normal,
            area=patch["area"],
        ))
        if len(result) >= 12:
            break
    return result


def build_candidates(
    obj,
    depsgraph,
    coplanar_angle,
    use_evaluated_mesh=True,
):
    world_vertices, surface_patches, _diagonal = evaluated_surface_data(
        obj,
        depsgraph,
        use_evaluated_mesh,
    )
    candidates = convex_hull_candidates(world_vertices, coplanar_angle)
    return candidates or fallback_surface_candidates(surface_patches)


def ray_hit_candidate(candidates, ray_origin, ray_direction):
    best_index = -1
    best_distance_squared = float('inf')
    for candidate_index, candidate in enumerate(candidates):
        points = candidate.points
        anchor = points[0]
        for index in range(1, len(points) - 1):
            hit = intersect_ray_tri(
                anchor,
                points[index],
                points[index + 1],
                ray_direction,
                ray_origin,
                True,
            )
            if hit is None:
                continue
            distance_squared = (hit - ray_origin).length_squared
            if distance_squared < best_distance_squared:
                best_distance_squared = distance_squared
                best_index = candidate_index
    return best_index


class OP_AutoPlaceObjectBottom(Operator):
    bl_idname = "ho.auto_place_object_bottom"
    bl_label = "自动底面放置"
    bl_description = "生成简化凸包，点击有代表性的平面将物体放置到地面"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    keep_origin_transform: BoolProperty(
        name="保持原点变换",
        description="保持物体原点的位置和旋转不变，直接变换网格数据",
        default=True,
    )  # type: ignore
    placement_point_local: FloatVectorProperty(
        name="放置平面点",
        size=3,
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore
    placement_normal_local: FloatVectorProperty(
        name="放置平面法线",
        size=3,
        default=(0.0, 0.0, 1.0),
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore
    has_placement_plane: BoolProperty(
        name="已有放置平面",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore

    coplanar_angle: FloatProperty(
        name="共面合并角度",
        description="合并凸包上近似共面的相邻面",
        subtype='ANGLE',
        default=math.radians(2.5),
        min=0.0,
        max=math.radians(15.0),
    )  # type: ignore
    merge_coplanar: BoolProperty(
        name="合并近似共面",
        description="合并凸包上法线接近的相邻面",
        default=True,
    )  # type: ignore
    use_evaluated_mesh: BoolProperty(
        name="使用求值后网格",
        description="使用包含可见修改器结果的网格生成凸包",
        default=True,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.area.type == 'VIEW_3D' and
            context.active_object is not None and
            context.active_object.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def draw(self, context):
        self.layout.prop(self, "keep_origin_transform")

    def execute(self, context):
        obj = context.active_object
        if (
            not self.has_placement_plane or
            obj is None or
            obj.type != 'MESH'
        ):
            self.report({'ERROR'}, "没有可重用的凸包放置面")
            return {'CANCELLED'}

        world_matrix = obj.matrix_world.copy()
        plane_point = world_matrix @ Vector(self.placement_point_local)
        normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
        world_normal = (
            normal_matrix @ Vector(self.placement_normal_local)
        ).normalized()
        place_object_on_ground(
            obj,
            [plane_point],
            world_normal,
            context,
            self.keep_origin_transform,
        )
        return {'FINISHED'}

    def _tag_redraw(self, context):
        if context.area is not None:
            context.area.tag_redraw()

    def _update_hover(self, context, event):
        self.mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        self._update_hover_at(context)

    def _update_hover_at(self, context):
        region = context.region
        region_3d = context.space_data.region_3d
        ray_origin = view3d_utils.region_2d_to_origin_3d(
            region,
            region_3d,
            self.mouse,
        )
        ray_direction = view3d_utils.region_2d_to_vector_3d(
            region,
            region_3d,
            self.mouse,
        ).normalized()
        self.hovered_index = ray_hit_candidate(
            self.candidates,
            ray_origin,
            ray_direction,
        )

    def _rebuild_candidates(self, context):
        merge_angle = self.coplanar_angle if self.merge_coplanar else 0.0
        self.candidates = build_candidates(
            self.obj,
            context.evaluated_depsgraph_get(),
            merge_angle,
            self.use_evaluated_mesh,
        )
        self.hovered_index = -1
        if self.candidates:
            self._update_hover_at(context)
        if context.area is not None:
            context.area.header_text_set(
                f"{self.bl_label} | 候选面 {len(self.candidates)}"
            )
        self._tag_redraw(context)

    def draw_preview(self):
        if not self.candidates:
            return

        inactive_polygons = [
            candidate.points
            for index, candidate in enumerate(self.candidates)
            if index != self.hovered_index
        ]
        active_polygons = []
        if 0 <= self.hovered_index < len(self.candidates):
            active_polygons.append(
                self.candidates[self.hovered_index].points
            )

        gpu.state.blend_set('ALPHA')
        shader = foreground_uniform_color_shader()
        if shader is None:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            shader.bind()
            depth_test = 'NONE'
            gpu.state.depth_mask_set(False)
        else:
            shader.bind()
            shader.uniform_float(
                "view_projection",
                gpu.matrix.get_projection_matrix() @
                gpu.matrix.get_model_view_matrix(),
            )
            shader.uniform_float("depth_scale", 0.01)
            depth_test = 'LESS_EQUAL'
            gpu.state.depth_mask_set(True)

        gpu.state.depth_test_set(depth_test)
        draw_polygons(
            shader,
            inactive_polygons,
            fill_color=(0.24, 0.34, 0.40, 0.10),
            line_color=(0.62, 0.76, 0.80, 0.46),
            line_width=1.0,
        )

        if active_polygons:
            gpu.state.depth_test_set(depth_test)
            gpu.state.depth_mask_set(False)
            draw_polygons(
                shader,
                active_polygons,
                fill_color=(0.12, 0.78, 0.34, 0.38),
                line_color=(0.92, 1.0, 0.36, 1.0),
                line_width=2.4,
            )

        restore_3d_state()

    def draw_text(self):
        lines = [
            ("滚轮:", f"共面角度 {math.degrees(self.coplanar_angle):.1f}°"),
            ("M键:", f"合并近似共面 {'开' if self.merge_coplanar else '关'}"),
            ("E键:", "求值后网格" if self.use_evaluated_mesh else "基础网格"),
            ("O键:", f"保持原点变换 {'开' if self.keep_origin_transform else '关'}"),
            ("R键:", "重建凸包"),
            ("候选面:", str(len(self.candidates))),
        ]
        if getattr(self, "show_target_axis_hud", False):
            target_axis = "-"
            if 0 <= self.hovered_index < len(self.candidates):
                target_axis = world_axis_label(nearest_world_axis(
                    self.candidates[self.hovered_index].normal
                ))
            lines.append(("目标轴:", target_axis))

        draw_mouse_hud(self.mouse, lines)

    def finish(self, context):
        handle_3d = getattr(self, "_draw_handle", None)
        handle_text = getattr(self, "_text_handle", None)
        if handle_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle_3d, 'WINDOW')
            self._draw_handle = None
        if handle_text is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle_text, 'WINDOW')
            self._text_handle = None
        if context.area is not None:
            context.area.header_text_set(None)
        self._tag_redraw(context)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self.finish(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            self._update_hover(context, event)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELUPMOUSE':
            self.merge_coplanar = True
            self.coplanar_angle = min(
                math.radians(15.0),
                self.coplanar_angle + math.radians(0.5),
            )
            self._rebuild_candidates(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELDOWNMOUSE':
            self.merge_coplanar = True
            self.coplanar_angle = max(
                0.0,
                self.coplanar_angle - math.radians(0.5),
            )
            self._rebuild_candidates(context)
            return {'RUNNING_MODAL'}

        if event.type == 'M' and event.value == 'PRESS':
            self.merge_coplanar = not self.merge_coplanar
            self._rebuild_candidates(context)
            return {'RUNNING_MODAL'}

        if event.type == 'E' and event.value == 'PRESS':
            self.use_evaluated_mesh = not self.use_evaluated_mesh
            self._rebuild_candidates(context)
            return {'RUNNING_MODAL'}

        if event.type == 'O' and event.value == 'PRESS':
            self.keep_origin_transform = not self.keep_origin_transform
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'R' and event.value == 'PRESS':
            self._rebuild_candidates(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.hovered_index < 0:
                return {'RUNNING_MODAL'}
            candidate = self.candidates[self.hovered_index]
            world_matrix = self.obj.matrix_world.copy()
            face_center = sum(
                candidate.points,
                Vector((0.0, 0.0, 0.0)),
            ) / len(candidate.points)
            self.placement_point_local = (
                world_matrix.inverted_safe() @ face_center
            )
            self.placement_normal_local = (
                world_matrix.to_3x3().transposed() @ candidate.normal
            ).normalized()
            self.has_placement_plane = True
            self.finish(context)
            return self.execute(context)

        if event.type in {
            'MIDDLEMOUSE',
            'NUMPAD_1',
            'NUMPAD_2',
            'NUMPAD_3',
            'NUMPAD_4',
            'NUMPAD_5',
            'NUMPAD_6',
            'NUMPAD_7',
            'NUMPAD_8',
            'NUMPAD_9',
        }:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        self.obj = context.active_object
        self.has_placement_plane = False
        if context.mode == 'EDIT_MESH':
            bmesh.update_edit_mesh(self.obj.data, destructive=False)

        self.mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
        self.candidates = []
        self.hovered_index = -1
        self._rebuild_candidates(context)
        if not self.candidates:
            self.report({'ERROR'}, "无法从当前网格生成有效的凸包放置面")
            return {'CANCELLED'}

        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview,
            (),
            'WINDOW',
            'POST_VIEW',
        )
        self._text_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_text,
            (),
            'WINDOW',
            'POST_PIXEL',
        )
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {'RUNNING_MODAL'}


class OP_AutoSnapFaceOrthogonal(Operator):
    bl_idname = "ho.auto_snap_face_orthogonal"
    bl_label = "自动面吸附正交旋转"
    bl_description = "生成凸包并点击候选面，将其法向旋转到最接近的世界正交轴"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
    show_target_axis_hud = True

    keep_origin_transform: BoolProperty(
        name="保持原点变换",
        description="保持物体原点的位置和旋转不变，直接旋转网格数据",
        default=True,
    )  # type: ignore
    placement_point_local: FloatVectorProperty(
        name="目标平面点",
        size=3,
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore
    placement_normal_local: FloatVectorProperty(
        name="目标平面法线",
        size=3,
        default=(0.0, 0.0, 1.0),
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore
    has_placement_plane: BoolProperty(
        name="已有目标平面",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )  # type: ignore
    coplanar_angle: FloatProperty(
        name="共面合并角度",
        description="合并凸包上近似共面的相邻面",
        subtype='ANGLE',
        default=math.radians(2.5),
        min=0.0,
        max=math.radians(15.0),
    )  # type: ignore
    merge_coplanar: BoolProperty(
        name="合并近似共面",
        description="合并凸包上法线接近的相邻面",
        default=True,
    )  # type: ignore
    use_evaluated_mesh: BoolProperty(
        name="使用求值后网格",
        description="使用包含可见修改器结果的网格生成凸包",
        default=True,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return OP_AutoPlaceObjectBottom.poll(context)

    def draw(self, context):
        self.layout.prop(self, "keep_origin_transform")

    def execute(self, context):
        obj = context.active_object
        if (
            not self.has_placement_plane or
            obj is None or
            obj.type != 'MESH'
        ):
            self.report({'ERROR'}, "没有可重用的凸包目标面")
            return {'CANCELLED'}

        world_matrix = obj.matrix_world.copy()
        normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
        world_normal = (
            normal_matrix @ Vector(self.placement_normal_local)
        ).normalized()
        snap_object_rotation_to_axis(
            obj,
            world_normal,
            context,
            self.keep_origin_transform,
        )
        return {'FINISHED'}

    _tag_redraw = OP_AutoPlaceObjectBottom._tag_redraw
    _update_hover = OP_AutoPlaceObjectBottom._update_hover
    _update_hover_at = OP_AutoPlaceObjectBottom._update_hover_at
    _rebuild_candidates = OP_AutoPlaceObjectBottom._rebuild_candidates
    draw_preview = OP_AutoPlaceObjectBottom.draw_preview
    draw_text = OP_AutoPlaceObjectBottom.draw_text
    finish = OP_AutoPlaceObjectBottom.finish
    modal = OP_AutoPlaceObjectBottom.modal
    invoke = OP_AutoPlaceObjectBottom.invoke
