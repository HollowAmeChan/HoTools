"""MagicaCloth2 mesh cloth parameter presets for OmniNode.

The JSON files in ``mc2_presets`` are copied from:
``D:/Unity_Fork/MagicaCloth2/Runtime/Res/Preset``.
"""

from __future__ import annotations

import json
from pathlib import Path

from .....PropertyCurve import float_curve_payload
from .constants import MC2SystemConstants


_PRESET_DIR = Path(__file__).parent.parent / "mc2_presets"

_PRESET_FILES = (
    ("Accessory", "MC2_Preset_Accessory.json"),
    ("Cape", "MC2_Preset_Cape.json"),
    ("FrontHair", "MC2_Preset_FrontHair.json"),
    ("LongHair", "MC2_Preset_LongHair.json"),
    ("ShortHair", "MC2_Preset_ShortHair.json"),
    ("Skirt", "MC2_Preset_Skirt.json"),
    ("SoftSkirt", "MC2_Preset_SoftSkirt.json"),
    ("MiddleSpring", "MC2_Preset_MiddleSpring.json"),
    ("SoftSpring", "MC2_Preset_SoftSpring.json"),
    ("HardSpring", "MC2_Preset_HardSpring.json"),
    ("Tail", "MC2_Preset_Tail.json"),
)


