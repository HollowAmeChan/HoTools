from dataclasses import dataclass, field
import hashlib
import importlib
from pathlib import Path
import re
from types import ModuleType

import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem, NodeItemCustom

from . import FunctionNodeCore
from .GraphNode import CLS_GRAPH
from .OmniNodeTree import TREE_ID
from .PhysicsWorld import nodes as physics_world_nodes
from .PhysicsWorld import registry as physics_world_registry


# 函数节点模块声明与发现
REGISTRATION_ATTRIBUTE = "OMNI_NODE_REGISTRATION"
_MODULE_KEYS = {"enabled", "category", "menu_path", "order"}
_CATEGORY_KEYS = {"id", "label", "order"}
_CATEGORY_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_FUNCTION_NODE_ROOTS = ("Function", "Custom")


@dataclass(frozen=True)
class FunctionModuleSpec:
    module_name: str
    source_path: str
    category_id: str
    category_label: str
    category_order: int
    menu_path: tuple[str, ...]
    module_order: int
    node_classes: tuple[type, ...]

    @property
    def sort_key(self) -> tuple[int, str]:
        return self.module_order, self.module_name.casefold()


def _unexpected_keys(mapping, allowed_keys):
    return sorted(str(key) for key in set(mapping) - allowed_keys)


def _require_order(value, field_name: str, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{source}: {field_name} 必须是整数")
    return value


def _normalize_function_module(
    module: ModuleType,
    *,
    source_path: str | None = None,
) -> FunctionModuleSpec | None:
    source = source_path or getattr(module, "__name__", "<未知模块>")
    missing = object()
    declaration = getattr(module, REGISTRATION_ATTRIBUTE, missing)
    if declaration is missing:
        raise ValueError(
            f"{source}: 缺少 {REGISTRATION_ATTRIBUTE}；"
            "非节点辅助模块请声明 {'enabled': False}"
        )
    if not isinstance(declaration, dict):
        raise ValueError(f"{source}: {REGISTRATION_ATTRIBUTE} 必须是字典")

    unexpected = _unexpected_keys(declaration, _MODULE_KEYS)
    if unexpected:
        raise ValueError(f"{source}: 不支持的注册字段：{unexpected}")

    enabled = declaration.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"{source}: enabled 必须是布尔值")
    if not enabled:
        return None

    category = declaration.get("category")
    if not isinstance(category, dict):
        raise ValueError(f"{source}: category 必须是字典")
    unexpected = _unexpected_keys(category, _CATEGORY_KEYS)
    if unexpected:
        raise ValueError(f"{source}: 不支持的分类字段：{unexpected}")

    raw_category_id = category.get("id")
    if not isinstance(raw_category_id, str):
        raise ValueError(f"{source}: category.id 必须是字符串")
    category_id = raw_category_id.strip()
    if not _CATEGORY_ID_PATTERN.fullmatch(category_id):
        raise ValueError(
            f"{source}: category.id 必须以字母开头，且只能包含 "
            "ASCII 字母、数字和下划线"
        )
    category_id = category_id.upper()

    raw_category_label = category.get("label")
    if not isinstance(raw_category_label, str):
        raise ValueError(f"{source}: category.label 必须是字符串")
    category_label = raw_category_label.strip()
    if not category_label:
        raise ValueError(f"{source}: category.label 不能为空")
    category_order = _require_order(
        category.get("order", 0), "category.order", source
    )
    module_order = _require_order(declaration.get("order", 0), "order", source)

    raw_menu_path = declaration.get("menu_path", ())
    if not isinstance(raw_menu_path, (list, tuple)):
        raise ValueError(f"{source}: menu_path 必须是列表或元组")
    if any(not isinstance(label, str) for label in raw_menu_path):
        raise ValueError(f"{source}: menu_path 中的名称必须是字符串")
    menu_path = tuple(label.strip() for label in raw_menu_path)
    if any(not label for label in menu_path):
        raise ValueError(f"{source}: menu_path 中的名称不能为空")

    node_classes = tuple(FunctionNodeCore.loadRegisterFuncNodes(module))
    if not node_classes:
        raise ValueError(
            f"{source}: 已启用的注册声明中没有 @omni(enable=True) 节点"
        )

    return FunctionModuleSpec(
        module_name=module.__name__,
        source_path=source,
        category_id=category_id,
        category_label=category_label,
        category_order=category_order,
        menu_path=menu_path,
        module_order=module_order,
        node_classes=node_classes,
    )


def _module_name_for_path(path: Path, package: str) -> str:
    module_token = path.stem
    if not module_token.isidentifier():
        raise ValueError(f"{path.name}: 文件名必须是合法的 Python 模块名")
    return f"{package}.{module_token}"


