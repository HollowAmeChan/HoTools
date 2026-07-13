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
initial_state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.initial_state")
state = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.state")
final_proxy = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.final_proxy"
)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "tier_a", "frame_reset_pose_001.json"
)


def _initial(count=2):
    return initial_state.MC2InitialStateSpec(
        task_id="mc2:mesh:test",
        setup_type="mesh_cloth",
        topology_signature="topology",
        particle_count=count,
        rest_positions=((9.0, 9.0, 9.0),) * count,
        rest_rotations=((0.0, 0.0, 0.0, 1.0),) * count,
        parent_indices=(-1,) * count,
        depths=(0.0,) * count,
        fixed_mask=(False,) * count,
        source_indices=(0,) * count,
        source_local_indices=tuple(range(count)),
        initial_state_signature="initial",
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


def test_allocation_does_not_pretend_rest_pose_was_reset() -> None:
    buffer = state.MC2ParticleBuffer.allocate(_initial())
    runtime = _runtime()
    assert buffer.reset_count == runtime.reset_count == 0
    assert runtime.initialized is False
    assert runtime.last_reset_reason == "allocation_pending"
    assert not np.any(buffer.next_positions)


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


def test_first_pose_resets_all_history_and_clears_contact_state() -> None:
    buffer = state.MC2ParticleBuffer.allocate(_initial())
    runtime = _runtime()
    buffer.velocities.fill(4.0)
    buffer.friction.fill(1.0)
    result = frame_state.sync_mc2_frame_input(runtime, buffer, _frame(10, offset=2.0))
    assert result.action == "reset" and result.reset_reason == "first_valid_pose"
    assert runtime.initialized and runtime.reset_count == buffer.reset_count == 1
    for name in (
        "next_positions", "old_positions", "base_positions", "old_frame_positions",
        "velocity_positions", "display_positions", "step_basic_positions",
    ):
        np.testing.assert_array_equal(getattr(buffer, name), _frame(10, offset=2.0).world_positions)
    assert not np.any(buffer.velocities)
    assert not np.any(buffer.friction)


def test_same_frame_is_idempotent_and_continuous_frame_preserves_history() -> None:
    buffer = state.MC2ParticleBuffer.allocate(_initial())
    runtime = _runtime()
    first = _frame(3, offset=1.0)
    frame_state.sync_mc2_frame_input(runtime, buffer, first)
    before = buffer.next_positions.copy()
    same = frame_state.sync_mc2_frame_input(runtime, buffer, first)
    assert same.action == "same_frame" and runtime.frame_revision == 1
    continuous = frame_state.sync_mc2_frame_input(runtime, buffer, _frame(4, offset=2.0))
    assert continuous.action == "updated" and continuous.reset_reason == ""
    np.testing.assert_array_equal(buffer.next_positions, before)
    np.testing.assert_array_equal(buffer.base_positions, _frame(4, offset=2.0).world_positions)
    assert runtime.reset_count == 1 and runtime.frame_revision == 2


def test_discontinuities_and_user_request_have_stable_reset_reasons() -> None:
    cases = (
        (_frame(8), False, "time_discontinuity"),
        (_frame(2), False, "time_reversed"),
        (_frame(4, generation=8), False, "frame_generation_changed"),
        (_frame(4), True, "user_reset"),
    )
    for next_frame, user_reset, reason in cases:
        buffer = state.MC2ParticleBuffer.allocate(_initial())
        runtime = _runtime()
        frame_state.sync_mc2_frame_input(runtime, buffer, _frame(3))
        result = frame_state.sync_mc2_frame_input(
            runtime, buffer, next_frame, user_reset=user_reset
        )
        assert result.action == "reset" and result.reset_reason == reason
        assert runtime.last_reset_reason == reason


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
    buffer = state.MC2ParticleBuffer.allocate(_initial())
    runtime = _runtime()
    frame_state.sync_mc2_frame_input(runtime, buffer, frame)
    mappings = {
        "next_positions": "next_positions",
        "old_positions": "old_positions",
        "base_positions": "base_positions",
        "old_frame_positions": "animation_old_positions",
        "velocity_positions": "velocity_reference_positions",
        "display_positions": "display_positions",
        "velocities": "velocities",
        "real_velocities": "real_velocities",
        "friction": "friction",
        "static_friction": "static_friction",
        "collision_normals": "collision_normals",
    }
    for field, expected_field in mappings.items():
        np.testing.assert_array_equal(
            getattr(buffer, field), np.asarray(expected[expected_field], dtype=np.float32)
        )
    for field in ("old_rotations", "base_rotations", "old_frame_rotations"):
        np.testing.assert_array_equal(getattr(buffer, field), frame.world_rotations_xyzw)


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
