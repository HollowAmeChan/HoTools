"""E4 Physics World ownership tests for the staged Mesh product slot."""

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
OMNINODE = NODETREE
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.PhysicsWorld.mc2", MC2_ROOT),
    ("HoTools.OmniNode.PhysicsWorld.mc2.setups", os.path.join(MC2_ROOT, "setups")),
    (
        "HoTools.OmniNode.PhysicsWorld.mc2.setups.mesh_cloth",
        os.path.join(MC2_ROOT, "setups", "mesh_cloth"),
    ),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
field_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.names")
field_specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.specs")
field_native = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.native")
ir = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.domain_ir")
collector = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.domain_collect")
parameters = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.parameters")
partitions = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.partition_specs")
product = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.setups.mesh_cloth.product")
slot_module = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.product_slot")
product_frame_module = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.mesh_cloth.product"
)
collider_module = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mc2.collider_frame")
native_kernel_module = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.cpu_native_kernel"
)
debug_module = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.debug"
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
        self.users_collection = (types.SimpleNamespace(name_full="Cloth"),)

    def as_pointer(self):
        return self._pointer


def _collection(*, gravity=5.0, constraints=False):
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
                gravity=gravity if index == 0 else 8.0,
                self_collision_mode=2,
                max_distance_enabled=constraints,
                max_distance=0.1,
                backstop_enabled=constraints,
                backstop_radius=0.05,
                angle_limit_enabled=constraints,
                angle_limit=30.0,
            ),
            setup_options=parameters.make_mc2_setup_options("mesh_cloth"),
            task_parameters=parameters.make_mc2_task_parameters(),
        )
        for index, (source, snapshot) in enumerate(zip(sources, snapshots))
    )
    plan = partitions.collect_mc2_partition_entries(
        setup_type="mesh_cloth", explicit_entries=entries,
    )
    draft = collector.build_mc2_domain_draft(
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
        self.zero_frame_passes = []
        self.frame_shifts = []
        self.poses = []
        self.full_steps = []
        self.timed_steps = []
        self.field_contexts = []
        self.fail_create = False
        self.fail_parameter_stage = False
        self.fail_update = False
        self.fail_step = False

    def create_domain(self, program, packet):
        if self.fail_create:
            raise RuntimeError("injected slot create failure")
        handle = {"program": program, "packet": packet, "serial": len(self.created)}
        self.created.append(handle)
        return handle

    def stage_parameter_update(self, handle, program, packet):
        if self.fail_parameter_stage:
            raise RuntimeError("injected slot parameter stage failure")
        return {
            "handle": handle,
            "old_program": handle["program"],
            "old_packet": handle["packet"],
            "new_program": program,
            "new_packet": packet,
            "applied": False,
        }
    def apply_parameter_update(self, handle, update):
        handle["program"] = update["new_program"]
        handle["packet"] = update["new_packet"]
        update["applied"] = True
    def rollback_parameter_update(self, handle, update):
        handle["program"] = update["old_program"]
        handle["packet"] = update["old_packet"]
        update["applied"] = False
    def finish_parameter_update(self, handle, update):
        assert update["applied"]
    def discard_parameter_update(self, update):
        assert not update["applied"]

    def update_frame(self, handle, frame):
        if self.fail_update:
            raise RuntimeError("injected frame update failure")
        self.frames.append((handle, frame))
    def configure_field_consumers(self, handle, contexts):
        self.field_contexts.append((handle, tuple(contexts)))
    def step_task_reference_teleport(self, handle):
        self.zero_frame_passes.append(("task_reference_teleport", handle))
    def step_center_frame_shift(self, handle, anchor_component_local_positions):
        self.zero_frame_passes.append(("center_frame_shift", handle))
        self.frame_shifts.append((handle, anchor_component_local_positions))
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
    def step_compiled_domain_pipeline_timed(
        self, handle, settings, checkpoint, native_checkpoint
    ):
        if self.fail_step:
            raise RuntimeError("injected fused substep failure")
        self.timed_steps.append((handle, settings))
        checkpoint("CPU · 测试pass")
        native_checkpoint({
            "stages": {"CPU Self · 测试": 0.0},
            "residual_stage": "CPU Self · 测试边界",
        })
    def step(self, handle, frame, settings, colliders): pass
    def read_output(self, handle): raise AssertionError("not used")
    def inspect(self, handle): return {"serial": handle["serial"]}
    def dispose(self, handle): self.disposed.append(handle)


def _world(generation=1):
    world = world_types.PhysicsWorldCache()
    world.generation = generation
    return world


def _sync_mesh_product_slot(world, collection, *, kernel=None):
    return slot_module.sync_mc2_product_slot(
        world,
        collection,
        slot_id=slot_module.MC2_MESH_PRODUCT_SLOT_ID,
        kernel=kernel,
    )


def _capture_mesh_product_frame(world, **kwargs):
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    return slot_module.capture_and_publish_mc2_product_frame(
        world,
        slot,
        **kwargs,
    )


def test_slot_create_update_and_world_dispose_own_one_handle():
    world = _world()
    kernel = _Kernel()
    created = _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    owner = slot.data["owner"]
    scheduler_state = slot.data["scheduler_state"]
    updated = _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    assert created.action == "created" and updated.action == "updated"
    assert updated.owner_report.action == "reused"
    assert world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID] is slot
    assert slot.data["owner"] is owner and len(kernel.created) == 1
    assert slot.data["scheduler_state"] is scheduler_state
    assert slot.data["product_enabled"] is False
    world.omni_cache_dispose("test_complete")
    assert len(kernel.disposed) == 1 and world.solver_slots == {}


