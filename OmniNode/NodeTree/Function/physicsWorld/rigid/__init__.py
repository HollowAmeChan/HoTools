# physicsWorld.rigid — 刚体 domain
#
# 刚体是物理世界里的一个 domain，放在 physicsWorld 下面，不单独建立刚体世界。
# 公开语义使用 OmniNode / Blender 名称，Jolt 只作 backend（Phase 5 接入）。
#
#   specs.py    — RigidBodySpec、ConstraintSpec 及从 PropertyGroup 构造的工具函数
#   solver.py   — 把 specs 注册到 PhysicsWorldCache solver slot 的逻辑
#   results.py  — solver 每帧输出给 writeback/debug/export 的稳定结果
#   nodes.py    — @omni 装饰的节点定义
#   backends/   — native backend 适配层（Phase 5 加入 jolt.py）

from .specs import (
    RigidBodySpec,
    ConstraintSpec,
    build_rigid_body_spec,
    build_constraint_spec,
)
from .solver import (
    register_rigid_bodies,
    register_constraints,
)
from .declaration import (
    RIGID_SOLVER_DECLARATION,
    rigid_declaration_debug_dict,
)

__all__ = [
    "RIGID_SOLVER_DECLARATION",
    "RigidBodySpec",
    "ConstraintSpec",
    "build_rigid_body_spec",
    "build_constraint_spec",
    "register_rigid_bodies",
    "register_constraints",
    "rigid_declaration_debug_dict",
]
