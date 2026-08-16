"""
physicsPanel.py — HoTools 统一物理属性面板

父面板顶部显示开关网格，各类型开关形式统一为 toggle 按钮。
开启后对应子面板自动展开，关闭则收起。

面板结构：
  PT_Hotools_PhysicsPanel            — 父面板（开关网格）
  PT_Hotools_Physics_ObjectCollision — 简单碰撞子面板
  PT_Hotools_Physics_MeshCollision   — 简单布料子面板（仅 MESH）
  PT_Hotools_Physics_RigidBody       — 刚体子面板
  PT_Hotools_Physics_RigidConstraint — 刚体约束子面板（仅 EMPTY）
  PT_Hotools_Physics_Field           — Field 子面板（仅 EMPTY）
"""

from bpy.types import Panel

from .operators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_Field_RegenerateId,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
)
from ..simple_cloth.base_pose import mesh_light_key
from .utils import (
    _active_armature_object,
    _active_collision_props,
    _collision_group_bit,
    _collision_props,
    _effective_bone_pin,
    _COLLISION_GROUP_COUNT,
)

_PARENT = "OBJECT_PT_Hotools_PhysicsPanel"

_COLLISION_GROUP_ROW_SIZE = 8
_BONE_SET_PRIMARY_GROUP_OP = "ho.bone_collision_set_primary_group"
_BONE_TOGGLE_COLLIDED_BY_GROUP_OP = "ho.bone_collision_toggle_collided_by_group"
_OBJECT_SET_PRIMARY_GROUP_OP = "ho.object_collision_set_primary_group"
_MESH_SET_PRIMARY_GROUP_OP = "ho.mesh_collision_set_primary_group"
_MESH_TOGGLE_COLLIDED_BY_GROUP_OP = "ho.mesh_collision_toggle_collided_by_group"
_RIGID_SET_COLLISION_GROUP_OP = "ho.rigid_body_set_collision_group"
_RIGID_TOGGLE_COLLIDES_WITH_GROUP_OP = "ho.rigid_body_toggle_collides_with_group"


def _draw_group_buttons(layout, operator_id, active_group=None, mask=None):
    for row_index in range(2):
        row = layout.row(align=True)
        row.operator_context = "INVOKE_DEFAULT"
        for group in range(
            row_index * _COLLISION_GROUP_ROW_SIZE + 1,
            min((row_index + 1) * _COLLISION_GROUP_ROW_SIZE, _COLLISION_GROUP_COUNT) + 1,
        ):
            depress = (group == active_group) if active_group is not None else _collision_group_bit(mask or 0, group)
            op = row.operator(operator_id, text=str(group), depress=depress)
            op.group = group


def _draw_bone_collision_details(layout, props):
    layout.prop(props, "pin")
    if props.collision_type == "NONE":
        return
    col = layout.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(col, _BONE_SET_PRIMARY_GROUP_OP, active_group=props.primary_collision_group)
    col.label(text="被碰撞组")
    _draw_group_buttons(col, _BONE_TOGGLE_COLLIDED_BY_GROUP_OP, mask=props.collided_by_groups)
    col.prop(props, "radius")
    if props.collision_type == "CAPSULE":
        col.prop(props, "length")
    col.prop(props, "offset")


def _draw_object_collision_controls(layout, props):
    layout.prop(props, "collision_type", text="类型")
    col = layout.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(col, _OBJECT_SET_PRIMARY_GROUP_OP, active_group=props.primary_collision_group)
    if props.collision_type == "NONE":
        return
    if props.collision_type == "PLANE":
        col.prop(props, "length", text="预览尺寸")
        col.prop(props, "offset", text="平面原点偏移")
        col.label(text="局部XY为平面，局部+Z为法线", icon="INFO")
        return
    if props.collision_type == "BOX":
        col.prop(props, "box_size", text="XYZ长度")
        col.prop(props, "offset", text="中心偏移")
        col.label(text="世界碰撞变换读取Object.matrix_world", icon="INFO")
        return
    col.prop(props, "radius")
    if props.collision_type == "CAPSULE":
        col.prop(props, "length")
    col.prop(props, "offset")


