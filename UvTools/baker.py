import bpy
import sys
import os
import random
import numpy as np

if sys.version_info >= (3, 11):
    from .._Lib.py311.PIL import Image, ImageDraw
else:
    from .._Lib.py310.PIL import Image, ImageDraw

import bmesh
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
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

class OT_UVTools_BakeUVIslandImage(Operator, ExportHelper):
    """将所有选中物体的UV岛填充为纯色并导出为一张图像"""
    bl_idname = "ho.uvtools_bakeuvisland_image"
    bl_label = "导出UV岛填充图"
    bl_description = "将所有选中物体的UV岛填充为纯色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1) # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1) # type: ignore

    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0,description="空白区域的透明度") # type: ignore

    image_format: EnumProperty(name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    ) # type: ignore

    dilate_radius: IntProperty(name="膨胀像素数",default=2,min=0,description="向外扩张的像素数,用于消除UV边缘缝隙") # type: ignore

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

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']

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
                        linked_faces = [lf for lf in edge.link_faces if lf not in island_faces]
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
    filter_glob: StringProperty(default="*", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1) # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1) # type: ignore
    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度") # type: ignore
    image_format: EnumProperty(name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    ) # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙") # type: ignore

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
        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)

        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
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
    filter_glob: StringProperty(default="*", options={'HIDDEN'})  # type: ignore # 不限制后缀，由用户选择格式

    image_width: IntProperty(name="图像宽度", default=2048, min=1) # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1) # type: ignore

    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0,description="空白区域的透明度") # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数",default=2,min=0,description="向外扩张的像素数,用于消除UV边缘缝隙") # type: ignore

    image_format: EnumProperty(name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    ) # type: ignore

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
            (  0, 255,   0, 255),       # 绿
            (  0,   0, 255, 255),       # 蓝
            (255, 255,   0, 255),       # 黄
            (255,   0, 255, 255),       # 品红
            (  0, 255, 255, 255),       # 青
            (255, 128,   0, 255),       # 橙
            (128,   0, 255, 255),       # 紫
            (128, 128, 128, 255),       # 灰
            (255, 192, 203, 255),       # 粉红
            (128, 128,   0, 255),       # 橄榄绿
            (  0, 128, 128, 255),       # 深青
            (128,   0,   0, 255),       # 深红
            (  0, 128,   0, 255),       # 深绿
            (  0,   0, 128, 255),       # 深蓝
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
                    used_colors = set(color_table.get(n, None) for n in neighbors[f])
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

        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, background_alpha_255))
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
    filter_glob: StringProperty(default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore

    image_format: EnumProperty(
        name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    )  # type: ignore

    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

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

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']

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
    filter_glob: StringProperty(default="*", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1) # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1) # type: ignore
    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0) # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0) # type: ignore
    image_format: EnumProperty(name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    ) # type: ignore
    
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
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']

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
                    cols = [(1.0, 1.0, 1.0, 1.0)] * len(uvs)#没有数据就填充白色，因bl对没有颜色属性的物体显示为白色，有但是没启用的为黑色（极少见）

                # 转为 0-255 范围
                cols = [
                    (
                        int(c[0] * 255),
                        int(c[1] * 255),
                        int(c[2] * 255),
                        int(c[3] * 255)
                    ) for c in cols
                ]

                px_uvs = [(int(uv.x * width), int((1.0 - uv.y) * height)) for uv in uvs]

                for i in range(1, len(px_uvs) - 1):
                    pts = [px_uvs[0], px_uvs[i], px_uvs[i + 1]]
                    cols_rgb = [cols[0], cols[i], cols[i + 1]]

                    # 用平均颜色填充三角形
                    avg_col = tuple(int(sum(c[j] for c in cols_rgb) / 3) for j in range(4))
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

class OT_UVTools_FastBakeUVImage(Operator, ExportHelper):
    """快速合并导出psd模板"""
    bl_idname = "ho.uvtools_fastbake_uv_image"
    bl_label = "快速导出"
    bl_description = "快速导出多张贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*.png", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1) # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1) # type: ignore

    background_alpha: FloatProperty(name="背景透明度",description="空白区域的透明度", default=0.0, min=0.0, max=1.0) # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数",description="向外扩张的像素数,用于消除UV边缘缝隙",default=2,min=0) # type: ignore

    export_UVIslandImage:BoolProperty(name="UV岛",default=True) # type: ignore
    export_MeshIslandImage:BoolProperty(name="Mesh岛",default=True) # type: ignore
    export_FaceIDImage:BoolProperty(name="面",default=True) # type: ignore
    export_ObjectIDImage:BoolProperty(name="物体",default=True) # type: ignore
    export_LineImage:BoolProperty(name="线框",default=True) # type: ignore

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self,"export_UVIslandImage",toggle=True)
        col.prop(self,"export_MeshIslandImage",toggle=True)
        col.prop(self,"export_FaceIDImage",toggle=True)
        col.prop(self,"export_ObjectIDImage",toggle=True)
        col.prop(self,"export_LineImage",toggle=True)
        

        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "dilate_radius")


    def execute(self, context):
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


class PL_UvTools(Panel):
    bl_idname = "VIEW_PT_Hollow_UvTools"
    bl_label = "UV工具"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "HoTools"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="导出UV贴图")
        row = box.row(align=True)
        row.operator(OT_UVTools_FastBakeUVImage.bl_idname,text="",icon="FUND")
        row.operator(OT_UVTools_BakeUVIslandImage.bl_idname, text="UV岛")
        row.operator(OT_UVTools_BakeMeshIslandImage.bl_idname, text="Mesh岛")
        row.operator(OT_UVTools_BakeFaceIDImage.bl_idname, text="面ID")
        row.operator(OT_UVTools_BakeObjectIDImage.bl_idname, text="物体ID")
        row.operator("uv.export_layout", text="网格")
        row = box.row(align=True)
        row.operator(OT_UVTools_BakeVertexColorImage.bl_idname, text="活动顶点色")
        

        # box = layout.box()
        # box.label(text="检查UV")

        return



   

cls = [PL_UvTools,
       OT_UVTools_BakeUVIslandImage,OT_UVTools_BakeFaceIDImage,OT_UVTools_BakeObjectIDImage,OT_UVTools_BakeMeshIslandImage,
       OT_UVTools_BakeVertexColorImage,
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
