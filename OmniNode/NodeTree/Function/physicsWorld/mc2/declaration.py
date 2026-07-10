"""统一 MC2 solver 声明。"""

from __future__ import annotations

from ..collision.capabilities import (
    BONE_COLLISION_CAPABILITY_ID,
    OBJECT_COLLISION_CAPABILITY_ID,
)
from .setups.mesh_cloth.capabilities import MESH_COLLISION_CAPABILITY_ID
from .capabilities import MC2_CAPABILITIES, MC2_UPDATE_FREQUENCY_TABLE
from .names import (
    MC2_BONE_RESULT_CHANNEL,
    MC2_MESH_RESULT_CHANNEL,
    MC2_SETUP_TYPES,
    MC2_SLOT_KIND,
    MC2_SOLVER_ID,
    MC2_STATS_CHANNEL,
)


MC2_SOLVER_DECLARATION = {
    "solver_id": MC2_SOLVER_ID,
    "slot_kind": MC2_SLOT_KIND,
    "stage": "framework_only_no_runtime_backend",
    "native_strategy": "one_solver_three_setup_adapters_backend_is_not_solver_identity",
    "implementation_status": "framework_only",
    "setup_types": list(MC2_SETUP_TYPES),
    "nodes": [
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
    ],
    "produces": [
        f'planned:world.result_streams["{MC2_MESH_RESULT_CHANNEL}"]',
        f'planned:world.result_streams["{MC2_BONE_RESULT_CHANNEL}"]',
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
        "planned:task.backend",
        "planned:collider_snapshot.source_key",
    ],
    "same_frame_policy": "framework_noop",
    "update_policy": {
        "framework": "no_slot_no_result_no_legacy_solver_call",
        "solver_core": "one_shared_mc2_step",
        "setup_dispatch": "mesh_cloth_or_bone_cloth_or_bone_spring_adapter",
        "backend_dispatch": "auto_python_cpp_inside_solver_not_separate_solver",
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
        "target": "GN mesh delta or PoseBone.matrix_basis selected by setup adapter",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [
            MC2_MESH_RESULT_CHANNEL,
            MC2_BONE_RESULT_CHANNEL,
            MC2_STATS_CHANNEL,
        ],
        "supports_bake": False,
        "solver_acceptance_blocker": True,
    },
    "legacy_policy": "old physicsMC2 packages remain active and are not called by this framework",
}
