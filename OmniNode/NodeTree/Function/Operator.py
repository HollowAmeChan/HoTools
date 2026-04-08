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
import re

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

def dilate_image_with_colors(pil_img, radius):
    if radius <= 0:
        return pil_img

    img = np.array(pil_img, dtype=np.uint8)
    h, w = img.shape[:2]

    rgb = img[..., :3]
    alpha = img[..., 3]

    mask = alpha > 0

    for _ in range(radius):
        if mask.all():
            break

        new_mask = mask.copy()

        # 8邻域
        neighbors = [
            (-1,0),(1,0),(0,-1),(0,1),
            (-1,-1),(-1,1),(1,-1),(1,1)
        ]

        for dy, dx in neighbors:
            shifted_mask = np.roll(mask, (dy, dx), axis=(0,1))
            shifted_rgb  = np.roll(rgb,  (dy, dx), axis=(0,1))

            fill = (~mask) & shifted_mask

            rgb[fill] = shifted_rgb[fill]
            alpha[fill] = 255

            new_mask |= fill

        mask = new_mask

    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")

def tri_area(uv):
    return abs(
        (uv[1][0] - uv[0][0]) * (uv[2][1] - uv[0][1]) -
        (uv[2][0] - uv[0][0]) * (uv[1][1] - uv[0][1])
    ) * 0.5

def sample_texture(src_pixels, src_uvs, src_w, src_h, scale, enable_aa):
    # -------------------------
    # 模式选择
    # -------------------------
    if not enable_aa or scale < 1.2:
        mode = 0
    elif scale < 2.5:
        mode = 1
    elif scale < 6.0:
        mode = 2
    else:
        mode = 3

    # -------------------------
    # nearest
    # -------------------------
    if mode == 0:
        sx = np.clip((src_uvs[..., 0] * (src_w - 1)).astype(np.int32), 0, src_w - 1)
        sy = np.clip((src_uvs[..., 1] * (src_h - 1)).astype(np.int32), 0, src_h - 1)
        return src_pixels[sy, sx]

    # -------------------------
    # bilinear函数
    # -------------------------
    def bilinear(u, v):
        sx = u * (src_w - 1)
        sy = v * (src_h - 1)

        x0 = np.floor(sx).astype(np.int32)
        x1 = np.clip(x0 + 1, 0, src_w - 1)
        y0 = np.floor(sy).astype(np.int32)
        y1 = np.clip(y0 + 1, 0, src_h - 1)

        wx = sx - x0
        wy = sy - y0

        c00 = src_pixels[y0, x0]
        c10 = src_pixels[y0, x1]
        c01 = src_pixels[y1, x0]
        c11 = src_pixels[y1, x1]

        return (
            c00 * (1 - wx)[..., None] * (1 - wy)[..., None] +
            c10 * wx[..., None] * (1 - wy)[..., None] +
            c01 * (1 - wx)[..., None] * wy[..., None] +
            c11 * wx[..., None] * wy[..., None]
        )

    # -------------------------
    # 纯bilinear
    # -------------------------
    if mode == 1:
        return bilinear(src_uvs[..., 0], src_uvs[..., 1])

    # -------------------------
    # 多采样
    # -------------------------
    radius = min(2.0, np.sqrt(scale) * 0.5)

    if mode == 2:
        offsets = [
            (-radius, -radius),
            ( radius, -radius),
            (-radius,  radius),
            ( radius,  radius),
        ]
    else:
        offsets = [
            (-radius, -radius), (0, -radius), (radius, -radius),
            (-radius, 0),       (0, 0),       (radius, 0),
            (-radius, radius),  (0, radius),  (radius, radius),
        ]

    acc = 0
    weight = 0

    for dx, dy in offsets:
        u = np.clip(src_uvs[..., 0] + dx / src_w, 0.0, 1.0)
        v = np.clip(src_uvs[..., 1] + dy / src_h, 0.0, 1.0)

        sample = bilinear(u, v)

        a = sample[..., 3:4]  # alpha

        acc += sample * a
        weight += a

    # 防止除0
    weight = np.clip(weight, 1e-6, None)

    return acc / weight

