import bpy
import bmesh
from bpy.types import Panel
import bmesh
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector
from collections import defaultdict
from bpy.app.handlers import persistent
from .stack import OP_UVTools_TopologyStack
from .unstack import OP_UVTools_Unstack
from .seams import OP_UVTools_SeamsFromIslands
from .length import OP_UVTools_UniformizeLength
from .transform import TRANSFORM_CLASSES, OP_UVTools_Mirror, OP_UVTools_MirrorInTile, OP_UVTools_Translate
from .straighten import STRAIGHTEN_CLASSES, OP_UVTools_LineUnwrap, OP_UVTools_StraightenIsland
from Utils.mesh_uv import selected_uv_point_groups, uv_edit_poll, write_uv_points
from Utils.uv_math import fit_points_to_tile

UV_LISTENER_CACHE = {
    "active_uv": None,
    "render_uv": None,
}
AUTO_CREATE_UV = False# 是否自动创建缺失UV
DEBUG = False# 调试输出
# =========================================================
# 监听器
# =========================================================
def uv_layer_listener(scene):
    global UV_LISTENER_CACHE

    context = bpy.context
    active_obj = context.object

    # ---------- 基础过滤 ----------
    if not active_obj or active_obj.type != 'MESH':
        return

    if len(context.selected_objects) < 2:
        return

    uv_layers = active_obj.data.uv_layers
    if not uv_layers:
        return

    # ---------- 获取当前状态 ----------
    active_uv = uv_layers.active.name if uv_layers.active else None

    render_uv = None
    for uv in uv_layers:
        if uv.active_render:
            render_uv = uv.name
            break

    # ---------- 缓存判断 ----------
    if (UV_LISTENER_CACHE["active_uv"] == active_uv and
        UV_LISTENER_CACHE["render_uv"] == render_uv):
        return

    # ---------- 更新缓存 ----------
    UV_LISTENER_CACHE["active_uv"] = active_uv
    UV_LISTENER_CACHE["render_uv"] = render_uv

    if DEBUG:
        print(f"[UV Sync] Active: {active_uv}, Render: {render_uv}")

    # =====================================================
    # 执行同步
    # =====================================================
    for obj in context.selected_objects:

        if obj == active_obj:
            continue

        if obj.type != 'MESH':
            continue

        obj_uvs = obj.data.uv_layers
        if not obj_uvs:
            continue

        # ---------- 同步 Active UV ----------
        if active_uv:
            uv = obj_uvs.get(active_uv)

            if not uv and AUTO_CREATE_UV:
                uv = obj_uvs.new(name=active_uv)
                if DEBUG:
                    print(f"[UV Sync] Created UV '{active_uv}' on {obj.name}")

            if uv:
                obj_uvs.active = uv
            else:
                if DEBUG:
                    print(f"[UV Sync] Missing Active UV '{active_uv}' on {obj.name}")

        # ---------- 同步 Render UV ----------
        if render_uv:
            uv = obj_uvs.get(render_uv)

            if not uv and AUTO_CREATE_UV:
                uv = obj_uvs.new(name=render_uv)
                if DEBUG:
                    print(f"[UV Sync] Created Render UV '{render_uv}' on {obj.name}")

            if uv:
                # 清空旧的 render 标记
                for u in obj_uvs:
                    u.active_render = False

                uv.active_render = True
            else:
                if DEBUG:
                    print(f"[UV Sync] Missing Render UV '{render_uv}' on {obj.name}")

# =========================================================
# 开关控制
# =========================================================
def update_uv_listener_switch(self, context):
    enabled = context.scene.hoUVTools_control_uv_listener
    if enabled:
        if uv_layer_listener not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(uv_layer_listener)
            print("UV监听器已启用")
    else:
        if uv_layer_listener in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(uv_layer_listener)
            print("UV监听器已禁用")


# =========================================================
# 文件加载处理器
# =========================================================
@persistent
def uv_load_handler(dummy):
    """Re-register UV listener when file is loaded"""
    for scene in bpy.data.scenes:
        if hasattr(scene, 'hoUVTools_control_uv_listener') and scene.hoUVTools_control_uv_listener:
            if uv_layer_listener not in bpy.app.handlers.depsgraph_update_post:
                bpy.app.handlers.depsgraph_update_post.append(uv_layer_listener)
            break


