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
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.results"
)
frame_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
results_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.results"
)


class _PointerOwner:
    def __init__(self, pointer: int) -> None:
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


class _MeshSource(_PointerOwner):
    def __init__(self, pointer: int, data_pointer: int) -> None:
        super().__init__(pointer)
        self.type = "MESH"
        self.data = _PointerOwner(data_pointer)


class _ResultWorld:
    def __init__(self, frame: int = 12, generation: int = 4) -> None:
        self.frame_context = SimpleNamespace(frame=frame)
        self.generation = generation
        self.result_streams = {}
        self.fail_publish = False

    def clear_results(self, channel=None, solver=None) -> None:
        if channel is None and solver is None:
            self.result_streams.clear()
            return
        channels = (str(channel),) if channel is not None else tuple(self.result_streams)
        for result_channel in channels:
            items = self.result_streams.get(result_channel, ())
            if solver is None:
                self.result_streams.pop(result_channel, None)
                continue
            kept = [item for item in items if item.get("solver") != solver]
            if kept:
                self.result_streams[result_channel] = kept
            else:
                self.result_streams.pop(result_channel, None)

    def publish_result(self, item, channel=None, solver="unknown", **payload):
        if self.fail_publish:
            raise RuntimeError("injected publish failure")
        result = dict(item or {})
        result.update(payload)
        result["channel"] = str(channel or result.get("channel") or "")
        result.setdefault("solver", solver)
        self.result_streams.setdefault(result["channel"], []).append(result)
        return result

    def consume_results(self, channel, solver=None, frame=None, generation=None):
        items = list(self.result_streams.get(str(channel), ()))
        if solver is not None:
            items = [item for item in items if item.get("solver") == solver]
        if frame is not None:
            items = [item for item in items if item.get("frame") == frame]
        if generation is not None:
            items = [item for item in items if item.get("generation") == generation]
        return items


def _inputs():
    source = _MeshSource(101, 202)
    spec = SimpleNamespace(
        task_id="mc2:mesh:test",
        setup_type="mesh_cloth",
        topology_signature="topology",
        sources=(source,),
    )
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
    assert candidate.schema_version == 1
    assert candidate.ready is False
    np.testing.assert_array_equal(
        candidate.mesh_object_local_offsets,
        np.ones((2, 3), dtype=np.float32),
    )
    assert candidate.mesh_object_local_offsets.flags.writeable is False
    assert candidate.debug_dict()["has_mesh_object_local_offsets"] is True
    assert candidate.debug_dict()["has_bone_component_world_rotation"] is False
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


def test_public_mesh_result_is_ready_and_read_only() -> None:
    spec, slot, frame, native_info = _inputs()
    candidate = candidate_module.make_mc2_result_candidate(
        spec=spec,
        slot=slot,
        frame_input=frame,
        revision=5,
        native_info=native_info,
        world_positions=frame.world_positions + np.float32(1.0),
        world_rotations_xyzw=frame.world_rotations_xyzw,
    )
    result = results_module.make_mc2_mesh_result(
        spec=spec,
        candidate=candidate,
        frame=12,
        world_generation=4,
    )
    assert result["ready"] is True
    assert result["revision"] == 5
    assert result["frame_generation"] == 3
    assert result["generation"] == result["world_generation"] == 4
    assert result["object_ptr"] == 101
    assert result["object_data_ptr"] == 202
    assert result["local_offsets"].flags.writeable is False
    np.testing.assert_allclose(
        result["local_offsets"],
        ((0.5, 0.25, 0.2),) * 2,
        rtol=0.0,
        atol=1.0e-7,
    )


def test_public_result_transaction_replaces_same_frame_without_revision_change() -> None:
    spec, slot, frame, native_info = _inputs()
    candidate = candidate_module.make_mc2_result_candidate(
        spec=spec,
        slot=slot,
        frame_input=frame,
        revision=7,
        native_info=native_info,
        world_positions=frame.world_positions,
        world_rotations_xyzw=frame.world_rotations_xyzw,
    )
    result = results_module.make_mc2_mesh_result(
        spec=spec,
        candidate=candidate,
        frame=12,
        world_generation=4,
    )
    world = _ResultWorld()
    other_result = {"channel": "gn_attribute", "solver": "other"}
    world.result_streams["gn_attribute"] = [other_result]
    first = results_module.publish_mc2_result_transaction(world, (result,))
    second = results_module.publish_mc2_result_transaction(world, (result,))
    assert first[0]["revision"] == second[0]["revision"] == 7
    assert world.result_streams["gn_attribute"][0] is other_result
    assert len(world.result_streams["gn_attribute"]) == 2


