import hashlib
import re

import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem, NodeItemCustom

from . import FunctionNodeCore
from .GraphNode import CLS_GRAPH
from .OmniNodeFunctionRegistry import discover_function_modules
from .OmniNodeTree import TREE_ID
from .PhysicsWorld import nodes as physicsWorld
from .PhysicsWorld import registry as physicsWorldRegistry


class OmniNodeCategory(NodeCategory):
    @classmethod
    def poll(cls, context):
        return True


_RESERVED_CATEGORY_IDS = {
    "GRAPH",
    "PHYSICS_WORLD",
    "PHYSICS_SOLVER",
    "PHYSICS_WORLD_DEBUG",
}


def _label_startswith(node_list, *prefixes):
    return [node for node in node_list if any(
        node.bl_label.startswith(prefix) for prefix in prefixes
    )]


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


def _new_menu_tree(label="", menu_path=()):
    return {
        "label": label,
        "menu_path": tuple(menu_path),
        "nodes": [],
        "children": {},
        "sort_key": None,
    }


def _build_function_category_records(registrations):
    categories = {}
    for registration in registrations:
        if registration.category_id in _RESERVED_CATEGORY_IDS:
            raise ValueError(
                f"{registration.relative_path}: category "
                f"{registration.category_id!r} is reserved by OmniNode"
            )

        category = categories.setdefault(registration.category_id, {
            "id": registration.category_id,
            "label": registration.category_label,
            "order": registration.category_order,
            "root": _new_menu_tree(),
        })
        module_key = (registration.order, registration.module_name.casefold())
        menu = category["root"]
        traversed_path = []
        for label in registration.menu_path:
            traversed_path.append(label)
            child = menu["children"].get(label)
            if child is None:
                child = _new_menu_tree(label, traversed_path)
                menu["children"][label] = child
            if child["sort_key"] is None or module_key < child["sort_key"]:
                child["sort_key"] = module_key
            menu = child

        for index, node_class in enumerate(registration.node_classes):
            menu["nodes"].append((
                (registration.order, registration.module_name.casefold(), 1, index),
                node_class,
            ))

    return tuple(sorted(
        categories.values(),
        key=lambda category: (category["order"], category["id"]),
    ))


def _build_menu_items(category_id, tree, menu_classes):
    entries = [
        (sort_key, NodeItem(node_class.bl_idname))
        for sort_key, node_class in tree["nodes"]
    ]
    for child in tree["children"].values():
        child_items = _build_menu_items(category_id, child, menu_classes)
        menu_id = _nested_menu_id(category_id, child["menu_path"])
        menu_classes.append(_make_menu_class(menu_id, child["label"], child_items))
        child_order, child_module = child["sort_key"]
        entries.append((
            (child_order, child_module, 0, child["label"].casefold()),
            _make_menu_item(menu_id),
        ))
    return [item for _sort_key, item in sorted(entries, key=lambda entry: entry[0])]


def _build_function_categories(registrations):
    category_records = _build_function_category_records(registrations)
    menu_classes = []
    categories = []
    for category in category_records:
        items = _build_menu_items(category["id"], category["root"], menu_classes)
        categories.append(OmniNodeCategory(
            category["id"],
            category["label"],
            items=items,
        ))
    menu_ids = [menu_class.bl_idname for menu_class in menu_classes]
    if len(menu_ids) != len(set(menu_ids)):
        raise ValueError("nested Function menu identifiers must be unique")
    return category_records, categories, menu_classes


def _solver_menu_id(solver_id):
    token = re.sub(r"[^A-Za-z0-9_]+", "_", str(solver_id)).strip("_").upper()
    if not token:
        raise ValueError("solver_id cannot produce an empty menu identifier")
    return f"NODE_MT_OMNINODE_SOLVER_{token}"


