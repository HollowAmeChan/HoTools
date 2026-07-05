from ..OmniNodeSocketMapping import _OmniFolderPath, _OmniImageFormat,_OmniRegex, _OmniGlob, _OmniDatablock, _OmniModifierType, _OmniModifier, _OmniMaterialSlot, _OmniUVLayer, _OmniColorAttribute, _OmniVertexGroup, _OmniShapeKey, _OmniFloatCurve, _OmniColorCurve, _OmniBone
from ..FunctionNodeCore import omni
from bpy.types import NodeSocketVector
import ast
import bpy
from datetime import datetime
from typing import Any
import mathutils
from . import _Color


def _parse_custom_property_token(token: str):
    token = str(token or "").strip()
    if len(token) < 4 or token[0] != "[" or token[-1] != "]":
        return None

    try:
        key = ast.literal_eval(token[1:-1].strip())
    except Exception:
        return None
    return key if isinstance(key, str) else None


def _parse_datablock_property_path(property_name: str):
    property_name = str(property_name or "").strip()
    if property_name.startswith("."):
        property_name = property_name[1:]
    if not property_name:
        return []

    segments = []
    index = 0
    while index < len(property_name):
        if property_name[index] == ".":
            index += 1
            continue

        if property_name[index] == "[":
            end = property_name.find("]", index)
            if end < 0:
                return []
            key = _parse_custom_property_token(property_name[index:end + 1])
            if key is None:
                return []
            segments.append(("key", key))
            index = end + 1
            continue

        start = index
        while index < len(property_name) and property_name[index] not in ".[":
            index += 1
        name = property_name[start:index].strip()
        if not name:
            return []
        segments.append(("attr", name))

    return segments


def _resolve_datablock_property_owner(datablock, property_name: str):
    segments = _parse_datablock_property_path(property_name)
    if not segments:
        return None, None

    owner = datablock
    for access_type, access_name in segments[:-1]:
        if owner is None:
            return None, None
        try:
            owner = getattr(owner, access_name) if access_type == "attr" else owner[access_name]
        except Exception:
            return None, None

    return owner, segments[-1]


def _read_datablock_property(datablock, property_name: str):
    property_name = str(property_name or "").strip()
    if datablock is None or not property_name:
        return None

    owner, last_segment = _resolve_datablock_property_owner(datablock, property_name)
    if owner is None or last_segment is None:
        return None

    access_type, access_name = last_segment
    try:
        return owner[access_name] if access_type == "key" else getattr(owner, access_name)
    except Exception:
        return None


def _bone_socket_value(
    armature_obj: bpy.types.Object,
    bone_name: str,
    collection_root: str = "",
    collection_bones: list[str] = None,
):
    value = {
        "armature": armature_obj,
        "bone": bone_name,
    }
    if collection_root and collection_bones:
        value["bone_collection_root"] = str(collection_root)
        value["bone_collection"] = list(collection_bones)
    return value


def _resolve_bone_value(value):
    if not isinstance(value, dict):
        raise ValueError("bone input is empty or invalid")
    armature_obj = value.get("armature")
    bone_name = str(value.get("bone") or "").strip()
    if (
        not isinstance(armature_obj, bpy.types.Object)
        or armature_obj.type != "ARMATURE"
        or not bone_name
    ):
        raise ValueError("bone input is empty or invalid")
    if armature_obj.pose is None or armature_obj.pose.bones.get(bone_name) is None:
        raise ValueError(f"bone not found: {bone_name}")
    return armature_obj, bone_name


def _collect_bone_names(root_pose_bone, include_all_bones: bool) -> list[str]:
    names: list[str] = []

    if include_all_bones:
        def visit(pose_bone):
            names.append(pose_bone.name)
            for child in list(getattr(pose_bone, "children", []) or []):
                visit(child)

        visit(root_pose_bone)
        return names

    pose_bone = root_pose_bone
    while pose_bone is not None:
        names.append(pose_bone.name)
        children = list(getattr(pose_bone, "children", []) or [])
        pose_bone = children[0] if children else None
    return names

@omni(enable=True,
      bl_label="颜色",
      base_color=_Color.colorCat["GetData"],
      )
def colorInput(color: mathutils.Color) -> mathutils.Color:
    return color


@omni(enable=True,
      bl_label="矢量",
      base_color=_Color.colorCat["GetData"],
      )
def vectorInput(vec: NodeSocketVector) -> NodeSocketVector:
    return vec