def _validate_and_sort_function_modules(module_specs):
    category_contracts: dict[str, tuple[str, int, str]] = {}
    for module_spec in module_specs:
        contract = (
            module_spec.category_label,
            module_spec.category_order,
            module_spec.source_path,
        )
        previous = category_contracts.get(module_spec.category_id)
        if previous is not None and previous[:2] != contract[:2]:
            raise ValueError(
                f"{module_spec.source_path}: 分类 "
                f"{module_spec.category_id!r} 与 {previous[2]} 冲突，"
                "同一分类的 label/order 必须一致"
            )
        category_contracts[module_spec.category_id] = contract

    return tuple(sorted(
        module_specs,
        key=lambda module_spec: (
            module_spec.category_order,
            module_spec.category_id,
            *module_spec.sort_key,
        ),
    ))


def _discover_function_modules(
    *,
    function_directory: Path | None = None,
    package: str | None = None,
    relative_prefix: str = "",
) -> tuple[FunctionModuleSpec, ...]:
    function_directory = (
        Path(function_directory)
        if function_directory is not None
        else Path(__file__).resolve().with_name("Function")
    )
    package = package or f"{__package__}.Function"
    if not function_directory.is_dir():
        raise FileNotFoundError(
            f"OmniNode 模块目录不存在：{function_directory}"
        )

    paths = sorted(
        (
            path
            for path in function_directory.glob("*.py")
            if path.name != "__init__.py"
        ),
        key=lambda path: path.name.casefold(),
    )
    relative_prefix = relative_prefix.strip("/")

    module_specs = []
    for path in paths:
        relative_path = path.relative_to(function_directory).as_posix()
        source_path = (
            f"{relative_prefix}/{relative_path}"
            if relative_prefix
            else relative_path
        )
        module_name = _module_name_for_path(path, package)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(
                f"导入 OmniNode 函数模块 {source_path} 失败：{exc}"
            ) from exc

        module_spec = _normalize_function_module(
            module,
            source_path=source_path,
        )
        if module_spec is not None:
            module_specs.append(module_spec)

    return _validate_and_sort_function_modules(module_specs)


def _discover_all_function_modules() -> tuple[FunctionModuleSpec, ...]:
    omni_node_directory = Path(__file__).resolve().parent
    module_specs = []
    for directory_name in _FUNCTION_NODE_ROOTS:
        module_specs.extend(_discover_function_modules(
            function_directory=omni_node_directory / directory_name,
            package=f"{__package__}.{directory_name}",
            relative_prefix=directory_name,
        ))
    return _validate_and_sort_function_modules(module_specs)


# 节点添加菜单构建
class OmniNodeCategory(NodeCategory):
    @classmethod
    def poll(cls, context):
        return True


@dataclass
class _MenuBranch:
    label: str = ""
    path: tuple[str, ...] = ()
    nodes: list[tuple[tuple, type]] = field(default_factory=list)
    children: dict[str, "_MenuBranch"] = field(default_factory=dict)
    sort_key: tuple[int, str] | None = None


@dataclass
class _FunctionCategorySpec:
    identifier: str
    label: str
    order: int
    root: _MenuBranch = field(default_factory=_MenuBranch)


_RESERVED_CATEGORY_IDS = {
    "GRAPH",
    "PHYSICS_WORLD",
    "PHYSICS_SOLVER",
    "PHYSICS_WORLD_DEBUG",
}


def _filter_nodes_by_label_prefix(node_classes, *prefixes):
    return tuple(
        node_class
        for node_class in node_classes
        if any(node_class.bl_label.startswith(prefix) for prefix in prefixes)
    )


def _node_items(node_classes):
    return [NodeItem(node_class.bl_idname) for node_class in node_classes]


def _make_menu_item(menu_id):
    def draw(_item, layout, _context):
        layout.menu(menu_id)

    return NodeItemCustom(draw=draw)


def _make_menu_class(menu_id, label, node_items):
    node_items = tuple(node_items)

    def draw(self, context):
        column = self.layout.column(align=True)
        for item in node_items:
            item.draw(item, column, context)

    return type(menu_id, (bpy.types.Menu,), {
        "__module__": __name__,
        "bl_idname": menu_id,
        "bl_label": label,
        "draw": draw,
    })


def _nested_menu_id(category_id, menu_path):
    identity = "/".join((category_id, *menu_path))
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12].upper()
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", menu_path[-1]).strip("_").upper()
    slug = (slug or "MENU")[:16]
    category_token = category_id[:16]
    return f"NODE_MT_OMNI_{category_token}_{slug}_{digest}"


