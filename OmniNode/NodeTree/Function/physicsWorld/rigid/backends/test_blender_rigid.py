"""
test_blender_rigid.py — Jolt 刚体物理 Blender 无头集成测试
用法：blender.exe --background --python test_blender_rigid.py
"""
import sys, os, importlib.util, types as _types

# ── 路径根 ────────────────────────────────────────────────────────────────────
_ADDONS   = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons"
_HOTOOLS  = os.path.join(_ADDONS, "HoTools")
_PY_LIB   = "py313" if sys.version_info >= (3, 13) else "py311"
_JOLT_LIB = os.path.join(_HOTOOLS, "_Lib", _PY_LIB, "HotoolsPackage")
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
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.utils",
         os.path.join(_PW_ROOT, "utils")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.spring_vrm",
         os.path.join(_PW_ROOT, "spring_vrm")),
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

_rt_key = "HoTools.OmniNode.NodeTree.OmniRuntimeState"
if _rt_key not in sys.modules:
    _rt_path = os.path.join(_NT_DIR, "OmniRuntimeState.py")
    _rt_spec = importlib.util.spec_from_file_location(_rt_key, _rt_path)
    _rt_mod = importlib.util.module_from_spec(_rt_spec)
    _rt_mod.__package__ = "HoTools.OmniNode.NodeTree"
    sys.modules[_rt_key] = _rt_mod
    _rt_spec.loader.exec_module(_rt_mod)
OmniRuntimeState = sys.modules[_rt_key]

# OmniNodeSocketMapping stub（world.py: from ...OmniNodeSocketMapping import _OmniCache）
# 真实路径：NodeTree/OmniNodeSocketMapping.py → 注册为 HoTools.OmniNode.NodeTree.OmniNodeSocketMapping
_nt_omni_key = "HoTools.OmniNode.NodeTree.OmniNodeSocketMapping"
if _nt_omni_key not in sys.modules:
    _sm = _types.ModuleType(_nt_omni_key)
    _sm.__package__ = "HoTools.OmniNode.NodeTree"
    class _OmniCache:
        """stub：用真实 runtime intent，避免无头测试绕过 Cache Write 语义。"""
        def __new__(cls, value=None):
            return OmniRuntimeState.cache_replace(value)
        @classmethod
        def replace(cls, v): return OmniRuntimeState.cache_replace(v)
        @classmethod
        def mutate(cls, v): return OmniRuntimeState.cache_mutate(v)
    _sm._OmniCache = _OmniCache
    class _OmniBone(dict):
        """stub：满足 spring_vrm 结果模块导入链。"""
        pass
    _sm._OmniBone = _OmniBone
    sys.modules[_nt_omni_key] = _sm
    # 同时用短名注册，防止其他路径查找
    sys.modules.setdefault("OmniNodeSocketMapping", _sm)

# FunctionNodeCore stub（rigid.nodes 只需要 omni 装饰器元数据）
_nt_fnc_key = "HoTools.OmniNode.NodeTree.FunctionNodeCore"
if _nt_fnc_key not in sys.modules:
    _fm = _types.ModuleType(_nt_fnc_key)
    _fm.__package__ = "HoTools.OmniNode.NodeTree"
    def omni(**omnidata):
        def decorator(func):
            func.__meta = omnidata
            return func
        return decorator
    _fm.omni = omni
    sys.modules[_nt_fnc_key] = _fm

# 按依赖顺序加载
_load_pw("names",                "names.py")
_load_pw("declarations",         "declarations.py")
_load_pw("utils.debug_draw",     "utils/debug_draw.py")
_load_pw("types",                "types.py")
_load_pw("scope",                "scope.py")
_load_pw("rigid.results",        "rigid/results.py")
_load_pw("writeback_commands",   "writeback_commands.py")
_load_pw("spring_vrm.results",   "spring_vrm/results.py")
_load_pw("writeback",            "writeback.py")
_load_pw("debug",                "debug.py")
_load_pw("world",                "world.py")
_load_pw("rigid.specs",          "rigid/specs.py")
_load_pw("rigid.declaration",    "rigid/declaration.py")
_load_pw("rigid.implicit_objects", "rigid/implicit_objects.py")
_load_pw("rigid.solver",         "rigid/solver.py")
_load_pw("rigid.backends.jolt",  "rigid/backends/jolt.py")
_load_pw("rigid.debug_draw",     "rigid/debug_draw.py")
_load_pw("nodes",                "nodes.py")
_load_pw("rigid.nodes",          "rigid/nodes.py")


# ── 导入快捷方式 ──────────────────────────────────────────────────────────────

def _pw(suffix):
    return sys.modules[f"{_PKG_PREFIX}.{suffix}"]

PhysicsWorldCache     = _pw("types").PhysicsWorldCache
make_scope            = _pw("scope").make_scope
physicsWorldBegin     = _pw("world").physicsWorldBegin
physicsWorldCommit    = _pw("world").physicsWorldCommit
apply_all_writebacks  = _pw("writeback").apply_all_writebacks
build_rigid_body_spec = _pw("rigid.specs").build_rigid_body_spec
build_constraint_spec = _pw("rigid.specs").build_constraint_spec
step_rigid_bodies     = _pw("rigid.solver").step_rigid_bodies
JoltAdapter           = _pw("rigid.backends.jolt").JoltAdapter
get_rigid_transform_result = _pw("rigid.results").get_rigid_transform_result
get_rigid_constraint_state_result = _pw("rigid.results").get_rigid_constraint_state_result
get_rigid_solver_stats_result = _pw("rigid.results").get_rigid_solver_stats_result
iter_rigid_contact_event_results = _pw("rigid.results").iter_rigid_contact_event_results
make_rigid_generated_constraint_properties = _pw("rigid.implicit_objects").make_rigid_generated_constraint_properties
register_rigid_generated_constraint_objects = _pw("rigid.implicit_objects").register_rigid_generated_constraint_objects
active_generated_constraint_slot_ids = _pw("rigid.implicit_objects").active_generated_constraint_slot_ids
make_rigid_jolt_world_setting_properties = _pw("rigid.implicit_objects").make_rigid_jolt_world_setting_properties
register_rigid_jolt_world_setting_objects = _pw("rigid.implicit_objects").register_rigid_jolt_world_setting_objects
physicsWorldResultStream = _pw("nodes").physicsWorldResultStream
physicsRigidReadState = _pw("rigid.nodes").physicsRigidReadState
physicsRigidConstraintReadState = _pw("rigid.nodes").physicsRigidConstraintReadState
physicsRigidSetVelocity = _pw("rigid.nodes").physicsRigidSetVelocity
physicsRigidGeneratedConstraintRegister = _pw("rigid.nodes").physicsRigidGeneratedConstraintRegister
physicsRigidJoltWorldSettingsRegister = _pw("rigid.nodes").physicsRigidJoltWorldSettingsRegister


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