def _draw_mesh_collision_controls(layout, obj, props):
    box = layout.box()
    row = box.row(align=True)
    row.prop(props, "mc2_base_pose_proxy", text="BasePose只读对象")
    row.operator(OP_Hotools_MeshCollision_CreateBasePoseProxy.bl_idname, text="", icon="DUPLICATE")
    base = props.mc2_base_pose_proxy
    if base is obj:
        box.label(text="BasePose不能指向当前物理写入对象", icon="ERROR")
    elif base is not None and mesh_light_key(base) != mesh_light_key(obj):
        box.label(text="BasePose顶点/Loop/面数量不一致", icon="ERROR")
    col = box.column(align=True)
    col.label(text="主碰撞组")
    _draw_group_buttons(col, _MESH_SET_PRIMARY_GROUP_OP, active_group=props.primary_collision_group)
    col.label(text="被碰撞组")
    _draw_group_buttons(col, _MESH_TOGGLE_COLLIDED_BY_GROUP_OP, mask=props.collided_by_groups)
    col.prop_search(props, "radius_vertex_group", obj, "vertex_groups", text="半径顶点组")

    pin_box = layout.box()
    pin_box.prop(props, "pin_enabled")
    pin_col = pin_box.column(align=True)
    pin_col.enabled = bool(props.pin_enabled)
    pin_col.prop_search(props, "pin_vertex_group", obj, "vertex_groups", text="Pin顶点组")

# ---------------------------------------------------------------------------
# 父面板：开关网格
# ---------------------------------------------------------------------------

class PT_Hotools_PhysicsPanel(Panel):
    bl_idname = _PARENT
    bl_label = "HoTools 物理"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        obj = context.object
        layout = self.layout

        obj_col    = getattr(obj, "hotools_object_collision", None)
        mesh_col   = getattr(obj, "hotools_mesh_collision", None)
        rigid      = getattr(obj, "hotools_rigid_body", None)
        fracture   = getattr(obj, "hotools_rigid_fracture", None)
        constraint = getattr(obj, "hotools_rigid_constraint", None)
        field_props = getattr(obj, "hotools_field", None)

        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)

        if obj_col is not None:
            grid.prop(obj_col, "enabled", text="简单碰撞",
                      icon="MOD_PHYSICS", toggle=True)

        if obj.type == "MESH" and mesh_col is not None:
            grid.prop(mesh_col, "enabled", text="简单布料",
                      icon="MOD_CLOTH", toggle=True)

        if rigid is not None:
            grid.prop(rigid, "enabled", text="刚体",
                      icon="RIGID_BODY", toggle=True)

        if obj.type == "MESH" and fracture is not None:
            grid.prop(fracture, "enabled", text="刚体破碎",
                      icon="MOD_EXPLODE", toggle=True)

        if obj.type == "EMPTY" and constraint is not None:
            grid.prop(constraint, "enabled", text="刚体约束",
                      icon="RIGID_BODY_CONSTRAINT", toggle=True)

        if obj.type == "EMPTY" and field_props is not None:
            grid.prop(
                field_props,
                "enabled",
                text="场",
                icon="EMPTY_AXIS",
                toggle=True,
            )


