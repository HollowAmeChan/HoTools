"""Whole-domain Mesh product frame capture and packet compilation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .domain_compile import MC2MeshCompiledDomainV1
from .frame_compile import MC2PartitionFrameSnapshotV1
from .frame_compile import compile_mc2_domain_frame_packet
from .native import native_module
from .product_collect import MC2MeshProductCollectionV1


def _readonly(values, dtype, shape, name):
    array = np.ascontiguousarray(values, dtype=dtype)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite with shape {shape}")
    array = np.array(array, dtype=dtype, order="C", copy=True)
    array.flags.writeable = False
    return array


@dataclass(frozen=True)
class MC2MeshProductFrameRowV1:
    partition_id: str
    output_target_id: str
    frame: int
    generation: int
    animated_base_world_positions: np.ndarray
    animated_base_world_normals: np.ndarray
    source_world_linear: np.ndarray
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_scale: tuple[float, float, float]
    anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_world_rotation_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    anchor_present: int = 0
    partition_frame_flags: int = 0
    velocity_weight: float = 1.0
    gravity_ratio: float = 1.0

    def __post_init__(self) -> None:
        if not str(self.partition_id or "").strip() or not str(self.output_target_id or "").strip():
            raise ValueError("Mesh product frame row identities cannot be empty")
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
        normals = _readonly(
            self.animated_base_world_normals,
            np.float32,
            positions.shape,
            "animated_base_world_normals",
        )
        linear = _readonly(
            self.source_world_linear,
            np.float32,
            (3, 3),
            "source_world_linear",
        )
        if abs(float(np.linalg.det(linear))) <= 1.0e-12:
            raise ValueError("source_world_linear must be invertible")
        for value, name, size in (
            (self.component_world_position, "component_world_position", 3),
            (self.component_world_rotation_xyzw, "component_world_rotation_xyzw", 4),
            (self.component_world_scale, "component_world_scale", 3),
            (self.anchor_world_position, "anchor_world_position", 3),
            (self.anchor_world_rotation_xyzw, "anchor_world_rotation_xyzw", 4),
        ):
            array = np.asarray(value, dtype=np.float64)
            if array.shape != (size,) or not np.isfinite(array).all():
                raise ValueError(f"{name} must be finite float[{size}]")
        for value, name in (
            (self.component_world_rotation_xyzw, "component_world_rotation_xyzw"),
            (self.anchor_world_rotation_xyzw, "anchor_world_rotation_xyzw"),
        ):
            if not np.isclose(np.linalg.norm(value), 1.0, rtol=1.0e-5, atol=1.0e-6):
                raise ValueError(f"{name} must be a unit quaternion")
        if any(abs(float(value)) <= 1.0e-12 for value in self.component_world_scale):
            raise ValueError("component_world_scale cannot contain zero")
        if type(self.anchor_present) is not int or not 0 <= self.anchor_present <= 1:
            raise ValueError("anchor_present must be 0 or 1")
        if type(self.partition_frame_flags) is not int or not 0 <= self.partition_frame_flags <= 0xFFFFFFFF:
            raise ValueError("partition_frame_flags must be uint32")
        if not np.isfinite(float(self.velocity_weight)) or not np.isfinite(float(self.gravity_ratio)):
            raise ValueError("frame weights must be finite")
        object.__setattr__(self, "animated_base_world_positions", positions)
        object.__setattr__(self, "animated_base_world_normals", normals)
        object.__setattr__(self, "source_world_linear", linear)

    @property
    def vertex_count(self) -> int:
        return int(self.animated_base_world_positions.shape[0])


def _frame_row_from_snapshot(
    snapshot,
    *,
    partition_id: str,
    output_target_id: str,
    anchor=None,
    partition_frame_flags: int = 0,
    velocity_weight: float = 1.0,
    gravity_ratio: float = 1.0,
) -> MC2MeshProductFrameRowV1:
    anchor_identity = str(getattr(anchor, "anchor_identity", "") or "") if anchor is not None else ""
    return MC2MeshProductFrameRowV1(
        partition_id=partition_id,
        output_target_id=output_target_id,
        frame=int(snapshot.frame),
        generation=int(snapshot.generation),
        animated_base_world_positions=snapshot.animated_base_world_positions,
        animated_base_world_normals=snapshot.animated_base_world_normals,
        source_world_linear=snapshot.source_world_linear,
        component_world_position=tuple(snapshot.component_world_position),
        component_world_rotation_xyzw=tuple(snapshot.component_world_rotation_xyzw),
        component_world_scale=tuple(snapshot.component_world_scale),
        anchor_world_position=(
            tuple(anchor.anchor_world_position)
            if anchor is not None else (0.0, 0.0, 0.0)
        ),
        anchor_world_rotation_xyzw=(
            tuple(anchor.anchor_world_rotation_xyzw)
            if anchor is not None else (0.0, 0.0, 0.0, 1.0)
        ),
        anchor_present=int(bool(anchor_identity)),
        partition_frame_flags=partition_frame_flags,
        velocity_weight=velocity_weight,
        gravity_ratio=gravity_ratio,
    )


def compile_mc2_mesh_product_frame(
    compiled: MC2MeshCompiledDomainV1,
    rows,
):
    if not isinstance(compiled, MC2MeshCompiledDomainV1):
        raise TypeError("compiled must be MC2MeshCompiledDomainV1")
    rows = tuple(rows)
    if len(rows) != compiled.program.partition_count or any(
        not isinstance(row, MC2MeshProductFrameRowV1) for row in rows
    ):
        raise TypeError("rows must contain one MC2MeshProductFrameRowV1 per partition")
    if tuple(row.partition_id for row in rows) != compiled.program.partition_ids:
        raise ValueError("product frame rows must follow compiled partition order")
    frame_snapshots = []
    for fragment, row in zip(compiled.fragments, rows):
        if row.output_target_id != fragment.output_target_id:
            raise ValueError(f"frame output target mismatch for {row.partition_id}")
        if row.vertex_count != fragment.final_proxy.vertex_count:
            raise ValueError(f"frame vertex count mismatch for {row.partition_id}")
        output = np.empty((row.vertex_count, 4), dtype=np.float32)
        native_module().mc2_mesh_frame_orientations_v1(
            row.animated_base_world_positions,
            fragment.frame_triangles,
            fragment.frame_triangle_uvs,
            fragment.frame_triangle_ranges,
            fragment.frame_triangle_records,
            output,
        )
        frame_snapshots.append(MC2PartitionFrameSnapshotV1(
            partition_id=row.partition_id,
            frame=row.frame,
            generation=row.generation,
            animated_base_world_positions=row.animated_base_world_positions,
            animated_base_world_rotations=output,
            animated_base_world_normals=row.animated_base_world_normals,
            partition_world_position=row.component_world_position,
            partition_world_rotation=row.component_world_rotation_xyzw,
            partition_world_scale=row.component_world_scale,
            partition_world_linear=row.source_world_linear,
            anchor_world_position=row.anchor_world_position,
            anchor_world_rotation=row.anchor_world_rotation_xyzw,
            anchor_present=row.anchor_present,
            partition_frame_flags=row.partition_frame_flags,
            velocity_weight=row.velocity_weight,
            gravity_ratio=row.gravity_ratio,
        ))
    packet = compile_mc2_domain_frame_packet(compiled.program, frame_snapshots)
    return packet, tuple(frame_snapshots)


def capture_mc2_mesh_product_frame(
    world,
    collection: MC2MeshProductCollectionV1,
    owner,
    *,
    depsgraph=None,
    partition_frame_flags=None,
    velocity_weights=None,
    gravity_ratios=None,
):
    """Capture BasePose/Anchor once per source, then compile one domain frame."""
    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise TypeError("collection must be MC2MeshProductCollectionV1")
    compiled = getattr(owner, "compiled", None)
    if not isinstance(compiled, MC2MeshCompiledDomainV1):
        raise RuntimeError("MC2 Mesh product owner has no compiled domain")
    from .anchor import attach_mc2_task_anchor
    from .center_state import MC2CenterFramePoseSpec
    from .setups.mesh_cloth.frame_input import read_base_pose_frame_snapshot

    if depsgraph is None:
        import bpy

        depsgraph = bpy.context.evaluated_depsgraph_get()

    frame_context = getattr(world, "frame_context", None)
    frame = int(getattr(frame_context, "frame", 0) or 0)
    generation = int(getattr(frame_context, "generation", 0) or getattr(world, "generation", 0) or 0)
    if generation <= 0:
        raise ValueError("MC2 Mesh product frame requires an active Physics World")
    flags = tuple(partition_frame_flags or (0,) * len(collection.draft.partitions))
    velocities = tuple(velocity_weights or (1.0,) * len(flags))
    gravities = tuple(gravity_ratios or (1.0,) * len(flags))
    if not (len(flags) == len(velocities) == len(gravities) == len(collection.draft.partitions)):
        raise ValueError("product frame options must match partition count")
    rows = []
    for index, (partition, topology_signature) in enumerate(
        zip(collection.draft.partitions, collection.mesh_topology_signatures)
    ):
        source = partition.source
        properties = getattr(source, "hotools_mesh_collision", None)
        base_obj = getattr(properties, "mc2_base_pose_proxy", None) if properties is not None else None
        if base_obj is None:
            raise ValueError(f"Mesh source {partition.stable_id} has no BasePose proxy")
        snapshot = read_base_pose_frame_snapshot(
            source,
            base_obj,
            mesh_topology_signature=topology_signature,
            frame=frame,
            generation=generation,
            depsgraph=depsgraph,
            cache=getattr(world, "runtime_caches", None),
        )
        center_frame_pose = MC2CenterFramePoseSpec(
            frame=frame,
            generation=generation,
            component_identity=f"object:{snapshot.source_object_ptr}",
            component_world_position=tuple(snapshot.component_world_position),
            component_world_rotation_xyzw=tuple(snapshot.component_world_rotation_xyzw),
            component_world_scale=tuple(snapshot.component_world_scale),
        )
        center_frame_pose = attach_mc2_task_anchor(
            center_frame_pose,
            partition,
            depsgraph=depsgraph,
        )
        rows.append(_frame_row_from_snapshot(
            snapshot,
            partition_id=partition.stable_id,
            output_target_id=collection.static_snapshots[index].output_target_id,
            anchor=center_frame_pose,
            partition_frame_flags=int(flags[index]),
            velocity_weight=float(velocities[index]),
            gravity_ratio=float(gravities[index]),
        ))
    return compile_mc2_mesh_product_frame(compiled, rows)


__all__ = [
    "MC2MeshProductFrameRowV1",
    "capture_mc2_mesh_product_frame",
    "compile_mc2_mesh_product_frame",
]
