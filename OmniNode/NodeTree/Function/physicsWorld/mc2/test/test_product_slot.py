"""E4 Physics World ownership tests for the staged fused Mesh slot."""

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

world_types = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.types")
ir = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_ir")
collector = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_collect")
parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
partitions = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs")
product = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_collect")
slot_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot")
product_frame_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_frame"
)
collider_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.collider_frame")
native_kernel_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.cpu_native_kernel"
)

FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "domain_pipeline", "two_mesh_static", "two_mesh_domain_v1.json",
)


class _Data:
    def __init__(self, pointer):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Source:
    type = "MESH"

    def __init__(self, pointer, name):
        self._pointer = pointer
        self.data = _Data(pointer + 1000)
        self.name = self.name_full = name

    def as_pointer(self):
        return self._pointer


def _collection(*, gravity=5.0):
    with open(FIXTURE, "r", encoding="utf-8") as handle:
        payloads = json.load(handle)["static_snapshots"]
    snapshots = tuple(
        ir.make_mc2_mesh_partition_static_snapshot(**payload)
        for payload in payloads
    )
    sources = (_Source(1, "Sleeve"), _Source(2, "Coat"))
    entries = tuple(
        partitions.make_mc2_partition_entry(
            source, setup_type="mesh_cloth", stable_id=snapshot.partition_id,
            profile=parameters.make_mc2_particle_profile(
                gravity=gravity if index == 0 else 8.0, self_collision_mode=2,
            ),
            setup_options=parameters.make_mc2_setup_options("mesh_cloth"),
            task_parameters=parameters.make_mc2_task_parameters(),
        )
        for index, (source, snapshot) in enumerate(zip(sources, snapshots))
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type="mesh_cloth", explicit_entries=entries,
    )
    draft = collector.build_mc2_mesh_domain_draft(
        plan, domain_id="mc2.domain:product-slot-test",
    )
    return product.MC2MeshProductCollectionV1(
        draft=draft, static_snapshots=snapshots,
        task_ids=("task:sleeve", "task:coat"),
        observation_identities=((1, "mesh_cloth", 1, 1001), (1, "mesh_cloth", 2, 1002)),
        observation_statuses=("hit", "hit"),
        mesh_topology_signatures=("1" * 64, "2" * 64),
    )


class _Kernel:
    def __init__(self):
        self.created = []
        self.disposed = []
        self.frames = []
        self.poses = []
        self.full_steps = []
        self.fail_create = False
        self.fail_update = False
        self.fail_step = False

    def create_domain(self, program, packet):
        if self.fail_create:
            raise RuntimeError("injected slot create failure")
        handle = {"program": program, "packet": packet, "serial": len(self.created)}
        self.created.append(handle)
        return handle

    def update_frame(self, handle, frame):
        if self.fail_update:
            raise RuntimeError("injected frame update failure")
        self.frames.append((handle, frame))
    def prepare_step_basic_pose(self, handle, _ratios):
        self.poses.append(handle)
        return {
            "positions": handle["program"].particle_bind_position,
            "rotations": handle["program"].particle_bind_rotation,
        }
    def step_compiled_domain_pipeline_full(self, handle, settings):
        if self.fail_step:
            raise RuntimeError("injected fused substep failure")
        self.full_steps.append((handle, settings))
    def step(self, handle, frame, settings, colliders): pass
    def read_output(self, handle): raise AssertionError("not used")
    def inspect(self, handle): return {"serial": handle["serial"]}
    def dispose(self, handle): self.disposed.append(handle)


def _world(generation=1):
    world = world_types.PhysicsWorldCache()
    world.generation = generation
    return world


def test_slot_create_update_and_world_dispose_own_one_handle():
    world = _world()
    kernel = _Kernel()
    created = slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    owner = slot.data["owner"]
    scheduler_state = slot.data["scheduler_state"]
    updated = slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    assert created.action == "created" and updated.action == "updated"
    assert updated.owner_report.action == "reused"
    assert world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID] is slot
    assert slot.data["owner"] is owner and len(kernel.created) == 1
    assert slot.data["scheduler_state"] is scheduler_state
    assert slot.data["product_enabled"] is False
    world.omni_cache_dispose("test_complete")
    assert len(kernel.disposed) == 1 and world.solver_slots == {}


