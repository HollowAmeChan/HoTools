"""公共 Field 持久 RNA 的纯数据 schema；不导入 bpy。"""

from .names import (
    FIELD_TYPE_WIND,
    VOLUME_SHAPE_BOX,
    VOLUME_SHAPE_SPHERE,
)


# ``update`` 是由 Blender 适配层解释的符号，不在纯数据层保存 Python 回调。
# ``update_policy`` 同时供 capability 元数据使用，避免属性契约在两处重复维护。
FIELD_RNA_FIELDS = (
    {
        "name": "enabled",
        "property": "bool",
        "update": "enabled",
        "update_policy": "每帧收集场规格；启用时补齐持久 UUID",
        "kwargs": {
            "name": "启用场",
            "description": "把这个 Empty 作为物理世界中的场源",
            "default": False,
        },
    },
    {
        "name": "field_id",
        "property": "string",
        "update": "visualization",
        "update_policy": "持久身份；显式创建或修复",
        "kwargs": {
            "name": "场 ID",
            "description": "持久 UUID；对象改名不会改变此身份",
            "default": "",
        },
    },
    {
        "name": "field_type",
        "property": "enum",
        "update": "visualization",
        "update_policy": "Field 类型与 generator 能力签名",
        "kwargs": {
            "name": "场类型",
            "description": "先选择场类型，再显示该类型的参数；V0 仅提供 Wind",
            "items": (
                (
                    FIELD_TYPE_WIND,
                    "风",
                    "由 Empty 局部 +Z 定义基础空气速度，并可叠加紊流",
                ),
            ),
            "default": FIELD_TYPE_WIND,
        },
    },
    {
        "name": "shape",
        "property": "enum",
        "update": "visualization",
        "update_policy": "场规格签名与预览",
        "kwargs": {
            "name": "体积形状",
            "description": "由 Empty 的单位局部边界和 matrix_world 定义",
            "items": (
                (VOLUME_SHAPE_SPHERE, "球形", "中心为 1，边界线性衰减到 0"),
                (VOLUME_SHAPE_BOX, "方形", "内部权重为 1，外部为 0，无衰减"),
            ),
            "default": VOLUME_SHAPE_SPHERE,
        },
    },
    {
        "name": "speed_mps",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 数值签名与预览",
        "kwargs": {
            "name": "风速 (m/s)",
            "description": "沿 Empty 局部 +Z 方向的基础空气速度",
            "default": 1.0,
            "min": 0.0,
            "soft_max": 100.0,
        },
    },
    {
        "name": "turbulence",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 数值签名与预览",
        "kwargs": {
            "name": "紊流",
            "description": "叠加时空噪声的连续强度；0 为纯定向风",
            "default": 0.0,
            "min": 0.0,
            "max": 1.0,
            "subtype": "FACTOR",
        },
    },
    {
        "name": "spatial_scale_m",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "空间尺度 (m)",
            "description": "紊流采样的基础空间尺度",
            "default": 1.0,
            "min": 1.0e-6,
            "soft_max": 100.0,
        },
    },
    {
        "name": "temporal_frequency_hz",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "时间频率",
            "description": "紊流随物理时间变化的频率（Hz）",
            "default": 0.5,
            "min": 0.0,
            "soft_max": 20.0,
        },
    },
    {
        "name": "octaves",
        "property": "int",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "叠加层数",
            "description": "紊流噪声的 octave 数量",
            "default": 3,
            "min": 1,
            "max": 8,
        },
    },
    {
        "name": "lacunarity",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "频率倍率",
            "description": "相邻 octave 的空间频率倍率",
            "default": 2.0,
            "min": 1.0,
            "max": 8.0,
        },
    },
    {
        "name": "gain",
        "property": "float",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "幅值衰减",
            "description": "相邻 octave 的幅值倍率",
            "default": 0.5,
            "min": 0.0,
            "max": 1.0,
            "subtype": "FACTOR",
        },
    },
    {
        "name": "seed_u32",
        "property": "int",
        "update": "visualization",
        "update_policy": "WindV0 配置签名与预览",
        "kwargs": {
            "name": "随机种子",
            "description": "确定性紊流种子；RNA 首版开放非负 31 位范围",
            "default": 0,
            "min": 0,
            "max": 0x7FFFFFFF,
        },
    },
    {
        "name": "blend_weight",
        "property": "float",
        "update": "visualization",
        "update_policy": "场合成数值签名与预览",
        "kwargs": {
            "name": "混合权重",
            "description": "这个场参与加法合成时的权重",
            "default": 1.0,
            "min": 0.0,
            "soft_max": 4.0,
        },
    },
    {
        "name": "priority",
        "property": "int",
        "update": "visualization",
        "update_policy": "场合成顺序签名与预览",
        "kwargs": {
            "name": "优先级",
            "description": "多个场按优先级、再按场 ID 确定遍历顺序",
            "default": 0,
        },
    },
    {
        "name": "scope_solver_ids",
        "property": "string",
        "update": "visualization",
        "update_policy": "场作用域签名",
        "kwargs": {
            "name": "解算器范围",
            "description": "逗号或换行分隔的 consumer ID；留空表示不限制",
            "default": "",
        },
    },
    {
        "name": "scope_collection_ids",
        "property": "string",
        "update": "visualization",
        "update_policy": "场作用域签名",
        "kwargs": {
            "name": "集合范围",
            "description": "逗号或换行分隔的 Blender Collection 名称；留空表示不限制",
            "default": "",
        },
    },
    {
        "name": "scope_include_ids",
        "property": "string",
        "update": "visualization",
        "update_policy": "场作用域签名",
        "kwargs": {
            "name": "包含对象",
            "description": "逗号或换行分隔的对象名称白名单；骨布料使用骨架对象名称",
            "default": "",
        },
    },
    {
        "name": "scope_exclude_ids",
        "property": "string",
        "update": "visualization",
        "update_policy": "场作用域签名",
        "kwargs": {
            "name": "排除对象",
            "description": "逗号或换行分隔的对象名称黑名单；骨布料使用骨架对象名称",
            "default": "",
        },
    },
    {
        "name": "scope_collision_groups",
        "property": "string",
        "update": "visualization",
        "update_policy": "场作用域签名",
        "kwargs": {
            "name": "碰撞组范围",
            "description": "逗号分隔的碰撞组编号（1 到 16）；留空表示不限制",
            "default": "",
        },
    },
)


__all__ = ["FIELD_RNA_FIELDS"]