def test_generation_change_stages_new_slot_then_disposes_old_owner():
    world = _world(generation=1)
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    old_slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    world.generation = 2
    replaced = _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    new_slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    assert replaced.action == "replaced" and new_slot is not old_slot
    assert new_slot.world_generation == 2
    assert len(kernel.created) == 2 and len(kernel.disposed) == 1


def test_staged_create_failure_preserves_previous_generation_slot():
    world = _world(generation=1)
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    old_slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    world.generation = 2
    kernel.fail_create = True
    try:
        _sync_mesh_product_slot(
            world, _collection(), kernel=kernel
        )
    except RuntimeError as exc:
        assert "injected slot create failure" in str(exc)
    else:
        raise AssertionError("slot create failure was accepted")
    assert world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID] is old_slot
    assert old_slot.data["owner"].domain is not None
    assert kernel.disposed == []


def test_same_generation_parameter_failure_preserves_slot_owner_state():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(gravity=5.0), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    owner = slot.data["owner"]
    compiled = owner.compiled
    kernel.fail_parameter_stage = True
    try:
        _sync_mesh_product_slot(
            world, _collection(gravity=6.0), kernel=kernel,
        )
    except RuntimeError as exc:
        assert "injected slot parameter stage failure" in str(exc)
    else:
        raise AssertionError("owner replacement failure was accepted")
    assert world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID] is slot
    assert slot.data["owner"] is owner and owner.compiled is compiled
    assert world._current_writer is None


def test_same_generation_parameter_update_preserves_product_scheduler_state():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(
        world, _collection(gravity=5.0), kernel=kernel,
    )
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    old_scheduler = slot.data["scheduler_state"]
    updated = _sync_mesh_product_slot(
        world, _collection(gravity=6.0), kernel=kernel,
    )
    assert updated.owner_report.action == "parameters_updated"
    assert updated.owner_report.native_domain_reused
    assert slot.data["scheduler_state"] is old_scheduler


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


