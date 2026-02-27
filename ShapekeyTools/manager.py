import bpy
from bpy.types import PropertyGroup, UIList, Operator, Panel
from bpy.types import UILayout, Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, IntProperty


class PG_SKManager_SKCache(PropertyGroup):  # 存储目标骨骼和源骨骼的映射关系
    key_name: StringProperty(name="")  # type: ignore
    is_selected: BoolProperty(default=False)  # type: ignore
    is_basis: BoolProperty(default=False)  # type: ignore 


class UL_SKManager_SKItems(UIList):  
    def draw_item(self, context, layout:UILayout, data, item, icon, active_data, active_propname, index):
        sk_cache = item
        
        row = layout.row(align=True)
        row_t = row.row(align=True)
        row_t.scale_x = 0.5
        row_t.label(text=str(index + 1))

        if sk_cache.is_basis:
            row.alert = True
        row.prop(sk_cache, "is_selected", text=sk_cache.key_name,emboss=1-sk_cache.is_basis,toggle=True,translate=False)
        row.alert = False

        
        
        


def reg_props():
    # 缓存列表
    bpy.types.Scene.skmanager_skcache_col = CollectionProperty(
        type=PG_SKManager_SKCache,)
    bpy.types.Scene.skmanager_skcache_index = IntProperty()
    bpy.types.Scene.skmanager_skcache_fastmove_num = IntProperty(
        default=10, min=0, soft_max=10)


def ureg_props():
    del bpy.types.Scene.skmanager_skcache_col
    del bpy.types.Scene.skmanager_skcache_index
    del bpy.types.Scene.skmanager_skcache_fastmove_num



class OP_SelectAllSKCacheItems(Operator):
    bl_idname = "ho.skmanager_selectall_skitem"
    bl_label = "全选形态键"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col

        # 遍历列表，将所有项的 is_selected 设为 True
        for item in sk_list:
            if item.is_basis:
                continue
            item.is_selected = True

        return {'FINISHED'}


class OP_DeselectAllSKCacheItems(Operator):
    bl_idname = "ho.skmanager_deselectall_skitem"
    bl_label = "全部弃选形态键"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col

        # 遍历列表，将所有项的 is_selected 设为 False
        for item in sk_list:
            item.is_selected = False

        return {'FINISHED'}


class OP_RefreshSKCacheItems(Operator):
    bl_idname = "ho.skmanager_refresh_skitem"
    bl_label = "刷新列表"
    bl_description = "使用功能前请先刷新列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'FINISHED'}
        if not obj.data.shape_keys:
            return {'FINISHED'}

        shape_keys = obj.data.shape_keys.key_blocks
        sk_list = context.scene.skmanager_skcache_col

        # 清空旧列表
        sk_list.clear()

        # 将形态键添加到自定义列表中
        for index, key in enumerate(shape_keys):
            item = sk_list.add()
            item.key_name = key.name
            item.index = index
            item.is_basis = (obj.data.shape_keys.reference_key  == key) 

        return {'FINISHED'}


class OP_MoveUpSKCacheItems(Operator):
    bl_idname = "ho.skmanager_moveup_skitem"
    bl_label = "列表勾选上移"
    bl_options = {'REGISTER', 'UNDO'}

    #所有移动的基础操作，方便管理
    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col
        for i, bone in enumerate(sk_list):
            if bone.is_selected and i > 0:
                if sk_list[i-1].is_selected or sk_list[i - 1].is_basis:
                    continue#防止与前一个选中对象换位，跳过基型
                sk_list.move(i, i - 1)
        return {'FINISHED'}


class OP_MoveDownSKCacheItems(Operator):
    bl_idname = "ho.skmanager_movedown_skitem"
    bl_label = "列表勾选下移"
    bl_options = {'REGISTER', 'UNDO'}

    #所有移动的基础操作，方便管理
    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col
        for i in reversed(range(len(sk_list))):
            if sk_list[i].is_selected and i < len(sk_list) - 1:
                if sk_list[i + 1].is_selected or sk_list[i + 1].is_basis:
                    continue  # 防止与后一个选中对象换位，跳过基型
                sk_list.move(i, i + 1)
        return {'FINISHED'}


class OP_MoveTopSKCacheItems(Operator):
    bl_idname = "ho.skmanager_movetop_skitem"
    bl_label = "列表勾选置顶"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col
        selected_indices = [i for i, item in enumerate(sk_list) if item.is_selected]

        # 逐个选中的元素调用上下移动操作，直到到达顶部
        for index in selected_indices:
            while index > 0:  # 如果该项不在顶部
                # 调用上移操作
                context.view_layer.objects.active = context.active_object
                bpy.ops.ho.skmanager_moveup_skitem()
                # 更新当前元素的新索引
                index -= 1

        return {'FINISHED'}


