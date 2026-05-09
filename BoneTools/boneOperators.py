import bpy
from mathutils import Vector
import numpy as np
from bpy.types import PropertyGroup, UIList, Operator, Panel,Menu
from bpy.types import UILayout, Context
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,FloatProperty,IntProperty
from .boneSplit import OP_SplitBoneWithWeight
from .boneDissolve import OP_DissolveBoneWithWeight




class PG_Hotools_BoneProps(PropertyGroup):
    keepRotation: bpy.props.BoolProperty(
        name="保留旋转",
        description="在使用hotools fbx导出时,如果这段骨骼不保留旋转,将会自动将骨骼竖直，注意会导致这段骨骼后续的叶骨添加错误",
        default=True) # type: ignore
    endBone:bpy.props.BoolProperty(
        name="叶骨",
        description="Hotools是否将骨骼标记为叶骨",
        default=False) # type: ignore
    humanoidMapping: bpy.props.StringProperty(
        name="Humanoid映射",
        description="定义此骨对应Unity-Humannoid标准骨",
        default="") # type: ignore

def reg_props():
    bpy.types.Bone.hotools_boneprops = bpy.props.PointerProperty(type=PG_Hotools_BoneProps)


def ureg_props():
    del bpy.types.Bone.hotools_boneprops

class OP_ApplyRestPose(Operator):
    bl_idname = "ho.apply_rest_pose"
    bl_label = "应用骨架与网格为当前姿势"
    bl_description = "与此同时会智能处理带形态键的绑定物体"
    bl_options = {'REGISTER', 'UNDO'}

    def draw(self, context):
        self.layout.label(text="本操作将应用骨架所有子级网格的全部'骨架'修改器")
        self.layout.label(text="同时应用掉现在的姿态为静置姿态")
        self.layout.label(text="如果子级网格物体有形态键，将会调用额外操作保证形态家的保留")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def process_object(self, context, obj):
        """智能处理单个物体"""

        # 检查是否需要特殊处理形态键
        needs_shapekey_processing = (
            obj.data.shape_keys and
            len(obj.data.shape_keys.key_blocks) > 1
        )

        # 如果有复杂形态键则使用新方法
        if needs_shapekey_processing:
            try:
                # 设置当前活动对象
                bpy.context.view_layer.objects.active = obj
                if obj.select_get() is False:
                    obj.select_set(True)

                # 调用形态键保留操作符
                bpy.ops.ho.apply_armature_modifiers_keepshapekeys()
                return True
            except Exception as e:
                self.report({'WARNING'}, f"形态键处理失败: {str(e)}")
                return False
        # 普通处理流程
        else:
            for mod in obj.modifiers[:]:
                if mod.type == 'ARMATURE' and mod.show_viewport:
                    try:
                        with bpy.context.temp_override(object=obj, modifier=mod):
                            bpy.ops.object.modifier_apply(modifier=mod.name)
                    except Exception as e:
                        self.report(
                            {'WARNING'}, f"应用失败: {obj.name} 的 {mod.name}")
                        continue
            return True

    def execute(self, context):

        armature = context.active_object
        original_mode = armature.mode

        # 获取所有绑定物体（包含间接子级）
        mesh_objects = [
            obj for obj in armature.children_recursive
            if obj.type == 'MESH' and
            any(m.type == 'ARMATURE' for m in obj.modifiers)
        ]
        # print(mesh_objects[:])

        if not mesh_objects:
            self.report({'WARNING'}, "没有找到绑定到该骨架的网格对象")
            return {'CANCELLED'}

        # 切换到 OBJECT 模式
        bpy.ops.object.mode_set(mode='OBJECT')

        # 处理所有网格物体
        success_count = 0
        for obj in mesh_objects:
            if self.process_object(context, obj):
                success_count += 1
                

        # 应用骨架姿态
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.armature_apply()
        bpy.ops.object.mode_set(mode=original_mode)

        # 再次获取绑定的物体(防止进行行改期应用过程中，有物体的变动的情况)#TODO 这里又不用看有没有骨架修改器了，一锅端不太好，但是没办法了
        mesh_objects = [
            obj for obj in armature.children_recursive if obj.type == 'MESH'
        ]

        # 重新添加骨架修改器
        for obj in mesh_objects:
            new_mod = obj.modifiers.new(
                name="Armature", type='ARMATURE')
            new_mod.object = armature
            print(obj.name,"恢复阶段成功")

        self.report({'INFO'}, "成功处理"+ str(success_count) + "/" + str(len(mesh_objects)) +"个物体")
        return {'FINISHED'}