def _make_constraint_empty(name, target_a, target_b, loc=(0, 0, 1)):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.empty_display_type = "ARROWS"
    obj.location = loc
    con = obj.hotools_rigid_constraint
    con.enabled = True
    con.constraint_type = "POINT"
    con.target_a = target_a
    con.target_b = target_b
    con.disable_collisions = True
    return obj


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

    a = JoltAdapter(max_bodies=32, max_body_pairs=64, max_contact_constraints=32)
    direct_debug = a.debug_snapshot()
    assert direct_debug["jolt_max_bodies"] == 32
    assert direct_debug["jolt_max_body_pairs"] == 64
    assert direct_debug["jolt_max_contact_constraints"] == 32
    spec_g = build_rigid_body_spec(ground)
    spec_b = build_rigid_body_spec(ball)
    assert spec_g is not None and spec_b is not None

    a.sync_body(spec_g.slot_id, spec_g)
    a.sync_body(spec_b.slot_id, spec_b)
    assert a._jw.body_count == 2

    assert a.set_gravity((0, 0, 0)) is True
    for _ in range(5):
        a.step(1/60.0, 1)
    zero_g_state = a.get_body_state(spec_b.slot_id)
    assert zero_g_state is not None
    assert abs(zero_g_state["linear_velocity"][2]) < 1e-4
    assert a.debug_snapshot()["jolt_world_gravity"] == (0.0, 0.0, 0.0)
    assert a.set_gravity((0, 0, -9.81)) is True

    z0 = zero_g_state["position"][2]
    for _ in range(20):
        a.step(1/60.0, 2)

    pos, _ = a.get_body_transform(spec_b.slot_id)
    assert pos is not None and pos[2] < z0, \
        f"DYNAMIC 球应下落 z0={z0:.2f} jolt_z={pos[2]:.2f}"
    state = a.get_body_state(spec_b.slot_id)
    assert state is not None
    assert state["position"][2] < z0
    assert state["linear_velocity"][2] < 0.0
    assert isinstance(state["active"], bool) and isinstance(state["sleeping"], bool)
    assert a.set_body_velocity(spec_b.slot_id, (0, 0, 0), (0, 0, 0)) is True
    assert a.add_body_impulse(spec_b.slot_id, (0, 0, 3), (0, 0, 0.5)) is True
    state2 = a.get_body_state(spec_b.slot_id)
    assert state2["linear_velocity"][2] > 0.0
    assert state2["angular_velocity"][2] > 0.0
    assert a.set_body_gravity_factor(spec_b.slot_id, 0.0) is True
    assert a.set_body_material_response(spec_b.slot_id, 0.2, 0.8) is True
    assert a.set_body_motion_quality(spec_b.slot_id, "LINEAR_CAST") is True
    assert a.set_body_active(spec_b.slot_id, False) is True
    state3 = a.get_body_state(spec_b.slot_id)
    assert state3["active"] is False and state3["sleeping"] is True
    assert a.set_body_active(spec_b.slot_id, True) is True
    assert a.set_body_velocity(spec_g.slot_id, (0, 0, 1), (0, 0, 0)) is False

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
    item = world.publish_exchange({
        "channel": "test_exchange",
        "producer": "test",
        "scope": "frame",
        "value": 1,
    })
    assert item is not None
    assert len(world.consume_exchange("test_exchange")) == 1
    snapshot = world.omni_cache_debug_snapshot()
    assert snapshot["exchange_channels"]["test_exchange"] == 1
    result = world.publish_result({
        "channel": "test_result",
        "solver": "test",
        "value": 2,
    })
    assert result is not None
    assert len(world.consume_results("test_result", solver="test")) == 1
    snapshot = world.omni_cache_debug_snapshot()
    assert snapshot["result_channels"]["test_result"] == 1

    cache_val, _, _ = physicsWorldCommit(world, enabled=True)

    world2, _, _, _ = physicsWorldBegin(
        cache_state=cache_val, scene=scene, object_scope=scope, enabled=True)
    assert not world2.replace_required, "连续帧应 mutate"
    assert world2.consume_exchange("test_exchange") == [], "Begin 应清空 frame exchange"
    assert world2.consume_results("test_result") == [], "Begin 应清空 result stream"
    world2.omni_cache_dispose("test")


def test_rigid_body_commands_exchange():
    scene = bpy.context.scene
    ball = _make_obj("T3B_CommandBall", (0, 0, 5), body_type="DYNAMIC")

    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    scene.frame_set(1)
    world, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)
    spec = build_rigid_body_spec(ball)
    assert spec is not None
    cmd = world.publish_exchange({
        "channel": "rigid_body_commands",
        "producer": "test",
        "scope": "frame",
        "target_slot_id": spec.slot_id,
        "command": "set_velocity",
        "linear_velocity": (0, 0, 4),
        "angular_velocity": (0, 0, 0),
    })
    assert cmd is not None

    step_rigid_bodies(world, enabled=True)
    result = get_rigid_transform_result(
        world, slot_id=spec.slot_id, frame=scene.frame_current, generation=world.generation)
    assert result is not None
    assert result["linear_velocity"][2] > 3.0
    snapshot = world.omni_cache_debug_snapshot()
    assert snapshot["result_channels"]["rigid_transform"] == 1
    assert snapshot["result_channels"]["rigid_solver_stats"] == 1
    stats = get_rigid_solver_stats_result(
        world, frame=scene.frame_current, generation=world.generation)
    assert stats is not None
    assert stats["body_count"] == 1
    assert stats["transform_count"] == 1
    assert stats["command_count"] == 1
    assert stats["command_failed"] == 0
    _, items, count, text = physicsWorldResultStream(
        world, "rigid_solver_stats", "", True, True)
    assert count == 1 and len(items) == 1
    assert "rigid_solver_stats" in text and "command_count" in text

    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None
    debug = adapter.debug_snapshot()
    assert debug["last_command_count"] == 1
    assert debug["last_command_failed"] == 0

    step_rigid_bodies(world, enabled=True)
    debug2 = adapter.debug_snapshot()
    assert debug2["last_command_count"] == 0, "同一 frame item 不应重复消费"
    stats2 = get_rigid_solver_stats_result(
        world, frame=scene.frame_current, generation=world.generation)
    assert stats2 is not None
    assert stats2["command_count"] == 0

    world.omni_cache_dispose("test_commands")
    _del(ball)


