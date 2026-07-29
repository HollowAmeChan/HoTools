from dataclasses import dataclass
import math

import bmesh
import bpy
import gpu
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector
from mathutils.geometry import intersect_ray_tri

from .viewport_draw import draw_polygons, restore_3d_state


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


def ground_alignment_matrix(world_matrix, plane_points, world_normal):
    normal = world_normal.normalized()
    target_normal = Vector((0.0, 0.0, -1.0))
    dot = max(-1.0, min(1.0, normal.dot(target_normal)))

    if dot >= 1.0 - 1e-10:
        rotation = Matrix.Identity(4)
    elif dot <= -1.0 + 1e-10:
        reference = (
            Vector((1.0, 0.0, 0.0))
            if abs(normal.x) < 0.9
            else Vector((0.0, 1.0, 0.0))
        )
        axis = normal.cross(reference).normalized()
        rotation = Matrix.Rotation(math.pi, 4, axis)
    else:
        axis = normal.cross(target_normal)
        angle = math.atan2(axis.length, dot)
        rotation = Matrix.Rotation(angle, 4, axis.normalized())

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


def place_object_on_ground(
    obj,
    plane_points,
    world_normal,
    context,
    keep_origin_transform=True,
):
    original_world_matrix = obj.matrix_world.copy()
    target_world_matrix = ground_alignment_matrix(
        original_world_matrix,
        plane_points,
        world_normal,
    )
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
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.normal_update()

        selected_faces = [
            face for face in bm.faces
            if face.select and not face.hide
        ]
        if not selected_faces:
            self.report({'ERROR'}, "未选择任何面")
            return {'CANCELLED'}

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
            self.report({'ERROR'}, "所选面退化或法线互相抵消，无法确定底面方向")
            return {'CANCELLED'}

        points = list(selected_world_points.values())
        place_object_on_ground(
            obj,
            points,
            normal_sum.normalized(),
            context,
            self.keep_origin_transform,
        )

        return {'FINISHED'}


MAX_SURFACE_SAMPLES = 20000
MAX_SUPPORT_CANDIDATES = 160
MAX_DISPLAY_CANDIDATES = 48


@dataclass
class HullFaceCandidate:
    points: list
    normal: Vector
    area: float
    support_ratio: float = 0.0
    score: float = 0.0


def evaluated_surface_data(obj, depsgraph):
    evaluated_obj = obj.evaluated_get(depsgraph)
    mesh = evaluated_obj.to_mesh()
    try:
        world_matrix = evaluated_obj.matrix_world
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
            support_ratio=1.0,
            score=1.0,
        ))
        if len(result) >= 12:
            break
    return result


def filter_hull_candidates(
    candidates,
    surface_patches,
    diagonal,
    min_face_area_ratio,
    support_angle,
    support_distance_ratio,
):
    if not candidates:
        return fallback_surface_candidates(surface_patches)

    total_hull_area = sum(candidate.area for candidate in candidates)
    max_area = max(candidate.area for candidate in candidates)
    min_area = max(
        total_hull_area * min_face_area_ratio,
        max_area * 0.012,
        diagonal * diagonal * 1e-8,
    )
    significant = [
        candidate
        for candidate in candidates
        if candidate.area >= min_area
    ]
    if not significant:
        significant = sorted(
            candidates,
            key=lambda candidate: candidate.area,
            reverse=True,
        )[:12]

    support_pool = sorted(
        significant,
        key=lambda candidate: candidate.area,
        reverse=True,
    )[:MAX_SUPPORT_CANDIDATES]
    normal_threshold = math.cos(support_angle)
    distance_limit = max(diagonal * support_distance_ratio, 1e-7)

    for candidate in support_pool:
        plane_point = candidate.points[0]
        support_area = 0.0
        for patch in surface_patches:
            if abs(candidate.normal.dot(patch["normal"])) < normal_threshold:
                continue
            plane_distance = abs(
                (patch["center"] - plane_point).dot(candidate.normal)
            )
            if plane_distance <= distance_limit:
                support_area += patch["area"]

        candidate.support_ratio = support_area / max(candidate.area, 1e-12)
        area_weight = math.pow(candidate.area / max_area, 0.35)
        candidate.score = min(candidate.support_ratio, 4.0) * area_weight

    supported = [
        candidate
        for candidate in support_pool
        if candidate.support_ratio >= 0.10
    ]
    ranked = sorted(
        supported or support_pool,
        key=lambda candidate: (candidate.score, candidate.area),
        reverse=True,
    )

    if len(ranked) < min(6, len(support_pool)):
        for candidate in sorted(
            support_pool,
            key=lambda item: item.area,
            reverse=True,
        ):
            if candidate not in ranked:
                ranked.append(candidate)
            if len(ranked) >= min(6, len(support_pool)):
                break

    return ranked[:MAX_DISPLAY_CANDIDATES]


