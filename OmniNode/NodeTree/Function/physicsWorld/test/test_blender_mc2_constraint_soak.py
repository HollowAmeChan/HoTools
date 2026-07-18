"""Long-run MC2 constraint and task-scope acceptance cases."""

from __future__ import annotations

import importlib
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
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
frame_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
center_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.center_state"
)
debug_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug"
)
solver_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


def _grid(name: str, x_offset: float = 0.0, *, size: int = 4):
    vertices = [
        (x_offset + x * 0.04, y * 0.04, 0.0)
        for y in range(size)
        for x in range(size)
    ]
    faces = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            b = a + 1
            c = a + size
            d = c + 1
            faces.extend(((a, b, d), (a, d, c)))
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, (), faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        vertex = vertices[loop.vertex_index]
        uv.data[loop.index].uv = (
            (vertex[0] - x_offset) / max((size - 1) * 0.04, 1.0e-6),
            vertex[1] / max((size - 1) * 0.04, 1.0e-6),
        )
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="Pin")
    pin.add(tuple(range(size)), 1.0, "REPLACE")
    props = obj.hotools_mesh_collision
    props.pin_enabled = True
    props.pin_vertex_group = pin.name
    props.collided_by_groups = 1
    return obj


def _task(obj, **profile_overrides):
    defaults = {
        "gravity": 0.0,
        "damping": 0.05,
        "stabilization_time_after_reset": 0.0,
        "collision_mode": 0,
        "self_collision_mode": 0,
    }
    defaults.update(profile_overrides)
    return specs.make_mc2_task_spec(
        "mesh_cloth",
        [obj],
        profile=parameters.make_mc2_particle_profile(**defaults),
    )


def _base_positions(obj):
    return np.asarray([tuple(vertex.co) for vertex in obj.data.vertices], dtype=np.float32)


def _frame_input(task, topology, frame, positions, *, generation):
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    return frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=generation,
        world_positions=positions,
        world_rotations_xyzw=rotations,
        source_world_linear=np.eye(3, dtype=np.float32),
        center_frame_pose=center_state.MC2CenterFramePoseSpec(
            frame=frame,
            generation=generation,
            component_identity=task.task_id,
            component_world_position=(0.0, 0.0, 0.0),
            component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            component_world_scale=(1.0, 1.0, 1.0),
        ),
    )


def _center_frame_input(task, topology, frame, positions, component_position, generation):
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    return frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=generation,
        world_positions=positions,
        world_rotations_xyzw=rotations,
        source_world_linear=np.eye(3, dtype=np.float32),
        center_frame_pose=center_state.MC2CenterFramePoseSpec(
            frame=frame,
            generation=generation,
            component_identity=task.task_id,
            component_world_position=component_position,
            component_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
            component_world_scale=(1.0, 1.0, 1.0),
            anchor_identity=f"anchor:{task.task_id}",
            anchor_world_position=(0.0, 0.0, 0.0),
            anchor_world_rotation_xyzw=(0.0, 0.0, 0.0, 1.0),
        ),
    )


def _set_world_frame(world, frame, previous, generation):
    context = world.frame_context
    context.previous_frame = previous
    context.frame = frame
    context.same_frame = previous == frame
    context.continuous = previous is not None and frame == previous + 1
    context.raw_dt = 1.0 / 90.0
    context.dt = 1.0 / 90.0
    context.generation = generation
    world.generation = generation


def _step(world, task_list, topology_by_id, frame, positions_by_id, generation):
    previous = frame - 1 if frame > 1 else None
    _set_world_frame(world, frame, previous, generation)
    inputs = {
        task.task_id: _frame_input(
            task,
            topology_by_id[task.task_id],
            frame,
            positions_by_id[task.task_id],
            generation=generation,
        )
        for task in task_list
    }
    returned, ready, status = solver_module.step_mc2(
        world,
        task_list,
        frame_inputs=inputs,
        dt=1.0 / 90.0,
    )
    assert returned is world and ready is True, status
    return inputs


def _candidate(world, task):
    candidate = world.solver_slots[task.task_id].data["result_candidate"]
    assert np.all(np.isfinite(candidate.world_positions))
    assert np.all(np.isfinite(candidate.world_rotations_xyzw))
    return candidate


