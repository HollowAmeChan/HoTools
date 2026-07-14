"""Tier A reference checks for MC2 Center world-inertia frame shift."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import types

import numpy as np


MC2_ROOT = Path(__file__).resolve().parents[1]
PHYSICS_WORLD = MC2_ROOT.parent
FUNCTION = PHYSICS_WORLD.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent
HOTOOLS = OMNINODE.parent

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [str(package_path)]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

center = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state")


FIXTURES = tuple(
    Path(__file__).parent / "fixtures" / "tier_a" / name
    for name in (
        "center_frame_shift_world_inertia_001.json",
        "center_frame_shift_speed_limit_001.json",
        "center_frame_shift_anchor_world_limit_001.json",
        "center_frame_shift_smoothing_001.json",
        "center_frame_shift_time_scale_001.json",
        "center_frame_shift_fixed_center_001.json",
        "center_frame_shift_zero_time_scale_001.json",
    )
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


def _multiply(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first_xyz = first[:3]
    second_xyz = second[:3]
    return np.asarray(
        (
            first[3] * second_xyz
            + second[3] * first_xyz
            + np.cross(first_xyz, second_xyz)
        ).tolist()
        + [first[3] * second[3] - np.dot(first_xyz, second_xyz)],
        dtype=np.float32,
    )


def _inverse(rotation: np.ndarray) -> np.ndarray:
    return np.asarray(
        (-rotation[0], -rotation[1], -rotation[2], rotation[3]),
        dtype=np.float32,
    )


def _shift_position(position, pivot, shift_vector, shift_rotation) -> np.ndarray:
    return np.asarray(
        pivot + _rotate(shift_rotation, position - pivot) + shift_vector,
        dtype=np.float32,
    )


def _assert_center_frame_shift_fixture(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
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
    identity = np.asarray((0.0, 0.0, 0.0, 1.0), dtype=np.float32)
    use_anchor = "anchor_inertia" in values
    anchor_rotation = identity
    if use_anchor:
        anchor_half_angle = _f32(
            np.radians(values["anchor_world_rotation_axis_angle"]["degrees"]) * 0.5
        )
        anchor_rotation = np.asarray(
            (0.0, np.sin(anchor_half_angle), 0.0, np.cos(anchor_half_angle)),
            dtype=np.float32,
        )
    frame_world_position = np.asarray(
        values.get("frame_world_position", values["component_world_position"]),
        dtype=np.float32,
    )
    frame_world_rotation = component_rotation
    if "frame_world_rotation_axis_angle" in values:
        frame_half_angle = _f32(
            np.radians(values["frame_world_rotation_axis_angle"]["degrees"]) * 0.5
        )
        frame_world_rotation = np.asarray(
            (0.0, np.sin(frame_half_angle), 0.0, np.cos(frame_half_angle)),
            dtype=np.float32,
        )
    result = center.evaluate_mc2_center_frame_shift(
        center.MC2CenterFrameShiftInputSpec(
            simulation_delta_time=values["simulation_delta_time"],
            frame_delta_time=values["frame_delta_time"],
            now_time_scale=values["now_time_scale"],
            velocity_weight=values["velocity_weight"],
            skip_count=values.get("skip_count", 0),
            world_inertia=values["world_inertia"],
            movement_speed_limit=values["movement_speed_limit"],
            rotation_speed_limit=values["rotation_speed_limit"],
            old_component_world_position=values["old_component_world_position"],
            old_component_world_rotation_xyzw=values[
                "old_component_world_rotation_xyzw"
            ],
            component_world_position=values["component_world_position"],
            component_world_rotation_xyzw=tuple(float(value) for value in component_rotation),
            old_frame_world_position=values["old_frame_world_position"],
            old_frame_world_rotation_xyzw=values["old_frame_world_rotation_xyzw"],
            now_world_position=values["now_world_position"],
            now_world_rotation_xyzw=values["now_world_rotation_xyzw"],
            use_anchor=use_anchor,
            anchor_inertia=values.get("anchor_inertia", 0.0),
            old_anchor_world_position=values.get(
                "old_anchor_world_position", (0.0, 0.0, 0.0)
            ),
            old_anchor_world_rotation_xyzw=values.get(
                "old_anchor_world_rotation_xyzw", (0.0, 0.0, 0.0, 1.0)
            ),
            anchor_world_position=values.get(
                "anchor_world_position", (0.0, 0.0, 0.0)
            ),
            anchor_world_rotation_xyzw=tuple(float(value) for value in anchor_rotation),
            anchor_component_local_position=values.get(
                "anchor_component_local_position", (0.0, 0.0, 0.0)
            ),
            movement_inertia_smoothing=values.get(
                "movement_inertia_smoothing", 0.0
            ),
            smoothing_velocity=values.get("smoothing_velocity", (0.0, 0.0, 0.0)),
            is_running=values.get("is_running", True),
            frame_world_position=tuple(float(value) for value in frame_world_position),
            frame_world_rotation_xyzw=tuple(
                float(value) for value in frame_world_rotation
            ),
        )
    )
    for field, expected_value in expected.items():
        np.testing.assert_allclose(
            getattr(result, field), expected_value, rtol=1.0e-6, atol=1.0e-6
        )

    # Retain an independent formula check so the fixture does not only test itself
    # through the production evaluator.
    anchor_shift_vector = np.zeros(3, dtype=np.float32)
    anchor_shift_rotation = identity
    adjusted_old_component = old_component.copy()
    adjusted_old_rotation = old_rotation.copy()
    if use_anchor:
        anchor_position = np.asarray(values["anchor_world_position"], dtype=np.float32)
        anchor_local = np.asarray(
            values["anchor_component_local_position"], dtype=np.float32
        )
        old_anchor_rotation = np.asarray(
            values["old_anchor_world_rotation_xyzw"], dtype=np.float32
        )
        anchor_center = anchor_position + _rotate(anchor_rotation, anchor_local)
        anchor_ratio = _f32(1.0) - _f32(values["anchor_inertia"])
        anchor_shift_vector = (anchor_center - old_component) * anchor_ratio
        anchor_shift_rotation = _slerp(
            identity,
            _normalize_quaternion(
                _multiply(anchor_rotation, _inverse(old_anchor_rotation))
            ),
            anchor_ratio,
        )
        adjusted_old_component += anchor_shift_vector
        adjusted_old_rotation = _normalize_quaternion(
            _multiply(anchor_shift_rotation, adjusted_old_rotation)
        )

    smooth_shift_vector = np.zeros(3, dtype=np.float32)
    smoothing_velocity = np.asarray(
        values.get("smoothing_velocity", (0.0, 0.0, 0.0)),
        dtype=np.float32,
    )
    smoothing = _f32(values.get("movement_inertia_smoothing", 0.0))
    if smoothing >= _f32(1.0e-6):
        if values.get("is_running", True):
            frame_delta_velocity = (
                component - adjusted_old_component
            ) / _f32(values["frame_delta_time"])
            movement_limit = _f32(values["movement_speed_limit"])
            frame_delta_speed = _f32(np.linalg.norm(frame_delta_velocity))
            if movement_limit >= 0.0 and frame_delta_speed > movement_limit:
                frame_delta_velocity *= movement_limit / frame_delta_speed
            one_minus_smoothing = _f32(1.0) - smoothing
            average_ratio = np.clip(
                one_minus_smoothing
                * one_minus_smoothing
                * one_minus_smoothing
                * _f32(0.99)
                + _f32(0.01),
                _f32(0.0),
                _f32(1.0),
            )
            smoothing_velocity += (
                frame_delta_velocity - smoothing_velocity
            ) * average_ratio
        smooth_position = (
            component
            - smoothing_velocity * _f32(values["frame_delta_time"])
        )
        smooth_shift_vector = smooth_position - adjusted_old_component
        adjusted_old_component = smooth_position

    shift_ratio = _f32(1.0) - _f32(values["world_inertia"])
    rotation_shift_ratio = shift_ratio
    world_component_delta = component - adjusted_old_component
    work_old_component = adjusted_old_component + world_component_delta * shift_ratio
    work_old_rotation = _slerp(
        adjusted_old_rotation,
        component_rotation,
        rotation_shift_ratio,
    )
    movement_speed = _f32(np.linalg.norm(component - work_old_component)) / _f32(
        values["frame_delta_time"]
    )
    movement_limit = _f32(values["movement_speed_limit"])
    if movement_limit >= 0.0 and movement_speed > movement_limit:
        limit_ratio = _f32((movement_speed - movement_limit) / movement_speed)
        shift_ratio += (_f32(1.0) - shift_ratio) * limit_ratio
        work_old_component += (component - work_old_component) * limit_ratio
    rotation_cosine = np.clip(
        abs(_f32(np.dot(work_old_rotation, component_rotation))),
        _f32(0.0),
        _f32(1.0),
    )
    rotation_speed = _f32(
        np.degrees(_f32(2.0) * _f32(np.arccos(rotation_cosine)))
    ) / _f32(values["frame_delta_time"])
    rotation_limit = _f32(values["rotation_speed_limit"])
    if rotation_limit >= 0.0 and rotation_speed > rotation_limit:
        limit_ratio = _f32((rotation_speed - rotation_limit) / rotation_speed)
        rotation_shift_ratio += (_f32(1.0) - rotation_shift_ratio) * limit_ratio
        work_old_rotation = _slerp(
            work_old_rotation,
            component_rotation,
            limit_ratio,
        )
    other_shift_ratio = _f32(0.0)
    skip_count = int(values.get("skip_count", 0))
    if skip_count > 0:
        denominator = (
            _f32(values["frame_delta_time"])
            * _f32(values["now_time_scale"])
        )
        skip_ratio = (
            _f32(1.0)
            if denominator <= _f32(1.0e-8)
            else np.clip(
                (_f32(skip_count) * _f32(values["simulation_delta_time"]))
                / denominator,
                _f32(0.0),
                _f32(1.0),
            )
        )
        other_shift_ratio += (
            _f32(1.0) - other_shift_ratio
        ) * skip_ratio
    velocity_weight = _f32(values["velocity_weight"])
    if velocity_weight < _f32(1.0):
        ratio = _f32(1.0) - velocity_weight
        other_shift_ratio += (_f32(1.0) - other_shift_ratio) * ratio
    now_time_scale = _f32(values["now_time_scale"])
    if now_time_scale < _f32(1.0):
        ratio = _f32(1.0) - now_time_scale
        other_shift_ratio += (_f32(1.0) - other_shift_ratio) * ratio
    if other_shift_ratio > _f32(0.0):
        shift_ratio += (_f32(1.0) - shift_ratio) * other_shift_ratio
        rotation_shift_ratio += (
            _f32(1.0) - rotation_shift_ratio
        ) * other_shift_ratio
        work_old_component += (
            component - work_old_component
        ) * other_shift_ratio
        work_old_rotation = _slerp(
            work_old_rotation,
            component_rotation,
            other_shift_ratio,
        )
    frame_shift_vector = (
        anchor_shift_vector
        + smooth_shift_vector
        + world_component_delta * shift_ratio
    )
    full_world_rotation = _normalize_quaternion(
        _multiply(component_rotation, _inverse(adjusted_old_rotation))
    )
    world_shift_rotation = _slerp(
        identity,
        full_world_rotation,
        rotation_shift_ratio,
    )
    frame_shift_rotation = _normalize_quaternion(
        _multiply(anchor_shift_rotation, world_shift_rotation)
    )

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
    moving_vector = component - work_old_component
    moving_length = _f32(np.linalg.norm(moving_vector))
    moving_direction = (
        moving_vector / moving_length
        if moving_length > _f32(1.0e-6)
        else np.zeros(3, dtype=np.float32)
    )
    moving_speed = moving_length / _f32(values["frame_delta_time"])
    moving_speed *= (
        _f32(1.0) / _f32(values["now_time_scale"])
        if _f32(values["now_time_scale"]) > _f32(1.0e-6)
        else _f32(0.0)
    )

    vector_values = {
        "frame_component_shift_vector": frame_shift_vector,
        "frame_component_shift_rotation_xyzw": frame_shift_rotation,
        "old_frame_world_position": shifted_old_frame,
        "old_frame_world_rotation_xyzw": frame_shift_rotation,
        "now_world_position": shifted_now,
        "now_world_rotation_xyzw": frame_shift_rotation,
        "frame_world_position": frame_world_position,
        "frame_world_rotation_xyzw": frame_world_rotation,
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
    if "smoothing_velocity" in expected:
        np.testing.assert_allclose(
            smoothing_velocity,
            expected["smoothing_velocity"],
            rtol=1.0e-6,
            atol=1.0e-6,
        )


def test_center_frame_shift_matches_fixed_mc2_oracle() -> None:
    for path in FIXTURES:
        _assert_center_frame_shift_fixture(path)


if __name__ == "__main__":
    test_center_frame_shift_matches_fixed_mc2_oracle()
    print("PASS MC2 Center frame-shift Tier A oracle")
