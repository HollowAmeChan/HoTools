import bpy
import gpu
import math
import mathutils
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty
from gpu_extras.batch import batch_for_shader


_DRAW_HANDLE = None
_SPHERE_COLOR = (0.15, 0.75, 1.0, 0.85)
_CAPSULE_COLOR = (1.0, 0.62, 0.18, 0.85)
_ROOT_COLOR = (0.45, 1.0, 0.25, 0.85)
_SHAPE_SEGMENTS = 32


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


def _selected_bone_names(context, armature_obj) -> list[str]:
    if armature_obj.mode == "EDIT":
        return [bone.name for bone in armature_obj.data.edit_bones if bone.select]

    if armature_obj.mode == "POSE":
        selected_pose_bones = context.selected_pose_bones or []
        return [pose_bone.name for pose_bone in selected_pose_bones]

    active_bone = context.active_bone
    if active_bone is not None:
        return [active_bone.name]
    return []


def _spring_root_bones(armature_obj):
    return [
        bone
        for bone in armature_obj.data.bones
        if _collision_props(bone) is not None and bone.hotools_collision.spring_root
    ]


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
    if props.collision_type == "NONE":
        return

    col = layout.column(align=True)
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

    sphere_lines = []
    capsule_lines = []
    root_lines = []

    for armature_obj in _visible_armature_objects(context):
        for bone in armature_obj.data.bones:
            props = _collision_props(bone)
            if props is None:
                continue

            matrix = _bone_draw_matrix(armature_obj, bone)
            if props.spring_root:
                _append_spring_root_marker(root_lines, matrix, bone)

            if props.collision_type == "SPHERE":
                _append_sphere_lines(sphere_lines, matrix, props)
            elif props.collision_type == "CAPSULE":
                _append_capsule_lines(capsule_lines, matrix, props)

    if not sphere_lines and not capsule_lines and not root_lines:
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    gpu.state.depth_mask_set(False)
    try:
        _draw_line_batch(shader, sphere_lines, _SPHERE_COLOR, 1.5)
        _draw_line_batch(shader, capsule_lines, _CAPSULE_COLOR, 1.5)
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
        return _active_armature_object(context) is not None

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
