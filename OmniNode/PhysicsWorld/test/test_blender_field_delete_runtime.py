# -*- coding: utf-8 -*-
"""MC2 运行中删除活动 Field 的 Blender 后台回归。"""

from __future__ import annotations

import importlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_field_wind_soak as field_soak


mixed = field_soak.mixed
nodes = field_soak.mc2_nodes
parameters = field_soak.parameters
product_slot = field_soak.product_slot
physics_blender = field_soak.physics_blender
world_types = field_soak.world_types
physics_nodes = importlib.import_module("HoTools.OmniNode.PhysicsWorld.nodes")
field_debug_draw = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.debug_draw"
)
field_visualization = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.visualization"
)
field_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.names"
)


def _mesh_request(mesh):
    mesh_objects, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1
    entries, _domain_ids = nodes.physicsMC2MeshClothTask(
        mesh_objects,
        profile=field_soak._field_profile(
            setup_type="mesh_cloth",
            enabled=True,
        ),
    )
    requests, report = nodes.physicsMC2MeshCollector(entries)
    assert report and len(requests) == 1
    return requests[0]


def _step(world, scene, scope, requests):
    world, frame, _collider_count, _restart = physics_nodes.physicsWorldBegin(
        world,
        scene,
        scope,
        time_scale=1.0,
        substeps=4,
    )
    returned, ready, status = nodes.physicsMC2Step(
        world,
        list(requests),
        simulation_frequency=90,
        max_simulation_count_per_frame=4,
    )
    assert returned is world and ready is True, status
    debug_world, debug_status = physics_nodes.physicsFieldRuntimeDebugDraw(
        world,
        show_bounds=True,
        show_air_velocity=True,
        density=2,
        glyph_scale=0.15,
    )
    assert debug_world is world, debug_status
    assert "不可用" not in debug_status, debug_status
    assert frame == scene.frame_current
    return world


def _remove_mesh(mesh):
    if mesh is None or mesh.name not in bpy.data.objects:
        return
    data = mesh.data
    bpy.data.objects.remove(mesh, do_unlink=True)
    if data is not None and not data.users:
        bpy.data.meshes.remove(data)


def test_delete_active_field_during_mc2_runtime_is_safe() -> None:
    scene = bpy.context.scene
    old_frame = int(scene.frame_current)
    old_fps = int(scene.render.fps)
    old_fps_base = float(scene.render.fps_base)
    old_overlay = bool(getattr(scene, "ho_field_overlay_show", False))
    world = None
    mesh = proxy = field = None
    physics_blender.register()
    try:
        scene.render.fps = 60
        scene.render.fps_base = 1.0
        if hasattr(scene, "ho_field_overlay_show"):
            scene.ho_field_overlay_show = True
        field_visualization.register()
        mesh, proxy = mixed._mesh_object("FieldDeleteRuntimeMesh")
        field = field_soak._field_empty("FieldDeleteRuntimeField")
        scope = physics_nodes.physicsObjectScope(
            [mesh, field],
            include_passive_collision=False,
            include_bone_collision=False,
            include_rigid_body=False,
            include_rigid_constraint=False,
        )
        requests = (_mesh_request(mesh),)

        scene.frame_set(1)
        bpy.context.view_layer.update()
        world = _step(world, scene, scope, requests)
        scene.frame_set(2)
        bpy.context.view_layer.update()
        world = _step(world, scene, scope, requests)
        runtime = world.runtime_cache(
            field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1
        )
        old_runtime = runtime
        assert runtime.debug_snapshot()["field_count"] == 1
        slot_id = product_slot.make_mc2_product_slot_id(
            requests[0].setup_type,
            requests[0].domain_signature,
        )
        state = world.solver_slots[slot_id].data["owner"].inspect()["domain"]["kernel"]
        assert state["field_sample_count"] > 0

        # 保留旧 scope 中的 stale RNA 引用，模拟用户在播放/求值期间直接删除 Empty。
        bpy.data.objects.remove(field, do_unlink=True)
        field = None
        bpy.context.view_layer.update()

        for frame in (3, 4, 5):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            world = _step(world, scene, scope, requests)
            runtime = world.runtime_cache(
                field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1
            )
            assert runtime.debug_snapshot()["field_count"] == 0
            # 场删除后旧 native runtime 仍在退休队列中，防止帧回调中的旧 handle 悬空。
            assert old_runtime.live is True
            assert old_runtime.debug_snapshot()["field_count"] == 1
            slot = world.solver_slots[slot_id]
            output = slot.data["owner"].read_output()
            assert output.frame == frame
            assert np.isfinite(output.world_positions).all()
            state = slot.data["owner"].inspect()["domain"]["kernel"]
            assert state["field_runtime_handle"] == 0
            assert state["field_prepared_active"] is False
    finally:
        field_debug_draw.shutdown_field_runtime_debug_draw()
        field_visualization.unregister()
        if hasattr(scene, "ho_field_overlay_show"):
            scene.ho_field_overlay_show = old_overlay
        if isinstance(world, world_types.PhysicsWorldCache):
            world.omni_cache_dispose("field_delete_runtime_cleanup")
        if field is not None and field.name in bpy.data.objects:
            bpy.data.objects.remove(field, do_unlink=True)
        _remove_mesh(mesh)
        _remove_mesh(proxy)
        scene.render.fps = old_fps
        scene.render.fps_base = old_fps_base
        scene.frame_set(old_frame)


TESTS = tuple(
    (name, value)
    for name, value in sorted(globals().items())
    if name.startswith("test_") and callable(value)
)


def main() -> None:
    passed = 0
    for name, test in TESTS:
        test()
        passed += 1
        print(f"[通过] {name}")
    print(f"{passed}/{len(TESTS)} 项测试通过")


if __name__ == "__main__":
    main()
