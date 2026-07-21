# -*- coding: utf-8 -*-
"""Blender E1 acceptance: explicit MeshCloth old/new static shadow compare."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module

mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


def _make_object():
    mesh = bpy.data.meshes.new("MC2DomainShadowMesh")
    mesh.from_pydata(
        (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ),
        (),
        ((0, 1, 2, 3),),
    )
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="MC2_UV")
    coords = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = coords[loop.vertex_index]
    obj = bpy.data.objects.new("MC2DomainShadowObject", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _remove_object(obj):
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def test_mc2_mesh_domain_shadow_compile():
    obj = _make_object()
    world = world_types.PhysicsWorldCache()
    reports = []
    try:
        task = mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [obj])
        returned, ready, status = mc2_solver.step_mc2(
            world,
            [task],
            shadow_compile=True,
            shadow_reports=reports,
        )
        assert returned is world
        assert ready is False
        assert status
        assert len(reports) == 1
        report = reports[0]
        assert report.compatible is True
        assert all(item.matched for item in report.checks)
        assert set(("capture", "fragment", "compile", "legacy_static")) <= set(
            report.timing_seconds
        )
        assert report.timing_seconds["total"] >= 0.0
    finally:
        for slot in tuple(world.solver_slots.values()):
            slot.dispose("E1 shadow test cleanup")
        _remove_object(obj)


if __name__ == "__main__":
    test_mc2_mesh_domain_shadow_compile()
    print("PASS test_mc2_mesh_domain_shadow_compile")
