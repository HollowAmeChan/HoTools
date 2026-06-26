import bpy
import gpu
import math
import mathutils
from bpy.types import Panel
from gpu_extras.batch import batch_for_shader

from ..i18n import tr
from .collisionUtils import (
    _COLLISION_GROUP_COUNT,
    _PIN_COLOR,
    _SHAPE_SEGMENTS,
    _UNPIN_COLOR,
    _collision_group_color,
    _collision_props,
    _effective_bone_pin,
    _mesh_collision_props,
    _object_collision_props,
)


_DRAW_HANDLE = None
_MESH_VERTEX_SPHERE_SEGMENTS = 8


def _visible_armature_objects(context):
    visible_objects = getattr(context, "visible_objects", None)
    if visible_objects is None:
        visible_objects = context.view_layer.objects

    return [
        obj
        for obj in visible_objects
        if obj.type == "ARMATURE" and obj.visible_get()
    ]


def _visible_object_collision_objects(context):
    visible_objects = getattr(context, "visible_objects", None)
    if visible_objects is None:
        visible_objects = context.view_layer.objects

    result = []
    for obj in visible_objects:
        if not obj.visible_get():
            continue
        props = _object_collision_props(obj)
        if props is not None and props.collision_type != "NONE":
            result.append(obj)
    return result


def _visible_mesh_collision_objects(context):
    visible_objects = getattr(context, "visible_objects", None)
    if visible_objects is None:
        visible_objects = context.view_layer.objects

    result = []
    for obj in visible_objects:
        if obj.type != "MESH" or not obj.visible_get():
            continue
        props = _mesh_collision_props(obj)
        if props is not None and props.enabled and props.radius > 0.0:
            result.append(obj)
    return result


def _bone_draw_matrix(armature_obj, bone):
    pose_bone = armature_obj.pose.bones.get(bone.name) if armature_obj.pose else None
    if pose_bone is not None:
        return armature_obj.matrix_world @ pose_bone.matrix

    return armature_obj.matrix_world @ bone.matrix_local


def _append_line(lines, point_a, point_b):
    lines.append(tuple(point_a))
    lines.append(tuple(point_b))


def _append_circle(lines, matrix, center, axis_a, axis_b, radius, segments=_SHAPE_SEGMENTS):
    if radius <= 0.0:
        return

    first = matrix @ (center + axis_a * radius)
    previous = first
    for index in range(1, segments + 1):
        angle = math.tau * index / segments
        point = matrix @ (
            center
            + axis_a * math.cos(angle) * radius
            + axis_b * math.sin(angle) * radius
        )
        _append_line(lines, previous, point)
        previous = point


