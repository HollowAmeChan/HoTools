"""
test_jolt_backend.py — hotools_jolt 后端模块基础功能测试
用法：
  Blender 5.2 内置 Python：python.exe test_jolt_backend.py
"""
import sys, os

# hotools_jolt 编译产物路径
_TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
_HOTOOLS_ROOT = os.path.abspath(os.path.join(_TEST_ROOT, *(("..",) * 4)))
_PY_LIB      = "py313" if sys.version_info >= (3, 13) else "py311"
_JOLT_LIB    = os.path.join(_HOTOOLS_ROOT, "_Lib", _PY_LIB, "HotoolsPackage")
_ADDON_ROOT  = os.path.dirname(_HOTOOLS_ROOT)

for p in [_JOLT_LIB, _HOTOOLS_ROOT, _ADDON_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 强制 stdout 使用 UTF-8，避免 GBK 编码问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import hotools_jolt
from OmniNode.PhysicsWorld.types import PhysicsWorldCache
from OmniNode.PhysicsWorld.rigid.implicit_objects import (
    make_rigid_jolt_world_setting_properties,
    register_rigid_jolt_world_setting_objects,
)
from OmniNode.PhysicsWorld.rigid.backends.jolt import ensure_jolt_adapter
from OmniNode.PhysicsWorld.rigid.scope_sync import reset_rigid_world_runtime
from OmniNode.PhysicsWorld.rigid.specs import RigidBodySpec

PASS = "[PASS]"
FAIL = "[FAIL]"

def run(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        return True
    except Exception as e:
        print(f"  {FAIL}  {name}  →  {e}")
        return False

# ─────────────────────────────────────────────────────────────────────────────

def test_create_world():
    jw = hotools_jolt.JoltWorld(max_bodies=32, max_body_pairs=64,
                                max_contact_constraints=32)
    assert jw.body_count == 0
    assert jw.constraint_count == 0
    jw.clear()

def test_worker_threads():
    single = hotools_jolt.JoltWorld(32, 64, 32, worker_threads=0)
    threaded = hotools_jolt.JoltWorld(32, 64, 32, worker_threads=2)
    single.set_solver_iterations(4, 1)
    assert single.worker_threads == 0
    assert threaded.worker_threads == 2
    threaded.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                      (0, 0, 3), (1, 0, 0, 0),
                      "SPHERE", 0.4, 0.4, (0.4, 0.4, 0.4))
    threaded.step(1 / 60.0, 2)
    single.clear()
    threaded.clear()

def test_optimization_switches():
    """Jolt 世界级优化开关应可显式设置，并保持逐项布尔语义。"""
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    assert hasattr(jw, "set_optimization_switches")
    jw.set_optimization_switches(False, False, False, False, False, False)
    jw.set_optimization_switches(True, True, True, True, True, True)
    jw.clear()

def test_node_worker_setting_replacement():
    world = PhysicsWorldCache()
    single_props = make_rigid_jolt_world_setting_properties(
        worker_threads=0, source_id="worker-test")
    register_rigid_jolt_world_setting_objects(world, single_props)
    single = ensure_jolt_adapter(world)
    assert single is not None and single.jolt_worker_threads == 0

    threaded_props = make_rigid_jolt_world_setting_properties(
        worker_threads=2, source_id="worker-test")
    register_rigid_jolt_world_setting_objects(world, threaded_props)
    threaded = ensure_jolt_adapter(world)
    assert threaded is not None and threaded is not single
    assert threaded.jolt_worker_threads == 2
    assert threaded._jw.worker_threads == 2
    threaded.dispose("worker-test")

def test_node_optimization_setting_replacement():
    world = PhysicsWorldCache()
    default_props = make_rigid_jolt_world_setting_properties(source_id="optimization-test")
    register_rigid_jolt_world_setting_objects(world, default_props)
    default = ensure_jolt_adapter(world)
    assert default is not None and default.jolt_constraint_warm_start is True

    tuned_props = make_rigid_jolt_world_setting_properties(
        source_id="optimization-test",
        constraint_warm_start=False,
    )
    register_rigid_jolt_world_setting_objects(world, tuned_props)
    tuned = ensure_jolt_adapter(world)
    assert tuned is not None and tuned is not default
    assert tuned.jolt_constraint_warm_start is False
    tuned.dispose("optimization-test")

def test_restart_flushes_native_bodies():
    world = PhysicsWorldCache()
    adapter = ensure_jolt_adapter(world)
    spec = RigidBodySpec(
        obj=None,
        obj_ptr=2,
        data_ptr=2,
        simulation_order_key=("test", "restart"),
        world_position=(0.0, 0.0, 3.0),
        shape_type="SPHERE",
    )
    assert adapter.sync_bodies_batch([("rigid:restart", spec)]) == {}
    assert adapter.body_count == 1
    reset_rigid_world_runtime(world, None, "test_restart")
    assert adapter.body_count == 0
    adapter.dispose("restart-test")

def test_adapter_batch_body_registration():
    world = PhysicsWorldCache()
    adapter = ensure_jolt_adapter(world)
    spec = RigidBodySpec(
        obj=None,
        obj_ptr=1,
        data_ptr=1,
        simulation_order_key=("test", "body"),
        world_position=(0.0, 0.0, 3.0),
        shape_type="SPHERE",
    )
    errors = adapter.sync_bodies_batch([("rigid:test", spec)])
    assert errors == {}, errors
    assert adapter.body_count == 1
    assert adapter.get_body_transform("rigid:test") is not None
    states = adapter.get_body_states()
    assert set(states) == {"rigid:test"}
    assert len(states["rigid:test"]["position"]) == 3
    columns = adapter.get_body_state_columns()
    assert columns is not None
    assert len(columns) == 7
    assert columns[-1] == {"rigid:test": 0}
    adapter.dispose("adapter-batch-test")


def test_adapter_start_deactivated_body():
    world = PhysicsWorldCache()
    adapter = ensure_jolt_adapter(world)
    spec = RigidBodySpec(
        obj=None,
        obj_ptr=3,
        data_ptr=3,
        simulation_order_key=("test", "start_deactivated"),
        world_position=(0.0, 0.0, 3.0),
        shape_type="SPHERE",
        start_deactivated=True,
    )
    assert adapter.sync_bodies_batch([("rigid:start_deactivated", spec)]) == {}
    before = adapter.get_body_state("rigid:start_deactivated")
    assert before is not None and before["active"] is False and before["sleeping"] is True
    for _ in range(10):
        adapter.step(1.0 / 60.0, 1)
    parked = adapter.get_body_state("rigid:start_deactivated")
    assert parked is not None and abs(parked["position"][2] - 3.0) < 1.0e-6
    assert adapter.set_body_active("rigid:start_deactivated", True) is True
    adapter.step(1.0 / 60.0, 1)
    falling = adapter.get_body_state("rigid:start_deactivated")
    assert falling is not None and falling["active"] is True
    assert falling["linear_velocity"][2] < 0.0
    adapter.dispose("adapter-start-deactivated-test")

def test_add_remove_bodies():
    jw = hotools_jolt.JoltWorld(32, 64, 32)

    g = jw.add_body("STATIC", 0, 0.5, 0.0,
                    (0, 0, 0), (1, 0, 0, 0),
                    "BOX", 0.5, 0.5, (5.0, 5.0, 0.1))
    assert jw.body_count == 1

    b = jw.add_body("DYNAMIC", 1.0, 0.5, 0.5,
                    (0, 0, 3), (1, 0, 0, 0),
                    "SPHERE", 0.4, 0.4, (0.4, 0.4, 0.4))
    assert jw.body_count == 2

    jw.remove_body(b)
    assert jw.body_count == 1

    jw.clear()
    assert jw.body_count == 0

def test_gravity_fall():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    jw.add_body("STATIC", 0, 0.5, 0.3,
                (0, 0, 0), (1, 0, 0, 0),
                "BOX", 0.5, 0.5, (10.0, 10.0, 0.1))
    ball = jw.add_body("DYNAMIC", 1.0, 0.5, 0.5,
                       (0, 0, 5), (1, 0, 0, 0),
                       "SPHERE", 0.5, 0.5, (0.5, 0.5, 0.5))

    pos0, _ = jw.get_body_transform(ball)
    z0 = pos0[2]

    for _ in range(30):
        jw.step(1/60.0, 2)

    pos1, _ = jw.get_body_transform(ball)
    z1 = pos1[2]

    assert z1 < z0, f"球体应下落：z0={z0:.3f} z1={z1:.3f}"
    jw.clear()


def test_batch_body_registration():
    jw = hotools_jolt.JoltWorld(32, 128, 64)
    if not hasattr(jw, "finalize_body_batch"):
        # 旧版 native ABI 使用逐体注册；Python 适配器会自动回退到该路径。
        jw.clear()
        return
    handles = []
    for index in range(8):
        handles.append(jw.add_body(
            "DYNAMIC", 1.0, 0.5, 0.0,
            (float(index) * 1.1, 0.0, 3.0), (1, 0, 0, 0),
            "BOX", 0.5, 0.5, (0.5, 0.5, 0.5),
            defer_add=True,
        ))
    assert jw.finalize_body_batch() == 8
    assert jw.body_count == 8
    jw.step(1 / 60.0, 1)
    for handle in handles:
        position, _rotation = jw.get_body_transform(handle)
        assert len(position) == 3
    jw.clear()

def test_set_gravity_zero():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    jw.set_gravity((0.0, 0.0, 0.0))
    ball = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                       (0, 0, 5), (1, 0, 0, 0),
                       "SPHERE", 0.5, 0.5, (0.5, 0.5, 0.5))
    for _ in range(10):
        jw.step(1/60.0, 1)
    _pos, _rot, lin, _ang, _active, _sleeping = jw.get_body_state(ball)
    assert abs(lin[2]) < 1e-4, f"零重力下 Z 线速度应接近 0，得到 {lin[2]}"
    jw.clear()

