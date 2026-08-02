# -*- coding: utf-8 -*-
"""Field 的 undo、持久化与动画 Blender 后台验收。

用法：
    blender.exe --factory-startup --background --python test_blender_field_persistence.py
"""

from __future__ import annotations

import importlib
import math
import os
import shutil
import sys
import tempfile
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
field_implicit = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.implicit_objects"
)
field_properties = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.properties"
)
field_schema = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.schema"
)
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


UNDO_FIELD_NAME = "PW_Field_UndoPersistence"
ANIMATED_FIELDS = frozenset({
    "enabled",
    "status",
    "field_type",
    "shape",
    "speed_mps",
    "turbulence",
    "spatial_scale_m",
    "temporal_frequency_hz",
    "octaves",
    "lacunarity",
    "gain",
    "seed_u32",
    "blend_weight",
    "priority",
})
STATIC_FIELDS = frozenset({
    "field_id",
    "scope_solver_ids",
    "scope_collection_ids",
    "scope_include_ids",
    "scope_exclude_ids",
    "scope_collision_groups",
})


def _field_schema_names() -> tuple[str, ...]:
    return tuple(str(item["name"]) for item in field_schema.FIELD_RNA_FIELDS)


def _property_snapshot(props) -> dict:
    result = {}
    for declaration in field_schema.FIELD_RNA_FIELDS:
        name = str(declaration["name"])
        value = getattr(props, name)
        kind = str(declaration["property"])
        if kind == "bool":
            value = bool(value)
        elif kind == "int":
            value = int(value)
        elif kind == "float":
            value = float(value)
        else:
            value = str(value)
        result[name] = value
    return result


def _matrix_snapshot(matrix) -> tuple[tuple[float, ...], ...]:
    return tuple(
        tuple(float(matrix[row][column]) for column in range(4))
        for row in range(4)
    )


def _scene_scope(scene):
    return world_types.PhysicsObjectScope(tuple(scene.objects))


def _assert_handlers_registered_once() -> None:
    for handlers, callback in field_visualization._HANDLERS:
        assert sum(item is callback for item in handlers) == 1


def _refresh_preview(scene) -> dict:
    frozen = field_visualization.refresh_field_visualization(
        scene,
        bpy.context.evaluated_depsgraph_get(),
    )
    assert "error" not in frozen, frozen.get("error")
    return frozen


def test_animation_capability_is_explicit() -> None:
    names = frozenset(_field_schema_names())
    assert names == ANIMATED_FIELDS | STATIC_FIELDS
    props = bpy.context.scene.objects[0].hotools_field
    actual = frozenset(
        name
        for name in names
        if bool(props.bl_rna.properties[name].is_animatable)
    )
    assert actual == ANIMATED_FIELDS


def test_undo_redo_restores_identity_manifest_and_preview() -> str:
    scene = bpy.context.scene
    scene.ho_field_overlay_show = True
    scene.ho_field_overlay_mode = "COMBINED"
    assert bpy.ops.ed.undo_push(message="Field 空场景基线") == {"FINISHED"}

    assert bpy.ops.object.empty_add(type="SPHERE") == {"FINISHED"}
    obj = bpy.context.view_layer.objects.active
    assert obj is not None and obj.type == "EMPTY"
    obj.name = UNDO_FIELD_NAME
    props = obj.hotools_field
    props.field_id = str(uuid.uuid4())
    props.field_type = "WIND"
    props.status = "PREVIEW_ONLY"
    props.enabled = True
    props.shape = "BOX"
    props.speed_mps = 4.25
    props.turbulence = 0.35
    field_id = str(props.field_id)
    bpy.context.view_layer.update()

    frozen = _refresh_preview(scene)
    assert frozen["field_ids"] == (field_id,)
    world = world_types.PhysicsWorldCache()
    report = field_implicit.collect_scope_field_specs(world, _scene_scope(scene))
    assert report.registered_ids == (field_id,)
    assert tuple(entry["stable_id"] for entry in world.implicit_objects) == (field_id,)

    assert bpy.ops.ed.undo_push(message="Field 创建完成") == {"FINISHED"}
    assert bpy.ops.ed.undo() == {"FINISHED"}
    scene = bpy.context.scene
    assert bpy.data.objects.get(UNDO_FIELD_NAME) is None
    frozen = _refresh_preview(scene)
    assert frozen["field_ids"] == ()
    report = field_implicit.collect_scope_field_specs(world, _scene_scope(scene))
    assert report.removed_ids == (field_id,)
    assert world.implicit_objects == []

    assert bpy.ops.ed.redo() == {"FINISHED"}
    scene = bpy.context.scene
    obj = bpy.data.objects.get(UNDO_FIELD_NAME)
    assert obj is not None
    assert obj.hotools_field.field_id == field_id
    assert math.isclose(obj.hotools_field.speed_mps, 4.25)
    assert math.isclose(obj.hotools_field.turbulence, 0.35, abs_tol=1.0e-6)
    frozen = _refresh_preview(scene)
    assert frozen["field_ids"] == (field_id,)
    report = field_implicit.collect_scope_field_specs(world, _scene_scope(scene))
    assert report.registered_ids == (field_id,)
    assert tuple(entry["stable_id"] for entry in world.implicit_objects) == (field_id,)
    _assert_handlers_registered_once()
    return field_id


