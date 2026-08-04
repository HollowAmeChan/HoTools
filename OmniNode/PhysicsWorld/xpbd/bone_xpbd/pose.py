"""Bone XPBD 逐帧端点采集与端点到 PoseBone 姿态重建。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from .specs import BoneXpbdTaskSpec
from .topology import BoneXpbdTopology


_EPSILON = 1.0e-8


def _matrix_array(matrix) -> np.ndarray:
    result = np.asarray(
        [[float(matrix[row][column]) for column in range(4)] for row in range(4)],
        dtype=np.float64,
    )
    if result.shape != (4, 4) or not np.isfinite(result).all():
        raise ValueError("Bone XPBD matrix 必须是有限 4x4")
    return result


def _digest(arrays, extra=()) -> str:
    digest = hashlib.sha256(b"bone_xpbd_pose_frame_v1")
    for value in extra:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    for values in arrays:
        array = np.ascontiguousarray(values)
        digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class BoneXpbdPoseFrame:
    armature: object
    matrix_world: object
    inverse_matrix_world: object
    source_pose_matrices: tuple[object, ...]
    world_positions: np.ndarray
    world_collision_radii: np.ndarray
    signature: str

    def debug_dict(self) -> dict:
        return {
            "schema": "bone_xpbd_pose_frame_v1",
            "particle_count": int(self.world_positions.shape[0]),
            "signature": self.signature,
        }


def build_bone_xpbd_pose_frame(
    topology: BoneXpbdTopology,
    spec: BoneXpbdTaskSpec,
    logical_pose_matrices: dict[tuple[int, str], object] | None = None,
) -> BoneXpbdPoseFrame:
    if not isinstance(topology, BoneXpbdTopology):
        raise TypeError("build_bone_xpbd_pose_frame 需要 BoneXpbdTopology")
    import mathutils

    armature = spec.armature
    matrix_world = armature.matrix_world.copy()
    world_array = _matrix_array(matrix_world)
    determinant = float(np.linalg.det(world_array[:3, :3]))
    if not math.isfinite(determinant) or abs(determinant) <= _EPSILON:
        raise ValueError("Bone XPBD Armature matrix_world 不可逆")
    inverse_world = matrix_world.inverted()
    pose_bones = armature.pose.bones
    logical = logical_pose_matrices or {}
    if len(topology.segment_pins) != len(topology.segments):
        raise ValueError("Bone XPBD 骨级 Pin 标记与拓扑段数量不一致")
    raw_world = np.empty((len(topology.segments) * 2, 3), dtype=np.float64)
    source_matrices = []
    for index, segment in enumerate(topology.segments):
        pose_bone = pose_bones.get(segment.bone_name)
        if pose_bone is None:
            raise ValueError(f"Bone XPBD PoseBone 已失效: {segment.bone_name!r}")
        pose_matrix = logical.get(
            (topology.armature_ptr, segment.bone_name),
            pose_bone.matrix,
        ).copy()
        source_matrices.append(pose_matrix)
        head = pose_matrix.translation
        bone_length = float(getattr(getattr(pose_bone, "bone", None), "length", 0.0))
        if not math.isfinite(bone_length) or bone_length <= _EPSILON:
            bone_length = float(segment.rest_length)
        tail = pose_matrix @ mathutils.Vector((0.0, bone_length, 0.0))
        head_world = matrix_world @ head
        tail_world = matrix_world @ tail
        raw_world[index * 2] = tuple(float(value) for value in head_world)
        raw_world[index * 2 + 1] = tuple(float(value) for value in tail_world)

    axis_scales = np.linalg.norm(world_array[:3, :3], axis=0)
    radius_scale = float(np.max(axis_scales))
    coordinate_magnitude = max(1.0, float(np.max(np.abs(raw_world), initial=0.0)))
    conflict_tolerance = max(
        1.0e-6,
        4.0 * float(np.finfo(np.float32).eps) * coordinate_magnitude,
    )
    contributors = [[] for _index in range(topology.particle_count)]
    for raw_index, particle in enumerate(topology.endpoint_particles.reshape(-1)):
        contributors[int(particle)].append(raw_index)
    compact = np.empty((topology.particle_count, 3), dtype=np.float64)
    for particle, raw_indices in enumerate(contributors):
        pinned_indices = [
            raw_index
            for raw_index in raw_indices
            if bool(topology.segment_pins[raw_index // 2])
        ]
        selected_indices = pinned_indices or raw_indices
        selected_positions = raw_world[selected_indices]
        target = np.mean(selected_positions, axis=0)
        if pinned_indices:
            deviations = np.linalg.norm(selected_positions - target, axis=1)
            if float(np.max(deviations, initial=0.0)) > conflict_tolerance:
                labels = ", ".join(
                    f"{topology.segments[index // 2].bone_name}."
                    f"{'head' if index % 2 == 0 else 'tail'}"
                    for index in pinned_indices
                )
                raise ValueError(
                    "Bone XPBD 多个 Pin 端点为同一共享粒子提供了互相冲突的世界目标: "
                    f"particle={particle}, endpoints=[{labels}]"
                )
        # 只要共享粒子含 Pin 贡献，普通 Move 端点就不能稀释硬锚目标。
        compact[particle] = target
    radii = np.asarray(topology.local_collision_radii, dtype=np.float64) * radius_scale
    compact = np.ascontiguousarray(compact, dtype=np.float32)
    radii = np.ascontiguousarray(radii, dtype=np.float32)
    compact.setflags(write=False)
    radii.setflags(write=False)
    return BoneXpbdPoseFrame(
        armature,
        matrix_world,
        inverse_world,
        tuple(source_matrices),
        compact,
        radii,
        _digest((world_array, compact, radii), (topology.static_signature,)),
    )


def _aligned_rotation(source_matrix, source_axis, target_axis):
    import mathutils

    source = source_axis.normalized()
    target = target_axis.normalized()
    dot = max(-1.0, min(1.0, float(source.dot(target))))
    if dot <= -1.0 + 1.0e-7:
        axis = source_matrix.to_quaternion() @ mathutils.Vector((1.0, 0.0, 0.0))
        if axis.length <= _EPSILON:
            axis = mathutils.Vector((1.0, 0.0, 0.0))
        else:
            axis.normalize()
        swing = mathutils.Quaternion(axis, math.pi)
    else:
        swing = source.rotation_difference(target)
    result = swing @ source_matrix.to_quaternion()
    result.normalize()
    return result


def target_pose_matrices_from_particles(
    topology: BoneXpbdTopology,
    frame: BoneXpbdPoseFrame,
    world_positions,
    *,
    tail_follow: bool,
) -> dict[str, object]:
    """先锁定 Pin 骨最终 Pose，再从粒子线段重建其余骨骼。"""

    import mathutils

    positions = np.asarray(world_positions, dtype=np.float64)
    if positions.shape != (topology.particle_count, 3) or not np.isfinite(positions).all():
        raise ValueError("Bone XPBD 输出 positions 与拓扑不匹配")
    if len(topology.segment_pins) != len(topology.segments):
        raise ValueError("Bone XPBD 骨级 Pin 标记与拓扑段数量不一致")

    result = {
        segment.bone_name: source_matrix.copy()
        for segment, source_matrix, pinned in zip(
            topology.segments,
            frame.source_pose_matrices,
            topology.segment_pins,
        )
        if bool(pinned)
    }
    for segment, source_matrix, pinned in zip(
        topology.segments,
        frame.source_pose_matrices,
        topology.segment_pins,
    ):
        if bool(pinned):
            # Pin 的语义是完整最终 Pose 硬目标。不能再用 head->tail 线段
            # 反推旋转，否则父级剧烈运动时会丢失 roll 并产生写回抖动。
            continue
        head_world = mathutils.Vector(positions[segment.head_particle])
        tail_world = mathutils.Vector(positions[segment.tail_particle])
        head = frame.inverse_matrix_world @ head_world
        tail = frame.inverse_matrix_world @ tail_world
        source_head = source_matrix.translation
        source_axis = (source_matrix.to_3x3() @ mathutils.Vector((0.0, 1.0, 0.0)))
        target_axis = tail - head
        if (
            not tail_follow
            or source_axis.length <= _EPSILON
            or target_axis.length <= _EPSILON
        ):
            rotation = source_matrix.to_quaternion()
        else:
            rotation = _aligned_rotation(source_matrix, source_axis, target_axis)
        scale = source_matrix.to_scale()
        if min(abs(float(value)) for value in scale) <= _EPSILON:
            raise ValueError(f"Bone XPBD 骨骼 {segment.bone_name!r} 含零 scale")
        result[segment.bone_name] = mathutils.Matrix.LocRotScale(
            head,
            rotation,
            scale,
        )
    return result


__all__ = [
    "BoneXpbdPoseFrame",
    "build_bone_xpbd_pose_frame",
    "target_pose_matrices_from_particles",
]