def test_body_state():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    ball = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                       (0, 0, 5), (1, 0, 0, 0),
                       "SPHERE", 0.5, 0.5, (0.5, 0.5, 0.5))
    jw.step(1/60.0, 2)
    pos, rot, lin, ang, active, sleeping = jw.get_body_state(ball)
    assert len(pos) == 3 and len(rot) == 4 and len(lin) == 3 and len(ang) == 3
    assert lin[2] < 0.0, f"重力后 Z 线速度应为负，得 {lin[2]}"
    assert isinstance(active, bool) and isinstance(sleeping, bool)
    jw.clear()

def test_bulk_body_state_and_contact_recording_switch():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    assert not hasattr(jw, "get_contact_events")
    assert hasattr(jw, "get_contact_events_numpy")
    assert jw.contact_event_count == 0
    assert jw.sensor_event_count == 0
    ground = jw.add_body("STATIC", 0, 0.5, 0.0,
                         (0, 0, 0), (1, 0, 0, 0),
                         "BOX", 0.5, 0.5, (5.0, 5.0, 0.1))
    ball = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                       (0, 0, 1), (1, 0, 0, 0),
                       "SPHERE", 0.5, 0.5, (0.5, 0.5, 0.5))
    states = jw.get_body_states()
    assert {item[0] for item in states} == {ground, ball}
    assert all(len(item[1]) == 3 and len(item[2]) == 4 for item in states)
    assert hasattr(jw, "get_body_states_numpy")
    columns = jw.get_body_states_numpy()
    assert len(columns) == 7
    assert len(columns[0]) == 2
    assert len(columns[1]) == 6 and len(columns[2]) == 8
    assert len(columns[3]) == 6 and len(columns[4]) == 6
    assert len(columns[5]) == 2 and len(columns[6]) == 2

    jw.set_record_contact_events(False)
    jw.step(1 / 60.0, 1)
    contact_snapshot = jw.get_contact_events_numpy()
    assert len(contact_snapshot) == 14
    assert len(contact_snapshot[0]) == 0
    assert jw.contact_event_count == 0
    assert jw.sensor_event_count == 0
    jw.set_record_contact_events(True)
    jw.clear()

