"""
physicsWorld.rigid.specs — 刚体和约束的 spec 数据结构

spec 是 OmniNode 自己的物理语义表达，不依赖 Jolt 类型。
Jolt adapter（Phase 5）负责把 spec 映射到 Jolt BodyCreationSettings 等结构。

属性来源：bpy.types.Object.hotools_rigid_body 和 hotools_rigid_constraint
（PG_Hotools_RigidBody / PG_Hotools_RigidConstraint，由 PhysicsTools 注册），
由 HoTools 面板维护，节点图视为只读。

Phase 4 先只收集和调试，不要求 Jolt step 和写回。
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# RigidBodySpec
# ---------------------------------------------------------------------------

class RigidBodySpec:
    """
    单个刚体的 OmniNode 语义描述。

    使用 OmniNode 自己的字段名，不暴露 Jolt 内部概念。
    Jolt adapter 负责把这个 spec 映射到 BodyCreationSettings。
    """

    __slots__ = (
        "obj",
        "obj_ptr",
        "data_ptr",
        "slot_id",
        "body_type",
        "mass",
        "friction",
        "restitution",
        "collision_group",
    )

    def __init__(
        self,
        obj,
        obj_ptr: int,
        data_ptr: int,
        body_type: str = "DYNAMIC",
        mass: float = 1.0,
        friction: float = 0.5,
        restitution: float = 0.0,
        collision_group: int = 1,
    ) -> None:
        self.obj = obj
        self.obj_ptr: int = obj_ptr
        self.data_ptr: int = data_ptr
        self.slot_id: str = f"rigid:{obj_ptr}:{data_ptr}"
        self.body_type: str = body_type
        self.mass: float = mass
        self.friction: float = friction
        self.restitution: float = restitution
        self.collision_group: int = collision_group

    def debug_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "body_type": self.body_type,
            "mass": self.mass,
            "friction": self.friction,
            "restitution": self.restitution,
            "collision_group": self.collision_group,
        }


# ---------------------------------------------------------------------------
# ConstraintSpec
# ---------------------------------------------------------------------------

class ConstraintSpec:
    """
    单个约束的 OmniNode 语义描述。

    约束点载体为 Empty 对象：
      - Empty.matrix_world 表示约束 anchor frame（位置 + 旋转）
      - hotools_rigid_constraint PropertyGroup 表示约束类型和目标 A/B

    Jolt adapter 负责把 constraint_type 映射到 Jolt constraint 子类。
    Jolt ConstraintID 只保存在 runtime slot 中，不写回 Empty。
    """

    __slots__ = (
        "empty_obj",
        "empty_ptr",
        "slot_id",
        "constraint_type",
        "target_a",
        "target_b",
    )

    def __init__(
        self,
        empty_obj,
        empty_ptr: int,
        constraint_type: str = "FIXED",
        target_a=None,
        target_b=None,
    ) -> None:
        self.empty_obj = empty_obj
        self.empty_ptr: int = empty_ptr
        self.slot_id: str = f"constraint:{empty_ptr}"
        self.constraint_type: str = constraint_type
        self.target_a = target_a   # bpy.types.Object 或 None（固定到世界）
        self.target_b = target_b   # bpy.types.Object 或 None

    def debug_dict(self) -> dict:
        return {
            "slot_id": self.slot_id,
            "constraint_type": self.constraint_type,
            "target_a": self.target_a.name if self.target_a is not None else None,
            "target_b": self.target_b.name if self.target_b is not None else None,
        }


# ---------------------------------------------------------------------------
# 从 PropertyGroup 构造 spec
# ---------------------------------------------------------------------------

def build_rigid_body_spec(obj) -> RigidBodySpec | None:
    """
    从 obj.hotools_rigid_body PropertyGroup 构造 RigidBodySpec。

    hotools_rigid_body.enabled=False 或属性不存在时返回 None（不参与刚体）。
    """
    if obj is None:
        return None

    props = getattr(obj, "hotools_rigid_body", None)
    if props is None or not bool(getattr(props, "enabled", False)):
        return None

    try:
        obj_ptr = int(obj.as_pointer())
        data_ptr = int(obj.data.as_pointer()) if obj.data is not None else 0
    except Exception:
        return None

    body_type = str(getattr(props, "body_type", "DYNAMIC"))
    mass = max(float(getattr(props, "mass", 1.0)), 0.001)
    friction = max(0.0, min(1.0, float(getattr(props, "friction", 0.5))))
    restitution = max(0.0, min(1.0, float(getattr(props, "restitution", 0.0))))
    collision_group = max(1, min(16, int(getattr(props, "collision_group", 1))))

    return RigidBodySpec(
        obj=obj,
        obj_ptr=obj_ptr,
        data_ptr=data_ptr,
        body_type=body_type,
        mass=mass,
        friction=friction,
        restitution=restitution,
        collision_group=collision_group,
    )


def build_constraint_spec(empty_obj) -> ConstraintSpec | None:
    """
    从 empty_obj.hotools_rigid_constraint PropertyGroup 构造 ConstraintSpec。

    hotools_rigid_constraint.enabled=False 或对象不是 EMPTY 时返回 None。
    """
    if empty_obj is None:
        return None

    try:
        if empty_obj.type != "EMPTY":
            return None
        empty_ptr = int(empty_obj.as_pointer())
    except Exception:
        return None

    props = getattr(empty_obj, "hotools_rigid_constraint", None)
    if props is None or not bool(getattr(props, "enabled", False)):
        return None

    constraint_type = str(getattr(props, "constraint_type", "FIXED"))
    target_a = getattr(props, "target_a", None)
    target_b = getattr(props, "target_b", None)

    return ConstraintSpec(
        empty_obj=empty_obj,
        empty_ptr=empty_ptr,
        constraint_type=constraint_type,
        target_a=target_a,
        target_b=target_b,
    )