@meta(
    enable=True,
    bl_label="纹理UV重定向",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体","UV源层","UV目标层","图像","膨胀像素数","输出分辨率","是否为法线图","新建图像名称","文件路径","图像格式","自动抗锯齿"],
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
    objs:list[bpy.types.Object],
    uv_source: str,
    uv_target: str,
    img: bpy.types.Image,
    dilate_radius: int = 2,
    resolution: int = 2048,
    isNormal: bool = False,
    new_name: str = "UVBakeResult",
    file_path: _OmniFolderPath = "",
    format: _OmniImageFormat = "PNG",
    enable_aa: bool = True,
) -> tuple[bpy.types.Image, _OmniFolderPath]:

    # 检查是否在编辑模式下
    if bpy.context.mode == 'EDIT_MESH':
        raise RuntimeError("无法在编辑模式下运行，请切换到物体模式")

    total_start = time.perf_counter()
    timings = {k: 0.0 for k in [
        "collect_meshes","reproject","dilate","fill_normal",
        "save","load_blender","create_blender_image"
    ]}

    # -------------------------
    # Source image
    # -------------------------
    src_w, src_h = img.size
    src_pixels = np.empty(src_w * src_h * 4, dtype=np.float32)
    img.pixels.foreach_get(src_pixels)
    src_pixels = src_pixels.reshape(src_h, src_w, 4)

    # -------------------------
    # Output
    # -------------------------
    out_w = out_h = resolution

    if isNormal:
        out = np.zeros((out_h, out_w, 4), dtype=np.float32)
        out[..., :3] = (0.5, 0.5, 1.0)
    else:
        out = np.zeros((out_h, out_w, 4), dtype=np.float32)

    # -------------------------
    # Collect meshes
    # -------------------------
    collect_start = time.perf_counter()
    meshes = [o for o in objs if o.type == 'MESH']
    timings["collect_meshes"] = time.perf_counter() - collect_start

    # -------------------------
    # Reproject (核心优化区)
    # -------------------------
    repro_start = time.perf_counter()

    for obj in meshes:
        me = obj.data

        if uv_source not in me.uv_layers or uv_target not in me.uv_layers:
            continue

        me.calc_loop_triangles()
        tris = me.loop_triangles

        uv_src_layer = me.uv_layers[uv_source].data
        uv_dst_layer = me.uv_layers[uv_target].data

        for tri in tris:
            idx = tri.loops

            # ---- 取UV（numpy化）----
            src_uv = np.array([uv_src_layer[i].uv[:] for i in idx], dtype=np.float32)
            dst_uv = np.array([uv_dst_layer[i].uv[:] for i in idx], dtype=np.float32)

            # ---- bounding box ----
            uv_min = np.clip(dst_uv.min(axis=0), 0.0, 1.0)
            uv_max = np.clip(dst_uv.max(axis=0), 0.0, 1.0)

            min_x = int(uv_min[0] * (out_w - 1))
            max_x = int(uv_max[0] * (out_w - 1))

            min_y = int((1.0 - uv_max[1]) * (out_h - 1))
            max_y = int((1.0 - uv_min[1]) * (out_h - 1))

            if min_x > max_x or min_y > max_y:
                continue

            # ---- 像素grid ----
            xs = np.arange(min_x, max_x + 1)
            ys = np.arange(min_y, max_y + 1)

            grid_x, grid_y = np.meshgrid(xs, ys)

            px = (grid_x + 0.5) / out_w
            py = 1.0 - (grid_y + 0.5) / out_h

            p = np.stack([px, py], axis=-1)

            # ---- barycentric（向量化）----
            a, b, c = dst_uv

            v0 = b - a
            v1 = c - a
            v2 = p - a

            d00 = np.dot(v0, v0)
            d01 = np.dot(v0, v1)
            d11 = np.dot(v1, v1)

            denom = d00 * d11 - d01 * d01
            if denom == 0:
                continue

            d20 = v2[..., 0] * v0[0] + v2[..., 1] * v0[1]
            d21 = v2[..., 0] * v1[0] + v2[..., 1] * v1[1]

            v = (d11 * d20 - d01 * d21) / denom
            w = (d00 * d21 - d01 * d20) / denom
            u = 1.0 - v - w

            mask = (u >= 0) & (v >= 0) & (w >= 0)
            if not mask.any():
                continue

            # ---- src uv ----
            src_uvs = (
                src_uv[0] * u[..., None] +
                src_uv[1] * v[..., None] +
                src_uv[2] * w[..., None]
            )

            # ---- 采样 ----
            sx = np.clip((src_uvs[..., 0] * (src_w - 1)).astype(np.int32), 0, src_w - 1)
            sy = np.clip((src_uvs[..., 1] * (src_h - 1)).astype(np.int32), 0, src_h - 1)

            #是否抗锯齿
            scale = (tri_area(src_uv) * src_w * src_h) / (tri_area(dst_uv) * out_w * out_h + 1e-8)
            colors = sample_texture(
                src_pixels,
                src_uvs,
                src_w,
                src_h,
                scale,
                enable_aa
            )

            region = out[min_y:max_y+1, min_x:max_x+1]

            if isNormal:
                region[mask] = colors[mask]
                region[mask, 3] = 1.0
            else:
                a_col = colors[..., 3:4]
                region[..., :3] = colors[..., :3] * a_col + region[..., :3] * (1.0 - a_col)
                region[..., 3] = np.maximum(region[..., 3], colors[..., 3])

            out[min_y:max_y+1, min_x:max_x+1] = region

    timings["reproject"] = time.perf_counter() - repro_start

    # -------------------------
    # 后处理（保持你原逻辑）
    # -------------------------
    def fill_normal_background(img):
        arr = np.array(img, dtype=np.uint8)
        mask = arr[:, :, 3] == 0
        if mask.any():
            arr[mask, 0] = 128
            arr[mask, 1] = 128
            arr[mask, 2] = 255
            arr[mask, 3] = 255
        return Image.fromarray(arr, mode='RGBA')

    file_format = format.upper()
    output_path = ""

    if file_path:
        abs_file_path = bpy.path.abspath(file_path)
        dir_path = os.path.dirname(abs_file_path)
        full_path = os.path.join(dir_path, new_name + '.' + file_format.lower())
        os.makedirs(dir_path, exist_ok=True)

        img_array = (out * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_array, 'RGBA')

        t = time.perf_counter()
        pil_img = dilate_image_with_colors(pil_img, dilate_radius)
        timings["dilate"] = time.perf_counter() - t

        if isNormal:
            t = time.perf_counter()
            pil_img = fill_normal_background(pil_img)
            timings["fill_normal"] = time.perf_counter() - t

        t = time.perf_counter()
        pil_img.save(full_path, format=file_format)
        timings["save"] = time.perf_counter() - t

        output_path = full_path

        t = time.perf_counter()
        if new_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[new_name])
        out_img = bpy.data.images.load(full_path)
        out_img.name = new_name
        if isNormal:
            out_img.colorspace_settings.name = "Non-Color"
        timings["load_blender"] = time.perf_counter() - t

    else:
        t = time.perf_counter()
        out_img = bpy.data.images.new(
            name=new_name,
            width=out_w,
            height=out_h,
            alpha=True
        )
        if isNormal:
            out_img.colorspace_settings.name = "Non-Color"

        flat = out.ravel()  # 不复制
        out_img.pixels.foreach_set(flat)
        out_img.update()
        timings["create_blender_image"] = time.perf_counter() - t

    total_time = time.perf_counter() - total_start

    print(
        f"[uv_reprojectionTransfer OPT] "
        f"collect_meshes={timings['collect_meshes']:.4f}s "
        f"reproject={timings['reproject']:.4f}s "
        f"dilate={timings['dilate']:.4f}s "
        f"fill_normal={timings['fill_normal']:.4f}s "
        f"save={timings['save']:.4f}s "
        f"load_blender={timings['load_blender']:.4f}s "
        f"create_blender_image={timings['create_blender_image']:.4f}s "
        f"total={total_time:.4f}s"
    )

    return out_img, output_path

