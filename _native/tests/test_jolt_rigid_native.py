"""
test_jolt_rigid_native.py — hotools_jolt JoltWorld 单元测试

测试覆盖：
- 模块加载与常量
- STATIC / DYNAMIC / KINEMATIC 刚体注册与变换读取
- 形状：SPHERE / BOX / CAPSULE / CYLINDER / TAPERED_CAPSULE / TAPERED_CYLINDER / PLANE
- 模拟步：DYNAMIC 刚体受重力下落（Z-down）
- KINEMATIC 刚体位置跟随
- remove_body / clear()
- 约束注册与移除（FIXED / HINGE / POINT）
- set_gravity
"""
import os
import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
sys.path.insert(0, os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    str(ROOT / "_Lib" / PY_LIB / "HotoolsPackage"),
))

import hotools_jolt  # noqa: E402


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_world(**kw) -> hotools_jolt.JoltWorld:
    return hotools_jolt.JoltWorld(
        max_bodies=kw.get("max_bodies", 64),
        max_body_pairs=kw.get("max_body_pairs", 256),
        max_contact_constraints=kw.get("max_contact_constraints", 128),
    )


def _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 0.0), radius=0.5):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="SPHERE",
        shape_radius=radius,
    )


def _add_box(jw, body_type="STATIC", pos=(0.0, 0.0, 0.0), half_extents=(1.0, 1.0, 0.05)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="BOX",
        shape_half_extents=half_extents,
    )


def _add_capsule(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 0.0)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="CAPSULE",
        shape_radius=0.3,
        shape_half_height=0.4,
    )


def _add_cylinder(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 0.0)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="CYLINDER",
        shape_radius=0.35,
        shape_half_height=0.5,
        shape_convex_radius=0.03,
    )


def _add_tapered_capsule(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 0.0)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="TAPERED_CAPSULE",
        shape_top_radius=0.45,
        shape_bottom_radius=0.25,
        shape_half_height=0.5,
    )


def _add_tapered_cylinder(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 0.0)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="TAPERED_CYLINDER",
        shape_top_radius=0.45,
        shape_bottom_radius=0.25,
        shape_half_height=0.5,
        shape_convex_radius=0.02,
    )


def _add_plane(jw, body_type="STATIC", pos=(0.0, 0.0, 0.0), half_extents=(10.0, 10.0, 0.001)):
    return jw.add_body(
        body_type=body_type,
        mass=1.0,
        friction=0.5,
        restitution=0.0,
        position=pos,
        rotation_wxyz=(1.0, 0.0, 0.0, 0.0),
        shape_type="PLANE",
        shape_half_extents=half_extents,
        shape_plane_half_extent=max(float(half_extents[0]), float(half_extents[1])),
    )


# ---------------------------------------------------------------------------
# 测试：模块常量
# ---------------------------------------------------------------------------

def test_module_constants():
    """WORLD_HANDLE 和 INVALID_HANDLE 必须存在且值正确。"""
    assert hasattr(hotools_jolt, "WORLD_HANDLE"),   "缺少 WORLD_HANDLE 常量"
    assert hasattr(hotools_jolt, "INVALID_HANDLE"), "缺少 INVALID_HANDLE 常量"
    assert hotools_jolt.WORLD_HANDLE   == 0xFFFFFFFF, f"WORLD_HANDLE 值错误: {hotools_jolt.WORLD_HANDLE}"
    assert hotools_jolt.INVALID_HANDLE == 0,          f"INVALID_HANDLE 值错误: {hotools_jolt.INVALID_HANDLE}"


# ---------------------------------------------------------------------------
# 测试：JoltWorld 创建与属性
# ---------------------------------------------------------------------------

def test_world_creation():
    """JoltWorld 初始状态 body_count=0, constraint_count=0。"""
    jw = _make_world()
    assert jw.body_count == 0,       f"初始 body_count 应为 0，得 {jw.body_count}"
    assert jw.constraint_count == 0, f"初始 constraint_count 应为 0，得 {jw.constraint_count}"


