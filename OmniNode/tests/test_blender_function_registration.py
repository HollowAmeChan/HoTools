"""Regression coverage for self-describing Function module registration."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import tempfile
import types

import bpy


HOTOOLS = Path(__file__).resolve().parents[2]
FUNCTION_DIRECTORY = HOTOOLS / "OmniNode" / "Function"
sys.path.insert(0, str(HOTOOLS.parent))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package

OmniNode = importlib.import_module("HoTools.OmniNode")
function_registry = importlib.import_module(
    "HoTools.OmniNode.OmniNodeFunctionRegistry"
)
node_register = importlib.import_module("HoTools.OmniNode.OmniNodeRegister")


def assert_raises(exception_type, callback, text):
    try:
        callback()
    except exception_type as exc:
        assert text in str(exc), str(exc)
        return
    raise AssertionError(f"expected {exception_type.__name__}: {text}")


# Every Function source file is self-describing near the module header.
function_paths = sorted(
    path for path in FUNCTION_DIRECTORY.rglob("*.py")
    if path.name != "__init__.py"
)
for path in function_paths:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declaration_index = next(
        (
            index
            for index, statement in enumerate(tree.body)
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name)
                and target.id == function_registry.REGISTRATION_ATTRIBUTE
                for target in (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else (statement.target,)
                )
            )
        ),
        None,
    )
    assert declaration_index is not None, path
    assert declaration_index <= 2, f"registration marker must stay in header: {path}"

discovered_paths = {
    registration.relative_path
    for registration in node_register.function_module_registrations
}
expected_paths = {
    path.relative_to(FUNCTION_DIRECTORY).as_posix()
    for path in function_paths
}
assert discovered_paths == expected_paths

expected_categories = [
    "GRAPH", "DATA", "ARMATURE", "DATA_TYPECAST", "MATH", "OPERATOR",
    "MODIFIER", "MATERIAL", "UV", "VERTEXCOLOR", "VERTEXGROUP", "IMAGE",
    "RIGTOOLKIT", "LOGIC", "DEBUG", "CACHE", "PHYSICS",
    "CUSTOM",
    "PHYSICS_WORLD", "PHYSICS_SOLVER", "PHYSICS_WORLD_DEBUG",
]
assert [category.identifier for category in node_register.node_categories] == expected_categories


# Function discovery must not add category or path data to persisted node IDs.
function_node_classes = [
    node_class
    for registration in node_register.function_module_registrations
    for node_class in registration.node_classes
]
for node_class in function_node_classes:
    assert node_class.bl_idname == f"HO_OmniNode_{node_class._func.__name__}"

legacy_node_ids = {
    "HO_OmniNode_GroupNode",
    "HO_OmniNode_GroupNode_Inputs",
    "HO_OmniNode_GroupNode_Outputs",
    "HO_OmniNode_BatchGroupNode",
    "HO_OmniNode_CacheRead",
    "HO_OmniNode_CacheWrite",
    "HO_OmniNode_CacheDelete",
    "HO_OmniNode_CacheDump",
    "HO_OmniNode_stringInput",
    "HO_OmniNode_bonesFromRoot",
    "HO_OmniNode_float2int",
    "HO_OmniNode_floatAdd",
    "HO_OmniNode_composeTransform",
    "HO_OmniNode_objectAddModifier",
    "HO_OmniNode_objectAddMaterialSlot",
    "HO_OmniNode_objectCreateUVLayer",
    "HO_OmniNode_objectCreateColorAttribute",
    "HO_OmniNode_objectCreateVertexGroup",
    "HO_OmniNode_saveImage",
    "HO_OmniNode_createCollection",
    "HO_OmniNode_switch",
    "HO_OmniNode_debug_print_any",
    "HO_OmniNode_floating",
    "HO_OmniNode_meshPhysicsXPBD",
    "HO_OmniNode_physicsWorldBegin",
    "HO_OmniNode_physicsWorldCommit",
    "HO_OmniNode_physicsSpringVRMSolver",
    "HO_OmniNode_physicsRigidSolver",
    "HO_OmniNode_physicsMC2Step",
    "HO_OmniNode_customExampleScale",
}
current_node_ids = {node_class.bl_idname for node_class in node_register.cls}
assert legacy_node_ids <= current_node_ids
assert len(current_node_ids) == len(node_register.cls)


# Disabled helpers and malformed declarations have explicit behavior.
disabled_module = types.ModuleType("test_disabled_function_module")
disabled_module.OMNI_NODE_REGISTRATION = {"enabled": False}
assert function_registry.normalize_function_registration(disabled_module) is None

missing_module = types.ModuleType("test_missing_function_module")
assert_raises(
    ValueError,
    lambda: function_registry.normalize_function_registration(missing_module),
    "missing OMNI_NODE_REGISTRATION",
)

invalid_path_module = types.ModuleType("test_invalid_path_function_module")
invalid_path_module.OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "Custom", "order": 1000},
    "menu_path": "Characters/Face",
}
assert_raises(
    ValueError,
    lambda: function_registry.normalize_function_registration(invalid_path_module),
    "menu_path must be a list or tuple",
)


# A nested namespace-package module is found without editing a central registry.
temporary_package_name = "omninode_test_custom_functions"
with tempfile.TemporaryDirectory() as temporary_directory:
    temporary_function_directory = Path(temporary_directory)
    nested_directory = temporary_function_directory / "User" / "Face"
    nested_directory.mkdir(parents=True)
    (nested_directory / "Eyes.py").write_text(
        """OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "Custom", "order": 1000},
    "menu_path": ("Character", "Face", "Eyes"),
    "order": 10,
}

