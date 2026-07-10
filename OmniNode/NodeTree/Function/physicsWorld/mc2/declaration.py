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
    "stage": "framework_only_no_runtime_backend",
    "native_strategy": "one_solver_three_setup_adapters_single_native_context",
    "implementation_status": "framework_only",
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
    ],
    "produces": [
        f'planned:world.result_streams["{GN_ATTRIBUTE_CHANNEL}"]',
        f'planned:world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
        f'planned:world.result_streams["{MC2_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        "planned:slot.data.mc2_context",
        "planned:slot.data.setup_adapters",
        "planned:slot.data.writeback_plan",
    ],
    "dirty_keys": [
        "planned:world.generation",
        "planned:task.setup_type",
        "planned:task.sources",
        "planned:task.task_id",
        "planned:task.source_signature",
        "task.topology_signature",
        "task.config_signature",
        "task.parameter_signature",
        "step.settings.signature",
        "planned:collider_snapshot.source_key",
    ],
    "same_frame_policy": "framework_noop",
    "update_policy": {
        "framework": "no_slot_no_result_no_legacy_solver_call",
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
        "update_policy": "framework_noop",
        "conflict_policy": "future stable_id last writer wins",
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "shared OBJECT_LOCAL mesh final offset or PoseBone.matrix_basis selected by setup adapter",
        "composition": "intermediate offset parts stay in world.exchange; publish one final result per Mesh target",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [],
        "shared_result_channels": [],
        "planned_result_channels": [
            MC2_STATS_CHANNEL,
        ],
        "planned_shared_result_channels": [
            GN_ATTRIBUTE_CHANNEL,
            BONE_TRANSFORM_CHANNEL,
        ],
        "supports_bake": False,
        "solver_acceptance_blocker": True,
    },
    "legacy_policy": "old physicsMC2 packages remain active and are not called by this framework",
}
