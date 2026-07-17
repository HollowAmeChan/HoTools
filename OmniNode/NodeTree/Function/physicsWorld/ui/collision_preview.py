import bpy
import gpu
import math
import mathutils
from bpy.types import Panel
from gpu_extras.batch import batch_for_shader

from .utils import (
    _COLLISION_GROUP_COUNT,
    _PIN_COLOR,
    _SHAPE_SEGMENTS,
    _UNPIN_COLOR,
    _collision_group_color,
    _collision_group_bit,
    _collision_props,
    _effective_bone_pin,
    _object_collision_props,
)


_DRAW_HANDLE = None

# 预计算单位圆 cos/sin 值，避免每次绘制球/胶囊时重复调用 math.cos/sin。
# 每根骨骼3个圆 × 32段 = 96 次三角函数 → 0 次（全部变查表+向量乘法）。
_UNIT_CIRCLE = [
    (math.cos(math.tau * i / _SHAPE_SEGMENTS), math.sin(math.tau * i / _SHAPE_SEGMENTS))
    for i in range(_SHAPE_SEGMENTS + 1)  # +1 使最后一点闭合回原点
]

COLLISION_OVERLAY_PREVIEW_MODE_ITEMS = [("STANDARD", "标准", "标准碰撞预览")]
for group in range(1, _COLLISION_GROUP_COUNT + 1):
    COLLISION_OVERLAY_PREVIEW_MODE_ITEMS.append(
        (
            f"GROUP_INTERACTION_{group}",
            f"碰撞组交互检查{group}",
            f"仅显示会与碰撞组{group}发生交互的碰撞体",
        )
    )


def _visible_armature_objects(context):
    visible_objects = getattr(context, "visible_objects", None)
    if visible_objects is None:
        visible_objects = context.view_layer.objects

    return [
        obj
        for obj in visible_objects
        if obj.type == "ARMATURE" and obj.visible_get()
    ]


def _bone_is_effectively_visible(bone):
    if getattr(bone, "hide", False):
        return False

    visible = getattr(bone, "visible", None)
    if visible is not None:
        return bool(visible)

    collections = getattr(bone, "collections", None)
    if collections is not None:
        for collection in collections:
            if getattr(collection, "is_visible_effectively", False):
                return True
        return False

    return True