@meta(
    enable=True,
    bl_label="加合",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["整数列表"],
    _OUTPUT_NAME=["和"],
    )
def sumInt(ints: list[int])->int:
    return sum(ints)

@meta(enable=True,
    bl_label="导入图片",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["图片路径","是否为法线图"],
    _OUTPUT_NAME=["图片"],
    )
def importImage2Blender(imagePath: _OmniFolderPath, isNormal: bool) -> bpy.types.Image:
    img_name = os.path.basename(imagePath)
    if bpy.data.images.get(img_name):
        bpy.data.images.remove(bpy.data.images[img_name])
    img = bpy.data.images.load(imagePath)
    img.name = img_name
    if isNormal:
        img.colorspace_settings.name = "Non-Color"
    return img

@meta(enable=True,
    bl_label="批量导入图片",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["图片路径","是否为法线图"],
    _OUTPUT_NAME=["图片"],
    )
def importMultiImage2Blender(imagePaths: list[_OmniFolderPath] ,isNormal: bool) -> list[bpy.types.Image]:
    imgs = []
    for path in imagePaths:
        img_name = os.path.basename(path)
        if bpy.data.images.get(img_name):
            bpy.data.images.remove(bpy.data.images[img_name])
        img = bpy.data.images.load(path)
        img.name = img_name
        if isNormal:
            img.colorspace_settings.name = "Non-Color"
        imgs.append(img)
    return imgs