def _set_persistent_field_values(obj, field_id: str) -> None:
    props = obj.hotools_field
    values = {
        "enabled": True,
        "field_id": field_id,
        "status": "PREVIEW_ONLY",
        "field_type": "WIND",
        "shape": "BOX",
        "spatial_scale_m": 2.5,
        "temporal_frequency_hz": 1.25,
        "octaves": 5,
        "lacunarity": 2.5,
        "gain": 0.4,
        "seed_u32": 123456,
        "blend_weight": 0.75,
        "priority": 7,
        "scope_solver_ids": "rigid, mc2",
        "scope_collection_ids": "collection-a\ncollection-b",
        "scope_include_ids": "object-a, object-b",
        "scope_exclude_ids": "object-x",
        "scope_collision_groups": "1, 4, 16",
    }
    for name, value in values.items():
        setattr(props, name, value)


def _keyframe_field(obj) -> None:
    scene = bpy.context.scene
    for frame, speed, turbulence, z in (
        (1, 2.0, 0.1, 1.0),
        (11, 8.0, 0.9, 11.0),
    ):
        scene.frame_set(frame)
        obj.hotools_field.speed_mps = speed
        obj.hotools_field.turbulence = turbulence
        obj.location.z = z
        assert obj.keyframe_insert(
            data_path="hotools_field.speed_mps",
            frame=frame,
        )
        assert obj.keyframe_insert(
            data_path="hotools_field.turbulence",
            frame=frame,
        )
        assert obj.keyframe_insert(data_path="location", index=2, frame=frame)

    action = obj.animation_data.action
    assert action is not None
    for fcurve in action.fcurves:
        for point in fcurve.keyframe_points:
            point.interpolation = "LINEAR"
    scene.frame_set(11)
    bpy.context.view_layer.update()


def _assert_animation_evaluation(obj, scene) -> None:
    expected = {
        1: (2.0, 0.1, 1.0),
        6: (5.0, 0.5, 6.0),
        11: (8.0, 0.9, 11.0),
    }
    for frame, (speed, turbulence, z) in expected.items():
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        spec = field_properties.resolve_field_spec_v0(obj, depsgraph=depsgraph)
        assert math.isclose(spec.wind.speed_mps, speed, abs_tol=1.0e-6)
        assert math.isclose(spec.wind.turbulence, turbulence, abs_tol=1.0e-6)
        assert math.isclose(spec.volume.world_transform[2][3], z, abs_tol=1.0e-6)


def test_save_reload_and_animation(field_id: str, temp_dir: str) -> None:
    scene = bpy.context.scene
    obj = bpy.data.objects[UNDO_FIELD_NAME]
    _set_persistent_field_values(obj, field_id)
    obj.rotation_euler = (0.2, 0.3, 0.4)
    obj.scale = (2.0, 3.0, 4.0)
    _keyframe_field(obj)

    scene.ho_field_overlay_show = True
    scene.ho_field_overlay_mode = "COMBINED"
    scene.ho_field_overlay_show_bounds = False
    scene.ho_field_overlay_density = 4
    scene.ho_field_overlay_glyph_scale = 0.23
    before_props = _property_snapshot(obj.hotools_field)
    before_matrix = _matrix_snapshot(obj.matrix_world)
    before_overlay = (
        bool(scene.ho_field_overlay_show),
        str(scene.ho_field_overlay_mode),
        bool(scene.ho_field_overlay_show_bounds),
        int(scene.ho_field_overlay_density),
        float(scene.ho_field_overlay_glyph_scale),
    )

    blend_path = os.path.join(temp_dir, "field_persistence.blend")
    assert bpy.ops.wm.save_as_mainfile(
        filepath=blend_path,
        check_existing=False,
    ) == {"FINISHED"}
    assert bpy.ops.wm.open_mainfile(filepath=blend_path, load_ui=False) == {"FINISHED"}

    scene = bpy.context.scene
    obj = bpy.data.objects.get(UNDO_FIELD_NAME)
    assert obj is not None
    assert _property_snapshot(obj.hotools_field) == before_props
    assert _matrix_snapshot(obj.matrix_world) == before_matrix
    after_overlay = (
        bool(scene.ho_field_overlay_show),
        str(scene.ho_field_overlay_mode),
        bool(scene.ho_field_overlay_show_bounds),
        int(scene.ho_field_overlay_density),
        float(scene.ho_field_overlay_glyph_scale),
    )
    assert after_overlay == before_overlay

    action = obj.animation_data.action
    assert action is not None
    curves = {
        (curve.data_path, int(curve.array_index)): len(curve.keyframe_points)
        for curve in action.fcurves
    }
    assert curves[("hotools_field.speed_mps", 0)] == 2
    assert curves[("hotools_field.turbulence", 0)] == 2
    assert curves[("location", 2)] == 2

    _assert_animation_evaluation(obj, scene)
    frozen = _refresh_preview(scene)
    assert field_id in frozen["field_ids"]
    world = world_types.PhysicsWorldCache()
    report = field_implicit.collect_scope_field_specs(world, _scene_scope(scene))
    assert report.registered_ids == (field_id,)
    assert tuple(entry["stable_id"] for entry in world.implicit_objects) == (field_id,)
    _assert_handlers_registered_once()


def main() -> None:
    temp_dir = tempfile.mkdtemp(prefix="hotools_field_persistence_")
    physics_blender.register()
    try:
        test_animation_capability_is_explicit()
        print("[通过] Field 动画能力矩阵")
        field_id = test_undo_redo_restores_identity_manifest_and_preview()
        print("[通过] Field undo/redo 身份、manifest 与预览")
        test_save_reload_and_animation(field_id, temp_dir)
        print("[通过] Field .blend 往返与动画求值")
    finally:
        if physics_blender.is_registered():
            physics_blender.unregister()
        shutil.rmtree(temp_dir, ignore_errors=True)
    print("Physics Field persistence: PASS")


if __name__ == "__main__":
    main()
