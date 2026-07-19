"""Long-run MC2 constraint and task-scope acceptance cases."""

from __future__ import annotations

import hashlib
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
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
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


def _frame_input(
    task, topology, frame, positions, *, generation,
    anchor_rotation_xyzw=None,
):
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
            anchor_identity=(
                f"anchor:{task.task_id}"
                if anchor_rotation_xyzw is not None else ""
            ),
            anchor_world_position=(0.0, 0.0, 0.0),
            anchor_world_rotation_xyzw=(
                anchor_rotation_xyzw
                if anchor_rotation_xyzw is not None
                else (0.0, 0.0, 0.0, 1.0)
            ),
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


def _step(
    world,
    task_list,
    topology_by_id,
    frame,
    positions_by_id,
    generation,
    *,
    dt=1.0 / 90.0,
    paused=False,
):
    previous = frame - 1 if frame > 1 else None
    _set_world_frame(world, frame, previous, generation)
    world.frame_context.time_scale = 0.0 if paused else 1.0
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
        dt=dt,
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


def _run_angle_restoration_rest(obj):
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
    trajectory_digest = hashlib.sha256()
    max_rest_error = 0.0
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
            max_rest_error = max(max_rest_error, float(error))
            assert error <= 1.0e-7, (frame, error)
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(candidate.world_positions.tobytes())
            native_context = world.solver_slots[task.task_id].data["native_context"]
            if frame in (1, 900):
                snapshot = native_context.refresh_debug_draw_snapshot(
                    include_step_basic=True,
                    include_angle_restoration=True,
                )
                step_basic = snapshot["step_basic_positions"]
                targets = snapshot["angle_restoration_target_positions"]
                vectors = snapshot["angle_restoration_target_vectors"]
                valid = snapshot["angle_restoration_target_valid"].astype(bool)
                valid_indices = np.flatnonzero(valid)
                assert len(valid_indices) > 0
                parent_points = targets[valid_indices] - vectors[valid_indices]
                parent_distances = np.linalg.norm(
                    parent_points[:, None, :] - candidate.world_positions[None, :, :],
                    axis=2,
                )
                parent_indices = np.argmin(parent_distances, axis=1)
                matched_distances = parent_distances[
                    np.arange(len(valid_indices)), parent_indices
                ]
                assert float(np.max(matched_distances)) <= 1.0e-7
                assert np.all(parent_indices != valid_indices)
                expected_vectors = (
                    step_basic[valid_indices] - step_basic[parent_indices]
                )
                expected_targets = (
                    candidate.world_positions[parent_indices] + expected_vectors
                )
                np.testing.assert_allclose(
                    vectors[valid_indices], expected_vectors, rtol=0.0, atol=1.0e-7
                )
                np.testing.assert_allclose(
                    targets[valid_indices], expected_targets, rtol=0.0, atol=1.0e-7
                )
                trajectory_digest.update(vectors[valid_indices].tobytes())
                trajectory_digest.update(targets[valid_indices].tobytes())
            if frame == 451:
                assert native_context is old_context
                assert native_context.inspect()["parameter_revision"] == old_revision + 1
        print(
            "[INFO] Mesh Angle Restoration max zero-force drift: "
            f"{max_rest_error:.9f}m"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("angle_restoration_soak")
        if native_context is not None:
            assert native_context.inspect()["released"] is True


def _angle_restoration_rest_soak(obj):
    first = _run_angle_restoration_rest(obj)
    second = _run_angle_restoration_rest(obj)
    assert first == second, (first, second)
    print("[PASS] Mesh Angle Restoration: 2 deterministic x 900 frames")


def _angle_response_task(obj, *, attenuation):
    return _task(
        obj,
        gravity=0.0,
        gravity_direction=(0.0, 0.0, -1.0),
        damping=0.0,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=True,
        angle_restoration_stiffness=0.65,
        angle_restoration_velocity_attenuation=attenuation,
        angle_restoration_gravity_falloff=0.0,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        self_collision_mode=0,
        spring_enabled=False,
        teleport_mode=0,
    )


def _run_mesh_angle_response(obj, *, attenuation):
    world = world_types.PhysicsWorldCache()
    generation = 48
    base = _base_positions(obj)
    target = base.copy()
    height = max(float(np.max(base[:, 1])), 1.0e-6)
    depth = base[:, 1] / height
    target[:, 0] += 0.08 * depth * depth
    task = _angle_response_task(
        obj,
        attenuation=attenuation,
    )
    topology = topology_module.build_mc2_topology_spec(task)
    topology_by_id = {task.task_id: topology}
    responses = []
    movements = []
    trajectory_digest = hashlib.sha256()
    previous = None
    try:
        _step(
            world, [task], topology_by_id, 1,
            {task.task_id: base}, generation,
        )
        initial_context = world.solver_slots[task.task_id].data["native_context"]
        for frame in range(2, 602):
            _step(
                world, [task], topology_by_id, frame,
                {task.task_id: target}, generation,
            )
            slot = world.solver_slots[task.task_id]
            context = slot.data["native_context"]
            assert context is initial_context
            candidate = _candidate(world, task).world_positions.copy()
            responses.append(float(np.mean(np.linalg.norm(candidate - base, axis=1))))
            movements.append(
                0.0 if previous is None
                else float(np.mean(np.linalg.norm(candidate - previous, axis=1)))
            )
            trajectory_digest.update(candidate.tobytes())
            previous = candidate
        return {
            "responses": np.asarray(responses),
            "movements": np.asarray(movements),
            "digest": trajectory_digest.hexdigest(),
        }
    finally:
        world.omni_cache_dispose("mesh_angle_response")


def mesh_angle_restoration_response(obj):
    attenuation_low = _run_mesh_angle_response(
        obj, attenuation=0.0,
    )
    attenuation_high = _run_mesh_angle_response(
        obj, attenuation=1.0,
    )
    np.testing.assert_allclose(
        attenuation_low["responses"][0],
        attenuation_high["responses"][0],
        rtol=0.0,
        atol=1.0e-7,
    )
    assert (
        attenuation_low["responses"][1]
        >= attenuation_high["responses"][1] + 0.005
    )
    low_movement = float(np.sum(attenuation_low["movements"][1:30]))
    high_movement = float(np.sum(attenuation_high["movements"][1:30]))
    assert low_movement >= high_movement * 1.5
    print(
        "[INFO] Mesh Angle Restoration attenuation: "
        f"frame3 low/high={attenuation_low['responses'][1]:.9f}/"
        f"{attenuation_high['responses'][1]:.9f}; "
        f"movement30 low/high={low_movement:.9f}/{high_movement:.9f}"
    )


def _restoration_angular_errors(native_context, candidate):
    snapshot = native_context.refresh_debug_draw_snapshot(
        include_step_basic=False,
        include_angle_restoration=True,
    )
    targets = snapshot["angle_restoration_target_positions"]
    vectors = snapshot["angle_restoration_target_vectors"]
    valid = snapshot["angle_restoration_target_valid"]
    angles = []
    for child, is_valid in enumerate(valid):
        if not is_valid:
            continue
        target_vector = vectors[child]
        parent_position = targets[child] - target_vector
        current_vector = candidate.world_positions[child] - parent_position
        target_length = float(np.linalg.norm(target_vector))
        current_length = float(np.linalg.norm(current_vector))
        if min(target_length, current_length) <= 1.0e-8:
            continue
        cosine = float(np.dot(target_vector, current_vector) / (
            target_length * current_length
        ))
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
    assert angles
    return angles


def _run_mesh_angle_falloff(obj, falloff):
    world = world_types.PhysicsWorldCache()
    generation = 49
    def make_task(enabled, value):
        return _task(
            obj,
            gravity=4.0,
            gravity_direction=(0.0, 0.0, -1.0),
            damping=0.05,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=enabled,
            angle_restoration_stiffness=0.65,
            angle_restoration_velocity_attenuation=1.0,
            angle_restoration_gravity_falloff=value,
            angle_limit_enabled=False,
            max_distance_enabled=False,
            backstop_enabled=False,
            self_collision_mode=0,
            spring_enabled=False,
            teleport_mode=0,
        )

    task = make_task(False, 0.0)
    stable_task_id = task.task_id
    topology = topology_module.build_mc2_topology_spec(task)
    base = _base_positions(obj)
    context = None
    branch_angles = None
    branch_gravity_dot = None
    prefix_digest = hashlib.sha256()
    try:
        for frame in range(1, 602):
            if frame == 301:
                context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = context.inspect()["parameter_revision"]
                task = make_task(True, falloff)
                assert task.task_id == stable_task_id
            angle = math.pi * min(max((frame - 1) / 120.0, 0.0), 1.0)
            anchor_rotation = (
                math.sin(angle * 0.5), 0.0, 0.0, math.cos(angle * 0.5)
            )
            _set_world_frame(world, frame, frame - 1 if frame > 1 else None, generation)
            frame_input = _frame_input(
                task,
                topology,
                frame,
                base,
                generation=generation,
                anchor_rotation_xyzw=anchor_rotation,
            )
            returned, ready, status = solver_module.step_mc2(
                world,
                [task],
                frame_inputs={task.task_id: frame_input},
                dt=1.0 / 90.0,
            )
            assert returned is world and ready is True, status
            candidate = _candidate(world, task)
            if frame <= 300:
                prefix_digest.update(candidate.world_positions.tobytes())
            slot = world.solver_slots[task.task_id]
            if context is None:
                context = slot.data["native_context"]
            assert slot.data["native_context"] is context
            if frame == 301:
                info = context.inspect()
                assert info["parameter_revision"] == old_revision + 1
                assert info["center_result_ready"]
                branch_gravity_dot = context.read_center_step().gravity_dot
                branch_angles = _restoration_angular_errors(context, candidate)
        assert branch_angles and branch_gravity_dot is not None
        return {
            "angles": np.asarray(branch_angles),
            "gravity_dot": float(branch_gravity_dot),
            "prefix_digest": prefix_digest.hexdigest(),
        }
    finally:
        world.omni_cache_dispose("mesh_angle_falloff")


def mesh_angle_restoration_falloff(obj):
    low = _run_mesh_angle_falloff(obj, 0.0)
    high = _run_mesh_angle_falloff(obj, 1.0)
    assert low["prefix_digest"] == high["prefix_digest"]
    assert abs(low["gravity_dot"] - 0.5) <= 1.0e-6
    assert abs(high["gravity_dot"] - 0.5) <= 1.0e-6
    assert np.mean(high["angles"]) >= np.mean(low["angles"]) + 0.5
    assert np.percentile(high["angles"], 95) >= (
        np.percentile(low["angles"], 95) + 1.0
    )
    print(
        "[INFO] Mesh Angle Restoration gravity falloff: "
        f"gravity dot low/high={low['gravity_dot']:.9f}/"
        f"{high['gravity_dot']:.9f}; "
        f"angle mean low/high={np.mean(low['angles']):.6f}/"
        f"{np.mean(high['angles']):.6f}; p95 low/high="
        f"{np.percentile(low['angles'], 95):.6f}/"
        f"{np.percentile(high['angles'], 95):.6f}"
    )


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
    trajectory_digest = hashlib.sha256()
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
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
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
        trajectory_digest.update(np.asarray(
            snapshot["motion"]["motion_base_positions"]
        ).tobytes())
        print("[PASS] 900-frame Motion BasePosition/max-distance boundary")
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("motion_base_soak")


def motion_base_deterministic(obj):
    first = _motion_base_soak(obj)
    second = _motion_base_soak(obj)
    assert first == second, (first, second)
    print("[PASS] repeated Mesh Motion trajectory is deterministic")


def _run_task_collider_scope(objects):
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
    response_budgets = {}
    span_budgets = {}
    for task in tasks:
        base = positions[task.task_id]
        fixed = base[:4]
        max_root_distance = float(np.max(np.min(np.linalg.norm(
            base[:, None, :] - fixed[None, :, :],
            axis=2,
        ), axis=1)))
        base_span = float(np.max(np.linalg.norm(
            base[:, None, :] - base[None, :, :],
            axis=2,
        )))
        response_budgets[task.task_id] = max_root_distance * 2.0 + 0.05
        span_budgets[task.task_id] = base_span * 1.5 + 0.02
    trajectory_digest = hashlib.sha256()
    max_responses = {task.task_id: 0.0 for task in tasks}
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
                        "center": (0.08, 0.08, -0.02),
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
                        "radius": 0.012,
                    },
                ),
            }
            _step(world, tasks, topologies, frame, positions, generation)
            for task in tasks:
                candidate = _candidate(world, task)
                trajectory_digest.update(task.task_id.encode("utf-8"))
                trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
                trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
                trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
                response = float(np.max(np.linalg.norm(
                    candidate.world_positions - positions[task.task_id],
                    axis=1,
                )))
                max_responses[task.task_id] = max(max_responses[task.task_id], response)
                assert response <= response_budgets[task.task_id], (
                    task.task_id,
                    frame,
                    response,
                    response_budgets[task.task_id],
                )
                candidate_span = float(np.max(np.linalg.norm(
                    candidate.world_positions[:, None, :]
                    - candidate.world_positions[None, :, :],
                    axis=2,
                )))
                assert candidate_span <= span_budgets[task.task_id], (
                    task.task_id,
                    frame,
                    candidate_span,
                    span_budgets[task.task_id],
                )
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
        assert all(value > 1.0e-4 for value in max_responses.values()), max_responses
        trajectory_digest.update("\0".join(
            first["collision"]["colliders"]["keys"]
            + second["collision"]["colliders"]["keys"]
        ).encode("utf-8"))
        print("[PASS] 600-frame per-task external collider scope")
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("task_collider_scope_soak")


