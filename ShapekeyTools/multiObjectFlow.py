import bpy
import numpy as np
import bmesh
from bpy.types import Operator,Panel,Menu,Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty,FloatVectorProperty
import bmesh
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d
import json

# region 变量
def reg_props():
    bpy.types.Scene.hoShapekeyTools_enable_multi = BoolProperty(default=False)#启用开关
    bpy.types.Scene.hoShapekeyTools_bs_multi_col = PointerProperty(type=bpy.types.Collection,name="源集合",description="选择生成的物体的集合",update=None)  # type: ignore

    return


def ureg_props():
    del bpy.types.Scene.hoShapekeyTools_enable_multi
    del bpy.types.Scene.hoShapekeyTools_bs_multi_col

    return
# endregion

class OP_ShapekeyTools_multi_generateLinkedObjects(Operator):
    bl_idname = "ho.shapekeytools_generate_linkedobjects"
    bl_label = "生成链接物体"
    bl_description = "为活动物体生成链接的形态键物体集合"
    bl_options = {'REGISTER', 'UNDO'}


    @classmethod
    def poll(cls, context):
        return True

    def get_bbox_corners(self,objs)->list:
        """计算所有物体的新包围盒拐角"""
        corners = []
        for obj in objs:
            bbox_world = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]# 获取世界空间包围盒8个点
            corners.extend(bbox_world)
        return corners

    def get_bbox_size(self,objs)->Vector:
        """计算所有物体的新包围盒尺寸"""
        corners = self.get_bbox_corners(objs)
        xs = [v.x for v in corners]
        ys = [v.y for v in corners]
        zs = [v.z for v in corners]
        width = max(xs) - min(xs)
        length = max(ys) - min(ys)
        height = max(zs) - min(zs)
        return Vector((width,length,height))


    def execute(self, context):
        objs = context.selected_objects
        if not objs:
            self.report({'ERROR'}, "没有选择物体")
            return {'CANCELLED'}

        # --- 检查选择物体的合法性 ---
        shapekey_names = None
        for obj in objs:
            if obj.type != 'MESH' or not obj.data.shape_keys:
                self.report({'ERROR'}, f"{obj.name} 缺少有效形态键")
                return {'CANCELLED'}
            keys = obj.data.shape_keys.key_blocks
            if len(keys) <= 1:
                self.report({'ERROR'}, f"{obj.name} 没有基型以外的键")
                return {'CANCELLED'}
            current_names = [k.name for k in keys if k.name != 'Basis']
            if shapekey_names is None:
                shapekey_names = current_names
            elif shapekey_names != current_names:
                self.report({'ERROR'}, "所有选中物体的形态键必须一致")
                return {'CANCELLED'}
        if not shapekey_names:
            self.report({'ERROR'}, "没有形态键")
            return {'CANCELLED'}

        # --- 创建总集合 ---
        main_collection_name = "Ho_BSLink"
        main_collection = None
        if main_collection_name in bpy.data.collections:
            main_collection = bpy.data.collections[main_collection_name]
        else:
            main_collection = bpy.data.collections.new(main_collection_name)
            context.scene.collection.children.link(main_collection)
        context.scene.hoShapekeyTools_bs_multi_col = main_collection#自动填入

        
        # --- 每个形态键一个空物体 ---
        emptys = []
        # 计算名称位置
        corners = self.get_bbox_corners(objs)       
        NameCenterLoc = (min([v.x for v in corners]),
                        (max([v.y for v in corners]) + min([v.y for v in corners]))/2,
                        (max([v.z for v in corners]) + min([v.z for v in corners]))/2,
                        )
        for key_name in shapekey_names:
            # 创建空物体(命名为键名)
            empty_name = f"{key_name}"

            empty = bpy.data.objects.new(empty_name, None)#TODO 没有处理重名
            empty.empty_display_size = 0.01
            emptys.append(empty)
            context.scene.collection.objects.link(empty)
            main_collection.objects.link(empty)

            #创建用于显示名称的物体
            emptyNameObj = bpy.data.objects.new(str("@"+empty_name), None)
            emptyNameObj.hide_select = True # 不可选
            emptyNameObj.show_name = True # 开启名称显示，名称为形态键名
            emptyNameObj.empty_display_size = 0.01
            emptyNameObj.location = NameCenterLoc
            emptyNameObj.parent = empty
            main_collection.objects.link(emptyNameObj)
            

            
            # 复制每个物体（命名为：物体名#键名）
            for obj in objs:
                new_obj = obj.copy()
                new_obj.data = obj.data.copy()
                new_obj.name = f"{obj.name}#{key_name}"
                context.scene.collection.objects.link(new_obj)

                # 设置父级为空物体
                new_obj.parent = empty
                # 打开形态键独显与编辑模式编辑并设置形态键
                new_obj.show_only_shape_key = True
                new_obj.use_shape_key_edit_mode = False

                # 找出要保留的两个键（Basis + 当前）
                shape_keys = new_obj.data.shape_keys
                key_blocks = shape_keys.key_blocks
                ref_key = shape_keys.reference_key
                keep_names = {ref_key.name, key_name}
                # 删除其余形态键(逆序防止删到基型)
                for i in reversed(range(len(key_blocks))):
                    kb = key_blocks[i]
                    if kb.name not in keep_names:
                        new_obj.shape_key_remove(kb)

                # 设置本次遍历的形态键为 active
                if key_name in new_obj.data.shape_keys.key_blocks:
                    index = new_obj.data.shape_keys.key_blocks.find(key_name)
                    new_obj.active_shape_key_index = index

                # 移动集合(需要额外处理空物体父级)
                for coll in empty.users_collection:
                    coll.objects.unlink(empty)
                main_collection.objects.link(empty)
                for coll in new_obj.users_collection:
                    coll.objects.unlink(new_obj)
                main_collection.objects.link(new_obj)

        #放置空物体
        cols = 10                                   # 每行数量
        bbox_size = self.get_bbox_size(objs)
        spacing_w = bbox_size.x                     # 列间距
        spacing_h = bbox_size.z                     # 行间距
        facotr_w = 1.1                              # 列间距倍率
        facotr_h = 1.1                              # 行间距倍率

        
        
        for i, empty in enumerate(emptys):
            row = i // cols
            col = i % cols
            empty.location = Vector(((col+1) * spacing_w * facotr_w, 0, -row * spacing_h * facotr_h))  # 横排 + 向下堆

        return {'FINISHED'}



