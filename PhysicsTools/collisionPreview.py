import bpy
import gpu
import math
import mathutils
from gpu_extras.batch import batch_for_shader

from .collisionUtils import (
    _COLLISION_GROUP_COUNT,
    _ROOT_COLOR,
    _SHAPE_SEGMENTS,
    _collision_group_color,
    _collision_props,
    _object_collision_props,
)


_DRAW_HANDLE = None


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
    center = mathutils.Vector(props.offset)
    radius = max(float(props.radius), 0.0)
    x_axis = mathutils.Vector((1.0, 0.0, 0.0))
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    z_axis = mathutils.Vector((0.0, 0.0, 1.0))

    _append_circle(lines, matrix, center, x_axis, y_axis, radius)
    _append_circle(lines, matrix, center, x_axis, z_axis, radius)
    _append_circle(lines, matrix, center, y_axis, z_axis, radius)


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


def _append_spring_root_marker(lines, matrix, bone):
    length = max(float(getattr(bone, "length", 0.0)), 0.001)
    radius = min(max(length * 0.08, 0.015), 0.08)
    center = mathutils.Vector((0.0, 0.0, 0.0))
    x_axis = mathutils.Vector((1.0, 0.0, 0.0))
    y_axis = mathutils.Vector((0.0, 1.0, 0.0))
    z_axis = mathutils.Vector((0.0, 0.0, 1.0))

    _append_circle(lines, matrix, center, x_axis, z_axis, radius, segments=16)
    _append_line(lines, matrix @ (center - x_axis * radius), matrix @ (center + x_axis * radius))
    _append_line(lines, matrix @ (center - y_axis * radius), matrix @ (center + y_axis * radius))
    _append_line(lines, matrix @ (center - z_axis * radius), matrix @ (center + z_axis * radius))


def _draw_line_batch(shader, coords, color, line_width):
    if not coords:
        return

    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.line_width_set(line_width)
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    batch.draw(shader)


def _draw_collision_overlay():
    context = bpy.context
    scene = context.scene
    if scene is None or not getattr(scene, "ho_bone_collision_overlay_show", False):
        return

    collision_lines_by_group = {
        group: []
        for group in range(1, _COLLISION_GROUP_COUNT + 1)
    }
    root_lines = []

    for armature_obj in _visible_armature_objects(context):
        for bone in armature_obj.data.bones:
            props = _collision_props(bone)
            if props is None:
                continue

            matrix = _bone_draw_matrix(armature_obj, bone)
            if props.spring_root:
                _append_spring_root_marker(root_lines, matrix, bone)

            group_lines = collision_lines_by_group[
                min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)
            ]
            if props.collision_type == "SPHERE":
                _append_sphere_lines(group_lines, matrix, props)
            elif props.collision_type == "CAPSULE":
                _append_capsule_lines(group_lines, matrix, props)

    for obj in _visible_object_collision_objects(context):
        props = _object_collision_props(obj)
        if props is None:
            continue

        group_lines = collision_lines_by_group[
            min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)
        ]
        if props.collision_type == "SPHERE":
            _append_sphere_lines(group_lines, obj.matrix_world, props)
        elif props.collision_type == "CAPSULE":
            _append_capsule_lines(group_lines, obj.matrix_world, props)

    if not any(collision_lines_by_group.values()) and not root_lines:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for group, group_lines in collision_lines_by_group.items():
            _draw_line_batch(shader, group_lines, _collision_group_color(group), 1.5)
        _draw_line_batch(shader, root_lines, _ROOT_COLOR, 2.0)
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