class OP_MoveBottomSKCacheItems(Operator):
    bl_idname = "ho.skmanager_movebottom_skitem"
    bl_label = "列表勾选置底"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sk_list = context.scene.skmanager_skcache_col
        selected_indices = [i for i, item in enumerate(sk_list) if item.is_selected]
        list_length = len(sk_list)

        # 逐个选中的元素调用上下移动操作，直到到达底部
        for index in reversed(selected_indices):
            while index < list_length - 1:  # 如果该项不在底部
                # 调用下移操作
                context.view_layer.objects.active = context.active_object
                bpy.ops.ho.skmanager_movedown_skitem()
                # 更新当前元素的新索引
                index += 1

        return {'FINISHED'}


class OP_MoveFastUpSKCacheItems(Operator):
    bl_idname = "ho.skmanager_movefastup_skitem"
    bl_label = "列表勾选快速上移"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        move_num = context.scene.skmanager_skcache_fastmove_num  # 获取快速移动的步数

        for _ in range(move_num):
            bpy.ops.ho.skmanager_moveup_skitem()
        
        return {'FINISHED'}


class OP_MoveFastDownSKCacheItems(Operator):
    bl_idname = "ho.skmanager_movefastdown_skitem"
    bl_label = "列表勾选快速下移"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        move_num = context.scene.skmanager_skcache_fastmove_num  # 获取快速移动的步数

        for _ in range(move_num):
            bpy.ops.ho.skmanager_movedown_skitem()

        return {'FINISHED'}


class OP_ClearSKCacheItems(Operator):
    bl_idname = "ho.skmanager_clear_skitem"
    bl_label = "清空列表中选择"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.skmanager_skcache_col.clear()
        return {'FINISHED'}


class OP_SortSKCacheItems(Operator):
    bl_idname = "ho.skmanager_sort_skitem"
    bl_label = "排序列表中选择"
    bl_options = {'REGISTER', 'UNDO'}

    def copy_item_data(self, item):
        """将项的属性复制到新的字典中，以便进行扩展"""
        return {
            "key_name": item.key_name,
            "is_selected": item.is_selected,
            "is_basis": item.is_basis,
            # 这里可以继续扩展属性，只需修改这个地方
        }

    def execute(self, context):
        scene = context.scene
        items = scene.skmanager_skcache_col

        # 分离选中和未选中项
        selected_items = [item for item in items if item.is_selected and not item.is_basis]
        unselected_items = [(i, item) for i, item in enumerate(items) if not item.is_selected and not item.is_basis]
        basis_items = [item for item in items if item.is_basis]  # 基型项，不参与排序

        if not selected_items:
            self.report({'WARNING'}, "No items selected for sorting")
            return {'CANCELLED'}

        # 对选中项按 key_name 排序
        sorted_selected_items = sorted(selected_items, key=lambda item: item.key_name)

        # 创建新列表，将未选中项和基型项保持原位置，插入排序后的选中项
        new_items = [None] * len(items)
        
        # 插入未选中项
        for index, item in unselected_items:
            new_items[index] = self.copy_item_data(item)
        
        # 插入基型项
        for index, item in enumerate(items):
            if item.is_basis:
                new_items[index] = self.copy_item_data(item)  # 基型项不参与排序，保持原位

        # 用迭代器将排序后的选中项插入到剩余的空位中
        sorted_iter = iter(sorted_selected_items)
        for i in range(len(new_items)):
            if new_items[i] is None:
                selected_item = next(sorted_iter)
                new_items[i] = self.copy_item_data(selected_item)

        # 清空并更新原始 CollectionProperty
        items.clear()
        for item_data in new_items:
            new_item = items.add()
            new_item.key_name = item_data["key_name"]
            new_item.is_selected = item_data["is_selected"]
            new_item.is_basis = item_data["is_basis"]

        return {'FINISHED'}


