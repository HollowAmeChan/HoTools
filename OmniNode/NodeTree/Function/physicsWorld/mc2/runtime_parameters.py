"""MC2 N2 runtime parameter ABI.

This module is the host/native boundary corresponding to MC2
``ClothSerializeData.GetClothParameters()``.  Authoring curves and scheduler
settings are deliberately absent from the packed representation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import json
from typing import Callable, Iterable

import numpy as np

from .names import MC2_SETUP_BONE_SPRING
from .parameters import (
    MC2_BONE_SPRING_COLLISION_FRICTION,
    MC2_BONE_SPRING_DISTANCE_STIFFNESS,
    MC2_BONE_SPRING_TETHER_COMPRESSION,
    MC2_DISTANCE_VELOCITY_ATTENUATION,
    MC2_TETHER_STRETCH_LIMIT,
    MC2CurveSpec,
    MC2ParticleProfileSpec,
    MC2SetupOptionsSpec,
    _thaw,
)


MC2_RUNTIME_PARAMETERS_ABI = 0
MC2_CURVE_SAMPLE_COUNT = 16

MC2_RUNTIME_FLOAT_FIELDS = (
    "gravity",
    "gravity_direction_x", "gravity_direction_y", "gravity_direction_z",
    "gravity_falloff", "stabilization_time_after_reset", "blend_weight",
    "rotational_interpolation", "root_rotation",
    "distance_culling_length", "distance_culling_fade_ratio",
    "anchor_inertia", "world_inertia", "movement_inertia_smoothing",
    "movement_speed_limit", "rotation_speed_limit", "local_inertia",
    "local_movement_speed_limit", "local_rotation_speed_limit", "depth_inertia",
    "centrifugal_acceleration", "particle_speed_limit",
    "teleport_distance", "teleport_rotation",
    "tether_compression_limit", "tether_stretch_limit",
    "distance_velocity_attenuation", "bending_stiffness",
    "angle_restoration_velocity_attenuation", "angle_restoration_gravity_falloff",
    "angle_limit_stiffness", "backstop_radius", "motion_stiffness",
    "collision_dynamic_friction", "collision_static_friction", "cloth_mass",
    "wind_influence", "wind_frequency", "wind_turbulence", "wind_blend",
    "wind_synchronization", "wind_depth_weight", "moving_wind",
    "spring_power", "spring_limit_distance", "spring_normal_limit_ratio", "spring_noise",
)

MC2_RUNTIME_INT_FIELDS = (
    "normal_axis", "use_distance_culling", "teleport_mode", "bending_method",
    "use_angle_restoration", "use_angle_limit", "use_max_distance", "use_backstop",
    "collision_mode", "self_collision_mode", "self_collision_sync_mode",
)

MC2_RUNTIME_CURVE_FIELDS = (
    "damping", "radius", "distance_stiffness", "angle_restoration_stiffness",
    "angle_limit", "max_distance", "backstop_distance", "collision_limit_distance",
    "self_collision_thickness",
)


CurveSampler = Callable[[dict, tuple[float, ...]], Iterable[float]]


def _float32(value: object) -> float:
    result = float(np.float32(value))
    if not np.isfinite(result):
        raise ValueError("MC2 runtime parameters cannot contain NaN/Inf")
    return result


def _multiply_float32(left: object, right: object) -> float:
    return _float32(np.float32(left) * np.float32(right))


def _default_curve_sampler(payload: dict, positions: tuple[float, ...]) -> Iterable[float]:
    try:
        module = importlib.import_module("HoTools.PropertyCurve")
        sample = module.sample_float_curve_positions
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "active MC2 curves require HoTools.PropertyCurve or an explicit curve_sampler"
        ) from exc
    return sample(payload, positions)


def sample_mc2_curve16(
    curve: MC2CurveSpec,
    *,
    scale: float = 1.0,
    curve_sampler: CurveSampler | None = None,
) -> tuple[float, ...]:
    """Convert authoring data with MC2's exact ``i / 15`` sample schedule."""
    if not isinstance(curve, MC2CurveSpec):
        raise TypeError("curve must be MC2CurveSpec")
    value = _multiply_float32(curve.value, scale)
    if not curve.use_curve:
        return (value,) * MC2_CURVE_SAMPLE_COUNT

    positions = tuple(index / 15.0 for index in range(MC2_CURVE_SAMPLE_COUNT))
    payload = _thaw(curve.curve_payload)
    sampler = curve_sampler or _default_curve_sampler
    multipliers = tuple(sampler(payload, positions))
    if len(multipliers) != MC2_CURVE_SAMPLE_COUNT:
        raise ValueError("curve_sampler must return exactly 16 values")
    return tuple(
        _multiply_float32(_multiply_float32(multiplier, curve.value), scale)
        for multiplier in multipliers
    )


