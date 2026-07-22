"""Blender N3 world-pose adapter shared by BoneCloth and BoneSpring."""

from __future__ import annotations

from dataclasses import dataclass

import bpy
import mathutils
import numpy as np

from ...utils.math3d import decompose_signed_orthogonal_linear_f64
from ..center_state import MC2CenterFramePoseSpec
from ..frame_state import MC2FrameInputSpec, make_mc2_frame_input
from ..anchor import attach_mc2_task_anchor
from ..names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ..specs import MC2TaskSpec
from ..topology import MC2TopologySpec, thaw_mc2_topology_payload


_TRANSFORM_EPSILON = 1.0e-8
_WRITEBACK_MATCH_EPSILON = 1.0e-6
MC2_BONE_FRAME_STATE_KEY = "_mc2_bone_frame_state_v0"


@dataclass(frozen=True)
class _MC2BoneFrameIntentV1:
    partition_id: str
    setup_type: str
    sources: tuple[object, ...]
    anchor_owner: object


@dataclass(frozen=True)
class MC2BoneFrameStateStageV1:
    generation: int
    base_present: bool
    base_state: object
    staged_state: dict

    def validate(self, world) -> None:
        if int(getattr(world, "generation", 0) or 0) != self.generation:
            raise RuntimeError("Bone frame state stage belongs to another generation")
        resources = world.backend_resources
        if self.base_present:
            if resources.get(MC2_BONE_FRAME_STATE_KEY) is not self.base_state:
                raise RuntimeError("Bone frame state changed while capture was staged")
        elif MC2_BONE_FRAME_STATE_KEY in resources:
            raise RuntimeError("Bone frame state appeared while capture was staged")

    def commit(self, world) -> None:
        self.validate(world)
        world.backend_resources[MC2_BONE_FRAME_STATE_KEY] = self.staged_state


def _copy_state_value(value):
    copier = getattr(value, "copy", None)
    if callable(copier):
        try:
            return copier()
        except (ReferenceError, RuntimeError, TypeError):
            pass
    return value


def _clone_mc2_bone_frame_state(state, generation: int) -> dict:
    if not isinstance(state, dict) or state.get("generation") != generation:
        return {"generation": generation, "bones": {}}
    bones = {}
    for key, entry in dict(state.get("bones") or {}).items():
        if not isinstance(entry, dict):
            continue
        cloned = dict(entry)
        for name in ("source_basis", "expected_writeback_basis"):
            cloned[name] = _copy_state_value(entry.get(name))
        bones[key] = cloned
    return {"generation": generation, "bones": bones}


def _stage_mc2_bone_frame_state(world) -> MC2BoneFrameStateStageV1:
    resources = world.backend_resources
    generation = int(getattr(world, "generation", 0) or 0)
    base_present = MC2_BONE_FRAME_STATE_KEY in resources
    base_state = resources.get(MC2_BONE_FRAME_STATE_KEY)
    return MC2BoneFrameStateStageV1(
        generation=generation,
        base_present=base_present,
        base_state=base_state,
        staged_state=_clone_mc2_bone_frame_state(base_state, generation),
    )


def _task_frame_intent(task: MC2TaskSpec) -> _MC2BoneFrameIntentV1:
    if not isinstance(task, MC2TaskSpec):
        raise TypeError("task must be MC2TaskSpec")
    return _MC2BoneFrameIntentV1(
        partition_id=task.task_id,
        setup_type=task.setup_type,
        sources=task.sources,
        anchor_owner=task,
    )


def _partition_frame_intent(partition) -> _MC2BoneFrameIntentV1:
    from ..partition_specs import MC2ResolvedPartitionSpec
    from ..product_bone_authoring import MC2BonePartitionSourceV1

    if not isinstance(partition, MC2ResolvedPartitionSpec):
        raise TypeError("partition must be MC2ResolvedPartitionSpec")
    if not isinstance(partition.source, MC2BonePartitionSourceV1):
        raise TypeError("Bone product partition source is invalid")
    return _MC2BoneFrameIntentV1(
        partition_id=partition.stable_id,
        setup_type=partition.setup_type,
        sources=partition.source.task_sources,
        anchor_owner=partition,
    )


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


def prepare_mc2_bone_writeback_expectations(
    world,
    plans,
) -> MC2BoneFrameStateStageV1:
    """在隔离副本上准备下一帧反馈指纹，由结果事务决定是否提交。"""

    stage = _stage_mc2_bone_frame_state(world)
    stage.validate(world)
    resources = world.backend_resources
    resources[MC2_BONE_FRAME_STATE_KEY] = stage.staged_state
    try:
        stage_mc2_bone_writeback_expectations(world, plans)
    finally:
        if resources.get(MC2_BONE_FRAME_STATE_KEY) is not stage.staged_state:
            raise RuntimeError("Bone frame state changed while writeback was staged")
        if stage.base_present:
            resources[MC2_BONE_FRAME_STATE_KEY] = stage.base_state
        else:
            resources.pop(MC2_BONE_FRAME_STATE_KEY, None)
    return stage


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
    return position, rotation_xyzw, signed_scale, np.ascontiguousarray(
        linear,
        dtype=np.float32,
    )


