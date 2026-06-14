import bpy
import gpu
import math
import mathutils
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty
from gpu_extras.batch import batch_for_shader


_DRAW_HANDLE = None
_ROOT_COLOR = (0.45, 1.0, 0.25, 0.85)
_SHAPE_SEGMENTS = 32
_COLLISION_GROUP_COUNT = 16
_COLLISION_GROUP_ROW_SIZE = 8
_ALL_COLLISION_GROUPS_MASK = (1 << _COLLISION_GROUP_COUNT) - 1
_COLLISION_GROUP_COLORS = (
    (0.10, 0.63, 1.00, 0.86),
    (1.00, 0.45, 0.25, 0.86),
    (0.35, 0.90, 0.35, 0.86),
    (1.00, 0.82, 0.18, 0.86),
    (0.78, 0.48, 1.00, 0.86),
    (0.12, 0.92, 0.82, 0.86),
    (1.00, 0.35, 0.62, 0.86),
    (0.62, 0.88, 0.18, 0.86),
    (0.30, 0.48, 1.00, 0.86),
    (1.00, 0.60, 0.12, 0.86),
    (0.20, 0.78, 0.55, 0.86),
    (0.92, 0.38, 1.00, 0.86),
    (0.88, 0.75, 0.55, 0.86),
    (0.52, 0.72, 0.95, 0.86),
    (0.95, 0.52, 0.52, 0.86),
    (0.78, 0.78, 0.78, 0.86),
)


