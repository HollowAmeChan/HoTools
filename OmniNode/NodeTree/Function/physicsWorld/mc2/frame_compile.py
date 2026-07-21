"""Pure frame snapshot validation and logical-domain packet packing."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .domain_ir import MC2CompiledDomainProgramV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import make_mc2_domain_frame_packet


def _readonly(values, dtype, shape, name):
    array = np.ascontiguousarray(values, dtype=dtype)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite values")
    array = np.array(array, dtype=dtype, order="C", copy=True)
    array.flags.writeable = False
    return array


@dataclass(frozen=True)
class MC2PartitionFrameSnapshotV1:
    partition_id: str
    frame: int
    generation: int
    animated_base_world_positions: np.ndarray
    animated_base_world_rotations: np.ndarray
    animated_base_world_normals: np.ndarray
    partition_world_position: tuple[float, float, float]
    partition_world_rotation: tuple[float, float, float, float]
    partition_world_scale: tuple[float, float, float]
    partition_world_linear: np.ndarray
    anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_world_rotation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    anchor_present: int = 0
    partition_frame_flags: int = 0
    velocity_weight: float = 1.0
    gravity_ratio: float = 1.0

    def __post_init__(self) -> None:
        partition_id = str(self.partition_id or "").strip()
        if not partition_id:
            raise ValueError("partition_id cannot be empty")
        object.__setattr__(self, "partition_id", partition_id)
        if type(self.frame) is not int or self.frame < 0:
            raise ValueError("frame must be a non-negative integer")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        positions = np.asarray(self.animated_base_world_positions)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("animated_base_world_positions must be [N,3]")
        positions = _readonly(
            positions, np.float32, positions.shape, "animated_base_world_positions"
        )
        rotations = _readonly(
            self.animated_base_world_rotations,
            np.float32,
            (len(positions), 4),
            "animated_base_world_rotations",
        )
        if not np.allclose(
            np.linalg.norm(rotations, axis=1),
            1.0,
            rtol=1.0e-5,
            atol=1.0e-6,
        ):
            raise ValueError("animated_base_world_rotations must be unit quaternions")
        normals = _readonly(
            self.animated_base_world_normals,
            np.float32,
            positions.shape,
            "animated_base_world_normals",
        )
        linear = _readonly(
            self.partition_world_linear,
            np.float32,
            (3, 3),
            "partition_world_linear",
        )
        if abs(float(np.linalg.det(linear))) <= 1.0e-12:
            raise ValueError("partition_world_linear must be invertible")
        for value, name, size in (
            (self.partition_world_position, "partition_world_position", 3),
            (self.partition_world_rotation, "partition_world_rotation", 4),
            (self.partition_world_scale, "partition_world_scale", 3),
            (self.anchor_world_position, "anchor_world_position", 3),
            (self.anchor_world_rotation, "anchor_world_rotation", 4),
        ):
            array = np.asarray(value, dtype=np.float64)
            if array.shape != (size,) or not np.isfinite(array).all():
                raise ValueError(f"{name} must be finite float[{size}]")
        rotation = np.asarray(self.partition_world_rotation, dtype=np.float64)
        anchor_rotation = np.asarray(self.anchor_world_rotation, dtype=np.float64)
        if not np.isclose(np.linalg.norm(rotation), 1.0, rtol=1.0e-5, atol=1.0e-6):
            raise ValueError("partition_world_rotation must be a unit quaternion")
        if not np.isclose(np.linalg.norm(anchor_rotation), 1.0, rtol=1.0e-5, atol=1.0e-6):
            raise ValueError("anchor_world_rotation must be a unit quaternion")
        if any(abs(float(value)) <= 1.0e-12 for value in self.partition_world_scale):
            raise ValueError("partition_world_scale cannot contain zero")
        if type(self.anchor_present) is not int or not 0 <= self.anchor_present <= 0xFFFFFFFF:
            raise ValueError("anchor_present must be uint32")
        if type(self.partition_frame_flags) is not int or not 0 <= self.partition_frame_flags <= 0xFFFFFFFF:
            raise ValueError("partition_frame_flags must be uint32")
        for value, name in ((self.velocity_weight, "velocity_weight"), (self.gravity_ratio, "gravity_ratio")):
            if not np.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        object.__setattr__(self, "animated_base_world_positions", positions)
        object.__setattr__(self, "animated_base_world_rotations", rotations)
        object.__setattr__(self, "animated_base_world_normals", normals)
        object.__setattr__(self, "partition_world_linear", linear)

    @property
    def vertex_count(self) -> int:
        return int(self.animated_base_world_positions.shape[0])


def compile_mc2_domain_frame_packet(
    program: MC2CompiledDomainProgramV1,
    snapshots,
) -> MC2DomainFramePacketV1:
    if not isinstance(program, MC2CompiledDomainProgramV1):
        raise TypeError("program must be MC2CompiledDomainProgramV1")
    snapshots = tuple(snapshots)
    if len(snapshots) != program.partition_count or any(
        not isinstance(snapshot, MC2PartitionFrameSnapshotV1) for snapshot in snapshots
    ):
        raise TypeError("snapshots must contain one MC2PartitionFrameSnapshotV1 per partition")
    if tuple(snapshot.partition_id for snapshot in snapshots) != program.partition_ids:
        raise ValueError("frame snapshots must follow compiled partition order")
    frame_generation = {(snapshot.frame, snapshot.generation) for snapshot in snapshots}
    if len(frame_generation) != 1:
        raise ValueError("all partition frame snapshots must share frame/generation")

    positions = np.zeros((program.particle_count, 3), dtype=np.float32)
    rotations = np.zeros((program.particle_count, 4), dtype=np.float32)
    normals = np.zeros((program.particle_count, 3), dtype=np.float32)
    partition_position = []
    partition_rotation = []
    partition_scale = []
    partition_linear = []
    anchor_position = []
    anchor_rotation = []
    anchor_present = []
    frame_flags = []
    velocity_weight = []
    gravity_ratio = []
    for partition_index, snapshot in enumerate(snapshots):
        logical_indices = program.partition_particle_views[partition_index].resolved_indices()
        if len(logical_indices) != snapshot.vertex_count:
            raise ValueError(
                f"frame snapshot particle count mismatch for {snapshot.partition_id}"
            )
        positions[logical_indices] = snapshot.animated_base_world_positions
        rotations[logical_indices] = snapshot.animated_base_world_rotations
        normals[logical_indices] = snapshot.animated_base_world_normals
        partition_position.append(snapshot.partition_world_position)
        partition_rotation.append(snapshot.partition_world_rotation)
        partition_scale.append(snapshot.partition_world_scale)
        partition_linear.append(snapshot.partition_world_linear)
        anchor_position.append(snapshot.anchor_world_position)
        anchor_rotation.append(snapshot.anchor_world_rotation)
        anchor_present.append(snapshot.anchor_present)
        frame_flags.append(snapshot.partition_frame_flags)
        velocity_weight.append(snapshot.velocity_weight)
        gravity_ratio.append(snapshot.gravity_ratio)

    return make_mc2_domain_frame_packet(
        program,
        frame=next(iter(frame_generation))[0],
        generation=next(iter(frame_generation))[1],
        animated_base_world_positions=positions,
        animated_base_world_rotations=rotations,
        animated_base_world_normals=normals,
        partition_world_position=partition_position,
        partition_world_rotation=partition_rotation,
        partition_world_scale=partition_scale,
        partition_world_linear=partition_linear,
        anchor_world_position=anchor_position,
        anchor_world_rotation=anchor_rotation,
        anchor_present=anchor_present,
        partition_frame_flags=frame_flags,
        velocity_weight=velocity_weight,
        gravity_ratio=gravity_ratio,
    )


__all__ = [
    "MC2PartitionFrameSnapshotV1",
    "compile_mc2_domain_frame_packet",
]
