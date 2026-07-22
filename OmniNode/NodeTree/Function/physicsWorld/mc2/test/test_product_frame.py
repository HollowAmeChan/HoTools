"""E4 whole-domain Mesh product frame compilation tests."""

from __future__ import annotations

from dataclasses import replace
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
compile_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_compile")
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
runtime = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters")
product_frame = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_frame")

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"]
    first = ir.make_mc2_mesh_partition_static_snapshot(**payload[0])
    second = replace(
        first,
        partition_id="coat",
        source_identity="source:coat",
        source_revision="revision:coat:v1",
        output_target_id="mesh:coat",
    )
    fragments = tuple(
        fragment_module.build_mc2_mesh_static_fragment(snapshot)
        for snapshot in (first, second)
    )
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(self_collision_mode=0),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return compile_module.compile_mc2_mesh_static_fragments(
        fragments,
        (effective, effective),
        domain_id="mc2.domain:product-frame-test",
    )


def _row(
    partition_id,
    output_target_id,
    positions,
    *,
    component_position=(0.0, 0.0, 0.0),
    anchor_present=0,
):
    normals = np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32)
    return product_frame.MC2MeshProductFrameRowV1(
        partition_id=partition_id,
        output_target_id=output_target_id,
        frame=12,
        generation=4,
        animated_base_world_positions=np.asarray(positions, dtype=np.float32),
        animated_base_world_normals=normals,
        source_world_linear=np.eye(3, dtype=np.float32),
        component_world_position=component_position,
        component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        component_world_scale=(1.0, 1.0, 1.0),
        anchor_world_position=(9.0, 8.0, 7.0) if anchor_present else (0.0, 0.0, 0.0),
        anchor_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        anchor_present=anchor_present,
        velocity_weight=0.75,
        gravity_ratio=0.5,
    )


def test_product_frame_compiles_two_partition_pose_and_metadata():
    compiled = _compiled()
    sleeve = _row(
        "sleeve", "mesh:sleeve",
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.2), (0.0, 1.0, 0.0)),
        component_position=(1.0, 2.0, 3.0),
        anchor_present=1,
    )
    coat = _row(
        "coat", "mesh:coat",
        ((4.0, 0.0, 0.0), (4.0, 1.0, 0.0), (4.0, 0.0, 1.0)),
        component_position=(4.0, 5.0, 6.0),
    )
    packet, snapshots = product_frame.compile_mc2_mesh_product_frame(
        compiled, (sleeve, coat)
    )
    assert packet.frame == 12 and packet.generation == 4
    assert [snapshot.partition_id for snapshot in snapshots] == ["sleeve", "coat"]
    np.testing.assert_array_equal(packet.animated_base_world_positions[:3], sleeve.animated_base_world_positions)
    np.testing.assert_array_equal(packet.animated_base_world_positions[3:], coat.animated_base_world_positions)
    np.testing.assert_allclose(
        np.linalg.norm(packet.animated_base_world_rotations, axis=1),
        1.0,
        rtol=1.0e-6,
        atol=1.0e-6,
    )
    assert not np.allclose(
        packet.animated_base_world_rotations[:3],
        packet.animated_base_world_rotations[3:],
    )
    np.testing.assert_array_equal(packet.partition_world_position, ((1, 2, 3), (4, 5, 6)))
    np.testing.assert_array_equal(packet.anchor_present, (1, 0))
    np.testing.assert_array_equal(packet.anchor_world_position[0], (9, 8, 7))
    np.testing.assert_allclose(packet.velocity_weight, (0.75, 0.75))
    np.testing.assert_allclose(packet.gravity_ratio, (0.5, 0.5))


def test_product_frame_rejects_partition_or_target_order_mismatch():
    compiled = _compiled()
    first = _row("sleeve", "mesh:sleeve", ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
    wrong = _row("coat", "mesh:wrong", ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
    try:
        product_frame.compile_mc2_mesh_product_frame(compiled, (first, wrong))
    except ValueError as exc:
        assert "output target mismatch" in str(exc)
    else:
        raise AssertionError("mismatched Mesh output target was accepted")
    try:
        product_frame.compile_mc2_mesh_product_frame(compiled, (wrong, first))
    except ValueError as exc:
        assert "partition order" in str(exc)
    else:
        raise AssertionError("mismatched Mesh partition order was accepted")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 product frame: {len(TESTS)} passed")
