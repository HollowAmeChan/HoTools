import ast

import bpy
from mathutils import Vector
from bpy.types import Operator
from bpy.types import UILayout, Context
from bpy.props import (
    StringProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    EnumProperty,
)
from .boneSplit import OP_SplitBoneWithWeight
from .boneDissolve import OP_DissolveBoneWithWeight, OP_SimpleDissolveBone
from Utils import bone_utils


def _armature_filter(_self, obj):
    return obj.type == 'ARMATURE'


def _copy_custom_properties(source, target, *, overwrite=True):
    try:
        keys = source.keys()
        target_keys = set(target.keys())
    except (AttributeError, RuntimeError, TypeError):
        return

    for key in keys:
        if not overwrite and key in target_keys:
            continue
        try:
            target[key] = source[key]
        except (AttributeError, KeyError, TypeError, ValueError):
            continue

        try:
            ui_data = source.id_properties_ui(key).as_dict()
            if ui_data:
                target.id_properties_ui(key).update(**ui_data)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass


def _copy_custom_property(source, target, source_key, target_key):
    try:
        target[target_key] = source[source_key]
    except (AttributeError, KeyError, TypeError, ValueError):
        return False

    try:
        ui_data = source.id_properties_ui(source_key).as_dict()
        if ui_data:
            target.id_properties_ui(target_key).update(**ui_data)
    except (AttributeError, KeyError, TypeError, ValueError):
        pass
    return True


def _direct_custom_property_key(data_path):
    if not data_path.startswith("[") or not data_path.endswith("]"):
        return None
    try:
        key = ast.literal_eval(data_path[1:-1])
    except (SyntaxError, ValueError):
        return None
    return key if isinstance(key, str) else None


def _copy_writable_rna_properties(source, target, skip=()):
    skipped = set(skip)
    skipped.add("rna_type")

    for prop in source.bl_rna.properties:
        identifier = prop.identifier
        if identifier in skipped or prop.is_readonly:
            continue
        if not hasattr(target, identifier):
            continue

        try:
            value = getattr(source, identifier)
            if prop.is_array:
                value = value[:]
            setattr(target, identifier, value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def _copy_bone_color(source, target):
    try:
        target.color.palette = source.color.palette
        if source.color.palette == 'CUSTOM':
            for attr in ("normal", "select", "active"):
                value = getattr(source.color.custom, attr)[:]
                setattr(target.color.custom, attr, value)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


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
            obj
            for obj in armature.children_recursive
            if obj.type == 'MESH'
            and bone_utils.object_is_deformed_by_armature(obj, armature)
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
    bl_description = "清空所选骨骼相对父骨的静置与姿态变换,保证导出后局部旋转为0"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
       return True

    def execute(self, context):
        if bpy.context.mode != 'EDIT_ARMATURE':
            print("不在骨骼编辑模式下")
        else:
            obj = context.object
            armature = obj.data
            armature.use_mirror_x = False #!!!必须关闭所有骨架的对称，否则处理会有底层逻辑上的问题
            selected_bones = bone_utils.selected_bones(context, obj)
            selected_names = [bone.name for bone in selected_bones]
            active_bone = armature.edit_bones.active
            active_name = active_bone.name if active_bone is not None else None

            bone_utils.clear_edit_bone_local_rotations(
                armature.edit_bones,
                selected_names,
            )

            # Pose channels are a separate transform layer and must also be reset
            # before a normal FBX export can produce zero local transforms.
            bpy.ops.object.mode_set(mode='OBJECT')
            try:
                bone_utils.clear_pose_bone_transforms(obj, selected_names)
            finally:
                bpy.ops.object.mode_set(mode='EDIT')
                bone_utils.select_bones(obj, selected_names)
                if active_name and armature.edit_bones.get(active_name) is not None:
                    armature.edit_bones.active = armature.edit_bones[active_name]
        return {'FINISHED'}
       
class OP_AddEndBone(Operator):
    bl_idname = "ho.add_endbone"
    bl_label = "添加叶骨"
    bl_description = "给当前选中骨添加叶骨"
    bl_options = {'REGISTER', 'UNDO'}

    length_factor: FloatProperty(
        name="叶骨长度系数",
        description="新建叶骨长度相对于原骨骼长度的比例",
        default=0.1,
        min=0.001,
        soft_max=1.0,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'ARMATURE'  and obj.mode == "EDIT" and context.active_bone is not None

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "length_factor")

    def execute(self, context):
        obj = context.object
        arm = obj.data
        ebones = arm.edit_bones

        selected_bones = bone_utils.selected_bones(context, obj)
        # 只处理选中骨中真正无子级的末端骨，断连状态不影响父子层级。
        target_bones = [bone for bone in selected_bones if not bone.children]

        end_bones = []
        for bone in target_bones:
            end_bone_name = bone.name + "_end"
            if end_bone_name in ebones:
                self.report({'WARNING'}, f"{end_bone_name} 已存在，跳过")
                continue
            new_bone:bpy.types.EditBone  
            new_bone = ebones.new(end_bone_name)
            new_bone.head = bone.tail
            bone_vector = bone.tail - bone.head
            bone_length = bone_vector.length
            if bone_length > 1e-8:
                direction = bone_vector.normalized()
            else:
                direction = Vector((0, 0, 1))
                bone_length = 1.0
            new_bone.tail = new_bone.head + direction * bone_length * self.length_factor
            new_bone.parent = bone
            new_bone.use_connect = True #相连项开
            new_bone.use_deform = False #形变关
            bone_utils.inherit_bone_collections(bone, new_bone)
            end_bones.append(new_bone.name)

        #刷新bones，再修改属性
        bpy.ops.object.mode_set(mode="OBJECT")
        for bn in end_bones:
            b = arm.bones[bn]
            b.hotools_boneprops.endBone = True
        bpy.ops.object.mode_set(mode="EDIT")

        if end_bones:
            bone_utils.select_bones(obj, end_bones)

        return {'FINISHED'}

class OP_SelectBoneBy_by_GenerateMCH(Operator):
    bl_idname = "ho.selectbone_by_generatemch"
    bl_label = "选择相似骨骼-生成MCH"
    bl_description = "选择相似骨骼-按照Hotools骨骼generateMCH生成MCH属性"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_bone != None

    def execute(self, context):
        active_bone = context.active_bone
        arm_obj = context.active_object
        bone_names = [
            bone.name
            for bone in arm_obj.data.bones
            if bone.hotools_boneprops.generateMCH
            == active_bone.hotools_boneprops.generateMCH
        ]
        bone_utils.select_bones(arm_obj, bone_names, extend=True)
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
        bone_names = [b.name for b in arm_data.bones if b.hotools_boneprops.endBone]
        bone_utils.select_bones(arm_obj, bone_names, extend=True)

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
        selected_bones = bone_utils.selected_bones(context, arm_obj)
        end_bone_names = [
            bone.name for bone in selected_bones if not bone.children
        ]
        if not end_bone_names:
            self.report({'WARNING'}, "当前选中骨骼中没有末端骨")
            return {'CANCELLED'}
        bone_utils.select_bones(arm_obj, end_bone_names)
        return {'FINISHED'}


class OP_SelectAllChildBones(Operator):
    bl_idname = "ho.select_all_child_bones"
    bl_label = "选择所有子级骨"
    bl_description = "选择当前所有选中骨的全部后代骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and context.mode in {'EDIT_ARMATURE', 'POSE'}
            and bool(bone_utils.selected_bone_names(context, obj))
        )

    def execute(self, context):
        armature = context.active_object
        selected_bones = bone_utils.selected_bones(context, armature)
        if not selected_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        descendant_names = []
        visited_names = set()
        pending = [
            child
            for bone in reversed(selected_bones)
            for child in reversed(bone.children)
        ]
        while pending:
            bone = pending.pop()
            if bone.name in visited_names:
                continue
            visited_names.add(bone.name)
            descendant_names.append(bone.name)
            pending.extend(reversed(bone.children))

        if not descendant_names:
            self.report({'WARNING'}, "选中骨没有子级骨")
            return {'CANCELLED'}

        bone_utils.select_bones(armature, descendant_names, extend=True)
        return {'FINISHED'}