class OP_ApplyOrderSKCacheItems(bpy.types.Operator):
    bl_idname = "ho.skmanager_applyorder_skitem"
    bl_label = "应用列表顺序"
    bl_description="""
    将当前的列表顺序，应用到活动形态键的形态键顺序
    使用方法：
    1.刷新形态键
    2.选中想要改变顺序的项移动/排序/置顶置底
    3.应用列表顺序
    """
    bl_options = {'REGISTER', 'UNDO'}

    
    def execute(self, context):
        obj = bpy.context.object  # 获取当前对象
        sk_cache_col = context.scene.skmanager_skcache_col  # 获取形态键列表
        
        # 获取当前对象的所有形态键名称
        shape_key_names = [key.name for key in obj.data.shape_keys.key_blocks]
        
        # 获取缓存中所有形态键名称
        cache_names = [sk.key_name for sk in sk_cache_col if sk.key_name]

        # 检查缓存中的形态键名称是否与对象中的形态键一致
        if sorted(shape_key_names) != sorted(cache_names):
            self.report({'WARNING'}, "形态键列表不一致！请确保两者的形态键一致。")
            return {'CANCELLED'}

        # 重新排序形态键
        self.reorder_shape_keys(obj, sk_cache_col)
        
        return {'FINISHED'}

    def reorder_shape_keys(self, obj, sk_cache_col):
        shape_keys = obj.data.shape_keys.key_blocks
        
        # 创建一个按PG_SKManager_SKCache的顺序排列的形态键名称列表
        new_order = [sk.key_name for sk in sk_cache_col if sk.key_name]

        # 逐个形态键，移动到正确的位置
        for target_index, target_name in enumerate(new_order):
            # 查找当前形态键的位置
            current_index = next((i for i, key in enumerate(shape_keys) if key.name == target_name), None)

            # 确保找到了当前形态键
            if current_index is not None and current_index != target_index:
                # 设置目标形态键为活动形态键
                bpy.context.object.active_shape_key_index = current_index
                
                # 判断方向并将其移到目标位置
                while current_index < target_index:
                    bpy.ops.object.shape_key_move(type='DOWN')
                    current_index += 1
                while current_index > target_index:
                    bpy.ops.object.shape_key_move(type='UP')
                    current_index -= 1


def drawShapekeyManagerPanel(layout: UILayout, context: Context):
    scene = context.scene
    row = layout.row()
    row.template_list("UL_SKManager_SKItems", "",
                      scene,"skmanager_skcache_col",
                      scene, "skmanager_skcache_index",
                      rows=20)
    col = row.column(align=True)
    col.operator(OP_SelectAllSKCacheItems.bl_idname,
                 icon="CHECKBOX_HLT", text="")
    col.operator(OP_DeselectAllSKCacheItems.bl_idname,
                 icon="CHECKBOX_DEHLT", text="")

    col.separator()
    col.alert = True
    col.operator(OP_RefreshSKCacheItems.bl_idname,
                 icon="FILE_REFRESH", text="")
    col.alert = False
    col.operator(OP_ClearSKCacheItems.bl_idname,
                 icon="PANEL_CLOSE", text="")
    col.operator(OP_SortSKCacheItems.bl_idname,
                 icon="SORTTIME", text="")
    col.operator(OP_MoveUpSKCacheItems.bl_idname,
                 icon="TRIA_UP", text="")
    col.operator(OP_MoveDownSKCacheItems.bl_idname,
                 icon="TRIA_DOWN", text="")
    col.operator(OP_MoveTopSKCacheItems.bl_idname,
                 icon="TRIA_UP_BAR", text="")
    col.operator(OP_MoveBottomSKCacheItems.bl_idname,
                 icon="TRIA_DOWN_BAR", text="")
    temp = col.row()
    temp.scale_x = 0.5
    temp.prop(context.scene, "skmanager_skcache_fastmove_num",
              icon_only=True, slider=True)
    col.operator(OP_MoveFastUpSKCacheItems.bl_idname,
                 icon="TRIA_UP", text="")
    col.operator(OP_MoveFastDownSKCacheItems.bl_idname,
                 icon="TRIA_DOWN", text="")
    
    col.separator()
    col.alert = True
    col.operator(OP_ApplyOrderSKCacheItems.bl_idname,
                 icon="FUND",text="")
    col.alert = False


cls = [PG_SKManager_SKCache, UL_SKManager_SKItems,
       OP_SelectAllSKCacheItems, OP_DeselectAllSKCacheItems,
       OP_RefreshSKCacheItems, OP_SortSKCacheItems,
       OP_ClearSKCacheItems,OP_ApplyOrderSKCacheItems,
       OP_MoveDownSKCacheItems, OP_MoveUpSKCacheItems,
       OP_MoveBottomSKCacheItems, OP_MoveTopSKCacheItems,
       OP_MoveFastDownSKCacheItems, OP_MoveFastUpSKCacheItems
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
