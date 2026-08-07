# -*- coding: utf-8 -*-
"""Physics World 低频对象注册策略的 Blender 后台验收。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import numpy as np


PHYSICS_WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OMNINODE_ROOT = os.path.dirname(PHYSICS_WORLD_ROOT)
PACKAGE_ROOT = "hotools_registration_refresh_test"


def _ensure_package(name: str, path: str) -> None:
    module = types.ModuleType(name)
    module.__path__ = [path]
    module.__package__ = name
    sys.modules[name] = module


_ensure_package(PACKAGE_ROOT, OMNINODE_ROOT)
_ensure_package(f"{PACKAGE_ROOT}.PhysicsWorld", PHYSICS_WORLD_ROOT)

mapping_stub = types.ModuleType(f"{PACKAGE_ROOT}.OmniNodeSocketMapping")
mapping_stub._OmniCache = type("_OmniCache", (), {})
sys.modules[mapping_stub.__name__] = mapping_stub

refresh_samples: list[bool] = []
registry_stub = types.ModuleType(f"{PACKAGE_ROOT}.PhysicsWorld.registry")
registry_stub.run_scope_restart_handlers = lambda world, scope: None
registry_stub.run_world_restart_handlers = lambda world, scope, reason: None
registry_stub.run_world_replace_handlers = lambda previous, world, reason: None
registry_stub.run_world_dispose_handlers = lambda world, reason: None
registry_stub.collect_scope_physics_specs = lambda world, scope: refresh_samples.append(
    bool(world.frame_context.registration_refresh_required)
)
sys.modules[registry_stub.__name__] = registry_stub

world_module = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.world")
world_types = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.types")
runtime_state = importlib.import_module(f"{PACKAGE_ROOT}.OmniRuntimeState")
rigid_scope_sync = importlib.import_module(
    f"{PACKAGE_ROOT}.PhysicsWorld.rigid.scope_sync"
)
rigid_specs = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.rigid.specs")
rigid_names = importlib.import_module(f"{PACKAGE_ROOT}.PhysicsWorld.rigid.names")


def _scope(count: int):
    return world_types.PhysicsObjectScope(
        tuple(object() for _ in range(count)),
        include_passive_collision=False,
        include_bone_collision=False,
        include_rigid_body=False,
        include_rigid_constraint=False,
        include_hidden=True,
        include_field=False,
    )


def _begin(world, frame: int, scope, *, reset: bool = False):
    bpy.context.scene.frame_set(frame)
    return world_module.physicsWorldBegin(
        world,
        bpy.context.scene,
        scope,
        reset=reset,
    )[0]


def test_registration_refresh_boundaries() -> None:
    refresh_samples.clear()
    world = _begin(None, 1, _scope(1))
    world = _begin(world, 2, _scope(1))
    world = _begin(world, 3, _scope(2))
    world = _begin(world, 4, _scope(2), reset=True)
    world = _begin(world, 8, _scope(2))
    assert refresh_samples == [True, False, True, True, True]

    refresh_samples.clear()
    world = _begin(world, 9, _scope(2))
    world = _begin(world, 10, _scope(2))
    assert refresh_samples == [False, False]

    world.omni_cache_on_recompile("test")
    world = _begin(world, 11, _scope(2))
    assert refresh_samples[-1] is True


def test_compatible_recompile_notifies_preserved_cache_owner() -> None:
    class Owner:
        def __init__(self) -> None:
            self.notifications = []

        def omni_cache_on_recompile(self, reason: str) -> None:
            self.notifications.append(reason)

    tree = object()
    owner = Owner()
    contract = {"schema": 1, "preservable": True, "signature": ("same",)}
    compiled = types.SimpleNamespace(
        runtime_cache_contract=contract,
        runtime_namespace_children=(),
    )
    namespace = (runtime_state.runtime_tree_key(tree), ())
    runtime_state._COMMITTED_CACHE[namespace] = {"physics": owner}
    try:
        report = runtime_state.reconcile_root_tree(tree, compiled, compiled)
        assert report["preserved_namespaces"] == 1
        assert owner.notifications == ["recompile_compatible"]
    finally:
        runtime_state._COMMITTED_CACHE.clear()


def test_continuous_frame_only_syncs_kinematic_pose() -> None:
    obj = bpy.data.objects.new("RegistrationRefreshKinematic", None)
    try:
        world = world_types.PhysicsWorldCache()
        world.frame_context.registration_refresh_required = False
        spec = rigid_specs.RigidBodySpec(
            obj=obj,
            obj_ptr=int(obj.as_pointer()),
            data_ptr=0,
            body_type="KINEMATIC",
        )
        slot = world.ensure_solver_slot(spec.slot_id, rigid_names.RIGID_BODY_SLOT_KIND)
        slot.data["spec"] = spec
        slot.data["_kinematic_pose_signature"] = (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0),
        )

        matrix = np.identity(4, dtype=np.float32)
        matrix[0, 3] = 3.0
        scope = world_types.PhysicsObjectScope(
            (obj,),
            include_passive_collision=False,
            include_bone_collision=False,
            include_rigid_body=True,
            include_rigid_constraint=False,
            include_hidden=True,
            include_field=False,
            collection_batches=({"matrix_world_f32": matrix.reshape(-1)},),
            collection_locations={int(obj.as_pointer()): (0, 0)},
        )
        rigid_scope_sync.collect_rigid_specs_from_scope(world, scope)
        assert spec.world_position == (3.0, 0.0, 0.0)
        assert slot.data["_jolt_kinematic_pose_dirty"] is True
    finally:
        bpy.data.objects.remove(obj)


TESTS = (
    test_registration_refresh_boundaries,
    test_compatible_recompile_notifies_preserved_cache_owner,
    test_continuous_frame_only_syncs_kinematic_pose,
)


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"[通过] {test.__name__}")
    print(f"Physics World 低频注册策略：{len(TESTS)}/{len(TESTS)} 项测试通过")
