import bpy
import sys
import os
import random
import numpy as np

if sys.version_info >= (3, 13):
    from .._Lib.py313.PIL import Image, ImageDraw
elif sys.version_info >= (3, 11):
    from .._Lib.py311.PIL import Image, ImageDraw

import bmesh
from bpy.types import Operator, Panel, Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty, FloatVectorProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d

# region 变量


def reg_props():
    return


def ureg_props():
    return
# endregion


def dilate_image_with_colors(pil_img, radius):
    """为每个像素保留颜色，使用膨胀传播颜色"""
    if radius <= 0:
        return pil_img

    img_arr = np.array(pil_img)
    alpha = img_arr[:, :, 3]
    mask = (alpha == 0)

    for _ in range(radius):
        dilated = img_arr.copy()
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1),
                       (0, -1),          (0, 1),
                       (1, -1), (1, 0),  (1, 1)]:
            shifted = np.roll(np.roll(img_arr, dx, axis=0), dy, axis=1)
            shifted_alpha = shifted[:, :, 3]
            cond = (shifted_alpha > 0) & mask
            dilated[cond] = shifted[cond]
        img_arr = dilated
        mask = (img_arr[:, :, 3] == 0)

    return Image.fromarray(img_arr, mode="RGBA")


def fill_weight_triangle(img_arr, pts, weights):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    w0, w1, w2 = weights

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))

    for py in range(min_y, max_y + 1):
        sample_y = py + 0.5
        for px in range(min_x, max_x + 1):
            sample_x = px + 0.5
            b0 = ((y1 - y2) * (sample_x - x2) +
                  (x2 - x1) * (sample_y - y2)) / denom
            b1 = ((y2 - y0) * (sample_x - x2) +
                  (x0 - x2) * (sample_y - y2)) / denom
            b2 = 1.0 - b0 - b1

            if b0 < 0.0 or b1 < 0.0 or b2 < 0.0:
                continue

            weight = max(0.0, min(1.0, b0 * w0 + b1 * w1 + b2 * w2))
            gray = int(weight * 255)
            img_arr[py, px] = (gray, gray, gray, 255)


def get_face_edge_uv_pair(face, edge, uv_layer):
    for loop in face.loops:
        if loop.edge == edge:
            return loop[uv_layer].uv.copy(), loop.link_loop_next[uv_layer].uv.copy()
    return None


def uv_edge_connected(face, linked_face, edge, uv_layer, epsilon=1e-5):
    pair_a = get_face_edge_uv_pair(face, edge, uv_layer)
    pair_b = get_face_edge_uv_pair(linked_face, edge, uv_layer)
    if pair_a is None or pair_b is None:
        return False

    a0, a1 = pair_a
    b0, b1 = pair_b
    same_dir = (a0 - b0).length < epsilon and (a1 - b1).length < epsilon
    flip_dir = (a0 - b1).length < epsilon and (a1 - b0).length < epsilon
    return same_dir or flip_dir


def find_uv_islands(bm, uv_layer):
    islands = []
    visited = set()

    for face in bm.faces:
        if face in visited:
            continue

        island_faces = set()
        stack = [face]
        while stack:
            f = stack.pop()
            if f in island_faces:
                continue

            island_faces.add(f)
            visited.add(f)

            for edge in f.edges:
                for linked_face in edge.link_faces:
                    if linked_face == f or linked_face in island_faces or linked_face in visited:
                        continue
                    if uv_edge_connected(f, linked_face, edge, uv_layer):
                        stack.append(linked_face)

        islands.append(island_faces)

    return islands


def fill_local_uv_triangle(img_arr, pts, local_uvs):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    uv0, uv1, uv2 = local_uvs

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))

    for py in range(min_y, max_y + 1):
        sample_y = py + 0.5
        for px in range(min_x, max_x + 1):
            sample_x = px + 0.5
            b0 = ((y1 - y2) * (sample_x - x2) +
                  (x2 - x1) * (sample_y - y2)) / denom
            b1 = ((y2 - y0) * (sample_x - x2) +
                  (x0 - x2) * (sample_y - y2)) / denom
            b2 = 1.0 - b0 - b1

            if b0 < -1e-6 or b1 < -1e-6 or b2 < -1e-6:
                continue

            local_u = max(0.0, min(1.0, b0 * uv0[0] + b1 * uv1[0] + b2 * uv2[0]))
            local_v = max(0.0, min(1.0, b0 * uv0[1] + b1 * uv1[1] + b2 * uv2[1]))
            img_arr[py, px] = (int(local_u * 255 + 0.5),
                               int(local_v * 255 + 0.5),
                               0,
                               255)


