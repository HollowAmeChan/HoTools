"""Mesh XPBD 任务规格与 solver 声明的纯宿主测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types


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

mesh_xpbd = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd")
declaration = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.declaration"
)
specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.mesh_xpbd.specs")
registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")


class _Data:
    def __init__(self, pointer: int):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Object:
    def __init__(self, pointer: int, data_pointer: int, name: str = "Cloth"):
        self._pointer = pointer
        self.data = _Data(data_pointer)
        self.type = "MESH"
        self.name = self.name_full = name

    def as_pointer(self):
        return self._pointer


def test_default_task_is_stable_and_collision_opt_in():
    task = specs.MeshXpbdTaskSpec(_Object(101, 201))
    assert task.slot_id == "mesh_xpbd:101:201"
    assert task.collided_by_groups == 0
    assert task.collision_enabled is False
    assert task.debug_dict()["schema"] == "mesh_xpbd_task_v1"
    assert len(task.signature) == 16


def test_static_and_parameter_signatures_have_separate_dirty_boundaries():
    source = _Object(102, 202)
    baseline = specs.MeshXpbdTaskSpec(source)
    parameter_change = specs.MeshXpbdTaskSpec(source, iterations=12)
    static_change = specs.MeshXpbdTaskSpec(
        source,
        pin_enabled=True,
        pin_vertex_group="Pin",
    )
    assert baseline.slot_id == parameter_change.slot_id == static_change.slot_id
    assert baseline.static_signature == parameter_change.static_signature
    assert baseline.parameter_signature != parameter_change.parameter_signature
    assert baseline.static_signature != static_change.static_signature


def test_build_flattens_values_and_rejects_duplicate_sources():
    first = specs.MeshXpbdTaskSpec(_Object(103, 203, "First"))
    second_payload = {
        "source_object": _Object(104, 204, "Second"),
        "collided_by_groups": 3,
    }
    result = specs.build_mesh_xpbd_task_specs([first, [second_payload]])
    assert tuple(item.source_name for item in result) == ("First", "Second")
    try:
        specs.build_mesh_xpbd_task_specs([first, first])
    except ValueError as exc:
        assert "source 重复" in str(exc)
    else:
        raise AssertionError("重复 Mesh XPBD source 被接受")


def test_invalid_task_values_fail_instead_of_silent_clamping():
    source = _Object(105, 205)
    invalid_values = (
        {"damping": 1.1},
        {"iterations": 6.5},
        {"iterations": 65},
        {"collided_by_groups": 1.5},
        {"collided_by_groups": 0x10000},
        {"gravity_direction": (0.0, float("nan"), 0.0)},
        {"stretch_compliance": -1.0},
    )
    for overrides in invalid_values:
        try:
            specs.MeshXpbdTaskSpec(source, **overrides)
        except ValueError:
            continue
        raise AssertionError(f"非法 task 值被接受: {overrides}")


def test_non_mesh_and_invalid_identity_are_rejected():
    non_mesh = _Object(106, 206)
    non_mesh.type = "ARMATURE"
    for source in (non_mesh, _Object(0, 207), _Object(107, 0)):
        try:
            specs.MeshXpbdTaskSpec(source)
        except ValueError:
            continue
        raise AssertionError("非法 Mesh XPBD source 被接受")


def test_registry_discovers_contract_without_exposing_runtime_nodes():
    assert "mesh_xpbd" in registry.builtin_solver_domains()
    descriptor = registry.all_solver_module_descriptors()["mesh_xpbd"]
    resolved = registry.resolve_solver_declaration("mesh_xpbd")
    assert descriptor["nodes"] == ()
    assert resolved["runtime_status"].startswith("not_available")
    assert resolved["writers"] == []
    assert resolved["planned_writers"] == ["mesh_xpbd.step"]
    assert resolved["same_frame_policy"] == "republish_cached_result_without_time_step"
    assert resolved["collision"]["default_collided_by_groups"] == 0
    assert resolved["writeback"]["solver_inline_writeback"] is False
    assert resolved["produces"] == []
    assert "meshPhysicsXPBDCpp" in declaration.MESH_XPBD_LEGACY_SURFACES["python_nodes"]
    assert mesh_xpbd.SOLVER_MODULE["solver_id"] == "mesh_xpbd"


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Mesh XPBD specs: {len(tests)} passed")
