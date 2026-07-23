# -*- coding: utf-8 -*-
"""Blender MC2统一域静态对照、E5产品节点与多目标事务验收。"""

from __future__ import annotations

import importlib
import hashlib
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
mc2_debug = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
mc2_debug_draw = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug_draw"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_product_collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_collect"
)
mc2_product_authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_authoring"
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
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
world_writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
mc2_native_loader = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native"
)
print("MC2_DOMAIN_SHADOW_NATIVE", mc2_native_loader.native_module().__file__)
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


def _offset_values_or_zero(obj):
    attribute = obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME)
    if attribute is None:
        return np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape((-1, 3))


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


def test_mc2_mesh_product_nodes_build_one_reported_domain():
    physics_blender.register()
    pairs = (
        _make_product_object("MC2CollectorNodeA", 0.0),
        _make_product_object("MC2CollectorNodeB", 1.5),
    )
    sources = tuple(pair[0] for pair in pairs)
    proxies = tuple(pair[1] for pair in pairs)
    world = world_types.PhysicsWorldCache()
    _set_frame_context(world, 1, None, 2)
    try:
        entries, count = mc2_nodes.physicsMC2MeshObject(list(sources))
        assert count == 2 and len(entries) == 2
        overridden, override_count = mc2_nodes.physicsMC2MeshOverride(
            entries[:1],
            profile=mc2_parameters.make_mc2_particle_profile(
                gravity=6.0,
                self_collision_mode=2,
                max_distance_enabled=True,
                max_distance=0.1,
                backstop_enabled=True,
                backstop_radius=0.05,
                angle_limit_enabled=True,
                angle_limit=30.0,
            ),
        )
        assert override_count == 1
        returned, registered, status = mc2_nodes.physicsMC2MeshImplicitRegister(
            world,
            overridden,
        )
        assert returned is world and registered == 1
        assert "隐式Mesh分区 1" in status

        requests, report = mc2_nodes.physicsMC2MeshCollector(
            world,
            entries,
            include_implicit=True,
        )
        assert len(requests) == 1
        request = requests[0]
        assert len(request.plan.active_partitions) == 2
        assert request.plan.report.merged_partition_count == 1
        assert "融合 2 个分区" in report
        assert "显隐合并 1" in report
        assert "Require Fusion" in report

        returned, ready, status = mc2_nodes.physicsMC2Step(
            world,
            requests,
            simulation_frequency=60,
            max_simulation_count_per_frame=3,
        )
        assert returned is world and ready is True, status
        slot_id = mc2_product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        slot = world.solver_slots[slot_id]
        assert slot.data["product_enabled"] is True
        assert slot.data["collector_request"] is request
        assert "分区 2" in status and "目标 2" in status
        assert world_writeback.writeback_gn_attributes(world) == 2
        assert mc2_debug.request_mc2_debug_capture(
            world,
            filters={
                "show_topology": True,
                "show_attributes": True,
                "show_depth": True,
                "show_step_basic": True,
                "show_gravity": True,
                "show_velocity": True,
                "show_motion_base": True,
                "show_motion": True,
                "show_angle_restoration": True,
                "show_angle_limit": True,
                "show_output": True,
                "show_center": True,
                "show_teleport_threshold": True,
                "show_teleport_status": True,
            },
        ) == 1

        sources[0].location.y = 0.05
        bpy.context.view_layer.update()
        _set_frame_context(world, 2, 1, 2)
        returned, ready, status = mc2_nodes.physicsMC2Step(
            world,
            requests,
            simulation_frequency=60,
            max_simulation_count_per_frame=3,
        )
        assert returned is world and ready is True, status
        assert world_writeback.writeback_gn_attributes(world) == 2
        assert len(slot.data["published_output_results"]) == 2
        snapshot = slot.data["_debug_draw_snapshot"]
        assert snapshot["schema"] == "mc2_product_debug_snapshot_v1"
        assert snapshot["source"] == "mc2_product_capture"
        assert snapshot["unsupported_filters"] == ()
        assert snapshot["native"]["positions"].flags.writeable is False
        assert snapshot["native"]["real_velocities"].flags.writeable is False
        assert snapshot["topology"]["baseline_depths"].shape == (
            slot.data["owner"].compiled.program.particle_count,
        )
        assert snapshot["motion"]["step_basic_positions"].flags.writeable is False
        assert snapshot["motion"]["normal_axis_values"].shape == (
            slot.data["owner"].compiled.program.particle_count,
        )
        for name in ("motion", "angle_restoration", "angle_limit"):
            records = snapshot["constraint_records"][name]
            assert len(records["states"]) > 0
            assert set(map(int, records["partitions"])).issubset({0, 1})
        assert np.isfinite(
            snapshot["constraint_records"]["motion"]["target_origins"]
        ).all()
        assert np.isfinite(
            snapshot["constraint_records"]["angle_limit"]["targets"]
        ).all()
        assert snapshot["parameters"]["schema"] == "mc2_product_gravity_debug_v1"
        assert len(snapshot["parameters"]["partitions"]) == 2
        assert len(snapshot["output"]["writeback_targets"]) == 2
        assert len(snapshot["center"]["partitions"]) == 2
        assert len(snapshot["teleport"]["partitions"]) == 2
        status_text = mc2_debug_draw.update_mc2_debug_draw_store(
            "mc2-product-center-debug",
            world,
            True,
            show_center=True,
            show_teleport_threshold=True,
            show_teleport_status=True,
            show_depth=True,
            show_step_basic=True,
            show_gravity=True,
            show_motion_base=True,
            show_motion=True,
            show_angle_restoration=True,
            show_angle_limit=True,
        )
        rendered = mc2_debug_draw.mc2_debug_draw_store_snapshot(
            "mc2-product-center-debug"
        )
        assert "Center：分区2" in status_text
        assert "Teleport：分区2" in status_text
        assert rendered is not None
        assert rendered["point_vertex_count"] > 0
        assert rendered["line_vertex_count"] > 0
        assert (
            mc2_names.MC2_INTERACTION_RESOURCE_KEY
            not in world.backend_resources
        )
        try:
            mc2_nodes.physicsMC2Step(world, [request, object()])
        except TypeError as exc:
            assert "只接受显式产品request" in str(exc)
        else:
            raise AssertionError("unified domain silently accepted legacy fallback input")
    finally:
        mc2_debug_draw.clear_mc2_debug_draw_store(
            node_uid="mc2-product-center-debug"
        )
        world.omni_cache_dispose("MC2 collector node acceptance cleanup")
        for source in reversed(sources):
            _remove_object(source)
        for proxy in reversed(proxies):
            _remove_object(proxy)


