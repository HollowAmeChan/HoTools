import bpy
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy.types import UILayout, Context
from bpy.types import Mesh, Object
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty
from mathutils import Vector
import bmesh
from collections import defaultdict
from mathutils.kdtree import KDTree
import math
# region 变量


class PG_transferSettings(PropertyGroup):
    '''操作的全部设置'''
    src_object: PointerProperty(
        type=bpy.types.Object,
        name="源网格",
        description="选择一个源网格",
        update=None
    )  # type: ignore

    dest_object: PointerProperty(
        type=bpy.types.Object,
        name="目标网格",
        description="选择一个目标网格",
        update=None
    )  # type: ignore

    only_selected_dest: BoolProperty(
        name="仅目标选中顶点",
        description="仅计算目标物体选中的顶点",
        default=False
    )  # type: ignore

    only_selected_src: BoolProperty(
        name="仅源物体选中顶点",
        description="仅计算源物体选中的顶点",
        default=False
    )  # type: ignore

    use_one_vertex: BoolProperty(
        name="点对点匹配",
        description="仅使用最近顶点的位置，否则使用范围内的多个顶点的平均位置(若未找到任何点则会退化为点对点匹配)",
        default=True
    )  # type: ignore

    absolute_mode: BoolProperty(
        name="绝对位置模式",
        description="默认传递的是相对形态键,开启以后传递绝对位置,传递的形态键直接会贴合到源物体形态键的mesh上",
        default=False
    )  # type: ignore

    increment_radius: FloatProperty(
        name="rbf半径",
        description="在一对多模式中，搜索多个顶点的半径,建议开的比较小",
        default=0.05,
        soft_min=0.01,
        soft_max=1,
        min=0.00000001
    )  # type: ignore

    is_list_inversed: BoolProperty(
        name="反转名单",
        description="将名单作为白名单使用",
        default=False
    )  # type: ignore
    mode_items = [
        ('MOD_WORLD_POSITION', "坐标",
         """
         世界空间坐标
         视图中需要将物体贴的很近
         """),
        ('MOD_UV_POSITION', "UV",
         """
         UV坐标,适用于UV贴的很近
         使用活动UV层(UV层里面选择高亮的,也是UV编辑器里面显示的)
         不是激活渲染的UV层
         """),
        ('MOD_VERTEX_INDEX', "索引",
         """
         顶点的索引值
         适用于对网格进行了形变处理以后的无损传输
         """),
    ]
    mode: EnumProperty(name="传递模式", items=mode_items)  # type: ignore


class PG_transferListItem(PropertyGroup):
    # 列表的元素,只是为了存string，故使用.name即可，内容物占位无视(覆盖了.name)
    name: StringProperty()  # type: ignore


