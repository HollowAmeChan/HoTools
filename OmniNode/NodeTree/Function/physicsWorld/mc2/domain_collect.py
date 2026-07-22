"""Pure resolved-partition to Mesh domain draft assembly."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .names import MC2_SETUP_MESH_CLOTH
from .partition_specs import (
    MC2PartitionCollectorPlan,
    MC2ResolvedPartitionSpec,
)
from .runtime_parameters import (
    MC2RuntimeParametersV0,
    make_mc2_runtime_parameters,
)


def _signature(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolved_collision_groups(
    partitions: tuple[MC2ResolvedPartitionSpec, ...],
) -> tuple[int, ...]:
    explicit = {
        int(partition.collision_group)
        for partition in partitions
        if partition.collision_group is not None
    }
    available = [
        1 << bit for bit in range(32)
        if (1 << bit) not in explicit
    ]
    cursor = 0
    result = []
    for partition in partitions:
        value = partition.collision_group
        if value is None:
            if cursor >= len(available):
                raise ValueError(
                    "MC2 automatic collision groups exhausted 32 uint32 bits"
                )
            value = available[cursor]
            cursor += 1
        result.append(int(value))
    return tuple(result)


@dataclass(frozen=True)
class MC2MeshDomainDraftV1:
    domain_id: str
    collector_domain_signature: str
    partitions: tuple[MC2ResolvedPartitionSpec, ...]
    effectives: tuple[MC2RuntimeParametersV0, ...]
    collision_groups: tuple[int, ...]
    collision_masks: tuple[int, ...]
    draft_signature: str

    def __post_init__(self) -> None:
        if not self.domain_id or not self.collector_domain_signature:
            raise ValueError("MC2 Mesh domain draft identity cannot be empty")
        count = len(self.partitions)
        if count <= 0:
            raise ValueError("MC2 Mesh domain draft requires active partitions")
        if len(self.effectives) != count:
            raise ValueError("MC2 Mesh domain draft effective count mismatch")
        if len(self.collision_groups) != count or len(self.collision_masks) != count:
            raise ValueError("MC2 Mesh domain draft filter count mismatch")
        if any(
            not isinstance(partition, MC2ResolvedPartitionSpec)
            or partition.setup_type != MC2_SETUP_MESH_CLOTH
            or not partition.enabled
            for partition in self.partitions
        ):
            raise TypeError("MC2 Mesh domain draft requires active Mesh partitions")
        if any(
            not isinstance(effective, MC2RuntimeParametersV0)
            for effective in self.effectives
        ):
            raise TypeError("MC2 Mesh domain draft effectives are invalid")
        if len(set(partition.stable_id for partition in self.partitions)) != count:
            raise ValueError("MC2 Mesh domain draft partition ids must be unique")
        if len(self.draft_signature) != 64:
            raise ValueError("MC2 Mesh domain draft signature is invalid")

    @property
    def partition_ids(self) -> tuple[str, ...]:
        return (*(partition.stable_id for partition in self.partitions),)

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_mesh_domain_draft_v1",
            "domain_id": self.domain_id,
            "collector_domain_signature": self.collector_domain_signature,
            "draft_signature": self.draft_signature,
            "partition_ids": list(self.partition_ids),
            "collision_groups": list(self.collision_groups),
            "collision_masks": list(self.collision_masks),
            "effective_parameter_signatures": [
                effective.parameter_signature for effective in self.effectives
            ],
            "partitions": [partition.debug_dict() for partition in self.partitions],
        }


def build_mc2_mesh_domain_draft(
    plan: MC2PartitionCollectorPlan,
    *,
    domain_id: str | None = None,
) -> MC2MeshDomainDraftV1:
    """Compile resolved authoring intent without Blender IO or dense buffers."""

    if not isinstance(plan, MC2PartitionCollectorPlan):
        raise TypeError("plan must be MC2PartitionCollectorPlan")
    if plan.setup_type != MC2_SETUP_MESH_CLOTH:
        raise ValueError("Mesh domain draft only accepts mesh_cloth plans")
    partitions = plan.active_partitions
    if not partitions:
        raise ValueError("Mesh domain draft has no active partitions")
    effectives = tuple(
        make_mc2_runtime_parameters(
            partition.profile,
            partition.setup_options,
            partition.task_parameters,
        )
        for partition in partitions
    )
    groups = _resolved_collision_groups(partitions)
    masks = tuple(int(partition.collision_mask) for partition in partitions)
    resolved_domain_id = str(
        domain_id or f"mc2.domain:{plan.report.domain_signature[:24]}"
    ).strip()
    payload = {
        "schema": "mc2_mesh_domain_draft_v1",
        "domain_id": resolved_domain_id,
        "collector_domain_signature": plan.report.domain_signature,
        "partition_ids": [partition.stable_id for partition in partitions],
        "effective_parameter_signatures": [
            effective.parameter_signature for effective in effectives
        ],
        "collision_groups": groups,
        "collision_masks": masks,
        "field_sources": [
            dict(partition.field_sources) for partition in partitions
        ],
    }
    return MC2MeshDomainDraftV1(
        domain_id=resolved_domain_id,
        collector_domain_signature=plan.report.domain_signature,
        partitions=partitions,
        effectives=effectives,
        collision_groups=groups,
        collision_masks=masks,
        draft_signature=_signature(payload),
    )


def build_mc2_mesh_domain_collider_frame(
    world,
    draft: MC2MeshDomainDraftV1,
):
    """Capture one public Physics World collider table for an entire draft."""

    if not isinstance(draft, MC2MeshDomainDraftV1):
        raise TypeError("draft must be MC2MeshDomainDraftV1")
    from .collider_frame import build_mc2_domain_collider_frame

    return build_mc2_domain_collider_frame(
        world,
        (partition.source for partition in draft.partitions),
    )


__all__ = [
    "MC2MeshDomainDraftV1",
    "build_mc2_mesh_domain_draft",
    "build_mc2_mesh_domain_collider_frame",
]
