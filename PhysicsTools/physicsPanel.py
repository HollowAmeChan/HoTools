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

from .collisionPanel import (
    _draw_object_collision_controls,
    _draw_mesh_collision_controls,
)

_PARENT = "OBJECT_PT_Hotools_PhysicsPanel"


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
