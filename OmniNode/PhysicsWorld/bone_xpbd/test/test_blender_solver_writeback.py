"""Bone XPBD 端点拓扑、运行决策与公共骨骼写回的 Blender 4.5 闭环。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import mathutils
import numpy as np


BONE_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(BONE_XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", os.path.join(OMNINODE, "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


collision_properties = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.collision.properties"
)
names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.names"
)
nodes = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.nodes"
)
results = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.results"
)
feedback = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.feedback"
)
solver = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.solver"
)
family_solver = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.family_solver"
)
topology = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.topology"
)
world_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.names")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
writeback = importlib.import_module("HoTools.OmniNode.PhysicsWorld.writeback")
writeback_pose = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.utils.writeback_pose"
)


def _ensure_bone_collision_property() -> tuple[bool, bool]:
    """Standalone Blender 运行时为 Pin 测试补齐公共 Bone RNA。"""

    if hasattr(bpy.types.Bone, "hotools_collision"):
        return False, False
    bone_class = collision_properties.PG_Hotools_BoneCollision
    registered_class = False
    try:
        bpy.utils.register_class(bone_class)
        registered_class = True
    except RuntimeError:
        pass
    bpy.types.Bone.hotools_collision = bpy.props.PointerProperty(type=bone_class)
    return True, registered_class


def _remove_bone_collision_property(added_binding: bool, registered_class: bool) -> None:
    if added_binding and hasattr(bpy.types.Bone, "hotools_collision"):
        del bpy.types.Bone.hotools_collision
    if registered_class:
        try:
            bpy.utils.unregister_class(collision_properties.PG_Hotools_BoneCollision)
        except RuntimeError:
            pass


def _make_explicit_chain():
    data = bpy.data.armatures.new("BoneXpbdWritebackData")
    armature = bpy.data.objects.new("BoneXpbdWriteback", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    # 稍微弯曲的四段链保留一个可运动内部端点，同时避免绝对直线拉紧。
    points = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (2.0, 0.35, 0.0),
        (3.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
    )
    names_in_order = []
    parent = None
    for index, (head, tail) in enumerate(zip(points, points[1:])):
        bone = data.edit_bones.new(f"Segment{index}")
        bone.head = head
        bone.tail = tail
        bone.parent = parent
        bone.use_connect = False
        names_in_order.append(bone.name)
        parent = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    data.bones[names_in_order[0]].hotools_collision.pin = True
    data.bones[names_in_order[-1]].hotools_collision.pin = True
    return armature, tuple(names_in_order), np.asarray(points, dtype=np.float32)


def _bone_socket_collection(armature, bone_names):
    return {
        "armature": armature,
        "bone": bone_names[0],
        "bone_collection_root": bone_names[0],
        "bone_collection": list(bone_names),
    }


def _make_tasks(
    armature,
    bone_groups,
    *,
    tail_follow: bool,
    collision_enabled: bool = False,
):
    objects, object_count = nodes.physicsBoneXpbdObject(
        [_bone_socket_collection(armature, group) for group in bone_groups]
    )
    assert object_count == len(bone_groups)
    tasks, task_count = nodes.physicsBoneXpbdTask(
        objects,
        tail_follow=tail_follow,
        collision_enabled=collision_enabled,
        damping=0.0,
        stretch_compliance=0.02,
        bend_compliance=0.2,
        iterations=12,
        gravity_direction=(0.0, 0.0, -1.0),
        gravity_power=40.0,
    )
    assert task_count == len(bone_groups)
    return tuple(tasks)


def _make_task(
    armature,
    bone_names,
    *,
    tail_follow: bool,
    collision_enabled: bool = False,
):
    return _make_tasks(
        armature,
        (tuple(bone_names),),
        tail_follow=tail_follow,
        collision_enabled=collision_enabled,
    )[0]


def _set_frame(
    world,
    frame: int,
    *,
    restart: bool = False,
    same_frame: bool = False,
) -> None:
    context = world.frame_context
    context.previous_frame = frame if same_frame else (frame - 1 if frame > 1 else None)
    context.frame = frame
    context.continuous = frame > 1 and not restart
    context.same_frame = same_frame
    context.restart_required = restart
    context.reset_requested = restart
    context.raw_dt = 1.0 / 24.0
    context.dt = 1.0 / 24.0
    context.substeps = 2
    context.generation = world.generation
    world.collider_snapshot = {
        "frame": frame,
        "generation": world.generation,
        "colliders": [],
        "source_count": 0,
    }


def _rotation_delta(left, right) -> float:
    left_quaternion = left.to_quaternion()
    right_quaternion = right.to_quaternion()
    left_quaternion.normalize()
    right_quaternion.normalize()
    return float(left_quaternion.rotation_difference(right_quaternion).angle)


def _batch_results(world, expected_count: int):
    commands = world.consume_results(
        world_names.BONE_TRANSFORM_CHANNEL,
        solver=names.BONE_XPBD_SOLVER_ID,
    )
    assert len(commands) == expected_count
    for command in commands:
        assert command["writeback_type"] == "bone_transform_batch"
        assert command["solver"] == names.BONE_XPBD_SOLVER_ID
        assert command["plan_schema"] == "bone_xpbd_writeback_plan_v1"
    return tuple(commands)


def _batch_result(world):
    return _batch_results(world, 1)[0]


def _plan_values(world, tasks):
    targets = {}
    bases = {}
    own_targets = {}
    for task in tasks:
        batch = world.solver_slots[task.slot_id].data["writeback_plan"]["batches"][0]
        task_targets = {}
        for record, basis, target in zip(
            batch["records"],
            batch["matrix_bases"],
            batch["target_pose_matrices"],
        ):
            name = record["bone_name"]
            targets[name] = target
            bases[name] = basis
            task_targets[name] = target
        own_targets[task.slot_id] = task_targets
    return targets, bases, own_targets


def _matrix_values(matrix) -> np.ndarray:
    return np.asarray(matrix, dtype=np.float64)


def test_bone_xpbd_explicit_chain_step_reset_same_frame_and_tail_follow():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, rest_points = _make_explicit_chain()
        assert all(not armature.data.bones[name].use_connect for name in bone_names)
        initial_pose_matrices = {
            name: armature.pose.bones[name].matrix.copy() for name in bone_names
        }

        follow_task = _make_task(armature, bone_names, tail_follow=True)
        graph = topology.build_bone_xpbd_topology(follow_task, world=world)
        assert graph.particle_count == 5
        assert graph.shared_endpoint_count == 3
        np.testing.assert_array_equal(
            graph.endpoint_particles,
            ((0, 1), (1, 2), (2, 3), (3, 4)),
        )
        np.testing.assert_allclose(graph.rest_armature_positions, rest_points, atol=1.0e-7)
        np.testing.assert_array_equal(graph.inverse_masses, (0.0, 0.0, 1.0, 0.0, 0.0))

        _set_frame(world, 1)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [follow_task], debug_capture=True
        )
        assert writeback_count == 1
        first_stats = results.get_bone_xpbd_stats_result(world)
        assert first_stats["reset_slot_count"] == 1
        assert first_stats["stepped_slot_count"] == 0
        first_command = _batch_result(world)
        assert first_command["bone_count"] == len(bone_names)
        assert first_command["tail_follow"] is True
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        first_receipts = writeback.get_bone_writeback_receipts(world)
        assert len(first_receipts) == 1
        assert first_receipts[0]["publication_id"] == first_command["publication_id"]

        slot = world.solver_slots[follow_task.slot_id]
        basis_values = slot.data["writeback_plan"].get("basis_values")
        assert isinstance(basis_values, list)
        assert len(basis_values) == len(armature.pose.bones) * 16
        reset_positions = slot.data["debug_capture"]["world_positions"].copy()
        np.testing.assert_allclose(reset_positions, rest_points, atol=1.0e-6)

        _set_frame(world, 2)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [follow_task], debug_capture=True
        )
        assert writeback_count == 1
        step_stats = results.get_bone_xpbd_stats_result(world)
        assert step_stats["stepped_slot_count"] == 1
        assert step_stats["reset_slot_count"] == 0
        stepped_positions = slot.data["debug_capture"]["world_positions"].copy()
        assert float(np.linalg.norm(stepped_positions[2] - reset_positions[2])) > 1.0e-5

        follow_plan = slot.data["writeback_plan"]
        assert follow_plan.get("basis_values") is basis_values
        follow_batch = follow_plan["batches"][0]
        assert follow_plan["schema"] == "bone_xpbd_writeback_plan_v1"
        assert len(follow_batch["records"]) == len(bone_names)
        assert all(record["tail_follow"] is True for record in follow_batch["records"])
        assert any(
            _rotation_delta(target, initial_pose_matrices[name]) > 1.0e-5
            for name, target in zip(bone_names, follow_batch["target_pose_matrices"])
        )
        stepped_command = _batch_result(world)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        bpy.context.view_layer.update()
        assert any(
            _rotation_delta(armature.pose.bones[name].matrix, initial_pose_matrices[name])
            > 1.0e-5
            for name in bone_names
        )

        _set_frame(world, 2, same_frame=True)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [follow_task], debug_capture=True
        )
        assert writeback_count == 1
        same_frame_stats = results.get_bone_xpbd_stats_result(world)
        assert same_frame_stats["republished_slot_count"] == 1
        assert same_frame_stats["stepped_slot_count"] == 0
        np.testing.assert_allclose(
            slot.data["debug_capture"]["world_positions"],
            stepped_positions,
            atol=1.0e-7,
        )
        same_frame_command = _batch_result(world)
        assert same_frame_command["transaction_id"] != stepped_command["transaction_id"]
        assert same_frame_command["publication_id"] != stepped_command["publication_id"]
        assert writeback.writeback_bone_transforms(world) == len(bone_names)

        _set_frame(world, 3)
        world.frame_context.dt = 0.0
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [follow_task], debug_capture=True
        )
        assert writeback_count == 1
        paused_stats = results.get_bone_xpbd_stats_result(world)
        assert paused_stats["republished_slot_count"] == 1
        assert paused_stats["stepped_slot_count"] == 0
        np.testing.assert_allclose(
            slot.data["debug_capture"]["world_positions"],
            stepped_positions,
            atol=1.0e-7,
        )
        _batch_result(world)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)

        # 真实Physics World Begin会在restart标志前先清理公共Bone写回。
        writeback.clear_all_deltas(world)
        _set_frame(world, 10, restart=True)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [follow_task], debug_capture=True
        )
        assert writeback_count == 1
        reset_stats = results.get_bone_xpbd_stats_result(world)
        assert reset_stats["reset_slot_count"] == 1
        assert reset_stats["stepped_slot_count"] == 0
        slot = world.solver_slots[follow_task.slot_id]
        np.testing.assert_allclose(
            slot.data["debug_capture"]["world_positions"],
            reset_positions,
            atol=1.0e-6,
        )
        _batch_result(world)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        bpy.context.view_layer.update()

        free_tail_task = _make_task(armature, bone_names, tail_follow=False)
        assert free_tail_task.slot_id == follow_task.slot_id
        _set_frame(world, 11)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [free_tail_task], debug_capture=True
        )
        assert writeback_count == 1
        free_command = _batch_result(world)
        assert free_command["tail_follow"] is False
        slot = world.solver_slots[free_tail_task.slot_id]
        free_batch = slot.data["writeback_plan"]["batches"][0]
        assert all(record["tail_follow"] is False for record in free_batch["records"])
        assert all(
            _rotation_delta(target, initial_pose_matrices[name]) < 1.0e-6
            for name, target in zip(bone_names, free_batch["target_pose_matrices"])
        )
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        bpy.context.view_layer.update()
        assert all(
            _rotation_delta(armature.pose.bones[name].matrix, initial_pose_matrices[name])
            < 1.0e-5
            for name in bone_names
        )
    finally:
        world.omni_cache_dispose("bone_xpbd_blender_test_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def _run_split_task_order(armature, bone_names, groups, *, verify_cross_parent):
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    tasks = _make_tasks(armature, groups, tail_follow=True)
    try:
        _set_frame(world, 1)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, tasks, debug_capture=True
        )
        assert writeback_count == 2
        _batch_results(world, 2)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        assert len(writeback.get_bone_writeback_diagnostics(world)["receipts"]) == 2
        assert len(writeback.get_bone_writeback_receipts(world)) == 2

        _set_frame(world, 2)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, tasks, debug_capture=True
        )
        assert writeback_count == 2
        targets, bases, own_targets = _plan_values(world, tasks)
        assert set(targets) == set(bone_names)

        if verify_cross_parent:
            child_name = bone_names[2]
            child_task = next(task for task in tasks if child_name in task.bone_names)
            child = armature.pose.bones[child_name]
            naive_basis = writeback_pose.matrix_basis_from_pose_matrix(
                child,
                targets[child_name],
                own_targets[child_task.slot_id],
            )
            assert not np.allclose(
                _matrix_values(bases[child_name]),
                _matrix_values(naive_basis),
                rtol=0.0,
                atol=1.0e-6,
            ), "跨 task 的父骨目标没有参与 child basis 反算"

        _batch_results(world, 2)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        bpy.context.view_layer.update()
        for name in bone_names:
            np.testing.assert_allclose(
                _matrix_values(armature.pose.bones[name].matrix),
                _matrix_values(targets[name]),
                rtol=1.0e-6,
                atol=1.0e-5,
            )
        return {
            name: armature.pose.bones[name].matrix.copy() for name in bone_names
        }
    finally:
        world.omni_cache_dispose("bone_xpbd_split_order_complete")
        bpy.context.view_layer.update()


def test_bone_xpbd_cross_task_parent_basis_is_order_independent():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        left = tuple(bone_names[:2])
        right = tuple(bone_names[2:])
        forward = _run_split_task_order(
            armature,
            bone_names,
            (left, right),
            verify_cross_parent=True,
        )
        reverse = _run_split_task_order(
            armature,
            bone_names,
            (right, left),
            verify_cross_parent=False,
        )
        for name in bone_names:
            np.testing.assert_allclose(
                _matrix_values(reverse[name]),
                _matrix_values(forward[name]),
                rtol=1.0e-6,
                atol=1.0e-5,
            )
    finally:
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_partial_publish_failure_discards_batch_and_cold_rebuilds():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    original_publish = solver.publish_bone_xpbd_writeback_result
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        tasks = _make_tasks(
            armature,
            (tuple(bone_names[:2]), tuple(bone_names[2:])),
            tail_follow=True,
        )
        publish_calls = []
        old_contexts = {}

        def fail_second_publish(active_world, result):
            publish_calls.append(str(result["slot_id"]))
            for task in tasks:
                slot = active_world.solver_slots.get(task.slot_id)
                if slot is not None:
                    old_contexts.setdefault(
                        task.slot_id,
                        slot.data.get("native_context"),
                    )
            if len(publish_calls) == 2:
                return None
            return original_publish(active_world, result)

        solver.publish_bone_xpbd_writeback_result = fail_second_publish
        _set_frame(world, 1)
        try:
            solver.step_bone_xpbd(world, tasks, debug_capture=True)
        except RuntimeError as exc:
            assert "Bone XPBD" in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了部分 batch 发布失败")
        finally:
            solver.publish_bone_xpbd_writeback_result = original_publish

        assert len(publish_calls) == 2
        assert set(old_contexts) == {task.slot_id for task in tasks}
        assert all(context is not None and not context.ready for context in old_contexts.values())
        assert all(task.slot_id not in world.solver_slots for task in tasks)
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
        failed_stats = results.get_bone_xpbd_stats_result(world)
        assert failed_stats["status"] == "error"
        assert failed_stats["writeback_count"] == 0

        _set_frame(world, 2)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, tasks, debug_capture=True
        )
        assert writeback_count == 2
        rebuilt_stats = results.get_bone_xpbd_stats_result(world)
        assert rebuilt_stats["status"] == "ok"
        assert rebuilt_stats["reset_slot_count"] == 2
        assert all(
            world.solver_slots[task.slot_id].data["native_context"].ready
            for task in tasks
        )
        _batch_results(world, 2)
    finally:
        solver.publish_bone_xpbd_writeback_result = original_publish
        world.omni_cache_dispose("bone_xpbd_failure_recovery_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_post_publish_failure_does_not_commit_feedback():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    original_capture = solver._capture_slot_debug
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)

        def fail_capture(*_args, **_kwargs):
            raise RuntimeError("模拟后置调试采集失败")

        solver._capture_slot_debug = fail_capture
        _set_frame(world, 1)
        try:
            solver.step_bone_xpbd(world, [task], debug_capture=True)
        except RuntimeError as exc:
            assert "调试采集失败" in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了后置调试采集失败")
        finally:
            solver._capture_slot_debug = original_capture

        assert task.slot_id not in world.solver_slots
        assert feedback.BONE_XPBD_FRAME_STATE_KEY not in world.backend_resources
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
        failed_stats = results.get_bone_xpbd_stats_result(world)
        assert failed_stats["status"] == "error"
        assert failed_stats["writeback_count"] == 0
    finally:
        solver._capture_slot_debug = original_capture
        world.omni_cache_dispose("bone_xpbd_post_publish_failure_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_prepare_failure_discards_old_slot_and_cold_rebuilds():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    original_prepare = solver.prepare_bone_xpbd_feedback
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)

        _set_frame(world, 1)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [task], debug_capture=True
        )
        assert writeback_count == 1
        old_context = world.solver_slots[task.slot_id].data["native_context"]
        assert old_context.ready
        _batch_result(world)
        feedback_state = world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ]

        def fail_prepare(_world, _specs):
            raise ReferenceError("模拟 Blender 对象引用在准备阶段失效")

        solver.prepare_bone_xpbd_feedback = fail_prepare
        _set_frame(world, 2)
        try:
            solver.step_bone_xpbd(world, [task], debug_capture=True)
        except ReferenceError as exc:
            assert "引用" in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了准备阶段失效引用")
        finally:
            solver.prepare_bone_xpbd_feedback = original_prepare

        assert task.slot_id not in world.solver_slots
        assert not old_context.ready
        assert world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ] is feedback_state
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
        failed_stats = results.get_bone_xpbd_stats_result(world)
        assert failed_stats["status"] == "error"
        assert failed_stats["slot_count"] == 1
        assert failed_stats["particle_count"] == 0

        _set_frame(world, 3)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [task], debug_capture=True
        )
        assert writeback_count == 1
        assert world.solver_slots[task.slot_id].data["native_context"].ready
        assert results.get_bone_xpbd_stats_result(world)["reset_slot_count"] == 1
        _batch_result(world)
    finally:
        solver.prepare_bone_xpbd_feedback = original_prepare
        world.omni_cache_dispose("bone_xpbd_prepare_failure_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_empty_task_batch_prunes_slot_context_and_feedback():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)

        _set_frame(world, 1)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world, [task], debug_capture=True
        )
        assert writeback_count == 1
        owner = world.solver_slots[task.slot_id].data["native_context"]
        assert owner.ready
        assert world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ]["bones"]

        _set_frame(world, 2)
        writeback_count, _elapsed = solver.step_bone_xpbd(world, [])
        assert writeback_count == 0
        assert task.slot_id not in world.solver_slots
        assert not owner.ready
        assert world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ]["bones"] == {}
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
        stats = results.get_bone_xpbd_stats_result(world)
        assert stats["status"] == "ok"
        assert stats["slot_count"] == 0
        assert stats["writeback_count"] == 0
    finally:
        world.omni_cache_dispose("bone_xpbd_empty_batch_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_multi_task_public_writeback_is_one_atomic_transaction():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        tasks = _make_tasks(
            armature,
            (tuple(bone_names[:2]), tuple(bone_names[2:])),
            tail_follow=True,
        )
        _set_frame(world, 1)
        writeback_count, _elapsed = solver.step_bone_xpbd(
            world,
            tasks,
            debug_capture=True,
        )
        assert writeback_count == 2
        commands = _batch_results(world, 2)
        assert len({command["transaction_id"] for command in commands}) == 1
        assert {command["transaction_size"] for command in commands} == {2}
        assert {command["transaction_index"] for command in commands} == {0, 1}

        for task in tasks:
            slot = world.solver_slots[task.slot_id]
            plan = slot.data["writeback_plan"]
            assert "spec" not in slot.data
            assert "armature" not in plan
            assert all(
                "pose_bone" not in record
                for batch in plan["batches"]
                for record in batch["records"]
            )

        # 让“第一部分已经写入”变得可观察，再破坏第二个 result 的目标。
        for index, name in enumerate(bone_names):
            armature.pose.bones[name].matrix_basis = mathutils.Matrix.Rotation(
                0.11 * (index + 1),
                4,
                "Z",
            )
        previous = {
            name: armature.pose.bones[name].matrix_basis.copy()
            for name in bone_names
        }
        second_plan = world.solver_slots[tasks[1].slot_id].data["writeback_plan"]
        second_batch = second_plan["batches"][0]
        records = list(second_batch["records"])
        records[0] = dict(records[0], bone_name="__deleted_target__")
        second_batch["records"] = tuple(records)

        assert writeback.writeback_bone_transforms(world) == 0
        assert writeback.get_bone_writeback_diagnostics(world)["receipts"] == []
        assert writeback.get_bone_writeback_receipts(world) == ()
        for name in bone_names:
            np.testing.assert_allclose(
                _matrix_values(armature.pose.bones[name].matrix_basis),
                _matrix_values(previous[name]),
                rtol=0.0,
                atol=1.0e-7,
            )
        assert all(
            world.solver_slots[task.slot_id].data.get("_writeback_error")
            for task in tasks
        )
    finally:
        world.omni_cache_dispose("bone_xpbd_atomic_writeback_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_failed_writeback_keeps_last_confirmed_feedback_source():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)
        source_pose = {
            name: armature.pose.bones[name].matrix.copy()
            for name in bone_names
        }

        _set_frame(world, 1)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        assert writeback.writeback_bone_transforms(world) == len(bone_names)

        _set_frame(world, 2)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        frame_two_command = _batch_result(world)
        assert writeback.writeback_bone_transforms(world) == len(bone_names)
        bpy.context.view_layer.update()
        written_pose = {
            name: armature.pose.bones[name].matrix.copy()
            for name in bone_names
        }
        assert any(
            not np.allclose(
                _matrix_values(written_pose[name]),
                _matrix_values(source_pose[name]),
                rtol=0.0,
                atol=1.0e-6,
            )
            for name in bone_names
        )

        _set_frame(world, 3)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        frame_three_command = _batch_result(world)
        assert frame_three_command["publication_id"] != frame_two_command["publication_id"]
        plan = world.solver_slots[task.slot_id].data["writeback_plan"]
        batch = plan["batches"][0]
        records = list(batch["records"])
        records[0] = dict(records[0], bone_name="__failed_feedback_target__")
        batch["records"] = tuple(records)

        assert writeback.writeback_bone_transforms(world) == 0
        assert writeback.get_bone_writeback_diagnostics(world)["receipts"] == []
        receipts = writeback.get_bone_writeback_receipts(world)
        assert len(receipts) == 1
        assert receipts[0]["publication_id"] == frame_two_command["publication_id"]
        for name in bone_names:
            np.testing.assert_allclose(
                _matrix_values(armature.pose.bones[name].matrix),
                _matrix_values(written_pose[name]),
                rtol=0.0,
                atol=1.0e-6,
            )

        _set_frame(world, 4)
        staged = feedback.prepare_bone_xpbd_feedback(world, (task,))
        for name in bone_names:
            np.testing.assert_allclose(
                _matrix_values(staged.logical_pose_matrices[
                    (int(armature.as_pointer()), name)
                ]),
                _matrix_values(source_pose[name]),
                rtol=0.0,
                atol=1.0e-6,
            )
        entries = tuple(staged.state["bones"].values())
        assert any(entry["confirmed_writeback_basis"] is not None for entry in entries)
        assert all(entry["pending_writeback_basis"] is None for entry in entries)
    finally:
        world.omni_cache_dispose("bone_xpbd_failed_writeback_feedback_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_deleted_armature_result_cannot_write_recreated_object():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    replacement = None
    old_data = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)
        _set_frame(world, 1)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        command = _batch_result(world)
        old_object_ptr = int(command["armature_ptr"])
        old_data_ptr = int(command["armature_data_ptr"])
        old_data = armature.data

        # 保留旧 data datablock，确保同名重建也不可能复用双指针身份。
        bpy.data.objects.remove(armature, do_unlink=True)
        armature = None
        replacement, replacement_names, _points = _make_explicit_chain()
        assert int(replacement.data.as_pointer()) != old_data_ptr
        for index, name in enumerate(replacement_names):
            replacement.pose.bones[name].matrix_basis = mathutils.Matrix.Rotation(
                -0.09 * (index + 1),
                4,
                "X",
            )
        previous = {
            name: replacement.pose.bones[name].matrix_basis.copy()
            for name in replacement_names
        }

        assert writeback.writeback_bone_transforms(world) == 0
        assert world.solver_slots[task.slot_id].data.get("_writeback_error")
        assert world.backend_resources["_writeback_touched_pose_bones"] == {}
        for name in replacement_names:
            np.testing.assert_allclose(
                _matrix_values(replacement.pose.bones[name].matrix_basis),
                _matrix_values(previous[name]),
                rtol=0.0,
                atol=1.0e-7,
            )
        assert old_object_ptr > 0
    finally:
        world.omni_cache_dispose("bone_xpbd_deleted_target_complete")
        if replacement is not None:
            replacement_data = replacement.data
            bpy.data.objects.remove(replacement, do_unlink=True)
            if not replacement_data.users:
                bpy.data.armatures.remove(replacement_data)
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        if old_data is not None and old_data.name in bpy.data.armatures:
            bpy.data.armatures.remove(old_data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_task_parse_failure_clears_entire_solver_batch():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)
        _set_frame(world, 1)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        owner = world.solver_slots[task.slot_id].data["native_context"]
        assert owner.ready
        assert world.backend_resources[feedback.BONE_XPBD_FRAME_STATE_KEY]["bones"]
        _batch_result(world)
        feedback_state = world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ]

        _set_frame(world, 2)
        try:
            solver.step_bone_xpbd(world, [task, object()])
        except TypeError as exc:
            assert "Bone XPBD" in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了非法 task 值")

        assert not owner.ready
        assert all(
            slot.kind != names.BONE_XPBD_SLOT_KIND
            for slot in world.solver_slots.values()
        )
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
        assert world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ] is feedback_state
        failed_stats = results.get_bone_xpbd_stats_result(world)
        assert failed_stats["status"] == "error"
        assert failed_stats["slot_count"] == 0
    finally:
        world.omni_cache_dispose("bone_xpbd_parse_failure_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_armature_world_scale_rebuilds_collision_radii():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(
            armature,
            bone_names,
            tail_follow=True,
            collision_enabled=True,
        )
        _set_frame(world, 1)
        assert solver.step_bone_xpbd(world, [task])[0] == 1
        slot = world.solver_slots[task.slot_id]
        old_owner = slot.data["native_context"]
        old_radii = slot.data["world_collision_radii"]

        armature.scale = (2.5, 2.5, 2.5)
        bpy.context.view_layer.update()
        _set_frame(world, 2)
        assert solver.step_bone_xpbd(world, [task])[0] == 1
        slot = world.solver_slots[task.slot_id]
        new_radii = slot.data["world_collision_radii"]
        assert slot.data["native_context"] is not old_owner
        assert not old_owner.ready
        np.testing.assert_allclose(
            np.asarray(new_radii),
            np.asarray(old_radii) * 2.5,
            rtol=1.0e-6,
            atol=1.0e-7,
        )
        stats = results.get_bone_xpbd_stats_result(world)
        assert stats["reset_slot_count"] == 1
    finally:
        world.omni_cache_dispose("bone_xpbd_scale_dirty_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_bone_xpbd_single_debug_capture_does_not_stick_node_request():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)
        _set_frame(world, 1)
        assert solver.step_bone_xpbd(world, [task], debug_capture=True)[0] == 1
        slot = world.solver_slots[task.slot_id]
        assert "debug_capture" in slot.data
        assert not bool(slot.data.get("_debug_requested", False))

        _set_frame(world, 2)
        assert solver.step_bone_xpbd(world, [task], debug_capture=False)[0] == 1
        slot = world.solver_slots[task.slot_id]
        assert "debug_capture" not in slot.data
        assert not bool(slot.data.get("_debug_requested", False))

        slot.data["_debug_requested"] = True
        _set_frame(world, 3)
        assert solver.step_bone_xpbd(world, [task], debug_capture=False)[0] == 1
        slot = world.solver_slots[task.slot_id]
        assert not bool(slot.data.get("_debug_requested", False))
        assert "debug_capture" in slot.data

        _set_frame(world, 4)
        assert solver.step_bone_xpbd(world, [task], debug_capture=False)[0] == 1
        slot = world.solver_slots[task.slot_id]
        assert "debug_capture" not in slot.data
    finally:
        world.omni_cache_dispose("bone_xpbd_debug_capture_scope_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


def test_shared_xpbd_step_dispatches_real_bone_task_and_prunes_it():
    added_binding, registered_class = _ensure_bone_collision_property()
    armature = None
    world = world_types.PhysicsWorldCache()
    world.generation = 1
    try:
        armature, bone_names, _rest_points = _make_explicit_chain()
        task = _make_task(armature, bone_names, tail_follow=True)

        _set_frame(world, 1, restart=True)
        writeback_count, _elapsed = family_solver.step_xpbd_tasks(
            world,
            [task],
            debug_capture=True,
        )
        assert writeback_count == 1
        assert task.slot_id in world.solver_slots
        assert _batch_result(world)["slot_id"] == task.slot_id
        assert writeback.writeback_bone_transforms(world) == len(bone_names)

        _set_frame(world, 2)
        writeback_count, _elapsed = family_solver.step_xpbd_tasks(world, [])
        assert writeback_count == 0
        assert task.slot_id not in world.solver_slots
        assert world.consume_results(
            world_names.BONE_TRANSFORM_CHANNEL,
            solver=names.BONE_XPBD_SOLVER_ID,
        ) == []
    finally:
        world.omni_cache_dispose("bone_xpbd_shared_step_complete")
        if armature is not None:
            data = armature.data
            bpy.data.objects.remove(armature, do_unlink=True)
            if not data.users:
                bpy.data.armatures.remove(data)
        _remove_bone_collision_property(added_binding, registered_class)


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Bone XPBD Blender integration: {len(tests)} passed")
