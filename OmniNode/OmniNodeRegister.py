from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib
import json
from pathlib import Path
import re
import sys
from types import ModuleType
import types

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


# 大型节点扩展：声明、清单、发现、隔离加载
#
# 扩展可以以两种形态存在于搜索根下：
#   <root>/<目录名>/omninode_registration.py      就地注册（内置扩展，如 PhysicsWorld）
#   <root>/<目录名>/extension.json + 包目录       清单驱动（外置安装的扩展仓库）
#
# 关键约定：**扩展身份是 identifier，不是目录名**。外置仓库的目录名可能带大写、
# 短横线甚至中文，因此清单用 identifier 声明稳定身份，目录名只用于定位。
_EXTENSION_REGISTRATION_FILENAME = "omninode_registration.py"
_EXTENSION_REGISTRATION_FACTORY = "build_omninode_registration"
_EXTENSION_MANIFEST_FILENAME = "extension.json"


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


# 扩展与父仓之间的 API 契约版本。父仓只在**破坏性**改动时递增主版本，
# 扩展通过 extension.json 的 omninode_api 声明自己支持的区间。
OMNINODE_EXTENSION_API_VERSION = "1.0"

# 内置扩展优先级低于外置清单：同名 identifier 时清单胜出，便于逐步外置。
_SOURCE_PRIORITY = {"builtin": 0, "manifest": 1}



def _user_extension_roots() -> tuple[Path, ...]:
    """Blender 用户目录下的扩展安装位（只读插件库安装时的回退落点）。

    通过 ``bpy.utils.user_resource("EXTENSIONS")`` 解析，因此天然跟随当前
    Blender 版本与 ``--env BLENDER_USER_EXTENSIONS`` 之类的覆盖。
    """
    try:
        base = Path(bpy.utils.user_resource("EXTENSIONS"))
    except Exception:  # noqa: BLE001 - 版本/环境差异时退回默认布局
        base = Path.home() / ".config" / "blender" / "extensions"
    return (base / "HoTools-Omninode",)


def _default_extension_search_roots() -> tuple[Path, ...]:
    """返回扩展搜索根（按优先级）。

    1. OmniNode 包目录本身：内置扩展（如 PhysicsWorld）直接位于其下。
    2. 插件内的 `extensions/`：随包分发或本地安装的扩展。
    3. Blender 用户目录的扩展安装位：插件目录只读时的回退落点。
    """
    omni_node_directory = Path(__file__).resolve().parent
    return (
        omni_node_directory,
        omni_node_directory / "extensions",
        *_user_extension_roots(),
    )


def _ensure_import_root(root: Path) -> bool:
    """把搜索根加入 sys.path，使清单驱动的扩展包可被 import。

    外置扩展解压在任意目录（例如 `extensions/Hotools-Omninode-Physics/`），
    其包名由清单声明，因此必须让该目录本身成为导入根。返回是否本次插入。
    """
    path_text = str(root)
    if path_text in sys.path:
        return False
    sys.path.insert(0, path_text)
    importlib.invalidate_caches()
    return True


def _register_canonical_extension_package(
    directory: Path,
    package_name: str = ".",
) -> str | None:
    """把扩展包以**规范包名** ``HoTools.OmniNode.<包名>`` 注册进 sys.modules。

    为什么需要这一步：扩展可以装在任意目录（插件内 `extensions/` 或 Blender
    用户扩展目录），但它的包内相对导入（本仓库有 700+ 处，如
    ``from ..PropertyCurve import ...``、``from ...native import ...``）是按
    “位于 HoTools.OmniNode 之下”的层级写的。物理位置一变，相对导入的级数就对不上。

    这里直接把该目录登记为规范包，让导入系统认为扩展仍在它原来的位置：

        physics_dir  →  sys.modules["HoTools.OmniNode.PhysicsWorld"]
                        __path__ = [physics_dir]

    于是**无论扩展装在哪儿，包内代码一行都不用改**。`extensions/` 与仓库目录都
    不需要 __init__.py，也不会成为包的一部分。

    返回规范包名；无法确定包目录时返回 None（调用方回退到按物理名导入）。
    """
    if not package_name or package_name == ".":
        return None
    physics_dir = Path(directory) / package_name
    if not physics_dir.is_dir():
        return None
    canonical = f"{__package__}.{_normalize_extension_directory(package_name)}"
    if canonical not in sys.modules:
        module = types.ModuleType(canonical)
        module.__path__ = [str(physics_dir)]
        module.__package__ = canonical
        module.__spec__ = None
        sys.modules[canonical] = module
        parent = sys.modules.get(__package__)
        if parent is not None:
            setattr(parent, _normalize_extension_directory(package_name), module)
        importlib.invalidate_caches()
    return canonical


