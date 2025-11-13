import bpy
import re
import os
import json
from bpy.types import Operator, UILayout, Context, PropertyGroup, UIList
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty

# region 变量


class PG_renameRule(PropertyGroup):
    # 枚举类型('identifier', "name", "description")
    enum_items = [
        ('MOD_FIXED_STRING', "固定", "固定添加的字符"),
        ('MOD_VARIABLE', "可变", "随着骨骼链递增"),
    ]
    type: EnumProperty(name="Mod", items=enum_items)  # type: ignore
    targetStr: StringProperty(name="Target String")  # type: ignore
    startNum: IntProperty(name="Start Number", default=1)  # type: ignore


class PG_changenameRule(PropertyGroup):
    # 枚举类型('identifier', "name", "description")
    enum_items = [
        ('MOD_HEAD', "头←", "头部添加"),
        ('MOD_TAIL', "尾→", "尾部添加"),
        ('MOD_REPLACE', "替换", "检查并替换")
    ]
    type: EnumProperty(name="Mod", items=enum_items)  # type: ignore
    targetStr: StringProperty(name="Target String")  # type: ignore
    # 替换相关
    sourceStr: StringProperty(name="Source String")  # type: ignore
    isCheckLower: BoolProperty(
        name="CheckLower?", description="区分大小写", default=True)  # type: ignore


class UL_RuleList(UIList):
    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        tmp = row.row(align=True)
        tmp.scale_x = 0.5
        tmp.prop(item, "type", text="")  # 绘制枚举类型

        if item.type == 'MOD_FIXED_STRING':
            row.prop(item, "targetStr", text="")
        if item.type == 'MOD_VARIABLE':
            row.prop(item, "startNum", text="")
        # 留空以便选择
        tmp = row.row(align=True)
        tmp.scale_x = 0.4
        tmp.label(text=" ")  # 占位


class UL_ChangeRuleList(UIList):
    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        tmp = row.row(align=True)
        tmp.scale_x = 0.5
        tmp.prop(item, "type", text="")  # 绘制枚举类型

        if item.type == 'MOD_REPLACE':
            row.prop(item, "isCheckLower", icon="SYNTAX_OFF", icon_only=True)
            row.prop(item, "sourceStr", text="")
        row.prop(item, "targetStr", text="")
        op = row.operator("ho.rename_rulechangenameboneselected",
                          text="", icon="FILE_REFRESH")
        op.index = index

        # 留空以便选择
        tmp = row.row(align=True)
        tmp.scale_x = 0.4
        tmp.label(text=" ")  # 占位


def reg_props():
    # renameRule集合属性
    bpy.types.Scene.ho_boneRename_rules = CollectionProperty(
        type=PG_renameRule)
    # renameRule的UIlist中当前选中索引(在绘制时进行的绑定)
    bpy.types.Scene.ho_boneRename_rules_index = IntProperty()
    # changeRule集合属性
    bpy.types.Scene.ho_boneRename_change_rules = CollectionProperty(
        type=PG_changenameRule)
    # changeRule的UIlist中当前选中索引(在绘制时进行的绑定)
    bpy.types.Scene.ho_boneRename_change_rules_index = IntProperty()
    return


def ureg_props():
    del bpy.types.Scene.ho_boneRename_rules
    del bpy.types.Scene.ho_boneRename_rules_index
    del bpy.types.Scene.ho_boneRename_change_rules
    del bpy.types.Scene.ho_boneRename_change_rules_index
    return
# endregion

# region 操作


