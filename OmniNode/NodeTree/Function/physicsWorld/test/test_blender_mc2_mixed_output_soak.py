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
specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
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
    parent = None
    for index in range(5):
        bone = data.edit_bones.new("Root" if index == 0 else f"Bone{index}")
        bone.head = (0.0, index * 0.12, 0.02 * index)
        bone.tail = (0.015 * index, (index + 1) * 0.12, 0.02 * (index + 1))
        bone.parent = parent
        bone.use_connect = parent is not None and index != 3
        parent = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _tasks(mesh, cloth, spring, damping, teleport_mode):
    mesh_task = specs.make_mc2_task_spec(
        names.MC2_SETUP_MESH_CLOTH,
        [mesh],
        profile=parameters.make_mc2_particle_profile(
            gravity=5.0,
            damping=damping,
            self_collision_mode=0,
            teleport_mode=teleport_mode,
            teleport_distance=0.5,
            teleport_rotation=180.0,
        ),
    )
    cloth_task = specs.make_mc2_task_spec(
        names.MC2_SETUP_BONE_CLOTH,
        [{"armature": cloth, "root_bone": "Root"}],
        profile=parameters.make_mc2_particle_profile(
            gravity=3.0,
            damping=damping,
            self_collision_mode=0,
            teleport_mode=teleport_mode,
            teleport_distance=0.5,
            teleport_rotation=180.0,
        ),
    )
    spring_task = specs.make_mc2_task_spec(
        names.MC2_SETUP_BONE_SPRING,
        [{"armature": spring, "root_bone": "Root"}],
        profile=parameters.make_mc2_particle_profile(
            damping=damping,
            teleport_mode=teleport_mode,
            teleport_distance=0.5,
            teleport_rotation=180.0,
        ),
        setup_options=parameters.make_mc2_setup_options(
            names.MC2_SETUP_BONE_SPRING,
            collided_by_groups=1,
        ),
    )
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
    root = armature.pose.bones["Root"]
    root.rotation_mode = "XYZ"
    root.rotation_euler.z = amplitude * math.sin(frame * 0.021)
    root.location.x = 0.015 * math.sin(frame * 0.013)


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
        reset_hits = set()
        previous_candidate_revisions = {task_id: 0 for task_id in stable_ids}
        topologies = {
            task.task_id: topology_module.build_mc2_topology_spec(task)
            for task in tasks
        }
        reset_counts_before = None
        reset_bone_inputs = {}
        for frame in range(1, 901):
            _animate_armature(cloth, frame, 0.18)
            _animate_armature(spring, frame, -0.14)
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
                tasks = _tasks(mesh, cloth, spring, 0.25, 1)
                assert tuple(task.task_id for task in tasks) == stable_ids
            if frame == 601:
                for source in (mesh, cloth, spring):
                    source.location.x += 2.0
                bpy.context.view_layer.update()
                reset_counts_before = {
                    task.task_id: world.solver_slots[task.task_id]
                    .data["native_context"]
                    .inspect()["reset_count"]
                    for task in tasks
                }
                reset_bone_inputs = {
                    task.task_id: bone_frame_input.build_mc2_bone_frame_input(
                        task,
                        topologies[task.task_id],
                        frame=frame,
                        generation=generation,
                        world=world,
                    )
                    for task in tasks
                    if task.setup_type != names.MC2_SETUP_MESH_CLOTH
                }
            _set_frame(
                world,
                frame,
                generation,
                raw_dt=(1.0 / 360.0 if frame == 601 else None),
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
                shift = slot.data["center_frame_shift_result"]
                if frame == 301:
                    assert shift is not None
                    assert shift.keep_teleport is True
                    assert shift.reset_teleport is False
                    assert shift.teleport_measured_distance >= shift.teleport_distance_threshold
                    keep_hits.add(task.setup_type)
                if frame == 601:
                    assert shift is not None
                    assert shift.keep_teleport is False
                    assert shift.reset_teleport is True
                    assert shift.teleport_measured_distance >= shift.teleport_distance_threshold
                    assert slot.data["frame_schedule"].update_count == 0
                    assert (
                        slot.data["native_context"].inspect()["reset_count"]
                        == reset_counts_before[task.task_id] + 1
                    )
                    if task.task_id in reset_bone_inputs:
                        np.testing.assert_allclose(
                            candidate.world_positions,
                            reset_bone_inputs[task.task_id].world_positions,
                            atol=1.0e-6,
                        )
                    reset_hits.add(task.setup_type)
            assert writeback.writeback_gn_attributes(world) == 1
            assert writeback.writeback_bone_transforms(world) == 10
            bpy.context.view_layer.update()
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
            if frame == 899:
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
        assert reset_hits == expected_setups

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
        print("[PASS] 900-frame mixed output/hot-update + all-setup Keep/Reset")
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
