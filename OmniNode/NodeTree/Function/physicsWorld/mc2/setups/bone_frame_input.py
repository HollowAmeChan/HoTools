"""Blender N3 world-pose adapter shared by BoneCloth and BoneSpring."""

from __future__ import annotations

import bpy
import numpy as np

from ...utils.math3d import decompose_signed_orthogonal_linear_f64
from ..center_state import MC2CenterFramePoseSpec
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


def _bone_armature_component_pose(armature):
    local_scale = tuple(float(value) for value in armature.scale)
    if any(abs(value) <= _TRANSFORM_EPSILON for value in local_scale):
        raise ValueError("MC2 Bone source transform cannot contain zero scale")
    owner = armature.parent
    while owner is not None:
        scale = tuple(float(value) for value in owner.scale)
        if any(abs(value) <= _TRANSFORM_EPSILON for value in scale):
            raise ValueError("MC2 Bone source transform chain cannot contain zero scale")
        if any(value < 0.0 for value in scale):
            raise ValueError(
                "MC2 Bone source does not support negative scale inherited from a parent"
            )
        owner = owner.parent

    matrix_world = armature.matrix_world
    linear = np.asarray(
        [[float(matrix_world[row][column]) for column in range(3)] for row in range(3)],
        dtype=np.float64,
    )
    rotation_xyzw, signed_scale = decompose_signed_orthogonal_linear_f64(
        linear,
        (-1.0 if value < 0.0 else 1.0 for value in local_scale),
        name="MC2 Bone source world transform",
        zero_epsilon=_TRANSFORM_EPSILON,
    )
    position = tuple(float(matrix_world[row][3]) for row in range(3))
    return position, rotation_xyzw, signed_scale


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
    pose_matrices = []
    component_pose = None
    component_poses = {}
    for source_topology in topology.sources:
        source_index = int(source_topology.source_index)
        armature = _armature_from_source(task.sources[source_index])
        if not _live_armature(armature):
            raise ValueError("bone frame source armature is unavailable")
        armature_key = int(armature.as_pointer())
        component_values = component_poses.get(armature_key)
        if component_values is None:
            component_values = _bone_armature_component_pose(armature)
            component_poses[armature_key] = component_values
        component_position, component_rotation_xyzw, component_scale = component_values
        source_component_pose = MC2CenterFramePoseSpec(
            frame=int(frame),
            generation=int(generation),
            component_identity=f"object:{int(armature.as_pointer())}",
            component_world_position=component_position,
            component_world_rotation_xyzw=component_rotation_xyzw,
            component_world_scale=component_scale,
        )
        if component_pose is not None and component_pose != source_component_pose:
            raise ValueError("bone frame sources do not share one component pose")
        component_pose = source_component_pose
        names = source_topology.bone_names
        if not names:
            payload = _thaw(source_topology.payload)
            names = tuple(
                str(record.get("name") or "")
                for record in payload.get("bones", ())
            )
        if len(names) != source_topology.particle_count:
            raise ValueError("bone frame topology record count mismatch")
        pose_bones = armature.pose.bones
        matrix_world = armature.matrix_world
        for name in names:
            pose_bone = pose_bones.get(name)
            if pose_bone is None:
                raise ValueError(f"bone frame pose is missing stable bone {name!r}")
            head = matrix_world @ pose_bone.head
            pose_matrices.append(np.asarray(
                [
                    [float(pose_bone.matrix[row][column]) for column in range(3)]
                    for row in range(3)
                ],
                dtype=np.float32,
            ))
            positions.append((float(head.x), float(head.y), float(head.z)))

    if len(positions) != topology.particle_count:
        raise ValueError("bone frame particle count mismatch")
    return make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=generation,
        world_positions=np.asarray(positions, dtype=np.float32),
        world_rotations_xyzw=None,
        raw_pose_matrices=np.asarray(pose_matrices, dtype=np.float32),
        center_frame_pose=component_pose,
        negative_scale_sign=(
            -1.0
            if component_pose is not None
            and any(value < 0.0 for value in component_pose.component_world_scale)
            else 1.0
        ),
    )


__all__ = ["build_mc2_bone_frame_input"]