def _auto_step(world, task, frame, generation):
    _set_world_frame(world, frame, frame - 1 if frame > 1 else None, generation)
    returned, ready, status = solver_module.step_mc2(
        world,
        [task],
        dt=1.0 / 90.0,
    )
    assert returned is world and ready is True, status
    return _candidate(world, task)


def _angle_restoration_rest_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 41
    task = _task(
        obj,
        angle_restoration_enabled=True,
        angle_restoration_stiffness=0.2,
        angle_limit_enabled=False,
    )
    stable_task_id = task.task_id
    base = _base_positions(obj)
    native_context = None
    try:
        for frame in range(1, 901):
            if frame == 451:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _task(
                    obj,
                    angle_restoration_enabled=True,
                    angle_restoration_stiffness=0.85,
                    angle_limit_enabled=False,
                )
                assert task.task_id == stable_task_id
            candidate = _auto_step(world, task, frame, generation)
            error = np.max(np.linalg.norm(candidate.world_positions - base, axis=1))
            assert error <= 2.0e-5, (frame, error)
            native_context = world.solver_slots[task.task_id].data["native_context"]
            if frame == 451:
                assert native_context is old_context
                assert native_context.inspect()["parameter_revision"] == old_revision + 1
        print("[PASS] 900-frame Angle Restoration zero-force rest/hot-update")
    finally:
        world.omni_cache_dispose("angle_restoration_soak")
        if native_context is not None:
            assert native_context.inspect()["released"] is True


def _motion_base_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 42
    task = _task(
        obj,
        angle_restoration_enabled=False,
        max_distance_enabled=True,
        max_distance=0.03,
        backstop_enabled=False,
        motion_stiffness=1.0,
    )
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    local = _base_positions(obj)
    last_positions = None
    try:
        for frame in range(1, 901):
            if frame == 451:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _task(
                    obj,
                    angle_restoration_enabled=False,
                    max_distance_enabled=True,
                    max_distance=0.03,
                    backstop_enabled=True,
                    backstop_radius=0.01,
                    backstop_distance=0.005,
                    normal_axis=2,
                    motion_stiffness=1.0,
                )
                assert task.task_id == stable_task_id
            translation = np.asarray(
                (0.06 * math.sin(frame * 0.031), 0.0, 0.0),
                dtype=np.float32,
            )
            positions = local + translation
            last_positions = positions
            _step(
                world,
                [task],
                {task.task_id: topology},
                frame,
                {task.task_id: positions},
                generation,
            )
            candidate = _candidate(world, task)
            distance = np.linalg.norm(candidate.world_positions - positions, axis=1)
            assert float(np.max(distance)) <= 0.031, (frame, float(np.max(distance)))
            if frame == 451:
                current_context = world.solver_slots[task.task_id].data["native_context"]
                assert current_context is old_context
                assert current_context.inspect()["parameter_revision"] == old_revision + 1
            if frame == 899:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_motion": True,
                        "show_motion_base": True,
                        "show_angle_restoration": False,
                        "show_self": False,
                    },
                )
        snapshot = world.solver_slots[task.task_id].data["_debug_draw_snapshot"]
        np.testing.assert_allclose(
            snapshot["motion"]["motion_base_positions"],
            last_positions,
            atol=1.0e-6,
        )
        assert snapshot["frame"] == 900
        assert snapshot["motion"]["use_backstop"] is True
        print("[PASS] 900-frame Motion BasePosition/max-distance boundary")
    finally:
        world.omni_cache_dispose("motion_base_soak")