def _task_collider_scope_soak(objects):
    first = _run_task_collider_scope(objects)
    second = _run_task_collider_scope(objects)
    assert first == second, (first, second)
    print("[PASS] repeated Mesh external-collision trajectory is deterministic")


def _run_mesh_friction(obj, friction):
    world = world_types.PhysicsWorldCache()
    generation = 50
    task = _task(
        obj,
        gravity=0.0,
        damping=0.02,
        angle_restoration_enabled=False,
        bending_stiffness=0.0,
        collision_mode=1,
        collision_friction=friction,
        radius=0.01,
    )
    topology = topology_module.build_mc2_topology_spec(task)
    base = _base_positions(obj)
    lags = []
    try:
        for frame in range(1, 601):
            translation = np.asarray((frame * 0.0002, 0.0, 0.0), dtype=np.float32)
            positions = base + translation
            world.collider_snapshot = {
                "frame": frame,
                "colliders": ({
                    "key": "mesh-friction-plane",
                    "type": "PLANE",
                    "primary_group": 1,
                    "center": (0.0, 0.0, 0.0),
                    "normal": (0.0, 0.0, 1.0),
                },),
            }
            _step(
                world,
                [task],
                {task.task_id: topology},
                frame,
                {task.task_id: positions},
                generation,
            )
            candidate = _candidate(world, task)
            lag = float(np.mean(
                positions[4:, 0] - candidate.world_positions[4:, 0]
            ))
            assert abs(lag) < 0.1, (friction, frame, lag)
            if frame > 300:
                lags.append(lag)
        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        assert info["point_collision_solve_count"] > 0
        assert info["collider_count"] == 1
        return float(np.mean(lags)), float(lags[-1])
    finally:
        world.omni_cache_dispose("mesh_friction_soak")


