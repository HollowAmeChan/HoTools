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
    return collector.build_mc2_domain_draft(
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
        self.fail_parameter_stage = False
        self.frame = None
        self.full_steps = []
        self.parameter_updates = []

    def create_domain(self, program, parameter_packet):
        if self.fail_create:
            raise RuntimeError("injected native create failure")
        handle = {"serial": len(self.created), "program": program, "parameters": parameter_packet}
        self.created.append(handle)
        return handle

    def stage_parameter_update(self, handle, program, parameter_packet):
        if self.fail_parameter_stage:
            raise RuntimeError("injected native parameter stage failure")
        update = {
            "handle": handle,
            "old_program": handle["program"],
            "old_parameters": handle["parameters"],
            "new_program": program,
            "new_parameters": parameter_packet,
            "applied": False,
            "closed": False,
        }
        self.parameter_updates.append(update)
        return update

    def apply_parameter_update(self, handle, update):
        assert update["handle"] is handle and not update["applied"]
        handle["program"] = update["new_program"]
        handle["parameters"] = update["new_parameters"]
        update["applied"] = True

    def rollback_parameter_update(self, handle, update):
        assert update["handle"] is handle and update["applied"]
        handle["program"] = update["old_program"]
        handle["parameters"] = update["old_parameters"]
        update["applied"] = False

    def finish_parameter_update(self, handle, update):
        assert update["handle"] is handle and update["applied"]
        update["closed"] = True

    def discard_parameter_update(self, update):
        assert not update["applied"]
        update["closed"] = True

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

    def read_debug_state(self, handle):
        return {"serial": handle["serial"], "real_velocities": np.zeros((0, 3), dtype=np.float32)}

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
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
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
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
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


def test_owner_exposes_explicit_product_debug_state():
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
    owner.sync(_draft(), _snapshots())
    program = owner.compiled.program
    rotations = np.zeros((program.particle_count, 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    owner.update_frame(
        ir.make_mc2_domain_frame_packet(
            program,
            frame=1,
            generation=1,
            animated_base_world_positions=program.particle_bind_position,
            animated_base_world_rotations=rotations,
            partition_world_position=np.zeros((2, 3), dtype=np.float32),
            partition_world_rotation=np.asarray(
                ((0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, 1.0)),
                dtype=np.float32,
            ),
            partition_world_scale=np.ones((2, 3), dtype=np.float32),
            partition_world_linear=np.asarray((np.eye(3), np.eye(3)), dtype=np.float32),
            velocity_weight=(1.0, 0.5),
            gravity_ratio=(1.0, 0.75),
        )
    )
    state = owner.read_debug_state()
    assert state["serial"] == 0
    assert state["real_velocities"].shape == (0, 3)
    inspection = owner.inspect()
    assert inspection["domain"]["kernel"]["serial"] == 0


def test_parameter_change_updates_same_domain_and_preserves_history():
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
    owner.sync(_draft(gravity=5.0), _snapshots())
    old_domain = owner.domain
    old_handle = kernel.created[0]
    old_parameter_signature = owner.compiled.parameters.parameter_signature
    report = owner.sync(_draft(gravity=6.0), _snapshots())
    assert report.action == "parameters_updated"
    assert report.native_domain_reused
    assert report.compile_cache.program_cache_hit
    assert report.compile_cache.parameter_layout_cache_hit
    assert not report.compile_cache.parameter_value_cache_hit
    assert owner.domain is old_domain
    assert kernel.created == [old_handle] and kernel.disposed == []
    assert old_handle["parameters"] is owner.compiled.parameters
    assert owner.compiled.parameters.parameter_signature != old_parameter_signature
    assert kernel.parameter_updates[0]["closed"]


def test_partition_gravity_direction_change_rebuilds_only_its_fragment():
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
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


def test_native_parameter_stage_failure_preserves_live_domain_and_cache_commit():
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
    owner.sync(_draft(), _snapshots())
    old_domain = owner.domain
    old_compiled = owner.compiled
    old_owner_revision = owner.revision
    old_cache_revision = owner.fragment_cache.revision
    kernel.fail_parameter_stage = True
    try:
        owner.sync(_draft(gravity=6.0), _snapshots())
    except RuntimeError as exc:
        assert "injected native parameter stage failure" in str(exc)
    else:
        raise AssertionError("native parameter stage failure was accepted")
    assert owner.domain is old_domain and owner.compiled is old_compiled
    assert owner.revision == old_owner_revision
    assert owner.fragment_cache.revision == old_cache_revision
    assert kernel.disposed == []


def test_host_commit_failure_rolls_back_applied_native_parameters():
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
    owner.sync(_draft(gravity=5.0), _snapshots())
    old_domain = owner.domain
    old_compiled = owner.compiled
    old_parameters = kernel.created[0]["parameters"]

    def fail_commit():
        raise RuntimeError("injected host commit failure")

    try:
        owner.sync_fragments(
            _draft(gravity=6.0),
            old_compiled.fragments,
            fragment_cache_revision=owner.fragment_cache.revision,
            fragment_cache_hits=2,
            commit_static=fail_commit,
        )
    except RuntimeError as exc:
        assert "injected host commit failure" in str(exc)
    else:
        raise AssertionError("host commit failure was accepted")
    assert owner.domain is old_domain and owner.compiled is old_compiled
    assert kernel.created[0]["parameters"] is old_parameters
    assert not kernel.parameter_updates[-1]["applied"]
    assert kernel.parameter_updates[-1]["closed"]


def test_fragment_failure_preserves_live_domain_and_fragment_cache():
    snapshots = _snapshots()
    builder = _FailingBuilder()
    cache = cache_module.MC2MeshFragmentCacheV1(builder)
    kernel = _FakeKernel()
    owner = owner_module.MC2FusedCPUOwnerV1(kernel, fragment_cache=cache)
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
    owner = owner_module.MC2FusedCPUOwnerV1(kernel)
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
