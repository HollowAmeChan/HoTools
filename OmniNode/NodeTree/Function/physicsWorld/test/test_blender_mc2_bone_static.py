"""Blender integration for staged MC2 BoneCloth Line static registration."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


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


names = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names")
native_flags = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
specs = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs")
topology_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_cloth.static_build"
)
solver = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver")
world_types = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.types")
writeback = importlib.import_module("HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback")


def _armature():
    data = bpy.data.armatures.new("MC2_BoneStaticData")
    obj = bpy.data.objects.new("MC2_BoneStatic", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 1.0, 0.0)
    mid = data.edit_bones.new("Mid")
    mid.head = root.tail
    mid.tail = (0.25, 2.0, 0.0)
    mid.parent = root
    mid.use_connect = True
    tip = data.edit_bones.new("Tip")
    tip.head = mid.tail
    tip.tail = (0.5, 3.0, 0.25)
    tip.parent = mid
    tip.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


class _FakeMatrix:
    def __init__(self, value):
        self.value = value

    def copy(self):
        return _FakeMatrix(self.value)


class _FakePoseBone:
    def __init__(self, value, fail_value=None):
        self._matrix_basis = _FakeMatrix(value)
        self.fail_value = fail_value

    @property
    def matrix_basis(self):
        return self._matrix_basis

    @matrix_basis.setter
    def matrix_basis(self, value):
        if self.fail_value is not None and value.value == self.fail_value:
            raise RuntimeError("injected bone writeback failure")
        self._matrix_basis = value.copy()


class _NoForeachPoseBones:
    def foreach_get(self, _name, _values):
        raise TypeError("foreach unavailable")


def _test_batch_writeback_rollback():
    first = _FakePoseBone("old-first")
    second = _FakePoseBone("old-second", fail_value="new-second")
    updates = (
        (first, 0, _FakeMatrix("new-first"), "First"),
        (second, 1, _FakeMatrix("new-second"), "Second"),
    )
    try:
        writeback._apply_bone_basis_updates(_NoForeachPoseBones(), updates, [0.0] * 32)
    except RuntimeError as exc:
        assert "injected bone writeback failure" in str(exc)
    else:
        raise AssertionError("batch writeback failure was not propagated")
    assert first.matrix_basis.value == "old-first"
    assert second.matrix_basis.value == "old-second"


armature = _armature()
world = None
try:
    _test_batch_writeback_rollback()
    source = {"armature": armature, "root_bone": "Root"}
    task = specs.make_mc2_task_spec(names.MC2_SETUP_BONE_CLOTH, [source])
    topology = topology_module.build_mc2_topology_spec(task)
    static = static_build.build_mc2_bone_cloth_static_for_task(task, topology)
    assert static is not None
    assert static.final_proxy.vertex_identities == ("Root", "Mid", "Tip")
    assert static.final_proxy.vertex_attributes == (0x01, 0x02, 0x02)
    assert static.final_proxy.edges == ((0, 1), (1, 2))
    assert static.final_proxy.triangles == ()
    assert static.baseline.parent_indices == (-1, 0, 1)
    assert static.finalizer.vertex_to_vertex_data == (1, 2, 0, 1)
    assert len(static.distance.distance_targets) == 4
    assert static.center.fixed_indices == (0,)

    world = world_types.PhysicsWorldCache()
    returned, ready, status = solver.step_mc2(world, [task])
    assert returned is world and ready is False
    assert "新建 1" in status
    slot = world.solver_slots[task.task_id]
    assert slot.data["mesh_static"] is None
    assert slot.data["bone_static"] is not None
    assert slot.data["result_candidate"] is None
    production_topology = slot.data["topology"]
    assert production_topology.topology_signature == topology.topology_signature
    assert production_topology.sources[0].bone_names == ("Root", "Mid", "Tip")
    assert all("bones" not in dict(source.payload) for source in production_topology.sources)
    info = slot.data["native_context"].inspect()
    assert info["proxy_static_ready"] is True
    assert info["baseline_static_ready"] is True
    assert info["bone_static_ready"] is True
    assert info["owned_static_take_count"] == 4
    assert slot.data["bone_static"].native_owned is True
    assert not hasattr(slot.data["bone_static"], "bone")
    assert not hasattr(slot.data["bone_static"].distance, "distance_targets")
    assert not hasattr(slot.data["bone_static"].center, "fixed_indices")
    assert not hasattr(slot.data["bone_static"].self_collision, "primitive_flags")
    assert info["distance_static_ready"] is True
    assert info["center_static_ready"] is True
    assert info["self_collision_static_ready"] is True
    assert info["self_collision_static_revision"] == 1
    assert info["self_primitive_count"] == 2
    assert info["self_point_primitive_count"] == 0
    assert info["self_edge_primitive_count"] == 2
    assert info["self_triangle_primitive_count"] == 0
    assert info["self_contact_cache_count"] == 0
    assert info["self_intersect_record_count"] == 0
    assert info["bone_vertex_adjacency_count"] == 4
    assert info["tether_enabled"] is True
    assert info["tether_solve_count"] == 0
    snapshot = slot.debug_snapshot()
    assert snapshot["mesh_static"] is None
    assert snapshot["bone_static"]["vertex_count"] == 3
    assert snapshot["bone_static"]["static_signature"] == static.static_signature

    world.omni_cache_dispose("static_only_complete")
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 1
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    returned, ready, _status = solver.step_mc2(world, [task])
    assert returned is world and ready is True
    slot = world.solver_slots[task.task_id]
    candidate = slot.data["result_candidate"]
    assert candidate is not None
    assert candidate.setup_type == names.MC2_SETUP_BONE_CLOTH
    assert candidate.ready is False
    assert candidate.mesh_object_local_offsets is None
    assert candidate.world_positions.flags.writeable is False
    assert candidate.world_rotations_xyzw.flags.writeable is False
    step_info = slot.data["native_context"].inspect()
    assert step_info["bone_line_output_count"] == 1
    assert step_info["bone_triangle_output_count"] == 0
    assert step_info["tether_enabled"] is True
    assert step_info["tether_solve_count"] == 0
    result = world.result_streams["bone_transform"][0]
    assert result["writeback_type"] == "bone_transform_batch"
    assert result["ready"] is True
    assert result["task_id"] == task.task_id
    assert result["bone_count"] == 3
    assert result["plan_schema"] == "mc2_bone_writeback_plan_v0"
    assert result["target_key"] == f"{armature.as_pointer()}:{armature.data.as_pointer()}"
    plan = slot.data["writeback_plan"]
    assert plan["schema"] == "mc2_bone_writeback_plan_v0"
    assert plan["armature"] is armature
    assert tuple(record["bone_name"] for record in plan["batches"][0]["records"]) == (
        "Root", "Mid", "Tip"
    )
    assert writeback.writeback_bone_transforms(world) == 3
    assert "_writeback_error" not in slot.data

    context_before_pose_change = slot.data["native_context"]
    armature.pose.bones["Root"].rotation_mode = "XYZ"
    armature.pose.bones["Root"].rotation_euler.z = 0.2
    bpy.context.view_layer.update()
    world.frame_context.frame = 2
    solver.step_mc2(world, [task])
    slot = world.solver_slots[task.task_id]
    second_candidate = slot.data["result_candidate"]
    second_info = slot.data["native_context"].inspect()
    assert slot.data["native_context"] is context_before_pose_change
    assert slot.data["last_static_change_mask"] == 0
    assert second_candidate.revision == 2
    assert second_info["step_count"] == 1
    assert second_info["bone_line_output_count"] == 2
    assert second_info["bone_triangle_output_count"] == 0
    assert second_info["tether_solve_count"] == 1
    assert second_info["angle_solve_count"] == 1
    solver.step_mc2(world, [task])
    assert slot.data["result_candidate"] is second_candidate
    assert slot.data["native_context"].inspect()["bone_line_output_count"] == 2
    assert len(world.result_streams["bone_transform"]) == 1
    assert world.result_streams["bone_transform"][0]["revision"] == 2
    assert writeback.writeback_bone_transforms(world) == 3
    assert "_writeback_error" not in slot.data

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    armature.data.edit_bones["Tip"].tail.z += 0.125
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    bpy.context.view_layer.update()
    world.frame_context.frame = 3
    _returned, _ready, rebuild_status = solver.step_mc2(world, [task])
    rebuilt_slot = world.solver_slots[task.task_id]
    assert "重建 1" in rebuild_status
    assert rebuilt_slot.data["native_context"] is not context_before_pose_change
    assert context_before_pose_change.inspect()["released"] is True
    assert rebuilt_slot.data["runtime_state"].allocation_reason == "static_input_changed"
    assert rebuilt_slot.data["last_static_change_mask"] == native_flags.MC2_STATIC_CHANGE_GEOMETRY

    geometry_context = rebuilt_slot.data["native_context"]
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    tip = armature.data.edit_bones["Tip"]
    tip.parent = armature.data.edit_bones["Root"]
    tip.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    bpy.context.view_layer.update()
    world.frame_context.frame = 4
    solver.step_mc2(world, [task])
    hierarchy_slot = world.solver_slots[task.task_id]
    assert hierarchy_slot.data["native_context"] is not geometry_context
    assert geometry_context.inspect()["released"] is True
    assert hierarchy_slot.data["runtime_state"].allocation_reason == "topology_changed"
    assert hierarchy_slot.data["last_static_change_mask"] & native_flags.MC2_STATIC_CHANGE_TOPOLOGY

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    tip = armature.data.edit_bones["Tip"]
    tip.parent = armature.data.edit_bones["Mid"]
    tip.use_connect = True
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    bpy.context.view_layer.update()

    world.omni_cache_dispose("bone_cloth_complete")
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 3
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    world.collider_snapshot = {
        "frame": 3,
        "colliders": [
            {
                "key": "spring-far-sphere",
                "type": "SPHERE",
                "primary_group": 1,
                "center": (100.0, 0.0, 0.0),
                "radius": 1.0,
            },
            {
                "key": "spring-filtered-plane",
                "type": "PLANE",
                "primary_group": 1,
                "center": (0.0, 0.0, -100.0),
                "normal": (0.0, 0.0, 1.0),
            },
        ],
    }
    spring_profile = parameters.make_mc2_particle_profile(
        gravity=9.0,
        tether_compression=0.1,
        distance_stiffness=0.2,
        max_distance_enabled=True,
        self_collision_mode=2,
    )
    spring_task = specs.make_mc2_task_spec(
        names.MC2_SETUP_BONE_SPRING,
        [source],
        profile=spring_profile,
        setup_options=parameters.make_mc2_setup_options(
            names.MC2_SETUP_BONE_SPRING,
            collided_by_groups=1,
        ),
    )
    returned, ready, _status = solver.step_mc2(world, [spring_task])
    assert returned is world and ready is True
    spring_slot = world.solver_slots[spring_task.task_id]
    assert spring_slot.data["bone_static"].final_proxy.setup_type == "bone_spring"
    assert spring_slot.data["bone_static"].static_signature != static.static_signature
    runtime = spring_slot.data["effective_parameters"].debug_dict()
    assert runtime["setup_type"] == "bone_spring"
    assert runtime["float_values"]["gravity"] == 0.0
    assert abs(runtime["float_values"]["tether_compression_limit"] - 0.8) < 1.0e-7
    assert runtime["curve_values"]["distance_stiffness"] == [0.5] * 16
    assert runtime["int_values"]["use_max_distance"] == 0
    assert runtime["int_values"]["self_collision_mode"] == 0
    spring_info = spring_slot.data["native_context"].inspect()
    assert spring_info["setup_kind"] == 2
    assert spring_info["self_collision_static_ready"] is True
    assert spring_info["self_primitive_count"] == 2
    assert spring_info["self_point_primitive_count"] == 0
    assert spring_info["self_edge_primitive_count"] == 2
    assert spring_info["self_triangle_primitive_count"] == 0
    assert spring_info["self_contact_cache_count"] == 0
    assert spring_info["self_intersect_record_count"] == 0
    assert spring_info["tether_enabled"] is True
    assert spring_info["collider_count"] == 1
    assert spring_info["collided_by_groups"] == 1
    spring_result = world.result_streams["bone_transform"][0]
    assert spring_result["setup_type"] == "bone_spring"
    assert spring_result["bone_count"] == 3
    assert spring_slot.data["writeback_plan"]["batches"][0]["source_kind"] == "bone_spring"
    assert writeback.writeback_bone_transforms(world) == 3
    assert "_writeback_error" not in spring_slot.data

    world.frame_context.frame = 4
    world.collider_snapshot["frame"] = 4
    solver.step_mc2(world, [spring_task])
    spring_info = spring_slot.data["native_context"].inspect()
    assert spring_info["point_collision_solve_count"] == 1
    assert spring_info["collider_revision"] == 2

    world.omni_cache_dispose("bone_spring_complete")
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    world.frame_context.frame = 4
    world.frame_context.generation = 1
    world.frame_context.dt = 1.0 / 60.0
    automatic_task = specs.make_mc2_task_spec(
        names.MC2_SETUP_BONE_CLOTH,
        [source],
        setup_options=parameters.make_mc2_setup_options(
            names.MC2_SETUP_BONE_CLOTH,
            connection_mode=1,
        ),
    )
    returned, ready, _status = solver.step_mc2(world, [automatic_task])
    assert returned is world and ready is True
    automatic_slot = world.solver_slots[automatic_task.task_id]
    automatic_static = automatic_slot.data["bone_static"]
    assert automatic_static.connection_mode == 1
    assert automatic_static.final_proxy.triangles.tolist() == []
    assert automatic_static.final_proxy.edges.tolist() == [[0, 1], [1, 2]]
    assert world.result_streams["bone_transform"][0]["setup_type"] == "bone_cloth"
    assert writeback.writeback_bone_transforms(world) == 3
    assert "_writeback_error" not in automatic_slot.data
    for pose_bone in armature.pose.bones:
        assert all(abs(float(value) - 1.0) < 1.0e-5 for value in pose_bone.scale)

    old_context = automatic_slot.data["native_context"]
    old_candidate = automatic_slot.data["result_candidate"]
    old_plan = automatic_slot.data["writeback_plan"]
    old_result = world.result_streams["bone_transform"][0]
    armature.scale = (-1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    world.frame_context.frame = 5
    returned, ready, _status = solver.step_mc2(world, [automatic_task])
    assert returned is world and ready is True
    assert automatic_slot.data["native_context"] is old_context
    assert automatic_slot.data["result_candidate"] is not old_candidate
    assert automatic_slot.data["result_candidate"].revision == old_candidate.revision + 1
    assert (
        automatic_slot.data["result_candidate"].bone_component_world_rotation_xyzw
        is not None
    )
    assert automatic_slot.data["writeback_plan"] is not old_plan
    assert world.result_streams["bone_transform"][0] is not old_result
    negative_info = old_context.inspect()
    assert negative_info["center_negative_scale_teleport_count"] == 1
    assert automatic_slot.data["center_state"].negative_scale_direction == (
        -1.0,
        1.0,
        1.0,
    )
    assert writeback.writeback_bone_transforms(world) == 3
    assert "_writeback_error" not in automatic_slot.data
    for pose_bone in armature.pose.bones:
        assert all(abs(float(value) - 1.0) < 1.0e-5 for value in pose_bone.scale)
    assert old_context.disposed is False

    armature.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    world.frame_context.frame = 6
    returned, ready, _status = solver.step_mc2(world, [automatic_task])
    assert returned is world and ready is True
    restored_info = old_context.inspect()
    assert restored_info["center_negative_scale_teleport_count"] == 2
    assert automatic_slot.data["center_state"].negative_scale_direction == (
        1.0,
        1.0,
        1.0,
    )
    assert writeback.writeback_bone_transforms(world) == 3
    for pose_bone in armature.pose.bones:
        assert all(abs(float(value) - 1.0) < 1.0e-5 for value in pose_bone.scale)
finally:
    if world is not None:
        world.omni_cache_dispose("test_cleanup")
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if data.users == 0:
        bpy.data.armatures.remove(data)

print("MC2 BoneCloth/BoneSpring Line static/native/writeback: PASS")
