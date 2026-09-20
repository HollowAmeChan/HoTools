"""物理世界对 OmniNode 注册器公开的节点、菜单声明与 Blender 生命周期钩子。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .. import FunctionNodeCore
from ..OmniNodeRegister import (
    OmniNodeCategorySpec,
    OmniNodeExtensionSpec,
    OmniNodeMenuSpec,
)
from . import nodes
from . import registry


def _ensure_addon_root_on_path() -> None:
    """确保父仓插件目录在 sys.path 上。

    物理世界里有沿用 `from Utils...` / `from HoTools...` 的历史写法（例如
    `PhysicsWorld/ui/utils.py`）。这类绝对导入只有在插件根被挂到 sys.path 时
    才成立——正常插件注册会做，但扩展被单独加载时（测试、外置安装）不一定。
    由扩展入口自举，避免整棵子树依赖宿主环境。
    """
    addon_root = Path(__file__).resolve().parents[3]
    path_text = str(addon_root)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


_ensure_addon_root_on_path()


def register_blender() -> None:
    """扩展的 Blender 生命周期钩子：属性组、UI 面板、draw handler 等。

    由 OmniNodeRegister 在扩展通过（启用 + 版本校验 + 加载成功）后调用。
    父仓不再硬编码物理世界的注册入口。
    """
    from . import blender

    blender.register()


def unregister_blender() -> None:
    from . import blender

    blender.unregister()


_LIFECYCLE_FUNCTIONS = (
    nodes.physicsObjectsFromScene,
    nodes.physicsObjectScope,
    nodes.physicsWorldBegin,
    nodes.physicsWorldCommit,
    nodes.physicsBake,
    nodes.clearPhysicsBake,
    nodes.physicsWriteback,
)
_DEBUG_FUNCTIONS = (
    nodes.physicsWorldDebugSnapshot,
    nodes.physicsWorldResultStream,
    nodes.physicsWorldDebugText,
    nodes.physicsFieldRuntimeDebugDraw,
)


def _node_classes_for_functions(node_classes, functions):
    classes_by_function = {
        node_class._func: node_class
        for node_class in node_classes
    }
    missing = [
        function.__name__
        for function in functions
        if function not in classes_by_function
    ]
    if missing:
        raise ValueError(f"物理世界分类引用了未启用的节点函数：{missing}")
    return tuple(classes_by_function[function] for function in functions)


def _solver_menu_id(solver_id):
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(solver_id)).strip("_").upper()
    if not token:
        raise ValueError("解算器标识符不能生成空菜单标识符")
    return f"NODE_MT_OMNINODE_SOLVER_{token}"


def _build_solver_registration():
    node_classes = []
    menus = []
    menu_ids = set()
    for group in registry.iter_solver_node_groups():
        group_node_classes = []
        for module_entry in group["modules"]:
            group_node_classes.extend(
                FunctionNodeCore.loadRegisterFuncNodes(module_entry["module"])
            )
        if not group_node_classes:
            continue

        menu_id = _solver_menu_id(group["solver_id"])
        if menu_id in menu_ids:
            raise ValueError(f"解算器菜单标识符重复：{menu_id}")
        menu_ids.add(menu_id)
        node_classes.extend(group_node_classes)
        menus.append(OmniNodeMenuSpec(
            identifier=menu_id,
            label=group["menu_name"],
            items=tuple(group_node_classes),
        ))

    return tuple(node_classes), tuple(menus)


def build_omninode_registration() -> OmniNodeExtensionSpec:
    world_node_classes = tuple(FunctionNodeCore.loadRegisterFuncNodes(nodes))
    solver_node_classes, solver_menus = _build_solver_registration()
    lifecycle_node_classes = _node_classes_for_functions(
        world_node_classes,
        _LIFECYCLE_FUNCTIONS,
    )
    debug_node_classes = _node_classes_for_functions(
        world_node_classes,
        _DEBUG_FUNCTIONS,
    )
    classified_node_classes = set(lifecycle_node_classes + debug_node_classes)
    unclassified = [
        node_class.bl_idname
        for node_class in world_node_classes
        if node_class not in classified_node_classes
    ]
    if unclassified:
        raise ValueError(f"物理世界存在未分类节点：{unclassified}")

    return OmniNodeExtensionSpec(
        identifier="PhysicsWorld",
        order=1000,
        node_classes=world_node_classes + solver_node_classes,
        categories=(
            OmniNodeCategorySpec(
                identifier="PHYSICS_WORLD",
                label="物理世界",
                items=lifecycle_node_classes,
            ),
            OmniNodeCategorySpec(
                identifier="PHYSICS_SOLVER",
                label="解算器",
                items=solver_menus,
            ),
            OmniNodeCategorySpec(
                identifier="PHYSICS_WORLD_DEBUG",
                label="物理世界调试",
                items=debug_node_classes,
            ),
        ),
    )