# ---------------------------------------------------------------------------
# 子面板：Field（仅 EMPTY）
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_Field(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_Field"
    bl_label = "场"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "EMPTY":
            return False
        props = getattr(obj, "hotools_field", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        obj = context.object
        props = obj.hotools_field
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "field_type", text="类型")

        if props.field_type == "WIND":
            layout.separator()
            layout.label(text="体积", icon="MESH_UVSPHERE")
            layout.prop(props, "shape", text="形状")
            if props.shape == "SPHERE":
                scale = obj.matrix_world.to_scale()
                if max(scale) - min(scale) > 1.0e-5:
                    layout.label(text="球形 Volume 需要均匀缩放", icon="ERROR")

            layout.separator()
            layout.label(text="风", icon="FORCE_WIND")
            layout.prop(props, "speed_mps")
            layout.prop(props, "turbulence")
            if props.turbulence > 0.0:
                header, body = layout.panel(
                    "hotools_field_turbulence_details",
                    default_closed=True,
                )
                header.label(text="紊流细节")
                if body is not None:
                    body.use_property_split = True
                    body.use_property_decorate = False
                    body.prop(props, "spatial_scale_m")
                    body.prop(props, "temporal_frequency_hz")
                    body.prop(props, "octaves")
                    body.prop(props, "lacunarity")
                    body.prop(props, "gain")
                    body.prop(props, "seed_u32")
        else:
            layout.label(text="该 Field 类型尚未实现", icon="INFO")

        header, body = layout.panel(
            "hotools_field_advanced",
            default_closed=True,
        )
        header.label(text="高级属性")
        if body is not None:
            body.use_property_split = True
            body.use_property_decorate = False
            identity_row = body.row(align=True)
            identity_row.label(text=f"场 ID：{props.field_id or '未分配'}")
            identity_row.operator(
                OP_Hotools_Field_RegenerateId.bl_idname,
                text="",
                icon="FILE_REFRESH",
            )
            body.prop(props, "blend_weight")
            body.prop(props, "priority")
            body.separator()
            body.label(text="作用域", icon="FILTER")
            body.prop(props, "scope_solver_ids")
            body.prop(props, "scope_collection_ids")
            body.prop(props, "scope_include_ids")
            body.prop(props, "scope_exclude_ids")
            body.prop(props, "scope_collision_groups")

# ---------------------------------------------------------------------------
# 子面板：简单碰撞
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_ObjectCollision(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_ObjectCollision"
    bl_label = "简单碰撞"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None:
            return False
        props = getattr(obj, "hotools_object_collision", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        props = getattr(context.object, "hotools_object_collision", None)
        if props is None:
            return
        _draw_object_collision_controls(self.layout, props)


# ---------------------------------------------------------------------------
# 子面板：简单布料（仅 MESH）
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_MeshCollision(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_MeshCollision"
    bl_label = "简单布料"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            return False
        props = getattr(obj, "hotools_mesh_collision", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        obj = context.object
        props = getattr(obj, "hotools_mesh_collision", None)
        if props is None:
            return
        _draw_mesh_collision_controls(self.layout, obj, props)


# ---------------------------------------------------------------------------
# 子面板：刚体
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_RigidBody(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_RigidBody"
    bl_label = "刚体"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None:
            return False
        props = getattr(obj, "hotools_rigid_body", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        props = context.object.hotools_rigid_body
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "body_type")

        col = layout.column(align=True)
        col.enabled = (props.body_type == "DYNAMIC")
        col.prop(props, "mass")

        layout.prop(props, "friction")
        layout.prop(props, "restitution")

        layout.separator()
        layout.label(text="刚体过滤", icon="FILTER")
        filter_col = layout.column(align=True)
        filter_col.label(text="所属刚体组")
        _draw_group_buttons(filter_col, _RIGID_SET_COLLISION_GROUP_OP, active_group=props.rigid_collision_group)
        filter_col.label(text="可碰刚体组")
        _draw_group_buttons(filter_col, _RIGID_TOGGLE_COLLIDES_WITH_GROUP_OP, mask=props.rigid_collides_with_groups)

        # ── 碰撞形状 ──────────────────────────────────────────────────────────
        layout.separator()
        layout.label(text="碰撞形状", icon="MESH_DATA")
        layout.prop(props, "shape_type")

        stype = props.shape_type
        if stype == "SPHERE":
            layout.prop(props, "shape_radius")
        elif stype == "CAPSULE":
            col2 = layout.column(align=True)
            col2.prop(props, "shape_radius")
            col2.prop(props, "shape_half_height")
        elif stype == "CYLINDER":
            col2 = layout.column(align=True)
            col2.prop(props, "shape_radius")
            col2.prop(props, "shape_half_height")
            col2.prop(props, "shape_convex_radius")
        elif stype in {"TAPERED_CAPSULE", "TAPERED_CYLINDER"}:
            col2 = layout.column(align=True)
            col2.prop(props, "shape_top_radius")
            col2.prop(props, "shape_bottom_radius")
            col2.prop(props, "shape_half_height")
            if stype == "TAPERED_CYLINDER":
                col2.prop(props, "shape_convex_radius")
        elif stype == "PLANE":
            layout.prop(props, "shape_plane_half_extent")
            layout.label(text="局部XY为平面，局部Z为法线；PLANE按STATIC处理", icon="INFO")
        elif stype == "BOX":
            layout.prop(props, "shape_half_extents")
        layout.prop(props, "shape_offset")
        layout.prop(props, "shape_rotation")

        layout.separator()
        layout.label(text="动力学", icon="FORCE_FORCE")
        dyn_col = layout.column(align=True)
        dyn_col.enabled = (props.body_type == "DYNAMIC")
        dyn_col.prop(props, "linear_velocity")
        dyn_col.prop(props, "angular_velocity")
        dyn_col.prop(props, "linear_damping")
        dyn_col.prop(props, "angular_damping")
        dyn_col.prop(props, "gravity_factor")
        dyn_col.prop(props, "max_linear_velocity")
        dyn_col.prop(props, "max_angular_velocity")

        layout.separator()
        layout.label(text="求解", icon="MOD_PHYSICS")
        layout.prop(props, "motion_quality")
        layout.prop(props, "allow_sleeping")
        layout.prop(props, "start_deactivated")
        layout.prop(props, "is_sensor")
        layout.prop(props, "collide_kinematic_vs_non_dynamic")

        lock_col = layout.column(align=True)
        lock_col.label(text="轴锁定")
        row = lock_col.row(align=True)
        row.prop(props, "lock_linear_x", toggle=True, text="线X")
        row.prop(props, "lock_linear_y", toggle=True, text="线Y")
        row.prop(props, "lock_linear_z", toggle=True, text="线Z")
        row = lock_col.row(align=True)
        row.prop(props, "lock_angular_x", toggle=True, text="角X")
        row.prop(props, "lock_angular_y", toggle=True, text="角Y")
        row.prop(props, "lock_angular_z", toggle=True, text="角Z")


class PT_Hotools_Physics_RigidFracture(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_RigidFracture"
    bl_label = "刚体破碎"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "MESH":
            return False
        props = getattr(obj, "hotools_rigid_fracture", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        obj = context.object
        props = obj.hotools_rigid_fracture
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        status_icons = {
            "EMPTY": "RADIOBUT_OFF",
            "READY": "CHECKMARK",
            "OUTDATED": "FILE_REFRESH",
            "ERROR": "ERROR",
        }
        status_labels = {
            "EMPTY": "未生成",
            "READY": "可用",
            "OUTDATED": "需刷新",
            "ERROR": "错误",
        }
        status_row = layout.row(align=True)
        status_row.alert = props.product_status in {"OUTDATED", "ERROR"}
        status_row.label(
            text=f"{status_labels.get(props.product_status, props.product_status)} · v{props.product_revision}",
            icon=status_icons.get(props.product_status, "QUESTION"),
        )
        if props.last_error:
            error = layout.row()
            error.alert = True
            error.label(text=props.last_error, icon="ERROR")

        layout.prop(props, "fracture_method", text="切割算法")
        layout.operator(
            "ho.rigid_fracture_add_preview",
            text="添加碎块预览",
            icon="GEOMETRY_NODES",
        )

        row = layout.row(align=True)
        row.operator(
            "ho.rigid_fracture_create_collection",
            text="创建碎块集合",
            icon="COLLECTION_NEW",
        )
        row.operator(
            "ho.rigid_fracture_refresh",
            text="刷新碎块集合",
            icon="FILE_REFRESH",
        )
        row.operator(
            "ho.rigid_fracture_delete_collection",
            text="删除碎块集合",
            icon="TRASH",
        )


# ---------------------------------------------------------------------------
# 子面板：刚体约束（仅 EMPTY）
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_RigidConstraint(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_RigidConstraint"
    bl_label = "刚体约束"
    bl_parent_id = _PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "object"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        if obj is None or obj.type != "EMPTY":
            return False
        props = getattr(obj, "hotools_rigid_constraint", None)
        return props is not None and bool(getattr(props, "enabled", False))

    def draw(self, context):
        props = context.object.hotools_rigid_constraint
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(props, "constraint_type")
        layout.prop(props, "target_a")
        layout.prop(props, "target_b")
        layout.prop(props, "anchor_mode")
        if props.anchor_mode == "LOCAL_FRAMES":
            frame_col = layout.column(align=True)
            frame_col.prop(props, "local_point_a")
            frame_col.prop(props, "local_rotation_a")
            frame_col.prop(props, "local_point_b")
            frame_col.prop(props, "local_rotation_b")
        layout.prop(props, "disable_collisions")
        layout.prop(props, "breakable")
        break_col = layout.column(align=True)
        break_col.enabled = bool(props.breakable)
        break_col.prop(props, "breaking_threshold")

        ctype = props.constraint_type

        if ctype in {"GEAR", "RACK_AND_PINION"}:
            layout.separator()
            layout.label(text="引用拓扑", icon="CONSTRAINT")
            layout.prop(props, "reference_constraint_a")
            layout.prop(props, "reference_constraint_b")
            if ctype == "GEAR":
                layout.prop(props, "gear_ratio")
            else:
                layout.prop(props, "rack_and_pinion_ratio")

        layout.separator()
        layout.label(text="求解", icon="MOD_PHYSICS")
        solver_col = layout.column(align=True)
        solver_col.prop(props, "constraint_priority")
        solver_col.prop(props, "solver_velocity_steps")
        solver_col.prop(props, "solver_position_steps")
        solver_col.prop(props, "draw_constraint_size")

        if ctype in {"HINGE", "SLIDER"}:
            layout.separator()
            layout.label(text="限制", icon="CON_TRACKTO")
            layout.prop(props, "limit_enabled")
            limit_col = layout.column(align=True)
            limit_col.enabled = bool(props.limit_enabled)
            if ctype == "HINGE":
                limit_col.prop(props, "angular_limit_min")
                limit_col.prop(props, "angular_limit_max")
            else:
                limit_col.prop(props, "linear_limit_min")
                limit_col.prop(props, "linear_limit_max")
            limit_col.prop(props, "limit_spring_frequency")
            limit_col.prop(props, "limit_spring_damping")

            layout.separator()
            layout.label(text="Motor", icon="DRIVER")
            if ctype == "HINGE":
                layout.prop(props, "max_friction_torque")
            else:
                layout.prop(props, "max_friction_force")
            layout.prop(props, "motor_state")
            motor_col = layout.column(align=True)
            motor_col.enabled = (props.motor_state != "OFF")
            motor_col.prop(props, "motor_frequency")
            motor_col.prop(props, "motor_damping")
            if ctype == "HINGE":
                motor_col.prop(props, "motor_torque_limit")
                if props.motor_state == "VELOCITY":
                    motor_col.prop(props, "motor_target_angular_velocity")
                elif props.motor_state == "POSITION":
                    motor_col.prop(props, "motor_target_angle")
            else:
                motor_col.prop(props, "motor_force_limit")
                if props.motor_state == "VELOCITY":
                    motor_col.prop(props, "motor_target_velocity")
                elif props.motor_state == "POSITION":
                    motor_col.prop(props, "motor_target_position")

        if ctype == "CONE":
            layout.separator()
            layout.label(text="Cone", icon="EMPTY_SINGLE_ARROW")
            layout.prop(props, "cone_half_angle")

        if ctype == "DISTANCE":
            layout.separator()
            layout.label(text="距离", icon="DRIVER_DISTANCE")
            layout.prop(props, "distance_min")
            layout.prop(props, "distance_max")
            layout.prop(props, "limit_spring_frequency")
            layout.prop(props, "limit_spring_damping")


_BONE_PARENT = "BONE_PT_Hotools_PhysicsPanel"


# ---------------------------------------------------------------------------
# Bone 父面板：HoTools 物理（BONE 上下文）
# ---------------------------------------------------------------------------

class PT_Hotools_Bone_PhysicsPanel(Panel):
    bl_idname = _BONE_PARENT
    bl_label = "HoTools 物理"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE" and _active_armature_object(context) is not None

    def draw(self, context):
        armature_obj = _active_armature_object(context)
        layout = self.layout

        # 辅助操作
        col = layout.column(align=True)
        col.operator(OP_Hotools_BoneCollision_AddSelectedColliders.bl_idname,
                     icon="MESH_UVSPHERE")
        col.operator(OP_Hotools_BoneCollision_GradientRadius.bl_idname)

        # 统计行
        collision_count = sum(
            1 for bone in armature_obj.data.bones
            if _collision_props(bone) is not None
            and bone.hotools_collision.collision_type != "NONE"
        )
        pin_count = sum(1 for bone in armature_obj.data.bones if _effective_bone_pin(bone))
        row = layout.row(align=True)
        row.label(text=f"骨骼: {len(armature_obj.data.bones)}")
        row.label(text=f"Pin: {pin_count}")
        row.label(text=f"碰撞体: {collision_count}")

        # 当前活动骨骼的碰撞类型开关
        props = _active_collision_props(context)
        if props is not None:
            layout.separator()
            layout.prop(props, "collision_type", text="骨骼碰撞")


# ---------------------------------------------------------------------------
# Bone 子面板：骨骼碰撞详细设置
# ---------------------------------------------------------------------------

class PT_Hotools_Bone_CollisionSubPanel(Panel):
    bl_idname = "BONE_PT_Hotools_BoneCollision"
    bl_label = "骨骼碰撞"
    bl_parent_id = _BONE_PARENT
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "bone"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        props = _active_collision_props(context)
        return (
            context.mode == "POSE"
            and props is not None
        )

    def draw(self, context):
        props = _active_collision_props(context)
        if props is None:
            return
        _draw_bone_collision_details(self.layout, props)