def _build_function_category_specs(
    module_specs,
) -> tuple[_FunctionCategorySpec, ...]:
    categories: dict[str, _FunctionCategorySpec] = {}
    for module_spec in module_specs:
        if module_spec.category_id in _RESERVED_CATEGORY_IDS:
            raise ValueError(
                f"{module_spec.source_path}: 分类 "
                f"{module_spec.category_id!r} 是 OmniNode 保留分类"
            )

        category = categories.get(module_spec.category_id)
        if category is None:
            category = _FunctionCategorySpec(
                identifier=module_spec.category_id,
                label=module_spec.category_label,
                order=module_spec.category_order,
            )
            categories[module_spec.category_id] = category

        branch = category.root
        traversed_path: list[str] = []
        for label in module_spec.menu_path:
            traversed_path.append(label)
            child = branch.children.get(label)
            if child is None:
                child = _MenuBranch(label=label, path=tuple(traversed_path))
                branch.children[label] = child
            if child.sort_key is None or module_spec.sort_key < child.sort_key:
                child.sort_key = module_spec.sort_key
            branch = child

        for index, node_class in enumerate(module_spec.node_classes):
            branch.nodes.append((
                (*module_spec.sort_key, 1, index),
                node_class,
            ))

    return tuple(sorted(
        categories.values(),
        key=lambda category: (category.order, category.identifier),
    ))


def _build_menu_items(
    category_id: str,
    branch: _MenuBranch,
    menu_classes: list[type],
) -> list:
    entries = [
        (sort_key, NodeItem(node_class.bl_idname))
        for sort_key, node_class in branch.nodes
    ]
    for child in branch.children.values():
        child_items = _build_menu_items(category_id, child, menu_classes)
        menu_id = _nested_menu_id(category_id, child.path)
        menu_classes.append(_make_menu_class(menu_id, child.label, child_items))
        child_order, child_module = child.sort_key
        entries.append((
            (child_order, child_module, 0, child.label.casefold()),
            _make_menu_item(menu_id),
        ))
    return [item for _sort_key, item in sorted(entries, key=lambda entry: entry[0])]


def _build_function_categories(
    module_specs,
) -> tuple[list[OmniNodeCategory], list[type]]:
    category_specs = _build_function_category_specs(module_specs)
    menu_classes = []
    categories = []
    for category in category_specs:
        items = _build_menu_items(
            category.identifier,
            category.root,
            menu_classes,
        )
        categories.append(OmniNodeCategory(
            category.identifier,
            category.label,
            items=items,
        ))
    menu_ids = [menu_class.bl_idname for menu_class in menu_classes]
    if len(menu_ids) != len(set(menu_ids)):
        raise ValueError("函数节点的嵌套菜单标识符必须唯一")
    return categories, menu_classes


# PhysicsWorld 节点来源
_PHYSICS_LIFECYCLE_LABEL_PREFIXES = (
    "物理对象",
    "物理世界-帧",
    "物理写回",
    "物理烘焙",
    "清除物理Bake",
)
_PHYSICS_DEBUG_LABEL_PREFIXES = (
    "物理世界-调试",
    "物理世界-结果",
    "物理世界-可视化",
)


@dataclass(frozen=True)
class _PhysicsSolverGroup:
    domain: str
    solver_id: str
    menu_name: str
    menu_id: str
    node_classes: tuple[type, ...]


def _solver_menu_id(solver_id):
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(solver_id)).strip("_").upper()
    if not token:
        raise ValueError("solver_id 不能生成空菜单标识符")
    return f"NODE_MT_OMNINODE_SOLVER_{token}"


def _load_physics_world_solver_groups() -> tuple[_PhysicsSolverGroup, ...]:
    groups = []
    menu_ids = set()
    for entry in physics_world_registry.iter_solver_node_groups():
        nodes = []
        for module_entry in entry["modules"]:
            nodes.extend(FunctionNodeCore.loadRegisterFuncNodes(module_entry["module"]))
        if not nodes:
            continue
        menu_id = _solver_menu_id(entry["solver_id"])
        if menu_id in menu_ids:
            raise ValueError(f"解算器菜单标识符重复：{menu_id}")
        menu_ids.add(menu_id)
        groups.append(_PhysicsSolverGroup(
            domain=entry["domain"],
            solver_id=entry["solver_id"],
            menu_name=entry["menu_name"],
            menu_id=menu_id,
            node_classes=tuple(nodes),
        ))
    return tuple(groups)


def _validate_unique_node_ids(node_classes):
    seen = {}
    for node_class in node_classes:
        node_id = node_class.bl_idname
        previous = seen.get(node_id)
        if previous is not None:
            previous_func = getattr(previous, "_func", None)
            current_func = getattr(node_class, "_func", None)
            previous_source = getattr(previous_func, "__module__", previous.__module__)
            current_source = getattr(current_func, "__module__", node_class.__module__)
            raise ValueError(
                f"OmniNode bl_idname 重复 {node_id!r}："
                f"{previous_source} 与 {current_source}"
            )
        seen[node_id] = node_class


