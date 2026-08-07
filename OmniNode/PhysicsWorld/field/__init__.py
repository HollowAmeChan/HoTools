"""Physics World 的公共 Field 领域包。"""

from __future__ import annotations

from importlib import import_module


COMPONENT_MODULE = {
    "component_id": "field",
    "kind": "core",
    "depends_on": ("collision",),
    "capabilities": ".capabilities:FIELD_CAPABILITIES",
    "blender_properties": ".properties:FIELD_BLENDER_PROPERTIES",
    "scope_collectors": (
        ".implicit_objects:collect_scope_field_specs",
        ".debug_draw:begin_field_runtime_debug_evaluation",
    ),
    "world_restart_handlers": (
        ".debug_draw:dispose_field_runtime_debug_draw_for_world",
    ),
    "world_dispose_handlers": (
        ".debug_draw:dispose_field_runtime_debug_draw_for_world",
    ),
    "blender_lifecycle": ".debug_draw",
}


_EXPORTS = {
    "AIR_VELOCITY_CHANNEL_ID": ".names",
    "FIELD_TYPE_WIND": ".names",
    "FIELD_TYPES_V0": ".names",
    "FIELD_CHANNELS_V0": ".channels",
    "FIELD_CHANNEL_REGISTRY_V0": ".channels",
    "FieldChannelDescriptorV0": ".channels",
    "FIELD_AIR_VELOCITY_CAPABILITY": ".capabilities",
    "FIELD_CAPABILITIES": ".capabilities",
    "FIELD_BLENDER_PROPERTIES": ".properties",
    "FIELD_NATIVE_RUNTIME_CACHE_KEY_V1": ".names",
    "FIELD_OBJECT_TAG": ".names",
    "FieldDiagnosticV0": ".diagnostics",
    "FieldPointSampleV0": ".sampling",
    "FieldSampleBatchV0": ".sampling",
    "FieldSampleStatsV0": ".sampling",
    "FieldScopeV0": ".specs",
    "FieldSnapshotV0": ".specs",
    "FieldSpecV0": ".specs",
    "NativeFieldRuntimeV1": ".native",
    "PG_Hotools_Field": ".properties",
    "VolumeSpecV0": ".specs",
    "WindPayloadV0": ".specs",
    "build_field_snapshot_v0": ".specs",
    "build_field_channel_visualization_v0": ".visualization",
    "collect_scope_field_specs": ".implicit_objects",
    "ensure_field_id_v0": ".properties",
    "sample_air_velocity_at_v0": ".sampling",
    "sample_air_velocity_reference_at_v0": ".sampling",
    "sample_air_velocity_v0": ".sampling",
    "sample_volume_weight_v0": ".volume",
    "sample_volume_weight_reference_v0": ".volume",
    "sample_volume_weights_v0": ".volume",
    "sample_wind_raw_v0": ".wind",
    "sample_wind_raw_reference_v0": ".wind",
    "field_channel_descriptor_v0": ".channels",
    "field_channel_reports_v0": ".channels",
    "vector_value_noise4_reference_v0": ".wind",
    "vector_value_noise4_v0": ".wind",
    "wind_direction_world_v0": ".volume",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