class OP_ShapekeyTools_multi_refreshKeysFromMulti(Operator):
    bl_idname = "ho.shapekeytools_refreshkey_from_multi"
    bl_label = "从集合刷新"
    bl_description = "从集合刷新形态键到所选的全部物体的对应形态键"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True
    
    def execute(self, context):
        objs = context.selected_objects
        src_col = context.scene.hoShapekeyTools_bs_multi_col

        if not objs or not src_col:
            self.report({'ERROR'}, "请选择目标物体并确保已生成集合")
            return {'CANCELLED'}

        # 找出源集合中所有空物体（按空名区分形态键）
        emptys = [obj for obj in src_col.objects if obj.type == 'EMPTY']
        if not emptys:
            self.report({'ERROR'}, "集合中没有空物体")
            return {'CANCELLED'}

        # 遍历选中中的每个物体
        for obj in objs:
            if obj.type != 'MESH' or not obj.data.shape_keys:
                continue

            key_blocks = obj.data.shape_keys.key_blocks

            #遍历所有的空物体（等效于形态键）
            for empty in emptys:
                key_name = empty.name
                if key_name not in key_blocks:
                    self.report({'WARNING'}, f"{obj.name} 缺少形态键 {key_name}，已跳过")
                    continue

                # 查找当前空物体下对应的形态键物体
                linked_objs = [child for child in empty.children if '#' in child.name]  # 只扫描带#的子级物体
                matched = None
                for child in linked_objs:
                    parts = child.name.split("#", 1) # 使用第一个#来分割
                    if len(parts) == 2 and parts[0] == obj.name:
                        matched = child
                        break

                if not matched:
                    self.report({'WARNING'}, f"找不到与 {obj.name} 匹配的 {key_name} 形态键物体")
                    continue

                # 将该物体的数据拷贝回目标形态键
                src_mesh = matched.data
                dst_mesh = obj.data

                # 要求网格拓扑一致
                if len(src_mesh.vertices) != len(dst_mesh.vertices):
                    self.report({'WARNING'}, f"{obj.name} 与 {matched.name} 拓扑不一致，跳过")
                    continue

                # 传递回形态键
                src_keys = matched.data.shape_keys
                if key_name not in src_keys.key_blocks:
                    self.report({'WARNING'}, f"{matched.name} 缺少形态键 {key_name}")
                    continue

                src_shape_key = src_keys.key_blocks[key_name]
                dst_shape_key = key_blocks[key_name]

                for i in range(len(dst_shape_key.data)):
                    dst_shape_key.data[i].co = src_shape_key.data[i].co.copy()

        return {'FINISHED'}



def draw_in_DATA_PT_shape_keys(self, context: Context):
    """属性形态键下"""
    layout: bpy.types.UILayout = self.layout
    layout.use_property_decorate = False  # 禁用关键帧动画


    row = layout.row(align=True)
    row.prop(context.scene,"hoShapekeyTools_enable_multi",text="启用多物体工作流",toggle=True)
    if not context.scene.hoShapekeyTools_enable_multi:
            return
    row = layout.row(align=True)
    row.operator(OP_ShapekeyTools_multi_generateLinkedObjects.bl_idname,text="生成链接集合",icon="LINKED")
    row.prop(context.scene,"hoShapekeyTools_bs_multi_col",text="")
    row = layout.row(align=True)
    row.scale_y = 2.0
    row.operator(OP_ShapekeyTools_multi_refreshKeysFromMulti.bl_idname,text="从集合刷新",icon="FILE_REFRESH")

    

    

cls = [
    OP_ShapekeyTools_multi_generateLinkedObjects,OP_ShapekeyTools_multi_refreshKeysFromMulti,
    ]


def register():

    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.DATA_PT_shape_keys.append(draw_in_DATA_PT_shape_keys)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.DATA_PT_shape_keys.remove(draw_in_DATA_PT_shape_keys)

    ureg_props()
