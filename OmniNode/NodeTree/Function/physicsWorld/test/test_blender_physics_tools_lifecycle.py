# -*- coding: utf-8 -*-
"""真实 PhysicsTools 根入口与 Physics World 属性生命周期测试。

用法：
    blender.exe --factory-startup --background --python test_blender_physics_tools_lifecycle.py
"""

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


physics_tools = importlib.import_module("HoTools.PhysicsTools")
blender_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender_registry"
)


def main() -> None:
    physics_tools.register()
    try:
        assert blender_registry.registered_blender_property_domains() == ("collision", "rigid")
        assert hasattr(bpy.types.Bone, "hotools_collision")
        assert hasattr(bpy.types.Object, "hotools_object_collision")
        assert hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert hasattr(bpy.types.Object, "hotools_rigid_body")
        assert hasattr(bpy.types.Object, "hotools_rigid_constraint")
        physics_tools.unregister()
        assert blender_registry.registered_blender_property_domains() == ()
        assert not hasattr(bpy.types.Bone, "hotools_collision")
        assert not hasattr(bpy.types.Object, "hotools_object_collision")
        assert not hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert not hasattr(bpy.types.Object, "hotools_rigid_body")
        assert not hasattr(bpy.types.Object, "hotools_rigid_constraint")
    finally:
        if blender_registry.registered_blender_property_domains():
            blender_registry.unregister_all_blender_property_domains()
    print("PhysicsTools register/unregister lifecycle: PASS")


if __name__ == "__main__":
    main()
