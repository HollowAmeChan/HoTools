"""Neutral intermediate representation for HoTools rig constraints.

This module deliberately has no Blender dependency.  It describes facts found in
the Blender rig; consumers decide how those facts are implemented at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA = "hotools.rig-constraint-ir"
SCHEMA_VERSION = 2


def utc_export_time() -> str:
    """Return an RFC 3339 UTC timestamp using the contract's ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class RawConstraintIR:
    """One Blender constraint and its unchanged, serializable parameters."""

    stack_index: int
    name: str
    constraint_type: str
    target_object_name: str
    target_bone_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    references: dict[str, Any] = field(default_factory=dict)
    custom_properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "stackIndex": self.stack_index,
            "name": self.name,
            "constraintType": self.constraint_type,
            "targetObjectName": self.target_object_name,
            "targetBoneName": self.target_bone_name,
            "parameters": self.parameters,
            "references": self.references,
        }
        if self.custom_properties:
            result["customProperties"] = self.custom_properties
        return result


@dataclass
class MCHBindingIR:
    """A generated MCH sidecar bound to its original source bone."""

    source_bone: str
    mch_bone: str
    constraint: RawConstraintIR

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceBone": self.source_bone,
            "mchBone": self.mch_bone,
            "constraint": self.constraint.to_dict(),
        }


@dataclass
class AuxBoneIR:
    """An Aux bone identified by its persistent HoTools bone metadata."""

    bone_name: str
    aux_type: str
    source_bones: list[str] = field(default_factory=list)
    constraint_names: list[str] = field(default_factory=list)
    involved_bones: list[str] = field(default_factory=list)
    constraints: list[RawConstraintIR] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "boneName": self.bone_name,
            "auxType": self.aux_type,
            "sourceBones": self.source_bones,
            "constraintNames": self.constraint_names,
            "involvedBones": self.involved_bones,
            "constraints": [constraint.to_dict() for constraint in self.constraints],
        }


@dataclass
class KnownConstraintIR:
    """A raw constraint claimed by one generated rig relation."""

    owner_bone: str
    relation_type: str
    constraint: RawConstraintIR
    aux_bone: str = ""
    aux_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {
            "ownerBone": self.owner_bone,
            "relationType": self.relation_type,
            "constraint": self.constraint.to_dict(),
        }
        if self.aux_bone:
            result["auxBone"] = self.aux_bone
        if self.aux_type:
            result["auxType"] = self.aux_type
        return result


@dataclass
class UnknownConstraintIR:
    """A raw constraint not claimed by the known MCH/Aux relation graph."""

    owner_bone: str
    constraint: RawConstraintIR
    reason: str = "未被已知 Rig 关系认领"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerBone": self.owner_bone,
            "reason": self.reason,
            "constraint": self.constraint.to_dict(),
        }


@dataclass
class RigConstraintIR:
    """Top-level, platform-neutral snapshot of one armature's rig relations."""

    armature_name: str
    mch_enabled_bones: list[str] = field(default_factory=list)
    mch_bindings: list[MCHBindingIR] = field(default_factory=list)
    aux_bones: list[AuxBoneIR] = field(default_factory=list)
    known_constraints: list[KnownConstraintIR] = field(default_factory=list)
    unknown_constraints: list[UnknownConstraintIR] = field(default_factory=list)
    export_time: str = field(default_factory=utc_export_time)

    def is_empty(self) -> bool:
        return not (
            self.mch_enabled_bones
            or self.mch_bindings
            or self.aux_bones
            or self.known_constraints
            or self.unknown_constraints
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "schemaVersion": SCHEMA_VERSION,
            "exportTime": self.export_time,
            "armatureName": self.armature_name,
            "mchEnabledBones": self.mch_enabled_bones,
            "mchBindings": [binding.to_dict() for binding in self.mch_bindings],
            "auxBones": [aux_bone.to_dict() for aux_bone in self.aux_bones],
            "knownConstraints": [
                constraint.to_dict() for constraint in self.known_constraints
            ],
            "unknownConstraints": [
                constraint.to_dict() for constraint in self.unknown_constraints
            ],
        }
