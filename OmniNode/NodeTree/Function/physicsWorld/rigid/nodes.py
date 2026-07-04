"""
physicsWorld.rigid.nodes — 刚体 domain 节点定义（Phase 4）

节点列表：
  physicsRigidSolver — 同时注册刚体 spec 和约束 spec 到 world slot

Phase 4 只做 spec 收集和 slot 注册，不做 Jolt step。
通过 physicsWorldDebugSnapshot 可观察 body / constraint 数量和 slot 内容。
"""

import bpy

from ....FunctionNodeCore import omni
from ... import _Color
from ..types import PhysicsWorldCache
from .solver import register_rigid_bodies, register_constraints


@omni(
    enable=True,
    bl_label="刚体注册",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物理世界", "刚体对象", "约束点对象"],
    _OUTPUT_NAME=["物理世界", "刚体数量", "约束数量"],
    omni_description="""
    同时注册刚体 spec 和约束 spec 到 PhysicsWorldCache solver slot。

    刚体对象需在 HoTools 面板设置 hotools_rigid_type
    （DYNAMIC / STATIC / KINEMATIC），未设置的对象跳过。

    约束点为 Empty 对象，需设置 hotools_constraint_type
    （FIXED / HINGE / SLIDER / CONE / POINT）及 target_a / target_b。

    Phase 4 只收集 spec，不执行 Jolt 模拟步。
    通过"物理世界-调试快照"节点可确认 body / constraint 数量。
    """,
)
def physicsRigidSolver(
    world: object,
    rigid_objects: list[bpy.types.Object],
    constraint_objects: list[bpy.types.Object],
) -> tuple[object, int, int]:
    if not isinstance(world, PhysicsWorldCache):
        return world, 0, 0
    body_count, _ = register_rigid_bodies(world, rigid_objects)
    constraint_count, _ = register_constraints(world, constraint_objects)
    return world, body_count, constraint_count
