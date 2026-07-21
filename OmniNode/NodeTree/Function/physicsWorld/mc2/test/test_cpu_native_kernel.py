"""E3 Python adapter to native CPU data-path owner integration test."""

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
cpu_backend = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_backend")
native_kernel = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    effective = runtime.make_mc2_runtime_parameters(
        parameters.make_mc2_particle_profile(self_collision_mode=2),
        parameters.make_mc2_setup_options("mesh_cloth"),
        parameters.make_mc2_task_parameters(),
    )
    return compiler.compile_mc2_mesh_static_fragment(fragment, effective)


def _frame(program):
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=6,
        generation=2,
        animated_base_world_positions=program.particle_bind_position + np.float32(2.0),
        animated_base_world_normals=np.asarray(((0.0, 0.0, 1.0),) * 3, dtype=np.float32),
        partition_world_position=((2.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
    )


def test_native_cpu_kernel_runs_only_explicit_data_path_mode():
    compiled = _compiled()
    kernel = native_kernel.MC2NativeCPUKernelV1()
    domain = cpu_backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    try:
        domain.update_frame(frame)
        try:
            domain.step({"substeps": 1})
        except RuntimeError as exc:
            assert "numerical kernel is not ready" in str(exc)
        else:
            raise AssertionError("native data-path owner accepted a product step")
        domain.step({"data_path_only": True})
        output = domain.read_output()
        assert output.frame == frame.frame and output.generation == frame.generation
        assert np.array_equal(output.world_positions, frame.animated_base_world_positions)
        inspection = domain.inspect()
        assert inspection["kernel"]["numerical_kernel_ready"] is False
        assert inspection["step_count"] == 1
    finally:
        domain.dispose()
    assert domain.disposed


if __name__ == "__main__":
    test_native_cpu_kernel_runs_only_explicit_data_path_mode()
    print("PASS test_native_cpu_kernel_runs_only_explicit_data_path_mode")
