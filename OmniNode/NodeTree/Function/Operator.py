from ..FunctionCore import meta
from bpy.types import NodeSocketVector, NodeSocketColor
import bpy
import typing
from typing import Any
import time
import mathutils
from . import _COLOR

@meta(enable=True,
      bl_label="设置物体位置",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=True,
      color_tag = "GEOMETRY",
      bl_icon = "OBJECT_DATAMODE",
      )
def objectSetPosition(obj: bpy.types.Object, pos: NodeSocketVector) -> bpy.types.Object:
    obj.location = pos
    return obj


@meta(enable=True,
      bl_label="设置图像颜色",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=True,
      img={"name": "图像输入"},
      )
def imgSetPureColor(img: bpy.types.Image, color: mathutils.Color) -> bpy.types.Image:
    length = len(img.pixels)//4
    col = list(color)*length
    img.pixels = col
    return img

@meta(enable=True,
      bl_label="创建UV层",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=False,
      _OUTPUT_NAME=["物体","UV层"],
      omni_description="""
      在输入的Mesh上创建一个UV层，返回Mesh和UV层名称
      如果已经存在同名UV层，则不创建，直接返回已有的层
      """,
      )
def meshCreateUVLayer(obj: bpy.types.Object, uv_layer_name: str) -> tuple[bpy.types.Mesh,str]:
    mesh = obj.data
    if uv_layer_name in mesh.uv_layers:
        return mesh, uv_layer_name
    mesh.uv_layers.new(name=uv_layer_name)
    return mesh, uv_layer_name


import bpy
import bmesh
import numpy as np
from mathutils import Vector

# -------------------------
# UV sampling
# -------------------------
def sample_image(img_array, uv, w, h):
    x = min(max(uv.x * w, 0), w - 1)
    y = min(max(uv.y * h, 0), h - 1)
    ix, iy = int(x), int(y)
    return img_array[iy, ix]


# -------------------------
# barycentric
# -------------------------
def barycentric(p, a, b, c):
    v0 = b - a
    v1 = c - a
    v2 = p - a

    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)

    denom = d00 * d11 - d01 * d01
    if denom == 0:
        return None

    v = (d11 * d20 - d01 * d21) / denom
    w_ = (d00 * d21 - d01 * d20) / denom
    u = 1.0 - v - w_
    return u, v, w_


@meta(
    enable=True,
    bl_label="跨UV烘焙贴图",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=True,
    _OUTPUT_NAME=["图像"],
    omni_description="""
    该节点用于在同一Collection内对所有Mesh进行UV空间贴图重映射（UV Reprojection Transfer）。

    核心功能：
    - 将输入图像从 uv_source 层重采样到 uv_target 层
    - 支持 COLOR / NORMAL 两种贴图语义模式
    - 支持 alpha 通道混合（COLOR模式）
    - 支持 padding（UV边缘扩展，减少接缝）
    - 支持 overwrite（原地编辑）或生成新贴图

    工作逻辑说明：
    1. 如果 overwrite=True：
    - 使用原始图像分辨率（禁止修改尺寸）
    - 在原图上进行像素重写
    - 保持材质/UV系统一致性

    2. 如果 overwrite=False：
    - 使用 resolution 创建新贴图
    - 输出独立结果图像

    NORMAL模式说明：
    - 自动设置 colorspace = Non-Color
    - 初始化值为 (0.5, 0.5, 1.0)
    - 不进行 alpha 混合，直接覆盖写入

    COLOR模式说明：
    - 使用 alpha 进行混合写入
    - 支持透明区域叠加

    注意：
    该节点不依赖 Blender Bake 系统，属于CPU UV重映射实现。
    """,
    )
def bakeTextureBetweenUV(
    col: bpy.types.Collection,
    uv_source: str,
    uv_target: str,
    img: bpy.types.Image,
    expend: int = 4,
    resolution: int = 2048,
    mode: str = "COLOR",
    overwrite: bool = True,
    new_name: str = "UVBakeResult",
) -> bpy.types.Image:

    # -------------------------
    # 1. source image
    # -------------------------
    src_w, src_h = img.size
    src_pixels = np.array(img.pixels[:], dtype=np.float32).reshape(src_h, src_w, 4)

    # -------------------------
    # 2. output image setup
    # -------------------------
    if overwrite and img:
        out_img = img
        out_w, out_h = img.size
        out = src_pixels.copy()
    else:
        out_w = out_h = resolution

        out_img = bpy.data.images.new(
            name=new_name,
            width=out_w,
            height=out_h,
            alpha=True
        )

        if mode.upper() == "NORMAL":
            out_img.colorspace_settings.name = "Non-Color"
            out_img.alpha_mode = "STRAIGHT"

            out = np.zeros((out_h, out_w, 4), dtype=np.float32)
            out[..., :3] = 0.5
            out[..., 3] = 1.0

        else:
            out = np.zeros((out_h, out_w, 4), dtype=np.float32)

    # -------------------------
    # 3. mesh loop
    # -------------------------
    meshes = [o for o in col.objects if o.type == 'MESH']

    for obj in meshes:
        me = obj.data

        if uv_source not in me.uv_layers or uv_target not in me.uv_layers:
            continue

        uv_src = me.uv_layers[uv_source].data
        uv_dst = me.uv_layers[uv_target].data

        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()

        # -------------------------
        # 4. triangle raster
        # -------------------------
        for face in bm.faces:
            loops = face.loops
            if len(loops) < 3:
                continue

            for i in range(1, len(loops) - 1):

                tri = [0, i, i + 1]

                src_uv = [uv_src[loops[j].index].uv.copy() for j in tri]
                dst_uv = [uv_dst[loops[j].index].uv.copy() for j in tri]

                min_x = max(int(min(v.x for v in dst_uv) * out_w) - expend, 0)
                max_x = min(int(max(v.x for v in dst_uv) * out_w) + expend, out_w - 1)

                min_y = max(int(min(v.y for v in dst_uv) * out_h) - expend, 0)
                max_y = min(int(max(v.y for v in dst_uv) * out_h) + expend, out_h - 1)

                for y in range(min_y, max_y + 1):
                    for x in range(min_x, max_x + 1):

                        p = Vector((x / out_w, y / out_h))
                        bc = barycentric(p, dst_uv[0], dst_uv[1], dst_uv[2])

                        if bc is None:
                            continue

                        u, v, w_ = bc

                        if u < 0 or v < 0 or w_ < 0:
                            continue

                        src_p = (
                            src_uv[0] * u +
                            src_uv[1] * v +
                            src_uv[2] * w_
                        )

                        color = sample_image(src_pixels, src_p, src_w, src_h)

                        # -------------------------
                        # 5. write logic
                        # -------------------------
                        if mode.upper() == "COLOR":
                            a = color[3]
                            out[y, x, :3] = color[:3] * a + out[y, x, :3] * (1.0 - a)
                            out[y, x, 3] = max(out[y, x, 3], a)

                        elif mode.upper() == "NORMAL":
                            # direct overwrite
                            out[y, x, :3] = color[:3]
                            out[y, x, 3] = 1.0

        bm.free()

    # -------------------------
    # 5. write back
    # -------------------------
    out_img.pixels = out.flatten()
    out_img.update()

    return out_img