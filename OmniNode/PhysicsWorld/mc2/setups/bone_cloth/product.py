"""BoneCloth/BoneSpring setup 的 product collect 与 frame hooks。"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain_collect import MC2DomainDraftV1, build_mc2_domain_draft
from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...partition_specs import MC2PartitionCollectorPlan, MC2ResolvedPartitionSpec
from ...topology import (
    MC2BoneRawSnapshot,
    MC2StaticInputFingerprint,
    MC2TopologySpec,
    build_mc2_partition_topology_spec,
    prepare_static_inputs_for_partition,
)


_BONE_SETUP_TYPES = (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)


def _armature_identity(partition: MC2ResolvedPartitionSpec) -> tuple[object, int, int]:
    armature = getattr(partition.source, "armature", None)
    pointer = getattr(armature, "as_pointer", None)
    data_pointer = getattr(getattr(armature, "data", None), "as_pointer", None)
    try:
        owner = int(pointer()) if callable(pointer) else 0
        data = int(data_pointer()) if callable(data_pointer) else 0
    except (ReferenceError, RuntimeError) as exc:
        raise ValueError("Bone product Armature target is no longer live") from exc
    if getattr(armature, "type", None) != "ARMATURE" or owner <= 0 or data <= 0:
        raise ValueError("Bone product Armature target identity is invalid")
    return armature, owner, data


@dataclass(frozen=True)
class MC2BoneProductStaticInputV1:
    partition: MC2ResolvedPartitionSpec
    fingerprint: MC2StaticInputFingerprint
    topology: MC2TopologySpec
    raw_snapshots: tuple[MC2BoneRawSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.partition, MC2ResolvedPartitionSpec):
            raise TypeError("partition must be MC2ResolvedPartitionSpec")
        if self.partition.setup_type not in _BONE_SETUP_TYPES:
            raise ValueError("Bone static input setup type is invalid")
        if not isinstance(self.fingerprint, MC2StaticInputFingerprint):
            raise TypeError("fingerprint must be MC2StaticInputFingerprint")
        if not isinstance(self.topology, MC2TopologySpec):
            raise TypeError("topology must be MC2TopologySpec")
        if (
            self.topology.setup_type != self.partition.setup_type
            or self.topology.task_id != self.partition.stable_id
        ):
            raise ValueError("Bone static input topology identity does not match partition")
        if not self.raw_snapshots or any(
            not isinstance(value, MC2BoneRawSnapshot)
            for value in self.raw_snapshots
        ):
            raise TypeError("raw_snapshots must contain Bone raw snapshots")
        if any(not value.resolved for value in self.raw_snapshots):
            raise ValueError("Bone product static source did not resolve")
        _armature_identity(self.partition)

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_bone_product_static_input_v1",
            "partition_id": self.partition.stable_id,
            "setup_type": self.partition.setup_type,
            "fingerprint": self.fingerprint.debug_dict(),
            "topology_signature": self.topology.topology_signature,
            "source_count": len(self.raw_snapshots),
            "particle_count": self.topology.particle_count,
        }


@dataclass(frozen=True)
class MC2BoneProductCollectionV1:
    draft: MC2DomainDraftV1
    static_inputs: tuple[MC2BoneProductStaticInputV1, ...]
    armature: object
    armature_pointer: int
    armature_data_pointer: int

    def __post_init__(self) -> None:
        if not isinstance(self.draft, MC2DomainDraftV1):
            raise TypeError("draft must be MC2DomainDraftV1")
        if self.draft.setup_type not in _BONE_SETUP_TYPES:
            raise ValueError("Bone product collection setup type is invalid")
        if not self.static_inputs or any(
            not isinstance(value, MC2BoneProductStaticInputV1)
            for value in self.static_inputs
        ):
            raise TypeError("static_inputs must contain Bone product static inputs")
        if tuple(value.partition.stable_id for value in self.static_inputs) != (
            self.draft.partition_ids
        ):
            raise ValueError("Bone product static inputs must follow draft order")
        if any(value.partition.setup_type != self.draft.setup_type for value in self.static_inputs):
            raise ValueError("Bone product static input setup types must match draft")
        if self.armature_pointer <= 0 or self.armature_data_pointer <= 0:
            raise ValueError("Bone product collection target identity is invalid")
        for value in self.static_inputs:
            armature, owner, data = _armature_identity(value.partition)
            if (
                armature is not self.armature
                or owner != self.armature_pointer
                or data != self.armature_data_pointer
            ):
                raise ValueError("Bone product collection must target one Armature")

    @property
    def world_gravity_directions(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(
            tuple(float(component) for component in partition.profile.gravity_direction)
            for partition in self.draft.partitions
        )

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_bone_product_collection_v1",
            "setup_type": self.draft.setup_type,
            "partition_ids": list(self.draft.partition_ids),
            "armature_pointer": self.armature_pointer,
            "armature_data_pointer": self.armature_data_pointer,
            "draft": self.draft.debug_dict(),
            "static_inputs": [value.debug_dict() for value in self.static_inputs],
        }


def validate_mc2_bone_product_targets(collection: MC2BoneProductCollectionV1) -> None:
    if not isinstance(collection, MC2BoneProductCollectionV1):
        raise TypeError("collection must be MC2BoneProductCollectionV1")
    pose_bones = getattr(getattr(collection.armature, "pose", None), "bones", None)
    if pose_bones is None:
        raise ValueError("Bone product Armature has no pose bones")
    seen = set()
    for static_input in collection.static_inputs:
        armature, owner, data = _armature_identity(static_input.partition)
        if (
            armature is not collection.armature
            or owner != collection.armature_pointer
            or data != collection.armature_data_pointer
        ):
            raise ValueError("Bone product Armature identity changed")
        for snapshot in static_input.raw_snapshots:
            for name in snapshot.names:
                if name in seen:
                    raise ValueError(f"Bone product partitions overlap on bone {name!r}")
                if pose_bones.get(name) is None:
                    raise ValueError(f"Bone product target is missing stable bone {name!r}")
                seen.add(name)


def collect_mc2_bone_product_plan(
    world,
    plan: MC2PartitionCollectorPlan,
) -> MC2BoneProductCollectionV1:
    """一次读取显式 Bone plan，返回无 owner 状态的 whole-domain collection。"""

    del world
    if not isinstance(plan, MC2PartitionCollectorPlan):
        raise TypeError("plan must be MC2PartitionCollectorPlan")
    if plan.setup_type not in _BONE_SETUP_TYPES:
        raise ValueError("Bone product collector plan setup type mismatch")
    partitions = tuple(plan.active_partitions)
    if not partitions:
        raise ValueError("MC2 Bone product collector has no active partitions")
    rows = []
    target = None
    for partition in partitions:
        current_target = _armature_identity(partition)
        if target is None:
            target = current_target
        elif (
            current_target[0] is not target[0]
            or current_target[1:] != target[1:]
        ):
            raise ValueError("Bone product collector cannot silently split Armatures")
        fingerprint, raw_snapshots = prepare_static_inputs_for_partition(partition)
        snapshots = tuple(raw_snapshots)
        if not snapshots or any(
            not isinstance(value, MC2BoneRawSnapshot) or not value.resolved
            for value in snapshots
        ):
            raise ValueError(
                f"Bone product source observation did not resolve: {partition.stable_id}"
            )
        topology = build_mc2_partition_topology_spec(
            partition,
            static_input_fingerprint=fingerprint,
            static_input_snapshots=snapshots,
        )
        rows.append(MC2BoneProductStaticInputV1(
            partition=partition,
            fingerprint=fingerprint,
            topology=topology,
            raw_snapshots=snapshots,
        ))
    armature, owner, data = target
    collection = MC2BoneProductCollectionV1(
        draft=build_mc2_domain_draft(plan),
        static_inputs=tuple(rows),
        armature=armature,
        armature_pointer=owner,
        armature_data_pointer=data,
    )
    validate_mc2_bone_product_targets(collection)
    return collection


import numpy as np

from ...domain_compile import MC2CompiledDomainV1
from ...frame_compile import MC2PartitionFrameSnapshotV1
from ...frame_compile import compile_mc2_domain_frame_packet
from ...frame_state import MC2FrameInputSpec
from ...names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from ...native import native_module
from .static_fragment import MC2BoneStaticFragmentV1


_BONE_SETUP_TYPES = (MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING)


def _per_partition(values, defaults, count: int, name: str) -> tuple:
    result = tuple(defaults if values is None else values)
    if len(result) != count:
        raise ValueError(f"{name} must match Bone partition count")
    return result


def compile_mc2_bone_product_frame(
    compiled: MC2CompiledDomainV1,
    frame_inputs,
    *,
    partition_frame_flags=None,
    velocity_weights=None,
    gravity_ratios=None,
):
    """一次验证并编译全部 Bone partition，不接触 owner 或场景写回。"""

    if not isinstance(compiled, MC2CompiledDomainV1):
        raise TypeError("compiled must be MC2CompiledDomainV1")
    if compiled.program.setup_type not in _BONE_SETUP_TYPES:
        raise ValueError("Bone product frame requires a Bone compiled domain")
    inputs = tuple(frame_inputs)
    count = compiled.program.partition_count
    if len(inputs) != count or any(
        not isinstance(value, MC2FrameInputSpec) for value in inputs
    ):
        raise TypeError("frame_inputs must contain one MC2FrameInputSpec per partition")
    if tuple(value.task_id for value in inputs) != compiled.program.partition_ids:
        raise ValueError("Bone frame inputs must follow compiled partition order")
    flags = _per_partition(partition_frame_flags, (0,) * count, count, "flags")
    velocities = _per_partition(
        velocity_weights,
        tuple(value.velocity_weight for value in inputs),
        count,
        "velocity_weights",
    )
    gravities = _per_partition(
        gravity_ratios,
        tuple(value.gravity_ratio for value in inputs),
        count,
        "gravity_ratios",
    )

    snapshots = []
    for fragment, frame_input, flags_value, velocity, gravity in zip(
        compiled.fragments,
        inputs,
        flags,
        velocities,
        gravities,
    ):
        if not isinstance(fragment, MC2BoneStaticFragmentV1):
            raise TypeError("Bone compiled domain contains a non-Bone fragment")
        if frame_input.topology_signature != fragment.topology.topology_signature:
            raise ValueError(
                f"Bone frame topology is stale for {frame_input.task_id}"
            )
        if frame_input.particle_count != fragment.final_proxy.vertex_count:
            raise ValueError(
                f"Bone frame particle count is stale for {frame_input.task_id}"
            )
        if frame_input.raw_pose_matrices is None:
            raise ValueError("Bone product frame requires raw pose matrices")
        if frame_input.source_world_linear is None:
            raise ValueError("Bone product frame requires source_world_linear")
        center = frame_input.center_frame_pose
        if center is None:
            raise ValueError("Bone product frame requires a Center component pose")
        rotations = np.empty((frame_input.particle_count, 4), dtype=np.float32)
        native_module().mc2_bone_frame_orientations_v1(
            frame_input.raw_pose_matrices,
            np.ascontiguousarray(
                center.component_world_rotation_xyzw,
                dtype=np.float32,
            ),
            fragment.vertex_to_transform_rotations,
            rotations,
        )
        normals = np.zeros_like(frame_input.world_positions, dtype=np.float32)
        snapshots.append(MC2PartitionFrameSnapshotV1(
            partition_id=frame_input.task_id,
            frame=frame_input.frame,
            generation=frame_input.generation,
            animated_base_world_positions=frame_input.world_positions,
            animated_base_world_rotations=rotations,
            animated_base_world_normals=normals,
            partition_world_position=center.component_world_position,
            partition_world_rotation=center.component_world_rotation_xyzw,
            partition_world_scale=center.component_world_scale,
            partition_world_linear=frame_input.source_world_linear,
            anchor_world_position=center.anchor_world_position,
            anchor_world_rotation=center.anchor_world_rotation_xyzw,
            anchor_present=int(bool(center.anchor_identity)),
            partition_frame_flags=int(flags_value),
            velocity_weight=float(velocity),
            gravity_ratio=float(gravity),
        ))
    packet = compile_mc2_domain_frame_packet(compiled.program, snapshots)
    return packet, tuple(snapshots)

__all__ = [
    "MC2BoneProductCollectionV1",
    "MC2BoneProductStaticInputV1",
    "collect_mc2_bone_product_plan",
    "validate_mc2_bone_product_targets",
    "compile_mc2_bone_product_frame",
]