def _append_capsule_profile(lines, matrix, center, side_axis, radius, half_length, segments=_SHAPE_SEGMENTS):
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    top = center + y_axis * half_length
    bottom = center - y_axis * half_length

    _append_line(lines, matrix @ (bottom + side_axis * radius), matrix @ (top + side_axis * radius))
    _append_line(lines, matrix @ (top - side_axis * radius), matrix @ (bottom - side_axis * radius))

    half_segments = max(8, segments // 2)
    previous = matrix @ (top + side_axis * radius)
    for index in range(1, half_segments + 1):
        angle = math.pi * index / half_segments
        point = matrix @ (
            top
            + side_axis * math.cos(angle) * radius
            + y_axis * math.sin(angle) * radius
        )
        _append_line(lines, previous, point)
        previous = point

    previous = matrix @ (bottom - side_axis * radius)
    for index in range(1, half_segments + 1):
        angle = math.pi + math.pi * index / half_segments
        point = matrix @ (
            bottom
            + side_axis * math.cos(angle) * radius
            + y_axis * math.sin(angle) * radius
        )
        _append_line(lines, previous, point)
        previous = point


def _append_sphere_lines(lines, matrix, props):
    _append_sphere_shape_lines(
        lines,
        matrix,
        mathutils.Vector(props.offset),
        max(float(props.radius), 0.0),
    )


def _append_sphere_shape_lines(lines, matrix, center, radius, segments=_SHAPE_SEGMENTS):
    x_axis = mathutils.Vector((1.0, 0.0, 0.0))
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    z_axis = mathutils.Vector((0.0, 0.0, 1.0))

    _append_circle(lines, matrix, center, x_axis, y_axis, radius, segments=segments)
    _append_circle(lines, matrix, center, x_axis, z_axis, radius, segments=segments)
    _append_circle(lines, matrix, center, y_axis, z_axis, radius, segments=segments)


def _append_capsule_lines(lines, matrix, props):
    center = mathutils.Vector(props.offset)
    radius = max(float(props.radius), 0.0)
    half_length = max(float(props.length), 0.0) * 0.5
    x_axis = mathutils.Vector((1.0, 0.0, 0.0))
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    z_axis = mathutils.Vector((0.0, 0.0, 1.0))

    top = center + y_axis * half_length
    bottom = center - y_axis * half_length
    _append_circle(lines, matrix, top, x_axis, z_axis, radius)
    _append_circle(lines, matrix, bottom, x_axis, z_axis, radius)
    _append_capsule_profile(lines, matrix, center, x_axis, radius, half_length)
    _append_capsule_profile(lines, matrix, center, z_axis, radius, half_length)


def _append_plane_lines(lines, matrix, props):
    # 平面碰撞体本身是无限边界；叠加层只画一个局部 XY 方片和四根 +Z 法线射线帮助用户判断朝向。
    # matrix 必须传入 Object.matrix_world，和胶囊体一样从最终世界矩阵解析碰撞变换；不要拆读 location/rotation/scale。
    # 世界原点 = matrix_world @ offset；世界切线来自 matrix_world.to_3x3() 变换局部 X/Y；法线等价于两条世界切线叉乘后的 +Z 方向。
    # 平面碰撞体通常作为父级下的子物体摆放，父级位移/旋转/缩放都要体现在预览和后续求解器输入里。
    center = mathutils.Vector(props.offset)
    half_size = max(float(props.length), 1.0) * 0.5
    ray_length = max(half_size * 1.25, 0.75)
    x_axis = mathutils.Vector((1.0, 0.0, 0.0))
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    z_axis = mathutils.Vector((0.0, 0.0, 1.0))

    corners = [
        center - x_axis * half_size - y_axis * half_size,
        center + x_axis * half_size - y_axis * half_size,
        center + x_axis * half_size + y_axis * half_size,
        center - x_axis * half_size + y_axis * half_size,
    ]

    for index, corner in enumerate(corners):
        _append_line(lines, matrix @ corner, matrix @ corners[(index + 1) % len(corners)])
        _append_line(lines, matrix @ corner, matrix @ (corner - z_axis * ray_length))


def _append_box_lines(lines, matrix, props):
    # 长方体是 Object 级有向盒；matrix 必须传入 Object.matrix_world，保证父级、约束和动画后的最终世界变换被消费。
    # 求解器应使用同一规则：world_center = matrix_world @ offset，world_axes 来自 matrix_world.to_3x3()，半长来自 box_size * 0.5。
    center = mathutils.Vector(props.offset)
    size = mathutils.Vector(getattr(props, "box_size", (1.0, 1.0, 1.0)))
    half = mathutils.Vector((
        max(float(size.x), 0.0) * 0.5,
        max(float(size.y), 0.0) * 0.5,
        max(float(size.z), 0.0) * 0.5,
    ))
    if half.x <= 0.0 and half.y <= 0.0 and half.z <= 0.0:
        return

    corners = [
        center + mathutils.Vector((sx * half.x, sy * half.y, sz * half.z))
        for sx, sy, sz in (
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        )
    ]

    for start, end in (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ):
        _append_line(lines, matrix @ corners[start], matrix @ corners[end])


def _draw_line_batch(shader, coords, color, line_width):
    if not coords:
        return

    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.line_width_set(line_width)
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    batch.draw(shader)


def _mesh_vertex_collision_weight(obj, group_name, vertex_index):
    if not group_name:
        return 1.0

    vertex_group = obj.vertex_groups.get(group_name)
    if vertex_group is None:
        return 0.0

    try:
        return min(max(float(vertex_group.weight(vertex_index)), 0.0), 1.0)
    except RuntimeError:
        return 0.0


def _evaluated_mesh_vertices(obj, depsgraph):
    evaluated_obj = obj.evaluated_get(depsgraph)
    evaluated_mesh = None
    try:
        try:
            evaluated_mesh = evaluated_obj.to_mesh(depsgraph=depsgraph)
        except TypeError:
            evaluated_mesh = evaluated_obj.to_mesh()

        if evaluated_mesh is None or len(evaluated_mesh.vertices) != len(obj.data.vertices):
            return obj.matrix_world, [vertex.co.copy() for vertex in obj.data.vertices]

        return evaluated_obj.matrix_world.copy(), [vertex.co.copy() for vertex in evaluated_mesh.vertices]
    finally:
        if evaluated_mesh is not None:
            evaluated_obj.to_mesh_clear()


def _mesh_vertex_is_pinned(obj, props, vertex_index):
    if not props.pin_enabled:
        return False
    return _mesh_vertex_collision_weight(obj, str(props.pin_vertex_group or ""), vertex_index) > 0.0


def _append_mesh_vertex_collision_lines(lines, obj, props, depsgraph, *, pin_lines=None, unpin_lines=None):
    radius = max(float(props.radius), 0.0)
    if radius <= 0.0:
        return

    group_name = str(props.radius_vertex_group or "")
    matrix, vertex_coords = _evaluated_mesh_vertices(obj, depsgraph)
    for vertex_index, vertex_co in enumerate(vertex_coords):
        weight = _mesh_vertex_collision_weight(obj, group_name, vertex_index)
        if weight <= 0.0:
            continue
        target_lines = lines
        if pin_lines is not None and unpin_lines is not None:
            target_lines = pin_lines if _mesh_vertex_is_pinned(obj, props, vertex_index) else unpin_lines
        _append_sphere_shape_lines(
            target_lines,
            matrix,
            vertex_co,
            radius * weight,
            segments=_MESH_VERTEX_SPHERE_SEGMENTS,
        )


def _draw_collision_overlay():
    context = bpy.context
    scene = context.scene
    if scene is None or not scene.ho_collision_overlay_show:
        return

    show_bone_collision = scene.ho_collision_overlay_show_bone
    show_object_collision = scene.ho_collision_overlay_show_object
    show_mesh_vertices = scene.ho_collision_overlay_show_mesh_vertices
    use_pin_color = scene.ho_collision_overlay_color_mode == "PIN"

    collision_lines_by_group = {
        group: []
        for group in range(1, _COLLISION_GROUP_COUNT + 1)
    }
    mesh_vertex_lines_by_group = {
        group: []
        for group in range(1, _COLLISION_GROUP_COUNT + 1)
    }
    pin_lines = []
    unpin_lines = []

    if show_bone_collision:
        for armature_obj in _visible_armature_objects(context):
            for bone in armature_obj.data.bones:
                props = _collision_props(bone)
                if props is None:
                    continue

                matrix = _bone_draw_matrix(armature_obj, bone)
                if use_pin_color:
                    group_lines = pin_lines if _effective_bone_pin(bone) else unpin_lines
                else:
                    group_lines = collision_lines_by_group[
                        min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)
                    ]
                if props.collision_type == "SPHERE":
                    _append_sphere_lines(group_lines, matrix, props)
                elif props.collision_type == "CAPSULE":
                    _append_capsule_lines(group_lines, matrix, props)

    if show_object_collision:
        for obj in _visible_object_collision_objects(context):
            props = _object_collision_props(obj)
            if props is None:
                continue

            if use_pin_color:
                group_lines = unpin_lines
            else:
                group_lines = collision_lines_by_group[
                    min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)
                ]
            if props.collision_type == "SPHERE":
                _append_sphere_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "CAPSULE":
                _append_capsule_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "PLANE":
                _append_plane_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "BOX":
                _append_box_lines(group_lines, obj.matrix_world, props)

    if show_mesh_vertices:
        depsgraph = context.evaluated_depsgraph_get()
        for obj in _visible_mesh_collision_objects(context):
            props = _mesh_collision_props(obj)
            if props is not None:
                if use_pin_color:
                    _append_mesh_vertex_collision_lines(
                        [],
                        obj,
                        props,
                        depsgraph,
                        pin_lines=pin_lines,
                        unpin_lines=unpin_lines,
                    )
                else:
                    group = min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)
                    _append_mesh_vertex_collision_lines(mesh_vertex_lines_by_group[group], obj, props, depsgraph)

    if (
        not any(collision_lines_by_group.values())
        and not any(mesh_vertex_lines_by_group.values())
        and not pin_lines
        and not unpin_lines
    ):
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for group, group_lines in collision_lines_by_group.items():
            _draw_line_batch(shader, group_lines, _collision_group_color(group), 1.5)
        for group, group_lines in mesh_vertex_lines_by_group.items():
            _draw_line_batch(shader, group_lines, _collision_group_color(group), 1.0)
        _draw_line_batch(shader, pin_lines, _PIN_COLOR, 1.5)
        _draw_line_batch(shader, unpin_lines, _UNPIN_COLOR, 1.0)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")


