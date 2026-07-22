"""Product bridge from MC2 task authoring intent to one Mesh domain draft."""

from __future__ import annotations

from dataclasses import dataclass
import json

from .domain_collect import MC2MeshDomainDraftV1
from .domain_collect import build_mc2_mesh_domain_draft
from .domain_ir import MC2MeshPartitionStaticSnapshotV1
from .domain_output import MC2MeshWritebackBatchV1
from .names import MC2_SETUP_MESH_CLOTH
from .mesh_topology_identity import mesh_topology_signature_from_arrays
from .partition_specs import collect_mc2_partition_entries
from .partition_specs import make_mc2_partition_entry
from .partition_specs import MC2PartitionCollectorPlan
from .specs import MC2TaskSpec
from .specs import build_mc2_task_specs
from .specs import make_mc2_task_spec
from .specs import mc2_source_token
from .setups.mesh_cloth.source_capture import (
    capture_mc2_mesh_partition_static_snapshot,
)
from .topology import MC2MeshRawSnapshot


def _prepare_observed_static_inputs(world, task, *, force_audit=None):
    from .source_observation_blender import prepare_observed_static_inputs

    return prepare_observed_static_inputs(
        world,
        task,
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


@dataclass(frozen=True)
class MC2MeshProductCollectionV1:
    draft: MC2MeshDomainDraftV1
    static_snapshots: tuple[MC2MeshPartitionStaticSnapshotV1, ...]
    task_ids: tuple[str, ...]
    observation_identities: tuple[tuple, ...]
    observation_statuses: tuple[str, ...]
    mesh_topology_signatures: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.draft, MC2MeshDomainDraftV1):
            raise TypeError("draft must be MC2MeshDomainDraftV1")
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


def collect_mc2_mesh_product_domain(
    world,
    tasks,
    *,
    force_audit: bool | None = None,
) -> MC2MeshProductCollectionV1:
    """Observe every explicit Mesh task once and produce no runtime owner state."""

    specs = tuple(
        spec
        for spec in build_mc2_task_specs(tasks)
        if spec.enabled and spec.setup_type == MC2_SETUP_MESH_CLOTH and spec.sources
    )
    if not specs:
        raise ValueError("MC2 Mesh product collector has no active partitions")
    if any(not isinstance(spec, MC2TaskSpec) for spec in specs):
        raise TypeError("tasks must resolve to MC2TaskSpec values")
    if any(len(spec.sources) != 1 for spec in specs):
        raise ValueError(
            "transitional Mesh product collector requires one source per authoring task"
        )

    entries = []
    tasks_by_partition = {}
    for spec in specs:
        entries.append(make_mc2_partition_entry(
            spec.sources[0],
            setup_type=MC2_SETUP_MESH_CLOTH,
            stable_id=spec.task_id,
            producer="mc2.product_task",
            profile=spec.profile,
            task_parameters=spec.task_parameters,
            setup_options=spec.setup_options,
            anchor_object=spec.anchor_object,
            enabled=True,
        ))
        tasks_by_partition[spec.task_id] = spec
    plan = collect_mc2_partition_entries(
        setup_type=MC2_SETUP_MESH_CLOTH,
        explicit_entries=tuple(entries),
    )
    return collect_mc2_mesh_product_plan(
        world,
        plan,
        force_audit=force_audit,
        observation_tasks=tasks_by_partition,
    )


def collect_mc2_mesh_product_plan(
    world,
    plan: MC2PartitionCollectorPlan,
    *,
    force_audit: bool | None = None,
    observation_tasks=None,
) -> MC2MeshProductCollectionV1:
    """直接消费一个明确的 fused Mesh collector plan。"""

    if not isinstance(plan, MC2PartitionCollectorPlan):
        raise TypeError("plan must be MC2PartitionCollectorPlan")
    if plan.setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("Mesh product collector plan setup type mismatch")
    partitions = tuple(plan.active_partitions)
    if not partitions:
        raise ValueError("MC2 Mesh product collector has no active partitions")
    observation_tasks = dict(observation_tasks or {})
    rows = []
    identities = []
    statuses = []
    topology_signatures = []
    task_ids = []
    for partition in partitions:
        source = partition.source
        spec = observation_tasks.get(partition.stable_id)
        if spec is None:
            spec = make_mc2_task_spec(
                MC2_SETUP_MESH_CLOTH,
                [source],
                profile=partition.profile,
                setup_options=partition.setup_options,
                task_parameters=partition.task_parameters,
                anchor_object=partition.anchor_object,
                enabled=partition.enabled,
            )
        observation = _prepare_observed_static_inputs(
            world,
            spec,
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
    draft = build_mc2_mesh_domain_draft(plan)
    return MC2MeshProductCollectionV1(
        draft=draft,
        static_snapshots=tuple(rows),
        task_ids=tuple(task_ids),
        observation_identities=tuple(identities),
        observation_statuses=tuple(statuses),
        mesh_topology_signatures=tuple(topology_signatures),
    )


__all__ = [
    "MC2MeshProductCollectionV1",
    "collect_mc2_mesh_product_domain",
    "collect_mc2_mesh_product_plan",
    "validate_mc2_mesh_product_output_batch",
    "validate_mc2_mesh_product_targets",
]
