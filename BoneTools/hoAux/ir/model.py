"""Pure-Python data model for a HoAux Source IR snapshot."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceEdge:
    relation: str
    resource_key: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceRecord:
    resource_key: str
    resource_kind: str
    provenance: dict[str, Any] = field(default_factory=dict)
    owns: list[str] = field(default_factory=list)
    uses: list[ResourceEdge] = field(default_factory=list)
    used_by: list[ResourceEdge] = field(default_factory=list)
    provides_capabilities: list[str] = field(default_factory=list)
    requires_capabilities: list[str] = field(default_factory=list)
    blender_binding: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "RESOLVED"


@dataclass
class HoAuxSourceIR:
    rig_id: str
    armature_name: str
    resources: list[ResourceRecord] = field(default_factory=list)
    schema: str = "com.hotools.hoaux.source-ir"
    schema_version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
