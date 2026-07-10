import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import PropertyGroup

from .physicsUtils import _ALL_COLLISION_GROUPS_MASK, _COLLISION_GROUP_COUNT

_PI = 3.141592653589793


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
    4. rigid_collision_group / rigid_collides_with_groups 是刚体自己的过滤组，不复用简单碰撞的组状态。
    5. shape_type 决定刚体碰撞形状；shape_offset / shape_rotation 表示 shape 相对 Object 原点的局部偏移。
    6. 速度、阻尼、CCD、睡眠和轴锁定等字段在刚体注册到 Jolt 时消费；运行中热改需要 solver 同步策略支持。
    7. Jolt BodyID 等 native handle 只存在于 runtime solver slot，不写回到此属性组。
    8. 节点图通过 hotools_rigid_body.body_type 等字段读取，视为只读。
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

    rigid_collision_group: IntProperty(
        name="刚体碰撞组",
        description="刚体所属过滤组，仅在刚体/Jolt 求解器内部使用（1..16）",
        default=1,
        min=1,
        max=_COLLISION_GROUP_COUNT,
    )  # type: ignore
    rigid_collides_with_groups: IntProperty(
        name="可碰刚体组",
        description="允许哪些刚体碰撞组与此刚体碰撞；两个刚体需互相允许才会碰撞",
        default=_ALL_COLLISION_GROUPS_MASK,
        min=0,
        max=_ALL_COLLISION_GROUPS_MASK,
    )  # type: ignore

    # ── 碰撞形状 ────────────────────────────────────────────────────────────

    shape_type: EnumProperty(
        name="形状",
        description="刚体碰撞形状类型",
        items=[
            ("SPHERE",  "球体",   "球形；由半径决定大小"),
            ("CAPSULE", "胶囊",   "胶囊；由半径和高度决定大小"),
            ("CYLINDER", "圆柱",  "圆柱；局部Y轴为高度方向"),
            ("TAPERED_CAPSULE", "锥形胶囊", "两端半径可不同的胶囊；局部Y轴为高度方向"),
            ("TAPERED_CYLINDER", "锥形圆柱", "两端半径可不同的圆柱；局部Y轴为高度方向"),
            ("PLANE",   "平面",   "无限静态平面；局部XY为平面，局部Z为法线"),
            ("BOX",     "长方体", "轴对齐长方体；由三轴半尺寸决定大小"),
        ],
        default="SPHERE",
    )  # type: ignore

    shape_radius: FloatProperty(
        name="半径",
        description="球体半径，或胶囊/圆柱截面半径",
        default=0.5,
        min=0.001,
        soft_max=10.0,
        unit="LENGTH",
    )  # type: ignore

    shape_half_height: FloatProperty(
        name="半高",
        description="沿局部Y轴的半长；胶囊总高度 = 半高×2 + 半径×2",
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

    shape_plane_half_extent: FloatProperty(
        name="平面范围",
        description="Jolt PlaneShape broadphase/debug 半范围；物理平面本身无厚度",
        default=10.0,
        min=1.0,
        soft_max=1000.0,
        unit="LENGTH",
    )  # type: ignore

    shape_top_radius: FloatProperty(
        name="顶部半径",
        description="锥形胶囊/锥形圆柱在局部 +Y 端的半径",
        default=0.5,
        min=0.001,
        soft_max=10.0,
        unit="LENGTH",
    )  # type: ignore

    shape_bottom_radius: FloatProperty(
        name="底部半径",
        description="锥形胶囊/锥形圆柱在局部 -Y 端的半径",
        default=0.3,
        min=0.001,
        soft_max=10.0,
        unit="LENGTH",
    )  # type: ignore

    shape_convex_radius: FloatProperty(
        name="凸半径",
        description="Jolt convex radius；用于圆柱/锥形圆柱边缘圆角和接触稳定性",
        default=0.05,
        min=0.0,
        soft_max=1.0,
        unit="LENGTH",
    )  # type: ignore

    shape_offset: FloatVectorProperty(
        name="局部偏移",
        description="碰撞形状相对Object原点的局部偏移",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="LENGTH",
        subtype="XYZ",
    )  # type: ignore

    shape_rotation: FloatVectorProperty(
        name="局部旋转",
        description="碰撞形状相对Object旋转的局部欧拉旋转",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="ROTATION",
        subtype="EULER",
    )  # type: ignore

    # ── 动力学 ─────────────────────────────────────────────────────────────

    linear_velocity: FloatVectorProperty(
        name="线速度",
        description="动态刚体注册到Jolt时的初始世界线速度",
        default=(0.0, 0.0, 0.0),
        size=3,
        subtype="XYZ",
    )  # type: ignore

    angular_velocity: FloatVectorProperty(
        name="角速度",
        description="动态刚体注册到Jolt时的初始世界角速度（rad/s）",
        default=(0.0, 0.0, 0.0),
        size=3,
        subtype="XYZ",
    )  # type: ignore

    linear_damping: FloatProperty(
        name="线阻尼",
        description="线速度阻尼；Jolt建议范围0..1，通常接近0",
        default=0.05,
        min=0.0,
        max=1.0,
    )  # type: ignore

    angular_damping: FloatProperty(
        name="角阻尼",
        description="角速度阻尼；Jolt建议范围0..1，通常接近0",
        default=0.05,
        min=0.0,
        max=1.0,
    )  # type: ignore

    gravity_factor: FloatProperty(
        name="重力倍率",
        description="该刚体受到的世界重力倍率；0表示不受重力",
        default=1.0,
        soft_min=0.0,
        soft_max=2.0,
    )  # type: ignore

    allow_sleeping: BoolProperty(
        name="允许睡眠",
        description="允许Jolt在刚体静止后让它进入睡眠以节省计算",
        default=True,
    )  # type: ignore

    motion_quality: EnumProperty(
        name="碰撞质量",
        description="高速刚体的碰撞检测质量",
        items=[
            ("DISCRETE",    "离散", "普通离散步进，速度过高时可能穿透薄物体"),
            ("LINEAR_CAST", "CCD",  "使用线性投射降低高速穿透风险，成本更高"),
        ],
        default="DISCRETE",
    )  # type: ignore

    max_linear_velocity: FloatProperty(
        name="最大线速度",
        description="Jolt允许该刚体达到的最大线速度",
        default=500.0,
        min=0.0,
        soft_max=500.0,
    )  # type: ignore

    max_angular_velocity: FloatProperty(
        name="最大角速度",
        description="Jolt允许该刚体达到的最大角速度（rad/s）",
        default=47.1239,
        min=0.0,
        soft_max=100.0,
    )  # type: ignore

    is_sensor: BoolProperty(
        name="传感器",
        description="作为触发体接收接触事件，但不产生碰撞响应；事件输出接入前仅作为Jolt body设置",
        default=False,
    )  # type: ignore

    collide_kinematic_vs_non_dynamic: BoolProperty(
        name="运动学碰静态",
        description="允许运动学体和静态/运动学体生成接触点；大型传感器会显著增加接触成本",
        default=False,
    )  # type: ignore

    lock_linear_x: BoolProperty(name="锁定线性X", default=False)  # type: ignore
    lock_linear_y: BoolProperty(name="锁定线性Y", default=False)  # type: ignore
    lock_linear_z: BoolProperty(name="锁定线性Z", default=False)  # type: ignore
    lock_angular_x: BoolProperty(name="锁定角度X", default=False)  # type: ignore
    lock_angular_y: BoolProperty(name="锁定角度Y", default=False)  # type: ignore
    lock_angular_z: BoolProperty(name="锁定角度Z", default=False)  # type: ignore


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
            ("DISTANCE", "距离",  "限制两个锚点之间的最小和最大距离"),
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

    anchor_mode: EnumProperty(
        name="锚点模式",
        description="使用Empty共享世界锚点，或分别使用刚体A/B局部空间中的锚点frame",
        items=[
            ("SHARED_WORLD", "共享世界锚点", "两个刚体使用当前Empty的世界位置和旋转"),
            ("LOCAL_FRAMES", "独立局部Frame", "分别从刚体A/B局部点和局部旋转构造世界锚点frame"),
        ],
        default="SHARED_WORLD",
    )  # type: ignore

    local_point_a: FloatVectorProperty(
        name="A局部锚点",
        description="锚点相对刚体A Object局部空间的位置；A为空时按世界坐标解释",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="LENGTH",
        subtype="XYZ",
    )  # type: ignore

    local_rotation_a: FloatVectorProperty(
        name="A局部旋转",
        description="锚点frame相对刚体A Object局部空间的欧拉旋转",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="ROTATION",
        subtype="EULER",
    )  # type: ignore

    local_point_b: FloatVectorProperty(
        name="B局部锚点",
        description="锚点相对刚体B Object局部空间的位置；B为空时按世界坐标解释",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="LENGTH",
        subtype="XYZ",
    )  # type: ignore

    local_rotation_b: FloatVectorProperty(
        name="B局部旋转",
        description="锚点frame相对刚体B Object局部空间的欧拉旋转",
        default=(0.0, 0.0, 0.0),
        size=3,
        unit="ROTATION",
        subtype="EULER",
    )  # type: ignore

    # ── Jolt 通用 ConstraintSettings ───────────────────────────────────────

    disable_collisions: BoolProperty(
        name="禁用连接体碰撞",
        description="约束连接的两个刚体不再彼此碰撞；不影响它们与其他刚体的碰撞",
        default=True,
    )  # type: ignore

    breakable: BoolProperty(
        name="可断裂",
        description="当上一物理步的约束冲量超过阈值时禁用此约束",
        default=False,
    )  # type: ignore

    breaking_threshold: FloatProperty(
        name="断裂冲量阈值",
        description="约束断裂阈值，单位是Jolt每个物理步累计的lambda/冲量，不是力",
        default=1000.0,
        min=0.0,
        soft_max=10000.0,
    )  # type: ignore

    constraint_priority: IntProperty(
        name="求解优先级",
        description="Jolt约束求解优先级；更高数值会更优先满足",
        default=0,
        min=0,
    )  # type: ignore

    solver_velocity_steps: IntProperty(
        name="速度迭代覆盖",
        description="0表示使用物理世界默认速度迭代次数；非0会覆盖该约束所在岛的速度迭代下限",
        default=0,
        min=0,
        max=255,
    )  # type: ignore

    solver_position_steps: IntProperty(
        name="位置迭代覆盖",
        description="0表示使用物理世界默认位置迭代次数；非0会覆盖该约束所在岛的位置迭代下限",
        default=0,
        min=0,
        max=255,
    )  # type: ignore

    draw_constraint_size: FloatProperty(
        name="调试显示尺寸",
        description="Jolt debug renderer使用的约束显示尺寸；当前先作为调试可视化数据保留",
        default=1.0,
        min=0.0,
        soft_max=10.0,
    )  # type: ignore

    # ── Hinge / Slider 限制与弹簧 ──────────────────────────────────────────

    limit_enabled: BoolProperty(
        name="启用限制",
        description="为Hinge启用角度限制，或为Slider启用线性行程限制",
        default=False,
    )  # type: ignore

    angular_limit_min: FloatProperty(
        name="最小角度",
        description="Hinge最小旋转角度；范围[-π, 0]",
        default=-_PI,
        min=-_PI,
        max=0.0,
        unit="ROTATION",
    )  # type: ignore

    angular_limit_max: FloatProperty(
        name="最大角度",
        description="Hinge最大旋转角度；范围[0, π]",
        default=_PI,
        min=0.0,
        max=_PI,
        unit="ROTATION",
    )  # type: ignore

    linear_limit_min: FloatProperty(
        name="最小行程",
        description="Slider沿约束轴的最小位移",
        default=-1.0,
        unit="LENGTH",
    )  # type: ignore

    linear_limit_max: FloatProperty(
        name="最大行程",
        description="Slider沿约束轴的最大位移",
        default=1.0,
        unit="LENGTH",
    )  # type: ignore

    limit_spring_frequency: FloatProperty(
        name="限制弹簧频率",
        description="大于0时将硬限制变为软限制；单位Hz",
        default=0.0,
        min=0.0,
        soft_max=20.0,
    )  # type: ignore

    limit_spring_damping: FloatProperty(
        name="限制弹簧阻尼",
        description="限制弹簧阻尼比；0无阻尼，1约等于临界阻尼",
        default=0.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore

    # ── 摩擦与 Motor ──────────────────────────────────────────────────────

    max_friction_torque: FloatProperty(
        name="最大摩擦扭矩",
        description="Hinge未启用motor时用于阻碍旋转的最大摩擦扭矩",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
    )  # type: ignore

    max_friction_force: FloatProperty(
        name="最大摩擦力",
        description="Slider未启用motor时用于阻碍滑动的最大摩擦力",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
    )  # type: ignore

    motor_state: EnumProperty(
        name="Motor",
        description="Hinge或Slider motor状态",
        items=[
            ("OFF",      "关闭", "不驱动约束"),
            ("VELOCITY", "速度", "驱动到目标速度"),
            ("POSITION", "位置", "驱动到目标位置/角度"),
        ],
        default="OFF",
    )  # type: ignore

    motor_frequency: FloatProperty(
        name="Motor频率",
        description="Motor位置弹簧频率；单位Hz",
        default=2.0,
        min=0.0,
        soft_max=20.0,
    )  # type: ignore

    motor_damping: FloatProperty(
        name="Motor阻尼",
        description="Motor位置弹簧阻尼比",
        default=1.0,
        min=0.0,
        soft_max=2.0,
    )  # type: ignore

    motor_force_limit: FloatProperty(
        name="Motor力限制",
        description="Slider motor最大力；0表示使用Jolt默认无限制",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
    )  # type: ignore

    motor_torque_limit: FloatProperty(
        name="Motor扭矩限制",
        description="Hinge motor最大扭矩；0表示使用Jolt默认无限制",
        default=0.0,
        min=0.0,
        soft_max=1000.0,
    )  # type: ignore

    motor_target_angular_velocity: FloatProperty(
        name="目标角速度",
        description="Hinge速度motor目标角速度（rad/s）",
        default=0.0,
    )  # type: ignore

    motor_target_angle: FloatProperty(
        name="目标角度",
        description="Hinge位置motor目标角度",
        default=0.0,
        unit="ROTATION",
    )  # type: ignore

    motor_target_velocity: FloatProperty(
        name="目标线速度",
        description="Slider速度motor目标线速度",
        default=0.0,
    )  # type: ignore

    motor_target_position: FloatProperty(
        name="目标位置",
        description="Slider位置motor目标位移",
        default=0.0,
        unit="LENGTH",
    )  # type: ignore

    # ── Cone 专用 ──────────────────────────────────────────────────────────

    cone_half_angle: FloatProperty(
        name="半锥角",
        description="Cone约束允许的最大摆动半角；0保持旧行为",
        default=0.0,
        min=0.0,
        max=_PI,
        unit="ROTATION",
    )  # type: ignore

    # ── Distance 专用 ──────────────────────────────────────────────────────

    distance_min: FloatProperty(
        name="最小距离",
        description="Distance约束允许两个锚点保持的最小距离",
        default=0.0,
        min=0.0,
        unit="LENGTH",
    )  # type: ignore

    distance_max: FloatProperty(
        name="最大距离",
        description="Distance约束允许两个锚点保持的最大距离",
        default=1.0,
        min=0.0,
        unit="LENGTH",
    )  # type: ignore
