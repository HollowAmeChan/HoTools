from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import re
from types import ModuleType

from . import FunctionNodeCore


REGISTRATION_ATTRIBUTE = "OMNI_NODE_REGISTRATION"
_MODULE_KEYS = {"enabled", "category", "menu_path", "order"}
_CATEGORY_KEYS = {"id", "label", "order"}
_CATEGORY_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class FunctionModuleRegistration:
    module: ModuleType
    module_name: str
    relative_path: str
    category_id: str
    category_label: str
    category_order: int
    menu_path: tuple[str, ...]
    order: int
    node_classes: tuple[type, ...]


def _unexpected_keys(mapping, allowed_keys):
    return sorted(str(key) for key in set(mapping) - allowed_keys)


def _require_order(value, field_name: str, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{source}: {field_name} 必须是整数")
    return value


def normalize_function_registration(
    module: ModuleType,
    *,
    relative_path: str | None = None,
) -> FunctionModuleRegistration | None:
    source = relative_path or getattr(module, "__name__", "<未知模块>")
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
    order = _require_order(declaration.get("order", 0), "order", source)

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

    return FunctionModuleRegistration(
        module=module,
        module_name=module.__name__,
        relative_path=source,
        category_id=category_id,
        category_label=category_label,
        category_order=category_order,
        menu_path=menu_path,
        order=order,
        node_classes=node_classes,
    )


def _module_name_for_path(path: Path, package: str) -> str:
    module_token = path.stem
    if not module_token.isidentifier():
        raise ValueError(
            f"{path.name}: 文件名必须是合法的 Python 模块名"
        )
    return f"{package}.{module_token}"


def _validate_and_sort_registrations(registrations):
    category_contracts: dict[str, tuple[str, int, str]] = {}
    for registration in registrations:
        contract = (
            registration.category_label,
            registration.category_order,
            registration.relative_path,
        )
        previous = category_contracts.get(registration.category_id)
        if previous is not None and previous[:2] != contract[:2]:
            raise ValueError(
                f"{registration.relative_path}: 分类 "
                f"{registration.category_id!r} 与 {previous[2]} 冲突，"
                "同一分类的 label/order 必须一致"
            )
        category_contracts[registration.category_id] = contract

    return tuple(sorted(
        registrations,
        key=lambda entry: (
            entry.category_order,
            entry.category_id,
            entry.order,
            entry.module_name.casefold(),
        ),
    ))


def discover_function_modules(
    *,
    function_directory: Path | None = None,
    package: str | None = None,
    relative_prefix: str = "",
) -> tuple[FunctionModuleRegistration, ...]:
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

    registrations = []
    for path in paths:
        relative_path = path.relative_to(function_directory).as_posix()
        source_path = (
            f"{relative_prefix.strip('/')}/{relative_path}"
            if relative_prefix.strip("/")
            else relative_path
        )
        module_name = _module_name_for_path(path, package)
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeError(
                f"导入 OmniNode 函数模块 {source_path} 失败：{exc}"
            ) from exc

        registration = normalize_function_registration(
            module,
            relative_path=source_path,
        )
        if registration is None:
            continue
        registrations.append(registration)

    return _validate_and_sort_registrations(registrations)


def discover_node_modules() -> tuple[FunctionModuleRegistration, ...]:
    omni_node_directory = Path(__file__).resolve().parent
    registrations = []
    for directory_name in ("Function", "Custom"):
        registrations.extend(discover_function_modules(
            function_directory=omni_node_directory / directory_name,
            package=f"{__package__}.{directory_name}",
            relative_prefix=directory_name,
        ))
    return _validate_and_sort_registrations(registrations)
