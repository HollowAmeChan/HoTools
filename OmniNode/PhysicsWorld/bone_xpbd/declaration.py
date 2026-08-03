"""Bone XPBD Physics World solver 声明。"""

from __future__ import annotations

from ..collision.capabilities import BONE_COLLISION_CAPABILITY_ID
from ..names import BONE_TRANSFORM_CHANNEL
from .names import (
    BONE_XPBD_NATIVE_LAYOUT_VERSION,
    BONE_XPBD_SLOT_KIND,
    BONE_XPBD_SOLVER_ID,
    BONE_XPBD_STATS_CHANNEL,
    BONE_XPBD_STEP_WRITER_ID,
)


BONE_XPBD_SOLVER_DECLARATION = {
    "solver_id": BONE_XPBD_SOLVER_ID,
    "slot_kind": BONE_XPBD_SLOT_KIND,
    "stage": "experimental_vertical_slice",
    "runtime_status": "available_experimental",
    "native_strategy": "shared_stateful_xpbd_distance_context",
    "native_layout_version": BONE_XPBD_NATIVE_LAYOUT_VERSION,
    "nodes": [
        "Bone XPBD对象",
        "Bone XPBD自定义对象",
        "Bone XPBD任务",
        "Bone XPBD可视化调试",
    ],
    "planned_nodes": [],
    "writers": [BONE_XPBD_STEP_WRITER_ID],
    "planned_writers": [],
    "consumes_capabilities": [BONE_COLLISION_CAPABILITY_ID],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        "Bone.hotools_collision.pin与bone_collision.override",
        "显式Bone XPBD对象与任务",
        "共享XPBD模拟步的强类型域调度",
        "公共Bone writeback成功receipt",
    ],
    "produces": [
        f'world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
        f'world.result_streams["{BONE_XPBD_STATS_CHANNEL}"]',
    ],
    "planned_produces": ["公共Field WindV0原生子步响应"],
    "persistent_state": [
        "slot.data.topology",
        "slot.data.native_context",
        "slot.data.writeback_plan",
        "world.backend_resources[bone_xpbd.frame_state] pending/confirmed反馈",
        "slot.data.debug_capture (request-driven)",
    ],
    "dirty_keys": [
        "world.generation",
        "Armature object/data identity",
        "显式bone name集合与rest端点几何",
        "公共Bone Pin解析结果",
        "粒子半径与task参数",
        "collider_snapshot.source_key",
        "native_layout_version",
    ],
    "same_frame_policy": "republish_cached_particles_and_rebuild_pose_plan_without_time_step",
    "update_policy": {
        "authoring": "explicit_actual_bone_list_only",
        "simulation_node": "shared_xpbd_step_accepts_mesh_and_bone_tasks",
        "topology": "rest_geometry_endpoint_weld_without_depth_or_parent_direction",
        "pin": "moving_pin_targets_do_not_change_constraint_rest",
        "params": "native_hot_update_without_topology_rebuild",
        "same_frame": "read_and_republish_without_time_step",
        "restart": "rebuild_context_from_current_logical_animation_pose",
        "writeback": "merge_all_armature_targets_then_resolve_basis_and_confirm_by_receipt",
    },
    "collision": {
        "source": "PhysicsWorldCache.collider_snapshot",
        "shapes": ["SPHERE", "CAPSULE", "PLANE", "BOX"],
        "filter": "task-level 16-bit collided_by_groups",
        "self_filter": "exclude_simulated_bones_only",
        "per_particle_mask": False,
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "PoseBone.matrix_basis batch",
        "channel": BONE_TRANSFORM_CHANNEL,
        "solver_inline_writeback": False,
        "tail_follow_default": True,
        "use_connect_special_case": False,
    },
    "limitations": [
        "当前只有segment stretch与二阶distance bend，不等价于rod/shape matching",
        "外部碰撞mask首版为task统一值，不伪装成逐骨mask",
        "Field WindV0尚未接入此solver",
    ],
    "export": {
        "result_channels": [BONE_XPBD_STATS_CHANNEL],
        "shared_result_channels": [BONE_TRANSFORM_CHANNEL],
        "planned_result_channels": [],
        "planned_shared_result_channels": [],
        "supports_bake": True,
        "bake_owner": "Physics World public Bone bake path",
        "solver_acceptance_blocker": True,
    },
}
