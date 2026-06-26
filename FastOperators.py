import bpy
import sys
import os
import json
import subprocess
import random
import numpy as np
import blf
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
import gpu
from collections import defaultdict
if sys.version_info >= (3, 13):
    from ._Lib.py313.PIL import Image, ImageDraw, ImageFilter
elif sys.version_info >= (3, 11):
    from ._Lib.py311.PIL import Image, ImageDraw, ImageFilter

import bmesh
import math
from bpy.types import Operator, Panel, Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty, FloatVectorProperty
import bmesh

from mathutils import Vector, Matrix, Euler
from bpy_extras import view3d_utils
from bpy_extras.io_utils import ExportHelper, ImportHelper
from .i18n import tr


def reg_props():
    return


def ureg_props():
    return


class OP_select_inside_face_loop(bpy.types.Operator):
    bl_idname = "ho.select_inside_face_loop"
    bl_label = "填充选择"
    bl_options = {'REGISTER', 'UNDO'}

    event: bpy.types.Event
    location: tuple[int, int]

    @classmethod
    def poll(cls, context):
        # 确保操作在网格对象的编辑模式下执行
        return context.active_object and context.active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        ops = bpy.ops
        mesh = ops.mesh

        mesh.hide()
        ops.view3d.select(location=self.location)
        mesh.select_linked()
        mesh.reveal()
        return {'FINISHED'}

    def invoke(self, context, event):
        self.event = event
        self.location = (event.mouse_region_x, event.mouse_region_y)
        return self.execute(context)


class OP_RestartBlender(Operator):
    bl_idname = "ho.restart_blender"
    bl_label = "快速重启"
    bl_description = "不保存并重启 Blender"
    
    @classmethod
    def description(cls, context, properties):
        return tr("不保存并重启 Blender")
    bl_options = {'REGISTER'}

    def execute(self, context):
        blender_exe = bpy.app.binary_path
        filepath = bpy.data.filepath

        args = [blender_exe]

        if filepath:
            args.append(filepath)

        subprocess.Popen(args)
        bpy.ops.wm.quit_blender()

        return {'FINISHED'}


class OP_sync_render_visibility(Operator):
    bl_idname = "ho.sync_render_visibility"
    bl_label = "同步渲染/视图层显示"
    bl_description = "将所有启用物体的渲染与视图层显示同步"
    
    @classmethod
    def description(cls, context, properties):
        return tr("将所有启用物体的渲染与视图层显示同步")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        view_layer = context.view_layer

        # 遍历视图层中的所有集合
        for collection in view_layer.layer_collection.children:
            collection: bpy.types.LayerCollection
            if not collection.exclude:  # 只处理没有被排除的集合（本属性数据api与大纲绘制值相反，原因是指代不同
                # 遍历集合中的所有物体
                collection.collection.hide_render = collection.hide_viewport
        for obj in context.scene.objects:
            obj.hide_render = obj.hide_get()

        return {'FINISHED'}


class OP_CopyALL_modifiers_to_selected(Operator):
    bl_idname = "ho.copyall_modifiers_to_selected"
    bl_label = "复制全部修改器到所选"
    bl_description = "按顺序复制全部修改器到所选物体"
    
    @classmethod
    def description(cls, context, properties):
        return tr("按顺序复制全部修改器到所选物体")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取活动物体和选中物体列表
        active_obj = context.active_object
        selected_objs = context.selected_objects

        if not active_obj:
            self.report({'ERROR'}, tr("没有活动物体"))
            return {'CANCELLED'}

        if len(selected_objs) < 2:
            self.report({'ERROR'}, tr("需要选择至少两个物体（源物体+目标物体）"))
            return {'CANCELLED'}

        modifiers = active_obj.modifiers
        if not modifiers:
            self.report({'INFO'}, tr("活动物体没有修改器"))
            return {'FINISHED'}

        try:
            for m in modifiers:
                bpy.ops.object.modifier_copy_to_selected(
                    modifier=m.name
                )
        except RuntimeError as e:
            self.report({'ERROR'}, tr("复制失败: {0}").format(str(e)))
            return {'CANCELLED'}

        self.report({'INFO'}, tr("成功复制 {0} 个修改器").format(len(modifiers)))
        return {'FINISHED'}


class OP_PlaceObjectBottom(Operator):
    bl_idname = "ho.placeobjectbottom"
    bl_label = "选择底面放置"
    bl_description = "使用选择的面作为底面，旋转物体使底面贴合水平面摆放"
    
    @classmethod
    def description(cls, context, properties):
        return tr("使用选择的面作为底面，旋转物体使底面贴合水平面摆放")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')
        obj = context.active_object
        mesh = obj.data
        mat_world = obj.matrix_world

        # 计算选中面法线平均向量
        normal_sum = Vector((0, 0, 0))
        for poly in mesh.polygons:
            if poly.select:
                normal_sum += (mat_world.to_3x3() @ poly.normal)
        if normal_sum.length == 0:
            self.report({'ERROR'}, tr("未选择任何面"))
            return {'CANCELLED'}
        avg_normal = normal_sum.normalized()

        target_normal = Vector((0, 0, -1))  # 目标朝下

        axis = avg_normal.cross(target_normal)
        angle = avg_normal.angle(target_normal)

        if axis.length < 1e-6:
            # 平行或反向
            if avg_normal.dot(target_normal) < 0:
                # 180度旋转，任选垂直轴
                axis = Vector((1, 0, 0))
                angle = math.pi
            else:
                axis = Vector((0, 0, 1))
                angle = 0
        else:
            axis.normalize()

        # 转换旋转到物体本地坐标系
        local_axis = obj.matrix_world.to_3x3().inverted() @ axis
        # 叠加到物体的欧拉旋转（先确保是欧拉旋转模式）
        if obj.rotation_mode != 'XYZ':
            obj.rotation_mode = 'XYZ'

        # 通过轴角转换为欧拉角增量
        delta_rot = Euler(local_axis * angle, 'XYZ')

        # 叠加旋转（通过矩阵乘法）
        rot_mat = obj.rotation_euler.to_matrix().to_4x4()
        delta_mat = delta_rot.to_matrix().to_4x4()
        new_rot_mat = delta_mat @ rot_mat
        obj.rotation_euler = new_rot_mat.to_euler('XYZ')

        # 刷新依赖，更新变换
        context.view_layer.update()

        # 重新计算选中面旋转后顶点的最低点Z
        new_verts_z = []
        for poly in mesh.polygons:
            if poly.select:
                for idx in poly.vertices:
                    v_world = obj.matrix_world @ mesh.vertices[idx].co
                    new_verts_z.append(v_world.z)

        if not new_verts_z:
            self.report({'ERROR'}, tr("旋转后无法计算高度"))
            return {'CANCELLED'}

        min_z = min(new_verts_z)
        obj.location.z -= min_z

        return {'FINISHED'}


class OP_AlignViewToAvgNormal(Operator):
    bl_idname = "ho.align_to_avg_normal"
    bl_label = "视图对准面"
    bl_description = "根据当前选中面的平均法向，将视图对准法向的负方向"
    
    @classmethod
    def description(cls, context, properties):
        return tr("根据当前选中面的平均法向，将视图对准法向的负方向")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # 只能在 3D 视图且编辑网格模式下启用
        return (context.area.type == 'VIEW_3D' and
                context.object is not None and
                context.object.type == 'MESH' and
                context.mode == 'EDIT_MESH')

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        # 切换到 OBJECT 模式以便读取世界坐标下的法线
        bpy.ops.object.mode_set(mode='OBJECT')
        mat_world = obj.matrix_world

        # 计算选中面法线的世界空间平均向量
        normal_sum = Vector((0.0, 0.0, 0.0))
        for poly in mesh.polygons:
            if poly.select:
                normal_sum += mat_world.to_3x3() @ poly.normal

        if normal_sum.length == 0.0:
            self.report({'ERROR'}, tr("未选择任何面"))
            bpy.ops.object.mode_set(mode='EDIT')
            return {'CANCELLED'}

        avg_normal = normal_sum.normalized()
        # 我们希望视图沿 avg_normal 的反方向（法向朝向视点）
        view_dir = -avg_normal

        # 获取 3D 视图的 Region3D，设置为正交并对准法向
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                region_3d = area.spaces.active.region_3d
                # # 切换到正交视图
                # region_3d.view_perspective = 'ORTHO'
                # 计算旋转四元数：将本地 -Z 轴（视图朝向）对齐到 view_dir
                rot_quat = view_dir.to_track_quat('-Z', 'Y')
                region_3d.view_rotation = rot_quat
                # 可选：调整缩放或距离，以便更好地查看
                # region_3d.view_distance = max(mesh.dimensions) * 2.0
                break

        # 切回编辑模式
        bpy.ops.object.mode_set(mode='EDIT')

        return {'FINISHED'}


class OP_CustomSplitNormals_Export(Operator, ExportHelper):
    bl_idname = "ho.custom_splitnormal_export"
    bl_label = "导出自定义拆边法向为文件"
    bl_description = "如果没有添加自定义法线则跳过"
    
    @classmethod
    def description(cls, context, properties):
        return tr("如果没有添加自定义法线则跳过")
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        if not mesh.has_custom_normals:
            self.report({'WARNING'}, tr("当前网格没有自定义法线"))
            return {'CANCELLED'}

        # 确保在对象模式，否则 loop.normal 访问不正常
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 提取 loop normals
        normals = [list(loop.normal) for loop in mesh.loops]

        # 保存为 JSON
        import json
        try:
            with open(self.filepath, 'w') as f:
                json.dump(normals, f)
        except Exception as e:
            self.report({'ERROR'}, tr("导出失败: {0}").format(e))
            return {'CANCELLED'}

        self.report({'INFO'}, tr("已导出 {0} 个自定义法线").format(len(normals)))
        return {'FINISHED'}


class OP_CustomSplitNormals_Import(Operator, ImportHelper):
    bl_idname = "ho.custom_splitnormal_import"
    bl_label = "导入自定义拆边法向文件"
    bl_description = "覆盖当前的自定义法向"
    
    @classmethod
    def description(cls, context, properties):
        return tr("覆盖当前的自定义法向")
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        try:
            with open(self.filepath, 'r') as f:
                normal_data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, tr("读取文件失败: {0}").format(e))
            return {'CANCELLED'}

        if len(normal_data) != len(mesh.loops):
            self.report(
                {'ERROR'}, tr("法线数量不匹配 ({0} vs {1})").format(len(normal_data), len(mesh.loops)))
            return {'CANCELLED'}

        # 转换为 Vector 列表
        from mathutils import Vector
        split_normals = [Vector(n).normalized() for n in normal_data]

        # mesh.use_auto_smooth = True
        mesh.normals_split_custom_set(split_normals)
        self.report({'INFO'}, tr("成功导入并应用 {0} 个法线").format(len(split_normals)))
        return {'FINISHED'}


class OP_AddSelectSideRingLoops(Operator):
    bl_idname = "ho.addselect_sideringloops"
    bl_label = "加选Ring"
    bl_description = "选择并排的循环边线,如果选中中的不是loop会尝试首先选择loop"
    
    @classmethod
    def description(cls, context, properties):
        return tr("选择并排的循环边线,如果选中中的不是loop会尝试首先选择loop")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):

        obj = context.active_object
        me = obj.data

        # 1️⃣ 如果选中的不是完整 loop，先补全 loop
        bpy.ops.mesh.loop_multi_select(ring=False)

        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()  # 刷新索引表
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        selected_edges = [e for e in bm.edges if e.select]

        if not selected_edges:
            self.report({'WARNING'}, tr("没有选中任何边"))
            return {'CANCELLED'}

        side_edges = set()

        # 2️⃣ 对每条已选边，查找相邻的“并排ring边”
        for edge in selected_edges:

            if len(edge.link_faces) != 2:
                continue  # 非流形边跳过

            for face in edge.link_faces:

                # 找到该面中与当前边“相对”的边（quad专用）
                if len(face.edges) == 4:
                    for e in face.edges:
                        if e != edge and not any(v in edge.verts for v in e.verts):
                            side_edges.add(e)

        # 3️⃣ 选中这些并排边
        for e in side_edges:
            e.select = True

        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

        return {'FINISHED'}


