"""Tests for backend-neutral unified-domain output mapping."""

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
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.test", os.path.dirname(__file__)),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

ir = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir"
)
output = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_output"
)
domain_ir_test = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.test.test_domain_ir"
)


def _program():
    return domain_ir_test._build_program(domain_ir_test._load_fixture())


def _frame_and_output(program):
    count = program.particle_count
    base = np.asarray(program.particle_bind_position, dtype=np.float32)
    rotations = np.asarray(program.particle_bind_rotation, dtype=np.float32)
    linear = np.asarray((
        ((2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 1.0)),
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    ), dtype=np.float32)
    frame = ir.make_mc2_domain_frame_packet(
        program,
        frame=12,
        generation=4,
        animated_base_world_positions=base,
        animated_base_world_rotations=rotations,
        partition_world_position=np.zeros((2, 3), dtype=np.float32),
        partition_world_rotation=np.asarray(((0.0, 0.0, 0.0, 1.0),) * 2, dtype=np.float32),
        partition_world_scale=np.asarray(((2.0, 3.0, 1.0), (1.0, 1.0, 1.0)), dtype=np.float32),
        partition_world_linear=linear,
        is_running=True,
    )
    local_offsets = np.asarray((
        (0.10, 0.20, 0.30),
        (0.20, 0.30, 0.40),
        (0.30, 0.40, 0.50),
        (-0.10, -0.20, -0.30),
        (-0.20, -0.30, -0.40),
    ), dtype=np.float32)
    world = base.copy()
    world[:3] += local_offsets[:3] @ linear[0].T
    world[3:] += local_offsets[3:]
    frame_output = ir.make_mc2_domain_frame_output(
        program,
        frame,
        world_positions=world,
        world_rotations_xyzw=rotations,
        backend_revision=1,
        backend_kind="test",
    )
    return frame, frame_output, local_offsets


def test_domain_output_splits_logical_particles_and_unscales_offsets():
    program = _program()
    frame, frame_output, expected = _frame_and_output(program)
    commands = output.make_mc2_mesh_writeback_commands(program, frame, frame_output)
    assert [command.target_id for command in commands] == ["mesh:sleeve", "mesh:coat"]
    np.testing.assert_allclose(commands[0].object_local_offsets, expected[:3], atol=1.0e-6)
    np.testing.assert_allclose(commands[1].object_local_offsets, expected[3:], atol=1.0e-6)
    assert commands[0].source_elements.tolist() == [0, 1, 2]
    assert commands[1].source_elements.tolist() == [0, 1]
    assert commands[0].logical_particle_indices.tolist() == [0, 1, 2]
    assert commands[1].logical_particle_indices.tolist() == [3, 4]
    assert all(command.domain_signature == program.domain_signature for command in commands)
    assert all(command.layout_signature == program.layout_signature for command in commands)


def test_domain_output_rejects_frame_identity_mismatch():
    program = _program()
    frame, frame_output, _expected = _frame_and_output(program)
    invalid = ir.make_mc2_domain_frame_output(
        program,
        ir.make_mc2_domain_frame_packet(
            program,
            frame=13,
            generation=4,
            animated_base_world_positions=frame.animated_base_world_positions,
            animated_base_world_rotations=frame.animated_base_world_rotations,
            partition_world_position=frame.partition_world_position,
            partition_world_rotation=frame.partition_world_rotation,
            partition_world_scale=frame.partition_world_scale,
            partition_world_linear=frame.partition_world_linear,
        ),
        world_positions=frame_output.world_positions,
        world_rotations_xyzw=frame_output.world_rotations_xyzw,
        backend_revision=1,
        backend_kind="test",
    )
    try:
        output.make_mc2_mesh_writeback_commands(program, frame, invalid)
    except ValueError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("writeback mapper accepted a mismatched frame")


if __name__ == "__main__":
    test_domain_output_splits_logical_particles_and_unscales_offsets()
    test_domain_output_rejects_frame_identity_mismatch()
    print("PASS MC2 domain output mapping")