def _load_module_from_path(module_name: str, path: Path):
    """按文件路径加载模块，并挂到 ``module_name`` 下。

    扩展注册模块可能位于规范包之外（例如仓库根的 `omninode_registration.py`
    与包目录不同级），无法用普通 import 定位，因此这里用 spec_from_file_location。
    """
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法为 {path} 建立模块 spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class OmniNodeExtensionDescriptor:
    """一个扩展的完整描述：静态声明 + 清单元数据 + 加载诊断。

    ``spec`` 为 None 表示该扩展存在但不可用（清单非法、加载失败、API 不兼容、
    被用户禁用）。这类扩展不会中断 OmniNode 注册，只在 UI 中报告 ``error``。
    """

    identifier: str
    order: int
    source: str  # builtin | manifest
    source_path: str
    directory: str
    enabled: bool = True
    spec: OmniNodeExtensionSpec | None = None
    display_name: str = ""
    version: str = ""
    omninode_api: str = ""
    requires_hotools: str = ""
    error: str = ""
    disabled_by_user: bool = False

    @property
    def available(self) -> bool:
        return self.spec is not None

    @property
    def status(self) -> str:
        if self.disabled_by_user:
            return "disabled"
        if self.error:
            return "error"
        return "active"

    def node_classes(self) -> tuple[type, ...]:
        return () if self.spec is None else self.spec.node_classes

    def categories(self) -> tuple[OmniNodeCategorySpec, ...]:
        return () if self.spec is None else self.spec.categories


def _normalize_extension_directory(directory_name: str) -> str:
    """把任意目录名规整成 Python 标识符（``Hotools-Omninode-Physics`` -> 合法名）。

    扩展目录允许带短横线/点/大写；这里只做定位用途的规整，扩展身份仍由
    ``identifier`` 决定，因此目录名变化不会影响被禁用的扩展是否仍被记住。
    """
    token = re.sub(r"[^0-9A-Za-z_]+", "_", directory_name).strip("_")
    if not token:
        token = "extension"
    if token[0].isdigit():
        token = f"ext_{token}"
    return token