# ---------------------------------------------------------------------------
# 测试：刚体注册（基础形状）
# ---------------------------------------------------------------------------

def test_add_sphere_body():
    jw = _make_world()
    h = _add_sphere(jw, pos=(0.0, 0.0, 5.0))
    assert jw.body_count == 1, "注册 SPHERE 后 body_count 应为 1"
    pos, rot = jw.get_body_transform(h)
    assert abs(pos[0]) < 1e-4 and abs(pos[1]) < 1e-4, "位置 XY 应接近 0"
    assert abs(pos[2] - 5.0) < 1e-3, f"位置 Z 应约为 5.0，得 {pos[2]}"
    jw.clear()


def test_add_box_body():
    jw = _make_world()
    h = _add_box(jw, body_type="STATIC", pos=(1.0, 2.0, 3.0))
    assert jw.body_count == 1
    pos, rot = jw.get_body_transform(h)
    assert abs(pos[0] - 1.0) < 1e-3, f"BOX X 应为 1.0，得 {pos[0]}"
    assert abs(pos[1] - 2.0) < 1e-3
    assert abs(pos[2] - 3.0) < 1e-3
    jw.clear()


def test_add_capsule_body():
    jw = _make_world()
    h = _add_capsule(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    assert jw.body_count == 1
    jw.clear()


def test_add_cylinder_body():
    jw = _make_world()
    _add_cylinder(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    assert jw.body_count == 1
    jw.step(1.0 / 60.0, 1)
    jw.clear()


def test_add_tapered_capsule_body():
    jw = _make_world()
    _add_tapered_capsule(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    assert jw.body_count == 1
    jw.step(1.0 / 60.0, 1)
    jw.clear()


def test_add_tapered_cylinder_body():
    jw = _make_world()
    _add_tapered_cylinder(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    assert jw.body_count == 1
    jw.step(1.0 / 60.0, 1)
    jw.clear()


def test_add_plane_body():
    jw = _make_world()
    h = _add_plane(jw, body_type="STATIC", pos=(0.0, 0.0, 0.0))
    assert jw.body_count == 1
    pos, _ = jw.get_body_transform(h)
    assert abs(pos[2]) < 1e-4, f"PLANE Z 应为 0.0，得 {pos[2]}"
    jw.clear()


def test_multiple_bodies():
    """注册多个刚体，body_count 正确递增。"""
    jw = _make_world()
    h1 = _add_sphere(jw, body_type="STATIC",   pos=(0.0, 0.0, -1.0))
    h2 = _add_sphere(jw, body_type="DYNAMIC",  pos=(0.0, 0.0,  2.0))
    h3 = _add_sphere(jw, body_type="KINEMATIC",pos=(0.0, 0.0,  5.0))
    assert jw.body_count == 3
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：remove_body
# ---------------------------------------------------------------------------

def test_remove_body():
    jw = _make_world()
    h = _add_sphere(jw)
    assert jw.body_count == 1
    jw.remove_body(h)
    assert jw.body_count == 0, "remove_body 后 body_count 应为 0"
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：重力方向（Z-down）
# ---------------------------------------------------------------------------

def test_gravity_z_down():
    """DYNAMIC 刚体在默认重力下 Z 坐标应随时间减小（Z-down）。"""
    jw = _make_world()
    h = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 10.0))

    # 模拟 0.5 秒（10 步，每步 0.05s）
    for _ in range(10):
        jw.step(0.05, 2)

    pos, _ = jw.get_body_transform(h)
    assert pos[2] < 9.5, (
        f"受重力后 Z 应从 10.0 显著减小（Z-down），实际 Z={pos[2]:.4f}。"
        "可能是重力方向仍为 Y-down。"
    )
    jw.clear()


def test_gravity_x_y_stable():
    """无初速度时 DYNAMIC 刚体 X/Y 坐标应保持接近初始值。"""
    jw = _make_world()
    h = _add_sphere(jw, body_type="DYNAMIC", pos=(3.0, -2.0, 10.0))
    for _ in range(10):
        jw.step(0.05, 1)
    pos, _ = jw.get_body_transform(h)
    assert abs(pos[0] - 3.0) < 0.05, f"X 应保持约 3.0，得 {pos[0]}"
    assert abs(pos[1] - (-2.0)) < 0.05, f"Y 应保持约 -2.0，得 {pos[1]}"
    jw.clear()


def test_sphere_lands_on_static_plane():
    """A dynamic sphere should collide with a static PLANE floor instead of falling forever."""
    jw = _make_world()
    _add_plane(jw, body_type="STATIC", pos=(0.0, 0.0, 0.0), half_extents=(20.0, 20.0, 0.001))
    h = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 3.0), radius=0.5)

    for _ in range(180):
        jw.step(1.0 / 60.0, 2)

    pos, _ = jw.get_body_transform(h)
    assert 0.45 <= pos[2] <= 0.65, f"球落到PLANE后 Z 应接近半径0.5，得 {pos[2]:.4f}"
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：set_gravity 覆盖
# ---------------------------------------------------------------------------

