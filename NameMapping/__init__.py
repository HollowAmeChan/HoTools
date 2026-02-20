import bpy
import csv
import io
import os
from bpy.types import PropertyGroup, UIList, Operator, Panel, Menu
from bpy.types import UILayout, Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,IntProperty,EnumProperty
import subprocess




class PG_MappingItem(PropertyGroup):
    """
    UIlist内容物类
    添加修改属性需要同时修改swap等函数的内容
    """
    name: StringProperty(name="data name")  # type: ignore
    isTarget:BoolProperty(name="是否为目标数据",description="0",default=False) # type: ignore
    isSelected: BoolProperty(
        name="list item isSelected", default=False)  # type: ignore

class UL_Mapping_TargetItems(UIList):
    """Mapping的目标UIlist"""
    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        label = row.row(align=True)
        label.scale_x = 0.3
        label.label(text=str(index+1))
        label.prop(item, "isSelected", text=str(index + 1))
        row.prop(item, "name", text="")

class UL_Mapping_SearchItems(UIList):
    """Mapping的搜寻UIlist"""
    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        label = row.row(align=True)
        label.scale_x = 0.3
        label.label(text=str(index+1))
        label.prop(item, "isSelected", text=str(index + 1))
        row.prop(item, "name", text="")


def reg_props():
    # mapping列表
    bpy.types.Scene.ho_mapping_targetlist = CollectionProperty(
        type=PG_MappingItem)
    bpy.types.Scene.ho_mapping_searchlist = CollectionProperty(
        type=PG_MappingItem)
    bpy.types.Scene.ho_mapping_cachelist = CollectionProperty(
        type=PG_MappingItem)
    # mapping列表索引存储
    bpy.types.Scene.ho_mapping_targetlist_index = IntProperty()
    bpy.types.Scene.ho_mapping_searchlist_index = IntProperty()
    bpy.types.Scene.ho_mapping_cachelist_index = IntProperty()
    #mapping模式
    enum_items = [
        ('OBJECT_NAME', "物体名称", "物体名称"),
        ('OBJECT_VERTEXGROUP_NAME', "顶点组", "物体顶点组名称"),
        ('OBJECT_SHAPEKEY_NAME', "形态键", "物体形态键名称"),
        ('OBJECT_MATERIAL_NAME', "材质", ""),
        ('ARMATURE_BONE_NAME', "骨骼", ""),

    ]
    bpy.types.Scene.ho_mapping_type = EnumProperty(
        name="数据类型", items=enum_items)
    #mapping属性
    bpy.types.Scene.ho_mapping_isAllselected = BoolProperty(name="全部所选",description="开启将处理全部物体，否则仅处理活动物体",default=True)
    return 


def ureg_props():
   del bpy.types.Scene.ho_mapping_targetlist
   del bpy.types.Scene.ho_mapping_searchlist
   del bpy.types.Scene.ho_mapping_cachelist
   del bpy.types.Scene.ho_mapping_targetlist_index
   del bpy.types.Scene.ho_mapping_searchlist_index
   del bpy.types.Scene.ho_mapping_cachelist_index
   del bpy.types.Scene.ho_mapping_type
   del bpy.types.Scene.ho_mapping_isAllselected

   return 



class OP_Mapping_SwapList(Operator):
    bl_idname = "ho.mapping_swaplist"
    bl_label = "Swap Mapping"
    bl_description = "交换列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 获取场景中的两个 CollectionProperty 列表
        scene = context.scene
        target_list = scene.ho_mapping_targetlist
        search_list = scene.ho_mapping_searchlist
        temp_list = scene.ho_mapping_cachelist

        # 将 target_list 内容移到 temp_list
        for item in target_list:
            new_item = temp_list.add()
            new_item.name = item.name
            new_item.isTarget = item.isTarget
            new_item.isSelected = item.isSelected

        # 清空 target_list
        target_list.clear()

        # 将 search_list 内容移到 target_list
        for item in search_list:
            new_item = target_list.add()
            new_item.name = item.name
            new_item.isTarget = item.isTarget
            new_item.isSelected = item.isSelected

        # 清空 search_list
        search_list.clear()

        # 将 temp_list 内容移到 search_list
        for item in temp_list:
            new_item = search_list.add()
            new_item.name = item.name
            new_item.isTarget = item.isTarget
            new_item.isSelected = item.isSelected

        # 清空缓存
        temp_list.clear()
        return {'FINISHED'}

