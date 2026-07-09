from . import FunctionNodeCore
import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem
from .OmniNodeTree import TREE_ID
from .Function import Data, Math,Operator, RigTooKit,Logic,DataTypeCast,Image,Modifier,Material,UV,VertexColor,VertexGroup,Debug,Cache,Physics,physicsMC2MeshCloth,physicsMC2BoneCloth,Armature
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


def _load_physics_world_solver_nodes():
    nodes = []
    for entry in physicsWorldRegistry.iter_solver_node_modules():
        nodes.extend(FunctionNodeCore.loadRegisterFuncNodes(entry["module"]))
    return nodes


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
node_cls_physics_mc2 = FunctionNodeCore.loadRegisterFuncNodes(physicsMC2MeshCloth)
node_cls_physics_bonecloth = FunctionNodeCore.loadRegisterFuncNodes(physicsMC2BoneCloth)
node_cls_physics_world = FunctionNodeCore.loadRegisterFuncNodes(physicsWorld)
node_cls_physics_world_solvers = _load_physics_world_solver_nodes()
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
cls.extend(node_cls_physics_mc2)
cls.extend(node_cls_physics_bonecloth)
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
# 解算器：所有 solver + 配套属性/注册/命令（刚体全部 + 弹簧骨全部）
# 排序：属性 → 注册 → 模拟步 → 命令/结果，使同一 solver 的节点自然聚合
_solver_items = (
    node_cls_physics_world_solvers
)
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
    ] + [
        NodeItem(i.bl_idname) for i in node_cls_physics_mc2
    ] + [
        NodeItem(i.bl_idname) for i in node_cls_physics_bonecloth
    ]),
    # ── 物理世界：3个子分类 ─────────────────────────────────────────────────────
    OmniNodeCategory("PHYSICS_WORLD", "物理世界", items=[
        NodeItem(i.bl_idname) for i in _pw_lifecycle
    ]),
    OmniNodeCategory("PHYSICS_SOLVER", "解算器", items=[
        NodeItem(i.bl_idname) for i in _solver_items
    ]),
    OmniNodeCategory("PHYSICS_WORLD_DEBUG", "物理世界调试", items=[
        NodeItem(i.bl_idname) for i in _pw_debug
    ]),
]


def register():
    try:
        for i in cls:
            bpy.utils.register_class(i)
        nodeitems_utils.register_node_categories(TREE_ID, node_categories)
    except Exception:
        print(__file__+" register failed!!!")


def unregister():
    try:
        for i in cls:
            bpy.utils.unregister_class(i)
        nodeitems_utils.unregister_node_categories(TREE_ID)
    except Exception:
        print(__file__+" unregister failed!!!")