@dataclass(frozen=True)
class MC2RuntimeParametersV0:
    """Immutable, float32-normalized MC2 ``ClothParameters`` value block."""

    setup_type: str
    float_values: tuple[float, ...]
    int_values: tuple[int, ...]
    curve_values: tuple[tuple[float, ...], ...]
    parameter_signature: str

    def __post_init__(self) -> None:
        if len(self.float_values) != len(MC2_RUNTIME_FLOAT_FIELDS):
            raise ValueError("invalid MC2 runtime float field count")
        if len(self.int_values) != len(MC2_RUNTIME_INT_FIELDS):
            raise ValueError("invalid MC2 runtime int field count")
        if len(self.curve_values) != len(MC2_RUNTIME_CURVE_FIELDS):
            raise ValueError("invalid MC2 runtime curve field count")
        if any(len(values) != MC2_CURVE_SAMPLE_COUNT for values in self.curve_values):
            raise ValueError("every MC2 runtime curve must contain 16 values")

    def debug_dict(self) -> dict:
        return {
            "abi_version": MC2_RUNTIME_PARAMETERS_ABI,
            "setup_type": self.setup_type,
            "float_values": dict(zip(MC2_RUNTIME_FLOAT_FIELDS, self.float_values)),
            "int_values": dict(zip(MC2_RUNTIME_INT_FIELDS, self.int_values)),
            "curve_values": {
                name: list(values)
                for name, values in zip(MC2_RUNTIME_CURVE_FIELDS, self.curve_values)
            },
        }


