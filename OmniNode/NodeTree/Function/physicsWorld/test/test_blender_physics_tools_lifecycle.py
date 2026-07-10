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
legacy_delta_output = importlib.import_module("HoTools.PhysicsTools.deltaOutput")
legacy_base_pose = importlib.import_module("HoTools.PhysicsTools.meshClothBasePose")
delta_output = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.delta_output"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.base_pose"
)
blender_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender_registry"
)


def main() -> None:
    physics_tools.register()
    try:
        assert blender_registry.registered_blender_property_domains() == ("collision", "rigid", "mesh_cloth")
        assert hasattr(bpy.types.Bone, "hotools_collision")
        assert hasattr(bpy.types.Object, "hotools_object_collision")
        assert hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert hasattr(bpy.types.Object, "hotools_rigid_body")
        assert hasattr(bpy.types.Object, "hotools_rigid_constraint")
        assert legacy_delta_output.PhysicsDeltaOutputSpec is delta_output.PhysicsDeltaOutputSpec
        assert legacy_base_pose.MC2_DELTA_SPEC is base_pose.MC2_DELTA_SPEC

        mesh = bpy.data.meshes.new("PW_MeshClothIOContractMesh")
        mesh.from_pydata(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (), ((0, 1, 2),))
        source = bpy.data.objects.new("PW_MeshClothIOContract", mesh)
        bpy.context.scene.collection.objects.link(source)
        base_pose.ensure_delta_output(source)
        assert source.data.attributes.get(base_pose.DELTA_ATTRIBUTE_NAME) is not None
        assert source.modifiers.get(base_pose.DELTA_MODIFIER_NAME) is not None
        proxy = base_pose.ensure_base_pose_proxy(source)
        assert source.hotools_mesh_collision.mc2_base_pose_proxy == proxy
        assert base_pose.mesh_light_key(source) == base_pose.mesh_light_key(proxy)
        assert bool(proxy.get(base_pose.CACHE_OBJECT_FLAG, False))

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