class OP_AddSelectMirroredBones(Operator):
    bl_idname = "ho.add_select_mirrored_bones"
    bl_label = "加选镜像骨"
    bl_description = "根据当前选中骨骼的名称查找另一侧骨骼并加入选择"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and context.mode in {'EDIT_ARMATURE', 'POSE'}
            and bool(bone_utils.selected_bone_names(context, obj))
        )

    def execute(self, context):
        armature = context.active_object
        selected_names = bone_utils.selected_bone_names(context, armature)
        selected_set = set(selected_names)
        bones = (
            armature.data.edit_bones
            if armature.mode == 'EDIT'
            else armature.data.bones
        )

        mirrored_names = []
        seen = set()
        for bone_name in selected_names:
            mirrored_name = bpy.utils.flip_name(bone_name)
            if (
                mirrored_name == bone_name
                or mirrored_name in selected_set
                or mirrored_name in seen
                or bones.get(mirrored_name) is None
            ):
                continue
            seen.add(mirrored_name)
            mirrored_names.append(mirrored_name)

        if not mirrored_names:
            self.report({'WARNING'}, "没有找到可加选的镜像骨")
            return {'CANCELLED'}

        bone_utils.select_bones(armature, mirrored_names, extend=True)
        self.report({'INFO'}, f"已加选 {len(mirrored_names)} 根镜像骨")
        return {'FINISHED'}


def _pose_bone_has_transform(pose_bone):
    if any(value != 0.0 for value in pose_bone.location):
        return True
    if any(value != 1.0 for value in pose_bone.scale):
        return True

    if pose_bone.rotation_mode == 'QUATERNION':
        return tuple(pose_bone.rotation_quaternion) != (1.0, 0.0, 0.0, 0.0)
    if pose_bone.rotation_mode == 'AXIS_ANGLE':
        return pose_bone.rotation_axis_angle[0] != 0.0
    return any(value != 0.0 for value in pose_bone.rotation_euler)


class OP_SelectTransformedPoseBones(Operator):
    bl_idname = "ho.select_transformed_pose_bones"
    bl_label = "选择所有存在姿态变换的骨骼"
    bl_description = "选择所有位置、旋转或缩放不为默认值的姿态骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and context.mode == 'POSE'
        )

    def execute(self, context):
        armature = context.active_object
        transformed_names = [
            pose_bone.name
            for pose_bone in armature.pose.bones
            if _pose_bone_has_transform(pose_bone)
        ]
        bone_utils.select_bones(armature, transformed_names)

        if not transformed_names:
            self.report({'INFO'}, "未找到存在姿态变换的骨骼")
        return {'FINISHED'}


