import math

import bmesh
from bpy.types import Operator
from mathutils import Matrix, Vector


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


def place_object_on_ground(obj, plane_points, world_normal, view_layer):
    target_world_matrix = ground_alignment_matrix(
        obj.matrix_world.copy(),
        plane_points,
        world_normal,
    )
    apply_world_matrix(obj, target_world_matrix, view_layer)


class OP_PlaceObjectBottom(Operator):
    bl_idname = "ho.placeobjectbottom"
    bl_label = "选择底面放置"
    bl_description = "使用选择的面作为底面，旋转物体使底面贴合水平面摆放"
    bl_options = {'REGISTER', 'UNDO'}

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
            context.view_layer,
        )

        return {'FINISHED'}
