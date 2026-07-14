"""Tier A reference checks for MC2 Center anchor frame shift."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "tier_a"
    / "center_frame_shift_anchor_001.json"
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


def _axis_angle_y(values) -> np.ndarray:
    half_angle = _f32(np.radians(values["degrees"]) * 0.5)
    return np.asarray(
        (0.0, np.sin(half_angle), 0.0, np.cos(half_angle)),
        dtype=np.float32,
    )


def test_center_anchor_shift_matches_fixed_mc2_oracle() -> None:
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
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    old_component = np.asarray(values["old_component_world_position"], dtype=np.float32)
    component = np.asarray(values["component_world_position"], dtype=np.float32)
    anchor_position = np.asarray(values["anchor_world_position"], dtype=np.float32)
    anchor_rotation = _axis_angle_y(values["anchor_world_rotation_axis_angle"])
    anchor_local = np.asarray(values["anchor_component_local_position"], dtype=np.float32)
    anchor_center = anchor_position + _rotate(anchor_rotation, anchor_local)
    anchor_ratio = _f32(1.0) - _f32(values["anchor_inertia"])
    anchor_delta_vector = (anchor_center - old_component) * anchor_ratio
    anchor_delta_rotation = _slerp(identity, anchor_rotation, anchor_ratio)
    work_old_component = old_component + anchor_delta_vector

    old_frame = np.asarray(values["old_frame_world_position"], dtype=np.float32)
    now = np.asarray(values["now_world_position"], dtype=np.float32)
    shifted_old_frame = _shift_position(
        old_frame,
        old_component,
        anchor_delta_vector,
        anchor_delta_rotation,
    )
    shifted_now = _shift_position(
        now,
        old_component,
        anchor_delta_vector,
        anchor_delta_rotation,
    )
    moving_vector = component - work_old_component
    moving_length = _f32(np.linalg.norm(moving_vector))
    moving_direction = moving_vector / moving_length
    moving_speed = moving_length / _f32(values["frame_delta_time"])

    component_rotation = _axis_angle_y(values["component_world_rotation_axis_angle"])
    vector_values = {
        "frame_component_shift_vector": anchor_delta_vector,
        "frame_component_shift_rotation_xyzw": anchor_delta_rotation,
        "old_frame_world_position": shifted_old_frame,
        "old_frame_world_rotation_xyzw": anchor_delta_rotation,
        "now_world_position": shifted_now,
        "now_world_rotation_xyzw": anchor_delta_rotation,
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
    test_center_anchor_shift_matches_fixed_mc2_oracle()
    print("PASS MC2 Center anchor frame-shift Tier A oracle")
