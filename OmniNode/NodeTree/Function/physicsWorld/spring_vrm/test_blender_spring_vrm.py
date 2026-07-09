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

    _sm._OmniCache = _OmniCache
    _sm._OmniBone = _OmniBone
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
make_scope = _pw("scope").make_scope
physicsWorldBegin = _pw("world").physicsWorldBegin
physicsWorldCommit = _pw("world").physicsWorldCommit
apply_all_writebacks = _pw("writeback").apply_all_writebacks
physicsSpringVRMChainProperties = _pw("spring_vrm.nodes").physicsSpringVRMChainProperties
physicsSpringVRMChainRegister = _pw("spring_vrm.nodes").physicsSpringVRMChainRegister
physicsSpringVRMSolver = _pw("spring_vrm.nodes").physicsSpringVRMSolver
is_native_available = _pw("spring_vrm.native").is_available
iter_spring_vrm_pose_results = _pw("spring_vrm.results").iter_spring_vrm_pose_results
get_spring_vrm_stats_result = _pw("spring_vrm.results").get_spring_vrm_stats_result
resolve_bone_collision_fields = _pw("spring_vrm.bone_collision").resolve_bone_collision_fields
resolve_bone_pin = _pw("spring_vrm.bone_collision").resolve_bone_pin
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
        time_scale=1.0,
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
    return_details: bool = False,
):
    world, _frame, _collider_count, restart = _world_for_frame(
        cache,
        armature,
        frame,
        reset=reset,
        extra_objects=extra_objects,
        include_passive_collision=include_passive_collision,
    )
    properties = physicsSpringVRMChainProperties(
        [_bone_value(armature, "root")],
        enabled=True,
        stiffness_force=float(stiffness_force),
        drag_force=float(drag_force),
        gravity_dir=mathutils.Vector(gravity_dir or (1.0, 0.0, 0.0)),
        gravity_power=float(gravity_power),
    )
    world, object_count, dirty_count, _version = physicsSpringVRMChainRegister(world, properties, enabled=True)
    assert object_count == 1, f"应注册 1 条 VRM 骨链，实际 {object_count}"
    assert dirty_count >= 0

    world, write_count, _step_ms = physicsSpringVRMSolver(world, enabled=True, substeps=max(1, int(substeps)))
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
    assert is_native_available(), "hotools_native.solve_spring_bone_vrm_cpp 不可用"


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
        assert stats1.get("native_context", {}).get("chain_count") == 1
        assert stats1.get("native_context", {}).get("buffer_count") >= len(arrays1)
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
        debug2 = chain_context2.debug_dict()
        assert debug2.get("last_frame") == 91
        assert debug2.get("step_count") == 1
        assert {name: id(value) for name, value in getattr(chain_context2, "_dynamic").items()} == buffer_ids
        assert stats2.get("native_context", {}).get("step_count") == 1

        debug_snapshot = slot2.debug_snapshot()
        debug_context = debug_snapshot.get("native_context")
        assert debug_context and debug_context.get("available") is True
        assert debug_context.get("schema") == "spring_vrm_native_context_v2"
        assert debug_context.get("chain_count") == 1
        debug_chain = debug_context.get("chains", [])[0]
        assert debug_chain.get("root_bone") == "root"
        assert debug_chain.get("buffer_shapes", {}).get("current_tails") == [2, 3]
        assert debug_chain.get("buffer_shapes", {}).get("target_matrices") == [2, 16]

        world_debug = world2.omni_cache_debug_snapshot()
        world_slot_debug = world_debug.get("solver_slots", {}).get(slot2.slot_id, {})
        world_context = world_slot_debug.get("native_context", {})
        assert world_context.get("available") is True
        assert world_context.get("chains", [])[0].get("buffer_shapes", {}).get("current_tails") == [2, 3]
    finally:
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
    finally:
        _delete_object(armature)


print("\n----------------------------------------------------------")
print("  SpringBone VRM 新物理世界集成测试")
print("----------------------------------------------------------")

check("native 模块可用", test_native_available)
check("隐式对象注册 + native step + PoseBone 写回闭环", test_spring_vrm_vertical_slice)
check("SpringBone rest pose has no synthetic side force", test_spring_vrm_stiffness_rest_pose_has_no_side_force)
check("SpringBone frame jump resets without stepping", test_spring_vrm_frame_jump_resets_without_step)
check("SpringBone same-frame cached result semantics", test_spring_vrm_same_frame_republishes_cached_results)
check("SpringBone runtime parameter changes reuse slot", test_spring_vrm_runtime_parameter_change_reuses_slot)
check("SpringBone non-root pin keeps pose", test_spring_vrm_non_root_pin_keeps_pose)
check("SpringBone native_context reuses chain buffers", test_spring_vrm_native_context_reuses_chain_buffers)
check("SpringBone runtime cache delete + clear_all dispose", test_spring_vrm_runtime_cache_delete_and_clear_all_dispose)
check("world collider snapshot 接入 SpringBone native", test_spring_vrm_collider_snapshot)
check("SpringBone collider group mask filters snapshot", test_spring_vrm_collider_group_mask_filters_snapshot)
check("world capsule collider 接入 SpringBone native", test_spring_vrm_capsule_collider_snapshot)
check("world plane collider 接入 SpringBone native", test_spring_vrm_plane_collider_snapshot)
check("world box collider 接入 SpringBone native", test_spring_vrm_box_collider_snapshot)
check("骨骼碰撞 resolver 对照旧 hotools_collision 直读", test_spring_vrm_bone_collision_resolver_matches_legacy)
check("SpringBone debug draw 碰撞体形状与碰撞组颜色", test_spring_vrm_debug_draw_collider_shapes_and_group_colors)

passed = sum(1 for item in _results if item)
total = len(_results)
print("----------------------------------------------------------")
print(f"  {passed}/{total} 通过  {'全部通过' if passed == total else '存在失败'}")
print("----------------------------------------------------------")

if passed != total:
    raise SystemExit(1)