def distance_transform_1d_into(f, d, v, z, n):
    k = 0
    v[0] = 0
    z[0] = -np.inf
    z[1] = np.inf

    for q in range(1, n):
        q2 = q * q
        while True:
            p = v[k]
            s = ((f[q] + q2) - (f[p] + p * p)) / (2.0 * q - 2.0 * p)
            if s > z[k]:
                break
            k -= 1

        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = np.inf

    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        p = v[k]
        d[q] = (q - p) * (q - p) + f[p]


def euclidean_distance_transform(seeds):
    inf = 1.0e20
    f = np.empty(seeds.shape, dtype=np.float64)
    f[seeds] = 0.0
    f[~seeds] = inf
    height, width = f.shape
    tmp = np.empty_like(f)
    max_len = max(height, width)
    v = np.empty(max_len, dtype=np.int32)
    z = np.empty(max_len + 1, dtype=np.float64)

    for y in range(height):
        distance_transform_1d_into(f[y, :], tmp[y, :], v, z, width)

    tmp_t = np.ascontiguousarray(tmp.T)
    out_t = np.empty_like(tmp_t)
    for x in range(width):
        distance_transform_1d_into(tmp_t[x, :], out_t[x, :], v, z, height)

    return out_t.T


def get_resample_filter():
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


def rasterize_object_uv_mask(obj, depsgraph, draw, width, height):
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        uv_layer = mesh.uv_layers.active
        if uv_layer is None:
            return None

        drawn_faces = 0

        for poly in mesh.polygons:
            loop_indices = poly.loop_indices
            if len(loop_indices) < 3:
                continue

            pts = []
            for loop_index in loop_indices:
                uv = uv_layer.data[loop_index].uv
                pts.append((uv.x * width, (1.0 - uv.y) * height))

            for i in range(1, len(pts) - 1):
                draw.polygon([pts[0], pts[i], pts[i + 1]], fill=255)
                drawn_faces += 1

        return drawn_faces
    finally:
        eval_obj.to_mesh_clear()


def apply_black_mask(pil_img, mask):
    if mask is None or not mask.any():
        return pil_img

    mask_img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    if mask_img.size != pil_img.size:
        mask_img = mask_img.resize(pil_img.size, get_resample_filter())

    mask_arr = np.array(mask_img, dtype=np.uint8)
    if not mask_arr.any():
        return pil_img

    img_arr = np.array(pil_img)
    cond = mask_arr > 0
    img_arr[cond, 0:3] = 0
    img_arr[cond, 3] = np.maximum(img_arr[cond, 3], mask_arr[cond])
    return Image.fromarray(img_arr, mode="RGBA")


def build_inner_distance_gray(mask, max_distance, scale):
    gray = np.zeros(mask.shape, dtype=np.uint8)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return gray

    min_x = int(xs.min())
    max_x = int(xs.max()) + 1
    min_y = int(ys.min())
    max_y = int(ys.max()) + 1
    crop_mask = mask[min_y:max_y, min_x:max_x]

    padded_mask = np.zeros(
        (crop_mask.shape[0] + 2, crop_mask.shape[1] + 2), dtype=bool)
    padded_mask[1:-1, 1:-1] = crop_mask
    dist_sq = euclidean_distance_transform(~padded_mask)
    dist = dist_sq[1:-1, 1:-1]
    np.sqrt(dist, out=dist)
    dist -= 0.5
    np.maximum(dist, 0.0, out=dist)
    dist /= scale * float(max_distance)
    np.clip(dist, 0.0, 1.0, out=dist)
    crop_gray = dist
    crop_gray = (crop_gray * 255.0 + 0.5).astype(np.uint8)
    crop_gray[~crop_mask] = 0
    gray[min_y:max_y, min_x:max_x] = crop_gray
    return gray


