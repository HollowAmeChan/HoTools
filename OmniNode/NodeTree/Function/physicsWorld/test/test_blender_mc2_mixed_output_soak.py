"""Long-run mixed MeshCloth/BoneCloth/BoneSpring output acceptance."""

from __future__ import annotations

import importlib
import hashlib
import math
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


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
debug_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
bone_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
mesh_frame_input = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.frame_input"
)
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)


def _mesh_source():
    vertices = tuple(
        (x * 0.04, y * 0.04, 0.0)
        for y in range(4)
        for x in range(4)
    )
    faces = []
    for y in range(3):
        for x in range(3):
            a = y * 4 + x
            b = a + 1
            c = a + 4
            d = c + 1
            faces.extend(((a, b, d), (a, d, c)))
    mesh = bpy.data.meshes.new("MC2MixedMeshData")
    mesh.from_pydata(vertices, (), faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv.data[loop.index].uv = (x / 0.12, y / 0.12)
    obj = bpy.data.objects.new("MC2MixedMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="Pin")
    pin.add((0, 1, 2, 3), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    obj.hotools_mesh_collision.collided_by_groups = 1
    return obj


def _armature(name, x_offset, scale):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.location.x = x_offset
    obj.scale = (scale, scale, scale)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    control = data.edit_bones.new("Control")
    control.head = (0.0, -0.12, 0.0)
    control.tail = (0.0, 0.0, 0.0)
    parent = control
    for index in range(5):
        bone = data.edit_bones.new("Root" if index == 0 else f"Bone{index}")
        bone.head = (0.0, index * 0.12, 0.02 * index)
        bone.tail = (0.015 * index, (index + 1) * 0.12, 0.02 * (index + 1))
        bone.parent = parent
        bone.use_connect = index > 0 and index != 3
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _tasks(
    mesh,
    cloth,
    spring,
    damping,
    teleport_mode,
    *,
    blend_weight=1.0,
    stabilization_time_after_reset=0.1,
    teleport_rotation=180.0,
):
    mesh_profile = parameters.make_mc2_particle_profile(
        gravity=5.0,
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        self_collision_mode=0,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=teleport_rotation,
    )
    cloth_profile = parameters.make_mc2_particle_profile(
        gravity=3.0,
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        self_collision_mode=0,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=teleport_rotation,
    )
    spring_profile = parameters.make_mc2_particle_profile(
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=teleport_rotation,
    )
    mesh_tasks, _mesh_names = nodes.physicsMC2MeshClothTask(
        [mesh], profile=mesh_profile
    )
    cloth_tasks, _cloth_names = nodes.physicsMC2BoneClothTask(
        [{"armature": cloth, "bone": "Control"}],
        profile=cloth_profile,
        connection_mode=0,
        collided_by_groups=1,
    )
    spring_tasks, _spring_names = nodes.physicsMC2BoneSpringTask(
        [{"armature": spring, "bone": "Root"}],
        profile=spring_profile,
        collided_by_groups=1,
    )
    assert len(mesh_tasks) == len(cloth_tasks) == len(spring_tasks) == 1
    mesh_task = mesh_tasks[0]
    cloth_task = cloth_tasks[0]
    spring_task = spring_tasks[0]
    return (mesh_task, cloth_task, spring_task)


def _set_frame(world, frame, generation, *, raw_dt=None):
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    frame_dt = 1.0 / 90.0 if raw_dt is None else float(raw_dt)
    context.raw_dt = frame_dt
    context.dt = frame_dt
    context.time_scale = 1.0
    context.generation = generation
    world.generation = generation


def _animate_armature(armature, frame, amplitude):
    control = armature.pose.bones["Control"]
    control.rotation_mode = "XYZ"
    control.rotation_euler.z = amplitude * math.sin(frame * 0.021)
    control.location.x = 0.015 * math.sin(frame * 0.013)


def _assert_candidate(slot):
    candidate = slot.data["result_candidate"]
    assert candidate is not None
    assert np.all(np.isfinite(candidate.world_positions))
    assert np.all(np.isfinite(candidate.world_rotations_xyzw))
    return candidate


def _remove_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is None or data.users:
        return
    if isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Armature):
        bpy.data.armatures.remove(data)


def _run_scenario():
    physics_blender.register()
    mesh = cloth = spring = None
    world = world_types.PhysicsWorldCache()
    generation = 52
    original_contexts = None
    try:
        mesh = _mesh_source()
        cloth = _armature("MC2MixedBoneCloth", -0.3, 0.5)
        spring = _armature("MC2MixedBoneSpring", 0.3, 1.5)
        tasks = _tasks(mesh, cloth, spring, 0.05, 2)
        stable_ids = tuple(task.task_id for task in tasks)
        keep_hits = set()
        distance_reset_hits = set()
        rotation_reset_hits = set()
        root_keep_hits = set()
        root_reset_hits = set()
        previous_candidate_revisions = {task_id: 0 for task_id in stable_ids}
        max_particle_speeds = {
            task.setup_type: 0.0 for task in tasks
        }
        topologies = {
            task.task_id: topology_module.build_mc2_topology_spec(task)
            for task in tasks
        }
        teleport_counts_before = {}
        reset_frame_inputs = {}
        stabilization_samples = {
            setup_type: {}
            for setup_type in (
                names.MC2_SETUP_MESH_CLOTH,
                names.MC2_SETUP_BONE_CLOTH,
                names.MC2_SETUP_BONE_SPRING,
            )
        }
        for frame in range(1, 901):
            _animate_armature(cloth, frame, 0.18)
            _animate_armature(spring, frame, -0.14)
            if frame in (351, 401, 651, 701):
                root_x = 2.0 if frame in (351, 651) else -2.0
                for armature in (cloth, spring):
                    root = armature.pose.bones["Root"]
                    root.location = (root_x, 0.0, 0.0)
            bpy.context.view_layer.update()
            if frame == 301:
                for source in (mesh, cloth, spring):
                    source.location.x += 2.0
                bpy.context.view_layer.update()
            if frame == 451:
                original_contexts = tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
                )
                old_revisions = tuple(
                    context.inspect()["parameter_revision"]
                    for context in original_contexts
                )
                tasks = _tasks(
                    mesh,
                    cloth,
                    spring,
                    0.25,
                    1,
                    blend_weight=0.6,
                    stabilization_time_after_reset=0.2,
                    teleport_rotation=30.0,
                )
                assert tuple(task.task_id for task in tasks) == stable_ids
            if frame == 601:
                for source in (mesh, cloth, spring):
                    source.location.x += 2.0
                bpy.context.view_layer.update()
            if frame == 751:
                for source in (mesh, cloth, spring):
                    source.rotation_mode = "XYZ"
                    source.rotation_euler.z += math.radians(45.0)
                bpy.context.view_layer.update()
            _set_frame(
                world,
                frame,
                generation,
                raw_dt=(
                    1.0 / 360.0
                    if frame in (601, 651, 701)
                    else None
                ),
            )
            if frame in (301, 351, 401, 601, 651, 701, 751):
                teleport_counts_before = {}
                for task in tasks:
                    info = (
                        world.solver_slots[task.task_id]
                        .data["native_context"]
                        .inspect()
                    )
                    teleport_counts_before[task.task_id] = (
                        info["reset_count"],
                        info["particle_teleport_apply_count"],
                    )
            if frame in (601, 651, 701, 751):
                reset_frame_inputs = {}
                for task in tasks:
                    slot = world.solver_slots[task.task_id]
                    if task.setup_type == names.MC2_SETUP_MESH_CLOTH:
                        reset_frame_inputs[task.task_id] = (
                            mesh_frame_input.build_mc2_mesh_frame_input_for_task(
                                world,
                                task,
                                topologies[task.task_id],
                                slot.data["mesh_static"],
                            )
                        )
                    else:
                        reset_frame_inputs[task.task_id] = (
                            bone_frame_input.build_mc2_bone_frame_input(
                                task,
                                topologies[task.task_id],
                                frame=frame,
                                generation=generation,
                                world=world,
                            )
                        )
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(tasks),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            assert len(world.solver_slots) == 3
            for task in tasks:
                slot = world.solver_slots[task.task_id]
                candidate = _assert_candidate(slot)
                assert candidate.frame == frame
                assert candidate.revision == previous_candidate_revisions[task.task_id] + 1
                previous_candidate_revisions[task.task_id] = candidate.revision
                native_context = slot.data["native_context"]
                dynamics = native_context.refresh_debug_draw_snapshot(
                    include_step_basic=False,
                    include_dynamics=True,
                )["dynamics"]
                particle_speed = float(np.max(np.linalg.norm(
                    dynamics["velocities"],
                    axis=1,
                )))
                max_particle_speeds[task.setup_type] = max(
                    max_particle_speeds[task.setup_type], particle_speed
                )
                speed_limit = (
                    float(task.profile.particle_speed_limit)
                    * float(native_context.inspect()["scale_ratio"])
                )
                assert particle_speed <= speed_limit + 0.01, (
                    frame,
                    task.setup_type,
                    particle_speed,
                    speed_limit,
                )
                shift = slot.data["center_frame_shift_result"]
                if frame == 301:
                    assert shift is None
                    keep_hits.add(task.setup_type)
                if frame in (301, 601, 751):
                    teleport = slot.data["particle_teleport_result"]
                    assert teleport["mode"] == (2 if frame == 301 else 1)
                    assert (
                        teleport["trigger_count"]
                        == topologies[task.task_id].particle_count
                    ), (
                        frame,
                        task.setup_type,
                        teleport,
                        topologies[task.task_id].particle_count,
                    )
                    info = slot.data["native_context"].inspect()
                    reset_count, apply_count = teleport_counts_before[task.task_id]
                    assert info["reset_count"] == reset_count
                    assert info["particle_teleport_apply_count"] == apply_count + 1
                    if frame in (301, 601):
                        assert teleport["max_distance"] >= (
                            float(task.profile.teleport_distance)
                            * float(info["scale_ratio"])
                        )
                    else:
                        assert teleport["max_rotation_degrees"] >= float(
                            task.profile.teleport_rotation
                        )
                if frame in (351, 401, 651, 701):
                    teleport = slot.data["particle_teleport_result"]
                    reset_count, apply_count = teleport_counts_before[task.task_id]
                    info = slot.data["native_context"].inspect()
                    if task.setup_type == names.MC2_SETUP_MESH_CLOTH:
                        assert teleport["applied"] is False
                        assert teleport["trigger_count"] == 0
                        assert info["particle_teleport_apply_count"] == apply_count
                    else:
                        expected_mode = 2 if frame in (351, 401) else 1
                        assert teleport["mode"] == expected_mode
                        assert (
                            teleport["trigger_count"]
                            == topologies[task.task_id].particle_count
                        ), (frame, task.setup_type, teleport)
                        assert info["reset_count"] == reset_count
                        assert (
                            info["particle_teleport_apply_count"]
                            == apply_count + 1
                        )
                        if expected_mode == 2:
                            root_keep_hits.add((frame, task.setup_type))
                        else:
                            assert slot.data["frame_schedule"].update_count == 0
                            np.testing.assert_allclose(
                                candidate.world_positions,
                                reset_frame_inputs[task.task_id].world_positions,
                                atol=1.0e-6,
                            )
                            root_reset_hits.add((frame, task.setup_type))
                if frame in (601, 751):
                    assert shift is None
                    if frame == 601:
                        assert slot.data["frame_schedule"].update_count == 0
                    if frame == 601:
                        np.testing.assert_allclose(
                            candidate.world_positions,
                            reset_frame_inputs[task.task_id].world_positions,
                            atol=1.0e-6,
                        )
                        distance_reset_hits.add(task.setup_type)
                    else:
                        fixed = np.asarray(
                            slot.data[
                                "mesh_static"
                                if task.setup_type == names.MC2_SETUP_MESH_CLOTH
                                else "bone_static"
                            ].final_proxy.vertex_attributes,
                            dtype=np.uint8,
                        ) & np.uint8(0x01)
                        np.testing.assert_allclose(
                            candidate.world_positions[fixed != 0],
                            reset_frame_inputs[task.task_id].world_positions[fixed != 0],
                            atol=1.0e-6,
                        )
                        rotation_reset_hits.add(task.setup_type)
                    snapshot = slot.data["_debug_draw_snapshot"]
                    assert snapshot["frame"] == frame
                    assert snapshot["center"]["frame_shift"] is None
                    assert snapshot["center"]["particle_teleport"] == teleport
                    debug_output = snapshot["output"]
                    expected_output_positions = np.array(
                        candidate.world_positions,
                        dtype=np.float32,
                        copy=True,
                    )
                    translation_applied = np.asarray(
                        debug_output["translation_applied"],
                        dtype=np.uint8,
                    )
                    expected_output_positions[translation_applied == 0] = (
                        reset_frame_inputs[task.task_id]
                        .world_positions[translation_applied == 0]
                    )
                    np.testing.assert_allclose(
                        debug_output["target_positions"],
                        expected_output_positions,
                        atol=1.0e-7,
                    )
                if frame in (602, 610, 620):
                    assert not slot.data["particle_teleport_result"]["applied"], (
                        frame,
                        task.setup_type,
                        slot.data["particle_teleport_result"],
                    )
                    center_result = slot.data["center_step_result"]
                    assert center_result is not None
                    stabilization_samples[task.setup_type][frame] = (
                        center_result.velocity_weight,
                        center_result.blend_weight,
                    )
            assert writeback.writeback_gn_attributes(world) == 1
            assert writeback.writeback_bone_transforms(world) == 10
            bpy.context.view_layer.update()
            if frame == 751:
                same_frame_state = {
                    task.task_id: (
                        world.solver_slots[task.task_id]
                        .data["result_candidate"]
                        .revision,
                        np.array(
                            world.solver_slots[task.task_id]
                            .data["result_candidate"]
                            .world_positions,
                            copy=True,
                        ),
                        world.solver_slots[task.task_id]
                        .data["native_context"]
                        .inspect()["reset_count"],
                        world.solver_slots[task.task_id]
                        .data["native_context"]
                        .inspect()["particle_teleport_apply_count"],
                    )
                    for task in tasks
                }
                returned, ready, status = nodes.physicsMC2Step(
                    world,
                    list(tasks),
                    simulation_frequency=90,
                    max_simulation_count_per_frame=3,
                )
                assert returned is world and ready is True, status
                for task in tasks:
                    revision, positions, reset_count, teleport_count = (
                        same_frame_state[task.task_id]
                    )
                    slot = world.solver_slots[task.task_id]
                    assert slot.data["result_candidate"].revision == revision
                    np.testing.assert_array_equal(
                        slot.data["result_candidate"].world_positions,
                        positions,
                    )
                    assert slot.data["native_context"].inspect()["reset_count"] == reset_count
                    assert (
                        slot.data["native_context"]
                        .inspect()["particle_teleport_apply_count"]
                        == teleport_count
                    )
            if frame == 451:
                current_contexts = tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
                )
                assert current_contexts == original_contexts
                assert tuple(
                    context.inspect()["parameter_revision"]
                    for context in current_contexts
                ) == tuple(revision + 1 for revision in old_revisions)
            if frame in (600, 750):
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_center": True, "show_output": True},
                )
            elif frame == 899:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_output": True,
                        "show_motion": False,
                        "show_motion_base": False,
                        "show_angle_restoration": False,
                        "show_self": False,
                    },
                )

        setup_snapshots = {}
        for task in tasks:
            slot = world.solver_slots[task.task_id]
            snapshot = slot.data["_debug_draw_snapshot"]
            assert snapshot["frame"] == 900
            setup_snapshots[task.setup_type] = snapshot
            output = snapshot["output"]
            assert np.all(np.isfinite(output["world_offsets"]))
            assert output["writeback_target_count"] > 0

        mesh_output = setup_snapshots[names.MC2_SETUP_MESH_CLOTH]["output"]
        assert mesh_output["writeback_target_kind"] == "mesh_vertex"
        assert mesh_output["mesh_object_local_offsets"] is not None
        assert np.all(mesh_output["translation_applied"] == 1)

        for setup_type in (
            names.MC2_SETUP_BONE_CLOTH,
            names.MC2_SETUP_BONE_SPRING,
        ):
            output = setup_snapshots[setup_type]["output"]
            assert output["writeback_target_kind"] == "bone"
            assert output["rotation_only_connected_count"] > 0
            assert output["position_rotation_count"] > 0
            assert np.count_nonzero(output["translation_applied"] == 0) > 0
            assert np.count_nonzero(output["translation_applied"] == 1) > 0

        expected_setups = {
            names.MC2_SETUP_MESH_CLOTH,
            names.MC2_SETUP_BONE_CLOTH,
            names.MC2_SETUP_BONE_SPRING,
        }
        assert keep_hits == expected_setups
        assert distance_reset_hits == expected_setups
        assert rotation_reset_hits == expected_setups
        expected_bone_events = {
            (frame, setup_type)
            for frame in (351, 401)
            for setup_type in (
                names.MC2_SETUP_BONE_CLOTH,
                names.MC2_SETUP_BONE_SPRING,
            )
        }
        assert root_keep_hits == expected_bone_events
        expected_bone_events = {
            (frame, setup_type)
            for frame in (651, 701)
            for setup_type in (
                names.MC2_SETUP_BONE_CLOTH,
                names.MC2_SETUP_BONE_SPRING,
            )
        }
        assert root_reset_hits == expected_bone_events
        assert all(speed > 0.0 for speed in max_particle_speeds.values())
        expected_increment = (1.0 / 90.0) / 0.2
        for setup_type, samples in stabilization_samples.items():
            first_velocity, first_blend = samples[602]
            middle_velocity, middle_blend = samples[610]
            final_velocity, final_blend = samples[620]
            np.testing.assert_allclose(
                first_velocity, expected_increment, rtol=0.0, atol=1.0e-6
            )
            assert 0.0 < first_velocity < middle_velocity < final_velocity, (
                setup_type,
                first_velocity,
                middle_velocity,
                final_velocity,
            )
            np.testing.assert_allclose(final_velocity, 1.0, rtol=0.0, atol=1.0e-6)
            for velocity, blend in (
                (first_velocity, first_blend),
                (middle_velocity, middle_blend),
                (final_velocity, final_blend),
            ):
                np.testing.assert_allclose(
                    blend, velocity * 0.6, rtol=0.0, atol=1.0e-6
                )
            slot = next(
                world.solver_slots[task.task_id]
                for task in tasks
                if task.setup_type == setup_type
            )
            runtime = slot.data["effective_parameters"].debug_dict()
            np.testing.assert_allclose(
                runtime["float_values"]["blend_weight"],
                0.6,
                rtol=0.0,
                atol=1.0e-7,
            )
            np.testing.assert_allclose(
                runtime["float_values"]["stabilization_time_after_reset"],
                0.2,
                rtol=0.0,
                atol=1.0e-7,
            )

        stats = world.consume_results(
            names.MC2_STATS_CHANNEL,
            solver="mc2",
            frame=900,
            generation=generation,
        )
        assert len(stats) == 1
        assert stats[0]["mesh_cloth_count"] == 1
        assert stats[0]["bone_cloth_count"] == 1
        assert stats[0]["bone_spring_count"] == 1
        digest = hashlib.sha256()
        for setup_type in sorted(setup_snapshots):
            output = setup_snapshots[setup_type]["output"]
            digest.update(setup_type.encode("ascii"))
            for field in (
                "world_offsets", "target_positions", "translation_applied",
                "writeback_motion_modes",
            ):
                value = output.get(field)
                if value is None:
                    continue
                array = np.asarray(value)
                digest.update(str(array.dtype).encode("ascii"))
                digest.update(str(array.shape).encode("ascii"))
                digest.update(array.tobytes())
        deterministic_digest = digest.hexdigest()
        print(
            "[PASS] 900-frame mixed output/hot-update + all-setup Keep/Reset; "
            f"max speeds={max_particle_speeds}"
        )
    finally:
        world.omni_cache_dispose("mixed_output_soak")
        if mesh is not None and mesh.name in bpy.data.objects:
            proxy = mesh.hotools_mesh_collision.mc2_base_pose_proxy
            _remove_object(mesh)
            if proxy is not None and proxy.name in bpy.data.objects:
                _remove_object(proxy)
        for armature in (cloth, spring):
            if armature is not None and armature.name in bpy.data.objects:
                _remove_object(armature)
        if physics_blender.is_registered():
            physics_blender.unregister()
    return deterministic_digest


def main():
    first = _run_scenario()
    second = _run_scenario()
    assert second == first, (first, second)
    print("[PASS] repeated 900-frame mixed scenario is deterministic")
    print("MC2 mixed output soak: PASS")


if __name__ == "__main__":
    main()
