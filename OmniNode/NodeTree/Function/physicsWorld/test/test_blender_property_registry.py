

# -*- coding: utf-8 -*-
"""Physics World domain property registry 与迁移契约测试。

用法：
    blender.exe --factory-startup --background --python test_blender_property_registry.py
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
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
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.properties"
)
mesh_schema = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.schema"
)
mesh_capabilities = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mesh_cloth.capabilities"
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
mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_solver = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.solver"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
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
        "sha256": "c7d69696b5d3a5415b81232449de5611108149ffc231103922036c12b2658734",
        "fields": (
            "mc2_base_pose_proxy", "enabled", "radius", "radius_vertex_group",
            "pin_enabled", "pin_vertex_group", "self_collision_enabled",
            "self_collision_surface_thickness", "mass",
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
        "sha256": "5b2042671b7b399ddf2be817b7930b08b8369b1289de18e3449050474ed60488",
        "fields": (
            "enabled", "constraint_type", "target_a", "target_b", "anchor_mode",
            "local_point_a", "local_rotation_a", "local_point_b", "local_rotation_b",
            "disable_collisions", "breakable", "breaking_threshold",
            "constraint_priority", "solver_velocity_steps", "solver_position_steps",
            "draw_constraint_size", "limit_enabled", "angular_limit_min",
            "angular_limit_max", "linear_limit_min", "linear_limit_max",
            "limit_spring_frequency", "limit_spring_damping", "max_friction_torque",
            "max_friction_force", "motor_state", "motor_frequency", "motor_damping",
            "motor_force_limit", "motor_torque_limit",
            "motor_target_angular_velocity", "motor_target_angle",
            "motor_target_velocity", "motor_target_position", "cone_half_angle",
            "distance_min", "distance_max",
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
    assert tuple(len(schema) for _storage, schema, _cls, _capability in pairs) == (34, 37)
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
    assert len(schema) == 11
    assert tuple(mesh_property.PG_Hotools_MeshCollision.__annotations__) == names
    assert tuple(str(field["name"]) for field in capability_fields) == names
    for declaration, field in zip(schema, capability_fields):
        assert field["rna"] == declaration["kwargs"]
        assert field["default"] == declaration["kwargs"].get("default")
        assert field["explicit_property"] == f"Object.hotools_mesh_collision.{declaration['name']}"


def test_mc2_is_one_solver_with_three_setup_types_and_safe_framework_step():
    legacy_modules = (
        "HoTools.OmniNode.NodeTree.Function.physicsMC2MeshCloth",
        "HoTools.OmniNode.NodeTree.Function.physicsMC2BoneCloth",
    )
    assert not any(name in sys.modules for name in legacy_modules)

    assert solver_registry.builtin_solver_domains().count("mc2") == 1
    assert "mesh_cloth" not in solver_registry.builtin_solver_domains()
    assert solver_registry.builtin_component_domains() == ("collision", "mesh_cloth")
    descriptor = solver_registry.all_solver_module_descriptors()["mc2"]
    assert descriptor["solver_id"] == "mc2"
    assert descriptor["nodes"] == (".nodes",)
    assert tuple(
        node.__meta["bl_label"]
        for node in (
            mc2_nodes.physicsMC2MeshClothTask,
            mc2_nodes.physicsMC2BoneClothTask,
            mc2_nodes.physicsMC2BoneSpringTask,
            mc2_nodes.physicsMC2Step,
        )
    ) == (
        "MC2 MeshCloth任务（框架）",
        "MC2 BoneCloth任务（框架）",
        "MC2 BoneSpring任务（框架）",
        "MC2模拟步（框架）",
    )
    generated_node_classes = function_node_core.loadRegisterFuncNodes(mc2_nodes)
    assert tuple(node.bl_label for node in generated_node_classes) == (
        "MC2 BoneCloth任务（框架）",
        "MC2 BoneSpring任务（框架）",
        "MC2 MeshCloth任务（框架）",
        "MC2模拟步（框架）",
    )

    declaration = solver_registry.resolve_solver_declaration("mc2")
    assert declaration is not None
    assert solver_declarations.validate_solver_declaration(declaration) == []
    assert declaration["implementation_status"] == "framework_only"
    assert tuple(declaration["setup_types"]) == (
        mc2_names.MC2_SETUP_MESH_CLOTH,
        mc2_names.MC2_SETUP_BONE_CLOTH,
        mc2_names.MC2_SETUP_BONE_SPRING,
    )
    assert declaration["solver_id"] == mc2_names.MC2_SOLVER_ID == "mc2"
    assert "one_solver_three_setup_adapters" in declaration["native_strategy"]
    assert declaration["update_policy"]["framework"] == "no_slot_no_result_no_legacy_solver_call"

    tasks = tuple(
        mc2_specs.make_mc2_task_spec(setup_type, [object()])
        for setup_type in declaration["setup_types"]
    )
    assert tuple(task.setup_type for task in tasks) == tuple(declaration["setup_types"])
    assert {task.backend for task in tasks} == {"auto"}

    world = {"sentinel": object(), "slots": [], "result_streams": {}}
    before = {
        "sentinel": world["sentinel"],
        "slots": list(world["slots"]),
        "result_streams": dict(world["result_streams"]),
    }
    returned_world, ready, status = mc2_solver.step_mc2(world, tasks)
    assert returned_world is world
    assert ready is False
    assert "有效任务 3" in status
    assert world == before
    assert not any(name in sys.modules for name in legacy_modules)


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
    assert blender_registry.registered_blender_property_domains() == ("collision", "mesh_cloth", "rigid")
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
        "collision", "mesh_cloth", "rigid", "test_dynamic_solver",
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
                {"target_a": physical_obj, "target_b": base_pose_obj},
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
    ("one MC2 solver owns three safe framework setup types", test_mc2_is_one_solver_with_three_setup_types_and_safe_framework_step),
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
