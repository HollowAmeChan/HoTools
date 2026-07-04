# -*- coding: utf-8 -*-
# 语义映射表：Blender 数据路径 → Unity 属性绑定信息
# 以及"FBX 能带走的轨道"过滤逻辑（用于 scan.py 排除）。

# Unity classID 常量（只列本模块用到的）
CLASS_GAME_OBJECT     = 1
CLASS_TRANSFORM       = 4
CLASS_SKINNED_MESH    = 137


# ── 已知属性映射表 ────────────────────────────────────────────
# key  : Blender fcurve 的 data_path（完整路径）
# value: (unity_attribute, unity_class_id, is_boolean)
#   unity_attribute  — Unity curve 的 attribute 字符串
#   unity_class_id   — 绑定目标组件的 classID
#   is_boolean       — True 时强制阶梯插值并将值钳到 0/1
#
# 需要新增已知映射时，在这里加一行即可，其余代码不用动。
KNOWN_MAP: dict[str, tuple[str, int, bool]] = {
    # mmd_tools：模型整体显隐开关
    "mmd_root.show_meshes": ("m_IsActive", CLASS_GAME_OBJECT, True),
}


def resolve(data_path: str, array_index: int) -> tuple[str, int, bool]:
    """把 Blender data_path 解析成 Unity 绑定三元组。

    对已知路径走映射表；未知路径生成占位属性名（leaf token），
    默认挂到 GameObject，供用户在 Unity 端手动重绑。

    返回: (attribute, class_id, is_boolean)
    """
    if data_path in KNOWN_MAP:
        return KNOWN_MAP[data_path]

    # 生成占位 attribute：取路径最后一个 token
    # e.g. "mmd_root.show_rigid_bodies" → "show_rigid_bodies"
    #      '["my_prop"]'                → "my_prop"
    attr = _leaf_token(data_path)
    if array_index > 0:
        attr = f"{attr}.{array_index}"
    return (attr, CLASS_GAME_OBJECT, False)


def _leaf_token(data_path: str) -> str:
    """从 data_path 取最末端的可读 token。"""
    path = data_path.strip()
    # ID 自定义属性：obj["prop"] 或 pose.bones["b"]["prop"]
    if path.endswith('"]'):
        start = path.rfind('["')
        if start != -1:
            return path[start + 2: -2]
    # RNA 属性：a.b.c → c
    parts = path.replace('"', '').replace("'", '').split('.')
    return parts[-1] if parts else path


# ── FBX 能带走的轨道：过滤模式 ────────────────────────────────
# 这些前缀/完整路径的 fcurve 由 FBX 导出器处理，不需要进本工具。
# scan.py 用 is_fbx_handled() 来决定是否跳过。

_EXCLUDED_PREFIXES: tuple[str, ...] = (
    # 物体变换（Object-level）
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
    "scale",
    # 骨骼变换（Pose bone）
    'pose.bones["',
    # 形态键（Mesh Shape Key）—— FBX 作为 BlendShape 导出
    'key_blocks["',
)


def is_fbx_handled(data_path: str) -> bool:
    """如果这条 fcurve 是 FBX 导出器已经处理的轨道，返回 True（应排除）。"""
    for prefix in _EXCLUDED_PREFIXES:
        if data_path.startswith(prefix):
            return True
    return False
