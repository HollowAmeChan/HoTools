"""自描述函数模块注册的回归测试。"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import tempfile
import types

import bpy


HOTOOLS = Path(__file__).resolve().parents[2]
OMNINODE_DIRECTORY = HOTOOLS / "OmniNode"
MODULE_DIRECTORIES = {
    name: OMNINODE_DIRECTORY / name
    for name in ("Function", "Custom")
}
sys.path.insert(0, str(HOTOOLS.parent))

hotools_package = types.ModuleType("HoTools")
hotools_package.__path__ = [str(HOTOOLS)]
hotools_package.__package__ = "HoTools"
sys.modules["HoTools"] = hotools_package

OmniNode = importlib.import_module("HoTools.OmniNode")
node_register = importlib.import_module("HoTools.OmniNode.OmniNodeRegister")
node_register._rebuild_registry()


def assert_raises(exception_type, callback, text):
    try:
        callback()
    except exception_type as exc:
        assert text in str(exc), str(exc)
        return
    raise AssertionError(f"预期抛出 {exception_type.__name__}：{text}")


# 每个内置或自定义函数模块都必须在文件头自描述。
module_paths = sorted(
    (directory_name, path)
    for directory_name, directory in MODULE_DIRECTORIES.items()
    for path in directory.glob("*.py")
    if path.name != "__init__.py"
)
for _directory_name, path in module_paths:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    declaration_index = next(
        (
            index
            for index, statement in enumerate(tree.body)
            if isinstance(statement, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name)
                and target.id == node_register.REGISTRATION_ATTRIBUTE
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
    assert declaration_index <= 2, f"注册声明必须位于文件头：{path}"

discovered_paths = {
    module_spec.source_path
    for module_spec in node_register._registry.function_modules
}
expected_paths = {
    f"{directory_name}/{path.relative_to(MODULE_DIRECTORIES[directory_name]).as_posix()}"
    for directory_name, path in module_paths
}
assert discovered_paths == expected_paths
nested_example = next(
    module_spec
    for module_spec in node_register._registry.function_modules
    if module_spec.source_path == "Custom/NestedCategoryExample.py"
)
assert nested_example.menu_path == ("示例", "嵌套分类", "数值工具")
assert [node.bl_idname for node in nested_example.node_classes] == [
    "HO_OmniNode_customNestedCategoryOffset"
]

expected_categories = [
    "GRAPH", "DATA", "ARMATURE", "DATA_TYPECAST", "MATH", "OPERATOR",
    "MODIFIER", "MATERIAL", "UV", "VERTEXCOLOR", "VERTEXGROUP", "IMAGE",
    "RIGTOOLKIT", "LOGIC", "DEBUG", "CACHE", "PHYSICS",
    "CUSTOM",
    "PHYSICS_WORLD", "PHYSICS_SOLVER", "PHYSICS_WORLD_DEBUG",
]
assert [
    category.identifier
    for category in node_register._registry.node_categories
] == expected_categories
expected_category_labels = [
    "图结构", "数据", "骨架", "数据类型转换", "数学", "操作",
    "修改器", "材质", "UV", "顶点颜色", "顶点组", "图像",
    "绑定工具", "逻辑", "调试", "缓存", "物理", "自定义",
    "物理世界", "解算器", "物理世界调试",
]
assert [category.name for category in node_register._registry.node_categories] == (
    expected_category_labels
)
assert [
    extension.identifier
    for extension in node_register._registry.extensions
] == ["PhysicsWorld"]


# 自动发现不得把分类或路径写入持久化节点 ID。
function_node_classes = [
    node_class
    for module_spec in node_register._registry.function_modules
    for node_class in module_spec.node_classes
]
for node_class in function_node_classes:
    assert node_class.bl_idname == f"HO_OmniNode_{node_class._func.__name__}"

required_node_ids = {
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
    "HO_OmniNode_physicsWorldBegin",
    "HO_OmniNode_physicsWorldCommit",
    "HO_OmniNode_physicsSpringVRMSolver",
    "HO_OmniNode_physicsRigidSolver",
    "HO_OmniNode_physicsMC2Step",
    "HO_OmniNode_physicsMeshXpbdObject",
    "HO_OmniNode_physicsMeshXpbdCustomObject",
    "HO_OmniNode_physicsMeshXpbdTask",
    "HO_OmniNode_physicsMeshXpbdSolver",
    "HO_OmniNode_physicsMeshXpbdDebugDraw",
    "HO_OmniNode_customExampleScale",
}
current_node_ids = {
    node_class.bl_idname
    for node_class in node_register._registry.node_classes
}
assert required_node_ids <= current_node_ids
assert "HO_OmniNode_meshPhysicsXPBD" not in current_node_ids
assert "HO_OmniNode_meshPhysicsXPBDCpp" not in current_node_ids
assert len(current_node_ids) == len(node_register._registry.node_classes)


# 禁用的辅助模块与非法声明必须有明确行为。
disabled_module = types.ModuleType("test_disabled_function_module")
disabled_module.OMNI_NODE_REGISTRATION = {"enabled": False}
assert node_register._normalize_function_module(disabled_module) is None

missing_module = types.ModuleType("test_missing_function_module")
assert_raises(
    ValueError,
    lambda: node_register._normalize_function_module(missing_module),
    "缺少 OMNI_NODE_REGISTRATION",
)

invalid_path_module = types.ModuleType("test_invalid_path_function_module")
invalid_path_module.OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "自定义", "order": 1000},
    "menu_path": "角色/面部",
}
assert_raises(
    ValueError,
    lambda: node_register._normalize_function_module(invalid_path_module),
    "menu_path 必须是列表或元组",
)


# 新快照完整构建成功前，不得替换当前可用注册表。
registry_before_failure = node_register._registry
classes_before_failure = registry_before_failure.node_classes
original_snapshot_builder = node_register._build_registry_snapshot


def fail_snapshot_build():
    raise ValueError("预期的快照构建失败")


node_register._build_registry_snapshot = fail_snapshot_build
try:
    assert_raises(ValueError, node_register._rebuild_registry, "预期的快照构建失败")
finally:
    node_register._build_registry_snapshot = original_snapshot_builder
assert node_register._registry is registry_before_failure
assert node_register._registry.node_classes is classes_before_failure


# 只发现当前层文件；物理子目录不参与注册，UI 仍可任意嵌套。
temporary_package_name = "omninode_test_custom_functions"
with tempfile.TemporaryDirectory() as temporary_directory:
    temporary_function_directory = Path(temporary_directory)
    nested_directory = temporary_function_directory / "Ignored"
    nested_directory.mkdir()
    (nested_directory / "Nested.py").write_text(
        "raise AssertionError('不应导入子目录模块')\n",
        encoding="utf-8",
    )
    (temporary_function_directory / "Eyes.py").write_text(
        """OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "自定义", "order": 1000},
    "menu_path": ("角色", "面部", "眼睛"),
    "order": 10,
}