@meta(enable=True,
    bl_label="获取集合中的物体",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["集合"],
    _OUTPUT_NAME=["物体列表"],
    )
def getObjectsInCollection(col: bpy.types.Collection) -> list[bpy.types.Object]:
    return [o for o in col.objects]


@meta(
    enable=True,
    bl_label="文件路径(正则)",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["文件夹路径", "正则表达式"],
    _OUTPUT_NAME=["文件路径列表"],
    omni_description="""
    该节点用于扫描指定文件夹下所有符合正则表达式的文件路径，返回一个列表
    """
)
def scanFilePath(
    folderPath: _OmniFolderPath,
    pattern: str
) -> list[_OmniFolderPath]:

    # 路径解析
    folderPath = bpy.path.abspath(folderPath)

    if not folderPath:
        raise ValueError("[scanFilePath] folderPath is empty")

    if not os.path.isdir(folderPath):
        raise FileNotFoundError(f"[scanFilePath] folder not found: {folderPath}")
    # 正则编译
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"[scanFilePath] Invalid regex: {pattern} -> {e}")


    result = []
    for root, dirs, files in os.walk(folderPath):
        for f in files:
            if regex.search(f):
                result.append(os.path.join(root, f))
    # 稳定顺序
    result.sort()

    return result


def alpha_over(src_rgb, src_a, dst_rgb, dst_a):
    out_a = src_a + dst_a * (1.0 - src_a)

    # 防止除0
    safe_out_a = np.maximum(out_a, 1e-8)

    out_rgb = (
        src_rgb * src_a[..., None] +
        dst_rgb * dst_a[..., None] * (1.0 - src_a[..., None])
    ) / safe_out_a[..., None]

    return out_rgb, out_a