def test_rigid_body_command_nodes():
    scene = bpy.context.scene
    ball = _make_obj("T3C_CommandNodeBall", (0, 0, 5), body_type="DYNAMIC")

    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    scene.frame_set(1)
    world, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)

    _, item = physicsRigidSetVelocity(world, ball, (0, 0, 5), (0, 0, 0))
    assert item is not None
    assert item["command"] == "set_velocity"
    assert item["target_object"] == ball.name
    assert item["linear_velocity"] == (0.0, 0.0, 5.0)
    assert world.exchange_counts()["rigid_body_commands"] == 1

    step_rigid_bodies(world, enabled=True)
    spec = build_rigid_body_spec(ball)
    result = get_rigid_transform_result(
        world, slot_id=spec.slot_id, frame=scene.frame_current, generation=world.generation)
    assert result is not None
    assert result["linear_velocity"][2] > 4.0

    adapter = world.backend_resources.get("rigid_solver")
    debug = adapter.debug_snapshot()
    assert debug["last_command_count"] == 1
    assert debug["last_command_failed"] == 0

    _, found, position, rotation, linear_velocity, angular_velocity, active, sleeping, raw_result = physicsRigidReadState(world, ball)
    assert found is True
    assert position[2] > 4.0
    assert abs(rotation[0]) < 0.001 and abs(rotation[1]) < 0.001 and abs(rotation[2]) < 0.001
    assert linear_velocity[2] > 4.0
    assert abs(angular_velocity[0]) < 0.001
    assert active is True
    assert sleeping is False
    assert raw_result["slot_id"] == spec.slot_id

    world.omni_cache_dispose("test_command_nodes")
    _del(ball)


def test_rigid_jolt_world_settings_implicit_object_pipeline():
    scene = bpy.context.scene
    ball = _make_obj("T3E_WorldSettingBall", (0, 0, 5), body_type="DYNAMIC")

    defaults = make_rigid_jolt_world_setting_properties()
    assert defaults[0]["max_bodies"] == 1024
    assert defaults[0]["max_body_pairs"] == 4096
    assert defaults[0]["max_contact_constraints"] == 2048

    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    scene.frame_set(1)
    world, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)

    props = make_rigid_jolt_world_setting_properties(
        gravity=(0, 0, 0),
        max_bodies=32,
        max_body_pairs=64,
        max_contact_constraints=32,
        enabled=True,
        source_id="test_zero_gravity",
        priority=10,
    )
    count, dirty, version = register_rigid_jolt_world_setting_objects(
        world, props, enabled=True)
    assert count == 1 and dirty == 1 and version == 1
    assert world.implicit_object_counts().get("rigid_jolt.world_setting") == 1

    step_rigid_bodies(world, enabled=True)
    spec = build_rigid_body_spec(ball)
    result = get_rigid_transform_result(
        world, slot_id=spec.slot_id, frame=scene.frame_current, generation=world.generation)
    assert result is not None
    assert abs(result["linear_velocity"][2]) < 1e-4
    assert abs(result["position"][2] - ball.location.z) < 1e-3
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None
    debug = adapter.debug_snapshot()
    assert debug["jolt_world_gravity"] == (0.0, 0.0, 0.0)
    assert debug["jolt_world_settings_signature"] != "default"
    assert debug["jolt_max_bodies"] == 32
    assert debug["jolt_max_body_pairs"] == 64
    assert debug["jolt_max_contact_constraints"] == 32

    cache_val, _, _ = physicsWorldCommit(world, enabled=True)

    scene.frame_set(2)
    world2, _, _, _ = physicsWorldBegin(
        cache_state=cache_val, scene=scene, object_scope=scope, enabled=True)
    count2, dirty2, _version2 = register_rigid_jolt_world_setting_objects(
        world2, props, enabled=False)
    assert count2 == 1 and dirty2 == 1

    step_rigid_bodies(world2, enabled=True)
    result2 = get_rigid_transform_result(
        world2, slot_id=spec.slot_id, frame=scene.frame_current, generation=world2.generation)
    assert result2 is not None
    assert result2["linear_velocity"][2] < -0.01
    adapter2 = world2.backend_resources.get("rigid_solver")
    assert adapter2 is not adapter
    debug2 = adapter2.debug_snapshot()
    assert debug2["jolt_world_gravity"] == (0.0, 0.0, -9.81)
    assert debug2["jolt_world_settings_signature"] == "default"
    assert debug2["jolt_max_bodies"] == 1024
    assert debug2["jolt_max_body_pairs"] == 4096
    assert debug2["jolt_max_contact_constraints"] == 2048

    world2.omni_cache_dispose("test_world_settings")
    _del(ball)


def test_constraint_spec_disable_collisions():
    a = _make_obj("T3A_BodyA", (-1, 0, 1))
    b = _make_obj("T3A_BodyB", (1, 0, 1))
    c = _make_constraint_empty("T3A_Constraint", a, b, loc=(0, 0, 1))

    spec = build_constraint_spec(c)
    assert spec is not None
    assert spec.disable_collisions is True
    assert spec.debug_dict()["disable_collisions"] is True

    c.hotools_rigid_constraint.disable_collisions = False
    spec2 = build_constraint_spec(c)
    assert spec2 is not None
    assert spec2.disable_collisions is False

    _del(c, a, b)