def _ensure_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            _draw_collision_overlay,
            (),
            "WINDOW",
            "POST_VIEW",
        )


def _remove_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None


class PT_Hotools_CollisionOverlayPopover(Panel):
    bl_idname = "VIEW3D_PT_Hotools_CollisionOverlayPopover"
    bl_label = "HoTools碰撞预览"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_ui_units_x = 12

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(scene, "ho_collision_overlay_show", text=tr("显示碰撞预览"))

        col = layout.column(align=True)
        col.enabled = bool(scene.ho_collision_overlay_show)
        col.prop(scene, "ho_collision_overlay_color_mode", text=tr("颜色模式"))
        col.separator()
        col.prop(scene, "ho_collision_overlay_show_bone", text=tr("骨骼碰撞体"))
        col.prop(scene, "ho_collision_overlay_show_object", text=tr("物体碰撞体"))
        col.prop(scene, "ho_collision_overlay_show_mesh_vertices", text=tr("网格逐顶点球"))
        if scene.ho_collision_overlay_show_mesh_vertices:
            hint = col.column(align=True)
            hint.label(text=tr("提示：带修改器的网格逐顶点球预览"), icon="INFO")
            hint.label(text=tr("暂不保证跟随最终变形"))


def draw_collision_overlay_header(self, context):
    scene = context.scene
    if scene is None:
        return

    row = self.layout.row(align=True)
    row.prop(
        scene,
        "ho_collision_overlay_show",
        text="",
        icon="MESH_UVSPHERE",
        toggle=True,
    )
    row.popover(
        panel=PT_Hotools_CollisionOverlayPopover.bl_idname,
        text="",
    )
