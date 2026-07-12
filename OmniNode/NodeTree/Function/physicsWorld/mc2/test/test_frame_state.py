"""Pure N3 frame continuity and reset tests."""

from __future__ import annotations

import importlib
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


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
