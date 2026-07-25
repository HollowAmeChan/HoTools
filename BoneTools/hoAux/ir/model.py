"""Pure-Python data model for a HoAux Source IR snapshot."""

from dataclasses import dataclass, field
from typing import Any


SCHEMA_ID = "com.hotools.hoaux.source-ir"
SCHEMA_VERSION = 1
RESOURCE_KINDS = frozenset(
    {
        "BONE",
        "BONE_COLLECTION",
        "CONSTRAINT",
        "DRIVER",
        "DRIVER_VARIABLE",
        "EXPORT_ENDPOINT",
        "MODULE",
        "PIPELINE",
    }
)
RESOURCE_STATUSES = frozenset({"RESOLVED", "UNRESOLVED", "UNSUPPORTED"})


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


def derive_capabilities(resource) -> list[str]:
    kind = resource.resource_kind
    payload = resource.payload
    capabilities = set()

    if kind == "CONSTRAINT":
        constraint_type = payload.get("type")
        if constraint_type:
            capabilities.add(f"CONSTRAINT:{constraint_type}")
        for field_name in ("ownerSpace", "targetSpace"):
            value = payload.get(field_name)
            if value:
                capabilities.add(f"SPACE:{value}")
        if payload.get("headTail") == 1.0:
            capabilities.add("TARGET_POINT:TAIL")
        if constraint_type == "STRETCH_TO":
            keep_axis = payload.get("keepAxis")
            volume = payload.get("volume")
            if keep_axis:
                capabilities.add(f"STRETCH:{keep_axis}")
            if volume:
                capabilities.add(f"STRETCH:{volume}")
    elif kind == "DRIVER":
        capabilities.add(f"DRIVER:{payload.get('type', 'UNKNOWN')}")
        if payload.get("expression"):
            capabilities.add("DRIVER:SCRIPTED_EXPRESSION")
    elif kind == "DRIVER_VARIABLE":
        variable_type = payload.get("type")
        if variable_type:
            capabilities.add(f"DRIVER_VARIABLE:{variable_type}")
        transform_space = payload.get("transformSpace")
        if transform_space:
            capabilities.add(f"DRIVER_TARGET:{transform_space}")
    elif kind == "BONE_COLLECTION":
        capabilities.add("ORGANIZATION:BONE_COLLECTION")
        if payload.get("parentCollectionKey"):
            capabilities.add("ORGANIZATION:NESTED_COLLECTION")

    return sorted(capabilities)


def build_reverse_edges(resources) -> None:
    by_key = {resource.resource_key: resource for resource in resources}
    for resource in resources:
        resource.used_by.clear()
    for resource in resources:
        for edge in resource.uses:
            target = by_key.get(edge.resource_key)
            if target is None:
                continue
            target.used_by.append(
                ResourceEdge(
                    relation=edge.relation,
                    resource_key=resource.resource_key,
                    details=dict(edge.details),
                )
            )


def dependency_closure(resources, roots) -> set[str]:
    by_key = {resource.resource_key: resource for resource in resources}
    pending = list(roots)
    result = set()
    while pending:
        key = pending.pop()
        if key in result:
            continue
        result.add(key)
        resource = by_key.get(key)
        if resource is None:
            continue
        pending.extend(resource.owns)
        pending.extend(edge.resource_key for edge in resource.uses)
    return result