class OP_RemoveSelectSideRingLoops(Operator):
    bl_idname = "ho.removeselect_sideringloops"
    bl_label = "减选Ring"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):

        obj = context.active_object
        me = obj.data
        bm = bmesh.from_edit_mesh(me)

        bm.faces.ensure_lookup_table()  # 刷新索引表
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        selected_edges = {e for e in bm.edges if e.select}

        if not selected_edges:
            return {'CANCELLED'}

        ring_neighbors = {e: set() for e in selected_edges}

        # 建立 ring 邻接关系
        for edge in selected_edges:

            for face in edge.link_faces:

                if len(face.edges) != 4:
                    continue

                # 找对边（ring方向）
                for e in face.edges:
                    if e != edge and not any(v in edge.verts for v in e.verts):
                        if e in selected_edges:
                            ring_neighbors[edge].add(e)
                        break

        # 找外层（只有一个ring邻居的）
        edges_to_remove = {
            e for e, neighbors in ring_neighbors.items()
            if len(neighbors) <= 1
        }

        for e in edges_to_remove:
            e.select = False

        bmesh.update_edit_mesh(me)

        return {'FINISHED'}


class OP_CreatBoneChainByMeshFlow(Operator):
    bl_idname = "ho.create_bone_chain_by_meshflow"
    bl_label = "根据选中的线段创建骨骼链"
    bl_options = {'REGISTER', 'UNDO'}

    num_segments: IntProperty(
        name="段数",
        default=4,
        min=1,
    )  # type: ignore

    direction_mode: EnumProperty(
        name="方向模式",
        items=[
            ('FORWARD', "正向", ""),
            ('REVERSE', "反向", ""),
            ('CURSOR', "指向游标", ""),
            ('CURSORMINUS', "远离游标", ""),
        ],
        default='FORWARD'
    )  # type: ignore

    auto_rename: bpy.props.BoolProperty(
        name="自动重命名",
        description="创建完成后自动联动hotools规则重命名",
        default=False
    )  # type: ignore

    # 获取所有连通 flow

    align_roll_to_normal: BoolProperty(
        name="扭转对齐法线",
        description="创建骨骼时让每段骨骼的扭转对齐到对应边的法线",
        default=True
    )  # type: ignore

    def get_edge_world_normal(self, normal_matrix, edge):
        normal_sum = Vector((0.0, 0.0, 0.0))

        for face in edge.link_faces:
            normal_sum += (normal_matrix @ face.normal).normalized()

        if normal_sum.length <= 1e-6:
            return None

        return normal_sum.normalized()

    def build_sampled_segment_normals(self, lengths, edge_normals, total_length):
        if not edge_normals or len(edge_normals) != len(lengths):
            return [None] * self.num_segments

        sampled_normals = []
        edge_ranges = []
        start = 0.0

        for length, normal in zip(lengths, edge_normals):
            edge_ranges.append((start, start + length, normal))
            start += length

        step = total_length / self.num_segments

        for index in range(self.num_segments):
            seg_start = index * step
            seg_end = total_length if index == self.num_segments - 1 else (index + 1) * step
            normal_sum = Vector((0.0, 0.0, 0.0))

            for edge_start, edge_end, edge_normal in edge_ranges:
                if edge_normal is None:
                    continue

                overlap = min(seg_end, edge_end) - max(seg_start, edge_start)
                if overlap > 1e-6:
                    normal_sum += edge_normal * overlap

            if normal_sum.length <= 1e-6:
                center = (seg_start + seg_end) * 0.5
                for edge_start, edge_end, edge_normal in edge_ranges:
                    if edge_normal is None:
                        continue
                    if edge_start - 1e-6 <= center <= edge_end + 1e-6:
                        normal_sum = edge_normal.copy()
                        break

            sampled_normals.append(
                normal_sum.normalized() if normal_sum.length > 1e-6 else None
            )

        return sampled_normals

    def get_roll_align_vector(self, head, tail, normal):
        axis = tail - head
        if axis.length <= 1e-6:
            return None

        axis.normalize()

        candidates = []
        if normal is not None and normal.length > 1e-6:
            candidates.append(normal)
        candidates.extend((
            Vector((0.0, 0.0, 1.0)),
            Vector((1.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
        ))

        for candidate in candidates:
            projected = candidate - axis * axis.dot(candidate)
            if projected.length > 1e-6:
                return projected.normalized()

        return None

    def get_edge_flows(self, context):
        import bmesh
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)

        # 必须刷新，否则索引和选择状态可能不对
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        # 1. 获取当前所有选中的边
        selected_edges = [e for e in bm.edges if e.select]
        if not selected_edges:
            return None

        unvisited = set(selected_edges)
        world = obj.matrix_world
        normal_matrix = world.to_3x3().inverted().transposed()
        all_chains = []

        # 2. 提取选择历史中的边，作为排序种子
        # history 记录了用户点击的先后顺序
        seeds_from_history = []
        for elem in bm.select_history:
            if isinstance(elem, bmesh.types.BMEdge) and elem.select:
                if elem in unvisited:
                    seeds_from_history.append(elem)

        # 3. 构建完整的种子队列：历史种子 + 剩余选中的边
        seeds_queue = seeds_from_history + \
            [e for e in selected_edges if e not in set(seeds_from_history)]

        # 4. 开始按种子顺序遍历连通分支
        for start_edge in seeds_queue:
            if start_edge not in unvisited:
                continue

            # --- 寻找当前连通分支 (BFS) ---
            stack = [start_edge]
            component = {start_edge}
            unvisited.remove(start_edge)

            while stack:
                e = stack.pop()
                for v in e.verts:
                    for linked in v.link_edges:
                        if linked.select and linked in unvisited:
                            unvisited.remove(linked)
                            component.add(linked)
                            stack.append(linked)

            # --- 确定链条的逻辑顺序 ---
            # 计算分支内每个顶点的度
            vert_count = {}
            for e in component:
                for v in e.verts:
                    vert_count[v] = vert_count.get(v, 0) + 1

            # 找到端点（度为1的点）
            start_verts = [v for v, c in vert_count.items() if c == 1]

            is_closed = False
            if not start_verts:
                # 如果没有端点，说明是闭合环
                current_vert = start_edge.verts[0]
                is_closed = True
            else:
                # 如果是开链，选择离“种子边”最近的那个端点作为起点
                # 这样可以保证骨骼链的方向更符合用户点击时的直觉
                v1, v2 = start_verts[0], start_verts[-1]
                mid_seed = (start_edge.verts[0].co +
                            start_edge.verts[1].co) / 2
                if (v1.co - mid_seed).length <= (v2.co - mid_seed).length:
                    current_vert = v1
                else:
                    current_vert = v2

            # --- 按照拓扑顺序排列顶点 ---
            ordered_verts = [current_vert]
            ordered_edge_normals = []
            visited_edges_in_comp = set()

            while True:
                next_edge = None
                for e in current_vert.link_edges:
                    if e in component and e not in visited_edges_in_comp:
                        next_edge = e
                        break

                if not next_edge:
                    break

                visited_edges_in_comp.add(next_edge)
                ordered_edge_normals.append(
                    self.get_edge_world_normal(normal_matrix, next_edge)
                )
                # 移动到下一个顶点
                v_other = next_edge.other_vert(current_vert)
                current_vert = v_other
                ordered_verts.append(current_vert)

            # 转换为世界坐标
            chain_points = [world @ v.co.copy() for v in ordered_verts]

            if len(chain_points) > 1:
                all_chains.append({
                    "points": chain_points,
                    "edge_normals": ordered_edge_normals,
                    "is_closed": is_closed,
                })

        return all_chains

    def resample_chain(self, pts, edge_normals=None):

        if len(pts) < 2:
            return None

        lengths = []
        total = 0.0

        for i in range(len(pts) - 1):
            l = (pts[i + 1] - pts[i]).length
            lengths.append(l)
            total += l

        if total <= 1e-6:
            return None

        step = total / self.num_segments

        result = [pts[0]]
        accumulated = 0.0
        index = 0

        for i in range(1, self.num_segments):
            target = i * step

            while index < len(lengths) - 1 and accumulated + lengths[index] < target:
                accumulated += lengths[index]
                index += 1

            remain = target - accumulated
            direction = (pts[index + 1] - pts[index]).normalized()
            result.append(pts[index] + direction * remain)

        result.append(pts[-1])
        sampled_normals = self.build_sampled_segment_normals(
            lengths, edge_normals, total
        )
        return result, sampled_normals

    def apply_direction(self, chain, segment_normals=None):

        points = list(chain)
        normals = list(segment_normals) if segment_normals is not None else None

        if self.direction_mode == 'FORWARD':
            return (points, normals) if normals is not None else points

        if self.direction_mode == 'REVERSE':
            points.reverse()
            if normals is not None:
                normals.reverse()
            return (points, normals) if normals is not None else points

        if self.direction_mode == 'CURSOR':

            cursor = bpy.context.scene.cursor.location

            start = points[0]
            end = points[-1]

            d_start = (start - cursor).length
            d_end = (end - cursor).length

            if d_start > d_end:
                points.reverse()
                if normals is not None:
                    normals.reverse()

            return (points, normals) if normals is not None else points

        if self.direction_mode == 'CURSORMINUS':

            cursor = bpy.context.scene.cursor.location

            start = points[0]
            end = points[-1]

            d_start = (start - cursor).length
            d_end = (end - cursor).length

            if d_start < d_end:
                points.reverse()
                if normals is not None:
                    normals.reverse()

            return (points, normals) if normals is not None else points

        return (points, normals) if normals is not None else points

    def update_preview(self, context):

        self.preview_points = []

        for chain_data in self.base_chains:
            sampled = self.resample_chain(
                chain_data["points"],
                chain_data["edge_normals"],
            )
            if sampled:
                sampled_points, sampled_normals = sampled
                self.preview_points.append({
                    "points": sampled_points,
                    "segment_normals": sampled_normals,
                    "is_closed": chain_data["is_closed"],
                })

        context.area.tag_redraw()

    def draw_preview(self):

        if not self.preview_points:
            return

        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(4.0)

        rv3d = bpy.context.region_data
        if not rv3d:
            return

        view_dir = rv3d.view_rotation @ Vector((0, 0, -1))

        for preview_data in self.preview_points:

            points, segment_normals = self.apply_direction(
                preview_data["points"],
                preview_data["segment_normals"],
            )
            total = len(points) - 1
            if total <= 0:
                continue

            # ----- 线 -----
            coords = []
            colors = []

            for i in range(total):
                p1 = points[i]
                p2 = points[i + 1]

                t1 = i / total
                t2 = (i + 1) / total

                col1 = (t1, 1 - t1, 0.2, 1)
                col2 = (t2, 1 - t2, 0.2, 1)

                coords.extend([p1, p2])
                colors.extend([col1, col2])

            batch = batch_for_shader(shader, 'LINES', {
                "pos": coords,
                "color": colors,
            })

            shader.bind()
            batch.draw(shader)

            # ----- 箭头 -----
            arrow_coords = []
            arrow_colors = []

            for i in range(total):

                head = points[i]
                tail = points[i + 1]

                direction = (tail - head).normalized()
                length = (tail - head).length

                arrow_size = length * 0.25
                base = tail - direction * arrow_size

                side = direction.cross(view_dir)

                if side.length < 0.0001:
                    side = Vector((1, 0, 0))

                side.normalize()
                side *= arrow_size * 0.5

                left = base + side
                right = base - side

                t = (i + 1) / total
                col = (t, 1 - t, 0.2, 1)

                arrow_coords.extend([left, tail, right])
                arrow_colors.extend([col, col, col])

            arrow_batch = batch_for_shader(shader, 'TRIS', {
                "pos": arrow_coords,
                "color": arrow_colors,
            })

            arrow_batch.draw(shader)

            if self.align_roll_to_normal:
                z_axis_coords = []
                z_axis_colors = []

                for i in range(total):
                    head = points[i]
                    tail = points[i + 1]
                    segment_normal = segment_normals[i] if segment_normals else None
                    z_axis = self.get_roll_align_vector(head, tail, segment_normal)

                    if z_axis is None:
                        continue

                    mid = (head + tail) * 0.5
                    z_axis_length = (tail - head).length * 0.2
                    z_axis_end = mid + z_axis * z_axis_length
                    z_col = (0.2, 0.55, 1.0, 1.0)

                    z_axis_coords.extend([mid, z_axis_end])
                    z_axis_colors.extend([z_col, z_col])

                if z_axis_coords:
                    z_axis_batch = batch_for_shader(shader, 'LINES', {
                        "pos": z_axis_coords,
                        "color": z_axis_colors,
                    })
                    z_axis_batch.draw(shader)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    def draw_text(self):
        font_id = 0
        blf.size(font_id, 16)

        x = self.mouse_x + 20
        y = self.mouse_y + 20

        # ===== 开启阴影 =====
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.6)
        blf.shadow_offset(font_id, 1, -1)

        key_text = tr("滚轮:")
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y, 0)
        blf.draw(font_id, f"分段: {self.num_segments}")

        key_text = tr("F键:")
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 22, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 22, 0)
        blf.draw(font_id, f"方向模式: {self.direction_mode}")

        key_text = tr("R键:")
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 44, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 44, 0)
        blf.draw(font_id, f"联动重命名: {'开' if self.auto_rename else '关'}")

        key_text = tr("N键:")
        blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
        blf.position(font_id, x, y + 66, 0)
        blf.draw(font_id, key_text)
        key_width, _ = blf.dimensions(font_id, key_text)
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.position(font_id, x + key_width, y + 66, 0)
        blf.draw(
            font_id,
            f"扭转对齐法线: {'开' if self.align_roll_to_normal else '关'}"
        )

    def modal(self, context, event):

        if event.type == 'MOUSEMOVE':
            self.mouse_x = event.mouse_region_x
            self.mouse_y = event.mouse_region_y
            context.area.tag_redraw()

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self.finish(context)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.finish(context)
            self.create_bones(context)
            return {'FINISHED'}

        if event.type == 'WHEELUPMOUSE':
            self.num_segments += 1
            self.update_preview(context)

        if event.type == 'WHEELDOWNMOUSE':
            if self.num_segments > 1:
                self.num_segments -= 1
                self.update_preview(context)

        if event.type == 'F' and event.value == 'PRESS':
            modes = ['FORWARD', 'REVERSE', 'CURSOR', 'CURSORMINUS']
            i = modes.index(self.direction_mode)
            self.direction_mode = modes[(i + 1) % 4]
            context.area.tag_redraw()

        if event.type == 'R' and event.value == 'PRESS':
            self.auto_rename = not self.auto_rename
            context.area.tag_redraw()

        if event.type == 'N' and event.value == 'PRESS':
            self.align_roll_to_normal = not self.align_roll_to_normal
            context.area.tag_redraw()

        return {'RUNNING_MODAL'}

    def finish(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_3d, 'WINDOW')
        bpy.types.SpaceView3D.draw_handler_remove(self._handle_text, 'WINDOW')
        context.area.tag_redraw()

    def create_bones(self, context):
        bpy.ops.object.mode_set(mode='OBJECT')

        arm_data = bpy.data.armatures.new("FlowArmature")
        arm_obj = bpy.data.objects.new("FlowArmature", arm_data)
        context.collection.objects.link(arm_obj)

        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        # 用于存储所有新生成的骨骼名，保持创建顺序
        new_bone_names = []

        for chain_index, preview_data in enumerate(self.preview_points):
            points, segment_normals = self.apply_direction(
                preview_data["points"],
                preview_data["segment_normals"],
            )
            previous = None

            for i in range(len(points) - 1):
                bone_name = f"Flow_{chain_index}_{i}"
                bone = arm_data.edit_bones.new(bone_name)
                bone.head = points[i]
                bone.tail = points[i + 1]

                if self.align_roll_to_normal:
                    align_vector = self.get_roll_align_vector(
                        bone.head,
                        bone.tail,
                        segment_normals[i] if segment_normals else None,
                    )
                    if align_vector is not None:
                        bone.align_roll(align_vector)

                if previous:
                    bone.parent = previous
                    bone.use_connect = True

                previous = bone
                new_bone_names.append(bone.name)  # 记录顺序

        if self.auto_rename:
            # TODO:由于未知原因，5.1版本无法使用autorename功能
            arm_obj.data.show_names = True # TODO:由于未知原因，5.1-中show_names无法在模态中修改
            bpy.ops.armature.select_all(action='DESELECT')
            # 按照创建顺序（权重）选中骨骼
            for b_name in new_bone_names:
                eb = arm_data.edit_bones.get(b_name)
                if eb:
                    eb.select = True
            arm_data.edit_bones.active = arm_data.edit_bones[new_bone_names[0]]
            bpy.ops.ho.rename_rulerenameboneselected()
            bpy.ops.object.mode_set(mode='OBJECT')
        else:
            bpy.ops.object.mode_set(mode='OBJECT')

    def invoke(self, context, event):

        self.base_chains = self.get_edge_flows(context)

        if not self.base_chains:
            self.report({'WARNING'}, tr("请选择连续边"))
            return {'CANCELLED'}

        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y

        self.update_preview(context)

        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview, (), 'WINDOW', 'POST_VIEW'
        )

        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_text, (), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


