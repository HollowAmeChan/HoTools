"""Mesh XPBD Physics World slot/result 状态机的纯宿主测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import numpy as np


MESH_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MESH_XPBD_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
OMNINODE = os.path.dirname(FUNCTION)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

adapter_test = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.test.test_adapter"
)
names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.names")
xpbd_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.names"
)
results = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.results"
)
debug = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.debug")
solver = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.solver")
specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.specs")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


def _world(*, frame=1, restart=True, same_frame=False, dt=1.0 / 24.0):
    world = world_types.PhysicsWorldCache()
    world.generation = 4
    world.frame_context.frame = frame
    world.frame_context.restart_required = restart
    world.frame_context.same_frame = same_frame
    world.frame_context.dt = dt
    world.frame_context.substeps = 2
    return world


def _advance(world, *, frame, restart=False, same_frame=False, dt=1.0 / 24.0):
    world.frame_context.frame = frame
    world.frame_context.restart_required = restart
    world.frame_context.same_frame = same_frame
    world.frame_context.dt = dt


def _task(source, **overrides):
    values = {
        "source_object": source,
        "gravity_power": 9.8,
        "iterations": 4,
    }
    values.update(overrides)
    return specs.MeshXpbdTaskSpec(**values)


def _slot(world, task):
    return world.solver_slots[task.slot_id]


def _writebacks(world):
    return world.consume_results(
        names.GN_ATTRIBUTE_CHANNEL,
        solver=xpbd_names.MESH_XPBD_SOLVER_ID,
    )


def test_restart_step_same_frame_and_pause_have_distinct_native_decisions():
    source = adapter_test._Object()
    task = _task(source)
    world = _world()
    count, _elapsed = solver.step_mesh_xpbd(world, [task])
    assert count == 1
    slot = _slot(world, task)
    assert slot.data["native_context"].stats()["step_count"] == 0
    assert slot.data["native_context"].stats()["reset_count"] == 1
    np.testing.assert_allclose(_writebacks(world)[0]["local_offsets"], 0.0)
    assert results.get_mesh_xpbd_stats_result(world)["reset_slot_count"] == 1

    _advance(world, frame=2)
    solver.step_mesh_xpbd(world, [task])
    stepped = np.array(_writebacks(world)[0]["local_offsets"], copy=True)
    assert slot.data["native_context"].stats()["step_count"] == 1
    assert np.min(stepped[:, 2]) < 0.0
    assert results.get_mesh_xpbd_stats_result(world)["stepped_slot_count"] == 1

    _advance(world, frame=2, same_frame=True)
    solver.step_mesh_xpbd(world, [task])
    assert slot.data["native_context"].stats()["step_count"] == 1
    np.testing.assert_allclose(_writebacks(world)[0]["local_offsets"], stepped)
    assert results.get_mesh_xpbd_stats_result(world)["republished_slot_count"] == 1

    _advance(world, frame=3, dt=0.0)
    solver.step_mesh_xpbd(world, [task], debug_capture=True)
    assert slot.data["native_context"].stats()["step_count"] == 1
    assert "debug_capture" in slot.data
    assert slot.debug_snapshot()["summary"]["decision"] == "paused_republish"

    owner = slot.data["native_context"]
    disabled = _task(source, enabled=False)
    solver.step_mesh_xpbd(world, [disabled])
    assert task.slot_id not in world.solver_slots
    assert owner.ready is False
    assert _writebacks(world) == []


def test_debug_draw_request_captures_next_step_and_survives_context_rebuild():
    source = adapter_test._Object(pointer=105, data=adapter_test._Data(205))
    task = _task(source, collision_enabled=True, collision_radius=0.1)
    world = _world()
    solver.step_mesh_xpbd(world, [task])
    slot = _slot(world, task)
    assert "debug_capture" not in slot.data

    assert debug.request_mesh_xpbd_debug_capture(
        world,
        enabled=True,
        filters={"show_particles": True},
    ) == 1
    _advance(world, frame=2)
    solver.step_mesh_xpbd(world, [task])
    capture = slot.data["debug_capture"]
    assert capture["world_positions"].shape == (4, 3)
    assert capture["rest_world_positions"].shape == (4, 3)
    assert capture["loop_triangles"].shape == (2, 3)
    assert capture["inverse_masses"].shape == (4,)
    assert capture["world_collision_radii"].shape == (4,)
    assert capture["task"]["source_name"] == task.source_name
    for name in (
        "world_positions",
        "rest_world_positions",
        "local_offsets",
        "stretch_indices",
        "loop_triangles",
        "bend_indices",
        "inverse_masses",
        "world_collision_radii",
    ):
        assert capture[name].flags.writeable is False

    source.data.vertices.append(adapter_test._Value(co=(2, 2, 0), groups=[]))
    _advance(world, frame=3)
    solver.step_mesh_xpbd(world, [task])
    rebuilt_slot = _slot(world, task)
    assert debug.mesh_xpbd_debug_capture_requested(rebuilt_slot) is True
    assert rebuilt_slot.data["debug_capture"]["world_positions"].shape == (5, 3)

    debug.request_mesh_xpbd_debug_capture(world, enabled=False)
    assert debug.mesh_xpbd_debug_capture_requested(rebuilt_slot) is False
    assert "debug_capture" not in rebuilt_slot.data

    _advance(world, frame=4)
    solver.step_mesh_xpbd(world, [task], debug_capture=True)
    manual_capture = rebuilt_slot.data["debug_capture"]
    assert (
        rebuilt_slot.data[debug.MESH_XPBD_DEBUG_CAPTURE_SOURCE_KEY]
        == "solver"
    )
    debug.request_mesh_xpbd_debug_capture(world, enabled=False)
    assert rebuilt_slot.data["debug_capture"] is manual_capture


def test_multi_task_results_form_one_transaction_with_distinct_slots():
    first = _task(adapter_test._Object(pointer=111, data=adapter_test._Data(211)))
    second = _task(adapter_test._Object(pointer=112, data=adapter_test._Data(212)))
    world = _world()
    count, _elapsed = solver.step_mesh_xpbd(world, [first, [second]])
    assert count == 2
    writebacks = _writebacks(world)
    assert {item["slot_id"] for item in writebacks} == {first.slot_id, second.slot_id}
    assert len({item["transaction_id"] for item in writebacks}) == 1
    assert sorted(item["transaction_index"] for item in writebacks) == [0, 1]
    assert all(item["transaction_size"] == 2 for item in writebacks)


def test_prepare_failure_does_not_advance_or_replace_existing_slot():
    first_source = adapter_test._Object(pointer=121, data=adapter_test._Data(221))
    first = _task(first_source)
    world = _world()
    solver.step_mesh_xpbd(world, [first])
    _advance(world, frame=2)
    slot = _slot(world, first)
    owner = slot.data["native_context"]
    before_steps = owner.stats()["step_count"]
    before_result = _writebacks(world)[0]

    invalid_source = adapter_test._Object(pointer=122, data=adapter_test._Data(222))
    invalid = _task(
        invalid_source,
        pin_enabled=True,
        pin_vertex_group="Missing",
    )
    try:
        solver.step_mesh_xpbd(world, [first, invalid])
    except ValueError as exc:
        assert "顶点组不存在" in str(exc)
    else:
        raise AssertionError("非法第二 task 被 Mesh XPBD solver 接受")
    assert _slot(world, first).data["native_context"] is owner
    assert owner.stats()["step_count"] == before_steps
    assert _writebacks(world)[0] is before_result


def test_static_change_resets_while_parameter_change_hot_updates():
    source = adapter_test._Object(pointer=131, data=adapter_test._Data(231))
    baseline = _task(source)
    world = _world()
    solver.step_mesh_xpbd(world, [baseline])
    _advance(world, frame=2)
    solver.step_mesh_xpbd(world, [_task(source, iterations=8)])
    slot = _slot(world, baseline)
    assert slot.data["native_context"].stats()["step_count"] == 1
    assert slot.debug_snapshot()["summary"]["decision"] == "step"

    source.vertex_groups["Pin"] = adapter_test._Value(index=3)
    source.data.vertices[0].groups = [adapter_test._Value(group=3, weight=1.0)]
    _advance(world, frame=3)
    pinned = _task(source, pin_enabled=True, pin_vertex_group="Pin", iterations=8)
    solver.step_mesh_xpbd(world, [pinned])
    assert slot.data["native_context"].stats()["step_count"] == 1
    assert slot.debug_snapshot()["summary"]["decision"] == "reset"
    np.testing.assert_allclose(_writebacks(world)[0]["local_offsets"], 0.0)


def test_particle_count_and_generation_changes_replace_native_context():
    source = adapter_test._Object(pointer=141, data=adapter_test._Data(241))
    task = _task(source)
    world = _world()
    solver.step_mesh_xpbd(world, [task])
    first_owner = _slot(world, task).data["native_context"]

    source.data.vertices.append(adapter_test._Value(co=(2, 2, 0), groups=[]))
    _advance(world, frame=2)
    solver.step_mesh_xpbd(world, [task])
    slot = _slot(world, task)
    second_owner = slot.data["native_context"]
    assert second_owner is not first_owner
    assert first_owner.ready is False
    assert slot.data["topology"].particle_count == 5
    assert slot.debug_snapshot()["summary"]["decision"] == "reset"

    world.generation += 1
    _advance(world, frame=3)
    solver.step_mesh_xpbd(world, [task])
    third_owner = _slot(world, task).data["native_context"]
    assert third_owner is not second_owner
    assert second_owner.ready is False

    world.omni_cache_dispose("lifecycle_test")
    assert third_owner.ready is False
    assert world.solver_slots == {}
    assert world.result_streams == {}


def test_matrix_reference_animation_preserves_context_and_inertia():
    source = adapter_test._Object(pointer=151, data=adapter_test._Data(251))
    task = _task(source)
    world = _world()
    solver.step_mesh_xpbd(world, [task])
    _advance(world, frame=2)
    solver.step_mesh_xpbd(world, [task])
    slot = _slot(world, task)
    owner = slot.data["native_context"]
    before_reset_count = owner.stats()["reset_count"]

    source.matrix_world = np.asarray((
        (1, 0, 0, 0.25),
        (0, 1, 0, -0.5),
        (0, 0, 1, 0.75),
        (0, 0, 0, 1),
    ), dtype=np.float32)
    _advance(world, frame=3)
    solver.step_mesh_xpbd(world, [task])
    assert _slot(world, task).data["native_context"] is owner
    assert owner.stats()["step_count"] == 2
    assert owner.stats()["reset_count"] == before_reset_count
    assert slot.debug_snapshot()["summary"]["decision"] == "step"


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Mesh XPBD solver: {len(tests)} passed")
