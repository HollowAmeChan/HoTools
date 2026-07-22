"""把 Bone setup 帧输入编译为统一 DomainV1 frame packet。"""

from __future__ import annotations

import numpy as np

from .domain_compile import MC2CompiledDomainV1
from .frame_compile import MC2PartitionFrameSnapshotV1
from .frame_compile import compile_mc2_domain_frame_packet
from .frame_state import MC2FrameInputSpec
from .names import MC2_SETUP_BONE_CLOTH, MC2_SETUP_BONE_SPRING
from .native import native_module
from .setups.bone_cloth.static_fragment import MC2BoneStaticFragmentV1


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


__all__ = ["compile_mc2_bone_product_frame"]