def get_first_image_from_material(obj):
    if not obj.data.materials:
        return None
    mat = obj.data.materials[0]
    if not mat or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image:
            return n.image
    return None


def longest_edge_world(obj, face):
    mw = obj.matrix_world
    verts = obj.data.vertices

    max_len = 0.0
    v_idx = face.vertices
    n = len(v_idx)

    for i in range(n):
        v0 = mw @ verts[v_idx[i]].co
        v1 = mw @ verts[v_idx[(i + 1) % n]].co
        l = (v1 - v0).length
        if l > max_len:
            max_len = l

    return max_len


class OP_ModalFillMeshHole(Operator):
    bl_idname = "ho.modal_fill_mesh_hole"
    bl_label = "点击封闭孔洞"
    bl_description = "鼠标悬停高亮闭合边界孔洞，左键用三角面封闭"
    
    @classmethod
    def description(cls, context, properties):
        return tr("鼠标悬停高亮闭合边界孔洞，左键用三角面封闭")
    bl_options = {'REGISTER', 'UNDO'}

    hit_radius: IntProperty(
        name="捕捉半径",
        description="鼠标到孔洞边界的最大屏幕距离",
        default=30,
        min=4,
        max=120,
    )  # type: ignore
    fill_mode: EnumProperty(
        name="封孔模式",
        description="左键封闭孔洞时使用的算法",
        items=[
            ('SMOOTH_PATCH', "Smooth Patch", "三角剖分、补片细分、内部点平滑"),
            ('QUAD_PATCH', "Quad Grid", "自动四角参数化并生成规整四边网格"),
            ('TRIANGLE', "Triangle Fill", "Beauty 三角剖分，稳定但布线较稀"),
        ],
        default='SMOOTH_PATCH',
    )  # type: ignore
    patch_edge_factor: FloatProperty(
        name="边长倍率",
        description="目标补片边长 = 每个孔洞周围一圈网格边长的稳健中位数 * 该倍率；数值越小越密",
        default=0.85,
        min=0.35,
        max=4.0,
    )  # type: ignore
    patch_refine_iterations: IntProperty(
        name="细分轮数",
        description="补片内部过长边的最大细分轮数",
        default=4,
        min=0,
        max=8,
    )  # type: ignore
    patch_smooth_iterations: IntProperty(
        name="平滑轮数",
        description="只平滑新增内部点，边界点保持不动",
        default=10,
        min=0,
        max=40,
    )  # type: ignore
    patch_surface_blend: FloatProperty(
        name="曲面吸附",
        description="内部点向孔边外侧拟合曲面的吸附强度",
        default=0.82,
        min=0.0,
        max=1.0,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return (
            context.area is not None and
            context.area.type == 'VIEW_3D' and
            context.object is not None and
            context.object.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def _edit_bmesh(self, context):
        obj = context.edit_object or context.object
        if obj is None or obj.type != 'MESH':
            return None, None
        return obj, bmesh.from_edit_mesh(obj.data)

    def _tag_redraw(self, context):
        if context.area:
            context.area.tag_redraw()

    def _iter_boundary_components(self, bm):
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()

        boundary_edges = [
            e for e in bm.edges
            if e.is_valid and e.is_boundary and not e.hide
        ]
        vert_edges = defaultdict(list)
        for edge in boundary_edges:
            vert_edges[edge.verts[0]].append(edge)
            vert_edges[edge.verts[1]].append(edge)

        visited = set()
        for start_edge in boundary_edges:
            if start_edge in visited:
                continue

            stack = [start_edge]
            component_edges = set()
            component_verts = set()

            while stack:
                edge = stack.pop()
                if edge in component_edges:
                    continue
                component_edges.add(edge)
                visited.add(edge)

                for vert in edge.verts:
                    component_verts.add(vert)
                    for next_edge in vert_edges[vert]:
                        if next_edge not in component_edges:
                            stack.append(next_edge)

            yield list(component_edges), component_verts, vert_edges

    def _order_closed_boundary(self, component_edges, vert_edges):
        if len(component_edges) < 3:
            return None, None

        component_edge_set = set(component_edges)
        component_verts = set()
        for edge in component_edges:
            component_verts.update(edge.verts)

        if len(component_edges) != len(component_verts):
            return None, None

        for vert in component_verts:
            degree = sum(
                1 for edge in vert_edges[vert]
                if edge in component_edge_set
            )
            if degree != 2:
                return None, None

        start_edge = component_edges[0]
        start_vert = start_edge.verts[0]
        current_vert = start_edge.verts[1]
        previous_edge = start_edge

        ordered_edges = [start_edge]
        ordered_verts = [start_vert, current_vert]

        while current_vert != start_vert:
            next_edges = [
                edge for edge in vert_edges[current_vert]
                if edge in component_edge_set and edge != previous_edge
            ]
            if len(next_edges) != 1:
                return None, None

            edge = next_edges[0]
            next_vert = edge.other_vert(current_vert)
            ordered_edges.append(edge)

            if next_vert == start_vert:
                current_vert = next_vert
                break
            if next_vert in ordered_verts:
                return None, None

            ordered_verts.append(next_vert)
            previous_edge = edge
            current_vert = next_vert

            if len(ordered_edges) > len(component_edges):
                return None, None

        if len(ordered_edges) != len(component_edges):
            return None, None

        return ordered_verts, ordered_edges

    def _loop_normal(self, verts, edges):
        normal = Vector((0.0, 0.0, 0.0))
        for index, vert in enumerate(verts):
            co_a = vert.co
            co_b = verts[(index + 1) % len(verts)].co
            normal.x += (co_a.y - co_b.y) * (co_a.z + co_b.z)
            normal.y += (co_a.z - co_b.z) * (co_a.x + co_b.x)
            normal.z += (co_a.x - co_b.x) * (co_a.y + co_b.y)

        adjacent_normal = Vector((0.0, 0.0, 0.0))
        for edge in edges:
            for face in edge.link_faces:
                adjacent_normal += face.normal

        if adjacent_normal.length > 1e-8:
            adjacent_normal.normalize()
            if normal.length > 1e-8:
                normal.normalize()
                if normal.dot(adjacent_normal) < 0.0:
                    normal.negate()
            else:
                normal = adjacent_normal
        elif normal.length > 1e-8:
            normal.normalize()

        return normal

    def _rebuild_holes(self, context):
        obj, bm = self._edit_bmesh(context)
        self.obj = obj
        self.holes = []
        self.active_hole_index = -1

        if bm is None:
            self.message = "没有可编辑网格"
            return

        for component_edges, _component_verts, vert_edges in self._iter_boundary_components(bm):
            verts, edges = self._order_closed_boundary(component_edges, vert_edges)
            if not verts:
                continue

            normal = self._loop_normal(verts, edges)
            world_points = [obj.matrix_world @ vert.co.copy() for vert in verts]
            center_world = Vector((0.0, 0.0, 0.0))
            for point in world_points:
                center_world += point
            center_world /= len(world_points)

            self.holes.append({
                "edge_indices": [edge.index for edge in edges],
                "vert_indices": [vert.index for vert in verts],
                "vert_count": len(verts),
                "world_points": world_points,
                "center_world": center_world,
                "normal": normal.copy(),
                "signature": (
                    len(verts),
                    round(center_world.x, 5),
                    round(center_world.y, 5),
                    round(center_world.z, 5),
                ),
            })

        self.message = f"找到 {len(self.holes)} 个闭合孔洞"

    def _project_hole(self, context, hole):
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return None

        screen_points = []
        for point in hole["world_points"]:
            pos = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
            if pos is None:
                return None
            screen_points.append(pos)

        return screen_points

    def _point_segment_distance(self, point, start, end):
        segment = end - start
        length_squared = segment.length_squared
        if length_squared <= 1e-8:
            return (point - start).length

        factor = (point - start).dot(segment) / length_squared
        factor = max(0.0, min(1.0, factor))
        closest = start + segment * factor
        return (point - closest).length

    def _point_inside_polygon(self, point, polygon):
        inside = False
        x = point.x
        y = point.y
        count = len(polygon)

        for index in range(count):
            a = polygon[index]
            b = polygon[(index + 1) % count]
            if (a.y > y) == (b.y > y):
                continue
            x_intersect = (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x
            if x < x_intersect:
                inside = not inside

        return inside

    def _hole_screen_distance(self, mouse_point, screen_points):
        if len(screen_points) < 3:
            return None

        if self._point_inside_polygon(mouse_point, screen_points):
            return 0.0

        best_distance = None
        for index, start in enumerate(screen_points):
            end = screen_points[(index + 1) % len(screen_points)]
            distance = self._point_segment_distance(mouse_point, start, end)
            if best_distance is None or distance < best_distance:
                best_distance = distance

        return best_distance

    def _update_hover(self, context, event):
        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y
        self._update_hover_at(context)

    def _update_hover_at(self, context):
        mouse_point = Vector((self.mouse_x, self.mouse_y))

        best_index = -1
        best_distance = None
        for index, hole in enumerate(self.holes):
            screen_points = self._project_hole(context, hole)
            if screen_points is None:
                continue

            distance = self._hole_screen_distance(mouse_point, screen_points)
            if distance is None or distance > self.hit_radius:
                continue
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index

        self.active_hole_index = best_index

    def _active_hole(self):
        if self.active_hole_index < 0:
            return None
        if self.active_hole_index >= len(self.holes):
            return None
        return self.holes[self.active_hole_index]

    def _collect_hole_edges(self, bm, hole):
        bm.edges.ensure_lookup_table()
        edges = []
        for edge_index in hole["edge_indices"]:
            if edge_index < 0 or edge_index >= len(bm.edges):
                return None, "孔洞数据已变化，请移动鼠标刷新"
            edge = bm.edges[edge_index]
            if not edge.is_valid or not edge.is_boundary:
                return None, "孔洞已经被封闭"
            edges.append(edge)
        return edges, ""

    def _median(self, values):
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) * 0.5

    def _trimmed_median(self, values):
        ordered = sorted(
            value for value in values
            if value > 1e-8 and math.isfinite(value)
        )
        if not ordered:
            return 0.0

        if len(ordered) >= 8:
            trim_count = max(1, int(len(ordered) * 0.15))
            if trim_count * 2 < len(ordered):
                ordered = ordered[trim_count:-trim_count]

        return self._median(ordered)

    def _hole_neighbor_edge_length(self, boundary_edges):
        boundary_edge_set = set(boundary_edges)
        ring_edges = set()
        boundary_lengths = []
        boundary_verts = set()

        def add_ring_edge(edge):
            if (
                edge.is_valid and
                edge not in boundary_edge_set and
                not edge.hide and
                not edge.is_boundary and
                not edge.is_wire
            ):
                ring_edges.add(edge)

        for edge in boundary_edges:
            if not edge.is_valid:
                continue
            boundary_verts.update(edge.verts)
            boundary_lengths.append(edge.calc_length())
            for face in edge.link_faces:
                if not face.is_valid:
                    continue
                for face_edge in face.edges:
                    add_ring_edge(face_edge)

        for vert in boundary_verts:
            if not vert.is_valid:
                continue
            for edge in vert.link_edges:
                add_ring_edge(edge)
            for face in vert.link_faces:
                if not face.is_valid:
                    continue
                for edge in face.edges:
                    add_ring_edge(edge)

        ring_length = self._trimmed_median(
            edge.calc_length()
            for edge in ring_edges
        )
        boundary_length = self._trimmed_median(boundary_lengths)

        if ring_length > 1e-8 and boundary_length > 1e-8:
            return min(ring_length, boundary_length * 1.25)
        if ring_length > 1e-8:
            return ring_length
        return boundary_length

    def _vertex_surface_normal(self, vert):
        normal = Vector((0.0, 0.0, 0.0))
        for face in vert.link_faces:
            if not face.is_valid:
                continue
            weight = 1.0
            try:
                weight = max(face.calc_area(), 1e-8)
            except Exception:
                pass
            normal += face.normal * weight
        if normal.length <= 1e-8:
            return None
        return normal.normalized()

    def _boundary_surface_samples(self, boundary_verts):
        samples = []
        visited = set()
        frontier = {
            vert for vert in boundary_verts
            if vert.is_valid
        }

        for ring_index in range(3):
            next_frontier = set()
            for vert in frontier:
                if vert in visited or not vert.is_valid:
                    continue
                visited.add(vert)

                normal = self._vertex_surface_normal(vert)
                if normal is not None:
                    samples.append({
                        "co": vert.co.copy(),
                        "normal": normal,
                        "ring": ring_index,
                    })

                if ring_index >= 2:
                    continue

                for edge in vert.link_edges:
                    if not edge.is_valid:
                        continue
                    other = edge.other_vert(vert)
                    if other.is_valid and other not in visited:
                        next_frontier.add(other)

                for face in vert.link_faces:
                    if not face.is_valid:
                        continue
                    for other in face.verts:
                        if other.is_valid and other not in visited:
                            next_frontier.add(other)

            frontier = next_frontier
            if not frontier:
                break

        return self._surface_projector_from_samples(samples)

    def _surface_projector_from_samples(self, samples):
        tangent_samples = [
            (sample["co"], sample["normal"])
            for sample in samples
            if sample["normal"] is not None
        ]
        if not tangent_samples:
            return None

        projector = {"samples": tangent_samples}
        if len(samples) < 6:
            return projector

        total_weight = 0.0
        center = Vector((0.0, 0.0, 0.0))
        normal = Vector((0.0, 0.0, 0.0))
        for sample in samples:
            weight = 1.0 / (1.0 + sample["ring"] * 0.35)
            center += sample["co"] * weight
            normal += sample["normal"] * weight
            total_weight += weight

        if total_weight <= 1e-8 or normal.length <= 1e-8:
            return projector

        center /= total_weight
        n_axis = normal.normalized()
        u_axis = None
        for sample in samples:
            tangent = sample["co"] - center
            tangent -= n_axis * tangent.dot(n_axis)
            if tangent.length > 1e-8:
                u_axis = tangent.normalized()
                break

        if u_axis is None:
            helper = Vector((1.0, 0.0, 0.0))
            if abs(helper.dot(n_axis)) > 0.9:
                helper = Vector((0.0, 1.0, 0.0))
            u_axis = helper.cross(n_axis).normalized()

        v_axis = n_axis.cross(u_axis)
        if v_axis.length <= 1e-8:
            return projector
        v_axis.normalize()

        local_points = []
        radii = []
        z_values = []
        for sample in samples:
            rel = sample["co"] - center
            x = rel.dot(u_axis)
            y = rel.dot(v_axis)
            z = rel.dot(n_axis)
            local_points.append((x, y, z, sample["ring"]))
            radii.append(math.sqrt(x * x + y * y))
            z_values.append(z)

        scale = self._trimmed_median(radii)
        if scale <= 1e-8:
            scale = max(radii) if radii else 0.0
        if scale <= 1e-8:
            return projector

        rows = []
        rhs = []
        weights = []
        for x, y, z, ring_index in local_points:
            xs = x / scale
            ys = y / scale
            rows.append([xs * xs, ys * ys, xs * ys, xs, ys, 1.0])
            rhs.append(z / scale)
            weights.append(1.0 / (1.0 + ring_index * 0.35))

        try:
            matrix = np.asarray(rows, dtype=float)
            target = np.asarray(rhs, dtype=float)
            weight_array = np.sqrt(np.asarray(weights, dtype=float))
            weighted_matrix = matrix * weight_array[:, None]
            weighted_target = target * weight_array
            coeffs, _residuals, rank, singular_values = np.linalg.lstsq(
                weighted_matrix,
                weighted_target,
                rcond=None,
            )
        except Exception:
            return projector

        if rank < 3 or not np.all(np.isfinite(coeffs)):
            return projector
        if singular_values.size and singular_values[-1] > 1e-10:
            condition = singular_values[0] / singular_values[-1]
            if condition > 1e8:
                return projector

        z_min = min(z_values)
        z_max = max(z_values)
        projector.update({
            "center": center,
            "u_axis": u_axis,
            "v_axis": v_axis,
            "n_axis": n_axis,
            "scale": scale,
            "coeffs": coeffs,
            "z_min": z_min,
            "z_max": z_max,
        })
        return projector

    def _project_to_boundary_surface(self, co, projector):
        if not projector:
            return co

        coeffs = projector.get("coeffs") if isinstance(projector, dict) else None
        if coeffs is not None:
            center = projector["center"]
            u_axis = projector["u_axis"]
            v_axis = projector["v_axis"]
            n_axis = projector["n_axis"]
            scale = projector["scale"]
            rel = co - center
            x = rel.dot(u_axis)
            y = rel.dot(v_axis)
            xs = x / scale
            ys = y / scale
            target_z = float(
                coeffs[0] * xs * xs +
                coeffs[1] * ys * ys +
                coeffs[2] * xs * ys +
                coeffs[3] * xs +
                coeffs[4] * ys +
                coeffs[5]
            ) * scale
            z_min = projector["z_min"]
            z_max = projector["z_max"]
            z_margin = max((z_max - z_min) * 1.5, scale * 0.12)
            target_z = max(z_min - z_margin, min(z_max + z_margin, target_z))
            return center + u_axis * x + v_axis * y + n_axis * target_z

        samples = projector.get("samples", []) if isinstance(projector, dict) else projector
        if not samples:
            return co

        total_weight = 0.0
        projected = Vector((0.0, 0.0, 0.0))
        for sample_co, sample_normal in samples:
            delta = co - sample_co
            dist_sq = max(delta.length_squared, 1e-8)
            weight = 1.0 / dist_sq
            point_on_tangent = co - sample_normal * delta.dot(sample_normal)
            projected += point_on_tangent * weight
            total_weight += weight

        if total_weight <= 1e-8:
            return co

        return projected / total_weight

    def _tag_patch_faces(self, bm, patch_faces):
        for face in bm.faces:
            face.tag = False
        for face in patch_faces:
            if face.is_valid:
                face.tag = True

    def _tagged_patch_faces(self, bm):
        return {
            face for face in bm.faces
            if face.is_valid and face.tag
        }

    def _collect_patch_faces_from_boundary(self, boundary_edges, excluded_faces):
        boundary_edge_set = set(boundary_edges)
        patch_faces = set()
        stack = []
        for edge in boundary_edges:
            if not edge.is_valid:
                continue
            for face in edge.link_faces:
                if face.is_valid and face not in excluded_faces:
                    stack.append(face)

        while stack:
            face = stack.pop()
            if (
                not face.is_valid or
                face in patch_faces or
                face in excluded_faces
            ):
                continue
            patch_faces.add(face)
            for edge in face.edges:
                if not edge.is_valid or edge in boundary_edge_set:
                    continue
                for linked_face in edge.link_faces:
                    if (
                        linked_face.is_valid and
                        linked_face not in patch_faces and
                        linked_face not in excluded_faces
                    ):
                        stack.append(linked_face)

        return patch_faces

    def _patch_boundary_verts_from_faces(self, patch_faces):
        patch_face_set = set(patch_faces)
        verts = set()
        for face in patch_faces:
            if not face.is_valid:
                continue
            for edge in face.edges:
                linked_patch_count = sum(
                    1 for linked_face in edge.link_faces
                    if linked_face.is_valid and linked_face in patch_face_set
                )
                if linked_patch_count < 2:
                    verts.update(edge.verts)
        return verts

    def _clear_patch_tags(self, bm):
        for face in bm.faces:
            face.tag = False

    def _relax_patch_verts(self, patch_faces, boundary_verts, surface_samples):
        if not patch_faces:
            return

        patch_verts = set()
        for face in patch_faces:
            if face.is_valid:
                patch_verts.update(face.verts)

        movable = [
            vert for vert in patch_verts
            if vert.is_valid and vert not in boundary_verts
        ]
        if not movable:
            return

        for _iteration in range(self.patch_smooth_iterations):
            new_positions = {}
            for vert in movable:
                neighbors = [
                    edge.other_vert(vert)
                    for edge in vert.link_edges
                    if edge.is_valid and edge.other_vert(vert).is_valid
                ]
                if not neighbors:
                    continue

                avg = Vector((0.0, 0.0, 0.0))
                for neighbor in neighbors:
                    avg += neighbor.co
                avg /= len(neighbors)

                new_co = vert.co.lerp(avg, 0.45)
                if surface_samples:
                    projected = self._project_to_boundary_surface(
                        new_co,
                        surface_samples,
                    )
                    new_co = new_co.lerp(projected, self.patch_surface_blend)

                new_positions[vert] = new_co

            for vert, co in new_positions.items():
                vert.co = co

        if surface_samples:
            final_blend = max(0.0, min(1.0, self.patch_surface_blend))
            if final_blend > 0.0:
                for vert in movable:
                    projected = self._project_to_boundary_surface(
                        vert.co,
                        surface_samples,
                    )
                    vert.co = vert.co.lerp(projected, final_blend)

    def _collect_hole_verts(self, bm, hole):
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        vert_indices = hole.get("vert_indices")
        if not vert_indices:
            return None, "孔洞缺少有序顶点数据，请刷新缓存"

        verts = []
        for vert_index in vert_indices:
            if vert_index < 0 or vert_index >= len(bm.verts):
                return None, "孔洞数据已变化，请刷新缓存"
            vert = bm.verts[vert_index]
            if not vert.is_valid:
                return None, "孔洞顶点已变化，请刷新缓存"
            verts.append(vert)

        return verts, ""

    def _hole_tangent_basis(
        self,
        boundary_verts,
        boundary_edges,
        normal,
        use_neighbor_edges=True,
    ):
        if normal.length > 1e-8:
            n_axis = normal.normalized()
        else:
            n_axis = self._loop_normal(boundary_verts, boundary_edges)
            if n_axis.length <= 1e-8:
                return None, None

        directions = []
        for edge in boundary_edges:
            if not edge.is_valid:
                continue
            direction = edge.verts[1].co - edge.verts[0].co
            projected = direction - n_axis * direction.dot(n_axis)
            if projected.length > 1e-8:
                directions.append(projected.normalized())

        if use_neighbor_edges:
            boundary_vert_set = set(boundary_verts)
            for vert in boundary_verts:
                for edge in vert.link_edges:
                    if not edge.is_valid or edge.is_wire:
                        continue
                    other = edge.other_vert(vert)
                    if other in boundary_vert_set:
                        continue
                    direction = other.co - vert.co
                    projected = direction - n_axis * direction.dot(n_axis)
                    if projected.length > 1e-8:
                        directions.append(projected.normalized())

        if not directions:
            return None, None

        best_axis = None
        best_score = None
        for candidate in directions:
            u_axis = candidate.normalized()
            v_axis = n_axis.cross(u_axis)
            if v_axis.length <= 1e-8:
                continue
            v_axis.normalize()
            score = 0.0
            for direction in directions:
                score += max(
                    abs(direction.dot(u_axis)),
                    abs(direction.dot(v_axis)),
                ) ** 4
            if best_score is None or score > best_score:
                best_score = score
                best_axis = u_axis

        if best_axis is None:
            return None, None

        v_axis = n_axis.cross(best_axis)
        if v_axis.length <= 1e-8:
            return None, None
        v_axis.normalize()
        return best_axis, v_axis

    def _cluster_axis_values(self, values, tolerance):
        ordered = sorted(values)
        clusters = []
        for value in ordered:
            if not clusters or abs(value - clusters[-1][-1]) > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        return [sum(cluster) / len(cluster) for cluster in clusters]

    def _nearest_axis_index(self, value, axis_values):
        best_index = 0
        best_distance = None
        for index, axis_value in enumerate(axis_values):
            distance = abs(value - axis_value)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
        return best_index, best_distance

    def _point_in_poly_2d(self, point, polygon):
        inside = False
        x, y = point
        count = len(polygon)
        for index in range(count):
            ax, ay = polygon[index]
            bx, by = polygon[(index + 1) % count]
            if (ay > y) == (by > y):
                continue
            denom = by - ay
            if abs(denom) <= 1e-12:
                continue
            x_intersect = (bx - ax) * (y - ay) / denom + ax
            if x < x_intersect:
                inside = not inside
        return inside

    def _key_on_boundary(self, key, boundary_keys):
        ui, vi = key
        count = len(boundary_keys)
        for index, start in enumerate(boundary_keys):
            end = boundary_keys[(index + 1) % count]
            if start[0] == end[0] == ui:
                if min(start[1], end[1]) <= vi <= max(start[1], end[1]):
                    return True
            if start[1] == end[1] == vi:
                if min(start[0], end[0]) <= ui <= max(start[0], end[0]):
                    return True
        return False

    def _merge_boundary_grid_keys_to_nearest_verts(
        self,
        boundary_edges,
        boundary_keys,
        boundary_key_to_vert,
        u_values,
        v_values,
    ):
        merged_count = 0
        count = len(boundary_keys)
        for index, start in enumerate(boundary_keys):
            end = boundary_keys[(index + 1) % count]
            edge = boundary_edges[index]
            if not edge.is_valid:
                return False, 0, "孔边已变化，无法自动补分段"

            du = end[0] - start[0]
            dv = end[1] - start[1]
            if du and dv:
                continue

            steps = abs(du if du else dv)
            if steps <= 1:
                continue

            missing = []
            for step in range(1, steps):
                if du:
                    key = (start[0] + (1 if du > 0 else -1) * step, start[1])
                else:
                    key = (start[0], start[1] + (1 if dv > 0 else -1) * step)
                if key not in boundary_key_to_vert:
                    missing.append((step, key))

            if not missing:
                continue

            start_vert = boundary_key_to_vert.get(start)
            end_vert = boundary_key_to_vert.get(end)
            if start_vert is None or end_vert is None:
                return False, 0, "孔边端点缺失，无法自动补分段"

            start_2d = Vector((u_values[start[0]], v_values[start[1]], 0.0))
            end_2d = Vector((u_values[end[0]], v_values[end[1]], 0.0))
            for _step, key in missing:
                key_2d = Vector((u_values[key[0]], v_values[key[1]], 0.0))
                start_distance = (key_2d - start_2d).length_squared
                end_distance = (key_2d - end_2d).length_squared
                boundary_key_to_vert[key] = (
                    start_vert
                    if start_distance <= end_distance
                    else end_vert
                )
                merged_count += 1

        return True, merged_count, ""

    def _collapsed_grid_face_verts(self, verts):
        collapsed = []
        for vert in verts:
            if collapsed and collapsed[-1] is vert:
                continue
            collapsed.append(vert)

        if len(collapsed) > 1 and collapsed[0] is collapsed[-1]:
            collapsed.pop()
        if len(collapsed) < 3:
            return None
        if len(set(collapsed)) != len(collapsed):
            return None
        return collapsed

    def _rollback_quad_grid_geometry(self, bm, faces, verts):
        valid_faces = [
            face for face in faces
            if face.is_valid
        ]
        if valid_faces:
            bmesh.ops.delete(bm, geom=valid_faces, context='FACES_ONLY')

        valid_verts = [
            vert for vert in verts
            if vert.is_valid
        ]
        if valid_verts:
            bmesh.ops.delete(bm, geom=valid_verts, context='VERTS')

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()

    def _fill_hole_direct_quad_bm(self, bm, hole, boundary_verts):
        if len(boundary_verts) != 4:
            return False, "Direct Quad 需要 4 个边界点"

        try:
            face = bm.faces.new(boundary_verts)
        except ValueError as exc:
            return False, f"Direct Quad 失败: {exc}"

        face.normal_update()
        if (
            hole["normal"].length > 1e-8 and
            face.normal.length > 1e-8 and
            face.normal.dot(hole["normal"]) < 0.0
        ):
            bmesh.ops.reverse_faces(bm, faces=[face])

        self._tag_patch_faces(bm, [face])
        return True, "Quad Grid 四边封口 1 面"

    def _fill_hole_quad_grid_bm(self, bm, hole, allow_boundary_merges=True):
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        boundary_edges, error = self._collect_hole_edges(bm, hole)
        if boundary_edges is None:
            return False, error
        boundary_verts, error = self._collect_hole_verts(bm, hole)
        if boundary_verts is None:
            return False, error
        if len(boundary_verts) < 4:
            return False, "Quad Grid 至少需要 4 个边界点"
        if len(boundary_verts) == 4:
            return self._fill_hole_direct_quad_bm(
                bm,
                hole,
                boundary_verts,
            )

        center = Vector((0.0, 0.0, 0.0))
        for vert in boundary_verts:
            center += vert.co
        center /= len(boundary_verts)

        u_axis, v_axis = self._hole_tangent_basis(
            boundary_verts,
            boundary_edges,
            hole["normal"],
            use_neighbor_edges=False,
        )
        if u_axis is None or v_axis is None:
            return False, "无法推断四边网格方向"

        coords = []
        for vert in boundary_verts:
            delta = vert.co - center
            coords.append((delta.dot(u_axis), delta.dot(v_axis)))

        boundary_edge_length = self._trimmed_median(
            edge.calc_length()
            for edge in boundary_edges
            if edge.is_valid
        )
        snap_tolerance = max(boundary_edge_length * 0.32, 1e-6)
        u_values = self._cluster_axis_values(
            [coord[0] for coord in coords],
            snap_tolerance,
        )
        v_values = self._cluster_axis_values(
            [coord[1] for coord in coords],
            snap_tolerance,
        )
        if len(u_values) < 2 or len(v_values) < 2:
            return False, "Quad Grid 网格轴数量不足"

        boundary_keys = []
        boundary_key_to_vert = {}
        for vert, coord in zip(boundary_verts, coords):
            ui, u_distance = self._nearest_axis_index(coord[0], u_values)
            vi, v_distance = self._nearest_axis_index(coord[1], v_values)
            if u_distance > snap_tolerance or v_distance > snap_tolerance:
                return False, "边界无法稳定吸附到四边网格"
            key = (ui, vi)
            if key in boundary_key_to_vert and boundary_key_to_vert[key] is not vert:
                return False, "四边网格边界点重叠"
            boundary_keys.append(key)
            boundary_key_to_vert[key] = vert

        for index, start in enumerate(boundary_keys):
            end = boundary_keys[(index + 1) % len(boundary_keys)]
            if start == end:
                return False, "四边网格边界有重叠点"
            if start[0] != end[0] and start[1] != end[1]:
                return False, "当前孔洞不是可分块四边网格边界"

        polygon = [
            (u_values[ui], v_values[vi])
            for ui, vi in boundary_keys
        ]
        cells = []
        for ui in range(len(u_values) - 1):
            for vi in range(len(v_values) - 1):
                center_2d = (
                    (u_values[ui] + u_values[ui + 1]) * 0.5,
                    (v_values[vi] + v_values[vi + 1]) * 0.5,
                )
                if self._point_in_poly_2d(center_2d, polygon):
                    cells.append((ui, vi))

        if not cells:
            return False, "Quad Grid 没有可填充网格单元"

        used_keys = set()
        for ui, vi in cells:
            used_keys.update((
                (ui, vi),
                (ui + 1, vi),
                (ui + 1, vi + 1),
                (ui, vi + 1),
            ))

        missing_boundary_keys = []
        for key in used_keys:
            if key in boundary_key_to_vert:
                continue
            if self._key_on_boundary(key, boundary_keys):
                missing_boundary_keys.append(key)

        surface_samples = self._boundary_surface_samples(set(boundary_verts))
        merged_boundary_count = 0
        if missing_boundary_keys:
            if not allow_boundary_merges:
                return False, "四边网格边界需要补分段"
            success, merged_boundary_count, message = (
                self._merge_boundary_grid_keys_to_nearest_verts(
                    boundary_edges,
                    boundary_keys,
                    boundary_key_to_vert,
                    u_values,
                    v_values,
                )
            )
            if not success:
                return False, message

        for key in used_keys:
            if key in boundary_key_to_vert:
                continue
            if self._key_on_boundary(key, boundary_keys):
                return False, "边界内部补分段失败"

        grid_verts = {}
        created_grid_verts = set()
        for key in sorted(used_keys):
            if key in boundary_key_to_vert:
                grid_verts[key] = boundary_key_to_vert[key]
                continue
            ui, vi = key
            co = center + u_axis * u_values[ui] + v_axis * v_values[vi]
            if surface_samples:
                co = self._project_to_boundary_surface(co, surface_samples)
            vert = bm.verts.new(co)
            grid_verts[key] = vert
            created_grid_verts.add(vert)

        bm.verts.ensure_lookup_table()
        created_faces = []
        for ui, vi in cells:
            verts = [
                grid_verts[(ui, vi)],
                grid_verts[(ui + 1, vi)],
                grid_verts[(ui + 1, vi + 1)],
                grid_verts[(ui, vi + 1)],
            ]
            verts = self._collapsed_grid_face_verts(verts)
            if not verts:
                continue
            try:
                face = bm.faces.new(verts)
                created_faces.append(face)
            except ValueError:
                continue

        if not created_faces:
            self._rollback_quad_grid_geometry(
                bm,
                created_faces,
                created_grid_verts,
            )
            return False, "Quad Grid 未生成四边面"

        open_boundary_edges = [
            edge for edge in boundary_edges
            if edge.is_valid and edge.is_boundary
        ]
        if open_boundary_edges:
            self._rollback_quad_grid_geometry(
                bm,
                created_faces,
                created_grid_verts,
            )
            return False, f"Quad Grid 边界未闭合 {len(open_boundary_edges)} 边"

        self._tag_patch_faces(bm, created_faces)

        if hole["normal"].length > 1e-8:
            fill_normal = Vector((0.0, 0.0, 0.0))
            for face in created_faces:
                face.normal_update()
                fill_normal += face.normal
            if fill_normal.length > 1e-8 and fill_normal.dot(hole["normal"]) < 0.0:
                bmesh.ops.reverse_faces(bm, faces=created_faces)

        self._relax_patch_verts(
            set(created_faces),
            set(boundary_verts),
            surface_samples,
        )

        quad_count = sum(1 for face in created_faces if len(face.verts) == 4)
        tri_count = sum(1 for face in created_faces if len(face.verts) == 3)
        if tri_count:
            return True, f"Quad Grid 四边 {quad_count} 面 / 边界三角 {tri_count} 面 / 融并 {merged_boundary_count} 点"
        if merged_boundary_count:
            return True, f"Quad Grid 四边 {quad_count} 面 / 融并 {merged_boundary_count} 点"
        return True, f"Quad Grid 四边填充 {quad_count} 面"

    def _fill_hole_patch_bm(self, bm, hole, quadrangulate=False):
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        original_faces = {
            face for face in bm.faces
            if face.is_valid
        }

        boundary_edges, error = self._collect_hole_edges(bm, hole)
        if boundary_edges is None:
            return False, error
        boundary_edge_set = set(boundary_edges)

        boundary_verts = set()
        for edge in boundary_edges:
            boundary_verts.update(edge.verts)

        target_edge_length = self._hole_neighbor_edge_length(boundary_edges)
        if target_edge_length <= 1e-8:
            target_edge_length = self._median([
                edge.calc_length()
                for edge in boundary_edges
                if edge.calc_length() > 1e-8
            ])
        if target_edge_length <= 1e-8:
            target_edge_length = 1.0
        target_edge_length *= self.patch_edge_factor

        surface_samples = self._boundary_surface_samples(boundary_verts)

        try:
            result = bmesh.ops.triangle_fill(
                bm,
                edges=boundary_edges,
                normal=hole["normal"],
                use_beauty=True,
                use_dissolve=False,
            )
        except Exception as exc:
            return False, f"Patch Fill 三角剖分失败: {exc}"

        new_faces = [
            item for item in result.get("geom", [])
            if isinstance(item, bmesh.types.BMFace)
        ]
        if not new_faces:
            return False, "Patch Fill 未生成面"
        patch_faces = set(new_faces)
        self._tag_patch_faces(bm, patch_faces)

        if hole["normal"].length > 1e-8:
            fill_normal = Vector((0.0, 0.0, 0.0))
            for face in new_faces:
                face.normal_update()
                fill_normal += face.normal
            if fill_normal.length > 1e-8 and fill_normal.dot(hole["normal"]) < 0.0:
                bmesh.ops.reverse_faces(bm, faces=new_faces)

        refined_edges = 0
        for _iteration in range(self.patch_refine_iterations):
            patch_faces = self._collect_patch_faces_from_boundary(
                boundary_edges,
                original_faces,
            )
            self._tag_patch_faces(bm, patch_faces)
            patch_edges = {
                edge for face in patch_faces if face.is_valid
                for edge in face.edges
                if edge.is_valid
            }
            long_edges = [
                edge for edge in patch_edges
                if edge.is_valid
                and edge not in boundary_edge_set
                and edge.calc_length() > target_edge_length * 1.35
            ]
            if not long_edges:
                break

            bmesh.ops.subdivide_edges(
                bm,
                edges=long_edges,
                cuts=1,
                smooth=0.0,
                use_smooth_even=True,
            )
            refined_edges += len(long_edges)

        patch_faces = self._collect_patch_faces_from_boundary(
            boundary_edges,
            original_faces,
        )
        self._tag_patch_faces(bm, patch_faces)
        if patch_faces:
            bmesh.ops.triangulate(
                bm,
                faces=list(patch_faces),
                quad_method='BEAUTY',
                ngon_method='BEAUTY',
            )
            patch_faces = self._collect_patch_faces_from_boundary(
                boundary_edges,
                original_faces,
            )
            self._tag_patch_faces(bm, patch_faces)
            patch_boundary_verts = self._patch_boundary_verts_from_faces(patch_faces)
            self._relax_patch_verts(
                patch_faces,
                patch_boundary_verts,
                surface_samples,
            )
            try:
                patch_faces = self._collect_patch_faces_from_boundary(
                    boundary_edges,
                    original_faces,
                )
                self._tag_patch_faces(bm, patch_faces)
                bmesh.ops.beautify_fill(
                    bm,
                    faces=list(patch_faces),
                    edges=[],
                    method='AREA',
                )
            except Exception:
                pass

            if quadrangulate:
                patch_faces = self._collect_patch_faces_from_boundary(
                    boundary_edges,
                    original_faces,
                )
                try:
                    bmesh.ops.join_triangles(
                        bm,
                        faces=list(patch_faces),
                        cmp_seam=False,
                        cmp_sharp=False,
                        cmp_uvs=False,
                        cmp_vcols=False,
                        cmp_materials=False,
                        angle_face_threshold=math.radians(140.0),
                        angle_shape_threshold=math.radians(140.0),
                        topology_influence=0.85,
                        deselect_joined=False,
                    )
                    patch_faces = self._collect_patch_faces_from_boundary(
                        boundary_edges,
                        original_faces,
                    )
                except Exception:
                    pass

        patch_faces = self._collect_patch_faces_from_boundary(
            boundary_edges,
            original_faces,
        )
        quad_count = sum(1 for face in patch_faces if len(face.verts) == 4)
        tri_count = sum(1 for face in patch_faces if len(face.verts) == 3)

        self._clear_patch_tags(bm)
        if quadrangulate:
            return True, (
                f"Quad Fallback 封闭 {len(boundary_edges)} 边孔洞"
                f" / 四边 {quad_count} 面"
                f" / 三角 {tri_count} 面"
            )
        return True, (
            f"Smooth Patch 封闭 {len(boundary_edges)} 边孔洞"
            f" / 细分 {refined_edges} 边"
        )

    def _fill_active_hole_patch(self, context, hole, quadrangulate=False):
        obj, bm = self._edit_bmesh(context)
        if bm is None:
            return False, "没有可编辑网格"

        success, message = self._fill_hole_patch_bm(
            bm,
            hole,
            quadrangulate=quadrangulate,
        )
        if success:
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        return success, message

    def _fill_hole_triangle_bm(self, bm, hole):
        bm.edges.ensure_lookup_table()
        edges = []
        for edge_index in hole["edge_indices"]:
            if edge_index < 0 or edge_index >= len(bm.edges):
                return False, "孔洞数据已变化，请移动鼠标刷新"
            edge = bm.edges[edge_index]
            if not edge.is_valid or not edge.is_boundary:
                return False, "孔洞已经被封闭"
            edges.append(edge)

        boundary_verts = set()
        for edge in edges:
            boundary_verts.update(edge.verts)
        surface_samples = self._boundary_surface_samples(boundary_verts)

        try:
            result = bmesh.ops.triangle_fill(
                bm,
                edges=edges,
                normal=hole["normal"],
                use_beauty=True,
                use_dissolve=False,
            )
        except Exception as exc:
            return False, f"Triangle Fill 失败: {exc}"

        new_faces = [
            item for item in result.get("geom", [])
            if isinstance(item, bmesh.types.BMFace)
        ]
        if not new_faces:
            return False, "Triangle Fill 未生成面"

        if new_faces and hole["normal"].length > 1e-8:
            fill_normal = Vector((0.0, 0.0, 0.0))
            for face in new_faces:
                face.normal_update()
                fill_normal += face.normal
            if fill_normal.length > 1e-8 and fill_normal.dot(hole["normal"]) < 0.0:
                bmesh.ops.reverse_faces(bm, faces=new_faces)

        self._relax_patch_verts(
            set(new_faces),
            boundary_verts,
            surface_samples,
        )

        return True, f"Triangle Fill 三角封闭 {len(edges)} 边孔洞"

    def _fill_active_hole_triangle(self, context, hole):
        obj, bm = self._edit_bmesh(context)
        if bm is None:
            return False, "没有可编辑网格"

        success, message = self._fill_hole_triangle_bm(bm, hole)
        if success:
            bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        return success, message

    def _fill_active_hole(self, context):
        hole = self._active_hole()
        if hole is None:
            self.message = "鼠标下没有闭合孔洞"
            return False

        if self.fill_mode == 'TRIANGLE':
            success, message = self._fill_active_hole_triangle(context, hole)
        elif self.fill_mode == 'QUAD_PATCH':
            obj, bm = self._edit_bmesh(context)
            if bm is None:
                success, message = False, "没有可编辑网格"
            else:
                success, message = self._fill_hole_quad_grid_bm(
                    bm,
                    hole,
                )
                if not success:
                    success, message = self._fill_hole_patch_bm(
                        bm,
                        hole,
                        quadrangulate=True,
                    )
                    if success:
                        message = f"{message} / Grid 回退"
                if success:
                    bmesh.update_edit_mesh(
                        obj.data,
                        loop_triangles=True,
                        destructive=True,
                    )
        else:
            success, message = self._fill_active_hole_patch(context, hole)

        self.message = message if success else f"封闭失败: {message}"
        return success

    def _preview_mode_supported(self):
        return self.fill_mode in {'SMOOTH_PATCH', 'QUAD_PATCH', 'TRIANGLE'}

    def _build_preview_faces_for_hole(self, context, hole):
        if not self._preview_mode_supported():
            return False, "当前模式不支持伪预览", []

        obj, bm = self._edit_bmesh(context)
        if obj is None or bm is None:
            return False, "没有可编辑网格", []

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        temp_bm = bmesh.new()
        vert_map = {}
        for vert in bm.verts:
            new_vert = temp_bm.verts.new(vert.co.copy())
            vert_map[vert.index] = new_vert
        temp_bm.verts.ensure_lookup_table()
        temp_bm.verts.index_update()

        for edge in bm.edges:
            if edge.is_valid:
                try:
                    temp_bm.edges.new((
                        vert_map[edge.verts[0].index],
                        vert_map[edge.verts[1].index],
                    ))
                except ValueError:
                    pass

        for face in bm.faces:
            if not face.is_valid:
                continue
            try:
                temp_bm.faces.new([vert_map[vert.index] for vert in face.verts])
            except ValueError:
                pass

        temp_bm.verts.ensure_lookup_table()
        temp_bm.edges.ensure_lookup_table()
        temp_bm.faces.ensure_lookup_table()
        temp_bm.verts.index_update()
        temp_bm.edges.index_update()
        temp_bm.faces.index_update()
        temp_bm.normal_update()
        old_face_count = len(temp_bm.faces)

        temp_hole = {
            "edge_indices": list(hole["edge_indices"]),
            "normal": hole["normal"].copy(),
        }

        try:
            if self.fill_mode == 'TRIANGLE':
                success, message = self._fill_hole_triangle_bm(temp_bm, temp_hole)
            elif self.fill_mode == 'QUAD_PATCH':
                temp_hole["vert_indices"] = list(hole.get("vert_indices", []))
                success, message = self._fill_hole_quad_grid_bm(
                    temp_bm,
                    temp_hole,
                )
                if not success:
                    success, message = self._fill_hole_patch_bm(
                        temp_bm,
                        temp_hole,
                        quadrangulate=True,
                    )
                    if success:
                        message = f"{message} / Grid 回退"
            else:
                success, message = self._fill_hole_patch_bm(temp_bm, temp_hole)
        except Exception as exc:
            temp_bm.free()
            return False, f"预览失败: {exc}", []

        if not success:
            temp_bm.free()
            return False, f"预览失败: {message}", []

        temp_bm.verts.ensure_lookup_table()
        temp_bm.edges.ensure_lookup_table()
        temp_bm.faces.ensure_lookup_table()
        temp_bm.verts.index_update()
        temp_bm.edges.index_update()
        temp_bm.faces.index_update()
        temp_bm.normal_update()
        world = obj.matrix_world
        preview_faces = []
        tagged_faces = [
            face for face in temp_bm.faces
            if face.is_valid and face.tag
        ]
        export_faces = tagged_faces if tagged_faces else list(temp_bm.faces)[old_face_count:]
        for face in export_faces:
            if len(face.verts) < 3:
                continue
            preview_faces.append([world @ vert.co.copy() for vert in face.verts])

        temp_bm.free()
        return bool(preview_faces), message, preview_faces

    def _queue_active_hole_preview(self, context):
        hole = self._active_hole()
        if hole is None:
            self.message = "鼠标下没有闭合孔洞"
            return False

        signature = hole.get("signature")
        if signature in self.preview_hole_signatures:
            self.preview_hole_signatures = [
                item for item in self.preview_hole_signatures
                if item != signature
            ]
            if self.preview_hole_signatures:
                self._rebuild_preview_faces(context)
                self.message = f"已移除孔洞，剩余 {len(self.preview_hole_signatures)} 个"
            else:
                self._clear_preview("已移除最后一个孔洞")
            return True

        if signature is not None:
            self.preview_hole_signatures.append(signature)

        return self._rebuild_preview_faces(context)

    def _queue_all_holes_preview(self, context):
        self._rebuild_holes(context)
        signatures = [
            hole.get("signature")
            for hole in self.holes
            if hole.get("signature") is not None
        ]
        if not signatures:
            self.message = "没有可预览孔洞"
            return False

        self.preview_hole_signatures = signatures
        if self._rebuild_preview_faces(context):
            self.message = "全部孔洞已预览"
            return True

        return False

    def _hole_by_signature(self, signature):
        for index, hole in enumerate(self.holes):
            if hole.get("signature") == signature:
                return index, hole
        return -1, None

    def _rebuild_preview_faces(self, context):
        self.preview_faces = []
        if not self.preview_hole_signatures:
            return False

        if not self._preview_mode_supported():
            self.message = (
                f"已加入 {len(self.preview_hole_signatures)} 个孔洞，"
                "当前模式不支持伪预览"
            )
            return True

        all_preview_faces = []
        messages = []
        valid_signatures = []
        for signature in self.preview_hole_signatures:
            _hole_index, hole = self._hole_by_signature(signature)
            if hole is None:
                continue
            success, message, faces = self._build_preview_faces_for_hole(
                context,
                hole,
            )
            if success:
                valid_signatures.append(signature)
                all_preview_faces.extend(faces)
                messages.append(message)

        self.preview_hole_signatures = valid_signatures
        self.preview_faces = all_preview_faces

        if not self.preview_hole_signatures:
            self.message = "预览失败: 没有有效孔洞"
            return False

        self.message = (
            f"预览 {len(self.preview_hole_signatures)} 个孔洞"
            f" / {messages[-1] if messages else ''}"
        )
        return bool(self.preview_faces)

    def _clear_preview(self, message="已清除预览"):
        had_preview = bool(self.preview_faces or self.preview_hole_signatures)
        self.preview_faces = []
        self.preview_hole_signatures = []
        if had_preview:
            self.message = message
        return had_preview

    def _hole_line_coords(self, hole):
        points = hole["world_points"]
        if len(points) < 2:
            return []

        coords = []
        for index, start in enumerate(points):
            coords.append(start)
            coords.append(points[(index + 1) % len(points)])

        return coords

    def _draw_hole_lines(self, shader, hole, color, line_width):
        coords = self._hole_line_coords(hole)
        if not coords:
            return

        gpu.state.line_width_set(line_width)
        batch = batch_for_shader(shader, 'LINES', {"pos": coords})
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw_preview_faces(self, shader):
        if not self.preview_faces:
            return

        tri_coords = []
        line_coords = []
        for face in self.preview_faces:
            if len(face) < 3:
                continue
            anchor = face[0]
            for index in range(1, len(face) - 1):
                tri_coords.extend([anchor, face[index], face[index + 1]])
            for index, point in enumerate(face):
                line_coords.append(point)
                line_coords.append(face[(index + 1) % len(face)])

        if tri_coords:
            gpu.state.depth_test_set('LESS_EQUAL')
            gpu.state.depth_mask_set(False)
            batch = batch_for_shader(shader, 'TRIS', {"pos": tri_coords})
            shader.uniform_float("color", (0.15, 0.95, 0.35, 0.34))
            batch.draw(shader)

        if line_coords:
            gpu.state.line_width_set(1.6)
            batch = batch_for_shader(shader, 'LINES', {"pos": line_coords})
            shader.uniform_float("color", (0.82, 1.0, 0.30, 0.95))
            batch.draw(shader)

    def draw_preview(self):
        if not self.holes:
            return

        active_index = self.active_hole_index
        inactive_holes = [
            hole for index, hole in enumerate(self.holes)
            if index != active_index
        ]
        active_hole = self._active_hole()

        gpu.state.blend_set('ALPHA')
        gpu.state.depth_mask_set(False)

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader.bind()

        # Faint no-depth pass keeps blocked holes discoverable without dominating.
        gpu.state.depth_test_set('NONE')
        for hole in inactive_holes:
            self._draw_hole_lines(shader, hole, (1.0, 0.08, 0.04, 0.18), 5.0)
            self._draw_hole_lines(shader, hole, (1.0, 0.88, 0.10, 0.28), 2.0)
        if active_hole:
            self._draw_hole_lines(shader, active_hole, (0.05, 1.0, 0.25, 0.24), 7.0)
            self._draw_hole_lines(shader, active_hole, (0.70, 1.0, 0.30, 0.34), 3.0)

        # Depth-tested pass reads and writes depth so mesh surfaces occlude the hint.
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        for hole in inactive_holes:
            self._draw_hole_lines(shader, hole, (1.0, 0.08, 0.04, 0.92), 5.0)
            self._draw_hole_lines(shader, hole, (1.0, 0.92, 0.08, 1.0), 2.0)
        if active_hole:
            self._draw_hole_lines(shader, active_hole, (0.02, 0.95, 0.20, 0.98), 7.0)
            self._draw_hole_lines(shader, active_hole, (0.72, 1.0, 0.22, 1.0), 3.0)

        self._draw_preview_faces(shader)

        gpu.state.line_width_set(1.0)
        gpu.state.depth_mask_set(True)
        gpu.state.blend_set('NONE')
        gpu.state.depth_test_set('LESS_EQUAL')

    def draw_text(self):
        font_id = 0
        blf.size(font_id, 16)

        x = self.mouse_x + 20
        y = self.mouse_y + 20

        active_hole = self._active_hole()
        queued_count = len(self.preview_hole_signatures)

        if queued_count:
            status_text = tr("预览中")
            status_color = (0.35, 1.0, 0.35, 1.0)
        elif active_hole:
            status_text = tr("已命中孔洞")
            status_color = (0.42, 1.0, 0.42, 1.0)
        else:
            status_text = tr("寻找孔洞")
            status_color = (1.0, 0.65, 0.18, 1.0)

        if self.message.startswith("预览"):
            status_text = tr("预览已更新")
            status_color = (0.35, 1.0, 0.35, 1.0)
        elif "提交" in self.message or ("封闭" in self.message and not self.message.startswith("封闭失败")):
            status_text = tr("已提交")
            status_color = (0.35, 1.0, 0.35, 1.0)
        elif self.message.startswith("倍率"):
            status_text = tr("密度已调整")
            status_color = (1.0, 0.85, 0.2, 1.0)
        elif self.message.startswith("模式切换"):
            status_text = tr("模式已切换")
            status_color = (1.0, 0.85, 0.2, 1.0)
        elif self.message.startswith("已移除"):
            status_text = tr("已取消预览")
            status_color = (1.0, 0.85, 0.2, 1.0)
        elif self.message.startswith("全部"):
            status_text = tr("全部已预览")
            status_color = (0.35, 1.0, 0.35, 1.0)
        elif self.message.startswith("封闭失败"):
            status_text = tr("封闭失败")
            status_color = (1.0, 0.28, 0.20, 1.0)

        # 跟骨链工具保持同一套 HUD：阴影、黄色按键、白色说明。
        blf.enable(font_id, blf.SHADOW)
        blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.6)
        blf.shadow_offset(font_id, 1, -1)

        def draw_key_value(key_text, value_text, offset_y, value_color=(1.0, 1.0, 1.0, 1.0)):
            blf.color(font_id, 1.0, 0.85, 0.2, 1.0)
            blf.position(font_id, x, y + offset_y, 0)
            blf.draw(font_id, key_text)
            key_width, _ = blf.dimensions(font_id, key_text)

            blf.color(font_id, *value_color)
            blf.position(font_id, x + key_width, y + offset_y, 0)
            blf.draw(font_id, value_text)

        mode_names = {
            'SMOOTH_PATCH': "Smooth Patch",
            'QUAD_PATCH': "Quad Grid",
            'TRIANGLE': "Triangle Fill",
        }

        draw_key_value("状态:", status_text, 0, status_color)
        draw_key_value("左键:", "加入/取消预览", 24)
        draw_key_value("右键:", "取消/退出", 46)
        draw_key_value("Enter:", "提交", 68)
        draw_key_value("A键:", "全部预览", 94)
        draw_key_value("F键:", mode_names.get(self.fill_mode, self.fill_mode), 118)
        draw_key_value("Shift+滚轮:", f"倍率 {self.patch_edge_factor:.2f}", 140)
        draw_key_value("Ctrl+Shift滚轮:", f"吸附 {self.patch_surface_blend:.2f}", 162)
        draw_key_value("R键:", "刷新", 184)

        blf.disable(font_id, blf.SHADOW)

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            if self._clear_preview("已取消预览"):
                self._tag_redraw(context)
                return {'RUNNING_MODAL'}
            self.finish(context)
            if self.did_fill:
                return {'FINISHED'}
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            self._update_hover(context, event)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELUPMOUSE':
            if not event.shift:
                return {'PASS_THROUGH'}
            if event.ctrl:
                self.patch_surface_blend = min(1.0, self.patch_surface_blend + 0.05)
                self.message = f"曲面吸附: {self.patch_surface_blend:.2f}"
            else:
                self.patch_edge_factor = max(0.35, self.patch_edge_factor * 0.9)
                self.message = f"倍率: {self.patch_edge_factor:.2f}"
            if self.preview_hole_signatures:
                self._rebuild_preview_faces(context)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'WHEELDOWNMOUSE':
            if not event.shift:
                return {'PASS_THROUGH'}
            if event.ctrl:
                self.patch_surface_blend = max(0.0, self.patch_surface_blend - 0.05)
                self.message = f"曲面吸附: {self.patch_surface_blend:.2f}"
            else:
                self.patch_edge_factor = min(4.0, self.patch_edge_factor / 0.9)
                self.message = f"倍率: {self.patch_edge_factor:.2f}"
            if self.preview_hole_signatures:
                self._rebuild_preview_faces(context)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._queue_active_hole_preview(context)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'A' and event.value == 'PRESS':
            self._queue_all_holes_preview(context)
            self._update_hover_at(context)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if self.preview_hole_signatures:
                queued_signatures = list(self.preview_hole_signatures)
                filled_count = 0
                messages = []
                self._clear_preview("")
                for signature in queued_signatures:
                    self._rebuild_holes(context)
                    hole_index, _hole = self._hole_by_signature(signature)
                    if hole_index < 0:
                        continue
                    self.active_hole_index = hole_index
                    if self._fill_active_hole(context):
                        filled_count += 1
                        messages.append(self.message)
                self.did_fill = self.did_fill or filled_count > 0
                self._rebuild_holes(context)
                self._update_hover_at(context)
                if filled_count:
                    tail = messages[-1] if messages else ""
                    self.message = f"已提交 {filled_count} 个孔洞: {tail}"
                else:
                    self.message = "没有成功提交的孔洞"
            else:
                self.message = "没有待提交孔洞"
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'F' and event.value == 'PRESS':
            modes = ['SMOOTH_PATCH', 'QUAD_PATCH', 'TRIANGLE']
            mode_names = {
                'SMOOTH_PATCH': "Smooth Patch",
                'QUAD_PATCH': "Quad Grid",
                'TRIANGLE': "Triangle Fill",
            }
            index = modes.index(self.fill_mode) if self.fill_mode in modes else -1
            self.fill_mode = modes[(index + 1) % len(modes)]
            self.message = f"模式切换: {mode_names[self.fill_mode]}"
            if self.preview_hole_signatures:
                self._rebuild_preview_faces(context)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type == 'R' and event.value == 'PRESS':
            self._clear_preview("")
            self._rebuild_holes(context)
            self._update_hover(context, event)
            self._tag_redraw(context)
            return {'RUNNING_MODAL'}

        if event.type in {
            'MIDDLEMOUSE',
            'WHEELUPMOUSE',
            'WHEELDOWNMOUSE',
            'TRACKPADPAN',
            'TRACKPADZOOM',
            'NDOF_MOTION',
        }:
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'}

    def finish(self, context):
        handle_3d = getattr(self, "_handle_3d", None)
        handle_text = getattr(self, "_handle_text", None)
        if handle_3d is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle_3d, 'WINDOW')
            self._handle_3d = None
        if handle_text is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle_text, 'WINDOW')
            self._handle_text = None
        self._tag_redraw(context)

    def invoke(self, context, event):
        self.mouse_x = event.mouse_region_x
        self.mouse_y = event.mouse_region_y
        self.holes = []
        self.active_hole_index = -1
        self.message = ""
        self.obj = None
        self.did_fill = False
        self.preview_faces = []
        self.preview_hole_signatures = []
        if not self._preview_mode_supported():
            self.fill_mode = 'SMOOTH_PATCH'

        self._rebuild_holes(context)
        self._update_hover(context, event)

        self._handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_preview, (), 'WINDOW', 'POST_VIEW'
        )
        self._handle_text = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_text, (), 'WINDOW', 'POST_PIXEL'
        )

        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {'RUNNING_MODAL'}