def push_temp_export_undo(message):
    try:
        bpy.ops.ed.undo_push(message=message)
        return True
    except RuntimeError:
        return False


def reset_temp_export_undo(message):
    try:
        bpy.ops.ed.undo_push(message="")
        bpy.ops.ed.undo()
        bpy.ops.ed.undo_push(message=message)
        return True
    except RuntimeError:
        return False


def enter_object_mode_for_export(context):
    active_obj = context.view_layer.objects.active
    previous_mode = active_obj.mode if active_obj is not None else 'OBJECT'
    switched = False

    if active_obj is not None and previous_mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
            switched = True
        except RuntimeError:
            pass

    return active_obj, previous_mode, switched


def restore_export_mode(context, mode_state):
    active_obj, previous_mode, switched = mode_state
    if not switched or previous_mode == 'OBJECT' or active_obj is None:
        return
    if active_obj.name not in bpy.data.objects:
        return

    try:
        context.view_layer.objects.active = active_obj
        if active_obj.select_get():
            bpy.ops.object.mode_set(mode=previous_mode)
    except RuntimeError:
        pass


def set_modifier_enum_if_available(modifier, prop_name, value):
    if not hasattr(modifier, prop_name):
        return
    try:
        setattr(modifier, prop_name, value)
    except TypeError:
        pass


