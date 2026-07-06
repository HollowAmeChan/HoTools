# physicsWorld — 统一物理世界包
#
# 目录语义：
#   types.py   — PhysicsWorldCache、PhysicsFrameContext、PhysicsObjectScope、PhysicsColliderSource
#   scope.py   — 对象列表合并、过滤、去重、作用域键计算
#   world.py   — 开始 / 提交 / 生命周期 / 槽管理
#   debug.py   — 调试快照、文本展开、校验结果
#   nodes.py   — 对外暴露的通用函数节点（由 OmniNodeRegister 加载注册）
#   names.py   — solver/channel/backend/implicit object 使用的全局名称常量
#   utils/     — 新物理世界通用数学、id、buffer 辅助函数
#   rigid/     — 刚体领域（阶段 4+）
#   spring_vrm/ — VRM SpringBone 重写领域（面向物理世界的垂直切片）

from .types import (
    PhysicsObjectScope,
    PhysicsFrameContext,
    PhysicsColliderSource,
    PhysicsSolverSlot,
    PhysicsWorldCache,
)
from .scope import (
    build_scope_key,
    dedupe_objects,
    merge_object_lists,
    objects_from_collection,
    filter_objects_by_type,
    make_scope,
    collect_physics_sources,
)
from .world import (
    physicsWorldBegin,
    physicsWorldCommit,
    build_collider_snapshot,
)
from .debug import (
    snapshot_to_text,
    result_items_to_text,
    validate_world,
    print_world_summary,
)
from .names import (
    JOLT_STEP_WRITER_ID,
    RIGID_BACKEND_RESOURCE_KEY,
    RIGID_BODY_COMMANDS_CHANNEL,
    RIGID_BODY_REGISTER_WRITER_ID,
    RIGID_BODY_SLOT_KIND,
    RIGID_CONSTRAINT_REGISTER_WRITER_ID,
    RIGID_CONSTRAINT_SLOT_KIND,
    RIGID_SOLVER_ID,
    RIGID_SOLVER_STATS_CHANNEL,
    RIGID_TRANSFORM_CHANNEL,
    SPRING_VRM_CHAIN_OBJECT_TAG,
    SPRING_VRM_POSE_CHANNEL,
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    SPRING_VRM_STEP_WRITER_ID,
)

__all__ = [
    # types
    "PhysicsObjectScope",
    "PhysicsFrameContext",
    "PhysicsColliderSource",
    "PhysicsSolverSlot",
    "PhysicsWorldCache",
    # scope
    "build_scope_key",
    "dedupe_objects",
    "merge_object_lists",
    "objects_from_collection",
    "filter_objects_by_type",
    "make_scope",
    "collect_physics_sources",
    # world
    "physicsWorldBegin",
    "physicsWorldCommit",
    "build_collider_snapshot",
    # debug
    "snapshot_to_text",
    "result_items_to_text",
    "validate_world",
    "print_world_summary",
    # names
    "JOLT_STEP_WRITER_ID",
    "RIGID_BACKEND_RESOURCE_KEY",
    "RIGID_BODY_COMMANDS_CHANNEL",
    "RIGID_BODY_REGISTER_WRITER_ID",
    "RIGID_BODY_SLOT_KIND",
    "RIGID_CONSTRAINT_REGISTER_WRITER_ID",
    "RIGID_CONSTRAINT_SLOT_KIND",
    "RIGID_SOLVER_ID",
    "RIGID_SOLVER_STATS_CHANNEL",
    "RIGID_TRANSFORM_CHANNEL",
    "SPRING_VRM_CHAIN_OBJECT_TAG",
    "SPRING_VRM_POSE_CHANNEL",
    "SPRING_VRM_SLOT_KIND",
    "SPRING_VRM_SOLVER_ID",
    "SPRING_VRM_STATS_CHANNEL",
    "SPRING_VRM_STEP_WRITER_ID",
]
