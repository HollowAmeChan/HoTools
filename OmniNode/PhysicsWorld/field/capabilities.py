"""Physics World 共享 Field capability 与 WindV0 创作 schema。"""

from __future__ import annotations

from .names import (
    AIR_VELOCITY_CHANNEL_ID,
    FIELD_CAPABILITY_ID,
    FIELD_OBJECT_TAG,
    WIND_GENERATOR_ID,
)
from .schema import FIELD_RNA_FIELDS


_PROPERTY_SEMANTIC_TYPES = {
    "bool": "bool",
    "enum": "enum",
    "float": "float",
    "int": "int",
    "string": "string",
}


def _schema_capability_fields() -> list[dict]:
    result: list[dict] = []
    for declaration in FIELD_RNA_FIELDS:
        name = str(declaration.get("name") or "")
        property_kind = str(declaration.get("property") or "")
        kwargs = dict(declaration.get("kwargs") or {})
        field = {
            "name": name,
            "type": _PROPERTY_SEMANTIC_TYPES[property_kind],
            "default": kwargs.get("default"),
            "explicit_property": f"Object.hotools_field.{name}",
            "rna": kwargs,
            "update_policy": str(declaration.get("update_policy") or "场规格签名"),
        }
        if property_kind == "enum":
            field["values"] = [str(item[0]) for item in kwargs.get("items", ())]
        result.append(field)
    return result


def _enum_values(field_name: str) -> tuple[str, ...]:
    declaration = next(
        field for field in FIELD_RNA_FIELDS if field.get("name") == field_name
    )
    return tuple(
        str(item[0]) for item in declaration.get("kwargs", {}).get("items", ())
    )


FIELD_AIR_VELOCITY_CAPABILITY = {
    "capability_id": FIELD_CAPABILITY_ID,
    "display_name": "空气速度场",
    "semantic_owner": "physicsWorld.field 共享能力",
    "explicit_storage": "Object.hotools_field",
    "implicit_object_tag": FIELD_OBJECT_TAG,
    "channel_id": AIR_VELOCITY_CHANNEL_ID,
    "rank": "vector",
    "unit": "m/s",
    "value_space": "world",
    "source_kinds": ("analytic",),
    "generator_ids": (WIND_GENERATOR_ID,),
    "volume_shapes": _enum_values("shape"),
    "sample_modes": ("point", "batch"),
    "sample_phase": "pre_substep",
    "status": "preview_ready_no_active_consumer",
    "attenuation_policy": "V0 临时由 Volume 权重乘到 raw wind；最终所有权待冻结",
    "fields": _schema_capability_fields(),
}


FIELD_CAPABILITIES = {
    FIELD_CAPABILITY_ID: FIELD_AIR_VELOCITY_CAPABILITY,
}


__all__ = ["FIELD_AIR_VELOCITY_CAPABILITY", "FIELD_CAPABILITIES"]