def test_distance_constraint_spec_and_generated_properties():
    a = _make_obj("T3B_DistanceBodyA", (-1, 0, 1))
    b = _make_obj("T3B_DistanceBodyB", (1, 0, 1))
    c = _make_constraint_empty("T3B_DistanceConstraint", a, b, loc=(0, 0, 1))
    props = c.hotools_rigid_constraint
    props.constraint_type = "DISTANCE"
    props.distance_min = 2.5
    props.distance_max = 0.5
    props.limit_spring_frequency = 3.0
    props.limit_spring_damping = 0.75
    props.breakable = True
    props.breaking_threshold = 12.5
    props.anchor_mode = "LOCAL_FRAMES"
    props.local_point_a = (0.25, 0.0, 0.0)
    props.local_rotation_a = (0.0, 0.0, 0.2)
    props.local_point_b = (-0.25, 0.0, 0.0)
    props.local_rotation_b = (0.0, 0.0, -0.3)
    bpy.context.view_layer.update()

    spec = build_constraint_spec(c)
    assert spec is not None
    assert spec.constraint_type == "DISTANCE"
    assert spec.distance_min == 0.5
    assert spec.distance_max == 2.5
    assert spec.limit_spring_frequency == 3.0
    assert spec.limit_spring_damping == 0.75
    assert spec.breakable is True
    assert spec.breaking_threshold == 12.5
    assert spec.anchor_mode == "LOCAL_FRAMES"
    assert spec.anchor_position_a == (-0.75, 0.0, 1.0)
    assert spec.anchor_position_b == (0.75, 0.0, 1.0)
    assert spec.anchor_rotation_wxyz_a != spec.anchor_rotation_wxyz_b
    assert spec.debug_dict()["distance_max"] == 2.5

    adapter = JoltAdapter(max_bodies=16, max_body_pairs=32, max_contact_constraints=16)
    body_a = build_rigid_body_spec(a)
    body_b = build_rigid_body_spec(b)
    assert body_a is not None and body_b is not None
    adapter.sync_body(body_a.slot_id, body_a)
    adapter.sync_body(body_b.slot_id, body_b)
    adapter.sync_constraint(spec.slot_id, spec)
    assert adapter.constraint_count == 1
    adapter.step(1.0 / 60.0, 1)
    state = adapter.get_constraint_state(spec.slot_id)
    assert state is not None
    assert state["constraint_type"] == "DISTANCE"
    assert state["current_value_kind"] == "distance"
    assert abs(state["current_value"] - 1.5) < 1.0e-4
    assert state["enabled"] is True
    assert state["lambda_max_abs"] >= 0.0
    adapter.dispose("test_distance_constraint")

    anchor_a = bpy.data.objects.new("T3B_GeneratedAnchorA", None)
    anchor_b = bpy.data.objects.new("T3B_GeneratedAnchorB", None)
    bpy.context.scene.collection.objects.link(anchor_a)
    bpy.context.scene.collection.objects.link(anchor_b)
    anchor_a.location = (-0.5, 0.0, 1.5)
    anchor_b.location = (0.5, 0.0, 1.5)
    bpy.context.view_layer.update()
    generated = make_rigid_generated_constraint_properties(
        target_a=a,
        target_b=b,
        constraint_type="DISTANCE",
        distance_min=4.0,
        distance_max=1.0,
        breakable=True,
        breaking_threshold=7.5,
        anchor_object_a=anchor_a,
        anchor_object_b=anchor_b,
    )
    assert len(generated) == 1
    assert generated[0]["constraint_type"] == "DISTANCE"
    assert generated[0]["distance_min"] == 1.0
    assert generated[0]["distance_max"] == 4.0
    assert generated[0]["breakable"] is True
    assert generated[0]["breaking_threshold"] == 7.5
    assert generated[0]["anchor_mode"] == "SEPARATE_WORLD"
    assert generated[0]["anchor_position_a"] == (-0.5, 0.0, 1.5)
    assert generated[0]["anchor_position_b"] == (0.5, 0.0, 1.5)

    _del(anchor_a, anchor_b, c, a, b)


