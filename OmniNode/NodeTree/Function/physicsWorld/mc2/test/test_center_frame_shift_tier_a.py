"""Tier A reference checks for MC2 Center world-inertia frame shift."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "tier_a"
    / "center_frame_shift_world_inertia_001.json"
)
EXPECTED_COMMIT = "418f89ff31a45bb4b2336641ad5907a1110eabea"


def _f32(value):
    return np.float32(value)


def _normalize_quaternion(value: np.ndarray) -> np.ndarray:
    return np.asarray(value / _f32(np.linalg.norm(value)), dtype=np.float32)


def _slerp(first: np.ndarray, second: np.ndarray, ratio) -> np.ndarray:
    ratio = _f32(ratio)
    target = second.copy()
    cosine = _f32(np.dot(first, target))
    if cosine < 0.0:
        target = -target
        cosine = -cosine
    if cosine > _f32(0.9995):
        return _normalize_quaternion(first + (target - first) * ratio)
    angle = _f32(np.arccos(np.clip(cosine, -1.0, 1.0)))
    sine = _f32(np.sin(angle))
    first_weight = _f32(np.sin((_f32(1.0) - ratio) * angle) / sine)
    second_weight = _f32(np.sin(ratio * angle) / sine)
    return _normalize_quaternion(first * first_weight + target * second_weight)


def _rotate(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    xyz = rotation[:3]
    twice_cross = _f32(2.0) * np.cross(xyz, vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(xyz, twice_cross),
        dtype=np.float32,
    )


def _shift_position(position, pivot, shift_vector, shift_rotation) -> np.ndarray:
    return np.asarray(
        pivot + _rotate(shift_rotation, position - pivot) + shift_vector,
        dtype=np.float32,
    )


def test_center_frame_shift_matches_fixed_mc2_oracle() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source"]
    assert fixture["oracle_tier"] == "A"
    assert fixture["mc2_commit"] == EXPECTED_COMMIT
    assert source["commit"] == EXPECTED_COMMIT
    assert source["producer"] == [
        "Runtime/Manager/Team/TeamManager.cs::SimulationCalcCenterAndInertiaAndWind"
    ]

    values = fixture["input"]
    expected = fixture["expected"]
    old_component = np.asarray(values["old_component_world_position"], dtype=np.float32)
    component = np.asarray(values["component_world_position"], dtype=np.float32)
    old_rotation = np.asarray(values["old_component_world_rotation_xyzw"], dtype=np.float32)
    half_angle = _f32(
        np.radians(values["component_world_rotation_axis_angle"]["degrees"]) * 0.5
    )
    component_rotation = np.asarray(
        (0.0, np.sin(half_angle), 0.0, np.cos(half_angle)),
        dtype=np.float32,
    )
    shift_ratio = _f32(1.0) - _f32(values["world_inertia"])
    frame_shift_vector = (component - old_component) * shift_ratio
    frame_shift_rotation = _slerp(old_rotation, component_rotation, shift_ratio)

    old_frame = np.asarray(values["old_frame_world_position"], dtype=np.float32)
    now = np.asarray(values["now_world_position"], dtype=np.float32)
    shifted_old_frame = _shift_position(
        old_frame,
        old_component,
        frame_shift_vector,
        frame_shift_rotation,
    )
    shifted_now = _shift_position(
        now,
        old_component,
        frame_shift_vector,
        frame_shift_rotation,
    )
    work_old_component = old_component + (component - old_component) * shift_ratio
    moving_vector = component - work_old_component
    moving_length = _f32(np.linalg.norm(moving_vector))
    moving_direction = moving_vector / moving_length
    moving_speed = moving_length / _f32(values["frame_delta_time"])
    moving_speed /= _f32(values["now_time_scale"])

    vector_values = {
        "frame_component_shift_vector": frame_shift_vector,
        "frame_component_shift_rotation_xyzw": frame_shift_rotation,
        "old_frame_world_position": shifted_old_frame,
        "old_frame_world_rotation_xyzw": frame_shift_rotation,
        "now_world_position": shifted_now,
        "now_world_rotation_xyzw": frame_shift_rotation,
        "frame_world_position": component,
        "frame_world_rotation_xyzw": component_rotation,
        "frame_moving_direction": moving_direction,
    }
    for field, actual in vector_values.items():
        np.testing.assert_allclose(actual, expected[field], rtol=1.0e-6, atol=1.0e-6)
    np.testing.assert_allclose(
        moving_speed,
        expected["frame_moving_speed"],
        rtol=1.0e-6,
        atol=1.0e-6,
    )


if __name__ == "__main__":
    test_center_frame_shift_matches_fixed_mc2_oracle()
    print("PASS MC2 Center frame-shift Tier A oracle")