class OP_Mapping_RemoveListItems(Operator):
    """删除列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_removelistitems"
    bl_label = "删除勾选"
    bl_description = "删除列表中所有勾选对象"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist
        # 逆序删除，避免索引问题
        for i in reversed(range(len(list))):
            if list[i].isSelected:
                list.remove(i)  # 删除勾选
        return {'FINISHED'}
    
class OP_Mapping_ClearItems(Operator):
    """删除列表所有item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_clearlistitems"
    bl_label = "清空列表"
    bl_description = "清空列表中所有的对象"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore


    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist
        list.clear()
        return {'FINISHED'}
    
class OP_Mapping_MoveUpItems(Operator):
    """上移列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_move_up_listitems"
    bl_label = "上移所选"
    bl_description = "将列表中勾选的对象向上移动"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore


    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        for i, item in enumerate(list):
            if item.isSelected and i > 0:
                list.move(i, i - 1)
        return {'FINISHED'}

class OP_Mapping_MoveDownItems(Operator):
    """下移列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_move_down_listitems"
    bl_label = "下移所选"
    bl_description = "将列表中勾选的对象向下移动"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        for i in reversed(range(len(list))):
            if list[i].isSelected and i < len(list) - 1:
                list.move(i, i + 1)
        return {'FINISHED'}
    
class OP_Mapping_MoveTopItems(Operator):
    """置顶列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_move_top_listitems"
    bl_label = "置顶所选"
    bl_description = "将列表中勾选的对象置顶"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        # 获取所有勾选的项目并保持顺序
        selected_indices = [i for i, item in enumerate(
            list) if item.isSelected]
        # 先收集勾选项目，然后依次移到顶部
        for i, idx in enumerate(selected_indices):
            list.move(idx, i)  # 将第i个勾选的项目移到i的位置
        return {'FINISHED'}

class OP_Mapping_MoveBottomItems(Operator):
    """置底列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_move_bottom_listitems"
    bl_label = "置底所选"
    bl_description = "将列表中勾选的对象置底"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        length = len(list) - 1
        # 获取所有勾选的项目并保持顺序
        selected_indices = [i for i, item in enumerate(
            list) if item.isSelected]
        # 先收集勾选项目，然后依次移到底部
        for i, idx in enumerate(reversed(selected_indices)):
            list.move(idx, length - i)
        return {'FINISHED'}
    
