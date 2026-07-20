"""Official MagicaCloth2 presets adapted to Profile and Task authoring.

The JSON files in ``presets`` are copied without modification from
``MagicaCloth2/Runtime/Res/Preset``. This module translates source fields into
the unified authoring vocabulary. Public Profile and Task nodes filter the same
named preset by their owned inputs, so applying both halves restores the source
configuration. Source self-collision thickness is not exposed as a second radius.
"""

from __future__ import annotations

import json
from pathlib import Path

from ......PropertyCurve import float_curve_payload


_PRESET_DIR = Path(__file__).with_name("presets")

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
    except (TypeError, ValueError):
        return float(fallback)


def _int(value, fallback=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def _bool(value, fallback=False) -> bool:
    if value is None:
        return bool(fallback)
    return bool(value)


def _unity_vector_to_blender(
    value,
    fallback=(0.0, 0.0, -1.0),
) -> tuple[float, float, float]:
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
            handle_dx = -max(x - previous_x, 0.0) * _unity_curve_weight(key, "in")
            point["left_handle_x"] = handle_dx
            point["left_handle_y"] = _float(key.get("inSlope"), 0.0) * handle_dx

        if index + 1 < len(keys) and isinstance(keys[index + 1], dict):
            next_x = max(0.0, min(1.0, _float(keys[index + 1].get("time"), 1.0)))
            handle_dx = max(next_x - x, 0.0) * _unity_curve_weight(key, "out")
            point["right_handle_x"] = handle_dx
            point["right_handle_y"] = _float(key.get("outSlope"), 0.0) * handle_dx

        points.append(point)
    return points


def _curve_payload(data) -> dict:
    if not isinstance(data, dict) or not _bool(data.get("useCurve"), False):
        points = (
            {"x": 0.0, "y": 1.0, "interpolation": "LINEAR"},
            {"x": 1.0, "y": 1.0, "interpolation": "LINEAR"},
        )
        return float_curve_payload(
            points,
            value=1.0,
            interpolation="LINEAR",
            extend="CLAMP",
        )

    points = _unity_curve_points(data.get("curve"))
    return float_curve_payload(
        points or (
            {"x": 0.0, "y": 1.0, "interpolation": "LINEAR"},
            {"x": 1.0, "y": 1.0, "interpolation": "LINEAR"},
        ),
        value=1.0,
        interpolation="BEZIER" if points else "LINEAR",
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
    distance_stiffness = _constraint(
        _constraint(source, "distanceConstraint"),
        "stiffness",
    )
    bending = _constraint(source, "triangleBendingConstraint")
    angle_restore = _constraint(source, "angleRestorationConstraint")
    angle_restore_stiffness = _constraint(angle_restore, "stiffness")
    angle_limit = _constraint(source, "angleLimitConstraint")
    angle_limit_value = _constraint(angle_limit, "limitAngle")
    motion = _constraint(source, "motionConstraint")
    max_distance = _constraint(motion, "maxDistance")
    backstop_distance = _constraint(motion, "backstopDistance")
    collider = _constraint(source, "colliderCollisionConstraint")
    collision_limit = _constraint(collider, "limitDistance")
    self_collision = _constraint(source, "selfCollisionConstraint")
    spring = _constraint(source, "springConstraint")
    wind = _constraint(source, "wind")

    self_mode = _int(self_collision.get("selfMode"), 0)
    sync_mode = _int(self_collision.get("syncMode"), 0)
    values = {
        "blend_weight": _float(source.get("blendWeight"), 1.0),
        "gravity_direction": _unity_vector_to_blender(source.get("gravityDirection")),
        "gravity": _float(source.get("gravity"), 5.0),
        "gravity_falloff": _float(source.get("gravityFalloff"), 0.0),
        "stabilization_time_after_reset": _float(source.get("stablizationTimeAfterReset"), 0.1),
        "normal_axis": _int(source.get("normalAxis"), 1),
        "animation_pose_ratio": _float(
            source.get("animationPoseRatio", source.get("animationBlendRatio")),
            0.0,
        ),
        "anchor_inertia": _float(inertia.get("anchorInertia"), 0.0),
        "world_inertia": _float(inertia.get("worldInertia"), 1.0),
        "movement_inertia_smoothing": _float(inertia.get("movementInertiaSmoothing"), 0.4),
        "movement_speed_limit": _check_slider_value(inertia.get("movementSpeedLimit"), 5.0),
        "rotation_speed_limit": _check_slider_value(inertia.get("rotationSpeedLimit"), 720.0),
        "local_inertia": _float(inertia.get("localInertia"), 1.0),
        "local_movement_speed_limit": _check_slider_value(inertia.get("localMovementSpeedLimit"), -1.0),
        "local_rotation_speed_limit": _check_slider_value(inertia.get("localRotationSpeedLimit"), -1.0),
        "depth_inertia": _float(inertia.get("depthInertia"), 0.0),
        "centrifugal_acceleration": _float(inertia.get("centrifualAcceleration"), 0.0),
        "particle_speed_limit": _check_slider_value(inertia.get("particleSpeedLimit"), 4.0),
        "teleport_mode": _int(inertia.get("teleportMode"), 0),
        "teleport_distance": _float(inertia.get("teleportDistance"), 0.5),
        "teleport_rotation": _float(inertia.get("teleportRotation"), 90.0),
        "damping": _curve_value(damping, 0.05),
        "damping_curve": _curve_payload(damping),
        "radius": _curve_value(radius, 0.02),
        "radius_curve": _curve_payload(radius),
        "tether_compression": _float(tether.get("distanceCompression"), 0.4),
        "distance_stiffness": _curve_value(distance_stiffness, 1.0),
        "distance_stiffness_curve": _curve_payload(distance_stiffness),
        "bending_stiffness": _float(bending.get("stiffness"), 1.0),
        "angle_restoration_enabled": _bool(angle_restore.get("useAngleRestoration"), True),
        "angle_restoration_stiffness": _curve_value(angle_restore_stiffness, 0.2),
        "angle_restoration_curve": _curve_payload(angle_restore_stiffness),
        "angle_restoration_velocity_attenuation": _float(angle_restore.get("velocityAttenuation"), 0.8),
        "angle_restoration_gravity_falloff": _float(angle_restore.get("gravityFalloff"), 0.0),
        "angle_limit_enabled": _bool(angle_limit.get("useAngleLimit"), False),
        "angle_limit": _curve_value(angle_limit_value, 60.0),
        "angle_limit_curve": _curve_payload(angle_limit_value),
        "angle_limit_stiffness": _float(angle_limit.get("stiffness"), 1.0),
        "max_distance_enabled": _bool(motion.get("useMaxDistance"), False),
        "max_distance": _curve_value(max_distance, 0.3),
        "max_distance_curve": _curve_payload(max_distance),
        "backstop_enabled": _bool(motion.get("useBackstop"), False),
        "backstop_radius": _float(motion.get("backstopRadius"), 10.0),
        "backstop_distance": _curve_value(backstop_distance, 0.0),
        "backstop_distance_curve": _curve_payload(backstop_distance),
        "motion_stiffness": _float(motion.get("stiffness"), 1.0),
        "collision_mode": _int(collider.get("mode"), 1),
        "collision_friction": _float(collider.get("friction"), 0.05),
        "collision_limit_distance": _curve_value(collision_limit, 0.05),
        "collision_limit_curve": _curve_payload(collision_limit),
        "self_collision_mode": 2 if self_mode == 2 else 0,
        "self_collision_interaction": sync_mode == 2,
        "cloth_mass": _float(self_collision.get("clothMass"), 0.0),
        "spring_enabled": _bool(spring.get("useSpring"), True),
        "spring_power": _float(spring.get("springPower"), 0.04),
        "spring_limit_distance": _float(spring.get("limitDistance"), 0.1),
        "spring_normal_limit_ratio": _float(spring.get("normalLimitRatio"), 1.0),
        "spring_noise": _float(spring.get("springNoise"), 0.0),
        "wind_influence": _float(wind.get("influence"), 1.0),
        "wind_frequency": _float(wind.get("frequency"), 1.0),
        "wind_turbulence": _float(wind.get("turbulence"), 1.0),
        "wind_blend": _float(wind.get("blend"), 0.7),
        "wind_synchronization": _float(wind.get("synchronization"), 0.7),
        "wind_depth_weight": _float(wind.get("depthWeight"), 0.0),
        "moving_wind": _float(wind.get("movingWind"), 0.0),
    }
    return {
        "name": f"MC2 {label}",
        "description": f"Official MagicaCloth2 particle preset: {label}",
        "values": values,
    }


def _load_source(filename: str) -> dict | None:
    path = _PRESET_DIR / filename
    try:
        with path.open("r", encoding="utf-8") as stream:
            source = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return None
    return source if isinstance(source, dict) else None


def _load_presets() -> tuple[dict, ...]:
    presets = []
    for label, filename in _PRESET_FILES:
        source = _load_source(filename)
        if source is not None:
            presets.append(_convert_preset(label, source))
    return tuple(presets)


MC2_PARTICLE_PRESETS = _load_presets()
