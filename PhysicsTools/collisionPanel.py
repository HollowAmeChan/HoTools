from bpy.types import Panel

from .collisionOperators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_AddSelectedSpringRoots,
    OP_Hotools_BoneCollision_ClearAllSpringRoots,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_BoneCollision_SelectSpringRoots,
)
from .collisionUtils import (
    _COLLISION_GROUP_COUNT,
    _active_armature_object,
    _active_collision_props,
    _active_mesh_collision_props,
    _active_object_collision_props,
    _collision_group_bit,
    _collision_props,
    _effective_bone_pin,
    _spring_root_bones,
)


COLLISION_GROUP_ROW_SIZE = 8
BONE_SET_PRIMARY_GROUP_OPERATOR = "ho.bone_collision_set_primary_group"
BONE_TOGGLE_COLLIDED_BY_GROUP_OPERATOR = "ho.bone_collision_toggle_collided_by_group"
OBJECT_SET_PRIMARY_GROUP_OPERATOR = "ho.object_collision_set_primary_group"
MESH_SET_PRIMARY_GROUP_OPERATOR = "ho.mesh_collision_set_primary_group"
MESH_TOGGLE_COLLIDED_BY_GROUP_OPERATOR = "ho.mesh_collision_toggle_collided_by_group"


def _draw_section_toggles(layout, scene):
    row = layout.row(align=True)
    row.alignment = "LEFT"
    row.prop(
        scene,
        "ho_bone_collision_show_info_section",
        text="",
        icon="INFO",
        icon_only=True,
        toggle=True,
    )
    row.prop(
        scene,
        "ho_bone_collision_show_roots_section",
        text="",
        icon="BONE_DATA",
        icon_only=True,
        toggle=True,
    )


def _section_box(layout, scene, prop_name: str):
    if not bool(getattr(scene, prop_name)):
        return None
    return layout.box()


def _draw_group_buttons(layout, operator_id, *, active_group=None, mask=None):
    for row_index in range(2):
        row = layout.row(align=True)
        row.operator_context = "INVOKE_DEFAULT"
        for group in range(
            row_index * COLLISION_GROUP_ROW_SIZE + 1,
            min((row_index + 1) * COLLISION_GROUP_ROW_SIZE, _COLLISION_GROUP_COUNT) + 1,
        ):
            if active_group is not None:
                depress = group == active_group
            else:
                depress = _collision_group_bit(mask or 0, group)

            op = row.operator(
                operator_id,
                text=str(group),
                depress=depress,
            )
            op.group = group


def _draw_collision_controls(layout, props):
    layout.prop(props, "spring_root")
    pin_row = layout.row(align=True)
    pin_row.prop(props, "pin")
    if props.spring_root:
        pin_row.label(text="Root强制Pin", icon="PINNED")
    layout.prop(props, "collision_type", text="类型")

    col = layout.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(
        col,
        BONE_SET_PRIMARY_GROUP_OPERATOR,
        active_group=props.primary_collision_group,
    )
    col.label(text="被碰撞组")
    _draw_group_buttons(
        col,
        BONE_TOGGLE_COLLIDED_BY_GROUP_OPERATOR,
        mask=props.collided_by_groups,
    )
    if props.collision_type == "NONE":
        return

    col.prop(props, "radius")
    if props.collision_type == "CAPSULE":
        col.prop(props, "length")
    col.prop(props, "offset")


def _draw_object_collision_controls(layout, props):
    layout.prop(props, "collision_type", text="类型")

    col = layout.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(
        col,
        OBJECT_SET_PRIMARY_GROUP_OPERATOR,
        active_group=props.primary_collision_group,
    )
    if props.collision_type == "NONE":
        return

    col.prop(props, "radius")
    if props.collision_type == "CAPSULE":
        col.prop(props, "length")
    col.prop(props, "offset")


def _draw_mesh_collision_controls(layout, obj, props):
    collision_box = layout.box()
    collision_box.prop(props, "enabled")

    col = collision_box.column(align=True)
    col.enabled = bool(props.enabled)
    col.label(text="主碰撞组")
    _draw_group_buttons(
        col,
        MESH_SET_PRIMARY_GROUP_OPERATOR,
        active_group=props.primary_collision_group,
    )
    col.label(text="被碰撞组")
    _draw_group_buttons(
        col,
        MESH_TOGGLE_COLLIDED_BY_GROUP_OPERATOR,
        mask=props.collided_by_groups,
    )
    col.prop(props, "radius")
    col.prop_search(
        props,
        "radius_vertex_group",
        obj,
        "vertex_groups",
        text="半径顶点组",
    )

    pin_box = layout.box()
    pin_box.prop(props, "pin_enabled")
    pin_col = pin_box.column(align=True)
    pin_col.enabled = bool(props.pin_enabled)
    pin_col.prop_search(
        props,
        "pin_vertex_group",
        obj,
        "vertex_groups",
        text="Pin顶点组",
    )
    pin_col.label(text="留空时固定全部顶点", icon="INFO")


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


class PT_Hotools_ObjectCollisionPanel(Panel):
    bl_idname = "OBJECT_PT_Hotools_ObjectCollisionPanel"
    bl_label = "HoTools被动碰撞体"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and _active_object_collision_props(context) is not None

    def draw(self, context):
        props = _active_object_collision_props(context)
        layout = self.layout

        _draw_object_collision_controls(layout, props)


class PT_Hotools_MeshCollisionPanel(Panel):
    bl_idname = "OBJECT_PT_Hotools_MeshCollisionPanel"
    bl_label = "HoTools网格碰撞"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == "MESH" and _active_mesh_collision_props(context) is not None

    def draw(self, context):
        obj = context.object
        props = _active_mesh_collision_props(context)
        layout = self.layout

        _draw_mesh_collision_controls(layout, obj, props)


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
        pin_count = sum(1 for bone in armature_obj.data.bones if _effective_bone_pin(bone))

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
            row.label(text=f"Pin: {pin_count}")
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
                icon = "PINNED" if _effective_bone_pin(active_bone) else "BONE_DATA"
                root_box.label(text=f"活动骨骼: {active_bone.name}", icon=icon)
                _draw_collision_controls(root_box, active_props)

        if armature_obj.mode not in {"EDIT", "POSE"}:
            layout.label(text="进入姿态或编辑模式后可使用选中骨操作", icon="INFO")
