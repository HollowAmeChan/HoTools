import bpy
import json
import subprocess
from mathutils import Matrix, Vector
from collections import defaultdict

import bmesh
import math
from bpy.types import Operator
from bpy.props import FloatProperty, IntVectorProperty
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

class HO_OT_QuickAddLattice(Operator):
    """以固定默认值为物体模式选中项快速添加晶格。"""

    bl_idname = "ho.quick_add_lattice"
    bl_label = "快速添加晶格"
    bl_description = "单物体使用本地包围盒，多物体使用全局整体包围盒"
    bl_options = {'REGISTER', 'UNDO'}

    _OBJECT_TYPES = {
        'LATTICE', 'MESH', 'CURVE', 'FONT', 'SURFACE',
        'GREASEPENCIL', 'GPENCIL',
    }
    _GREASE_PENCIL_TYPES = {'GREASEPENCIL', 'GPENCIL'}

    @classmethod
    def _selected_objects(cls, context):
        """获取物体模式下可添加晶格修改器的选中物体。"""
        if getattr(context, "mode", None) != 'OBJECT':
            return []
        return [
            obj for obj in getattr(context, "selected_objects", ())
            if getattr(obj, "type", None) in cls._OBJECT_TYPES
        ]

    @staticmethod
    def _object_points(obj):
        """将物体包围盒角点转换到世界空间。"""
        bound_box = getattr(obj, "bound_box", ())
        if not bound_box:
            return []
        try:
            points = [obj.matrix_world @ Vector(corner) for corner in bound_box]
        except (AttributeError, TypeError, ValueError):
            return []
        if not all(math.isfinite(float(value)) for point in points for value in point):
            return []
        return points

    @classmethod
    def _bounds(cls, objects, rotation):
        """在晶格自身坐标系中计算选中物体的中心和尺寸。"""
        inverse_rotation = rotation.to_matrix().transposed()
        points = []
        for obj in objects:
            points.extend(
                inverse_rotation @ point
                for point in cls._object_points(obj)
            )
        if not points:
            return None

        minimum = Vector(tuple(
            min(point[index] for point in points)
            for index in range(3)
        ))
        maximum = Vector(tuple(
            max(point[index] for point in points)
            for index in range(3)
        ))
        center = (minimum + maximum) * 0.5
        # 退化轴使用一个很小的尺寸，避免生成不可用的晶格。
        extent = Vector(tuple(
            value if abs(value) > 1.0e-8 else 0.1
            for value in (maximum - minimum)
        ))
        return center, extent

    @staticmethod
    def _link_object(context, lattice_object):
        """将新晶格链接到当前集合。"""
        collection = getattr(context, "collection", None)
        if collection is None:
            collection = getattr(getattr(context, "scene", None), "collection", None)
        if collection is None:
            return False
        collection.objects.link(lattice_object)
        return True

    @staticmethod
    def _set_parent(obj, lattice_object):
        """设置父级，同时保持原物体的世界变换不变。"""
        world_matrix = obj.matrix_world.copy()
        obj.parent = lattice_object
        obj.matrix_parent_inverse = lattice_object.matrix_world.inverted()
        obj.matrix_world = world_matrix

    @classmethod
    def _add_modifier(cls, obj, lattice_object, name):
        """创建兼容不同 Blender 版本的晶格修改器。"""
        try:
            if getattr(obj, "type", None) in cls._GREASE_PENCIL_TYPES:
                grease_pencil_modifiers = getattr(obj, "grease_pencil_modifiers", None)
                if grease_pencil_modifiers is not None:
                    try:
                        modifier = grease_pencil_modifiers.new(
                            name=name,
                            type='GP_LATTICE',
                        )
                    except (RuntimeError, TypeError, ValueError):
                        modifier = obj.modifiers.new(
                            name=name,
                            type='GREASE_PENCIL_LATTICE',
                        )
                else:
                    modifier = obj.modifiers.new(
                        name=name,
                        type='GREASE_PENCIL_LATTICE',
                    )
            else:
                modifier = obj.modifiers.new(name=name, type='LATTICE')
            modifier.object = lattice_object
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        return modifier

    def _create(self, context, objects, rotation, name):
        """按当前分辨率创建线性晶格并绑定到物体。"""
        bounds = self._bounds(objects, rotation)
        if bounds is None:
            return None, 0

        center, extent = bounds
        lattice_data = bpy.data.lattices.new(name=f"{name}_LP")
        lattice_object = bpy.data.objects.new(
            name=lattice_data.name,
            object_data=lattice_data,
        )
        if not self._link_object(context, lattice_object):
            bpy.data.objects.remove(lattice_object, do_unlink=True)
            bpy.data.lattices.remove(lattice_data)
            return None, 0

        lattice_object.rotation_mode = 'QUATERNION'
        lattice_object.rotation_quaternion = rotation
        lattice_object.location = rotation @ center
        lattice_object.scale = extent
        lattice_data.points_u, lattice_data.points_v, lattice_data.points_w = self.resolution
        lattice_data.interpolation_type_u = 'KEY_LINEAR'
        lattice_data.interpolation_type_v = 'KEY_LINEAR'
        lattice_data.interpolation_type_w = 'KEY_LINEAR'

        # 等待变换更新后再计算父级逆矩阵，避免不同 Blender 版本读到旧矩阵。
        view_layer = getattr(context, "view_layer", None)
        if view_layer is not None:
            view_layer.update()

        attached = 0
        for index, obj in enumerate(objects, start=1):
            modifier = self._add_modifier(
                obj,
                lattice_object,
                name=f"Ho Lattice {index}",
            )
            if modifier is None:
                continue
            try:
                self._set_parent(obj, lattice_object)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
            attached += 1

        if attached == 0:
            bpy.data.objects.remove(lattice_object, do_unlink=True)
            if lattice_data.users == 0:
                bpy.data.lattices.remove(lattice_data)
            return None, 0
        return lattice_object, attached

    @classmethod
    def poll(cls, context):
        return bool(cls._selected_objects(context))

    def invoke(self, context, event):
        """从菜单调用时弹出唯一需要输入的分辨率参数。"""
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        objects = self._selected_objects(context)
        if not objects:
            self.report({'ERROR'}, "请在物体模式下选择可添加晶格的物体")
            return {'CANCELLED'}

        if len(objects) == 1:
            rotation = objects[0].matrix_world.to_quaternion()
            lattice_object, attached = self._create(
                context,
                objects,
                rotation,
                f"HoLattice_{objects[0].name}",
            )
        else:
            rotation = Matrix.Identity(3).to_quaternion()
            lattice_object, attached = self._create(
                context,
                objects,
                rotation,
                "HoLattice_Group",
            )

        if lattice_object is None:
            self.report({'ERROR'}, "没有物体可以添加晶格修改器")
            return {'CANCELLED'}

        self.report({'INFO'}, f"已添加晶格，影响 {attached} 个物体")
        return {'FINISHED'}

    resolution: IntVectorProperty(
        name="晶格分辨率",
        description="晶格在 U、V、W 三个方向上的控制点数量",
        size=3,
        default=(2, 2, 2),
        min=2,
        max=64,
        options={'SKIP_SAVE'},
    )

    def draw(self, context):
        """参数面板只显示分辨率，其余行为保持固定默认值。"""
        self.layout.prop(self, "resolution", text="分辨率")