class OP_Fix_EmptyRotate_Bone(Operator):
    # 保存父骨骼名称，用于根据打开弹窗时选中的编辑骨骼生成选项。
    target_parent_name: StringProperty(options={'HIDDEN'})  # type: ignore

    def _target_child_items(self, context):
        obj = context.object if context is not None else None
        if obj is None or obj.type != 'ARMATURE' or obj.mode != 'EDIT':
            return []

        parent = obj.data.edit_bones.get(self.target_parent_name)
        if parent is None:
            return []
        children = [
            child for child in obj.data.edit_bones if child.parent == parent
        ]
        return [
            (child.name, child.name, "将父骨骼的尾部吸附到该子骨骼的头部")
            for child in children
        ]

    target_child_name: EnumProperty(
        name="吸附到的子骨骼",
        description="选择将父骨骼尾部吸附到哪个子骨骼的头部",
        items=_target_child_items,
    )  # type: ignore

    bl_idname = "ho.fix_empty_rotate_bone"
    bl_label = "修复空旋转的骨骼"
    bl_description = """另选中中骨骼的tail位置设定为子级骨骼的head位置(若有多个子级可在弹窗中选择目标骨骼，默认第一个)
                        若没有子级则将tail位置设置在自己的父级与自己连线的延长线上(保持自己的骨骼长度)"""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_ARMATURE' and context.active_bone is not None

    def _ambiguous_bones(self, context):
        obj = context.object
        selected_bones = bone_utils.selected_bones(context, obj)
        return [bone for bone in selected_bones if len(bone.children) > 1]

    def invoke(self, context, event):
        obj = context.object
        ambiguous_bones = self._ambiguous_bones(context)
        if not ambiguous_bones:
            return self.execute(context)

        active_name = context.active_bone.name if context.active_bone else None
        target = next(
            (bone for bone in ambiguous_bones if bone.name == active_name),
            ambiguous_bones[0],
        )
        self.target_parent_name = target.name
        # 弹窗打开时显式将排列中的第一个子骨骼设为默认值。
        children = [
            child for child in obj.data.edit_bones if child.parent == target
        ]
        self.target_child_name = children[0].name
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        parent = context.object.data.edit_bones.get(self.target_parent_name)
        if parent is None or len(parent.children) < 2:
            return
        self.layout.prop(self, "target_child_name", text=parent.name)

    def execute(self, context):
        obj = context.object
        armature = obj.data
        armature.use_mirror_x = False  # 禁用对称，否则有同步问题

        selected_bones = bone_utils.selected_bones(context, obj)

        for bone in selected_bones:
            children = [b for b in armature.edit_bones if b.parent == bone]
            
            if children:
                # 有子骨骼：单子级直接吸附，多子级使用弹窗选择的子级。
                if len(children) == 1:
                    target_child = children[0]
                else:
                    target_child = children[0]
                    if bone.name == self.target_parent_name:
                        selected_child = armature.edit_bones.get(
                            self.target_child_name
                        )
                        if selected_child in children:
                            target_child = selected_child
                bone.tail = target_child.head
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
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and context.mode == 'EDIT_ARMATURE'
            and bool(bone_utils.selected_bone_names(context, obj))
        )

    def execute(self, context):

        obj = context.object
        arm = obj.data
        arm.use_mirror_x = False

        selected = bone_utils.selected_bones(context, obj)
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
            context.mode == 'POSE' and
            bool(bone_utils.selected_bone_names(context, obj))
        )
    pose_name: StringProperty(name="姿态名称", default="New Pose") # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pose_name")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        try:
            result = bpy.ops.poselib.create_pose_asset(
                pose_name=self.pose_name,
                asset_library_reference='LOCAL',
            )
        except RuntimeError as error:
            self.report({'ERROR'}, f"创建姿态资产失败: {error}")
            return {'CANCELLED'}
        if 'FINISHED' not in result:
            return {'CANCELLED'}
        return {'FINISHED'}


def _active_action_curve_owners(animation_data):
    action = getattr(animation_data, "action", None)
    if action is None:
        return []

    owners = []
    seen = set()
    slot = getattr(animation_data, "action_slot", None)
    if slot is not None:
        for layer in action.layers:
            for strip in layer.strips:
                if strip.type != 'KEYFRAME':
                    continue
                channelbag = strip.channelbag(slot)
                if channelbag is None:
                    continue
                pointer = channelbag.as_pointer()
                if pointer not in seen:
                    seen.add(pointer)
                    owners.append(channelbag)

    if not owners and getattr(action, "is_action_legacy", False):
        owners.append(action)
    return owners


def _bone_name_for_curve(data_path, bone_roots):
    for root, bone_name in bone_roots:
        if (
            data_path == root
            or data_path.startswith(root + ".")
            or data_path.startswith(root + "[")
        ):
            return bone_name
    return None


class OP_DeleteSelectedBoneCurrentFrameKeyframes(Operator):
    bl_idname = "ho.delete_selected_bone_current_frame_keyframes"
    bl_label = "删除选中骨骼当前帧关键帧"
    bl_description = "删除选中骨骼在当前帧上的全部姿态关键帧，并清理空动画曲线"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        animation_data = getattr(obj, "animation_data", None) if obj else None
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and context.mode == 'POSE'
            and bool(bone_utils.selected_bone_names(context, obj))
            and animation_data is not None
            and animation_data.action is not None
        )

    def execute(self, context):
        armature = context.active_object
        current_frame = context.scene.frame_current_final
        selected_names = set(bone_utils.selected_bone_names(context, armature))
        bone_roots = [
            (pose_bone.path_from_id(), pose_bone.name)
            for pose_bone in armature.pose.bones
            if pose_bone.name in selected_names
        ]

        removed_keys = 0
        removed_curves = 0
        affected_bones = set()
        for owner in _active_action_curve_owners(armature.animation_data):
            group_names = set()
            for fcurve in list(owner.fcurves):
                bone_name = _bone_name_for_curve(fcurve.data_path, bone_roots)
                if bone_name is None:
                    continue

                keys_at_frame = [
                    key
                    for key in fcurve.keyframe_points
                    if abs(key.co.x - current_frame) <= 1e-4
                ]
                if not keys_at_frame:
                    continue

                affected_bones.add(bone_name)
                removed_keys += len(keys_at_frame)
                for key in keys_at_frame:
                    fcurve.keyframe_points.remove(key, fast=True)

                if not fcurve.keyframe_points and not fcurve.sampled_points:
                    if fcurve.group is not None:
                        group_names.add(fcurve.group.name)
                    owner.fcurves.remove(fcurve)
                    removed_curves += 1
                else:
                    fcurve.update()

            for group_name in group_names:
                group = owner.groups.get(group_name)
                if group is not None and not group.channels:
                    owner.groups.remove(group)

        if removed_keys == 0:
            self.report({'WARNING'}, "选中骨骼在当前帧没有姿态关键帧")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"已删除 {len(affected_bones)} 根骨骼当前帧的 {removed_keys} 个关键帧，"
            f"并清理 {removed_curves} 条空曲线",
        )
        return {'FINISHED'}