def _field_snapshot(*, frame, sample_time_seconds, include_ids=("Sleeve",)):
    transform = (
        (100.0, 0.0, 0.0, 0.0),
        (0.0, 100.0, 0.0, 0.0),
        (0.0, 0.0, 100.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    wind = field_specs.FieldSpecV0(
        field_id="product-slot-wind",
        source_id="test:product-slot-wind",
        status=field_names.FIELD_STATUS_ACTIVE,
        volume=field_specs.VolumeSpecV0(
            shape=field_names.VOLUME_SHAPE_BOX,
            world_transform=transform,
        ),
        wind=field_specs.WindPayloadV0(speed_mps=4.0, turbulence=0.0),
        scope=field_specs.FieldScopeV0(
            include_ids=include_ids,
            collection_ids=("Cloth",),
            collision_groups=(1,),
        ),
    )
    return field_specs.build_field_snapshot_v0(
        (wind,),
        generation=1,
        frame=frame,
        sample_time_seconds=sample_time_seconds,
    )


def _field_runtime(*, frame, sample_time_seconds, include_ids=("Sleeve",)):
    return field_native.NativeFieldRuntimeV1.create(
        _field_snapshot(
            frame=frame,
            sample_time_seconds=sample_time_seconds,
            include_ids=include_ids,
        )
    )


def test_slot_publishes_one_domain_frame_and_collider_table_atomically():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    frame = _domain_frame(program)
    scheduled = _scheduled(slot, frame)
    try:
        slot_module.publish_mc2_product_frame(
            world, slot, scheduled, _empty_collider_frame(8),
        )
    except ValueError as exc:
        assert "frame numbers" in str(exc)
    else:
        raise AssertionError("mismatched collider frame was accepted")
    assert kernel.frames == [] and "frame_packet" not in slot.data
    assert slot.data["scheduler_state"].revision == 0

    report = slot_module.publish_mc2_product_frame(
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
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
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
        slot_module.publish_mc2_product_frame(
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
    slot_module.publish_mc2_product_frame(
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


def test_product_frame_feedback_stage_commits_only_after_native_publish():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    scheduled = _scheduled(slot, _domain_frame(slot.data["owner"].compiled.program))

    class _Stage:
        def __init__(self):
            self.validations = 0
            self.commits = 0

        def validate(self, value):
            assert value is world
            self.validations += 1

        def commit(self, value):
            assert value is world
            self.commits += 1

    stage = _Stage()
    kernel.fail_update = True
    try:
        slot_module.publish_mc2_product_frame(
            world,
            slot,
            scheduled,
            _empty_collider_frame(7),
            frame_state_stage=stage,
        )
    except RuntimeError as exc:
        assert "injected frame update failure" in str(exc)
    else:
        raise AssertionError("native frame failure committed feedback stage")
    assert stage.validations == 1 and stage.commits == 0
    assert slot.data["scheduler_state"].revision == 0

    kernel.fail_update = False
    slot_module.publish_mc2_product_frame(
        world,
        slot,
        scheduled,
        _empty_collider_frame(7),
        frame_state_stage=stage,
    )
    assert stage.validations == 2 and stage.commits == 1


def test_capture_path_publishes_world_and_solver_timing_atomically():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    frame = _domain_frame(program, frame=9)
    world.frame_context.frame = 9
    world.frame_context.generation = 1
    world.frame_context.raw_dt = 0.1
    world.frame_context.dt = 0.05
    world.frame_context.time_scale = 0.5
    original_capture = product_frame_module.capture_mc2_mesh_product_frame
    original_collider = slot_module.build_mc2_domain_collider_frame_for_draft
    product_frame_module.capture_mc2_mesh_product_frame = (
        lambda *_args, **_kwargs: (frame, ("first", "second"))
    )
    slot_module.build_mc2_domain_collider_frame_for_draft = (
        lambda *_args, **_kwargs: _empty_collider_frame(9)
    )
    try:
        report = _capture_mesh_product_frame(
            world,
            settings=parameters.make_mc2_solver_settings(
                time_scale=0.5,
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            ),
        )
    finally:
        product_frame_module.capture_mc2_mesh_product_frame = original_capture
        slot_module.build_mc2_domain_collider_frame_for_draft = original_collider
    packet = slot.data["frame_packet"]
    assert packet.frame == 9 and packet.frame_delta_time == np.float32(0.1)
    assert packet.time_scale == np.float32(0.25)
    assert packet.is_running is False and packet.simulation_delta_time == 0.0
    assert report.update_count == 0 and report.skip_count == 0
    assert slot.data["partition_frame_snapshots"] == ("first", "second")
    assert slot.data["scheduler_state"].revision == 1


def test_slot_executes_and_commits_compiled_substeps_sequentially():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=10))
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(10),
    )
    results = tuple(
        slot_module.step_mc2_product_substep(world, slot)
        for _ in range(scheduled.schedule.update_count)
    )
    assert tuple(result.update_index for result in results) == tuple(
        range(scheduled.schedule.update_count)
    )
    assert all(not result.is_final_substep for result in results[:-1])
    assert results[-1].is_final_substep
    assert slot.data["completed_substeps"] == scheduled.schedule.update_count
    assert slot.data["frame_complete"] is True
    assert kernel.frame_shifts == []
    assert slot.data["scheduler_state"].revision == 1 + len(results)
    assert len(kernel.poses) == len(results) == len(kernel.full_steps)
    assert "_debug_product_step_basic" not in slot.data
    for _handle, settings in kernel.full_steps:
        np.testing.assert_array_equal(
            settings["distance_weights"],
            np.ones(program.partition_count, dtype=np.float32),
        )
        assert settings["external_collision"]["collider_types"].shape == (0,)
    try:
        slot_module.step_mc2_product_substep(world, slot)
    except RuntimeError as exc:
        assert "no pending substeps" in str(exc)
    else:
        raise AssertionError("completed fused frame accepted an extra substep")


def test_slot_sends_only_field_runtime_identity_per_fixed_update():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=10))
    world.frame_context.frame = 10
    world.frame_context.generation = 1
    world.frame_context.sample_time_seconds = 2.0
    world.frame_context.frame_step_dt = 0.1
    world.set_runtime_cache(
        field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1,
        _field_runtime(frame=10, sample_time_seconds=2.0),
    )
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(10),
    )

    first = slot_module.step_mc2_product_substep(world, slot)
    first_runtime = kernel.full_steps[-1][1]["field_runtime"]
    assert first.update_index == 0
    assert first_runtime["sample_time_seconds"] == 2.0
    assert first_runtime["handle"] > 0
    assert not hasattr(kernel, "read_particle_positions")

    second = slot_module.step_mc2_product_substep(world, slot)
    second_runtime = kernel.full_steps[-1][1]["field_runtime"]
    expected_time = 2.0 + 0.1 / scheduled.schedule.update_count
    assert second.update_index == 1
    assert second_runtime["sample_time_seconds"] == expected_time
    assert second_runtime["handle"] == first_runtime["handle"]
    assert set(second_runtime) == {"handle", "sample_time_seconds"}
    assert not hasattr(kernel, "read_particle_positions")
    world.omni_cache_dispose("field_runtime_identity_test_complete")


