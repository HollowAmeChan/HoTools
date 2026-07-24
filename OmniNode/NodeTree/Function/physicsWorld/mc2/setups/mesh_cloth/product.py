"""MeshCloth setup 的 product collect 与 frame hooks。"""

from __future__ import annotations

from dataclasses import dataclass
import json

from ...domain_collect import MC2DomainDraftV1
from ...domain_collect import build_mc2_domain_draft
from ...domain_ir import MC2MeshPartitionStaticSnapshotV1
from ...domain_output import MC2MeshWritebackBatchV1
from ...names import MC2_SETUP_MESH_CLOTH
from ...mesh_topology_identity import mesh_topology_signature_from_arrays
from ...partition_specs import MC2PartitionCollectorPlan
from ...source_identity import mc2_source_token
from .source_capture import (
    capture_mc2_mesh_partition_static_snapshot,
)
from ...topology import MC2MeshRawSnapshot


def _prepare_observed_static_inputs(
    world,
    partition,
    *,
    receipt_slot_id,
    force_audit=None,
):
    from ...source_observation_blender import (
        prepare_observed_static_inputs_for_partition,
    )

    return prepare_observed_static_inputs_for_partition(
        world,
        partition,
        receipt_slot_id=receipt_slot_id,
        force_audit=force_audit,
    )


def _canonical_source_identity(source) -> str:
    return json.dumps(
        mc2_source_token(source),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _output_target_id(source) -> str:
    pointer = getattr(source, "as_pointer", None)
    data_pointer = getattr(getattr(source, "data", None), "as_pointer", None)
    if not callable(pointer) or not callable(data_pointer):
        raise TypeError("Mesh product source must expose object/data pointers")
    owner = int(pointer())
    data = int(data_pointer())
    if owner <= 0 or data <= 0:
        raise ValueError("Mesh product source is no longer valid")
    return f"mesh:{owner}:{data}"


def _external_collision_mask(partition) -> int:
    """在产品 IO 边界解析 Mesh 对象面板的外部碰撞组。"""

    properties = getattr(partition.source, "hotools_mesh_collision", None)
    value = (
        partition.setup_options.collided_by_groups
        if properties is None
        else getattr(properties, "collided_by_groups", 0)
    )
    return max(0, min(0xFFFF, int(value or 0)))


@dataclass(frozen=True)
class MC2MeshProductCollectionV1:
    draft: MC2DomainDraftV1
    static_snapshots: tuple[MC2MeshPartitionStaticSnapshotV1, ...]
    task_ids: tuple[str, ...]
    observation_identities: tuple[tuple, ...]
    observation_statuses: tuple[str, ...]
    mesh_topology_signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.draft, MC2DomainDraftV1):
            raise TypeError("draft must be MC2DomainDraftV1")
        count = len(self.static_snapshots)
        if (
            count != len(self.task_ids)
            or count != len(self.observation_statuses)
            or count != len(self.mesh_topology_signatures)
        ):
            raise ValueError("Mesh product collection rows must match")
        if count != len(self.draft.partition_ids):
            raise ValueError("Mesh product collection must cover every partition")
        if any(
            not isinstance(value, MC2MeshPartitionStaticSnapshotV1)
            for value in self.static_snapshots
        ):
            raise TypeError("static_snapshots must contain Mesh snapshot V1 values")
        if tuple(value.partition_id for value in self.static_snapshots) != (
            self.draft.partition_ids
        ):
            raise ValueError("Mesh product snapshots must follow draft partition order")
        if any(len(str(value or "")) != 64 for value in self.mesh_topology_signatures):
            raise ValueError("Mesh product topology signatures are invalid")

    @property
    def world_gravity_directions(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(
            tuple(float(component) for component in partition.profile.gravity_direction)
            for partition in self.draft.partitions
        )

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_mesh_product_collection_v1",
            "task_ids": list(self.task_ids),
            "partition_ids": list(self.draft.partition_ids),
            "observation_statuses": list(self.observation_statuses),
            "observation_identity_count": len(self.observation_identities),
            "mesh_topology_signatures": list(self.mesh_topology_signatures),
            "draft": self.draft.debug_dict(),
            "static_snapshots": [
                snapshot.debug_dict() for snapshot in self.static_snapshots
            ],
        }


def validate_mc2_mesh_product_output_batch(
    collection: MC2MeshProductCollectionV1,
    batch: MC2MeshWritebackBatchV1,
) -> None:
    """在发布前一次校验 collector 的全部 live Mesh target。"""

    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise TypeError("collection must be MC2MeshProductCollectionV1")
    if not isinstance(batch, MC2MeshWritebackBatchV1):
        raise TypeError("batch must be MC2MeshWritebackBatchV1")
    expected = tuple(snapshot.output_target_id for snapshot in collection.static_snapshots)
    actual = tuple(command.target_id for command in batch.commands)
    if actual != expected:
        raise ValueError("Mesh product output targets no longer match the collector")
    if len(collection.draft.partitions) != len(batch.commands):
        raise ValueError("Mesh product output target count is stale")
    validate_mc2_mesh_product_targets(collection)
    for partition, snapshot, command in zip(
        collection.draft.partitions,
        collection.static_snapshots,
        batch.commands,
    ):
        if snapshot.vertex_count != len(command.source_elements):
            raise ValueError(
                f"Mesh product output {partition.stable_id} vertex count is stale"
            )


