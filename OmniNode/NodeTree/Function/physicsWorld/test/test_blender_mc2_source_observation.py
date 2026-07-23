# -*- coding: utf-8 -*-
"""MC2 Mesh source observation cache 的 Blender 5.2 失效矩阵。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
PYTHON_ABI = f"py{sys.version_info.major}{sys.version_info.minor}"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for module_name in tuple(sys.modules):
    if (
        module_name == "hotools_native"
        or module_name == "HoTools"
        or module_name.startswith("HoTools.")
    ):
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in reversed((NATIVE_PACKAGE, HOTOOLS, os.path.dirname(HOTOOLS))):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
writeback_commands = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback_commands"
)
topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
observation_adapter = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.source_observation_blender"
)
observation_cache = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.source_observation"
)
partition_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.partition_specs"
)
native_loader = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native"
)
print("MC2_SOURCE_OBSERVATION_SOURCE", observation_adapter.__file__)
print("MC2_SOURCE_OBSERVATION_NATIVE", native_loader.native_module().__file__)


def _make_source():
    mesh = bpy.data.meshes.new("MC2ObservationMesh")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2)),
        ((0, 1, 2), (0, 2, 3)),
    )
    uv_layer = mesh.uv_layers.new(name="MC2UV")
    for index, item in enumerate(uv_layer.data):
        item.uv = ((index % 2), ((index // 2) % 2))
    source = bpy.data.objects.new("MC2ObservationObject", mesh)
    bpy.context.scene.collection.objects.link(source)
    pin_group = source.vertex_groups.new(name="Pinned")
    pin_group.add((0,), 1.0, "REPLACE")
    radius_a = source.vertex_groups.new(name="RadiusA")
    radius_a.add((0, 1, 2, 3), 0.75, "REPLACE")
    radius_b = source.vertex_groups.new(name="RadiusB")
    radius_b.add((0, 1, 2, 3), 0.25, "REPLACE")
    properties = source.hotools_mesh_collision
    properties.pin_enabled = True
    properties.pin_vertex_group = pin_group.name
    properties.radius_vertex_group = radius_a.name
    mesh.update()
    source.update_tag()
    bpy.context.view_layer.update()
    return source


def _task(source):
    entry = partition_specs.make_mc2_partition_entry(
        source,
        setup_type="mesh_cloth",
        origin="explicit",
        producer="test_blender_mc2_source_observation",
    )
    plan = partition_specs.collect_mc2_partition_entries(
        setup_type="mesh_cloth",
        explicit_entries=(entry,),
    )
    partition = plan.active_partitions[0]
    return types.SimpleNamespace(
        partition=partition,
        slot_id="mc2.domain.product.v1:mesh_cloth:" + plan.report.domain_signature,
    )


def _observe(world, task, **kwargs):
    return observation_adapter.prepare_observed_static_inputs_for_partition(
        world,
        task.partition,
        receipt_slot_id=task.slot_id,
        **kwargs,
    )


def _fingerprint_tuple(value):
    return value.fingerprint.native_values()


def _assert_matches_full_scan(task, observed) -> None:
    scanned, _snapshots = topology.prepare_static_inputs_for_partition(task.partition)
    assert observed.fingerprint == scanned


def _geometry_update(source) -> None:
    source.data.update()
    source.update_tag()
    bpy.context.view_layer.update()


def main() -> None:
    physics_blender.register()
    source = _make_source()
    replacement_mesh = None
    try:
        world = world_types.PhysicsWorldCache()
        world.generation = 7
        world.frame_context.frame = 11
        world.set_runtime_cache(
            observation_adapter.MC2_SOURCE_OBSERVATION_AUDIT_INTERVAL_KEY,
            0,
        )
        task = _task(source)

        first = _observe(world, task)
        assert first.statuses == ("miss",)
        _assert_matches_full_scan(task, first)
        assert all(
            not array.flags.writeable
            for array in (
                first.snapshots[0].positions,
                first.snapshots[0].normals,
                first.snapshots[0].edges,
                first.snapshots[0].triangles,
                first.snapshots[0].loop_uvs,
                first.snapshots[0].pin_weights,
                first.snapshots[0].radius_multipliers,
            )
        )
        hit = _observe(world, task)
        assert hit.statuses == ("hit",)
        assert hit.snapshots[0] is first.snapshots[0]

        source.location.x = 2.0
        bpy.context.view_layer.update()
        transformed = _observe(world, task)
        assert transformed.statuses == ("hit",)
        assert transformed.snapshots[0] is first.snapshots[0]

        writeback_commands.publish_gn_offset_writeback(
            world,
            solver="mc2",
            slot_id=task.slot_id,
            object_ptr=int(source.as_pointer()),
            object_data_ptr=int(source.data.as_pointer()),
            frame=world.frame_context.frame,
            generation=world.generation,
            local_offsets=np.zeros((len(source.data.vertices), 3), dtype=np.float32),
        )
        assert writeback.writeback_gn_attributes(world) == 1
        bpy.context.view_layer.update()
        internal = _observe(world, task)
        assert internal.statuses == ("hit",)
        assert internal.snapshots[0] is first.snapshots[0]

        world.frame_context.frame += 1
        writeback_commands.publish_gn_offset_writeback(
            world,
            solver="mc2",
            slot_id=task.slot_id,
            object_ptr=int(source.as_pointer()),
            object_data_ptr=int(source.data.as_pointer()),
            frame=world.frame_context.frame,
            generation=world.generation,
            local_offsets=np.full(
                (len(source.data.vertices), 3),
                0.001,
                dtype=np.float32,
            ),
        )
        assert writeback.writeback_gn_attributes(world) == 1
        bpy.context.view_layer.update()
        repeated_internal = _observe(world, task)
        assert repeated_internal.statuses == ("hit",)
        assert repeated_internal.snapshots[0] is first.snapshots[0]

        before_geometry = _fingerprint_tuple(repeated_internal)
        source.data.vertices[1].co.x = 1.25
        _geometry_update(source)
        geometry = _observe(world, task)
        assert geometry.statuses == ("revision",)
        assert geometry.fingerprint.geometry != before_geometry[1]
        _assert_matches_full_scan(task, geometry)

        before_surface = geometry.fingerprint.surface
        source.data.uv_layers.active.data[0].uv.x = 0.375
        _geometry_update(source)
        uv = _observe(world, task)
        assert uv.statuses == ("revision",)
        assert uv.fingerprint.surface != before_surface
        _assert_matches_full_scan(task, uv)

        before_surface = uv.fingerprint.surface
        source.vertex_groups["Pinned"].add((1,), 0.5, "REPLACE")
        _geometry_update(source)
        pin = _observe(world, task)
        assert pin.statuses == ("revision",)
        assert pin.fingerprint.surface != before_surface
        _assert_matches_full_scan(task, pin)

        before_surface = pin.fingerprint.surface
        source.hotools_mesh_collision.radius_vertex_group = "RadiusB"
        radius = _observe(world, task)
        assert radius.statuses == ("revision",)
        assert radius.fingerprint.surface != before_surface
        _assert_matches_full_scan(task, radius)

        before_topology = radius.fingerprint.topology
        source.data.clear_geometry()
        source.data.from_pydata(
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
             (0.0, 1.0, 0.0), (0.5, 0.5, 0.25)),
            ((0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)),
            ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
        )
        source.hotools_mesh_collision.pin_enabled = False
        source.hotools_mesh_collision.radius_vertex_group = ""
        _geometry_update(source)
        changed_topology = _observe(world, task)
        assert changed_topology.statuses == ("revision",)
        assert changed_topology.fingerprint.topology != before_topology
        _assert_matches_full_scan(task, changed_topology)

        audit_base = _observe(world, task)
        assert audit_base.statuses == ("hit",)
        source.data.vertices[2].co.y = 1.375
        audited = _observe(world, task, force_audit=True)
        assert audited.statuses == ("audit_mismatch",)
        assert audited.fingerprint.geometry != audit_base.fingerprint.geometry
        _assert_matches_full_scan(task, audited)

        replacement_mesh = source.data.copy()
        source.data = replacement_mesh
        bpy.context.view_layer.update()
        replacement_task = _task(source)
        replacement = _observe(world, replacement_task)
        assert replacement.statuses == ("miss",)
        assert replacement.identities != audited.identities
        assert observation_adapter.prune_source_observation_cache(
            world,
            replacement.identities,
        ) == 1

        entry = partition_specs.make_mc2_partition_entry(
            source,
            setup_type="mesh_cloth",
        )
        plan = partition_specs.collect_mc2_partition_entries(
            setup_type="mesh_cloth",
            explicit_entries=(entry,),
        )
        partition = plan.active_partitions[0]
        product_slot_id = (
            "mc2.domain.product.v1:mesh_cloth:" + plan.report.domain_signature
        )
        product_base = observation_adapter.prepare_observed_static_inputs_for_partition(
            world,
            partition,
            receipt_slot_id=product_slot_id,
        )
        world.frame_context.frame += 1
        writeback_commands.publish_gn_offset_writeback(
            world,
            solver="mc2",
            slot_id=product_slot_id,
            object_ptr=int(source.as_pointer()),
            object_data_ptr=int(source.data.as_pointer()),
            frame=world.frame_context.frame,
            generation=world.generation,
            local_offsets=np.zeros((len(source.data.vertices), 3), dtype=np.float32),
        )
        assert writeback.writeback_gn_attributes(world) == 1
        bpy.context.view_layer.update()
        product_internal = (
            observation_adapter.prepare_observed_static_inputs_for_partition(
                world,
                partition,
                receipt_slot_id=product_slot_id,
            )
        )
        assert product_internal.statuses == ("hit",)
        assert product_internal.snapshots[0] is product_base.snapshots[0]

        cache = world.runtime_cache(observation_cache.MC2_SOURCE_OBSERVATION_CACHE_KEY)
        report = cache.inspect()
        assert report["hits"] >= 4
        assert report["refreshes"] >= 5
        assert report["audit_mismatches"] == 1
        assert report["entries"] == 1
        print("MC2 source observation Blender invalidation matrix: PASS")
    finally:
        physics_blender.unregister()
        original_mesh = source.data
        bpy.data.objects.remove(source, do_unlink=True)
        if original_mesh is not None and original_mesh.users == 0:
            bpy.data.meshes.remove(original_mesh)


if __name__ == "__main__":
    main()
