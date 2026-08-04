"""Bone XPBD 显式对象、任务与无深度拓扑的纯宿主测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import numpy as np


BONE_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XPBD_ROOT = os.path.dirname(BONE_XPBD_ROOT)
PHYSICS_WORLD = os.path.dirname(XPBD_ROOT)
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


object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.object_spec"
)
specs = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.specs"
)
topology = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.xpbd.bone_xpbd.topology"
)
registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")


class _Props:
    def __init__(self, pin=False):
        self.pin = bool(pin)
        self.collision_type = "NONE"
        self.radius = 0.05
        self.length = 0.2
        self.offset = (0.0, 0.0, 0.0)
        self.primary_collision_group = 1
        self.collided_by_groups = 0


class _Bone:
    def __init__(self, name, head, tail, pin=False):
        self.name = name
        self.head_local = tuple(head)
        self.tail_local = tuple(tail)
        self.length = float(np.linalg.norm(np.asarray(tail) - np.asarray(head)))
        self.hotools_collision = _Props(pin)


class _PoseBone:
    def __init__(self, bone, parent=None):
        self.name = bone.name
        self.bone = bone
        self.parent = parent
        self.scale = (1.0, 1.0, 1.0)


class _Collection(dict):
    def __iter__(self):
        return iter(self.values())


class _Data:
    def __init__(self, pointer, bones):
        self._pointer = pointer
        self.bones = _Collection((bone.name, bone) for bone in bones)

    def as_pointer(self):
        return self._pointer


class _Armature:
    def __init__(self, points, pins=(), pointer=101, data_pointer=201):
        self.type = "ARMATURE"
        self.name = self.name_full = "Rig"
        self._pointer = pointer
        bones = [
            _Bone(f"B{index}", points[index], points[index + 1], index in pins)
            for index in range(len(points) - 1)
        ]
        poses = []
        parent = None
        for bone in bones:
            pose = _PoseBone(bone, parent)
            poses.append(pose)
            parent = pose
        self.data = _Data(data_pointer, bones)
        self.pose = types.SimpleNamespace(
            bones=_Collection((pose.name, pose) for pose in poses)
        )

    def as_pointer(self):
        return self._pointer


def _source(armature, names):
    return {
        "armature": armature,
        "bone": names[0],
        "bone_collection_root": names[0],
        "bone_collection": list(names),
    }


def test_collection_values_are_deduplicated_without_mc2_control_bone_semantics():
    armature = _Armature(((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    value = _source(armature, ("B0", "B1"))
    objects = object_spec.read_bone_xpbd_panel_objects([value, value])
    assert len(objects) == 1
    assert objects[0].bone_names == ("B0", "B1")
    assert objects[0].collection_root == "B0"


def test_custom_object_uses_socket_pin_without_reading_panel_pin():
    armature = _Armature(((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    value = _source(armature, ("B0", "B1"))
    custom = object_spec.make_bone_xpbd_custom_objects(
        value,
        pin_enabled=True,
    )[0]
    assert custom.property_origin == "socket"
    assert custom.pin_overrides == (True, True)
    graph = topology.build_bone_xpbd_topology(specs.BoneXpbdTaskSpec(custom))
    assert graph.segment_pins.tolist() == [1, 1]
    assert graph.inverse_masses.tolist() == [0.0, 0.0, 0.0]


def test_task_defaults_tail_follow_and_keeps_writeback_out_of_static_signature():
    armature = _Armature(((0, 0, 0), (1, 0, 0)))
    obj = object_spec.read_bone_xpbd_panel_objects(_source(armature, ("B0",)))[0]
    follow = specs.BoneXpbdTaskSpec(obj)
    free = specs.BoneXpbdTaskSpec(obj, tail_follow=False)
    assert follow.tail_follow is True
    assert follow.slot_id == free.slot_id
    assert follow.static_signature == free.static_signature
    assert follow.parameter_signature != free.parameter_signature
    assert follow.bend_compliance == 0.0
    assert follow.iterations == 16


def test_rest_geometry_builds_shared_endpoint_graph_without_depth():
    armature = _Armature(
        ((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)),
        pins=(0, 3),
    )
    names = ("B0", "B1", "B2", "B3")
    obj = object_spec.read_bone_xpbd_panel_objects(_source(armature, names))[0]
    graph = topology.build_bone_xpbd_topology(specs.BoneXpbdTaskSpec(obj))
    assert graph.particle_count == 5
    assert graph.shared_endpoint_count == 3
    assert graph.endpoint_particles.tolist() == [[0, 1], [1, 2], [2, 3], [3, 4]]
    assert graph.stretch_indices.tolist() == [[0, 1], [1, 2], [2, 3], [3, 4]]
    assert graph.bend_indices.tolist() == [[0, 2], [1, 3], [2, 4]]
    assert graph.segment_pins.tolist() == [1, 0, 0, 1]
    assert graph.inverse_masses.tolist() == [0.0, 0.0, 1.0, 0.0, 0.0]
    assert "depth" not in graph.debug_dict()


def test_bone_pin_identity_participates_in_static_signature():
    armature = _Armature(
        ((0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)),
        pins=(0, 2),
    )
    names = ("B0", "B1", "B2")
    obj = object_spec.read_bone_xpbd_panel_objects(_source(armature, names))[0]
    first = topology.build_bone_xpbd_topology(specs.BoneXpbdTaskSpec(obj))
    armature.data.bones["B1"].hotools_collision.pin = True
    second = topology.build_bone_xpbd_topology(specs.BoneXpbdTaskSpec(obj))

    # 两端 Pin 已让全部共享粒子 fixed；骨级 Pin 身份仍必须触发静态更新，
    # 否则输出阶段无法知道中段是否应锁定完整最终 Pose。
    assert first.inverse_masses.tolist() == second.inverse_masses.tolist()
    assert first.segment_pins.tolist() == [1, 0, 1]
    assert second.segment_pins.tolist() == [1, 1, 1]
    assert first.static_signature != second.static_signature


def test_parent_relation_does_not_connect_noncoincident_endpoints():
    armature = _Armature(((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    armature.data.bones["B1"].head_local = (4.0, 0.0, 0.0)
    armature.data.bones["B1"].tail_local = (5.0, 0.0, 0.0)
    obj = object_spec.read_bone_xpbd_panel_objects(
        _source(armature, ("B0", "B1"))
    )[0]
    graph = topology.build_bone_xpbd_topology(specs.BoneXpbdTaskSpec(obj))
    assert graph.particle_count == 4
    assert graph.shared_endpoint_count == 0
    assert graph.stretch_indices.shape == (2, 2)
    assert graph.bend_indices.shape == (0, 2)


def test_task_batch_rejects_overlapping_bone_writeback():
    armature = _Armature(((0, 0, 0), (1, 0, 0)))
    obj = object_spec.read_bone_xpbd_panel_objects(_source(armature, ("B0",)))[0]
    task = specs.BoneXpbdTaskSpec(obj)
    try:
        specs.build_bone_xpbd_task_specs([task, task])
    except ValueError as exc:
        assert "重复" in str(exc) or "重叠" in str(exc)
    else:
        raise AssertionError("Bone XPBD 接受了重复写回目标")


def test_disabled_task_does_not_occupy_active_overlap_identity():
    armature = _Armature(((0, 0, 0), (1, 0, 0)))
    obj = object_spec.read_bone_xpbd_panel_objects(_source(armature, ("B0",)))[0]
    disabled = specs.BoneXpbdTaskSpec(obj, enabled=False)
    enabled = specs.BoneXpbdTaskSpec(obj, enabled=True)
    resolved = specs.build_bone_xpbd_task_specs((disabled, enabled))
    assert resolved == (disabled, enabled)
    assert tuple(task for task in resolved if task.enabled) == (enabled,)


def test_disabled_task_does_not_occupy_active_writeback_target():
    armature = _Armature(((0, 0, 0), (1, 0, 0), (2, 0, 0)))
    disabled_object = object_spec.read_bone_xpbd_panel_objects(
        _source(armature, ("B0",))
    )[0]
    active_object = object_spec.read_bone_xpbd_panel_objects(
        _source(armature, ("B0", "B1"))
    )[0]
    tasks = specs.build_bone_xpbd_task_specs((
        specs.BoneXpbdTaskSpec(disabled_object, enabled=False),
        specs.BoneXpbdTaskSpec(active_object, enabled=True),
    ))
    assert len(tasks) == 2
    assert [task.enabled for task in tasks] == [False, True]


def test_registry_discovers_bone_xpbd_as_xpbd_task_domain():
    assert "xpbd.bone_xpbd" in registry.builtin_solver_domains()
    descriptor = registry.all_solver_module_descriptors()["xpbd.bone_xpbd"]
    declaration = registry.resolve_solver_declaration("bone_xpbd")
    assert descriptor["menu_group"] == "xpbd"
    assert descriptor["menu_name"] == "XPBD"
    assert declaration["runtime_status"] == "available_experimental"
    assert declaration["writeback"]["solver_inline_writeback"] is False
    assert declaration["writeback"]["tail_follow_default"] is True
    assert declaration["limitations"]


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Bone XPBD contract: {len(tests)} passed")