@omni(enable=True,
      bl_label="整数",
      base_color=_Color.colorCat["GetData"],)
def intInput(v: int) -> int:
    return v

@omni(enable=True,
      bl_label="浮点数",
      base_color=_Color.colorCat["GetData"],)
def floatInput(v: float) -> float:
    return v

@omni(enable=True, 
      bl_label="布尔",
      base_color=_Color.colorCat["GetData"],)
def boolInput(v: bool) -> bool:
    return v

@omni(enable=True, 
      bl_label="字符串",
      base_color=_Color.colorCat["GetData"],)
def stringInput(v: str) -> str:
    return v

@omni(enable=True,
      bl_label="骨骼",
      base_color=_Color.colorCat["GetData"],
      _INPUT_NAME=["骨骼"],
      _OUTPUT_NAME=["骨骼"],
      omni_description="透传单个 Bone socket 值。用于把 Armature+Bone 选择作为普通数据接入后续节点。",
      )
def boneInput(v: _OmniBone) -> _OmniBone:
    armature_obj, bone_name = _resolve_bone_value(v)
    return _bone_socket_value(armature_obj, bone_name)

@omni(enable=True,
      bl_label="从根获取骨骼",
      base_color=_Color.colorCat["GetData"],
      is_output_node=False,
      _INPUT_NAME=["根骨骼", "包含全部骨"],
      _OUTPUT_NAME=["骨骼"],
      omni_description="""
      从根骨骼收集一组 Bone socket 值。

      “包含全部骨”开启时递归输出根骨下的全部子骨；关闭时遇到分叉只沿第一个子骨走到底。
      输出仍是普通骨骼列表，物理节点如果需要链结构会在内部自行解释。
      """,
      )
def bonesFromRoot(
    root_bone: _OmniBone,
    include_all_bones: bool = True,
) -> list[_OmniBone]:
    armature_obj, root_name = _resolve_bone_value(root_bone)
    root_pose_bone = armature_obj.pose.bones.get(root_name)
    if root_pose_bone is None:
        raise ValueError(f"bone not found: {root_name}")

    bone_names = _collect_bone_names(root_pose_bone, include_all_bones)
    return [
        _bone_socket_value(armature_obj, bone_name, root_name, bone_names)
        for bone_name in bone_names
    ]

@omni(enable=True,
      bl_label="当前时间",
      base_color=_Color.colorCat["GetData"],
      omni_description="输出当前系统本地时间，以及拆分后的年月日时分秒。",
      _OUTPUT_NAME=["时间", "年", "月", "日", "时", "分", "秒"],
      )
def currentTime() -> tuple[str, int, int, int, int, int, int]:
    now = datetime.now()
    return (
        now.strftime("%Y-%m-%d %H:%M:%S"),
        now.year,
        now.month,
        now.day,
        now.hour,
        now.minute,
        now.second,
    )

@omni(enable=True,
      bl_label="当前帧",
      base_color=_Color.colorCat["GetData"],
      omni_description="""
      输出当前场景的当前帧、帧范围和预览范围设置。
      在每帧运行模式下，OmniNode 会在 Blender 完成帧切换后运行，
      因此这里读到的是已经切换后的帧
      从起始帧 1 开始播放时，首次运行通常会读到第 2 帧。
      """,
      _OUTPUT_NAME=["当前帧", "帧开始", "帧结束", "预览开始", "预览结束", "启用预览范围"],
      )
def currentFrame() -> tuple[int, int, int, int, int, bool]:
    scene = bpy.context.scene
    return (
        scene.frame_current,
        scene.frame_start,
        scene.frame_end,
        scene.frame_preview_start,
        scene.frame_preview_end,
        scene.use_preview_range,
    )

@omni(enable=True,
      bl_label="场景帧率",
      base_color=_Color.colorCat["GetData"],
      omni_description="输出当前场景的实际帧率，以及每帧对应的秒数。",
      _OUTPUT_NAME=["帧率", "帧间隔"],
      )
def sceneFrameRate() -> tuple[float, float]:
    render = bpy.context.scene.render
    fps_base = render.fps_base if render.fps_base else 1.0
    fps = render.fps / fps_base
    return (
        fps,
        1.0 / fps if fps else 0.0,
    )

@omni(enable=True, 
      bl_label="文件路径",
      base_color=_Color.colorCat["GetData"],)
def filepathInput(v: _OmniFolderPath) -> _OmniFolderPath:
    return v