@meta(
    enable=True,
    bl_label="合成图片",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["图片列表","背景颜色","新建图像名称","覆盖同名图像","16bit"],
    _OUTPUT_NAME=["合成图像"],
)
def combineImages(
    imgs: list[bpy.types.Image],
    backgroundColor: mathutils.Color,
    name: str,
    overwrite: bool = True,
    use_16bit: bool = False,
) -> bpy.types.Image:

    if not imgs:
        raise ValueError("[combineImages] empty image list")

    # -------------------------
    # 0. 覆写逻辑
    # -------------------------
    if overwrite:
        old_img = bpy.data.images.get(name)
        if old_img:
            old_img.user_clear()
            bpy.data.images.remove(old_img)

    # -------------------------
    # 1. 尺寸
    # -------------------------
    base = imgs[0]
    width = base.size[0]
    height = base.size[1]

    # -------------------------
    # 2. 背景
    # -------------------------
    bg_rgb = np.ones((height, width, 3), dtype=np.float32)

    backgroundColor = mathutils.Color(backgroundColor[:3])

    bg_rgb[..., 0] *= backgroundColor.r
    bg_rgb[..., 1] *= backgroundColor.g
    bg_rgb[..., 2] *= backgroundColor.b

    bg_a = np.ones((height, width), dtype=np.float32)

    # -------------------------
    # 3. 合成
    # -------------------------
    acc_rgb = bg_rgb
    acc_a = bg_a

    for img in imgs:

        if img.size[0] != width or img.size[1] != height:
            raise ValueError(
                f"[combineImages] size mismatch: {img.name} "
                f"({img.size[0]}x{img.size[1]}) != ({width}x{height})"
            )

        img_pixels = np.array(img.pixels[:], dtype=np.float32)
        img_pixels = img_pixels.reshape((height, width, 4))

        src_rgb = img_pixels[..., :3]
        src_a = img_pixels[..., 3]

        acc_rgb, acc_a = alpha_over(src_rgb, src_a, acc_rgb, acc_a)

    # -------------------------
    # 4. 创建 Image（关键升级点）
    # -------------------------
    result = bpy.data.images.new(
        name=name,
        width=width,
        height=height,
        alpha=True,
        float_buffer=use_16bit  # ⭐ 核心开关
    )

    # -------------------------
    # 5. 写入
    # -------------------------
    out = np.zeros((height, width, 4), dtype=np.float32)
    out[..., :3] = acc_rgb
    out[..., 3] = acc_a

    result.pixels = out.flatten()

    # -------------------------
    # 6. 额外安全：强制颜色空间（可选但推荐）
    # -------------------------
    if use_16bit:
        result.colorspace_settings.name = 'Linear Rec.709'
    else:
        result.colorspace_settings.name = 'sRGB'

    return result


@meta(enable=True,
    bl_label="保存图片",
    base_color=_COLOR.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["图片","文件路径","格式"],
    _OUTPUT_NAME=["文件路径"],
    omni_description="""
    该节点用于将Blender图片保存到指定路径，支持 PNG、JPEG、EXR 等格式
    """
)
def saveImage(bl_img, file_path, format):

    if not bl_img:
        raise ValueError("[saveImage] bl_img is None")

    if not file_path:
        raise ValueError("[saveImage] file_path is empty")

    # -------------------------
    # 1. 转换路径
    # -------------------------
    file_path = bpy.path.abspath(file_path)

    # -------------------------
    # 2. 如果传进来是目录 -> 自动补文件名
    # -------------------------
    if file_path.endswith(os.sep) or os.path.isdir(file_path):
        name = bl_img.name

        fmt = format.lower()
        ext_map = {
            "png": ".png",
            "jpg": ".jpg",
            "jpeg": ".jpg",
            "exr": ".exr",
            "open_exr": ".exr",
        }

        ext = ext_map.get(fmt, ".png")

        file_path = os.path.join(file_path, name + ext)

    # -------------------------
    # 3. 创建目录
    # -------------------------
    folder = os.path.dirname(file_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    # -------------------------
    # 4. format
    # -------------------------
    fmt = format.upper()

    if fmt == "PNG":
        bl_img.file_format = 'PNG'

    elif fmt in ("EXR", "OPEN_EXR"):
        bl_img.file_format = 'OPEN_EXR'
        bl_img.exr_codec = 'ZIP'

    elif fmt in ("JPG", "JPEG"):
        bl_img.file_format = 'JPEG'

    else:
        raise ValueError(f"[saveImage] unsupported format: {format}")

    # -------------------------
    # 5. 保存
    # -------------------------
    bl_img.filepath_raw = file_path

    bl_img.save()

    return file_path
