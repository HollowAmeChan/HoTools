"""E4 tests for transactional fused CPU domain ownership."""

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
collector = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_collect")
owner_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_owner")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
partition_specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs")
fragment_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_fragment"
)
cache_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.fragment_cache"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


class _FakeData:
    def __init__(self, pointer):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _FakeSource:
    type = "MESH"

    def __init__(self, pointer):
        self._pointer = pointer
        self.name = self.name_full = f"Mesh{pointer}"
        self.data = _FakeData(pointer + 1000)

    def as_pointer(self):
        return self._pointer


def _draft(*, gravity=5.0):
    entries = (
        partition_specs.make_mc2_partition_entry(
            _FakeSource(1), setup_type="mesh_cloth", stable_id="sleeve",
            profile=parameters.make_mc2_particle_profile(
                gravity=gravity, damping=0.1, self_collision_mode=2,
            ),
            task_parameters=parameters.make_mc2_task_parameters(cloth_mass=0.2),
            setup_options=parameters.make_mc2_setup_options(
                "mesh_cloth", collided_by_groups=1,
            ),
            collision_mask=3,
        ),
        partition_specs.make_mc2_partition_entry(
            _FakeSource(2), setup_type="mesh_cloth", stable_id="coat",
            profile=parameters.make_mc2_particle_profile(
                gravity=8.0, damping=0.3, self_collision_mode=2,
            ),
            task_parameters=parameters.make_mc2_task_parameters(cloth_mass=0.8),
            setup_options=parameters.make_mc2_setup_options(
                "mesh_cloth", collided_by_groups=2,
            ),
            collision_group=8, collision_mask=8,
        ),
    )
    plan = partition_specs.collect_mc2_partition_entries(
        setup_type="mesh_cloth", explicit_entries=entries,
    )
    return collector.build_mc2_mesh_domain_draft(
        plan, domain_id="mc2.domain:fused-owner-test",
    )


def _snapshots():
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payloads = json.load(handle)["static_snapshots"]
    return tuple(
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
        for payload in payloads
    )


class _FakeKernel:
    def __init__(self):
        self.created = []
        self.disposed = []
        self.fail_create = False
        self.frame = None
        self.full_steps = []

    def create_domain(self, program, parameter_packet):
        if self.fail_create:
            raise RuntimeError("injected native create failure")
        handle = {"serial": len(self.created), "program": program, "parameters": parameter_packet}
        self.created.append(handle)
        return handle

    def update_frame(self, handle, frame_packet):
        self.frame = frame_packet

    def step(self, handle, frame_packet, scheduler_settings, collider_snapshot):
        pass

    def read_output(self, handle):
        return ir.make_mc2_domain_frame_output(
            handle["program"], self.frame,
            world_positions=self.frame.animated_base_world_positions,
            backend_revision=1, backend_kind="fake_fused_cpu",
        )

    def step_compiled_domain_pipeline_full(self, handle, settings):
        self.full_steps.append((handle, settings))

    def inspect(self, handle):
        return {"serial": handle["serial"]}

    def dispose(self, handle):
        self.disposed.append(handle)


class _FailingBuilder:
    def __init__(self):
        self.fail_partition = None

    def __call__(self, snapshot, *, world_gravity_direction):
        if snapshot.partition_id == self.fail_partition:
            raise RuntimeError("injected fragment failure")
        return fragment_module.build_mc2_mesh_static_fragment(
            snapshot, world_gravity_direction=world_gravity_direction,
        )


def test_owner_creates_once_then_reuses_exact_native_domain():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    first = owner.sync(_draft(), _snapshots())
    domain = owner.domain
    second = owner.sync(_draft(), _snapshots())
    assert first.action == "created" and first.fragment_builds == 2
    assert second.action == "reused" and second.fragment_cache_hits == 2
    assert second.compile_cache.exact_cache_hit
    assert owner.domain is domain and len(kernel.created) == 1
    owner.dispose()
    assert len(kernel.disposed) == 1


