# -*- coding: utf-8 -*-
"""Blender 5.2 registration and operator smoke test for rigid fracture UI."""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


HOTOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), *('..',) * 4))
PW_ROOT = os.path.join(HOTOOLS, "OmniNode", "PhysicsWorld")
for path in (os.path.dirname(HOTOOLS), HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", os.path.join(HOTOOLS, "OmniNode", "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


registry = importlib.import_module("HoTools.OmniNode.PhysicsWorld.registry")
ui = importlib.import_module("HoTools.OmniNode.PhysicsWorld.ui")
panels = importlib.import_module("HoTools.OmniNode.PhysicsWorld.ui.panels")
fracture_gn = importlib.import_module("HoTools.OmniNode.PhysicsWorld.rigid_fracture.geometry_nodes")


def main():
    registry.register_physics_world_blender_properties()
    ui.register()
    try:
        mesh = bpy.data.meshes.new("FractureUISourceMesh")
        mesh.from_pydata(
            [
                (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
            ],
            [],
            [
                (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
            ],
        )
        mesh.update(calc_edges=True)
        source = bpy.data.objects.new("FractureUISource", mesh)
        bpy.context.scene.collection.objects.link(source)
        bpy.context.view_layer.objects.active = source
        source.select_set(True)
        source.hotools_rigid_fracture.enabled = True

        assert panels.PT_Hotools_Physics_RigidFracture.poll(bpy.context)
        assert bpy.ops.ho.rigid_fracture_add_preview.poll()
        assert bpy.ops.ho.rigid_fracture_add_preview() == {"FINISHED"}
        assert bpy.ops.ho.rigid_fracture_create_collection() == {"FINISHED"}
        props = source.hotools_rigid_fracture
        assert props.modifier_name in source.modifiers
        assert props.product_collection is not None
        modifier = source.modifiers[props.modifier_name]
        assert fracture_gn.is_managed_fracture_group(modifier.node_group)
        assert fracture_gn.fracture_method_from_group(modifier.node_group) == props.fracture_method
        assert props.piece_id_attribute == fracture_gn.FRACTURE_PIECE_ID_ATTRIBUTE
        assert bpy.ops.ho.rigid_fracture_delete_collection() == {"FINISHED"}
        assert props.product_collection is None
        print("[PASS] rigid fracture UI registered; preview/create/delete operators ready")
    finally:
        ui.unregister()
        registry.unregister_physics_world_blender_properties()


if __name__ == "__main__":
    main()