def _task_collider_scope_soak(objects):
    world = world_types.PhysicsWorldCache()
    generation = 43
    tasks = tuple(
        _task(
            obj,
            angle_restoration_enabled=False,
            collision_mode=2,
            radius=0.01,
        )
        for obj in objects
    )
    topologies = {
        task.task_id: topology_module.build_mc2_topology_spec(task)
        for task in tasks
    }
    positions = {task.task_id: _base_positions(task.sources[0]) for task in tasks}
    try:
        for frame in range(1, 601):
            world.collider_snapshot = {
                "frame": frame,
                "colliders": (
                    {
                        "key": "scope-sphere",
                        "owner": objects[1],
                        "type": "SPHERE",
                        "primary_group": 1,
                        "center": (0.08, 0.08, -0.03),
                        "radius": 0.02,
                    },
                    {
                        "key": "scope-capsule",
                        "owner": objects[0],
                        "type": "CAPSULE",
                        "primary_group": 1,
                        "center": (0.28, 0.08, 0.0),
                        "segment_a": (0.28, 0.04, -0.02),
                        "segment_b": (0.28, 0.12, 0.02),
                        "radius": 0.01,
                    },
                ),
            }
            _step(world, tasks, topologies, frame, positions, generation)
            for task in tasks:
                _candidate(world, task)
            if frame == 599:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_collision": True, "show_self": False},
                )
        first = world.solver_slots[tasks[0].task_id].data["_debug_draw_snapshot"]
        second = world.solver_slots[tasks[1].task_id].data["_debug_draw_snapshot"]
        assert first["collision"]["colliders"]["keys"] == ("scope-sphere",)
        assert second["collision"]["colliders"]["keys"] == ("scope-capsule",)
        assert first["frame"] == second["frame"] == 600
        print("[PASS] 600-frame per-task external collider scope")
    finally:
        world.omni_cache_dispose("task_collider_scope_soak")


def _distance_tether_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 44
    task = _task(
        obj,
        gravity=7.0,
        gravity_direction=(0.0, 0.0, -1.0),
        angle_restoration_enabled=False,
        distance_stiffness=1.0,
        bending_stiffness=0.0,
    )
    stable_task_id = task.task_id
    base = _base_positions(obj)
    edges = np.asarray([tuple(edge.vertices) for edge in obj.data.edges], dtype=np.int32)
    rest_lengths = np.linalg.norm(base[edges[:, 1]] - base[edges[:, 0]], axis=1)
    native_context = None
    try:
        for frame in range(1, 901):
            if frame == 451:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = _task(
                    obj,
                    gravity=7.0,
                    gravity_direction=(0.0, 0.0, -1.0),
                    angle_restoration_enabled=False,
                    distance_stiffness=0.35,
                    bending_stiffness=0.0,
                )
                assert task.task_id == stable_task_id
            candidate = _auto_step(world, task, frame, generation)
            lengths = np.linalg.norm(
                candidate.world_positions[edges[:, 1]]
                - candidate.world_positions[edges[:, 0]],
                axis=1,
            )
            assert float(np.max(lengths / rest_lengths)) <= 1.55, (
                frame,
                float(np.max(lengths / rest_lengths)),
            )
            native_context = world.solver_slots[task.task_id].data["native_context"]
            if frame == 451:
                assert native_context is old_context
                assert native_context.inspect()["parameter_revision"] == old_revision + 1
        info = native_context.inspect()
        assert info["distance_solve_count"] > 0
        assert info["tether_solve_count"] > 0
        print("[PASS] 900-frame Distance/Tether stretch and hot-update")
    finally:
        world.omni_cache_dispose("distance_tether_soak")


def _run_bending_profile(obj, stiffness, generation):
    world = world_types.PhysicsWorldCache()
    task = _task(
        obj,
        gravity=8.0,
        gravity_direction=(0.0, 0.0, -1.0),
        angle_restoration_enabled=False,
        distance_stiffness=0.8,
        bending_stiffness=stiffness,
        collision_mode=2,
        radius=0.01,
    )
    try:
        candidate = None
        for frame in range(1, 901):
            world.collider_snapshot = {
                "frame": frame,
                "colliders": ({
                    "key": "bending-sphere",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": (0.06, 0.08, -0.035),
                    "radius": 0.045,
                },),
            }
            candidate = _auto_step(world, task, frame, generation)
        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        if stiffness > 0.0:
            assert info["bending_solve_count"] > 0
        else:
            assert info["bending_solve_count"] == 0
        positions = np.array(candidate.world_positions, copy=True)
        rows = positions[:, 2].reshape((4, 4))
        curvature = float(np.mean(np.abs(rows[:-2] - 2.0 * rows[1:-1] + rows[2:])))
        return curvature, positions
    finally:
        world.omni_cache_dispose("bending_profile_soak")


