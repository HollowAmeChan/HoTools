"""Blender N3 world-pose adapter shared by BoneCloth and BoneSpring."""

from __future__ import annotations

import bpy
import numpy as np

from ..frame_state import MC2FrameInputSpec, make_mc2_frame_input
from ..names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ..specs import MC2TaskSpec
from ..topology import MC2TopologySpec, _thaw


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
