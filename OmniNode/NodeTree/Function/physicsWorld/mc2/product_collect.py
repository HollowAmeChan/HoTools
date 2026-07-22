"""Product bridge from MC2 task authoring intent to one Mesh domain draft."""

from __future__ import annotations

from dataclasses import dataclass
import json

from .domain_collect import MC2MeshDomainDraftV1
from .domain_collect import build_mc2_mesh_domain_draft
from .domain_ir import MC2MeshPartitionStaticSnapshotV1
from .names import MC2_SETUP_MESH_CLOTH
from .partition_specs import collect_mc2_partition_entries
from .partition_specs import make_mc2_partition_entry
from .specs import MC2TaskSpec
from .specs import build_mc2_task_specs
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

    def __post_init__(self) -> None:
        if not isinstance(self.draft, MC2MeshDomainDraftV1):
            raise TypeError("draft must be MC2MeshDomainDraftV1")
        count = len(self.static_snapshots)
        if count != len(self.task_ids) or count != len(self.observation_statuses):
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
            "draft": self.draft.debug_dict(),
            "static_snapshots": [
                snapshot.debug_dict() for snapshot in self.static_snapshots
            ],
        }


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

    rows = []
    entries = []
    identities = []
    statuses = []
    for spec in specs:
        source = spec.sources[0]
        observation = _prepare_observed_static_inputs(
            world,
            spec,
            force_audit=force_audit,
        )
        if len(observation.snapshots) != 1 or not isinstance(
            observation.snapshots[0], MC2MeshRawSnapshot
        ):
            raise ValueError("Mesh product source observation did not resolve")
        snapshot = capture_mc2_mesh_partition_static_snapshot(
            source,
            observation.snapshots[0],
            partition_id=spec.task_id,
            source_identity=_canonical_source_identity(source),
            source_revision=observation.fingerprint.overall,
            output_target_id=_output_target_id(source),
        )
        rows.append(snapshot)
        identities.extend(observation.identities)
        statuses.extend(observation.statuses)
        entries.append(make_mc2_partition_entry(
            source,
            setup_type=MC2_SETUP_MESH_CLOTH,
            stable_id=spec.task_id,
            producer="mc2.product_task",
            profile=spec.profile,
            task_parameters=spec.task_parameters,
            setup_options=spec.setup_options,
            anchor_object=spec.anchor_object,
            enabled=True,
        ))

    plan = collect_mc2_partition_entries(
        setup_type=MC2_SETUP_MESH_CLOTH,
        explicit_entries=tuple(entries),
    )
    draft = build_mc2_mesh_domain_draft(plan)
    return MC2MeshProductCollectionV1(
        draft=draft,
        static_snapshots=tuple(rows),
        task_ids=tuple(spec.task_id for spec in specs),
        observation_identities=tuple(identities),
        observation_statuses=tuple(statuses),
    )


__all__ = [
    "MC2MeshProductCollectionV1",
    "collect_mc2_mesh_product_domain",
]