def _bending_soak(obj):
    soft_curvature, soft_positions = _run_bending_profile(obj, 0.0, 45)
    stiff_curvature, stiff_positions = _run_bending_profile(obj, 1.0, 46)
    assert np.all(np.isfinite(soft_positions))
    assert np.all(np.isfinite(stiff_positions))
    assert max(soft_curvature, stiff_curvature) < 0.02
    assert abs(stiff_curvature - soft_curvature) > 1.0e-3
    assert not np.allclose(soft_positions, stiff_positions, atol=1.0e-6)
    print("[PASS] 2x900-frame Triangle Bending response")


def _angle_limit_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 47
    limit_degrees = 30.0
    task = _task(
        obj,
        gravity=8.0,
        gravity_direction=(0.0, 0.0, -1.0),
        angle_restoration_enabled=False,
        angle_limit_enabled=True,
        angle_limit=limit_degrees,
        angle_limit_stiffness=1.0,
        distance_stiffness=0.8,
        bending_stiffness=0.0,
    )
    try:
        for frame in range(1, 1201):
            candidate = _auto_step(world, task, frame, generation)
            if frame == 1199:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_motion": False,
                        "show_motion_base": True,
                        "show_angle_restoration": False,
                        "show_self": False,
                    },
                )
        slot = world.solver_slots[task.task_id]
        native_context = slot.data["native_context"]
        motion = slot.data["_debug_draw_snapshot"]["motion"]
        target_positions = motion["angle_restoration_target_positions"]
        target_vectors = motion["angle_restoration_target_vectors"]
        valid = motion["angle_restoration_target_valid"]
        current = candidate.world_positions
        attributes = np.asarray(
            slot.data["mesh_static"].final_proxy.vertex_attributes,
            dtype=np.uint8,
        )
        angles = []
        for child, is_valid in enumerate(valid):
            if not is_valid:
                continue
            base_vector = target_vectors[child]
            parent_position = target_positions[child] - base_vector
            parent_distances = np.linalg.norm(current - parent_position, axis=1)
            parent = int(np.argmin(parent_distances))
            if parent_distances[parent] > 1.0e-5 or attributes[parent] & 0x02:
                continue
            current_vector = current[child] - parent_position
            base_length = float(np.linalg.norm(base_vector))
            current_length = float(np.linalg.norm(current_vector))
            if min(base_length, current_length) <= 1.0e-8:
                continue
            cosine = float(np.dot(base_vector, current_vector) / (base_length * current_length))
            angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        assert angles
        assert max(angles) <= limit_degrees + 5.0, max(angles)
        assert native_context.inspect()["angle_solve_count"] > 0
        print("[PASS] 1200-frame Angle Limit target bound")
    finally:
        world.omni_cache_dispose("angle_limit_soak")


def _center_keep_teleport_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 48
    task = _task(
        obj,
        gravity=0.0,
        angle_restoration_enabled=False,
        world_inertia=0.35,
        anchor_inertia=0.25,
        movement_inertia_smoothing=0.5,
        movement_speed_limit=2.0,
        rotation_speed_limit=360.0,
        teleport_mode=2,
        teleport_distance=0.25,
        teleport_rotation=45.0,
    )
    topology = topology_module.build_mc2_topology_spec(task)
    local = _base_positions(obj)
    keep_teleport_count = 0
    try:
        for frame in range(1, 1201):
            jump = 1.0 if frame >= 601 else 0.0
            component = (
                jump + 0.08 * math.sin(frame * 0.019),
                0.03 * math.sin(frame * 0.011),
                0.0,
            )
            positions = local + np.asarray(component, dtype=np.float32)
            _set_world_frame(
                world,
                frame,
                frame - 1 if frame > 1 else None,
                generation,
            )
            frame_input = _center_frame_input(
                task,
                topology,
                frame,
                positions,
                component,
                generation,
            )
            returned, ready, status = solver_module.step_mc2(
                world,
                [task],
                frame_inputs={task.task_id: frame_input},
                dt=1.0 / 90.0,
            )
            assert returned is world and ready is True, status
            _candidate(world, task)
            shift_result = world.solver_slots[task.task_id].data[
                "center_frame_shift_result"
            ]
            keep_teleport_count += int(
                bool(getattr(shift_result, "keep_teleport", False))
            )
            if frame == 1199:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={"show_center": True, "show_self": False},
                )
        slot = world.solver_slots[task.task_id]
        info = slot.data["native_context"].inspect()
        assert keep_teleport_count >= 1
        assert info["center_step_count"] > 0
        center = slot.data["_debug_draw_snapshot"]["center"]
        assert center["frame_sync"]["action"] == "updated"
        assert center["frame_shift"]["keep_teleport"] is False
        assert np.all(np.isfinite(center["source_world_linear"]))
        print("[PASS] 1200-frame Center inertia/Keep Teleport")
    finally:
        world.omni_cache_dispose("center_keep_teleport_soak")