def reg_props():
    bpy.types.Scene.hoUVTools_control_uv_listener = bpy.props.BoolProperty(
        name="开启UV多物体同步",
        description="""
        启用后监听活动物体的UV层变化：
        - 同步 Active UV
        - 同步 Render UV
        - 自动跳过无变化
        - 支持自动创建UV（可配置，默认关闭）
        - 多物体实时同步
        """,
        default=False,
        update=update_uv_listener_switch
    )
    bpy.app.handlers.load_post.append(uv_load_handler)
    return

def ureg_props():
    if uv_layer_listener in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(uv_layer_listener)
    del bpy.types.Scene.hoUVTools_control_uv_listener
    if uv_load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(uv_load_handler)
    return

class OP_UVTools_ReplaceFromLayer(Operator):
    bl_idname = "ho.uvtools_replacefromlayer"
    bl_label = "UV从层替换"
    bl_description = "类似从形态键混合,所选的顶点的UV,使用其他UV层的UV替换"
    bl_options = {'REGISTER', 'UNDO'}

    layer_name: StringProperty(
        name="使用UV层",
        default=""
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and obj.mode == 'EDIT'

    def draw(self, context):
        layout = self.layout
        layout.prop_search(
            self, "layer_name",
            context.object.data, "uv_layers",
            text="源UV层"
        )

    def invoke(self, context, event):
        # 自动设置默认源UV层为第一个非活动层
        uv_layers = context.object.data.uv_layers
        if uv_layers and len(uv_layers) > 1:
            active_uv = uv_layers.active
            for uv in uv_layers:
                if uv != active_uv:
                    self.layer_name = uv.name
                    break
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        if not context.scene.tool_settings.use_uv_select_sync:
            self.report({'ERROR'}, "操作需要开启UV同步模式")
            return {'CANCELLED'}

        obj = context.active_object
        mesh = obj.data

        # 验证源UV层
        if not self.layer_name or self.layer_name not in mesh.uv_layers:
            self.report({'ERROR'}, "无效的UV层名称")
            return {'CANCELLED'}

        # 获取bmesh数据
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()  # 刷新索引表
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table() 
        uv_layers = bm.loops.layers.uv

        # 获取源层和目标层
        src_layer = uv_layers.get(self.layer_name)
        dst_layer = uv_layers.active

        if not src_layer or not dst_layer:
            self.report({'ERROR'}, "找不到UV层")
            return {'CANCELLED'}

        # 遍历所有面的循环
        updated = False
        for face in bm.faces:
            if not face.select:
                continue

            for loop in face.loops:
                # 仅处理选中顶点的循环
                if loop.vert.select:
                    # 复制UV坐标
                    loop[dst_layer].uv = loop[src_layer].uv
                    updated = True

        if updated:
            # 更新网格数据
            bmesh.update_edit_mesh(mesh)
            self.report({'INFO'}, f"已从 '{self.layer_name}' 更新UV")
        else:
            self.report({'WARNING'}, "没有选中的顶点需要更新")

        return {'FINISHED'}

class OP_UVTools_MoveActiveUV(Operator):
    """移动活动UV层顺序"""
    bl_idname = "ho.uvtools_move_active_uv"
    bl_label = "移动活动UV层"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(
        name="方向",
        items=[
            ('UP', "上移", ""),
            ('DOWN', "下移", "")
        ],
        default='UP'
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH' and len(obj.data.uv_layers) > 1

    def execute(self, context):
        obj = context.active_object
        current_mode = bpy.context.mode
        switched = False

        # 如果在编辑模式，就暂时切换到物体模式
        if current_mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            switched = True

        # 执行 UV 层移动
        self.move_active_uv_layer(obj, self.direction)

        # 如果之前在编辑模式，执行完再切回去
        if switched:
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}

    def move_active_uv_layer(self,obj, direction='UP'):
        """交换两个UV层的数据、名称.并更新active_index"""
        uv_layers = obj.data.uv_layers
        count = len(uv_layers)
        if count < 2:
            return

        active_index = uv_layers.active_index

        if direction == 'UP':
            target_index = active_index - 1
            if target_index < 0:return
        elif direction == 'DOWN':
            target_index = active_index + 1
            if target_index >= count:return
        else:return

        uv1 = uv_layers[active_index]
        uv2 = uv_layers[target_index]

        # --- 1. 交换 UV 数据 ---
        data1 = [loop.uv.copy() for loop in uv1.data]
        data2 = [loop.uv.copy() for loop in uv2.data]
        for i in range(len(data1)):
            uv1.data[i].uv = data2[i]
            uv2.data[i].uv = data1[i]
        # --- 2. 安全交换名称（防止重名导致.001） ---
        name1 = uv1.name
        name2 = uv2.name
        temp_name = "__TEMP_UV_NAME__"
        # 确保缓存名不与现有层重名
        while temp_name in [layer.name for layer in uv_layers]:
            temp_name += "_"
        uv1.name = temp_name       # 先腾出 name1
        uv2.name = name1           # 把 name1 给 uv2
        uv1.name = name2           # 把 name2 给 uv1
        # --- 3. 交换渲染层状态 ---
        uv1_render = uv1.active_render
        uv2_render = uv2.active_render
        uv1.active_render = uv2_render
        uv2.active_render = uv1_render
        # --- 4. 更新活动层索引 ---
        uv_layers.active_index = target_index




class OP_UVTools_FitToFirstQuadrant(Operator):
    bl_idname = "ho.uvtools_fit_to_first_quadrant"
    bl_label = "选中UV适配到第一象限"
    bl_description = "将所选UV整体AABB中心移到(0.5, 0.5)，保持比例并尽量填满0~1第一象限；支持UV同步模式"
    bl_options = {'REGISTER', 'UNDO'}

    margin: FloatProperty(
        name="边距", description="第一象限四边留白的UV距离；默认无边距，按最长边尽量填满",
        default=0.0, min=0.0, max=0.499, soft_max=0.1,
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        return uv_edit_poll(context)

    def execute(self, context):

        try:
            points = selected_uv_point_groups(context)[0]
            result = fit_points_to_tile([point.coordinate for point in points], margin=self.margin)
            write_uv_points(zip(points, result))
        except (ValueError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}

class OP_UVTools_UV2SK(Operator):
    bl_idname = "ho.uvtools_uv2sk"
    bl_label = "UV转形态键"
    bl_description = "将当前UV层的顶点坐标转换为形态键"
    bl_options = {'REGISTER', 'UNDO'}

    plane: EnumProperty(
        name="投影平面",
        description="选择UV写入的目标平面",
        items=[
            ('XY', "XY 平面", "U→X, V→Y"),
            ('XZ', "XZ 平面", "U→X, V→Z"),
        ],
        default='XY'
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj and obj.type == 'MESH'
    
    # 让操作执行前弹出设置面板
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    # 绘制UI
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "plane", expand=True)


    def execute(self, context):
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "请先选择一个网格物体作为活动物体")
            return {'CANCELLED'}

        mesh = obj.data

        uv_layer = mesh.uv_layers.active
        if not uv_layer:
            self.report({'WARNING'}, "活动物体没有UV层")
            return {'CANCELLED'}

        # 如果没有 shape key，先创建 Basis
        if obj.data.shape_keys is None:
            obj.shape_key_add(name="Basis")

        # 创建新的 shape key
        new_key = obj.shape_key_add(name=f"UV_{uv_layer.name}", from_mix=False)

        # --- 计算每个顶点对应的UV（取平均值） ---
        vert_uv_sum = defaultdict(lambda: [0.0, 0.0])
        vert_uv_count = defaultdict(int)

        for loop in mesh.loops:
            vert_index = loop.vertex_index
            uv = uv_layer.data[loop.index].uv
            vert_uv_sum[vert_index][0] += uv.x
            vert_uv_sum[vert_index][1] += uv.y
            vert_uv_count[vert_index] += 1

        # --- 写入 Shape Key ---
        for v in mesh.vertices:
            idx = v.index

            if vert_uv_count[idx] == 0:
                continue

            avg_u = vert_uv_sum[idx][0] / vert_uv_count[idx]
            avg_v = vert_uv_sum[idx][1] / vert_uv_count[idx]

            co = new_key.data[idx].co

            if self.plane == 'XY':
                co.x = avg_u
                co.y = avg_v
                co.z = 0.0
            elif self.plane == 'XZ':
                co.x = avg_u
                co.y = 0.0
                co.z = avg_v

        self.report({'INFO'}, "已根据活动UV层生成形态键")

        return {'FINISHED'}


def draw_in_DATA_PT_uv_texture(self,context: bpy.types.Context):
    """UV贴图属性下"""
    layout: bpy.types.UILayout = self.layout

    row = layout.row(align=True)

    row1 = row.row(align=True)
    row1.alignment = 'LEFT'
    row1.operator(OP_UVTools_MoveActiveUV.bl_idname,text="",icon="TRIA_UP").direction = 'UP'
    row1.operator(OP_UVTools_MoveActiveUV.bl_idname,text="",icon="TRIA_DOWN").direction = 'DOWN'
    row1.operator(OP_UVTools_UV2SK.bl_idname,text="",icon="SHAPEKEY_DATA")
    row1.operator(OP_UVTools_ReplaceFromLayer.bl_idname,text="",icon="TRANSFORM_ORIGINS")
    row1.operator(OP_UVTools_SeamsFromIslands.bl_idname,text="",icon="EDGESEL")

    row2 = row.row(align=True)
    row2.alignment= 'RIGHT'
    row2.prop(context.scene,"hoUVTools_control_uv_listener",text="",toggle=True,icon="UV_SYNC_SELECT")

    

class IMAGE_MT_uvs_context_hotools(Menu):
    """UV编辑器右键时的菜单追加"""
    bl_label = "Hotools"

    def draw(self, context):
        layout = self.layout
        layout.operator(OP_UVTools_FitToFirstQuadrant.bl_idname, text="适配到象限", icon="GESTURE_ZOOM")
        layout.operator(OP_UVTools_TopologyStack.bl_idname, text="拓扑堆栈", icon="AREA_JOIN_DOWN")
        layout.operator(OP_UVTools_Unstack.bl_idname, text="取消堆栈", icon="MOD_ARRAY")
        layout.operator(OP_UVTools_LineUnwrap.bl_idname, text="线展开",icon="MOD_TINT")
        layout.operator(OP_UVTools_UniformizeLength.bl_idname, text="长度均化", icon="ALIGN_JUSTIFY")
        layout.operator(OP_UVTools_StraightenIsland.bl_idname, text="直化岛",icon="VIEW_ORTHO")
        layout.operator(OP_UVTools_SeamsFromIslands.bl_idname, text="UV边界缝合边", icon="EDGESEL")
        layout.operator(OP_UVTools_MirrorInTile.bl_idname, text="翻转",icon="MOD_MIRROR")
        layout.operator(OP_UVTools_Mirror.bl_idname, text="镜像",icon="ARROW_LEFTRIGHT")
        layout.operator(OP_UVTools_Translate.bl_idname, text="平移",icon="TRIA_RIGHT")

def draw_in_IMAGE_MT_uvs_context_menu(self,context: bpy.types.Context):
    """UV编辑器右键菜单"""
    self.layout.menu("IMAGE_MT_uvs_context_hotools") 



cls = [OP_UVTools_ReplaceFromLayer,OP_UVTools_MoveActiveUV,
       IMAGE_MT_uvs_context_hotools,OP_UVTools_FitToFirstQuadrant,
       OP_UVTools_UV2SK,OP_UVTools_TopologyStack,OP_UVTools_Unstack,OP_UVTools_SeamsFromIslands,
       OP_UVTools_UniformizeLength,*TRANSFORM_CLASSES,*STRAIGHTEN_CLASSES]



def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.DATA_PT_uv_texture.append(draw_in_DATA_PT_uv_texture)
    bpy.types.IMAGE_MT_uvs_context_menu.append(draw_in_IMAGE_MT_uvs_context_menu)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.DATA_PT_uv_texture.remove(draw_in_DATA_PT_uv_texture)
    bpy.types.IMAGE_MT_uvs_context_menu.remove(draw_in_IMAGE_MT_uvs_context_menu)

    ureg_props()
