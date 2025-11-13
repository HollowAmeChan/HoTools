import bpy
import bmesh
from bpy.types import Panel
import bmesh
from bpy.types import Operator,Panel,Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper


def reg_props():
    return

def ureg_props():
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







def draw_in_DATA_PT_uv_texture(self,context: bpy.types.Context):
    """UV贴图属性下"""
    layout: bpy.types.UILayout = self.layout

    row = layout.row(align=True)
    row.operator(OP_UVTools_MoveActiveUV.bl_idname,text="",icon="TRIA_UP").direction = 'UP'
    row.operator(OP_UVTools_MoveActiveUV.bl_idname,text="",icon="TRIA_DOWN").direction = 'DOWN'


    layout.operator(OP_UVTools_ReplaceFromLayer.bl_idname)
    



cls = [OP_UVTools_ReplaceFromLayer,OP_UVTools_MoveActiveUV]



def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.DATA_PT_uv_texture.append(draw_in_DATA_PT_uv_texture)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.DATA_PT_uv_texture.remove(draw_in_DATA_PT_uv_texture)
    ureg_props()