class OT_UVTools_BakeUVIslandImage(Operator, ExportHelper):
    """将所有选中物体的UV岛填充为纯色并导出为一张图像"""
    bl_idname = "ho.uvtools_bakeuvisland_image"
    bl_label = "导出UV岛填充图"
    bl_description = "将所有选中物体的UV岛填充为纯色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore

    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        island_id_counter = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            visited = set()

            for face in bm.faces:
                if face in visited:
                    continue

                # 广度优先搜索，找出一个UV岛
                island_faces = set()
                stack = [face]
                while stack:
                    f = stack.pop()
                    if f in island_faces:
                        continue
                    island_faces.add(f)
                    visited.add(f)

                    f_uvs = [l[uv_layer].uv for l in f.loops]
                    for edge in f.edges:
                        linked_faces = [
                            lf for lf in edge.link_faces if lf not in island_faces]
                        for lf in linked_faces:
                            lf_uvs = [l[uv_layer].uv for l in lf.loops]
                            shared = False
                            for uv1 in f_uvs:
                                for uv2 in lf_uvs:
                                    if (uv1 - uv2).length < 1e-5:
                                        shared = True
                                        break
                                if shared:
                                    break
                            if shared:
                                stack.append(lf)

                # 给这个UV岛分配一个随机颜色
                color = random_color(island_id_counter)
                island_id_counter += 1

                for f in island_faces:
                    if len(f.loops) < 3:
                        continue
                    uvs = [loop[uv_layer].uv for loop in f.loops]
                    pts = [(uv[0] * width, (1-uv[1]) * height) for uv in uvs]
                    for i in range(1, len(pts) - 1):
                        draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀每个区域颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出ID图像:{final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeMeshIslandImage(Operator, ExportHelper):
    """将所有选中物体的网格孤岛填充为纯色并导出为一张图像"""
    bl_idname = "ho.uvtools_bakemeshisland_image"
    bl_label = "导出网格孤岛填充图"
    bl_description = "将所有选中物体的网格孤岛填充为纯色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)

        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        island_id_counter = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            visited = set()

            for face in bm.faces:
                if face in visited:
                    continue

                # 搜索网格孤岛（拓扑连通）
                mesh_island = set()
                stack = [face]
                while stack:
                    f = stack.pop()
                    if f in mesh_island:
                        continue
                    mesh_island.add(f)
                    visited.add(f)
                    for edge in f.edges:
                        for linked_face in edge.link_faces:
                            if linked_face not in mesh_island:
                                stack.append(linked_face)

                # 给该孤岛上色
                color = random_color(island_id_counter)
                island_id_counter += 1
                for f in mesh_island:
                    if len(f.loops) < 3:
                        continue
                    uvs = [loop[uv_layer].uv for loop in f.loops]
                    pts = [(uv[0] * width, (1 - uv[1]) * height) for uv in uvs]
                    for i in range(1, len(pts) - 1):
                        draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀处理
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出网格孤岛图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeFaceIDImage(Operator, ExportHelper):
    """导出相邻面不同色的UV图像,用于面ID选择"""
    bl_idname = "ho.uvtools_bakefaceid_image"
    bl_label = "导出UV面ID图"
    bl_description = "将所有选中物体的面着色,相邻面使用不同颜色,导出为UV贴图图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    # type: ignore # 不限制后缀，由用户选择格式
    filter_glob: StringProperty(default="*", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        # 初始颜色使用颜色
        self.palette = [
            (255,   0,   0, 255),       # 红
            (0, 255,   0, 255),       # 绿
            (0,   0, 255, 255),       # 蓝
            (255, 255,   0, 255),       # 黄
            (255,   0, 255, 255),       # 品红
            (0, 255, 255, 255),       # 青
            (255, 128,   0, 255),       # 橙
            (128,   0, 255, 255),       # 紫
            (128, 128, 128, 255),       # 灰
            (255, 192, 203, 255),       # 粉红
            (128, 128,   0, 255),       # 橄榄绿
            (0, 128, 128, 255),       # 深青
            (128,   0,   0, 255),       # 深红
            (0, 128,   0, 255),       # 深绿
            (0,   0, 128, 255),       # 深蓝
            (255, 165,   0, 255),       # 橘黄
        ]

        def expand_palette(pal):
            """将颜色列表细分一倍（插值），保持颜色对比度"""
            new_palette = []
            for i in range(len(pal)):
                c1 = pal[i]
                c2 = pal[(i + 1) % len(pal)]
                new_palette.append(c1)
                # 插值
                blended = tuple((a + b) // 2 for a, b in zip(c1, c2))
                new_palette.append(blended)
            return new_palette

        def build_strict_adjacency(bm):
            vert_faces_map = {v: set() for v in bm.verts}
            for f in bm.faces:
                for v in f.verts:
                    vert_faces_map[v].add(f)

            face_neighbors = {}
            for f in bm.faces:
                neighbors = set()
                for v in f.verts:
                    neighbors.update(vert_faces_map[v])
                neighbors.discard(f)
                face_neighbors[f] = neighbors
            return face_neighbors

        def greedy_coloring(faces, neighbors, palette, max_attempts=5):
            for attempt in range(max_attempts):
                color_table = {}
                failed = False
                for f in faces:
                    used_colors = set(color_table.get(n, None)
                                      for n in neighbors[f])
                    for c in range(len(palette)):
                        if c not in used_colors:
                            color_table[f] = c
                            break
                    else:
                        failed = True
                        break
                if not failed:
                    return color_table
                palette[:] = expand_palette(palette)
                self.report({'WARNING'}, f"颜色不足，已扩展颜色数量到 {len(palette)}")
            return None

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            neighbors = build_strict_adjacency(bm)
            face_colors = greedy_coloring(bm.faces, neighbors, self.palette)
            if face_colors is None:
                self.report({'ERROR'}, f"{obj.name}：自动扩展颜色仍不足，导出失败")
                bm.free()
                eval_obj.to_mesh_clear()
                return {'CANCELLED'}

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue
                uvs = [loop[uv_layer].uv for loop in face.loops]
                pts = [(uv[0] * width, (1-uv[1]) * height) for uv in uvs]
                color_idx = face_colors[face]
                color = self.palette[color_idx]
                for i in range(1, len(pts) - 1):
                    tri = [pts[0], pts[i], pts[i + 1]]
                    draw.polygon(tri, fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀每个区域颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出ID图像:{final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeObjectIDImage(Operator, ExportHelper):
    """将每个选中物体填充为不同颜色并导出为一张图像"""
    bl_idname = "ho.uvtools_bake_objectid_image"
    bl_label = "导出物体ID图"
    bl_description = "将每个选中物体的UV填充为不同颜色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore

    image_format: EnumProperty(
        name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    )  # type: ignore

    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        for idx, obj in enumerate(selected_objs):
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            color = random_color(idx)

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue
                uvs = [loop[uv_layer].uv for loop in face.loops]
                pts = [(uv[0] * width, (1 - uv[1]) * height) for uv in uvs]
                for i in range(1, len(pts) - 1):
                    draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀边缘颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出物体ID图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeIslandUVMapImage(Operator, ExportHelper):
    """导出每个UV岛各自归一化的局部UV坐标图"""
    bl_idname = "ho.uvtools_bake_island_uvmap_image"
    bl_label = "导出岛UV图"
    bl_description = "每个UV岛单独归一化到0-1并写入RG通道, R=U, G=V"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 3] = background_alpha_255

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        skipped_objects = []

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                skipped_objects.append(f"{obj.name}(无UV)")
                bm.free()
                eval_obj.to_mesh_clear()
                continue

            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            for island_faces in find_uv_islands(bm, uv_layer):
                island_uvs = [
                    loop[uv_layer].uv
                    for face in island_faces
                    for loop in face.loops
                ]
                if not island_uvs:
                    continue

                min_u = min(uv.x for uv in island_uvs)
                max_u = max(uv.x for uv in island_uvs)
                min_v = min(uv.y for uv in island_uvs)
                max_v = max(uv.y for uv in island_uvs)
                u_range = max_u - min_u
                v_range = max_v - min_v
                if abs(u_range) < 1e-8:
                    u_range = 1.0
                if abs(v_range) < 1e-8:
                    v_range = 1.0

                for face in island_faces:
                    if len(face.loops) < 3:
                        continue

                    uvs = [loop[uv_layer].uv.copy() for loop in face.loops]
                    pts = [(uv.x * width, (1.0 - uv.y) * height)
                           for uv in uvs]
                    local_uvs = [((uv.x - min_u) / u_range,
                                  (uv.y - min_v) / v_range)
                                 for uv in uvs]

                    for i in range(1, len(pts) - 1):
                        fill_local_uv_triangle(
                            img_arr,
                            [pts[0], pts[i], pts[i + 1]],
                            [local_uvs[0], local_uvs[i], local_uvs[i + 1]]
                        )

                island_count += 1

            bm.free()
            eval_obj.to_mesh_clear()

        if island_count == 0:
            self.report({'ERROR'}, "没有可导出的UV岛")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出岛UV图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeIslandSDFImage(Operator, ExportHelper):
    """导出UV岛内部到边缘的欧氏距离场"""
    bl_idname = "ho.uvtools_bake_island_sdf_image"
    bl_label = "导出岛SDF图"
    bl_description = "离线烘焙UV岛内部到边缘的精确欧氏距离场,白色表示离边缘更远"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore
    max_distance: IntProperty(
        name="最大距离像素", default=64, min=1, description="达到此岛内距离后输出纯白")  # type: ignore
    temp_subdivide: BoolProperty(
        name="临时细分2级", default=False, description="烘焙前临时添加2级Subdivision Surface,导出后自动移除")  # type: ignore
    temp_subdivide_uv_smooth: EnumProperty(name="细分UV平滑",
                                           items=[
                                               ('SMOOTH_ALL', "平滑全部", "使用细分后的平滑UV形状"),
                                               ('PRESERVE_BOUNDARIES', "保留边界", "保持UV岛边界锐利")
                                           ],
                                           default='SMOOTH_ALL'
                                           )  # type: ignore
    fill_subdivide_shrink: BoolProperty(
        name="补黑细分收缩", default=True, description="对比原始UV和细分后UV,将细分后收缩掉的像素填黑")  # type: ignore
    supersample: EnumProperty(name="超采样",
                              items=[
                                  ('1', "1x", "最快"),
                                  ('2', "2x", "更平滑"),
                                  ('4', "4x", "最平滑,内存和时间开销较高")
                              ],
                              default='1'
                              )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")
        layout.prop(self, "max_distance")
        layout.prop(self, "temp_subdivide")
        if self.temp_subdivide:
            layout.prop(self, "temp_subdivide_uv_smooth")
            layout.prop(self, "fill_subdivide_shrink")
        layout.prop(self, "supersample")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        width = self.image_width
        height = self.image_height
        scale = int(self.supersample)
        hi_width = width * scale
        hi_height = height * scale
        if hi_width * hi_height > 100_000_000:
            self.report({'ERROR'}, "岛SDF超采样图过大,请降低图像尺寸或超采样倍率")
            return {'CANCELLED'}

        mask_img = Image.new("L", (hi_width, hi_height), 0)
        draw = ImageDraw.Draw(mask_img)
        base_mask_img = None
        base_draw = None
        if self.temp_subdivide and self.fill_subdivide_shrink:
            base_mask_img = Image.new("L", (hi_width, hi_height), 0)
            base_draw = ImageDraw.Draw(base_mask_img)
        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        skipped_objects = []
        undo_restore_needed = False
        temp_modifiers = []

        if self.temp_subdivide:
            undo_restore_needed = push_temp_export_undo(
                "Prepare HoTools Island SDF")

        try:
            raster_objs = selected_objs
            if base_draw is not None:
                raster_objs = []
                for obj in selected_objs:
                    base_island_count = rasterize_object_uv_mask(
                        obj, depsgraph, base_draw, hi_width, hi_height)
                    if base_island_count is None:
                        skipped_objects.append(f"{obj.name}(无UV)")
                        continue
                    raster_objs.append(obj)

            if self.temp_subdivide:
                for obj in raster_objs:
                    temp_modifier = obj.modifiers.new(
                        name="__HoTools_Temp_SDF_Subdivide__",
                        type='SUBSURF'
                    )
                    temp_modifier.levels = 2
                    temp_modifier.render_levels = 2
                    temp_modifier.subdivision_type = 'CATMULL_CLARK'
                    set_modifier_enum_if_available(
                        temp_modifier,
                        "uv_smooth",
                        self.temp_subdivide_uv_smooth
                    )
                    temp_modifiers.append((obj, temp_modifier))
                context.view_layer.update()
                depsgraph = context.evaluated_depsgraph_get()

            for obj in raster_objs:
                object_island_count = rasterize_object_uv_mask(
                    obj, depsgraph, draw, hi_width, hi_height)
                if object_island_count is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                island_count += object_island_count
        finally:
            if self.temp_subdivide:
                restored_by_undo = False
                if undo_restore_needed:
                    restored_by_undo = reset_temp_export_undo(
                        "Bake HoTools Island SDF")
                if not restored_by_undo:
                    for obj, temp_modifier in reversed(temp_modifiers):
                        try:
                            obj.modifiers.remove(temp_modifier)
                        except (ReferenceError, RuntimeError):
                            pass
                    context.view_layer.update()

        if island_count == 0:
            self.report({'ERROR'}, "没有可导出的UV岛")
            return {'CANCELLED'}

        mask = np.array(mask_img, dtype=np.uint8) > 0
        if not mask.any():
            self.report({'ERROR'}, "UV岛没有落在导出图像范围内")
            return {'CANCELLED'}

        shrink_mask = None
        if base_mask_img is not None:
            base_mask = np.array(base_mask_img, dtype=np.uint8) > 0
            shrink_mask = base_mask & ~mask

        gray = build_inner_distance_gray(mask, self.max_distance, scale)

        alpha_inside = np.full_like(gray, 255, dtype=np.uint8)
        alpha_outside = np.full_like(gray, int(self.background_alpha * 255), dtype=np.uint8)
        alpha = np.where(mask, alpha_inside, alpha_outside).astype(np.uint8)
        rgba = np.dstack((gray, gray, gray, alpha))
        pil_img = Image.fromarray(rgba, mode="RGBA")

        if scale > 1:
            pil_img = pil_img.resize((width, height), get_resample_filter())

        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)
        pil_img = apply_black_mask(pil_img, shrink_mask)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出岛SDF图像: {final_path}")
        return {'FINISHED'}


def linear_channel_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * pow(c, 1.0 / 2.4) - 0.055


def linear_to_srgb(color):
    return [linear_channel_to_srgb(c) for c in color]


class OT_UVTools_BakeVertexColorImage(Operator, ExportHelper):
    """导出选中物体的顶点色贴图（无顶点色则为黑）"""
    bl_idname = "ho.uvtools_bake_vertex_color_image"
    bl_label = "导出顶点色贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        width = self.image_width
        height = self.image_height
        alpha_val = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, alpha_val))
        draw = ImageDraw.Draw(pil_img)

        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()

            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            color_layer = bm.loops.layers.color.active

            if uv_layer is None:
                bm.free()
                eval_obj.to_mesh_clear()
                self.report({'WARNING'}, f"{obj.name} 没有UV,跳过")
                continue

            bm.faces.ensure_lookup_table()

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue

                uvs = [loop[uv_layer].uv for loop in face.loops]
                if color_layer:
                    cols = [loop[color_layer][:4] for loop in face.loops]
                else:
                    # 没有数据就填充白色，因bl对没有颜色属性的物体显示为白色，有但是没启用的为黑色（极少见）
                    cols = [(1.0, 1.0, 1.0, 1.0)] * len(uvs)

                # 转为 0-255 范围
                cols = [
                    (
                        int(c[0] * 255),
                        int(c[1] * 255),
                        int(c[2] * 255),
                        int(c[3] * 255)
                    ) for c in cols
                ]

                px_uvs = [(int(uv.x * width), int((1.0 - uv.y) * height))
                          for uv in uvs]

                for i in range(1, len(px_uvs) - 1):
                    pts = [px_uvs[0], px_uvs[i], px_uvs[i + 1]]
                    cols_rgb = [cols[0], cols[i], cols[i + 1]]

                    # 用平均颜色填充三角形
                    avg_col = tuple(
                        int(sum(c[j] for c in cols_rgb) / 3) for j in range(4))
                    draw.polygon(pts, fill=avg_col)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀颜色边界
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出顶点色贴图: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeActiveVertexGroupImage(Operator, ExportHelper):
    """导出选中物体的活动顶点组权重贴图，无活动顶点组则跳过"""
    bl_idname = "ho.uvtools_bake_active_vertex_group_image"
    bl_label = "导出顶点组权重贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def get_vertex_group_weight(obj, vertex_index, group_index):
            try:
                return obj.vertex_groups[group_index].weight(vertex_index)
            except RuntimeError:
                return 0.0

        width = self.image_width
        height = self.image_height
        alpha_val = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, alpha_val))
        img_arr = np.array(pil_img)

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        exported_count = 0
        skipped_objects = []

        for obj in selected_objs:
            vertex_group = obj.vertex_groups.active
            if vertex_group is None:
                skipped_objects.append(f"{obj.name}(无活动顶点组)")
                continue

            mesh = obj.data
            uv_layer = mesh.uv_layers.active
            if uv_layer is None:
                skipped_objects.append(f"{obj.name}(无UV)")
                continue

            group_index = vertex_group.index

            for poly in mesh.polygons:
                loop_indices = poly.loop_indices
                if len(loop_indices) < 3:
                    continue

                uvs = []
                weights = []
                for loop_index in loop_indices:
                    loop = mesh.loops[loop_index]
                    uv = uv_layer.data[loop_index].uv
                    uvs.append((int(uv.x * width), int((1.0 - uv.y) * height)))
                    weights.append(
                        get_vertex_group_weight(obj, loop.vertex_index, group_index))

                for i in range(1, len(uvs) - 1):
                    pts = [uvs[0], uvs[i], uvs[i + 1]]
                    tri_weights = [weights[0], weights[i], weights[i + 1]]
                    fill_weight_triangle(img_arr, pts, tri_weights)

            exported_count += 1

        if exported_count == 0:
            self.report({'ERROR'}, "没有可导出的活动顶点组权重")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出活动顶点组权重贴图: {final_path}")
        return {'FINISHED'}