def test_owner_delegates_frame_full_pipeline_and_logical_output():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    owner.sync(_draft(), _snapshots())
    program = owner.compiled.program
    particle_count = program.particle_count
    rotations = np.zeros((particle_count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    frame = ir.make_mc2_domain_frame_packet(
        program, frame=3, generation=7,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=rotations,
        partition_world_position=np.zeros((2, 3), dtype=np.float32),
        partition_world_rotation=np.asarray(
            ((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, 1.0)), dtype=np.float32,
        ),
        partition_world_scale=np.ones((2, 3), dtype=np.float32),
        partition_world_linear=np.asarray((np.eye(3), np.eye(3)), dtype=np.float32),
        velocity_weight=(1.0, 0.5), gravity_ratio=(1.0, 0.75),
    )
    settings = {"opaque_native_inputs": True}
    owner.update_frame(frame)
    owner.step(settings)
    output = owner.read_output()
    assert kernel.full_steps == [(kernel.created[0], settings)]
    assert output.frame == 3 and output.generation == 7
    assert output.world_positions.tolist() == program.particle_bind_position.tolist()


def test_parameter_change_stages_replacement_until_hot_update_abi_exists():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    owner.sync(_draft(gravity=5.0), _snapshots())
    old_domain = owner.domain
    report = owner.sync(_draft(gravity=6.0), _snapshots())
    assert report.action == "replaced"
    assert report.compile_cache.program_cache_hit
    assert not report.compile_cache.parameter_value_cache_hit
    assert owner.domain is not old_domain
    assert len(kernel.created) == 2 and len(kernel.disposed) == 1


def test_partition_gravity_direction_change_rebuilds_only_its_fragment():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    snapshots = _snapshots()
    owner.sync(
        _draft(), snapshots,
        world_gravity_directions=((0.0, -1.0, 0.0), (0.0, -1.0, 0.0)),
    )
    report = owner.sync(
        _draft(), snapshots,
        world_gravity_directions=((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    )
    assert report.action == "replaced"
    assert report.fragment_cache_hits == 1 and report.fragment_builds == 1
    assert not report.compile_cache.program_cache_hit


def test_native_create_failure_preserves_live_domain_and_cache_commit():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    owner.sync(_draft(), _snapshots())
    old_domain = owner.domain
    old_compiled = owner.compiled
    old_owner_revision = owner.revision
    old_cache_revision = owner.fragment_cache.revision
    kernel.fail_create = True
    try:
        owner.sync(_draft(gravity=6.0), _snapshots())
    except RuntimeError as exc:
        assert "injected native create failure" in str(exc)
    else:
        raise AssertionError("native create failure was accepted")
    assert owner.domain is old_domain and owner.compiled is old_compiled
    assert owner.revision == old_owner_revision
    assert owner.fragment_cache.revision == old_cache_revision
    assert kernel.disposed == []


def test_fragment_failure_preserves_live_domain_and_fragment_cache():
    snapshots = _snapshots()
    builder = _FailingBuilder()
    cache = cache_module.MC2MeshFragmentCacheV1(builder)
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel, fragment_cache=cache)
    owner.sync(_draft(), snapshots)
    old_domain = owner.domain
    old_revision = cache.revision
    changed = (
        snapshots[0],
        replace(snapshots[1], source_revision="revision:coat:v2"),
    )
    builder.fail_partition = "coat"
    try:
        owner.sync(_draft(), changed)
    except RuntimeError as exc:
        assert "injected fragment failure" in str(exc)
    else:
        raise AssertionError("fragment failure was accepted")
    assert owner.domain is old_domain
    assert cache.revision == old_revision and cache.entry_count == 2
    assert len(kernel.created) == 1 and kernel.disposed == []


def test_snapshot_order_mismatch_fails_before_any_staging():
    kernel = _FakeKernel()
    owner = owner_module.MC2MeshFusedCPUOwnerV1(kernel)
    snapshots = _snapshots()
    try:
        owner.sync(_draft(), tuple(reversed(snapshots)))
    except ValueError as exc:
        assert "snapshot order" in str(exc)
    else:
        raise AssertionError("snapshot order mismatch was accepted")
    assert owner.revision == 0 and owner.fragment_cache.revision == 0
    assert kernel.created == []


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 fused CPU owner: {len(TESTS)} passed")
