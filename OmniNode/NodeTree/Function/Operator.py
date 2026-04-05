from ..FunctionCore import meta , _OmniImageFormat , _OmniFolderPath
from . import _COLOR

from bpy.types import NodeSocketVector, NodeSocketColor
import bpy
import bmesh
import typing
from typing import Any
import time
import mathutils
from mathutils import Vector
import numpy as np

import os
import sys
if sys.version_info >= (3, 13):
    from ...._Lib.py313.PIL import Image, ImageDraw
elif sys.version_info >= (3, 11):
    from ...._Lib.py311.PIL import Image, ImageDraw

@meta(enable=True,
      bl_label="设置物体位置",
      base_color=_COLOR.colorCat["Operator"],
      is_output_node=False,
      color_tag = "GEOMETRY",
      bl_icon = "OBJECT_DATAMODE",
      )
def objectSetPosition(obj: bpy.types.Object, pos: NodeSocketVector) -> bpy.types.Object:
    obj.location = pos
    return obj


@meta(enable=True,
    bl_label="设置图像颜色",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["图像","颜色"],
    _OUTPUT_NAME=["图像"],
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
    _INPUT_NAME=["物体","UV层"],
    _OUTPUT_NAME=["物体","UV层"],
    omni_description="""
    在输入的Mesh上创建一个UV层，返回Mesh和UV层名称
    如果已经存在同名UV层，则不创建，直接返回已有的层
    """,
    )
def meshCreateUVLayer(obj: bpy.types.Object, uv_layer_name: str) -> tuple[bpy.types.Object,str]:
    mesh = obj.data
    if uv_layer_name in mesh.uv_layers:
        return obj, uv_layer_name
    mesh.uv_layers.new(name=uv_layer_name)
    return obj, uv_layer_name



def sample_image(img_array, uv, w, h):
    x = min(max(uv.x * (w - 1), 0.0), w - 1)
    y = min(max((1.0 - uv.y) * (h - 1), 0.0), h - 1)
    ix = int(x)
    iy = int(y)
    return img_array[iy, ix]

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

def dilate_image_with_colors(pil_img, radius):
    """为每个像素保留颜色，使用膨胀传播颜色"""
    if radius <= 0:
        return pil_img

    img_arr = np.array(pil_img)
    h, w = img_arr.shape[:2]

    for _ in range(radius):
        dilated = img_arr.copy()
        alpha = img_arr[:, :, 3]
        mask = (alpha == 0)
        if not mask.any():
            break

        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue

                src_y0 = max(0, -dy)
                src_y1 = h - max(0, dy)
                src_x0 = max(0, -dx)
                src_x1 = w - max(0, dx)
                dst_y0 = max(0, dy)
                dst_y1 = h - max(0, -dy)
                dst_x0 = max(0, dx)
                dst_x1 = w - max(0, -dx)

                src = img_arr[src_y0:src_y1, src_x0:src_x1]
                dst_mask = mask[dst_y0:dst_y1, dst_x0:dst_x1]
                cond = (src[:, :, 3] > 0) & dst_mask
                if cond.any():
                    region = dilated[dst_y0:dst_y1, dst_x0:dst_x1]
                    region[cond] = src[cond]
                    dilated[dst_y0:dst_y1, dst_x0:dst_x1] = region

        img_arr = dilated

    return Image.fromarray(img_arr, mode="RGBA")

@meta(
    enable=True,
    bl_label="纹理UV重定向",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["集合","UV源层","UV目标层","图像","膨胀像素数","输出分辨率","是否为法线图","新建图像名称","文件路径","图像格式"],
    _OUTPUT_NAME=["图像","图像路径"],
    omni_description="""
    该节点用于在同一Collection内对所有Mesh进行UV空间贴图重映射(UV Reprojection Transfer)
    1. 总是创建新图像，使用指定的分辨率
    2. isNormal=True
    - 自动设置 colorspace = Non-Color
    - 初始化值为 (0.5, 0.5, 1.0)
    - 不进行 alpha 混合，直接覆盖写入
    否则
    - 使用 alpha 进行混合写入
    - 支持透明区域叠加
    3. 直接保存图像到指定文件路径，支持的格式：PNG, JPG, JPEG, TGA, BMP，然后导入到Blender中
    4. 膨胀像素数用于消除UV边缘缝隙
    """,
    )
