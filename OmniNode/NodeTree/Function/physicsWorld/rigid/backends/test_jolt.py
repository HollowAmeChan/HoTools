"""
test_jolt.py — hotools_jolt 模块基础功能测试
用法：
  "D:\\Blender\\Blender 4.5\\4.5\\python\\bin\\python.exe" test_jolt.py
"""
import sys, os

# hotools_jolt 编译产物路径
_HOTOOLS_ROOT = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
_JOLT_LIB    = os.path.join(_HOTOOLS_ROOT, "_Lib", "py311", "HotoolsPackage")
_ADDON_ROOT  = os.path.dirname(_HOTOOLS_ROOT)

for p in [_JOLT_LIB, _HOTOOLS_ROOT, _ADDON_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

# 强制 stdout 使用 UTF-8，避免 GBK 编码问题
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import hotools_jolt

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
        ("创建 JoltWorld",          test_create_world),
        ("添加/删除刚体",           test_add_remove_bodies),
        ("重力下落验证",            test_gravity_fall),
        ("body state 输出",          test_body_state),
        ("运动学 body 驱动",        test_kinematic_drive),
        ("约束 body-body",          test_constraint),
        ("约束 WORLD_HANDLE",       test_world_handle_constraint),
        ("clear() 清空验证",        test_clear_wipe),
        ("dispose() 幂等",          test_dispose_idempotent),
        ("step() 返回耗时ms",       test_step_timing),
    ]

    print("\n" + "─" * 52)
    print("  hotools_jolt 测试")
    print("─" * 52)

    passed = sum(run(name, fn) for name, fn in tests)
    total  = len(tests)

    print("─" * 52)
    if passed == total:
        print(f"  全部通过 {passed}/{total}  ✓")
    else:
        print(f"  {passed}/{total} 通过，{total - passed} 失败  ✗")
    print("─" * 52 + "\n")
    sys.exit(0 if passed == total else 1)
