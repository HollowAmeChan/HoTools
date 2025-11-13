import bpy
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy.types import UILayout, Context
from bpy.types import Mesh, Object
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty
from mathutils import Vector
import bmesh
from collections import defaultdict

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
        description="仅使用最近顶点的位置，否则使用范围内的多个顶点(第一次发现有顶点匹配成功时的全部匹配顶点)的平均位置",
        default=True
    )  # type: ignore

    absolute_mode: BoolProperty(
        name="绝对位置模式",
        description="默认传递的是相对形态键，开启以后传递绝对位置，传递的形态键直接会贴合到源物体形态键的mesh上",
        default=False
    )  # type: ignore

    increment_radius: FloatProperty(
        name="增量半径",
        description="在没有搜索到配对顶点时，额外的判定顶点配对的球形半径，如果匹配到的顶点太多，可以缩小这个值",
        default=0.05,
        soft_min=0.01,
        soft_max=1,
        min=0.00000001
    )  # type: ignore

    number_of_increments: IntProperty(
        name="搜索次数",
        description="增加半径搜索顶点的最大次数,半径乘以次数为1时可以全包裹,UV在界外时这个积可以更大",
        default=20,
        soft_min=1,
        soft_max=50,
        min=1
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
    """
    构造传递形态键操作的类(仅限一个形态键到另一个形态键)
    这个类的作用是存一些不能用Bl数值类型存储的数据结构,以及将用到的函数封装好
    为什么要再存一份数据(PropertyGroup,Int)在scene里面,是为了方便改动这些数值(UI,ops里面改)
    在使用实例的时候,先将Bl内置类型数据拷贝进来再操作
    """

    def __init__(self):
        self.dest_object = None
        self.src_object = None
        self.use_one_vertex = True
        self.increment_radius = .05
        self.number_of_increments = 20
        self.is_list_inversed = False
        self.mode = ""
        self.only_selected_dest = False
        self.only_selected_src = False
        self.list_shape_keys = []  # 名单内的列表,需要传递进来

        # 需要用到的缓存
        self.work_shape_keys = []  # 需要传递的列表,内部生成
        self.base_shape_keys = ['Basis', '基型']  # 默认参数，默认忽略的列表
        self.src_mwi = None
        self.src_uv_avglayer = {}  # 所有顶点的平均UV字典
        self.dest_uv_avglayer = {}  # 所有顶点的平均UV字典
        self.src_vertex_isSeleted: list[bool] = []  # 所有顶点是否被选中
        self.dest_vertex_isSeleted: list[bool] = []  # 所有顶点是否被选中

        self.dest_shape_key_index = 0  # 目标网格形态键的索引
        self.src_shape_key_index = 0  # 源网格形态键的索引
        self.current_vertex_index = 0  # 正在处理的dest_object的网格的顶点序号
        self.current_vertex = None  # 当前处理的顶点对象
        self.total_vertices = 0  # 目标网格的总顶点数
        self.do_once_per_vertex = False  # 是否是第一次处理顶点(遍历顶点，所以此值可以重复使用)
        self.src_chosen_vertices = []  # 匹配到的源网络的顶点索引列表(按距离搜索到的顶点可能不止一个)
        self.message = ""  # 需要汇报的信息(本次形态键->形态键传递过程中的情况)

    # 功能函数
    def set_vertex_position(self, v_pos):
        """在形状键上设置新的顶点位置（并非偏移量）"""
        self.dest_object.data.shape_keys.key_blocks[
            self.dest_shape_key_index].data[self.current_vertex_index].co = v_pos

    def update_global_shapekey_indices(self, p_key_name):
        """储存临时工作形态键索引"""
        for index, sk in enumerate(self.dest_object.data.shape_keys.key_blocks):
            if sk.name == p_key_name:
                self.dest_shape_key_index = index
        for index, sk in enumerate(self.src_object.data.shape_keys.key_blocks):
            if sk.name == p_key_name:
                self.src_shape_key_index = index

    def get_shape_keys_mesh(self, obj: Object):
        """获取网格的形态键"""
        keys = []
        if (not hasattr(obj.data.shape_keys, "key_blocks")):
            self.message = "网格中没有形态键！"
            return True
        for shape_key_iter in obj.data.shape_keys.key_blocks:
            keys.append(shape_key_iter.name)
        self.message = keys
        return False

    def save_vertex_isSelected(self, obj: Object):
        """根据物体名称选中物体，进入编辑模式，并保存顶点选择状态。
        返回:list[bool]: 顶点选择状态的列表。如果物体不存在或不是网格对象，返回 None。"""

        # 保存当前活动物体和模式
        current_obj = bpy.context.object
        current_mode = current_obj.mode if current_obj else 'OBJECT'

        try:
            # 选中目标物体并进入编辑模式
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')

            # 使用 bmesh 读取顶点选择状态
            bm = bmesh.from_edit_mesh(obj.data)
            selection_data = [vert.select for vert in bm.verts]

            return selection_data
        except Exception as e:
            print(f"处理物体 '{obj.name}' 时发生错误: {e}")
            return None
        finally:
            # 恢复原活动物体和模式
            if current_obj:
                bpy.context.view_layer.objects.active = current_obj
                bpy.ops.object.mode_set(mode=current_mode)

    # worldPos匹配
    def select_vertices(self, center, radius):
        """选择半径内配对的顶点并返回索引数组"""
        src_chosen_vertices = []
        closest_vertex_index = -1
        radius_vec = center + Vector((0, 0, radius))
        # 将选择范围放入本地坐标中
        lco = self.src_mwi @ center
        r = self.src_mwi @ (radius_vec) - lco
        closest_length = r.length

        # 选择半径内的顶点
        for index, v in enumerate(self.src_object.data.shape_keys.key_blocks[0].data):

            if self.only_selected_src:  # 仅处理选中时，若没选中就跳过这个顶点
                isSelected = self.src_vertex_isSeleted[index]
                if not isSelected:
                    continue

            isLengthOK = (v.co - lco).length <= r.length
            if (isLengthOK):
                src_chosen_vertices.append(index)
                if (self.use_one_vertex):  # 只要一个顶点时，额外存储最近的顶点索引与最近距离
                    if ((v.co - lco).length <= closest_length):
                        closest_length = (v.co - lco).length
                        closest_vertex_index = index

        # 只要一个顶点时，舍弃已选顶点，只留最近的顶点
        if (self.use_one_vertex):
            src_chosen_vertices = []
            if (closest_vertex_index > - 1):
                src_chosen_vertices.append(closest_vertex_index)

        return src_chosen_vertices

    def select_required_verts(self, vert, rad, level=0):
        """该选择函数最初通过匹配与源网格相同空间中的点开始(如果 level=0),如果找不到相似的定位点,将会增加level继续直到达到最大重复次数"""
        verts = []
        if (level > self.number_of_increments):
            return verts
        verts = self.select_vertices(vert, rad)
        if (len(verts) == 0):
            return self.select_required_verts(vert, rad + self.increment_radius, level + 1)
        else:
            return verts

    def update_vertex_worldPos(self):
        """更新目标网格的 1 个顶点"""
        if (self.current_vertex_index >= self.total_vertices):
            return False  # 工作顶点序号达到总顶点数时，返回顶点处理完毕
        if self.only_selected_dest and not self.dest_vertex_isSeleted[self.current_vertex_index]:
            return False  # 开启了仅处理选中顶点时若工作顶点没选中，返回顶点处理完毕

        if (self.do_once_per_vertex):  # 每个顶点只执行一次
            self.current_vertex = self.dest_object.matrix_world @ self.dest_object.data.shape_keys.key_blocks[
                0].data[self.current_vertex_index].co
            # self.current_vertex = self.dest_object.data.shape_keys.key_blocks[
            #     0].data[self.current_vertex_index].co

            self.src_chosen_vertices = self.select_required_verts(
                self.current_vertex, 0)
            self.do_once_per_vertex = False

        if (len(self.src_chosen_vertices) == 0):
            return True  # 没匹配到返回没设置成功

        result_position = Vector()
        for v in self.src_chosen_vertices:
            result_position += self.src_object.data.shape_keys.key_blocks[0].data[v].co
        result_position /= len(self.src_chosen_vertices)

        result_position2 = Vector()
        for v in self.src_chosen_vertices:
            result_position2 += self.src_object.data.shape_keys.key_blocks[self.src_shape_key_index].data[v].co
        result_position2 /= len(self.src_chosen_vertices)


        #根据模式传递绝对位置或相对位置
        props = bpy.context.scene.shapekeytransfer
        abs_mode = props.absolute_mode
        if abs_mode:
            result = result_position2
        else:
            result = result_position2 - result_position + self.current_vertex


        self.set_vertex_position(result)  # 将新的位置设置到这个形态键中
        return False

    # uvPos匹配
    def calculate_avgUV(self, obj: Object):
        """计算网格物体的所有顶点平均 UV,返回{vertexIndex:avgUV}"""
        # 创建 BMesh 并加载网格数据
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        # 获取 UV 层
        uv_layer = bm.loops.layers.uv.active  # TODO
        if not uv_layer:
            raise ValueError(f"对象 {obj.name} 没有 UV 数据")

        # 使用 defaultdict 存储累积 UV 数据
        uv_data = defaultdict(lambda: [0.0, 0.0, 0])  # [累积 U, 累积 V, 计数]

        # 遍历所有面
        for face in bm.faces:
            for loop in face.loops:
                vert_idx = loop.vert.index
                uv = loop[uv_layer].uv
                uv_data[vert_idx][0] += uv.x
                uv_data[vert_idx][1] += uv.y
                uv_data[vert_idx][2] += 1

        average_uvs = {
            idx: Vector((data[0] / data[2], data[1] / data[2]))
            for idx, data in uv_data.items()
        }
        bm.free()  # 释放 BMesh 内存
        return average_uvs

    def select_vertices_byUV(self, uv_center, uv_radius):
        """选择 UV 半径内配对的顶点并返回索引数组, uv_center为目标顶点的UV"""
        src_chosen_vertices = []
        closest_vertex_index = -1
        closest_length = uv_radius

        for index, uv in self.src_uv_avglayer.items():

            if self.only_selected_src:  # 仅处理选中时，若没选中就跳过这个顶点
                isSelected = self.src_vertex_isSeleted[index]
                if not isSelected:
                    continue

            distance = (uv - uv_center).length  # 计算 UV 距离

            # 检查顶点是否在半径范围内
            if distance <= uv_radius:
                src_chosen_vertices.append(index)

                # 如果只选择最近的顶点，更新最近的顶点
                if distance < closest_length:
                    closest_length = distance
                    closest_vertex_index = index

        # 如果只选择最近的顶点，更新选择结果
        if self.use_one_vertex and closest_vertex_index != -1:
            src_chosen_vertices = [closest_vertex_index]

        return src_chosen_vertices

    def select_required_verts_byUV(self, uv, uv_radius, level=0):
        """通过 UV 匹配的递归选择函数"""
        verts = []
        if level > self.number_of_increments:
            return verts  # 递归达到上限直接返回
        verts = self.select_vertices_byUV(uv, uv_radius)  # dest的UV
        if len(verts) == 0:  # 没找到递归了找
            return self.select_required_verts_byUV(uv, uv_radius + self.increment_radius, level + 1)
        else:
            return verts

    def update_vertex_uvPos(self):
        """更新目标网格的 1 个顶点 (基于 UV 匹配)"""
        if self.current_vertex_index >= self.total_vertices:
            return False  # 工作顶点序号达到总顶点数时，返回完毕
        if self.only_selected_dest and not self.dest_vertex_isSeleted[self.current_vertex_index]:
            return False  # 开启了仅处理选中顶点时若工作顶点没选中，返回顶点处理完毕

        if self.do_once_per_vertex:  # 每个顶点只执行一次
            # 存一次世界空间坐标位置
            # self.current_vertex = self.dest_object.matrix_world @ self.dest_object.data.shape_keys.key_blocks[
            #     0].data[self.current_vertex_index].co
            self.current_vertex = self.dest_object.data.shape_keys.key_blocks[
                0].data[self.current_vertex_index].co

            # 获取目标顶点的 平均UV 坐标
            uv = self.dest_uv_avglayer[self.current_vertex_index]

            self.src_chosen_vertices = self.select_required_verts_byUV(uv, 0)
            self.do_once_per_vertex = False

        if len(self.src_chosen_vertices) == 0:
            return True  # 没匹配到返回没设置成功

        result_position = Vector((0, 0, 0))
        for v in self.src_chosen_vertices:
            result_position += self.src_object.data.shape_keys.key_blocks[0].data[v].co
        result_position /= len(self.src_chosen_vertices)

        result_position2 = Vector((0, 0, 0))
        for v in self.src_chosen_vertices:
            result_position2 += self.src_object.data.shape_keys.key_blocks[self.src_shape_key_index].data[v].co
        result_position2 /= len(self.src_chosen_vertices)

        #根据模式传递绝对位置或相对位置
        props = bpy.context.scene.shapekeytransfer
        abs_mode = props.absolute_mode
        if abs_mode:
            result = result_position2
        else:
            result = result_position2 - result_position + self.current_vertex


        self.set_vertex_position(result)  # 将新的位置设置到这个形态键中
        return False
    # 顶点索引匹配

    def select_required_verts_byIndex(self, dest_index: int):

        if self.only_selected_src:
            if not self.src_vertex_isSeleted[dest_index]:
                return []  # 仅处理选中时，若没选中就跳过这个顶点

        return [dest_index]

    def update_vertex_index(self):
        """更新目标网格的顶点索引并处理其位置"""
        if self.current_vertex_index >= self.total_vertices:
            return False  # 所有顶点已处理完成
        if self.only_selected_dest and not self.dest_vertex_isSeleted[self.current_vertex_index]:
            return False  # 开启了仅处理选中顶点时若工作顶点没选中，返回顶点处理完毕

        if self.do_once_per_vertex:  # 每个顶点只执行一次
            self.current_vertex = self.dest_object.data.shape_keys.key_blocks[
                0].data[self.current_vertex_index].co

            self.src_chosen_vertices = self.select_required_verts_byIndex(
                dest_index=self.current_vertex_index)  
            self.do_once_per_vertex = False

        if len(self.src_chosen_vertices) == 0:
            return True  # 没匹配到返回没设置成功
        if self.src_chosen_vertices[0] >= len(self.src_object.data.shape_keys.key_blocks[
                0].data):    # 没超出字典范围返回处理完成
            return False

        result_position = self.src_object.data.shape_keys.key_blocks[
            0].data[self.src_chosen_vertices[0]].co
        result_position2 = self.src_object.data.shape_keys.key_blocks[
            self.src_shape_key_index].data[self.src_chosen_vertices[0]].co

        #根据模式传递绝对位置或相对位置
        props = bpy.context.scene.shapekeytransfer
        abs_mode = props.absolute_mode
        if abs_mode:
            result = result_position2
        else:
            result = result_position2 - result_position + self.current_vertex



        self.set_vertex_position(result)
        return False

    # 主功能
    def transfer_shape_keys(self, src: Object, dest: Object):
        """传递形态键"""
        self.src_object = src
        self.dest_object = dest
        self.src_mwi = self.src_object.matrix_world.inverted()

        self.current_vertex_index = 0  # 正在处理的dest_object的网格的顶点索引
        self.total_vertices = len(self.dest_object.data.vertices)
        if self.only_selected_src:
            self.src_vertex_isSeleted = self.save_vertex_isSelected(
                self.src_object)  # 预储存顶点是否被选择
        if self.only_selected_dest:
            self.dest_vertex_isSeleted = self.save_vertex_isSelected(
                self.dest_object)  # 预储存顶点是否被选择

        if self.mode == "MOD_UV_POSITION":
            self.src_uv_avglayer = self.calculate_avgUV(
                self.src_object)  # 预计算平均UV
            self.dest_uv_avglayer = self.calculate_avgUV(
                self.dest_object)  # 预计算平均UV

        if (not (self.src_object.data and self.dest_object.data)):
            self.message = "网格无效!"
            return True

        if (not hasattr(self.src_object.data.shape_keys, "key_blocks")):
            self.message = "源网格中没有形态键!"
            return True

        # 保证目标物体有basis键
        if (not hasattr(self.dest_object.data.shape_keys, "key_blocks")):
            self.dest_object.shape_key_add(name="Basis")

        # 生成工作形态键目录(遍历源物体的形态键)
        for src_shape_key_iter in self.src_object.data.shape_keys.key_blocks:
            src_name = src_shape_key_iter.name
            if self.is_list_inversed:  # 白名单模式
                if src_name in self.list_shape_keys:  # 原物体的形态键在列表的就加进work列表
                    self.work_shape_keys.append(src_name)
                else:
                    continue
            else:  # 黑名单模式
                if (src_name not in self.list_shape_keys) and (src_name not in self.base_shape_keys):
                    self.work_shape_keys.append(src_name)
                else:
                    continue

            # 检查目标物体是否缺少该形态键，若缺少则添加
            if not any(src_name == dest_shape_key_iter.name for dest_shape_key_iter in self.dest_object.data.shape_keys.key_blocks):
                self.dest_object.shape_key_add(name=src_name)
        # print("列表目录", self.list_shape_keys[:])
        # print("传递目录", self.work_shape_keys[:])

        # 处理全部的顶点
        update_vertex_method = self.update_vertex_worldPos
        if self.mode == "MOD_UV_POSITION":
            update_vertex_method = self.update_vertex_uvPos
        if self.mode == "MOD_VERTEX_INDEX":
            update_vertex_method = self.update_vertex_index

        while self.current_vertex_index < self.total_vertices:  # 对所有顶点处理
            self.do_once_per_vertex = True  # 设置工作顶点为第一次处理此顶点
            # 遍历源对象的形态键，根据过滤规则处理
            for shape_key_iter in self.src_object.data.shape_keys.key_blocks:
                key_name = shape_key_iter.name
                if key_name in self.work_shape_keys:
                    self.update_global_shapekey_indices(key_name)  # 设置工作形态键的索引
                    if update_vertex_method():  # 执行一次形态键的传递
                        print(f"目标物体顶点{self.current_vertex_index}的形态键未设置成功:")
            self.current_vertex_index += 1

        self.message = "形态键传递成功"
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
        SKT.number_of_increments = skt.number_of_increments
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
        col.prop(skt, "number_of_increments")


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
    row.prop(skt, "number_of_increments", slider=True)
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
