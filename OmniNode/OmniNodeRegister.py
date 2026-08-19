from __future__ import annotations

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


# 大型节点扩展声明与发现
_EXTENSION_REGISTRATION_FILENAME = "omninode_registration.py"
_EXTENSION_REGISTRATION_FACTORY = "build_omninode_registration"


@dataclass(frozen=True)
class OmniNodeMenuSpec:
    identifier: str
    label: str
    items: tuple[type | OmniNodeMenuSpec, ...]


@dataclass(frozen=True)
class OmniNodeCategorySpec:
    identifier: str
    label: str
    items: tuple[type | OmniNodeMenuSpec, ...]


@dataclass(frozen=True)
class OmniNodeExtensionSpec:
    identifier: str
    order: int
    node_classes: tuple[type, ...]
    categories: tuple[OmniNodeCategorySpec, ...]


def _discover_omninode_extensions(
    *,
    omni_node_directory: Path | None = None,
    package: str | None = None,
) -> tuple[OmniNodeExtensionSpec, ...]:
    omni_node_directory = (
        Path(omni_node_directory)
        if omni_node_directory is not None
        else Path(__file__).resolve().parent
    )
    package = package or __package__
    registration_files = sorted(
        omni_node_directory.glob(f"*/{_EXTENSION_REGISTRATION_FILENAME}"),
        key=lambda path: path.parent.name.casefold(),
    )

    extensions = []
    extension_sources: dict[str, str] = {}
    for path in registration_files:
        directory_name = path.parent.name
        if not directory_name.isidentifier():
            raise ValueError(
                f"{path}: 扩展目录名必须是合法的 Python 模块名"
            )
        module_name = f"{package}.{directory_name}.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(f"导入 OmniNode 扩展 {module_name} 失败：{exc}") from exc

        factory = getattr(module, _EXTENSION_REGISTRATION_FACTORY, None)
        if not callable(factory):
            raise ValueError(
                f"{path}: 必须定义可调用的 {_EXTENSION_REGISTRATION_FACTORY}()"
            )
        extension = factory()
        if not isinstance(extension, OmniNodeExtensionSpec):
            raise TypeError(
                f"{path}: {_EXTENSION_REGISTRATION_FACTORY}() "
                "必须返回 OmniNodeExtensionSpec"
            )
        if (
            not isinstance(extension.identifier, str)
            or not extension.identifier.strip()
        ):
            raise ValueError(f"{path}: 扩展 identifier 不能为空")
        _require_order(extension.order, "扩展 order", str(path))

        previous_source = extension_sources.get(extension.identifier)
        if previous_source is not None:
            raise ValueError(
                f"{path}: 扩展 identifier {extension.identifier!r} "
                f"与 {previous_source} 重复"
            )
        extension_sources[extension.identifier] = str(path)
        extensions.append(extension)

    return tuple(sorted(
        extensions,
        key=lambda extension: (extension.order, extension.identifier.casefold()),
    ))


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


_RESERVED_CATEGORY_IDS = {"GRAPH"}


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


def _build_extension_items(
    extension: OmniNodeExtensionSpec,
    items,
    node_class_set: set[type],
    menu_classes: list[type],
    menu_ids: set[str],
):
    built_items = []
    for item in items:
        if isinstance(item, type):
            if item not in node_class_set:
                raise ValueError(
                    f"扩展 {extension.identifier!r} 的分类引用了未声明节点 "
                    f"{item.__module__}.{item.__name__}"
                )
            built_items.append(NodeItem(item.bl_idname))
            continue

        if not isinstance(item, OmniNodeMenuSpec):
            raise TypeError(
                f"扩展 {extension.identifier!r} 的分类项目必须是节点类或 "
                "OmniNodeMenuSpec"
            )
        if (
            not isinstance(item.identifier, str)
            or not _CATEGORY_ID_PATTERN.fullmatch(item.identifier)
        ):
            raise ValueError(
                f"扩展 {extension.identifier!r} 的菜单 ID "
                f"{item.identifier!r} 无效"
            )
        if not isinstance(item.label, str) or not item.label.strip():
            raise ValueError(f"扩展 {extension.identifier!r} 的菜单名称不能为空")
        if item.identifier in menu_ids:
            raise ValueError(f"OmniNode 菜单标识符重复：{item.identifier}")
        menu_ids.add(item.identifier)

        child_items = _build_extension_items(
            extension,
            item.items,
            node_class_set,
            menu_classes,
            menu_ids,
        )
        menu_classes.append(
            _make_menu_class(item.identifier, item.label, child_items)
        )
        built_items.append(_make_menu_item(item.identifier))
    return built_items