from HoTools.OmniNode.FunctionNodeCore import omni

@omni(enable=True, bl_label="Custom Eyes")
def customEyes(value: float) -> float:
    return value
""",
        encoding="utf-8",
    )
    temporary_package = types.ModuleType(temporary_package_name)
    temporary_package.__path__ = [str(temporary_function_directory)]
    temporary_package.__package__ = temporary_package_name
    sys.modules[temporary_package_name] = temporary_package
    try:
        temporary_registrations = function_registry.discover_function_modules(
            function_directory=temporary_function_directory,
            package=temporary_package_name,
        )
        assert len(temporary_registrations) == 1
        temporary_registration = temporary_registrations[0]
        assert temporary_registration.relative_path == "User/Face/Eyes.py"
        assert temporary_registration.menu_path == ("Character", "Face", "Eyes")
        assert [node.bl_idname for node in temporary_registration.node_classes] == [
            "HO_OmniNode_customEyes"
        ]

        (nested_directory / "Conflict.py").write_text(
            """OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "Conflicting", "order": 1000},
    "menu_path": (),
}

from HoTools.OmniNode.FunctionNodeCore import omni

@omni(enable=True)
def customConflict(value: float) -> float:
    return value
""",
            encoding="utf-8",
        )
        assert_raises(
            ValueError,
            lambda: function_registry.discover_function_modules(
                function_directory=temporary_function_directory,
                package=temporary_package_name,
            ),
            "label/order must match",
        )
    finally:
        for module_name in tuple(sys.modules):
            if module_name == temporary_package_name or module_name.startswith(
                temporary_package_name + "."
            ):
                del sys.modules[module_name]


# Synthetic declarations cover mixed root nodes and arbitrary-depth nested menus.
def fake_node_class(name):
    return type(name, (), {"bl_idname": f"HO_Test_{name}"})


def fake_registration(module_name, menu_path, order, *node_names):
    module = types.ModuleType(module_name)
    return function_registry.FunctionModuleRegistration(
        module=module,
        module_name=module_name,
        relative_path=f"Custom/{module_name.rsplit('.', 1)[-1]}.py",
        category_id="CUSTOM",
        category_label="Custom",
        category_order=1000,
        menu_path=menu_path,
        order=order,
        node_classes=tuple(fake_node_class(name) for name in node_names),
    )


synthetic_registrations = (
    fake_registration("custom.root", (), 0, "Root"),
    fake_registration("custom.eyes", ("Characters", "Face", "Eyes"), 10, "Eyes"),
    fake_registration("custom.mouth", ("Characters", "Face", "Mouth"), 20, "Mouth"),
    fake_registration("custom.rig", ("Characters", "Rig"), 30, "Rig"),
)
records = node_register._build_function_category_records(synthetic_registrations)
assert len(records) == 1
custom_root = records[0]["root"]
assert [node.bl_idname for _key, node in custom_root["nodes"]] == ["HO_Test_Root"]
characters = custom_root["children"]["Characters"]
face = characters["children"]["Face"]
assert set(face["children"]) == {"Eyes", "Mouth"}
assert "Rig" in characters["children"]

_records, synthetic_categories, synthetic_menu_classes = (
    node_register._build_function_categories(synthetic_registrations)
)
assert [category.identifier for category in synthetic_categories] == ["CUSTOM"]
assert len(synthetic_menu_classes) == 5
assert len({menu.bl_idname for menu in synthetic_menu_classes}) == 5
for menu_class in synthetic_menu_classes:
    bpy.utils.register_class(menu_class)
for menu_class in reversed(synthetic_menu_classes):
    bpy.utils.unregister_class(menu_class)

duplicate_a = fake_node_class("Duplicate")
duplicate_b = fake_node_class("Duplicate")
assert_raises(
    ValueError,
    lambda: node_register._validate_unique_node_ids((duplicate_a, duplicate_b)),
    "duplicate OmniNode bl_idname",
)


for cycle in range(2):
    OmniNode.register()
    tree = bpy.data.node_groups.new(
        f"OmniNodeFunctionRegistration{cycle}",
        "OmniNodeTree",
    )
    for node_id in sorted(legacy_node_ids):
        node = tree.nodes.new(node_id)
        assert node.bl_idname == node_id
    bpy.data.node_groups.remove(tree)
    OmniNode.unregister()
    assert not node_register._registered_node_classes
    assert not node_register._registered_menu_classes

print("OmniNode Function registration: PASS")
