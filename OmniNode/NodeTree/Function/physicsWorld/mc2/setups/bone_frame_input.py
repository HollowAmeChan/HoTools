"""Blender N3 world-pose adapter shared by BoneCloth and BoneSpring."""

from __future__ import annotations

import bpy
import numpy as np

from ..frame_state import MC2FrameInputSpec, make_mc2_frame_input
from ..names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ..specs import MC2TaskSpec
from ..topology import MC2TopologySpec, _thaw


_TRANSFORM_EPSILON = 1.0e-8


def _armature_from_source(source):
    if isinstance(source, dict):
        return source.get("armature")
    if isinstance(source, tuple) and len(source) == 2:
        return source[0]
    return None


def _live_armature(value) -> bool:
    return (
        isinstance(value, bpy.types.Object)
        and value.type == "ARMATURE"
        and value.data is not None
        and value.pose is not None
    )


def _validate_bone_armature_transform(armature) -> None:
    owner = armature
    while owner is not None:
        scale = tuple(float(value) for value in owner.scale)
        if any(abs(value) <= _TRANSFORM_EPSILON for value in scale):
            raise ValueError("MC2 Bone source transform chain cannot contain zero scale")
        if any(value < 0.0 for value in scale):
            raise ValueError(
                "MC2 Bone source does not support negative scale on the Armature or its parents"
            )
        owner = owner.parent

    linear = np.asarray(
        [[float(armature.matrix_world[row][column]) for column in range(3)] for row in range(3)],
        dtype=np.float64,
    )
    axis_lengths = np.linalg.norm(linear, axis=0)
    if np.any(axis_lengths <= _TRANSFORM_EPSILON):
        raise ValueError("MC2 Bone source world transform cannot contain zero scale")
    rotation = linear / axis_lengths[np.newaxis, :]
    if not np.allclose(
        rotation.T @ rotation,
        np.eye(3),
        rtol=1.0e-5,
        atol=1.0e-6,
    ) or np.linalg.det(rotation) <= 0.0:
        raise ValueError(
            "MC2 Bone source world transform must have positive scale and no shear"
        )


def build_mc2_bone_frame_input(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
    *,
    frame: int,
    generation: int,
) -> MC2FrameInputSpec:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if task.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        raise ValueError("bone frame input requires BoneCloth or BoneSpring")
    if topology.task_id != task.task_id or topology.setup_type != task.setup_type:
        raise ValueError("bone frame task/topology identity mismatch")

    positions = []
    rotations = []
    for source_topology in topology.sources:
        source_index = int(source_topology.source_index)
        armature = _armature_from_source(task.sources[source_index])
        if not _live_armature(armature):
            raise ValueError("bone frame source armature is unavailable")
        _validate_bone_armature_transform(armature)
        payload = _thaw(source_topology.payload)
        records = tuple(payload.get("bones") or ())
        if len(records) != source_topology.particle_count:
            raise ValueError("bone frame topology record count mismatch")
        pose_bones = armature.pose.bones
        matrix_world = armature.matrix_world
        for record in records:
            name = str(record.get("name") or "")
            pose_bone = pose_bones.get(name)
            if pose_bone is None:
                raise ValueError(f"bone frame pose is missing stable bone {name!r}")
            head = matrix_world @ pose_bone.head
            world_matrix = matrix_world @ pose_bone.matrix
            rotation = world_matrix.to_quaternion()
            rotation.normalize()
            positions.append((float(head.x), float(head.y), float(head.z)))
            rotations.append(
                (float(rotation.x), float(rotation.y), float(rotation.z), float(rotation.w))
            )

    if len(positions) != topology.particle_count:
        raise ValueError("bone frame particle count mismatch")
    return make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=generation,
        world_positions=np.asarray(positions, dtype=np.float32),
        world_rotations_xyzw=np.asarray(rotations, dtype=np.float32),
    )


__all__ = ["build_mc2_bone_frame_input"]