def test_constraint_state_result_pipeline():
    scene = bpy.context.scene
    a = _make_obj("T3C_StateBodyA", (-0.5, 0, 2), body_type="STATIC")
    b = _make_obj("T3C_StateBodyB", (0.5, 0, 2), body_type="DYNAMIC")
    c = _make_constraint_empty("T3C_StateConstraint", a, b, loc=(0, 0, 2))
    props = c.hotools_rigid_constraint
    props.constraint_type = "HINGE"
    props.breakable = True
    props.breaking_threshold = 0.0

    scope = make_scope(
        [a, b, c],
        include_rigid_body=True,
        include_rigid_constraint=True,
        include_passive_collision=False,
        include_bone_collision=False,
        include_mesh_collision=False,
    )
    scene.frame_set(1)
    world, _, _, _ = physicsWorldBegin(
        cache_state=None,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    step_rigid_bodies(world, enabled=True)

    spec = build_constraint_spec(c)
    assert spec is not None
    result = get_rigid_constraint_state_result(
        world,
        slot_id=spec.slot_id,
        frame=scene.frame_current,
        generation=world.generation,
    )
    assert result is not None
    assert result["constraint_type"] == "HINGE"
    assert result["current_value_kind"] == "angle"
    assert result["breakable"] is True
    assert result["broken"] is True
    assert result["enabled"] is False
    assert result["breaking_impulse"] > 0.0
    assert len(result["lambda_position"]) == 3
    assert len(result["lambda_rotation"]) == 3
    assert result["lambda_max_abs"] >= 0.0

    node_result = physicsRigidConstraintReadState(world, c)
    assert node_result[1] is True
    assert node_result[2] is False
    assert node_result[3] == "HINGE"
    assert node_result[4] == "angle"
    assert node_result[-2] is True
    assert node_result[-1] is result

    cache_value, _, _ = physicsWorldCommit(world, enabled=True)
    props.breaking_threshold = 1000.0
    scene.frame_set(2)
    world2, _, _, _ = physicsWorldBegin(
        cache_state=cache_value,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    step_rigid_bodies(world2, enabled=True)
    result2 = get_rigid_constraint_state_result(
        world2,
        slot_id=spec.slot_id,
        frame=scene.frame_current,
        generation=world2.generation,
    )
    assert result2 is not None
    assert result2["enabled"] is True
    assert result2["broken"] is False
    assert "_jolt_broken" not in world2.solver_slots[spec.slot_id].data

    world2.omni_cache_dispose("test_constraint_state_result")
    _del(c, a, b)


def test_generated_constraint_implicit_object_pipeline():
    scene = bpy.context.scene
    a = _make_obj("T3D_GeneratedBodyA", (-0.5, 0, 2), body_type="DYNAMIC")
    b = _make_obj("T3D_GeneratedBodyB", (0.5, 0, 2), body_type="DYNAMIC")

    scope = make_scope([a, b], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    scene.frame_set(1)
    world, _, _, _ = physicsWorldBegin(
        cache_state=None, scene=scene, object_scope=scope, enabled=True)

    props = make_rigid_generated_constraint_properties(
        a, b, None, "POINT", True, True, "test_generated_pair")
    assert len(props) == 1

    count, dirty, version = register_rigid_generated_constraint_objects(
        world, props, enabled=True)
    assert count == 1 and dirty == 1 and version == 1
    assert world.implicit_object_counts().get("rigid.generated_constraint") == 1

    active_ids = active_generated_constraint_slot_ids(world)
    assert len(active_ids) == 1
    generated_slot_id = next(iter(active_ids))

    step_rigid_bodies(world, enabled=True)
    assert generated_slot_id in world.solver_slots
    assert world.solver_slots[generated_slot_id].kind == "rigid_constraint"
    stats = get_rigid_solver_stats_result(
        world, frame=scene.frame_current, generation=world.generation)
    assert stats is not None
    assert stats["body_count"] == 2
    assert stats["constraint_count"] == 1
    assert stats["sync_error_count"] == 0

    cache_val, _, _ = physicsWorldCommit(world, enabled=True)

    scene.frame_set(2)
    world2, _, _, _ = physicsWorldBegin(
        cache_state=cache_val, scene=scene, object_scope=scope, enabled=True)
    assert generated_slot_id in world2.solver_slots, \
        "Begin 不应 prune 上一帧已注册的 generated constraint slot"

    count2, dirty2, _version2 = register_rigid_generated_constraint_objects(
        world2, props, enabled=False)
    assert count2 == 1 and dirty2 == 1

    step_rigid_bodies(world2, enabled=True)
    assert generated_slot_id not in world2.solver_slots
    stats2 = get_rigid_solver_stats_result(
        world2, frame=scene.frame_current, generation=world2.generation)
    assert stats2 is not None
    assert stats2["constraint_count"] == 0

    world2.omni_cache_dispose("test_generated_constraint")
    _del(a, b)


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
    ball_ptr = int(ball.as_pointer())
    result = get_rigid_transform_result(
        world, obj_ptr=ball_ptr, frame=scene.frame_current, generation=world.generation)
    assert result is not None, "刚体 solver 应写入 world.result_streams rigid_transform"
    assert "linear_velocity" in result and "angular_velocity" in result
    assert isinstance(result.get("active"), bool)
    assert isinstance(result.get("sleeping"), bool)
    stats = get_rigid_solver_stats_result(
        world, frame=scene.frame_current, generation=world.generation)
    assert stats is not None
    assert stats["body_count"] == 2
    assert stats["transform_count"] == 2
    assert stats["sync_error_count"] == 0
    assert stats["result_error_count"] == 0

    world.omni_cache_dispose("test_end")
    _del(ground, ball)


def test_contact_and_sensor_event_result_pipeline():
    scene = bpy.context.scene
    sensor = _make_obj("T4B_Sensor", (0, 0, 0), body_type="STATIC")
    sensor.hotools_rigid_body.is_sensor = True
    sensor.hotools_object_collision.collision_type = "BOX"
    sensor.hotools_object_collision.box_size = (2.0, 2.0, 2.0)
    probe = _make_obj("T4B_Probe", (0, 0, 0), body_type="DYNAMIC")
    scope = make_scope(
        [sensor, probe],
        include_rigid_body=True,
        include_rigid_constraint=False,
        include_passive_collision=False,
        include_bone_collision=False,
        include_mesh_collision=False,
    )

    world, cache_value, stats = _begin_step_commit(scene, None, scope, 1)
    contacts = iter_rigid_contact_event_results(
        world, frame=1, generation=world.generation)
    sensors = iter_rigid_contact_event_results(
        world, frame=1, generation=world.generation, sensor_only=True)
    assert contacts and sensors, "重叠 sensor 应同时发布 contact 与 sensor 结果通道"
    event = sensors[0]
    expected_slots = {
        build_rigid_body_spec(sensor).slot_id,
        build_rigid_body_spec(probe).slot_id,
    }
    assert {event["body_a_slot_id"], event["body_b_slot_id"]} == expected_slots
    assert event["is_sensor"] is True and event["sensor_slot_ids"]
    assert "body_a_handle" not in event and "body_b_handle" not in event
    assert stats["contact_event_count"] == len(contacts)
    assert stats["sensor_event_count"] == len(sensors)
    assert stats["contact_event_overflow"] == 0

    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 1)
    sensors2 = iter_rigid_contact_event_results(
        world2, frame=1, generation=world2.generation, sensor_only=True)
    assert world2 is world and world2.frame_context.same_frame is True
    assert sensors2 == sensors, "same-frame 应重发上一真实模拟步的 sensor 快照"
    assert stats2["sensor_event_count"] == len(sensors2)

    probe.hotools_rigid_body.shape_radius = 0.7
    world3, _cache_value3, stats3 = _begin_step_commit(scene, cache_value, scope, 1)
    sensors3 = iter_rigid_contact_event_results(
        world3, frame=1, generation=world3.generation, sensor_only=True)
    assert world3 is world and world3.frame_context.same_frame is True
    assert not sensors3, "same-frame 结构重建后不得重发重建前的 contact 快照"
    assert stats3["contact_event_count"] == 0
    assert stats3["sensor_event_count"] == 0

    world3.omni_cache_dispose("test_contact_sensor_events")
    _del(sensor, probe)


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


def _runtime_cache_rigid_step(scene, cache_state, scope, frame):
    scene.frame_set(frame)
    world, _, _, restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    step_rigid_bodies(world, enabled=True)
    write_count = apply_all_writebacks(world, restart=restart)
    cache_value, _, _ = physicsWorldCommit(world, enabled=True)
    return world, cache_value, write_count


def _begin_step_commit(scene, cache_state, scope, frame, *, reset=False, writeback=False):
    scene.frame_set(frame)
    world, _, _, restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        reset=bool(reset),
        enabled=True,
    )
    step_rigid_bodies(world, enabled=True)
    if writeback:
        apply_all_writebacks(world, restart=restart)
    stats = get_rigid_solver_stats_result(
        world, frame=scene.frame_current, generation=world.generation)
    cache_value, _, _ = physicsWorldCommit(world, enabled=True)
    return world, cache_value, stats


def _assert_delta_cleared(obj, label):
    delta = getattr(obj, "delta_location", (0.0, 0.0, 0.0))
    assert abs(float(delta[0])) < 1e-6, f"{label} delta_location.x 未清零"
    assert abs(float(delta[1])) < 1e-6, f"{label} delta_location.y 未清零"
    assert abs(float(delta[2])) < 1e-6, f"{label} delta_location.z 未清零"


def _assert_world_disposed(world, adapter, label):
    assert not bool(getattr(world, "valid", True)), f"{label} world.valid 应为 False"
    assert not world.solver_slots, f"{label} solver_slots 应清空"
    assert not world.backend_resources, f"{label} backend_resources 应清空"
    assert not world.implicit_objects, f"{label} implicit_objects 应清空"
    assert not world.result_streams, f"{label} result_streams 应清空"
    if adapter is not None:
        assert not bool(getattr(adapter, "_valid", True)), f"{label} JoltAdapter 应失效"


def test_runtime_cache_delete_and_clear_all_dispose():
    scene = bpy.context.scene
    root_tree = scene
    cache_key = "test_rigid_physics_world_runtime_cache"
    OmniRuntimeState.clear_all()

    ball = _make_obj("T5B_RuntimeCacheBall", (0, 0, 4), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    ctx = OmniRuntimeState.begin_run(root_tree)
    hit, cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
    assert not hit and cache_state is None
    world, cache_value, write_count = _runtime_cache_rigid_step(scene, cache_state, scope, 1)
    assert write_count == 1
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None and adapter._valid
    OmniRuntimeState.write_cache(ctx, cache_key, cache_value)
    OmniRuntimeState.finish_run(ctx)

    ctx = OmniRuntimeState.begin_run(root_tree)
    hit, cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
    assert hit and cache_state is world, "dispose-owner cache read 应返回同一个 world owner"
    world2, cache_value2, write_count2 = _runtime_cache_rigid_step(scene, cache_state, scope, 2)
    assert world2 is world
    assert write_count2 == 1
    assert abs(float(ball.delta_location.z)) > 1e-6, "写回应产生非零 delta，供 delete 清理验证"
    OmniRuntimeState.write_cache(ctx, cache_key, cache_value2)
    OmniRuntimeState.finish_run(ctx)

    ctx = OmniRuntimeState.begin_run(root_tree)
    deleted = OmniRuntimeState.delete_cache(ctx, cache_key)
    assert deleted == 1
    OmniRuntimeState.finish_run(ctx)
    _assert_world_disposed(world, adapter, "Cache Delete")
    _assert_delta_cleared(ball, "Cache Delete")

    ctx = OmniRuntimeState.begin_run(root_tree)
    hit, _cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
    assert not hit
    OmniRuntimeState.finish_run(ctx)

    ball2 = _make_obj("T5C_RuntimeClearAllBall", (0, 0, 4), body_type="DYNAMIC")
    scope2 = make_scope([ball2], include_rigid_body=True, include_rigid_constraint=False,
                        include_passive_collision=False, include_bone_collision=False,
                        include_mesh_collision=False)

    ctx = OmniRuntimeState.begin_run(root_tree)
    world_clear, cache_value_clear, write_count_clear = _runtime_cache_rigid_step(scene, None, scope2, 1)
    assert write_count_clear == 1
    adapter_clear = world_clear.backend_resources.get("rigid_solver")
    assert adapter_clear is not None and adapter_clear._valid
    assert abs(float(ball2.delta_location.z)) > 1e-6
    OmniRuntimeState.write_cache(ctx, cache_key, cache_value_clear)
    OmniRuntimeState.finish_run(ctx)

    OmniRuntimeState.clear_all()
    _assert_world_disposed(world_clear, adapter_clear, "clear_all")
    _assert_delta_cleared(ball2, "clear_all")

    _del(ball, ball2)


def test_same_frame_repeats_publish_cached_results_without_step():
    scene = bpy.context.scene
    ball = _make_obj("T6A_SameFrameBall", (0, 0, 4), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1)
    assert stats1 is not None
    assert stats1["same_frame"] is False
    assert stats1["restart_required"] is True
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None and adapter._valid
    generation = world.generation

    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 1)
    assert world2 is world
    assert world2.generation == generation
    assert world2.frame_context.same_frame is True
    assert world2.frame_context.restart_required is False
    assert stats2 is not None
    assert stats2["same_frame"] is True
    assert stats2["restart_required"] is False
    assert stats2["step_ms"] == 0.0
    assert stats2["body_count"] == 1
    assert stats2["transform_count"] == 1
    assert world2.backend_resources.get("rigid_solver") is adapter

    world2.omni_cache_dispose("test_same_frame")
    _del(ball)


def test_frame_jump_back_replaces_world_and_restarts():
    scene = bpy.context.scene
    ball = _make_obj("T6B_JumpBackBall", (0, 0, 4), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    world1, cache_value, _stats1 = _begin_step_commit(scene, None, scope, 1)
    world2, cache_value, stats2 = _begin_step_commit(scene, cache_value, scope, 2)
    assert world2 is world1
    assert stats2 is not None
    adapter2 = world2.backend_resources.get("rigid_solver")
    assert adapter2 is not None and adapter2._valid

    world_back, _cache_value_back, stats_back = _begin_step_commit(scene, cache_value, scope, 1)
    assert world_back is not world2
    assert world_back.replace_required is False, "Commit 后 replace_required 应已清除"
    assert world_back.frame_context.previous_frame == 2
    assert world_back.frame_context.frame == 1
    assert world_back.frame_context.restart_required is True
    assert world_back.frame_context.same_frame is False
    assert stats_back is not None
    assert stats_back["restart_required"] is True
    assert stats_back["same_frame"] is False
    assert stats_back["body_count"] == 1
    assert world_back.backend_resources.get("rigid_solver") is not adapter2

    world2.omni_cache_dispose("test_jump_old_world")
    world_back.omni_cache_dispose("test_jump_new_world")
    _del(ball)


def test_scope_prune_removes_rigid_slot_and_resyncs_remaining_body():
    scene = bpy.context.scene
    a = _make_obj("T6C_PruneA", (0, 0, 4), body_type="DYNAMIC")
    b = _make_obj("T6C_PruneB", (1, 0, 4), body_type="DYNAMIC")
    scope_both = make_scope([a, b], include_rigid_body=True, include_rigid_constraint=False,
                            include_passive_collision=False, include_bone_collision=False,
                            include_mesh_collision=False)
    scope_one = make_scope([a], include_rigid_body=True, include_rigid_constraint=False,
                           include_passive_collision=False, include_bone_collision=False,
                           include_mesh_collision=False)

    spec_a = build_rigid_body_spec(a)
    spec_b = build_rigid_body_spec(b)
    assert spec_a is not None and spec_b is not None

    world, cache_value, stats1 = _begin_step_commit(scene, None, scope_both, 1)
    assert stats1 is not None
    assert stats1["body_count"] == 2
    assert spec_a.slot_id in world.solver_slots
    assert spec_b.slot_id in world.solver_slots
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None and adapter.body_count == 2
    generation1 = world.generation

    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope_one, 2)
    assert world2 is world
    assert world2.generation == generation1 + 1
    assert world2.frame_context.restart_required is True
    assert spec_a.slot_id in world2.solver_slots
    assert spec_b.slot_id not in world2.solver_slots
    assert world2.solver_slots[spec_a.slot_id].data.get("_jolt_generation") == world2.generation
    assert stats2 is not None
    assert stats2["restart_required"] is True
    assert stats2["body_count"] == 1
    assert stats2["transform_count"] == 1
    assert adapter.body_count == 1

    world2.omni_cache_dispose("test_scope_prune")
    _del(a, b)


def test_reset_restarts_generation_and_clears_writeback_delta():
    scene = bpy.context.scene
    ball = _make_obj("T6D_ResetBall", (0, 0, 4), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1, writeback=True)
    assert stats1 is not None
    assert abs(float(ball.delta_location.z)) > 1e-6
    generation1 = world.generation
    spec = build_rigid_body_spec(ball)
    assert spec is not None and spec.slot_id in world.solver_slots

    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 2, reset=True, writeback=False)
    assert world2 is world
    assert world2.generation == generation1 + 1
    assert world2.frame_context.reset_requested is True
    assert world2.frame_context.restart_required is True
    assert stats2 is not None
    assert stats2["restart_required"] is True
    assert stats2["body_count"] == 1
    assert world2.solver_slots[spec.slot_id].data.get("_jolt_generation") == world2.generation
    _assert_delta_cleared(ball, "reset")

    world2.omni_cache_dispose("test_reset_semantics")
    _del(ball)