@omni(enable=True,
      bl_label="图像格式",
      base_color=_Color.colorCat["GetData"],)
def imageFormatInput(v:_OmniImageFormat) -> _OmniImageFormat:
    return v

@omni(enable=True,
      bl_label="Modifier Type",
      base_color=_Color.colorCat["GetData"],)
def modifierTypeInput(v: _OmniModifierType) -> _OmniModifierType:
    return v

@omni(enable=True,
      bl_label="修改器",
      base_color=_Color.colorCat["GetData"],)
def modifierInput(v: _OmniModifier) -> _OmniModifier:
    return v

@omni(enable=True,
      bl_label="Material Slot",
      base_color=_Color.colorCat["GetData"],)
def materialSlotInput(v: _OmniMaterialSlot) -> _OmniMaterialSlot:
    return v

@omni(enable=True,
      bl_label="UV槽",
      base_color=_Color.colorCat["GetData"],)
def uvLayerInput(v: _OmniUVLayer) -> _OmniUVLayer:
    return v

@omni(enable=True,
      bl_label="顶点色属性",
      base_color=_Color.colorCat["GetData"],)
def colorAttributeInput(v: _OmniColorAttribute) -> _OmniColorAttribute:
    return v

@omni(enable=True,
      bl_label="顶点组",
      base_color=_Color.colorCat["GetData"],)
def vertexGroupInput(v: _OmniVertexGroup) -> _OmniVertexGroup:
    if v is None or not isinstance(v, bpy.types.VertexGroup):
        raise ValueError("vertex group input is empty or invalid")
    return v

@omni(enable=True,
      bl_label="形态键",
      base_color=_Color.colorCat["GetData"],)
def shapeKeyInput(v: _OmniShapeKey) -> _OmniShapeKey:
    if not isinstance(v, dict):
        raise ValueError("shape key input is empty or invalid")
    obj = v.get("object")
    shape_key_name = str(v.get("shape_key") or "").strip()
    if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "MESH" or not shape_key_name:
        raise ValueError("shape key input is empty or invalid")
    return v

@omni(enable=True,
      bl_label="Datablock",
      base_color=_Color.colorCat["GetData"],)
def datablockInput(v: _OmniDatablock) -> _OmniDatablock:
    return v

@omni(enable=True,
      bl_label="获取Datablock数据",
      base_color=_Color.colorCat["GetData"],
      _INPUT_NAME=["数据块","属性名称"],
      )
def getDatablockProperty(datablock: _OmniDatablock, prop_name: str) -> Any:
    return _read_datablock_property(datablock, prop_name)

@omni(enable=True,
      bl_label="物体",
      bl_icon = "OBJECT_DATAMODE",
      base_color=_Color.colorCat["GetData"],
      )
def objectInput(obj: bpy.types.Object) -> bpy.types.Object:
    return obj

@omni(enable=True, 
      bl_label="集合",
      base_color=_Color.colorCat["GetData"],)
def collectionInput(col: bpy.types.Collection) -> bpy.types.Collection:
    return col

@omni(enable=True, 
      bl_label="材质",
      base_color=_Color.colorCat["GetData"],)
def materialInput(mat: bpy.types.Material) -> bpy.types.Material:
    return mat

@omni(enable=True,
      bl_label="图像",
      base_color=_Color.colorCat["GetData"],
      )
def imageInput(img: bpy.types.Image) -> bpy.types.Image:
    return img

@omni(enable=True, 
      bl_label="纹理",
      base_color=_Color.colorCat["GetData"],)
def textureInput(tex: bpy.types.Texture) -> bpy.types.Texture:
    return tex

@omni(enable=True,
      bl_label="浮点曲线",
      base_color=_Color.colorCat["GetData"],
      omni_description="透传浮点曲线数据。",
      _INPUT_NAME=["曲线"],
      _OUTPUT_NAME=["曲线"],
      )
def floatCurveInput(v: _OmniFloatCurve) -> _OmniFloatCurve:
    return v

@omni(enable=True,
      bl_label="颜色曲线",
      base_color=_Color.colorCat["GetData"],
      omni_description="透传颜色曲线数据。",
      _INPUT_NAME=["曲线"],
      _OUTPUT_NAME=["曲线"],
      )
def colorCurveInput(v: _OmniColorCurve) -> _OmniColorCurve:
    return v