class HO_MT_HoObjectTools(bpy.types.Menu):
    """物体模式下的 HoObjectTools 折叠菜单。"""

    bl_idname = "HO_MT_HoObjectTools"
    bl_label = "HoObjectTools"

    @classmethod
    def poll(cls, context):
        return getattr(context, "mode", None) == 'OBJECT'

    def draw(self, context):
        if getattr(context, "mode", None) != 'OBJECT':
            return
        self.layout.operator_context = 'INVOKE_DEFAULT'
        self.layout.operator(
            HO_OT_QuickAddLattice.bl_idname,
            text="快速添加晶格",
            icon='MOD_LATTICE',
        )


def draw_in_OUTLINER_MT_context_menu(self, context: bpy.types.Context):
    """大纲视图右键菜单"""
    layout: bpy.types.UILayout = self.layout
    layout.operator(OP_sync_render_visibility.bl_idname,
                    icon="RESTRICT_RENDER_OFF")


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


def draw_in_VIEW3D_MT_object_context_menu(self, context: bpy.types.Context):
    """仅在物体模式的对象右键菜单中显示 HoObjectTools。"""
    if getattr(context, "mode", None) != 'OBJECT':
        return
    self.layout.menu(
        HO_MT_HoObjectTools.bl_idname,
        text=HO_MT_HoObjectTools.bl_label,
        icon='OBJECT_DATA',
    )


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


cls = [OP_RestartBlender,
       OP_sync_render_visibility,
       OP_CopyALL_modifiers_to_selected,
       OP_CustomSplitNormals_Import, OP_CustomSplitNormals_Export,
       OP_MeshToImageEmpty,
       OP_AddSelectSideRingLoops, OP_RemoveSelectSideRingLoops,
       OP_MergeOverlapping_VertexNormals,
       HO_OT_QuickAddLattice,
       HO_MT_HoObjectTools,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    bpy.types.OUTLINER_MT_context_menu.append(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_customdata.append(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_object_convert.append(draw_in_VIEW3D_MT_object_convert)
    bpy.types.VIEW3D_MT_object_context_menu.prepend(
        draw_in_VIEW3D_MT_object_context_menu
    )
    bpy.types.VIEW3D_MT_edit_curve_context_menu.append(
        draw_in_VIEW3D_MT_edit_curve_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.append(draw_in_TOPBAR_MT_editor_menus)
    bpy.types.VIEW3D_MT_edit_mesh_merge.append(draw_in_VIEW3D_MT_edit_mesh_merge)

    # 快捷键设置可以被preference保存，不用担心注册阶段写死
    wm = bpy.context.window_manager
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    bpy.types.OUTLINER_MT_context_menu.remove(draw_in_OUTLINER_MT_context_menu)
    bpy.types.DATA_PT_customdata.remove(draw_in_DATA_PT_customdata)
    bpy.types.VIEW3D_MT_object_context_menu.remove(
        draw_in_VIEW3D_MT_object_context_menu
    )
    bpy.types.VIEW3D_MT_edit_curve_context_menu.remove(
        draw_in_VIEW3D_MT_edit_curve_context_menu)
    # bpy.types.TOPBAR_MT_editor_menus.remove(draw_in_TOPBAR_MT_editor_menus)
    bpy.types.VIEW3D_MT_edit_mesh_merge.remove(draw_in_VIEW3D_MT_edit_mesh_merge)


    ureg_props()