def test_generation_change_stages_new_slot_then_disposes_old_owner():
    world = _world(generation=1)
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    old_slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    world.generation = 2
    replaced = slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    new_slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    assert replaced.action == "replaced" and new_slot is not old_slot
    assert new_slot.world_generation == 2
    assert len(kernel.created) == 2 and len(kernel.disposed) == 1


def test_staged_create_failure_preserves_previous_generation_slot():
    world = _world(generation=1)
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    old_slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    world.generation = 2
    kernel.fail_create = True
    try:
        slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    except RuntimeError as exc:
        assert "injected slot create failure" in str(exc)
    else:
        raise AssertionError("slot create failure was accepted")
    assert world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID] is old_slot
    assert old_slot.data["owner"].domain is not None
    assert kernel.disposed == []


def test_same_generation_parameter_failure_preserves_slot_owner_state():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(gravity=5.0), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    owner = slot.data["owner"]
    compiled = owner.compiled
    kernel.fail_create = True
    try:
        slot_module.sync_mc2_mesh_fused_slot(
            world, _collection(gravity=6.0), kernel=kernel,
        )
    except RuntimeError as exc:
        assert "injected slot create failure" in str(exc)
    else:
        raise AssertionError("owner replacement failure was accepted")
    assert world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID] is slot
    assert slot.data["owner"] is owner and owner.compiled is compiled
    assert world._current_writer is None


def test_same_generation_native_replacement_resets_product_scheduler_state():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(
        world, _collection(gravity=5.0), kernel=kernel,
    )
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    old_scheduler = slot.data["scheduler_state"]
    updated = slot_module.sync_mc2_mesh_fused_slot(
        world, _collection(gravity=6.0), kernel=kernel,
    )
    assert updated.owner_report.action == "replaced"
    assert slot.data["scheduler_state"] is not old_scheduler
    assert slot.data["scheduler_state"].revision == 0
    assert slot.data["frame_ready"] is False


def _empty_collider_frame(frame):
    return collider_module.MC2DomainColliderFrameSpec(
        frame=frame,
        source_pointers=(1, 2),
        collider_keys=(),
        collider_types=np.empty(0, dtype=np.int32),
        collider_group_bits=np.empty(0, dtype=np.int32),
        collider_centers=np.empty((0, 3), dtype=np.float32),
        collider_segment_a=np.empty((0, 3), dtype=np.float32),
        collider_segment_b=np.empty((0, 3), dtype=np.float32),
        collider_old_centers=np.empty((0, 3), dtype=np.float32),
        collider_old_segment_a=np.empty((0, 3), dtype=np.float32),
        collider_old_segment_b=np.empty((0, 3), dtype=np.float32),
        collider_radii=np.empty(0, dtype=np.float32),
        frame_signature="e" * 64,
    )


