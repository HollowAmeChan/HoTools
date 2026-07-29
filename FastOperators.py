import bpy
import json
import subprocess
from mathutils import Vector
from collections import defaultdict

import bmesh
import math
from bpy.types import Operator
from bpy.props import FloatProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper


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
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取活动物体和选中物体列表
        active_obj = context.active_object
        selected_objs = context.selected_objects

        if not active_obj:
            self.report({'ERROR'}, "没有活动物体")
            return {'CANCELLED'}

        if len(selected_objs) < 2:
            self.report({'ERROR'}, "需要选择至少两个物体（源物体+目标物体）")
            return {'CANCELLED'}

        modifiers = active_obj.modifiers
        if not modifiers:
            self.report({'INFO'}, "活动物体没有修改器")
            return {'FINISHED'}

        try:
            for m in modifiers:
                bpy.ops.object.modifier_copy_to_selected(
                    modifier=m.name
                )
        except RuntimeError as e:
            self.report({'ERROR'}, f"复制失败: {str(e)}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"成功复制 {len(modifiers)} 个修改器")
        return {'FINISHED'}






class OP_CustomSplitNormals_Export(Operator, ExportHelper):
    bl_idname = "ho.custom_splitnormal_export"
    bl_label = "导出自定义拆边法向为文件"
    bl_description = "如果没有添加自定义法线则跳过"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return context.object and context.object.type == 'MESH'

    def execute(self, context):
        obj = context.object
        mesh = obj.data

        if not mesh.has_custom_normals:
            self.report({'WARNING'}, "当前网格没有自定义法线")
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
            self.report({'ERROR'}, f"导出失败: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已导出 {len(normals)} 个自定义法线")
        return {'FINISHED'}


class OP_CustomSplitNormals_Import(Operator, ImportHelper):
    bl_idname = "ho.custom_splitnormal_import"
    bl_label = "导入自定义拆边法向文件"
    bl_description = "覆盖当前的自定义法向"
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
            self.report({'ERROR'}, f"读取文件失败: {e}")
            return {'CANCELLED'}

        if len(normal_data) != len(mesh.loops):
            self.report(
                {'ERROR'}, f"法线数量不匹配 ({len(normal_data)} vs {len(mesh.loops)})")
            return {'CANCELLED'}

        # 转换为 Vector 列表
        from mathutils import Vector
        split_normals = [Vector(n).normalized() for n in normal_data]

        # mesh.use_auto_smooth = True
        mesh.normals_split_custom_set(split_normals)
        self.report({'INFO'}, f"成功导入并应用 {len(split_normals)} 个法线")
        return {'FINISHED'}


class OP_AddSelectSideRingLoops(Operator):
    bl_idname = "ho.addselect_sideringloops"
    bl_label = "加选Ring"
    bl_description = "选择并排的循环边线,如果选中中的不是loop会尝试首先选择loop"
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
            self.report({'WARNING'}, "没有选中任何边")
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




class OP_MeshToImageEmpty(Operator):
    bl_idname = "ho.mesh_to_image_empty"
    bl_label = "面片转参考图"
    bl_description = "将面片转为 Image Empty，复用原物体变换，尺寸基于面片世界空间最长边"
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
            self.report({'ERROR'}, "未选择物体")
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
            self.report({'WARNING'}, "间距必须大于 0")
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
            self.report({'INFO'}, "可处理的顶点少于 2 个")
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

        self.report({'INFO'}, f"已合并 {merged_count} 个重叠/近邻顶点的法线")
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
                 text="复制全部到所选")


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






def draw_in_TOPBAR_MT_editor_menus(self, context):
    # TODO 不知道要不要加,顶部的快速重启bl按键
    layout: bpy.types.UILayout = self.layout
    layout.alert = True
    layout.operator(OP_RestartBlender.bl_idname, icon="QUIT", text="")
    layout.alert = False


cls = [OP_select_inside_face_loop, OP_RestartBlender,
       OP_sync_render_visibility,
       OP_CopyALL_modifiers_to_selected,
       OP_CustomSplitNormals_Import, OP_CustomSplitNormals_Export,
       OP_MeshToImageEmpty,
       OP_AddSelectSideRingLoops, OP_RemoveSelectSideRingLoops,
       OP_MergeOverlapping_VertexNormals
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.OUTLINER_MT_context_menu.append(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_modifiers.append(draw_in_DATA_PT_modifiers)
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
    bpy.types.DATA_PT_customdata.remove(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(
        draw_in_VIEW3D_MT_edit_curve_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.remove(draw_in_TOPBAR_MT_editor_menus)
    bpy.types.VIEW3D_MT_edit_mesh_merge.remove(draw_in_VIEW3D_MT_edit_mesh_merge)


    ureg_props()
