import bpy
from importlib import import_module
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .physicsUtils import _ALL_COLLISION_GROUPS_MASK, _COLLISION_GROUP_COUNT

_PI = 3.141592653589793


def __getattr__(name: str):
    """短期兼容旧导入；PropertyGroup 的唯一实现位于 physicsWorld。"""
    modules = {
        "PG_Hotools_ObjectCollision": "collision.properties",
        "PG_Hotools_RigidBody": "rigid.properties",
        "PG_Hotools_RigidConstraint": "rigid.properties",
    }
    module_name = modules.get(name)
    if module_name is None:
        raise AttributeError(name)
    package_root = __package__.split(".", 1)[0] if "." in __package__ else "HoTools"
    module = import_module(
        f"{package_root}.OmniNode.NodeTree.Function.physicsWorld.{module_name}"
    )
    value = getattr(module, name)
    globals()[name] = value
    return value


def _mesh_object_poll(self, obj):
    return obj is not None and obj.type == "MESH"


# 这个文件只定义可保存到 Blender 数据块上的原始配置。
# 不在 PropertyGroup 里缓存运行时对象、顶点数组或经过矩阵/顶点组加工后的结果；
# 求解器和预览代码需要在各自运行时解析这些字段，并保持同一套语义。


class PG_Hotools_MeshCollision(PropertyGroup):
    """
    简单布料（XPBD）物理、逐顶点碰撞球、Pin 和自碰撞的持久化配置。

    消费约定：
    1. Mesh 物理解算输出由各 solver 写入自己的 GN 后置位移属性。
    2. radius 是逐顶点球基础半径；radius_vertex_group 留空表示所有顶点权重 1。
    3. 顶点组存在时，权重会被限制在 0..1；顶点不在组内或组名不存在时权重为 0。
    4. pin_enabled 关闭时没有 Pin 顶点；开启且 pin_vertex_group 留空时所有顶点 Pin。
    5. Pin 结果由 XPBD 求解器在 cache 重建时转成 inv_masses，模拟中不热更新。
    6. mass 只用于自碰撞的质量加权，不是通用刚体质量；对象间碰撞仍走主/被碰撞组。
    7. 预览绘制逐顶点球时使用 evaluated mesh 顶点位置，并按同一顶点组语义计算半径和 Pin 颜色。
    """
    mc2_base_pose_proxy: PointerProperty(
        type=bpy.types.Object,
        name="BasePose只读对象",
        description="MC2每帧只读这个Mesh对象的骨架/修改器变形结果作为基础姿态；不要指向当前物理写入对象",
        poll=_mesh_object_poll,
    )  # type: ignore
    enabled: BoolProperty(
        name="启用",
        description="启用简单布料（XPBD）模拟",
        default=False,
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="逐顶点碰撞球的基础半径；最终半径会乘以顶点组权重",
        default=0.02,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    radius_vertex_group: StringProperty(
        name="半径顶点组",
        description="用于缩放逐顶点碰撞半径的顶点组；留空时所有顶点使用完整半径",
        default="",
    )  # type: ignore
    pin_enabled: BoolProperty(
        name="Pin启用",
        description="启用简单布料Pin顶点；只在物理cache重建时读取，模拟过程中修改不会立即生效",
        default=False,
    )  # type: ignore
    pin_vertex_group: StringProperty(
        name="Pin顶点组",
        description="用于指定固定顶点的顶点组；启用Pin且留空时固定全部顶点",
        default="",
    )  # type: ignore
    self_collision_enabled: BoolProperty(
        name="自碰撞",
        description="启用当前网格内部的自碰撞检测；对象间碰撞仍然使用主/被碰撞组",
        default=False,
    )  # type: ignore
    self_collision_surface_thickness: FloatProperty(
        name="表面厚度",
        description="自碰撞接触厚度；这是接触包裹层，不是网格实际尺寸",
        default=0.005,
        min=0.0,
        soft_max=0.05,
    )  # type: ignore
    mass: FloatProperty(
        name="质量",
        description="自碰撞用布料质量系数；数值越大，自碰撞修正越保守",
        default=0.0,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    primary_collision_group: IntProperty(
        name="主碰撞组",
        description="这个网格的所有逐顶点碰撞球所属的主碰撞组",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    collided_by_groups: IntProperty(
        name="被碰撞组",
        description="允许哪些主碰撞组碰撞到这个网格的逐顶点碰撞球",
        default=0,
        min=0,
        max=_ALL_COLLISION_GROUPS_MASK,
    )  # type: ignore
