"""统一 MC2 solver 声明。"""

from __future__ import annotations

from .capabilities import MC2_CAPABILITIES, MC2_UPDATE_FREQUENCY_TABLE
from .names import (
    MC2_FUSED_PRODUCT_SLOT_KIND,
    MC2_SETUP_TYPES,
    MC2_SOLVER_ID,
)
from ..collision.capabilities import (
    BONE_COLLISION_CAPABILITY_ID,
    OBJECT_COLLISION_CAPABILITY_ID,
)
from ..names import BONE_TRANSFORM_CHANNEL, GN_ATTRIBUTE_CHANNEL
from .setups.mesh_cloth.capabilities import MESH_COLLISION_CAPABILITY_ID


MC2_SOLVER_DECLARATION = {
    "solver_id": MC2_SOLVER_ID,
    "slot_kind": MC2_FUSED_PRODUCT_SLOT_KIND,
    "stage": "p6_contract_complete_cpu_product_domain_only",
    "native_strategy": "one_domain_v1_per_explicit_collector_request",
    "implementation_status": "e7_complete_p6_complete_no_gpu_runtime",
    "backend_contract": {
        "schema_version": 2,
        "data_pass": "MC2BackendDataPassContractV1",
        "upload": "MC2BackendUploadPlanV1",
        "dynamic_capacity": "MC2BackendDynamicCapacityPolicyV1",
        "io": "MC2_BACKEND_IO_CONTRACT_V1",
        "numerical": "MC2_BACKEND_NUMERICAL_POLICY_V1",
        "runtime_backend_created": False,
    },
    "slot_kinds": [
        MC2_FUSED_PRODUCT_SLOT_KIND,
    ],
    "setup_types": list(MC2_SETUP_TYPES),
    "nodes": [
        "MC2 MeshCloth粒子配置",
        "MC2 BoneCloth粒子配置",
        "MC2 BoneSpring粒子配置",
        "MC2 MeshCloth对象",
        "MC2 MeshCloth自定义对象",
        "MC2 MeshCloth域",
        "MC2 Mesh域收集",
        "MC2 BoneCloth对象",
        "MC2 BoneCloth自定义对象",
        "MC2 BoneCloth域",
        "MC2 Bone域收集",
        "MC2 BoneSpring域",
        "MC2模拟步",
    ],
    "planned_nodes": [],
    "writers": [MC2_SOLVER_ID],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        "one or more collected MC2ProductRequestV1 domains",
        "complete Mesh partitions with frozen object properties",
        "complete BoneCloth partitions with frozen object properties",
        "optional task.anchor_object evaluated world transform",
        "MC2 step time_scale/simulation_frequency/max_simulation_count_per_frame",
        "configured Mesh mc2_base_pose_proxy frame snapshot",
    ],
    "produces": [
        f'world.result_streams["{GN_ATTRIBUTE_CHANNEL}"]',
        f'world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
    ],
    "persistent_state": [
        "fused slot.data.owner",
        "fused slot.data.collection",
        "fused slot.data.scheduler_state",
        "fused slot.data.output_batch",
        "fused slot.data.collector_request/report",
    ],
    "dirty_keys": [
        "world.generation",
        "request.setup_type",
        "request.domain_signature",
        "request.plan.report.topology_signature",
        "request.plan.report.config_signature",
        "request.plan.report.parameter_signature",
        "step.scheduler_settings_signature",
        "collider_snapshot.source_key",
    ],
    "same_frame_policy": "reuse_candidate_no_backend_step_republish_result",
    "update_policy": {
        "node_execution": "always_run_then_frame_context_decides_step_reset_pause_or_same_frame",
        "framework": "object_adapter_to_domain_partition_to_setup_collector",
        "solver_core": "all_product_domains_v1_fixed_full_pass_order",
        "setup_dispatch": "explicit_product_request_batch_only",
        "bone_cloth_partition": "one_wrapped_control_bone_per_partition_same_armature_per_explicit_request",
        "bone_frame_feedback": "mc2_owned_restore_read_barrier_preserves_current_animation_override",
        "bone_motion_mapping": "connected_rotation_only_disconnected_position_rotation",
        "anchor_frame": "optional_object_evaluated_each_frame_no_static_rebuild",
        "native_backend": "one_domain_v1_per_explicit_collector_request",
    },
    "capabilities": MC2_CAPABILITIES,
    "consumes_capabilities": [
        OBJECT_COLLISION_CAPABILITY_ID,
        BONE_COLLISION_CAPABILITY_ID,
        MESH_COLLISION_CAPABILITY_ID,
    ],
    "update_frequency_table": MC2_UPDATE_FREQUENCY_TABLE,
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "shared OBJECT_LOCAL mesh final offset or PoseBone.matrix_basis selected by setup adapter",
        "composition": "publish one atomic multi-target GN transaction per Mesh domain or one PoseBone batch per Armature target",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [],
        "shared_result_channels": [
            GN_ATTRIBUTE_CHANNEL,
            BONE_TRANSFORM_CHANNEL,
        ],
        "planned_result_channels": [],
        "planned_shared_result_channels": [],
        "supports_bake": False,
        "solver_acceptance_blocker": False,
    },
}