# 注册快照与 Blender 生命周期
@dataclass(frozen=True)
class _RegistrySnapshot:
    function_modules: tuple[FunctionModuleSpec, ...] = ()
    physics_world_node_classes: tuple[type, ...] = ()
    physics_solver_groups: tuple[_PhysicsSolverGroup, ...] = ()
    physics_solver_menu_classes: tuple[type, ...] = ()
    physics_lifecycle_node_classes: tuple[type, ...] = ()
    physics_debug_node_classes: tuple[type, ...] = ()
    node_classes: tuple[type, ...] = ()
    node_categories: tuple[OmniNodeCategory, ...] = ()
    menu_classes: tuple[type, ...] = ()


_registry = _RegistrySnapshot()


def _build_registry_snapshot() -> _RegistrySnapshot:
    function_modules = _discover_all_function_modules()
    function_categories, function_menu_classes = _build_function_categories(
        function_modules
    )
    function_node_classes = tuple(
        node_class
        for module_spec in function_modules
        for node_class in module_spec.node_classes
    )

    graph_node_classes = tuple(CLS_GRAPH)
    physics_world_node_classes = tuple(
        FunctionNodeCore.loadRegisterFuncNodes(physics_world_nodes)
    )
    physics_solver_groups = _load_physics_world_solver_groups()
    physics_solver_node_classes = tuple(
        node_class
        for group in physics_solver_groups
        for node_class in group.node_classes
    )
    physics_solver_menu_classes = tuple(
        _make_menu_class(
            group.menu_id,
            group.menu_name,
            _node_items(group.node_classes),
        )
        for group in physics_solver_groups
    )

    node_classes = (
        graph_node_classes
        + function_node_classes
        + physics_world_node_classes
        + physics_solver_node_classes
    )
    _validate_unique_node_ids(node_classes)

    physics_lifecycle_node_classes = _filter_nodes_by_label_prefix(
        physics_world_node_classes,
        *_PHYSICS_LIFECYCLE_LABEL_PREFIXES,
    )
    physics_debug_node_classes = _filter_nodes_by_label_prefix(
        physics_world_node_classes,
        *_PHYSICS_DEBUG_LABEL_PREFIXES,
    )
    solver_items = [
        _make_menu_item(group.menu_id)
        for group in physics_solver_groups
    ]

    node_categories = (
        OmniNodeCategory(
            "GRAPH",
            "图结构",
            items=_node_items(graph_node_classes),
        ),
        *function_categories,
        OmniNodeCategory(
            "PHYSICS_WORLD",
            "物理世界",
            items=_node_items(physics_lifecycle_node_classes),
        ),
        OmniNodeCategory("PHYSICS_SOLVER", "解算器", items=solver_items),
        OmniNodeCategory(
            "PHYSICS_WORLD_DEBUG",
            "物理世界调试",
            items=_node_items(physics_debug_node_classes),
        ),
    )

    return _RegistrySnapshot(
        function_modules=function_modules,
        physics_world_node_classes=physics_world_node_classes,
        physics_solver_groups=physics_solver_groups,
        physics_solver_menu_classes=physics_solver_menu_classes,
        physics_lifecycle_node_classes=physics_lifecycle_node_classes,
        physics_debug_node_classes=physics_debug_node_classes,
        node_classes=node_classes,
        node_categories=node_categories,
        menu_classes=tuple(function_menu_classes) + physics_solver_menu_classes,
    )


def _rebuild_registry() -> _RegistrySnapshot:
    global _registry
    _registry = _build_registry_snapshot()
    return _registry


_registered_node_classes = []
_registered_menu_classes = []
_node_categories_registered = False


def _rollback_registration():
    global _node_categories_registered
    if _node_categories_registered:
        nodeitems_utils.unregister_node_categories(TREE_ID)
        _node_categories_registered = False
    for menu_class in reversed(_registered_menu_classes):
        bpy.utils.unregister_class(menu_class)
    _registered_menu_classes.clear()
    for node_class in reversed(_registered_node_classes):
        bpy.utils.unregister_class(node_class)
    _registered_node_classes.clear()


def register():
    global _node_categories_registered
    if _node_categories_registered:
        return
    registry = _rebuild_registry()
    try:
        for node_class in registry.node_classes:
            bpy.utils.register_class(node_class)
            _registered_node_classes.append(node_class)
        for menu_class in registry.menu_classes:
            bpy.utils.register_class(menu_class)
            _registered_menu_classes.append(menu_class)
        nodeitems_utils.register_node_categories(TREE_ID, registry.node_categories)
        _node_categories_registered = True
    except Exception:
        _rollback_registration()
        raise


def unregister():
    _rollback_registration()