def _domain_frame(program, *, frame=7, component_positions=None, anchors=None):
    partition_count = program.partition_count
    normals = np.zeros((program.particle_count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    if component_positions is None:
        component_positions = np.zeros((partition_count, 3), dtype=np.float32)
    if anchors is None:
        anchors = np.zeros((partition_count, 3), dtype=np.float32)
        anchor_present = np.zeros(partition_count, dtype=np.uint32)
    else:
        anchor_present = np.ones(partition_count, dtype=np.uint32)
    return ir.make_mc2_domain_frame_packet(
        program,
        frame=frame,
        generation=1,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=normals,
        partition_world_position=component_positions,
        partition_world_rotation=np.asarray(
            ((0.0, 0.0, 0.0, 1.0),) * partition_count,
            dtype=np.float32,
        ),
        partition_world_scale=np.ones((partition_count, 3), dtype=np.float32),
        partition_world_linear=np.asarray(
            (np.eye(3, dtype=np.float32),) * partition_count,
            dtype=np.float32,
        ),
        anchor_world_position=anchors,
        anchor_world_rotation=np.asarray(
            ((0.0, 0.0, 0.0, 1.0),) * partition_count,
            dtype=np.float32,
        ),
        anchor_present=anchor_present,
    )


def _scheduled(slot, frame, *, frame_delta_time=0.1, world_time_scale=1.0):
    return slot.data["scheduler_state"].stage_frame(
        frame,
        parameters.make_mc2_solver_settings(),
        frame_delta_time=frame_delta_time,
        world_time_scale=world_time_scale,
    )


def test_slot_publishes_one_domain_frame_and_collider_table_atomically():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    frame = _domain_frame(program)
    scheduled = _scheduled(slot, frame)
    try:
        slot_module.publish_mc2_mesh_fused_frame(
            world, slot, scheduled, _empty_collider_frame(8),
        )
    except ValueError as exc:
        assert "frame numbers" in str(exc)
    else:
        raise AssertionError("mismatched collider frame was accepted")
    assert kernel.frames == [] and "frame_packet" not in slot.data
    assert slot.data["scheduler_state"].revision == 0

    report = slot_module.publish_mc2_mesh_fused_frame(
        world, slot, scheduled, _empty_collider_frame(7),
    )
    assert report.partition_ids == program.partition_ids
    assert report.collider_count == 0 and len(kernel.frames) == 1
    assert slot.data["frame_packet"] is scheduled.frame_packet
    assert slot.data["frame_packet"].is_running is True
    assert slot.data["frame_packet"].simulation_delta_time > 0.0
    assert report.update_count == scheduled.schedule.update_count
    assert report.skip_count == scheduled.schedule.skip_count
    assert slot.data["collider_frame"].frame == 7
    assert slot.data["frame_ready"] is True
    assert slot.data["product_enabled"] is False
    assert world._current_writer is None


def test_slot_commits_anchor_history_only_after_native_frame_publish():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    components = np.asarray(((1.0, 2.0, 3.0), (4.0, 5.0, 6.0)), dtype=np.float32)
    anchors = np.asarray(((10.0, 0.0, 0.0), (0.0, 10.0, 0.0)), dtype=np.float32)
    first = _scheduled(
        slot,
        _domain_frame(
            program, frame=7, component_positions=components, anchors=anchors,
        ),
        world_time_scale=0.0,
    )
    np.testing.assert_array_equal(first.anchor_component_local_positions, 0.0)
    expected_first = components - anchors
    np.testing.assert_array_equal(
        first.next_anchor_component_local_positions, expected_first,
    )

    kernel.fail_update = True
    try:
        slot_module.publish_mc2_mesh_fused_frame(
            world, slot, first, _empty_collider_frame(7),
        )
    except RuntimeError as exc:
        assert "injected frame update failure" in str(exc)
    else:
        raise AssertionError("native frame update failure was accepted")
    state = slot.data["scheduler_state"]
    assert state.revision == 0
    np.testing.assert_array_equal(state.anchor_component_local_positions, 0.0)
    assert "frame_packet" not in slot.data

    kernel.fail_update = False
    slot_module.publish_mc2_mesh_fused_frame(
        world, slot, first, _empty_collider_frame(7),
    )
    assert state.revision == 1
    np.testing.assert_array_equal(
        state.anchor_component_local_positions, expected_first,
    )
    second = _scheduled(
        slot,
        _domain_frame(
            program,
            frame=8,
            component_positions=components + np.float32(1.0),
            anchors=anchors + np.float32(2.0),
        ),
        world_time_scale=0.0,
    )
    np.testing.assert_array_equal(
        second.anchor_component_local_positions, expected_first,
    )


def test_capture_path_publishes_world_and_solver_timing_atomically():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    frame = _domain_frame(program, frame=9)
    world.frame_context.frame = 9
    world.frame_context.generation = 1
    world.frame_context.raw_dt = 0.1
    world.frame_context.dt = 0.05
    world.frame_context.time_scale = 0.5
    original_capture = product_frame_module.capture_mc2_mesh_product_frame
    original_collider = slot_module.build_mc2_mesh_domain_collider_frame
    product_frame_module.capture_mc2_mesh_product_frame = (
        lambda *_args, **_kwargs: (frame, ("first", "second"))
    )
    slot_module.build_mc2_mesh_domain_collider_frame = (
        lambda *_args, **_kwargs: _empty_collider_frame(9)
    )
    try:
        report = slot_module.capture_and_publish_mc2_mesh_fused_frame(
            world,
            settings=parameters.make_mc2_solver_settings(
                time_scale=0.5,
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            ),
        )
    finally:
        product_frame_module.capture_mc2_mesh_product_frame = original_capture
        slot_module.build_mc2_mesh_domain_collider_frame = original_collider
    packet = slot.data["frame_packet"]
    assert packet.frame == 9 and packet.frame_delta_time == np.float32(0.1)
    assert packet.time_scale == np.float32(0.25)
    assert packet.is_running is True and packet.simulation_delta_time > 0.0
    assert report.update_count > 0 and report.skip_count == 0
    assert slot.data["partition_frame_snapshots"] == ("first", "second")
    assert slot.data["scheduler_state"].revision == 1


def test_slot_executes_and_commits_compiled_substeps_sequentially():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=10))
    slot_module.publish_mc2_mesh_fused_frame(
        world, slot, scheduled, _empty_collider_frame(10),
    )
    results = tuple(
        slot_module.step_mc2_mesh_fused_substep(world, slot)
        for _ in range(scheduled.schedule.update_count)
    )
    assert tuple(result.update_index for result in results) == tuple(
        range(scheduled.schedule.update_count)
    )
    assert all(not result.is_final_substep for result in results[:-1])
    assert results[-1].is_final_substep
    assert slot.data["completed_substeps"] == scheduled.schedule.update_count
    assert slot.data["frame_complete"] is True
    assert slot.data["scheduler_state"].revision == 1 + len(results)
    assert len(kernel.poses) == len(results) == len(kernel.full_steps)
    for _handle, settings in kernel.full_steps:
        np.testing.assert_array_equal(
            settings["distance_weights"],
            np.ones(program.partition_count, dtype=np.float32),
        )
        assert settings["external_collision"]["collider_types"].shape == (0,)
    try:
        slot_module.step_mc2_mesh_fused_substep(world, slot)
    except RuntimeError as exc:
        assert "no pending substeps" in str(exc)
    else:
        raise AssertionError("completed fused frame accepted an extra substep")