class OP_MeshToImageEmpty(Operator):
    bl_idname = "ho.mesh_to_image_empty"
    bl_label = "面片转参考图"
    bl_description = "将面片转为 Image Empty，复用原物体变换，尺寸基于面片世界空间最长边"
    
    @classmethod
    def description(cls, context, properties):
        return tr("将面片转为 Image Empty，复用原物体变换，尺寸基于面片世界空间最长边")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(
            obj.type == 'MESH'
            for obj in context.selected_objects
        )

    def execute(self, context):
        objs = context.selected_objects
        if not objs:
            self.report({'ERROR'}, tr("未选择物体"))
            return {'CANCELLED'}

        for obj in list(objs):
            # 仅处理 Mesh
            if obj.type != 'MESH' or not obj.data.polygons:
                continue

            image = get_first_image_from_material(obj)
            if not image:
                continue

            # 取选中面，否则取第一个面
            face = next((f for f in obj.data.polygons if f.select), None)
            if not face:
                face = obj.data.polygons[0]

            # 创建 Image Empty
            empty = bpy.data.objects.new(f"REF_{image.name}", None)
            empty.empty_display_type = 'IMAGE'
            empty.data = image

            # 直接服用原物体变换
            empty.matrix_world = obj.matrix_world.copy()

            # Image Empty 使用 bbox 最长边作为显示尺寸
            empty.empty_display_size = longest_edge_world(obj, face)
            empty.scale = (1, 1, 1)

            # 链接到场景
            context.collection.objects.link(empty)

            # 删除原 Mesh
            bpy.data.objects.remove(obj, do_unlink=True)

        return {'FINISHED'}