def mesh_friction_response(obj):
    low_mean, low_final = _run_mesh_friction(obj, 0.0)
    high_mean, high_final = _run_mesh_friction(obj, 0.5)
    assert high_mean > low_mean + 0.005, (low_mean, high_mean)
    assert high_final > low_final + 0.005, (low_final, high_final)
    print(
        "[PASS] Mesh friction ordered tangential lag: "
        f"mean {low_mean:.6f}m -> {high_mean:.6f}m"
    )


def _run_mesh_distance_profile(obj):
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
    attributes = None
    trajectory_digest = hashlib.sha256()
    max_edge_ratio = 0.0
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
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            slot = world.solver_slots[task.task_id]
            if attributes is None:
                attributes = np.asarray(
                    slot.data["mesh_static"].final_proxy.vertex_attributes,
                    dtype=np.uint8,
                )
                assert np.any(attributes & 0x01)
            fixed = (attributes & 0x01) != 0
            np.testing.assert_allclose(
                candidate.world_positions[fixed],
                base[fixed],
                atol=1.0e-6,
            )
            lengths = np.linalg.norm(
                candidate.world_positions[edges[:, 1]]
                - candidate.world_positions[edges[:, 0]],
                axis=1,
            )
            edge_ratio = float(np.max(lengths / rest_lengths))
            max_edge_ratio = max(max_edge_ratio, edge_ratio)
            assert edge_ratio <= 1.55, (
                frame,
                edge_ratio,
            )
            native_context = slot.data["native_context"]
            if frame == 451:
                assert native_context is old_context
                assert native_context.inspect()["parameter_revision"] == old_revision + 1
        info = native_context.inspect()
        assert info["distance_solve_count"] > 0
        assert info["tether_solve_count"] > 0
        print(
            "[PASS] 900-frame Distance profile/hot-update: "
            f"max edge ratio {max_edge_ratio:.6f}"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("mesh_distance_profile_soak")


def _run_mesh_tether_branch(obj, *, direction, compression, generation):
    world = world_types.PhysicsWorldCache()
    task = _task(
        obj,
        gravity=0.5,
        gravity_direction=direction,
        damping=0.5,
        tether_compression=compression,
        angle_restoration_enabled=False,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
    )
    base = _base_positions(obj)
    roots = step_basic = attributes = None
    trajectory_digest = hashlib.sha256()
    ratios = []
    try:
        for frame in range(1, 601):
            candidate = _auto_step(world, task, frame, generation)
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            slot = world.solver_slots[task.task_id]
            if roots is None:
                native_debug = slot.data["native_context"].refresh_debug_draw_snapshot(
                    include_step_basic=True,
                    include_motion_base=False,
                    include_dynamics=False,
                    include_distance_tether=True,
                    include_bending=False,
                )
                roots = np.asarray(
                    native_debug["distance_tether"]["baseline_roots"],
                    dtype=np.int32,
                )
                step_basic = np.asarray(
                    native_debug["step_basic_positions"],
                    dtype=np.float32,
                )
                attributes = np.asarray(
                    slot.data["mesh_static"].final_proxy.vertex_attributes,
                    dtype=np.uint8,
                )
            fixed = (attributes & 0x01) != 0
            np.testing.assert_allclose(
                candidate.world_positions[fixed], base[fixed], atol=1.0e-6
            )
            for particle, root in enumerate(roots):
                if root < 0 or root == particle:
                    continue
                rest = float(np.linalg.norm(step_basic[particle] - step_basic[root]))
                if rest <= 1.0e-8:
                    continue
                ratio = float(np.linalg.norm(
                    candidate.world_positions[particle]
                    - candidate.world_positions[root]
                )) / rest
                assert 0.15 <= ratio <= 1.35, (frame, particle, ratio)
                ratios.append(ratio)
        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        assert info["tether_solve_count"] > 0
        return min(ratios), max(ratios), trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("mesh_tether_branch_soak")


def _run_distance_tether_suite(obj):
    distance_digest = _run_mesh_distance_profile(obj)
    stretch_min, stretch_max, stretch_digest = _run_mesh_tether_branch(
        obj,
        direction=(0.0, 1.0, 0.0),
        compression=0.4,
        generation=45,
    )
    compression_min, compression_max, compression_digest = _run_mesh_tether_branch(
        obj,
        direction=(0.0, -1.0, 0.0),
        compression=0.65,
        generation=46,
    )
    assert stretch_max > 1.03, stretch_max
    assert compression_min < 0.35, compression_min
    print(
        "[PASS] Mesh Tether branches: "
        f"stretch {stretch_min:.6f}..{stretch_max:.6f}, "
        f"compression {compression_min:.6f}..{compression_max:.6f}"
    )
    digest = hashlib.sha256()
    for value in (distance_digest, stretch_digest, compression_digest):
        digest.update(value.encode("ascii"))
    return digest.hexdigest()


def _distance_tether_soak(obj):
    first = _run_distance_tether_suite(obj)
    second = _run_distance_tether_suite(obj)
    assert first == second, (first, second)
    print("[PASS] repeated Mesh Distance/Tether trajectory is deterministic")


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
    trajectory_digest = hashlib.sha256()
    fixed_indices = None
    fixed_positions = None
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
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            if fixed_indices is None:
                attributes = world.solver_slots[task.task_id].data[
                    "mesh_static"
                ].final_proxy.vertex_attributes
                fixed_indices = np.flatnonzero(attributes & 0x01)
                assert len(fixed_indices) > 0
                fixed_positions = np.array(
                    candidate.world_positions[fixed_indices], copy=True
                )
            np.testing.assert_allclose(
                candidate.world_positions[fixed_indices],
                fixed_positions,
                rtol=0.0,
                atol=1.0e-7,
            )
        info = world.solver_slots[task.task_id].data["native_context"].inspect()
        if stiffness > 0.0:
            assert info["bending_solve_count"] > 0
        else:
            assert info["bending_solve_count"] == 0
        positions = np.array(candidate.world_positions, copy=True)
        rows = positions[:, 2].reshape((4, 4))
        curvature = float(np.mean(np.abs(rows[:-2] - 2.0 * rows[1:-1] + rows[2:])))
        return curvature, positions, trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("bending_profile_soak")


def _run_bending_suite(obj):
    soft_curvature, soft_positions, soft_digest = _run_bending_profile(obj, 0.0, 45)
    stiff_curvature, stiff_positions, stiff_digest = _run_bending_profile(obj, 1.0, 46)
    assert np.all(np.isfinite(soft_positions))
    assert np.all(np.isfinite(stiff_positions))
    assert max(soft_curvature, stiff_curvature) < 0.02
    assert abs(stiff_curvature - soft_curvature) > 1.0e-3
    assert not np.allclose(soft_positions, stiff_positions, atol=1.0e-6)
    digest = hashlib.sha256()
    digest.update(soft_digest.encode("ascii"))
    digest.update(stiff_digest.encode("ascii"))
    return digest.hexdigest()


def _bending_soak(obj):
    first = _run_bending_suite(obj)
    second = _run_bending_suite(obj)
    assert first == second, (first, second)
    print("[PASS] Mesh Triangle Bending: zero/strong x 2 deterministic x 900")


def _run_angle_limit_soak(obj):
    world = world_types.PhysicsWorldCache()
    generation = 47
    final_limit_degrees = 20.0

    def make_task(enabled, limit):
        return _task(
            obj,
            gravity=8.0,
            gravity_direction=(0.0, 0.0, -1.0),
            angle_restoration_enabled=False,
            angle_limit_enabled=enabled,
            angle_limit=limit,
            angle_limit_stiffness=1.0,
            distance_stiffness=0.8,
            bending_stiffness=0.0,
        )

    task = make_task(False, 30.0)
    stable_task_id = task.task_id
    trajectory_digest = hashlib.sha256()
    disabled_count = None
    try:
        for frame in range(1, 1201):
            if frame == 301:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(True, 30.0)
                assert task.task_id == stable_task_id
            elif frame == 601:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(False, 30.0)
                assert task.task_id == stable_task_id
            elif frame == 901:
                old_context = world.solver_slots[task.task_id].data["native_context"]
                old_revision = old_context.inspect()["parameter_revision"]
                task = make_task(True, final_limit_degrees)
                assert task.task_id == stable_task_id
            candidate = _auto_step(world, task, frame, generation)
            trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
            trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
            info = world.solver_slots[task.task_id].data["native_context"].inspect()
            if frame == 300:
                assert info["angle_solve_count"] == 0
            elif frame in (301, 601, 901):
                assert world.solver_slots[task.task_id].data["native_context"] is old_context
                assert info["parameter_revision"] == old_revision + 1
                if frame == 601:
                    disabled_count = info["angle_solve_count"]
            elif 601 < frame <= 900:
                assert info["angle_solve_count"] == disabled_count
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
        assert max(angles) <= final_limit_degrees + 6.0, max(angles)
        assert native_context.inspect()["angle_solve_count"] > 0
        trajectory_digest.update(np.asarray(angles, dtype=np.float32).tobytes())
        print(
            "[PASS] 1200-frame Angle Limit transition/target bound: "
            f"max {max(angles):.6f}deg"
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("angle_limit_soak")


def _angle_limit_soak(obj):
    first = _run_angle_limit_soak(obj)
    second = _run_angle_limit_soak(obj)
    assert first == second, (first, second)
    print("[PASS] repeated Mesh Angle Limit trajectory is deterministic")


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


def _run_self_interaction_soak(objects):
    world = world_types.PhysicsWorldCache()
    generation = 49

    def make_tasks(radius, teleport_mode=0):
        result = []
        for index, obj in enumerate(objects):
            profile = parameters.make_mc2_particle_profile(
                gravity=0.0,
                angle_restoration_enabled=False,
                radius=radius,
                self_collision_mode=2,
                self_collision_sync_mode=2,
                cloth_mass=0.25 + index * 0.5,
                teleport_mode=teleport_mode,
                teleport_distance=0.5,
                teleport_rotation=180.0,
            )
            product_tasks, _names = nodes.physicsMC2MeshClothTask(
                [obj], profile=profile
            )
            assert len(product_tasks) == 1
            result.append(product_tasks[0])
        return tuple(result)

    tasks = make_tasks(0.02)
    topologies = {
        task.task_id: topology_module.build_mc2_topology_spec(task)
        for task in tasks
    }
    positions = {task.task_id: _base_positions(task.sources[0]) for task in tasks}
    original_contexts = None
    pre_teleport_interaction = None
    teleport_frame = None
    interaction_invalidated = False
    trajectory_digest = hashlib.sha256()
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
            elif teleport_frame is not None and frame == teleport_frame:
                old_revisions = tuple(
                    world.solver_slots[task.task_id]
                    .data["native_context"]
                    .inspect()["parameter_revision"]
                    for task in tasks
                )
                tasks = make_tasks(0.03, teleport_mode=1)
                moved = np.array(positions[tasks[0].task_id], copy=True)
                moved[(3, 7, 11, 15), 0] += 0.6
                positions[tasks[0].task_id] = moved
            _step(
                world,
                tasks,
                topologies,
                frame,
                positions,
                generation,
                dt=(
                    1.0e-6
                    if teleport_frame is not None and frame == teleport_frame
                    else 1.0 / 90.0
                ),
                paused=(teleport_frame is not None and frame == teleport_frame),
            )
            for task in tasks:
                candidate = _candidate(world, task)
                trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
                trajectory_digest.update(task.task_id.encode("ascii"))
                trajectory_digest.update(np.asarray(candidate.world_positions).tobytes())
                trajectory_digest.update(np.asarray(candidate.world_rotations_xyzw).tobytes())
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
            if teleport_frame is not None and frame == teleport_frame:
                for index, task in enumerate(tasks):
                    slot = world.solver_slots[task.task_id]
                    info = slot.data["native_context"].inspect()
                    assert info["parameter_revision"] == old_revisions[index] + 1
                    teleport = slot.data["particle_teleport_result"]
                    if index == 0:
                        assert teleport["mode"] == 1
                        assert 0 < teleport["trigger_count"] < topologies[
                            task.task_id
                        ].particle_count
                    else:
                        assert teleport["applied"] is False
                    assert slot.data["frame_schedule"].update_count == 0
                invalidated = world.backend_resources[
                    "mc2_interaction_v0"
                ].inspect()
                assert invalidated["invalidation_count"] == (
                    pre_teleport_interaction["invalidation_count"] + 1
                )
                assert invalidated["participant_count"] == 0
                assert invalidated["pair_count"] == 0
                assert invalidated["candidate_count"] == 0
                assert invalidated["contact_count"] == 0
                assert invalidated["intersect_record_count"] == 0
                interaction_invalidated = True
            elif teleport_frame is not None and frame == teleport_frame + 1:
                rebuilt = world.backend_resources["mc2_interaction_v0"].inspect()
                assert rebuilt["participant_count"] == 2
                assert rebuilt["pair_count"] == 1
                assert rebuilt["candidate_count"] > 0
            if teleport_frame is None and 1000 <= frame <= 1700:
                interaction_info = world.backend_resources[
                    "mc2_interaction_v0"
                ].inspect()
                if all(
                    interaction_info[name] > 0
                    for name in (
                        "candidate_count",
                        "contact_count",
                        "intersect_record_count",
                    )
                ):
                    pre_teleport_interaction = dict(interaction_info)
                    teleport_frame = frame + 1
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
        assert interaction_info["participant_count"] == 2
        assert interaction_info["pair_count"] == 1, interaction_info
        assert interaction_info["candidate_count"] > 0
        assert interaction_info["contact_count"] <= interaction_info["candidate_count"]
        assert interaction_info["primitive_count"] > 0
        assert pre_teleport_interaction is not None
        assert teleport_frame is not None
        assert interaction_invalidated is True
        for task in tasks:
            slot = world.solver_slots[task.task_id]
            info = slot.data["native_context"].inspect()
            assert info["self_contact_cache_count"] <= info["self_contact_candidate_count"]
            snapshot = slot.data["_debug_draw_snapshot"]
            assert snapshot["frame"] == 1800
            assert len(snapshot["self_collision"]["particle_indices"]) > 0
            runtime_thickness = slot.data["effective_parameters"].debug_dict()[
                "curve_values"
            ]["self_collision_thickness"]
            np.testing.assert_allclose(
                runtime_thickness,
                0.03 * 0.25,
                rtol=0.0,
                atol=1.0e-7,
            )
        interaction_snapshot = interaction.debug_draw_snapshot()
        assert interaction_snapshot["native"]["candidate_count"] > 0
        trajectory_digest.update(
            np.asarray(
                (
                    interaction_info["participant_count"],
                    interaction_info["pair_count"],
                    interaction_info["candidate_count"],
                    interaction_info["contact_count"],
                ),
                dtype=np.int64,
            ).tobytes()
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("self_interaction_soak")


def _self_interaction_soak(objects):
    first = _run_self_interaction_soak(objects)
    second = _run_self_interaction_soak(objects)
    assert first == second, (first, second)
    print("[PASS] Mesh cross-task self: 2 deterministic x 1800 frames")


def _run_mesh_gravity_axes_falloff():
    world = world_types.PhysicsWorldCache()
    world.generation = 93
    directions = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    objects = tuple(
        _grid(f"MC2GravityAxis{index}", index * 0.25)
        for index in range(3)
    ) + (
        _grid("MC2GravityFalloff0", 0.8),
        _grid("MC2GravityFalloff1", 1.05),
    )
    for obj in objects[:3]:
        obj.hotools_mesh_collision.pin_enabled = False

    def profile(direction, falloff):
        return parameters.make_mc2_particle_profile(
            gravity=0.6,
            gravity_direction=direction,
            gravity_falloff=falloff,
            damping=0.5,
            stabilization_time_after_reset=0.0,
            distance_stiffness=0.0,
            bending_stiffness=0.0,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            collision_mode=0,
            self_collision_mode=0,
        )

    profiles = tuple(profile(direction, 0.0) for direction in directions) + (
        profile((0.0, 0.0, -1.0), 0.0),
        profile((0.0, 0.0, -1.0), 1.0),
    )
    tasks = tuple(
        nodes.physicsMC2MeshClothTask([obj], profile=item)[0][0]
        for obj, item in zip(objects, profiles)
    )
    base_positions = {
        task.task_id: _base_positions(obj)
        for task, obj in zip(tasks, objects)
    }
    axis_velocity_directions = {}
    trajectory_digest = hashlib.sha256()
    try:
        for frame in range(1, 601):
            _set_world_frame(
                world,
                frame,
                frame - 1 if frame > 1 else None,
                world.generation,
            )
            returned, ready, status = nodes.physicsMC2Step(world, list(tasks))
            assert returned is world and ready is True, status
            for task_index, task in enumerate(tasks):
                candidate = _candidate(world, task)
                trajectory_digest.update(
                    np.asarray(task_index, dtype=np.int32).tobytes()
                )
                trajectory_digest.update(np.asarray(frame, dtype=np.int32).tobytes())
                trajectory_digest.update(candidate.world_positions.tobytes())
                if frame == 2 and task in tasks[:3]:
                    dynamics = world.solver_slots[task.task_id].data[
                        "native_context"
                    ].refresh_debug_draw_snapshot(
                        include_step_basic=False,
                        include_dynamics=True,
                    )["dynamics"]["velocities"]
                    mean_velocity = np.mean(dynamics, axis=0)
                    speed = float(np.linalg.norm(mean_velocity))
                    assert speed > 1.0e-6
                    axis_velocity_directions[task.task_id] = mean_velocity / speed

        for task, direction in zip(tasks[:3], directions):
            candidate = _candidate(world, task)
            displacement = np.mean(
                candidate.world_positions - base_positions[task.task_id],
                axis=0,
            )
            direction_array = np.asarray(direction, dtype=np.float32)
            projection = float(np.dot(displacement, direction_array))
            orthogonal = float(np.linalg.norm(
                displacement - direction_array * projection
            ))
            assert projection > 0.1, (direction, projection)
            assert orthogonal <= 1.0e-5, (direction, orthogonal)
            np.testing.assert_allclose(
                axis_velocity_directions[task.task_id],
                direction_array,
                rtol=0.0,
                atol=1.0e-6,
            )

        falloff_zero, falloff_one = tasks[3:]
        zero_slot = world.solver_slots[falloff_zero.task_id]
        one_slot = world.solver_slots[falloff_one.task_id]
        np.testing.assert_allclose(
            zero_slot.data["center_step_result"].gravity_ratio,
            1.0,
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            one_slot.data["center_step_result"].gravity_ratio,
            0.0,
            rtol=0.0,
            atol=1.0e-6,
        )
        zero_displacement = float(np.max(np.linalg.norm(
            _candidate(world, falloff_zero).world_positions
            - base_positions[falloff_zero.task_id],
            axis=1,
        )))
        one_displacement = float(np.max(np.linalg.norm(
            _candidate(world, falloff_one).world_positions
            - base_positions[falloff_one.task_id],
            axis=1,
        )))
        assert zero_displacement > one_displacement + 0.05, (
            zero_displacement,
            one_displacement,
        )
        return trajectory_digest.hexdigest()
    finally:
        world.omni_cache_dispose("mesh_gravity_axes_falloff_soak")
        for obj in objects:
            if obj.name in bpy.data.objects:
                _remove_source_with_proxy(obj)


def mesh_gravity_axes_falloff():
    first = _run_mesh_gravity_axes_falloff()
    second = _run_mesh_gravity_axes_falloff()
    assert first == second, (first, second)
    print("[PASS] Mesh gravity XYZ/falloff: 2 deterministic x 600 frames")


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
        mesh_angle_restoration_response(objects[0])
        mesh_angle_restoration_falloff(objects[0])
        motion_base_deterministic(objects[0])
        _task_collider_scope_soak(objects[:2])
        mesh_friction_response(objects[0])
        _distance_tether_soak(objects[0])
        _bending_soak(objects[0])
        _angle_limit_soak(objects[0])
        _center_keep_teleport_soak(objects[0])
        _self_interaction_soak(objects[2:])
        mesh_gravity_axes_falloff()
    finally:
        for obj in objects:
            if obj.name in bpy.data.objects:
                _remove_source_with_proxy(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()
    print("MC2 constraint soak: PASS")


if __name__ == "__main__":
    main()
