"""
test_blender_rigid.py — Jolt 刚体物理 Blender 无头集成测试
用法：blender.exe --background --python test_blender_rigid.py
"""
import sys, os, importlib.util, types as _types

# ── 路径根 ────────────────────────────────────────────────────────────────────
_ADDONS   = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons"
_HOTOOLS  = os.path.join(_ADDONS, "HoTools")
_JOLT_LIB = os.path.join(_HOTOOLS, "_Lib", "py311", "HotoolsPackage")
_NT_DIR   = os.path.join(_HOTOOLS, "OmniNode", "NodeTree")
_PW_ROOT  = os.path.join(_NT_DIR, "Function", "physicsWorld")

# ADDONS 作为 sys.path 根，HoTools 是顶级包
# from ...OmniNodeSocketMapping  在 HoTools.OmniNode.NodeTree.Function.physicsWorld.world
# level=3 → HoTools.OmniNode.NodeTree.OmniNodeSocketMapping  ← 文件真实存在  ✓
for p in [_JOLT_LIB, _ADDONS]:
    if p not in sys.path:
        sys.path.insert(0, p)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import bpy

PASS = "[PASS]"
FAIL = "[FAIL]"
_results = []

def check(name, fn):
    try:
        fn()
        print(f"  {PASS}  {name}")
        _results.append(True)
    except Exception as e:
        import traceback
        print(f"  {FAIL}  {name}  =>  {e}")
        traceback.print_exc()
        _results.append(False)


# ── Step 0：选择性注册 PropertyGroup（跳过 GPU/面板） ─────────────────────────

def _register_physics_props():
    # 加 HoTools 子包路径，让 PhysicsTools 可直接 import
    _ht = os.path.join(_HOTOOLS)
    if _ht not in sys.path:
        sys.path.insert(0, _ht)
    from PhysicsTools.physicsUtils import _ALL_COLLISION_GROUPS_MASK  # noqa
    from PhysicsTools.physicsProperty import (
        PG_Hotools_ObjectCollision,
        PG_Hotools_RigidBody,
        PG_Hotools_RigidConstraint,
    )
    for cls in [PG_Hotools_ObjectCollision, PG_Hotools_RigidBody, PG_Hotools_RigidConstraint]:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    if not hasattr(bpy.types.Object, "hotools_object_collision"):
        bpy.types.Object.hotools_object_collision = bpy.props.PointerProperty(
            type=PG_Hotools_ObjectCollision)
    if not hasattr(bpy.types.Object, "hotools_rigid_body"):
        bpy.types.Object.hotools_rigid_body = bpy.props.PointerProperty(
            type=PG_Hotools_RigidBody)
    if not hasattr(bpy.types.Object, "hotools_rigid_constraint"):
        bpy.types.Object.hotools_rigid_constraint = bpy.props.PointerProperty(
            type=PG_Hotools_RigidConstraint)

_register_physics_props()


# ── Step 1：手动注册包层次，绕过 __init__.py 的跨包 import ────────────────────
# 模块名前缀：HoTools.OmniNode.NodeTree.Function.physicsWorld.*
# from ...OmniNodeSocketMapping (level=3) 解析到 HoTools.OmniNode.NodeTree.OmniNodeSocketMapping ✓

_PKG_PREFIX = "HoTools.OmniNode.NodeTree.Function.physicsWorld"

def _load_pw(suffix: str, file_rel: str):
    """suffix 如 'world'，file_rel 如 'world.py'"""
    full = f"{_PKG_PREFIX}.{suffix}" if suffix else _PKG_PREFIX
    if full in sys.modules:
        return sys.modules[full]
    path = os.path.join(_PW_ROOT, *file_rel.split("/"))
    spec = importlib.util.spec_from_file_location(full, path)
    mod  = importlib.util.module_from_spec(spec)
    mod.__package__ = full.rsplit(".", 1)[0]
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod

# 注册空包（不执行 __init__.py）
_pkg_dirs = [
    ("HoTools",                                      _HOTOOLS),
    ("HoTools.OmniNode",                             os.path.join(_HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree",                    _NT_DIR),
    ("HoTools.OmniNode.NodeTree.Function",           os.path.join(_NT_DIR, "Function")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", _PW_ROOT),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid",
         os.path.join(_PW_ROOT, "rigid")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid.backends",
         os.path.join(_PW_ROOT, "rigid", "backends")),
]
for _pkg, _dir in _pkg_dirs:
    if _pkg not in sys.modules:
        _m = _types.ModuleType(_pkg)
        _m.__path__ = [_dir]; _m.__package__ = _pkg
        sys.modules[_pkg] = _m

# OmniNodeSocketMapping stub（world.py: from ...OmniNodeSocketMapping import _OmniCache）
# 真实路径：NodeTree/OmniNodeSocketMapping.py → 注册为 HoTools.OmniNode.NodeTree.OmniNodeSocketMapping
_nt_omni_key = "HoTools.OmniNode.NodeTree.OmniNodeSocketMapping"
if _nt_omni_key not in sys.modules:
    _sm = _types.ModuleType(_nt_omni_key)
    _sm.__package__ = "HoTools.OmniNode.NodeTree"
    class _OmniCache:
        """stub：满足 world.py 中 hasattr(raw, 'value') 检查。"""
        def __init__(self, value=None): self.value = value
        @classmethod
        def replace(cls, v): return cls(v)
        @classmethod
        def mutate(cls, v): return cls(v)
    _sm._OmniCache = _OmniCache
    sys.modules[_nt_omni_key] = _sm
    # 同时用短名注册，防止其他路径查找
    sys.modules.setdefault("OmniNodeSocketMapping", _sm)

# 按依赖顺序加载
_load_pw("types",                "types.py")
_load_pw("scope",                "scope.py")
_load_pw("rigid.results",        "rigid/results.py")
_load_pw("writeback",            "writeback.py")
_load_pw("world",                "world.py")
_load_pw("rigid.specs",          "rigid/specs.py")
_load_pw("rigid.solver",         "rigid/solver.py")
_load_pw("rigid.backends.jolt",  "rigid/backends/jolt.py")


# ── 导入快捷方式 ──────────────────────────────────────────────────────────────

def _pw(suffix):
    return sys.modules[f"{_PKG_PREFIX}.{suffix}"]

PhysicsWorldCache     = _pw("types").PhysicsWorldCache
make_scope            = _pw("scope").make_scope
physicsWorldBegin     = _pw("world").physicsWorldBegin
physicsWorldCommit    = _pw("world").physicsWorldCommit
apply_all_writebacks  = _pw("writeback").apply_all_writebacks
build_rigid_body_spec = _pw("rigid.specs").build_rigid_body_spec
step_rigid_bodies     = _pw("rigid.solver").step_rigid_bodies
JoltAdapter           = _pw("rigid.backends.jolt").JoltAdapter


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _make_obj(name, loc, body_type="DYNAMIC", mass=1.0, friction=0.5, restitution=0.3):
    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    rb = obj.hotools_rigid_body
    rb.enabled = True; rb.body_type = body_type
    rb.mass = mass; rb.friction = friction; rb.restitution = restitution
    rb.rigid_collision_group = 1
    col = obj.hotools_object_collision
    col.enabled = True; col.collision_type = "SPHERE"; col.radius = 0.4
    return obj

def _make_ground(name="Ground"):
    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (0, 0, 0)
    rb = obj.hotools_rigid_body
    rb.enabled = True; rb.body_type = "STATIC"; rb.friction = 0.5; rb.restitution = 0.3
    col = obj.hotools_object_collision
    col.enabled = True; col.collision_type = "BOX"; col.box_size = (10.0, 10.0, 0.2)
    return obj

def _del(*objs):
    for o in objs:
        try: bpy.data.objects.remove(o)
        except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# 测试 1：PropertyGroup 注册验证
# ─────────────────────────────────────────────────────────────────────────────

def test_props_registered():
    obj = _make_obj("T1_probe", (0, 0, 0))
    assert hasattr(obj, "hotools_rigid_body"),       "缺 hotools_rigid_body"
    assert hasattr(obj, "hotools_object_collision"), "缺 hotools_object_collision"
    assert obj.hotools_rigid_body.body_type == "DYNAMIC"
    _del(obj)


# ─────────────────────────────────────────────────────────────────────────────
# 测试 2：JoltAdapter 直接测试
# ─────────────────────────────────────────────────────────────────────────────

def test_jolt_adapter_direct():
    ground = _make_ground("T2_Ground")
    ball   = _make_obj("T2_Ball", (0, 0, 5))

    a = JoltAdapter(max_bodies=32)
    spec_g = build_rigid_body_spec(ground)
    spec_b = build_rigid_body_spec(ball)
    assert spec_g is not None and spec_b is not None

    a.sync_body(spec_g.slot_id, spec_g)
    a.sync_body(spec_b.slot_id, spec_b)
    assert a._jw.body_count == 2

    z0 = ball.location.z
    for _ in range(20):
        a.step(1/60.0, 2)

    pos, _ = a.get_body_transform(spec_b.slot_id)
    assert pos is not None and pos[2] < z0, \
        f"DYNAMIC 球应下落 z0={z0:.2f} jolt_z={pos[2]:.2f}"

    a.dispose("test"); assert not a._valid
    a.dispose("idempotent")
    _del(ground, ball)


# ─────────────────────────────────────────────────────────────────────────────
# 测试 3：PhysicsWorldCache 生命周期
# ─────────────────────────────────────────────────────────────────────────────

def test_world_lifecycle():
    scene = bpy.context.scene
    scope = make_scope([], include_passive_collision=False,
                       include_bone_collision=False, include_mesh_collision=False,
                       include_rigid_body=True, include_rigid_constraint=False,
                       include_hidden=False)

    world, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)
    assert isinstance(world, PhysicsWorldCache)
    assert world.replace_required, "首帧应 replace"

    cache_val, _, _ = physicsWorldCommit(world, enabled=True)

    world2, _, _, _ = physicsWorldBegin(
        cache_state=cache_val, scene=scene, object_scope=scope, enabled=True)
    assert not world2.replace_required, "连续帧应 mutate"
    world2.omni_cache_dispose("test")


# ─────────────────────────────────────────────────────────────────────────────
# 测试 4：完整刚体链路（60帧，DYNAMIC 球下落写回 Blender）
# ─────────────────────────────────────────────────────────────────────────────

def test_full_rigid_pipeline():
    scene  = bpy.context.scene
    ground = _make_ground("T4_Ground")
    ball   = _make_obj("T4_Ball", (0, 0, 5), body_type="DYNAMIC", mass=1.0)

    scope = make_scope([ground, ball],
                       include_passive_collision=True, include_bone_collision=False,
                       include_mesh_collision=False, include_rigid_body=True,
                       include_rigid_constraint=False, include_hidden=False)

    cache_state, z0 = None, ball.location.z

    for fi in range(60):
        scene.frame_set(fi + 1)
        world, _, _, restart = physicsWorldBegin(
            cache_state=cache_state, scene=scene, object_scope=scope, enabled=True)
        step_rigid_bodies(world, enabled=True)
        apply_all_writebacks(world, restart=restart)
        cache_val, _, _ = physicsWorldCommit(world, enabled=True)
        cache_state = cache_val

    bpy.context.view_layer.update()
    z1 = ball.matrix_world.translation.z
    assert z1 < z0, f"DYNAMIC 球应下落 z0={z0:.2f} z1={z1:.2f}"
    assert z1 > -2.0, f"球应落地停止 z1={z1:.2f}"

    world.omni_cache_dispose("test_end")
    _del(ground, ball)


# ─────────────────────────────────────────────────────────────────────────────
# 测试 5：dispose 路径 + 重建
# ─────────────────────────────────────────────────────────────────────────────

def test_dispose_and_rebuild():
    scene = bpy.context.scene
    ball  = _make_obj("T5_Ball", (0, 0, 3), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    cache_state = None
    for fi in range(10):
        scene.frame_set(fi + 1)
        world, _, _, _ = physicsWorldBegin(
            cache_state=cache_state, scene=scene, object_scope=scope, enabled=True)
        step_rigid_bodies(world, enabled=True)
        cache_val, _, _ = physicsWorldCommit(world, enabled=True)
        cache_state = cache_val

    world.omni_cache_dispose("clear_all_sim")
    adapter = world.backend_resources.get("rigid_solver")
    if adapter is not None:
        assert not adapter._valid, "dispose 后 _valid 应 False"

    world2, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)
    assert world2.replace_required
    world2.omni_cache_dispose("test_rebuild")
    _del(ball)


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "-" * 58)
    print("  Blender Jolt 刚体集成测试")
    print("-" * 58)

    check("PropertyGroup 注册",         test_props_registered)
    check("JoltAdapter 直接测试",        test_jolt_adapter_direct)
    check("PhysicsWorldCache 生命周期",  test_world_lifecycle)
    check("完整刚体链路（60帧）",         test_full_rigid_pipeline)
    check("dispose + 重建",             test_dispose_and_rebuild)

    passed = sum(_results)
    total  = len(_results)
    print("-" * 58)
    print(f"  {passed}/{total} 通过" + ("  全部通过" if passed == total else f"  {total-passed} 失败"))
    print("-" * 58 + "\n")
    sys.exit(0 if passed == total else 1)
