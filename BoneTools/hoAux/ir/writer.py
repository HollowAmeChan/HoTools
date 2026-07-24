"""Deterministic HoAux Source IR writer."""

import json

from .model import HoAuxSourceIR, ResourceEdge, ResourceRecord


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