def _set_all_bone_constraints_mute(armature: bpy.types.Object, mute: bool, bone_filter=None) -> tuple[int, int]:
    """把活动骨架内姿态骨的约束 mute 设为 mute。返回 (受影响约束数, 受影响骨数)。

    bone_filter 为 None 时作用于全部骨；否则只作用于 bone_filter(pose_bone) 为真的骨。
    """
    constraint_count = 0
    bone_count = 0
    for pose_bone in armature.pose.bones:
        if not pose_bone.constraints:
            continue
        if bone_filter is not None and not bone_filter(pose_bone):
            continue
        touched = False
        for constraint in pose_bone.constraints:
            if constraint.mute != mute:
                constraint.mute = mute
                constraint_count += 1
                touched = True
        if touched:
            bone_count += 1
    return constraint_count, bone_count


def _is_humanoid_bone(pose_bone) -> bool:
    """姿态骨是否带 Humanoid 映射（humanoidMapping 非空）。"""
    props = getattr(pose_bone.bone, "hotools_boneprops", None)
    return bool(props and getattr(props, "humanoidMapping", "").strip())


def _is_aux_bone(pose_bone) -> bool:
    """姿态骨是否为 HoTools 辅助骨（auxBone.isAuxBone）。"""
    props = getattr(pose_bone.bone, "hotools_boneprops", None)
    aux = getattr(props, "auxBone", None) if props else None
    return bool(aux and aux.isAuxBone)


class OP_DisableAllBoneConstraints(Operator):
    bl_idname = "ho.disable_all_bone_constraints"
    bl_label = "禁用所有骨骼约束"
    bl_description = "禁用当前活动骨架内所有骨骼的所有约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, True)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要禁用的约束")
        else:
            self.report({'INFO'}, f"已禁用 {bone_count} 根骨骼上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_EnableAllBoneConstraints(Operator):
    bl_idname = "ho.enable_all_bone_constraints"
    bl_label = "启用所有骨骼约束"
    bl_description = "启用当前活动骨架内所有骨骼的所有约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, False)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要启用的约束")
        else:
            self.report({'INFO'}, f"已启用 {bone_count} 根骨骼上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_DisableHumanoidBoneConstraints(Operator):
    bl_idname = "ho.disable_humanoid_bone_constraints"
    bl_label = "禁用所有Humanoid约束"
    bl_description = "禁用当前活动骨架内所有带 Humanoid 映射的骨骼的约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, True, _is_humanoid_bone)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要禁用的 Humanoid 约束")
        else:
            self.report({'INFO'}, f"已禁用 {bone_count} 根 Humanoid 骨上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_EnableHumanoidBoneConstraints(Operator):
    bl_idname = "ho.enable_humanoid_bone_constraints"
    bl_label = "启用所有Humanoid约束"
    bl_description = "启用当前活动骨架内所有带 Humanoid 映射的骨骼的约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, False, _is_humanoid_bone)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要启用的 Humanoid 约束")
        else:
            self.report({'INFO'}, f"已启用 {bone_count} 根 Humanoid 骨上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_DisableAuxBoneConstraints(Operator):
    bl_idname = "ho.disable_aux_bone_constraints"
    bl_label = "禁用所有辅助骨约束"
    bl_description = "禁用当前活动骨架内所有 HoTools 辅助骨的约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, True, _is_aux_bone)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要禁用的辅助骨约束")
        else:
            self.report({'INFO'}, f"已禁用 {bone_count} 根辅助骨上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_EnableAuxBoneConstraints(Operator):
    bl_idname = "ho.enable_aux_bone_constraints"
    bl_label = "启用所有辅助骨约束"
    bl_description = "启用当前活动骨架内所有 HoTools 辅助骨的约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        constraint_count, bone_count = _set_all_bone_constraints_mute(armature, False, _is_aux_bone)
        if constraint_count == 0:
            self.report({'INFO'}, "没有需要启用的辅助骨约束")
        else:
            self.report({'INFO'}, f"已启用 {bone_count} 根辅助骨上的 {constraint_count} 个约束")
        return {'FINISHED'}


class OP_ResetAllBonePose(Operator):
    bl_idname = "ho.reset_all_bone_pose"
    bl_label = "重置所有骨骼姿态"
    bl_description = "把活动骨架内所有骨骼的位置、旋转、缩放清零，回到静置姿态（不改变静置骨架本身）"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object
        count = 0
        for pose_bone in armature.pose.bones:
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
            if pose_bone.rotation_mode == 'QUATERNION':
                pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            elif pose_bone.rotation_mode == 'AXIS_ANGLE':
                pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            else:
                pose_bone.rotation_euler = (0.0, 0.0, 0.0)
            count += 1
        self.report({'INFO'}, f"已重置 {count} 根骨骼的姿态")
        return {'FINISHED'}

class OP_BoneApplyConstraint(Operator):
    bl_idname = "ho.bone_apply_constraint"
    bl_label = "应用约束到骨骼"
    bl_description = "将选中骨骼的约束结果应用为当前姿态，并移除约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = bone_utils.selected_bones(context, obj)

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        # 确保在 Pose 模式
        bpy.ops.object.mode_set(mode='POSE')

        # 1. 应用视觉变换（约束结果）
        bpy.ops.pose.visual_transform_apply()

        # 2. 移除约束
        for pb in pose_bones:
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)


        self.report({'INFO'}, f"已应用 {len(pose_bones)} 根骨骼的约束")
        return {'FINISHED'}
 
class OP_BoneRemoveConstraints(Operator):
    bl_idname = "ho.bone_remove_constraints"
    bl_label = "移除骨骼约束"
    bl_description = "移除选中骨骼上的全部约束"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and
            obj.type == 'ARMATURE' and
            context.mode == 'POSE'
        )

    def execute(self, context):
        obj = context.active_object
        pose_bones = bone_utils.selected_bones(context, obj)

        if not pose_bones:
            self.report({'WARNING'}, "未选择任何骨骼")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='POSE')

        for pb in pose_bones:
            if not pb.constraints:
                continue

            # 逐个移除约束（倒序，防炸）
            for c in reversed(pb.constraints):
                pb.constraints.remove(c)

        self.report({'INFO'}, "已移除选中骨骼的全部约束")
        return {'FINISHED'}


