# -*- coding: utf-8 -*-
"""Blender E1 acceptance: explicit MeshCloth old/new static shadow compare."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
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

mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_product_collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_collect"
)
mc2_product_slot = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
mc2_domain_output = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.domain_output"
)
mc2_base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
mc2_gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


def _make_object():
    mesh = bpy.data.meshes.new("MC2DomainShadowMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        (),
        ((0, 1, 2, 3),),
    )
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="MC2_UV")
    coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = coords[loop.vertex_index]
    obj = bpy.data.objects.new("MC2DomainShadowObject", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _remove_object(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _make_product_object(name, x_offset):
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        (),
        ((0, 1, 2), (0, 2, 3)),
    )
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = coords[loop.vertex_index]
    obj = bpy.data.objects.new(name, mesh)
    obj.location.x = float(x_offset)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add((0,), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    mc2_gn_offset.write_gn_local_offsets(
        obj, np.zeros((len(mesh.vertices), 3), dtype=np.float32)
    )
    topology_signature = mc2_base_pose.mesh_topology_signature(obj)
    proxy = mc2_base_pose.ensure_base_pose_proxy(
        obj,
        expected_mesh_topology_signature=topology_signature,
    )
    return obj, proxy


def _set_frame_context(world, frame, previous_frame, generation):
    world.generation = generation
    context = world.frame_context
    context.previous_frame = previous_frame
    context.frame = frame
    context.continuous = previous_frame is not None and frame == previous_frame + 1
    context.same_frame = previous_frame == frame
    context.reset_requested = False
    context.restart_required = previous_frame is None
    context.raw_dt = 1.0 / 60.0
    context.dt = 1.0 / 60.0
    context.time_scale = 1.0
    context.substeps = 1
    context.generation = generation
    world.collider_snapshot = {"frame": frame, "colliders": []}


def test_mc2_mesh_domain_shadow_compile():
    obj = _make_object()
    world = world_types.PhysicsWorldCache()
    reports = []
    try:
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])
        returned, ready, status = mc2_solver.step_mc2(
            world,
            [task],
            shadow_compile=True,
            shadow_reports=reports,
        )
        assert returned is world
        assert ready is False
        assert status
        assert len(reports) == 1
        report = reports[0]
        assert report.compatible is True
        assert all(item.matched for item in report.checks)
        assert set(("capture", "fragment", "compile", "legacy_static")) <= set(
            report.timing_seconds
        )
        assert report.timing_seconds["total"] >= 0.0
    finally:
        for slot in tuple(world.solver_slots.values()):
            slot.dispose("E1 shadow test cleanup")
        _remove_object(obj)


def test_mc2_mesh_fused_domain_matches_two_v0_sources():
    physics_blender.register()
    sources = []
    proxies = []
    worlds = (world_types.PhysicsWorldCache(), world_types.PhysicsWorldCache())
    v0_world, fused_world = worlds
    generation = 73
    settings = mc2_parameters.make_mc2_solver_settings(
        simulation_frequency=60,
        max_simulation_count_per_frame=3,
    )
    try:
        for name, x_offset in (("MC2DomainSleeve", -1.5), ("MC2DomainCoat", 1.5)):
            source, proxy = _make_product_object(name, x_offset)
            sources.append(source)
            proxies.append(proxy)
        profiles = (
            mc2_parameters.make_mc2_particle_profile(
                gravity=5.0,
                damping=0.08,
                stabilization_time_after_reset=0.0,
                bending_stiffness=0.0,
                angle_restoration_enabled=False,
                angle_limit_enabled=False,
                self_collision_mode=0,
                collision_mode=0,
                collision_friction=0.0,
            ),
            mc2_parameters.make_mc2_particle_profile(
                gravity=8.0,
                damping=0.2,
                stabilization_time_after_reset=0.0,
                bending_stiffness=0.0,
                angle_restoration_enabled=False,
                angle_limit_enabled=False,
                self_collision_mode=0,
                collision_mode=0,
                collision_friction=0.0,
            ),
        )
        tasks = tuple(
            mc2_specs.make_mc2_task_spec(
                mc2_names.MC2_SETUP_MESH_CLOTH,
                [source],
                profile=profile,
            )
            for source, profile in zip(sources, profiles)
        )
        _set_frame_context(v0_world, 1, None, generation)
        _set_frame_context(fused_world, 1, None, generation)
        collection = mc2_product_collect.collect_mc2_mesh_product_domain(
            fused_world,
            tasks,
        )
        sync = mc2_product_slot.sync_mc2_mesh_fused_slot(
            fused_world,
            collection,
        )
        assert sync.action == "created"
        slot = fused_world.solver_slots[mc2_product_slot.MC2_FUSED_MESH_SLOT_ID]
        assert slot.data["product_enabled"] is False
        target_to_task = {
            snapshot.output_target_id: task
            for snapshot, task in zip(collection.static_snapshots, tasks)
        }

        previous_frame = None
        for frame in range(1, 4):
            sources[0].location.y = 0.04 * (frame - 1)
            sources[1].rotation_euler.z = 0.0
            bpy.context.view_layer.update()
            _set_frame_context(v0_world, frame, previous_frame, generation)
            _set_frame_context(fused_world, frame, previous_frame, generation)

            returned, ready, status = mc2_nodes.physicsMC2Step(
                v0_world,
                list(tasks),
                simulation_frequency=60,
                max_simulation_count_per_frame=3,
            )
            assert returned is v0_world and ready is True, status
            published = mc2_product_slot.capture_and_publish_mc2_mesh_fused_frame(
                fused_world,
                settings=settings,
            )
            assert published.partition_ids == collection.draft.partition_ids
            expected_update_count = 0 if frame == 1 else 1
            assert (
                published.update_count == expected_update_count
                and published.collider_count == 0
            )
            if expected_update_count:
                result = mc2_product_slot.step_mc2_mesh_fused_substep(
                    fused_world,
                    slot,
                )
                assert result.is_final_substep is True and result.update_index == 0
            else:
                assert slot.data["frame_complete"] is True

            owner = slot.data["owner"]
            output = owner.read_output()
            commands = mc2_domain_output.make_mc2_mesh_writeback_commands(
                owner.compiled.program,
                slot.data["frame_packet"],
                output,
            )
            assert output.frame == frame and output.generation == generation
            assert len(commands) == len(tasks) == 2
            for target_index, command in enumerate(commands):
                task = target_to_task[command.target_id]
                candidate = v0_world.solver_slots[task.task_id].data["result_candidate"]
                np.testing.assert_allclose(
                    command.world_positions,
                    candidate.world_positions,
                    rtol=1.0e-6,
                    atol=1.0e-6,
                )
                program = owner.compiled.program
                logical = np.flatnonzero(
                    program.output_target_index == np.uint32(target_index)
                )
                source_order = np.argsort(
                    program.output_source_element[logical],
                    kind="stable",
                )
                np.testing.assert_allclose(
                    output.world_rotations_xyzw[logical[source_order]],
                    candidate.world_rotations_xyzw,
                    rtol=1.0e-6,
                    atol=1.0e-6,
                )
            previous_frame = frame
    finally:
        for world in worlds:
            world.omni_cache_dispose("MC2 fused Blender oracle cleanup")
        for source in reversed(sources):
            _remove_object(source)
        for proxy in reversed(proxies):
            _remove_object(proxy)


if __name__ == "__main__":
    test_mc2_mesh_domain_shadow_compile()
    print("PASS test_mc2_mesh_domain_shadow_compile")
    test_mc2_mesh_fused_domain_matches_two_v0_sources()
    print("PASS test_mc2_mesh_fused_domain_matches_two_v0_sources")
