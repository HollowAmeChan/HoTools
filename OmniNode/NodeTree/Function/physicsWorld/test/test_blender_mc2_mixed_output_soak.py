"""Long-run mixed MeshCloth/BoneCloth/BoneSpring output acceptance."""

from __future__ import annotations

import importlib
import hashlib
import math
import os
import sys
import types

import bpy
from mathutils import Matrix
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


def _mesh_source(name="MC2MixedMesh"):
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
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(vertices, (), faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv.data[loop.index].uv = (x / 0.12, y / 0.12)
    obj = bpy.data.objects.new(name, mesh)
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
    particle_speed_limit=4.0,
    anchor_inertia=0.0,
    world_inertia=1.0,
    movement_inertia_smoothing=0.4,
    movement_speed_limit=5.0,
    rotation_speed_limit=720.0,
    local_inertia=1.0,
    local_movement_speed_limit=-1.0,
    local_rotation_speed_limit=-1.0,
    depth_inertia=0.0,
    anchor_object=None,
):
    mesh_profile = parameters.make_mc2_particle_profile(
        gravity=5.0,
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        self_collision_mode=0,
        particle_speed_limit=particle_speed_limit,
    )
    cloth_profile = parameters.make_mc2_particle_profile(
        gravity=3.0,
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        self_collision_mode=0,
        particle_speed_limit=particle_speed_limit,
    )
    spring_profile = parameters.make_mc2_particle_profile(
        damping=damping,
        blend_weight=blend_weight,
        stabilization_time_after_reset=stabilization_time_after_reset,
        particle_speed_limit=particle_speed_limit,
    )
    task_values = {
        "anchor_inertia": anchor_inertia,
        "world_inertia": world_inertia,
        "movement_inertia_smoothing": movement_inertia_smoothing,
        "movement_speed_limit": movement_speed_limit,
        "rotation_speed_limit": rotation_speed_limit,
        "local_inertia": local_inertia,
        "local_movement_speed_limit": local_movement_speed_limit,
        "local_rotation_speed_limit": local_rotation_speed_limit,
        "depth_inertia": depth_inertia,
        "teleport_mode": teleport_mode,
        "teleport_distance": 0.5,
        "teleport_rotation": teleport_rotation,
    }
    mesh_tasks, _mesh_names = nodes.physicsMC2MeshClothTask(
        [mesh], profile=mesh_profile, anchor_object=anchor_object, **task_values
    )
    cloth_tasks, _cloth_names = nodes.physicsMC2BoneClothTask(
        [{"armature": cloth, "bone": "Control"}],
        profile=cloth_profile,
        anchor_object=anchor_object,
        **task_values,
        connection_mode=0,
        collided_by_groups=1,
    )
    spring_tasks, _spring_names = nodes.physicsMC2BoneSpringTask(
        [{"armature": spring, "bone": "Root"}],
        profile=spring_profile,
        anchor_object=anchor_object,
        **task_values,
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


def _build_frame_inputs(world, tasks, topologies, frame, generation):
    result = {}
    for task in tasks:
        slot = world.solver_slots[task.task_id]
        if task.setup_type == names.MC2_SETUP_MESH_CLOTH:
            result[task.task_id] = (
                mesh_frame_input.build_mc2_mesh_frame_input_for_task(
                    world,
                    task,
                    topologies[task.task_id],
                    slot.data["mesh_static"],
                )
            )
        else:
            result[task.task_id] = bone_frame_input.build_mc2_bone_frame_input(
                task,
                topologies[task.task_id],
                frame=frame,
                generation=generation,
                world=world,
            )
    return result


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
        low_limit_peak_ratios = {
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
            animation_frame = min(frame, 800)
            _animate_armature(cloth, animation_frame, 0.18)
            _animate_armature(spring, animation_frame, -0.14)
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
            if frame in (501, 551):
                contexts_before_limit_update = tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
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
                    particle_speed_limit=0.05 if frame == 501 else 4.0,
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
                    1.0e-6
                    if frame in (601, 651, 701)
                    else None
                ),
            )
            if frame in (301, 351, 401):
                world.frame_context.time_scale = 0.0
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
                        info["task_teleport_apply_count"],
                    )
            if frame in (601, 651, 701, 751):
                reset_frame_inputs = _build_frame_inputs(
                    world, tasks, topologies, frame, generation
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
                if 501 <= frame < 551:
                    low_limit_peak_ratios[task.setup_type] = max(
                        low_limit_peak_ratios[task.setup_type],
                        particle_speed / speed_limit,
                    )
                shift = slot.data["center_frame_shift_result"]
                if frame == 301:
                    assert shift is None
                    assert np.all(np.isfinite(dynamics["velocities"]))
                    assert np.all(np.isfinite(dynamics["real_velocities"]))
                    keep_hits.add(task.setup_type)
                if frame in (301, 601, 751):
                    teleport = slot.data["task_teleport_result"]
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
                    assert info["reset_count"] == reset_count + (
                        1 if int(teleport["mode"]) == 1 else 0
                    )
                    assert info["task_teleport_apply_count"] == apply_count + 1
                    if frame in (301, 601):
                        assert teleport["measured_distance"] >= (
                            float(task.task_parameters.teleport_distance)
                            * float(info["scale_ratio"])
                        )
                    else:
                        assert teleport["measured_rotation_degrees"] >= float(
                            task.task_parameters.teleport_rotation
                        )
                if frame in (351, 401, 651, 701):
                    teleport = slot.data["task_teleport_result"]
                    reset_count, apply_count = teleport_counts_before[task.task_id]
                    info = slot.data["native_context"].inspect()
                    if task.setup_type == names.MC2_SETUP_MESH_CLOTH:
                        assert teleport["applied"] is False
                        assert teleport["trigger_count"] == 0
                        assert info["task_teleport_apply_count"] == apply_count
                    else:
                        expected_mode = 2 if frame in (351, 401) else 1
                        assert teleport["mode"] == expected_mode
                        assert (
                            teleport["trigger_count"]
                            == topologies[task.task_id].particle_count
                        ), (frame, task.setup_type, teleport)
                        assert info["reset_count"] == reset_count + (
                            1 if expected_mode == 1 else 0
                        )
                        assert (
                            info["task_teleport_apply_count"]
                            == apply_count + 1
                        )
                        if expected_mode == 2:
                            assert np.all(np.isfinite(dynamics["velocities"]))
                            assert np.all(np.isfinite(dynamics["real_velocities"]))
                            root_keep_hits.add((frame, task.setup_type))
                        else:
                            assert slot.data["frame_schedule"].update_count == 0
                            np.testing.assert_allclose(
                                candidate.world_positions,
                                reset_frame_inputs[task.task_id].world_positions,
                                atol=1.0e-6,
                            )
                            np.testing.assert_array_equal(
                                dynamics["velocities"],
                                np.zeros_like(dynamics["velocities"]),
                            )
                            np.testing.assert_array_equal(
                                dynamics["real_velocities"],
                                np.zeros_like(dynamics["real_velocities"]),
                            )
                            root_reset_hits.add((frame, task.setup_type))
                    if frame == 651:
                        snapshot = slot.data["_debug_draw_snapshot"]
                        assert snapshot["teleport"]["reference_kind"] == "first_fixed"
                        assert snapshot["teleport"]["applied"] is (
                            task.setup_type != names.MC2_SETUP_MESH_CLOTH
                        )
                        assert snapshot["filters"]["show_teleport_threshold"] is True
                        assert snapshot["filters"].get("show_teleport_status", False) is False
                    if frame == 701:
                        snapshot = slot.data["_debug_draw_snapshot"]
                        assert snapshot["teleport"]["mode"] == 1
                        assert snapshot["teleport"]["applied"] is (
                            task.setup_type != names.MC2_SETUP_MESH_CLOTH
                        )
                        assert snapshot["filters"]["show_teleport_status"] is True
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
                        np.testing.assert_array_equal(
                            dynamics["velocities"],
                            np.zeros_like(dynamics["velocities"]),
                        )
                        np.testing.assert_array_equal(
                            dynamics["real_velocities"],
                            np.zeros_like(dynamics["real_velocities"]),
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
                    assert snapshot["center"]["task_teleport"] == teleport
                    if frame == 601:
                        assert snapshot["teleport"]["applied"] is True
                        assert snapshot["teleport"]["trigger_count"] == candidate.particle_count
                        assert snapshot["teleport"]["reference_kind"] in (
                            "first_fixed", "object_origin"
                        )
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
                    assert not slot.data["task_teleport_result"]["applied"], (
                        frame,
                        task.setup_type,
                        slot.data["task_teleport_result"],
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
                        .inspect()["task_teleport_apply_count"],
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
                        .inspect()["task_teleport_apply_count"]
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
            if frame in (501, 551):
                assert tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
                ) == contexts_before_limit_update
            if frame in (300, 350, 400, 650):
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_teleport_threshold": True},
                )
            elif frame == 600:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_center": True,
                        "show_teleport_threshold": True,
                        "show_teleport_status": True,
                        "show_output": True,
                    },
                )
            elif frame == 700:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_teleport_status": True},
                )
            elif frame == 750:
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
        assert all(
            0.98 <= ratio <= 1.0001
            for ratio in low_limit_peak_ratios.values()
        ), low_limit_peak_ratios
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
            digest.update(
                np.asarray(
                    low_limit_peak_ratios[setup_type], dtype=np.float32
                ).tobytes()
            )
        deterministic_digest = digest.hexdigest()
        print(
            "[PASS] 900-frame mixed output/hot-update + all-setup Keep/Reset; "
            f"max speeds={max_particle_speeds}; "
            f"low-limit peak ratios={low_limit_peak_ratios}"
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


def _center_translation_velocity(frame):
    if frame <= 200:
        return 0.9
    if frame <= 400:
        return -0.45
    return 0.3


_CENTER_TRANSLATION_FRAME_RATE = 30.0


def _run_center_case(
    case_name,
    *,
    motion_space="world",
    component_translation=True,
    component_rotation_speed=0.0,
    **profile_values,
):
    physics_blender.register()
    mesh = cloth = spring = None
    world = world_types.PhysicsWorldCache()
    generation = 70
    try:
        mesh = _mesh_source(f"MC2Center{case_name}Mesh")
        cloth = _armature(f"MC2Center{case_name}Cloth", -0.3, 0.5)
        spring = _armature(f"MC2Center{case_name}Spring", 0.3, 1.5)
        sources = (mesh, cloth, spring)
        base_x = {source.name: float(source.location.x) for source in sources}
        tasks = _tasks(
            mesh,
            cloth,
            spring,
            0.1,
            0,
            stabilization_time_after_reset=0.0,
            particle_speed_limit=4.0,
            **profile_values,
        )
        observations = {
            task.setup_type: {
                "shift_x": [],
                "moving_speed": [],
                "smoothing_x": [],
                "shift_rotation_degrees": [],
                "step_x": [],
                "step_rotation_degrees": [],
                "angular_velocity_degrees": [],
                "step_move_inertia_ratio": [],
                "step_rotation_inertia_ratio": [],
                "inertia_x": [],
                "inertia_rotation_degrees": [],
                "candidate_positions": [],
                "update_count": [],
                "skip_count": [],
            }
            for task in tasks
        }
        component_x = 0.0
        component_rotation_degrees = 0.0
        proxy_base = None
        proxy_pivot = None
        for frame in range(1, 601):
            velocity = _center_translation_velocity(frame)
            if frame > 1 and component_translation:
                component_x += velocity / _CENTER_TRANSLATION_FRAME_RATE
            if frame > 1:
                component_rotation_degrees += (
                    component_rotation_speed / _CENTER_TRANSLATION_FRAME_RATE
                )
            if motion_space == "world":
                for source in sources:
                    source.location.x = base_x[source.name] + component_x
                    source.rotation_mode = "XYZ"
                    source.rotation_euler.z = math.radians(
                        component_rotation_degrees
                    )
            elif motion_space == "local" and frame > 1:
                angle = math.radians(component_rotation_degrees)
                cosine = math.cos(angle)
                sine = math.sin(angle)
                for index in range(4):
                    local = proxy_base[index] - proxy_pivot
                    rotated = np.asarray((
                        cosine * local[0] - sine * local[1],
                        sine * local[0] + cosine * local[1],
                        local[2],
                    ))
                    target = proxy_pivot + rotated
                    target[0] += component_x
                    proxy.data.vertices[index].co = target
                proxy.data.update()
                for armature in (cloth, spring):
                    root = armature.pose.bones["Root"]
                    root.rotation_mode = "XYZ"
                    root.location = (component_x, 0.0, 0.0)
                    root.rotation_euler = (
                        0.0, 0.0, math.radians(component_rotation_degrees)
                    )
            elif motion_space != "local":
                raise ValueError(f"unsupported Center motion space: {motion_space}")
            bpy.context.view_layer.update()
            _set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / _CENTER_TRANSLATION_FRAME_RATE
            world.frame_context.dt = 1.0 / _CENTER_TRANSLATION_FRAME_RATE
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(tasks),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            for task in tasks:
                slot = world.solver_slots[task.task_id]
                candidate = _assert_candidate(slot)
                assert candidate.frame == frame
                if frame == 1:
                    assert slot.data["center_frame_shift_result"] is None
                    if motion_space == "local" and proxy_base is None:
                        proxy = mesh.hotools_mesh_collision.mc2_base_pose_proxy
                        assert proxy is not None
                        proxy_base = np.asarray(
                            [vertex.co[:] for vertex in proxy.data.vertices],
                            dtype=np.float64,
                        )
                        proxy_pivot = np.mean(proxy_base[:4], axis=0)
                    continue
                result = slot.data["center_frame_shift_result"]
                values = observations[task.setup_type]
                schedule = slot.data["frame_schedule"]
                values["update_count"].append(float(schedule.update_count))
                values["skip_count"].append(float(schedule.skip_count))
                if result is None:
                    assert case_name == "Hold" or motion_space == "local", (
                        case_name,
                        motion_space,
                        task.setup_type,
                        frame,
                    )
                    values["shift_x"].append(0.0)
                    values["moving_speed"].append(0.0)
                    values["smoothing_x"].append(0.0)
                    values["shift_rotation_degrees"].append(0.0)
                else:
                    assert result.teleport_triggered is False
                    values["shift_x"].append(
                        float(result.frame_component_shift_vector[0])
                    )
                    values["moving_speed"].append(
                        float(result.frame_moving_speed)
                    )
                    values["smoothing_x"].append(
                        float(result.smoothing_velocity[0])
                    )
                    shift_rotation = result.frame_component_shift_rotation_xyzw
                    shift_cosine = min(
                        1.0, max(0.0, abs(float(shift_rotation[3])))
                    )
                    values["shift_rotation_degrees"].append(
                        math.degrees(2.0 * math.acos(shift_cosine))
                    )
                center_step = slot.data["center_step_result"]
                assert center_step is not None
                values["candidate_positions"].append(
                    np.array(candidate.world_positions, dtype=np.float32, copy=True)
                )
                values["step_x"].append(float(center_step.step_vector[0]))
                step_rotation = center_step.step_rotation_xyzw
                step_cosine = min(
                    1.0, max(0.0, abs(float(step_rotation[3])))
                )
                values["step_rotation_degrees"].append(
                    math.degrees(2.0 * math.acos(step_cosine))
                )
                values["angular_velocity_degrees"].append(
                    math.degrees(float(center_step.angular_velocity))
                )
                values["step_move_inertia_ratio"].append(
                    float(center_step.step_move_inertia_ratio)
                )
                values["step_rotation_inertia_ratio"].append(
                    float(center_step.step_rotation_inertia_ratio)
                )
                values["inertia_x"].append(
                    float(center_step.inertia_vector[0])
                )
                inertia_rotation = center_step.inertia_rotation_xyzw
                inertia_cosine = min(
                    1.0, max(0.0, abs(float(inertia_rotation[3])))
                )
                values["inertia_rotation_degrees"].append(
                    math.degrees(2.0 * math.acos(inertia_cosine))
                )

        for task in tasks:
            slot = world.solver_slots[task.task_id]
            context = slot.data["native_context"]
            info = context.inspect()
            assert info["debug_readback_count"] == 0
            if case_name == "Hold" or motion_space == "local":
                assert info["center_frame_shift_count"] <= 3, (
                    task.setup_type,
                    info["center_frame_shift_count"],
                )
            else:
                assert info["center_frame_shift_count"] == 599, (
                    case_name,
                    task.setup_type,
                    info["center_frame_shift_count"],
                )
            mesh_static = slot.data.get("mesh_static")
            bone_static = slot.data.get("bone_static")
            if mesh_static is not None:
                depths = mesh_static.baseline.baseline.depths
                attributes = mesh_static.final_proxy.vertex_attributes
            else:
                assert bone_static is not None
                depths = bone_static.baseline.depths
                attributes = bone_static.final_proxy.vertex_attributes
            observations[task.setup_type]["depths"] = list(depths)
            observations[task.setup_type]["move_mask"] = [
                1.0 if int(attribute) & 0x02 else 0.0
                for attribute in attributes
            ]
            observations[task.setup_type]["particle_inertia_count"] = [
                float(info["particle_inertia_count"])
            ]
        return {
            setup_type: {
                name: np.asarray(values, dtype=np.float32)
                for name, values in setup_values.items()
            }
            for setup_type, setup_values in observations.items()
        }
    finally:
        world.omni_cache_dispose(f"center_world_translation_{case_name}")
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


def _run_center_world_suite():
    cases = {
        "follow": _run_center_case(
            "Follow",
            world_inertia=0.0,
            movement_inertia_smoothing=0.0,
            movement_speed_limit=-1.0,
            rotation_speed_limit=-1.0,
        ),
        "hold": _run_center_case(
            "Hold",
            world_inertia=1.0,
            movement_inertia_smoothing=0.0,
            movement_speed_limit=-1.0,
            rotation_speed_limit=-1.0,
        ),
        "smooth": _run_center_case(
            "Smooth",
            world_inertia=1.0,
            movement_inertia_smoothing=0.8,
            movement_speed_limit=-1.0,
            rotation_speed_limit=-1.0,
        ),
        "limited": _run_center_case(
            "Limited",
            world_inertia=1.0,
            movement_inertia_smoothing=0.0,
            movement_speed_limit=0.2,
            rotation_speed_limit=-1.0,
        ),
        "rotation_limited": _run_center_case(
            "RotationLimited",
            component_translation=False,
            component_rotation_speed=90.0,
            world_inertia=1.0,
            movement_inertia_smoothing=0.0,
            movement_speed_limit=-1.0,
            rotation_speed_limit=30.0,
        ),
    }
    input_velocity = np.asarray(
        [_center_translation_velocity(frame) for frame in range(2, 601)],
        dtype=np.float32,
    )
    input_delta = input_velocity / np.float32(_CENTER_TRANSLATION_FRAME_RATE)
    digest = hashlib.sha256()
    for setup_type in sorted(cases["follow"]):
        follow = cases["follow"][setup_type]
        hold = cases["hold"][setup_type]
        smooth = cases["smooth"][setup_type]
        limited = cases["limited"][setup_type]
        rotation_limited = cases["rotation_limited"][setup_type]
        stable = np.logical_and(
            hold["update_count"] == 3.0,
            hold["skip_count"] == 0.0,
        )
        assert int(np.count_nonzero(stable)) >= 590
        np.testing.assert_allclose(
            follow["shift_x"][stable],
            input_delta[stable],
            rtol=0.0,
            atol=2.0e-6,
        )
        np.testing.assert_allclose(
            hold["shift_x"][stable],
            np.zeros(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=2.0e-6,
        )
        residual_speed = (
            np.abs(input_delta - limited["shift_x"])
            * _CENTER_TRANSLATION_FRAME_RATE
        )
        assert np.all(residual_speed[stable] <= 0.2001), (
            setup_type,
            float(np.max(residual_speed[stable])),
        )
        np.testing.assert_allclose(
            residual_speed[stable],
            np.full(int(np.count_nonzero(stable)), 0.2, dtype=np.float32),
            rtol=0.0,
            atol=2.0e-4,
        )
        assert np.max(np.abs(smooth["smoothing_x"])) > 0.25
        assert np.max(np.abs(smooth["shift_x"] - hold["shift_x"])) > 1.0e-4
        assert np.max(np.abs(smooth["shift_x"] - follow["shift_x"])) > 1.0e-4
        assert np.all(
            np.abs(follow["shift_x"][stable]) + 2.0e-6
            >= np.abs(limited["shift_x"][stable])
        )
        assert np.all(
            np.abs(limited["shift_x"][stable]) + 2.0e-6
            >= np.abs(hold["shift_x"][stable])
        )
        rotation_stable = np.logical_and(
            rotation_limited["update_count"] == 3.0,
            rotation_limited["skip_count"] == 0.0,
        )
        assert int(np.count_nonzero(rotation_stable)) >= 590
        np.testing.assert_allclose(
            rotation_limited["shift_rotation_degrees"][rotation_stable],
            np.full(
                int(np.count_nonzero(rotation_stable)),
                2.0,
                dtype=np.float32,
            ),
            rtol=0.0,
            atol=2.0e-3,
        )
        for case_name in sorted(cases):
            values = cases[case_name][setup_type]
            for field in (
                "shift_x", "moving_speed", "smoothing_x",
                "shift_rotation_degrees",
                "update_count", "skip_count",
            ):
                array = values[field]
                assert np.all(np.isfinite(array))
                digest.update(setup_type.encode("ascii"))
                digest.update(case_name.encode("ascii"))
                digest.update(field.encode("ascii"))
                digest.update(array.tobytes())
    return digest.hexdigest()


def center_world_controls():
    first = _run_center_world_suite()
    second = _run_center_world_suite()
    assert second == first, (first, second)
    print(
        "[PASS] Center World inertia/smoothing/translation+rotation limits: "
        "3 setups x 5 cases x 2 deterministic runs x 600 frames"
    )


def _run_center_local_suite():
    common = {
        "motion_space": "local",
        "world_inertia": 1.0,
        "movement_inertia_smoothing": 0.0,
        "movement_speed_limit": -1.0,
        "rotation_speed_limit": -1.0,
    }
    cases = {
        "inertia_zero": _run_center_case(
            "LocalInertiaZero",
            component_rotation_speed=90.0,
            local_inertia=0.0,
            local_movement_speed_limit=-1.0,
            local_rotation_speed_limit=-1.0,
            **common,
        ),
        "inertia_one": _run_center_case(
            "LocalInertiaOne",
            component_rotation_speed=90.0,
            local_inertia=1.0,
            local_movement_speed_limit=-1.0,
            local_rotation_speed_limit=-1.0,
            **common,
        ),
        "movement_limited": _run_center_case(
            "LocalMovementLimited",
            component_rotation_speed=0.0,
            local_inertia=1.0,
            local_movement_speed_limit=0.2,
            local_rotation_speed_limit=-1.0,
            **common,
        ),
        "rotation_limited": _run_center_case(
            "LocalRotationLimited",
            component_translation=False,
            component_rotation_speed=90.0,
            local_inertia=1.0,
            local_movement_speed_limit=-1.0,
            local_rotation_speed_limit=30.0,
            **common,
        ),
    }
    digest = hashlib.sha256()
    for setup_type in sorted(cases["inertia_zero"]):
        zero = cases["inertia_zero"][setup_type]
        one = cases["inertia_one"][setup_type]
        movement = cases["movement_limited"][setup_type]
        rotation = cases["rotation_limited"][setup_type]
        stable = np.logical_and(
            zero["update_count"] == 3.0,
            zero["skip_count"] == 0.0,
        )
        assert int(np.count_nonzero(stable)) >= 590
        np.testing.assert_allclose(
            zero["step_move_inertia_ratio"][stable],
            np.ones(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            one["step_move_inertia_ratio"][stable],
            np.zeros(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            zero["inertia_x"][stable],
            zero["step_x"][stable],
            rtol=0.0,
            atol=2.0e-6,
        )
        np.testing.assert_allclose(
            one["inertia_x"][stable],
            np.zeros(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=2.0e-6,
        )
        np.testing.assert_allclose(
            zero["step_rotation_inertia_ratio"][stable],
            np.ones(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            one["step_rotation_inertia_ratio"][stable],
            np.zeros(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            zero["inertia_rotation_degrees"][stable],
            zero["step_rotation_degrees"][stable],
            rtol=0.0,
            atol=3.0e-3,
        )
        np.testing.assert_allclose(
            one["inertia_rotation_degrees"][stable],
            np.zeros(int(np.count_nonzero(stable)), dtype=np.float32),
            rtol=0.0,
            atol=2.0e-3,
        )

        movement_stable = np.logical_and(
            movement["update_count"] == 3.0,
            movement["skip_count"] == 0.0,
        )
        input_speed = np.abs(movement["step_x"]) * 90.0
        movement_active = np.logical_and(movement_stable, input_speed > 0.2001)
        movement_inactive = np.logical_and(movement_stable, ~movement_active)
        assert int(np.count_nonzero(movement_active)) >= 390
        followed_speed = input_speed * (
            1.0 - movement["step_move_inertia_ratio"]
        )
        np.testing.assert_allclose(
            followed_speed[movement_active],
            np.full(
                int(np.count_nonzero(movement_active)),
                0.2,
                dtype=np.float32,
            ),
            rtol=0.0,
            atol=2.0e-4,
        )
        np.testing.assert_allclose(
            movement["step_move_inertia_ratio"][movement_inactive],
            np.zeros(int(np.count_nonzero(movement_inactive)), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            movement["inertia_x"][movement_stable],
            (
                movement["step_x"]
                * movement["step_move_inertia_ratio"]
            )[movement_stable],
            rtol=0.0,
            atol=2.0e-6,
        )

        rotation_stable = np.logical_and(
            rotation["update_count"] == 3.0,
            rotation["skip_count"] == 0.0,
        )
        input_rotation_speed = rotation["angular_velocity_degrees"]
        assert np.all(input_rotation_speed[rotation_stable] > 30.0)
        followed_rotation_speed = input_rotation_speed * (
            1.0 - rotation["step_rotation_inertia_ratio"]
        )
        np.testing.assert_allclose(
            followed_rotation_speed[rotation_stable],
            np.full(
                int(np.count_nonzero(rotation_stable)),
                30.0,
                dtype=np.float32,
            ),
            rtol=0.0,
            atol=2.0e-3,
        )
        for case_name in sorted(cases):
            for field, array in sorted(cases[case_name][setup_type].items()):
                assert np.all(np.isfinite(array))
                digest.update(setup_type.encode("ascii"))
                digest.update(case_name.encode("ascii"))
                digest.update(field.encode("ascii"))
                digest.update(array.tobytes())
    return digest.hexdigest()


def center_local_controls():
    first = _run_center_local_suite()
    second = _run_center_local_suite()
    assert second == first, (first, second)
    print(
        "[PASS] Center Local inertia/translation+rotation limits: "
        "3 setups x 4 cases x 2 deterministic runs x 600 frames"
    )


def _run_center_depth_suite():
    common = {
        "motion_space": "local",
        "component_rotation_speed": 0.0,
        "world_inertia": 1.0,
        "movement_inertia_smoothing": 0.0,
        "movement_speed_limit": -1.0,
        "rotation_speed_limit": -1.0,
        "local_inertia": 1.0,
        "local_movement_speed_limit": -1.0,
        "local_rotation_speed_limit": -1.0,
    }
    zero = _run_center_case("DepthZero", depth_inertia=0.0, **common)
    one = _run_center_case("DepthOne", depth_inertia=1.0, **common)
    digest = hashlib.sha256()
    for setup_type in sorted(zero):
        zero_values = zero[setup_type]
        one_values = one[setup_type]
        np.testing.assert_array_equal(
            zero_values["depths"], one_values["depths"]
        )
        np.testing.assert_array_equal(
            zero_values["move_mask"], one_values["move_mask"]
        )
        assert zero_values["particle_inertia_count"][0] > 0.0
        assert one_values["particle_inertia_count"][0] > 0.0
        depths = zero_values["depths"]
        move = zero_values["move_mask"].astype(bool)
        expected_ratio = 1.0 - depths[move] * depths[move]
        first_delta_x = (
            one_values["candidate_positions"][0, move, 0]
            - zero_values["candidate_positions"][0, move, 0]
        )
        correlation = float(np.corrcoef(expected_ratio, first_delta_x)[0, 1])
        assert correlation > 0.9, (setup_type, correlation)
        median_depth = float(np.median(depths[move]))
        near = np.logical_and(move, depths <= median_depth)
        far = np.logical_and(move, depths > median_depth)
        assert np.any(near) and np.any(far)
        all_first_delta_x = (
            one_values["candidate_positions"][0, :, 0]
            - zero_values["candidate_positions"][0, :, 0]
        )
        assert float(np.mean(all_first_delta_x[near])) > (
            float(np.mean(all_first_delta_x[far])) + 0.002
        ), (setup_type, all_first_delta_x, depths)
        for case_name, values in (("zero", zero_values), ("one", one_values)):
            for field, array in sorted(values.items()):
                assert np.all(np.isfinite(array))
                digest.update(setup_type.encode("ascii"))
                digest.update(case_name.encode("ascii"))
                digest.update(field.encode("ascii"))
                digest.update(array.tobytes())
    return digest.hexdigest()


def center_depth_controls():
    first = _run_center_depth_suite()
    second = _run_center_depth_suite()
    assert second == first, (first, second)
    print(
        "[PASS] Center depth inertia: "
        "3 setups x 2 cases x 2 deterministic runs x 600 frames"
    )


def _run_center_anchor_case(case_name, anchor_inertia):
    physics_blender.register()
    mesh = cloth = spring = driver = anchor = None
    world = world_types.PhysicsWorldCache()
    generation = 73
    try:
        mesh = _mesh_source(f"MC2Anchor{case_name}Mesh")
        cloth = _armature(f"MC2Anchor{case_name}Cloth", -0.3, 0.5)
        spring = _armature(f"MC2Anchor{case_name}Spring", 0.3, 1.5)
        driver = bpy.data.objects.new(f"MC2Anchor{case_name}Driver", None)
        anchor = bpy.data.objects.new(f"MC2Anchor{case_name}", None)
        bpy.context.scene.collection.objects.link(driver)
        bpy.context.scene.collection.objects.link(anchor)
        constraint = anchor.constraints.new("COPY_TRANSFORMS")
        constraint.target = driver
        sources = (mesh, cloth, spring)
        base_matrices = {
            source.name: source.matrix_world.copy() for source in sources
        }
        tasks = _tasks(
            mesh,
            cloth,
            spring,
            0.1,
            0,
            stabilization_time_after_reset=0.0,
            particle_speed_limit=100.0,
            anchor_inertia=anchor_inertia,
            world_inertia=1.0,
            movement_inertia_smoothing=0.0,
            movement_speed_limit=-1.0,
            rotation_speed_limit=-1.0,
            local_inertia=1.0,
            local_movement_speed_limit=-1.0,
            local_rotation_speed_limit=-1.0,
            depth_inertia=0.0,
            anchor_object=anchor,
        )
        stable_task_ids = tuple(task.task_id for task in tasks)
        initial_contexts = None
        observations = {
            task.setup_type: {
                "shift_x": [],
                "shift_rotation_degrees": [],
                "candidate_positions": [],
                "update_count": [],
                "skip_count": [],
            }
            for task in tasks
        }
        for frame in range(1, 601):
            translation = 0.004 * float(min(frame - 1, 300))
            rotation_degrees = 0.15 * float(max(frame - 301, 0))
            platform = (
                Matrix.Translation((translation, 0.0, 0.0))
                @ Matrix.Rotation(math.radians(rotation_degrees), 4, "Z")
            )
            driver.matrix_world = platform
            for source in sources:
                source.matrix_world = platform @ base_matrices[source.name]
            bpy.context.view_layer.update()
            _set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / 30.0
            world.frame_context.dt = 1.0 / 30.0
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(tasks),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            current_contexts = tuple(
                world.solver_slots[task.task_id].data["native_context"]
                for task in tasks
            )
            if frame == 1:
                initial_contexts = current_contexts
            else:
                assert current_contexts == initial_contexts
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated_anchor = anchor.evaluated_get(depsgraph)
            evaluated_position = tuple(
                float(evaluated_anchor.matrix_world[row][3]) for row in range(3)
            )
            for task in tasks:
                assert task.task_id in stable_task_ids
                assert task.anchor_object is anchor
                slot = world.solver_slots[task.task_id]
                candidate = _assert_candidate(slot)
                assert candidate.frame == frame
                center_state = slot.data["center_state"]
                assert center_state.anchor_identity == f"object:{int(anchor.as_pointer())}"
                np.testing.assert_allclose(
                    center_state.old_anchor_world_position,
                    evaluated_position,
                    rtol=0.0,
                    atol=2.0e-6,
                )
                values = observations[task.setup_type]
                values["candidate_positions"].append(
                    np.array(candidate.world_positions, dtype=np.float32, copy=True)
                )
                if frame == 1:
                    continue
                schedule = slot.data["frame_schedule"]
                values["update_count"].append(float(schedule.update_count))
                values["skip_count"].append(float(schedule.skip_count))
                shift = slot.data["center_frame_shift_result"]
                if shift is None:
                    values["shift_x"].append(0.0)
                    values["shift_rotation_degrees"].append(0.0)
                else:
                    values["shift_x"].append(
                        float(shift.frame_component_shift_vector[0])
                    )
                    quaternion = shift.frame_component_shift_rotation_xyzw
                    cosine = min(1.0, max(0.0, abs(float(quaternion[3]))))
                    values["shift_rotation_degrees"].append(
                        math.degrees(2.0 * math.acos(cosine))
                    )
            if frame == 299:
                assert debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_center": True},
                ) == 3

        for task in tasks:
            slot = world.solver_slots[task.task_id]
            info = slot.data["native_context"].inspect()
            assert info["debug_readback_count"] == 0
            if anchor_inertia < 1.0:
                assert info["center_frame_shift_count"] == 599
            else:
                assert info["center_frame_shift_count"] <= 3, (
                    case_name,
                    task.setup_type,
                    info["center_frame_shift_count"],
                )
            snapshot = slot.data["_debug_draw_snapshot"]
            assert snapshot["frame"] == 300
            frame_pose = snapshot["center"]["frame_pose"]
            assert frame_pose["anchor_identity"] == (
                f"object:{int(anchor.as_pointer())}"
            )
            assert snapshot["native"] == {}
        return {
            setup_type: {
                name: np.asarray(values, dtype=np.float32)
                for name, values in setup_values.items()
            }
            for setup_type, setup_values in observations.items()
        }
    finally:
        world.omni_cache_dispose(f"center_anchor_{case_name}")
        if mesh is not None and mesh.name in bpy.data.objects:
            proxy = mesh.hotools_mesh_collision.mc2_base_pose_proxy
            _remove_object(mesh)
            if proxy is not None and proxy.name in bpy.data.objects:
                _remove_object(proxy)
        for obj in (cloth, spring, anchor, driver):
            if obj is not None and obj.name in bpy.data.objects:
                _remove_object(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()


def _run_center_anchor_suite():
    follow = _run_center_anchor_case("Follow", 0.0)
    inertial = _run_center_anchor_case("Inertial", 1.0)
    digest = hashlib.sha256()
    for setup_type in sorted(follow):
        follow_values = follow[setup_type]
        inertial_values = inertial[setup_type]
        stable = np.logical_and(
            inertial_values["update_count"] == 3.0,
            inertial_values["skip_count"] == 0.0,
        )
        assert int(np.count_nonzero(stable)) >= 590
        np.testing.assert_allclose(
            follow_values["shift_x"][:299][stable[:299]],
            np.full((int(np.count_nonzero(stable[:299])),), 0.004, dtype=np.float32),
            rtol=0.0,
            atol=2.0e-6,
        )
        np.testing.assert_allclose(
            inertial_values["shift_x"][stable],
            np.zeros((int(np.count_nonzero(stable)),), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-7,
        )
        np.testing.assert_allclose(
            follow_values["shift_rotation_degrees"][300:][stable[300:]],
            np.full((int(np.count_nonzero(stable[300:])),), 0.15, dtype=np.float32),
            rtol=0.0,
            atol=1.0e-2,
        )
        np.testing.assert_allclose(
            inertial_values["shift_rotation_degrees"][stable],
            np.zeros((int(np.count_nonzero(stable)),), dtype=np.float32),
            rtol=0.0,
            atol=1.0e-7,
        )
        trajectory_delta = np.linalg.norm(
            follow_values["candidate_positions"]
            - inertial_values["candidate_positions"],
            axis=2,
        )
        assert float(np.max(trajectory_delta)) > 1.0e-4, (
            setup_type,
            trajectory_delta,
        )
        for case_name, values in (("follow", follow_values), ("inertial", inertial_values)):
            for field, array in sorted(values.items()):
                assert np.all(np.isfinite(array))
                digest.update(setup_type.encode("ascii"))
                digest.update(case_name.encode("ascii"))
                digest.update(field.encode("ascii"))
                digest.update(array.tobytes())
    return digest.hexdigest()


def center_anchor_controls():
    first = _run_center_anchor_suite()
    second = _run_center_anchor_suite()
    assert second == first, (first, second)
    print(
        "[PASS] Center Object Anchor: "
        "3 setups x 2 endpoints x 2 deterministic runs x 600 frames"
    )


def main():
    first = _run_scenario()
    second = _run_scenario()
    assert second == first, (first, second)
    print("[PASS] repeated 900-frame mixed scenario is deterministic")
    center_world_controls()
    center_local_controls()
    center_depth_controls()
    center_anchor_controls()
    print("MC2 mixed output soak: PASS")


if __name__ == "__main__":
    main()
