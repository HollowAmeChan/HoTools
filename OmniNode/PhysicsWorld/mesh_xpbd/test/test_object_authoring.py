"""Mesh XPBD 面板/自定义对象与任务分层的纯宿主测试。"""

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

authoring = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.authoring"
)
object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mesh_xpbd.object_spec"
)


class _Data:
    def __init__(self, pointer: int):
        self._pointer = pointer

    def as_pointer(self):
        return self._pointer


class _Object:
    def __init__(self, pointer: int, data_pointer: int, name: str):
        self._pointer = pointer
        self.data = _Data(data_pointer)
        self.type = "MESH"
        self.name = self.name_full = name
        self.hotools_mesh_collision = types.SimpleNamespace(
            enabled=True,
            radius_vertex_group="PanelRadius",
            pin_enabled=True,
            pin_vertex_group="PanelPin",
            collided_by_groups=0x0005,
            primary_collision_group=7,
            mc2_base_pose_proxy=object(),
        )

    def as_pointer(self):
        return self._pointer


def test_panel_object_snapshots_only_declared_xpbd_fields():
    source = _Object(101, 201, "Panel")
    result = object_spec.read_mesh_xpbd_panel_object(source)
    assert result.property_origin == "panel"
    assert result.properties.radius_vertex_group == "PanelRadius"
    assert result.properties.pin_enabled is True
    assert result.properties.pin_vertex_group == "PanelPin"
    assert result.properties.collided_by_groups == 0x0005
    assert "primary_collision_group" not in result.properties.debug_dict()
    assert "mc2_base_pose_proxy" not in result.properties.debug_dict()
    disabled = _Object(109, 209, "Disabled")
    disabled.hotools_mesh_collision.enabled = False
    assert object_spec.read_mesh_xpbd_panel_objects([source, disabled]) == (result,)
    try:
        object_spec.read_mesh_xpbd_panel_object(disabled)
    except ValueError as exc:
        assert "没有启用简单布料" in str(exc)
    else:
        raise AssertionError("disabled panel XPBD object was accepted")
    source.hotools_mesh_collision.collided_by_groups = 0
    assert result.properties.collided_by_groups == 0x0005


def test_custom_object_uses_socket_values_and_defaults_to_no_collision():
    source = _Object(102, 202, "Custom")
    custom = object_spec.make_mesh_xpbd_custom_object(source)
    assert custom.property_origin == "socket"
    assert custom.properties.collided_by_groups == 0
    assert custom.properties.pin_enabled is False
    explicit = object_spec.make_mesh_xpbd_custom_object(
        source,
        radius_vertex_group="SocketRadius",
        pin_enabled=True,
        pin_vertex_group="SocketPin",
        collided_by_groups=0x0010,
    )
    assert explicit.properties.radius_vertex_group == "SocketRadius"
    assert explicit.properties.pin_vertex_group == "SocketPin"
    assert explicit.properties.collided_by_groups == 0x0010


def test_task_combines_object_fields_with_shared_solver_parameters():
    first = object_spec.read_mesh_xpbd_panel_object(_Object(103, 203, "First"))
    second = object_spec.make_mesh_xpbd_custom_object(
        _Object(104, 204, "Second"),
        radius_vertex_group="CustomRadius",
        collided_by_groups=0x0020,
    )
    tasks = authoring.make_mesh_xpbd_tasks(
        [first, [second]],
        collision_enabled=True,
        collision_radius=0.125,
        damping=0.1,
        iterations=9,
    )
    assert tuple(task.source_name for task in tasks) == ("First", "Second")
    assert tuple(task.collided_by_groups for task in tasks) == (0x0005, 0x0020)
    assert tuple(task.radius_vertex_group for task in tasks) == (
        "PanelRadius", "CustomRadius"
    )
    assert all(task.collision_enabled for task in tasks)
    assert all(task.collision_radius == 0.125 for task in tasks)
    assert all(task.damping == 0.1 and task.iterations == 9 for task in tasks)


def test_task_rejects_raw_mesh_and_duplicate_object_sources():
    source = _Object(105, 205, "Raw")
    try:
        authoring.make_mesh_xpbd_tasks(source)
    except TypeError as exc:
        assert "只接受XPBD网格对象" in str(exc)
    else:
        raise AssertionError("XPBD网格任务接受了未包装的裸Mesh")

    wrapped = object_spec.make_mesh_xpbd_custom_object(source)
    try:
        authoring.make_mesh_xpbd_tasks([wrapped, wrapped])
    except ValueError as exc:
        assert "source 重复" in str(exc)
    else:
        raise AssertionError("XPBD网格任务接受了重复source")


def test_object_properties_reject_invalid_types_and_masks():
    for values in (
        {"pin_enabled": 1},
        {"collided_by_groups": 1.5},
        {"collided_by_groups": -1},
        {"collided_by_groups": 0x10000},
    ):
        try:
            object_spec.MeshXpbdObjectPropertiesSpec(**values)
        except (TypeError, ValueError):
            continue
        raise AssertionError(f"非法XPBD对象属性被接受: {values}")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Mesh XPBD object authoring: {len(tests)} passed")
