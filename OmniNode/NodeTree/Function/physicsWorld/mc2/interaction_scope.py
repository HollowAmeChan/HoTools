"""Stable task-pair ownership for world-level MC2 cloth interaction."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .names import MC2_SETUP_MESH_CLOTH
from .specs import MC2TaskSpec


def _signature(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _mesh_collision_properties(source):
    return getattr(source, "hotools_mesh_collision", None)


@dataclass(frozen=True)
class MC2InteractionParticipantSpec:
    task_id: str
    primary_group: int
    collided_by_groups: int
    primitive_count: int = 0

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("interaction participant task_id cannot be empty")
        if self.primary_group not in range(1, 17):
            raise ValueError("interaction primary_group must be in 1..16")
        if not 0 <= self.collided_by_groups <= 0xFFFF:
            raise ValueError("interaction collided_by_groups must be in 0..65535")
        if self.primitive_count < 0:
            raise ValueError("interaction primitive_count cannot be negative")

    @property
    def primary_group_bit(self) -> int:
        return 1 << (self.primary_group - 1)


@dataclass(frozen=True)
class MC2InteractionScopeSpec:
    participants: tuple[MC2InteractionParticipantSpec, ...]
    pairs: tuple[tuple[str, str], ...]
    scope_signature: str
    mode: str = "automatic_group_mask"

    def __post_init__(self) -> None:
        task_ids = tuple(item.task_id for item in self.participants)
        if task_ids != tuple(sorted(task_ids)) or len(task_ids) != len(set(task_ids)):
            raise ValueError("interaction participants must be unique and task-id sorted")
        expected_pairs = tuple(sorted(tuple(sorted(pair)) for pair in self.pairs))
        if self.pairs != expected_pairs or len(self.pairs) != len(set(self.pairs)):
            raise ValueError("interaction pairs must be unique and canonical")
        known = set(task_ids)
        if any(left == right or left not in known or right not in known for left, right in self.pairs):
            raise ValueError("interaction pair identity is invalid")

    def debug_dict(self) -> dict:
        return {
            "mode": self.mode,
            "participant_count": len(self.participants),
            "pair_count": len(self.pairs),
            "primitive_count": sum(item.primitive_count for item in self.participants),
            "participants": [
                {
                    "task_id": item.task_id,
                    "primary_group": item.primary_group,
                    "collided_by_groups": item.collided_by_groups,
                    "primitive_count": item.primitive_count,
                }
                for item in self.participants
            ],
            "pairs": [list(pair) for pair in self.pairs],
            "scope_signature": self.scope_signature,
        }


def _allows(source: MC2InteractionParticipantSpec, target: MC2InteractionParticipantSpec) -> bool:
    mask = source.collided_by_groups
    return mask == 0 or bool(mask & target.primary_group_bit)


def _automatic_pairs(participants) -> tuple[tuple[str, str], ...]:
    result = []
    for index, left in enumerate(participants[:-1]):
        for right in participants[index + 1:]:
            if _allows(left, right) and _allows(right, left):
                result.append((left.task_id, right.task_id))
    return tuple(result)


def build_mc2_interaction_scope(
    tasks,
    *,
    primitive_counts: dict[str, int] | None = None,
) -> MC2InteractionScopeSpec:
    primitive_counts = primitive_counts or {}
    participants = []
    for task in tasks:
        if not isinstance(task, MC2TaskSpec):
            raise TypeError("interaction scope tasks must be MC2TaskSpec values")
        if (
            not task.enabled
            or task.setup_type != MC2_SETUP_MESH_CLOTH
            or task.profile.self_collision_sync_mode == 0
        ):
            continue
        if len(task.sources) != 1:
            raise ValueError("interactive MeshCloth task requires one final-proxy source")
        properties = _mesh_collision_properties(task.sources[0])
        primary_group = max(1, min(16, int(getattr(properties, "primary_collision_group", 1) or 1)))
        collided_by_groups = max(0, min(0xFFFF, int(getattr(properties, "collided_by_groups", 0) or 0)))
        participants.append(MC2InteractionParticipantSpec(
            task_id=task.task_id,
            primary_group=primary_group,
            collided_by_groups=collided_by_groups,
            primitive_count=max(0, int(primitive_counts.get(task.task_id, 0) or 0)),
        ))
    participants.sort(key=lambda item: item.task_id)
    participant_values = tuple(participants)
    pairs = _automatic_pairs(participant_values)
    payload = {
        "schema": 0,
        "mode": "automatic_group_mask",
        "participants": [
            (item.task_id, item.primary_group, item.collided_by_groups, item.primitive_count)
            for item in participant_values
        ],
        "pairs": pairs,
    }
    return MC2InteractionScopeSpec(
        participants=participant_values,
        pairs=pairs,
        scope_signature=_signature(payload),
    )


def explicit_partner_pairs(partners: dict[str, object]) -> tuple[tuple[str, str], ...]:
    """Canonicalize a ListObj-like partner graph for benchmark comparison only."""

    pairs = set()
    for task_id, values in partners.items():
        left = str(task_id or "")
        if not left:
            raise ValueError("explicit partner task identity cannot be empty")
        if isinstance(values, str):
            values = (values,)
        for value in values or ():
            right = str(value or "")
            if not right or right == left:
                raise ValueError("explicit partner identity is invalid")
            pairs.add(tuple(sorted((left, right))))
    return tuple(sorted(pairs))


__all__ = [
    "MC2InteractionParticipantSpec",
    "MC2InteractionScopeSpec",
    "build_mc2_interaction_scope",
    "explicit_partner_pairs",
]
