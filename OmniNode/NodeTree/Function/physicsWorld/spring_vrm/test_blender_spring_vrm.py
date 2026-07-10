# -*- coding: utf-8 -*-
"""
SpringBone VRM 新物理世界链路的 Blender 后台集成测试。

用法：
    blender.exe --background --python test_blender_spring_vrm.py
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys
import types as _types


_ADDONS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons"
_HOTOOLS = os.path.join(_ADDONS, "HoTools")
_PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
_NATIVE_LIB = os.path.join(_HOTOOLS, "_Lib", _PY_LIB, "HotoolsPackage")
_NT_DIR = os.path.join(_HOTOOLS, "OmniNode", "NodeTree")
_PW_ROOT = os.path.join(_NT_DIR, "Function", "physicsWorld")
_PKG_PREFIX = "HoTools.OmniNode.NodeTree.Function.physicsWorld"

for _path in (_NATIVE_LIB, _ADDONS):
    if _path not in sys.path:
        sys.path.insert(0, _path)
if _HOTOOLS not in sys.path:
    sys.path.insert(0, _HOTOOLS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bpy
import mathutils


PASS = "[PASS]"
FAIL = "[FAIL]"
_results: list[bool] = []


def _register_physics_props() -> None:
    from PhysicsTools.physicsProperty import PG_Hotools_BoneCollision, PG_Hotools_ObjectCollision

    for cls in (PG_Hotools_BoneCollision, PG_Hotools_ObjectCollision):
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    if not hasattr(bpy.types.Bone, "hotools_collision"):
        bpy.types.Bone.hotools_collision = bpy.props.PointerProperty(type=PG_Hotools_BoneCollision)
    if not hasattr(bpy.types.Object, "hotools_object_collision"):
        bpy.types.Object.hotools_object_collision = bpy.props.PointerProperty(type=PG_Hotools_ObjectCollision)


_register_physics_props()

from PhysicsTools.physicsProperty import PG_Hotools_BoneCollision


def check(name, fn) -> None:
    try:
        fn()
        print(f"  {PASS}  {name}")
        _results.append(True)
    except Exception as exc:
        import traceback

        print(f"  {FAIL}  {name}  =>  {exc}")
        traceback.print_exc()
        _results.append(False)


def _load_pw(suffix: str, file_rel: str):
    full = f"{_PKG_PREFIX}.{suffix}" if suffix else _PKG_PREFIX
    if full in sys.modules:
        return sys.modules[full]
    path = os.path.join(_PW_ROOT, *file_rel.split("/"))
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = full.rsplit(".", 1)[0]
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


_pkg_dirs = [
    ("HoTools", _HOTOOLS),
    ("HoTools.OmniNode", os.path.join(_HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", _NT_DIR),
    ("HoTools.OmniNode.NodeTree.Function", os.path.join(_NT_DIR, "Function")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", _PW_ROOT),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.utils", os.path.join(_PW_ROOT, "utils")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid", os.path.join(_PW_ROOT, "rigid")),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.spring_vrm", os.path.join(_PW_ROOT, "spring_vrm")),
]
for _pkg, _dir in _pkg_dirs:
    if _pkg not in sys.modules:
        _m = _types.ModuleType(_pkg)
        _m.__path__ = [_dir]
        _m.__package__ = _pkg
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


_nt_omni_key = "HoTools.OmniNode.NodeTree.OmniNodeSocketMapping"
if _nt_omni_key not in sys.modules:
    _sm = _types.ModuleType(_nt_omni_key)
    _sm.__package__ = "HoTools.OmniNode.NodeTree"

    class _OmniCache:
        def __new__(cls, value=None):
            return OmniRuntimeState.cache_replace(value)

        @classmethod
        def replace(cls, value):
            return OmniRuntimeState.cache_replace(value)

        @classmethod
        def mutate(cls, value):
            return OmniRuntimeState.cache_mutate(value)

    class _OmniBone(dict):
        pass

    class _OmniBitMask(int):
        def __new__(cls, value=0):
            return int.__new__(cls, value)

    _sm._OmniCache = _OmniCache
    _sm._OmniBone = _OmniBone
    _sm._OmniBitMask = _OmniBitMask
    sys.modules[_nt_omni_key] = _sm
    sys.modules.setdefault("OmniNodeSocketMapping", _sm)


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


_load_pw("names", "names.py")
_load_pw("declarations", "declarations.py")
_load_pw("utils.ids", "utils/ids.py")
_load_pw("utils.values", "utils/values.py")
_load_pw("utils.writeback_pose", "utils/writeback_pose.py")
_load_pw("utils.debug_draw", "utils/debug_draw.py")
_load_pw("types", "types.py")
_load_pw("scope", "scope.py")
_load_pw("rigid.results", "rigid/results.py")
_load_pw("writeback_commands", "writeback_commands.py")
_load_pw("spring_vrm.results", "spring_vrm/results.py")
_load_pw("writeback", "writeback.py")
_load_pw("world", "world.py")
_load_pw("spring_vrm.specs", "spring_vrm/specs.py")
_load_pw("spring_vrm.implicit_objects", "spring_vrm/implicit_objects.py")
_load_pw("spring_vrm.declaration", "spring_vrm/declaration.py")
_load_pw("spring_vrm.capabilities", "spring_vrm/capabilities.py")
_load_pw("spring_vrm.bone_collision", "spring_vrm/bone_collision.py")
_load_pw("spring_vrm.native", "spring_vrm/native.py")
_load_pw("spring_vrm.debug", "spring_vrm/debug.py")
_load_pw("spring_vrm.solver", "spring_vrm/solver.py")
_load_pw("spring_vrm.debug_draw", "spring_vrm/debug_draw.py")
_load_pw("spring_vrm.nodes", "spring_vrm/nodes.py")


def _pw(suffix: str):
    return sys.modules[f"{_PKG_PREFIX}.{suffix}"]


_OmniCache = sys.modules[_nt_omni_key]._OmniCache
PhysicsWorldCache = _pw("types").PhysicsWorldCache
BONE_TRANSFORM_CHANNEL = _pw("names").BONE_TRANSFORM_CHANNEL
COLLIDER_TYPE_CAPSULE = _pw("names").COLLIDER_TYPE_CAPSULE
make_scope = _pw("scope").make_scope
physicsWorldBegin = _pw("world").physicsWorldBegin
physicsWorldCommit = _pw("world").physicsWorldCommit
apply_all_writebacks = _pw("writeback").apply_all_writebacks
physicsSpringVRMChainProperties = _pw("spring_vrm.nodes").physicsSpringVRMChainProperties
physicsSpringVRMChainRegister = _pw("spring_vrm.nodes").physicsSpringVRMChainRegister
physicsBoneCollisionOverrideProperties = _pw("spring_vrm.nodes").physicsBoneCollisionOverrideProperties
physicsSpringVRMSolver = _pw("spring_vrm.nodes").physicsSpringVRMSolver
is_native_available = _pw("spring_vrm.native").is_available
iter_spring_vrm_pose_results = _pw("spring_vrm.results").iter_spring_vrm_pose_results
get_spring_vrm_stats_result = _pw("spring_vrm.results").get_spring_vrm_stats_result
audit_bone_collision_legacy_property_group = _pw("spring_vrm.capabilities").audit_bone_collision_legacy_property_group
resolve_bone_collision_fields = _pw("spring_vrm.bone_collision").resolve_bone_collision_fields
resolve_bone_pin = _pw("spring_vrm.bone_collision").resolve_bone_pin
make_bone_collision_override_properties = _pw("spring_vrm.implicit_objects").make_bone_collision_override_properties
register_bone_collision_override_objects = _pw("spring_vrm.implicit_objects").register_bone_collision_override_objects
register_spring_vrm_chain_objects = _pw("spring_vrm.implicit_objects").register_spring_vrm_chain_objects
native_bone_collision_profile = _pw("spring_vrm.native")._bone_collision_profile
spring_vrm_debug_draw = _pw("spring_vrm.debug_draw")


def _delete_object(obj) -> None:
    if obj is None:
        return
    data = getattr(obj, "data", None)
    try:
        bpy.data.objects.remove(obj, do_unlink=True)
    except Exception:
        pass
    if data is not None and getattr(data, "users", 0) == 0:
        try:
            if getattr(data, "bl_rna", None) is not None and data.bl_rna.identifier == "Armature":
                bpy.data.armatures.remove(data)
            elif getattr(data, "bl_rna", None) is not None and data.bl_rna.identifier == "Mesh":
                bpy.data.meshes.remove(data)
        except Exception:
            pass


def _make_chain_armature(name: str = "PW_SpringVRM_Armature"):
    arm_data = bpy.data.armatures.new(f"{name}Data")
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    root = arm_data.edit_bones.new("root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 1.0)

    bone_1 = arm_data.edit_bones.new("bone_1")
    bone_1.parent = root
    bone_1.use_connect = True
    bone_1.head = root.tail
    bone_1.tail = (0.0, 0.0, 2.0)

    bone_2 = arm_data.edit_bones.new("bone_2")
    bone_2.parent = bone_1
    bone_2.use_connect = True
    bone_2.head = bone_1.tail
    bone_2.tail = (0.0, 0.0, 3.0)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return arm_obj


def _make_multi_chain_armature(name: str = "PW_SpringVRM_MultiChain"):
    arm_data = bpy.data.armatures.new(f"{name}Data")
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    for x, prefix in ((-0.5, "a"), (0.5, "b")):
        root = arm_data.edit_bones.new(f"root_{prefix}")
        root.head = (x, 0.0, 0.0)
        root.tail = (x, 0.0, 1.0)
        bone_1 = arm_data.edit_bones.new(f"{prefix}_1")
        bone_1.parent = root
        bone_1.use_connect = True
        bone_1.head = root.tail
        bone_1.tail = (x, 0.0, 2.0)
        bone_2 = arm_data.edit_bones.new(f"{prefix}_2")
        bone_2.parent = bone_1
        bone_2.use_connect = True
        bone_2.head = bone_1.tail
        bone_2.tail = (x, 0.0, 3.0)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return arm_obj


def _make_branch_armature(name: str = "PW_SpringVRM_Branch"):
    arm_data = bpy.data.armatures.new(f"{name}Data")
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    root = arm_data.edit_bones.new("root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 1.0)
    for x, name_suffix in ((-0.5, "left"), (0.5, "right")):
        child = arm_data.edit_bones.new(name_suffix)
        child.parent = root
        child.use_connect = True
        child.head = root.tail
        child.tail = (x, 0.0, 2.0)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()
    return arm_obj


def _make_sphere_collider(name: str, location, radius: float, group: int = 1):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    props = obj.hotools_object_collision
    props.enabled = True
    props.collision_type = "SPHERE"
    props.radius = float(radius)
    props.primary_collision_group = int(group)
    bpy.context.view_layer.update()
    return obj


def _make_capsule_collider(name: str, location, radius: float, length: float, group: int = 1):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    props = obj.hotools_object_collision
    props.enabled = True
    props.collision_type = "CAPSULE"
    props.radius = float(radius)
    props.length = float(length)
    props.primary_collision_group = int(group)
    bpy.context.view_layer.update()
    return obj


def _make_plane_collider(name: str, location, normal_axis: str = "+X", group: int = 1):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    if normal_axis == "+X":
        obj.rotation_euler = (0.0, math.radians(90.0), 0.0)
    elif normal_axis == "-X":
        obj.rotation_euler = (0.0, math.radians(-90.0), 0.0)
    props = obj.hotools_object_collision
    props.enabled = True
    props.collision_type = "PLANE"
    props.length = 4.0
    props.primary_collision_group = int(group)
    bpy.context.view_layer.update()
    return obj


def _make_box_collider(name: str, location, size, group: int = 1):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    props = obj.hotools_object_collision
    props.enabled = True
    props.collision_type = "BOX"
    props.box_size = size
    props.primary_collision_group = int(group)
    bpy.context.view_layer.update()
    return obj


def _enable_bone_hit_radius(armature, bone_name: str = "bone_1", radius: float = 0.15, mask: int = 1) -> None:
    props = armature.data.bones[bone_name].hotools_collision
    props.collision_type = "SPHERE"
    props.radius = float(radius)
    props.collided_by_groups = int(mask)


def _bone_value(armature, bone_name: str) -> dict:
    return {"armature": armature, "bone": bone_name}


def _world_for_frame(
    cache,
    armature,
    frame: int,
    reset: bool = False,
    extra_objects: list | None = None,
    include_passive_collision: bool = False,
    time_scale: float = 1.0,
):
    scene = bpy.context.scene
    scene.frame_set(frame)
    objects = [armature]
    if extra_objects:
        objects.extend(extra_objects)
    scope = make_scope(
        objects,
        include_passive_collision=include_passive_collision,
        include_bone_collision=False,
        include_mesh_collision=False,
        include_rigid_body=False,
        include_rigid_constraint=False,
        include_hidden=True,
    )
    return physicsWorldBegin(
        cache,
        scene,
        scope,
        enabled=True,
        reset=reset,
        time_scale=float(time_scale),
        substeps=1,
        debug_output=False,
    )


def _tail_world(armature, bone_name: str) -> mathutils.Vector:
    pose_bone = armature.pose.bones[bone_name]
    return armature.matrix_world @ pose_bone.tail


def _basis_delta_from_identity(pose_bone) -> float:
    identity = mathutils.Matrix.Identity(4)
    return sum(abs(float(pose_bone.matrix_basis[row][col] - identity[row][col])) for row in range(4) for col in range(4))


def _run_spring_frame(
    cache,
    armature,
    frame: int,
    reset: bool = False,
    extra_objects: list | None = None,
    include_passive_collision: bool = False,
    expected_collider_count: int | None = None,
    stiffness_force: float = 0.0,
    drag_force: float = 0.0,
    gravity_dir=None,
    gravity_power: float = 9.8,
    substeps: int = 1,
    time_scale: float = 1.0,
    return_details: bool = False,
):
    world, _frame, _collider_count, restart = _world_for_frame(
        cache,
        armature,
        frame,
        reset=reset,
        extra_objects=extra_objects,
        include_passive_collision=include_passive_collision,
        time_scale=float(time_scale),
    )
    properties = physicsSpringVRMChainProperties(
        [_bone_value(armature, "root")],
        stiffness_force=float(stiffness_force),
        drag_force=float(drag_force),
        gravity_dir=mathutils.Vector(gravity_dir or (1.0, 0.0, 0.0)),
        gravity_power=float(gravity_power),
    )
    world, object_count, dirty_count, _version = physicsSpringVRMChainRegister(world, properties)
    assert object_count == 1, f"应注册 1 条 VRM 骨链，实际 {object_count}"
    assert dirty_count >= 0

    world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=max(1, int(substeps)))
    assert write_count == 2, f"应产生 2 个 PoseBone 写回项，实际 {write_count}"

    results = list(iter_spring_vrm_pose_results(
        world,
        frame=frame,
        generation=world.generation,
    ))
    assert len(results) == 2, f"result stream 应包含 2 项，实际 {len(results)}"
    assert all(item.get("channel") == BONE_TRANSFORM_CHANNEL for item in results), (
        f"SpringBone 应输出通用 bone_transform 写回通道，实际 {results}"
    )
    assert all(item.get("writeback_type") == "bone_transform" for item in results), (
        f"SpringBone 应输出通用骨骼写回指令，实际 {results}"
    )
    assert all(item.get("source_kind") == "spring_vrm" for item in results), (
        f"SpringBone 写回指令应保留 source_kind=spring_vrm，实际 {results}"
    )

    written = apply_all_writebacks(world, restart=restart)
    assert written == 2, f"应写回 2 根模拟骨骼，实际 {written}"

    stats = get_spring_vrm_stats_result(world, frame=frame, generation=world.generation)
    assert stats is not None, "缺少 SpringBone VRM stats result"
    assert stats.get("status") == "ok", f"stats 状态异常: {stats}"
    if expected_collider_count is not None:
        assert int(stats.get("collider_count", -1)) == int(expected_collider_count), (
            f"stats collider_count 应为 {expected_collider_count}，实际 {stats}"
        )

    cache, _world, solver_count = physicsWorldCommit(world, enabled=True)
    assert solver_count == 1, f"应只有 1 个 SpringBone solver slot，实际 {solver_count}"
    if return_details:
        return cache, world, stats, results
    return cache


def _run_spring_after_reset(cache, armature, frame: int, **kwargs):
    cache = _run_spring_frame(cache, armature, frame, reset=True, **kwargs)
    return _run_spring_frame(cache, armature, frame + 1, reset=False, **kwargs)


def _spring_slot_ids(world) -> list[str]:
    return [
        str(slot_id)
        for slot_id, slot in world.solver_slots.items()
        if getattr(slot, "kind", "") == "spring_vrm"
    ]


def _spring_chain_context(world, root_bone: str = "root"):
    slot_ids = _spring_slot_ids(world)
    assert len(slot_ids) == 1, f"expected one SpringBone slot, got {slot_ids}"
    slot = world.solver_slots[slot_ids[0]]
    native_context = slot.data.get("_native_ctxs")
    assert isinstance(native_context, dict), "SpringBone slot should keep native contexts in _native_ctxs"
    chain_context = native_context.get(root_bone)
    assert hasattr(chain_context, "debug_dict"), f"missing SpringBone native context for {root_bone!r}"
    return slot, native_context, chain_context


def _runtime_cache_spring_step(scene, cache_state, armature, frame: int):
    scene.frame_set(frame)
    cache_value, world, stats, results = _run_spring_frame(
        cache_state,
        armature,
        frame,
        reset=(frame == 1),
        return_details=True,
    )
    return world, cache_value, stats, results


def _assert_world_disposed(world, label: str) -> None:
    assert isinstance(world, PhysicsWorldCache), f"{label} world type mismatch"
    assert not bool(getattr(world, "valid", True)), f"{label} world.valid should be False"
    assert not world.solver_slots, f"{label} solver_slots should be empty"
    assert not world.backend_resources, f"{label} backend_resources should be empty"
    assert not world.implicit_objects, f"{label} implicit_objects should be empty"
    assert not world.result_streams, f"{label} result_streams should be empty"


def _assert_basis_identity(armature, bone_name: str, label: str) -> None:
    delta = _basis_delta_from_identity(armature.pose.bones[bone_name])
    assert delta < 1.0e-6, f"{label} {bone_name} matrix_basis should be identity, delta={delta}"


def test_native_available():
    assert is_native_available(), "hotools_native SpringBone context API 不可用"


def test_spring_vrm_vertical_slice():
    armature = _make_chain_armature()
    try:
        before_tail = _tail_world(armature, "bone_1").copy()
        before_basis_delta = _basis_delta_from_identity(armature.pose.bones["bone_1"])

        cache = _OmniCache()
        cache = _run_spring_frame(cache, armature, 1, reset=True)
        bpy.context.view_layer.update()

        reset_tail = _tail_world(armature, "bone_1")
        reset_basis_delta = _basis_delta_from_identity(armature.pose.bones["bone_1"])
        assert (reset_tail - before_tail).length < 1.0e-5, (
            f"reset frame should publish the input pose, before={tuple(before_tail)} reset={tuple(reset_tail)}"
        )
        assert reset_basis_delta <= before_basis_delta + 1.0e-6, "reset frame should not write a simulated basis"

        cache = _run_spring_frame(cache, armature, 2, reset=False)
        bpy.context.view_layer.update()
        second_tail = _tail_world(armature, "bone_1")
        second_basis_delta = _basis_delta_from_identity(armature.pose.bones["bone_1"])
        assert second_tail.x > before_tail.x + 1.0e-4, (
            f"bone_1 tail 应沿 X 方向被 SpringBone 推动，before={tuple(before_tail)} second={tuple(second_tail)}"
        )
        assert second_basis_delta > before_basis_delta + 1.0e-6, "matrix_basis 未发生可观测写回"
        assert cache.value is not None
    finally:
        _delete_object(armature)


def test_spring_vrm_stiffness_rest_pose_has_no_side_force():
    armature = _make_chain_armature("PW_SpringVRM_NoSideForce")
    try:
        before_tail = _tail_world(armature, "bone_1").copy()
        cache = _OmniCache()
        cache = _run_spring_frame(
            cache,
            armature,
            100,
            reset=True,
            stiffness_force=1.0,
            gravity_power=0.0,
        )
        cache = _run_spring_frame(
            cache,
            armature,
            101,
            reset=False,
            stiffness_force=1.0,
            gravity_power=0.0,
        )
        bpy.context.view_layer.update()
        after_tail = _tail_world(armature, "bone_1")
        assert (after_tail - before_tail).length < 1.0e-5, (
            f"rest pose should not get a synthetic side force, before={tuple(before_tail)} after={tuple(after_tail)}"
        )
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6
        assert cache.value is not None
    finally:
        _delete_object(armature)


def test_spring_vrm_frame_jump_resets_without_step():
    armature = _make_chain_armature("PW_SpringVRM_FrameJump")
    try:
        initial_tail = _tail_world(armature, "bone_1").copy()
        cache = _OmniCache()
        cache = _run_spring_frame(cache, armature, 1, reset=True)
        cache = _run_spring_frame(cache, armature, 2, reset=False)
        bpy.context.view_layer.update()
        moved_tail = _tail_world(armature, "bone_1").copy()
        assert moved_tail.x > initial_tail.x + 1.0e-4, (
            f"continuous frame should move before jump, initial={tuple(initial_tail)} moved={tuple(moved_tail)}"
        )

        cache, world, _stats, _results = _run_spring_frame(
            cache,
            armature,
            10,
            reset=False,
            return_details=True,
        )
        bpy.context.view_layer.update()
        reset_tail = _tail_world(armature, "bone_1")
        assert bool(getattr(world.frame_context, "restart_required", False)) is True
        assert (reset_tail - initial_tail).length < 1.0e-5, (
            f"jump frame should restore input pose, initial={tuple(initial_tail)} reset={tuple(reset_tail)}"
        )
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6

        cache, backward_world, _stats, _results = _run_spring_frame(
            cache,
            armature,
            5,
            reset=False,
            return_details=True,
        )
        assert bool(getattr(backward_world.frame_context, "restart_required", False)) is True
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6
        assert cache.value is not None
    finally:
        _delete_object(armature)


def test_spring_vrm_same_frame_republishes_cached_results():
    armature = _make_chain_armature("PW_SpringVRM_SameFrame")
    try:
        cache = _OmniCache()
        cache, world1, stats1, results1 = _run_spring_frame(
            cache,
            armature,
            70,
            reset=True,
            return_details=True,
        )
        slot_ids1 = _spring_slot_ids(world1)
        assert len(slot_ids1) == 1
        assert stats1.get("writeback_count") == 2
        assert len(results1) == 2
        _slot1, _native_context1, chain_context1 = _spring_chain_context(world1)
        step_count1 = int(chain_context1.debug_dict().get("step_count", 0) or 0)
        assert step_count1 == 0

        cache, world2, stats2, results2 = _run_spring_frame(
            cache,
            armature,
            70,
            reset=False,
            return_details=True,
        )
        assert world2 is world1
        assert world2.frame_context.same_frame is True
        assert world2.frame_context.restart_required is False
        assert _spring_slot_ids(world2) == slot_ids1
        assert stats2.get("step_ms") == 0.0
        assert stats2.get("writeback_count") == 2
        assert len(results2) == 2
        _slot2, _native_context2, chain_context2 = _spring_chain_context(world2)
        assert chain_context2 is chain_context1
        assert int(chain_context2.debug_dict().get("step_count", 0) or 0) == step_count1
        assert stats2.get("native_context", {}).get("step_count") == step_count1
    finally:
        _delete_object(armature)


def test_spring_vrm_zero_or_negative_time_scale_pauses():
    armature = _make_chain_armature("PW_SpringVRM_PausedTime")
    try:
        cache, world1, _stats1, _results1 = _run_spring_frame(
            _OmniCache(), armature, 74, reset=True, return_details=True,
        )
        _slot1, _contexts1, context1 = _spring_chain_context(world1)
        assert int(context1.debug_dict().get("step_count", 0) or 0) == 0

        for frame, scale in ((75, 0.0), (76, -2.0)):
            cache, world, stats, results = _run_spring_frame(
                cache,
                armature,
                frame,
                reset=False,
                time_scale=scale,
                return_details=True,
            )
            _slot, _contexts, context = _spring_chain_context(world)
            assert context is context1
            assert int(context.debug_dict().get("step_count", 0) or 0) == 0
            assert stats.get("writeback_count") == 2
            assert len(results) == 2
            assert all(
                math.isfinite(float(value))
                for result in results
                for value in result.get("matrix_basis", ())
            )
    finally:
        _delete_object(armature)


def test_spring_vrm_runtime_parameter_change_reuses_slot():
    armature = _make_chain_armature("PW_SpringVRM_Prune")
    try:
        cache = _OmniCache()
        cache, world1, stats1, _results1 = _run_spring_frame(
            cache,
            armature,
            80,
            reset=True,
            gravity_power=2.0,
            return_details=True,
        )
        slot_ids1 = _spring_slot_ids(world1)
        assert len(slot_ids1) == 1
        assert stats1.get("slot_count") == 1
        _slot, _native_context, chain_context = _spring_chain_context(world1)
        assert chain_context.debug_dict().get("buffer_shapes"), "first SpringBone slot should build native context buffers"
        step_count1 = int(chain_context.debug_dict().get("step_count", 0) or 0)

        cache, world2, stats2, _results2 = _run_spring_frame(
            cache,
            armature,
            81,
            reset=False,
            gravity_power=7.0,
            return_details=True,
        )
        slot_ids2 = _spring_slot_ids(world2)
        assert world2 is world1
        assert len(slot_ids2) == 1
        assert stats2.get("slot_count") == 1
        assert slot_ids2[0] == slot_ids1[0], "runtime parameter changes should not replace the SpringBone slot"
        slot2, _native_context2, chain_context2 = _spring_chain_context(world2)
        assert slot2 is _slot
        assert chain_context2 is chain_context
        assert int(chain_context2.debug_dict().get("step_count", 0) or 0) == step_count1 + 1
    finally:
        _delete_object(armature)


def test_spring_vrm_public_parameters_reach_native_context():
    armature = _make_chain_armature("PW_SpringVRM_ParameterMatrix")
    module = _pw("spring_vrm.native").native_module()
    original_update = module.spring_vrm_update_dynamic
    original_step = module.spring_vrm_step
    observed = {"gravity_dir": [], "step": []}

    def capture_update(*args):
        observed["gravity_dir"].append(tuple(float(value) for value in args[10]))
        return original_update(*args)

    def capture_step(*args):
        observed["step"].append(tuple(args[1:]))
        return original_step(*args)

    module.spring_vrm_update_dynamic = capture_update
    module.spring_vrm_step = capture_step
    try:
        cache = _OmniCache()
        cache = _run_spring_frame(
            cache,
            armature,
            82,
            reset=True,
            stiffness_force=2.5,
            drag_force=0.7,
            gravity_dir=(0.0, 1.0, 0.0),
            gravity_power=4.25,
            substeps=5,
        )
        _run_spring_frame(
            cache,
            armature,
            83,
            reset=False,
            stiffness_force=2.5,
            drag_force=0.7,
            gravity_dir=(0.0, 1.0, 0.0),
            gravity_power=4.25,
            substeps=5,
        )
        assert observed["gravity_dir"][-1] == (0.0, 1.0, 0.0), observed
        dt, substeps, stiffness, drag, gravity_power = observed["step"][-1]
        assert abs(float(dt) - (1.0 / 24.0)) < 1.0e-6, observed
        assert int(substeps) == 5, observed
        assert abs(float(stiffness) - 2.5) < 1.0e-6, observed
        assert abs(float(drag) - 0.7) < 1.0e-6, observed
        assert abs(float(gravity_power) - 4.25) < 1.0e-6, observed
    finally:
        module.spring_vrm_update_dynamic = original_update
        module.spring_vrm_step = original_step
        _delete_object(armature)


def test_spring_vrm_spec_clamps_public_parameter_bounds():
    armature = _make_chain_armature("PW_SpringVRM_ParameterBounds")
    try:
        properties = physicsSpringVRMChainProperties(
            [_bone_value(armature, "root")],
            stiffness_force=-3.0,
            drag_force=4.0,
            gravity_power=-8.0,
        )
        specs = _pw("spring_vrm.specs").build_spring_vrm_solver_specs(
            properties,
            backend="cpp",
            substeps=99,
        )
        assert len(specs) == 1
        spec = specs[0]
        chain = spec.chains[0]
        assert chain.stiffness_force == 0.0
        assert chain.drag_force == 1.0
        assert chain.gravity_power == 0.0
        assert spec.substeps == 16
    finally:
        _delete_object(armature)


def test_spring_vrm_multiple_armatures_create_isolated_slots():
    armature_a = _make_chain_armature("PW_SpringVRM_MultiA")
    armature_b = _make_chain_armature("PW_SpringVRM_MultiB")
    try:
        cache = _OmniCache()
        world, _frame, _collider_count, restart = _world_for_frame(
            cache,
            armature_a,
            84,
            reset=True,
            extra_objects=[armature_b],
        )
        properties = []
        for armature in (armature_a, armature_b):
            properties.extend(physicsSpringVRMChainProperties([_bone_value(armature, "root")]))
        world, object_count, _dirty_count, _version = physicsSpringVRMChainRegister(world, properties)
        assert object_count == 2
        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 4
        assert apply_all_writebacks(world, restart=restart) == 4
        cache, committed_world, solver_count = physicsWorldCommit(world, enabled=True)
        assert cache.value is committed_world
        assert solver_count == 2
        slot_ids = _spring_slot_ids(world)
        assert len(slot_ids) == 2 and slot_ids[0] != slot_ids[1]
    finally:
        _delete_object(armature_b)
        _delete_object(armature_a)


def test_spring_vrm_multiple_chains_share_one_armature_slot():
    armature = _make_multi_chain_armature()
    try:
        world, _frame, _collider_count, restart = _world_for_frame(
            _OmniCache(), armature, 85, reset=True,
        )
        properties = physicsSpringVRMChainProperties([
            _bone_value(armature, "root_a"),
            _bone_value(armature, "root_b"),
        ])
        assert len(properties) == 2
        world, object_count, _dirty_count, _version = physicsSpringVRMChainRegister(world, properties)
        assert object_count == 2
        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 4
        assert apply_all_writebacks(world, restart=restart) == 4
        slot_ids = _spring_slot_ids(world)
        assert len(slot_ids) == 1
        slot = world.solver_slots[slot_ids[0]]
        assert slot.data["spec"].chain_count == 2
        assert set(slot.data["_native_ctxs"]) == {"root_a", "root_b"}
    finally:
        _delete_object(armature)


def test_spring_vrm_rejects_duplicate_roots_and_overlapping_bones():
    armature = _make_chain_armature("PW_SpringVRM_InvalidTopology")
    build_specs = _pw("spring_vrm.specs").build_spring_vrm_solver_specs
    base = physicsSpringVRMChainProperties([_bone_value(armature, "root")])[0]
    try:
        try:
            build_specs([base, dict(base)], backend="cpp", substeps=1)
        except ValueError as exc:
            assert "root bone 重复" in str(exc)
        else:
            raise AssertionError("duplicate SpringBone roots must be rejected")

        nested = dict(base)
        nested["root_bone"] = "bone_1"
        nested["bones"] = ["bone_1", "bone_2"]
        try:
            build_specs([base, nested], backend="cpp", substeps=1)
        except ValueError as exc:
            assert "模拟骨重复" in str(exc)
        else:
            raise AssertionError("overlapping simulated bones must be rejected")
    finally:
        _delete_object(armature)


def test_spring_vrm_branch_chain_reaches_native_context():
    armature = _make_branch_armature()
    try:
        world, _frame, _collider_count, _restart = _world_for_frame(
            _OmniCache(), armature, 86, reset=True,
        )
        properties = physicsSpringVRMChainProperties([_bone_value(armature, "root")])
        assert properties[0]["bones"] == ["root", "left", "right"]
        world, _count, _dirty, _version = physicsSpringVRMChainRegister(world, properties)
        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 2
        _slot, _contexts, context = _spring_chain_context(world)
        assert [record["bone_name"] for record in context._records] == ["left", "right"]
        assert tuple(int(value) for value in context._static["parent_indices"]) == (-1, -1)
        assert tuple(int(value) for value in context._static["use_connect"]) == (1, 1)
    finally:
        _delete_object(armature)


def test_spring_vrm_topology_change_disposes_old_slot():
    armature = _make_multi_chain_armature("PW_SpringVRM_TopologyChange")
    try:
        cache = _OmniCache()
        world, _frame, _collider_count, _restart = _world_for_frame(cache, armature, 87, reset=True)
        chain_a = physicsSpringVRMChainProperties([_bone_value(armature, "root_a")])
        register_spring_vrm_chain_objects(world, chain_a, enabled=True)
        physicsSpringVRMSolver(world, substeps=1)
        old_slot_id = _spring_slot_ids(world)[0]
        old_slot = world.solver_slots[old_slot_id]
        old_context = old_slot.data["_native_ctxs"]["root_a"]
        assert old_context._handle is not None
        cache, _committed, _count = physicsWorldCommit(world, enabled=True)

        world, _frame, _collider_count, _restart = _world_for_frame(cache, armature, 88, reset=False)
        register_spring_vrm_chain_objects(world, chain_a, enabled=False)
        chain_b = physicsSpringVRMChainProperties([_bone_value(armature, "root_b")])
        register_spring_vrm_chain_objects(world, chain_b, enabled=True)
        physicsSpringVRMSolver(world, substeps=1)

        new_slot_ids = _spring_slot_ids(world)
        assert len(new_slot_ids) == 1 and new_slot_ids[0] != old_slot_id
        assert old_slot.data == {}
        assert old_context._handle is None
        new_slot = world.solver_slots[new_slot_ids[0]]
        assert set(new_slot.data["_native_ctxs"]) == {"root_b"}
    finally:
        _delete_object(armature)


def test_spring_vrm_override_pin_reaches_native_static_state():
    armature = _make_chain_armature("PW_SpringVRM_OverridePinRuntime")

    def run_frame(cache, frame: int, reset: bool):
        world, _frame, _collider_count, restart = _world_for_frame(
            cache,
            armature,
            frame,
            reset=reset,
        )
        properties = physicsSpringVRMChainProperties(
            [_bone_value(armature, "root")],
            gravity_dir=(1.0, 0.0, 0.0),
            gravity_power=9.8,
        )
        physicsSpringVRMChainRegister(world, properties)
        override = make_bone_collision_override_properties(
            _bone_value(armature, "bone_1"),
            pin=True,
        )
        register_bone_collision_override_objects(world, [override])
        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 2
        apply_all_writebacks(world, restart=restart)
        cache, _world, _solver_count = physicsWorldCommit(world, enabled=True)
        return cache, world

    try:
        cache, _world1 = run_frame(_OmniCache(), 87, True)
        cache, world2 = run_frame(cache, 88, False)
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6
        _slot, _contexts, context = _spring_chain_context(world2)
        pinned = getattr(context, "_static", {}).get("pinned")
        assert pinned is not None and int(pinned[0]) == 1, pinned
    finally:
        _delete_object(armature)


def test_spring_vrm_non_root_pin_keeps_pose():
    armature = _make_chain_armature("PW_SpringVRM_Pin")
    try:
        armature.data.bones["bone_1"].hotools_collision.pin = True
        cache = _OmniCache()
        cache = _run_spring_frame(
            cache,
            armature,
            85,
            reset=True,
            gravity_power=9.8,
        )
        cache = _run_spring_frame(
            cache,
            armature,
            86,
            reset=False,
            gravity_power=9.8,
        )
        bpy.context.view_layer.update()
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6, (
            "non-root hotools_collision.pin should keep the simulated bone pose unchanged"
        )
    finally:
        _delete_object(armature)


def test_spring_vrm_native_context_reuses_chain_buffers():
    armature = _make_chain_armature("PW_SpringVRM_NativeContext")
    try:
        cache = _OmniCache()
        cache, world1, stats1, _results1 = _run_spring_frame(
            cache,
            armature,
            90,
            reset=True,
            return_details=True,
        )
        slot1, native_context1, chain_context1 = _spring_chain_context(world1)
        debug1 = chain_context1.debug_dict()
        arrays1 = getattr(chain_context1, "_dynamic", None)
        assert isinstance(arrays1, dict) and arrays1, "SpringBone native_context should own chain buffers"
        assert debug1.get("bone_count") == 2
        assert debug1.get("last_frame") == 90
        assert debug1.get("step_count") == 0
        assert debug1.get("cpp_handle") is True
        assert stats1.get("native_context", {}).get("chain_count") == 1
        assert stats1.get("native_context", {}).get("cpp_handle_count") == 1
        assert stats1.get("native_context", {}).get("buffer_count") >= len(arrays1)
        raw_results1 = world1.result_streams.get(BONE_TRANSFORM_CHANNEL) or []
        assert len(raw_results1) == 1
        assert raw_results1[0].get("writeback_type") == "bone_transform_batch"
        assert raw_results1[0].get("bone_count") == 2
        assert "armature" not in raw_results1[0] and "batches" not in raw_results1[0]
        writeback_plan1 = slot1.data.get("writeback_plan")
        assert writeback_plan1.get("schema") == "spring_vrm_writeback_plan_v1"
        assert len(writeback_plan1.get("batches") or ()) == 1
        basis_values1 = writeback_plan1.get("basis_values")
        assert isinstance(basis_values1, list) and len(basis_values1) == len(armature.pose.bones) * 16
        buffer_ids = {name: id(value) for name, value in arrays1.items()}

        cache, world2, stats2, _results2 = _run_spring_frame(
            cache,
            armature,
            91,
            reset=False,
            return_details=True,
        )
        slot2, native_context2, chain_context2 = _spring_chain_context(world2)
        assert world2 is world1
        assert slot2 is slot1
        assert native_context2 is native_context1
        assert chain_context2 is chain_context1
        writeback_plan2 = slot2.data.get("writeback_plan")
        assert writeback_plan2 is writeback_plan1
        assert writeback_plan2.get("basis_values") is basis_values1
        debug2 = chain_context2.debug_dict()
        assert debug2.get("last_frame") == 91
        assert debug2.get("step_count") == 1
        assert {name: id(value) for name, value in getattr(chain_context2, "_dynamic").items()} == buffer_ids
        assert stats2.get("native_context", {}).get("step_count") == 1
        assert stats2.get("native_context", {}).get("cpp_handle_count") == 1

        debug_snapshot = slot2.debug_snapshot()
        debug_context = debug_snapshot.get("native_context")
        assert debug_context and debug_context.get("available") is True
        assert debug_context.get("schema") == "spring_vrm_native_context_v2"
        assert debug_context.get("chain_count") == 1
        debug_chain = debug_context.get("chains", [])[0]
        assert debug_chain.get("cpp_handle") is True
        assert debug_chain.get("root_bone") == "root"
        assert debug_chain.get("buffer_shapes", {}).get("current_tails") == [2, 3]
        assert debug_chain.get("buffer_shapes", {}).get("current_pose_matrices") == [2, 16]

        world_debug = world2.omni_cache_debug_snapshot()
        world_slot_debug = world_debug.get("solver_slots", {}).get(slot2.slot_id, {})
        world_context = world_slot_debug.get("native_context", {})
        assert world_context.get("available") is True
        assert world_context.get("chains", [])[0].get("buffer_shapes", {}).get("current_tails") == [2, 3]
    finally:
        _delete_object(armature)


def test_spring_vrm_nonuniform_scale_uses_axis_world_length():
    armature = _make_chain_armature("PW_SpringVRM_NonuniformScale")
    try:
        armature.scale = (2.0, 1.0, 3.0)
        bpy.context.view_layer.update()
        cache = _OmniCache()
        _cache, world, _stats, _results = _run_spring_frame(
            cache,
            armature,
            92,
            reset=True,
            gravity_power=0.0,
            return_details=True,
        )
        _slot, _native_context, chain_context = _spring_chain_context(world)
        lengths = getattr(chain_context, "_static", {}).get("lengths")
        assert lengths is not None and len(lengths) == 2
        assert all(abs(float(value) - 3.0) < 1.0e-5 for value in lengths), lengths
    finally:
        _delete_object(armature)


def test_spring_vrm_mirrored_scale_and_box_are_finite():
    armature = _make_chain_armature("PW_SpringVRM_Mirrored")
    box = _make_box_collider(
        "PW_SpringVRM_MirroredBox",
        (0.4, 0.0, 1.8),
        (0.5, 0.7, 0.9),
        group=1,
    )
    try:
        armature.scale = (-1.0, 1.5, 0.75)
        box.scale = (-1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        cache = _run_spring_frame(
            _OmniCache(),
            armature,
            89,
            reset=True,
            extra_objects=[box],
            include_passive_collision=True,
        )
        cache, world, _stats, results = _run_spring_frame(
            cache,
            armature,
            90,
            reset=False,
            extra_objects=[box],
            include_passive_collision=True,
            return_details=True,
        )
        assert cache.value is world
        assert all(
            math.isfinite(float(value))
            for result in results
            for value in result.get("matrix_basis", ())
        )
        _slot, _contexts, context = _spring_chain_context(world)
        assert all(math.isfinite(float(value)) for value in context._static["lengths"])
        assert all(float(value) > 0.0 for value in context._static["lengths"])
        arrays = context._collider_cache_arrays
        assert arrays is not None and len(arrays[0]) == 1
        assert all(math.isfinite(float(value)) for array in arrays[2:] for value in array.ravel())
    finally:
        _delete_object(box)
        _delete_object(armature)


def test_spring_vrm_debug_capture_is_next_frame_state_machine():
    armature = _make_chain_armature("PW_SpringVRM_DebugState")
    try:
        cache = _OmniCache()
        cache, world1, _stats1, _results1 = _run_spring_frame(
            cache,
            armature,
            93,
            reset=True,
            return_details=True,
        )
        slot1, _native_context1, chain_context1 = _spring_chain_context(world1)
        assert chain_context1.debug_draw_snapshot() is None

        used = spring_vrm_debug_draw._append_slot_context_debug_lines(
            slot1,
            world1,
            [],
            [],
            [],
        )
        assert used is False, "first debug request should use the regular result fallback"
        capture_state = slot1.data.get("_debug_capture_state")
        assert capture_state == {"requested": True, "request_frame": 93}, capture_state

        cache, world2, _stats2, _results2 = _run_spring_frame(
            cache,
            armature,
            94,
            reset=False,
            return_details=True,
        )
        slot2, _native_context2, chain_context2 = _spring_chain_context(world2)
        assert slot2 is slot1 and chain_context2 is chain_context1
        snapshot = chain_context2.debug_draw_snapshot()
        assert isinstance(snapshot, dict) and snapshot.get("source") == "cpp_context", snapshot
        capture_state = slot2.data.get("_debug_capture_state")
        assert capture_state.get("requested") is False
        assert int(capture_state.get("captured_frame", -1)) == 94

        spring_vrm_debug_draw._append_slot_context_debug_lines(slot2, world2, [], [], [])
        original_refresh = chain_context2.refresh_debug_draw_snapshot

        def fail_debug_capture(*_args, **_kwargs):
            raise RuntimeError("intentional debug readback failure")

        chain_context2.refresh_debug_draw_snapshot = fail_debug_capture
        try:
            _cache3, world3, stats3, results3 = _run_spring_frame(
                cache,
                armature,
                95,
                reset=False,
                return_details=True,
            )
        finally:
            chain_context2.refresh_debug_draw_snapshot = original_refresh
        assert stats3.get("status") == "ok", stats3
        assert len(results3) == 2
        state3 = slot2.data.get("_debug_capture_state")
        assert state3.get("requested") is False
        assert int(state3.get("attempted_frame", -1)) == 95
        assert "intentional debug readback failure" in str(state3.get("error"))
    finally:
        _delete_object(armature)


def test_spring_vrm_collider_arrays_cache_reuses_snapshot():
    armature = _make_chain_armature("PW_SpringVRM_ColliderArrayCache")
    collider = _make_sphere_collider(
        "PW_SpringVRM_ColliderArrayCacheSphere",
        (0.35, 0.0, 1.93),
        0.35,
        group=1,
    )
    try:
        _enable_bone_hit_radius(armature, "bone_1", radius=0.15, mask=1)
        cache = _OmniCache()
        cache, world1, _stats1, _results1 = _run_spring_frame(
            cache,
            armature,
            95,
            reset=True,
            extra_objects=[collider],
            include_passive_collision=True,
            expected_collider_count=1,
            return_details=True,
        )
        slot1, _native_context1, chain_context1 = _spring_chain_context(world1)
        spec1 = slot1.data.get("spec")
        chain1 = spec1.chains[0]
        before = chain_context1.debug_dict().get("collider_cache") or {}
        assert int(before.get("misses", 0) or 0) >= 1
        arrays1 = chain_context1._collision_arrays(world1, armature, chain1)
        arrays2 = chain_context1._collision_arrays(world1, armature, chain1)
        assert arrays2 is arrays1, "same-frame SpringBone collider arrays should reuse the context cache tuple"
        after_hits = chain_context1.debug_dict().get("collider_cache") or {}
        assert int(after_hits.get("hits", 0) or 0) >= int(before.get("hits", 0) or 0) + 2

        cache, world2, _stats2, _results2 = _run_spring_frame(
            cache,
            armature,
            96,
            reset=False,
            extra_objects=[collider],
            include_passive_collision=True,
            expected_collider_count=1,
            return_details=True,
        )
        _slot2, _native_context2, chain_context2 = _spring_chain_context(world2)
        assert chain_context2 is chain_context1
        after_miss = chain_context2.debug_dict().get("collider_cache") or {}
        assert int(after_miss.get("misses", 0) or 0) > int(after_hits.get("misses", 0) or 0), (
            "new PhysicsWorld collider_snapshot should invalidate SpringBone collider array cache"
        )
    finally:
        _delete_object(collider)
        _delete_object(armature)


def test_spring_vrm_moving_collider_refreshes_native_arrays():
    armature = _make_chain_armature("PW_SpringVRM_MovingCollider")
    collider = _make_sphere_collider(
        "PW_SpringVRM_MovingColliderSphere",
        (0.35, 0.0, 1.93),
        0.2,
        group=1,
    )
    try:
        cache, world1, _stats1, _results1 = _run_spring_frame(
            _OmniCache(),
            armature,
            97,
            reset=True,
            extra_objects=[collider],
            include_passive_collision=True,
            return_details=True,
        )
        slot1, _contexts1, context1 = _spring_chain_context(world1)
        chain1 = slot1.data["spec"].chains[0]
        arrays1 = context1._collision_arrays(world1, armature, chain1)
        center1 = mathutils.Vector(arrays1[2][0])

        collider.location.x += 0.8
        collider.location.z -= 0.25
        bpy.context.view_layer.update()
        cache, world2, _stats2, _results2 = _run_spring_frame(
            cache,
            armature,
            98,
            reset=False,
            extra_objects=[collider],
            include_passive_collision=True,
            return_details=True,
        )
        slot2, _contexts2, context2 = _spring_chain_context(world2)
        chain2 = slot2.data["spec"].chains[0]
        arrays2 = context2._collision_arrays(world2, armature, chain2)
        center2 = mathutils.Vector(arrays2[2][0])
        assert context2 is context1
        assert arrays2 is not arrays1
        assert (center2 - center1).length > 0.5
        assert (center2 - collider.matrix_world.translation).length < 1.0e-5
    finally:
        _delete_object(collider)
        _delete_object(armature)


def test_spring_vrm_runtime_cache_delete_and_clear_all_dispose():
    scene = bpy.context.scene
    root_tree = scene
    cache_key = "test_spring_vrm_physics_world_runtime_cache"
    OmniRuntimeState.clear_all()

    armature = _make_chain_armature("PW_SpringVRM_RuntimeDelete")
    try:
        ctx = OmniRuntimeState.begin_run(root_tree)
        hit, cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
        assert not hit and cache_state is None
        world, cache_value, _stats, _results = _runtime_cache_spring_step(scene, cache_state, armature, 1)
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) < 1.0e-6
        OmniRuntimeState.write_cache(ctx, cache_key, cache_value)
        OmniRuntimeState.finish_run(ctx)

        ctx = OmniRuntimeState.begin_run(root_tree)
        hit, cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
        assert hit and cache_state is world
        world2, cache_value2, _stats2, _results2 = _runtime_cache_spring_step(scene, cache_state, armature, 2)
        assert world2 is world
        assert _basis_delta_from_identity(armature.pose.bones["bone_1"]) > 1.0e-6
        OmniRuntimeState.write_cache(ctx, cache_key, cache_value2)
        OmniRuntimeState.finish_run(ctx)

        ctx = OmniRuntimeState.begin_run(root_tree)
        deleted = OmniRuntimeState.delete_cache(ctx, cache_key)
        assert deleted == 1
        OmniRuntimeState.finish_run(ctx)
        _assert_world_disposed(world, "Cache Delete")
        _assert_basis_identity(armature, "bone_1", "Cache Delete")
        _assert_basis_identity(armature, "bone_2", "Cache Delete")
    finally:
        _delete_object(armature)

    armature_clear = _make_chain_armature("PW_SpringVRM_RuntimeClearAll")
    try:
        ctx = OmniRuntimeState.begin_run(root_tree)
        world_clear, cache_value_clear, _stats_clear, _results_clear = _runtime_cache_spring_step(
            scene,
            None,
            armature_clear,
            1,
        )
        assert _basis_delta_from_identity(armature_clear.pose.bones["bone_1"]) < 1.0e-6
        OmniRuntimeState.write_cache(ctx, cache_key, cache_value_clear)
        OmniRuntimeState.finish_run(ctx)

        ctx = OmniRuntimeState.begin_run(root_tree)
        hit, cache_state = OmniRuntimeState.read_cache(ctx, cache_key)
        assert hit and cache_state is world_clear
        world_clear, cache_value_clear, _stats_clear, _results_clear = _runtime_cache_spring_step(
            scene,
            cache_state,
            armature_clear,
            2,
        )
        assert _basis_delta_from_identity(armature_clear.pose.bones["bone_1"]) > 1.0e-6
        OmniRuntimeState.write_cache(ctx, cache_key, cache_value_clear)
        OmniRuntimeState.finish_run(ctx)

        OmniRuntimeState.clear_all()
        _assert_world_disposed(world_clear, "clear_all")
        _assert_basis_identity(armature_clear, "bone_1", "clear_all")
        _assert_basis_identity(armature_clear, "bone_2", "clear_all")
    finally:
        _delete_object(armature_clear)


def test_spring_vrm_collider_snapshot():
    armature_free = _make_chain_armature("PW_SpringVRM_NoCollider")
    armature_hit = _make_chain_armature("PW_SpringVRM_WithCollider")
    collider = _make_sphere_collider("PW_SpringVRM_Collider", (0.35, 0.0, 1.93), 0.35, group=1)
    try:
        _enable_bone_hit_radius(armature_free, "bone_1", radius=0.15, mask=1)
        _enable_bone_hit_radius(armature_hit, "bone_1", radius=0.15, mask=1)

        _run_spring_after_reset(_OmniCache(), armature_free, 10, expected_collider_count=0)
        bpy.context.view_layer.update()
        free_tail = _tail_world(armature_free, "bone_1").copy()

        _run_spring_after_reset(
            _OmniCache(),
            armature_hit,
            20,
            extra_objects=[collider],
            include_passive_collision=True,
            expected_collider_count=1,
        )
        bpy.context.view_layer.update()
        hit_tail = _tail_world(armature_hit, "bone_1").copy()

        assert hit_tail.x > free_tail.x + 0.05, (
            f"碰撞体应把 bone_1 tail 从参考位置推开，free={tuple(free_tail)} hit={tuple(hit_tail)}"
        )
    finally:
        _delete_object(collider)
        _delete_object(armature_free)
        _delete_object(armature_hit)


def test_spring_vrm_collider_group_mask_filters_snapshot():
    armature_free = _make_chain_armature("PW_SpringVRM_GroupFree")
    armature_miss = _make_chain_armature("PW_SpringVRM_GroupMiss")
    collider = None
    try:
        _enable_bone_hit_radius(armature_free, "bone_1", radius=0.15, mask=1)
        _enable_bone_hit_radius(armature_miss, "bone_1", radius=0.15, mask=1)

        _run_spring_after_reset(_OmniCache(), armature_free, 21, expected_collider_count=0)
        bpy.context.view_layer.update()
        free_tail = _tail_world(armature_free, "bone_1").copy()

        collider = _make_sphere_collider(
            "PW_SpringVRM_GroupMismatchCollider",
            (free_tail.x - 0.05, free_tail.y, free_tail.z),
            0.35,
            group=2,
        )
        _run_spring_after_reset(
            _OmniCache(),
            armature_miss,
            22,
            extra_objects=[collider],
            include_passive_collision=True,
            expected_collider_count=1,
        )
        bpy.context.view_layer.update()
        miss_tail = _tail_world(armature_miss, "bone_1").copy()

        assert (miss_tail - free_tail).length < 1.0e-4, (
            f"group mismatch should keep bone_1 tail on the no-collider path, free={tuple(free_tail)} miss={tuple(miss_tail)}"
        )
    finally:
        if collider is not None:
            _delete_object(collider)
        _delete_object(armature_free)
        _delete_object(armature_miss)


def test_spring_vrm_capsule_collider_snapshot():
    armature_free = _make_chain_armature("PW_SpringVRM_NoCapsule")
    armature_hit = _make_chain_armature("PW_SpringVRM_WithCapsule")
    capsule = None
    try:
        _enable_bone_hit_radius(armature_free, "bone_1", radius=0.15, mask=1)
        _enable_bone_hit_radius(armature_hit, "bone_1", radius=0.15, mask=1)

        _run_spring_after_reset(_OmniCache(), armature_free, 25, expected_collider_count=0)
        bpy.context.view_layer.update()
        free_tail = _tail_world(armature_free, "bone_1").copy()

        capsule = _make_capsule_collider(
            "PW_SpringVRM_Capsule",
            (free_tail.x - 0.12, free_tail.y, free_tail.z),
            0.25,
            1.0,
            group=1,
        )
        _run_spring_after_reset(
            _OmniCache(),
            armature_hit,
            26,
            extra_objects=[capsule],
            include_passive_collision=True,
            expected_collider_count=1,
        )
        bpy.context.view_layer.update()
        hit_tail = _tail_world(armature_hit, "bone_1").copy()

        assert hit_tail.x > free_tail.x + 0.03, (
            f"capsule collider should push bone_1 tail away from the capsule axis, free={tuple(free_tail)} hit={tuple(hit_tail)}"
        )
    finally:
        if capsule is not None:
            _delete_object(capsule)
        _delete_object(armature_free)
        _delete_object(armature_hit)


def test_spring_vrm_plane_collider_snapshot():
    armature_free = _make_chain_armature("PW_SpringVRM_NoPlane")
    armature_hit = _make_chain_armature("PW_SpringVRM_WithPlane")
    plane = None
    try:
        _enable_bone_hit_radius(armature_free, "bone_1", radius=0.15, mask=1)
        _enable_bone_hit_radius(armature_hit, "bone_1", radius=0.15, mask=1)

        _run_spring_after_reset(_OmniCache(), armature_free, 30, expected_collider_count=0)
        bpy.context.view_layer.update()
        free_tail = _tail_world(armature_free, "bone_1").copy()

        plane = _make_plane_collider(
            "PW_SpringVRM_Plane",
            (free_tail.x - 0.05, free_tail.y, free_tail.z),
            normal_axis="+X",
            group=1,
        )
        _run_spring_after_reset(
            _OmniCache(),
            armature_hit,
            40,
            extra_objects=[plane],
            include_passive_collision=True,
            expected_collider_count=1,
        )
        bpy.context.view_layer.update()
        hit_tail = _tail_world(armature_hit, "bone_1").copy()

        assert hit_tail.x > free_tail.x + 0.03, (
            f"平面碰撞体应沿法线推开 bone_1 tail，free={tuple(free_tail)} hit={tuple(hit_tail)}"
        )
    finally:
        if plane is not None:
            _delete_object(plane)
        _delete_object(armature_free)
        _delete_object(armature_hit)


def test_spring_vrm_box_collider_snapshot():
    armature_free = _make_chain_armature("PW_SpringVRM_NoBox")
    armature_hit = _make_chain_armature("PW_SpringVRM_WithBox")
    box = None
    try:
        _enable_bone_hit_radius(armature_free, "bone_1", radius=0.15, mask=1)
        _enable_bone_hit_radius(armature_hit, "bone_1", radius=0.15, mask=1)

        _run_spring_after_reset(_OmniCache(), armature_free, 50, expected_collider_count=0)
        bpy.context.view_layer.update()
        free_tail = _tail_world(armature_free, "bone_1").copy()

        box = _make_box_collider(
            "PW_SpringVRM_Box",
            (free_tail.x - 0.25, free_tail.y, free_tail.z),
            (0.8, 2.0, 2.0),
            group=1,
        )
        _run_spring_after_reset(
            _OmniCache(),
            armature_hit,
            60,
            extra_objects=[box],
            include_passive_collision=True,
            expected_collider_count=1,
        )
        bpy.context.view_layer.update()
        hit_tail = _tail_world(armature_hit, "bone_1").copy()

        assert hit_tail.x > free_tail.x + 0.03, (
            f"盒体碰撞体应把 bone_1 tail 从盒体内投影出来，free={tuple(free_tail)} hit={tuple(hit_tail)}"
        )
    finally:
        if box is not None:
            _delete_object(box)
        _delete_object(armature_free)
        _delete_object(armature_hit)


def test_spring_vrm_bone_collision_resolver_matches_legacy():
    """resolver 逐字段对照旧 Bone.hotools_collision 直读。

    这一步是外部属性迁移的验收护栏（REHEARSAL 2026-07-09 要求）：
    resolver 必须与旧直读产出完全一致，才能后续把 native 消费端从直读切到
    resolver、并最终把属性注册挪到物理世界侧。
    """
    armature = _make_chain_armature("PW_SpringVRM_Resolver")
    try:
        # 1) 显式设过值的骨骼：resolver 必须逐字段等于直读
        props = armature.data.bones["bone_1"].hotools_collision
        props.pin = True
        props.collision_type = "CAPSULE"
        props.radius = 0.17
        props.length = 0.42
        props.offset = (0.01, -0.02, 0.03)
        props.primary_collision_group = 2
        props.collided_by_groups = 5

        prof = resolve_bone_collision_fields(armature, "bone_1")
        assert prof.pin is bool(props.pin), f"pin 不一致: {prof.pin} vs {props.pin}"
        assert prof.collision_type == str(props.collision_type), (
            f"collision_type 不一致: {prof.collision_type} vs {props.collision_type}"
        )
        assert abs(prof.radius - float(props.radius)) < 1e-6, (
            f"radius 不一致: {prof.radius} vs {props.radius}"
        )
        assert abs(prof.length - float(props.length)) < 1e-6, (
            f"length 不一致: {prof.length} vs {props.length}"
        )
        assert all(abs(a - b) < 1e-6 for a, b in zip(prof.offset, tuple(props.offset))), (
            f"offset 不一致: {prof.offset} vs {tuple(props.offset)}"
        )
        assert prof.primary_collision_group == int(props.primary_collision_group), (
            f"primary_collision_group 不一致: {prof.primary_collision_group} vs {props.primary_collision_group}"
        )
        assert prof.collided_by_groups == int(props.collided_by_groups), (
            f"collided_by_groups 不一致: {prof.collided_by_groups} vs {props.collided_by_groups}"
        )
        assert prof.source == "legacy_property", f"有旧属性时 source 应为 legacy_property，实际 {prof.source}"

        # 2) 未改动的骨骼：resolver 仍应等于直读的 PropertyGroup 默认值
        base_props = armature.data.bones["bone_2"].hotools_collision
        base_prof = resolve_bone_collision_fields(armature, "bone_2")
        assert base_prof.pin is bool(base_props.pin)
        assert base_prof.collision_type == str(base_props.collision_type)
        assert abs(base_prof.radius - float(base_props.radius)) < 1e-6
        assert base_prof.collided_by_groups == int(base_props.collided_by_groups)

        # 3) resolve_bone_pin 与直读 pin 一致
        assert resolve_bone_pin(armature, "bone_1") is bool(props.pin)
        assert resolve_bone_pin(armature, "bone_2") is bool(base_props.pin)

        # 4) 不存在的骨骼：走能力默认值，不抛错
        missing = resolve_bone_collision_fields(armature, "no_such_bone")
        assert missing.source == "default", f"缺失骨骼应返回 default，实际 {missing.source}"
        assert missing.collision_type == "NONE"
    finally:
        _delete_object(armature)


def test_spring_vrm_bone_collision_capability_audits_legacy_rna():
    issues = audit_bone_collision_legacy_property_group(PG_Hotools_BoneCollision)
    assert not issues, "Bone.hotools_collision drifted from BONE_COLLISION_CAPABILITY: " + "; ".join(issues)


def test_spring_vrm_bone_collision_override_preempts_legacy():
    armature = _make_chain_armature("PW_SpringVRM_Override")
    try:
        props = armature.data.bones["bone_1"].hotools_collision
        props.pin = False
        props.collision_type = "CAPSULE"
        props.radius = 0.11
        props.length = 0.44
        props.offset = (0.02, 0.03, 0.04)
        props.primary_collision_group = 3
        props.collided_by_groups = 5

        world = PhysicsWorldCache()
        override = make_bone_collision_override_properties(
            {"armature": armature, "bone": "bone_1"},
            pin=True,
            radius=0.27,
            collided_by_groups=12,
        )
        count, dirty_count, version = register_bone_collision_override_objects(world, [override])
        assert count == 1
        assert dirty_count == 1
        assert version >= 1

        prof = resolve_bone_collision_fields(armature, "bone_1", world=world)
        assert prof.source == "override"
        assert prof.pin is True
        assert prof.collision_type == "CAPSULE"
        assert abs(prof.radius - 0.27) < 1e-6
        assert abs(prof.length - float(props.length)) < 1e-6
        assert prof.primary_collision_group == int(props.primary_collision_group)
        assert prof.collided_by_groups == 12
        assert resolve_bone_pin(armature, "bone_1", world=world) is True

        native_radius, native_mask = native_bone_collision_profile(armature, "bone_1", world=world)
        assert abs(native_radius - 0.27) < 1e-5, native_radius
        assert native_mask == 12

        disabled = dict(override)
        disabled["enabled"] = False
        count, dirty_count, version = register_bone_collision_override_objects(world, [disabled], enabled=False)
        assert count == 1
        assert dirty_count == 1

        fallback = resolve_bone_collision_fields(armature, "bone_1", world=world)
        assert fallback.source == "legacy_property"
        assert fallback.pin is False
        assert abs(fallback.radius - float(props.radius)) < 1e-6
        assert fallback.collided_by_groups == int(props.collided_by_groups)
    finally:
        _delete_object(armature)


def test_spring_vrm_bone_collision_override_node_uses_capability_type_index():
    armature = _make_chain_armature("PW_SpringVRM_OverrideNodeTypeIndex")
    try:
        payloads = physicsBoneCollisionOverrideProperties(
            [_bone_value(armature, "bone_1"), _bone_value(armature, "bone_2")],
            override_collision_type=True,
            collision_type=2,
            override_radius=True,
            radius=0.23,
        )
        assert len(payloads) == 2, payloads
        assert all(item.get("fields", {}).get("collision_type") == "CAPSULE" for item in payloads), payloads
        assert all(abs(float(item.get("fields", {}).get("radius", 0.0)) - 0.23) < 1e-6 for item in payloads), payloads
    finally:
        _delete_object(armature)


def test_spring_vrm_bone_collider_override_reaches_native_arrays():
    armature = _make_chain_armature("PW_SpringVRM_BoneColliderTarget")
    collider_armature = _make_chain_armature("PW_SpringVRM_BoneColliderSource")
    try:
        collider_armature.location = (0.4, -0.2, 0.1)
        legacy = collider_armature.data.bones["bone_1"].hotools_collision
        legacy.collision_type = "NONE"

        scene = bpy.context.scene
        scene.frame_set(73)
        scope = make_scope(
            [armature, collider_armature],
            include_passive_collision=False,
            include_bone_collision=True,
            include_mesh_collision=False,
            include_rigid_body=False,
            include_rigid_constraint=False,
            include_hidden=True,
        )
        world, _frame, collider_count, _restart = physicsWorldBegin(
            _OmniCache(), scene, scope,
            enabled=True,
            reset=True,
            time_scale=1.0,
            substeps=1,
            debug_output=False,
        )
        assert collider_count == 0, "legacy NONE should not create a world snapshot collider"

        properties = physicsSpringVRMChainProperties([_bone_value(armature, "root")])
        world, object_count, _dirty_count, _version = physicsSpringVRMChainRegister(world, properties)
        assert object_count == 1

        override = make_bone_collision_override_properties(
            _bone_value(collider_armature, "bone_1"),
            collision_type="CAPSULE",
            radius=0.18,
            length=0.64,
            offset=(0.07, -0.03, 0.11),
            primary_collision_group=9,
        )
        register_bone_collision_override_objects(world, [override])
        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 2

        slot, _native_context, chain_context = _spring_chain_context(world)
        chain = slot.data["spec"].chains[0]
        arrays1 = chain_context._collision_arrays(world, armature, chain)
        types1, groups1, centers1, segment_a1, segment_b1, radii1 = arrays1
        assert len(types1) == 1, arrays1
        assert int(types1[0]) == int(COLLIDER_TYPE_CAPSULE)
        assert int(groups1[0]) == 9
        assert abs(float(radii1[0]) - 0.18) < 1.0e-5

        pose_matrix = collider_armature.matrix_world @ collider_armature.pose.bones["bone_1"].matrix
        offset = mathutils.Vector((0.07, -0.03, 0.11))
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        expected_center = pose_matrix @ offset
        expected_a = pose_matrix @ (offset - axis * 0.32)
        expected_b = pose_matrix @ (offset + axis * 0.32)
        assert (mathutils.Vector(centers1[0]) - expected_center).length < 1.0e-5
        assert (mathutils.Vector(segment_a1[0]) - expected_a).length < 1.0e-5
        assert (mathutils.Vector(segment_b1[0]) - expected_b).length < 1.0e-5

        changed = make_bone_collision_override_properties(
            _bone_value(collider_armature, "bone_1"),
            collision_type="CAPSULE",
            radius=0.18,
            length=0.30,
            offset=(-0.02, 0.06, 0.03),
            primary_collision_group=4,
        )
        register_bone_collision_override_objects(world, [changed])
        arrays2 = chain_context._collision_arrays(world, armature, chain)
        assert arrays2 is not arrays1, "override version change must invalidate collider array cache"
        assert int(arrays2[1][0]) == 4
        assert abs((mathutils.Vector(arrays2[4][0]) - mathutils.Vector(arrays2[3][0])).length - 0.30) < 1.0e-5

        disabled_shape = make_bone_collision_override_properties(
            _bone_value(collider_armature, "bone_1"),
            collision_type="NONE",
        )
        register_bone_collision_override_objects(world, [disabled_shape])
        arrays3 = chain_context._collision_arrays(world, armature, chain)
        assert len(arrays3[0]) == 0, "override NONE must remove the legacy-disabled bone collider"
    finally:
        _delete_object(collider_armature)
        _delete_object(armature)


def test_spring_vrm_cpp_debug_snapshot_uses_override_profile():
    armature = _make_chain_armature("PW_SpringVRM_DebugOverride")
    try:
        root_props = armature.data.bones["root"].hotools_collision
        root_props.collision_type = "SPHERE"
        root_props.radius = 0.19
        root_props.primary_collision_group = 6

        props = armature.data.bones["bone_1"].hotools_collision
        props.collision_type = "SPHERE"
        props.radius = 0.05
        props.length = 0.2
        props.offset = (0.0, 0.0, 0.0)
        props.primary_collision_group = 1
        props.collided_by_groups = 1

        cache = _OmniCache()
        frame = 77
        world, _frame, _collider_count, _restart = _world_for_frame(
            cache,
            armature,
            frame,
            reset=True,
        )
        properties = physicsSpringVRMChainProperties([_bone_value(armature, "root")])
        world, object_count, _dirty_count, _version = physicsSpringVRMChainRegister(world, properties)
        assert object_count == 1
        override = make_bone_collision_override_properties(
            _bone_value(armature, "bone_1"),
            collision_type="CAPSULE",
            radius=0.31,
            length=0.72,
            offset=(0.03, 0.04, 0.05),
            primary_collision_group=9,
            collided_by_groups=8,
        )
        count, _dirty_count, _version = register_bone_collision_override_objects(world, [override])
        assert count == 1

        world, write_count, _step_ms = physicsSpringVRMSolver(world, substeps=1)
        assert write_count == 2
        slot, _native_context, chain_context = _spring_chain_context(world)
        spec = slot.data.get("spec")
        chain_context.refresh_debug_draw_snapshot(world, armature, spec.chains[0])
        snapshot = chain_context.debug_draw_snapshot()
        assert isinstance(snapshot, dict), "SpringBone native context 应提供 debug draw snapshot"
        assert snapshot.get("source") == "cpp_context", snapshot
        root = next((item for item in snapshot.get("bones", []) if item.get("bone_name") == "root"), None)
        assert root is not None, snapshot
        root_shape = root.get("collider_shape")
        assert isinstance(root_shape, dict), root
        assert root_shape.get("type") == "SPHERE", root_shape
        assert abs(float(root_shape.get("radius", 0.0)) - 0.19) < 1e-5, root_shape
        assert int(root_shape.get("primary_group", 0)) == 6, root_shape

        bone_1 = next((item for item in snapshot.get("bones", []) if item.get("bone_name") == "bone_1"), None)
        assert bone_1 is not None, snapshot
        assert abs(float(bone_1.get("hit_radius", 0.0)) - 0.31) < 1e-5, bone_1
        assert int(bone_1.get("collided_by_groups", 0)) == 8, bone_1
        shape = bone_1.get("collider_shape")
        assert isinstance(shape, dict), bone_1
        assert shape.get("type") == "CAPSULE", shape
        assert abs(float(shape.get("radius", 0.0)) - 0.31) < 1e-5, shape
        assert int(shape.get("primary_group", 0)) == 9, shape
        assert int(shape.get("collided_by_groups", 0)) == 8, shape
        assert shape.get("segment_a") is not None and shape.get("segment_b") is not None, shape

        pose_matrix = armature.matrix_world @ armature.pose.bones["bone_1"].matrix
        offset = mathutils.Vector((0.03, 0.04, 0.05))
        half_length = 0.72 * 0.5
        axis = mathutils.Vector((0.0, 1.0, 0.0))
        expected_center = pose_matrix @ offset
        expected_a = pose_matrix @ (offset - axis * half_length)
        expected_b = pose_matrix @ (offset + axis * half_length)
        assert (mathutils.Vector(shape.get("center")) - expected_center).length < 1e-5, shape
        assert (mathutils.Vector(shape.get("segment_a")) - expected_a).length < 1e-5, shape
        assert (mathutils.Vector(shape.get("segment_b")) - expected_b).length < 1e-5, shape

        batches = []
        spring_vrm_debug_draw._append_debug_bone_collider_batch(
            batches,
            bone_1,
            color_by_group=True,
        )
        assert batches, "C++ debug snapshot bone collider shape should be drawable"
        assert batches[0][1] == spring_vrm_debug_draw._collider_color(9, True), batches[0]
        sphere_lines = []
        capsule_lines = batches[0][0]
        spring_vrm_debug_draw._append_collider_shape_lines(
            sphere_lines,
            {"type": "SPHERE", "center": shape.get("center"), "radius": 0.31},
        )
        assert len(capsule_lines) > len(sphere_lines), "bone_1 override CAPSULE should draw as capsule, not tail sphere"
    finally:
        _delete_object(armature)


def test_spring_vrm_debug_draw_collider_shapes_and_group_colors():
    draw = spring_vrm_debug_draw
    shape_cases = [
        {
            "type": "SPHERE",
            "center": mathutils.Vector((0.0, 0.0, 0.0)),
            "radius": 0.5,
            "primary_group": 1,
        },
        {
            "type": "CAPSULE",
            "segment_a": mathutils.Vector((0.0, 0.0, 0.0)),
            "segment_b": mathutils.Vector((0.0, 1.0, 0.0)),
            "radius": 0.25,
            "primary_group": 2,
        },
        {
            "type": "PLANE",
            "center": mathutils.Vector((0.0, 0.0, 0.0)),
            "normal": mathutils.Vector((0.0, 0.0, 1.0)),
            "plane_axis_x": mathutils.Vector((1.0, 0.0, 0.0)),
            "plane_axis_y": mathutils.Vector((0.0, 1.0, 0.0)),
            "primary_group": 3,
        },
        {
            "type": "BOX",
            "center": mathutils.Vector((0.0, 0.0, 0.0)),
            "box_axis_x": mathutils.Vector((0.5, 0.0, 0.0)),
            "box_axis_y": mathutils.Vector((0.0, 0.5, 0.0)),
            "box_axis_z": mathutils.Vector((0.0, 0.0, 0.5)),
            "primary_group": 4,
        },
    ]
    for case in shape_cases:
        lines = []
        assert draw._append_collider_shape_lines(lines, case), f"{case['type']} 应生成 debug 线段"
        assert lines, f"{case['type']} debug 线段不能为空"

    sphere_lines = []
    capsule_lines = []
    assert draw._append_collider_shape_lines(sphere_lines, shape_cases[0])
    assert draw._append_collider_shape_lines(capsule_lines, shape_cases[1])
    assert len(capsule_lines) > len(sphere_lines), "CAPSULE 应绘制半球弧线，而不只是两端圆和侧线"

    assert draw._collider_color(1, True) != draw._collider_color(2, True)
    assert draw._collider_color(99, True) == draw._collider_color(16, True)
    assert draw._collider_color(1, True) == (0.10, 0.63, 1.00, 0.86)
    assert draw._collider_color(16, True) == (0.78, 0.78, 0.78, 0.86)
    assert draw._collider_color(1, False) == (0.62, 0.66, 0.72, 0.58)

    armature = _make_chain_armature("PW_DebugDraw_BoneCollider")
    try:
        props = armature.data.bones["bone_1"].hotools_collision
        props.collision_type = "CAPSULE"
        props.radius = 0.1
        props.length = 0.8
        props.primary_collision_group = 5

        tail_1 = mathutils.Vector((0.4, 0.0, 1.6))
        tail_2 = mathutils.Vector((0.8, 0.0, 2.2))
        chain_lines = []
        draw._append_spec_lines(
            _types.SimpleNamespace(
                armature=armature,
                chains=(
                    _types.SimpleNamespace(root_bone="root", bones=("root", "bone_1", "bone_2")),
                ),
            ),
            {
                "chains": {
                    "root": {
                        "tails": {
                            "bone_1": {"current_tail": tail_1},
                            "bone_2": {"current_tail": tail_2},
                        },
                    },
                },
            },
            {},
            chain_lines,
            None,
            None,
            color_by_group=True,
            spring_bone_keys=set(),
        )

        def _rounded(value):
            return tuple(round(float(item), 6) for item in value)

        pairs = [
            (_rounded(start), _rounded(end))
            for start, end in zip(chain_lines[0::2], chain_lines[1::2])
        ]
        assert len(pairs) == 3, f"解算链条应只绘制连续骨链段，实际线段: {pairs}"
        assert pairs[1] == (_rounded((0.0, 0.0, 1.0)), _rounded(tail_1)), pairs
        assert pairs[2] == (_rounded(tail_1), _rounded(tail_2)), pairs
        assert (_rounded((0.0, 0.0, 2.0)), _rounded(tail_2)) not in pairs, (
            "解算链条不应绘制静态 bone_2 head 到动态 tail 的引导线"
        )

        batches = []
        draw._append_bone_collider_batch(
            batches,
            armature,
            "bone_1",
            armature.pose.bones["bone_1"],
            color_by_group=True,
        )
        assert batches and batches[0][0], "骨骼 CAPSULE 碰撞体应生成胶囊线段"
        assert batches[0][1] == draw._collider_color(5, True)

        snapshot_world = _types.SimpleNamespace(collider_snapshot={
            "colliders": [
                {
                    "type": "SPHERE",
                    "owner_type": "BONE",
                    "owner": armature,
                    "bone": "bone_1",
                    "center": mathutils.Vector((0.0, 0.0, 0.0)),
                    "radius": 0.1,
                    "primary_group": 5,
                }
            ]
        })
        batches = []
        draw._append_world_collider_batches(
            batches,
            snapshot_world,
            color_by_group=True,
            skip_bone_keys={(id(armature), "bone_1")},
        )
        assert not batches, "SpringBone 自身骨骼碰撞体不应从 world snapshot 重复绘制"

        chain_lines = []
        root_lines = []
        batches = []
        draw._append_context_debug_snapshot(
            {
                "source": "cpp_context",
                "root_bone": "root",
                "bones": [
                    {
                        "bone_name": "root",
                        "current_head": (0.0, 0.0, 0.0),
                        "current_tail": (0.0, 0.0, 1.0),
                        "hit_radius": 0.0,
                        "collided_by_groups": 0,
                    },
                    {
                        "bone_name": "bone_1",
                        "current_head": (0.0, 0.0, 1.0),
                        "current_tail": tuple(tail_1),
                        "hit_radius": 0.27,
                        "collided_by_groups": 4,
                    },
                    {
                        "bone_name": "bone_2",
                        "current_head": (0.0, 0.0, 2.0),
                        "current_tail": tuple(tail_2),
                        "hit_radius": 0.0,
                        "collided_by_groups": 0,
                    },
                ],
                "colliders": [shape_cases[0]],
            },
            chain_lines,
            root_lines,
            batches,
            color_by_group=True,
        )
        context_pairs = [
            (_rounded(start), _rounded(end))
            for start, end in zip(chain_lines[0::2], chain_lines[1::2])
        ]
        assert context_pairs[1] == (_rounded((0.0, 0.0, 1.0)), _rounded(tail_1)), context_pairs
        assert root_lines, "C++ context debug snapshot 应绘制 root 标记"
        assert batches and batches[0][1] == draw._collider_color(3, True), (
            "骨骼 hit radius 应按 C++ 消费的 collided_by_groups mask 着色"
        )
    finally:
        _delete_object(armature)


def test_spring_vrm_soak_reuses_native_resources():
    frame_count = max(2, int(os.environ.get("SPRING_VRM_SOAK_FRAMES", "10000") or 10000))
    armature = _make_chain_armature("PW_SpringVRM_Soak")
    try:
        cache, world, _stats, _results = _run_spring_frame(
            _OmniCache(), armature, 1, reset=True, return_details=True,
        )
        slot, contexts, context = _spring_chain_context(world)
        identities = (
            id(slot), id(contexts), id(context), id(context._handle),
            id(context._static), id(context._dynamic), id(context._result),
        )
        for frame in range(2, frame_count + 1):
            cache, world, _stats, _results = _run_spring_frame(
                cache, armature, frame, reset=False, return_details=True,
            )

        final_slot, final_contexts, final_context = _spring_chain_context(world)
        final_identities = (
            id(final_slot), id(final_contexts), id(final_context), id(final_context._handle),
            id(final_context._static), id(final_context._dynamic), id(final_context._result),
        )
        assert final_identities == identities
        assert len(world.solver_slots) == 1
        assert len(final_contexts) == 1
        assert len(world.implicit_objects) == 1
        assert int(final_context.debug_dict().get("step_count", 0) or 0) == frame_count - 1
    finally:
        _delete_object(armature)


_TESTS = (
    ("native 模块可用", test_native_available),
    ("隐式对象注册 + native step + PoseBone 写回闭环", test_spring_vrm_vertical_slice),
    ("SpringBone rest pose has no synthetic side force", test_spring_vrm_stiffness_rest_pose_has_no_side_force),
    ("SpringBone frame jump resets without stepping", test_spring_vrm_frame_jump_resets_without_step),
    ("SpringBone same-frame cached result semantics", test_spring_vrm_same_frame_republishes_cached_results),
    ("SpringBone zero/negative time scale pauses", test_spring_vrm_zero_or_negative_time_scale_pauses),
    ("SpringBone runtime parameter changes reuse slot", test_spring_vrm_runtime_parameter_change_reuses_slot),
    ("SpringBone public parameter matrix reaches native context", test_spring_vrm_public_parameters_reach_native_context),
    ("SpringBone public parameter bounds clamp in solver spec", test_spring_vrm_spec_clamps_public_parameter_bounds),
    ("SpringBone multiple armatures create isolated slots", test_spring_vrm_multiple_armatures_create_isolated_slots),
    ("SpringBone multiple chains share one armature slot", test_spring_vrm_multiple_chains_share_one_armature_slot),
    ("SpringBone rejects duplicate roots and overlapping bones", test_spring_vrm_rejects_duplicate_roots_and_overlapping_bones),
    ("SpringBone branch chain reaches native context", test_spring_vrm_branch_chain_reaches_native_context),
    ("SpringBone topology change disposes old slot", test_spring_vrm_topology_change_disposes_old_slot),
    ("SpringBone override pin reaches native static state", test_spring_vrm_override_pin_reaches_native_static_state),
    ("SpringBone non-root pin keeps pose", test_spring_vrm_non_root_pin_keeps_pose),
    ("SpringBone native_context reuses chain buffers", test_spring_vrm_native_context_reuses_chain_buffers),
    ("SpringBone nonuniform scale uses bone-axis world length", test_spring_vrm_nonuniform_scale_uses_axis_world_length),
    ("SpringBone mirrored scale and box remain finite", test_spring_vrm_mirrored_scale_and_box_are_finite),
    ("SpringBone debug capture is a next-frame state machine", test_spring_vrm_debug_capture_is_next_frame_state_machine),
    ("SpringBone collider arrays cache reuses snapshot", test_spring_vrm_collider_arrays_cache_reuses_snapshot),
    ("SpringBone moving collider refreshes native arrays", test_spring_vrm_moving_collider_refreshes_native_arrays),
    ("SpringBone runtime cache delete + clear_all dispose", test_spring_vrm_runtime_cache_delete_and_clear_all_dispose),
    ("world collider snapshot 接入 SpringBone native", test_spring_vrm_collider_snapshot),
    ("SpringBone collider group mask filters snapshot", test_spring_vrm_collider_group_mask_filters_snapshot),
    ("world capsule collider 接入 SpringBone native", test_spring_vrm_capsule_collider_snapshot),
    ("world plane collider 接入 SpringBone native", test_spring_vrm_plane_collider_snapshot),
    ("world box collider 接入 SpringBone native", test_spring_vrm_box_collider_snapshot),
    ("骨骼碰撞 resolver 对照旧 hotools_collision 直读", test_spring_vrm_bone_collision_resolver_matches_legacy),
    ("SpringBone bone_collision capability audits legacy RNA", test_spring_vrm_bone_collision_capability_audits_legacy_rna),
    ("SpringBone bone_collision.override preempts legacy profile", test_spring_vrm_bone_collision_override_preempts_legacy),
    ("SpringBone bone_collision.override node consumes capability type index", test_spring_vrm_bone_collision_override_node_uses_capability_type_index),
    ("SpringBone bone collider override reaches native arrays", test_spring_vrm_bone_collider_override_reaches_native_arrays),
    ("SpringBone C++ debug snapshot consumes bone_collision.override", test_spring_vrm_cpp_debug_snapshot_uses_override_profile),
    ("SpringBone debug draw 碰撞体形状与碰撞组颜色", test_spring_vrm_debug_draw_collider_shapes_and_group_colors),
)

if int(os.environ.get("SPRING_VRM_SOAK_FRAMES", "0") or 0) > 0:
    _TESTS += (("SpringBone soak reuses native resources", test_spring_vrm_soak_reuses_native_resources),)


def main() -> None:
    _results.clear()
    print("\n----------------------------------------------------------")
    print("  SpringBone VRM 新物理世界集成测试")
    print("----------------------------------------------------------")
    for name, fn in _TESTS:
        check(name, fn)

    passed = sum(1 for item in _results if item)
    total = len(_results)
    print("----------------------------------------------------------")
    print(f"  {passed}/{total} 通过  {'全部通过' if passed == total else '存在失败'}")
    print("----------------------------------------------------------")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
