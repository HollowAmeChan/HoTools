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
physics_ui = importlib.import_module("HoTools.OmniNode.PhysicsWorld.ui")
physics_panels = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.ui.panels"
)
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)


class _RecordingLayout:
    """记录 Panel.draw 的结构调用，不依赖可见窗口。"""

    def __init__(self, events, path=()):
        self.events = events
        self.path = tuple(path)

    def _child(self, name):
        return _RecordingLayout(self.events, self.path + (str(name),))

    def grid_flow(self, **_kwargs):
        return self._child("grid")

    def row(self, **_kwargs):
        return self._child("row")

    def column(self, **_kwargs):
        return self._child("column")

    def panel(self, panel_id, *, default_closed=False):
        self.events.append(
            ("panel", self.path, str(panel_id), bool(default_closed))
        )
        return self._child(f"{panel_id}:header"), self._child(panel_id)

    def prop(self, _owner, name, **_kwargs):
        self.events.append(("prop", self.path, str(name)))

    def operator(self, operator_id, **_kwargs):
        self.events.append(("operator", self.path, str(operator_id)))
        return types.SimpleNamespace()

    def label(self, **_kwargs):
        return None

    def separator(self):
        return None


def _draw_events(panel_class, context):
    events = []
    panel_class.draw(
        types.SimpleNamespace(layout=_RecordingLayout(events)),
        context,
    )
    return tuple(events)


def _assert_registered() -> None:
    class UnreadableScene:
        def __getattribute__(self, _name):
            raise SystemError("unreadable RNA")

    domains = blender_registry.registered_blender_property_domains()
    assert domains[:2] == ("collision", "field")
    assert domains[-1] == "physics_ui"
    assert hasattr(bpy.types.Object, "hotools_field")
    assert hasattr(bpy.types.Scene, "ho_field_overlay_show")
    assert bpy.context.scene.ho_field_overlay_show is False
    assert field_visualization._scene_overlay_enabled(UnreadableScene()) is False
    assert "field_air_velocity" in physics_registry.all_component_capabilities()

    component_collectors = tuple(
        entry["domain"]
        for entry in physics_registry.iter_scope_collectors()
        if entry.get("kind") == "component"
    )
    assert component_collectors == ("field",)
    for handlers, callback in field_visualization._HANDLERS:
        assert callback in handlers


def _assert_empty_authoring():
    before = set(bpy.context.scene.objects)
    result = bpy.ops.object.empty_add(type="SPHERE")
    assert result == {"FINISHED"}
    created = tuple(obj for obj in bpy.context.scene.objects if obj not in before)
    assert len(created) == 1
    field_object = created[0]
    assert field_object.type == "EMPTY"
    field_object.hotools_field.field_type = "WIND"
    field_object.hotools_field.enabled = True
    assert field_object.hotools_field.enabled is True
    assert str(uuid.UUID(field_object.hotools_field.field_id)) == (
        field_object.hotools_field.field_id
    )
    assert bpy.context.view_layer.objects.active == field_object
    return field_object


def _assert_simple_field_ui(field_object) -> None:
    class_ids = {
        str(getattr(cls, "bl_idname", ""))
        for cls in physics_ui.PHYSICS_UI_CLASSES
    }
    assert "ho.field_create" not in class_ids
    assert "ho.field_create_wind" not in class_ids

    parent_events = _draw_events(
        physics_panels.PT_Hotools_PhysicsPanel,
        bpy.context,
    )
    assert not any(
        event[0] == "operator" and event[2].startswith("ho.field_create")
        for event in parent_events
    )

    props = field_object.hotools_field
    props.turbulence = 0.0
    events = _draw_events(
        physics_panels.PT_Hotools_Physics_Field,
        bpy.context,
    )
    property_events = tuple(event for event in events if event[0] == "prop")
    assert property_events[0][2] == "field_type"
    panel_events = tuple(event for event in events if event[0] == "panel")
    assert (
        "panel",
        (),
        "hotools_field_advanced",
        True,
    ) in panel_events
    assert not any(
        event[2] == "hotools_field_turbulence_details"
        for event in panel_events
    )
    for name in (
        "blend_weight",
        "priority",
        "scope_solver_ids",
        "scope_collection_ids",
        "scope_include_ids",
        "scope_exclude_ids",
        "scope_collision_groups",
    ):
        event = next(item for item in property_events if item[2] == name)
        assert "hotools_field_advanced" in event[1]

    props.turbulence = 0.5
    turbulent_events = _draw_events(
        physics_panels.PT_Hotools_Physics_Field,
        bpy.context,
    )
    assert (
        "panel",
        (),
        "hotools_field_turbulence_details",
        True,
    ) in turbulent_events


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
        field_object = _assert_empty_authoring()
        _assert_simple_field_ui(field_object)
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
