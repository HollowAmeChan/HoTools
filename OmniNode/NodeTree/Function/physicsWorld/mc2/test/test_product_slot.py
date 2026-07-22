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
collider_module = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.collider_frame")

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
        self.fail_create = False

    def create_domain(self, program, packet):
        if self.fail_create:
            raise RuntimeError("injected slot create failure")
        handle = {"program": program, "packet": packet, "serial": len(self.created)}
        self.created.append(handle)
        return handle

    def update_frame(self, handle, frame): self.frames.append((handle, frame))
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
    updated = slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    assert created.action == "created" and updated.action == "updated"
    assert updated.owner_report.action == "reused"
    assert world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID] is slot
    assert slot.data["owner"] is owner and len(kernel.created) == 1
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


def test_slot_publishes_one_domain_frame_and_collider_table_atomically():
    world = _world()
    kernel = _Kernel()
    slot_module.sync_mc2_mesh_fused_slot(world, _collection(), kernel=kernel)
    slot = world.solver_slots[slot_module.MC2_FUSED_MESH_SLOT_ID]
    program = slot.data["owner"].compiled.program
    normals = np.zeros((program.particle_count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    frame = ir.make_mc2_domain_frame_packet(
        program,
        frame=7,
        generation=1,
        animated_base_world_positions=program.particle_bind_position,
        animated_base_world_rotations=program.particle_bind_rotation,
        animated_base_world_normals=normals,
        partition_world_position=np.zeros((program.partition_count, 3), dtype=np.float32),
        partition_world_rotation=np.asarray(
            ((0.0, 0.0, 0.0, 1.0),) * program.partition_count,
            dtype=np.float32,
        ),
        partition_world_scale=np.ones((program.partition_count, 3), dtype=np.float32),
        partition_world_linear=np.asarray(
            (np.eye(3, dtype=np.float32),) * program.partition_count,
            dtype=np.float32,
        ),
    )
    try:
        slot_module.publish_mc2_mesh_fused_frame(
            world, slot, frame, _empty_collider_frame(8),
        )
    except ValueError as exc:
        assert "frame numbers" in str(exc)
    else:
        raise AssertionError("mismatched collider frame was accepted")
    assert kernel.frames == [] and "frame_packet" not in slot.data

    report = slot_module.publish_mc2_mesh_fused_frame(
        world, slot, frame, _empty_collider_frame(7),
    )
    assert report.partition_ids == program.partition_ids
    assert report.collider_count == 0 and len(kernel.frames) == 1
    assert slot.data["frame_packet"] is frame
    assert slot.data["collider_frame"].frame == 7
    assert slot.data["frame_ready"] is True
    assert slot.data["product_enabled"] is False
    assert world._current_writer is None


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