class OP_SaveRules(Operator):
    bl_idname = "ho.rename_saverules"
    bl_label = "Save Rules"
    bl_description = "保存规则重命名的规则到磁盘"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene
        rules = scene.ho_boneRename_rules

        # 检查文件路径，确保有 .json 后缀
        if not self.filepath.endswith('.json'):
            self.filepath += '.json'

        # 将CollectionProperty序列化为JSON
        data = [{"type": rule.type,
                 "targetStr": rule.targetStr,
                 "startNum": rule.startNum}
                for rule in rules]

        # 保存到指定的文件路径
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        self.report({'INFO'}, f"Rename rules saved to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        self.filepath = self.filepath or "rules.json"  # 设置默认文件名
        return {'RUNNING_MODAL'}


class OP_LoadRules(Operator):
    bl_idname = "ho.rename_loadrules"
    bl_label = "Save Rules"
    bl_description = "从磁盘加载规则重命名的规则"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene

        # 读取文件
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}

        with open(self.filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 清空现有的CollectionProperty
        scene.ho_boneRename_rules.clear()

        # 反序列化并将数据添加到CollectionProperty
        for entry in data:
            rule = scene.ho_boneRename_rules.add()
            rule.type = entry.get("type", "")
            rule.targetStr = entry.get("targetStr", "")
            rule.startNum = entry.get("startNum", 1)

        self.report({'INFO'}, f"Rename rules loaded from {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 打开文件选择窗口
        context.window_manager.fileselect_add(self)
        self.filepath = self.filepath or "rules.json"  # 设置默认文件名
        return {'RUNNING_MODAL'}


class OP_SaveChangeRules(Operator):
    bl_idname = "ho.rename_savechangerules"
    bl_label = "Save Rules"
    bl_description = "保存规则到磁盘"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene
        rules = scene.ho_boneRename_change_rules

        # 检查文件路径，确保有 .json 后缀
        if not self.filepath.endswith('.json'):
            self.filepath += '.json'

        # 将CollectionProperty序列化为JSON
        data = [{"type": rule.type,
                 "targetStr": rule.targetStr,
                 "sourceStr": rule.sourceStr,
                 "isCheckLower": rule.isCheckLower}
                for rule in rules]

        # 保存到指定的文件路径
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

        self.report({'INFO'}, f"Change name rules saved to {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        self.filepath = self.filepath or "rules.json"  # 设置默认文件名
        return {'RUNNING_MODAL'}


class OP_LoadChangeRules(Operator):
    bl_idname = "ho.rename_loadchangerules"
    bl_label = "Save Rules"
    bl_description = "从磁盘加载规则"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")  # type: ignore

    def execute(self, context):
        scene = context.scene

        # 读取文件
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}

        with open(self.filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 清空现有的CollectionProperty
        scene.ho_boneRename_change_rules.clear()

        # 反序列化并将数据添加到CollectionProperty
        for entry in data:
            rule = scene.ho_boneRename_change_rules.add()
            rule.type = entry.get("type", "")
            rule.targetStr = entry.get("targetStr", "")
            rule.sourceStr = entry.get("sourceStr", "")
            rule.isCheckLower = entry.get("isCheckLower", True)

        self.report({'INFO'}, f"Change name rules loaded from {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        # 打开文件选择窗口
        context.window_manager.fileselect_add(self)
        self.filepath = self.filepath or "rules.json"  # 设置默认文件名
        return {'RUNNING_MODAL'}


class OP_MoveRule(Operator):
    bl_idname = "ho.rename_moverule"
    bl_label = "Move Rule"
    bl_description = "将选择的规则移动"
    bl_options = {'REGISTER', 'UNDO'}

    mode: BoolProperty(name="Move dir 0:up 1:down",
                       default=False)  # type: ignore

    def execute(self, context):
        # 上移
        index = context.scene.ho_boneRename_rules_index
        if self.mode == False and index > 0:
            context.scene.ho_boneRename_rules.move(index, index - 1)
            context.scene.ho_boneRename_rules_index -= 1
            return {'FINISHED'}
        # 下移
        if self.mode == True and index < (len(context.scene.ho_boneRename_rules)-1):
            context.scene.ho_boneRename_rules.move(index, index + 1)
            context.scene.ho_boneRename_rules_index += 1
            return {'FINISHED'}
        return {'FINISHED'}


class OP_MoveChangeRule(Operator):
    bl_idname = "ho.rename_movechangerule"
    bl_label = "Move Rule"
    bl_description = "将选择的规则移动"
    bl_options = {'REGISTER', 'UNDO'}

    mode: BoolProperty(name="Move dir 0:up 1:down",
                       default=False)  # type: ignore

    def execute(self, context):
        # 上移
        index = context.scene.ho_boneRename_change_rules_index
        if self.mode == False and index > 0:
            context.scene.ho_boneRename_change_rules.move(index, index - 1)
            context.scene.ho_boneRename_change_rules_index -= 1
            return {'FINISHED'}
        # 下移
        if self.mode == True and index < (len(context.scene.ho_boneRename_change_rules)-1):
            context.scene.ho_boneRename_change_rules.move(index, index + 1)
            context.scene.ho_boneRename_change_rules_index += 1
            return {'FINISHED'}
        return {'FINISHED'}


class OP_RemoveNumberTail(Operator):
    bl_idname = "ho.rename_removenumbertail"
    bl_label = "Remove BoneName Number Tail"
    bl_description = "删除骨骼的.001等数字后缀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = bpy.context.active_object
        # 检查对象是否是骨骼
        if armature and armature.type == 'ARMATURE':
            suffix_pattern = r'\.\d{3}$'

            # 遍历所有选中的骨骼
            for bone in armature.data.bones:
                if bone.select:
                    # 修改骨骼名称，去掉后缀
                    original_name = bone.name
                    new_name = re.sub(suffix_pattern, '', original_name)
                    bone.name = new_name

        return {'FINISHED'}


class OP_RemoveSideTail(Operator):
    bl_idname = "ho.rename_removesidetail"
    bl_label = "Remove BoneName Side Tail(.l .r .L .R)"
    bl_description = "删除骨骼的.l/r/L/R后缀"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = bpy.context.active_object
        # 检查对象是否是骨骼
        if armature and armature.type == 'ARMATURE':
            suffix_pattern = r'\.[RrLl]$'

            # 遍历所有选中的骨骼
            for bone in armature.data.bones:
                if bone.select:
                    # 修改骨骼名称，去掉后缀
                    original_name = bone.name
                    new_name = re.sub(suffix_pattern, '', original_name)
                    bone.name = new_name

        return {'FINISHED'}


class OP_RuleRenameBoneSelected(Operator):
    bl_idname = "ho.rename_rulerenameboneselected"
    bl_label = "对选择的骨骼链进行规则重命名，多条链将依次重命名"
    bl_options = {'REGISTER', 'UNDO'}

    def sort_bones_by_hierarchy(self, bones: list) -> list:
        """
        按照父子级关系将骨骼集合排序
        """

        def collect_hierarchy(bone):  # 递归函数获取骨骼的所有子骨骼，只处理选中的子骨骼
            hierarchy = [bone]
            for child in bone.children:
                if child in bones:  # 只处理选中的子骨骼
                    hierarchy.extend(collect_hierarchy(child))
            return hierarchy

        # 找到所有没有父级的选中骨骼（根骨骼）
        root_bones = [
            bone for bone in bones if bone.parent is None or bone.parent not in bones]
        # 按层次结构排序，只处理选中的骨骼
        sorted_bones = []
        for root in root_bones:
            sorted_bones.extend(collect_hierarchy(root))

        return sorted_bones

    def rename_bones_byRules(self, context, bones: list):
        rules = context.scene.ho_boneRename_rules
        stratNumCopy = []
        newnames = []
        for rule in rules:
            if rule.type == "MOD_VARIABLE":
                stratNumCopy.append(rule.startNum)

        for i in range(len(bones)):
            ruleNumIndex = 0
            newname = ""
            for j in range(len(rules)):
                rule = rules[j]
                if rule.type == "MOD_FIXED_STRING":
                    newname += rule.targetStr
                if rule.type == "MOD_VARIABLE":
                    newname += str(stratNumCopy[ruleNumIndex])
                    stratNumCopy[ruleNumIndex] += 1
                    ruleNumIndex += 1
            newnames.append(newname)

        for i in range(len(bones)):
            bone = bones[i]
            bone.name = newnames[i]

    def execute(self, context):
        armature = bpy.context.active_object
        if not (armature and armature.type == 'ARMATURE'):
            return {'FINISHED'}
        
        current_mode = armature.mode
        bpy.ops.object.mode_set(mode='OBJECT')#强制更新

        # 获取当前选中的骨骼列表
        selected_bones = [
            bone for bone in armature.data.bones if bone.select]
        # 按照父子级关系排序（存的是指针
        sorted_bones = self.sort_bones_by_hierarchy(selected_bones)
        # 按照规则重命名
        self.rename_bones_byRules(context, sorted_bones)
        # 再运行一遍，防止有冲突命名自动加了.001后缀
        self.rename_bones_byRules(context, sorted_bones)

        bpy.ops.object.mode_set(mode=current_mode)

        return {'FINISHED'}


class OP_RuleChangeNameBoneSelected(Operator):
    bl_idname = "ho.rename_rulechangenameboneselected"
    bl_label = "执行骨骼重命名"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(name="Index", default=0)  # type: ignore

    def execute(self, context):
        armature = bpy.context.active_object

        if not (armature and armature.type == 'ARMATURE'):
            return {'FINISHED'}
        
        current_mode = armature.mode
        bpy.ops.object.mode_set(mode='OBJECT')#强制更新
        
        # 获取当前选中的骨骼列表
        selected_bones = [
            bone for bone in armature.data.bones if bone.select]

        changerule = context.scene.ho_boneRename_change_rules[self.index]

        if changerule.type == "MOD_HEAD":
            for bone in selected_bones:
                bone.name = changerule.targetStr + bone.name
        if changerule.type == "MOD_TAIL":
            for bone in selected_bones:
                bone.name = bone.name + changerule.targetStr
        if changerule.type == "MOD_REPLACE":
            #转义sourceStr，防止用户填入正则表达式
            pattern = re.compile(re.escape(changerule.sourceStr), flags=re.IGNORECASE)
            for bone in selected_bones:
                if changerule.isCheckLower:  # 匹配大小写
                    # bone.name = re.sub(
                    #     changerule.sourceStr, changerule.targetStr, bone.name)
                    bone.name = bone.name.replace(changerule.sourceStr, changerule.targetStr)
                else:
                    # 忽略大小写
                    # bone.name = re.sub(
                    #     changerule.sourceStr, changerule.targetStr, bone.name, flags=re.IGNORECASE)
                    bone.name = pattern.sub(changerule.targetStr, bone.name)

        
        bpy.ops.object.mode_set(mode=current_mode)

        return {'FINISHED'}


class OP_AddRule(Operator):
    bl_idname = "ho.rename_addrule"
    bl_label = "Add Rename Rule"

    def execute(self, context):
        scene = context.scene
        scene.ho_boneRename_rules.add()  # 添加新的 renameRule
        return {'FINISHED'}


class OP_RemoveRule(Operator):
    bl_idname = "ho.rename_removerule"
    bl_label = "Remove Rename Rule"

    def execute(self, context):
        scene = context.scene
        if scene.ho_boneRename_rules:
            scene.ho_boneRename_rules.remove(
                scene.ho_boneRename_rules_index)  # 删除选中的 renameRule
            scene.ho_boneRename_rules_index = max(
                0, scene.ho_boneRename_rules_index - 1)  # 更新索引
        return {'FINISHED'}


class OP_AddChangeRule(Operator):
    bl_idname = "ho.rename_addchangerule"
    bl_label = "Add ChangeName Rule"

    def execute(self, context):
        scene = context.scene
        scene.ho_boneRename_change_rules.add()  # 添加新的 renameRule
        return {'FINISHED'}


class OP_RemoveChangeRule(Operator):
    bl_idname = "ho.rename_removechangerule"
    bl_label = "Remove ChangeName Rule"

    def execute(self, context):
        scene = context.scene
        if scene.ho_boneRename_change_rules:
            scene.ho_boneRename_change_rules.remove(
                scene.ho_boneRename_change_rules_index)  # 删除选中的 renameRule
            scene.ho_boneRename_change_rules_index = max(
                0, scene.ho_boneRename_change_rules_index - 1)  # 更新索引
        return {'FINISHED'}
# endregion


# region 面板

def drawBoneRenamePanel(layout: UILayout, context: Context):
    scene = context.scene
    # ------------------------------
    layout.label(text="批量规则：")
    row = layout.row(align=True)  # 左右两列
    # 左侧UIList
    col1 = row.column()
    col1.template_list("UL_RuleList", "", scene,
                       "ho_boneRename_rules", scene, "ho_boneRename_rules_index")

    # 右侧按钮
    col2 = row.column(align=True)
    col2.operator(OP_AddRule.bl_idname, text="", icon="ADD")
    col2.operator(OP_RemoveRule.bl_idname, text="", icon="REMOVE")
    up = col2.operator(OP_MoveRule.bl_idname, text="", icon="TRIA_UP")
    up.mode = False
    down = col2.operator(OP_MoveRule.bl_idname, text="", icon="TRIA_DOWN")
    down.mode = True
    col2.operator(OP_SaveRules.bl_idname, text="", icon="FILE_TICK")
    col2.operator(OP_LoadRules.bl_idname, text="", icon="FILEBROWSER")

    # 下方功能
    col = layout.column(align=True)
    row1 = col.row(align=True)
    row1.scale_y = 2.0
    row1.operator(OP_RuleRenameBoneSelected.bl_idname, text="重命名")

    row2 = col.row(align=True)
    row2.operator(OP_RemoveNumberTail.bl_idname, text="去除数字后缀")
    row2.operator(OP_RemoveSideTail.bl_idname, text="去除.L.R后缀")
    # ------------------------------
    layout.label(text="规则修改：")
    row = layout.row(align=True)  # 左右两列
    # 左侧UIList
    col1 = row.column()
    col1.template_list("UL_ChangeRuleList", "", scene,
                       "ho_boneRename_change_rules", scene, "ho_boneRename_change_rules_index")
    # 右侧按钮
    col2 = row.column(align=True)
    col2.operator(OP_AddChangeRule.bl_idname, text="", icon="ADD")
    col2.operator(OP_RemoveChangeRule.bl_idname, text="", icon="REMOVE")
    up = col2.operator(OP_MoveChangeRule.bl_idname, text="", icon="TRIA_UP")
    up.mode = False
    down = col2.operator(OP_MoveChangeRule.bl_idname,
                         text="", icon="TRIA_DOWN")
    down.mode = True
    col2.operator(OP_SaveChangeRules.bl_idname, text="", icon="FILE_TICK")
    col2.operator(OP_LoadChangeRules.bl_idname, text="", icon="FILEBROWSER")
    return
# endregion


cls = [PG_renameRule, PG_changenameRule,
       UL_RuleList, UL_ChangeRuleList,
       OP_SaveRules, OP_LoadRules,
       OP_SaveChangeRules, OP_LoadChangeRules,
       OP_RemoveNumberTail, OP_RemoveSideTail,
       OP_AddRule, OP_RemoveRule, OP_MoveRule,
       OP_AddChangeRule, OP_RemoveChangeRule, OP_MoveChangeRule,
       OP_RuleRenameBoneSelected, OP_RuleChangeNameBoneSelected
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