class OP_ForceClearBoneRotation(Operator):
    bl_idname = "ho.force_clear_bone_rotation"
    bl_label = "强制骨骼变换"
    bl_description = "强制移除所选骨骼的变换,保证导出后旋转为0"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
       return True

    def execute(self, context):
        if bpy.context.mode != 'EDIT_ARMATURE':
            print("不在骨骼编辑模式下")
        else:
            armature = bpy.context.object.data
            armature.use_mirror_x = False #!!!必须关闭所有骨架的对称，否则处理会有底层逻辑上的问题
            selected_bones = [b for b in armature.edit_bones if b.select]

            for bone in selected_bones:
                for cb in bone.children:#清空所有子骨的相连，防止影响子骨头部位置
                    cb.use_connect = False
                original_length = (bone.tail - bone.head).length
                bone.roll = 0
                new_tail = bone.head + Vector((0, 0, original_length))
                bone.tail = new_tail
        return {'FINISHED'}
       
class OP_AddEndBone(Operator):
    bl_idname = "ho.add_endbone"
    bl_label = "添加叶骨"
    bl_description = "给当前选中骨添加叶骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'ARMATURE'  and obj.mode == "EDIT" and context.active_bone is not None

    def execute(self, context):
        obj = context.object
        arm = obj.data
        ebones = arm.edit_bones

        selected_bones = [bone for bone in ebones if bone.select]
        end_bones = []
        for bone in selected_bones:
            end_bone_name = bone.name + "_end"
            if end_bone_name in ebones:
                self.report({'WARNING'}, f"{end_bone_name} 已存在，跳过")
                continue
            new_bone:bpy.types.EditBone  
            new_bone = ebones.new(end_bone_name)
            new_bone.head = bone.tail
            direction = (bone.tail - bone.head).normalized() if (bone.tail - bone.head).length > 0 else Vector((0, 0, 0.1))
            new_bone.tail = new_bone.head + direction * 0.1  # 可调长度
            new_bone.parent = bone
            new_bone.use_connect = True #相连项开
            new_bone.use_deform = False #形变关
            end_bones.append(new_bone.name)

        #刷新bones，再修改属性
        bpy.ops.object.mode_set(mode="OBJECT")
        for bn in end_bones:
            b = arm.bones[bn]
            b.hotools_boneprops.keepRotation = False
            b.hotools_boneprops.endBone = True
        bpy.ops.object.mode_set(mode="EDIT")

        return {'FINISHED'}

class OP_SelectBoneBy_by_KeepRotation(Operator):
    bl_idname = "ho.selectbone_by_keeprotation"
    bl_label = "选择相似骨骼-保留旋转"
    bl_description = "选择相似骨骼-按照Hotools骨骼keepRotation保留旋转属性"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_bone != None

    def execute(self, context):
        active_bone = context.active_bone
        bones = context.active_object.data.bones
        for bone in bones:
            if bone.hotools_boneprops.keepRotation == active_bone.hotools_boneprops.keepRotation:
                bone.select = True
        return {'FINISHED'}
    