class OT_UVTools_FastBakeUVImage(Operator, ExportHelper):
    """快速合并导出psd模板"""
    bl_idname = "ho.uvtools_fastbake_uv_image"
    bl_label = "快速导出"
    bl_description = "快速导出多张贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*.png", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", description="空白区域的透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", description="向外扩张的像素数,用于消除UV边缘缝隙", default=2, min=0)  # type: ignore

    export_UVIslandImage: BoolProperty(
        name="UV岛", default=True)  # type: ignore
    export_IslandUVMapImage: BoolProperty(
        name="岛UV", default=True)  # type: ignore
    export_MeshIslandImage: BoolProperty(
        name="Mesh岛", default=True)  # type: ignore
    export_FaceIDImage: BoolProperty(name="面", default=True)  # type: ignore
    export_ObjectIDImage: BoolProperty(name="物体", default=True)  # type: ignore
    export_LineImage: BoolProperty(name="线框", default=True)  # type: ignore

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "export_UVIslandImage", toggle=True)
        col.prop(self, "export_IslandUVMapImage", toggle=True)
        col.prop(self, "export_MeshIslandImage", toggle=True)
        col.prop(self, "export_FaceIDImage", toggle=True)
        col.prop(self, "export_ObjectIDImage", toggle=True)
        col.prop(self, "export_LineImage", toggle=True)

        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        base_path = os.path.splitext(self.filepath)[0]
        temp_files = []
        width = self.image_width
        height = self.image_height
        alpha = self.background_alpha
        radius = self.dilate_radius

        # 调用UV岛导出
        if self.export_UVIslandImage:
            result = bpy.ops.ho.uvtools_bakeuvisland_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_UVIsland.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "UV岛导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_UVIsland.png")

        # 调用每岛UV图导出
        if self.export_IslandUVMapImage:
            result = bpy.ops.ho.uvtools_bake_island_uvmap_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_IslandUV.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "岛UV导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_IslandUV.png")

         # 调用Mesh岛导出
        if self.export_MeshIslandImage:
            result = bpy.ops.ho.uvtools_bakemeshisland_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_MeshIsland.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "Mesh岛导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_MeshIsland.png")

        # 调用FaceID导出
        if self.export_FaceIDImage:
            result = bpy.ops.ho.uvtools_bakefaceid_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_FaceID.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "面ID导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_FaceID.png")

        # 调用ObjectID导出
        if self.export_ObjectIDImage:
            result = bpy.ops.ho.uvtools_bake_objectid_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_ObjectID.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "物体ID导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_ObjectID.png")

        # 调用线框导出
        if self.export_LineImage:
            result = bpy.ops.uv.export_layout(
                filepath=base_path + "_Wire.png",
                export_all=False,
                modified=False,
                mode='PNG',
                size=(width, height),
                opacity=0.0,
                check_existing=False
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "线框导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_Wire.png")

        self.report({'INFO'}, f"导出完成: {len(temp_files)} 个图像生成")
        return {'FINISHED'}


