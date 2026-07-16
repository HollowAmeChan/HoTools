"""Pure N3 frame continuity and reset tests."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types

import numpy as np


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

frame_state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state")
center_state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state")
state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.state")
final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "tier_a", "frame_reset_pose_001.json"
)


def _runtime(count=2):
    return state.MC2SlotRuntimeState(
        task_id="mc2:mesh:test",
        topology_signature="topology",
        config_signature="config",
        parameter_signature="parameters",
        settings_signature="settings",
        world_generation=7,
        particle_count=count,
    )


def _frame(frame, generation=7, offset=0.0):
    return frame_state.make_mc2_frame_input(
        task_id="mc2:mesh:test",
        topology_signature="topology",
        frame=frame,
        generation=generation,
        world_positions=((offset, 0.0, 0.0), (1.0 + offset, 0.0, 0.0)),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),) * 2,
    )


def test_frame_interpolation_is_checked_at_the_host_boundary() -> None:
    assert _frame(1).frame_interpolation == 1.0
    for value in (-0.01, 1.01, float("nan")):
        try:
            frame_state.make_mc2_frame_input(
                task_id="mc2:mesh:test",
                topology_signature="topology",
                frame=1,
                generation=7,
                world_positions=((0.0, 0.0, 0.0),),
                world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
                frame_interpolation=value,
            )
        except ValueError as exc:
            assert "frame_interpolation" in str(exc)
        else:
            raise AssertionError("out-of-range frame interpolation was accepted")

    try:
        frame_state.make_mc2_frame_input(
            task_id="mc2:mesh:test",
            topology_signature="topology",
            frame=1,
            generation=7,
            world_positions=((0.0, 0.0, 0.0),),
            world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
            source_world_linear=((1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        )
    except ValueError as exc:
        assert "invertible" in str(exc)
    else:
        raise AssertionError("singular source world linear was accepted")


def test_center_frame_pose_identity_must_match_particle_frame_identity() -> None:
    center_pose = center_state.MC2CenterFramePoseSpec(
        frame=2,
        generation=7,
        component_identity="object:7",
        component_world_position=(0.0, 0.0, 0.0),
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(1.0, 1.0, 1.0),
    )
    try:
        frame_state.make_mc2_frame_input(
            task_id="mc2:mesh:test",
            topology_signature="topology",
            frame=1,
            generation=7,
            world_positions=((0.0, 0.0, 0.0),),
            world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),),
            center_frame_pose=center_pose,
        )
    except ValueError as exc:
        assert "frame identity" in str(exc)
    else:
        raise AssertionError("mismatched Center frame identity was accepted")


def test_first_pose_plans_native_reset() -> None:
    runtime = _runtime()
    result = frame_state.plan_mc2_frame_sync(runtime, _frame(10, offset=2.0))
    assert result.action == "reset" and result.reset_reason == "first_valid_pose"
    assert runtime.initialized is False and runtime.reset_count == 0


def test_same_frame_is_idempotent_and_continuous_frame_preserves_history() -> None:
    runtime = _runtime()
    first = _frame(3, offset=1.0)
    runtime.mark_frame_reset(first, "first_valid_pose")
    same = frame_state.plan_mc2_frame_sync(runtime, first)
    assert same.action == "same_frame" and runtime.frame_revision == 1
    continuous = frame_state.plan_mc2_frame_sync(runtime, _frame(4, offset=2.0))
    assert continuous.action == "updated" and continuous.reset_reason == ""
    assert runtime.reset_count == 1 and runtime.frame_revision == 1


def test_discontinuities_and_user_request_have_stable_reset_reasons() -> None:
    cases = (
        (_frame(8), False, "time_discontinuity"),
        (_frame(2), False, "time_reversed"),
        (_frame(4, generation=8), False, "frame_generation_changed"),
        (_frame(4), True, "user_reset"),
    )
    for next_frame, user_reset, reason in cases:
        runtime = _runtime()
        runtime.mark_frame_reset(_frame(3), "first_valid_pose")
        result = frame_state.plan_mc2_frame_sync(
            runtime, next_frame, user_reset=user_reset
        )
        assert result.action == "reset" and result.reset_reason == reason
        assert runtime.last_reset_reason == "first_valid_pose"


def test_tier_a_world_rotation_and_reset_arrays_match_mc2() -> None:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert fixture["oracle_tier"] == "A"
    expected = fixture["expected"]
    inv_sqrt2 = np.float32(1.0 / np.sqrt(2.0)).item()
    rotations = np.asarray(
        (
            final_proxy.mc2_world_rotation_xyzw((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            final_proxy.mc2_world_rotation_xyzw(
                (inv_sqrt2, inv_sqrt2, 0.0), (0.0, 0.0, 1.0)
            ),
        ),
        dtype=np.float32,
    )
    expected_rotations = np.asarray(expected["world_rotations_xyzw"], dtype=np.float32)
    np.testing.assert_allclose(rotations, expected_rotations, rtol=1.0e-6, atol=1.0e-7)

    frame = frame_state.make_mc2_frame_input(
        task_id="mc2:mesh:test",
        topology_signature="topology",
        frame=1,
        generation=7,
        world_positions=expected["world_positions"],
        world_rotations_xyzw=rotations,
    )
    runtime = _runtime()
    result = frame_state.plan_mc2_frame_sync(runtime, frame)
    assert result.action == "reset" and result.reset_reason == "first_valid_pose"


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