def _load_physics_world_solver_groups():
    groups = []
    menu_ids = set()
    for entry in physicsWorldRegistry.iter_solver_node_groups():
        nodes = []
        for module_entry in entry["modules"]:
            nodes.extend(FunctionNodeCore.loadRegisterFuncNodes(module_entry["module"]))
        if not nodes:
            continue
        menu_id = _solver_menu_id(entry["solver_id"])
        if menu_id in menu_ids:
            raise ValueError(f"duplicate solver menu identifier: {menu_id}")
        menu_ids.add(menu_id)
        groups.append({
            "domain": entry["domain"],
            "solver_id": entry["solver_id"],
            "menu_name": entry["menu_name"],
            "menu_id": menu_id,
            "nodes": tuple(nodes),
        })
    return groups


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
                f"duplicate OmniNode bl_idname {node_id!r}: "
                f"{previous_source} and {current_source}"
            )
        seen[node_id] = node_class


function_module_registrations = ()
function_nodes_by_module = {}
function_category_records = ()
function_menu_classes = []
node_cls_graph = []
node_cls_physics_world = []
physics_world_solver_groups = []
node_cls_physics_world_solvers = []
physics_world_solver_menu_classes = []
_pw_lifecycle = []
_pw_debug = []
cls = []
node_categories = []
menu_classes = []


def _rebuild_registry():
    global function_module_registrations
    global function_nodes_by_module
    global function_category_records
    global function_menu_classes
    global node_cls_graph
    global node_cls_physics_world
    global physics_world_solver_groups
    global node_cls_physics_world_solvers
    global physics_world_solver_menu_classes
    global _pw_lifecycle
    global _pw_debug
    global cls
    global node_categories
    global menu_classes

    function_module_registrations = discover_function_modules()
    function_nodes_by_module = {
        registration.relative_path: list(registration.node_classes)
        for registration in function_module_registrations
    }

    (
        function_category_records,
        function_categories,
        function_menu_classes,
    ) = _build_function_categories(function_module_registrations)

    node_cls_graph = list(CLS_GRAPH)
    function_nodes = [
        node_class
        for registration in function_module_registrations
        for node_class in registration.node_classes
    ]
    node_cls_physics_world = FunctionNodeCore.loadRegisterFuncNodes(physicsWorld)
    physics_world_solver_groups = _load_physics_world_solver_groups()
    node_cls_physics_world_solvers = [
        node
        for group in physics_world_solver_groups
        for node in group["nodes"]
    ]
    physics_world_solver_menu_classes = [
        _make_menu_class(
            group["menu_id"],
            group["menu_name"],
            [NodeItem(node.bl_idname) for node in group["nodes"]],
        )
        for group in physics_world_solver_groups
    ]

    cls = (
        node_cls_graph
        + function_nodes
        + node_cls_physics_world
        + node_cls_physics_world_solvers
    )
    _validate_unique_node_ids(cls)

    _pw_lifecycle = _label_startswith(
        node_cls_physics_world,
        "物理对象", "物理世界-帧", "物理写回", "物理烘焙", "清除物理Bake",
    )
    _pw_debug = _label_startswith(
        node_cls_physics_world,
        "物理世界-调试", "物理世界-结果", "物理世界-可视化",
    )
    solver_items = [
        _make_menu_item(group["menu_id"])
        for group in physics_world_solver_groups
    ]

    node_categories = [
        OmniNodeCategory("GRAPH", "graph", items=[
            NodeItem(node.bl_idname) for node in node_cls_graph
        ]),
        *function_categories,
        OmniNodeCategory("PHYSICS_WORLD", "物理世界", items=[
            NodeItem(node.bl_idname) for node in _pw_lifecycle
        ]),
        OmniNodeCategory("PHYSICS_SOLVER", "解算器", items=solver_items),
        OmniNodeCategory("PHYSICS_WORLD_DEBUG", "物理世界调试", items=[
            NodeItem(node.bl_idname) for node in _pw_debug
        ]),
    ]
    menu_classes = function_menu_classes + physics_world_solver_menu_classes


_registered_node_classes = []
_registered_menu_classes = []
_registered_solver_menu_classes = _registered_menu_classes
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
    _rebuild_registry()
    try:
        for node_class in cls:
            bpy.utils.register_class(node_class)
            _registered_node_classes.append(node_class)
        for menu_class in menu_classes:
            bpy.utils.register_class(menu_class)
            _registered_menu_classes.append(menu_class)
        nodeitems_utils.register_node_categories(TREE_ID, node_categories)
        _node_categories_registered = True
    except Exception:
        _rollback_registration()
        raise


def unregister():
    _rollback_registration()


_rebuild_registry()