def _read_extension_manifest(path: Path) -> tuple[dict, str]:
    """读取 extension.json，返回 (manifest, error)。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"无法读取 extension.json：{exc}"
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return {}, f"extension.json 不是合法 JSON：{exc}"
    if not isinstance(data, dict):
        return {}, "extension.json 顶层必须是对象"
    return data, ""


def _manifest_relative_path(manifest: dict, default: str) -> str:
    """取清单里的包相对路径。

    兼容三种写法：
      * 省略（默认）：注册模块与 extension.json 同目录  → "."
      * package: "PhysicsWorld"  且目录名也叫 PhysicsWorld → "."（避免叠加同名目录）
      * package: "src/physics"  明确的子路径           → 原样使用
    """
    value = (
        manifest.get("package")
        or manifest.get("package_path")
        or manifest.get("extension_package")
    )
    if not value:
        return "."
    text = str(value).strip().replace("\\", "/").strip("/")
    if not text or text in (".", default):
        return "."
    return text


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts[:4])


def _meets_minimum(actual: str, minimum: str) -> bool:
    return _version_tuple(actual) >= _version_tuple(minimum)


def _version_in_range(actual: str, requirement: str) -> bool:
    """支持 ``>=1.0``、``1.0``、``>=1.0,<2``、``~1.0`` 这几种常见写法。"""
    text = str(requirement or "").strip()
    if not text or text == "*":
        return True

    actual_tuple = _version_tuple(actual)
    if not actual_tuple:
        return False

    for token in re.split(r"[,\s]+", text):
        if not token:
            continue
        match = re.match(r"^(>=|<=|==|!=|>|<|~=)?\s*([0-9][0-9.]*)$", token)
        if match is None:
            return False
        operator = match.group(1) or "=="
        bound = _version_tuple(match.group(2))
        if operator == ">=" and not actual_tuple >= bound:
            return False
        if operator == "<=" and not actual_tuple <= bound:
            return False
        if operator == ">" and not actual_tuple > bound:
            return False
        if operator == "<" and not actual_tuple < bound:
            return False
        if operator == "==" and not actual_tuple == bound:
            return False
        if operator == "!=" and actual_tuple == bound:
            return False
        if operator == "~=" and not (
            actual_tuple >= bound and actual_tuple[: len(bound) - 1] == bound[: len(bound) - 1]
        ):
            return False
    return True


def _hotools_version() -> str:
    """读取父仓版本（version_info.json 优先，回退 bl_info）。"""
    try:
        from .. import updater  # 局部导入，避免注册期循环依赖

        metadata = updater.read_version_info()
        version = str(metadata.get("release_tag") or metadata.get("version") or "")
        if version and version != "dev":
            return version
    except Exception:  # noqa: BLE001 - 版本探测失败不应影响扩展加载
        pass
    try:
        import HoTools

        return ".".join(str(part) for part in HoTools.bl_info.get("version", ()))
    except Exception:  # noqa: BLE001
        return ""


def _build_extension_descriptor(
    directory: Path,
    *,
    search_root: Path,
    manifest: dict | None,
    source: str,
    package: str | None = None,
) -> OmniNodeExtensionDescriptor:
    """发现并加载单个扩展目录；任何失败都收敛为 descriptor.error。"""
    directory_name = directory.name
    manifest = manifest or {}
    identifier = str(
        manifest.get("identifier") or manifest.get("id") or directory_name
    ).strip()
    default_package = directory_name
    package_name = _manifest_relative_path(manifest, default_package)
    package_directory = directory / package_name
    registration = package_directory / _EXTENSION_REGISTRATION_FILENAME

    display_name = str(
        manifest.get("display_name") or manifest.get("name") or identifier
    ).strip()
    version = str(manifest.get("version") or "").strip()
    api_requirement = str(manifest.get("omninode_api") or "").strip()
    hotools_requirement = str(manifest.get("requires_hotools") or "").strip()

    def failed(message: str) -> OmniNodeExtensionDescriptor:
        """把失败收敛成带来源信息的描述符，而不是抛异常中断整棵树。"""
        return OmniNodeExtensionDescriptor(
            identifier=identifier,
            order=0,
            source=source,
            source_path=str(directory),
            directory=str(directory),
            display_name=display_name or identifier,
            version=version,
            omninode_api=api_requirement,
            requires_hotools=hotools_requirement,
            error=message,
        )

    if not identifier:
        return failed("扩展标识符为空（extension.json 的 identifier 必须有值）")

    if not registration.is_file():
        try:
            shown = registration.relative_to(search_root).as_posix()
        except ValueError:
            shown = registration.as_posix()
        return failed(f"未找到注册模块：{shown}")

    # 版本契约先于导入检查：不兼容的扩展不必执行任何代码。
    if api_requirement and not _version_in_range(
        OMNINODE_EXTENSION_API_VERSION, api_requirement
    ):
        return failed(
            f"OmniNode 扩展 API 不兼容：扩展要求 {api_requirement}，"
            f"当前为 {OMNINODE_EXTENSION_API_VERSION}"
        )
    if hotools_requirement:
        hotools_version = _hotools_version()
        if hotools_version and not _meets_minimum(hotools_version, hotools_requirement):
            return failed(
                f"需要 HoTools {hotools_requirement} 或更高，当前为 {hotools_version}"
            )

    # 加载策略：
    #   1. **规范包名**：把扩展包目录登记为 HoTools.OmniNode.<包名>，再按该名字
    #      导入注册模块。扩展装在哪儿都不影响包内 700+ 处相对导入的层级。
    #   2. 按文件路径加载：注册模块可能不在规范包内（例如仓库根与包目录不同级）。
    #   3. 退回按物理名导入（无父级相对导入的简单扩展）。
    module = None
    load_error = ""
    if source == "manifest":
        canonical = _register_canonical_extension_package(directory, package_name)
        if canonical:
            candidate = (
                f"{canonical}.{Path(_EXTENSION_REGISTRATION_FILENAME).stem}"
            )
            try:
                module = importlib.import_module(candidate)
            except Exception as exc:  # noqa: BLE001 - 隔离扩展自身失败
                load_error = f"{candidate}: {type(exc).__name__}: {exc}"
        if module is None:
            flat_registration = directory / _EXTENSION_REGISTRATION_FILENAME
            if flat_registration.is_file():
                try:
                    module = _load_module_from_path(
                        f"{__package__}.{_normalize_extension_directory(directory_name)}"
                        f"_{Path(_EXTENSION_REGISTRATION_FILENAME).stem}",
                        flat_registration,
                    )
                except Exception as exc:  # noqa: BLE001
                    load_error = (
                        f"{flat_registration}: {type(exc).__name__}: {exc}"
                    )
    if module is None:
        candidates = [
            f"{package or __package__}.{_normalize_extension_directory(directory_name)}"
            f".{Path(_EXTENSION_REGISTRATION_FILENAME).stem}"
        ]
        module, fallback_error = _load_extension_module(
            candidates,
            import_root=search_root if source == "manifest" else None,
        )
        if module is None:
            return failed(load_error or fallback_error)

    factory = getattr(module, _EXTENSION_REGISTRATION_FACTORY, None)
    if not callable(factory):
        return failed(f"必须定义可调用的 {_EXTENSION_REGISTRATION_FACTORY}()")

    try:
        spec = factory()
    except Exception as exc:  # noqa: BLE001 - 隔离扩展自身构造失败
        return failed(
            f"{_EXTENSION_REGISTRATION_FACTORY}() 执行失败："
            f"{type(exc).__name__}: {exc}"
        )

    if not isinstance(spec, OmniNodeExtensionSpec):
        return failed(
            f"{_EXTENSION_REGISTRATION_FACTORY}() 必须返回 OmniNodeExtensionSpec"
        )
    if not isinstance(spec.identifier, str) or not spec.identifier.strip():
        return failed("扩展 identifier 不能为空")
    try:
        order = _require_order(spec.order, "扩展 order", str(registration))
    except ValueError as exc:
        return failed(str(exc))

    if spec.identifier != identifier:
        # 清单身份与代码声明不一致时必须报出来，否则禁用列表会与节点对不上。
        return failed(
            f"identifier 不一致：清单声明 {identifier!r}，"
            f"注册模块声明 {spec.identifier!r}"
        )

    return OmniNodeExtensionDescriptor(
        identifier=identifier,
        order=order,
        source=source,
        source_path=str(directory),
        directory=str(directory),
        spec=spec,
        display_name=display_name or identifier,
        version=version,
        omninode_api=api_requirement,
        requires_hotools=hotools_requirement,
    )


def _load_extension_module(candidates, *, import_root: Path | None = None):
    """按候选模块名导入扩展注册模块，返回 (module, error)。

    清单驱动的扩展包名由清单声明、解压在任意目录，因此先把该目录挂到
    sys.path 上；成功后**保留**（扩展的其它子模块稍后仍要按同一包名导入）。
    """
    if import_root is not None:
        _ensure_import_root(import_root)
    errors = []
    for module_name in candidates:
        try:
            return importlib.import_module(module_name), ""
        except Exception as exc:  # noqa: BLE001 - 隔离失败，逐个候选继续
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
    return None, "导入扩展注册模块失败：" + "；".join(errors)


def _discover_extension_directories(search_roots) -> list[tuple[Path, Path, dict | None, str]]:
    """枚举搜索根下的扩展目录，返回 (root, directory, manifest, source)。"""
    found = []
    for root in search_roots:
        root = Path(root)
        if not root.is_dir():
            continue
        manifest_directories = set()
        for manifest_path in sorted(root.glob(f"*/{_EXTENSION_MANIFEST_FILENAME}")):
            manifest, error = _read_extension_manifest(manifest_path)
            directory = manifest_path.parent
            if error:
                manifest = {"identifier": directory.name, "_manifest_error": error}
            manifest_directories.add(directory)
            found.append((root, directory, manifest, "manifest"))
        for registration in sorted(root.glob(f"*/{_EXTENSION_REGISTRATION_FILENAME}")):
            directory = registration.parent
            if directory in manifest_directories:
                continue
            found.append((root, directory, None, "builtin"))
    return found


def _discover_omninode_extensions(
    *,
    omni_node_directory: Path | None = None,
    package: str | None = None,
    search_roots=None,
) -> tuple[OmniNodeExtensionDescriptor, ...]:
    """发现并加载全部扩展（内置就地注册 + 清单驱动），按 (order, identifier) 排序。

    与旧实现的区别：任何单个扩展的失败都被隔离成 descriptor.error，不再抛异常
    中断整个 OmniNode 注册；identifier 重复时优先采用清单来源。
    """
    if omni_node_directory is not None or package is not None:
        # 兼容旧签名：显式包目录时按“就地注册”扫描，并用调用方给的包名定位模块。
        directory = Path(omni_node_directory) if omni_node_directory else Path(
            __file__
        ).resolve().parent
        roots = (directory,)
        scan_package = package or __package__
    else:
        roots = tuple(search_roots) if search_roots else _default_extension_search_roots()
        scan_package = __package__

    descriptors: list[OmniNodeExtensionDescriptor] = []
    sources: dict[str, str] = {}

    for root, directory, manifest, source in _discover_extension_directories(roots):
        if manifest is not None and manifest.get("_manifest_error"):
            descriptor = OmniNodeExtensionDescriptor(
                identifier=str(manifest.get("identifier") or directory.name),
                order=0,
                source=source,
                source_path=str(directory),
                directory=str(directory),
                display_name=str(manifest.get("name") or directory.name),
                error=str(manifest["_manifest_error"]),
            )
        else:
            descriptor = _build_extension_descriptor(
                directory,
                search_root=root,
                manifest=manifest,
                source=source,
                package=scan_package,
            )

        previous_source = sources.get(descriptor.identifier)
        if previous_source is not None:
            previous_priority = _SOURCE_PRIORITY.get(previous_source, 0)
            new_priority = _SOURCE_PRIORITY.get(descriptor.source, 0)
            if new_priority <= previous_priority:
                # 保留先发现的（更高优先级）来源，把重复者标记为错误供 UI 展示。
                descriptors.append(OmniNodeExtensionDescriptor(
                    identifier=descriptor.identifier,
                    order=descriptor.order,
                    source=descriptor.source,
                    source_path=descriptor.source_path,
                    directory=descriptor.directory,
                    display_name=descriptor.display_name,
                    version=descriptor.version,
                    omninode_api=descriptor.omninode_api,
                    requires_hotools=descriptor.requires_hotools,
                    error=f"扩展 identifier {descriptor.identifier!r} 与 {previous_source} 重复",
                ))
                continue
            # 新来源优先级更高：移除已收集的低优先级同名扩展。
            descriptors = [
                item for item in descriptors
                if item.identifier != descriptor.identifier
            ]
        sources[descriptor.identifier] = descriptor.source
        descriptors.append(descriptor)

    return tuple(sorted(
        descriptors,
        key=lambda item: (item.order, item.identifier.casefold()),
    ))


def iter_extension_descriptors() -> tuple[OmniNodeExtensionDescriptor, ...]:
    """返回上次构建快照时的扩展描述符（含不可用/被禁用的），供 UI 使用。"""
    return _registry.extensions


def active_extension_specs() -> tuple[OmniNodeExtensionSpec, ...]:
    """返回可用的扩展声明。"""
    return tuple(
        descriptor.spec
        for descriptor in _registry.extensions
        if descriptor.spec is not None
    )


def find_extension_descriptor(identifier):
    """按 identifier 取扩展描述符（含被禁用/不可用的），找不到返回 None。"""
    wanted = str(identifier)
    for descriptor in _registry.extensions:
        if descriptor.identifier == wanted:
            return descriptor
    return None


def find_extension_spec(identifier):
    """按 identifier 取可用的扩展声明；不存在或被禁用时返回 None。"""
    descriptor = find_extension_descriptor(identifier)
    return None if descriptor is None else descriptor.spec


def _apply_disabled_extensions(
    descriptors: tuple[OmniNodeExtensionDescriptor, ...],
    disabled_ids,
) -> tuple[OmniNodeExtensionDescriptor, ...]:
    """按禁用列表标记扩展；被禁用者保留描述但清空 spec（节点不参与注册）。"""
    disabled = {str(item) for item in (disabled_ids or ()) if str(item).strip()}
    if not disabled:
        return descriptors
    result = []
    for descriptor in descriptors:
        if descriptor.identifier not in disabled:
            result.append(descriptor)
            continue
        result.append(OmniNodeExtensionDescriptor(
            identifier=descriptor.identifier,
            order=descriptor.order,
            source=descriptor.source,
            source_path=descriptor.source_path,
            directory=descriptor.directory,
            spec=None,
            display_name=descriptor.display_name,
            version=descriptor.version,
            omninode_api=descriptor.omninode_api,
            requires_hotools=descriptor.requires_hotools,
            error=descriptor.error,
            disabled_by_user=True,
        ))
    return tuple(result)


# 扩展 Blender 生命周期钩子
#
# 扩展可以在自己的注册模块里定义 register_blender()/unregister_blender()，
# 用来注册属性组、UI 面板、draw handler 等不属于节点目录的东西。父仓不再
# 硬编码任何扩展的生命周期调用。
_EXTENSION_REGISTER_HOOK = "register_blender"
_EXTENSION_UNREGISTER_HOOK = "unregister_blender"


def _extension_hook_module(descriptor):
    """取回扩展注册模块（用于生命周期钩子），与发现阶段使用同一策略。"""
    directory = Path(descriptor.directory)
    if descriptor.source == "manifest":
        manifest, _error = _read_extension_manifest(
            directory / _EXTENSION_MANIFEST_FILENAME
        )
        relative = _manifest_relative_path(manifest, directory.name)
        canonical = _register_canonical_extension_package(directory, relative)
        if canonical:
            try:
                return importlib.import_module(
                    f"{canonical}.{Path(_EXTENSION_REGISTRATION_FILENAME).stem}"
                )
            except Exception:  # noqa: BLE001 - 回退到按路径加载
                pass
        flat_registration = directory / _EXTENSION_REGISTRATION_FILENAME
        if flat_registration.is_file():
            try:
                return _load_module_from_path(
                    f"{__package__}.{_normalize_extension_directory(directory.name)}"
                    f"_{Path(_EXTENSION_REGISTRATION_FILENAME).stem}",
                    flat_registration,
                )
            except Exception:  # noqa: BLE001
                return None
        return None
    module, _error = _load_extension_module([
        f"{__package__}.{_normalize_extension_directory(directory.name)}"
        f".{Path(_EXTENSION_REGISTRATION_FILENAME).stem}"
    ])
    return module


def start_extension_blender_hooks() -> tuple[str, ...]:
    """调用已启用扩展的 register_blender()；返回失败信息列表（不抛异常）。"""
    failures = []
    for descriptor in _registry.extensions:
        if descriptor.spec is None:
            continue
        module = _extension_hook_module(descriptor)
        hook = getattr(module, _EXTENSION_REGISTER_HOOK, None) if module else None
        if not callable(hook):
            continue
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 - 单个扩展失败不应中断其它扩展
            failures.append(
                f"{descriptor.identifier}.{_EXTENSION_REGISTER_HOOK}: "
                f"{type(exc).__name__}: {exc}"
            )
    return tuple(failures)


def stop_extension_blender_hooks() -> tuple[str, ...]:
    """调用已启用扩展的 unregister_blender()；返回失败信息列表（不抛异常）。"""
    failures = []
    for descriptor in reversed(_registry.extensions):
        module = _extension_hook_module(descriptor)
        hook = getattr(module, _EXTENSION_UNREGISTER_HOOK, None) if module else None
        if not callable(hook):
            continue
        try:
            hook()
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{descriptor.identifier}.{_EXTENSION_UNREGISTER_HOOK}: "
                f"{type(exc).__name__}: {exc}"
            )
    return tuple(failures)



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
    # 注意：这里是**描述符**而非纯 spec——包含被禁用/加载失败的扩展，
    # 供偏好面板展示状态与错误原因。
    extensions: tuple[OmniNodeExtensionDescriptor, ...] = ()
    node_classes: tuple[type, ...] = ()
    node_categories: tuple[OmniNodeCategory, ...] = ()
    menu_classes: tuple[type, ...] = ()


_registry = _RegistrySnapshot()

# 禁用列表由父仓偏好写入。OmniNodeRegister 不反向 import 偏好模块（注册期会循环
# 依赖），因此用 setter 注入；未注入时视为“全部启用”。
_disabled_extension_ids: frozenset[str] = frozenset()


def set_disabled_extensions(identifiers) -> None:
    """设置被用户禁用的扩展 identifier 集合（父仓偏好调用）。"""
    global _disabled_extension_ids
    _disabled_extension_ids = frozenset(
        str(item) for item in (identifiers or ()) if str(item).strip()
    )


def disabled_extensions() -> frozenset[str]:
    return _disabled_extension_ids


def _build_registry_snapshot(
    disabled_extensions_ids=None,
) -> _RegistrySnapshot:
    function_modules = _discover_all_function_modules()
    function_categories, function_menu_classes = _build_function_categories(
        function_modules
    )
    function_node_classes = tuple(
        node_class
        for module_spec in function_modules
        for node_class in module_spec.node_classes
    )

    disabled = (
        _disabled_extension_ids
        if disabled_extensions_ids is None
        else frozenset(str(item) for item in disabled_extensions_ids)
    )
    descriptors = _discover_omninode_extensions()
    descriptors = _apply_disabled_extensions(descriptors, disabled)

    extension_specs = tuple(
        descriptor.spec for descriptor in descriptors if descriptor.spec is not None
    )
    (
        extension_node_classes,
        extension_categories,
        extension_menu_classes,
    ) = _build_extension_categories(extension_specs)

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
        extensions=descriptors,
        node_classes=node_classes,
        node_categories=node_categories,
        menu_classes=menu_classes,
    )


def _rebuild_registry() -> _RegistrySnapshot:
    """重建注册快照。失败时保留旧快照（调用方按需回滚）。"""
    global _registry
    _registry = _build_registry_snapshot()
    return _registry


_registered_node_classes = []
_registered_menu_classes = []
_node_categories_registered = False
_extension_hooks_started = False


def _registry_is_registered() -> bool:
    return _node_categories_registered


def extension_failures() -> tuple[OmniNodeExtensionDescriptor, ...]:
    """返回当前快照里不可用（加载失败 / 版本不兼容）的扩展。"""
    return tuple(
        descriptor
        for descriptor in _registry.extensions
        if descriptor.spec is None and not descriptor.disabled_by_user
    )


def extension_status_text(descriptor) -> str:
    """把描述符状态渲染成一行中文说明，供偏好面板使用。"""
    if descriptor.disabled_by_user:
        return "已禁用（用户设置）"
    if descriptor.error:
        return f"不可用：{descriptor.error}"
    label = descriptor.display_name or descriptor.identifier
    version = f" v{descriptor.version}" if descriptor.version else ""
    return f"{label}{version}｜来源：{descriptor.source}"


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
    global _node_categories_registered, _extension_hooks_started
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
        # 扩展的 Blender 生命周期钩子（属性组、面板、handler）：失败只记录不抛出，
        # 否则一个坏扩展开关会让整棵节点树注册失败。
        hook_failures = start_extension_blender_hooks()
        _extension_hooks_started = True
        if hook_failures:
            print(
                "[HoTools] 扩展 Blender 钩子部分失败：\n  "
                + "\n  ".join(hook_failures)
            )
    except Exception:
        _rollback_registration()
        raise


def unregister():
    global _extension_hooks_started
    # 幂等：扩展开关的延迟重建可能已经反注册过一次，重复反注册会让
    # bpy.utils.unregister_class 抛异常并留下半截状态。
    if _extension_hooks_started:
        failures = stop_extension_blender_hooks()
        _extension_hooks_started = False
        if failures:
            print(
                "[HoTools] 扩展 Blender 钩子反注册部分失败：\n  "
                + "\n  ".join(failures)
            )
    _rollback_registration()

