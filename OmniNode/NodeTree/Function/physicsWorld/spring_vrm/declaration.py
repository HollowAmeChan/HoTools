"""VRM SpringBone 解算器声明。"""

from __future__ import annotations

from ..collision.capabilities import (
    BONE_COLLISION_CAPABILITY,
    BONE_COLLISION_CAPABILITY_ID,
)
from .capabilities import SPRING_VRM_UPDATE_FREQUENCY_TABLE
from ..names import BONE_TRANSFORM_CHANNEL
from .names import (
    BONE_COLLISION_OVERRIDE_OBJECT_TAG,
    SPRING_VRM_CHAIN_OBJECT_TAG,
    SPRING_VRM_SLOT_KIND,
    SPRING_VRM_SOLVER_ID,
    SPRING_VRM_STATS_CHANNEL,
    SPRING_VRM_STEP_WRITER_ID,
)


SPRING_VRM_SOLVER_DECLARATION = {
    "solver_id": SPRING_VRM_SOLVER_ID,
    "slot_kind": SPRING_VRM_SLOT_KIND,
    "stage": "spring_vrm_world_vertical_slice",
    "native_strategy": "context_api_only_no_python_or_legacy_array_backend",
    "nodes": [
        "骨骼碰撞覆写属性",
        "骨骼碰撞覆写注册",
        "VRM骨链属性",
        "VRM骨链对象注册",
        "SpringBone VRM模拟步",
    ],
    "planned_nodes": [],
    "writers": [
        SPRING_VRM_STEP_WRITER_ID,
        SPRING_VRM_SOLVER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        f"capability[{BONE_COLLISION_CAPABILITY_ID}] 生成并读取 Bone.hotools_collision 显式 RNA",
        f"capability[{BONE_COLLISION_CAPABILITY_ID}] 覆写层通过 "
        f'world.implicit_objects["{BONE_COLLISION_OVERRIDE_OBJECT_TAG}"]',
    ],
    "produces": [
        f'world.result_streams["{BONE_TRANSFORM_CHANNEL}"]',
        f'world.result_streams["{SPRING_VRM_STATS_CHANNEL}"]',
    ],
    "persistent_state": [
        "slot.data.frame_state",
        "slot.data.native_context",
        "slot.data.writeback_plan",
    ],
    "dirty_keys": [
        "world.generation",
        "armature_ptr",
        "armature_data_ptr",
        "implicit_object.signature",
        "implicit_object.version",
        f'world.implicit_objects["{BONE_COLLISION_OVERRIDE_OBJECT_TAG}"].signature',
        "Bone.hotools_collision capability hash",
        "collider_snapshot.source_key",
        "native_layout_version",
    ],
    "same_frame_policy": "skip_republish_cached_results",
    "update_policy": {
        "implicit_objects": "lazy_by_tag_stable_id_signature",
        "topology": "rebuild_slot_on_armature_or_chain_topology_change",
        "params": "refresh_native_arrays_without_python_solver_backend",
        "bone_collision_profile": "resolve_capability_override_then_explicit_property_then_default",
        "colliders": "lazy_cached_arrays_by_collider_snapshot_chain_and_bone_override_version",
        "same_frame": "republish_last_pose_results_no_time_step",
        "paused_time": "dt_le_zero_republish_last_pose_results_no_time_step",
    },
    "capabilities": {},
    "consumes_capabilities": [BONE_COLLISION_CAPABILITY_ID],
    "update_frequency_table": SPRING_VRM_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": [SPRING_VRM_CHAIN_OBJECT_TAG, BONE_COLLISION_OVERRIDE_OBJECT_TAG],
        "planned": [],
        "entry_kind": "spring_vrm_chain 或 bone_collision.override",
        "producer_nodes": ["VRM骨链对象注册", "骨骼碰撞覆写注册"],
        "planned_producer_nodes": [],
        "update_policy": "lazy_by_signature",
        "conflict_policy": "same_tag_and_stable_id_last_writer_wins",
        "capability_binding": {
            BONE_COLLISION_OVERRIDE_OBJECT_TAG: BONE_COLLISION_CAPABILITY_ID,
        },
    },
    "writeback": {
        "owner": "physicsWorld.writeback",
        "target": "PoseBone.matrix_basis",
        "solver_inline_writeback": False,
        "update_tag_owner": "writeback.apply",
    },
    "export": {
        "result_channels": [BONE_TRANSFORM_CHANNEL, SPRING_VRM_STATS_CHANNEL],
        "supports_bake": False,
        "bake_owner": "future unified writeback keyframe node",
        "solver_acceptance_blocker": False,
    },
    "legacy_policy": "removed_no_runtime_compatibility",
}



SPRING_VRM_REMOVED_SURFACES = {
    "python_nodes": (
        "springBoneVRMChainSetting",
        "springBoneVRM",
        "springBoneVRM_CPP",
        "springBoneBase",
    ),
    "python_runtime": (
        "_SpringBoneVRM",
        "_SpringBoneVRMCppBackend",
        "_run_spring_bone_vrm_node",
    ),
    "native_abi": (
        "hotools_native.solve_spring_bone_vrm_cpp",
        "hotools::SpringBoneVrmChainView",
        "hotools::solve_spring_bone_vrm_cpp",
    ),
    "property_owner": "physicsWorld.collision.properties",
    "property_registration_owner": "physicsWorld.registry",
    "persistent_storage_name": "Bone.hotools_collision",
}


def spring_vrm_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(SPRING_VRM_SOLVER_DECLARATION),
        "removed_surfaces": dict(SPRING_VRM_REMOVED_SURFACES),
    }