class OP_SelectBone_by_endBone(Operator):
    bl_idname = "ho.selectbone_by_endbone"
    bl_label = "选择叶骨"
    bl_description = "选择所有的叶骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        arm_obj = context.object
        arm_data = arm_obj.data
        bones = arm_data.bones
        for b in bones:
            if b.hotools_boneprops.endBone:
                b.select = True

        return {'FINISHED'}

class OP_SelectBone_by_Nochild(Operator):
    bl_idname = "ho.selectbone_by_nochild"
    bl_label = "选择当前尾端骨"
    bl_description = "选择当前选中骨中的尾端骨"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_bone != None

    def execute(self, context):
        arm_obj = context.object
        arm_data = arm_obj.data
        bones = arm_data.bones
        end_bones = [eb for eb in bones if eb.select and len(eb.children) == 0]
        if not end_bones:
            self.report({'WARNING'}, "当前选中骨骼中没有末端骨")
            return {'CANCELLED'}
        for eb in bones:
            eb.select = False
        for eb in end_bones:
            eb.select = True
        arm_obj.data.bones.active = end_bones[0]
        return {'FINISHED'}

class OP_Fix_EmptyRotate_Bone(Operator):
    bl_idname = "ho.fix_empty_rotate_bone"
    bl_label = "修复空旋转的骨骼"
    bl_description = """另选中中骨骼的tail位置设定为子级骨骼的head位置(若有多个子级则设置为平均位置)
                        若没有子级则将tail位置设置在自己的父级与自己连线的延长线上(保持自己的骨骼长度)"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE' and context.active_bone is not None

    def execute(self, context):
        armature = context.object.data
        armature.use_mirror_x = False  # 禁用对称，否则有同步问题

        selected_bones = [b for b in armature.edit_bones if b.select]

        for bone in selected_bones:
            children = [b for b in armature.edit_bones if b.parent == bone]
            
            if children:
                # 有子骨骼：取子骨骼 head 的平均值
                avg_head = Vector()
                for child in children:
                    avg_head += child.head
                avg_head /= len(children)
                bone.tail = avg_head
            elif bone.parent:
                # 没有子骨骼，有父骨骼：保持长度，延长方向
                direction = (bone.head - bone.parent.head).normalized()
                length = (bone.tail - bone.head).length
                bone.tail = bone.head + direction * length
            else:
                # 无父无子：默认方向向上的单位骨骼
                bone.tail = bone.head + Vector((0, 0.1, 0))

        return {'FINISHED'}

class OP_RelaxBoneChain(Operator):
    bl_idname = "ho.relax_bone_chain"
    bl_label = "松弛骨骼链"
    bl_options = {'REGISTER', 'UNDO'}

    iterations: IntProperty(default=3, min=1, max=200)  # type: ignore
    factor: FloatProperty(default=1.0, min=0.0, max=1.0)  # type: ignore

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE' and context.selected_editable_bones

    def execute(self, context):

        arm = context.object.data
        arm.use_mirror_x = False

        selected = [b for b in arm.edit_bones if b.select]
        selected_set = set(selected)

        if len(selected) < 3:
            self.report({'WARNING'}, "至少需要3根骨骼")
            return {'CANCELLED'}

        # -------------------------------------------------
        # 1️⃣ 拆分成多条独立链
        # -------------------------------------------------

        roots = []
        for b in selected:
            if b.parent not in selected_set:
                roots.append(b)

        if not roots:
            self.report({'WARNING'}, "未检测到链根")
            return {'CANCELLED'}

        chains = []

        for root in roots:

            chain = []
            cur = root

            while cur:
                chain.append(cur)
                children = [c for c in cur.children if c in selected_set]

                if len(children) > 1:
                    self.report({'WARNING'}, f"{cur.name} 存在分叉")
                    return {'CANCELLED'}

                cur = children[0] if children else None

            chains.append(chain)

        # 校验是否所有骨骼都被覆盖（防止断链）
        total_count = sum(len(c) for c in chains)
        if total_count != len(selected):
            self.report({'WARNING'}, "检测到非连续结构")
            return {'CANCELLED'}

        # -------------------------------------------------
        # 2️⃣ 对每条链做合法性校验
        # -------------------------------------------------

        for chain in chains:

            if len(chain) < 3:
                self.report({'WARNING'}, "每条链至少需要3根骨骼")
                return {'CANCELLED'}

            for i, b in enumerate(chain):

                if (b.tail - b.head).length < 1e-8:
                    self.report({'WARNING'}, f"{b.name} 长度为0")
                    return {'CANCELLED'}

                if i > 0:
                    if not b.use_connect:
                        self.report({'WARNING'}, f"{b.name} 未开启连接")
                        return {'CANCELLED'}

                    if (b.head - chain[i - 1].tail).length > 1e-6:
                        self.report({'WARNING'}, f"{b.name} 头尾未真实连接")
                        return {'CANCELLED'}

        # -------------------------------------------------
        # 3️⃣ 对每条链分别进行 Laplacian Relax
        # -------------------------------------------------

        for chain in chains:

            # ---- 提取 polyline ----
            heads = [b.head.copy() for b in chain]
            heads.append(chain[-1].tail.copy())

            original_first = heads[0].copy()
            original_last = heads[-1].copy()

            # ---- 迭代 ----
            for _ in range(self.iterations):
                new_heads = heads.copy()

                for i in range(1, len(heads) - 1):
                    target = (heads[i - 1] + heads[i + 1]) * 0.5
                    new_heads[i] = heads[i].lerp(target, self.factor)

                heads = new_heads

            # 锁首尾
            heads[0] = original_first
            heads[-1] = original_last

            # ---- 写回 ----
            for i, bone in enumerate(chain):
                bone.head = heads[i]
                bone.tail = heads[i + 1]

        return {'FINISHED'}

class OP_FastCreatPoseAsset(Operator):
    bl_idname = "ho.fast_create_pose_asset"
    bl_label = "快速创建姿态资产"
    bl_description = """一个对内部资产库的创建资产的再封装，原版位置比较反人类
    对选中的骨骼进行快速资产创建"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )
    pose_name: StringProperty(name="姿态名称", default="New Pose") # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pose_name")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        bpy.ops.poselib.create_pose_asset(pose_name = self.pose_name, activate_new_action=False)
        return {'FINISHED'}