_CURVE_PREVIEW_STACK_PRESETS = [
    {
        "name": "折线 / RGB 渐变",
        "description": "四个曲线输入都填入线性曲线，方便测试预览刷新。",
        "values": {
            "float_a": {
                "kind": "float_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 0.35, "y": 0.85},
                    {"x": 0.7, "y": 0.25},
                    {"x": 1.0, "y": 1.0},
                ],
            },
            "color_a": {
                "kind": "color_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "color": (1.0, 0.0, 0.0, 1.0)},
                    {"x": 0.5, "color": (0.0, 1.0, 0.0, 1.0)},
                    {"x": 1.0, "color": (0.0, 0.2, 1.0, 1.0)},
                ],
            },
            "float_b": {
                "kind": "float_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "y": 1.0},
                    {"x": 0.5, "y": 0.0},
                    {"x": 1.0, "y": 1.0},
                ],
            },
            "color_b": {
                "kind": "color_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "color": (0.0, 0.0, 0.0, 1.0)},
                    {"x": 0.5, "color": (1.0, 0.8, 0.0, 1.0)},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0)},
                ],
            },
        },
    },
    {
        "name": "阶梯 / 重复",
        "description": "使用常量插值和重复/镜像越界，方便观察曲线形状变化。",
        "values": {
            "float_a": {
                "kind": "float_curve",
                "interpolation": "CONSTANT",
                "extend": "REPEAT",
                "points": [
                    {"x": 0.0, "y": -0.2},
                    {"x": 0.25, "y": 0.8},
                    {"x": 0.6, "y": 0.1},
                    {"x": 1.0, "y": 1.2},
                ],
            },
            "color_a": {
                "kind": "color_curve",
                "interpolation": "CONSTANT",
                "extend": "REPEAT",
                "points": [
                    {"x": 0.0, "color": (1.0, 0.1, 0.1, 1.0)},
                    {"x": 0.33, "color": (0.1, 1.0, 0.1, 1.0)},
                    {"x": 0.66, "color": (0.1, 0.2, 1.0, 1.0)},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0)},
                ],
            },
            "float_b": {
                "kind": "float_curve",
                "interpolation": "CONSTANT",
                "extend": "MIRROR",
                "points": [
                    {"x": 0.0, "y": 1.0},
                    {"x": 0.25, "y": -0.35},
                    {"x": 0.6, "y": 0.55},
                    {"x": 1.0, "y": -0.1},
                ],
            },
            "color_b": {
                "kind": "color_curve",
                "interpolation": "CONSTANT",
                "extend": "REPEAT",
                "points": [
                    {"x": 0.0, "color": (0.0, 0.0, 0.0, 1.0)},
                    {"x": 0.33, "color": (1.0, 0.8, 0.0, 1.0)},
                    {"x": 0.66, "color": (0.7, 0.0, 1.0, 1.0)},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0)},
                ],
            },
        },
    },
    {
        "name": "反向 / 高低范围",
        "description": "数值范围更大，方便测试坐标轴自适应。",
        "values": {
            "float_a": {
                "kind": "float_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "y": 1.5},
                    {"x": 0.4, "y": -1.0},
                    {"x": 1.0, "y": 0.3},
                ],
            },
            "color_a": {
                "kind": "color_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "color": (0.0, 0.0, 1.0, 1.0)},
                    {"x": 0.5, "color": (1.0, 0.0, 1.0, 1.0)},
                    {"x": 1.0, "color": (1.0, 0.0, 0.0, 1.0)},
                ],
            },
            "float_b": {
                "kind": "float_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "y": -1.0},
                    {"x": 0.5, "y": 1.4},
                    {"x": 1.0, "y": -0.6},
                ],
            },
            "color_b": {
                "kind": "color_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "color": (1.0, 1.0, 1.0, 1.0)},
                    {"x": 0.5, "color": (0.0, 0.6, 1.0, 1.0)},
                    {"x": 1.0, "color": (0.0, 0.0, 0.0, 1.0)},
                ],
            },
        },
    },
    {
        "name": "点插值 / 手柄",
        "description": "测试每个控制点自己的插值模式和手柄数据。",
        "values": {
            "float_a": {
                "kind": "float_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "y": 0.0, "interpolation": "CONSTANT"},
                    {"x": 0.28, "y": 0.8, "interpolation": "BEZIER", "right_handle_type": "FREE", "right_tangent": -1.8, "right_weight": 0.7},
                    {"x": 0.72, "y": -0.35, "interpolation": "LINEAR", "left_handle_type": "FREE", "left_tangent": -1.8, "left_weight": 0.7},
                    {"x": 1.0, "y": 1.0, "interpolation": "LINEAR"},
                ],
            },
            "color_a": {
                "kind": "color_curve",
                "interpolation": "LINEAR",
                "extend": "CLAMP",
                "points": [
                    {"x": 0.0, "color": (1.0, 0.0, 0.0, 1.0), "interpolation": "BEZIER", "right_handle_type": "FREE", "right_tangent": (-2.0, 2.0, 0.0, 0.0), "right_weight": 0.55},
                    {"x": 0.4, "color": (0.0, 1.0, 0.0, 1.0), "interpolation": "CONSTANT", "left_handle_type": "FREE", "left_tangent": (-2.0, 2.0, 0.0, 0.0), "left_weight": 0.55},
                    {"x": 0.7, "color": (0.0, 0.2, 1.0, 1.0), "interpolation": "LINEAR"},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0), "interpolation": "LINEAR"},
                ],
            },
            "float_b": {
                "kind": "float_curve",
                "interpolation": "BEZIER",
                "extend": "MIRROR",
                "points": [
                    {"x": 0.0, "y": -0.7, "interpolation": "BEZIER", "right_handle_type": "AUTO"},
                    {"x": 0.5, "y": 1.2, "interpolation": "BEZIER", "left_handle_type": "AUTO", "right_handle_type": "AUTO"},
                    {"x": 1.0, "y": -0.7, "interpolation": "BEZIER", "left_handle_type": "AUTO"},
                ],
            },
            "color_b": {
                "kind": "color_curve",
                "interpolation": "CONSTANT",
                "extend": "REPEAT",
                "points": [
                    {"x": 0.0, "color": (0.0, 0.0, 0.0, 1.0), "interpolation": "CONSTANT"},
                    {"x": 0.25, "color": (1.0, 0.0, 0.0, 1.0), "interpolation": "CONSTANT"},
                    {"x": 0.5, "color": (0.0, 1.0, 0.0, 1.0), "interpolation": "CONSTANT"},
                    {"x": 0.75, "color": (0.0, 0.0, 1.0, 1.0), "interpolation": "CONSTANT"},
                    {"x": 1.0, "color": (1.0, 1.0, 1.0, 1.0), "interpolation": "LINEAR"},
                ],
            },
        },
    },
]

