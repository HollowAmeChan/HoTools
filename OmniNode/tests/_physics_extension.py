"""OmniNode 测试共用：把已安装的物理扩展按规范包名注入 sys.modules。

物理世界已拆为独立扩展（`OmniNode/extensions/<仓库>/PhysicsWorld`），不再躺在
`OmniNode/PhysicsWorld` 下。测试必须走扩展发现机制，否则会在干净环境下因为旧路径
不存在而失败。

用法（在 import 物理子模块之前）：

    from _physics_extension import ensure_physics_world_package
    PACKAGE = ensure_physics_world_package()
    types_mod = importlib.import_module(f"{PACKAGE}.types")
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

PHYSICS_IDENTIFIER = "PhysicsWorld"


def ensure_physics_world_package() -> str:
    """发现 PhysicsWorld 扩展并注入规范包名，返回包名。"""
    tests_dir = Path(__file__).resolve().parent
    omninode = tests_dir.parent
    hotools = omninode.parent
    for path in (str(hotools.parent), str(hotools)):
        if path not in sys.path:
            sys.path.insert(0, path)

    if "HoTools" not in sys.modules:
        package = types.ModuleType("HoTools")
        package.__path__ = [str(hotools)]
        package.__package__ = "HoTools"
        sys.modules["HoTools"] = package

    register = importlib.import_module("HoTools.OmniNode.OmniNodeRegister")
    descriptor = next(
        (
            item
            for item in register._discover_omninode_extensions()
            if item.identifier == PHYSICS_IDENTIFIER and item.available
        ),
        None,
    )
    if descriptor is None:
        raise RuntimeError(
            "未发现可用的 PhysicsWorld 扩展；请确认扩展仓库位于 "
            "OmniNode/extensions/<仓库>/ 之下且清单有效"
        )
    canonical = register._register_canonical_extension_package(
        Path(descriptor.directory), PHYSICS_IDENTIFIER
    )
    if not canonical:
        raise RuntimeError(f"规范包名注入失败：{descriptor.directory}")
    return canonical
