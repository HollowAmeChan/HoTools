"""BoneCloth object authoring with one complete property source."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ...source_identity import mc2_source_token
from .source_spec import (
    MC2BonePartitionSourceV1,
    mc2_bone_cloth_property_owner,
    make_mc2_bone_cloth_partition_source,
)


def _signature(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MC2BoneClothExplicitPropertiesSpec:
    """Complete BoneCloth object properties from either panel or sockets."""

    primary_collision_group: int = 1
    collided_by_groups: int = 0

    def __post_init__(self) -> None:
        group = int(self.primary_collision_group)
        if not 1 <= group <= 16:
            raise ValueError(
                "BoneCloth primary_collision_group must be in 1..16"
            )
        object.__setattr__(self, "primary_collision_group", group)
        mask = int(self.collided_by_groups)
        if not 0 <= mask <= 0xFFFF:
            raise ValueError("BoneCloth collided_by_groups must be a 16-bit mask")
        object.__setattr__(self, "collided_by_groups", mask)

    @property
    def self_group_bit(self) -> int:
        return 1 << (self.primary_collision_group - 1)

    @property
    def self_collision_groups(self) -> int:
        return self.collided_by_groups | self.self_group_bit

    @property
    def signature(self) -> str:
        return _signature(self.debug_dict())

    def debug_dict(self) -> dict:
        return {
            "primary_collision_group": self.primary_collision_group,
            "collided_by_groups": self.collided_by_groups,
        }


@dataclass(frozen=True)
class MC2BoneClothObjectSpec:
    """One resolved BoneCloth partition source and its object properties."""

    partition_source: MC2BonePartitionSourceV1
    explicit_properties: MC2BoneClothExplicitPropertiesSpec
    property_origin: str

    def __post_init__(self) -> None:
        if not isinstance(self.partition_source, MC2BonePartitionSourceV1):
            raise TypeError(
                "MC2 BoneCloth object requires MC2BonePartitionSourceV1"
            )
        if self.partition_source.setup_type != "bone_cloth":
            raise ValueError("MC2 BoneCloth object source setup type is invalid")
        if not isinstance(
            self.explicit_properties, MC2BoneClothExplicitPropertiesSpec
        ):
            raise TypeError(
                "MC2 BoneCloth object requires complete explicit properties"
            )
        origin = str(self.property_origin or "").strip().lower()
        if origin not in {"panel", "socket"}:
            raise ValueError(
                "BoneCloth property_origin must be panel or socket"
            )
        object.__setattr__(self, "property_origin", origin)

    @property
    def source_identity(self) -> str:
        return _signature(mc2_source_token(self.partition_source))

    @property
    def signature(self) -> str:
        return _signature({
            "source": mc2_source_token(self.partition_source),
            "explicit_properties": self.explicit_properties.debug_dict(),
        })

    def debug_dict(self) -> dict:
        return {
            "source": mc2_source_token(self.partition_source),
            "source_identity": self.source_identity,
            "property_origin": self.property_origin,
            "explicit_properties": self.explicit_properties.debug_dict(),
            "signature": self.signature,
        }


def make_mc2_bone_cloth_explicit_properties(
    *,
    primary_collision_group=1,
    collided_by_groups=0,
) -> MC2BoneClothExplicitPropertiesSpec:
    return MC2BoneClothExplicitPropertiesSpec(
        primary_collision_group=int(primary_collision_group),
        collided_by_groups=int(collided_by_groups),
    )


def _panel_properties(value) -> MC2BoneClothExplicitPropertiesSpec:
    armature, bone_name = mc2_bone_cloth_property_owner(value)
    bones = getattr(getattr(armature, "data", None), "bones", None)
    bone = bones.get(bone_name) if bones is not None else None
    if bone is None:
        raise ValueError(f"BoneCloth panel bone not found: {bone_name!r}")
    properties = getattr(bone, "hotools_collision", None)
    if properties is None:
        raise ValueError("Bone has no registered hotools_collision properties")
    return make_mc2_bone_cloth_explicit_properties(
        primary_collision_group=getattr(
            properties, "primary_collision_group", 1
        ),
        collided_by_groups=getattr(properties, "collided_by_groups", 0),
    )


def read_mc2_bone_cloth_panel_object(value) -> MC2BoneClothObjectSpec:
    """Read the complete object property set from the control/root Bone panel."""

    return MC2BoneClothObjectSpec(
        partition_source=make_mc2_bone_cloth_partition_source(value),
        explicit_properties=_panel_properties(value),
        property_origin="panel",
    )


def make_mc2_bone_cloth_custom_object(
    value,
    *,
    primary_collision_group=1,
    collided_by_groups=0,
) -> MC2BoneClothObjectSpec:
    """Build a complete object without reading Bone panel properties."""

    return MC2BoneClothObjectSpec(
        partition_source=make_mc2_bone_cloth_partition_source(value),
        explicit_properties=make_mc2_bone_cloth_explicit_properties(
            primary_collision_group=primary_collision_group,
            collided_by_groups=collided_by_groups,
        ),
        property_origin="socket",
    )


def _flatten_bone_values(values) -> tuple[object, ...]:
    pending = list(values) if isinstance(values, list) else [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, list):
            pending[0:0] = value
            continue
        result.append(value)
    return tuple(result)


def read_mc2_bone_cloth_panel_objects(values) -> tuple[MC2BoneClothObjectSpec, ...]:
    return tuple(
        read_mc2_bone_cloth_panel_object(value)
        for value in _flatten_bone_values(values)
    )


def make_mc2_bone_cloth_custom_objects(
    values,
    **properties,
) -> tuple[MC2BoneClothObjectSpec, ...]:
    return tuple(
        make_mc2_bone_cloth_custom_object(value, **properties)
        for value in _flatten_bone_values(values)
    )


__all__ = [
    "MC2BoneClothExplicitPropertiesSpec",
    "MC2BoneClothObjectSpec",
    "make_mc2_bone_cloth_custom_object",
    "make_mc2_bone_cloth_custom_objects",
    "make_mc2_bone_cloth_explicit_properties",
    "read_mc2_bone_cloth_panel_object",
    "read_mc2_bone_cloth_panel_objects",
]