def test_runtime_controls():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    ball = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                       (0, 0, 5), (1, 0, 0, 0),
                       "SPHERE", 0.5, 0.5, (0.5, 0.5, 0.5))
    ground = jw.add_body("STATIC", 0, 0.5, 0.0,
                         (0, 0, 0), (1, 0, 0, 0),
                         "BOX", 0.5, 0.5, (5.0, 5.0, 0.1))
    assert jw.set_body_velocity(ball, (0, 0, 2), (0, 0, 0.5)) is True
    _pos, _rot, lin, ang, _active, _sleeping = jw.get_body_state(ball)
    assert abs(lin[2] - 2.0) < 1e-4 and abs(ang[2] - 0.5) < 1e-4
    assert jw.add_body_impulse(ball, (0, 0, 1), (0, 0, 0.25)) is True
    _pos, _rot, lin2, ang2, _active, _sleeping = jw.get_body_state(ball)
    assert lin2[2] > lin[2] and ang2[2] > ang[2]
    assert jw.set_body_gravity_factor(ball, 0.0) is True
    assert jw.set_body_material_response(ball, 0.2, 0.8) is True
    assert jw.set_body_motion_quality(ball, "LINEAR_CAST") is True
    assert jw.activate_body(ball, False) is True
    assert jw.activate_body(ball, True) is True
    assert jw.set_body_velocity(ground, (0, 0, 1), (0, 0, 0)) is False
    assert jw.add_body_impulse(ground, (0, 0, 1), (0, 0, 0)) is False
    jw.clear()

def test_kinematic_drive():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    plat = jw.add_body("KINEMATIC", 0, 0.5, 0.0,
                       (0, 0, 0), (1, 0, 0, 0),
                       "BOX", 0.5, 0.5, (2.0, 2.0, 0.1))
    # 驱动到 z=3
    jw.set_kinematic_transform(plat, (0, 0, 3), (1, 0, 0, 0), 1/60.0)
    jw.step(1/60.0, 1)
    pos, _ = jw.get_body_transform(plat)
    assert abs(pos[2] - 3.0) < 0.2, f"平台应在 z≈3，实际 {pos[2]:.3f}"
    jw.clear()