def _self_interaction_soak(objects):
    world = world_types.PhysicsWorldCache()
    generation = 49

    def make_tasks(radius):
        return tuple(
            _task(
                obj,
                gravity=0.0,
                angle_restoration_enabled=False,
                radius=radius,
                self_collision_mode=2,
                self_collision_sync_mode=2,
            )
            for obj in objects
        )

    tasks = make_tasks(0.02)
    topologies = {
        task.task_id: topology_module.build_mc2_topology_spec(task)
        for task in tasks
    }
    positions = {task.task_id: _base_positions(task.sources[0]) for task in tasks}
    original_contexts = None
    try:
        for frame in range(1, 1801):
            if frame == 901:
                original_contexts = tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
                )
                old_revisions = tuple(
                    context.inspect()["parameter_revision"]
                    for context in original_contexts
                )
                tasks = make_tasks(0.03)
            _step(world, tasks, topologies, frame, positions, generation)
            for task in tasks:
                _candidate(world, task)
            if frame == 901:
                current_contexts = tuple(
                    world.solver_slots[task.task_id].data["native_context"]
                    for task in tasks
                )
                assert current_contexts == original_contexts
                assert tuple(
                    context.inspect()["parameter_revision"]
                    for context in current_contexts
                ) == tuple(revision + 1 for revision in old_revisions)
            if frame == 1799:
                debug_module.request_mc2_debug_capture(
                    world,
                    filters={
                        "show_self": True,
                        "show_self_primitives": True,
                        "show_self_candidates": True,
                        "show_self_contacts": True,
                    },
                )
        interaction = world.backend_resources["mc2_interaction_v0"]
        interaction_info = interaction.inspect()
        assert interaction_info["candidate_count"] > 0
        assert interaction_info["contact_count"] <= interaction_info["candidate_count"]
        assert interaction_info["primitive_count"] > 0
        for task in tasks:
            slot = world.solver_slots[task.task_id]
            info = slot.data["native_context"].inspect()
            assert info["self_contact_cache_count"] <= info["self_contact_candidate_count"]
            snapshot = slot.data["_debug_draw_snapshot"]
            assert snapshot["frame"] == 1800
            assert np.all(np.isfinite(snapshot["self_collision"]["thickness"]))
        interaction_snapshot = interaction.debug_draw_snapshot()
        assert interaction_snapshot["native"]["candidate_count"] > 0
        print("[PASS] 1800-frame cross-task self interaction/hot-update")
    finally:
        world.omni_cache_dispose("self_interaction_soak")


def _remove_object(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _remove_source_with_proxy(obj):
    proxy = obj.hotools_mesh_collision.mc2_base_pose_proxy
    _remove_object(obj)
    if proxy is not None and proxy.name in bpy.data.objects:
        _remove_object(proxy)


def main():
    physics_blender.register()
    objects = ()
    try:
        objects = (
            _grid("MC2ConstraintSoakA", 0.0),
            _grid("MC2ConstraintSoakB", 0.24),
            _grid("MC2ConstraintSelfA", 0.48),
            _grid("MC2ConstraintSelfB", 0.485),
        )
        _angle_restoration_rest_soak(objects[0])
        _motion_base_soak(objects[0])
        _task_collider_scope_soak(objects[:2])
        _distance_tether_soak(objects[0])
        _bending_soak(objects[0])
        _angle_limit_soak(objects[0])
        _center_keep_teleport_soak(objects[0])
        _self_interaction_soak(objects[2:])
    finally:
        for obj in objects:
            if obj.name in bpy.data.objects:
                _remove_source_with_proxy(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()
    print("MC2 constraint soak: PASS")


if __name__ == "__main__":
    main()