def _signature(setup_type: str, floats, ints, curves) -> str:
    payload = {
        "abi": MC2_RUNTIME_PARAMETERS_ABI,
        "setup_type": setup_type,
        "float_fields": MC2_RUNTIME_FLOAT_FIELDS,
        "float_values": floats,
        "int_fields": MC2_RUNTIME_INT_FIELDS,
        "int_values": ints,
        "curve_fields": MC2_RUNTIME_CURVE_FIELDS,
        "curve_values": curves,
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def make_mc2_runtime_parameters(
    profile: MC2ParticleProfileSpec,
    setup_options: MC2SetupOptionsSpec,
    *,
    curve_sampler: CurveSampler | None = None,
) -> MC2RuntimeParametersV0:
    """Apply MC2 setup overrides and build the N2 runtime value block."""
    if not isinstance(profile, MC2ParticleProfileSpec):
        raise TypeError("profile must be MC2ParticleProfileSpec")
    if not isinstance(setup_options, MC2SetupOptionsSpec):
        raise TypeError("setup_options must be MC2SetupOptionsSpec")

    setup_type = setup_options.setup_type
    is_spring = setup_type == MC2_SETUP_BONE_SPRING
    friction = MC2_BONE_SPRING_COLLISION_FRICTION if is_spring else profile.collision_friction

    float_map = {
        "gravity": 0.0 if is_spring else profile.gravity,
        "gravity_direction_x": profile.gravity_direction[0],
        "gravity_direction_y": profile.gravity_direction[1],
        "gravity_direction_z": profile.gravity_direction[2],
        "gravity_falloff": profile.gravity_falloff,
        "stabilization_time_after_reset": profile.stabilization_time_after_reset,
        "blend_weight": profile.blend_weight,
        "rotational_interpolation": setup_options.rotational_interpolation,
        "root_rotation": setup_options.root_rotation,
        "distance_culling_length": profile.distance_culling_length,
        "distance_culling_fade_ratio": profile.distance_culling_fade_ratio,
        "anchor_inertia": profile.anchor_inertia,
        "world_inertia": profile.world_inertia,
        "movement_inertia_smoothing": profile.movement_inertia_smoothing,
        "movement_speed_limit": profile.movement_speed_limit,
        "rotation_speed_limit": profile.rotation_speed_limit,
        "local_inertia": profile.local_inertia,
        "local_movement_speed_limit": profile.local_movement_speed_limit,
        "local_rotation_speed_limit": profile.local_rotation_speed_limit,
        "depth_inertia": profile.depth_inertia,
        "centrifugal_acceleration": profile.centrifugal_acceleration,
        "particle_speed_limit": profile.particle_speed_limit,
        "teleport_distance": profile.teleport_distance,
        "teleport_rotation": profile.teleport_rotation,
        "tether_compression_limit": MC2_BONE_SPRING_TETHER_COMPRESSION if is_spring else profile.tether_compression,
        "tether_stretch_limit": MC2_TETHER_STRETCH_LIMIT,
        "distance_velocity_attenuation": MC2_DISTANCE_VELOCITY_ATTENUATION,
        "bending_stiffness": profile.bending_stiffness,
        "angle_restoration_velocity_attenuation": profile.angle_restoration_velocity_attenuation,
        "angle_restoration_gravity_falloff": profile.angle_restoration_gravity_falloff,
        "angle_limit_stiffness": profile.angle_limit_stiffness,
        "backstop_radius": profile.backstop_radius,
        "motion_stiffness": profile.motion_stiffness,
        "collision_dynamic_friction": friction,
        "collision_static_friction": friction,
        "cloth_mass": profile.cloth_mass,
        "wind_influence": profile.wind_influence,
        "wind_frequency": profile.wind_frequency,
        "wind_turbulence": profile.wind_turbulence,
        "wind_blend": profile.wind_blend,
        "wind_synchronization": profile.wind_synchronization,
        "wind_depth_weight": profile.wind_depth_weight,
        "moving_wind": profile.moving_wind,
        "spring_power": profile.spring_power if is_spring and profile.spring_enabled else 0.0,
        "spring_limit_distance": profile.spring_limit_distance,
        "spring_normal_limit_ratio": profile.spring_normal_limit_ratio,
        "spring_noise": profile.spring_noise,
    }
    int_map = {
        "normal_axis": profile.normal_axis,
        "use_distance_culling": int(profile.distance_culling_enabled),
        "teleport_mode": profile.teleport_mode,
        "bending_method": 2 if profile.bending_stiffness > 1.0e-8 else 0,
        "use_angle_restoration": int(profile.angle_restoration_enabled),
        "use_angle_limit": int(profile.angle_limit_enabled),
        "use_max_distance": int(profile.max_distance_enabled and not is_spring),
        "use_backstop": int(profile.backstop_enabled and not is_spring),
        "collision_mode": 1 if is_spring else profile.collision_mode,
        "self_collision_mode": 0 if is_spring else profile.self_collision_mode,
        "self_collision_sync_mode": 0 if is_spring else profile.self_collision_sync_mode,
    }
    zero_curve = MC2CurveSpec(0.0)
    curve_specs = {
        "damping": (profile.damping, 0.2),
        "radius": (profile.radius, 1.0),
        "distance_stiffness": (
            MC2CurveSpec(MC2_BONE_SPRING_DISTANCE_STIFFNESS) if is_spring else profile.distance_stiffness,
            1.0,
        ),
        "angle_restoration_stiffness": (profile.angle_restoration_stiffness, 0.2),
        "angle_limit": (profile.angle_limit, 1.0),
        "max_distance": (profile.max_distance, 1.0),
        "backstop_distance": (profile.backstop_distance, 1.0),
        "collision_limit_distance": (profile.collision_limit_distance if is_spring else zero_curve, 1.0),
        "self_collision_thickness": (profile.self_collision_thickness, 1.0),
    }

    floats = tuple(_float32(float_map[name]) for name in MC2_RUNTIME_FLOAT_FIELDS)
    ints = tuple(int(int_map[name]) for name in MC2_RUNTIME_INT_FIELDS)
    curves = tuple(
        sample_mc2_curve16(curve_specs[name][0], scale=curve_specs[name][1], curve_sampler=curve_sampler)
        for name in MC2_RUNTIME_CURVE_FIELDS
    )
    return MC2RuntimeParametersV0(
        setup_type=setup_type,
        float_values=floats,
        int_values=ints,
        curve_values=curves,
        parameter_signature=_signature(setup_type, floats, ints, curves),
    )


def pack_mc2_runtime_parameters(spec: MC2RuntimeParametersV0) -> dict[str, np.ndarray]:
    """Pack the fixed V0 layout; array order is defined by the schema constants."""
    if not isinstance(spec, MC2RuntimeParametersV0):
        raise TypeError("spec must be MC2RuntimeParametersV0")
    arrays = {
        "float_values": np.ascontiguousarray(spec.float_values, dtype=np.float32),
        "int_values": np.ascontiguousarray(spec.int_values, dtype=np.int32),
        "curve_values": np.ascontiguousarray(spec.curve_values, dtype=np.float32),
    }
    for array in arrays.values():
        array.setflags(write=False)
    return arrays


__all__ = [
    "MC2_CURVE_SAMPLE_COUNT",
    "MC2_RUNTIME_CURVE_FIELDS",
    "MC2_RUNTIME_FLOAT_FIELDS",
    "MC2_RUNTIME_INT_FIELDS",
    "MC2_RUNTIME_PARAMETERS_ABI",
    "MC2RuntimeParametersV0",
    "make_mc2_runtime_parameters",
    "pack_mc2_runtime_parameters",
    "sample_mc2_curve16",
]