def test_constraint():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    a = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                    (-1, 0, 5), (1, 0, 0, 0),
                    "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    b = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                    ( 1, 0, 5), (1, 0, 0, 0),
                    "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))

    c = jw.add_constraint("POINT", a, b, (0, 0, 5), (1, 0, 0, 0), disable_collisions=True)
    assert jw.constraint_count == 1

    for _ in range(20):
        jw.step(1/60.0, 2)

    jw.remove_constraint(c)
    assert jw.constraint_count == 0
    jw.clear()

def test_world_handle_constraint():
    """body_a = WORLD_HANDLE（固定到世界）"""
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    b = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                    (0, 0, 5), (1, 0, 0, 0),
                    "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    c = jw.add_constraint("FIXED",
                          hotools_jolt.WORLD_HANDLE, b,
                          (0, 0, 5), (1, 0, 0, 0))
    assert jw.constraint_count == 1
    for _ in range(10):
        jw.step(1/60.0, 1)
    pos, _ = jw.get_body_transform(b)
    assert abs(pos[2] - 5.0) < 0.5, f"FIXED 约束应限制下落，z={pos[2]:.3f}"
    jw.clear()

def test_clear_wipe():
    """clear() 应清空所有资源，body_count 和 constraint_count 归零"""
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    for _ in range(5):
        jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                    (0, 0, 3), (1, 0, 0, 0),
                    "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    assert jw.body_count == 5
    jw.clear()
    assert jw.body_count == 0 and jw.constraint_count == 0

def test_dispose_idempotent():
    """JoltAdapter.dispose() 幂等 —— 直接用 hotools_jolt 模拟 adapter 行为"""
    jw = hotools_jolt.JoltWorld(32, 64, 32)

    # 添加几个 body/constraint
    b1 = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                     (0, 0, 3), (1, 0, 0, 0),
                     "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    b2 = jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                     (0, 1, 3), (1, 0, 0, 0),
                     "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    jw.add_constraint("POINT", b1, b2, (0, 0.5, 3), (1, 0, 0, 0))

    # 第1次 dispose：clear() 清空所有
    jw.clear()
    assert jw.body_count == 0 and jw.constraint_count == 0

    # 第2次调用 clear() 不应崩溃（幂等）
    jw.clear()
    jw.clear()

    # 销毁后 del 不应崩溃
    del jw

def test_step_timing():
    jw = hotools_jolt.JoltWorld(32, 64, 32)
    jw.add_body("DYNAMIC", 1.0, 0.5, 0.0,
                (0, 0, 3), (1, 0, 0, 0),
                "SPHERE", 0.3, 0.3, (0.3, 0.3, 0.3))
    ms = jw.step(1/60.0, 2)
    assert isinstance(ms, float) and ms >= 0.0, f"step 应返回耗时 ms，得到 {ms!r}"
    jw.clear()

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        ("batch body registration",       test_batch_body_registration),
        ("Jolt worker_threads",            test_worker_threads),
        ("Jolt optimization switches",     test_optimization_switches),
        ("node worker setting replacement", test_node_worker_setting_replacement),
        ("node optimization setting replacement", test_node_optimization_setting_replacement),
        ("Jolt restart flushes native bodies", test_restart_flushes_native_bodies),
        ("adapter body batch registration", test_adapter_batch_body_registration),
        ("adapter start deactivated body", test_adapter_start_deactivated_body),
        ("创建 JoltWorld",          test_create_world),
        ("添加/删除刚体",           test_add_remove_bodies),
        ("重力下落验证",            test_gravity_fall),
        ("set_gravity 零重力",       test_set_gravity_zero),
        ("body state 输出",          test_body_state),
        ("bulk body state/contact recording", test_bulk_body_state_and_contact_recording_switch),
        ("runtime 控制 API",         test_runtime_controls),
        ("运动学 body 驱动",        test_kinematic_drive),
        ("约束 body-body",          test_constraint),
        ("约束 WORLD_HANDLE",       test_world_handle_constraint),
        ("clear() 清空验证",        test_clear_wipe),
        ("dispose() 幂等",          test_dispose_idempotent),
        ("step() 返回耗时ms",       test_step_timing),
    ]

    print("\n" + "─" * 42)
    print("  hotools_jolt 测试")
    print("─" * 42)

    passed = sum(run(name, fn) for name, fn in tests)
    total  = len(tests)

    print("─" * 42)
    if passed == total:
        print(f"  全部通过 {passed}/{total}  ✓")
    else:
        print(f"  {passed}/{total} 通过，{total - passed} 失败  ✗")
    print("─" * 42 + "\n")
    sys.exit(0 if passed == total else 1)