def _run_mc2_mesh_product_node_soak(run_name):
    pairs = (
        _make_product_object(f"{run_name}A", -0.75),
        _make_product_object(f"{run_name}B", 0.75),
    )
    sources = tuple(pair[0] for pair in pairs)
    proxies = tuple(pair[1] for pair in pairs)
    world = world_types.PhysicsWorldCache()
    trajectory = []
    try:
        entries, count = mc2_nodes.physicsMC2MeshObject(list(sources))
        assert count == 2
        requests, report = mc2_nodes.physicsMC2MeshCollector(
            world,
            entries,
            include_implicit=False,
        )
        assert len(requests) == 1 and "融合 2 个分区" in report
        previous = None
        for frame in range(1, 121):
            sources[0].location.y = 0.025 * np.sin(frame * 0.07)
            sources[1].rotation_euler.z = 0.04 * np.sin(frame * 0.05)
            bpy.context.view_layer.update()
            _set_frame_context(world, frame, previous, 41)
            returned, ready, status = mc2_nodes.physicsMC2Step(
                world,
                requests,
                simulation_frequency=60,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            assert world_writeback.writeback_gn_attributes(world) == 2
            diagnostics = world_writeback.get_gn_writeback_diagnostics(world)
            assert diagnostics["committed_transaction_count"] == 1
            assert diagnostics["failed_transaction_count"] == 0
            assert len(diagnostics["receipts"]) == 2
            trajectory.append(np.concatenate(
                tuple(_offset_values_or_zero(source) for source in sources),
                axis=0,
            ))
            previous = frame
        values = np.asarray(trajectory, dtype=np.float32)
        assert np.isfinite(values).all()
        digest = hashlib.sha256(
            np.ascontiguousarray(values).tobytes()
        ).hexdigest()
        request = requests[0]
        slot_id = mc2_product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        slot = world.solver_slots[slot_id]
        assert slot.data["product_enabled"] is True
        assert slot.data["owner"].compiled.program.partition_count == 2
        return digest, values
    finally:
        world.omni_cache_dispose("MC2 product node soak cleanup")
        for source in reversed(sources):
            _remove_object(source)
        for proxy in reversed(proxies):
            _remove_object(proxy)


def test_mc2_mesh_product_nodes_120_frame_deterministic_soak():
    physics_blender.register()
    first_digest, first = _run_mc2_mesh_product_node_soak("MC2ProductSoakOne")
    second_digest, second = _run_mc2_mesh_product_node_soak("MC2ProductSoakTwo")
    assert first_digest == second_digest
    np.testing.assert_array_equal(first, second)


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
        entries = tuple(
            mc2_product_authoring.override_mc2_mesh_partition_entries(
                mc2_product_authoring.make_mc2_mesh_partition_entries((source,)),
                profile=profile,
            )[0]
            for source, profile in zip(sources, profiles)
        )
        request = mc2_product_authoring.make_mc2_mesh_product_request(
            fused_world,
            entries,
            include_implicit=False,
        )
        slot_id = mc2_product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        collection = mc2_product_collect.collect_mc2_mesh_product_plan(
            fused_world,
            request.plan,
            receipt_slot_id=slot_id,
        )
        sync = mc2_product_slot.sync_mc2_product_slot(
            fused_world,
            collection,
            slot_id=slot_id,
        )
        assert sync.action == "created"
        slot = fused_world.solver_slots[slot_id]
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

            returned, ready, status = mc2_solver.step_mc2(
                v0_world,
                list(tasks),
                settings=settings,
            )
            assert returned is v0_world and ready is True, status
            published = mc2_product_slot.capture_and_publish_mc2_product_frame(
                fused_world,
                slot,
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
            public_results = (
                mc2_product_slot.publish_mc2_mesh_fused_output_transaction(
                    fused_world,
                    slot,
                )
            )
            assert len(public_results) == len(sources) == 2
            assert len({item["transaction_id"] for item in public_results}) == 1
            assert world_writeback.writeback_gn_attributes(fused_world) == 2
            for source, command in zip(
                sources,
                slot.data["published_output_batch"].commands,
            ):
                np.testing.assert_allclose(
                    _offset_values_or_zero(source),
                    command.object_local_offsets,
                    rtol=0.0,
                    atol=1.0e-6,
                )
            previous_frame = frame

        previous_stream = tuple(
            fused_world.result_streams.get(world_names.GN_ATTRIBUTE_CHANNEL, ())
        )
        sources[1].data.vertices.add(1)
        sources[1].data.update()
        try:
            mc2_product_slot.publish_mc2_mesh_fused_output_transaction(
                fused_world,
                slot,
            )
        except ValueError as exc:
            assert "vertex count changed" in str(exc)
        else:
            raise AssertionError("stale Mesh target was published")
        current_stream = tuple(
            fused_world.result_streams.get(world_names.GN_ATTRIBUTE_CHANNEL, ())
        )
        assert len(current_stream) == len(previous_stream)
        assert all(
            current is previous
            for current, previous in zip(current_stream, previous_stream)
        )
        assert world_writeback.writeback_gn_attributes(fused_world) == 0
        np.testing.assert_allclose(_offset_values_or_zero(sources[0]), 0.0)
        np.testing.assert_allclose(_offset_values_or_zero(sources[1]), 0.0)
        diagnostics = world_writeback.get_gn_writeback_diagnostics(fused_world)
        assert diagnostics["failed_transaction_count"] == 1
        assert diagnostics["written_count"] == 0
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
    test_mc2_mesh_product_nodes_build_one_reported_domain()
    print("PASS test_mc2_mesh_product_nodes_build_one_reported_domain")
    test_mc2_mesh_product_nodes_120_frame_deterministic_soak()
    print("PASS test_mc2_mesh_product_nodes_120_frame_deterministic_soak")
    test_mc2_mesh_fused_domain_matches_two_v0_sources()
    print("PASS test_mc2_mesh_fused_domain_matches_two_v0_sources")
