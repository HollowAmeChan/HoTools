"""MC2 product 注册表与公开节点契约验收入口。"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import types

import bpy


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
HOTOOLS = os.path.dirname(os.path.dirname(os.path.dirname(TEST_ROOT)))
NODETREE = os.path.join(HOTOOLS, "OmniNode")
FUNCTION = os.path.join(NODETREE, "Function")
PHYSICS_WORLD = os.path.join(NODETREE, "PhysicsWorld")
MC2_ROOT = os.path.join(PHYSICS_WORLD, "mc2")
MC2_TEST_ROOT = os.path.join(MC2_ROOT, "test")

for path in (TEST_ROOT, MC2_TEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", FUNCTION),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.PhysicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


solver_registry = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.registry"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.nodes"
)
mesh_schema = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.simple_cloth.schema"
)
mesh_property = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.simple_cloth.properties"
)
mesh_object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.mc2.setups.mesh_cloth.object_spec"
)


def test_mc2_product_registry_contract():
    assert solver_registry.builtin_solver_domains().count("mc2") == 1
    assert "mesh_cloth" not in solver_registry.builtin_solver_domains()
    descriptor = solver_registry.all_solver_module_descriptors()["mc2"]
    assert descriptor["nodes"] == (".nodes",)
    assert descriptor["blender_lifecycle"] == ".source_observation_blender"

    schema_names = tuple(str(field["name"]) for field in mesh_schema.MESH_COLLISION_RNA_FIELDS)
    assert tuple(mesh_property.PG_Hotools_MeshCollision.__annotations__) == schema_names
    assert len(schema_names) == 7
    assert "enabled" in schema_names
    assert "enabled" not in mesh_object_spec.MC2_MESH_EXPLICIT_PROPERTY_FIELDS
    assert mc2_nodes.physicsMC2MeshObject.__meta["bl_label"] == "MC2 MeshCloth对象"
    assert mc2_nodes.physicsMC2MeshCustomObject.__meta["bl_label"] == (
        "MC2 MeshCloth自定义对象"
    )
    assert mc2_nodes.physicsMC2MeshCollector.__meta["bl_label"] == "MC2 Mesh域收集"
    assert mc2_nodes.physicsMC2MeshCollector.__meta["_INPUT_NAME"] == ["Mesh分区"]
    assert mc2_nodes.physicsMC2MeshCollector.__meta["_OUTPUT_NAME"][0] == "MC2域"
    assert mc2_nodes.physicsMC2MeshClothTask.__meta["bl_label"] == "MC2 MeshCloth域"
    assert mc2_nodes.physicsMC2MeshClothTask.__meta["_OUTPUT_NAME"] == [
        "Mesh分区", "域标识"
    ]
    assert "启用" not in mc2_nodes.physicsMC2MeshClothTask.__meta["_INPUT_NAME"]
    assert "自碰交互质量" in mc2_nodes.physicsMC2MeshClothProfile.__meta["_INPUT_NAME"]
    assert "自碰交互质量" in mc2_nodes.physicsMC2BoneClothProfile.__meta["_INPUT_NAME"]
    assert "自碰交互质量" not in mc2_nodes.physicsMC2BoneSpringProfile.__meta["_INPUT_NAME"]
    assert mc2_nodes.physicsMC2BoneClothObject.__meta["bl_label"] == (
        "MC2 BoneCloth对象"
    )
    assert mc2_nodes.physicsMC2BoneClothCustomObject.__meta["bl_label"] == (
        "MC2 BoneCloth自定义对象"
    )
    assert mc2_nodes.physicsMC2BoneCollector.__meta["bl_label"] == (
        "MC2 Bone域收集"
    )
    assert mc2_nodes.physicsMC2BoneCollector.__meta["_INPUT_NAME"] == [
        "Bone分区"
    ]
    assert mc2_nodes.physicsMC2BoneClothTask.__meta["bl_label"] == "MC2 BoneCloth域"
    bone_cloth_signature = inspect.signature(mc2_nodes.physicsMC2BoneClothTask)
    assert bone_cloth_signature.parameters["rotational_interpolation"].default == 1.0
    assert bone_cloth_signature.parameters["root_rotation"].default == 1.0
    assert mc2_nodes.physicsMC2BoneSpringTask.__meta["bl_label"] == "MC2 BoneSpring域"
    assert mc2_nodes.physicsMC2BoneClothTask.__meta["_OUTPUT_NAME"] == [
        "Bone分区", "域标识"
    ]
    assert mc2_nodes.physicsMC2BoneClothTask.__meta["_INPUT_NAME"][0] == (
        "BoneCloth对象"
    )
    for node in (
        mc2_nodes.physicsMC2BoneClothObject,
        mc2_nodes.physicsMC2BoneClothCustomObject,
        mc2_nodes.physicsMC2BoneClothTask,
    ):
        description = node.__meta["omni_description"]
        assert "尽量关闭Bone > Relations > Connected" in description
        assert "rotation-only兼容模式" in description
        assert "solver不会自动断开骨骼" in description
    assert "逐骨碰撞属性来自实际模拟骨" in (
        mc2_nodes.physicsMC2BoneClothObject.__meta["input_init"]
        ["control_bones"]["description"]
    )
    assert "Connected骨在Blender中不能接收粒子的独立局部平移" in (
        mc2_nodes.physicsMC2BoneClothTask.__meta["input_init"]
        ["bone_objects"]["description"]
    )
    assert "被碰撞组" not in mc2_nodes.physicsMC2BoneClothTask.__meta["_INPUT_NAME"]
    assert mc2_nodes.physicsMC2BoneSpringTask.__meta["_OUTPUT_NAME"] == [
        "MC2域", "域标识"
    ]
    for domain_node in (
        mc2_nodes.physicsMC2MeshClothTask,
        mc2_nodes.physicsMC2BoneClothTask,
        mc2_nodes.physicsMC2BoneSpringTask,
    ):
        assert "启用" not in domain_node.__meta["_INPUT_NAME"]
        assert "自碰交互质量" not in domain_node.__meta["_INPUT_NAME"]
    assert mc2_nodes.physicsMC2Step.__meta["_INPUT_NAME"][1] == "MC2域"
    assert "启用" not in mc2_nodes.physicsMC2Step.__meta["_INPUT_NAME"]

    product_slot = importlib.import_module("test_product_slot")
    product_collect = importlib.import_module("test_product_collect")
    product_slot.test_slot_native_executes_complete_compiled_frame()
    product_collect.test_product_collector_consumes_one_explicit_domain_plan_without_task_expansion()
    print("PASS test_mc2_product_registry_contract")


if __name__ == "__main__":
    test_mc2_product_registry_contract()
