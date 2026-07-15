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
    "stage": "mesh_point_collision_and_bone_line_native_public_result",
    "native_strategy": "one_solver_three_setup_adapters_single_native_context",
    "implementation_status": "mesh_point_collision_and_bone_line_native_public_result",
    "setup_types": list(MC2_SETUP_TYPES),
    "nodes": [
        "MC2粒子配置",
        "MC2模拟设置",
        "MC2 MeshCloth任务（框架）",
        "MC2 BoneCloth任务（框架）",
        "MC2 BoneSpring任务（框架）",
        "MC2模拟步（框架）",
    ],
    "planned_nodes": [],
    "writers": [MC2_SOLVER_ID],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        "list[MC2TaskSpec] containing three setup types",
        "MC2SolverSettingsSpec",
        "configured Mesh mc2_base_pose_proxy frame snapshot",
    ],
    "produces": [
        f'world.result_streams["{GN_ATTRIBUTE_CHANNEL}"]',
        f'world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
        f'planned:world.result_streams["{MC2_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        "slot.data.topology",
        "slot.data.initial_state",
        "slot.data.particle_buffer",
        "slot.data.effective_parameters",
        "slot.data.runtime_state",
        "slot.data.writeback_plan",
        "slot.data.native_context",
        "slot.data.result_candidate",
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
        "step.settings.signature",
        "planned:collider_snapshot.source_key",
    ],
    "same_frame_policy": "reuse_candidate_no_backend_step_republish_result",
    "update_policy": {
        "framework": "sync_topology_auto_mesh_or_bone_frame_native_context_and_public_result",
        "solver_core": "one_shared_mc2_step",
        "setup_dispatch": "mesh_cloth_or_bone_cloth_or_bone_spring_adapter",
        "native_backend": "single_native_context_no_python_fallback",
    },
    "capabilities": MC2_CAPABILITIES,
    "consumes_capabilities": [
        OBJECT_COLLISION_CAPABILITY_ID,
        BONE_COLLISION_CAPABILITY_ID,
        MESH_COLLISION_CAPABILITY_ID,
    ],
    "update_frequency_table": MC2_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": [],
        "planned": ["mc2.mesh_cloth", "mc2.bone_cloth", "mc2.bone_spring"],
        "producer_nodes": [],
        "planned_producer_nodes": [],
        "update_policy": "topology_and_particle_buffer_only",
        "conflict_policy": "future stable_id last writer wins",
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "shared OBJECT_LOCAL mesh final offset or PoseBone.matrix_basis selected by setup adapter",
        "composition": "publish one final GN result per Mesh target or one PoseBone batch per Armature target",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [],
        "shared_result_channels": [
            GN_ATTRIBUTE_CHANNEL,
            BONE_TRANSFORM_CHANNEL,
        ],
        "planned_result_channels": [
            MC2_STATS_CHANNEL,
        ],
        "planned_shared_result_channels": [],
        "supports_bake": False,
        "solver_acceptance_blocker": True,
    },
    "legacy_policy": "old physicsMC2 packages remain active and are not called by this framework",
}
