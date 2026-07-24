"""Pure resolved-partition to setup-neutral domain draft assembly."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .names import MC2_SETUP_TYPES
from .partition_specs import (
    MC2PartitionCollectorPlan,
    MC2ResolvedPartitionSpec,
)
from .runtime_parameters import (
    MC2RuntimeParameters,
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
class MC2DomainDraftV1:
    setup_type: str
    domain_id: str
    collector_domain_signature: str
    partitions: tuple[MC2ResolvedPartitionSpec, ...]
    effectives: tuple[MC2RuntimeParameters, ...]
    collision_groups: tuple[int, ...]
    collision_masks: tuple[int, ...]
    external_collision_masks: tuple[int, ...]
    draft_signature: str

    def __post_init__(self) -> None:
        if not self.domain_id or not self.collector_domain_signature:
            raise ValueError("MC2 domain draft identity cannot be empty")
        if self.setup_type not in MC2_SETUP_TYPES:
            raise ValueError("MC2 domain draft setup_type 无效")
        count = len(self.partitions)
        if count <= 0:
            raise ValueError("MC2 domain draft requires active partitions")
        if len(self.effectives) != count:
            raise ValueError("MC2 domain draft effective count mismatch")
        if (
            len(self.collision_groups) != count
            or len(self.collision_masks) != count
            or len(self.external_collision_masks) != count
        ):
            raise ValueError("MC2 domain draft filter count mismatch")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 0xFFFF
            for value in self.external_collision_masks
        ):
            raise ValueError("MC2 external collision masks must fit 16 groups")
        if any(
            not isinstance(partition, MC2ResolvedPartitionSpec)
            or partition.setup_type != self.setup_type
            or not partition.enabled
            for partition in self.partitions
        ):
            raise TypeError("MC2 domain draft requires one setup type of active partitions")
        if any(
            not isinstance(effective, MC2RuntimeParameters)
            for effective in self.effectives
        ):
            raise TypeError("MC2 domain draft effectives are invalid")
        if len(set(partition.stable_id for partition in self.partitions)) != count:
            raise ValueError("MC2 domain draft partition ids must be unique")
        if len(self.draft_signature) != 64:
            raise ValueError("MC2 domain draft signature is invalid")

    @property
    def partition_ids(self) -> tuple[str, ...]:
        return (*(partition.stable_id for partition in self.partitions),)

    def debug_dict(self) -> dict:
        return {
            "schema": "mc2_domain_draft_v1",
            "setup_type": self.setup_type,
            "domain_id": self.domain_id,
            "collector_domain_signature": self.collector_domain_signature,
            "draft_signature": self.draft_signature,
            "partition_ids": list(self.partition_ids),
            "collision_groups": list(self.collision_groups),
            "collision_masks": list(self.collision_masks),
            "external_collision_masks": list(self.external_collision_masks),
            "effective_parameter_signatures": [
                effective.parameter_signature for effective in self.effectives
            ],
            "partitions": [partition.debug_dict() for partition in self.partitions],
        }


def build_mc2_domain_draft(
    plan: MC2PartitionCollectorPlan,
    *,
    domain_id: str | None = None,
    external_collision_masks=None,
) -> MC2DomainDraftV1:
    """Compile resolved authoring intent without Blender IO or dense buffers."""

    if not isinstance(plan, MC2PartitionCollectorPlan):
        raise TypeError("plan must be MC2PartitionCollectorPlan")
    partitions = plan.active_partitions
    if not partitions:
        raise ValueError("MC2 domain draft has no active partitions")
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
    external_masks = (
        tuple(int(partition.setup_options.collided_by_groups) for partition in partitions)
        if external_collision_masks is None
        else tuple(external_collision_masks)
    )
    if len(external_masks) != len(partitions):
        raise ValueError("MC2 external collision masks must match active partitions")
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 0xFFFF
        for value in external_masks
    ):
        raise ValueError("MC2 external collision masks must fit 16 groups")
    resolved_domain_id = str(
        domain_id or f"mc2.domain:{plan.report.domain_signature[:24]}"
    ).strip()
    payload = {
        "schema": "mc2_domain_draft_v1",
        "setup_type": plan.setup_type,
        "domain_id": resolved_domain_id,
        "collector_domain_signature": plan.report.domain_signature,
        "partition_ids": [partition.stable_id for partition in partitions],
        "effective_parameter_signatures": [
            effective.parameter_signature for effective in effectives
        ],
        "collision_groups": groups,
        "collision_masks": masks,
        "external_collision_masks": external_masks,
        "field_sources": [
            dict(partition.field_sources) for partition in partitions
        ],
    }
    return MC2DomainDraftV1(
        setup_type=plan.setup_type,
        domain_id=resolved_domain_id,
        collector_domain_signature=plan.report.domain_signature,
        partitions=partitions,
        effectives=effectives,
        collision_groups=groups,
        collision_masks=masks,
        external_collision_masks=external_masks,
        draft_signature=_signature(payload),
    )


def build_mc2_domain_collider_frame_for_draft(
    world,
    draft: MC2DomainDraftV1,
):
    """Capture one public Physics World collider table for an entire draft."""

    if not isinstance(draft, MC2DomainDraftV1):
        raise TypeError("draft must be MC2DomainDraftV1")
    from .collider_frame import build_mc2_domain_collider_frame

    return build_mc2_domain_collider_frame(
        world,
        (
            getattr(partition.source, "armature", partition.source)
            for partition in draft.partitions
        ),
        allowed_types=(
            frozenset(("SPHERE",))
            if draft.setup_type == "bone_spring"
            else None
        ),
    )


# E5-B 迁移包装；E7-S 在产品调用点全部切换后删除。
MC2MeshDomainDraftV1 = MC2DomainDraftV1


def build_mc2_mesh_domain_draft(
    plan: MC2PartitionCollectorPlan,
    *,
    domain_id: str | None = None,
    external_collision_masks=None,
) -> MC2DomainDraftV1:
    return build_mc2_domain_draft(
        plan,
        domain_id=domain_id,
        external_collision_masks=external_collision_masks,
    )


def build_mc2_mesh_domain_collider_frame(world, draft: MC2DomainDraftV1):
    return build_mc2_domain_collider_frame_for_draft(world, draft)


__all__ = [
    "MC2DomainDraftV1",
    "MC2MeshDomainDraftV1",
    "build_mc2_domain_draft",
    "build_mc2_domain_collider_frame_for_draft",
    "build_mc2_mesh_domain_draft",
    "build_mc2_mesh_domain_collider_frame",
]
