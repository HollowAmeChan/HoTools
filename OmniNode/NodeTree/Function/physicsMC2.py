"""MagicaCloth2-style cloth solver nodes for OmniNode.

This module is intentionally introduced as a separate implementation surface from
Physics.py.  The first production target is MeshCloth, with shared data and solve
helpers kept reusable for the later BoneCloth path.  Nodes stay disabled until
the Python reference implementation is complete.
"""

from ..FunctionNodeCore import omni
from ..OmniNodeSocketMapping import _OmniCache
from . import _Color

import bpy
import mathutils
import numpy as np


MC2_CACHE_KIND = "MESH_PHYSICS_MC2"
MC2_SOLVER_VERSION = 1


MC2_CURVE_READY_PARAMETERS = {
    "distance_stiffness",
    "radius",
    "max_distance",
    "backstop_distance",
    "angle_restoration_stiffness",
    "angle_limit",
}


class _MC2Common:
    """Shared MC2-like data preparation for MeshCloth and future BoneCloth."""

    EPSILON = 0.000001

    @staticmethod
    def scene_delta_time(scene: bpy.types.Scene = None) -> float:
        scene = scene or bpy.context.scene
        render = scene.render
        fps_base = float(render.fps_base) if render.fps_base else 1.0
        fps = float(render.fps) / fps_base
        return 1.0 / fps if fps > 0.0 else 0.0

    @staticmethod
    def vector3(value, fallback: mathutils.Vector) -> mathutils.Vector:
        if value is None or value == "":
            return fallback.copy()
        try:
            vec = mathutils.Vector(value)
        except Exception:
            return fallback.copy()
        if len(vec) == 0:
            return fallback.copy()
        if len(vec) == 1:
            return mathutils.Vector((vec[0], fallback[1], fallback[2]))
        if len(vec) == 2:
            return mathutils.Vector((vec[0], vec[1], fallback[2]))
        return vec.to_3d()

    @staticmethod
    def require_mesh_object(obj, label: str) -> bpy.types.Object:
        if obj is None or not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
            raise ValueError(f"{label} is not a mesh object")
        if obj.data is None or len(obj.data.vertices) == 0:
            raise ValueError(f"{label} mesh has no vertices")
        return obj

    @staticmethod
    def read_mesh_positions(obj: bpy.types.Object) -> np.ndarray:
        vertex_count = len(obj.data.vertices)
        values = np.empty(vertex_count * 3, dtype=np.float32)
        obj.data.vertices.foreach_get("co", values)
        return values.reshape((vertex_count, 3))

    @staticmethod
    def output_shape_key_name(obj: bpy.types.Object) -> str:
        props = getattr(obj, "hotools_mesh_collision", None)
        name = str(getattr(props, "output_shape_key", "") or "").strip()
        return name or "MC2MeshCloth"

    @staticmethod
    def cache_frame(cache) -> int | None:
        if not isinstance(cache, dict) or "frame" not in cache:
            return None
        try:
            return int(cache.get("frame"))
        except Exception:
            return None


class _MC2MeshCloth:
    """MeshCloth reference implementation placeholder.

    Planned responsibilities:
    - Build a low-poly proxy directly from the input mesh.
    - Store MC2-style particle arrays in OmniNode runtime cache.
    - Match SpringBone frame-continuity protection and world-space state.
    - Solve one frame in Python first.
    - Keep the same cache and array contract for the later C++ backend.
    """

    @classmethod
    def state_matches(cls, state, obj: bpy.types.Object) -> bool:
        return (
            isinstance(state, dict)
            and state.get("kind") == MC2_CACHE_KIND
            and state.get("solver_version") == MC2_SOLVER_VERSION
            and state.get("object_ptr") == int(obj.as_pointer())
            and state.get("mesh_ptr") == int(obj.data.as_pointer())
            and state.get("vertex_count") == len(obj.data.vertices)
        )

    @classmethod
    def build_empty_state(cls, obj: bpy.types.Object, shape_key_name: str) -> dict:
        rest_local = _MC2Common.read_mesh_positions(obj)
        vertex_count = len(obj.data.vertices)
        zeros3 = np.zeros((vertex_count, 3), dtype=np.float32)
        zeros1 = np.zeros(vertex_count, dtype=np.float32)
        return {
            "kind": MC2_CACHE_KIND,
            "solver_version": MC2_SOLVER_VERSION,
            "frame": None,
            "object_name": obj.name_full,
            "object_ptr": int(obj.as_pointer()),
            "mesh_ptr": int(obj.data.as_pointer()),
            "shape_key_name": shape_key_name,
            "vertex_count": vertex_count,
            "rest_local_positions": np.ascontiguousarray(rest_local, dtype=np.float32),
            "next_positions": zeros3.copy(),
            "old_positions": zeros3.copy(),
            "base_positions": zeros3.copy(),
            "velocity_positions": zeros3.copy(),
            "display_positions": zeros3.copy(),
            "friction": zeros1.copy(),
            "static_friction": zeros1.copy(),
            "collision_normals": zeros3.copy(),
            "extension_slots": {
                "bonecloth": None,
                "curves": {},
                "self_collision": None,
                "native": None,
            },
        }


@omni(
    enable=False,
    bl_label="网格布料-MC2",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=[
        "缓存",
        "低模代理",
        "场景",
        "启用",
        "重置",
        "子步数",
        "迭代",
        "重力方向",
        "重力强度",
        "阻尼",
        "距离刚度",
        "弯曲刚度",
        "最大距离",
        "碰撞半径",
        "调试输出",
    ],
    input_init={
        "substeps": {"min_value": 1, "max_value": 16},
        "iterations": {"min_value": 0, "max_value": 64},
        "gravity_power": {"min_value": 0.0, "max_value": 100.0},
        "damping": {"min_value": 0.0, "max_value": 1.0},
        "distance_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "bend_stiffness": {"min_value": 0.0, "max_value": 1.0},
        "max_distance": {"min_value": 0.0},
        "collision_radius": {"min_value": 0.0},
    },
    _OUTPUT_NAME=["缓存", "低模代理", "顶点数", "约束数"],
    omni_description="""
    规划中的 MC2 MeshCloth Python 参考节点。解算器永远直接驱动输入低模代理，不做 MC2 reduction，也不做高低模映射。
    碰撞将复用 HoTools/OmniNode 现有碰撞组快照；曲线参数先以标量输入实现，但 cache 和参数层保留升级为曲线采样表的空间。
    当前节点未启用，避免未完成求解器进入用户菜单。
    """,
)
def meshClothMC2(
    cache_state: _OmniCache,
    proxy_obj: bpy.types.Object,
    scene: bpy.types.Scene = None,
    enabled: bool = True,
    reset: bool = False,
    substeps: int = 1,
    iterations: int = 4,
    gravity_dir: mathutils.Vector = mathutils.Vector((0.0, 0.0, -1.0)),
    gravity_power: float = 9.8,
    damping: float = 0.04,
    distance_stiffness: float = 1.0,
    bend_stiffness: float = 0.5,
    max_distance: float = 0.0,
    collision_radius: float = 0.0,
    debug_output: bool = False,
) -> tuple[_OmniCache, bpy.types.Object, int, int]:
    raise NotImplementedError("meshClothMC2 is a disabled planning stub; implement the Python reference solver first")