def validate_mc2_mesh_product_targets(
    collection: MC2MeshProductCollectionV1,
) -> None:
    """在求解前校验整域全部 target，失败时不推进 native 状态。"""

    if not isinstance(collection, MC2MeshProductCollectionV1):
        raise TypeError("collection must be MC2MeshProductCollectionV1")
    for partition, snapshot in zip(
        collection.draft.partitions,
        collection.static_snapshots,
    ):
        source = partition.source
        pointer = getattr(source, "as_pointer", None)
        data = getattr(source, "data", None)
        data_pointer = getattr(data, "as_pointer", None)
        try:
            object_ptr = int(pointer()) if callable(pointer) else 0
            object_data_ptr = int(data_pointer()) if callable(data_pointer) else 0
        except (ReferenceError, RuntimeError) as exc:
            raise ValueError(
                f"Mesh product target {partition.stable_id} is no longer live"
            ) from exc
        target_id = f"mesh:{object_ptr}:{object_data_ptr}"
        if object_ptr <= 0 or object_data_ptr <= 0 or target_id != snapshot.output_target_id:
            raise ValueError(
                f"Mesh product target {partition.stable_id} object/data identity changed"
            )
        vertices = getattr(data, "vertices", None)
        if vertices is None or len(vertices) != snapshot.vertex_count:
            raise ValueError(
                f"Mesh product target {partition.stable_id} vertex count changed"
            )
        if int(getattr(data, "users", 1) or 1) != 1:
            raise ValueError(
                f"Mesh product target {partition.stable_id} must use single-user Mesh data"
            )


def collect_mc2_mesh_product_plan(
    world,
    plan: MC2PartitionCollectorPlan,
    *,
    receipt_slot_id: str,
    force_audit: bool | None = None,
) -> MC2MeshProductCollectionV1:
    """直接消费一个明确的 Mesh product collector plan。"""

    if not isinstance(plan, MC2PartitionCollectorPlan):
        raise TypeError("plan must be MC2PartitionCollectorPlan")
    if plan.setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("Mesh product collector plan setup type mismatch")
    partitions = tuple(plan.active_partitions)
    if not partitions:
        raise ValueError("MC2 Mesh product collector has no active partitions")
    receipt_slot_id = str(receipt_slot_id or "").strip()
    if not receipt_slot_id:
        raise ValueError("Mesh product collection requires receipt_slot_id")
    rows = []
    identities = []
    statuses = []
    topology_signatures = []
    task_ids = []
    for partition in partitions:
        source = partition.source
        observation = _prepare_observed_static_inputs(
            world,
            partition,
            receipt_slot_id=receipt_slot_id,
            force_audit=force_audit,
        )
        if len(observation.snapshots) != 1 or not isinstance(
            observation.snapshots[0], MC2MeshRawSnapshot
        ):
            raise ValueError("Mesh product source observation did not resolve")
        raw_snapshot = observation.snapshots[0]
        snapshot = capture_mc2_mesh_partition_static_snapshot(
            source,
            raw_snapshot,
            partition_id=partition.stable_id,
            source_identity=_canonical_source_identity(source),
            source_revision=observation.fingerprint.overall,
            output_target_id=_output_target_id(source),
        )
        rows.append(snapshot)
        topology_signatures.append(mesh_topology_signature_from_arrays(
            len(raw_snapshot.positions),
            raw_snapshot.edges,
            raw_snapshot.polygon_loop_totals,
            raw_snapshot.loop_vertices,
            raw_snapshot.triangles,
        ))
        identities.extend(observation.identities)
        statuses.extend(observation.statuses)
        task_ids.append(partition.stable_id)
    draft = build_mc2_domain_draft(
        plan,
        external_collision_masks=tuple(
            _external_collision_mask(partition) for partition in partitions
        ),
    )
    return MC2MeshProductCollectionV1(
        draft=draft,
        static_snapshots=tuple(rows),
        task_ids=tuple(task_ids),
        observation_identities=tuple(identities),
        observation_statuses=tuple(statuses),
        mesh_topology_signatures=tuple(topology_signatures),
    )


from dataclasses import dataclass

import numpy as np

from ...domain_compile import MC2MeshCompiledDomainV1
from ...frame_compile import MC2PartitionFrameSnapshotV1
from ...frame_compile import compile_mc2_domain_frame_packet
from ...native import native_module

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
    from ...anchor import attach_mc2_task_anchor
    from ...center_state import MC2CenterFramePoseSpec
    from .frame_input import read_base_pose_frame_snapshot

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
    "MC2MeshProductCollectionV1",
    "collect_mc2_mesh_product_plan",
    "validate_mc2_mesh_product_output_batch",
    "validate_mc2_mesh_product_targets",
    "MC2MeshProductFrameRowV1",
    "capture_mc2_mesh_product_frame",
    "compile_mc2_mesh_product_frame",
]
