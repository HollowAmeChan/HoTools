

# -*- coding: utf-8 -*-
"""Physics World domain property registry 与迁移契约测试。

用法：
    blender.exe --factory-startup --background --python test_blender_property_registry.py
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import types
from dataclasses import replace

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


physics_utils = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.ui.utils"
)
collision_property = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.collision.properties"
)
rigid_property = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid.properties"
)
rigid_schema = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid.schema"
)
rigid_capabilities = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.rigid.capabilities"
)
mesh_property = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.properties"
)
mesh_schema = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.schema"
)
mesh_capabilities = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.capabilities"
)
collision_groups = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.collision.groups"
)
blender_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender_registry"
)
solver_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.registry"
)
solver_declarations = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.declarations"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)
mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_runtime_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
mc2_presets = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.presets"
)
mc2_results = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.results"
)
mc2_setups = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups"
)
mc2_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
mc2_topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
function_node_core = importlib.import_module(
    "HoTools.OmniNode.NodeTree.FunctionNodeCore"
)


EXPECTED_PROPERTY_CONTRACTS = {
    "PG_Hotools_BoneCollision": {
        "sha256": "f371091c0921050a34a5aa3386614119da1420aa1208af03b252c09dcb6eae7c",
        "fields": (
            "pin", "collision_type", "radius", "length", "offset",
            "primary_collision_group", "collided_by_groups",
        ),
    },
    "PG_Hotools_ObjectCollision": {
        "sha256": "8b7d3ed4867fc83f6ee62dc30fd9e56ddf14c762fc4ec602fec38228dc2f06b4",
        "fields": (
            "enabled", "collision_type", "radius", "length", "offset",
            "box_size", "primary_collision_group",
        ),
    },
    "PG_Hotools_MeshCollision": {
        "sha256": "1e117dd41c351f8d5ef39a5d54dc254f4bfafef57e867b7ece348ebed0195304",
        "fields": (
            "mc2_base_pose_proxy", "radius_vertex_group",
            "pin_enabled", "pin_vertex_group",
            "primary_collision_group", "collided_by_groups",
        ),
    },
    "PG_Hotools_RigidBody": {
        "sha256": "24be8f418efe9930f183624ab2ea985f6a73da61915739d4bfa66aa1b2711fdb",
        "fields": (
            "enabled", "body_type", "mass", "friction", "restitution",
            "rigid_collision_group", "rigid_collides_with_groups", "shape_type",
            "shape_radius", "shape_half_height", "shape_half_extents",
            "shape_plane_half_extent", "shape_top_radius", "shape_bottom_radius",
            "shape_convex_radius", "shape_offset", "shape_rotation",
            "linear_velocity", "angular_velocity", "linear_damping",
            "angular_damping", "gravity_factor", "allow_sleeping", "motion_quality",
            "max_linear_velocity", "max_angular_velocity", "is_sensor",
            "collide_kinematic_vs_non_dynamic", "lock_linear_x", "lock_linear_y",
            "lock_linear_z", "lock_angular_x", "lock_angular_y", "lock_angular_z",
        ),
    },
    "PG_Hotools_RigidConstraint": {
        "sha256": "8f911c5efab9f1ac26dbe26171bd4a9c4979ad7ef82d9dbddd2ac44384e3948b",
        "fields": (
            "enabled", "constraint_type", "target_a", "target_b",
            "reference_constraint_a", "reference_constraint_b", "anchor_mode",
            "local_point_a", "local_rotation_a", "local_point_b", "local_rotation_b",
            "disable_collisions", "breakable", "breaking_threshold",
            "constraint_priority", "solver_velocity_steps", "solver_position_steps",
            "draw_constraint_size", "limit_enabled", "angular_limit_min",
            "angular_limit_max", "linear_limit_min", "linear_limit_max",
            "limit_spring_frequency", "limit_spring_damping", "max_friction_torque",
            "max_friction_force", "motor_state", "motor_frequency", "motor_damping",
            "motor_force_limit", "motor_torque_limit",
            "motor_target_angular_velocity", "motor_target_angle",
            "motor_target_velocity", "motor_target_position", "swing_motor_state",
            "twist_motor_state", "swing_twist_target_angular_velocity",
            "swing_twist_target_rotation", "six_dof_swing_type",
            "six_dof_translation_x_mode", "six_dof_translation_x_min",
            "six_dof_translation_x_max", "six_dof_translation_x_limit_spring_frequency",
            "six_dof_translation_x_limit_spring_damping",
            "six_dof_translation_x_friction", "six_dof_translation_x_motor_state",
            "six_dof_translation_y_mode", "six_dof_translation_y_min",
            "six_dof_translation_y_max", "six_dof_translation_y_limit_spring_frequency",
            "six_dof_translation_y_limit_spring_damping",
            "six_dof_translation_y_friction", "six_dof_translation_y_motor_state",
            "six_dof_translation_z_mode", "six_dof_translation_z_min",
            "six_dof_translation_z_max", "six_dof_translation_z_limit_spring_frequency",
            "six_dof_translation_z_limit_spring_damping",
            "six_dof_translation_z_friction", "six_dof_translation_z_motor_state",
            "six_dof_rotation_x_mode", "six_dof_rotation_x_min",
            "six_dof_rotation_x_max", "six_dof_rotation_x_friction",
            "six_dof_rotation_x_motor_state", "six_dof_rotation_y_mode",
            "six_dof_rotation_y_min", "six_dof_rotation_y_max",
            "six_dof_rotation_y_friction", "six_dof_rotation_y_motor_state",
            "six_dof_rotation_z_mode", "six_dof_rotation_z_min",
            "six_dof_rotation_z_max", "six_dof_rotation_z_friction",
            "six_dof_rotation_z_motor_state", "six_dof_target_velocity",
            "six_dof_target_angular_velocity", "six_dof_target_position",
            "six_dof_target_rotation", "cone_half_angle", "swing_type",
            "swing_normal_half_angle", "swing_plane_half_angle", "twist_min_angle",
            "twist_max_angle", "distance_min", "distance_max",
            "pulley_fixed_point_a", "pulley_fixed_point_b", "pulley_ratio",
            "pulley_min_length", "pulley_max_length", "gear_ratio",
            "rack_and_pinion_ratio",
        ),
    },
}


def _canonical(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, type):
        return {"type": str(getattr(value, "__name__", value.__qualname__))}
    if callable(value):
        return {"callable": str(getattr(value, "__name__", type(value).__name__))}
    try:
        return [_canonical(item) for item in value]
    except Exception:
        return {"repr": repr(value)}


def _property_contract(cls) -> dict:
    fields = []
    for name, deferred in (getattr(cls, "__annotations__", {}) or {}).items():
        fields.append({
            "name": str(name),
            "factory": getattr(getattr(deferred, "function", None), "__name__", ""),
            "keywords": _canonical(getattr(deferred, "keywords", {}) or {}),
        })
    payload = {"class": cls.__name__, "fields": fields}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "fields": tuple(item["name"] for item in fields),
    }


def test_persistent_property_contracts_are_frozen():
    classes = (
        collision_property.PG_Hotools_BoneCollision,
        collision_property.PG_Hotools_ObjectCollision,
        mesh_property.PG_Hotools_MeshCollision,
        rigid_property.PG_Hotools_RigidBody,
        rigid_property.PG_Hotools_RigidConstraint,
    )
    actual = {cls.__name__: _property_contract(cls) for cls in classes}
    assert actual == EXPECTED_PROPERTY_CONTRACTS, json.dumps(actual, ensure_ascii=False, indent=2)


def test_components_own_shared_and_solver_adapter_capabilities():
    capabilities = solver_registry.all_component_capabilities()
    assert tuple(capabilities) == ("bone_collision", "object_collision", "mesh_collision")
    assert capabilities["bone_collision"]["explicit_storage"] == "Bone.hotools_collision"
    assert capabilities["object_collision"]["explicit_storage"] == "Object.hotools_object_collision"
    assert capabilities["mesh_collision"]["explicit_storage"] == "Object.hotools_mesh_collision"

    spring = solver_registry.resolve_solver_declaration("spring_vrm")
    assert spring is not None
    assert spring.get("capabilities") == {}
    assert spring.get("consumes_capabilities") == ["bone_collision"]
    assert rigid_property.PG_Hotools_RigidBody.__module__.endswith("physicsWorld.rigid.properties")
    assert rigid_property.PG_Hotools_RigidConstraint.__module__.endswith("physicsWorld.rigid.properties")
    assert physics_utils._COLLISION_GROUP_COUNT == collision_groups.COLLISION_GROUP_COUNT
    assert physics_utils._ALL_COLLISION_GROUPS_MASK == collision_groups.ALL_COLLISION_GROUPS_MASK
    assert physics_utils._COLLISION_GROUP_COLORS is collision_groups.COLLISION_GROUP_COLORS


def test_rigid_rna_and_capabilities_share_one_schema():
    pairs = (
        (
            "Object.hotools_rigid_body",
            rigid_schema.RIGID_BODY_RNA_FIELDS,
            rigid_property.PG_Hotools_RigidBody,
            rigid_capabilities.RIGID_BODY_CAPABILITY,
        ),
        (
            "Object.hotools_rigid_constraint",
            rigid_schema.RIGID_CONSTRAINT_RNA_FIELDS,
            rigid_property.PG_Hotools_RigidConstraint,
            rigid_capabilities.RIGID_CONSTRAINT_CAPABILITY,
        ),
    )
    assert tuple(len(schema) for _storage, schema, _cls, _capability in pairs) == (34, 96)
    for storage, schema, cls, capability in pairs:
        schema_names = tuple(str(field["name"]) for field in schema)
        assert tuple(cls.__annotations__) == schema_names
        capability_fields = tuple(capability["fields"])
        assert tuple(str(field["name"]) for field in capability_fields) == schema_names
        for declaration, field in zip(schema, capability_fields):
            assert field["rna"] == declaration["kwargs"]
            assert field["default"] == declaration["kwargs"].get("default")
            assert field["explicit_property"] == f"{storage}.{declaration['name']}"


def test_mesh_cloth_rna_and_capability_share_one_schema():
    schema = mesh_schema.MESH_COLLISION_RNA_FIELDS
    capability_fields = tuple(mesh_capabilities.MESH_COLLISION_CAPABILITY["fields"])
    names = tuple(str(field["name"]) for field in schema)
    assert len(schema) == 6
    assert tuple(mesh_property.PG_Hotools_MeshCollision.__annotations__) == names
    assert tuple(str(field["name"]) for field in capability_fields) == names
    for declaration, field in zip(schema, capability_fields):
        assert field["rna"] == declaration["kwargs"]
        assert field["default"] == declaration["kwargs"].get("default")
        assert field["explicit_property"] == f"Object.hotools_mesh_collision.{declaration['name']}"


def test_solver_node_modules_are_grouped_by_manifest_menu_name():
    groups = solver_registry.iter_solver_node_groups()
    assert tuple(group["solver_id"] for group in groups) == (
        "spring_vrm",
        "rigid_jolt",
        "mc2",
    )
    assert tuple(group["menu_name"] for group in groups) == (
        "VRM SpringBone",
        "Jolt刚体",
        "MC2",
    )
    assert all(group["modules"] for group in groups)
    assert all(
        module["solver_id"] == group["solver_id"]
        and module["menu_name"] == group["menu_name"]
        for group in groups
        for module in group["modules"]
    )
    assert tuple(
        (module["domain"], module["module_ref"])
        for module in solver_registry.iter_solver_node_modules()
    ) == tuple(
        (module["domain"], module["module_ref"])
        for group in groups
        for module in group["modules"]
    )


def test_solver_node_add_menu_uses_manifest_submenus():
    node_register = importlib.import_module(
        "HoTools.OmniNode.NodeTree.OmniNodeRegister"
    )
    expected = (
        ("spring_vrm", "VRM SpringBone", "NODE_MT_OMNINODE_SOLVER_SPRING_VRM"),
        ("rigid_jolt", "Jolt刚体", "NODE_MT_OMNINODE_SOLVER_RIGID_JOLT"),
        ("mc2", "MC2", "NODE_MT_OMNINODE_SOLVER_MC2"),
    )
    assert tuple(
        (group["solver_id"], group["menu_name"], group["menu_id"])
        for group in node_register.physics_world_solver_groups
    ) == expected
    assert tuple(
        (menu_class.bl_idname, menu_class.bl_label)
        for menu_class in node_register.physics_world_solver_menu_classes
    ) == tuple((menu_id, menu_name) for _solver, menu_name, menu_id in expected)

    solver_category = next(
        category
        for category in node_register.node_categories
        if category.identifier == "PHYSICS_SOLVER"
    )
    menu_calls = []

    class Layout:
        def menu(self, menu_id):
            menu_calls.append(menu_id)

    for item in solver_category.items(None):
        item.draw(item, Layout(), None)
    assert tuple(menu_calls) == tuple(menu_id for _solver, _name, menu_id in expected)


def test_mc2_is_one_solver_with_three_setup_types_and_public_step():
    assert solver_registry.builtin_solver_domains().count("mc2") == 1
    assert "mesh_cloth" not in solver_registry.builtin_solver_domains()
    assert solver_registry.builtin_component_domains() == ("collision", "mc2")
    descriptor = solver_registry.all_solver_module_descriptors()["mc2"]
    assert descriptor["solver_id"] == "mc2"
    assert descriptor["menu_name"] == "MC2"
    assert descriptor["nodes"] == (".nodes",)
    assert tuple(
        node.__meta["bl_label"]
        for node in (
            mc2_nodes.physicsMC2MeshClothProfile,
            mc2_nodes.physicsMC2BoneClothProfile,
            mc2_nodes.physicsMC2BoneSpringProfile,
            mc2_nodes.physicsMC2MeshClothTask,
            mc2_nodes.physicsMC2BoneClothTask,
            mc2_nodes.physicsMC2BoneSpringTask,
            mc2_nodes.physicsMC2Step,
        )
    ) == (
        "MC2 MeshCloth粒子配置",
        "MC2 BoneCloth粒子配置",
        "MC2 BoneSpring粒子配置",
        "MC2 MeshCloth任务",
        "MC2 BoneCloth任务",
        "MC2 BoneSpring任务",
        "MC2模拟步",
    )
    generated_node_classes = function_node_core.loadRegisterFuncNodes(mc2_nodes)
    assert tuple(node.bl_label for node in generated_node_classes) == (
        "MC2 BoneCloth粒子配置",
        "MC2 BoneCloth任务",
        "MC2 BoneSpring粒子配置",
        "MC2 BoneSpring任务",
        "MC2可视化调试",
        "MC2 MeshCloth粒子配置",
        "MC2 MeshCloth任务",
        "MC2模拟步",
    )
    assert not hasattr(mc2_nodes, "physicsMC2SolverSettings")
    assert tuple(inspect.signature(mc2_nodes.physicsMC2Step).parameters) == (
        "world",
        "mc2_tasks",
        "time_scale",
        "simulation_frequency",
        "max_simulation_count_per_frame",
        "enabled",
    )
    assert tuple(mc2_nodes.physicsMC2Step.__meta["_INPUT_NAME"]) == (
        "物理世界",
        "MC2任务",
        "时间缩放",
        "模拟频率",
        "每帧最大模拟次数",
        "启用",
    )

    declaration = solver_registry.resolve_solver_declaration("mc2")
    assert declaration is not None
    assert solver_declarations.validate_solver_declaration(declaration) == []
    assert declaration["implementation_status"] == "mesh_and_bone_collider_native_public_result"
    assert tuple(declaration["setup_types"]) == (
        mc2_names.MC2_SETUP_MESH_CLOTH,
        mc2_names.MC2_SETUP_BONE_CLOTH,
        mc2_names.MC2_SETUP_BONE_SPRING,
    )
    assert declaration["solver_id"] == mc2_names.MC2_SOLVER_ID == "mc2"
    assert "one_solver_three_setup_adapters" in declaration["native_strategy"]
    assert declaration["native_strategy"].endswith("single_native_context")
    assert declaration["update_policy"]["framework"] == "sync_topology_auto_mesh_or_bone_frame_native_context_and_public_result"
    assert declaration["update_policy"]["native_backend"] == "single_native_context_no_python_fallback"
    assert declaration["export"]["result_channels"] == [
        mc2_names.MC2_STATS_CHANNEL,
    ]
    assert declaration["export"]["shared_result_channels"] == [
        world_names.GN_ATTRIBUTE_CHANNEL,
        world_names.BONE_TRANSFORM_CHANNEL,
    ]
    assert declaration["export"]["planned_result_channels"] == []
    assert declaration["export"]["planned_shared_result_channels"] == []

    task_nodes = (
        mc2_nodes.physicsMC2MeshClothTask,
        mc2_nodes.physicsMC2BoneClothTask,
        mc2_nodes.physicsMC2BoneSpringTask,
    )
    for task_node in task_nodes:
        assert "backend" not in inspect.signature(task_node).parameters
        assert all("后端" not in name for name in task_node.__meta["_INPUT_NAME"])
    public_mc2_nodes = (
        mc2_nodes.physicsMC2MeshClothProfile,
        mc2_nodes.physicsMC2BoneClothProfile,
        mc2_nodes.physicsMC2BoneSpringProfile,
        *task_nodes,
        mc2_nodes.physicsMC2Step,
        mc2_nodes.physicsMC2DebugDraw,
    )
    for public_node in public_mc2_nodes:
        settings = function_node_core.CheckMetaInfo(public_node)[5]
        assert all(
            settings[identifier].get("description")
            for identifier in inspect.signature(public_node).parameters
        ), public_node.__name__
    source_socket_contracts = (
        (
            mc2_nodes.physicsMC2MeshClothTask,
            "mesh_objects",
            "代理网格",
            "NodeSocketObject",
        ),
        (
            mc2_nodes.physicsMC2BoneClothTask,
            "control_bones",
            "中控骨",
            "OmniNodeSocketBone",
        ),
        (
            mc2_nodes.physicsMC2BoneSpringTask,
            "root_bones",
            "根骨",
            "OmniNodeSocketBone",
        ),
    )
    for task_node, identifier, label, socket_type in source_socket_contracts:
        _node, inputs, _outputs, _defaults, multi, _settings = (
            function_node_core.CheckMetaInfo(task_node)
        )
        assert tuple(inspect.signature(task_node).parameters)[0] == identifier
        assert inputs[identifier] == {
            "type": socket_type,
            "name": label,
            "identifier": identifier,
            "use_multi_input": True,
        }
        assert multi[identifier] is True
    profile_nodes = (
        mc2_nodes.physicsMC2MeshClothProfile,
        mc2_nodes.physicsMC2BoneClothProfile,
        mc2_nodes.physicsMC2BoneSpringProfile,
    )
    cloth_profile_nodes = profile_nodes[:2]
    assert all(
        tuple(inspect.signature(node).parameters) == mc2_nodes._CLOTH_PROFILE_FIELDS
        for node in cloth_profile_nodes
    )
    assert tuple(
        inspect.signature(mc2_nodes.physicsMC2BoneSpringProfile).parameters
    ) == mc2_nodes._SPRING_PROFILE_FIELDS
    for profile_node in cloth_profile_nodes:
        parameters = set(inspect.signature(profile_node).parameters)
        assert "self_collision_enabled" in parameters
        assert "self_collision_interaction" in parameters
        assert "self_collision_mode" not in parameters
        assert "self_collision_thickness" not in parameters
        assert "spring_enabled" not in parameters
        assert "spring_power" not in parameters
        assert "collision_limit_distance" not in parameters
        assert "wind_influence" not in parameters
        assert "moving_wind" not in parameters
    spring_parameters = set(
        inspect.signature(mc2_nodes.physicsMC2BoneSpringProfile).parameters
    )
    assert {"collision_limit_distance"} <= spring_parameters
    assert not {
        "gravity", "tether_compression", "distance_stiffness",
        "max_distance_enabled", "backstop_enabled", "collision_mode",
        "self_collision_enabled", "self_collision_interaction", "cloth_mass",
        "spring_enabled", "spring_power", "spring_limit_distance",
        "spring_normal_limit_ratio", "spring_noise", "wind_influence", "moving_wind",
    } & spring_parameters
    assert not hasattr(mc2_nodes, "physicsMC2ParticleProfile")

    presets = tuple(mc2_presets.MC2_PARTICLE_PRESETS)
    assert tuple(preset["name"] for preset in presets) == (
        "MC2 Accessory",
        "MC2 Cape",
        "MC2 FrontHair",
        "MC2 LongHair",
        "MC2 ShortHair",
        "MC2 Skirt",
        "MC2 SoftSkirt",
        "MC2 MiddleSpring",
        "MC2 SoftSpring",
        "MC2 HardSpring",
        "MC2 Tail",
    )
    for profile_node in profile_nodes:
        profile_parameters = set(inspect.signature(profile_node).parameters)
        node_presets = tuple(profile_node.__meta["omni_presets"])
        assert tuple(item["name"] for item in node_presets) == tuple(
            item["name"] for item in presets
        )
        for preset in node_presets:
            values = preset["values"]
            assert set(values) <= profile_parameters
            assert "self_collision_thickness" not in values
            assert "self_collision_curve" not in values
            profile = profile_node(**values)
            assert isinstance(profile, mc2_parameters.MC2ParticleProfileSpec)
            assert profile.radius.value >= 0.001
            assert profile.self_collision_thickness.value == 0.005

    for profile_node in profile_nodes:
        _node, _inputs, _outputs, _defaults, _multi, settings = (
            function_node_core.CheckMetaInfo(profile_node)
        )
        for identifier in inspect.signature(profile_node).parameters:
            assert settings[identifier].get("description"), (
                profile_node.__name__, identifier
            )
        assert "0=+X" in settings["normal_axis"]["description"]
        assert "1=Reset" in settings["teleport_mode"]["description"]
    for profile_node in cloth_profile_nodes:
        settings = function_node_core.CheckMetaInfo(profile_node)[5]
        assert "1=Point" in settings["collision_mode"]["description"]

    for task_node in (
        mc2_nodes.physicsMC2BoneClothTask,
        mc2_nodes.physicsMC2BoneSpringTask,
    ):
        _node, inputs, _outputs, _defaults, _multi, settings = (
            function_node_core.CheckMetaInfo(task_node)
        )
        assert inputs["collided_by_groups"]["type"] == "OmniNodeSocketBitMask"
        assert settings["collided_by_groups"]["mask_length"] == 16
        assert settings["collided_by_groups"]["description"]

    class _FakeData:
        def __init__(self, pointer):
            self._pointer = pointer

        def as_pointer(self):
            return self._pointer

    class _FakeSource:
        def __init__(self, pointer, name, source_type):
            self._pointer = pointer
            self.name = name
            self.name_full = name
            self.type = source_type
            self.data = _FakeData(pointer + 1000)

        def as_pointer(self):
            return self._pointer

    mesh = _FakeSource(10, "Cloth", "MESH")
    second_mesh = _FakeSource(11, "SecondCloth", "MESH")
    armature = _FakeSource(20, "Rig", "ARMATURE")
    mesh_sources = [mesh]
    cloth_sources = [{"armature": armature, "root_bone": "ClothRoot"}]
    spring_sources = [{"armature": armature, "bones": ("SpringA", "SpringB")}]
    product_profile = mc2_nodes.physicsMC2MeshClothProfile(
        radius=0.04,
        self_collision_enabled=True,
        self_collision_interaction=True,
    )
    assert product_profile.self_collision_sync_mode == 2
    product_tasks = mc2_nodes.physicsMC2MeshClothTask(
        [mesh, second_mesh],
        product_profile,
    )
    assert len(product_tasks) == 2
    assert tuple(task.sources for task in product_tasks) == ((mesh,), (second_mesh,))
    product_task = product_tasks[0]
    assert product_task.setup_options.self_collision_radius_model == "derived_radius"
    product_runtime = mc2_runtime_parameters.make_mc2_runtime_parameters(
        product_profile,
        product_task.setup_options,
    ).debug_dict()
    assert all(
        abs(value - 0.01) < 1.0e-7
        for value in product_runtime["curve_values"]["self_collision_thickness"]
    )
    bone_cloth_profile = mc2_nodes.physicsMC2BoneClothProfile(
        gravity=3.0,
        self_collision_enabled=True,
    )
    bone_spring_profile = mc2_nodes.physicsMC2BoneSpringProfile(
        collision_limit_distance=0.08,
    )
    assert type(product_profile) is type(bone_cloth_profile) is type(bone_spring_profile)
    assert product_profile.spring_enabled is False
    assert bone_cloth_profile.spring_enabled is False
    assert bone_spring_profile.spring_enabled is False
    cloth_runtime = mc2_runtime_parameters.make_mc2_runtime_parameters(
        bone_cloth_profile,
        mc2_parameters.make_mc2_setup_options(mc2_names.MC2_SETUP_BONE_CLOTH),
    ).debug_dict()
    spring_runtime = mc2_runtime_parameters.make_mc2_runtime_parameters(
        bone_spring_profile,
        mc2_parameters.make_mc2_setup_options(mc2_names.MC2_SETUP_BONE_SPRING),
    ).debug_dict()
    assert cloth_runtime["float_values"]["gravity"] == 3.0
    assert cloth_runtime["float_values"]["spring_power"] == 0.0
    assert cloth_runtime["int_values"]["self_collision_mode"] == 2
    assert spring_runtime["float_values"]["gravity"] == 0.0
    assert spring_runtime["float_values"]["spring_power"] == 0.0
    assert spring_runtime["int_values"]["self_collision_mode"] == 0

    tasks = tuple(
        mc2_specs.make_mc2_task_spec(setup_type, sources)
        for setup_type, sources in zip(
            declaration["setup_types"],
            (mesh_sources, cloth_sources, spring_sources),
        )
    )
    assert tuple(task.setup_type for task in tasks) == tuple(declaration["setup_types"])
    assert len({task.task_id for task in tasks}) == 3
    assert all(task.task_id.startswith(f"mc2:{task.setup_type}:") for task in tasks)
    assert all(len(task.source_signature) == 64 for task in tasks)
    assert all(len(task.topology_signature) == 64 for task in tasks)
    assert all(len(task.config_signature) == 64 for task in tasks)
    assert all(len(task.parameter_signature) == 64 for task in tasks)
    assert all(task.implementation_version == 2 for task in tasks)
    assert all(not hasattr(task, "backend") for task in tasks)
    rebuilt = tuple(
        mc2_specs.make_mc2_task_spec(setup_type, sources)
        for setup_type, sources in zip(
            declaration["setup_types"],
            (mesh_sources, cloth_sources, spring_sources),
        )
    )
    assert tuple(task.task_id for task in rebuilt) == tuple(task.task_id for task in tasks)
    mesh_b = _FakeSource(11, "ClothB", "MESH")
    ordered_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH, [mesh, mesh_b]
    )
    reversed_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH, [mesh_b, mesh]
    )
    assert ordered_task.task_id == reversed_task.task_id
    assert ordered_task.source_signature == reversed_task.source_signature
    assert ordered_task.topology_signature != reversed_task.topology_signature
    assert mc2_specs.build_mc2_task_specs([tasks[0], [tasks[1], tasks[2]], tasks[0]]) == tasks

    soft_profile = mc2_parameters.make_mc2_particle_profile(damping=0.2)
    soft_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH,
        [mesh],
        profile=soft_profile,
    )
    assert soft_task.task_id == tasks[0].task_id
    assert soft_task.topology_signature == tasks[0].topology_signature
    assert soft_task.parameter_signature != tasks[0].parameter_signature
    source_curve = {
        "kind": "float_curve",
        "mode": "curve",
        "value": 1.0,
        "points": [
            {"x": 0.0, "y": 1.0, "handle_right": [0.25, 1.0]},
            {"x": 1.0, "y": 0.5, "handle_left": [0.75, 0.5]},
        ],
    }
    curved_profile = mc2_parameters.make_mc2_particle_profile(
        damping=0.2, damping_curve=source_curve
    )
    frozen_curve_signature = curved_profile.damping.signature
    source_curve["points"][0]["handle_right"][1] = 0.25
    assert curved_profile.damping.signature == frozen_curve_signature
    changed_curve = mc2_parameters.make_mc2_particle_profile(
        damping=0.2, damping_curve=source_curve
    )
    assert changed_curve.damping.signature != frozen_curve_signature
    try:
        mc2_specs.build_mc2_task_specs([tasks[0], soft_task])
    except ValueError:
        pass
    else:
        raise AssertionError("same MC2 task identity with different parameters must fail")

    line_options = mc2_parameters.make_mc2_setup_options(
        mc2_names.MC2_SETUP_BONE_CLOTH, connection_mode=0
    )
    loop_options = mc2_parameters.make_mc2_setup_options(
        mc2_names.MC2_SETUP_BONE_CLOTH, connection_mode=2
    )
    nonloop_options = mc2_parameters.make_mc2_setup_options(
        mc2_names.MC2_SETUP_BONE_CLOTH, connection_mode=3
    )
    line_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_CLOTH, cloth_sources, setup_options=line_options
    )
    loop_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_CLOTH, cloth_sources, setup_options=loop_options
    )
    nonloop_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_CLOTH,
        cloth_sources,
        setup_options=nonloop_options,
    )
    assert line_task.task_id == loop_task.task_id
    assert line_task.topology_signature != loop_task.topology_signature
    assert nonloop_options.connection_mode == 3
    assert nonloop_task.topology_signature != loop_task.topology_signature
    spring_options = mc2_parameters.make_mc2_setup_options(
        mc2_names.MC2_SETUP_BONE_SPRING,
        connection_mode=2,
        collided_by_groups=3,
    )
    assert spring_options.connection_mode == 0
    assert spring_options.collided_by_groups == 3

    real_mesh = bpy.data.meshes.new("MC2_B2_TopologyMesh")
    real_mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1), (1, 2), (2, 0)],
        [(0, 1, 2)],
    )
    real_obj = bpy.data.objects.new("MC2_B2_TopologyObject", real_mesh)
    bpy.context.scene.collection.objects.link(real_obj)
    armature_data = bpy.data.armatures.new("MC2_B2_TopologyArmature")
    armature_obj = bpy.data.objects.new("MC2_B2_TopologyRig", armature_data)
    bpy.context.scene.collection.objects.link(armature_obj)
    try:
        mesh_task = mc2_specs.make_mc2_task_spec(
            mc2_names.MC2_SETUP_MESH_CLOTH, [real_obj]
        )
        mesh_fingerprint = mc2_topology.static_input_fingerprint_for_task(mesh_task)
        mesh_topology = mc2_topology.build_mc2_topology_spec(
            mesh_task,
            static_input_fingerprint=mesh_fingerprint,
        )
        assert mesh_topology.particle_count == 3
        assert mesh_topology.sources[0].resolved is True
        mesh_signature = mesh_topology.topology_signature
        real_mesh.vertices[1].co.x = 2.0
        real_mesh.update()
        changed_fingerprint = mc2_topology.static_input_fingerprint_for_task(mesh_task)
        changed_topology = mc2_topology.build_mc2_topology_spec(
            mesh_task,
            static_input_fingerprint=changed_fingerprint,
        )
        assert changed_topology.topology_signature == mesh_signature
        assert changed_fingerprint.topology == mesh_fingerprint.topology
        assert changed_fingerprint.geometry != mesh_fingerprint.geometry
        assert changed_fingerprint.surface == mesh_fingerprint.surface

        bpy.context.view_layer.objects.active = armature_obj
        armature_obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        root_edit = armature_data.edit_bones.new("Root")
        root_edit.head = (0.0, 0.0, 0.0)
        root_edit.tail = (0.0, 0.0, 1.0)
        child_edit = armature_data.edit_bones.new("Child")
        child_edit.head = root_edit.tail
        child_edit.tail = (0.0, 0.0, 2.0)
        child_edit.parent = root_edit
        child_edit.use_connect = True
        bpy.ops.object.mode_set(mode="OBJECT")
        armature_obj.select_set(False)

        bone_task = mc2_specs.make_mc2_task_spec(
            mc2_names.MC2_SETUP_BONE_CLOTH,
            [{"armature": armature_obj, "root_bone": "Root"}],
        )
        bone_topology = mc2_topology.build_mc2_topology_spec(bone_task)
        assert bone_topology.particle_count == 2
        assert bone_topology.sources[0].resolved is True
        assert bone_topology.bone_connection is not None
        assert bone_topology.bone_connection.lines == ((0, 1),)
        assert bone_topology.bone_connection.triangles == ()
        bone_payload = bone_topology.sources[0].debug_dict(include_payload=True)["payload"]
        assert [record["name"] for record in bone_payload["bones"]] == ["Root", "Child"]
        assert [record["parent_index"] for record in bone_payload["bones"]] == [-1, 0]
        overlapping_task = mc2_specs.make_mc2_task_spec(
            mc2_names.MC2_SETUP_BONE_CLOTH,
            [
                {"armature": armature_obj, "root_bone": "Root"},
                {"armature": armature_obj, "root_bone": "Child"},
            ],
        )
        try:
            mc2_topology.build_mc2_topology_spec(overlapping_task)
        except ValueError:
            pass
        else:
            raise AssertionError("overlapping MC2 bone sources must fail")
    finally:
        if armature_obj.mode != "OBJECT":
            bpy.context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(real_obj, do_unlink=True)
        bpy.data.objects.remove(armature_obj, do_unlink=True)
        bpy.data.meshes.remove(real_mesh)
        bpy.data.armatures.remove(armature_data)

    try:
        mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [])
    except ValueError:
        pass
    else:
        raise AssertionError("empty MC2 source list must fail")
    try:
        mc2_specs.make_mc2_task_spec(mc2_names.MC2_SETUP_MESH_CLOTH, [mesh, mesh])
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate MC2 sources must fail")
    try:
        mc2_specs.build_mc2_task_specs([tasks[0], object()])
    except TypeError:
        pass
    else:
        raise AssertionError("invalid MC2 task list item must fail")
    try:
        replace(tasks[0], task_id="mc2:mesh_cloth:forged")
    except ValueError:
        pass
    else:
        raise AssertionError("forged MC2 task identity must fail")

    adapters = mc2_setups.all_mc2_setup_adapters()
    assert tuple(adapters) == tuple(declaration["setup_types"])
    assert adapters[mc2_names.MC2_SETUP_MESH_CLOTH].source_kind == "mesh_object"
    assert adapters[mc2_names.MC2_SETUP_MESH_CLOTH].writeback_channel == world_names.GN_ATTRIBUTE_CHANNEL
    assert adapters[mc2_names.MC2_SETUP_MESH_CLOTH].debug_dict()["topology_builder"] == "build_mc2_mesh_source_topology"
    for setup_type in (mc2_names.MC2_SETUP_BONE_CLOTH, mc2_names.MC2_SETUP_BONE_SPRING):
        assert adapters[setup_type].source_kind == "bone_chain"
        assert adapters[setup_type].writeback_channel == world_names.BONE_TRANSFORM_CHANNEL
        assert adapters[setup_type].debug_dict()["topology_builder"] == "build_mc2_bone_source_topology"

    class _ResultWorld:
        def __init__(self):
            self.calls = []

        def consume_results(self, channel, *, solver=None):
            self.calls.append((channel, solver))
            return [{"channel": channel, "solver": solver}]

    result_world = _ResultWorld()
    results = tuple(mc2_results.iter_mc2_results(result_world))
    assert tuple(result["channel"] for result in results) == (
        world_names.GN_ATTRIBUTE_CHANNEL,
        world_names.BONE_TRANSFORM_CHANNEL,
        mc2_names.MC2_STATS_CHANNEL,
    )
    assert all(solver == mc2_names.MC2_SOLVER_ID for _channel, solver in result_world.calls)

    world = {"sentinel": object(), "slots": [], "result_streams": {}}
    before = {
        "sentinel": world["sentinel"],
        "slots": list(world["slots"]),
        "result_streams": dict(world["result_streams"]),
    }
    returned_world, ready, status = mc2_solver.step_mc2(world, tasks)
    assert returned_world is world
    assert ready is False
    assert "需要 PhysicsWorldCache" in status
    assert world == before

    physics_world = world_types.PhysicsWorldCache()
    returned_world, ready, status = mc2_solver.step_mc2(physics_world, tasks)
    assert returned_world is physics_world
    assert ready is False
    assert "任务 3" in status and "新建 3" in status
    assert len(physics_world.solver_slots) == 3
    assert physics_world.result_streams == {}
    first_states = {
        slot_id: slot.data["runtime_state"]
        for slot_id, slot in physics_world.solver_slots.items()
    }
    first_native_contexts = {
        slot_id: slot.data["native_context"]
        for slot_id, slot in physics_world.solver_slots.items()
        if slot.data["native_context"] is not None
    }
    for slot in physics_world.solver_slots.values():
        assert slot.kind == mc2_names.MC2_SLOT_KIND
        assert isinstance(slot.data["topology"], mc2_topology.MC2TopologySpec)
        assert isinstance(slot.data["runtime_state"], mc2_state.MC2SlotRuntimeState)
        assert slot.data["runtime_state"].initialized is False
        assert slot.data["runtime_state"].last_reset_reason == "allocation_pending"
        assert slot.data["writeback_plan"] == {}
        snapshot = slot.debug_snapshot()
        expected_backend = slot.data["topology"].particle_count > 0
        assert snapshot["has_backend"] is expected_backend
        if expected_backend:
            assert snapshot["native_context"]["parameters_ready"] is True
            assert snapshot["native_context"]["initialized"] is False

    _, _, status = mc2_solver.step_mc2(physics_world, tasks)
    assert "复用 3" in status
    assert all(
        physics_world.solver_slots[slot_id].data["runtime_state"] is state
        for slot_id, state in first_states.items()
    )

    updated_tasks = (soft_task, tasks[1], tasks[2])
    _, _, status = mc2_solver.step_mc2(physics_world, updated_tasks)
    assert "更新 1" in status and "复用 2" in status
    mesh_state = physics_world.solver_slots[soft_task.task_id].data["runtime_state"]
    mesh_native_context = physics_world.solver_slots[soft_task.task_id].data["native_context"]
    assert mesh_state is first_states[soft_task.task_id]
    assert mesh_state.parameter_revision == 1

    overlapping_fake_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_BONE_CLOTH,
        [
            {"armature": armature, "root_bone": "ClothRoot"},
            {"armature": armature, "bones": ("ClothRoot", "Nested")},
        ],
    )
    revision_before_failed_step = mesh_state.parameter_revision
    conflicting_profile = mc2_parameters.make_mc2_particle_profile(damping=0.35)
    conflicting_mesh_task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH,
        [mesh],
        profile=conflicting_profile,
    )
    try:
        mc2_solver.step_mc2(
            physics_world,
            [conflicting_mesh_task, overlapping_fake_task],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid MC2 topology batch must fail")
    assert mesh_state.parameter_revision == revision_before_failed_step
    assert physics_world.solver_slots[soft_task.task_id].data["spec"] is soft_task
    assert physics_world.solver_slots[soft_task.task_id].data["native_context"] is mesh_native_context

    stepped_settings = mc2_parameters.make_mc2_solver_settings(time_scale=0.5)
    _, _, status = mc2_nodes.physicsMC2Step(
        physics_world,
        updated_tasks,
        time_scale=stepped_settings.time_scale,
        simulation_frequency=stepped_settings.simulation_frequency,
        max_simulation_count_per_frame=(
            stepped_settings.max_simulation_count_per_frame
        ),
    )
    assert "更新 3" in status
    assert all(
        slot.data["runtime_state"].settings_revision == 1
        for slot in physics_world.solver_slots.values()
    )

    _, _, status = mc2_solver.step_mc2(physics_world, [ordered_task])
    assert "新建 1" in status and "清理 3" in status
    ordered_state = physics_world.solver_slots[ordered_task.task_id].data["runtime_state"]
    ordered_context = physics_world.solver_slots[ordered_task.task_id].data["native_context"]
    _, _, status = mc2_solver.step_mc2(physics_world, [reversed_task])
    assert "重建 1" in status
    reversed_state = physics_world.solver_slots[reversed_task.task_id].data["runtime_state"]
    assert reversed_state is not ordered_state
    assert ordered_state.disposed is True
    assert ordered_state.dispose_reason == "topology_changed"
    assert ordered_context is None

    physics_world.generation += 1
    generation_state = reversed_state
    generation_context = physics_world.solver_slots[reversed_task.task_id].data["native_context"]
    _, _, status = mc2_solver.step_mc2(physics_world, [reversed_task])
    assert "重建 1" in status
    assert generation_state.disposed is True
    assert generation_state.dispose_reason == "world_generation_changed"
    assert generation_context is None

    slot_count = len(physics_world.solver_slots)
    _, _, status = mc2_solver.step_mc2(
        physics_world, [], settings=stepped_settings, enabled=False
    )
    assert "已禁用" in status
    assert len(physics_world.solver_slots) == slot_count
    pruned_context = physics_world.solver_slots[reversed_task.task_id].data["native_context"]
    _, _, status = mc2_solver.step_mc2(physics_world, [])
    assert "清理 1" in status
    assert physics_world.solver_slots == {}
    assert pruned_context is None
    assert all(context.disposed for context in first_native_contexts.values())
    source_profile = mc2_parameters.make_mc2_particle_profile(
        gravity=9.8,
        max_distance_enabled=True,
        backstop_enabled=True,
        self_collision_mode=2,
        collision_mode=2,
        collision_friction=0.1,
        spring_enabled=True,
        spring_power=0.07,
    )
    mesh_effective = mc2_parameters.make_mc2_effective_parameters(
        source_profile,
        mc2_parameters.make_mc2_setup_options(mc2_names.MC2_SETUP_MESH_CLOTH),
    ).debug_dict()
    spring_effective = mc2_parameters.make_mc2_effective_parameters(
        source_profile,
        mc2_parameters.make_mc2_setup_options(mc2_names.MC2_SETUP_BONE_SPRING),
    ).debug_dict()
    assert mesh_effective["gravity"] == 9.8
    assert mesh_effective["damping"]["value"] == source_profile.damping.value * 0.2
    assert mesh_effective["angle"]["restoration_stiffness"]["value"] == source_profile.angle_restoration_stiffness.value * 0.2
    assert spring_effective["gravity"] == 0.0
    assert spring_effective["tether"]["compression_limit"] == 0.8
    assert spring_effective["distance"]["stiffness"]["value"] == 0.5
    assert spring_effective["motion"]["max_distance_enabled"] is False
    assert spring_effective["motion"]["backstop_enabled"] is False
    assert spring_effective["self_collision"]["mode"] == 0
    assert spring_effective["collision"]["mode"] == 1
    assert spring_effective["collision"]["dynamic_friction"] == 0.5
    assert spring_effective["spring"]["power"] == 0.07


def test_solver_registry_separates_owned_shared_and_planned_result_channels():
    mc2_declaration = solver_registry.resolve_solver_declaration("mc2")
    summary = solver_declarations.solver_declaration_summary(mc2_declaration)
    assert summary["result_channels"] == [mc2_names.MC2_STATS_CHANNEL]
    assert summary["shared_result_channels"] == [
        world_names.GN_ATTRIBUTE_CHANNEL,
        world_names.BONE_TRANSFORM_CHANNEL,
    ]
    assert summary["planned_result_channels"] == []
    assert summary["planned_shared_result_channels"] == []

    invalid_declaration = solver_registry.resolve_solver_declaration("spring_vrm")
    invalid_declaration["export"] = {
        "result_channels": [world_names.BONE_TRANSFORM_CHANNEL],
        "shared_result_channels": [world_names.BONE_TRANSFORM_CHANNEL],
    }
    assert any(
        "不能重复声明" in problem
        for problem in solver_declarations.validate_solver_declaration(invalid_declaration)
    )

    baseline = solver_registry.validate_solver_registry()
    assert baseline["valid"], baseline["problems"]
    assert world_names.BONE_TRANSFORM_CHANNEL not in baseline["result_channels"]
    assert set(baseline["shared_result_channels"][world_names.BONE_TRANSFORM_CHANNEL]) == {
        "mc2",
        "spring_vrm",
    }
    assert baseline["shared_result_channels"][world_names.GN_ATTRIBUTE_CHANNEL] == ["mc2"]
    assert baseline["result_channels"][mc2_names.MC2_STATS_CHANNEL] == "mc2"
    assert mc2_names.MC2_STATS_CHANNEL not in baseline["planned_result_channels"]
    assert world_names.BONE_TRANSFORM_CHANNEL not in baseline["planned_shared_result_channels"]
    assert world_names.GN_ATTRIBUTE_CHANNEL not in baseline["planned_shared_result_channels"]

    shared_domain = "test_shared_result_solver"
    exclusive_domain = "test_exclusive_result_solver"
    try:
        solver_registry.register_solver_module(shared_domain, {
            "solver_id": shared_domain,
            "declaration": {
                "solver_id": shared_domain,
                "slot_kind": "test_shared_result_slot",
                "export": {
                    "result_channels": [],
                    "shared_result_channels": [world_names.BONE_TRANSFORM_CHANNEL],
                },
            },
        })
        shared = solver_registry.validate_solver_registry()
        assert shared["valid"], shared["problems"]
        assert set(shared["shared_result_channels"][world_names.BONE_TRANSFORM_CHANNEL]) == {
            "mc2",
            "spring_vrm",
            shared_domain,
        }

        solver_registry.register_solver_module(exclusive_domain, {
            "solver_id": exclusive_domain,
            "declaration": {
                "solver_id": exclusive_domain,
                "slot_kind": "test_exclusive_result_slot",
                "export": {
                    "result_channels": [world_names.BONE_TRANSFORM_CHANNEL],
                    "shared_result_channels": [],
                },
            },
        })
        conflict = solver_registry.validate_solver_registry()
        assert conflict["valid"] is False
        assert any(
            problem.get("kind") == "result_channel_ownership"
            and problem.get("id") == world_names.BONE_TRANSFORM_CHANNEL
            for problem in conflict["problems"]
        )
    finally:
        solver_registry.unregister_solver_module(exclusive_domain)
        solver_registry.unregister_solver_module(shared_domain)


def test_domain_registry_dependencies_idempotency_and_rollback():
    blender_registry.unregister_all_blender_property_domains()

    class PG_PhysicsWorldRegistryCoreTest(bpy.types.PropertyGroup):
        value: bpy.props.IntProperty(default=7)  # type: ignore

    class PG_PhysicsWorldRegistryFailTest(bpy.types.PropertyGroup):
        value: bpy.props.FloatProperty(default=1.0)  # type: ignore

    def _raise_factory(**_kwargs):
        raise RuntimeError("intentional binding failure")

    core_decl = {
        "classes": (PG_PhysicsWorldRegistryCoreTest,),
        "bindings": ({
            "owner": bpy.types.Object,
            "name": "hotools_test_world_core_temp",
            "property": "pointer",
            "type": PG_PhysicsWorldRegistryCoreTest,
        },),
    }
    core = blender_registry.register_blender_property_domain("test_core", core_decl)
    assert core["class_count"] == 1 and core["binding_count"] == 1
    assert hasattr(bpy.types.Object, "hotools_test_world_core_temp")
    assert blender_registry.register_blender_property_domain("test_core", core_decl) == core
    drifted_core_decl = {
        "classes": (PG_PhysicsWorldRegistryCoreTest,),
        "bindings": ({
            "owner": bpy.types.Object,
            "name": "hotools_test_world_core_temp",
            "property": "pointer",
            "type": PG_PhysicsWorldRegistryCoreTest,
            "kwargs": {"description": "drifted declaration"},
        },),
    }
    try:
        blender_registry.register_blender_property_domain("test_core", drifted_core_decl)
    except RuntimeError as exc:
        assert "声明发生变化" in str(exc)
    else:
        raise AssertionError("已注册 domain 的 binding metadata 漂移必须被拒绝")

    ui_decl = {
        "bindings": ({
            "owner": "Scene",
            "name": "hotools_test_world_ui_temp",
            "property": "bool",
            "kwargs": {"default": True},
        },),
    }
    blender_registry.register_blender_property_domain(
        "test_ui", ui_decl, dependencies=("test_core",)
    )
    assert hasattr(bpy.types.Scene, "hotools_test_world_ui_temp")
    try:
        blender_registry.unregister_blender_property_domain("test_core")
    except RuntimeError as exc:
        assert "test_ui" in str(exc)
    else:
        raise AssertionError("依赖中的 core domain 不应被提前注销")

    fail_decl = {
        "classes": (PG_PhysicsWorldRegistryFailTest,),
        "bindings": (
            {
                "owner": bpy.types.Object,
                "name": "hotools_test_world_rollback_temp",
                "property": "pointer",
                "type": PG_PhysicsWorldRegistryFailTest,
            },
            {
                "owner": bpy.types.Scene,
                "name": "hotools_test_world_failure_temp",
                "factory": _raise_factory,
            },
        ),
    }
    try:
        blender_registry.register_blender_property_domain("test_failure", fail_decl)
    except RuntimeError as exc:
        assert "intentional binding failure" in str(exc)
    else:
        raise AssertionError("故障 binding 应触发 domain 回滚")
    assert not hasattr(bpy.types.Object, "hotools_test_world_rollback_temp")
    assert not hasattr(bpy.types.Scene, "hotools_test_world_failure_temp")
    assert not blender_registry.is_blender_property_domain_registered("test_failure")

    blender_registry.unregister_blender_property_domain("test_ui")
    blender_registry.unregister_blender_property_domain("test_core")
    assert blender_registry.registered_blender_property_domains() == ()


def test_solver_registry_supports_dynamic_property_domain_lifecycle():
    blender_registry.unregister_all_blender_property_domains()
    solver_registry.unregister_solver_blender_properties()

    binding_count = solver_registry.register_physics_world_blender_properties()
    assert binding_count == 5, {
        "binding_count": binding_count,
        "registry": blender_registry.blender_property_registry_snapshot(),
    }
    assert hasattr(bpy.types.Bone, "hotools_collision")
    assert hasattr(bpy.types.Object, "hotools_object_collision")
    assert blender_registry.registered_blender_property_domains() == ("collision", "mc2", "rigid")
    assert solver_registry.register_physics_world_blender_properties() == 5

    class PG_PhysicsWorldDynamicSolverTest(bpy.types.PropertyGroup):
        enabled: bpy.props.BoolProperty(default=False)  # type: ignore

    descriptor = {
        "solver_id": "test_dynamic_solver",
        "blender_properties": {
            "classes": (PG_PhysicsWorldDynamicSolverTest,),
            "bindings": ({
                "owner": bpy.types.Object,
                "name": "hotools_test_dynamic_solver_temp",
                "property": "pointer",
                "type": PG_PhysicsWorldDynamicSolverTest,
            },),
        },
        "property_dependencies": ("collision",),
    }
    solver_registry.register_solver_module("test_dynamic_solver", descriptor)
    assert hasattr(bpy.types.Object, "hotools_test_dynamic_solver_temp")
    assert blender_registry.registered_blender_property_domains() == (
        "collision", "mc2", "rigid", "test_dynamic_solver",
    )

    solver_registry.unregister_solver_module("test_dynamic_solver")
    assert not hasattr(bpy.types.Object, "hotools_test_dynamic_solver_temp")
    assert hasattr(bpy.types.Bone, "hotools_collision")
    assert hasattr(bpy.types.Object, "hotools_object_collision")

    solver_registry.unregister_physics_world_blender_properties()
    assert not hasattr(bpy.types.Bone, "hotools_collision")
    assert not hasattr(bpy.types.Object, "hotools_object_collision")
    assert blender_registry.registered_blender_property_domains() == ()

    assert solver_registry.register_physics_world_blender_properties() == 5
    solver_registry.unregister_physics_world_blender_properties()
    assert blender_registry.registered_blender_property_domains() == ()


def _contract_property_declaration() -> dict:
    return {
        "classes": (
            collision_property.PG_Hotools_BoneCollision,
            collision_property.PG_Hotools_ObjectCollision,
            mesh_property.PG_Hotools_MeshCollision,
            rigid_property.PG_Hotools_RigidBody,
            rigid_property.PG_Hotools_RigidConstraint,
        ),
        "bindings": (
            {
                "owner": bpy.types.Bone,
                "name": "hotools_collision",
                "property": "pointer",
                "type": collision_property.PG_Hotools_BoneCollision,
            },
            {
                "owner": bpy.types.Object,
                "name": "hotools_object_collision",
                "property": "pointer",
                "type": collision_property.PG_Hotools_ObjectCollision,
            },
            {
                "owner": bpy.types.Object,
                "name": "hotools_mesh_collision",
                "property": "pointer",
                "type": mesh_property.PG_Hotools_MeshCollision,
            },
            {
                "owner": bpy.types.Object,
                "name": "hotools_rigid_body",
                "property": "pointer",
                "type": rigid_property.PG_Hotools_RigidBody,
            },
            {
                "owner": bpy.types.Object,
                "name": "hotools_rigid_constraint",
                "property": "pointer",
                "type": rigid_property.PG_Hotools_RigidConstraint,
            },
        ),
    }


def _new_mesh_object(name: str):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _new_armature_object(name: str):
    armature = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, armature)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("contract_bone")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _bounded_alternate(value, minimum, maximum, *, integer=False):
    step = 1 if integer else 0.125
    candidates = (value + step, value - step)
    for candidate in candidates:
        if minimum is not None:
            candidate = max(candidate, minimum)
        if maximum is not None:
            candidate = min(candidate, maximum)
        if candidate != value:
            return int(candidate) if integer else float(candidate)
    return int(value) if integer else float(value)


def _assign_non_default_fields(instance, cls, pointer_values: dict[str, object]) -> None:
    for name, deferred in (getattr(cls, "__annotations__", {}) or {}).items():
        factory_name = getattr(getattr(deferred, "function", None), "__name__", "")
        keywords = dict(getattr(deferred, "keywords", {}) or {})
        current = getattr(instance, name)

        if factory_name == "BoolProperty":
            value = not bool(current)
        elif factory_name == "EnumProperty":
            items = keywords.get("items") or ()
            identifiers = [str(item[0]) for item in items if isinstance(item, (list, tuple)) and item]
            value = next((item for item in reversed(identifiers) if item != str(current)), str(current))
        elif factory_name == "FloatProperty":
            value = _bounded_alternate(
                float(current),
                keywords.get("min"),
                keywords.get("max"),
            )
        elif factory_name == "IntProperty":
            value = _bounded_alternate(
                int(current),
                keywords.get("min"),
                keywords.get("max"),
                integer=True,
            )
        elif factory_name == "FloatVectorProperty":
            minimum = keywords.get("min")
            maximum = keywords.get("max")
            value = tuple(
                _bounded_alternate(float(item), minimum, maximum)
                for item in current
            )
        elif factory_name == "StringProperty":
            value = f"contract_{name}"
        elif factory_name == "PointerProperty":
            value = pointer_values[name]
        else:
            raise AssertionError(f"unsupported contract property: {cls.__name__}.{name} ({factory_name})")

        setattr(instance, name, value)


def _serialize_property_value(value):
    if isinstance(value, bpy.types.ID):
        return {"id_type": value.bl_rna.identifier, "name": value.name}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return tuple(float(item) for item in value)
    except Exception:
        return repr(value)


def _snapshot_property_group(instance, cls) -> dict:
    return {
        name: _serialize_property_value(getattr(instance, name))
        for name in (getattr(cls, "__annotations__", {}) or {})
    }


def test_blend_roundtrip_preserves_all_persistent_property_fields():
    blender_registry.unregister_all_blender_property_domains()
    declaration = _contract_property_declaration()
    blend_path = os.path.join(tempfile.gettempdir(), "hotools_physics_property_contract.blend")

    blender_registry.register_blender_property_domain("contract_fixture", declaration)
    try:
        armature = _new_armature_object("PW_PropertyContractArmature")
        physical_obj = _new_mesh_object("PW_PropertyContractObject")
        base_pose_obj = _new_mesh_object("PW_PropertyContractBasePose")
        constraint_obj = bpy.data.objects.new("PW_PropertyContractConstraint", None)
        bpy.context.scene.collection.objects.link(constraint_obj)

        bone = armature.data.bones["contract_bone"]
        instances = {
            "PG_Hotools_BoneCollision": (
                bone.hotools_collision,
                collision_property.PG_Hotools_BoneCollision,
                {},
            ),
            "PG_Hotools_ObjectCollision": (
                physical_obj.hotools_object_collision,
                collision_property.PG_Hotools_ObjectCollision,
                {},
            ),
            "PG_Hotools_MeshCollision": (
                physical_obj.hotools_mesh_collision,
                mesh_property.PG_Hotools_MeshCollision,
                {"mc2_base_pose_proxy": base_pose_obj},
            ),
            "PG_Hotools_RigidBody": (
                physical_obj.hotools_rigid_body,
                rigid_property.PG_Hotools_RigidBody,
                {},
            ),
            "PG_Hotools_RigidConstraint": (
                constraint_obj.hotools_rigid_constraint,
                rigid_property.PG_Hotools_RigidConstraint,
                {
                    "target_a": physical_obj,
                    "target_b": base_pose_obj,
                    "reference_constraint_a": physical_obj,
                    "reference_constraint_b": base_pose_obj,
                },
            ),
        }
        for instance, cls, pointers in instances.values():
            _assign_non_default_fields(instance, cls, pointers)
        before = {
            name: _snapshot_property_group(instance, cls)
            for name, (instance, cls, _pointers) in instances.items()
        }

        bpy.ops.wm.save_as_mainfile(filepath=blend_path)
        blender_registry.unregister_blender_property_domain("contract_fixture")
        blender_registry.register_blender_property_domain("contract_fixture", declaration)
        bpy.ops.wm.open_mainfile(filepath=blend_path)

        armature = bpy.data.objects["PW_PropertyContractArmature"]
        physical_obj = bpy.data.objects["PW_PropertyContractObject"]
        constraint_obj = bpy.data.objects["PW_PropertyContractConstraint"]
        after_instances = {
            "PG_Hotools_BoneCollision": (
                armature.data.bones["contract_bone"].hotools_collision,
                collision_property.PG_Hotools_BoneCollision,
            ),
            "PG_Hotools_ObjectCollision": (
                physical_obj.hotools_object_collision,
                collision_property.PG_Hotools_ObjectCollision,
            ),
            "PG_Hotools_MeshCollision": (
                physical_obj.hotools_mesh_collision,
                mesh_property.PG_Hotools_MeshCollision,
            ),
            "PG_Hotools_RigidBody": (
                physical_obj.hotools_rigid_body,
                rigid_property.PG_Hotools_RigidBody,
            ),
            "PG_Hotools_RigidConstraint": (
                constraint_obj.hotools_rigid_constraint,
                rigid_property.PG_Hotools_RigidConstraint,
            ),
        }
        after = {
            name: _snapshot_property_group(instance, cls)
            for name, (instance, cls) in after_instances.items()
        }
        assert after == before, json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2)
    finally:
        blender_registry.unregister_blender_property_domain("contract_fixture", force=True)
        if os.path.exists(blend_path):
            os.remove(blend_path)


TESTS = (
    ("persistent PropertyGroup RNA contracts", test_persistent_property_contracts_are_frozen),
    ("components own shared and adapter capabilities", test_components_own_shared_and_solver_adapter_capabilities),
    ("rigid RNA/capabilities share one schema", test_rigid_rna_and_capabilities_share_one_schema),
    ("mesh cloth RNA/capability share one schema", test_mesh_cloth_rna_and_capability_share_one_schema),
    ("solver node modules keep manifest menu groups", test_solver_node_modules_are_grouped_by_manifest_menu_name),
    ("solver add menu uses manifest submenus", test_solver_node_add_menu_uses_manifest_submenus),
    ("one MC2 solver owns three public setup types", test_mc2_is_one_solver_with_three_setup_types_and_public_step),
    ("solver registry separates owned/shared/planned result channels", test_solver_registry_separates_owned_shared_and_planned_result_channels),
    ("domain dependencies/idempotency/rollback", test_domain_registry_dependencies_idempotency_and_rollback),
    ("dynamic solver property lifecycle", test_solver_registry_supports_dynamic_property_domain_lifecycle),
    (".blend roundtrip for all persistent fields", test_blend_roundtrip_preserves_all_persistent_property_fields),
)


def main() -> None:
    passed = 0
    try:
        for name, test in TESTS:
            test()
            passed += 1
            print(f"[PASS] {name}")
    finally:
        try:
            solver_registry.unregister_solver_module("test_dynamic_solver")
        except Exception:
            pass
        try:
            solver_registry.unregister_physics_world_blender_properties()
        except Exception:
            pass
        try:
            blender_registry.unregister_all_blender_property_domains()
        except Exception:
            pass
    print(f"{passed}/{len(TESTS)} passed")
    if passed != len(TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