def drawBakePanel(layout: bpy.types.UILayout, context):
    box = layout.box()
    box.label(text="导出UV贴图")
    row = box.row(align=True)
    row.operator(OT_UVTools_FastBakeUVImage.bl_idname, text="", icon="FUND")
    row.operator(OT_UVTools_BakeUVIslandImage.bl_idname, text="UV岛")
    row.operator(OT_UVTools_BakeMeshIslandImage.bl_idname, text="Mesh岛")
    row.operator(OT_UVTools_BakeFaceIDImage.bl_idname, text="面ID")
    row.operator(OT_UVTools_BakeObjectIDImage.bl_idname, text="物体ID")
    row.operator("uv.export_layout", text="网格")
    row = box.row(align=True)
    row.operator(OT_UVTools_BakeVertexColorImage.bl_idname, text="活动顶点色")

    row.operator(OT_UVTools_BakeActiveVertexGroupImage.bl_idname, text="活动顶点组")
    row.operator(OT_UVTools_BakeIslandUVMapImage.bl_idname, text="每岛UV")
    row.operator(OT_UVTools_BakeIslandSDFImage.bl_idname, text="岛SDF")


    # box = layout.box()
    # box.label(text="检查UV")

    return


cls = [OT_UVTools_BakeUVIslandImage, OT_UVTools_BakeIslandUVMapImage, OT_UVTools_BakeIslandSDFImage, OT_UVTools_BakeFaceIDImage, OT_UVTools_BakeObjectIDImage, OT_UVTools_BakeMeshIslandImage,
       OT_UVTools_BakeVertexColorImage,
       OT_UVTools_BakeActiveVertexGroupImage,
       OT_UVTools_FastBakeUVImage,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    ureg_props()