def test_slot_substep_failure_does_not_advance_scheduler_and_can_retry():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=11))
    slot_module.publish_mc2_mesh_fused_frame(
        world, slot, scheduled, _empty_collider_frame(11),
    )
    revision = slot.data["scheduler_state"].revision
    kernel.fail_step = True
    try:
        slot_module.step_mc2_mesh_fused_substep(world, slot)
    except RuntimeError as exc:
        assert "injected fused substep failure" in str(exc)
    else:
        raise AssertionError("fused substep failure was accepted")
    assert slot.data["scheduler_state"].revision == revision
    assert (
        slot.data["scheduler_state"].debug_dict()["time_scheduler"]["next_step_index"]
        == 0
    )
    assert slot.data["completed_substeps"] == 0
    assert "injected fused substep failure" in slot.data["last_step_failure"]
    kernel.fail_step = False
    result = slot_module.step_mc2_mesh_fused_substep(world, slot)
    assert result.update_index == 0
    assert slot.data["scheduler_state"].revision == revision + 1
    assert "last_step_failure" not in slot.data


def test_paused_fused_frame_has_no_product_substeps():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(
        slot, _domain_frame(program, frame=12), world_time_scale=0.0,
    )
    assert scheduled.schedule.update_count == 0
    slot_module.publish_mc2_mesh_fused_frame(
        world, slot, scheduled, _empty_collider_frame(12),
    )
    assert slot.data["frame_complete"] is True
    try:
        slot_module.step_mc2_mesh_fused_substep(world, slot)
    except RuntimeError as exc:
        assert "no pending substeps" in str(exc)
    else:
        raise AssertionError("paused fused frame accepted a substep")
    assert kernel.poses == [] and kernel.full_steps == []


def test_slot_native_executes_complete_compiled_frame():
    world = _world()
    kernel = native_kernel_module.MC2NativeCPUKernelV1()
    try:
        slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
        slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
        owner = slot.data["owner"]
        frame = _domain_frame(owner.compiled.program, frame=13)
        scheduled = _scheduled(slot, frame)
        slot_module.publish_mc2_mesh_fused_frame(
            world, slot, scheduled, _empty_collider_frame(13),
        )
        results = tuple(
            slot_module.step_mc2_mesh_fused_substep(world, slot)
            for _ in range(scheduled.schedule.update_count)
        )
        assert tuple(result.update_index for result in results) == tuple(
            range(scheduled.schedule.update_count)
        )
        assert results[-1].is_final_substep
        output = owner.read_output()
        assert output.frame == 13 and output.generation == 1
        assert np.isfinite(output.world_positions).all()
        assert slot.data["scheduler_state"].revision == 1 + len(results)
        assert slot.data["frame_complete"] is True
    finally:
        world.omni_cache_dispose("native_substep_test_complete")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 product slot: {len(TESTS)} passed")