def test_stale_field_runtime_fails_before_native_step_and_scheduler_commit():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=11))
    world.frame_context.frame = 11
    world.frame_context.generation = 1
    world.frame_context.sample_time_seconds = 3.0
    world.frame_context.frame_step_dt = 0.1
    world.set_runtime_cache(
        field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1,
        _field_runtime(frame=10, sample_time_seconds=3.0),
    )
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(11),
    )
    revision = slot.data["scheduler_state"].revision

    try:
        slot_module.step_mc2_product_substep(world, slot)
    except RuntimeError as exc:
        assert "runtime 已过期" in str(exc)
    else:
        raise AssertionError("stale Field runtime was accepted")
    assert not hasattr(kernel, "read_particle_positions")
    assert kernel.poses == [] and kernel.full_steps == []
    assert slot.data["scheduler_state"].revision == revision
    assert slot.data["completed_substeps"] == 0
    assert "runtime 已过期" in slot.data["last_step_failure"]
    world.omni_cache_dispose("stale_field_runtime_test_complete")


def test_slot_uses_timed_pipeline_only_when_hotspot_timing_is_requested():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=12))
    assert scheduled.schedule.update_count >= 2
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(12),
    )

    slot_module.step_mc2_product_substep(world, slot)
    assert len(kernel.full_steps) == 1
    assert kernel.timed_steps == []

    class _Timing:
        def __init__(self):
            self.details = []

        def detail_checkpoint(self, stage):
            self.details.append(stage)

        def detail_native_checkpoint(self, payload):
            self.details.extend(payload["stages"])

    timing = _Timing()
    slot_module.step_mc2_product_substep(world, slot, timing=timing)
    assert len(kernel.full_steps) == 1
    assert len(kernel.timed_steps) == 1
    assert timing.details == [
        "CPU · StepBasic准备",
        "CPU · 子步参数构建",
        "CPU · 测试pass",
        "CPU Self · 测试",
    ]


def test_slot_substep_failure_does_not_advance_scheduler_and_can_retry():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(slot, _domain_frame(program, frame=11))
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(11),
    )
    revision = slot.data["scheduler_state"].revision
    kernel.fail_step = True
    try:
        slot_module.step_mc2_product_substep(world, slot)
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
    result = slot_module.step_mc2_product_substep(world, slot)
    assert result.update_index == 0
    assert slot.data["scheduler_state"].revision == revision + 1
    assert "last_step_failure" not in slot.data


