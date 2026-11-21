"""Capture writable raw constraint parameters and custom properties."""

from typing import Any
from .values import _UNSERIALIZABLE, json_value


_NON_PARAMETER_PROPERTIES = {
        "rna_type",
        "name",
        "type",
        "target",
        "subtarget",
        "is_valid",
        "error_location",
        "error_rotation",
        "show_expanded",
        # Blender UI/transient flags are not part of the constraint result.
        "active",
        "set_inverse_pending",
    }

_COMMON_FALLBACK_PARAMETERS = (
        "influence",
        "mute",
        "owner_space",
        "target_space",
    )

_TYPE_FALLBACK_PARAMETERS = {
        "ARMATURE": (
            "use_deform_preserve_volume", "use_bone_envelopes", "use_current_location",
        ),
        "DAMPED_TRACK": ("head_tail", "use_bbone_shape", "track_axis"),
        "LOCKED_TRACK": ("head_tail", "use_bbone_shape", "track_axis", "lock_axis"),
        "COPY_ROTATION": (
            "euler_order",
            "mix_mode",
            "use_x",
            "use_y",
            "use_z",
            "invert_x",
            "invert_y",
            "invert_z",
        ),
        "COPY_LOCATION": (
            "head_tail",
            "use_bbone_shape",
            "use_offset",
            "use_x",
            "use_y",
            "use_z",
            "invert_x",
            "invert_y",
            "invert_z",
        ),
        "COPY_SCALE": (
            "power",
            "use_offset",
            "use_add",
            "use_make_uniform",
            "use_x",
            "use_y",
            "use_z",
        ),
        "COPY_TRANSFORMS": (
            "head_tail",
            "use_bbone_shape",
            "mix_mode",
            "remove_target_shear",
        ),
        "STRETCH_TO": (
            "head_tail",
            "use_bbone_shape",
            "rest_length",
            "bulge",
            "volume",
            "keep_axis",
            "use_original_length",
            "use_bulge_min",
            "use_bulge_max",
            "bulge_min",
            "bulge_max",
            "bulge_smooth",
        ),
        "CHILD_OF": (
            "inverse_matrix",
            "use_location_x",
            "use_location_y",
            "use_location_z",
            "use_rotation_x",
            "use_rotation_y",
            "use_rotation_z",
            "use_scale_x",
            "use_scale_y",
            "use_scale_z",
        ),
    }


def capture_parameters(constraint: Any) -> dict[str, Any]:
    names = _rna_parameter_names(constraint)
    if names is None:
        names = set(_COMMON_FALLBACK_PARAMETERS)
        names.update(
            _TYPE_FALLBACK_PARAMETERS.get(
                str(getattr(constraint, "type", "")),
                (),
            )
        )

    result = {}
    for name in sorted(names):
        if name in _NON_PARAMETER_PROPERTIES or not hasattr(constraint, name):
            continue
        value = json_value(getattr(constraint, name))
        if value is not _UNSERIALIZABLE:
            result[name] = value
    return result


def _rna_parameter_names(constraint: Any) -> set[str] | None:
    rna = getattr(constraint, "bl_rna", None)
    properties = getattr(rna, "properties", None)
    if properties is None:
        return None

    names = set()
    for prop in properties:
        identifier = str(getattr(prop, "identifier", ""))
        if not identifier or bool(getattr(prop, "is_readonly", False)):
            continue
        if getattr(prop, "type", "") in {"POINTER", "COLLECTION"}:
            continue
        names.add(identifier)
    return names


def capture_custom_properties(constraint: Any) -> dict[str, Any]:
    items = getattr(constraint, "items", None)
    if not callable(items):
        return {}
    try:
        raw_items = items()
    except (AttributeError, TypeError, RuntimeError):
        return {}

    result = {}
    for key, value in raw_items:
        serialized = json_value(value)
        if serialized is not _UNSERIALIZABLE:
            result[str(key)] = serialized
    return dict(sorted(result.items()))
