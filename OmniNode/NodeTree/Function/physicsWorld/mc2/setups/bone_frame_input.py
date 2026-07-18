"""Blender N3 world-pose adapter shared by BoneCloth and BoneSpring."""

from __future__ import annotations

import bpy
import mathutils
import numpy as np

from ...utils.math3d import decompose_signed_orthogonal_linear_f64
from ..center_state import MC2CenterFramePoseSpec
from ..frame_state import MC2FrameInputSpec, make_mc2_frame_input
from ..names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ..specs import MC2TaskSpec
from ..topology import MC2TopologySpec, thaw_mc2_topology_payload


_TRANSFORM_EPSILON = 1.0e-8
_WRITEBACK_MATCH_EPSILON = 1.0e-6
MC2_BONE_FRAME_STATE_KEY = "_mc2_bone_frame_state_v0"


def _matrix_matches(left, right, epsilon: float = _WRITEBACK_MATCH_EPSILON) -> bool:
    if left is None or right is None:
        return False
    try:
        return all(
            abs(float(left[row][column]) - float(right[row][column])) <= epsilon
            for row in range(4)
            for column in range(4)
        )
    except Exception:
        return False


def _mc2_bone_frame_state(world) -> dict:
    resources = world.backend_resources
    generation = int(getattr(world, "generation", 0) or 0)
    state = resources.get(MC2_BONE_FRAME_STATE_KEY)
    if not isinstance(state, dict) or state.get("generation") != generation:
        state = {"generation": generation, "bones": {}}
        resources[MC2_BONE_FRAME_STATE_KEY] = state
    return state


def clear_mc2_bone_frame_state(world) -> None:
    world.backend_resources.pop(MC2_BONE_FRAME_STATE_KEY, None)


def _resolve_mc2_bone_source_basis(world, armature_ptr: int, pose_bone):
    """Resolve the pre-physics basis at MC2's RestoreTransform/ReadTransform boundary."""
    bones = _mc2_bone_frame_state(world)["bones"]
    bone_key = (int(armature_ptr), str(pose_bone.name))
    current_basis = pose_bone.matrix_basis.copy()
    entry = bones.get(bone_key)
    if entry is None:
        bones[bone_key] = {
            "armature": pose_bone.id_data,
            "bone_name": str(pose_bone.name),
            "source_basis": current_basis,
            "expected_writeback_basis": None,
        }
        return None

    expected_basis = entry.get("expected_writeback_basis")
    if _matrix_matches(current_basis, expected_basis):
        source_basis = entry.get("source_basis")
        return source_basis.copy() if source_basis is not None else None

    # Blender animation/driver/user evaluation has replaced the old MC2 output.
    entry["source_basis"] = current_basis
    return None


def stage_mc2_bone_writeback_expectations(world, plans) -> None:
    """Stage MC2-owned output fingerprints for the next frame's input adapter."""
    bones = _mc2_bone_frame_state(world)["bones"]
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        armature = plan.get("armature")
        try:
            armature_ptr = int(armature.as_pointer())
        except Exception:
            continue
        planned_bones = {}
        for batch in plan.get("batches") or ():
            if not isinstance(batch, dict):
                continue
            records = tuple(batch.get("records") or ())
            matrix_bases = tuple(batch.get("matrix_bases") or ())
            for record, matrix_basis in zip(records, matrix_bases):
                if not isinstance(record, dict) or matrix_basis is None:
                    continue
                pose_bone = record.get("pose_bone")
                bone_name = str(record.get("bone_name") or "")
                if pose_bone is None or not bone_name:
                    continue
                location, rotation, scale = matrix_basis.decompose()
                if bool(getattr(pose_bone.bone, "use_connect", False)):
                    location = mathutils.Vector((0.0, 0.0, 0.0))
                planned_bones[bone_name] = (
                    pose_bone,
                    mathutils.Matrix.LocRotScale(location, rotation, scale),
                )

        for bone_name, (pose_bone, canonical_basis) in planned_bones.items():
            bone_key = (armature_ptr, bone_name)
            entry = bones.setdefault(bone_key, {
                "armature": armature,
                "bone_name": bone_name,
                "source_basis": pose_bone.matrix_basis.copy(),
                "expected_writeback_basis": None,
            })
            entry["expected_writeback_basis"] = canonical_basis.copy()


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
    world=None,
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
    resolved_pose_matrices = {}
    reconstructed_bones = set()
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
            payload = thaw_mc2_topology_payload(source_topology.payload)
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
            bone_key = (armature_key, name)
            parent = pose_bone.parent
            parent_key = (
                (armature_key, str(parent.name))
                if parent is not None
                else None
            )
            source_basis = (
                _resolve_mc2_bone_source_basis(world, armature_key, pose_bone)
                if world is not None
                else None
            )
            reconstruct = source_basis is not None or parent_key in reconstructed_bones
            if reconstruct:
                basis = source_basis if source_basis is not None else pose_bone.matrix_basis
                bone_rest = pose_bone.bone.matrix_local
                if parent is None:
                    pose_matrix = bone_rest @ basis
                else:
                    parent_matrix = resolved_pose_matrices.get(parent_key, parent.matrix)
                    parent_rest = parent.bone.matrix_local
                    pose_matrix = (
                        parent_matrix
                        @ parent_rest.inverted()
                        @ bone_rest
                        @ basis
                    )
                reconstructed_bones.add(bone_key)
            else:
                pose_matrix = pose_bone.matrix.copy()
            resolved_pose_matrices[bone_key] = pose_matrix
            head = matrix_world @ pose_matrix.translation
            pose_matrices.append(np.asarray(
                [
                    [float(pose_matrix[row][column]) for column in range(3)]
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


__all__ = [
    "MC2_BONE_FRAME_STATE_KEY",
    "build_mc2_bone_frame_input",
    "clear_mc2_bone_frame_state",
    "stage_mc2_bone_writeback_expectations",
]