def _float(value, fallback=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _int(value, fallback=0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _bool(value, fallback=False) -> bool:
    if value is None:
        return bool(fallback)
    return bool(value)


def _unity_vector_to_blender(value, fallback=(0.0, 0.0, -1.0)) -> tuple[float, float, float]:
    if not isinstance(value, dict):
        return tuple(float(item) for item in fallback)
    x = _float(value.get("x"), fallback[0])
    y = _float(value.get("y"), fallback[2])
    z = _float(value.get("z"), -fallback[1])
    return (x, -z, y)


def _curve_value(data, fallback=0.0) -> float:
    if not isinstance(data, dict):
        return _float(data, fallback)
    return _float(data.get("value"), fallback)


def _unity_curve_weight(key, side: str) -> float:
    weighted_mode = _int(key.get("weightedMode"), 0)
    has_weight = bool(weighted_mode & (1 if side == "in" else 2))
    weight_key = "inWeight" if side == "in" else "outWeight"
    default_weight = 1.0 / 3.0
    weight = _float(key.get(weight_key), default_weight) if has_weight else default_weight
    return max(weight, 0.0)


def _unity_curve_points(curve_data) -> list[dict]:
    if not isinstance(curve_data, dict):
        return []
    keys = curve_data.get("m_Curve")
    if not isinstance(keys, list):
        return []

    points = []
    for index, key in enumerate(keys):
        if not isinstance(key, dict):
            continue
        x = max(0.0, min(1.0, _float(key.get("time"), 0.0)))
        y = _float(key.get("value"), 0.0)
        point = {
            "x": x,
            "y": y,
            "interpolation": "BEZIER",
            "left_handle_type": "COORD",
            "right_handle_type": "COORD",
            "left_handle_x": 0.0,
            "left_handle_y": 0.0,
            "right_handle_x": 0.0,
            "right_handle_y": 0.0,
        }

        if index > 0 and isinstance(keys[index - 1], dict):
            previous_x = max(0.0, min(1.0, _float(keys[index - 1].get("time"), 0.0)))
            dx = max(x - previous_x, 0.0)
            weight = _unity_curve_weight(key, "in")
            handle_dx = -dx * weight
            point["left_handle_x"] = handle_dx
            point["left_handle_y"] = _float(key.get("inSlope"), 0.0) * handle_dx

        if index + 1 < len(keys) and isinstance(keys[index + 1], dict):
            next_x = max(0.0, min(1.0, _float(keys[index + 1].get("time"), 1.0)))
            dx = max(next_x - x, 0.0)
            weight = _unity_curve_weight(key, "out")
            handle_dx = dx * weight
            point["right_handle_x"] = handle_dx
            point["right_handle_y"] = _float(key.get("outSlope"), 0.0) * handle_dx

        points.append(point)

    return points


def _curve_payload(data, fallback_multiplier=1.0) -> dict:
    if not isinstance(data, dict) or not _bool(data.get("useCurve"), False):
        value = _float(fallback_multiplier, 1.0)
        return float_curve_payload(
            (
                {"x": 0.0, "y": value, "interpolation": "LINEAR"},
                {"x": 1.0, "y": value, "interpolation": "LINEAR"},
            ),
            value=1.0,
            interpolation="LINEAR",
            extend="CLAMP",
        )

    points = _unity_curve_points(data.get("curve"))
    interpolation = "BEZIER" if points else "LINEAR"
    return float_curve_payload(
        points or (
            {"x": 0.0, "y": 1.0, "interpolation": "LINEAR"},
            {"x": 1.0, "y": 1.0, "interpolation": "LINEAR"},
        ),
        value=1.0,
        interpolation=interpolation,
        extend="CLAMP",
    )


def _check_slider_value(data, fallback, disabled=-1.0) -> float:
    if not isinstance(data, dict):
        return _float(data, fallback)
    if not _bool(data.get("use"), True):
        return float(disabled)
    return _float(data.get("value"), fallback)


def _constraint(data, key) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _convert_preset(label: str, source: dict) -> dict:
    damping = _constraint(source, "damping")
    radius = _constraint(source, "radius")
    inertia = _constraint(source, "inertiaConstraint")
    tether = _constraint(source, "tetherConstraint")
    distance = _constraint(source, "distanceConstraint")
    distance_stiffness = _constraint(distance, "stiffness")
    bending = _constraint(source, "triangleBendingConstraint")
    angle_restore = _constraint(source, "angleRestorationConstraint")
    angle_restore_stiffness = _constraint(angle_restore, "stiffness")
    angle_limit = _constraint(source, "angleLimitConstraint")
    angle_limit_value = _constraint(angle_limit, "limitAngle")
    motion = _constraint(source, "motionConstraint")
    max_distance = _constraint(motion, "maxDistance")
    backstop_distance = _constraint(motion, "backstopDistance")
    collider = _constraint(source, "colliderCollisionConstraint")

    collider_mode = _int(collider.get("mode"), 1)
    values = {
        "enabled": True,
        "reset": False,
        "gravity_dir": _unity_vector_to_blender(source.get("gravityDirection")),
        "gravity_power": _float(source.get("gravity"), 9.8),
        "gravity_falloff": _float(source.get("gravityFalloff"), 0.0),
        "stablization_time_after_reset": _float(source.get("stablizationTimeAfterReset"), 0.1),
        "blend_weight": _float(source.get("blendWeight"), 1.0),
        "damping": _curve_value(damping, 0.2),
        "damping_curve": _curve_payload(damping),
        "use_tether": "tetherConstraint" in source,
        "tether_compression": _float(
            tether.get("distanceCompression"),
            MC2SystemConstants.TETHER_COMPRESSION_LIMIT,
        ),
        "use_distance": "distanceConstraint" in source,
        "distance_stiffness": _curve_value(distance_stiffness, 1.0),
        "distance_stiffness_curve": _curve_payload(distance_stiffness),
        "use_bend": "triangleBendingConstraint" in source,
        "bend_stiffness": _float(bending.get("stiffness"), 0.5),
        "bend_stiffness_curve": _curve_payload(None),
        "use_angle_restoration": _bool(angle_restore.get("useAngleRestoration"), True),
        "angle_restoration_stiffness": _curve_value(angle_restore_stiffness, 0.2),
        "angle_restoration_stiffness_curve": _curve_payload(angle_restore_stiffness),
        "angle_restoration_velocity_attenuation": _float(
            angle_restore.get("velocityAttenuation"),
            MC2SystemConstants.ANGLE_RESTORATION_VELOCITY_ATTENUATION,
        ),
        "angle_restoration_velocity_attenuation_curve": _curve_payload(None),
        "angle_restoration_gravity_falloff": _float(
            angle_restore.get("gravityFalloff"),
            MC2SystemConstants.ANGLE_RESTORATION_GRAVITY_FALLOFF,
        ),
        "use_angle_limit": _bool(angle_limit.get("useAngleLimit"), False),
        "angle_limit": _curve_value(angle_limit_value, 0.0),
        "angle_limit_curve": _curve_payload(angle_limit_value),
        "angle_limit_stiffness": _float(angle_limit.get("stiffness"), 1.0),
        "collision_radius": _curve_value(radius, 0.0),
        "anchor_inertia": _float(inertia.get("anchorInertia"), MC2SystemConstants.ANCHOR_INERTIA),
        "world_inertia": _float(inertia.get("worldInertia"), MC2SystemConstants.WORLD_INERTIA),
        "movement_inertia_smoothing": _float(
            inertia.get("movementInertiaSmoothing"),
            MC2SystemConstants.MOVEMENT_INERTIA_SMOOTHING,
        ),
        "local_inertia": _float(inertia.get("localInertia"), MC2SystemConstants.LOCAL_INERTIA),
        "depth_inertia": _float(inertia.get("depthInertia"), MC2SystemConstants.DEPTH_INERTIA),
        "centrifugal": _float(
            inertia.get("centrifualAcceleration"),
            MC2SystemConstants.CENTRIFUGAL_ACCELERATION,
        ),
        "movement_speed_limit": _check_slider_value(
            inertia.get("movementSpeedLimit"),
            MC2SystemConstants.MOVEMENT_SPEED_LIMIT,
        ),
        "rotation_speed_limit": _check_slider_value(
            inertia.get("rotationSpeedLimit"),
            MC2SystemConstants.ROTATION_SPEED_LIMIT,
        ),
        "local_movement_speed_limit": _check_slider_value(
            inertia.get("localMovementSpeedLimit"),
            MC2SystemConstants.LOCAL_MOVEMENT_SPEED_LIMIT,
        ),
        "local_rotation_speed_limit": _check_slider_value(
            inertia.get("localRotationSpeedLimit"),
            MC2SystemConstants.LOCAL_ROTATION_SPEED_LIMIT,
        ),
        "particle_speed_limit": _check_slider_value(
            inertia.get("particleSpeedLimit"),
            MC2SystemConstants.PARTICLE_SPEED_LIMIT,
        ),
        "teleport_mode": _int(inertia.get("teleportMode"), 0),
        "teleport_distance": _float(inertia.get("teleportDistance"), MC2SystemConstants.TELEPORT_DISTANCE),
        "teleport_rotation": _float(inertia.get("teleportRotation"), MC2SystemConstants.TELEPORT_ROTATION),
        "animation_pose_ratio": _float(
            source.get("animationPoseRatio", source.get("animationBlendRatio")),
            0.0,
        ),
        "use_max_distance": _bool(motion.get("useMaxDistance"), False),
        "max_distance": _curve_value(max_distance, 0.0),
        "max_distance_curve": _curve_payload(max_distance),
        "use_backstop": _bool(motion.get("useBackstop"), False),
        "backstop_radius": _float(motion.get("backstopRadius"), 0.0),
        "backstop_distance": _curve_value(backstop_distance, 0.0),
        "backstop_distance_curve": _curve_payload(backstop_distance),
        "motion_stiffness": _float(motion.get("stiffness"), 1.0),
        "normal_axis": _int(source.get("normalAxis"), 1),
        "use_collider_collision": collider_mode != 0,
        "collider_friction": _float(collider.get("friction"), 0.05),
        "collider_collision_mode": collider_mode,
    }

    return {
        "name": f"MC2 {label}",
        "description": f"MagicaCloth2 mesh cloth preset: {label}",
        "values": values,
    }


_SETTING_PRESET_KEYS = {
    "enabled",
    "blend_weight",
    "damping",
    "damping_curve",
    "use_tether",
    "tether_compression",
    "use_distance",
    "distance_stiffness",
    "distance_stiffness_curve",
    "use_bend",
    "bend_stiffness",
    "bend_stiffness_curve",
    "use_angle_restoration",
    "angle_restoration_stiffness",
    "angle_restoration_stiffness_curve",
    "angle_restoration_velocity_attenuation",
    "angle_restoration_velocity_attenuation_curve",
    "angle_restoration_gravity_falloff",
    "use_angle_limit",
    "angle_limit",
    "angle_limit_curve",
    "angle_limit_stiffness",
    "collision_radius",
    "use_max_distance",
    "max_distance",
    "max_distance_curve",
    "use_backstop",
    "backstop_radius",
    "backstop_distance",
    "backstop_distance_curve",
    "motion_stiffness",
}

_SOLVER_PRESET_KEYS = {
    "enabled",
    "reset",
    "gravity_dir",
    "gravity_power",
    "gravity_falloff",
    "stablization_time_after_reset",
    "anchor_inertia",
    "world_inertia",
    "movement_inertia_smoothing",
    "local_inertia",
    "depth_inertia",
    "centrifugal",
    "movement_speed_limit",
    "rotation_speed_limit",
    "local_movement_speed_limit",
    "local_rotation_speed_limit",
    "particle_speed_limit",
    "teleport_mode",
    "teleport_distance",
    "teleport_rotation",
    "normal_axis",
    "animation_pose_ratio",
    "use_collider_collision",
    "collider_friction",
    "collider_collision_mode",
}


def _filter_preset_values(preset: dict, keys: set[str]) -> dict:
    return {
        "name": preset.get("name", ""),
        "description": preset.get("description", ""),
        "values": {
            key: value
            for key, value in (preset.get("values") or {}).items()
            if key in keys
        },
    }


def _load_source(filename: str) -> dict | None:
    path = _PRESET_DIR / filename
    try:
        with path.open("r", encoding="utf-8") as stream:
            source = json.load(stream)
    except Exception:
        return None
    return source if isinstance(source, dict) else None


def _load_presets() -> tuple[dict, ...]:
    presets = []
    for label, filename in _PRESET_FILES:
        source = _load_source(filename)
        if source is not None:
            presets.append(_convert_preset(label, source))
    return tuple(presets)


MC2_MESH_CLOTH_PRESETS = _load_presets()
MC2_MESH_CLOTH_SETTING_PRESETS = tuple(
    _filter_preset_values(preset, _SETTING_PRESET_KEYS)
    for preset in MC2_MESH_CLOTH_PRESETS
)
MC2_MESH_CLOTH_SOLVER_PRESETS = tuple(
    _filter_preset_values(preset, _SOLVER_PRESET_KEYS)
    for preset in MC2_MESH_CLOTH_PRESETS
)
