from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import PropertyGroup

from .collisionUtils import _ALL_COLLISION_GROUPS_MASK, _COLLISION_GROUP_COUNT


# 这个文件只定义可保存到 Blender 数据块上的原始配置。
# 不在 PropertyGroup 里缓存运行时对象、顶点数组或经过矩阵/顶点组加工后的结果；
# 求解器和预览代码需要在各自运行时解析这些字段，并保持同一套语义。


class PG_Hotools_BoneCollision(PropertyGroup):
    """
    骨骼碰撞与 SpringBone 固定标记的持久化配置。

    消费约定：
    1. 碰撞体真实世界空间数据由物理节点按 PoseBone 矩阵解析。
    2. spring_root 是链 root 标记；解算中链 root 始终硬 Pin。
    3. 非 root 骨骼是否 Pin 由 pin 字段决定，只在物理 cache 重建时读取。
    4. 预览侧用 spring_root 或 pin 显示 Pin 状态，和解算语义保持一致。
    """

    spring_root: BoolProperty(
        name="Spring Root",
        description="把这根骨骼标记为一条SpringBone链的根；整骨架面板会批量管理这个标记",
        default=False,
    )  # type: ignore
    pin: BoolProperty(
        name="Pin",
        description="固定这根骨骼，让物理解算保持当前姿态；Spring Root 在解算中始终视为Pin，即使这里关闭也不会被推动",
        default=False,
    )  # type: ignore
    collision_type: EnumProperty(
        name="碰撞体",
        description="这根骨骼携带的物理碰撞体类型；当前只负责持久化与编辑",
        items=[
            ("NONE", "无", "不作为物理碰撞体"),
            ("SPHERE", "球体", "以骨骼局部偏移为中心的球形碰撞体"),
            ("CAPSULE", "胶囊", "沿骨骼局部Y轴延伸的胶囊碰撞体"),
        ],
        default="NONE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.05,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    length: FloatProperty(
        name="长度",
        description="胶囊中段长度，球体类型会忽略这个参数",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset: FloatVectorProperty(
        name="中心偏移",
        description="碰撞体中心相对骨骼局部空间的偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore
    primary_collision_group: IntProperty(
        name="主碰撞组",
        description="这根碰撞体所属的主碰撞组，叠加显示颜色由它决定",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    collided_by_groups: IntProperty(
        name="被碰撞组",
        description="允许哪些主碰撞组碰撞到这根碰撞体的位掩码",
        default=0,
        min=0,
        max=_ALL_COLLISION_GROUPS_MASK,
    )  # type: ignore


class PG_Hotools_ObjectCollision(PropertyGroup):
    """
    Object 级被动碰撞体的持久化配置。

    消费约定：
    真实碰撞体由 Object.matrix_world、offset、radius、length 和 collision_type
    在运行时解析；属性层只保存用户输入，不保存世界空间快照。
    """

    collision_type: EnumProperty(
        name="碰撞体",
        description="这个Object携带的被动碰撞体类型",
        items=[
            ("NONE", "无", "不作为被动碰撞体"),
            ("SPHERE", "球体", "以Object局部偏移为中心的球形碰撞体"),
            ("CAPSULE", "胶囊", "沿Object局部Y轴延伸的胶囊碰撞体"),
        ],
        default="NONE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="碰撞体半径，使用Blender单位",
        default=0.05,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    length: FloatProperty(
        name="长度",
        description="胶囊中段长度，球体类型会忽略这个参数",
        default=0.2,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore
    offset: FloatVectorProperty(
        name="中心偏移",
        description="碰撞体中心相对Object局部空间的偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore
    primary_collision_group: IntProperty(
        name="主碰撞组",
        description="这个被动碰撞体所属的主碰撞组，叠加显示颜色由它决定",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore


class PG_Hotools_MeshCollision(PropertyGroup):
    """
    网格 XPBD 物理、逐顶点碰撞球和 Pin 的持久化配置。

    消费约定：
    1. output_shape_key 是目标形态键名；XPBD 节点运行时读取它，缺失时自动创建。
    2. radius 是逐顶点球基础半径；radius_vertex_group 留空表示所有顶点权重 1。
    3. 顶点组存在时，权重会被限制在 0..1；顶点不在组内或组名不存在时权重为 0。
    4. pin_enabled 关闭时没有 Pin 顶点；开启且 pin_vertex_group 留空时所有顶点 Pin。
    5. Pin 结果由 XPBD 求解器在 cache 重建时转成 inv_masses，模拟中不热更新。
    6. 预览绘制逐顶点球时使用 evaluated mesh 顶点位置，并按同一顶点组语义计算半径和 Pin 颜色。
    """

    output_shape_key: StringProperty(
        name="物理形态键",
        description="XPBD网格物理解算写入的目标形态键；不存在时会自动创建",
        default="MeshPhysics",
    )  # type: ignore
    enabled: BoolProperty(
        name="启用",
        description="启用XPBD网格逐顶点碰撞球",
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
        description="启用XPBD网格Pin顶点；只在物理cache重建时读取，模拟过程中修改不会立即生效",
        default=False,
    )  # type: ignore
    pin_vertex_group: StringProperty(
        name="Pin顶点组",
        description="用于指定固定顶点的顶点组；启用Pin且留空时固定全部顶点",
        default="",
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
