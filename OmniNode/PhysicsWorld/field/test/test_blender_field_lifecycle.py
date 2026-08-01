# -*- coding: utf-8 -*-
"""Field component、集中 UI 与 handler 的 Blender 后台生命周期验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types
import uuid

import bpy


FIELD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD_ROOT = os.path.dirname(FIELD_ROOT)
OMNINODE_ROOT = os.path.dirname(PHYSICS_WORLD_ROOT)
HOTOOLS_ROOT = os.path.dirname(OMNINODE_ROOT)
FUNCTION_ROOT = os.path.join(OMNINODE_ROOT, "Function")

for path in (HOTOOLS_ROOT, os.path.dirname(HOTOOLS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS_ROOT),
    ("HoTools.OmniNode", OMNINODE_ROOT),
    ("HoTools.OmniNode.Function", FUNCTION_ROOT),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


physics_blender = importlib.import_module("HoTools.OmniNode.PhysicsWorld.blender")
blender_registry = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.blender_registry"
)
physics_registry = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.registry"
)
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)


def _assert_registered() -> None:
    domains = blender_registry.registered_blender_property_domains()
    assert domains[:2] == ("collision", "field")
    assert domains[-1] == "physics_ui"
    assert hasattr(bpy.types.Object, "hotools_field")
    assert hasattr(bpy.types.Scene, "ho_field_overlay_show")
    assert "field_air_velocity" in physics_registry.all_component_capabilities()

    component_collectors = tuple(
        entry["domain"]
        for entry in physics_registry.iter_scope_collectors()
        if entry.get("kind") == "component"
    )
    assert component_collectors == ("field",)
    for handlers, callback in field_visualization._HANDLERS:
        assert callback in handlers


def _assert_create_operator() -> None:
    before = set(bpy.context.scene.objects)
    result = bpy.ops.ho.field_create_wind()
    assert result == {"FINISHED"}
    created = tuple(obj for obj in bpy.context.scene.objects if obj not in before)
    assert len(created) == 1
    field_object = created[0]
    assert field_object.type == "EMPTY"
    assert field_object.hotools_field.enabled is True
    assert str(uuid.UUID(field_object.hotools_field.field_id)) == (
        field_object.hotools_field.field_id
    )
    assert bpy.context.view_layer.objects.active == field_object


def _assert_unregistered() -> None:
    assert blender_registry.registered_blender_property_domains() == ()
    assert not hasattr(bpy.types.Object, "hotools_field")
    assert not hasattr(bpy.types.Scene, "ho_field_overlay_show")
    for handlers, callback in field_visualization._HANDLERS:
        assert callback not in handlers


def main() -> None:
    physics_blender.register()
    try:
        _assert_registered()
        _assert_create_operator()
    finally:
        if physics_blender.is_registered():
            physics_blender.unregister()
    _assert_unregistered()

    # 重复注册/注销必须幂等，避免 addon reload 留下 RNA 或 handler。
    physics_blender.register()
    _assert_registered()
    physics_blender.unregister()
    _assert_unregistered()
    print("Physics Field Blender lifecycle: PASS")


if __name__ == "__main__":
    main()
