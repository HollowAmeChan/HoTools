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


if __name__ == "__main__":
    test_owner_lifecycle_and_readback()
    print("PASS MC2 context V0 Python owner")