@omni(enable=True,
      bl_label="测试多曲线预览",
      base_color=_Color.colorCat["GetData"],
      omni_description="用于测试同一个节点上多个曲线预览的从上到下排列。",
      _INPUT_NAME=["浮点曲线 A", "颜色曲线 A", "浮点曲线 B", "颜色曲线 B"],
      _OUTPUT_NAME=["浮点曲线", "颜色曲线"],
      omni_presets=_CURVE_PREVIEW_STACK_PRESETS,
      )
def curvePreviewStackTest(
        float_a: _OmniFloatCurve,
        color_a: _OmniColorCurve,
        float_b: _OmniFloatCurve,
        color_b: _OmniColorCurve,
) -> tuple[_OmniFloatCurve, _OmniColorCurve]:
    return float_a or float_b, color_a or color_b

# @meta(enable=True, 
#       bl_label="Mesh",
#       base_color=_Color.colorCat["GetData"],)
# def meshInput(mesh: bpy.types.Mesh) -> bpy.types.Mesh:
#     return mesh


# @meta(enable=True, 
#       bl_label="曲线",
#       base_color=_Color.colorCat["GetData"],)
# def curveInput(curve: bpy.types.Curve) -> bpy.types.Curve:
#     return curve


@omni(enable=True, 
      bl_label="骨架",
      base_color=_Color.colorCat["GetData"],)
def armatureInput(arm: bpy.types.Armature) -> bpy.types.Armature:
    return arm


@omni(enable=True, 
      bl_label="矩阵",
      base_color=_Color.colorCat["GetData"],)
def matrixInput(m: mathutils.Matrix) -> mathutils.Matrix:
    return m

@omni(enable=True,
      bl_label="正则表达式"
      ,base_color=_Color.colorCat["GetData"],)
def regexInput(r: _OmniRegex) -> _OmniRegex:
      return r

@omni(enable=True,
      bl_label="Glob表达式"
      ,base_color=_Color.colorCat["GetData"],)
def globInput(g: _OmniGlob) -> _OmniGlob:
      return g
