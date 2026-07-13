"""Pure tests for the private MC2 native readback candidate."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
from types import SimpleNamespace

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

candidate_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.candidate"
)
frame_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)


def _inputs():
    spec = SimpleNamespace(task_id="mc2:mesh:test", setup_type="mesh_cloth")
    slot = SimpleNamespace(slot_id=spec.task_id, world_generation=4)
    frame = frame_module.make_mc2_frame_input(
        task_id=spec.task_id,
        topology_signature="topology",
        frame=12,
        generation=3,
        world_positions=((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)),
        world_rotations_xyzw=((0.0, 0.0, 0.0, 1.0),) * 2,
        source_world_linear=((2.0, 0.0, 0.0), (0.0, 4.0, 0.0), (0.0, 0.0, 5.0)),
    )
    native_info = {
        "schema": "mc2_context_v0",
        "released": False,
        "initialized": True,
        "vertex_count": 2,
        "frame": 12,
        "generation": 3,
        "reset_count": 1,
        "step_count": 2,
        "dynamic_revision": 3,
    }
    return spec, slot, frame, native_info


def test_candidate_copies_readback_and_stays_private() -> None:
    spec, slot, frame, native_info = _inputs()
    positions = frame.world_positions.copy()
    positions += np.asarray(((2.0, 4.0, 5.0), (2.0, 4.0, 5.0)), dtype=np.float32)
    rotations = frame.world_rotations_xyzw.copy()
    candidate = candidate_module.make_mc2_result_candidate(
        spec=spec,
        slot=slot,
        frame_input=frame,
        revision=5,
        native_info=native_info,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    )
    positions.fill(99.0)
    rotations.fill(0.0)
    np.testing.assert_array_equal(
        candidate.world_positions,
        frame.world_positions + np.asarray(((2.0, 4.0, 5.0),) * 2, dtype=np.float32),
    )
    np.testing.assert_array_equal(candidate.world_rotations_xyzw, frame.world_rotations_xyzw)
    assert candidate.world_positions.flags.writeable is False
    assert candidate.world_rotations_xyzw.flags.writeable is False
    assert candidate.ready is False
    np.testing.assert_array_equal(
        candidate.mesh_object_local_offsets,
        np.ones((2, 3), dtype=np.float32),
    )
    assert candidate.mesh_object_local_offsets.flags.writeable is False
    assert candidate.debug_dict()["has_mesh_object_local_offsets"] is True
    assert candidate.debug_dict()["native_dynamic_revision"] == 3


def test_candidate_rejects_mismatched_native_identity() -> None:
    spec, slot, frame, native_info = _inputs()
    cases = (
        ("frame", 11, "frame identity"),
        ("generation", 2, "frame identity"),
        ("vertex_count", 3, "particle count"),
        ("initialized", False, "initialized"),
        ("released", True, "live native"),
    )
    for key, value, message in cases:
        invalid = dict(native_info)
        invalid[key] = value
        try:
            candidate_module.make_mc2_result_candidate(
                spec=spec,
                slot=slot,
                frame_input=frame,
                revision=1,
                native_info=invalid,
                world_positions=frame.world_positions,
                world_rotations_xyzw=frame.world_rotations_xyzw,
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"mismatched native {key} was accepted")

    wrong_slot = SimpleNamespace(slot_id="mc2:mesh:other", world_generation=4)
    try:
        candidate_module.make_mc2_result_candidate(
            spec=spec,
            slot=wrong_slot,
            frame_input=frame,
            revision=1,
            native_info=native_info,
            world_positions=frame.world_positions,
            world_rotations_xyzw=frame.world_rotations_xyzw,
        )
    except ValueError as exc:
        assert "host task identity" in str(exc)
    else:
        raise AssertionError("mismatched host task identity was accepted")

    missing_linear_frame = frame_module.make_mc2_frame_input(
        task_id=frame.task_id,
        topology_signature=frame.topology_signature,
        frame=frame.frame,
        generation=frame.generation,
        world_positions=frame.world_positions,
        world_rotations_xyzw=frame.world_rotations_xyzw,
    )
    try:
        candidate_module.make_mc2_result_candidate(
            spec=spec,
            slot=slot,
            frame_input=missing_linear_frame,
            revision=1,
            native_info=native_info,
            world_positions=frame.world_positions,
            world_rotations_xyzw=frame.world_rotations_xyzw,
        )
    except ValueError as exc:
        assert "world linear snapshot" in str(exc)
    else:
        raise AssertionError("Mesh candidate accepted a missing source transform snapshot")


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
