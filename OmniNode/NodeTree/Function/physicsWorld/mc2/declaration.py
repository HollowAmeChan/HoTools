"""统一 MC2 solver 声明。"""

from __future__ import annotations

from ..collision.capabilities import (
    BONE_COLLISION_CAPABILITY_ID,
    OBJECT_COLLISION_CAPABILITY_ID,
)
from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from .setups.mesh_cloth.capabilities import MESH_COLLISION_CAPABILITY_ID
from .capabilities import MC2_CAPABILITIES, MC2_UPDATE_FREQUENCY_TABLE
from .names import (
    MC2_SETUP_TYPES,
    MC2_SLOT_KIND,
    MC2_SOLVER_ID,
    MC2_STATS_CHANNEL,
)


MC2_SOLVER_DECLARATION = {
    "solver_id": MC2_SOLVER_ID,
    "slot_kind": MC2_SLOT_KIND,
    "stage": "mesh_e5_bone_e5b_unified_domain_product",
    "native_strategy": "one_domain_v1_per_explicit_product_collector",
    "implementation_status": "mesh_and_bone_product_enabled_nodes_pending",
    "slot_kinds": [
        MC2_SLOT_KIND,
        "mc2_fused_cpu_product_v1",
        "mc2_fused_mesh_cpu_v1",
    ],
    "setup_types": list(MC2_SETUP_TYPES),
    "nodes": [
        "MC2 MeshCloth粒子配置",
        "MC2 BoneCloth粒子配置",
        "MC2 BoneSpring粒子配置",
        "MC2 MeshCloth任务",
        "MC2 Mesh对象",
        "MC2 Mesh覆盖",
        "MC2 Mesh隐式注册",
        "MC2 Mesh收集器",
        "MC2 BoneCloth任务",
        "MC2 BoneSpring任务",
        "MC2模拟步",
    ],
    "planned_nodes": [],
    "writers": [MC2_SOLVER_ID],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        "list[MC2TaskSpec] containing three setup types",
        "one MC2ProductRequestV1 for one explicit unified domain",
        "PhysicsWorldCache implicit tag mc2.mesh_partition.v1",
        "optional task.anchor_object evaluated world transform",
        "MC2 step time_scale/simulation_frequency/max_simulation_count_per_frame",
        "configured Mesh mc2_base_pose_proxy frame snapshot",
    ],
    "produces": [
        f'world.result_streams["{GN_ATTRIBUTE_CHANNEL}"]',
        f'world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
        f'world.result_streams["{MC2_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        "slot.data.topology",
        "slot.data.effective_parameters",
        "slot.data.runtime_state",
        "slot.data.writeback_plan",
        "slot.data.native_context",
        "slot.data.result_candidate",
        "fused slot.data.owner",
        "fused slot.data.collection",
        "fused slot.data.scheduler_state",
        "fused slot.data.output_batch",
        "fused slot.data.collector_request/report",
    ],
    "dirty_keys": [
        "world.generation",
        "task.setup_type",
        "task.sources",
        "task.task_id",
        "task.source_signature",
        "task.topology_signature",
        "task.config_signature",
        "task.parameter_signature",
        "step.scheduler_settings_signature",
        "collider_snapshot.source_key",
    ],
    "same_frame_policy": "reuse_candidate_no_backend_step_republish_result",
    "update_policy": {
        "node_execution": "always_run_then_frame_context_decides_step_reset_pause_or_same_frame",
        "framework": "mesh_request_uses_one_fused_domain_bone_and_legacy_tasks_use_v0_until_e7",
        "solver_core": "mesh_domain_v1_fixed_full_pass_order",
        "setup_dispatch": "mesh_product_request_or_explicit_legacy_task_path_never_implicit_fallback",
        "bone_cloth_partition": "one_control_bone_per_task_and_lateral_topology_group",
        "bone_frame_feedback": "mc2_owned_restore_read_barrier_preserves_current_animation_override",
        "bone_motion_mapping": "connected_rotation_only_disconnected_position_rotation",
        "anchor_frame": "optional_object_evaluated_each_frame_no_static_rebuild",
        "native_backend": "mesh_one_domain_v1_no_python_fallback",
    },
    "capabilities": MC2_CAPABILITIES,
    "consumes_capabilities": [
        OBJECT_COLLISION_CAPABILITY_ID,
        BONE_COLLISION_CAPABILITY_ID,
        MESH_COLLISION_CAPABILITY_ID,
    ],
    "update_frequency_table": MC2_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": ["mc2.mesh_partition.v1"],
        "planned": ["mc2.bone_cloth", "mc2.bone_spring"],
        "producer_nodes": ["MC2 Mesh隐式注册"],
        "planned_producer_nodes": [],
        "update_policy": "stable_id_snapshot_upsert_and_disable_missing_entries",
        "conflict_policy": "implicit_then_explicit_same_stable_id_field_resolution_or_explicit_conflict_failure",
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "shared OBJECT_LOCAL mesh final offset or PoseBone.matrix_basis selected by setup adapter",
        "composition": "publish one atomic multi-target GN transaction per Mesh domain or one PoseBone batch per Armature target",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [MC2_STATS_CHANNEL],
        "shared_result_channels": [
            GN_ATTRIBUTE_CHANNEL,
            BONE_TRANSFORM_CHANNEL,
        ],
        "planned_result_channels": [],
        "planned_shared_result_channels": [],
        "supports_bake": False,
        "solver_acceptance_blocker": False,
    },
    "legacy_policy": "mesh_v0_task_and_aggregate_frozen_pending_e7_cpu_removal_no_collector_fallback",
}