def build_candidates(
    obj,
    depsgraph,
    coplanar_angle,
    min_face_area_ratio,
    support_angle,
    support_distance_ratio,
):
    world_vertices, surface_patches, diagonal = evaluated_surface_data(
        obj,
        depsgraph,
    )
    candidates = convex_hull_candidates(world_vertices, coplanar_angle)
    return filter_hull_candidates(
        candidates,
        surface_patches,
        diagonal,
        min_face_area_ratio,
        support_angle,
        support_distance_ratio,
    )


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

    coplanar_angle: FloatProperty(
        name="共面合并角度",
        description="合并凸包上近似共面的相邻面",
        subtype='ANGLE',
        default=math.radians(2.5),
        min=0.0,
        max=math.radians(15.0),
    )  # type: ignore
    min_face_area_ratio: FloatProperty(
        name="最小面面积比例",
        description="排除无法代表稳定放置面的细小凸包面",
        default=0.002,
        min=0.0001,
        max=0.05,
        subtype='FACTOR',
    )  # type: ignore
    support_angle: FloatProperty(
        name="表面贴合角度",
        description="原网格表面与凸包候选面的最大法线夹角",
        subtype='ANGLE',
        default=math.radians(12.0),
        min=math.radians(1.0),
        max=math.radians(45.0),
    )  # type: ignore
    support_distance_ratio: FloatProperty(
        name="表面贴合距离",
        description="按物体尺寸计算原网格对凸包平面的支持距离",
        default=0.006,
        min=0.0001,
        max=0.05,
        subtype='FACTOR',
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.area.type == 'VIEW_3D' and
            context.active_object is not None and
            context.active_object.type == 'MESH' and
            context.mode in {'OBJECT', 'EDIT_MESH'}
        )

    def _tag_redraw(self, context):
        if context.area is not None:
            context.area.tag_redraw()

    def _update_hover(self, context, event):
        self.mouse = Vector((
            event.mouse_region_x,
            event.mouse_region_y,
        ))
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
        gpu.state.depth_mask_set(False)
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader.bind()

        gpu.state.depth_test_set('LESS_EQUAL')
        draw_polygons(
            shader,
            inactive_polygons,
            fill_color=(0.24, 0.34, 0.40, 0.10),
            line_color=(0.62, 0.76, 0.80, 0.46),
            line_width=1.0,
        )

        if active_polygons:
            gpu.state.depth_test_set('NONE')
            draw_polygons(
                shader,
                active_polygons,
                fill_color=(0.12, 0.78, 0.34, 0.38),
                line_color=(0.92, 1.0, 0.36, 1.0),
                line_width=2.4,
            )

        restore_3d_state()

    def finish(self, context):
        handle = getattr(self, "_draw_handle", None)
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            self._draw_handle = None
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

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self.hovered_index < 0:
                return {'RUNNING_MODAL'}
            candidate = self.candidates[self.hovered_index]
            place_object_on_ground(
                self.obj,
                candidate.points,
                candidate.normal,
                context,
                self.keep_origin_transform,
            )
            self.finish(context)
            return {'FINISHED'}

        if event.type in {
            'MIDDLEMOUSE',
            'WHEELUPMOUSE',
            'WHEELDOWNMOUSE',
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
        if context.mode == 'EDIT_MESH':
            bmesh.update_edit_mesh(self.obj.data, destructive=False)

        self.candidates = build_candidates(
            self.obj,
            context.evaluated_depsgraph_get(),
            self.coplanar_angle,
            self.min_face_area_ratio,
            self.support_angle,
            self.support_distance_ratio,
        )
        if not self.candidates:
            self.report({'ERROR'}, "无法从当前网格生成有效的凸包放置面")
            return {'CANCELLED'}

        self.hovered_index = -1
        self._update_hover(context, event)
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview,
            (),
            'WINDOW',
            'POST_VIEW',
        )
        context.area.header_text_set(
            f"自动底面放置 | 候选面 {len(self.candidates)}"
        )
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {'RUNNING_MODAL'}
