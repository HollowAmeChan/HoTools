# -*- coding: utf-8 -*-
"""Physics World Blender 根入口、UI 与属性生命周期测试。

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


physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
delta_output = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.delta_output"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
blender_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender_registry"
)
physics_panels = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.ui.panels"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)


def main() -> None:
    managed_group = gn_offset.ensure_gn_offset_node_group()
    output_node = next(
        node for node in managed_group.nodes
        if node.bl_idname == "NodeGroupOutput"
    )
    for link in tuple(output_node.inputs["Geometry"].links):
        managed_group.links.remove(link)
    assert not output_node.inputs["Geometry"].is_linked

    physics_blender.register()
    try:
        assert physics_blender.is_registered()
        output_node = next(
            node for node in managed_group.nodes
            if node.bl_idname == "NodeGroupOutput"
        )
        assert output_node.inputs["Geometry"].is_linked
        assert blender_registry.registered_blender_property_domains() == (
            "collision", "mc2", "rigid", "physics_ui",
        )
        assert hasattr(bpy.types.Bone, "hotools_collision")
        assert hasattr(bpy.types.Object, "hotools_object_collision")
        assert hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert hasattr(bpy.types.Object, "hotools_rigid_body")
        assert hasattr(bpy.types.Object, "hotools_rigid_constraint")
        assert delta_output.PhysicsDeltaOutputSpec is type(base_pose.MC2_DELTA_SPEC)

        mesh = bpy.data.meshes.new("PW_MeshClothIOContractMesh")
        mesh.from_pydata(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (), ((0, 1, 2),))
        source = bpy.data.objects.new("PW_MeshClothIOContract", mesh)
        bpy.context.scene.collection.objects.link(source)
        mesh_props = source.hotools_mesh_collision
        assert mesh_props.enabled is False
        mesh_props.enabled = True
        pin_group = source.vertex_groups.new(name="Pinned")
        pin_group.add((0,), 1.0, "REPLACE")
        mesh_props.pin_enabled = True
        mesh_props.pin_vertex_group = pin_group.name
        assert mesh_props.pin_vertex_group == "Pinned"
        assert physics_panels.PT_Hotools_Physics_MeshCollision.poll(
            types.SimpleNamespace(object=source)
        ) is True
        base_pose.ensure_delta_output(source)
        assert source.data.attributes.get(base_pose.DELTA_ATTRIBUTE_NAME) is not None
        assert source.modifiers.get(base_pose.DELTA_MODIFIER_NAME) is not None
        proxy = base_pose.ensure_base_pose_proxy(source)
        assert source.hotools_mesh_collision.mc2_base_pose_proxy == proxy
        assert proxy.hotools_mesh_collision.enabled is False
        assert base_pose.mesh_light_key(source) == base_pose.mesh_light_key(proxy)
        assert bool(proxy.get(base_pose.CACHE_OBJECT_FLAG, False))

        named_attribute = next(
            node for node in managed_group.nodes
            if node.bl_idname == "GeometryNodeInputNamedAttribute"
        )
        named_attribute.inputs["Name"].default_value = "broken_during_reload"
        physics_blender.register()
        named_attribute = next(
            node for node in managed_group.nodes
            if node.bl_idname == "GeometryNodeInputNamedAttribute"
        )
        assert (
            named_attribute.inputs["Name"].default_value
            == "hotools_physics_offset"
        )

        physics_blender.unregister()
        assert not physics_blender.is_registered()
        assert blender_registry.registered_blender_property_domains() == ()
        assert not hasattr(bpy.types.Bone, "hotools_collision")
        assert not hasattr(bpy.types.Object, "hotools_object_collision")
        assert not hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert not hasattr(bpy.types.Object, "hotools_rigid_body")
        assert not hasattr(bpy.types.Object, "hotools_rigid_constraint")
        physics_blender.register()
        assert physics_blender.is_registered()
        physics_blender.unregister()
        assert not physics_blender.is_registered()
    finally:
        if blender_registry.registered_blender_property_domains():
            blender_registry.unregister_all_blender_property_domains()
    print("Physics World Blender/UI register/unregister lifecycle: PASS")


if __name__ == "__main__":
    main()