def test_static_transform_dirty_resyncs_jolt_body_without_generation_restart():
    scene = bpy.context.scene
    block = _make_obj("T6E_StaticDirty", (0, 0, 0), body_type="STATIC")
    scope = make_scope([block], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    spec = build_rigid_body_spec(block)
    assert spec is not None
    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1)
    assert stats1 is not None and stats1["body_count"] == 1
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None and adapter.body_count == 1
    generation1 = world.generation
    signature1 = world.solver_slots[spec.slot_id].data.get("_sync_signature")

    block.location.z = 1.25
    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 2)
    assert world2 is world
    assert world2.generation == generation1
    assert world2.frame_context.restart_required is False
    assert stats2 is not None
    assert stats2["restart_required"] is False
    assert stats2["body_count"] == 1
    slot = world2.solver_slots[spec.slot_id]
    assert slot.data.get("_sync_signature") != signature1
    assert slot.data.get("_jolt_generation") == world2.generation
    assert world2.backend_resources.get("rigid_solver") is adapter
    assert adapter.body_count == 1

    world2.omni_cache_dispose("test_static_dirty")
    _del(block)


def test_kinematic_transform_dirty_updates_jolt_body_without_resync_generation():
    scene = bpy.context.scene
    mover = _make_obj("T6F_KinematicDirty", (0, 0, 1), body_type="KINEMATIC")
    scope = make_scope([mover], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    spec = build_rigid_body_spec(mover)
    assert spec is not None
    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1)
    assert stats1 is not None and stats1["body_count"] == 1
    generation1 = world.generation
    signature1 = world.solver_slots[spec.slot_id].data.get("_sync_signature")
    pose_signature1 = world.solver_slots[spec.slot_id].data.get("_kinematic_pose_signature")

    scene.frame_set(2)
    mover.location.z = 2.5
    bpy.context.view_layer.update()
    world2, _, _, restart = physicsWorldBegin(
        cache_state=cache_value,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    assert world2 is world
    assert restart is False
    assert world2.generation == generation1
    slot = world2.solver_slots[spec.slot_id]
    assert slot.data.get("_sync_signature") == signature1
    assert slot.data.get("_kinematic_pose_signature") != pose_signature1
    assert slot.data.get("_jolt_kinematic_pose_dirty") is True

    step_rigid_bodies(world2, enabled=True)
    stats2 = get_rigid_solver_stats_result(
        world2, frame=scene.frame_current, generation=world2.generation)
    assert stats2 is not None
    assert stats2["restart_required"] is False
    assert stats2["body_count"] == 1
    assert "_jolt_kinematic_pose_dirty" not in slot.data
    state = world2.backend_resources["rigid_solver"].get_body_state(spec.slot_id)
    assert state is not None
    assert abs(float(state["position"][2]) - 2.5) < 0.05
    physicsWorldCommit(world2, enabled=True)

    world2.omni_cache_dispose("test_kinematic_dirty")
    _del(mover)


def test_shape_parameter_dirty_resyncs_jolt_body_without_generation_restart():
    scene = bpy.context.scene
    ball = _make_obj("T6G_ShapeDirty", (0, 0, 4), body_type="DYNAMIC")
    scope = make_scope([ball], include_rigid_body=True, include_rigid_constraint=False,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    spec = build_rigid_body_spec(ball)
    assert spec is not None
    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1)
    assert stats1 is not None and stats1["body_count"] == 1
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None
    generation1 = world.generation
    signature1 = world.solver_slots[spec.slot_id].data.get("_sync_signature")

    ball.hotools_rigid_body.shape_radius = 0.9
    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 2)
    assert world2 is world
    assert world2.generation == generation1
    assert world2.frame_context.restart_required is False
    assert stats2 is not None
    assert stats2["restart_required"] is False
    assert stats2["body_count"] == 1
    slot = world2.solver_slots[spec.slot_id]
    assert slot.data.get("_sync_signature") != signature1
    assert slot.data.get("_jolt_generation") == world2.generation
    assert world2.backend_resources.get("rigid_solver") is adapter
    assert adapter.body_count == 1

    world2.omni_cache_dispose("test_shape_dirty")
    _del(ball)


