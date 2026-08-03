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

    compact = np.zeros((topology.particle_count, 3), dtype=np.float64)
    counts = np.zeros((topology.particle_count,), dtype=np.int32)
    for raw_index, particle in enumerate(topology.endpoint_particles.reshape(-1)):
        compact[int(particle)] += raw_world[raw_index]
        counts[int(particle)] += 1
    compact /= counts[:, None]
    axis_scales = np.linalg.norm(world_array[:3, :3], axis=0)
    radius_scale = float(np.max(axis_scales))
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
    """以模拟 head 为平移，以 head->tail 方向吸附旋转并保留参考 roll/scale。"""

    import mathutils

    positions = np.asarray(world_positions, dtype=np.float64)
    if positions.shape != (topology.particle_count, 3) or not np.isfinite(positions).all():
        raise ValueError("Bone XPBD 输出 positions 与拓扑不匹配")
    result = {}
    for segment, source_matrix in zip(topology.segments, frame.source_pose_matrices):
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