def test_set_gravity_zero():
    """重力设为 0 时 DYNAMIC 刚体应悬停。"""
    jw = _make_world()
    jw.set_gravity((0.0, 0.0, 0.0))
    h = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 5.0))
    for _ in range(20):
        jw.step(0.05, 1)
    pos, _ = jw.get_body_transform(h)
    assert abs(pos[2] - 5.0) < 0.01, f"零重力下 Z 应保持 5.0，得 {pos[2]}"
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：KINEMATIC 刚体位置跟随
# ---------------------------------------------------------------------------

def test_kinematic_follows_transform():
    """set_kinematic_transform 后 body 应移动到目标位置。"""
    jw = _make_world()
    h = _add_sphere(jw, body_type="KINEMATIC", pos=(0.0, 0.0, 0.0))
    target_pos = (1.0, 2.0, 3.0)
    jw.set_kinematic_transform(h, target_pos, (1.0, 0.0, 0.0, 0.0), 1.0 / 60.0)
    jw.step(1.0 / 60.0, 1)
    pos, _ = jw.get_body_transform(h)
    assert abs(pos[0] - 1.0) < 0.01, f"KINEMATIC X 应为 1.0，得 {pos[0]}"
    assert abs(pos[1] - 2.0) < 0.01
    assert abs(pos[2] - 3.0) < 0.01
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：约束
# ---------------------------------------------------------------------------

def test_add_fixed_constraint():
    """FIXED 约束注册后 constraint_count 应为 1，remove 后为 0。"""
    jw = _make_world()
    h_a = _add_sphere(jw, body_type="STATIC",  pos=(0.0, 0.0, 0.0))
    h_b = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 1.0))
    ch = jw.add_constraint(
        constraint_type="FIXED",
        body_a_handle=h_a,
        body_b_handle=h_b,
        anchor_pos=(0.0, 0.0, 0.5),
        anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
        disable_collisions=True,
    )
    assert jw.constraint_count == 1, f"constraint_count 应为 1，得 {jw.constraint_count}"
    jw.remove_constraint(ch)
    assert jw.constraint_count == 0
    jw.clear()