class OP_MergeOverlapping_VertexNormals(Operator):
    bl_idname = "ho.merge_overlapping_vertexnormals"
    bl_label = "合并最近顶点法线(仅法线)"
    bl_description = "支持多物体同时编辑（未合并物体情况），仅合并法线不合并mesh，法线写入自定义法线"
    
    @classmethod
    def description(cls, context, properties):
        return tr("支持多物体同时编辑（未合并物体情况），仅合并法线不合并mesh，法线写入自定义法线")
    bl_options = {'REGISTER', 'UNDO'}

    distancs:FloatProperty(name="间距",default=0.0001,min=0) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'MESH' and
            context.mode == 'EDIT_MESH'
        )

    def execute(self, context):
        distance = self.distancs
        if distance <= 0:
            self.report({'WARNING'}, tr("间距必须大于 0"))
            return {'CANCELLED'}

        edit_objs = [
            obj for obj in context.objects_in_mode_unique_data
            if obj.type == 'MESH'
        ]

        if not edit_objs:
            return {'CANCELLED'}

        # 退出编辑模式，让 mesh 数据同步
        bpy.ops.object.mode_set(mode='OBJECT')

        items = []
        any_selected = False

        for obj in edit_objs:
            mesh = obj.data
            mw = obj.matrix_world
            normal_mat = mw.to_3x3().inverted().transposed()

            if any(v.select and not v.hide for v in mesh.vertices):
                any_selected = True

            for v in mesh.vertices:
                if v.hide:
                    continue

                items.append({
                    "obj": obj,
                    "mesh": mesh,
                    "vi": v.index,
                    "selected": v.select,
                    "co": mw @ v.co,
                    "normal_world": (normal_mat @ v.normal).normalized(),
                })

        # 如果有选中点，只处理选中点；否则处理全部点
        if any_selected:
            items = [it for it in items if it["selected"]]

        if len(items) < 2:
            bpy.ops.object.mode_set(mode='EDIT')
            self.report({'INFO'}, tr("可处理的顶点少于 2 个"))
            return {'FINISHED'}

        # ---------- 并查集 ----------
        parent = list(range(len(items)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # ---------- 空间哈希找近邻 ----------
        cell_size = distance
        dist_sq = distance * distance
        grid = defaultdict(list)

        def cell_key(co):
            return (
                math.floor(co.x / cell_size),
                math.floor(co.y / cell_size),
                math.floor(co.z / cell_size),
            )

        for i, it in enumerate(items):
            co = it["co"]
            cx, cy, cz = cell_key(co)

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        key = (cx + dx, cy + dy, cz + dz)
                        for j in grid.get(key, []):
                            if (co - items[j]["co"]).length_squared <= dist_sq:
                                union(i, j)

            grid[(cx, cy, cz)].append(i)

        groups = defaultdict(list)
        for i in range(len(items)):
            groups[find(i)].append(i)

        # ---------- 计算每组平均世界法线 ----------
        merged_count = 0
        target_normals = defaultdict(dict)

        for group in groups.values():
            if len(group) < 2:
                continue

            avg = Vector((0.0, 0.0, 0.0))
            for idx in group:
                avg += items[idx]["normal_world"]

            if avg.length <= 1e-8:
                continue

            avg.normalize()
            merged_count += len(group)

            for idx in group:
                it = items[idx]
                obj :bpy.types.Object = it["obj"]

                # 世界法线转回物体本地法线
                local_normal = (obj.matrix_world.to_3x3().transposed() @ avg).normalized()
                target_normals[obj][it["vi"]] = local_normal

        # ---------- 写入 custom normals ----------
        for obj, normal_map in target_normals.items():
            mesh :bpy.types.Mesh = obj.data

            normals = [v.normal.copy() for v in mesh.vertices]

            for vi, n in normal_map.items():
                normals[vi] = n

            # 自定义法线通常需要 smooth face 才明显生效
            for poly in mesh.polygons:
                poly.use_smooth = True

            if hasattr(mesh, "use_auto_smooth"):
                mesh.use_auto_smooth = True

            mesh.normals_split_custom_set_from_vertices(normals)
            mesh.update()

        bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, tr("已合并 {0} 个重叠/近邻顶点的法线").format(merged_count))
        return {'FINISHED'}

def draw_in_OUTLINER_MT_context_menu(self, context: bpy.types.Context):
    """大纲视图右键菜单"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_sync_render_visibility.bl_idname,
                    icon="RESTRICT_RENDER_OFF")


def draw_in_DATA_PT_modifiers(self, context: bpy.types.Context):
    """修改器顶上"""
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画

    obj = context.object

    if not obj:
        return  # 未选物体不显示
    if not obj.modifiers:
        return  # 物体没有修改器不显示
    if obj.type != "MESH":
        return  # 不是网格的不显示

    row = layout.row(align=True)
    row.operator(OP_CopyALL_modifiers_to_selected.bl_idname,
                 text=tr("复制全部到所选"))


def draw_in_DATA_PT_customdata(self, context: bpy.types.Context):
    """几何数据属性下"""
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)
    row.operator(OP_CustomSplitNormals_Export.bl_idname)
    row.operator(OP_CustomSplitNormals_Import.bl_idname)


def draw_in_VIEW3D_MT_object_convert(self, context: bpy.types.Context):
    """物体转换菜单下"""
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)
    row.operator(OP_MeshToImageEmpty.bl_idname)


def draw_in_VIEW3D_MT_edit_curve_context_menu(self, context: bpy.types.Context):
    """曲线物体右键菜单下"""
    # TODO
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)

def draw_in_VIEW3D_MT_edit_mesh_merge(self, context: bpy.types.Context):
    """编辑模式，M合并菜单内"""
    layout: bpy.types.UILayout = self.layout
    row = layout.row(align=True)
    row.operator(OP_MergeOverlapping_VertexNormals.bl_idname)


class VIEW3D_MT_edit_mesh_hotools(Menu):
    """编辑模式右键时的菜单追加"""
    bl_label = "Hotools"

    def draw(self, context):
        layout = self.layout
        layout.operator(OP_PlaceObjectBottom.bl_idname, icon='TRIA_DOWN')
        layout.operator(OP_AlignViewToAvgNormal.bl_idname,
                        icon="RESTRICT_RENDER_OFF")
        layout.operator(OP_CreatBoneChainByMeshFlow.bl_idname, icon="ADD")
        layout.operator(OP_ModalFillMeshHole.bl_idname, icon="FACESEL")


def draw_in_VIEW3D_MT_edit_mesh_context_menu(self, context):
    """编辑模式右键时的菜单追加"""
    self.layout.menu("VIEW3D_MT_edit_mesh_hotools")


def draw_in_TOPBAR_MT_editor_menus(self, context):
    # TODO 不知道要不要加,顶部的快速重启bl按键
    layout: bpy.types.UILayout = self.layout
    layout.alert = True
    layout.operator(OP_RestartBlender.bl_idname, icon="QUIT", text="")
    layout.alert = False


cls = [OP_select_inside_face_loop, OP_RestartBlender,
       OP_sync_render_visibility,
       OP_CopyALL_modifiers_to_selected, OP_PlaceObjectBottom,
       VIEW3D_MT_edit_mesh_hotools,
       OP_AlignViewToAvgNormal,
       OP_CustomSplitNormals_Import, OP_CustomSplitNormals_Export,
       OP_MeshToImageEmpty,
       OP_AddSelectSideRingLoops, OP_RemoveSelectSideRingLoops,
       OP_CreatBoneChainByMeshFlow, OP_ModalFillMeshHole,
       OP_MergeOverlapping_VertexNormals
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.OUTLINER_MT_context_menu.append(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_modifiers.append(draw_in_DATA_PT_modifiers)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(
        draw_in_VIEW3D_MT_edit_mesh_context_menu)
    bpy.types.DATA_PT_customdata.append(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_object_convert.append(draw_in_VIEW3D_MT_object_convert)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.append(
        draw_in_VIEW3D_MT_edit_curve_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.append(draw_in_TOPBAR_MT_editor_menus)
    bpy.types.VIEW3D_MT_edit_mesh_merge.append(draw_in_VIEW3D_MT_edit_mesh_merge)

    # 快捷键设置可以被preference保存，不用担心注册阶段写死
    wm = bpy.context.window_manager
    # 填充选择-默认绑定 Ctrl + Shift + 右键
    km = wm.keyconfigs.addon.keymaps.new(
        name="Window", space_type="EMPTY", region_type="WINDOW")
    kmi = km.keymap_items.new(OP_select_inside_face_loop.bl_idname,
                              type='RIGHTMOUSE', value='PRESS', ctrl=True, shift=True)
    kmi.active = True

    # 加减选环线-默认绑定 Alt + 小键盘"+/-"
    km = wm.keyconfigs.addon.keymaps.new(
        name="Window", space_type="EMPTY", region_type="WINDOW")
    kmi = km.keymap_items.new(OP_AddSelectSideRingLoops.bl_idname,
                              type='NUMPAD_PLUS', value='PRESS', alt=True)
    kmi.active = True
    kmi = km.keymap_items.new(OP_RemoveSelectSideRingLoops.bl_idname,
                              type='NUMPAD_MINUS', value='PRESS', alt=True)
    kmi.active = True

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    bpy.types.OUTLINER_MT_context_menu.remove(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_modifiers.remove(draw_in_DATA_PT_modifiers)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(
        draw_in_VIEW3D_MT_edit_mesh_context_menu)
    bpy.types.DATA_PT_customdata.remove(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(
        draw_in_VIEW3D_MT_edit_curve_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.remove(draw_in_TOPBAR_MT_editor_menus)
    bpy.types.VIEW3D_MT_edit_mesh_merge.remove(draw_in_VIEW3D_MT_edit_mesh_merge)


    ureg_props()