class PG_Hotools_BoneCollision(PropertyGroup):
    spring_root: BoolProperty(
        name="Spring Root",
        description="把这根骨骼标记为一条SpringBone链的根；整骨架面板会批量管理这个标记",
        default=False,
    )  # type: ignore
    collision_type: EnumProperty(
        name="碰撞体",
        description="这根骨骼携带的物理碰撞体类型；当前只负责持久化与编辑",
        items=[
            ("NONE", "无", "不作为物理碰撞体"),
            ("SPHERE", "球体", "以骨骼局部偏移为中心的球形碰撞体"),
            ("CAPSULE", "胶囊", "沿骨骼局部Y轴延伸的胶囊碰撞体"),
        ],
        default="NONE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.05,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    length: FloatProperty(
        name="长度",
        description="胶囊中段长度，球体类型会忽略这个参数",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset: FloatVectorProperty(
        name="中心偏移",
        description="碰撞体中心相对骨骼局部空间的偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore
    primary_collision_group: IntProperty(
        name="主碰撞组",
        description="这根碰撞体所属的主碰撞组，叠加显示颜色由它决定",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    collided_by_groups: IntProperty(
        name="被碰撞组",
        description="允许哪些主碰撞组碰撞到这根碰撞体的位掩码",
        default=0,
        min=0,
        max=_ALL_COLLISION_GROUPS_MASK,
    )  # type: ignore


def _tag_view3d_redraw():
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _overlay_show_update(self, context):
    _tag_view3d_redraw()


def _active_armature_object(context):
    obj = context.object or context.active_object
    if obj is None or obj.type != "ARMATURE":
        return None
    return obj


def _collision_props(bone):
    return getattr(bone, "hotools_collision", None)


def _active_collision_props(context):
    bone = context.active_bone
    if bone is None:
        return None
    return _collision_props(bone)


def _set_collision_group_bit(mask, group, value):
    bit = 1 << (group - 1)
    if value:
        return mask | bit
    return mask & ~bit


def _collision_group_bit(mask, group):
    return bool(mask & (1 << (group - 1)))


def _collision_group_color(group):
    index = min(max(int(group), 1), _COLLISION_GROUP_COUNT) - 1
    return _COLLISION_GROUP_COLORS[index]


def _collision_group_target_props(context, apply_selected):
    armature_obj = _active_armature_object(context)
    if armature_obj is None:
        return []

    if not apply_selected:
        props = _active_collision_props(context)
        return [props] if props is not None else []

    targets = []
    seen_names = set()
    for name in _selected_bone_names(context, armature_obj):
        if name in seen_names:
            continue
        bone = armature_obj.data.bones.get(name)
        props = _collision_props(bone) if bone else None
        if props is not None:
            targets.append(props)
            seen_names.add(name)

    if not targets:
        props = _active_collision_props(context)
        if props is not None:
            targets.append(props)
    return targets


def _draw_group_buttons(layout, operator_id, *, active_group=None, mask=None):
    for row_index in range(2):
        row = layout.row(align=True)
        row.operator_context = "INVOKE_DEFAULT"
        for group in range(
            row_index * _COLLISION_GROUP_ROW_SIZE + 1,
            (row_index + 1) * _COLLISION_GROUP_ROW_SIZE + 1,
        ):
            if active_group is not None:
                depress = group == active_group
            else:
                icon = "CHECKBOX_HLT" if _collision_group_bit(mask or 0, group) else "CHECKBOX_DEHLT"
                depress = _collision_group_bit(mask or 0, group)

            op = row.operator(
                operator_id,
                text=str(group),
                depress=depress,
            )
            op.group = group


def _append_unique_bone_name(names, seen_names, bone):
    if bone is None or bone.name in seen_names:
        return
    names.append(bone.name)
    seen_names.add(bone.name)


def _selected_bone_names(context, armature_obj) -> list[str]:
    mode = getattr(context, "mode", "")
    object_mode = getattr(armature_obj, "mode", "")
    names = []
    seen_names = set()

    if mode == "EDIT_ARMATURE" or object_mode == "EDIT":
        selected_editable_bones = getattr(context, "selected_editable_bones", None) or []
        for bone in selected_editable_bones:
            _append_unique_bone_name(names, seen_names, bone)

        selected_bones = getattr(context, "selected_bones", None) or []
        for bone in selected_bones:
            _append_unique_bone_name(names, seen_names, bone)

        for bone in armature_obj.data.edit_bones:
            if (
                getattr(bone, "select", False)
                or getattr(bone, "select_head", False)
                or getattr(bone, "select_tail", False)
            ):
                _append_unique_bone_name(names, seen_names, bone)
        return names

    if mode == "POSE" or object_mode == "POSE":
        selected_pose_bones = getattr(context, "selected_pose_bones", None) or []
        for pose_bone in selected_pose_bones:
            _append_unique_bone_name(names, seen_names, pose_bone)

        selected_bones = getattr(context, "selected_bones", None) or []
        for bone in selected_bones:
            _append_unique_bone_name(names, seen_names, bone)

        if armature_obj.pose is not None:
            for pose_bone in armature_obj.pose.bones:
                if pose_bone.bone.select:
                    _append_unique_bone_name(names, seen_names, pose_bone)

        for bone in armature_obj.data.bones:
            if bone.select:
                _append_unique_bone_name(names, seen_names, bone)
        return names

    selected_bones = getattr(context, "selected_bones", None) or []
    for bone in selected_bones:
        _append_unique_bone_name(names, seen_names, bone)

    for bone in armature_obj.data.bones:
        if getattr(bone, "select", False):
            _append_unique_bone_name(names, seen_names, bone)
    return names


def _spring_root_bones(armature_obj):
    return [
        bone
        for bone in armature_obj.data.bones
        if _collision_props(bone) is not None and bone.hotools_collision.spring_root
    ]


def _bone_topology_data(bones):
    scope_names = {bone.name for bone in bones}
    roots = [bone for bone in bones if bone.parent is None or bone.parent.name not in scope_names]
    topology_data = {}

    def scan_topology(bone, root_index, current_chains, depth):
        topology_data[bone.name] = {
            "bone": bone,
            "root_index": root_index,
            "chains": tuple(current_chains),
            "depth": depth,
        }

        children = [child for child in bone.children if child.name in scope_names]
        for index, child in enumerate(children):
            next_chains = list(current_chains)
            if len(children) > 1:
                next_chains.append(index)
            scan_topology(child, root_index, next_chains, depth + 1)

    for root_index, root in enumerate(roots):
        scan_topology(root, root_index, [root_index], 0)

    return topology_data


def _clamp01(value):
    return min(max(float(value), 0.0), 1.0)


def _exponent_factor(value, exponent, offset):
    t = _clamp01(float(value) + float(offset))
    return t ** max(float(exponent), 0.001)


def _draw_section_toggles(layout, scene):
    row = layout.row(align=True)
    left_row = row.row(align=True)
    left_row.alignment = "LEFT"
    left_row.prop(
        scene,
        "ho_bone_collision_show_info_section",
        text="",
        icon="INFO",
        icon_only=True,
        toggle=True,
    )
    left_row.prop(
        scene,
        "ho_bone_collision_show_roots_section",
        text="",
        icon="BONE_DATA",
        icon_only=True,
        toggle=True,
    )
    right_row = row.row(align=True)
    right_row.alignment = "RIGHT"
    right_row.prop(
        scene,
        "ho_bone_collision_overlay_show",
        text="",
        icon="MESH_UVSPHERE",
        toggle=True,
    )


def _section_box(layout, scene, prop_name: str):
    if not bool(getattr(scene, prop_name)):
        return None
    return layout.box()


def _draw_collision_controls(layout, props):
    layout.prop(props, "spring_root")
    layout.prop(props, "collision_type", text="类型")

    col = layout.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(
        col,
        OP_Hotools_BoneCollision_SetPrimaryGroup.bl_idname,
        active_group=props.primary_collision_group,
    )
    col.label(text="被碰撞组")
    _draw_group_buttons(
        col,
        OP_Hotools_BoneCollision_ToggleCollidedByGroup.bl_idname,
        mask=props.collided_by_groups,
    )
    if props.collision_type == "NONE":
        return

    col.prop(props, "radius")
    if props.collision_type == "CAPSULE":
        col.prop(props, "length")
    col.prop(props, "offset")


def _visible_armature_objects(context):
    visible_objects = getattr(context, "visible_objects", None)
    if visible_objects is None:
        visible_objects = context.view_layer.objects

    return [
        obj
        for obj in visible_objects
        if obj.type == "ARMATURE" and obj.visible_get()
    ]


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


class OP_Hotools_BoneCollision_AddSelectedSpringRoots(Operator):
    bl_idname = "ho.bone_collision_add_selected_spring_roots"
    bl_label = "选中骨设为Root"
    bl_description = "把当前选中的骨骼标记为Spring Root"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = _selected_bone_names(context, armature_obj)
        if not selected_names:
            self.report({"WARNING"}, "没有选中骨骼")
            return {"CANCELLED"}

        changed = 0
        for name in selected_names:
            bone = armature_obj.data.bones.get(name)
            props = _collision_props(bone) if bone else None
            if props is None:
                continue
            props.spring_root = True
            changed += 1

        self.report({"INFO"}, f"已设置 {changed} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_ClearAllSpringRoots(Operator):
    bl_idname = "ho.bone_collision_clear_all_spring_roots"
    bl_label = "清空全部Root"
    bl_description = "清空当前骨架所有骨骼的Spring Root标记"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_armature_object(context) is not None

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        changed = 0
        for bone in armature_obj.data.bones:
            props = _collision_props(bone)
            if props is None:
                continue
            if props.spring_root:
                changed += 1
            props.spring_root = False

        self.report({"INFO"}, f"已清空 {changed} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_SelectSpringRoots(Operator):
    bl_idname = "ho.bone_collision_select_spring_roots"
    bl_label = "选择全部Root"
    bl_description = "选择当前骨架中所有标记为Spring Root的骨骼"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        root_names = {bone.name for bone in _spring_root_bones(armature_obj)}
        if not root_names:
            self.report({"WARNING"}, "当前骨架没有Spring Root")
            return {"CANCELLED"}

        if armature_obj.mode == "EDIT":
            for bone in armature_obj.data.edit_bones:
                bone.select = bone.name in root_names
        else:
            for bone in armature_obj.data.bones:
                bone.select = bone.name in root_names
            active_name = next(iter(root_names))
            armature_obj.data.bones.active = armature_obj.data.bones.get(active_name)

        self.report({"INFO"}, f"已选择 {len(root_names)} 个Spring Root")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_SetPrimaryGroup(Operator):
    bl_idname = "ho.bone_collision_set_primary_group"
    bl_label = "设置主碰撞组"
    bl_description = "设置当前活动骨碰撞体所属的主碰撞组"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    apply_selected: BoolProperty(
        name="应用到选中骨",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_collision_props(context) is not None

    def invoke(self, context, event):
        self.apply_selected = bool(event.alt)
        return self.execute(context)

    def execute(self, context):
        targets = _collision_group_target_props(context, self.apply_selected)
        if not targets:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        for props in targets:
            props.primary_collision_group = group

        _tag_view3d_redraw()
        if self.apply_selected:
            self.report({"INFO"}, f"已设置 {len(targets)} 根选中骨的主碰撞组")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_ToggleCollidedByGroup(Operator):
    bl_idname = "ho.bone_collision_toggle_collided_by_group"
    bl_label = "切换被碰撞组"
    bl_description = "切换允许哪些主碰撞组碰撞到当前活动骨碰撞体"
    bl_options = {"REGISTER", "UNDO"}

    group: IntProperty(
        name="组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    apply_selected: BoolProperty(
        name="应用到选中骨",
        default=False,
        options={"HIDDEN", "SKIP_SAVE"},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_collision_props(context) is not None

    def invoke(self, context, event):
        self.apply_selected = bool(event.shift or event.ctrl or event.alt)
        return self.execute(context)

    def execute(self, context):
        targets = _collision_group_target_props(context, self.apply_selected)
        if not targets:
            return {"CANCELLED"}

        group = min(max(int(self.group), 1), _COLLISION_GROUP_COUNT)
        active_props = _active_collision_props(context)
        if active_props is not None:
            enable = not _collision_group_bit(active_props.collided_by_groups, group)
        else:
            enable = not all(_collision_group_bit(props.collided_by_groups, group) for props in targets)

        for props in targets:
            props.collided_by_groups = _set_collision_group_bit(
                props.collided_by_groups,
                group,
                enable,
            )

        _tag_view3d_redraw()
        if self.apply_selected:
            self.report({"INFO"}, f"已更新 {len(targets)} 根选中骨的被碰撞组")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_AddSelectedColliders(Operator):
    bl_idname = "ho.bone_collision_add_selected_colliders"
    bl_label = "选中骨添加碰撞"
    bl_description = "给当前选中的所有骨骼批量添加碰撞体"
    bl_options = {"REGISTER", "UNDO"}

    collision_type: EnumProperty(
        name="类型",
        description="要写入选中骨骼的碰撞体类型",
        items=[
            ("SPHERE", "球体", "批量添加球形碰撞体"),
            ("CAPSULE", "胶囊", "批量添加胶囊碰撞体"),
        ],
        default="SPHERE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.2,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    height: FloatProperty(
        name="高度",
        description="胶囊中段长度；球体也会写入，方便之后切换到胶囊体",
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset_delta: FloatVectorProperty(
        name="相对偏移增量",
        description="在每根骨骼head/tail中点基础上追加的局部XYZ偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        armature_obj = _active_armature_object(context)
        return armature_obj is not None and armature_obj.mode in {"EDIT", "POSE"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "collision_type")
        layout.prop(self, "radius")
        layout.prop(self, "height")
        layout.prop(self, "offset_delta")

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = _selected_bone_names(context, armature_obj)
        target_bones = []
        seen_names = set()
        for name in selected_names:
            if name in seen_names:
                continue
            bone = armature_obj.data.bones.get(name)
            props = _collision_props(bone) if bone else None
            if props is None:
                continue
            target_bones.append(bone)
            seen_names.add(name)

        if not target_bones:
            self.report({"WARNING"}, "没有选中可处理的骨骼")
            return {"CANCELLED"}

        delta = mathutils.Vector(self.offset_delta)
        for bone in target_bones:
            props = _collision_props(bone)
            if props is None:
                continue

            midpoint_offset = mathutils.Vector((0.0, bone.length * 0.5, 0.0))
            props.collision_type = self.collision_type
            props.radius = self.radius
            props.length = self.height
            props.offset = midpoint_offset + delta

        _tag_view3d_redraw()
        self.report({"INFO"}, f"已给 {len(target_bones)} 根选中骨添加碰撞体")
        return {"FINISHED"}


class OP_Hotools_BoneCollision_GradientRadius(Operator):
    bl_idname = "ho.bone_collision_gradient_radius"
    bl_label = "碰撞半径渐变"
    bl_description = "按骨骼层级顺序批量递增或递减已有碰撞体半径"
    bl_options = {"REGISTER", "UNDO"}

    target_scope: EnumProperty(
        name="范围",
        description="选择只处理当前选中骨的碰撞体，或处理当前骨架的全部碰撞体",
        items=[
            ("SELECTED", "选中碰撞体", "只处理当前选中骨骼中已有碰撞体"),
            ("ALL", "全部碰撞体", "处理当前骨架中所有已有碰撞体"),
        ],
        default="SELECTED",
    )  # type: ignore
    direction: EnumProperty(
        name="方向",
        description="半径沿骨骼顺序递减或递增",
        items=[
            ("DECREASE", "递减", "从头倍率过渡到尾倍率"),
            ("INCREASE", "递增", "从尾倍率过渡到头倍率"),
        ],
        default="DECREASE",
    )  # type: ignore
    head_factor: FloatProperty(
        name="头倍率",
        description="链头半径倍率；按每根骨当前半径乘以该渐变倍率",
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    tail_factor: FloatProperty(
        name="尾倍率",
        description="链尾半径倍率；默认让尾部变为当前半径的0.2倍",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    exponent: FloatProperty(
        name="指数",
        description="控制半径渐变曲线；1为线性，大于1前段更慢，小于1前段更快",
        default=2.0,
        min=0.001,
        soft_min=0.1,
        soft_max=8.0,
    )  # type: ignore
    factor_offset: FloatProperty(
        name="曲线偏移",
        description="先偏移归一化顺序再计算指数，负值延后变化，正值提前变化",
        default=0.0,
        min=-1.0,
        max=1.0,
        soft_min=-0.5,
        soft_max=0.5,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return _active_armature_object(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "target_scope")
        layout.prop(self, "direction")

        row = layout.row(align=True)
        row.prop(self, "head_factor")
        row.prop(self, "tail_factor")

        layout.prop(self, "exponent")
        layout.prop(self, "factor_offset")

    def execute(self, context):
        armature_obj = _active_armature_object(context)
        selected_names = set(_selected_bone_names(context, armature_obj))
        scope_bones = []
        target_items = []

        if self.target_scope == "SELECTED" and not selected_names:
            self.report({"WARNING"}, "没有选中骨骼")
            return {"CANCELLED"}

        for bone in armature_obj.data.bones:
            if self.target_scope == "ALL" or bone.name in selected_names:
                scope_bones.append(bone)

        topology_data = _bone_topology_data(scope_bones)
        max_depth_by_root = {}

        for bone in scope_bones:
            props = _collision_props(bone)
            if props is None or props.collision_type == "NONE":
                continue

            data = topology_data.get(bone.name)
            if data is None:
                continue

            target_items.append((bone, props, data))
            root_index = data["root_index"]
            max_depth_by_root[root_index] = max(
                max_depth_by_root.get(root_index, 0),
                data["depth"],
            )

        if not target_items:
            if self.target_scope == "SELECTED":
                self.report({"WARNING"}, "选中骨骼中没有已有碰撞体")
            else:
                self.report({"WARNING"}, "当前骨架没有已有碰撞体")
            return {"CANCELLED"}

        first_factor = self.head_factor if self.direction == "DECREASE" else self.tail_factor
        last_factor = self.tail_factor if self.direction == "DECREASE" else self.head_factor

        for bone, props, data in target_items:
            denominator = max(max_depth_by_root.get(data["root_index"], 0), 1)
            factor = _exponent_factor(data["depth"] / denominator, self.exponent, self.factor_offset)
            radius_factor = first_factor + (last_factor - first_factor) * factor
            props.radius = max(props.radius * radius_factor, 0.0)

        _tag_view3d_redraw()
        self.report({"INFO"}, f"已调整 {len(target_items)} 个碰撞体半径")
        return {"FINISHED"}


class PT_Hotools_BoneCollisionPanel(Panel):
    bl_idname = "BONE_PT_Hotools_BoneCollisionPanel"
    bl_label = "HoTools碰撞体"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE" and _active_collision_props(context) is not None

    def draw(self, context):
        props = _active_collision_props(context)
        layout = self.layout

        _draw_collision_controls(layout, props)


class PT_Hotools_ArmatureCollisionPanel(Panel):
    bl_idname = "DATA_PT_Hotools_ArmatureCollisionPanel"
    bl_label = "HoTools碰撞管理"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _active_armature_object(context) is not None

    def draw(self, context):
        armature_obj = _active_armature_object(context)
        layout = self.layout
        scene = context.scene
        roots = _spring_root_bones(armature_obj)
        active_bone = context.active_bone
        active_props = _active_collision_props(context)
        collision_count = sum(
            1
            for bone in armature_obj.data.bones
            if _collision_props(bone) is not None
            and bone.hotools_collision.collision_type != "NONE"
        )

        _draw_section_toggles(layout, scene)

        op_box = layout.box()
        col = op_box.column(align=True)
        row = col.row(align=True)
        row.operator(OP_Hotools_BoneCollision_AddSelectedSpringRoots.bl_idname, icon="ADD")
        row.operator(OP_Hotools_BoneCollision_SelectSpringRoots.bl_idname, icon="RESTRICT_SELECT_OFF")
        col.operator(OP_Hotools_BoneCollision_AddSelectedColliders.bl_idname, icon="MESH_UVSPHERE")
        col.operator(OP_Hotools_BoneCollision_GradientRadius.bl_idname)
        col.operator(OP_Hotools_BoneCollision_ClearAllSpringRoots.bl_idname, icon="TRASH")

        info_box = _section_box(layout, scene, "ho_bone_collision_show_info_section")
        if info_box:
            row = info_box.row(align=True)
            row.label(text=f"骨骼: {len(armature_obj.data.bones)}")
            row.label(text=f"Spring Root: {len(roots)}")
            info_box.label(text=f"碰撞体: {collision_count}")

            if roots:
                info_box.separator()
                for bone in roots:
                    row = info_box.row(align=True)
                    is_active = active_bone is not None and active_bone.name == bone.name
                    row.label(text=bone.name, icon="BONE_DATA" if not is_active else "PINNED")

        root_box = _section_box(layout, scene, "ho_bone_collision_show_roots_section")
        if root_box:
            if active_bone is None or active_props is None:
                root_box.label(text="活动骨骼: 无", icon="INFO")
            else:
                icon = "PINNED" if active_props.spring_root else "BONE_DATA"
                root_box.label(text=f"活动骨骼: {active_bone.name}", icon=icon)
                _draw_collision_controls(root_box, active_props)

        if armature_obj.mode not in {"EDIT", "POSE"}:
            layout.label(text="进入姿态或编辑模式后可使用选中骨操作", icon="INFO")


cls = [
    PG_Hotools_BoneCollision,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_SelectSpringRoots,
    OP_Hotools_BoneCollision_SetPrimaryGroup,
    OP_Hotools_BoneCollision_ToggleCollidedByGroup,
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    PT_Hotools_BoneCollisionPanel,
    PT_Hotools_ArmatureCollisionPanel,
]


def reg_props():
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision
    bpy.types.Bone.hotools_collision = PointerProperty(type=PG_Hotools_BoneCollision)

    if hasattr(bpy.types.Scene, "ho_bone_collision_show_overlay_section"):
        del bpy.types.Scene.ho_bone_collision_show_overlay_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_overlay_show"):
        del bpy.types.Scene.ho_bone_collision_overlay_show
    bpy.types.Scene.ho_bone_collision_overlay_show = BoolProperty(
        name="显示HoTools碰撞体",
        description="在3D视图叠加层中显示HoTools骨骼碰撞范围和Spring Root标记",
        default=False,
        update=_overlay_show_update,
    )
    bpy.types.Scene.ho_bone_collision_show_info_section = BoolProperty(
        name="信息",
        default=True,
    )
    bpy.types.Scene.ho_bone_collision_show_roots_section = BoolProperty(
        name="活动骨碰撞",
        default=True,
    )


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_overlay_section"):
        del bpy.types.Scene.ho_bone_collision_show_overlay_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_roots_section"):
        del bpy.types.Scene.ho_bone_collision_show_roots_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_show_info_section"):
        del bpy.types.Scene.ho_bone_collision_show_info_section
    if hasattr(bpy.types.Scene, "ho_bone_collision_overlay_show"):
        del bpy.types.Scene.ho_bone_collision_overlay_show
    if hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()
    _ensure_draw_handler()


def unregister():
    _remove_draw_handler()
    ureg_props()
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