def build_mc2_bone_frame_input(
    task: MC2TaskSpec,
    topology: MC2TopologySpec,
    *,
    frame: int,
    generation: int,
    world=None,
) -> MC2FrameInputSpec:
    return _build_mc2_bone_frame_input(
        _task_frame_intent(task),
        topology,
        frame=frame,
        generation=generation,
        world=world,
    )


def build_mc2_bone_partition_frame_input(
    partition,
    topology: MC2TopologySpec,
    *,
    frame: int,
    generation: int,
    world=None,
) -> MC2FrameInputSpec:
    """读取 resolved Bone partition，且不创建 MC2TaskSpec 或 V0 context。"""

    return _build_mc2_bone_frame_input(
        _partition_frame_intent(partition),
        topology,
        frame=frame,
        generation=generation,
        world=world,
    )


def _build_mc2_bone_frame_input(
    intent: _MC2BoneFrameIntentV1,
    topology: MC2TopologySpec,
    *,
    frame: int,
    generation: int,
    world=None,
) -> MC2FrameInputSpec:
    if not isinstance(topology, MC2TopologySpec):
        raise TypeError("topology must be MC2TopologySpec")
    if intent.setup_type not in (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING):
        raise ValueError("bone frame input requires BoneCloth or BoneSpring")
    if (
        topology.task_id != intent.partition_id
        or topology.setup_type != intent.setup_type
    ):
        raise ValueError("bone frame task/topology identity mismatch")

    positions = []
    pose_matrices = []
    component_pose = None
    component_world_linear = None
    component_poses = {}
    resolved_pose_matrices = {}
    reconstructed_bones = set()
    for source_topology in topology.sources:
        source_index = int(source_topology.source_index)
        armature = _armature_from_source(intent.sources[source_index])
        if not _live_armature(armature):
            raise ValueError("bone frame source armature is unavailable")
        armature_key = int(armature.as_pointer())
        component_values = component_poses.get(armature_key)
        if component_values is None:
            component_values = _bone_armature_component_pose(armature)
            component_poses[armature_key] = component_values
        (
            component_position,
            component_rotation_xyzw,
            component_scale,
            source_world_linear,
        ) = component_values
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
        if component_world_linear is not None and not np.array_equal(
            component_world_linear,
            source_world_linear,
        ):
            raise ValueError("bone frame sources do not share one component linear transform")
        component_pose = source_component_pose
        component_world_linear = source_world_linear
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
    if component_pose is not None:
        depsgraph = None
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
        except (AttributeError, RuntimeError):
            pass
        component_pose = attach_mc2_task_anchor(
            component_pose,
            intent.anchor_owner,
            depsgraph=depsgraph,
        )
    return make_mc2_frame_input(
        task_id=intent.partition_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=generation,
        world_positions=np.asarray(positions, dtype=np.float32),
        world_rotations_xyzw=None,
        raw_pose_matrices=np.asarray(pose_matrices, dtype=np.float32),
        source_world_linear=component_world_linear,
        center_frame_pose=component_pose,
        negative_scale_sign=(
            -1.0
            if component_pose is not None
            and any(value < 0.0 for value in component_pose.component_world_scale)
            else 1.0
        ),
    )


def capture_mc2_bone_product_frame_inputs(
    world,
    static_inputs,
    *,
    frame: int,
    generation: int,
) -> tuple[tuple[MC2FrameInputSpec, ...], MC2BoneFrameStateStageV1]:
    """在隔离反馈副本上采集所有 Bone partition，等待 frame publish 后提交。"""

    rows = tuple(static_inputs)
    if not rows:
        raise ValueError("Bone product frame capture requires static inputs")
    stage = _stage_mc2_bone_frame_state(world)
    if int(generation) != stage.generation:
        raise ValueError("Bone product frame generation does not match Physics World")
    stage.validate(world)
    resources = world.backend_resources
    resources[MC2_BONE_FRAME_STATE_KEY] = stage.staged_state
    try:
        inputs = tuple(
            build_mc2_bone_partition_frame_input(
                row.partition,
                row.topology,
                frame=int(frame),
                generation=int(generation),
                world=world,
            )
            for row in rows
        )
    finally:
        if resources.get(MC2_BONE_FRAME_STATE_KEY) is not stage.staged_state:
            raise RuntimeError("Bone frame state changed during isolated capture")
        if stage.base_present:
            resources[MC2_BONE_FRAME_STATE_KEY] = stage.base_state
        else:
            resources.pop(MC2_BONE_FRAME_STATE_KEY, None)
    return inputs, stage


__all__ = [
    "MC2_BONE_FRAME_STATE_KEY",
    "MC2BoneFrameStateStageV1",
    "build_mc2_bone_frame_input",
    "build_mc2_bone_partition_frame_input",
    "capture_mc2_bone_product_frame_inputs",
    "clear_mc2_bone_frame_state",
    "prepare_mc2_bone_writeback_expectations",
    "stage_mc2_bone_writeback_expectations",
]
