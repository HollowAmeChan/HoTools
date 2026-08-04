"""统一 XPBD 模拟步的强类型分域与失败事务。"""

from __future__ import annotations

import importlib
import os
import sys
import types


MESH_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XPBD_ROOT = os.path.dirname(MESH_XPBD_ROOT)
PHYSICS_WORLD = os.path.dirname(XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


family = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.family_solver"
)
mesh_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.simple_mesh_xpbd.names"
)
mesh_specs = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.simple_mesh_xpbd.specs"
)
bone_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.names"
)
bone_objects = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.object_spec"
)
bone_specs = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.specs"
)
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


class _Identity:
    def as_pointer(self):
        return id(self)


class _MeshObject(_Identity):
    type = "MESH"
    name = "FamilyMesh"
    name_full = name

    def __init__(self):
        self.data = _Identity()


class _Armature(_Identity):
    type = "ARMATURE"
    name = "FamilyArmature"
    name_full = name

    def __init__(self):
        self.data = _Identity()
        self.data.bones = {
            "Bone": types.SimpleNamespace(use_connect=False),
        }
        self.pose = types.SimpleNamespace(
            bones={"Bone": types.SimpleNamespace(parent=None)}
        )


def _tasks():
    mesh_task = mesh_specs.MeshXpbdTaskSpec(_MeshObject())
    armature = _Armature()
    bone_object = bone_objects.BoneXpbdObjectSpec(armature, ("Bone",))
    bone_task = bone_specs.BoneXpbdTaskSpec(bone_object)
    return mesh_task, bone_task


def test_family_step_splits_mixed_tasks_and_runs_empty_domains():
    mesh_task, bone_task = _tasks()
    world = world_types.PhysicsWorldCache()
    calls = []
    original_mesh = family.step_mesh_xpbd
    original_bone = family.step_bone_xpbd
    try:
        family.step_mesh_xpbd = lambda _world, tasks, **_kwargs: (
            calls.append(("mesh", tuple(tasks))) or (len(tasks), 0.0)
        )
        family.step_bone_xpbd = lambda _world, tasks, **_kwargs: (
            calls.append(("bone", tuple(tasks))) or (len(tasks), 0.0)
        )
        count, elapsed_ms = family.step_xpbd_tasks(
            world,
            [[bone_task], mesh_task],
            debug_capture=True,
        )
        assert count == 2 and elapsed_ms >= 0.0
        assert calls == [("mesh", (mesh_task,)), ("bone", (bone_task,))]

        calls.clear()
        count, _elapsed_ms = family.step_xpbd_tasks(world, [bone_task])
        assert count == 1
        assert calls == [("mesh", ()), ("bone", (bone_task,))]
    finally:
        family.step_mesh_xpbd = original_mesh
        family.step_bone_xpbd = original_bone
        world.omni_cache_dispose("xpbd_family_split_test")


def test_family_failure_discards_both_domain_slots_and_results():
    mesh_task, bone_task = _tasks()
    world = world_types.PhysicsWorldCache()
    disposed = []
    for slot_id, kind in (
        (mesh_task.slot_id, mesh_names.MESH_XPBD_SLOT_KIND),
        (bone_task.slot_id, bone_names.BONE_XPBD_SLOT_KIND),
    ):
        slot = world.ensure_solver_slot(slot_id, kind)
        slot.data["_dispose"] = (
            lambda reason, slot_id=slot_id: disposed.append((slot_id, reason))
        )
    world.result_streams = {
        "gn_attribute": [{"solver": mesh_names.MESH_XPBD_SOLVER_ID}],
        "bone_transform": [{"solver": bone_names.BONE_XPBD_SOLVER_ID}],
        mesh_names.MESH_XPBD_STATS_CHANNEL: [
            {"solver": mesh_names.MESH_XPBD_SOLVER_ID}
        ],
        bone_names.BONE_XPBD_STATS_CHANNEL: [
            {"solver": bone_names.BONE_XPBD_SOLVER_ID}
        ],
    }
    feedback_state = {"generation": 0, "bones": {"sentinel": object()}}
    world.backend_resources["bone_xpbd.frame_state"] = feedback_state
    original_mesh = family.step_mesh_xpbd
    original_bone = family.step_bone_xpbd
    try:
        family.step_mesh_xpbd = lambda _world, tasks, **_kwargs: (len(tasks), 0.0)

        def fail_bone(_world, _tasks, **_kwargs):
            raise RuntimeError("Bone域失败")

        family.step_bone_xpbd = fail_bone
        try:
            family.step_xpbd_tasks(world, [mesh_task, bone_task])
        except RuntimeError as exc:
            assert "Bone域失败" in str(exc)
        else:
            raise AssertionError("统一XPBD模拟步接受了半批域失败")

        assert world.solver_slots == {}
        assert {item[0] for item in disposed} == {mesh_task.slot_id, bone_task.slot_id}
        assert all(
            item.get("solver") not in {
                mesh_names.MESH_XPBD_SOLVER_ID,
                bone_names.BONE_XPBD_SOLVER_ID,
            }
            for items in world.result_streams.values()
            for item in items
        )
        assert world.backend_resources["bone_xpbd.frame_state"] is feedback_state
    finally:
        family.step_mesh_xpbd = original_mesh
        family.step_bone_xpbd = original_bone
        world.omni_cache_dispose("xpbd_family_failure_test")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"XPBD family solver: {len(tests)} passed")