class UL_transferListItems(UIList):
    """黑/白名单"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        # split = layout.split(0.3)
        # split.label("Index: %d" % (index))
        # custom_icon = "OUTLINER_OB_%s" % item.obj_type
        # split.prop(item, "name", text="", emboss=False, translate=False, icon=custom_icon)
        # split.label(item.name, icon=custom_icon) # avoids renaming the item by accident
        layout.prop(item, "name", text="", emboss=False, icon_value=icon)

    def invoke(self, context, event):
        pass


class ShapeKeyTransfer:

    def __init__(self):

        self.src_object = None
        self.dest_object = None

        self.use_one_vertex = True
        self.increment_radius = 0.05  # RBF 半径
        self.mode = "MOD_WORLD_POSITION"

        self.only_selected_dest = False
        self.only_selected_src = False

        self.base_shape_keys = ['Basis', '基型']
        self.list_shape_keys = []
        self.is_list_inversed = False

        self.src_vertex_selected = []
        self.dest_vertex_selected = []

        self.src_world_kdtree = None
        self.src_uv_kdtree = None

        self.src_uv_avg = {}
        self.dest_uv_avg = {}

        # dest_idx -> [(src_idx, weight)]
        self.match_cache = {}

        self.message = ""

    # -------------------------------------------------
    # 选择缓存
    # -------------------------------------------------

    def save_vertex_selection(self, obj):

        current_obj = bpy.context.object
        current_mode = current_obj.mode if current_obj else 'OBJECT'

        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            return [v.select for v in bm.verts]
        finally:
            if current_obj:
                bpy.context.view_layer.objects.active = current_obj
                bpy.ops.object.mode_set(mode=current_mode)

    # -------------------------------------------------
    # KDTree 构建
    # -------------------------------------------------

    def build_world_kdtree(self):

        verts = self.src_object.data.shape_keys.key_blocks[0].data
        kd = KDTree(len(verts))

        for i, v in enumerate(verts):

            if self.only_selected_src and not self.src_vertex_selected[i]:
                continue

            world_co = self.src_object.matrix_world @ v.co
            kd.insert(world_co, i)

        kd.balance()
        self.src_world_kdtree = kd

    def calculate_avg_uv(self, obj):

        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            bm.free()
            raise ValueError(f"{obj.name} 没有 UV")

        uv_data = defaultdict(lambda: [0.0, 0.0, 0])

        for face in bm.faces:
            for loop in face.loops:
                idx = loop.vert.index
                uv = loop[uv_layer].uv
                uv_data[idx][0] += uv.x
                uv_data[idx][1] += uv.y
                uv_data[idx][2] += 1

        avg = {
            idx: Vector((d[0]/d[2], d[1]/d[2]))
            for idx, d in uv_data.items()
        }

        bm.free()
        return avg

    def build_uv_kdtree(self):

        kd = KDTree(len(self.src_uv_avg))

        for idx, uv in self.src_uv_avg.items():

            if self.only_selected_src and not self.src_vertex_selected[idx]:
                continue

            kd.insert((uv.x, uv.y, 0.0), idx)

        kd.balance()
        self.src_uv_kdtree = kd

    # -------------------------------------------------
    # RBF 权重计算（高斯核）
    # -------------------------------------------------

    def rbf_weights(self, distances, radius):

        weights = []

        for d in distances:
            if d > radius:
                weights.append(0.0)
            else:
                w = math.exp(-(d * d) / (radius * radius))
                weights.append(w)

        total = sum(weights)

        if total == 0:
            return None

        return [w / total for w in weights]

    # -------------------------------------------------
    # 构建匹配缓存（只执行一次）
    # -------------------------------------------------

    def build_match_cache(self):

        self.match_cache = {}

        total = len(self.dest_object.data.vertices)

        for dest_idx in range(total):

            if self.only_selected_dest and not self.dest_vertex_selected[dest_idx]:
                continue

            # ================= WORLD =================
            if self.mode == "MOD_WORLD_POSITION":

                dest_world = (
                    self.dest_object.matrix_world @
                    self.dest_object.data.shape_keys.key_blocks[0]
                    .data[dest_idx].co
                )

                co, index, dist = self.src_world_kdtree.find(dest_world)

                if self.use_one_vertex:
                    self.match_cache[dest_idx] = [(index, 1.0)]
                else:
                    results = self.src_world_kdtree.find_range(
                        dest_world,
                        self.increment_radius
                    )

                    if not results:
                        self.match_cache[dest_idx] = [(index, 1.0)]
                    else:
                        distances = [r[2] for r in results]
                        indices = [r[1] for r in results]

                        weights = self.rbf_weights(distances, self.increment_radius)

                        if not weights:
                            self.match_cache[dest_idx] = [(index, 1.0)]
                        else:
                            self.match_cache[dest_idx] = list(zip(indices, weights))

            # ================= UV =================
            elif self.mode == "MOD_UV_POSITION":

                uv = self.dest_uv_avg.get(dest_idx)
                if uv is None:
                    continue

                center = (uv.x, uv.y, 0.0)

                co, index, dist = self.src_uv_kdtree.find(center)

                if self.use_one_vertex:
                    self.match_cache[dest_idx] = [(index, 1.0)]
                else:
                    results = self.src_uv_kdtree.find_range(
                        center,
                        self.increment_radius
                    )

                    if not results:
                        self.match_cache[dest_idx] = [(index, 1.0)]
                    else:
                        distances = [r[2] for r in results]
                        indices = [r[1] for r in results]

                        weights = self.rbf_weights(distances, self.increment_radius)

                        if not weights:
                            self.match_cache[dest_idx] = [(index, 1.0)]
                        else:
                            self.match_cache[dest_idx] = list(zip(indices, weights))

            # ================= INDEX =================
            else:
                if self.only_selected_src:
                    if not self.src_vertex_selected[dest_idx]:
                        continue

                self.match_cache[dest_idx] = [(dest_idx, 1.0)]

    # -------------------------------------------------
    # 主传递逻辑
    # -------------------------------------------------

    def transfer_shape_keys(self, src, dest):

        self.src_object = src
        self.dest_object = dest

        if self.only_selected_src:
            self.src_vertex_selected = self.save_vertex_selection(src)

        if self.only_selected_dest:
            self.dest_vertex_selected = self.save_vertex_selection(dest)

        if self.mode == "MOD_WORLD_POSITION":
            self.build_world_kdtree()

        elif self.mode == "MOD_UV_POSITION":
            self.src_uv_avg = self.calculate_avg_uv(src)
            self.dest_uv_avg = self.calculate_avg_uv(dest)
            self.build_uv_kdtree()

        if not dest.data.shape_keys:
            dest.shape_key_add(name="Basis")

        # 构建工作 key 列表
        work_keys = []

        if not src.data.shape_keys:
            self.message = "源物体没有形态键"
            return True

        for sk in src.data.shape_keys.key_blocks:

            name = sk.name

            # 跳过 Basis
            if name in self.base_shape_keys:
                continue

            # ===== 黑白名单判断 =====
            if self.list_shape_keys:
                if self.is_list_inversed:
                    # 白名单
                    if name not in self.list_shape_keys:
                        continue
                else:
                    # 黑名单
                    if name in self.list_shape_keys:
                        continue

            # ===== 真正通过过滤 =====
            work_keys.append(name)

            # 只为需要传递的 key 创建目标 key
            if not any(name == dsk.name
                    for dsk in dest.data.shape_keys.key_blocks):
                dest.shape_key_add(name=name)

        # ⚡ 只算一次匹配
        self.build_match_cache()

        props = bpy.context.scene.shapekeytransfer

        # 批量写入
        for key_name in work_keys:

            src_basis = src.data.shape_keys.key_blocks[0]
            src_key = src.data.shape_keys.key_blocks[key_name]
            dest_key = dest.data.shape_keys.key_blocks[key_name]
            dest_basis = dest.data.shape_keys.key_blocks[0]

            for dest_idx, src_list in self.match_cache.items():

                result_basis = Vector()
                result_key = Vector()

                for sidx, weight in src_list:
                    result_basis += src_basis.data[sidx].co * weight
                    result_key += src_key.data[sidx].co * weight

                if props.absolute_mode:
                    final = result_key
                else:
                    dest_base = dest_basis.data[dest_idx].co
                    final = result_key - result_basis + dest_base

                dest_key.data[dest_idx].co = final

        self.message = "形态键传递成功（RBF 高性能模式）"
        return False

SKT = ShapeKeyTransfer()


def reg_props():
    bpy.types.Scene.shapekeytransfer_list_index = IntProperty()  # 传递自定义名单绑定的活动计数
    bpy.types.Scene.shapekeytransfer = PointerProperty(
        type=PG_transferSettings)  # 传递功能的属性组
    bpy.types.Scene.customshapekeylist = CollectionProperty(
        type=PG_transferListItem)  # 传递自定义名单绑定的内容
    return


def ureg_props():
    del bpy.types.Scene.shapekeytransfer
    del bpy.types.Scene.customshapekeylist
    del bpy.types.Scene.shapekeytransfer_list_index
    return
# endregion

# region 操作


class OP_copyKeyNames(Operator):
    """将所有形状键名称复制到剪贴板"""
    bl_idname = "ho.copy_key_names"
    bl_label = "复制名称"
    bl_description = "从物体复制形态键到剪贴板,跳过基型"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global SKT
        skt = context.scene.shapekeytransfer
        if not skt.src_object:
            self.report({'INFO'}, "没有找到数据")
            return {'FINISHED'}
        if skt.src_object.data:
            if SKT.get_shape_keys_mesh(obj=skt.src_object):
                self.report({'INFO'}, SKT.message)
            else:
                keys = SKT.message
                temp_str = ""
                shape_keys = skt.src_object.data.shape_keys.key_blocks
                for key in shape_keys:
                    if key == shape_keys[0]:  # 跳过基型（第一个形态键）
                        continue
                    temp_str += key.name + "\n"
                context.window_manager.clipboard = temp_str
                self.report({'INFO'}, "已复制到剪贴板")
        else:
            self.report({'INFO'}, "源网格无效")
        return {'FINISHED'}


class OP_insertKeyNames(Operator):
    """从剪贴板粘贴所有形态键名称"""
    bl_idname = "ho.insert_key_names"
    bl_label = "粘贴名称"
    bl_description = "从剪贴板插入形状键名称（每行为一个形态键）"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    def execute(self, context):
        scn = context.scene
        for key in context.window_manager.clipboard.split("\n"):
            if (len(key)):
                item = scn.customshapekeylist.add()
                item.name = key
                scn.shapekeytransfer_list_index = len(scn.customshapekeylist)-1
        self.report({'INFO'}, "从剪贴板添加形态键名称")
        return {'FINISHED'}


class OP_transferShapeKeys(Operator):
    """将形态键传递到选定的网格"""
    bl_idname = "ho.transfer_shape_keys"
    bl_label = "传递形态键"
    bl_description = "位置传递需要世界空间下贴的近,UV模式/索引模式不需要"
    bl_context = 'objectmode'
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        global SKT
        skt = context.scene.shapekeytransfer
        SKT.increment_radius = skt.increment_radius
        SKT.use_one_vertex = skt.use_one_vertex
        SKT.is_list_inversed = skt.is_list_inversed
        SKT.mode = skt.mode
        SKT.only_selected_dest = skt.only_selected_dest
        SKT.only_selected_src = skt.only_selected_src

        SKT.work_shape_keys = []
        SKT.list_shape_keys = [
            key.name for key in context.scene.customshapekeylist]

        result = SKT.transfer_shape_keys(skt.src_object, skt.dest_object)
        if (result):
            self.report({'ERROR'}, SKT.message)
        else:
            self.report({'INFO'}, SKT.message)
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        skt = context.scene.shapekeytransfer
        col = layout.column()
        col.label(text="顶点判定:")
        col.prop(skt, "increment_radius")
        col.prop(skt, "use_one_vertex")


class OP_removeShapeKeys(Operator):
    """删除指定对象的所有形状键"""
    bl_idname = "ho.remove_src_shape_keys"
    bl_label = "删除形态键"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    target_object: bpy.props.StringProperty(
        name="Target Object",
        description="名称为指定对象的名称",
        default=""
    )  # type: ignore

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = bpy.data.objects.get(self.target_object)

        if not obj:
            self.report({'ERROR'}, f"对象 {self.target_object} 不存在。")
            return {'CANCELLED'}

        if (obj.data.shape_keys):
            x: bpy.types.ShapeKey
            for x in obj.data.shape_keys.key_blocks:
                if x == obj.data.shape_keys.reference_key:
                    continue
                obj.shape_key_remove(x)
            obj.shape_key_remove(obj.data.shape_keys.reference_key)

        return {'FINISHED'}


class OP_transferListActions(Operator):
    """对列表元素进行移动增删"""
    bl_idname = "ho.transferlist_action"
    bl_label = "List Actions"
    bl_description = "移动增删列表元素"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    action: EnumProperty(
        items=(
            ('UP', "Up", ""),
            ('DOWN', "Down", ""),
            ('REMOVE', "Remove", ""),
            ('ADD', "Add", "")
        ))  # type: ignore

    def invoke(self, context, event):
        scn = context.scene
        idx = scn.shapekeytransfer_list_index

        try:
            item = scn.customshapekeylist[idx]
        except IndexError:
            pass
        else:
            if self.action == 'DOWN' and idx < len(scn.customshapekeylist) - 1:
                item_next = scn.customshapekeylist[idx+1].name
                scn.customshapekeylist.move(idx, idx+1)
                scn.shapekeytransfer_list_index += 1

            elif self.action == 'UP' and idx >= 1:
                item_prev = scn.customshapekeylist[idx-1].name
                scn.customshapekeylist.move(idx, idx-1)
                scn.shapekeytransfer_list_index -= 1

            elif self.action == 'REMOVE':
                scn.shapekeytransfer_list_index -= 1
                scn.customshapekeylist.remove(idx)

        if self.action == 'ADD':
            scn = context.scene
            item = scn.customshapekeylist.add()
            item.name = "key"
            scn.shapekeytransfer_list_index = len(scn.customshapekeylist)-1

        return {"FINISHED"}


class OP_clearList(Operator):
    """删除列表全部元素"""
    bl_idname = "ho.transferlist_clear_list"
    bl_label = "清空列表"
    bl_description = "删除列表全部元素"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.customshapekeylist)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if bool(context.scene.customshapekeylist):
            context.scene.customshapekeylist.clear()
        else:
            self.report({'INFO'}, "Nothing to remove")
        return {'FINISHED'}


class OP_removeShapeKeysByList(Operator):
    """根据名单删除活动物体的形态键"""
    bl_idname = "ho.transferlist_remove_shapekey"
    bl_label = "名单规则删除物体形态键"
    bl_description = "根据名单删除活动物体的形态键,不会移除基型"
    bl_options = {'REGISTER', 'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not bool(context.scene.customshapekeylist):
            return False
        obj: bpy.types.Object = context.active_object
        if not obj:
            return False
        if not obj.data.shape_keys:
            return False
        return True

    def execute(self, context):
        obj = context.active_object
        keys = obj.data.shape_keys.key_blocks
        props = context.scene.shapekeytransfer
        keylist = context.scene.customshapekeylist
        # 遍历活动物体的形态键
        for key in keys:
            name = key.name
            if props.is_list_inversed:  # 白名单模式
                if name in keylist:  # 在列表的就加进work列表
                    obj.shape_key_remove(keys[name])
                else:
                    continue
            else:  # 黑名单模式
                if name not in keylist:
                    if name == obj.data.shape_keys.reference_key.name:
                        continue
                    obj.shape_key_remove(keys[name])
                else:
                    continue
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
# endregion

# region 面板


def drawShapekeyTransferPanel(layout: UILayout, context: Context):
    layout.use_property_decorate = False  # No animation.
    scn = context.scene
    global SKT
    skt: ShapeKeyTransfer = scn.shapekeytransfer
    # 物体选择
    col = layout.column(align=True)
    row1 = col.row(align=True)
    if skt.src_object:
        op = row1.operator(OP_removeShapeKeys.bl_idname, text="",
                           icon='CANCEL')
        op.target_object = skt.src_object.name
    row1.prop(skt, "only_selected_src", text="",
              icon="RESTRICT_SELECT_OFF", toggle=True)  # 仅选中
    row1.prop(skt, "src_object", text="源物体")

    row2 = col.row(align=True)
    if skt.dest_object:
        op = row2.operator(OP_removeShapeKeys.bl_idname, text="",
                           icon='CANCEL')
        op.target_object = skt.dest_object.name
    row2.prop(skt, "only_selected_dest", text="",
              icon="RESTRICT_SELECT_OFF", toggle=True)  # 仅选中
    row2.prop(skt, "dest_object", text="目标物体")

    # 参数指定
    layout.separator()
    row = layout.row(align=True)
    row.prop(skt, "increment_radius", slider=True)
    row = layout.row(align=True)
    # 主功能
    row = layout.row(align=True)
    row.scale_y = 2.0
    row1 = row.row()
    row1.scale_x = 0.6
    row1.prop(skt, "mode", text="")
    row.prop(skt, "use_one_vertex", text="", icon="CON_TRACKTO", toggle=True)
    row.prop(skt, "absolute_mode", text="", icon="RESTRICT_INSTANCED_OFF", toggle=True)

    row.operator(OP_transferShapeKeys.bl_idname,
                 icon='ARROW_LEFTRIGHT', text="传递形态键")

    # 名单
    if (skt.is_list_inversed):
        layout.label(text="白名单")
    else:
        layout.label(text="黑名单")
    row = layout.row()
    row.template_list(UL_transferListItems.__name__, "", scn, "customshapekeylist",
                      scn, "shapekeytransfer_list_index", rows=9)

    col = row.column(align=True)
    col.prop(skt, "is_list_inversed", text="", icon_only=True,
             icon="UV_SYNC_SELECT", toggle=True)  # 反转列表
    col.operator(OP_transferListActions.bl_idname,
                 icon='ADD', text="").action = 'ADD'  # 添加
    col.operator(OP_transferListActions.bl_idname, icon='REMOVE',
                 text="").action = 'REMOVE'  # 移除
    col.operator(OP_clearList.bl_idname, icon="X", text="")  # 清空
    col.operator(OP_removeShapeKeysByList.bl_idname,
                 icon="GHOST_ENABLED", text="")  # 按照名单删除活动物体的形态键

    col.separator()
    col.operator(OP_transferListActions.bl_idname,
                 icon='TRIA_UP', text="").action = 'UP'  # 上移
    col.operator(OP_transferListActions.bl_idname,
                 icon='TRIA_DOWN', text="").action = 'DOWN'  # 下移
    col.separator()
    col.operator(OP_copyKeyNames.bl_idname,
                 icon="COPYDOWN", text="")  # 从物体提取形态键
    col.operator(OP_insertKeyNames.bl_idname,
                 icon="PASTEDOWN", text="")  # 从剪切板粘贴
# endregion


cls = (
    PG_transferSettings, PG_transferListItem,
    UL_transferListItems,
    OP_copyKeyNames, OP_insertKeyNames,
    OP_transferShapeKeys,
    OP_removeShapeKeys,
    OP_transferListActions,
    OP_clearList, OP_removeShapeKeysByList,
)


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