from HoTools.OmniNode.FunctionNodeCore import omni

@omni(enable=True, bl_label="自定义眼睛")
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
        temporary_registrations = node_register._discover_function_modules(
            function_directory=temporary_function_directory,
            package=temporary_package_name,
        )
        assert len(temporary_registrations) == 1
        temporary_registration = temporary_registrations[0]
        assert temporary_registration.source_path == "Eyes.py"
        assert temporary_registration.menu_path == ("角色", "面部", "眼睛")
        assert [node.bl_idname for node in temporary_registration.node_classes] == [
            "HO_OmniNode_customEyes"
        ]
        assert f"{temporary_package_name}.Ignored.Nested" not in sys.modules

        (temporary_function_directory / "Conflict.py").write_text(
            """OMNI_NODE_REGISTRATION = {
    "category": {"id": "CUSTOM", "label": "冲突分类", "order": 1000},
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
            lambda: node_register._discover_function_modules(
                function_directory=temporary_function_directory,
                package=temporary_package_name,
            ),
            "label/order 必须一致",
        )
    finally:
        for module_name in tuple(sys.modules):
            if module_name == temporary_package_name or module_name.startswith(
                temporary_package_name + "."
            ):
                del sys.modules[module_name]


# 大型扩展只需在一级目录声明注册文件；详细分类与嵌套菜单由扩展自行提供。
temporary_extension_package = "omninode_test_large_extensions"
with tempfile.TemporaryDirectory() as temporary_directory:
    temporary_omninode_directory = Path(temporary_directory)
    extension_directory = temporary_omninode_directory / "LargeFeature"
    extension_directory.mkdir()
    ignored_directory = extension_directory / "Ignored"
    ignored_directory.mkdir()
    (ignored_directory / "omninode_registration.py").write_text(
        "raise AssertionError('不应扫描扩展的子目录')\n",
        encoding="utf-8",
    )
    (extension_directory / "omninode_registration.py").write_text(
        """from HoTools.OmniNode.OmniNodeRegister import (
    OmniNodeCategorySpec,
    OmniNodeExtensionSpec,
    OmniNodeMenuSpec,
)

class RootNode:
    bl_idname = "HO_Test_LargeFeatureRoot"

class NestedNode:
    bl_idname = "HO_Test_LargeFeatureNested"

def build_omninode_registration():
    return OmniNodeExtensionSpec(
        identifier="LargeFeature",
        order=50,
        node_classes=(RootNode, NestedNode),
        categories=(
            OmniNodeCategorySpec(
                identifier="LARGE_FEATURE",
                label="大型扩展",
                items=(
                    RootNode,
                    OmniNodeMenuSpec(
                        identifier="NODE_MT_OMNI_LARGE_TOOLS",
                        label="工具",
                        items=(
                            OmniNodeMenuSpec(
                                identifier="NODE_MT_OMNI_LARGE_NESTED",
                                label="嵌套分类",
                                items=(NestedNode,),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
""",
        encoding="utf-8",
    )
    temporary_package = types.ModuleType(temporary_extension_package)
    temporary_package.__path__ = [str(temporary_omninode_directory)]
    temporary_package.__package__ = temporary_extension_package
    sys.modules[temporary_extension_package] = temporary_package
    try:
        extensions = node_register._discover_omninode_extensions(
            omni_node_directory=temporary_omninode_directory,
            package=temporary_extension_package,
        )
        assert [extension.identifier for extension in extensions] == [
            "LargeFeature"
        ]
        extension_nodes, extension_categories, extension_menus = (
            node_register._build_extension_categories(extensions)
        )
        assert [node.bl_idname for node in extension_nodes] == [
            "HO_Test_LargeFeatureRoot",
            "HO_Test_LargeFeatureNested",
        ]
        assert [category.identifier for category in extension_categories] == [
            "LARGE_FEATURE"
        ]
        assert [menu.bl_idname for menu in extension_menus] == [
            "NODE_MT_OMNI_LARGE_NESTED",
            "NODE_MT_OMNI_LARGE_TOOLS",
        ]
        assert not any(
            module_name.endswith("Ignored.omninode_registration")
            for module_name in sys.modules
        )
    finally:
        for module_name in tuple(sys.modules):
            if module_name == temporary_extension_package or module_name.startswith(
                temporary_extension_package + "."
            ):
                del sys.modules[module_name]


# 合成声明覆盖顶层节点与任意深度嵌套菜单的混排。
def fake_node_class(name):
    return type(name, (), {"bl_idname": f"HO_Test_{name}"})


def fake_registration(module_name, menu_path, order, *node_names):
    return node_register.FunctionModuleSpec(
        module_name=module_name,
        source_path=f"Custom/{module_name.rsplit('.', 1)[-1]}.py",
        category_id="CUSTOM",
        category_label="自定义",
        category_order=1000,
        menu_path=menu_path,
        module_order=order,
        node_classes=tuple(fake_node_class(name) for name in node_names),
    )


synthetic_registrations = (
    fake_registration("custom.root", (), 0, "Root"),
    fake_registration("custom.eyes", ("角色", "面部", "眼睛"), 10, "Eyes"),
    fake_registration("custom.mouth", ("角色", "面部", "嘴部"), 20, "Mouth"),
    fake_registration("custom.rig", ("角色", "绑定"), 30, "Rig"),
)
category_specs = node_register._build_function_category_specs(
    synthetic_registrations
)
assert len(category_specs) == 1
custom_root = category_specs[0].root
assert [node.bl_idname for _key, node in custom_root.nodes] == ["HO_Test_Root"]
characters = custom_root.children["角色"]
face = characters.children["面部"]
assert set(face.children) == {"眼睛", "嘴部"}
assert "绑定" in characters.children

synthetic_categories, synthetic_menu_classes = (
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
    "OmniNode bl_idname 重复",
)


for cycle in range(2):
    OmniNode.register()
    tree = bpy.data.node_groups.new(
        f"OmniNodeFunctionRegistration{cycle}",
        "OmniNodeTree",
    )
    for node_id in sorted(required_node_ids):
        node = tree.nodes.new(node_id)
        assert node.bl_idname == node_id
    bpy.data.node_groups.remove(tree)
    OmniNode.unregister()
    assert not node_register._registered_node_classes
    assert not node_register._registered_menu_classes

print("OmniNode 函数模块注册测试：通过")