def uv_reprojectionTransfer(
    col: bpy.types.Collection,
    uv_source: str,
    uv_target: str,
    img: bpy.types.Image,
    dilate_radius: int = 2,
    resolution: int = 2048,
    isNormal: bool = False,
    new_name: str = "UVBakeResult",
    file_path: _OmniFolderPath = "",
    format: _OmniImageFormat = "PNG",
) -> tuple[bpy.types.Image, str]:

    src_w, src_h = img.size
    src_pixels = np.array(img.pixels[:], dtype=np.float32).reshape(src_h, src_w, 4)

    # Always create new image with specified resolution
    out_w = out_h = resolution

    if isNormal:
        out = np.zeros((out_h, out_w, 4), dtype=np.float32)
        out[..., :3] = (0.5, 0.5, 1.0)
        out[..., 3] = 0.0
    else:
        out = np.zeros((out_h, out_w, 4), dtype=np.float32)
        out[..., :] = 0.0

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

        for face in bm.faces:
            loops = face.loops
            if len(loops) < 3:
                continue

            for i in range(1, len(loops) - 1):

                tri = [0, i, i + 1]

                src_uv = [uv_src[loops[j].index].uv.copy() for j in tri]
                dst_uv = [uv_dst[loops[j].index].uv.copy() for j in tri]

                uv_min_x = max(min(v.x for v in dst_uv), 0.0)
                uv_max_x = min(max(v.x for v in dst_uv), 1.0)
                uv_min_y = max(min(v.y for v in dst_uv), 0.0)
                uv_max_y = min(max(v.y for v in dst_uv), 1.0)

                min_x = int(uv_min_x * (out_w - 1))
                max_x = int(uv_max_x * (out_w - 1))
                pixel_min_y = int((1.0 - uv_max_y) * (out_h - 1))
                pixel_max_y = int((1.0 - uv_min_y) * (out_h - 1))

                min_y = max(min(pixel_min_y, out_h - 1), 0)
                max_y = max(min(pixel_max_y, out_h - 1), 0)

                if min_x > max_x or min_y > max_y:
                    continue

                for y in range(min_y, max_y + 1):
                    for x in range(min_x, max_x + 1):

                        p = Vector(((x + 0.5) / out_w, 1.0 - (y + 0.5) / out_h))  # Pixel center UV
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

                        if not isNormal:
                            a = color[3]
                            out[y, x, :3] = color[:3] * a + out[y, x, :3] * (1.0 - a)
                            out[y, x, 3] = max(out[y, x, 3], a)

                        elif isNormal:
                            # direct overwrite
                            out[y, x, :3] = color[:3]
                            out[y, x, 3] = 1.0

        bm.free()

    def fill_normal_background(img):
        arr = np.array(img, dtype=np.uint8)
        mask = arr[:, :, 3] == 0
        if mask.any():
            arr[mask, 0] = int(0.5 * 255)
            arr[mask, 1] = int(0.5 * 255)
            arr[mask, 2] = int(1.0 * 255)
            arr[mask, 3] = 255
        return Image.fromarray(arr, mode='RGBA')

    def normalize_format(fmt):
        fmt = fmt.upper()
        if fmt == 'JPG':
            return 'JPEG', 'jpg'
        if fmt == 'JPEG':
            return 'JPEG', 'jpeg'
        if fmt == 'PNG':
            return 'PNG', 'png'
        if fmt == 'TGA':
            return 'TGA', 'tga'
        if fmt == 'BMP':
            return 'BMP', 'bmp'
        return fmt, fmt.lower()

    file_format, file_ext = normalize_format(format)
    output_path = ""
    if file_path:
        abs_file_path = bpy.path.abspath(file_path)
        dir_path = os.path.dirname(abs_file_path)
        full_path = os.path.join(dir_path, new_name + '.' + file_ext)
        os.makedirs(dir_path, exist_ok=True)
        # Convert to uint8 for PIL
        img_array = (out * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_array, 'RGBA')
        pil_img = dilate_image_with_colors(pil_img, dilate_radius)
        if isNormal:
            pil_img = fill_normal_background(pil_img)
        if file_format == 'JPEG':
            pil_img = pil_img.convert('RGB')
        pil_img.save(full_path, format=file_format)
        output_path = full_path

        # Load into Blender
        if new_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[new_name])
        out_img = bpy.data.images.load(full_path)
        out_img.name = new_name  # Set the name in Blender
        if isNormal:
            out_img.colorspace_settings.name = "Non-Color"
    else:
        # Create Blender image
        if isNormal and dilate_radius > 0:
            img_array = (out * 255).astype(np.uint8)
            pil_img = Image.fromarray(img_array, 'RGBA')
            pil_img = dilate_image_with_colors(pil_img, dilate_radius)
            pil_img = fill_normal_background(pil_img)
            out = np.array(pil_img, dtype=np.uint8).astype(np.float32) / 255.0
        elif isNormal:
            # fill neutral background for normal maps
            mask = out[:, :, 3] == 0
            if mask.any():
                out[mask, 0] = 0.5
                out[mask, 1] = 0.5
                out[mask, 2] = 1.0
                out[mask, 3] = 1.0
        out_img = bpy.data.images.new(
            name=new_name,
            width=out_w,
            height=out_h,
            alpha=True
        )
        if isNormal:
            out_img.colorspace_settings.name = "Non-Color"
            out_img.alpha_mode = "STRAIGHT"
        out_img.pixels = out.flatten()
        out_img.update()

    return out_img, output_path