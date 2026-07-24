"""E3 lifecycle tests for the backend-neutral CPU domain adapter."""

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
backend = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_backend")

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


def _compiled(*, animation_pose_ratio=0.0):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payload = json.load(handle)["static_snapshots"][0]
    snapshot = ir.make_mc2_mesh_partition_static_snapshot(**payload)
    fragment = fragment_module.build_mc2_mesh_static_fragment(snapshot)
    profile = parameters.make_mc2_particle_profile(
        self_collision_mode=2,
        animation_pose_ratio=animation_pose_ratio,
    )
    options = parameters.make_mc2_setup_options("mesh_cloth")
    task = parameters.make_mc2_task_parameters()
    effective = runtime.make_mc2_runtime_parameters(profile, options, task)
    return compiler.compile_mc2_mesh_static_fragments(
        (fragment,), (effective,)
    )


def _frame(program, frame=1, generation=1):
    count = program.particle_count
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=frame,
        generation=generation,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        partition_world_position=((0.0, 0.0, 0.0),),
        partition_world_rotation=((0.0, 0.0, 0.0, 1.0),),
        partition_world_scale=((1.0, 1.0, 1.0),),
        partition_world_linear=(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),),
        velocity_weight=(1.0,),
        gravity_ratio=(1.0,),
    )


class _FakeKernel:
    def __init__(self, *, physical=False):
        self.created = []
        self.disposed = []
        self.frame = None
        self.physical = physical
        self.steps = 0
        self.pose_ratio = None

    def create_domain(self, program, parameters_packet):
        handle = {"program": program, "parameters": parameters_packet}
        self.created.append(handle)
        return handle

    def update_frame(self, handle, frame_packet):
        self.frame = frame_packet

    def step(self, handle, frame_packet, scheduler_settings, collider_snapshot):
        self.steps += 1

    def prepare_step_basic_pose(self, handle, animation_pose_ratio):
        self.pose_ratio = float(animation_pose_ratio)
        return {
            "positions": handle["program"].particle_bind_position,
            "rotations": handle["program"].particle_bind_rotation,
        }

    def read_output(self, handle):
        positions = self.frame.animated_base_world_positions
        if not self.physical:
            return ir.make_mc2_domain_frame_output(
                handle["program"], self.frame,
                world_positions=positions,
                backend_revision=1,
                backend_kind="fake_cpu",
            )
        p2l = np.asarray((2, 0, 1), dtype=np.uint32)
        physical = positions[p2l]
        return ir.make_mc2_domain_frame_output(
            handle["program"], self.frame,
            world_positions=physical,
            backend_revision=1,
            backend_kind="fake_cpu",
            index_order="physical",
            physical_to_logical=p2l,
        )

    def inspect(self, handle):
        return {"fake_steps": self.steps}

    def dispose(self, handle):
        self.disposed.append(handle)


def test_cpu_backend_lifecycle_and_partition_history():
    compiled = _compiled()
    kernel = _FakeKernel()
    domain = backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    domain.update_frame(frame)
    domain.step({"substeps": 1})
    output = domain.read_output()
    assert output.index_order == "logical"
    assert output.frame == 1 and output.generation == 1
    assert domain.inspect()["partition_history"]["sleeve"]["last_frame"] == 1
    assert kernel.steps == 1
    domain.dispose()
    domain.dispose()
    assert domain.disposed
    assert len(kernel.disposed) == 1


def test_cpu_backend_normalizes_physical_kernel_output():
    compiled = _compiled()
    kernel = _FakeKernel(physical=True)
    domain = backend.create_mc2_cpu_backend_domain(compiled, kernel)
    frame = _frame(compiled.program)
    domain.update_frame(frame)
    domain.step({"substeps": 1})
    output = domain.read_output()
    assert output.index_order == "logical"
    assert np.array_equal(output.world_positions, frame.animated_base_world_positions)
    domain.dispose()


def test_cpu_backend_capability_gate_rejects_before_kernel_allocation():
    compiled = _compiled()
    kernel = _FakeKernel()
    incompatible = backend.MC2_CPU_REFERENCE_CAPABILITIES.__class__(
        backend_id="cpu_without_self",
        schema_versions=(1,),
        setup_types=("mesh_cloth",),
        capabilities=("mesh_cloth",),
        max_particles=100,
        index_width_bits=32,
        supports_physical_reorder=True,
    )
    try:
        backend.create_mc2_cpu_backend_domain(compiled, kernel, capabilities=incompatible)
    except RuntimeError as exc:
        assert "capability:self_collision" in str(exc)
    else:
        raise AssertionError("incompatible CPU capability was accepted")
    assert kernel.created == []


def test_cpu_backend_declares_all_unified_cpu_setups():
    assert backend.MC2_CPU_REFERENCE_CAPABILITIES.setup_types == (
        "bone_cloth",
        "bone_spring",
        "mesh_cloth",
    )
    assert set(backend.MC2_CPU_REFERENCE_CAPABILITIES.capabilities) == {
        "bone_cloth",
        "bone_spring",
        "mesh_cloth",
        "self_collision",
    }


def test_cpu_backend_step_basic_uses_compiled_animation_pose_ratio_by_default():
    compiled = _compiled(animation_pose_ratio=0.625)
    kernel = _FakeKernel()
    domain = backend.create_mc2_cpu_backend_domain(compiled, kernel)
    domain.update_frame(_frame(compiled.program))
    domain.prepare_step_basic_pose()
    assert kernel.pose_ratio == 0.625
    domain.prepare_step_basic_pose(0.125)
    assert kernel.pose_ratio == 0.125
    domain.dispose()


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 CPU backend: {len(TESTS)} passed")
