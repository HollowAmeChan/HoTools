from . import FunctionNodeCore
import bpy
import nodeitems_utils
import re
from nodeitems_utils import NodeCategory, NodeItem, NodeItemCustom
from .OmniNodeTree import TREE_ID
from .Function import Data, Math,Operator, RigTooKit,Logic,DataTypeCast,Image,Modifier,Material,UV,VertexColor,VertexGroup,Debug,Cache,Physics,Armature
from .Function.physicsWorld import nodes as physicsWorld
from .Function.physicsWorld import registry as physicsWorldRegistry
from .GraphNode import CLS_GRAPH

class OmniNodeCategory(NodeCategory):  # 定义一个节点集合类
    @classmethod
    def poll(cls, context):
        return True


def _label_startswith(node_list, *prefixes):
    """按 bl_label 前缀过滤节点类列表。"""
    return [n for n in node_list if any(n.bl_label.startswith(p) for p in prefixes)]


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


def _make_solver_menu_class(group):
    node_items = tuple(NodeItem(node.bl_idname) for node in group["nodes"])

    def draw(self, context):
        column = self.layout.column(align=True)
        for item in node_items:
            item.draw(item, column, context)

    return type(group["menu_id"], (bpy.types.Menu,), {
        "bl_idname": group["menu_id"],
        "bl_label": group["menu_name"],
        "draw": draw,
    })


def _make_solver_menu_item(menu_id):
    def draw(_item, layout, _context):
        layout.menu(menu_id)

    return NodeItemCustom(draw=draw)


cls = []
# Graph节点
node_cls_graph = []
node_cls_graph.extend(CLS_GRAPH)
cls.extend(node_cls_graph)
# Function生成节点
node_cls_data = FunctionNodeCore.loadRegisterFuncNodes(Data)
node_cls_armature = FunctionNodeCore.loadRegisterFuncNodes(Armature)
node_cls_math = FunctionNodeCore.loadRegisterFuncNodes(Math)
node_cls_operator = FunctionNodeCore.loadRegisterFuncNodes(Operator)
node_cls_modifier = FunctionNodeCore.loadRegisterFuncNodes(Modifier)
node_cls_material = FunctionNodeCore.loadRegisterFuncNodes(Material)
node_cls_uv = FunctionNodeCore.loadRegisterFuncNodes(UV)
node_cls_vertexcolor = FunctionNodeCore.loadRegisterFuncNodes(VertexColor)
node_cls_vertexgroup = FunctionNodeCore.loadRegisterFuncNodes(VertexGroup)
node_cls_rigtoolkit = FunctionNodeCore.loadRegisterFuncNodes(RigTooKit)
node_cls_logic = FunctionNodeCore.loadRegisterFuncNodes(Logic)
node_cls_datatypecast = FunctionNodeCore.loadRegisterFuncNodes(DataTypeCast)
node_cls_image = FunctionNodeCore.loadRegisterFuncNodes(Image)
node_cls_debug = FunctionNodeCore.loadRegisterFuncNodes(Debug)
node_cls_cache = FunctionNodeCore.loadRegisterFuncNodes(Cache)
node_cls_physics = FunctionNodeCore.loadRegisterFuncNodes(Physics)
node_cls_physics_world = FunctionNodeCore.loadRegisterFuncNodes(physicsWorld)
physics_world_solver_groups = _load_physics_world_solver_groups()
node_cls_physics_world_solvers = [
    node
    for group in physics_world_solver_groups
    for node in group["nodes"]
]
physics_world_solver_menu_classes = [
    _make_solver_menu_class(group)
    for group in physics_world_solver_groups
]
cls.extend(node_cls_data)
cls.extend(node_cls_armature)
cls.extend(node_cls_math)
cls.extend(node_cls_operator)
cls.extend(node_cls_modifier)
cls.extend(node_cls_material)
cls.extend(node_cls_uv)
cls.extend(node_cls_vertexcolor)
cls.extend(node_cls_vertexgroup)
cls.extend(node_cls_rigtoolkit)
cls.extend(node_cls_logic)
cls.extend(node_cls_datatypecast)
cls.extend(node_cls_image)
cls.extend(node_cls_debug)
cls.extend(node_cls_cache)
cls.extend(node_cls_physics)
cls.extend(node_cls_physics_world)
cls.extend(node_cls_physics_world_solvers)