class PT_Hotools_PosebonePanel(Panel):
    bl_idname = "BONE_PT_Hotools_PoseBonePanel"
    bl_label = "HoTools骨骼"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "bone"                 # Bone 页签:contentReference[oaicite:6]{index=6}
    bl_options = {"DEFAULT_CLOSED"}     # 折叠:contentReference[oaicite:7]{index=7}

    @classmethod
    def poll(cls, context):
        return context.mode == "POSE"

    def draw(self, context):
        bone = context.active_bone
        layout = self.layout
        layout.prop(bone.hotools_boneprops, "keepRotation",toggle=False)
        layout.prop(bone.hotools_boneprops, "endBone",toggle=False)
        layout.prop(bone.hotools_boneprops, "humanoidMapping",toggle=False)

def drawBoneOperatorsPanel(layout: UILayout, context: Context):
    scene = context.scene
     #细分骨骼
    row = layout.row(align=True)
    row.operator(OP_SplitBoneWithWeight.bl_idname,text="细分骨骼")
    row.operator(OP_DissolveBoneWithWeight.bl_idname,text="融并骨骼")
       

cls = [
    OP_ApplyRestPose,
    OP_ForceClearBoneRotation,
    PG_Hotools_BoneProps,
    PT_Hotools_PosebonePanel,
    OP_SelectBoneBy_by_KeepRotation,
    OP_SelectBone_by_Nochild,
    OP_AddEndBone,
    OP_SelectBone_by_endBone,
    OP_Fix_EmptyRotate_Bone,
    OP_RelaxBoneChain,
    OP_FastCreatPoseAsset,
]



def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
