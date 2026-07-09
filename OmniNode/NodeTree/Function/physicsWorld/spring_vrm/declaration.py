"""VRM SpringBone 解算器声明。"""

from __future__ import annotations

from .capabilities import (
    BONE_COLLISION_CAPABILITY,
    BONE_COLLISION_CAPABILITY_ID,
    SPRING_VRM_UPDATE_FREQUENCY_TABLE,
)
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
    "native_strategy": "cpp_only_no_python_runtime_backend",
    "nodes": [
        "VRM骨链属性",
        "VRM骨链对象注册",
        "SpringBone VRM模拟步",
    ],
    "planned_nodes": [
        "骨骼碰撞覆写属性",
        "骨骼碰撞覆写注册",
    ],
    "writers": [
        SPRING_VRM_STEP_WRITER_ID,
        SPRING_VRM_SOLVER_ID,
    ],
    "consumes": [
        "PhysicsWorldCache.frame_context",
        "PhysicsWorldCache.collider_snapshot",
        f'world.implicit_objects["{SPRING_VRM_CHAIN_OBJECT_TAG}"]',
        f"capability[{BONE_COLLISION_CAPABILITY_ID}] 通过旧 Bone.hotools_collision 回退读取",
        f"计划中的 capability[{BONE_COLLISION_CAPABILITY_ID}] 通过 "
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
        "Bone.hotools_collision 能力回退 hash",
        "collider_snapshot.source_key",
        "native_layout_version",
    ],
    "same_frame_policy": "skip_republish_cached_results",
    "update_policy": {
        "implicit_objects": "lazy_by_tag_stable_id_signature",
        "topology": "rebuild_slot_on_armature_or_chain_topology_change",
        "params": "refresh_native_arrays_without_python_solver_backend",
        "bone_collision_profile": "resolve_capability_override_then_legacy_property_then_default",
        "colliders": "sample_world_collider_snapshot_each_step",
        "same_frame": "republish_last_pose_results_no_time_step",
    },
    "capabilities": {
        BONE_COLLISION_CAPABILITY_ID: BONE_COLLISION_CAPABILITY,
    },
    "update_frequency_table": SPRING_VRM_UPDATE_FREQUENCY_TABLE,
    "implicit_objects": {
        "consumes": [SPRING_VRM_CHAIN_OBJECT_TAG],
        "planned": [BONE_COLLISION_OVERRIDE_OBJECT_TAG],
        "entry_kind": "spring_vrm_chain",
        "producer_nodes": ["VRM骨链对象注册"],
        "planned_producer_nodes": ["骨骼碰撞覆写注册"],
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
    },
    "legacy_policy": "rewrite_only_no_compatibility",
}


SPRING_VRM_LEGACY_DISCARD_AUDIT = [
    {
        "legacy_symbol": "_run_spring_bone_vrm_node",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "discard",
        "reason": "旧节点把 cache 分发、帧规则、solver 执行和写回合在一个黑箱入口里。",
    },
    {
        "legacy_symbol": "_SpringBoneVRM.prepare",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "rewrite",
        "reason": "旧实现混合输入校验、cache match、scene 碰撞扫描和跳帧处理。",
    },
    {
        "legacy_symbol": "_SpringBoneVRM.write_pose",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "discard",
        "reason": "旧实现会在 solver 流程内部直接写 PoseBone.matrix_basis。",
    },
    {
        "legacy_symbol": "armature.update_tag in _SpringBoneVRM.run",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "discard",
        "reason": "depsgraph invalidation 必须归属统一 writeback，而不是 solver step。",
    },
    {
        "legacy_symbol": "_SpringBoneVRM.collision_snapshot/_collision_sources",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "discard",
        "reason": "旧 scene 扫描已经替换为 PhysicsWorldCache.collider_snapshot。",
    },
    {
        "legacy_symbol": "_SpringBoneVRM.solve_cpp pack/unpack wrapper",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "rewrite",
        "reason": "数组映射可参考，但 state 和对象引用必须进入 solver slot 分区。",
    },
    {
        "legacy_symbol": "hotools_native.solve_spring_bone_vrm_cpp",
        "source": "_native/src/spring_bone_vrm.cpp",
        "decision": "keep_as_kernel_reference",
        "reason": "纯数组计算核不持有 Blender 对象，适合作为新 C++ 单实现的数值参考。",
    },
    {
        "legacy_symbol": "springBoneBase",
        "source": "OmniNode/NodeTree/Function/Physics.py",
        "decision": "migrate_then_discard",
        "reason": (
            "非 VRM 基础弹簧骨，共享 _BonePhysics 但走旧 cache/直写 PoseBone 路径。"
            "纳入统一物理世界迁移；新路径落地并验证后与旧 VRM 节点一起删除。"
        ),
    },
]


# 删除清单：新路径在 Blender 内验证与旧路径行为一致后，一次性移除下列符号。
# 本轮只登记，不删除（用户决定：先留作对照，补完 + Blender 验证后再删）。
SPRING_VRM_LEGACY_DELETE_CHECKLIST = {
    "gate": "新 physicsWorld/spring_vrm 路径在 Blender 内与旧 VRM 节点逐帧行为对齐后执行",
    "nodes": [
        "springBoneVRMChainSetting",  # 弹簧骨-VRM链设置
        "springBoneVRM",              # 弹簧骨-VRM
        "springBoneVRM_CPP",          # 弹簧骨-VRM-CPP
        "springBoneBase",             # 弹簧骨（基础，需先迁移出新路径）
    ],
    "classes": [
        "_SpringBoneVRM",
        "_SpringBoneVRMCppBackend",
    ],
    "shared_class_methods_to_remove": {
        # _BonePhysics 是共享类（springBoneBase/keyframePoseBones 也用），不整删；
        # 只删这两个 VRM 专属方法。
        "_BonePhysics": [
            "flatten_vrm_spring_bone_chain_settings",
            "vrm_spring_bone_collision_profile",
        ],
    },
    "dangling_after_delete": [
        # 删除后需顺手清理的无害残留（非阻塞）。
        "OmniNode/NodeTree/OmniDebug.py: section 标签列表里的 'springBoneVRM' 字符串",
        "physicsMC2BoneCloth/bone_build.py: 注释里引用 flatten_vrm_spring_bone_chain_settings",
    ],
}


def spring_vrm_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(SPRING_VRM_SOLVER_DECLARATION),
        "legacy_discard_audit": [dict(item) for item in SPRING_VRM_LEGACY_DISCARD_AUDIT],
        "legacy_delete_checklist": dict(SPRING_VRM_LEGACY_DELETE_CHECKLIST),
    }