def test_constraint_target_dirty_resyncs_jolt_constraint_without_generation_restart():
    scene = bpy.context.scene
    a = _make_obj("T6H_TargetA", (-1, 0, 2), body_type="DYNAMIC")
    b = _make_obj("T6H_TargetB", (0, 0, 2), body_type="DYNAMIC")
    c = _make_obj("T6H_TargetC", (1, 0, 2), body_type="DYNAMIC")
    empty = _make_constraint_empty("T6H_TargetConstraint", a, b, loc=(0, 0, 2))
    scope = make_scope([a, b, c, empty], include_rigid_body=True, include_rigid_constraint=True,
                       include_passive_collision=False, include_bone_collision=False,
                       include_mesh_collision=False)

    spec = build_constraint_spec(empty)
    assert spec is not None
    world, cache_value, stats1 = _begin_step_commit(scene, None, scope, 1)
    assert stats1 is not None
    assert stats1["body_count"] == 3
    assert stats1["constraint_count"] == 1
    adapter = world.backend_resources.get("rigid_solver")
    assert adapter is not None and adapter.constraint_count == 1
    generation1 = world.generation
    signature1 = world.solver_slots[spec.slot_id].data.get("_sync_signature")

    empty.hotools_rigid_constraint.target_b = c
    world2, _cache_value2, stats2 = _begin_step_commit(scene, cache_value, scope, 2)
    assert world2 is world
    assert world2.generation == generation1
    assert world2.frame_context.restart_required is False
    assert stats2 is not None
    assert stats2["restart_required"] is False
    assert stats2["body_count"] == 3
    assert stats2["constraint_count"] == 1
    slot = world2.solver_slots[spec.slot_id]
    assert slot.data.get("_sync_signature") != signature1
    assert slot.data.get("_jolt_generation") == world2.generation
    assert world2.backend_resources.get("rigid_solver") is adapter
    assert adapter.constraint_count == 1

    world2.omni_cache_dispose("test_constraint_target_dirty")
    _del(a, b, c, empty)


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
    check("rigid body commands exchange", test_rigid_body_commands_exchange)
    check("rigid body command nodes", test_rigid_body_command_nodes)
    check("rigid jolt world settings implicit object pipeline", test_rigid_jolt_world_settings_implicit_object_pipeline)
    check("完整刚体链路（60帧）",         test_full_rigid_pipeline)
    check("contact + sensor event result pipeline", test_contact_and_sensor_event_result_pipeline)
    check("dispose + 重建",             test_dispose_and_rebuild)
    check("runtime cache delete + clear_all dispose", test_runtime_cache_delete_and_clear_all_dispose)
    check("same-frame cached result semantics", test_same_frame_repeats_publish_cached_results_without_step)
    check("frame jump restart semantics", test_frame_jump_back_replaces_world_and_restarts)
    check("scope prune rigid slot semantics", test_scope_prune_removes_rigid_slot_and_resyncs_remaining_body)
    check("reset restart semantics", test_reset_restarts_generation_and_clears_writeback_delta)
    check("static transform dirty resync", test_static_transform_dirty_resyncs_jolt_body_without_generation_restart)
    check("kinematic transform dirty update", test_kinematic_transform_dirty_updates_jolt_body_without_resync_generation)
    check("shape parameter dirty resync", test_shape_parameter_dirty_resyncs_jolt_body_without_generation_restart)
    check("constraint target dirty resync", test_constraint_target_dirty_resyncs_jolt_constraint_without_generation_restart)

    check("ConstraintSpec disable collisions", test_constraint_spec_disable_collisions)
    check("DISTANCE constraint spec + generated properties", test_distance_constraint_spec_and_generated_properties)
    check("constraint state result pipeline", test_constraint_state_result_pipeline)
    check("generated constraint implicit object pipeline", test_generated_constraint_implicit_object_pipeline)

    passed = sum(_results)
    total  = len(_results)
    print("-" * 58)
    print(f"  {passed}/{total} 通过" + ("  全部通过" if passed == total else f"  {total-passed} 失败"))
    print("-" * 58 + "\n")
    sys.exit(0 if passed == total else 1)
