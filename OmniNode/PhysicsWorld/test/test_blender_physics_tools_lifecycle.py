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
NODETREE = os.path.join(HOTOOLS, "OmniNode")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(NODETREE, "PhysicsWorld")

for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)

for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


physics_blender = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.blender"
)
delta_output = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.simple_cloth.delta_output"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.simple_cloth.base_pose"
)
blender_registry = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.blender_registry"
)
solver_registry = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.registry"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.types"
)
physics_panels = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.ui.panels"
)
mc2_source_observation = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.source_observation_blender"
)
def main() -> None:
    physics_blender.register()
    try:
        assert physics_blender.is_registered()
        registered_domains = blender_registry.registered_blender_property_domains()
        assert registered_domains[0] == "collision"
        assert registered_domains[-3:] == (
            "simple_cloth", "rigid", "physics_ui",
        )
        assert "mc2" not in registered_domains
        assert hasattr(bpy.types.Bone, "hotools_collision")
        assert hasattr(bpy.types.Object, "hotools_object_collision")
        assert hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert hasattr(bpy.types.Object, "hotools_rigid_body")
        assert hasattr(bpy.types.Object, "hotools_rigid_constraint")
        assert (
            mc2_source_observation._mc2_depsgraph_update_post
            in bpy.app.handlers.depsgraph_update_post
        )
        assert {
            entry["domain"]
            for entry in solver_registry.iter_world_dispose_handlers()
        } == {
            "field", "spring_vrm", "rigid", "mc2",
            "xpbd.simple_mesh_xpbd", "xpbd.bone_xpbd",
        }
        assert {
            entry["domain"]
            for entry in solver_registry.iter_world_restart_handlers()
        } == {
            "field", "spring_vrm", "rigid", "mc2",
            "xpbd.simple_mesh_xpbd", "xpbd.bone_xpbd",
        }
        lifecycle_events = []
        dispose_events = []
        restart_events = []
        dynamic_lifecycle = types.SimpleNamespace(
            register=lambda: lifecycle_events.append("register"),
            unregister=lambda: lifecycle_events.append("unregister"),
        )
        solver_registry.register_solver_module(
            "test_blender_lifecycle",
            {
                "blender_lifecycle": dynamic_lifecycle,
                "world_dispose_handlers": (
                    lambda world, reason: dispose_events.append(
                        (str(id(world)), str(reason))
                    ),
                ),
                "world_restart_handlers": (
                    lambda world, scope, reason: restart_events.append(
                        (str(id(world)), scope, str(reason))
                    ),
                ),
            },
        )
        try:
            assert lifecycle_events == ["register"]
            lifecycle_world = world_types.PhysicsWorldCache()
            solver_registry.run_world_restart_handlers(
                lifecycle_world, None, "frame_jump"
            )
            assert restart_events == [
                (str(id(lifecycle_world)), None, "frame_jump")
            ]
            assert lifecycle_world.runtime_cache("solver_registry_errors") is None
            lifecycle_world.backend_resources["mc2.bone.frame_state"] = {
                "generation": 1,
                "bones": {},
            }
            solver_registry.run_scope_restart_handlers(lifecycle_world, None)
            assert "mc2.bone.frame_state" not in lifecycle_world.backend_resources
            assert lifecycle_world.runtime_cache("solver_registry_errors") is None
            lifecycle_world.omni_cache_dispose("registry_lifecycle_test")
            assert dispose_events == [
                (str(id(lifecycle_world)), "registry_lifecycle_test")
            ]
        finally:
            solver_registry.unregister_solver_module("test_blender_lifecycle")
        assert lifecycle_events == ["register", "unregister"]
        assert delta_output.PhysicsDeltaOutputSpec is type(base_pose.MC2_DELTA_SPEC)

        mesh = bpy.data.meshes.new("PW_MeshClothIOContractMesh")
        mesh.from_pydata(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (), ((0, 1, 2),))
        source = bpy.data.objects.new("PW_MeshClothIOContract", mesh)
        bpy.context.scene.collection.objects.link(source)
        mesh_props = source.hotools_mesh_collision
        assert mesh_props.enabled is False
        assert physics_panels.PT_Hotools_Physics_MeshCollision.poll(
            types.SimpleNamespace(object=source)
        ) is False
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
        assert proxy.hotools_mesh_collision.mc2_base_pose_proxy is None
        assert base_pose.mesh_light_key(source) == base_pose.mesh_light_key(proxy)
        assert bool(proxy.get(base_pose.CACHE_OBJECT_FLAG, False))

        physics_blender.unregister()
        assert not physics_blender.is_registered()
        assert blender_registry.registered_blender_property_domains() == ()
        assert not hasattr(bpy.types.Bone, "hotools_collision")
        assert not hasattr(bpy.types.Object, "hotools_object_collision")
        assert not hasattr(bpy.types.Object, "hotools_mesh_collision")
        assert not hasattr(bpy.types.Object, "hotools_rigid_body")
        assert not hasattr(bpy.types.Object, "hotools_rigid_constraint")
        assert (
            mc2_source_observation._mc2_depsgraph_update_post
            not in bpy.app.handlers.depsgraph_update_post
        )
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
