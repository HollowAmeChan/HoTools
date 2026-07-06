import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .physicsUtils import _ALL_COLLISION_GROUPS_MASK, _COLLISION_GROUP_COUNT


def _mesh_object_poll(self, obj):
    return obj is not None and obj.type == "MESH"


# 这个文件只定义可保存到 Blender 数据块上的原始配置。
# 不在 PropertyGroup 里缓存运行时对象、顶点数组或经过矩阵/顶点组加工后的结果；
# 求解器和预览代码需要在各自运行时解析这些字段，并保持同一套语义。


class PG_Hotools_BoneCollision(PropertyGroup):
    """
    骨骼碰撞与 SpringBone 固定标记的持久化配置。

    消费约定：
    1. 碰撞体真实世界空间数据由物理节点按 PoseBone 矩阵解析。
    2. 链 root 由物理节点输入的骨骼决定（“从根获取骨链”填入的骨即 root），解算中链 root 始终硬 Pin，与骨骼上的标记无关。
    3. 非 root 骨骼是否 Pin 由 pin 字段决定，只在物理 cache 重建时读取。
    4. 预览侧用 pin 显示 Pin 状态。
    5. 骨骼级碰撞只定义球体和胶囊；平面和长方体碰撞需要完整 Object 变换和父级继承，必须用 Object 级碰撞体表达。
    """

    pin: BoolProperty(
        name="Pin",
        description="固定这根骨骼，让物理解算保持当前姿态；链 root 由物理节点输入决定，在解算中始终视为Pin",
        default=False,
    )  # type: ignore
    collision_type: EnumProperty(
        name="碰撞体",
        description="这根骨骼携带的物理碰撞体类型；骨骼级当前只支持球体和胶囊，平面和长方体请使用Object级碰撞体",
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
    Object 级简单碰撞体的持久化配置。
    ...（消费约定同前）
    """

    enabled: BoolProperty(
        name="启用",
        description="将此对象识别为简单碰撞体",
        default=False,
    )  # type: ignore

    collision_type: EnumProperty(
        name="碰撞体",
        description="这个Object携带的简单碰撞体类型",
        items=[
            ("NONE", "无", "不作为简单碰撞体"),
            ("SPHERE", "球体", "以Object局部偏移为中心的球形碰撞体"),
            ("CAPSULE", "胶囊", "沿Object局部Y轴延伸的胶囊碰撞体"),
            ("PLANE", "平面", "以Object局部XY平面为无限碰撞平面；运行时必须用Object.matrix_world求世界原点、切线和法线"),
            ("BOX", "长方体", "以Object局部偏移为中心、按局部XYZ长度定义的有向长方体；运行时必须用Object.matrix_world求世界角点"),
        ],
        default="NONE",
    )  # type: ignore
    radius: FloatProperty(
        name="半径",
        description="球体和胶囊半径，使用Blender单位；平面类型不把它作为真实碰撞厚度",
        default=0.05,
        min=0.0,
        soft_max=1.0,
    )  # type: ignore
    length: FloatProperty(
        name="长度",
        description="胶囊中段长度；平面类型把它作为叠加层方片的预览尺寸，不改变无限平面的物理语义",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )  # type: ignore
    offset: FloatVectorProperty(
        name="局部偏移",
        description="球体/胶囊/长方体中心或平面原点相对Object局部空间的偏移",
        size=3,
        subtype="XYZ",
        default=(0.0, 0.0, 0.0),
    )  # type: ignore
    box_size: FloatVectorProperty(
        name="XYZ长度",
        description="长方体在Object局部X/Y/Z方向上的全尺寸；实际世界尺寸和方向必须通过Object.matrix_world解析",
        size=3,
        subtype="XYZ",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        soft_max=10.0,
    )  # type: ignore
    primary_collision_group: IntProperty(
        name="主碰撞组",
        description="这个简单碰撞体所属的主碰撞组，叠加显示颜色由它决定",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore


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


class PG_Hotools_RigidBody(PropertyGroup):
    """
    Object 级刚体物理配置。

    消费约定：
    1. body_type 决定刚体是动态（受力模拟）、静态（固定碰撞体）还是运动学（由动画驱动）。
    2. mass 只对 DYNAMIC 有效；STATIC / KINEMATIC 不消耗质量。
    3. friction / restitution 影响碰撞响应，语义与 Jolt 等物理引擎一致。
    4. collision_group 与现有碰撞组体系对齐，值域 1..16。
    5. shape_type 决定刚体的碰撞形状；AUTO 时先尝试读 hotools_object_collision，
       失败则按 Object.dimensions 的 AABB 包围盒生成 BOX。
    6. Jolt BodyID 等 native handle 只存在于 runtime solver slot，不写回到此属性组。
    7. 节点图通过 hotools_rigid_body.body_type 等字段读取，视为只读。
    """

    enabled: BoolProperty(
        name="启用",
        description="将此对象纳入刚体模拟",
        default=False,
    )  # type: ignore

    body_type: EnumProperty(
        name="刚体类型",
        description="刚体的运动学类型",
        items=[
            ("DYNAMIC",   "动态",   "受重力和碰撞力驱动；需要设置质量"),
            ("STATIC",    "静态",   "固定不动的碰撞体；不响应外力"),
            ("KINEMATIC", "运动学", "由动画/节点驱动位移，不受物理力影响但会推动其他刚体"),
        ],
        default="DYNAMIC",
    )  # type: ignore

    mass: FloatProperty(
        name="质量",
        description="动态刚体的质量（千克）；静态和运动学类型忽略此值",
        default=1.0,
        min=0.001,
        soft_max=1000.0,
    )  # type: ignore

    friction: FloatProperty(
        name="摩擦",
        description="碰撞面摩擦系数；0=无摩擦，1=最大摩擦",
        default=0.5,
        min=0.0,
        max=1.0,
    )  # type: ignore

    restitution: FloatProperty(
        name="弹性",
        description="碰撞弹性系数（恢复系数）；0=完全非弹性，1=完全弹性",
        default=0.0,
        min=0.0,
        max=1.0,
    )  # type: ignore

    collision_group: IntProperty(
        name="碰撞组",
        description="刚体所属碰撞组，与现有碰撞组体系对齐（1..16）",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore

    # ── 碰撞形状 ────────────────────────────────────────────────────────────

    shape_type: EnumProperty(
        name="形状",
        description="刚体碰撞形状类型",
        items=[
            ("SPHERE",  "球体",   "球形；由半径决定大小"),
            ("CAPSULE", "胶囊",   "胶囊；由半径和高度决定大小"),
            ("BOX",     "长方体", "轴对齐长方体；由三轴半尺寸决定大小"),
        ],
        default="SPHERE",
    )  # type: ignore

    shape_radius: FloatProperty(
        name="半径",
        description="球体半径（SPHERE）或胶囊截面半径（CAPSULE）",
        default=0.5,
        min=0.001,
        soft_max=10.0,
        unit="LENGTH",
    )  # type: ignore

    shape_half_height: FloatProperty(
        name="半高",
        description="胶囊中段的半长（CAPSULE）；总高度 = 半高×2 + 半径×2",
        default=0.5,
        min=0.001,
        soft_max=10.0,
        unit="LENGTH",
    )  # type: ignore

    shape_half_extents: FloatVectorProperty(
        name="半尺寸",
        description="长方体在 X/Y/Z 轴的半尺寸（BOX）",
        default=(0.5, 0.5, 0.5),
        min=0.001,
        soft_max=10.0,
        size=3,
        unit="LENGTH",
        subtype="XYZ",
    )  # type: ignore


class PG_Hotools_RigidConstraint(PropertyGroup):
    """
    Empty 对象上的刚体约束配置。

    消费约定：
    1. 约束点载体为 Empty 对象；Empty.matrix_world 表示约束 anchor frame。
    2. target_a / target_b 指向参与约束的两个刚体对象（可以其中之一为 None 表示固定到世界）。
    3. constraint_type 使用 OmniNode 自己的名字；Jolt adapter 负责映射到对应 Jolt constraint 子类。
    4. Jolt ConstraintID 等 native handle 只存在于 runtime solver slot，不写回到此属性组。
    5. 节点图通过 hotools_rigid_constraint.constraint_type 等字段读取，视为只读。
    """

    enabled: BoolProperty(
        name="启用",
        description="将此 Empty 对象识别为刚体约束点",
        default=False,
    )  # type: ignore

    constraint_type: EnumProperty(
        name="约束类型",
        description="约束的自由度限制方式",
        items=[
            ("FIXED",   "固定",   "完全锁定两个刚体之间的相对运动"),
            ("HINGE",   "铰链",   "绕约束锚点 Z 轴允许旋转，限制其余自由度"),
            ("SLIDER",  "滑动",   "允许沿约束锚点 Z 轴平移，限制旋转"),
            ("CONE",    "锥形",   "允许在锥角范围内摆动，限制平移"),
            ("POINT",   "点约束", "仅锁定位置，允许任意旋转（球窝关节）"),
        ],
        default="FIXED",
    )  # type: ignore

    target_a: PointerProperty(
        type=bpy.types.Object,
        name="刚体 A",
        description="约束的第一个刚体目标；留空表示约束到世界原点",
    )  # type: ignore

    target_b: PointerProperty(
        type=bpy.types.Object,
        name="刚体 B",
        description="约束的第二个刚体目标；留空表示约束到世界原点",
    )  # type: ignore