def test_paused_fused_frame_has_no_product_substeps():
    world = _world()
    kernel = _Kernel()
    _sync_mesh_product_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
    world.frame_context = types.SimpleNamespace(frame=11)
    assert debug_module.request_mc2_debug_capture(
        world, filters={"show_step_basic": True},
    ) == 1
    program = slot.data["owner"].compiled.program
    scheduled = _scheduled(
        slot, _domain_frame(program, frame=12), world_time_scale=0.0,
    )
    assert scheduled.schedule.update_count == 0
    slot_module.publish_mc2_product_frame(
        world, slot, scheduled, _empty_collider_frame(12),
    )
    assert slot.data["frame_complete"] is True
    assert len(kernel.frame_shifts) == 1
    assert [name for name, _handle in kernel.zero_frame_passes] == [
        "task_reference_teleport", "center_frame_shift",
    ]
    np.testing.assert_array_equal(
        kernel.frame_shifts[0][1],
        scheduled.anchor_component_local_positions,
    )
    try:
        slot_module.step_mc2_product_substep(world, slot)
    except RuntimeError as exc:
        assert "no pending substeps" in str(exc)
    else:
        raise AssertionError("paused fused frame accepted a substep")
    assert kernel.poses == [] and kernel.full_steps == []
    world.frame_context = types.SimpleNamespace(frame=12)
    assert debug_module.capture_requested_mc2_product_debug(world, (slot,)) == 0
    debug_state = slot.data["_debug_capture_state"]
    assert debug_state["requested"] is True
    assert debug_state["waiting_for_substep"] is True


def test_product_teleport_debug_uses_object_origin_without_fixed_particle():
    program = types.SimpleNamespace(
        partition_ids=("partition:no-fixed",),
        particle_partition_index=np.asarray((0, 0), dtype=np.uint32),
        particle_attribute_flags=np.asarray((2, 2), dtype=np.uint32),
    )
    task = {
        "flags": np.asarray((3,), dtype=np.uint32),
        "reference_indices": np.asarray((-1,), dtype=np.int32),
        "modes": np.asarray((2,), dtype=np.int32),
        "old_reference_positions": np.asarray(
            ((1.0, 2.0, 3.0),), dtype=np.float32
        ),
        "reference_positions": np.asarray(
            ((2.0, 2.0, 3.0),), dtype=np.float32
        ),
        "old_reference_rotations_xyzw": np.asarray(
            ((0.0, 0.0, 0.0, 1.0),), dtype=np.float32
        ),
        "reference_rotations_xyzw": np.asarray(
            ((0.0, 0.0, 0.0, 1.0),), dtype=np.float32
        ),
        "measured_distances": np.asarray((1.0,), dtype=np.float32),
        "distance_thresholds": np.asarray((0.5,), dtype=np.float32),
        "measured_rotation_degrees": np.zeros(1, dtype=np.float32),
        "rotation_threshold_degrees": np.asarray((90.0,), dtype=np.float32),
    }
    center = {
        "teleport_flags": np.asarray((3,), dtype=np.uint32),
        "old_frame_world_positions": np.asarray(
            ((1.0, 2.0, 3.0),), dtype=np.float32
        ),
        "now_world_positions": np.asarray(
            ((2.0, 2.0, 3.0),), dtype=np.float32
        ),
        "old_frame_world_rotations_xyzw": task[
            "old_reference_rotations_xyzw"
        ],
        "now_world_rotations_xyzw": task["reference_rotations_xyzw"],
        "teleport_measured_distances": np.asarray((1.0,), dtype=np.float32),
        "teleport_distance_thresholds": np.asarray((0.5,), dtype=np.float32),
        "teleport_measured_rotation_degrees": np.zeros(1, dtype=np.float32),
    }
    item = debug_module._product_task_teleport_payload(
        program, task, center
    )["partitions"][0]
    assert item["eligible"] is True
    assert item["reference_source"] == "object_origin"
    assert item["reference_index"] == -1
    assert item["applied"] is True and item["keep"] is True
    np.testing.assert_array_equal(item["reference_position"], (2.0, 2.0, 3.0))


