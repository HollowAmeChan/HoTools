"""Strict deterministic codec for HoAux Source IR."""

import json

from .model import (
    HoAuxSourceIR,
    RESOURCE_KINDS,
    RESOURCE_STATUSES,
    ResourceEdge,
    ResourceRecord,
    SCHEMA_ID,
    SCHEMA_VERSION,
)


class HoAuxIRParseError(ValueError):
    pass


def _required(data: dict, key: str, expected_type):
    if key not in data:
        raise HoAuxIRParseError(f"missing required field: {key}")
    value = data[key]
    if not isinstance(value, expected_type):
        raise HoAuxIRParseError(f"{key} must be {expected_type.__name__}")
    return value


def _edge_from_dict(data: dict) -> ResourceEdge:
    if not isinstance(data, dict):
        raise HoAuxIRParseError("edge must be an object")
    return ResourceEdge(
        relation=_required(data, "relation", str),
        resource_key=_required(data, "resourceKey", str),
        details=dict(data.get("details", {})),
    )


def _resource_from_dict(data: dict) -> ResourceRecord:
    if not isinstance(data, dict):
        raise HoAuxIRParseError("resource must be an object")
    kind = _required(data, "resourceKind", str)
    if kind not in RESOURCE_KINDS:
        raise HoAuxIRParseError(f"unknown resourceKind: {kind}")
    status = data.get("status", "RESOLVED")
    if status not in RESOURCE_STATUSES:
        raise HoAuxIRParseError(f"unknown resource status: {status}")
    return ResourceRecord(
        resource_key=_required(data, "resourceKey", str),
        resource_kind=kind,
        status=status,
        provenance=dict(data.get("provenance", {})),
        owns=list(data.get("owns", [])),
        uses=[_edge_from_dict(edge) for edge in data.get("uses", [])],
        used_by=[_edge_from_dict(edge) for edge in data.get("usedBy", [])],
        provides_capabilities=list(data.get("providesCapabilities", [])),
        requires_capabilities=list(data.get("requiresCapabilities", [])),
        blender_binding=dict(data.get("blenderBinding", {})),
        payload=dict(data.get("payload", {})),
    )


def parse_dict(data: dict) -> HoAuxSourceIR:
    if not isinstance(data, dict):
        raise HoAuxIRParseError("IR root must be an object")
    if _required(data, "schema", str) != SCHEMA_ID:
        raise HoAuxIRParseError("unsupported schema")
    if _required(data, "schemaVersion", int) != SCHEMA_VERSION:
        raise HoAuxIRParseError("unsupported schemaVersion")
    resources_data = _required(data, "resources", list)
    resources = [_resource_from_dict(item) for item in resources_data]
    keys = [resource.resource_key for resource in resources]
    if len(keys) != len(set(keys)):
        raise HoAuxIRParseError("duplicate resourceKey")
    return HoAuxSourceIR(
        schema=data["schema"],
        schema_version=data["schemaVersion"],
        rig_id=_required(data, "rigId", str),
        armature_name=_required(data, "armatureName", str),
        metadata=dict(data.get("metadata", {})),
        resources=resources,
    )


def parse_json(value: str) -> HoAuxSourceIR:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HoAuxIRParseError(str(exc)) from exc
    return parse_dict(data)


def _edge_to_dict(edge: ResourceEdge) -> dict:
    result = {
        "relation": edge.relation,
        "resourceKey": edge.resource_key,
    }
    if edge.details:
        result["details"] = edge.details
    return result


def _resource_to_dict(resource: ResourceRecord) -> dict:
    return {
        "resourceKey": resource.resource_key,
        "resourceKind": resource.resource_kind,
        "status": resource.status,
        "provenance": resource.provenance,
        "owns": list(resource.owns),
        "uses": [_edge_to_dict(edge) for edge in resource.uses],
        "usedBy": [_edge_to_dict(edge) for edge in resource.used_by],
        "providesCapabilities": list(resource.provides_capabilities),
        "requiresCapabilities": list(resource.requires_capabilities),
        "blenderBinding": resource.blender_binding,
        "payload": resource.payload,
    }


def to_dict(source_ir: HoAuxSourceIR) -> dict:
    return {
        "schema": source_ir.schema,
        "schemaVersion": source_ir.schema_version,
        "rigId": source_ir.rig_id,
        "armatureName": source_ir.armature_name,
        "metadata": source_ir.metadata,
        "resources": [_resource_to_dict(item) for item in source_ir.resources],
    }


def to_json(source_ir: HoAuxSourceIR, *, indent: int | None = 2) -> str:
    return json.dumps(
        to_dict(source_ir),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
    )
