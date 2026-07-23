"""E7-A：Mesh产品collector直接消费resolved partition。"""

from __future__ import annotations

import importlib
import os
import sys
import types
from types import SimpleNamespace

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

parameters = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters")
topology = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology")
collector = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_collect")
authoring = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_authoring")
partition_specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs")
product_slot = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot")


class _Data:
    def __init__(self, pointer):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Source:
    type = "MESH"

    def __init__(self, pointer):
        self._pointer = pointer
        self.data = _Data(pointer + 1000)
        self.name = self.name_full = f"Mesh{pointer}"
        self.matrix_world = np.eye(4, dtype=np.float32)

    def as_pointer(self):
        return self._pointer


class _World:
    def __init__(self):
        self.generation = 4
        self.frame_context = SimpleNamespace(frame=12)
        self.runtime_caches = {}

    def runtime_cache(self, name):
        return self.runtime_caches.get(name)

    def set_runtime_cache(self, name, value):
        self.runtime_caches[name] = value


def _raw(source, count):
    positions = np.zeros((count, 3), dtype=np.float32)
    positions[:, 0] = np.arange(count, dtype=np.float32)
    normals = np.zeros((count, 3), dtype=np.float32)
    normals[:, 2] = 1.0
    edges = np.asarray(tuple((index, index + 1) for index in range(count - 1)), dtype=np.int32).reshape((-1, 2))
    triangles = np.empty((0, 3), dtype=np.int32)
    empty = np.empty((0,), dtype=np.int32)
    arrays = (
        positions, normals, edges, triangles, triangles.copy(), empty,
        np.arange(count, dtype=np.int32), np.empty((0, 2), dtype=np.float32),
        np.empty((0,), dtype=np.float32), np.ones(count, dtype=np.float32),
    )
    for value in arrays:
        value.flags.writeable = False
    return topology.MC2MeshRawSnapshot(
        source_pointer=source.as_pointer(), mesh_pointer=source.data.as_pointer(),
        positions=arrays[0], normals=arrays[1], edges=arrays[2], triangles=arrays[3],
        triangle_loops=arrays[4], polygon_loop_totals=arrays[5], loop_vertices=arrays[6],
        loop_uvs=arrays[7], pin_weights=arrays[8], radius_multipliers=arrays[9],
        pin_enabled=False, pin_name="", radius_group_name="", has_uv=False,
    )


def _entry(source, *, gravity_direction=(0.0, -1.0, 0.0), enabled=True):
    entry = authoring.make_mc2_mesh_partition_entries((source,))[0]
    return authoring.override_mc2_mesh_partition_entries(
        (entry,),
        profile=parameters.make_mc2_particle_profile(
            gravity_direction=gravity_direction, self_collision_mode=2,
        ),
        setup_options=parameters.make_mc2_setup_options(
            "mesh_cloth", collided_by_groups=3,
        ),
        task_parameters=parameters.make_mc2_task_parameters(),
        enabled=enabled,
    )[0]


def _collect_request(world, entries, *, force_audit=None):
    request = authoring.make_mc2_mesh_product_request(
        world,
        entries,
        include_implicit=False,
    )
    slot_id = product_slot.make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )
    return (
        collector.collect_mc2_mesh_product_plan(
            world,
            request.plan,
            receipt_slot_id=slot_id,
            force_audit=force_audit,
        ),
        slot_id,
    )


def _install_observer(monkey_rows):
    calls = []

    def observe(world, partition, *, receipt_slot_id, force_audit=None):
        calls.append((partition.stable_id, receipt_slot_id, force_audit))
        raw = monkey_rows[partition.source.as_pointer()]
        fingerprint = topology.MC2StaticInputFingerprint(
            topology="1" * 32, geometry="2" * 32, surface="3" * 32,
            config="4" * 32, source="5" * 32,
            overall=("a" if raw.source_pointer == 101 else "b") * 32,
        )
        return SimpleNamespace(
            fingerprint=fingerprint, snapshots=(raw,),
            identities=((1, "mesh_cloth", raw.source_pointer, raw.mesh_pointer),),
            statuses=("hit",),
        )

    collector._prepare_observed_static_inputs = observe
    return calls


def test_product_collector_observes_once_and_preserves_authoring_order():
    first, second = _Source(101), _Source(202)
    calls = _install_observer({101: _raw(first, 3), 202: _raw(second, 2)})
    entries = (
        _entry(first, gravity_direction=(0.0, -1.0, 0.0)),
        _entry(second, gravity_direction=(1.0, 0.0, 0.0)),
    )
    result, slot_id = _collect_request(_World(), entries, force_audit=True)
    assert result.task_ids == tuple(entry.stable_id for entry in entries)
    assert result.draft.partition_ids == result.task_ids
    assert [snapshot.vertex_count for snapshot in result.static_snapshots] == [3, 2]
    assert [snapshot.output_target_id for snapshot in result.static_snapshots] == [
        "mesh:101:1101", "mesh:202:1202",
    ]
    assert result.world_gravity_directions == (
        (0.0, -1.0, 0.0), (1.0, 0.0, 0.0),
    )
    assert calls == [(entry.stable_id, slot_id, True) for entry in entries]


def test_product_collector_filters_disabled_explicit_entries():
    first, disabled = _Source(101), _Source(202)
    calls = _install_observer({101: _raw(first, 3), 202: _raw(disabled, 2)})
    active = _entry(first)
    result, slot_id = _collect_request(
        _World(),
        (active, _entry(disabled, enabled=False)),
    )
    assert result.task_ids == (active.stable_id,)
    assert calls == [(active.stable_id, slot_id, None)]


def test_product_collector_rejects_no_active_mesh_partition():
    source = _Source(101)
    _install_observer({101: _raw(source, 3)})
    try:
        plan = partition_specs.collect_mc2_partition_entries(
            setup_type="mesh_cloth",
            explicit_entries=(_entry(source, enabled=False),),
            default_profile=parameters.make_mc2_particle_profile(),
            default_task_parameters=parameters.make_mc2_task_parameters(),
            default_setup_options=parameters.make_mc2_setup_options("mesh_cloth"),
        )
        collector.collect_mc2_mesh_product_plan(
            _World(),
            plan,
            receipt_slot_id="mc2.domain.product.v1:mesh_cloth:" + "0" * 64,
        )
    except ValueError as exc:
        assert "no active partitions" in str(exc)
    else:
        raise AssertionError("empty Mesh product domain was accepted")


def test_product_collector_consumes_one_explicit_domain_plan_without_task_expansion():
    first, second = _Source(301), _Source(302)
    calls = _install_observer({301: _raw(first, 4), 302: _raw(second, 5)})
    entries = authoring.make_mc2_mesh_partition_entries((first, second))
    request = authoring.make_mc2_mesh_product_request(
        _World(),
        entries,
        include_implicit=False,
    )
    result = collector.collect_mc2_mesh_product_plan(
        _World(),
        request.plan,
        receipt_slot_id="mc2.domain.product.v1:mesh_cloth:" + request.domain_signature,
    )
    assert result.task_ids == tuple(entry.stable_id for entry in entries)
    assert result.draft.partition_ids == result.task_ids
    assert len(calls) == 2
    assert result.draft.collector_domain_signature == request.domain_signature


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


if __name__ == "__main__":
    for name, test in TESTS:
        test()
        print(f"PASS {name}")
    print(f"MC2 product collector: {len(TESTS)} passed")
