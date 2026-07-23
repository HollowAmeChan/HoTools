"""MC2 product 注册表与公开节点契约验收入口。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
HOTOOLS = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(TEST_ROOT))))
)
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PHYSICS_WORLD = os.path.join(FUNCTION, "physicsWorld")
MC2_ROOT = os.path.join(PHYSICS_WORLD, "mc2")
MC2_TEST_ROOT = os.path.join(MC2_ROOT, "test")

for path in (TEST_ROOT, MC2_TEST_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PHYSICS_WORLD),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2", MC2_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


solver_registry = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.registry"
)
mc2_nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
mesh_schema = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.schema"
)
mesh_property = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.properties"
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
    assert mc2_nodes.physicsMC2MeshObject.__meta["bl_label"] == "MC2 Mesh对象"
    assert mc2_nodes.physicsMC2MeshCollector.__meta["bl_label"] == "MC2 Mesh收集器"

    product_slot = importlib.import_module("test_product_slot")
    product_collect = importlib.import_module("test_product_collect")
    product_slot.test_slot_native_executes_complete_compiled_frame()
    product_collect.test_product_collector_consumes_one_explicit_domain_plan_without_task_expansion()
    print("PASS test_mc2_product_registry_contract")


if __name__ == "__main__":
    test_mc2_product_registry_contract()