def test_public_result_transaction_rolls_back_on_publish_failure() -> None:
    spec, slot, frame, native_info = _inputs()
    candidate = candidate_module.make_mc2_result_candidate(
        spec=spec,
        slot=slot,
        frame_input=frame,
        revision=2,
        native_info=native_info,
        world_positions=frame.world_positions,
        world_rotations_xyzw=frame.world_rotations_xyzw,
    )
    result = results_module.make_mc2_mesh_result(
        spec=spec,
        candidate=candidate,
        frame=12,
        world_generation=4,
    )
    world = _ResultWorld()
    previous = {
        "channel": "gn_attribute",
        "solver": "other",
        "slot_id": "other:slot",
    }
    old_mc2 = {
        "channel": "gn_attribute",
        "solver": "mc2",
        "slot_id": "old:mc2",
    }
    world.result_streams["gn_attribute"] = [previous, old_mc2]
    old_stats = {
        "channel": "mc2_stats",
        "solver": "mc2",
        "frame": 11,
        "generation": 4,
    }
    world.result_streams["mc2_stats"] = [old_stats]
    world.fail_publish = True
    try:
        results_module.publish_mc2_result_transaction(world, (result,))
    except RuntimeError as exc:
        assert "injected publish failure" in str(exc)
    else:
        raise AssertionError("MC2 publish failure was not propagated")
    assert world.result_streams == {
        "gn_attribute": [previous, old_mc2],
        "mc2_stats": [old_stats],
    }


def test_stats_result_normalizes_aggregate_and_slot_snapshots() -> None:
    result = results_module.make_mc2_stats_result(
        frame=12,
        generation=4,
        writeback_result_count=2,
        slots=(
            {
                "slot_id": "mc2:mesh:b",
                "setup_type": "mesh_cloth",
                "native_schema": "mc2_context_v0",
                "native_available": True,
                "initialized": True,
                "particle_count": 6,
                "reset_count": 1,
                "step_count": 3,
                "dynamic_revision": 4,
                "ignored_handle": object(),
            },
            {
                "slot_id": "mc2:bone:a",
                "setup_type": "bone_spring",
                "native_available": True,
                "particle_count": 2,
                "step_count": 5,
            },
        ),
    )
    assert result["channel"] == "mc2_stats"
    assert result["schema"] == "mc2_stats_v0"
    assert result["mc2_stats_schema"] == 0
    assert result["slot_count"] == result["native_context_count"] == 2
    assert result["mesh_cloth_count"] == result["bone_spring_count"] == 1
    assert result["bone_cloth_count"] == 0
    assert result["particle_count"] == 8
    assert result["reset_count"] == 1
    assert result["step_count"] == 8
    assert result["writeback_result_count"] == 2
    assert tuple(item["slot_id"] for item in result["slots"]) == (
        "mc2:bone:a",
        "mc2:mesh:b",
    )
    assert "ignored_handle" not in result["slots"][1]


def test_public_result_transaction_accepts_mesh_and_bone_channels_atomically() -> None:
    world = _ResultWorld()
    mesh = {
        "channel": "gn_attribute",
        "solver": "mc2",
        "slot_id": "mc2:mesh:test",
        "target_key": "101:202",
        "frame": 12,
        "generation": 4,
        "ready": True,
    }
    bone = {
        "channel": "bone_transform",
        "writeback_type": "bone_transform_batch",
        "solver": "mc2",
        "slot_id": "mc2:bone:test",
        "target_key": "303:404",
        "frame": 12,
        "generation": 4,
        "ready": True,
    }
    stats = results_module.make_mc2_stats_result(
        frame=12,
        generation=4,
        slots=(),
        writeback_result_count=2,
    )
    published = results_module.publish_mc2_result_transaction(world, (mesh, bone, stats))
    assert tuple(result["channel"] for result in published) == (
        "gn_attribute",
        "bone_transform",
        "mc2_stats",
    )
    assert len(world.result_streams["gn_attribute"]) == 1
    assert len(world.result_streams["bone_transform"]) == 1
    assert results_module.get_mc2_stats_result(world) is published[2]


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
            print(f"PASS {name}")
