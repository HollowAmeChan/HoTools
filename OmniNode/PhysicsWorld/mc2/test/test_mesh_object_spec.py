"""MeshCloth 两种对象适配器的纯宿主合同测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types
from types import SimpleNamespace


MC2_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(MC2_ROOT)
FUNCTION = os.path.dirname(PHYSICS_WORLD)
NODETREE = os.path.dirname(FUNCTION)
OMNINODE = NODETREE
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.PhysicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)

object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2."
    "setups.mesh_cloth.object_spec"
)
MC2_MESH_EXPLICIT_PROPERTY_FIELDS = (
    object_spec.MC2_MESH_EXPLICIT_PROPERTY_FIELDS
)
make_mc2_mesh_custom_object = object_spec.make_mc2_mesh_custom_object
make_mc2_mesh_custom_objects = object_spec.make_mc2_mesh_custom_objects
read_mc2_mesh_panel_object = object_spec.read_mc2_mesh_panel_object
read_mc2_mesh_panel_objects = object_spec.read_mc2_mesh_panel_objects


class _Pointer:
    def __init__(self, pointer: int, *, object_type: str = "MESH"):
        self._pointer = pointer
        self.type = object_type
        self.name = self.name_full = f"Object{pointer}"
        self.data = SimpleNamespace(as_pointer=lambda: pointer + 1000)

    def as_pointer(self):
        return self._pointer


def _mesh(pointer=101, **panel_values):
    defaults = {
        "enabled": True,
        "mc2_base_pose_proxy": None,
        "radius_vertex_group": "Radius",
        "pin_enabled": True,
        "pin_vertex_group": "Pin",
        "primary_collision_group": 3,
        "collided_by_groups": 0b1010,
    }
    defaults.update(panel_values)
    source = _Pointer(pointer)
    source.hotools_mesh_collision = SimpleNamespace(**defaults)
    return source


def test_panel_and_socket_sources_share_identity_and_equal_values():
    source = _mesh()
    panel = read_mc2_mesh_panel_object(source)
    socket = make_mc2_mesh_custom_object(
        source,
        **panel.explicit_properties.debug_dict(),
    )
    assert panel.source_identity == socket.source_identity
    assert panel.signature == socket.signature
    assert panel.property_origin == "panel"
    assert socket.property_origin == "socket"


def test_custom_object_never_reads_panel_values():
    source = _mesh(primary_collision_group=9, collided_by_groups=0xFFFF)
    custom = make_mc2_mesh_custom_object(source)
    assert custom.explicit_properties.primary_collision_group == 1
    assert custom.explicit_properties.collided_by_groups == 0
    assert custom.explicit_properties.self_collision_groups == 1


def test_participation_enabled_is_not_an_explicit_property():
    assert "enabled" not in MC2_MESH_EXPLICIT_PROPERTY_FIELDS
    source = _mesh(enabled=True)
    spec = read_mc2_mesh_panel_object(source)
    assert "enabled" not in spec.explicit_properties.debug_dict()

    disabled = _mesh(102, enabled=False)
    assert read_mc2_mesh_panel_objects([source, disabled]) == (spec,)
    try:
        read_mc2_mesh_panel_object(disabled)
    except ValueError as exc:
        assert "没有启用简单布料" in str(exc)
    else:
        raise AssertionError("disabled panel MeshCloth was accepted")


def test_custom_object_list_applies_one_complete_property_set():
    first, second = _mesh(201), _mesh(202)
    specs = make_mc2_mesh_custom_objects(
        (first, [second]),
        primary_collision_group=4,
        collided_by_groups=5,
    )
    assert tuple(spec.source_object for spec in specs) == (first, second)
    assert tuple(
        spec.explicit_properties.primary_collision_group for spec in specs
    ) == (4, 4)
    assert tuple(
        spec.explicit_properties.self_collision_groups for spec in specs
    ) == (13, 13)


def test_invalid_source_and_collision_groups_fail_explicitly():
    try:
        make_mc2_mesh_custom_object(_Pointer(301, object_type="CURVE"))
    except TypeError as exc:
        assert "Mesh Object" in str(exc)
    else:
        raise AssertionError("non-Mesh source was accepted")

    for values in (
        {"primary_collision_group": 0},
        {"primary_collision_group": 17},
        {"collided_by_groups": -1},
        {"collided_by_groups": 0x10000},
    ):
        try:
            make_mc2_mesh_custom_object(_mesh(302), **values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid explicit properties accepted: {values!r}")


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"MC2 Mesh object spec: {len(tests)} passed")