class OP_MergeArmatures(Operator):
    bl_idname = "ho.mod_weight_merge_armatures"
    bl_label = "融合骨架"
    bl_description = (
        "保留主骨架的同名骨，将素材骨架的非同名骨原地复制到主骨架，"
        "并把父级转接到主骨架的同名骨；完成后移除素材骨架"
    )
    bl_options = {'REGISTER', 'UNDO'}

    _BONE_SKIP_PROPERTIES = {
        "name",
        "parent",
        "children",
        "collections",
        "color",
        "head",
        "head_local",
        "tail",
        "tail_local",
        "center",
        "vector",
        "length",
        "matrix",
        "matrix_local",
    }
    _POSE_SKIP_PROPERTIES = {
        "name",
        "bone",
        "parent",
        "children",
        "constraints",
        "custom_shape_transform",
        "head",
        "tail",
        "center",
        "vector",
        "length",
        "matrix",
        "matrix_basis",
        "channel_matrix",
        "location",
        "rotation_axis_angle",
        "rotation_euler",
        "rotation_quaternion",
        "scale",
    }

    @classmethod
    def poll(cls, context):
        scene = context.scene
        main = scene.ho_mod_weight_merge_main_armature
        asset = scene.ho_mod_weight_merge_asset_armature
        return (
            main is not None
            and asset is not None
            and main.type == 'ARMATURE'
            and asset.type == 'ARMATURE'
        )

    @staticmethod
    def _object_in_view_layer(context, obj):
        return obj is not None and obj.name in context.view_layer.objects

    @staticmethod
    def _enter_object_mode(context):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    @classmethod
    def _enter_edit_mode(cls, context, obj):
        cls._enter_object_mode(context)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def _snapshot_bones(asset):
        snapshots = []
        for bone in asset.data.bones:
            snapshots.append({
                "name": bone.name,
                "parent_name": bone.parent.name if bone.parent else None,
                "head": bone.head_local.copy(),
                "tail": bone.tail_local.copy(),
                "roll_axis": bone.z_axis.copy(),
                "use_connect": bone.use_connect,
                "collection_names": [
                    collection.name for collection in bone.collections
                ],
            })
        return snapshots

    @staticmethod
    def _restore_context(
        context,
        previous_active,
        previous_active_was_asset,
        previous_selected,
        asset_was_selected,
        previous_mode,
        main,
        merge_succeeded,
    ):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            try:
                should_select = obj in previous_selected
                if merge_succeeded and obj == main and asset_was_selected:
                    should_select = True
                obj.select_set(should_select)
            except RuntimeError:
                pass

        if merge_succeeded and previous_active_was_asset:
            target_active = main
        elif OP_MergeArmatures._object_in_view_layer(context, previous_active):
            target_active = previous_active
        else:
            target_active = main

        context.view_layer.objects.active = target_active
        if target_active is not None and previous_mode != 'OBJECT':
            try:
                target_active.select_set(True)
                bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass

    @classmethod
    def _remove_created_bones(cls, context, main, created_names):
        if not created_names or not cls._object_in_view_layer(context, main):
            return

        cls._enter_edit_mode(context, main)
        for bone_name in created_names:
            bone = main.data.edit_bones.get(bone_name)
            if bone is not None:
                main.data.edit_bones.remove(bone)
        bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def _copy_bone_collections(main, source_bone, target_bone, created_collections):
        target_collections = []
        for source_collection in source_bone.collections:
            target_collection = main.data.collections.get(source_collection.name)
            if target_collection is None:
                target_collection = main.data.collections.new(source_collection.name)
                created_collections.add(source_collection.name)
                _copy_custom_properties(source_collection, target_collection)
            target_collections.append(target_collection)
        bone_utils.replace_bone_collections(target_bone, target_collections)

    @classmethod
    def _copy_bone_data(cls, main, asset, copied_names, created_collections):
        for bone_name in copied_names:
            source_bone = asset.data.bones[bone_name]
            target_bone = main.data.bones[bone_name]
            _copy_writable_rna_properties(
                source_bone,
                target_bone,
                cls._BONE_SKIP_PROPERTIES,
            )
            for handle_property in (
                "bbone_custom_handle_start",
                "bbone_custom_handle_end",
            ):
                source_handle = getattr(source_bone, handle_property, None)
                if source_handle is None:
                    continue
                target_handle = main.data.bones.get(source_handle.name)
                if target_handle is not None:
                    try:
                        setattr(target_bone, handle_property, target_handle)
                    except (AttributeError, RuntimeError, TypeError):
                        pass
            _copy_custom_properties(source_bone, target_bone)
            _copy_bone_color(source_bone, target_bone)
            cls._copy_bone_collections(
                main,
                source_bone,
                target_bone,
                created_collections,
            )

    @staticmethod
    def _remap_driver_target_id(source_id, asset, main):
        if source_id == asset:
            return main
        if source_id == asset.data:
            return main.data
        return source_id

    @classmethod
    def _remap_driver_target_data_path(
        cls,
        source_target,
        source_id,
        target_id,
        asset,
    ):
        data_path = getattr(source_target, "data_path", "")
        if source_id not in {asset, asset.data}:
            return data_path

        source_key = _direct_custom_property_key(data_path)
        if source_key is None or source_key not in source_id.keys():
            return data_path
        if source_key not in target_id.keys():
            _copy_custom_property(source_id, target_id, source_key, source_key)
            return data_path

        try:
            if target_id[source_key] == source_id[source_key]:
                return data_path
        except (TypeError, ValueError):
            pass

        base_key = f"{source_key}__{asset.name}"
        target_key = base_key
        suffix = 1
        while target_key in target_id.keys():
            target_key = f"{base_key}_{suffix}"
            suffix += 1
        if not _copy_custom_property(
            source_id,
            target_id,
            source_key,
            target_key,
        ):
            return data_path
        return f'["{bpy.utils.escape_identifier(target_key)}"]'

    @classmethod
    def _copy_driver_variable(cls, source, target, asset, main):
        target.name = source.name
        target.type = source.type

        for source_target, target_target in zip(source.targets, target.targets):
            try:
                target_target.id_type = source_target.id_type
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass

            _copy_writable_rna_properties(
                source_target,
                target_target,
                {"id", "id_type"},
            )
            source_id = getattr(source_target, "id", None)
            target_id = cls._remap_driver_target_id(source_id, asset, main)
            if source_id is not None and hasattr(target_target, "id"):
                try:
                    target_target.id = target_id
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

            for property_name in (
                "bone_target",
                "context_property",
                "data_path",
                "rotation_mode",
                "transform_space",
                "transform_type",
            ):
                if not hasattr(source_target, property_name):
                    continue
                if not hasattr(target_target, property_name):
                    continue
                try:
                    value = getattr(source_target, property_name)
                    if property_name == "data_path" and target_id is not None:
                        value = cls._remap_driver_target_data_path(
                            source_target,
                            source_id,
                            target_id,
                            asset,
                        )
                    setattr(
                        target_target,
                        property_name,
                        value,
                    )
                except (AttributeError, RuntimeError, TypeError, ValueError):
                    pass

    @classmethod
    def _copy_driver_fcurve(
        cls,
        source_fcurve,
        target_id,
        target_data_path,
        asset,
        main,
    ):
        target_id.animation_data_create()
        drivers = target_id.animation_data.drivers
        existing = drivers.find(target_data_path, index=source_fcurve.array_index)
        if existing is not None:
            drivers.remove(existing)

        target_fcurve = drivers.new(
            target_data_path,
            index=source_fcurve.array_index,
        )
        _copy_writable_rna_properties(
            source_fcurve,
            target_fcurve,
            {
                "array_index",
                "data_path",
                "driver",
                "group",
                "keyframe_points",
                "modifiers",
                "sampled_points",
            },
        )

        source_driver = source_fcurve.driver
        target_driver = target_fcurve.driver
        target_driver.type = source_driver.type
        target_driver.expression = source_driver.expression
        target_driver.use_self = source_driver.use_self
        for variable in list(target_driver.variables):
            target_driver.variables.remove(variable)
        for source_variable in source_driver.variables:
            cls._copy_driver_variable(
                source_variable,
                target_driver.variables.new(),
                asset,
                main,
            )

        for source_modifier in source_fcurve.modifiers:
            target_modifier = target_fcurve.modifiers.new(source_modifier.type)
            _copy_writable_rna_properties(
                source_modifier,
                target_modifier,
                {"type"},
            )

        return (target_data_path, source_fcurve.array_index)

    @classmethod
    def _copy_constraint_drivers(
        cls,
        main,
        asset,
        source_constraint,
        target_constraint,
    ):
        animation_data = asset.animation_data
        if animation_data is None:
            return []

        source_path = source_constraint.path_from_id()
        target_path = target_constraint.path_from_id()
        created = []
        for source_fcurve in animation_data.drivers:
            data_path = source_fcurve.data_path
            if not (
                data_path == source_path
                or data_path.startswith(source_path + ".")
                or data_path.startswith(source_path + "[")
            ):
                continue

            target_data_path = target_path + data_path[len(source_path):]
            created.append(cls._copy_driver_fcurve(
                source_fcurve,
                main,
                target_data_path,
                asset,
                main,
            ))
        return created

    @staticmethod
    def _copy_constraint_targets(source_constraint, target_constraint, asset, main):
        source_targets = getattr(source_constraint, "targets", None)
        target_targets = getattr(target_constraint, "targets", None)
        if source_targets is None or target_targets is None:
            return
        if not hasattr(target_targets, "new"):
            return

        for source_target in source_targets:
            target = target_targets.new()
            _copy_writable_rna_properties(source_target, target)
            if hasattr(source_target, "target"):
                target.target = (
                    main if source_target.target == asset else source_target.target
                )
            for property_name in ("subtarget", "weight"):
                if not hasattr(source_target, property_name):
                    continue
                if not hasattr(target, property_name):
                    continue
                setattr(target, property_name, getattr(source_target, property_name))

    @classmethod
    def _copy_pose_data(cls, main, asset, copied_names, created_drivers):
        custom_shape_transform_names = {}

        for bone_name in copied_names:
            source_pose_bone = asset.pose.bones.get(bone_name)
            target_pose_bone = main.pose.bones.get(bone_name)
            if source_pose_bone is None or target_pose_bone is None:
                continue

            _copy_writable_rna_properties(
                source_pose_bone,
                target_pose_bone,
                cls._POSE_SKIP_PROPERTIES,
            )
            _copy_custom_properties(source_pose_bone, target_pose_bone)

            transform_bone = source_pose_bone.custom_shape_transform
            if transform_bone is not None:
                custom_shape_transform_names[bone_name] = transform_bone.name

            for source_constraint in source_pose_bone.constraints:
                target_constraint = target_pose_bone.constraints.new(
                    source_constraint.type
                )
                target_constraint.name = source_constraint.name
                _copy_writable_rna_properties(
                    source_constraint,
                    target_constraint,
                    {
                        "influence",
                        "owner_space",
                        "subtarget",
                        "target",
                        "target_space",
                        "type",
                    },
                )
                if hasattr(source_constraint, "target"):
                    try:
                        target_constraint.target = (
                            main
                            if source_constraint.target == asset
                            else source_constraint.target
                        )
                    except (AttributeError, RuntimeError, TypeError):
                        pass
                if hasattr(source_constraint, "subtarget"):
                    try:
                        target_constraint.subtarget = source_constraint.subtarget
                    except (AttributeError, RuntimeError, TypeError):
                        pass
                cls._copy_constraint_targets(
                    source_constraint,
                    target_constraint,
                    asset,
                    main,
                )
                # Constraint space enum items depend on the resolved target type.
                # Assign these only after target/subtarget have been remapped.
                for property_name in (
                    "owner_space",
                    "target_space",
                    "influence",
                ):
                    if not hasattr(source_constraint, property_name):
                        continue
                    if not hasattr(target_constraint, property_name):
                        continue
                    setattr(
                        target_constraint,
                        property_name,
                        getattr(source_constraint, property_name),
                    )
                _copy_custom_properties(source_constraint, target_constraint)
                created_drivers.extend(cls._copy_constraint_drivers(
                    main,
                    asset,
                    source_constraint,
                    target_constraint,
                ))

        for bone_name, transform_name in custom_shape_transform_names.items():
            transform_bone = main.pose.bones.get(transform_name)
            if transform_bone is not None:
                main.pose.bones[bone_name].custom_shape_transform = transform_bone

        return created_drivers

    @staticmethod
    def _remove_created_drivers(main, created_drivers):
        animation_data = main.animation_data
        if animation_data is None:
            return
        for data_path, array_index in created_drivers:
            fcurve = animation_data.drivers.find(data_path, index=array_index)
            if fcurve is not None:
                animation_data.drivers.remove(fcurve)

    @staticmethod
    def _remove_empty_created_collections(main, created_collections):
        for collection_name in created_collections:
            collection = main.data.collections.get(collection_name)
            if collection is None or collection.bones:
                continue
            try:
                main.data.collections.remove(collection)
            except RuntimeError:
                pass

    @staticmethod
    def _remap_object_references(asset, main):
        """Some RNA pointers created during the merge are not covered by ID.user_remap."""
        for obj in bpy.data.objects:
            for modifier in obj.modifiers:
                if hasattr(modifier, "object") and modifier.object == asset:
                    modifier.object = main

            for constraint in obj.constraints:
                if hasattr(constraint, "target") and constraint.target == asset:
                    constraint.target = main

            if obj.pose is None:
                continue
            for pose_bone in obj.pose.bones:
                for constraint in pose_bone.constraints:
                    if (
                        hasattr(constraint, "target")
                        and constraint.target == asset
                    ):
                        constraint.target = main

    def execute(self, context):
        scene = context.scene
        main = scene.ho_mod_weight_merge_main_armature
        asset = scene.ho_mod_weight_merge_asset_armature

        if main == asset:
            self.report({'ERROR'}, "主骨架与素材骨架不能是同一个对象")
            return {'CANCELLED'}
        if not self._object_in_view_layer(context, main):
            self.report({'ERROR'}, "主骨架不在当前视图层中")
            return {'CANCELLED'}
        if not self._object_in_view_layer(context, asset):
            self.report({'ERROR'}, "素材骨架不在当前视图层中")
            return {'CANCELLED'}
        if not main.data.is_editable:
            self.report({'ERROR'}, "主骨架数据不可编辑")
            return {'CANCELLED'}
        if not asset.is_editable:
            self.report({'ERROR'}, "素材骨架对象不可编辑")
            return {'CANCELLED'}

        previous_active = context.view_layer.objects.active
        previous_active_was_asset = previous_active == asset
        previous_selected = {
            obj for obj in context.view_layer.objects if obj.select_get()
        }
        asset_was_selected = asset in previous_selected
        previous_mode = (
            previous_active.mode if previous_active is not None else 'OBJECT'
        )

        existing_names = {bone.name for bone in main.data.bones}
        source_snapshots = self._snapshot_bones(asset)
        copied_snapshots = [
            snapshot
            for snapshot in source_snapshots
            if snapshot["name"] not in existing_names
        ]
        copied_names = [snapshot["name"] for snapshot in copied_snapshots]
        duplicate_count = len(source_snapshots) - len(copied_snapshots)
        created_names = []
        created_collections = set()
        created_drivers = []
        disconnected_count = 0
        merge_succeeded = False
        operation_error = None
        asset_data = asset.data
        parented_world_matrices = {
            obj: obj.matrix_world.copy()
            for obj in bpy.data.objects
            if obj.parent == asset
        }

        try:
            source_to_main = main.matrix_world.inverted_safe() @ asset.matrix_world
            direction_to_main = source_to_main.to_3x3()

            self._enter_edit_mode(context, main)
            edit_bones = main.data.edit_bones

            for snapshot in copied_snapshots:
                bone = edit_bones.new(snapshot["name"])
                created_names.append(bone.name)
                bone.head = source_to_main @ snapshot["head"]
                bone.tail = source_to_main @ snapshot["tail"]
                roll_axis = direction_to_main @ snapshot["roll_axis"]
                if roll_axis.length_squared > 1e-20:
                    bone.align_roll(roll_axis)

            for snapshot in copied_snapshots:
                bone = edit_bones[snapshot["name"]]
                parent_name = snapshot["parent_name"]
                if parent_name is not None:
                    bone.parent = edit_bones.get(parent_name)

                if snapshot["use_connect"] and bone.parent is not None:
                    if (bone.head - bone.parent.tail).length <= 1e-6:
                        bone.use_connect = True
                    else:
                        disconnected_count += 1

            bpy.ops.object.mode_set(mode='OBJECT')
            context.view_layer.update()

            self._copy_bone_data(
                main,
                asset,
                copied_names,
                created_collections,
            )
            # Driver variables that point at the source object or Armature data
            # keep working after their IDs are remapped to the main armature.
            _copy_custom_properties(asset, main, overwrite=False)
            _copy_custom_properties(asset.data, main.data, overwrite=False)
            self._copy_pose_data(
                main,
                asset,
                copied_names,
                created_drivers,
            )

            self._remap_object_references(asset, main)
            asset.user_remap(main)
            self._remap_object_references(asset, main)
            for child, world_matrix in parented_world_matrices.items():
                try:
                    child.matrix_world = world_matrix
                except (ReferenceError, RuntimeError):
                    pass
            scene.ho_mod_weight_merge_asset_armature = None
            bpy.data.objects.remove(asset, do_unlink=True)
            if asset_data.users == 0:
                bpy.data.armatures.remove(asset_data)

            merge_succeeded = True
        except Exception as error:
            operation_error = error
            try:
                self._remove_created_drivers(main, created_drivers)
                self._remove_created_bones(context, main, created_names)
                self._remove_empty_created_collections(main, created_collections)
            except Exception as rollback_error:
                print(
                    "[Mod Weight Armature Merge] failed to roll back: "
                    f"{rollback_error}"
                )
        finally:
            try:
                self._restore_context(
                    context,
                    previous_active,
                    previous_active_was_asset,
                    previous_selected,
                    asset_was_selected,
                    previous_mode,
                    main,
                    merge_succeeded,
                )
            except Exception as restore_error:
                print(
                    "[Mod Weight Armature Merge] failed to restore context: "
                    f"{restore_error}"
                )

        if operation_error is not None:
            self.report({'ERROR'}, f"融合骨架失败：{operation_error}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"骨架融合完成：新增 {len(copied_names)} 根骨，"
            f"忽略同名骨 {duplicate_count} 根，"
            f"迁移约束驱动 {len(created_drivers)} 条，"
            f"为保持原位断开连接 {disconnected_count} 根",
        )
        return {'FINISHED'}


