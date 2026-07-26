# -*- coding: utf-8 -*-
"""OmniNode 持久引用门禁的 Blender 后台集成测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


TEST_DIR = os.path.dirname(os.path.abspath(__file__))
OMNINODE = os.path.dirname(TEST_DIR)
HOTOOLS = os.path.dirname(OMNINODE)
PHYSICS_WORLD = os.path.join(OMNINODE, "PhysicsWorld")


def _install_package(name, path):
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [path]
    module.__package__ = name
    sys.modules[name] = module


_install_package("HoTools", HOTOOLS)
_install_package("HoTools.OmniNode", OMNINODE)
_install_package("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD)
_install_package(
    "HoTools.OmniNode.PhysicsWorld.spring_vrm",
    os.path.join(PHYSICS_WORLD, "spring_vrm"),
)

runtime_state = importlib.import_module("HoTools.OmniNode.OmniRuntimeState")
reference_guard = importlib.import_module("HoTools.OmniNode.OmniReferenceGuard")
world_types = importlib.import_module("HoTools.OmniNode.PhysicsWorld.types")
spring_native = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.spring_vrm.native"
)


class _Tree:
    def __init__(self, pointer):
        self.pointer = int(pointer)

    def as_pointer(self):
        return self.pointer


class _RefreshOwner:
    def __init__(self, *, fail=False):
        self.fail = bool(fail)
        self.reasons = []

    def omni_cache_refresh_references(self, reason):
        self.reasons.append(reason)
        if self.fail:
            raise RuntimeError("expected refresh failure")


def _write_values(tree, values):
    context = runtime_state.begin_run(tree)
    for key, value in values.items():
        runtime_state.write_cache(context, key, value)
    runtime_state.finish_run(context)


def _make_armature(name):
    data = bpy.data.armatures.new(f"{name}Data")
    armature = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(armature)
    return armature


def test_protocol_walk_is_unique_and_failure_isolated():
    runtime_state.clear_all()
    tree = _Tree(91001)
    good = _RefreshOwner()
    bad = _RefreshOwner(fail=True)
    _write_values(
        tree,
        {
            "first": {"owner": good},
            "duplicate": [good],
            "failure": bad,
        },
    )

    report = reference_guard.refresh_persistent_references("test_boundary")
    assert report.owner_count == 2
    assert report.refreshed_count == 1
    assert report.failed_count == 1
    assert good.reasons == ["test_boundary"]
    assert bad.reasons == ["test_boundary"]
    runtime_state.clear_all()


def test_object_resolver_requires_matching_identity():
    armature = _make_armature("ReferenceGuardResolver")
    mesh = bpy.data.meshes.new("ReferenceGuardWrongData")
    try:
        resolved = reference_guard.resolve_bpy_object_reference(
            armature.as_pointer(),
            armature.data.as_pointer(),
            object_type="ARMATURE",
        )
        assert resolved is armature
        assert reference_guard.resolve_bpy_object_reference(
            armature.as_pointer(),
            mesh.as_pointer(),
            object_type="ARMATURE",
        ) is None
        assert reference_guard.resolve_bpy_object_reference(
            armature.as_pointer(),
            armature.data.as_pointer(),
            object_type="MESH",
        ) is None
    finally:
        bpy.data.objects.remove(armature, do_unlink=True)
        bpy.data.meshes.remove(mesh)


def test_physics_world_refreshes_all_declared_armature_references():
    runtime_state.clear_all()
    armature = _make_armature("ReferenceGuardWorld")
    object_pointer = int(armature.as_pointer())
    data_pointer = int(armature.data.as_pointer())
    world = world_types.PhysicsWorldCache()
    slot = world.ensure_solver_slot("reference-guard", "test")
    chain = types.SimpleNamespace(
        armature=None,
        armature_ptr=object_pointer,
        armature_data_ptr=data_pointer,
    )
    spec = types.SimpleNamespace(
        armature=None,
        armature_ptr=object_pointer,
        armature_data_ptr=data_pointer,
        chains=(chain,),
    )
    slot.data["spec"] = spec
    payload = {
        "armature": None,
        "armature_ptr": object_pointer,
        "armature_data_ptr": data_pointer,
    }
    world.implicit_objects.append({"payload": payload})
    unrelated_entry = {"payload": {"setting": 1}}
    world.implicit_objects.append(unrelated_entry)

    tree = _Tree(91002)
    _write_values(tree, {"world": world, "world_alias": world})
    try:
        report = reference_guard.refresh_persistent_references("render_frame_start")
        assert report.owner_count == 1
        assert report.refreshed_count == 1
        assert report.failed_count == 0
        assert spec.armature is armature
        assert chain.armature is armature
        assert payload["armature"] is armature
        assert "armature" not in unrelated_entry
        assert "armature" not in unrelated_entry["payload"]
    finally:
        runtime_state.clear_all()
        bpy.data.objects.remove(armature, do_unlink=True)


def test_spring_native_fallback_uses_architecture_resolver():
    armature = _make_armature("ReferenceGuardSpringFallback")
    spec = types.SimpleNamespace(
        armature=None,
        armature_ptr=int(armature.as_pointer()),
        armature_data_ptr=int(armature.data.as_pointer()),
        chains=(),
    )
    try:
        assert spring_native._get_valid_armature(spec) is armature
        assert spec.armature is armature
    finally:
        bpy.data.objects.remove(armature, do_unlink=True)


TESTS = (
    test_protocol_walk_is_unique_and_failure_isolated,
    test_object_resolver_requires_matching_identity,
    test_physics_world_refreshes_all_declared_armature_references,
    test_spring_native_fallback_uses_architecture_resolver,
)


def main():
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"OmniNode reference guard: PASS ({len(TESTS)}/{len(TESTS)})")


if __name__ == "__main__":
    main()
