"""Preserve Blender RNA pointer and collection facts without engine mapping."""

from collections.abc import Mapping
from typing import Any

from .values import _UNSERIALIZABLE, json_value
from .parameters import _NON_PARAMETER_PROPERTIES


def capture_references(constraint: Any) -> dict[str, Any]:
    """Preserve additional RNA pointer/collection facts without engine mapping."""
    rna = getattr(constraint, "bl_rna", None)
    properties = getattr(rna, "properties", None)
    if properties is None:
        if getattr(constraint, "type", "") == "ARMATURE":
            return {"targets": [{"rnaType": "ArmatureConstraintTarget", "properties": {
                "target": None if getattr(t, "target", None) is None else {"name": str(getattr(t.target, "name", "")), "rnaType": "Object"},
                "subtarget": str(getattr(t, "subtarget", "")), "weight": getattr(t, "weight", 0.0),
            }} for t in getattr(constraint, "targets", ())]}
        return {}

    result = {}
    for prop in properties:
        identifier = str(getattr(prop, "identifier", ""))
        if (
            not identifier
            or identifier in _NON_PARAMETER_PROPERTIES
            or getattr(prop, "type", "") not in {"POINTER", "COLLECTION"}
            or not hasattr(constraint, identifier)
        ):
            continue
        try:
            value = getattr(constraint, identifier)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        serialized = (
            reference_collection(value)
            if getattr(prop, "type", "") == "COLLECTION"
            else reference_value(value)
        )
        if serialized is not _UNSERIALIZABLE:
            result[identifier] = serialized
    return dict(sorted(result.items()))


def reference_collection(
    value: Any,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    """Serialize an RNA collection before treating it as an RNA struct."""
    if value is None:
        return []
    if depth > 4:
        return _UNSERIALIZABLE
    seen = set() if seen is None else seen
    value_id = id(value)
    if value_id in seen:
        return _UNSERIALIZABLE
    try:
        iterator = iter(value)
    except TypeError:
        return _UNSERIALIZABLE

    seen.add(value_id)
    result = []
    try:
        for item in iterator:
            converted = reference_value(
                item,
                depth=depth + 1,
                seen=seen,
            )
            if converted is _UNSERIALIZABLE:
                return _UNSERIALIZABLE
            result.append(converted)
    finally:
        seen.remove(value_id)
    return result


def reference_value(
    value: Any,
    *,
    depth: int = 0,
    seen: set[int] | None = None,
) -> Any:
    """Serialize an RNA reference by stable identity or nested RNA fields."""
    if value is None:
        return None
    if depth > 4:
        return _UNSERIALIZABLE

    seen = set() if seen is None else seen
    value_id = id(value)
    if value_id in seen:
        return _UNSERIALIZABLE

    rna = getattr(value, "bl_rna", None)
    rna_type = str(getattr(rna, "identifier", ""))
    name_full = getattr(value, "name_full", None)
    if name_full is not None:
        result = {"name": str(name_full)}
        if rna_type:
            result["rnaType"] = rna_type
        return result

    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            converted = reference_value(
                item,
                depth=depth + 1,
                seen=seen,
            )
            if converted is not _UNSERIALIZABLE:
                result[str(key)] = converted
        return result
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return _UNSERIALIZABLE

    properties = getattr(rna, "properties", None)
    if properties is not None:
        seen.add(value_id)
        fields = {}
        try:
            for prop in properties:
                identifier = str(getattr(prop, "identifier", ""))
                if (
                    not identifier
                    or identifier == "rna_type"
                    or not hasattr(value, identifier)
                ):
                    continue
                try:
                    item = getattr(value, identifier)
                except (AttributeError, ReferenceError, RuntimeError):
                    continue
                if getattr(prop, "type", "") == "COLLECTION":
                    converted = reference_collection(
                        item,
                        depth=depth + 1,
                        seen=seen,
                    )
                elif getattr(prop, "type", "") == "POINTER":
                    converted = reference_value(
                        item,
                        depth=depth + 1,
                        seen=seen,
                    )
                else:
                    converted = json_value(item)
                if converted is not _UNSERIALIZABLE:
                    fields[identifier] = converted
        finally:
            seen.remove(value_id)
        result = {"properties": dict(sorted(fields.items()))}
        if rna_type:
            result["rnaType"] = rna_type
        return result

    return reference_collection(value, depth=depth, seen=seen)
