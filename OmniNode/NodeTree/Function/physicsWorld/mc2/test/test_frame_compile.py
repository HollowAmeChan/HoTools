"""E3 pure frame packet compiler tests."""

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
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups", os.path.join(MC2_ROOT, "setups")),
    (
        "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth",
        os.path.join(MC2_ROOT, "setups", "mesh_cloth"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

ir = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir")
compiler = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile")
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
frame_compile = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_compile"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"]
    fragments = []
    for item in payload:
        snapshot = ir.make_mc2_mesh_partition_static_snapshot(**item)
        fragments.append(fragment_module.build_mc2_mesh_static_fragment(snapshot))
    profile = parameters.make_mc2_particle_profile(self_collision_mode=2)
    options = parameters.make_mc2_setup_options("mesh_cloth")
    effective = runtime.make_mc2_runtime_parameters(
        profile, options, parameters.make_mc2_task_parameters()
    )
    return compiler.compile_mc2_static_fragments(
        tuple(fragments), (effective, effective), domain_id="mc2.domain:frames"
    )


def _snapshot(partition_id, count, frame=8, generation=2):
    positions = np.arange(count * 3, dtype=np.float32).reshape((count, 3))
    normals = np.zeros((count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    rotations = np.zeros((count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    linear = np.eye(3, dtype=np.float32)
    for array in (positions, normals, linear):
        array.flags.writeable = False
    return frame_compile.MC2PartitionFrameSnapshotV1(
        partition_id=partition_id,
        frame=frame,
        generation=generation,
        animated_base_world_positions=positions,
        animated_base_world_rotations=rotations,
        animated_base_world_normals=normals,
        partition_world_position=(float(len(partition_id)), 0.0, 0.0),
        partition_world_rotation=(0.0, 0.0, 0.0, 1.0),
        partition_world_scale=(1.0, 1.0, 1.0),
        partition_world_linear=linear,
        velocity_weight=0.5,
        gravity_ratio=0.75,
    )


def test_frame_compile_relocates_partition_snapshots_to_logical_indices():
    compiled = _compiled()
    packet = frame_compile.compile_mc2_domain_frame_packet(
        compiled.program, (_snapshot("sleeve", 3), _snapshot("coat", 2))
    )
    assert packet.domain_signature == compiled.program.domain_signature
    assert packet.frame == 8 and packet.generation == 2
    assert packet.animated_base_world_positions.tolist() == [
        [0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0],
        [0.0, 1.0, 2.0], [3.0, 4.0, 5.0],
    ]
    assert packet.velocity_weight.tolist() == [0.5, 0.5]
    assert packet.animated_base_world_rotations[:, 3].tolist() == [1.0] * 5
    assert not packet.animated_base_world_positions.flags.writeable


def test_frame_compile_rejects_order_count_and_frame_mismatch():
    compiled = _compiled()
    try:
        frame_compile.compile_mc2_domain_frame_packet(
            compiled.program, (_snapshot("coat", 2), _snapshot("sleeve", 3))
        )
    except ValueError as exc:
        assert "partition order" in str(exc)
    else:
        raise AssertionError("partition order mismatch was accepted")
    try:
        frame_compile.compile_mc2_domain_frame_packet(
            compiled.program, (_snapshot("sleeve", 2), _snapshot("coat", 2))
        )
    except ValueError as exc:
        assert "particle count" in str(exc)
    else:
        raise AssertionError("particle count mismatch was accepted")
    try:
        frame_compile.compile_mc2_domain_frame_packet(
            compiled.program, (_snapshot("sleeve", 3), _snapshot("coat", 2, frame=9))
        )
    except ValueError as exc:
        assert "frame/generation" in str(exc)
    else:
        raise AssertionError("frame mismatch was accepted")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 frame compile: {len(TESTS)} passed")
