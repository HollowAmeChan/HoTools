import bpy
import re
import os
import json
from bpy.types import Operator, UILayout, Context, PropertyGroup, UIList
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty

# region 变量


class PG_renameRule(PropertyGroup):
    enum_items = [
        ('MOD_FIXED_STRING', "字符", "固定字符"),
        ('MOD_CHAIN', "链", "拥有相同父级的骨骼视为同一层，递增：如A、B、C...当出现分叉时链名会固定，然后考虑下一个链名规则。递增只发生在语义上的最后一位，因此可以写HairA"),
        ('MOD_DEPTH', "深度", "从无父骨层级查询到当前骨的深度，递增只发生在语义上的最后一位，因此可以写d01、001"),
    ]
    type: EnumProperty(name="Mod", items=enum_items) # type: ignore
    fixedStr: StringProperty(name="字符", default="Bone") # type: ignore
    chainStr: StringProperty(name="链名", default="A", description="分叉时递增(A,B..)") # type: ignore
    deepStr: StringProperty(name="深度", default="01", description="沿链条向下递增(01,02..)") # type: ignore

class UL_RuleList(UIList):
    def draw_item(self, context, layout: UILayout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        tmp = row.row(align=True)
        tmp.scale_x = 0.5
        tmp.prop(item, "type", text="")  # 绘制枚举类型

        if item.type == 'MOD_FIXED_STRING':
            row.prop(item, "fixedStr", text="")
        if item.type == 'MOD_CHAIN':
            row.prop(item, "chainStr", text="")
        if item.type == 'MOD_DEPTH':
            row.prop(item, "deepStr", text="")
        # 留空以便选择
        tmp = row.row(align=True)
        tmp.scale_x = 0.4
        tmp.label(text=" ")  # 占位

class PG_changenameRule(PropertyGroup):
    # 枚举类型('identifier', "name", "description")
    enum_items = [
        ('MOD_HEAD', "头←", "头部添加"),
        ('MOD_TAIL', "尾→", "尾部添加"),
        ('MOD_REPLACE', "替", "检查并替换")
    ]
    type: EnumProperty(name="Mod", items=enum_items)  # type: ignore
    targetStr: StringProperty(name="Target String")  # type: ignore
    # 替换相关
    sourceStr: StringProperty(name="Source String")  # type: ignore
    isCheckLower: BoolProperty(
        name="CheckLower?", description="区分大小写", default=True)  # type: ignore

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
    # TODO
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
    bl_label = "链叉重命名"
    bl_description = "建议使用预设来学习用法"
    bl_options = {'REGISTER', 'UNDO'}

    def increment_string(self, s: str, times: int = 0) -> str:
        if times <= 0: return s
        result = s
        for _ in range(times):
            if result.isdigit():
                result = str(int(result) + 1).zfill(len(result))
            elif result.isalpha():
                chars = list(result)
                i = len(chars) - 1
                while i >= 0:
                    c = chars[i]
                    if c in ('z', 'Z'):
                        chars[i] = 'a' if c == 'z' else 'A'
                        i -= 1
                    else:
                        chars[i] = chr(ord(c) + 1)
                        result = ''.join(chars)
                        break
                else:
                    result = ('a' if result[0].islower() else 'A') + ''.join(chars)
            else:
                match = re.search(r'(\d+)$', result)
                if match:
                    num = match.group(1)
                    result = result[:-len(num)] + str(int(num) + 1).zfill(len(num))
                else:
                    result = result + "1"
        return result

    def execute(self, context):
        obj = context.active_object
        rules = context.scene.ho_boneRename_rules
        selected_bones = [b for b in obj.data.bones if b.select]
        
        if not selected_bones:
            return {'CANCELLED'}

        # 1. 找到所有的根骨骼
        roots = [b for b in selected_bones if b.parent not in selected_bones]

        # 2. 递归扫描拓扑结构，存储每个骨骼的“链信息”
        # bone_data 格式: { bone_pointer: { 'chains': [idx0, idx1...], 'depth': int } }
        self.bone_topology_data = {}
        
        for root in roots:
            # 根骨骼初始：链层级0，该层级分叉索引由root在所有根中的顺序决定
            root_idx = roots.index(root)
            self.scan_topology(root, [root_idx], 0, selected_bones)

        # 3. 根据扫描到的数据，对照 rules 统一渲染名字
        for bone, data in self.bone_topology_data.items():
            new_name_parts = []
            chain_rule_count = 0
            
            for rule in rules:
                if rule.type == 'MOD_FIXED_STRING':
                    new_name_parts.append(rule.fixedStr)
                
                elif rule.type == 'MOD_CHAIN':
                    # 只有当骨骼拥有对应层级的链信息时才添加
                    if chain_rule_count < len(data['chains']):
                        val_idx = data['chains'][chain_rule_count]
                        new_name_parts.append(self.increment_string(rule.chainStr, val_idx))
                    chain_rule_count += 1
                
                elif rule.type == 'MOD_DEPTH':
                    new_name_parts.append(self.increment_string(rule.deepStr, data['depth']))

            bone.name = "_".join(new_name_parts)

        return {'FINISHED'}

    def scan_topology(self, bone, current_chains, depth, scope):
        """
        current_chains: 列表，存储从祖先到当前骨骼每一级分叉的索引值
        """
        # 记录当前骨骼数据
        self.bone_topology_data[bone] = {
            'chains': current_chains,
            'depth': depth
        }

        # 获取在选中范围内的子骨骼
        children = [b for b in bone.children if b in scope]
        
        for i, child in enumerate(children):
            next_chains = list(current_chains)
            
            if len(children) > 1:
                # 发生分叉：子级开启一个新的链层级，记录它是第几个分叉
                next_chains.append(i)
                # 分叉后，子级的局部深度是否重置？
                # 按照常规骨骼命名，深度通常是全局增长的，所以这里保持 depth + 1
            else:
                # 单传：继承父级的链条索引，不增加新的链层级
                pass
            
            self.scan_topology(child, next_chains, depth + 1, scope)

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

class OP_AddRenamePreset(Operator):
    bl_idname = "ho.rename_add_preset"
    bl_label = "添加命名预设"
    bl_description = "快速添加常用的骨骼重命名规则组合"
    bl_options = {'REGISTER', 'UNDO'}

    preset_type: bpy.props.EnumProperty(
        items=[
            ('DEFAULT', "默认", "适用于复杂分叉(不超过三次分叉)：Bone_A_A_A_01"),
            ('SHORT', "短", "稍短(不超过三次分叉)：Bone01_A_A_01"),
        ],
        name="预设类型"
    ) # type: ignore

    def execute(self, context):
        rules = context.scene.ho_boneRename_rules
        rules.clear()  # 清空当前所有规则

        if self.preset_type == 'DEFAULT':
            r = rules.add(); r.type = 'MOD_FIXED_STRING'; r.fixedStr = "Bone"
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "A"
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "A"
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "A"
            r = rules.add(); r.type = 'MOD_DEPTH'; r.deepStr = "01"
        if self.preset_type == 'SHORT':
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "Bone01"
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "A"
            r = rules.add(); r.type = 'MOD_CHAIN'; r.chainStr = "A"
            r = rules.add(); r.type = 'MOD_DEPTH'; r.deepStr = "01"

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
    row1.operator_menu_enum(OP_AddRenamePreset.bl_idname, "preset_type", text="", icon='PRESET')

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
       OP_SaveChangeRules, OP_LoadChangeRules,OP_AddRenamePreset,
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
