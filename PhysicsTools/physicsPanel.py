"""
physicsPanel.py — HoTools 统一物理属性面板

父面板顶部显示开关网格，各类型开关形式统一为 toggle 按钮。
开启后对应子面板自动展开，关闭则收起。

面板结构：
  PT_Hotools_PhysicsPanel            — 父面板（开关网格）
  PT_Hotools_Physics_ObjectCollision — 被动碰撞子面板
  PT_Hotools_Physics_MeshCollision   — 网格碰撞子面板（仅 MESH）
  PT_Hotools_Physics_RigidBody       — 刚体子面板
  PT_Hotools_Physics_RigidConstraint — 刚体约束子面板（仅 EMPTY）
"""

from bpy.types import Panel

from .collisionOperators import (
    OP_Hotools_BoneCollision_AddSelectedColliders,
    OP_Hotools_BoneCollision_GradientRadius,
    OP_Hotools_MeshCollision_CreateBasePoseProxy,
)
from .collisionBasePose import mesh_light_key
from .collisionUtils import (
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
    box.prop(props, "enabled")
    col = box.column(align=True)
    col.enabled = bool(props.enabled)
    col.label(text="主碰撞组")
    _draw_group_buttons(col, _MESH_SET_PRIMARY_GROUP_OP, active_group=props.primary_collision_group)
    col.label(text="被碰撞组")
    _draw_group_buttons(col, _MESH_TOGGLE_COLLIDED_BY_GROUP_OP, mask=props.collided_by_groups)
    col.prop(props, "radius")
    col.prop_search(props, "radius_vertex_group", obj, "vertex_groups", text="半径顶点组")

    pin_box = layout.box()
    pin_box.prop(props, "pin_enabled")
    pin_col = pin_box.column(align=True)
    pin_col.enabled = bool(props.pin_enabled)
    pin_col.prop_search(props, "pin_vertex_group", obj, "vertex_groups", text="Pin顶点组")

    self_box = layout.box()
    self_box.prop(props, "self_collision_enabled")
    self_col = self_box.column(align=True)
    self_col.enabled = bool(props.self_collision_enabled)
    self_col.prop(props, "self_collision_surface_thickness")
    self_col.prop(props, "mass")


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
        constraint = getattr(obj, "hotools_rigid_constraint", None)

        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)

        if obj_col is not None:
            grid.prop(obj_col, "enabled", text="被动碰撞",
                      icon="MOD_PHYSICS", toggle=True)

        if obj.type == "MESH" and mesh_col is not None:
            grid.prop(mesh_col, "enabled", text="网格碰撞",
                      icon="MESH_DATA", toggle=True)

        if rigid is not None:
            grid.prop(rigid, "enabled", text="刚体",
                      icon="RIGID_BODY", toggle=True)

        if obj.type == "EMPTY" and constraint is not None:
            grid.prop(constraint, "enabled", text="刚体约束",
                      icon="RIGID_BODY_CONSTRAINT", toggle=True)


# ---------------------------------------------------------------------------
# 子面板：被动碰撞
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_ObjectCollision(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_ObjectCollision"
    bl_label = "被动碰撞"
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
# 子面板：网格碰撞（仅 MESH）
# ---------------------------------------------------------------------------

class PT_Hotools_Physics_MeshCollision(Panel):
    bl_idname = "OBJECT_PT_Hotools_Physics_MeshCollision"
    bl_label = "网格碰撞"
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
        layout.prop(props, "collision_group")


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
            and props.collision_type != "NONE"
        )

    def draw(self, context):
        props = _active_collision_props(context)
        if props is None:
            return
        _draw_bone_collision_details(self.layout, props)
