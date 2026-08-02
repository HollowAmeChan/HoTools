# -*- coding: utf-8 -*-
"""场作者静态预览与 native 运行态调试的 Blender 后台回归。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


FIELD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD_ROOT = os.path.dirname(FIELD_ROOT)
OMNINODE_ROOT = os.path.dirname(PHYSICS_WORLD_ROOT)
HOTOOLS_ROOT = os.path.dirname(OMNINODE_ROOT)

for path in (HOTOOLS_ROOT, os.path.dirname(HOTOOLS_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS_ROOT),
    ("HoTools.OmniNode", OMNINODE_ROOT),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


field_package = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field")
field_names = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.names")
field_specs = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.specs")
field_native = importlib.import_module("HoTools.OmniNode.PhysicsWorld.field.native")
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)
field_debug_draw = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.debug_draw"
)
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")


class _CountingWorld(world_types.PhysicsWorldCache):
    def __init__(self):
        super().__init__()
        self.runtime_cache_reads = 0

    def runtime_cache(self, name: str):
        self.runtime_cache_reads += 1
        return super().runtime_cache(name)


def _runtime_world(*, scope=None):
    world = _CountingWorld()
    world.generation = 3
    frame_context = world.frame_context
    frame_context.initialized = True
    frame_context.frame = 12
    frame_context.generation = 3
    frame_context.sample_time_seconds = 0.5

    field = field_specs.FieldSpecV0(
        field_id="field-debug-wind",
        source_id="object:FieldDebugWind",
        status=field_names.FIELD_STATUS_ACTIVE,
        wind=field_specs.WindPayloadV0(speed_mps=2.0, turbulence=0.0),
        scope=scope or field_specs.FieldScopeV0(),
    )
    snapshot = field_specs.build_field_snapshot_v0(
        (field,),
        generation=3,
        frame=12,
        sample_time_seconds=0.5,
    )
    runtime = field_native.NativeFieldRuntimeV1.create(snapshot)
    world.set_runtime_cache(field_names.FIELD_SNAPSHOT_CACHE_KEY_V0, snapshot)
    world.set_runtime_cache(field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1, runtime)
    return world, runtime


def test_author_preview_is_static() -> None:
    assert field_visualization._author_static_time_seconds(bpy.context.scene) == 0.0
    assert all(
        handlers is not bpy.app.handlers.frame_change_post
        for handlers, _callback in field_visualization._HANDLERS
    )
    scene = bpy.context.scene
    field = field_specs.FieldSpecV0(
        field_id="field-author-static",
        source_id="object:FieldAuthorStatic",
        status=field_names.FIELD_STATUS_ACTIVE,
    )
    stage = types.SimpleNamespace(specs=(field,), diagnostics=())
    original_stage = field_visualization.stage_field_sources_v0
    original_enabled = field_visualization._scene_overlay_enabled
    try:
        field_visualization.stage_field_sources_v0 = lambda *_args, **_kwargs: stage
        field_visualization._scene_overlay_enabled = lambda _scene: True
        first = field_visualization.refresh_field_visualization(scene)
        scene.frame_set(int(scene.frame_current) + 1)
        second = field_visualization.refresh_field_visualization(scene)
        assert first["time_source"] == second["time_source"] == "AUTHOR_STATIC"
        assert first["sample_time_seconds"] == second["sample_time_seconds"] == 0.0
        assert first["snapshot_signature"] == second["snapshot_signature"]
    finally:
        field_visualization.stage_field_sources_v0 = original_stage
        field_visualization._scene_overlay_enabled = original_enabled
        field_visualization._DRAW_STORE.clear()


def test_component_owns_debug_lifecycle() -> None:
    descriptor = field_package.COMPONENT_MODULE
    assert descriptor["blender_lifecycle"] == ".debug_draw"
    assert descriptor["scope_collectors"] == (
        ".implicit_objects:collect_scope_field_specs",
        ".debug_draw:begin_field_runtime_debug_evaluation",
    )
    assert descriptor["world_dispose_handlers"] == (
        ".debug_draw:dispose_field_runtime_debug_draw_for_world",
    )


def test_runtime_debug_rejects_ambiguous_advanced_scope() -> None:
    advanced_scopes = (
        field_specs.FieldScopeV0(solver_ids=("mc2",)),
        field_specs.FieldScopeV0(include_ids=("Allowed",)),
        field_specs.FieldScopeV0(exclude_ids=("Blocked",)),
        field_specs.FieldScopeV0(collection_ids=("Cloth",)),
        field_specs.FieldScopeV0(collision_groups=(1,)),
    )
    original_native_sampler = field_native.NativeFieldRuntimeV1.sample_air_velocity

    def _forbidden_native_sampler(*_args, **_kwargs):
        raise AssertionError("缺少消费上下文时禁止 native 采样")

    try:
        field_native.NativeFieldRuntimeV1.sample_air_velocity = _forbidden_native_sampler
        for scope in advanced_scopes:
            world, runtime = _runtime_world(scope=scope)
            try:
                world_id = str(id(world))
                status = field_debug_draw.update_field_runtime_debug_draw_store(
                    world,
                    show_bounds=True,
                    show_air_velocity=True,
                )
                assert "空气速度=未绘制" in status, status
                stored = field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id)
                assert stored is not None
                assert stored["metadata"]["scope_blocked_field_ids"] == (
                    "field-debug-wind",
                )
                assert stored["metadata"]["sampled_field_count"] == 0
                assert stored["metadata"]["participating_sample_count"] == 0
                assert stored["line_vertex_count"] > 0
            finally:
                field_debug_draw.shutdown_field_runtime_debug_draw()
                runtime.dispose("test_cleanup")
    finally:
        field_native.NativeFieldRuntimeV1.sample_air_velocity = original_native_sampler
        field_debug_draw.shutdown_field_runtime_debug_draw()


def test_invalid_input_does_not_clear_another_world() -> None:
    world, runtime = _runtime_world()
    world_id = str(id(world))
    try:
        field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=True,
        )
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is not None
        status = field_debug_draw.update_field_runtime_debug_draw_store(
            None,
            show_bounds=True,
        )
        assert "物理世界无效" in status
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is not None
    finally:
        field_debug_draw.shutdown_field_runtime_debug_draw()
        runtime.dispose("test_cleanup")


def test_runtime_debug_uses_native_cache_and_world_time() -> None:
    world, runtime = _runtime_world()
    world_id = str(id(world))
    original_python_sampler = field_visualization.sample_air_velocity_v0

    def _forbidden_python_sampler(*_args, **_kwargs):
        raise AssertionError("运行态调试禁止调用 Python sampler")

    try:
        status = field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=False,
            show_air_velocity=False,
        )
        assert "不会读取缓存" in status
        assert world.runtime_cache_reads == 0
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is None

        field_visualization.sample_air_velocity_v0 = _forbidden_python_sampler
        status = field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=True,
            show_air_velocity=True,
            density=3,
            glyph_scale=0.15,
        )
        assert "WORLD_FRAME_START" in status, status
        stored = field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id)
        assert stored is not None
        draw_handle = field_debug_draw._FIELD_RUNTIME_DRAW_HANDLE
        assert draw_handle is not None
        assert stored["time_source"] == "WORLD_FRAME_START"
        assert stored["sample_time_seconds"] == 0.5
        assert stored["native_inspect"]["cache_owner"] == "NativeFieldRuntimeV1"
        assert stored["metadata"]["sample_count"] > 0
        assert stored["metadata"]["participating_sample_count"] > 0
        assert stored["metadata"]["sampled_field_count"] == 1
        assert stored["line_vertex_count"] > 0

        world.frame_context.sample_time_seconds = 0.75
        stale_status = field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=True,
        )
        assert "采样时间已过期" in stale_status, stale_status
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is None

        world.frame_context.sample_time_seconds = 0.5
        field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=True,
        )
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is not None

        field_debug_draw.begin_field_runtime_debug_evaluation(world, None)
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is None
        assert field_debug_draw._FIELD_RUNTIME_DRAW_HANDLE is draw_handle
        field_debug_draw.update_field_runtime_debug_draw_store(
            world,
            show_bounds=True,
        )
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is not None
        assert field_debug_draw._FIELD_RUNTIME_DRAW_HANDLE is draw_handle
        world.omni_cache_dispose("test")
        assert field_debug_draw.field_runtime_debug_draw_store_snapshot(world_id) is None
        assert field_debug_draw._FIELD_RUNTIME_DRAW_HANDLE is draw_handle
        assert runtime.live is False
    finally:
        field_visualization.sample_air_velocity_v0 = original_python_sampler
        field_debug_draw.shutdown_field_runtime_debug_draw()
        assert field_debug_draw._FIELD_RUNTIME_DRAW_HANDLE is None
        runtime.dispose("test_cleanup")


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


def main() -> None:
    for name, test in TESTS:
        test()
        print(f"[通过] {name}")
    print(f"场运行态调试：{len(TESTS)}/{len(TESTS)} 项测试通过")


if __name__ == "__main__":
    main()