def _collision_overlay_preview_mode_group(preview_mode):
    if not isinstance(preview_mode, str) or not preview_mode.startswith("GROUP_INTERACTION_"):
        return None

    try:
        group = int(preview_mode.rsplit("_", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None

    if 1 <= group <= _COLLISION_GROUP_COUNT:
        return group
    return None


def _collision_overlay_matches_preview_group(props, preview_group, include_passive=False):
    if preview_group is None:
        return True

    try:
        primary_group = int(getattr(props, "primary_collision_group", 1))
    except (TypeError, ValueError):
        primary_group = 1
    primary_group = min(max(primary_group, 1), _COLLISION_GROUP_COUNT)
    if primary_group == preview_group:
        return True

    if not include_passive:
        return False

    try:
        collided_by_groups = int(getattr(props, "collided_by_groups", 0) or 0)
    except (TypeError, ValueError):
        collided_by_groups = 0
    return _collision_group_bit(collided_by_groups, preview_group)


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

    # 默认 segments 时使用预计算表，避免每次重算 cos/sin
    cos_sin = _UNIT_CIRCLE if segments == _SHAPE_SEGMENTS else [
        (math.cos(math.tau * i / segments), math.sin(math.tau * i / segments))
        for i in range(segments + 1)
    ]

    scaled_a = axis_a * radius
    scaled_b = axis_b * radius
    points = [matrix @ (center + c * scaled_a + s * scaled_b) for c, s in cos_sin]
    for i in range(len(points) - 1):
        _append_line(lines, points[i], points[i + 1])


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
    # 平面碰撞体本身是无限边界。
    # 预览里只画一个局部 XY 片和四根 +Z 射线，帮助判断朝向。
    # matrix 必须使用 Object.matrix_world，不要拆读 location / rotation / scale。
    # 世界原点 = matrix_world @ offset，世界切线来自 matrix_world.to_3x3() 变换局部 X/Y。
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
    # 长方体是 Object 级有向盒。
    # matrix 必须使用 Object.matrix_world，保证父级、约束和动画后的最终世界变换被消耗。
    # world_center = matrix_world @ offset，world_axes 来自 matrix_world.to_3x3()，半长来自 box_size * 0.5。
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



def _draw_collision_overlay():
    """
    Draw handler 回调，每次视口重绘都执行。
    骨骼/物体碰撞每次重建（矩阵运算，很快）。
    MC2 粒子半径由 solver 的隐式 debug 快照绘制，不在这里重算。
    """
    context = bpy.context
    scene = context.scene
    if scene is None or not scene.ho_collision_overlay_show:
        return

    preview_group = _collision_overlay_preview_mode_group(scene.ho_collision_overlay_preview_mode)
    include_passive_collision = bool(scene.ho_collision_overlay_include_passive_collision) and preview_group is not None
    show_bone_collision = bool(scene.ho_collision_overlay_show_bone)
    show_object_collision = bool(scene.ho_collision_overlay_show_object)
    show_visible_bone_only = scene.ho_collision_overlay_only_visible_bones
    use_pin_color = scene.ho_collision_overlay_color_mode == "PIN" and preview_group is None
    collision_lines_by_group = {g: [] for g in range(1, _COLLISION_GROUP_COUNT + 1)}
    pin_lines = []
    unpin_lines = []

    if show_bone_collision:
        for armature_obj in _visible_armature_objects(context):
            for bone in armature_obj.data.bones:
                if show_visible_bone_only and not _bone_is_effectively_visible(bone):
                    continue
                props = _collision_props(bone)
                if props is None:
                    continue
                if not _collision_overlay_matches_preview_group(props, preview_group, include_passive=include_passive_collision):
                    continue
                matrix = _bone_draw_matrix(armature_obj, bone)
                group_lines = (pin_lines if _effective_bone_pin(bone) else unpin_lines) if use_pin_color else collision_lines_by_group[min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)]
                if props.collision_type == "SPHERE":
                    _append_sphere_lines(group_lines, matrix, props)
                elif props.collision_type == "CAPSULE":
                    _append_capsule_lines(group_lines, matrix, props)

    if show_object_collision:
        for obj in _visible_object_collision_objects(context):
            props = _object_collision_props(obj)
            if props is None:
                continue
            if not _collision_overlay_matches_preview_group(props, preview_group, include_passive=include_passive_collision):
                continue
            group_lines = unpin_lines if use_pin_color else collision_lines_by_group[min(max(int(props.primary_collision_group), 1), _COLLISION_GROUP_COUNT)]
            if props.collision_type == "SPHERE":
                _append_sphere_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "CAPSULE":
                _append_capsule_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "PLANE":
                _append_plane_lines(group_lines, obj.matrix_world, props)
            elif props.collision_type == "BOX":
                _append_box_lines(group_lines, obj.matrix_world, props)

    if (
        not any(collision_lines_by_group.values())
        and not pin_lines
        and not unpin_lines
    ):
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        for group, lines in collision_lines_by_group.items():
            _draw_line_batch(shader, lines, _collision_group_color(group), 1.5)
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
        preview_group = _collision_overlay_preview_mode_group(scene.ho_collision_overlay_preview_mode)

        layout.prop(scene, "ho_collision_overlay_show", text="显示碰撞预览")

        col = layout.column(align=True)
        col.enabled = bool(scene.ho_collision_overlay_show)
        col.prop(scene, "ho_collision_overlay_only_visible_bones", text="仅显示可见骨")
        col.prop(scene, "ho_collision_overlay_preview_mode", text="预览模式")
        if preview_group is not None:
            col.prop(scene, "ho_collision_overlay_include_passive_collision", text="额外显示简单碰撞")
        else:
            col.prop(scene, "ho_collision_overlay_color_mode", text="颜色模式")

        col.separator()
        col.prop(scene, "ho_collision_overlay_show_bone", text="骨骼碰撞体")
        col.prop(scene, "ho_collision_overlay_show_object", text="物体碰撞体")
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