def test_slot_native_executes_complete_compiled_frame():
    world = _world()
    kernel = native_kernel_module.MC2NativeCPUKernelV1()
    try:
        _sync_mesh_product_slot(
            world, _collection(constraints=True), kernel=kernel
        )
        slot = world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
        owner = slot.data["owner"]
        world.frame_context = types.SimpleNamespace(frame=12)
        assert debug_module.request_mc2_debug_capture(
            world,
            filters={
                "show_topology": True,
                "show_attributes": True,
                "show_depth": True,
                "show_step_basic": True,
                "show_gravity": True,
                "show_velocity": True,
                "show_distance": True,
                "show_tether": True,
                "show_bending": True,
                "show_output": True,
                "show_center": True,
                "show_teleport_threshold": True,
                "show_teleport_status": True,
                "show_motion_base": True,
                "show_motion": True,
                "show_angle_restoration": True,
                "show_angle_limit": True,
                "show_collision": True,
                "show_collision_contacts": True,
                "show_radii": True,
                "show_self_primitives": True,
                "show_self_grid": True,
                "show_self_candidates": True,
                "show_self_contacts": True,
            },
        ) == 1
        frame = _domain_frame(owner.compiled.program, frame=13)
        scheduled = _scheduled(slot, frame)
        slot_module.publish_mc2_product_frame(
            world, slot, scheduled, _empty_collider_frame(13),
        )
        results = tuple(
            slot_module.step_mc2_product_substep(world, slot)
            for _ in range(scheduled.schedule.update_count)
        )
        assert tuple(result.update_index for result in results) == tuple(
            range(scheduled.schedule.update_count)
        )
        assert results[-1].is_final_substep
        output = owner.read_output()
        assert output.frame == 13 and output.generation == 1
        assert np.isfinite(output.world_positions).all()
        batch = slot_module.build_mc2_mesh_product_output_batch(world, slot)
        assert len(batch.commands) == 2
        assert [command.target_id for command in batch.commands] == [
            snapshot.output_target_id
            for snapshot in slot.data["collection"].static_snapshots
        ]
        assert batch.frame == 13 and batch.generation == 1
        assert slot.data["output_batch"] is batch
        world.frame_context = types.SimpleNamespace(frame=13)
        assert debug_module.capture_requested_mc2_product_debug(
            world, (slot,)
        ) == 1
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["schema"] == "mc2_product_debug_snapshot_v1"
        assert snapshot["source"] == "mc2_product_capture"
        assert snapshot["frame"] == 13
        assert snapshot["partition_ids"] == owner.compiled.program.partition_ids
        assert not {
            "show_distance", "show_tether", "show_bending",
            "show_motion_base", "show_motion",
            "show_angle_restoration", "show_angle_limit",
            "show_collision", "show_collision_contacts", "show_radii",
            "show_self_primitives", "show_self_grid",
            "show_self_candidates", "show_self_contacts",
        }.intersection(snapshot["unsupported_filters"])
        assert snapshot["native"]["positions"].flags.writeable is False
        dynamics = snapshot["native"]["dynamics"]
        assert dynamics["velocities"].flags.writeable is False
        assert dynamics["real_velocities"].flags.writeable is False
        contacts = snapshot["native"]["external_contacts"]
        assert contacts["vertices"].shape[1:] == (2,)
        assert contacts["origins"].shape[1:] == (2, 3)
        assert contacts["role_corrections"].shape[1:] == (2, 3)
        assert contacts["temporal"]["active_count"] == 0
        collision = snapshot["collision"]
        assert collision["schema"] == "mc2_product_external_collision_debug_v1"
        assert collision["particle_radii"].shape == (
            owner.compiled.program.particle_count,
        )
        assert collision["particle_partitions"].shape == (
            owner.compiled.program.particle_count,
        )
        assert collision["collision_modes"].shape == (
            owner.compiled.program.partition_count,
        )
        assert collision["collision_masks"].shape == (
            owner.compiled.program.partition_count,
        )
        assert collision["collision_masks"].tolist() == [0, 0]
        assert collision["colliders"]["collided_by_groups"] == 0
        assert collision["friction_before"].flags.writeable is False
        assert collision["friction_after"].flags.writeable is False
        self_collision = snapshot["self_collision"]
        self_primitive_count = (
            self_collision["point_primitive_count"]
            + self_collision["edge_primitive_count"]
            + self_collision["triangle_primitive_count"]
        )
        assert self_collision["particle_indices"].shape == (
            self_primitive_count, 3,
        )
        assert self_collision["primitive_grids"].shape == (
            self_primitive_count, 3,
        )
        assert self_collision["candidates"].shape[1:] == (3,)
        assert self_collision["contact_indices"].shape[1:] == (2,)
        assert self_collision["contact_corrections"].shape[1:] == (2, 3)
        assert self_collision["intersect_records"].shape[1:] == (5,)
        assert set(map(int, self_collision["owner_indices"])) == {0, 1}
        assert self_collision["contact_temporal"]["observed"] is True
        assert self_collision["intersection_temporal"]["observed"] is True
        assert self_collision["contact_temporal"]["frame"] == 13
        assert snapshot["topology"]["edges"].shape[1] == 2
        assert snapshot["topology"]["baseline_parent_indices"].shape == (
            owner.compiled.program.particle_count,
        )
        assert snapshot["topology"]["baseline_root_indices"].flags.writeable is False
        assert np.isfinite(snapshot["topology"]["baseline_depths"]).all()
        assert snapshot["motion"]["step_basic_positions"].shape == (
            owner.compiled.program.particle_count, 3,
        )
        assert snapshot["motion"]["step_basic_positions"].flags.writeable is False
        assert snapshot["motion"]["update_index"] == results[-1].update_index
        assert snapshot["motion"]["normal_axis_values"].shape == (
            owner.compiled.program.particle_count,
        )
        records = snapshot["constraint_records"]
        distance_records = records["distance"]
        assert len(distance_records["phases"]) > 0
        assert set(map(int, distance_records["phases"])) == {0, 1}
        assert np.isfinite(distance_records["target_origins"]).all()
        assert np.isfinite(distance_records["corrections"]).all()
        assert set(map(int, distance_records["partitions"])).issubset({0, 1})
        assert distance_records["hit"].dtype == np.uint8
        tether_records = records["tether"]
        assert len(tether_records["vertices"]) > 0
        assert np.isfinite(tether_records["root_origins"]).all()
        assert np.isfinite(tether_records["minimums"]).all()
        assert np.isfinite(tether_records["maximums"]).all()
        assert set(map(int, tether_records["partitions"])).issubset({0, 1})
        bending_records = records["bending"]
        assert len(bending_records["record_indices"]) == 0
        assert snapshot["native"]["bending_results"]["origins"].shape == (
            0, 4, 3,
        )
        motion_records = records["motion"]
        assert len(motion_records["branches"]) > 0
        assert np.isfinite(motion_records["target_origins"]).all()
        assert set(map(int, motion_records["partitions"])).issubset({0, 1})
        for name in ("angle_restoration", "angle_limit"):
            angle_records = records[name]
            assert len(angle_records["branches"]) > 0
            assert np.isfinite(angle_records["targets"]).all()
            assert np.isfinite(angle_records["target_vectors"]).all()
            assert set(map(int, angle_records["partitions"])).issubset({0, 1})
        assert snapshot["parameters"]["schema"] == "mc2_product_gravity_debug_v1"
        assert snapshot["parameters"]["gravity_directions"].shape == (
            owner.compiled.program.particle_count, 3,
        )
        assert len(snapshot["parameters"]["partitions"]) == 2
        assert np.isfinite(
            snapshot["parameters"]["gravity_effective_strengths"]
        ).all()
        assert "_debug_product_step_basic" not in slot.data
        assert "_debug_product_constraint_inputs" not in slot.data
        assert "_debug_product_constraint_capture" not in slot.data
        debug_inspect = owner.inspect()["domain"]["kernel"]
        assert debug_inspect["constraint_debug_active_mask"] == 0
        assert debug_inspect["constraint_debug_captured_mask"] == 0
        center_partitions = snapshot["center"]["partitions"]
        teleport_partitions = snapshot["teleport"]["partitions"]
        assert snapshot["teleport"]["schema"] == (
            "mc2_product_task_teleport_debug_v1"
        )
        assert len(center_partitions) == len(teleport_partitions) == 2
        for center in center_partitions:
            shift = center["frame_shift"]
            assert 0.0 <= center["step"]["velocity_weight"] <= 1.0
            assert 0.0 <= center["step"]["gravity_ratio"] <= 1.0
            assert np.allclose(
                shift["frame_component_shift_vector"],
                np.asarray(shift["anchor_shift_vector"])
                + np.asarray(shift["smoothing_shift_vector"])
                + np.asarray(shift["world_shift_vector"]),
                atol=1.0e-6,
                rtol=0.0,
            )
            assert np.isfinite(shift["raw_component_delta"]).all()
        for teleport in teleport_partitions:
            assert teleport["mode"] in (0, 1, 2)
            assert isinstance(teleport["eligible"], bool)
            assert teleport["reference_index"] >= -1
            assert teleport["distance_threshold"] >= 0.0
            assert teleport["rotation_threshold_degrees"] >= 0.0
            assert teleport["measured_distance"] >= 0.0
            assert teleport["measured_rotation_degrees"] >= 0.0
            if teleport["eligible"]:
                np.testing.assert_allclose(
                    np.linalg.norm(teleport["old_reference_rotation_xyzw"]),
                    1.0,
                    atol=1.0e-6,
                )
                np.testing.assert_allclose(
                    np.linalg.norm(teleport["reference_rotation_xyzw"]),
                    1.0,
                    atol=1.0e-6,
                )
        assert snapshot["output"]["target_positions"].shape == (
            owner.compiled.program.particle_count,
            3,
        )
        assert np.array_equal(
            snapshot["output"]["target_positions"],
            slot.data["domain_output"].world_positions,
        )
        assert slot.data["scheduler_state"].revision == 1 + len(results)
        assert slot.data["frame_complete"] is True
    finally:
        world.omni_cache_dispose("native_substep_test_complete")