# ── 物理世界子分类（3块）─────────────────────────────────────────────────────
# 物理世界：对象范围 + 帧开始/提交 + 写回
_pw_lifecycle = _label_startswith(
    node_cls_physics_world,
    "物理对象", "物理世界-帧", "物理写回",
)
# 物理世界调试：调试快照/文本/可视化 + 结果流
_pw_debug = _label_startswith(
    node_cls_physics_world,
    "物理世界-调试", "物理世界-结果", "物理世界-可视化",
)
# 解算器：顶层只保留 solver 子菜单；各模块自行声明 menu_name 和节点模块。
_solver_items = [
    _make_solver_menu_item(group["menu_id"])
    for group in physics_world_solver_groups
]
# ─────────────────────────────────────────────────────────────────────────────

node_categories = [
    OmniNodeCategory("GRAPH", "graph", items=[
        NodeItem(i.bl_idname) for i in node_cls_graph
    ]),
    OmniNodeCategory("DATA", "Data", items=[
        NodeItem(i.bl_idname) for i in node_cls_data
    ]),
    OmniNodeCategory("ARMATURE", "Armature", items=[
        NodeItem(i.bl_idname) for i in node_cls_armature
    ]),
    OmniNodeCategory("DATA_TYPECAST", "DataTypeCast", items=[
        NodeItem(i.bl_idname) for i in node_cls_datatypecast
    ]),
    OmniNodeCategory("MATH", "Math", items=[
        NodeItem(i.bl_idname) for i in node_cls_math
    ]),
    OmniNodeCategory("OPERATOR", "Operator", items=[
        NodeItem(i.bl_idname) for i in node_cls_operator
    ]),
    OmniNodeCategory("MODIFIER", "Modifier", items=[
        NodeItem(i.bl_idname) for i in node_cls_modifier
    ]),
    OmniNodeCategory("MATERIAL", "Material", items=[
        NodeItem(i.bl_idname) for i in node_cls_material
    ]),
    OmniNodeCategory("UV", "UV", items=[
        NodeItem(i.bl_idname) for i in node_cls_uv
    ]),
    OmniNodeCategory("VERTEXCOLOR", "VertexColor", items=[
        NodeItem(i.bl_idname) for i in node_cls_vertexcolor
    ]),
    OmniNodeCategory("VERTEXGROUP", "VertexGroup", items=[
        NodeItem(i.bl_idname) for i in node_cls_vertexgroup
    ]),
    OmniNodeCategory("IMAGE", "Image", items=[
        NodeItem(i.bl_idname) for i in node_cls_image
    ]),
    OmniNodeCategory("RIGTOOLKIT", "RigToolKit", items=[
        NodeItem(i.bl_idname) for i in node_cls_rigtoolkit
    ]),
    OmniNodeCategory("LOGIC", "Logic", items=[
        NodeItem(i.bl_idname) for i in node_cls_logic
    ]),
    OmniNodeCategory("DEBUG", "Debug", items=[
        NodeItem(i.bl_idname) for i in node_cls_debug
    ]),
    OmniNodeCategory("CACHE", "Cache", items=[
        NodeItem(i.bl_idname) for i in node_cls_cache
    ]),
    OmniNodeCategory("PHYSICS", "Physics", items=[
        NodeItem(i.bl_idname) for i in node_cls_physics
    ]),
    # ── 物理世界：3个子分类 ─────────────────────────────────────────────────────
    OmniNodeCategory("PHYSICS_WORLD", "物理世界", items=[
        NodeItem(i.bl_idname) for i in _pw_lifecycle
    ]),
    OmniNodeCategory("PHYSICS_SOLVER", "解算器", items=_solver_items),
    OmniNodeCategory("PHYSICS_WORLD_DEBUG", "物理世界调试", items=[
        NodeItem(i.bl_idname) for i in _pw_debug
    ]),
]


_registered_node_classes = []
_registered_solver_menu_classes = []
_node_categories_registered = False


def _rollback_registration():
    global _node_categories_registered
    if _node_categories_registered:
        nodeitems_utils.unregister_node_categories(TREE_ID)
        _node_categories_registered = False
    for menu_class in reversed(_registered_solver_menu_classes):
        bpy.utils.unregister_class(menu_class)
    _registered_solver_menu_classes.clear()
    for node_class in reversed(_registered_node_classes):
        bpy.utils.unregister_class(node_class)
    _registered_node_classes.clear()


def register():
    global _node_categories_registered
    if _node_categories_registered:
        return
    try:
        for node_class in cls:
            bpy.utils.register_class(node_class)
            _registered_node_classes.append(node_class)
        for menu_class in physics_world_solver_menu_classes:
            bpy.utils.register_class(menu_class)
            _registered_solver_menu_classes.append(menu_class)
        nodeitems_utils.register_node_categories(TREE_ID, node_categories)
        _node_categories_registered = True
    except Exception:
        _rollback_registration()
        raise


def unregister():
    _rollback_registration()
