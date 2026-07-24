"""MC2 产品批处理的请求式阶段计时验收。"""

from __future__ import annotations

import importlib
import os
import sys


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_mixed_output_soak as mixed


timing_module = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.timing"
)


def _step(world, request, frame: int, generation: int, *, enabled: bool):
    mixed.bone_soak._set_frame(world, frame, generation)
    world.collider_snapshot = {"frame": frame, "colliders": []}
    returned, ready, status = mixed.nodes.physicsMC2Step(
        world,
        [request],
        simulation_frequency=60,
        max_simulation_count_per_frame=1,
        hotspot_timing=enabled,
    )
    assert returned is world and ready is True, status


world = mixed.world_types.PhysicsWorldCache()
mesh = proxy = None
try:
    mixed.physics_blender.register()
    mesh, proxy = mixed._mesh_object("MC2ProductTimingMesh")
    request = mixed._mesh_request(world, mesh)

    _step(world, request, 1, 1401, enabled=False)
    assert timing_module.MC2_HOTSPOT_TIMING_RESOURCE_KEY not in world.backend_resources

    timing_module.MC2HotspotTimingProfile.PRINT_INTERVAL = 1000.0
    for frame in range(2, 5):
        _step(world, request, frame, 1401, enabled=True)
    profile = world.backend_resources[timing_module.MC2_HOTSPOT_TIMING_RESOURCE_KEY]
    assert profile._samples == 3
    assert {
        "统一域输入",
        "统一域采集",
        "统一域同步",
        "统一域Frame",
        "统一域求解",
        "统一域结果",
        "统一域发布",
    }.issubset(profile._stage_totals)
    assert {
        "CPU · StepBasic准备",
        "CPU · 子步参数构建",
        "CPU · 参数校验与碰撞体打包",
        "CPU · Integration",
        "CPU · 外部碰撞",
        "CPU Self · Primitive更新",
        "CPU Self · Grid构建与排序",
        "CPU Self · Contact构建",
        "CPU Self · 求解轮次1",
        "CPU Self · 求解轮次4",
        "CPU · Post/历史",
    }.issubset(profile._detail_totals), profile._detail_totals
    assert "CPU Self · Debug确认与快照" not in profile._detail_totals
    assert profile._action_totals["reused"] == 3
    assert profile._action_totals["updated"] == 0
    report = "\n".join(profile.format_report(profile._window_started + 1.0))
    assert "求解明细（包含于统一域求解）" in report
    assert "CPU · 外部碰撞" in report
    assert "CPU Self · Grid构建与排序" in report
    assert "CPU Self · 求解轮次1" in report
    print("MC2 Blender product timing: PASS")
finally:
    world.omni_cache_dispose("mc2_product_timing_cleanup")
    mixed._remove_mesh(mesh)
    mixed._remove_mesh(proxy)
    if mixed.physics_blender.is_registered():
        mixed.physics_blender.unregister()
