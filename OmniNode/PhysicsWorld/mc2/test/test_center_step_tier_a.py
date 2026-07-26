"""Tier A reference checks for MC2 Center substep derivation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


FIXTURE = Path(__file__).parent / "fixtures" / "tier_a" / "center_step_inertia_001.json"
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"


def _f32(value):
    return np.float32(value)


def _normalize_quaternion(value: np.ndarray) -> np.ndarray:
    return np.asarray(value / _f32(np.linalg.norm(value)), dtype=np.float32)


def _slerp(first: np.ndarray, second: np.ndarray, ratio: np.float32) -> np.ndarray:
    target = second.copy()
    cosine = _f32(np.dot(first, target))
    if cosine < 0.0:
        target = -target
        cosine = -cosine
    if cosine > _f32(0.9995):
        return _normalize_quaternion(first + (target - first) * ratio)
    angle = _f32(np.arccos(np.clip(cosine, -1.0, 1.0)))
    sine = _f32(np.sin(angle))
    first_weight = _f32(np.sin(_f32(1.0 - ratio) * angle) / sine)
    second_weight = _f32(np.sin(ratio * angle) / sine)
    return _normalize_quaternion(first * first_weight + target * second_weight)


def _rotate_xyzw(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    xyz = rotation[:3]
    twice_cross = _f32(2.0) * np.cross(xyz, vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(xyz, twice_cross),
        dtype=np.float32,
    )


def test_center_step_matches_fixed_mc2_oracle() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == EXPECTED_COMMIT
    assert source["commit"] == EXPECTED_COMMIT
    assert source["producer"] == [
        "Runtime/Manager/Team/TeamManager.cs::SimulationStepTeamUpdate"
    ]

    values = fixture["input"]
    expected = fixture["expected"]
    dt = _f32(values["simulation_delta_time"])
    now_update_time = _f32(values["now_update_time_before_step"]) + dt
    frame_duration = _f32(values["time"]) - _f32(values["frame_old_time"])
    frame_interpolation = np.clip(
        (now_update_time - _f32(values["frame_old_time"])) / frame_duration,
        _f32(0.0),
        _f32(1.0),
    )

    old_position = np.asarray(values["old_frame_world_position"], dtype=np.float32)
    frame_position = np.asarray(values["frame_world_position"], dtype=np.float32)
    now_position = old_position + (frame_position - old_position) * frame_interpolation

    old_rotation = np.asarray(values["old_frame_world_rotation_xyzw"], dtype=np.float32)
    half_angle = _f32(np.radians(values["frame_world_rotation_axis_angle"]["degrees"]) * 0.5)
    frame_rotation = np.asarray((0.0, np.sin(half_angle), 0.0, np.cos(half_angle)), dtype=np.float32)
    now_rotation = _slerp(old_rotation, frame_rotation, frame_interpolation)
    step_vector = now_position
    step_rotation = now_rotation
    step_angle = _f32(2.0) * _f32(np.arccos(np.clip(abs(step_rotation[3]), 0.0, 1.0)))

    local_movement_inertia = _f32(1.0) - _f32(values["local_inertia"])
    local_vector = step_vector * (_f32(1.0) - local_movement_inertia)
    local_speed = _f32(np.linalg.norm(local_vector)) / dt
    movement_limit = _f32(values["local_movement_speed_limit"])
    if local_speed > movement_limit and movement_limit >= 0.0:
        ratio = movement_limit / local_speed
        local_movement_inertia = _f32(1.0) + (local_movement_inertia - _f32(1.0)) * ratio

    local_rotation_inertia = _f32(1.0) - _f32(values["local_inertia"])
    local_angle = step_angle * (_f32(1.0) - local_rotation_inertia)
    local_angle_speed = _f32(np.degrees(local_angle / dt))
    rotation_limit = _f32(values["local_rotation_speed_limit"])
    if local_angle_speed > rotation_limit and rotation_limit >= 0.0:
        ratio = rotation_limit / local_angle_speed
        local_rotation_inertia = _f32(1.0) + (local_rotation_inertia - _f32(1.0)) * ratio

    inertia_vector = step_vector * local_movement_inertia
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    inertia_rotation = _slerp(identity, step_rotation, local_rotation_inertia)
    angular_velocity = step_angle / dt
    rotation_axis = step_rotation[:3] / _f32(np.linalg.norm(step_rotation[:3]))

    old_scale = np.asarray(values["old_frame_world_scale"], dtype=np.float32)
    frame_scale = np.asarray(values["frame_world_scale"], dtype=np.float32)
    world_scale = old_scale + (frame_scale - old_scale) * frame_interpolation
    initial_scale = np.asarray(values["init_scale"], dtype=np.float32)
    scale_ratio = np.maximum(
        _f32(np.linalg.norm(world_scale)) / _f32(np.linalg.norm(initial_scale)),
        _f32(1.0e-6),
    )

    initial_gravity = np.asarray(values["initial_local_gravity_direction"], dtype=np.float32)
    initial_gravity[1] *= _f32(values["negative_scale_direction"][1])
    world_falloff = _rotate_xyzw(now_rotation, initial_gravity)
    world_gravity = np.asarray(values["world_gravity_direction"], dtype=np.float32)
    gravity_dot = np.clip(
        _f32(np.dot(world_falloff, world_gravity)) * _f32(0.5) + _f32(0.5),
        _f32(0.0),
        _f32(1.0),
    )
    gravity_ratio = _f32(1.0 - values["gravity_falloff"])
    gravity_ratio += (_f32(1.0) - gravity_ratio) * np.clip(
        _f32(1.0) - gravity_dot, _f32(0.0), _f32(1.0)
    )
    velocity_weight = np.clip(
        _f32(values["velocity_weight_before_step"])
        + dt / _f32(values["stabilization_time_after_reset"]),
        _f32(0.0),
        _f32(1.0),
    )
    blend_weight = np.clip(
        velocity_weight
        * _f32(values["parameter_blend_weight"])
        * _f32(values["distance_weight"]),
        _f32(0.0),
        _f32(1.0),
    )

    scalar_values = {
        "frame_interpolation": frame_interpolation,
        "step_move_inertia_ratio": local_movement_inertia,
        "step_rotation_inertia_ratio": local_rotation_inertia,
        "angular_velocity": angular_velocity,
        "scale_ratio": scale_ratio,
        "gravity_dot": gravity_dot,
        "gravity_ratio": gravity_ratio,
        "velocity_weight": velocity_weight,
        "blend_weight": blend_weight,
    }
    vector_values = {
        "now_world_position": now_position,
        "now_world_rotation_xyzw": now_rotation,
        "step_vector": step_vector,
        "step_rotation_xyzw": step_rotation,
        "inertia_vector": inertia_vector,
        "inertia_rotation_xyzw": inertia_rotation,
        "rotation_axis": rotation_axis,
    }
    for field, actual in scalar_values.items():
        np.testing.assert_allclose(actual, expected[field], rtol=1.0e-6, atol=1.0e-6)
    for field, actual in vector_values.items():
        np.testing.assert_allclose(actual, expected[field], rtol=1.0e-6, atol=1.0e-6)


if __name__ == "__main__":
    test_center_step_matches_fixed_mc2_oracle()
    print("PASS MC2 Center step Tier A oracle")
