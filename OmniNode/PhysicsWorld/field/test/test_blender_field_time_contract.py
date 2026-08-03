# -*- coding: utf-8 -*-
"""Physics World 场采样时间合同的 Blender 后台验收。

用法：
    blender.exe --factory-startup --background --python test_blender_field_time_contract.py
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import types

import bpy


FIELD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD_ROOT = os.path.dirname(FIELD_ROOT)
OMNINODE_ROOT = os.path.dirname(PHYSICS_WORLD_ROOT)
PACKAGE_ROOT = "hotools_field_time_contract_test"


def _ensure_package(name: str, path: str) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [path]
    module.__package__ = name
    sys.modules[name] = module


_ensure_package(PACKAGE_ROOT, OMNINODE_ROOT)
_ensure_package(f"{PACKAGE_ROOT}.PhysicsWorld", PHYSICS_WORLD_ROOT)
_ensure_package(
    f"{PACKAGE_ROOT}.PhysicsWorld.utils",
    os.path.join(PHYSICS_WORLD_ROOT, "utils"),
)

# 这组测试只审计公共时间状态机，不装载节点缓存和 solver/component registry。
mapping_stub = types.ModuleType(f"{PACKAGE_ROOT}.OmniNodeSocketMapping")
mapping_stub._OmniCache = type("_OmniCache", (), {})
sys.modules[mapping_stub.__name__] = mapping_stub

registry_stub = types.ModuleType(f"{PACKAGE_ROOT}.PhysicsWorld.registry")
registry_stub.run_scope_restart_handlers = lambda world, scope: None
registry_stub.run_world_replace_handlers = lambda previous_world, world, reason: None
registry_stub.collect_scope_physics_specs = lambda world, scope: None
registry_stub.run_world_dispose_handlers = lambda world, reason: None
sys.modules[registry_stub.__name__] = registry_stub

writeback_stub = types.ModuleType(f"{PACKAGE_ROOT}.PhysicsWorld.writeback")
writeback_stub.clear_all_deltas = lambda world: None
sys.modules[writeback_stub.__name__] = writeback_stub

world_module = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.world")
world_types = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.types")
world_time = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.world_time")


EMPTY_SCOPE = world_types.PhysicsObjectScope(
    (),
    include_passive_collision=False,
    include_bone_collision=False,
    include_rigid_body=False,
    include_rigid_constraint=False,
)


def _assert_seconds(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1.0e-12):
        raise AssertionError(f"{label}：期望 {expected:.16g} 秒，实际 {actual:.16g} 秒")


def _configure_scene(
    fps: int,
    fps_base: float,
    *,
    frame_start: int = 10,
) -> bpy.types.Scene:
    scene = bpy.context.scene
    scene.render.fps = int(fps)
    scene.render.fps_base = float(fps_base)
    scene.frame_start = int(frame_start)
    scene.frame_end = max(int(frame_start) + 100, int(scene.frame_end))
    return scene


def _begin(
    world,
    scene: bpy.types.Scene,
    frame: int,
    *,
    time_scale: float = 1.0,
    substeps: int = 1,
    reset: bool = False,
):
    scene.frame_set(int(frame))
    result = world_module.physicsWorldBegin(
        world,
        scene,
        EMPTY_SCOPE,
        time_scale=time_scale,
        substeps=substeps,
        reset=reset,
    )
    returned, returned_frame, collider_count, restart_required = result
    assert isinstance(returned, world_types.PhysicsWorldCache), "Begin 必须返回公共 world owner"
    assert returned_frame == int(frame), "Begin 返回帧号必须等于 Blender 当前帧"
    assert collider_count == 0, "空作用域不应产生碰撞体"
    assert restart_required is returned.frame_context.restart_required
    return returned


def test_blender_output_fps_matrix() -> None:
    """24/30/60 与 30000/1001 都必须直接决定 raw_dt。"""
    for fps, fps_base in ((24, 1.0), (30, 1.0), (60, 1.0), (30000, 1001.0)):
        scene = _configure_scene(fps, fps_base, frame_start=10)
        expected_raw_dt = float(fps_base) / float(fps)

        _assert_seconds(
            world_time.scene_output_fps(scene),
            float(fps) / float(fps_base),
            f"{fps}/{fps_base} 公共输出帧率",
        )
        _assert_seconds(
            world_time.scene_raw_dt_seconds(scene),
            expected_raw_dt,
            f"{fps}/{fps_base} 公共 raw_dt",
        )
        _assert_seconds(
            world_time.scene_timeline_time_seconds(
                scene,
                frame=11,
                origin_frame=10,
            ),
            expected_raw_dt,
            f"{fps}/{fps_base} 公共时间线",
        )

        world = _begin(None, scene, 10)
        fc = world.frame_context
        assert fc.restart_required is True
        _assert_seconds(fc.raw_dt, expected_raw_dt, f"{fps}/{fps_base} raw_dt")
        _assert_seconds(fc.dt, expected_raw_dt, f"{fps}/{fps_base} dt")
        _assert_seconds(fc.frame_step_dt, expected_raw_dt, f"{fps}/{fps_base} 帧步长")
        _assert_seconds(fc.timeline_time_seconds, 0.0, "起始帧时间线")
        _assert_seconds(fc.sample_time_seconds, 0.0, "起始帧采样时间")

        world = _begin(world, scene, 11)
        fc = world.frame_context
        assert fc.continuous is True and fc.restart_required is False
        _assert_seconds(fc.timeline_time_seconds, expected_raw_dt, "第二帧时间线")
        _assert_seconds(fc.sample_time_seconds, expected_raw_dt, "第二帧采样时间")


def test_frame_zero_initialization_and_same_frame() -> None:
    """frame=0 不能再与未初始化状态混淆。"""
    scene = _configure_scene(24, 1.0, frame_start=0)
    raw_dt = 1.0 / 24.0

    world = _begin(None, scene, 0, time_scale=0.5, substeps=2)
    fc = world.frame_context
    assert fc.initialized is True
    assert fc.previous_frame is None
    assert fc.restart_required is True and fc.same_frame is False
    _assert_seconds(fc.timeline_time_seconds, 0.0, "frame 0 首次时间线")
    _assert_seconds(fc.sample_time_seconds, 0.0, "frame 0 首次采样时间")

    world = _begin(world, scene, 0, time_scale=0.0, substeps=2)
    fc = world.frame_context
    assert fc.initialized is True
    assert fc.previous_frame == 0
    assert fc.same_frame is True and fc.restart_required is False
    _assert_seconds(fc.sample_time_seconds, 0.0, "frame 0 同帧不得累计")
    _assert_seconds(fc.frame_step_dt, raw_dt * 0.5, "frame 0 同帧保留实际步长")

    world = _begin(world, scene, 1, time_scale=0.0, substeps=2)
    fc = world.frame_context
    assert fc.continuous is True and fc.restart_required is False
    _assert_seconds(fc.timeline_time_seconds, raw_dt, "frame 1 时间线")
    _assert_seconds(fc.sample_time_seconds, raw_dt * 0.5, "frame 1 累计 frame 0 步长")


def test_time_scale_pause_and_resume() -> None:
    """世界倍率只缩放模拟步长，不能改变 Blender 时间线。"""
    scene = _configure_scene(24, 1.0, frame_start=1)
    raw_dt = 1.0 / 24.0

    world = _begin(None, scene, 1, time_scale=0.5)
    fc = world.frame_context
    _assert_seconds(fc.raw_dt, raw_dt, "半速 raw_dt")
    _assert_seconds(fc.dt, raw_dt * 0.5, "半速 dt")
    _assert_seconds(fc.sample_time_seconds, 0.0, "半速起点")

    world = _begin(world, scene, 2, time_scale=0.5)
    fc = world.frame_context
    _assert_seconds(fc.timeline_time_seconds, raw_dt, "半速第二帧时间线")
    _assert_seconds(fc.sample_time_seconds, raw_dt * 0.5, "半速第二帧采样时间")

    world = _begin(world, scene, 3, time_scale=0.0)
    fc = world.frame_context
    _assert_seconds(fc.timeline_time_seconds, raw_dt * 2.0, "暂停首帧时间线")
    _assert_seconds(fc.sample_time_seconds, raw_dt, "暂停前累计采样时间")
    _assert_seconds(fc.dt, 0.0, "暂停 dt")
    _assert_seconds(fc.frame_step_dt, 0.0, "暂停帧步长")

    world = _begin(world, scene, 4, time_scale=0.0)
    fc = world.frame_context
    _assert_seconds(fc.timeline_time_seconds, raw_dt * 3.0, "暂停连续帧时间线")
    _assert_seconds(fc.sample_time_seconds, raw_dt, "暂停不能推进采样时间")

    world = _begin(world, scene, 5, time_scale=0.5)
    fc = world.frame_context
    _assert_seconds(fc.sample_time_seconds, raw_dt, "恢复首帧不能补跑暂停时间")
    _assert_seconds(fc.frame_step_dt, raw_dt * 0.5, "恢复后的帧步长")

    world = _begin(world, scene, 6, time_scale=0.5)
    _assert_seconds(
        world.frame_context.sample_time_seconds,
        raw_dt * 1.5,
        "恢复后的下一连续帧",
    )


def test_same_frame_keeps_the_actual_step() -> None:
    """同帧改倍率只能更新参数，不能篡改上一轮真正采用的步长。"""
    scene = _configure_scene(30, 1.0, frame_start=10)
    raw_dt = 1.0 / 30.0

    world = _begin(None, scene, 10, time_scale=0.5, substeps=4)
    fc = world.frame_context
    first_step = raw_dt * 0.5
    first_substep_times = tuple(fc.substep_sample_time_seconds(i) for i in range(4))

    world = _begin(world, scene, 10, time_scale=0.0, substeps=4)
    fc = world.frame_context
    assert fc.same_frame is True and fc.continuous is False
    assert fc.restart_required is False
    _assert_seconds(fc.dt, 0.0, "同帧更新后的参数 dt")
    _assert_seconds(fc.frame_step_dt, first_step, "同帧保留的实际帧步长")
    _assert_seconds(fc.sample_time_seconds, 0.0, "同帧不得累计")
    assert tuple(fc.substep_sample_time_seconds(i) for i in range(4)) == first_substep_times

    world = _begin(world, scene, 11, time_scale=0.0, substeps=4)
    fc = world.frame_context
    _assert_seconds(fc.sample_time_seconds, first_step, "连续帧累计上一实际步长")
    _assert_seconds(fc.frame_step_dt, 0.0, "当前暂停步长")

    # 暂停帧内再改回 1 倍，也不能让下一帧凭空累计一次 raw_dt。
    world = _begin(world, scene, 11, time_scale=1.0, substeps=4)
    fc = world.frame_context
    _assert_seconds(fc.frame_step_dt, 0.0, "暂停帧同帧重求值仍保留零步长")
    world = _begin(world, scene, 12, time_scale=1.0, substeps=4)
    _assert_seconds(world.frame_context.sample_time_seconds, first_step, "同帧改参不得偷跑")


def test_restart_jump_and_rewind_do_not_catch_up() -> None:
    """跳帧、显式 reset 和倒放都从零采样时间冷启动。"""
    scene = _configure_scene(60, 1.0, frame_start=1)
    raw_dt = 1.0 / 60.0

    world = _begin(None, scene, 1)
    world = _begin(world, scene, 2)
    world = _begin(world, scene, 3)
    _assert_seconds(world.frame_context.sample_time_seconds, raw_dt * 2.0, "连续三帧累计")

    before_jump = world
    world = _begin(world, scene, 9)
    fc = world.frame_context
    assert world is not before_jump, "跳帧必须替换失效 world owner"
    assert fc.restart_required is True and fc.same_frame is False
    _assert_seconds(fc.timeline_time_seconds, raw_dt * 8.0, "跳帧后的 Blender 时间线")
    _assert_seconds(fc.sample_time_seconds, 0.0, "跳帧不得按帧差追赶")

    world = _begin(world, scene, 10)
    _assert_seconds(world.frame_context.sample_time_seconds, raw_dt, "跳帧后只累计一个连续步")

    world = _begin(world, scene, 10, reset=True, time_scale=0.5, substeps=2)
    fc = world.frame_context
    assert fc.restart_required is True and fc.reset_requested is True
    _assert_seconds(fc.sample_time_seconds, 0.0, "显式 reset 清零采样时间")
    _assert_seconds(fc.frame_step_dt, raw_dt * 0.5, "reset 后采用当前倍率")

    world = _begin(world, scene, 11, time_scale=0.5, substeps=2)
    _assert_seconds(world.frame_context.sample_time_seconds, raw_dt * 0.5, "reset 后连续一步")

    world = _begin(world, scene, 4, time_scale=0.5, substeps=2)
    fc = world.frame_context
    assert fc.restart_required is True
    _assert_seconds(fc.timeline_time_seconds, raw_dt * 3.0, "倒放后的 Blender 时间线")
    _assert_seconds(fc.sample_time_seconds, 0.0, "倒放冷启动采样时间")


def test_substep_sample_times() -> None:
    """子步时间是当前帧步长的等分起点，暂停时全部停在同一时刻。"""
    scene = _configure_scene(24, 1.0, frame_start=1)
    raw_dt = 1.0 / 24.0
    world = _begin(None, scene, 1, time_scale=0.5, substeps=4)
    fc = world.frame_context
    expected = tuple(raw_dt * 0.5 * index / 4.0 for index in range(4))
    for index, expected_time in enumerate(expected):
        _assert_seconds(fc.substep_sample_time_seconds(index), expected_time, f"子步 {index}")

    for invalid_index in (-1, 4):
        try:
            fc.substep_sample_time_seconds(invalid_index)
        except ValueError as exc:
            assert "substep_index" in str(exc)
        else:
            raise AssertionError(f"非法子步 {invalid_index} 必须失败")

    world = _begin(world, scene, 2, time_scale=0.0, substeps=4)
    fc = world.frame_context
    paused_time = raw_dt * 0.5
    for index in range(4):
        _assert_seconds(fc.substep_sample_time_seconds(index), paused_time, f"暂停子步 {index}")


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
    print(f"Physics Field 时间合同：{passed}/{len(TESTS)} 项测试通过")
    if passed != len(TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
