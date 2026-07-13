"""Cross-ABI smoke test for the Python slot owner around MC2 context V0."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import types

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MC2_ROOT = ROOT / "OmniNode" / "NodeTree" / "Function" / "physicsWorld" / "mc2"
PHYSICS_WORLD = MC2_ROOT.parent
FUNCTION = PHYSICS_WORLD.parent
NODETREE = FUNCTION.parent
OMNINODE = NODETREE.parent

for package_name, package_path in (
    ("HoTools", ROOT),
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

names = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
frames = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state")
center = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state")
native = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native")


def test_owner_lifecycle_and_readback() -> None:
    module = native.native_module()
    baseline = module.mc2_context_v0_stats()["live"]
    profile = parameters.make_mc2_particle_profile(gravity=0.0)
    options = parameters.make_mc2_setup_options(names.MC2_SETUP_MESH_CLOTH)
    runtime_spec = runtime.make_mc2_runtime_parameters(profile, options)
    frame = frames.make_mc2_frame_input(
        task_id="mc2:test",
        topology_signature="topology",
        frame=4,
        generation=2,
        world_positions=((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),) * 2,
    )

    with native.MC2NativeContextV0(2) as owner:
        assert module.mc2_context_v0_stats()["live"] == baseline + 1
        owner.update_parameters(runtime_spec)
        owner.update_dynamic(frame)
        owner.reset()
        owner.step_no_collision(1.0 / 60.0)
        positions, rotations = owner.read()
        np.testing.assert_array_equal(positions, frame.world_positions)
        np.testing.assert_array_equal(rotations, frame.world_rotations_xyzw)
        info = owner.inspect()
        assert info["parameter_revision"] == 1
        assert info["dynamic_revision"] == 1
        assert info["reset_count"] == 1
        assert info["step_count"] == 1

    assert owner.disposed
    assert owner.inspect()["released"] is True
    assert module.mc2_context_v0_stats()["live"] == baseline


class _RecordingModule:
    def __init__(self) -> None:
        self.center_args = None
        self.step_calls = []
        self.freed = False

    def __getattr__(self, _name):
        return lambda *_args: None

    def mc2_context_v0_create(self, schema, count):
        assert schema == 0 and count == 1
        return object()

    def mc2_context_v0_update_center_dynamic(self, *args):
        self.center_args = args

    def mc2_context_v0_step(self, *args):
        self.step_calls.append(args)

    def mc2_context_v0_read_center_step(self, _handle, *outputs):
        expected = (
            (1.0, 2.0, 3.0), (0.0, 0.0, 0.0, 1.0),
            (0.1, 0.2, 0.3), (0.0, 0.1, 0.0, 0.995),
            (0.05, 0.1, 0.15), (0.0, 0.05, 0.0, 0.99875),
            (0.0, 1.0, 0.0),
        )
        for output, values in zip(outputs, expected):
            output[:] = values
        return {
            "frame_interpolation": 0.5,
            "step_move_inertia_ratio": 0.75,
            "step_rotation_inertia_ratio": 0.8,
            "angular_velocity": 1.25,
            "scale_ratio": 1.1,
            "gravity_dot": 0.9,
            "gravity_ratio": 0.4,
            "velocity_weight": 0.6,
            "blend_weight": 0.3,
        }

    def mc2_context_v0_free(self, _handle):
        self.freed = True


def test_owner_center_step_packing_dt_guard_and_readback() -> None:
    module = _RecordingModule()
    owner = native.MC2NativeContextV0(1, module=module)
    step_input = center.MC2CenterStepInputSpec(
        simulation_delta_time=0.1,
        frame_interpolation=0.5,
        old_frame_world_position=(0.0, 0.0, 0.0),
        frame_world_position=(2.0, 4.0, 6.0),
        old_frame_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        frame_world_rotation_xyzw=(0.0, 0.70710677, 0.0, 0.70710677),
        old_frame_world_scale=(1.0, 1.0, 1.0),
        frame_world_scale=(2.0, 1.0, 1.0),
        old_world_position=(0.0, 0.0, 0.0),
        old_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        initial_scale=(1.0, 1.0, 1.0),
        negative_scale_direction=(1.0, -1.0, 1.0),
        velocity_weight=0.2,
        distance_weight=0.8,
    )
    owner.update_center_dynamic(step_input)
    assert len(module.center_args) == 14
    for value in module.center_args[1:11]:
        assert value.dtype == np.float32 and value.flags.c_contiguous
    assert module.center_args[11:] == (0.8, 0.5, 0.2)

    owner.reset()
    owner.step_no_collision(0.2)
    assert len(module.step_calls) == 1
    owner.update_center_dynamic(step_input)

    try:
        owner.step_no_collision(0.2)
    except ValueError as exc:
        assert "simulation_delta_time" in str(exc)
    else:
        raise AssertionError("mismatched Center dt was accepted")
    assert len(module.step_calls) == 1
    owner.step_no_collision(0.1)
    assert len(module.step_calls) == 2

    result = owner.read_center_step()
    assert isinstance(result, center.MC2CenterStepResult)
    assert result.now_world_position == (1.0, 2.0, 3.0)
    np.testing.assert_allclose(result.inertia_vector, (0.05, 0.1, 0.15), atol=1.0e-7)
    assert result.blend_weight == 0.3
    owner.dispose()
    assert module.freed and owner.disposed


if __name__ == "__main__":
    test_owner_lifecycle_and_readback()
    print("PASS MC2 context V0 Python owner")
    test_owner_center_step_packing_dt_guard_and_readback()
    print("PASS MC2 context V0 Center wrapper")
