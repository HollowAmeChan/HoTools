"""MC2 V1-R mixed three-setup lifecycle and performance soak."""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
import time
import types

import bpy
import numpy as np


HERE = os.path.dirname(os.path.abspath(__file__))
PHYSICS_WORLD = os.path.dirname(HERE)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = os.path.dirname(NODETREE)
HOTOOLS = os.path.dirname(OMNINODE)

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)


BASELINE_PATH = os.path.join(PHYSICS_WORLD, "mc2", "test", "soak_baseline_v1.json")


def _make_mesh_armature():
    data = bpy.data.armatures.new("MC2_SoakMeshArmatureData")
    obj = bpy.data.objects.new("MC2_SoakMeshArmature", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("MeshDriver")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _make_mesh_source(armature):
    mesh = bpy.data.meshes.new("MC2_SoakMeshData")
    mesh.from_pydata(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)),
        (),
        ((0, 1, 2), (0, 2, 3)),
    )
    uv_layer = mesh.uv_layers.new(name="UVMap")
    uv_by_vertex = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = uv_by_vertex[loop.vertex_index]
    source = bpy.data.objects.new("MC2_SoakMesh", mesh)
    bpy.context.scene.collection.objects.link(source)
    deform = source.vertex_groups.new(name="MeshDriver")
    deform.add((0, 1, 2, 3), 1.0, "REPLACE")
    pin = source.vertex_groups.new(name="MC2Pin")
    pin.add((0,), 1.0, "REPLACE")
    modifier = source.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    return source, pin


def _make_chain(name, x_offset):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.location.x = x_offset
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    parent = None
    for index in range(4):
        bone = data.edit_bones.new("Root" if index == 0 else f"Bone{index}")
        bone.head = (0.0, float(index), 0.1 * index)
        bone.tail = (0.15 * index, float(index + 1), 0.1 * (index + 1))
        bone.parent = parent
        bone.use_connect = parent is not None
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _remove_object(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is None or data.users != 0:
        return
    if isinstance(data, bpy.types.Mesh):
        bpy.data.meshes.remove(data)
    elif isinstance(data, bpy.types.Armature):
        bpy.data.armatures.remove(data)


def _set_frame_context(world, frame, previous, generation, *, reset=False):
    context = world.frame_context
    context.previous_frame = previous
    context.frame = frame
    context.continuous = previous is not None and frame == previous + 1
    context.same_frame = previous == frame
    context.reset_requested = bool(reset)
    context.restart_required = previous is None or bool(reset)
    context.raw_dt = 1.0 / 60.0
    context.dt = 1.0 / 60.0
    context.time_scale = 1.0
    context.substeps = 1
    context.generation = generation


def _tasks(mesh_source, cloth_armature, spring_armature, damping):
    mesh_profile = parameters.make_mc2_particle_profile(
        damping=damping,
        gravity=9.0,
        self_collision_mode=2,
        self_collision_thickness=0.01,
        collision_mode=2,
    )
    mesh_task = specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH,
        [mesh_source],
        profile=mesh_profile,
    )
    cloth_task = specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_CLOTH,
        [{"armature": cloth_armature, "root_bone": "Root"}],
    )
    spring_task = specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_SPRING,
        [{"armature": spring_armature, "root_bone": "Root"}],
        setup_options=parameters.make_mc2_setup_options(
            mc2_names.MC2_SETUP_BONE_SPRING,
            collided_by_groups=1,
        ),
    )
    return [mesh_task, cloth_task, spring_task]