def drawMergeArmaturesPanel(layout: UILayout, context: Context):
    box = layout.box()
    box.label(text="融合骨架")
    row = box.row(align=True)
    row.prop(
        context.scene,
        "ho_mod_weight_merge_main_armature",
        text="主骨架",
    )
    row.prop(
        context.scene,
        "ho_mod_weight_merge_asset_armature",
        text="素材骨架",
    )
    box.operator(OP_MergeArmatures.bl_idname, text="融合骨架")


def drawBoneOperatorsPanel(layout: UILayout, context: Context):
    """Draw common bone operations."""
    layout.operator(OP_SelectAllChildBones.bl_idname, text="选择所有子级骨")

    row = layout.row(align=True)
    row.operator(OP_BoneApplyConstraint.bl_idname, text="应用约束到骨骼")
    row.operator(OP_BoneRemoveConstraints.bl_idname, text="移除骨骼约束")

    row = layout.row(align=True)
    row.operator(OP_SplitBoneWithWeight.bl_idname, text="细分骨骼")
    row.operator(OP_DissolveBoneWithWeight.bl_idname, text="溶并骨骼")
    row.operator(OP_SimpleDissolveBone.bl_idname, text="简单溶并")

    col = layout.column(align=True)
    col.operator(OP_ResetAllBonePose.bl_idname, text="重置所有骨骼姿态", icon="LOOP_BACK")
    row = col.row(align=True)
    row.operator(OP_DisableAllBoneConstraints.bl_idname, text="禁用所有约束")
    row.operator(OP_EnableAllBoneConstraints.bl_idname, text="启用所有约束")
    row = col.row(align=True)
    row.operator(OP_DisableHumanoidBoneConstraints.bl_idname, text="禁用Humanoid约束")
    row.operator(OP_EnableHumanoidBoneConstraints.bl_idname, text="启用Humanoid约束")

    layout.separator()
    drawMergeArmaturesPanel(layout, context)