class OP_Mapping_SelectAllItems(Operator):
    """全选列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_select_all_listitems"
    bl_label = "全选"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore


    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        for item in list:
            item.isSelected = True  # 勾选所有目标骨骼
        return {'FINISHED'}
    
class OP_Mapping_DeselectAllItems(Operator):
    """全部弃选列表所选item,使用isTargetList区分两个列表"""
    bl_idname = "ho.mapping_deselect_all_listitems"
    bl_label = "全弃"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist

        for item in list:
            item.isSelected = False
        return {'FINISHED'}

def copy_to_clipboard(text):
    subprocess.run("clip", universal_newlines=True, input=text)

def paste_from_clipboard():
    try:
        text = bpy.context.window_manager.clipboard
        if not text:
            return []

        reader = csv.reader(io.StringIO(text))
        lines = []

        for row in reader:
            # 即使 row 是空列表，也保留空行
            if not row:
                lines.append("")  # 表示空行
            else:
                # 保留原始内容（只去除两端空格）
                lines.append(row[0].strip() if row[0] else "")
        return lines
    except Exception:
        return []


class OP_Mapping_CopyListToClipboard(bpy.types.Operator):
    """将当前列表复制到剪贴板"""
    bl_idname = "ho.mapping_copy_list"
    bl_label = "复制列表到剪贴板"
    bl_options = {'REGISTER'}

    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        if self.isTargetList:
            items = [i.name for i in context.scene.ho_mapping_targetlist]
        else:
            items = [i.name for i in context.scene.ho_mapping_searchlist]

        if not items:
            self.report({'WARNING'}, "列表为空")
            return {'CANCELLED'}

        text = "\n".join(items)
        copy_to_clipboard(text)
        self.report({'INFO'}, f"{len(items)} 行已复制到剪贴板")
        return {'FINISHED'}


class OP_Mapping_PasteListFromClipboard(bpy.types.Operator):
    """从剪贴板粘贴到列表"""
    bl_idname = "ho.mapping_paste_list"
    bl_label = "从剪贴板粘贴到列表"
    bl_options = {'REGISTER', 'UNDO'}

    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    clear_before: bpy.props.BoolProperty(
        name="粘贴前清空现有列表",
        default=True
    ) # type: ignore

    def execute(self, context):
        lines = paste_from_clipboard()
        if not lines:
            self.report({'ERROR'}, "剪贴板为空或无法访问,尝试使用ctrlshiftV粘贴到其他地方后重新剪切")
            return {'CANCELLED'}

        lst = (context.scene.ho_mapping_targetlist
               if self.isTargetList
               else context.scene.ho_mapping_searchlist)

        if self.clear_before:
            lst.clear()

        for name in lines:
            item = lst.add()
            item.name = name

        self.report({'INFO'}, f"成功粘贴 {len(lines)} 行")
        return {'FINISHED'}
    
class OT_Mapping_OpenTemplateFile(Operator):
    bl_idname = "ho.mapping_opentemplatefile"
    bl_label = "打开预设文件"
    bl_description = ""

    def execute(self, context):
        base_dir = os.path.dirname(__file__)
        rel_path = "MappingTemplate.csv"

        # 拼接成绝对路径
        abs_path = os.path.join(base_dir, rel_path)

        if not os.path.exists(abs_path):
            self.report({'ERROR'}, f"文件不存在: {abs_path}")
            return {'CANCELLED'}
        os.startfile(abs_path)
        return {'FINISHED'}


class OP_Mapping_AddItem(Operator):
    bl_idname = "ho.mapping_additem"
    bl_label = "添加到列表"
    bl_description = "所选数据添加到列表,自动根据当前模式，识别选中物体对应的的活动数据"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore

    def execute(self, context):
        mode = context.scene.ho_mapping_type
        obj = context.active_object
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist
        func :function = None
        if mode=='OBJECT_NAME':              func = MappingCore.getItemNames_Object
        if mode=='OBJECT_SHAPEKEY_NAME':     func = MappingCore.getItemNames_ObjectShapeKey
        if mode=='OBJECT_VERTEXGROUP_NAME':  func = MappingCore.getItemNames_ObjectVertexGroup
        if mode=='OBJECT_MATERIAL_NAME':     func = MappingCore.getItemNames_ObjectMaterial
        if mode=='ARMATURE_BONE_NAME':       func = MappingCore.getItemNames_ArmatureBone

        names = func(obj)
        #添加并移位
        for name in names:
            new_item = list.add()
            new_item.name = name
            selected_idx = next((i for i, item in enumerate(
                    list) if item.isSelected), None)
            if selected_idx is not None:
                list.move(len(list) - 1, selected_idx + 1)


        return {'FINISHED'}

class OP_Mapping_RemoveItem(Operator):
    bl_idname = "ho.mapping_removeitem"
    bl_label = "从列表删除"
    bl_description = "删除被勾选的对象"
    bl_options = {'REGISTER', 'UNDO'}
    isTargetList:BoolProperty(description="是否为目标列表",default=False) # type: ignore


    def execute(self, context):
        list = context.scene.ho_mapping_searchlist
        if self.isTargetList:
            list = context.scene.ho_mapping_targetlist
        # 逆序删除，避免索引问题
        for i in reversed(range(len(list))):
            if list[i].isSelected:
                list.remove(i)  # 删除勾选的骨骼
        return {'FINISHED'}

class MappingCore:
    @staticmethod  
    def set_object_mode(obj, mode):
        """暴力设置物体模式"""
        ctx = bpy.context
        view3d_ctx = bpy.context.copy()
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        view3d_ctx =  {
                            "area": area,
                            "region": region,
                            "window": bpy.context.window,
                            "screen": bpy.context.screen,
                            "active_object": obj,
                        }
        if "area" in view3d_ctx and "region" in view3d_ctx:
            if hasattr(ctx, "temp_override"):
                with ctx.temp_override(**view3d_ctx):
                    bpy.ops.object.mode_set(mode=mode)
            else:
                bpy.ops.object.mode_set(view3d_ctx, mode=mode)
        else:
            bpy.ops.object.mode_set(mode=mode)
    @staticmethod
    def objectNameMapping(obj, tList, sList):
        # 对象重命名
        if not obj:
            return True

        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')

        if len(tList) != len(sList):
            return True
        for tgt, src in zip(tList, sList):
            if obj.name == src.name:
                obj.name = tgt.name
                break

        # 恢复模式
        MappingCore.set_object_mode(obj, old_mode)
        return False

    @staticmethod
    def objectVertexGroupNameMapping(obj, tList, sList):
        # 顶点组重命名，仅针对网格对象
        if not obj:
            return True
        if obj.type != 'MESH':
            return True
        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')

        groups = obj.vertex_groups
        if len(tList) != len(sList):
            return True
        for tgt, src in zip(tList, sList):
            # 查找对应源组并重命名
            try:
                grp = groups[src.name]
                grp.name = tgt.name
            except KeyError:
                continue
        
        # 恢复模式
        MappingCore.set_object_mode(obj, old_mode)
        return False

    @staticmethod
    def objectShapeKeyNameMapping(obj, tList, sList):
        # 形态键重命名
        if not obj:
            return True
        data = obj.data
        if not hasattr(data, 'shape_keys') or data.shape_keys is None:
            return True
        
        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')

        blocks = data.shape_keys.key_blocks
        if len(tList) != len(sList):
            return True
        for tgt, src in zip(tList, sList):
            if src.name in blocks:
                blocks[src.name].name = tgt.name

        # 恢复模式
        MappingCore.set_object_mode(obj, old_mode)
        return False

    @staticmethod
    def objectMaterialNameMapping(obj, tList, sList):
        # 材质重命名
        if not obj:
            return True
        mats = []
        if hasattr(obj.data, 'materials'):
            mats = obj.data.materials
        if len(tList) != len(sList):
            return True
        
        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')

        for tgt, src in zip(tList, sList):
            for i, mat in enumerate(mats):
                if mat and mat.name == src.name:
                    mats[i].name = tgt.name
        
        # 恢复模式
        MappingCore.set_object_mode(obj, old_mode)
        return False
    @staticmethod
    def armatureBoneNameMapping(obj,tList,sList):
        old_mode = obj.mode
        armature = obj
        target_bones = tList
        source_bones = sList

        if not armature or armature.type != 'ARMATURE':
            return True

        if len(target_bones) != len(source_bones):
            return True

        # 确保模式正确
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        MappingCore.set_object_mode(armature,'EDIT')

        # 获取当前模型中所有的骨骼名称，存储在字典中
        bones = {
            bone.name: bone for bone in armature.data.edit_bones}

        # 遍历源骨骼和目标骨骼，并根据源骨骼名称进行匹配和重命名
        for tbns, sbns in zip(target_bones, source_bones):
            bn = sbns.name

            # 如果找到匹配的源骨骼，进行重命名
            if bn in bones:
                bones[bn].name = tbns.name

        # 恢复原模式
        bpy.context.view_layer.objects.active = armature
        if old_mode == 'EDIT':
            MappingCore.set_object_mode(obj,'EDIT')
        return False

    @staticmethod
    def getItemNames_Object(obj)->str:
        return [o.name for o in bpy.context.selected_objects]
        
    @staticmethod
    def getItemNames_ObjectVertexGroup(obj)->str:
        name = ""
        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')
        # 获取活动顶点组
        if obj.type == 'MESH' and hasattr(obj.vertex_groups, 'active_index'):
            idx = obj.vertex_groups.active_index
            if idx is not None and 0 <= idx < len(obj.vertex_groups):
                name = obj.vertex_groups[idx].name

        MappingCore.set_object_mode(obj, old_mode)
        return [name,]

    @staticmethod
    def getItemNames_ObjectShapeKey(obj)->str:
        old_mode = obj.mode
        name = ""
        MappingCore.set_object_mode(obj, 'OBJECT')
        data = obj.data
        if hasattr(data, 'shape_keys') and data.shape_keys:
            idx = getattr(obj, 'active_shape_key_index', None)
            blocks = data.shape_keys.key_blocks
            if idx is not None and 0 <= idx < len(blocks):
                name = blocks[idx].name
        MappingCore.set_object_mode(obj, old_mode)
        return [name,]

    @staticmethod
    def getItemNames_ObjectMaterial(obj)->str:
        old_mode = obj.mode
        MappingCore.set_object_mode(obj, 'OBJECT')
        # 获取活动材质
        mat = getattr(obj, 'active_material', None)
        name = mat.name if mat else ''
        MappingCore.set_object_mode(obj, old_mode)
        return [name,]

    @staticmethod
    def getItemNames_ArmatureBone(obj)->str:
        armature:bpy.types.Armature = obj
        old_mode = obj.mode
        names = []
        #保证骨架显示并为活动物体
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature

        if old_mode == "POSE":
            MappingCore.set_object_mode(armature,'EDIT')
        if old_mode == "EDIT":
            MappingCore.set_object_mode(armature,'POSE')

        if armature and armature.type == 'ARMATURE':
            names = [bone.name for bone in armature.data.bones if bone.select]

        #刷新并返回
        bpy.context.view_layer.objects.active = armature
        MappingCore.set_object_mode(armature,old_mode)   
           
        if was_hidden:
            armature.hide_set(True)
        return names


class OP_Mapping_BatchRename(Operator):
    bl_idname = "ho.mapping_batchrename"
    bl_label = "批量重命名"
    bl_description = "根据选择的模式与列表内容，重命名对象的数据"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = [context.active_object]
        if context.scene.ho_mapping_isAllselected:
            objs = []
            for obj in bpy.data.objects:
                if obj.select_get():
                    objs.append(obj)
        mode = context.scene.ho_mapping_type
        func :function = None
        if mode=='OBJECT_NAME':              func = MappingCore.objectNameMapping
        if mode=='OBJECT_SHAPEKEY_NAME':     func = MappingCore.objectShapeKeyNameMapping
        if mode=='OBJECT_VERTEXGROUP_NAME':  func = MappingCore.objectVertexGroupNameMapping
        if mode=='OBJECT_MATERIAL_NAME':     func = MappingCore.objectMaterialNameMapping
        if mode=='ARMATURE_BONE_NAME':       func = MappingCore.armatureBoneNameMapping

        #执行重命名
        for obj in objs:
            if func(obj,context.scene.ho_mapping_targetlist,context.scene.ho_mapping_searchlist):
                self.report({'WARNING'}, "重命名失败")
                return {'CANCELLED'}

        return {'FINISHED'}

MENU_PRESETS = []



class NameMappingTools(Panel):
    bl_idname = "VIEW_PT_Hollow_NameMappingTool"
    bl_label = "映射改名工具"
    # bl_space_type = "VIEW_3D"
    # bl_region_type = "UI"
    # bl_category = "HoTools"
    # bl_options = {'DEFAULT_CLOSED'}
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_parent_id = "PT_Main_HotoolsMainPanel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        # 左右标题
        row = layout.row(align=True)
        row.label(text="查找")
        row.label(text="替换")

        row = layout.row(align=True)

        # 左侧列表
        row_left = row.row(align=True)
        # 添加全选和取消全部选择按钮
        list = row_left.column(align=True)

        list.template_list("UL_Mapping_SearchItems", "",
                        scene, "ho_mapping_searchlist",
                        scene, "ho_mapping_searchlist_index",
                        rows=10)

        # 源骨骼操作按钮
        buttons = row_left.column(align=True)
        buttons.operator(OP_Mapping_SelectAllItems.bl_idname,
                        text="", icon="CHECKBOX_HLT").isTargetList = False
        buttons.operator(OP_Mapping_DeselectAllItems.bl_idname,
                        text="", icon="CHECKBOX_DEHLT").isTargetList = False
        buttons.operator(OP_Mapping_AddItem.bl_idname,
                        icon="ADD", text="").isTargetList = False
        buttons.operator(OP_Mapping_RemoveItem.bl_idname,
                        icon="REMOVE", text="").isTargetList = False
        buttons.operator(OP_Mapping_ClearItems.bl_idname,
                        icon="X", text="").isTargetList = False
        buttons.operator(OP_Mapping_MoveUpItems.bl_idname,
                        icon="TRIA_UP", text="").isTargetList = False
        buttons.operator(OP_Mapping_MoveDownItems.bl_idname,
                        icon="TRIA_DOWN", text="").isTargetList = False
        buttons.operator(OP_Mapping_MoveTopItems.bl_idname,
                        icon="TRIA_UP_BAR", text="").isTargetList = False
        buttons.operator(OP_Mapping_MoveBottomItems.bl_idname,
                        icon="TRIA_DOWN_BAR", text="").isTargetList = False
        buttons.operator(OP_Mapping_CopyListToClipboard.bl_idname,
                         icon="COPYDOWN",text="").isTargetList =  False
        buttons.operator(OP_Mapping_PasteListFromClipboard.bl_idname,
                         icon="PASTEDOWN",text="").isTargetList =  False
        

        # 右侧列表
        row_right = row.row(align=True)
        list = row_right.column(align=True)
        list.template_list("UL_Mapping_TargetItems", "",
                        scene, "ho_mapping_targetlist",
                        scene, "ho_mapping_targetlist_index",
                        rows=10)

        buttons = row_right.column(align=True)
        buttons.operator(OP_Mapping_SelectAllItems.bl_idname,
                        text="", icon="CHECKBOX_HLT").isTargetList = True
        buttons.operator(OP_Mapping_DeselectAllItems.bl_idname,
                        text="", icon="CHECKBOX_DEHLT").isTargetList = True
        buttons.operator(OP_Mapping_AddItem.bl_idname,
                        icon="ADD", text="").isTargetList = True
        buttons.operator(OP_Mapping_RemoveItem.bl_idname,
                        icon="REMOVE", text="").isTargetList = True
        buttons.operator(OP_Mapping_ClearItems.bl_idname,
                        icon="X", text="").isTargetList = True
        buttons.operator(OP_Mapping_MoveUpItems.bl_idname,
                        icon="TRIA_UP", text="").isTargetList = True
        buttons.operator(OP_Mapping_MoveDownItems.bl_idname,
                        icon="TRIA_DOWN", text="").isTargetList = True
        buttons.operator(OP_Mapping_MoveTopItems.bl_idname,
                        icon="TRIA_UP_BAR", text="").isTargetList = True
        buttons.operator(OP_Mapping_MoveBottomItems.bl_idname,
                        icon="TRIA_DOWN_BAR", text="").isTargetList = True
        buttons.operator(OP_Mapping_CopyListToClipboard.bl_idname,
                         icon="COPYDOWN",text="").isTargetList =  True
        buttons.operator(OP_Mapping_PasteListFromClipboard.bl_idname,
                         icon="PASTEDOWN",text="").isTargetList =  True
        

        # 第一行
        row = layout.row(align=True)
        txt = ""
        if context.active_object:
            txt = context.active_object.name
        row.label(text=txt)
        row.prop(scene,"ho_mapping_isAllselected")
        row.prop(scene,"ho_mapping_type",text="")
        #第二行
        col = layout.row(align=True)
        col.scale_y = 2.0
        row = col.row(align=True)
        row.operator(OP_Mapping_SwapList.bl_idname, text="", icon="MOD_MIRROR",)
        row.operator(OP_Mapping_BatchRename.bl_idname, text="重命名")

        row2 = row.row(align=True)  # 保存和加载预设的按钮
        row2.operator(OT_Mapping_OpenTemplateFile.bl_idname,text="",icon="HELP")


        
cls = [PG_MappingItem,UL_Mapping_TargetItems,UL_Mapping_SearchItems,
       OP_Mapping_SwapList,OP_Mapping_RemoveListItems,OP_Mapping_ClearItems,
       OP_Mapping_MoveUpItems,OP_Mapping_MoveDownItems,OP_Mapping_MoveTopItems,OP_Mapping_MoveBottomItems,
       OP_Mapping_SelectAllItems,OP_Mapping_DeselectAllItems,
       OP_Mapping_AddItem,OP_Mapping_RemoveItem,
       OP_Mapping_BatchRename,
       NameMappingTools,OP_Mapping_CopyListToClipboard,OP_Mapping_PasteListFromClipboard,OT_Mapping_OpenTemplateFile
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