def main():
    with open(BASELINE_PATH, "r", encoding="utf-8") as handle:
        baseline = json.load(handle)
    assert baseline["schema"] == "mc2_v1_soak_baseline_v0"
    scenario = baseline["scenario"]
    required = baseline["required_totals"]
    ceilings = baseline["performance_ceiling_ms"]

    physics_blender.register()
    mesh_armature = mesh_source = base_object = None
    cloth_armature = spring_armature = None
    worlds = []
    counters = {
        "parameter_hot_updates": 0,
        "static_rebuilds": 0,
        "explicit_resets": 0,
        "same_frame_reuses": 0,
        "released_contexts": 0,
    }
    timings = []
    try:
        mesh_armature = _make_mesh_armature()
        mesh_source, pin_group = _make_mesh_source(mesh_armature)
        cloth_armature = _make_chain("MC2_SoakBoneCloth", -2.0)
        spring_armature = _make_chain("MC2_SoakBoneSpring", 2.0)
        gn_offset.write_gn_local_offsets(
            mesh_source, np.zeros((len(mesh_source.data.vertices), 3), dtype=np.float32)
        )
        topology_signature = base_pose.mesh_topology_signature(mesh_source)
        base_object = base_pose.ensure_base_pose_proxy(
            mesh_source,
            expected_mesh_topology_signature=topology_signature,
        )
        props = mesh_source.hotools_mesh_collision
        props.pin_enabled = True
        props.pin_vertex_group = "MC2Pin"

        step_settings = {
            "simulation_frequency": 60,
            "max_simulation_count_per_frame": 3,
        }
        for cycle in range(int(scenario["cycles"])):
            pin_group.remove((0, 1, 2, 3))
            pin_group.add((0,), 1.0, "REPLACE")
            world = world_types.PhysicsWorldCache()
            worlds.append(world)
            world.generation = cycle + 1
            tasks = _tasks(mesh_source, cloth_armature, spring_armature, 0.1)
            previous_frame = None
            previous_candidates = {}
            hot_context = None
            hot_reset_count = None
            old_static_context = None
            for local_frame in range(1, int(scenario["frames_per_cycle"]) + 1):
                frame = cycle * 1000 + local_frame
                mesh_armature.pose.bones["MeshDriver"].location.x = (
                    0.1 * math.sin(local_frame * 0.07)
                )
                for armature, scale in ((cloth_armature, 0.15), (spring_armature, -0.12)):
                    root = armature.pose.bones["Root"]
                    root.rotation_mode = "XYZ"
                    root.rotation_euler.z = scale * math.sin(local_frame * 0.05)
                bpy.context.view_layer.update()

                if local_frame == int(scenario["parameter_hot_update_frame"]):
                    mesh_slot = world.solver_slots[tasks[0].task_id]
                    hot_context = mesh_slot.data["native_context"]
                    hot_reset_count = hot_context.inspect()["reset_count"]
                    tasks = _tasks(mesh_source, cloth_armature, spring_armature, 0.35)

                if local_frame == int(scenario["static_rebuild_frame"]):
                    old_static_context = world.solver_slots[tasks[0].task_id].data[
                        "native_context"
                    ]
                    pin_group.add((1,), 1.0, "REPLACE")

                reset = local_frame == int(scenario["explicit_reset_frame"])
                _set_frame_context(
                    world, frame, previous_frame, cycle + 1, reset=reset
                )
                world.collider_snapshot = {
                    "frame": frame,
                    "colliders": [
                        {
                            "key": "soak-sphere",
                            "type": "SPHERE",
                            "primary_group": 1,
                            "center": (0.0, 0.0, -5.0),
                            "radius": 0.5,
                        }
                    ],
                }
                started = time.perf_counter()
                returned, ready, status = nodes.physicsMC2Step(
                    world, tasks, **step_settings
                )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                assert returned is world and ready is True, status
                if local_frame > int(scenario["warmup_frames_per_cycle"]):
                    timings.append(elapsed_ms)

                assert len(world.solver_slots) == 3
                for task in tasks:
                    slot = world.solver_slots[task.task_id]
                    candidate = slot.data["result_candidate"]
                    assert candidate is not None
                    assert candidate.frame == frame
                    assert candidate.generation == cycle + 1
                    assert np.all(np.isfinite(candidate.world_positions))
                    assert np.all(np.isfinite(candidate.world_rotations_xyzw))
                    assert candidate is not previous_candidates.get(task.task_id)
                    previous_candidates[task.task_id] = candidate
                stats = world.consume_results(
                    mc2_names.MC2_STATS_CHANNEL,
                    solver="mc2",
                    frame=frame,
                    generation=cycle + 1,
                )
                assert len(stats) == 1
                assert stats[0]["slot_count"] == stats[0]["native_context_count"] == 3
                assert stats[0]["mesh_cloth_count"] == 1
                assert stats[0]["bone_cloth_count"] == 1
                assert stats[0]["bone_spring_count"] == 1
                assert stats[0]["writeback_result_count"] == 3
                assert len(world.result_streams[world_names.GN_ATTRIBUTE_CHANNEL]) == 1
                assert len(world.result_streams[world_names.BONE_TRANSFORM_CHANNEL]) == 2
                assert writeback.writeback_gn_attributes(world) == 1
                assert writeback.writeback_bone_transforms(world) == 8

                if local_frame == int(scenario["parameter_hot_update_frame"]):
                    current = world.solver_slots[tasks[0].task_id].data["native_context"]
                    assert current is hot_context
                    assert current.inspect()["reset_count"] == hot_reset_count
                    counters["parameter_hot_updates"] += 1

                if local_frame == int(scenario["static_rebuild_frame"]):
                    current = world.solver_slots[tasks[0].task_id].data["native_context"]
                    assert current is not old_static_context
                    assert old_static_context.disposed is True
                    counters["static_rebuilds"] += 1

                if reset:
                    counters["explicit_resets"] += 1

                if local_frame == int(scenario["same_frame_reuse_frame"]):
                    before = {
                        task_id: (
                            slot.data["result_candidate"],
                            slot.data["native_context"].inspect()["step_count"],
                        )
                        for task_id, slot in world.solver_slots.items()
                    }
                    _set_frame_context(world, frame, frame, cycle + 1)
                    _, same_ready, _ = nodes.physicsMC2Step(
                        world, tasks, **step_settings
                    )
                    assert same_ready is True
                    for task_id, slot in world.solver_slots.items():
                        candidate, step_count = before[task_id]
                        assert slot.data["result_candidate"] is candidate
                        assert slot.data["native_context"].inspect()["step_count"] == step_count
                    counters["same_frame_reuses"] += 1

                previous_frame = frame

            owners = [
                slot.data["native_context"] for slot in world.solver_slots.values()
            ]
            world.omni_cache_dispose("v1_soak_cycle_complete")
            assert all(owner.disposed for owner in owners)
            counters["released_contexts"] += len(owners)

        for name, expected in required.items():
            assert counters[name] == int(expected), (name, counters[name], expected)
        values = np.asarray(timings, dtype=np.float64)
        mean_ms = float(np.mean(values))
        p95_ms = float(np.percentile(values, 95))
        max_ms = float(np.max(values))
        assert mean_ms <= float(ceilings["mean"]), (mean_ms, ceilings)
        assert p95_ms <= float(ceilings["p95"]), (p95_ms, ceilings)
        assert max_ms <= float(ceilings["max"]), (max_ms, ceilings)
        print(
            "MC2 V1-R soak: PASS "
            + json.dumps(
                {
                    "frames": int(scenario["cycles"]) * int(scenario["frames_per_cycle"]),
                    "samples": len(timings),
                    "mean_ms": round(mean_ms, 4),
                    "p95_ms": round(p95_ms, 4),
                    "max_ms": round(max_ms, 4),
                    **counters,
                },
                sort_keys=True,
            )
        )
    finally:
        for world in worlds:
            world.omni_cache_dispose("v1_soak_cleanup")
        for obj in (base_object, mesh_source, mesh_armature, cloth_armature, spring_armature):
            _remove_object(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    main()