class OP_RemoveEmptyBoneCollections(Operator):
    bl_idname = "ho.remove_empty_bone_collections"
    bl_label = "移除无骨的骨集合"
    bl_description = "移除当前骨架中不包含任何骨骼的骨集合"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        armature = context.active_object.data
        collections = getattr(armature, "collections_all", armature.collections)
        empty_collections = [collection for collection in collections if not collection.bones]

        for collection in empty_collections:
            try:
                armature.collections.remove(collection)
            except (ReferenceError, RuntimeError):
                # A parent collection may already have been removed with its children.
                continue

        removed_count = len(empty_collections)
        if removed_count:
            self.report({'INFO'}, f"已移除 {removed_count} 个无骨集合")
        else:
            self.report({'INFO'}, "没有找到无骨集合")
        return {'FINISHED'}


cls = [
    OP_ApplyRestPose,
    OP_ForceClearBoneRotation,
    OP_SelectBoneBy_by_GenerateMCH,
    OP_SelectBone_by_Nochild,
    OP_SelectAllChildBones,
    OP_AddSelectMirroredBones,
    OP_SelectTransformedPoseBones,
    OP_AddEndBone,
    OP_SelectBone_by_endBone,
    OP_Fix_EmptyRotate_Bone,
    OP_RelaxBoneChain,
    OP_FastCreatPoseAsset,
    OP_DeleteSelectedBoneCurrentFrameKeyframes,
    OP_DisableAllBoneConstraints,
    OP_EnableAllBoneConstraints,
    OP_DisableHumanoidBoneConstraints,
    OP_EnableHumanoidBoneConstraints,
    OP_DisableAuxBoneConstraints,
    OP_EnableAuxBoneConstraints,
    OP_ResetAllBonePose,
    OP_BoneApplyConstraint,
    OP_BoneRemoveConstraints,
    OP_MergeArmatures,
    OP_RemoveEmptyBoneCollections,
]



def register():
    bpy.types.Scene.ho_mod_weight_merge_main_armature = PointerProperty(
        name="主骨架",
        description="保留现有骨骼及其自定义信息的目标骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    bpy.types.Scene.ho_mod_weight_merge_asset_armature = PointerProperty(
        name="素材骨架",
        description="融合到主骨架并在完成后移除的素材骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    for i in cls:
        bpy.utils.register_class(i)


def unregister():
    for i in reversed(cls):
        bpy.utils.unregister_class(i)
    del bpy.types.Scene.ho_mod_weight_merge_asset_armature
    del bpy.types.Scene.ho_mod_weight_merge_main_armature