def _build_extension_categories(extension_specs):
    node_classes = []
    categories = []
    menu_classes = []
    menu_ids: set[str] = set()

    for extension in extension_specs:
        if any(
            not isinstance(node_class, type)
            for node_class in extension.node_classes
        ):
            raise TypeError(
                f"扩展 {extension.identifier!r} 的 node_classes 必须全部是类"
            )
        node_class_set = set(extension.node_classes)
        node_classes.extend(extension.node_classes)

        for category in extension.categories:
            if not isinstance(category, OmniNodeCategorySpec):
                raise TypeError(
                    f"扩展 {extension.identifier!r} 的 categories 必须全部是 "
                    "OmniNodeCategorySpec"
                )
            if (
                not isinstance(category.identifier, str)
                or not _CATEGORY_ID_PATTERN.fullmatch(category.identifier)
            ):
                raise ValueError(
                    f"扩展 {extension.identifier!r} 的分类 ID "
                    f"{category.identifier!r} 无效"
                )
            if (
                not isinstance(category.label, str)
                or not category.label.strip()
            ):
                raise ValueError(
                    f"扩展 {extension.identifier!r} 的分类名称不能为空"
                )
            items = _build_extension_items(
                extension,
                category.items,
                node_class_set,
                menu_classes,
                menu_ids,
            )
            categories.append(OmniNodeCategory(
                category.identifier,
                category.label,
                items=items,
            ))

    return tuple(node_classes), tuple(categories), tuple(menu_classes)


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


def _validate_unique_category_ids(node_categories):
    seen = set()
    for category in node_categories:
        if category.identifier in seen:
            raise ValueError(
                f"OmniNode 分类标识符重复：{category.identifier}"
            )
        seen.add(category.identifier)


def _validate_unique_menu_ids(menu_classes):
    seen = set()
    for menu_class in menu_classes:
        if menu_class.bl_idname in seen:
            raise ValueError(
                f"OmniNode 菜单标识符重复：{menu_class.bl_idname}"
            )
        seen.add(menu_class.bl_idname)


# 注册快照与 Blender 生命周期
@dataclass(frozen=True)
class _RegistrySnapshot:
    function_modules: tuple[FunctionModuleSpec, ...] = ()
    extensions: tuple[OmniNodeExtensionSpec, ...] = ()
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

    extensions = _discover_omninode_extensions()
    (
        extension_node_classes,
        extension_categories,
        extension_menu_classes,
    ) = _build_extension_categories(extensions)

    graph_node_classes = tuple(CLS_GRAPH)
    node_classes = (
        graph_node_classes
        + function_node_classes
        + extension_node_classes
    )
    _validate_unique_node_ids(node_classes)

    node_categories = (
        OmniNodeCategory(
            "GRAPH",
            "图结构",
            items=_node_items(graph_node_classes),
        ),
        *function_categories,
        *extension_categories,
    )
    _validate_unique_category_ids(node_categories)

    menu_classes = tuple(function_menu_classes) + extension_menu_classes
    _validate_unique_menu_ids(menu_classes)

    return _RegistrySnapshot(
        function_modules=function_modules,
        extensions=extensions,
        node_classes=node_classes,
        node_categories=node_categories,
        menu_classes=menu_classes,
    )


def _rebuild_registry() -> _RegistrySnapshot:
    global _registry
    _registry = _build_registry_snapshot()
    return _registry


_registered_node_classes = []
_registered_menu_classes = []
_node_categories_registered = False


def iter_registered_node_classes():
    """返回当前已经注册的 OmniNode 节点类，供其他模块读取目录。"""
    return tuple(_registered_node_classes)


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