def test_constraint_disable_collisions_lifecycle():
    """disable_collisions constraints must clean up on remove_body / clear."""
    jw = _make_world()
    h_a = _add_sphere(jw, body_type="DYNAMIC", pos=(-0.25, 0.0, 2.0), radius=0.5)
    h_b = _add_sphere(jw, body_type="DYNAMIC", pos=(0.25, 0.0, 2.0), radius=0.5)
    c1 = jw.add_constraint(
        constraint_type="POINT",
        body_a_handle=h_a,
        body_b_handle=h_b,
        anchor_pos=(0.0, 0.0, 2.0),
        anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
        disable_collisions=True,
    )
    jw.add_constraint(
        constraint_type="HINGE",
        body_a_handle=h_a,
        body_b_handle=h_b,
        anchor_pos=(0.0, 0.0, 2.0),
        anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
        disable_collisions=True,
    )
    assert jw.constraint_count == 2
    jw.step(1.0 / 60.0, 1)
    jw.remove_constraint(c1)
    assert jw.constraint_count == 1
    jw.remove_body(h_a)
    assert jw.body_count == 1
    assert jw.constraint_count == 0
    jw.clear()


def test_add_hinge_constraint():
    jw = _make_world()
    h_a = _add_box(jw,    body_type="STATIC",  pos=(0.0, 0.0, 0.0))
    h_b = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 1.5))
    jw.add_constraint(
        constraint_type="HINGE",
        body_a_handle=h_a,
        body_b_handle=h_b,
        anchor_pos=(0.0, 0.0, 0.75),
        anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    assert jw.constraint_count == 1
    jw.clear()


def test_add_point_constraint_to_world():
    """body_b 使用 WORLD_HANDLE，约束固定到世界原点。"""
    jw = _make_world()
    h = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    jw.add_constraint(
        constraint_type="POINT",
        body_a_handle=h,
        body_b_handle=hotools_jolt.WORLD_HANDLE,
        anchor_pos=(0.0, 0.0, 2.0),
        anchor_rot_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    assert jw.constraint_count == 1
    # 模拟几步，POINT 约束应限制刚体位移
    for _ in range(10):
        jw.step(1.0 / 60.0, 1)
    pos, _ = jw.get_body_transform(h)
    dist = math.sqrt(pos[0]**2 + pos[1]**2 + pos[2]**2)
    # POINT 约束使 anchor 附近距离受限，位置不应无限下落
    assert dist < 10.0, f"POINT 约束后刚体不应无限漂移，dist={dist:.4f}"
    jw.clear()


# ---------------------------------------------------------------------------
# 测试：clear() 完整清理
# ---------------------------------------------------------------------------

def test_clear():
    jw = _make_world()
    for i in range(5):
        _add_sphere(jw, body_type="DYNAMIC", pos=(float(i), 0.0, 1.0))
    assert jw.body_count == 5
    jw.clear()
    assert jw.body_count == 0,       f"clear() 后 body_count 应为 0，得 {jw.body_count}"
    assert jw.constraint_count == 0, "clear() 后 constraint_count 应为 0"


def test_clear_with_constraints():
    """clear() 在有约束时也不崩溃（先删约束再删 body）。"""
    jw = _make_world()
    h_a = _add_box(jw,    body_type="STATIC",  pos=(0.0, 0.0, 0.0))
    h_b = _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 2.0))
    jw.add_constraint("FIXED", h_a, h_b, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 0.0))
    jw.clear()
    assert jw.body_count == 0
    assert jw.constraint_count == 0


# ---------------------------------------------------------------------------
# 测试：step 返回耗时（ms）
# ---------------------------------------------------------------------------

def test_step_returns_ms():
    """step() 应返回非负浮点数（毫秒）。"""
    jw = _make_world()
    _add_sphere(jw, body_type="DYNAMIC", pos=(0.0, 0.0, 5.0))
    ms = jw.step(1.0 / 60.0, 1)
    assert isinstance(ms, float), f"step 返回值应为 float，得 {type(ms)}"
    assert ms >= 0.0, f"step 耗时应非负，得 {ms}"
    jw.clear()


# ---------------------------------------------------------------------------
# 直接运行
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in tests:
        try:
            fn()
            print(f"  通过  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  失败  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n通过: {passed}  失败: {failed}")
