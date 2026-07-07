"""VRM SpringBone 新物理世界重写的解算器声明。"""

from __future__ import annotations

from ..declarations import SPRING_VRM_SOLVER_DECLARATION


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
]


def spring_vrm_declaration_debug_dict() -> dict:
    return {
        "declaration": dict(SPRING_VRM_SOLVER_DECLARATION),
        "legacy_discard_audit": [dict(item) for item in SPRING_VRM_LEGACY_DISCARD_AUDIT],
    }
