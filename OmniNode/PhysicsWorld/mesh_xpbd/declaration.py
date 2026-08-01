"""Mesh XPBD Physics World solver 声明。"""

from __future__ import annotations

from ..names import GN_ATTRIBUTE_CHANNEL
from .names import (
    MESH_XPBD_NATIVE_LAYOUT_VERSION,
    MESH_XPBD_SLOT_KIND,
    MESH_XPBD_SOLVER_ID,
    MESH_XPBD_STATS_CHANNEL,
    MESH_XPBD_STEP_WRITER_ID,
)


MESH_XPBD_SOLVER_DECLARATION = {
    "solver_id": MESH_XPBD_SOLVER_ID,
    "slot_kind": MESH_XPBD_SLOT_KIND,
    "stage": "native_context_complete_world_runtime_not_connected",
    "runtime_status": "not_available_until_physics_world_vertical_slice",
    "native_strategy": "stateful_nanobind_context_only_no_python_numeric_backend",
    "native_layout_version": MESH_XPBD_NATIVE_LAYOUT_VERSION,
    "nodes": [],
    "planned_nodes": [
        "XPBD网格任务",
        "XPBD模拟步",
    ],
    "writers": [],
    "planned_writers": [MESH_XPBD_STEP_WRITER_ID],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        "XPBD网格任务.task_specs",
    ],
    "planned_produces": [
        f'world.result_streams["{GN_ATTRIBUTE_CHANNEL}"]',
        f'world.result_streams["{MESH_XPBD_STATS_CHANNEL}"]',
    ],
    "produces": [],
    "persistent_state": [
        "slot.data.topology",
        "slot.data.native_context",
        "slot.data.last_result",
        "slot.data.writeback_plan",
    ],
    "dirty_keys": [
        "world.generation",
        "source object/data identity",
        "evaluated mesh topology signature",
        "Basis/reference positions signature",
        "pin/radius vertex-group signatures",
        "task parameter signature",
        "collider_snapshot.source_key",
        "native_layout_version",
    ],
    "same_frame_policy": "republish_cached_result_without_time_step",
    "update_policy": {
        "task_input": "direct_list_validate_then_prune_stale_slots",
        "topology": "staged_replace_on_mesh_connectivity_or_reference_change",
        "params": "refresh_context_parameters_without_topology_rebuild",
        "colliders": "consume_common_snapshot_lazily_by_source_key_and_mask",
        "same_frame": "republish_last_result_no_time_step",
        "paused_time": "dt_le_zero_republish_last_result_no_time_step",
        "restart": "cold_reset_positions_and_velocity_from_current_reference_pose",
    },
    "collision": {
        "source": "PhysicsWorldCache.collider_snapshot",
        "shapes_required_before_freeze": ["SPHERE", "CAPSULE", "PLANE", "BOX"],
        "filter": "task.collided_by_groups intersects collider.primary_group",
        "default_collided_by_groups": 0,
        "self_collision": False,
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "GN mesh vertex offset",
        "channel": GN_ATTRIBUTE_CHANNEL,
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "backend_contract": {
        "binding": "nanobind typed ndarray/context",
        "native_context_available": True,
        "python_solver_fallback": False,
        "blender_access": False,
        "global_mutable_state": False,
    },
    "freeze_policy": (
        "production acceptance 后冻结基础 solver 的产品语义；自碰撞、体积软体、"
        "撕裂、塑性、高级弯曲、CCD 或 GPU 改良必须使用新 solver id"
    ),
    "legacy_policy": "remove_after_new_vertical_slice_acceptance_no_runtime_compatibility",
}


MESH_XPBD_LEGACY_SURFACES = {
    "python_runtime": (
        "_MeshPhysics",
        "_MeshPhysicsCppBackend",
        "_run_mesh_xpbd_node",
    ),
    "python_nodes": (
        "meshPhysicsXPBD",
        "meshPhysicsXPBDCpp",
    ),
    "private_writeback": (
        "XPBDDelta",
        "xpbd_delta",
    ),
    "private_cache": ("mesh_xpbd legacy _OmniCache payload",),
    "dangling_native_abi": (
        "hotools_native.solve_mesh_delta_xpbd",
        "hotools_native.solve_mesh_shape_key_xpbd",
    ),
}


def mesh_xpbd_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(MESH_XPBD_SOLVER_DECLARATION),
        "legacy_surfaces": dict(MESH_XPBD_LEGACY_SURFACES),
    }