def test_slot_native_field_wind_changes_only_the_scoped_partition():
    calm_world = _world()
    windy_world = _world()
    calm_kernel = native_kernel_module.MC2NativeCPUKernelV1()
    windy_kernel = native_kernel_module.MC2NativeCPUKernelV1()
    try:
        _sync_mesh_product_slot(calm_world, _collection(), kernel=calm_kernel)
        _sync_mesh_product_slot(windy_world, _collection(), kernel=windy_kernel)
        calm_slot = calm_world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
        windy_slot = windy_world.solver_slots[slot_module.MC2_MESH_PRODUCT_SLOT_ID]
        calm_owner = calm_slot.data["owner"]
        windy_owner = windy_slot.data["owner"]
        program = windy_owner.compiled.program
        frame = _domain_frame(program, frame=14)
        calm_scheduled = _scheduled(calm_slot, frame)
        windy_scheduled = _scheduled(windy_slot, frame)
        assert calm_scheduled.schedule == windy_scheduled.schedule

        calm_world.frame_context = types.SimpleNamespace(
            frame=14,
            generation=1,
            sample_time_seconds=4.0,
            frame_step_dt=0.1,
        )
        windy_world.frame_context = types.SimpleNamespace(
            frame=14,
            generation=1,
            sample_time_seconds=4.0,
            frame_step_dt=0.1,
        )
        windy_world.set_runtime_cache(
            field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1,
            _field_runtime(frame=14, sample_time_seconds=4.0),
        )
        slot_module.publish_mc2_product_frame(
            calm_world, calm_slot, calm_scheduled, _empty_collider_frame(14),
        )
        slot_module.publish_mc2_product_frame(
            windy_world, windy_slot, windy_scheduled, _empty_collider_frame(14),
        )
        for _ in range(calm_scheduled.schedule.update_count):
            slot_module.step_mc2_product_substep(calm_world, calm_slot)
            slot_module.step_mc2_product_substep(windy_world, windy_slot)

        calm_positions = calm_owner.read_output().world_positions
        windy_positions = windy_owner.read_output().world_positions
        owners = np.asarray(program.particle_partition_index, dtype=np.intp)
        attributes = np.asarray(program.particle_attribute_flags, dtype=np.uint32)
        sleeve_dynamic = (owners == 0) & ((attributes & np.uint32(1)) == 0)
        assert sleeve_dynamic.any()
        assert np.any(windy_positions[sleeve_dynamic] != calm_positions[sleeve_dynamic])
        np.testing.assert_array_equal(
            windy_positions[owners == 1], calm_positions[owners == 1]
        )
        expected_time = 4.0 + (
            0.1
            * (calm_scheduled.schedule.update_count - 1)
            / calm_scheduled.schedule.update_count
        )
        native_field = windy_owner.inspect()["domain"]["kernel"]
        assert native_field["field_sample_time_seconds"] == expected_time
        assert native_field["field_sample_count"] == calm_scheduled.schedule.update_count
        assert native_field["field_apply_count"] == calm_scheduled.schedule.update_count
        assert native_field["field_sampled_field_count"] == 1
    finally:
        calm_world.omni_cache_dispose("native_field_calm_test_complete")
        windy_world.omni_cache_dispose("native_field_windy_test_complete")


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
