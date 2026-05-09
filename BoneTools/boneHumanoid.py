import bpy
from bpy.types import Panel, UILayout, Context, Operator
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty,IntProperty,EnumProperty
from .humanoid_auto_mapping import auto_map_source_names_to_humanoid

def PF_armature_filter(self, obj):
    return obj.type == 'ARMATURE'

def reg_props():
    bpy.types.Scene.bone_constraint_resting_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)
    bpy.types.Scene.bone_constraint_moving_armature = PointerProperty(
        type=bpy.types.Object, poll=PF_armature_filter)

def ureg_props():
    del bpy.types.Scene.bone_constraint_resting_armature
    del bpy.types.Scene.bone_constraint_moving_armature

class OP_SameNameBone_addConstraint(Operator):
    bl_idname = "ho.samenamebone_addconstraint"
    bl_label = "按映射添加约束"
    bl_description = "根据humanoid映射，确定对应的pair，添加约束"
    bl_options = {'REGISTER', 'UNDO'}

    constraint_type: bpy.props.StringProperty(
        name="Constraint Type",
        default="COPY_LOCATION",
    )  # type: ignore

    def execute(self, context):
        scene = context.scene
        resting_armature = scene.bone_constraint_resting_armature
        moving_armature = scene.bone_constraint_moving_armature

        if not (resting_armature and moving_armature):
            self.report({'WARNING'}, "需要指定两个骨架")
            return {'CANCELLED'}

        if resting_armature.type != 'ARMATURE' or moving_armature.type != 'ARMATURE':
            self.report({'WARNING'}, "指定对象必须都是Armature")
            return {'CANCELLED'}

        # humanoidMapping -> resting pose bone
        resting_mapping_map = {}
        duplicate_resting_mappings = set()

        for resting_bone in resting_armature.pose.bones:
            props = getattr(resting_bone.bone, "hotools_boneprops", None)
            if props is None:
                continue

            mapping_name = props.humanoidMapping.strip()
            if not mapping_name:
                continue

            if mapping_name in resting_mapping_map:
                duplicate_resting_mappings.add(mapping_name)
                continue

            resting_mapping_map[mapping_name] = resting_bone

        added_count = 0
        existed_count = 0
        fallback_count = 0
        missing_count = 0
        skipped_no_mapping_count = 0

        for moving_bone in moving_armature.pose.bones:
            resting_bone = None

            props = getattr(moving_bone.bone, "hotools_boneprops", None)
            mapping_name = ""

            if props is not None:
                mapping_name = props.humanoidMapping.strip()

            if mapping_name:
                resting_bone = resting_mapping_map.get(mapping_name)
            else:
                skipped_no_mapping_count += 1

            # fallback：如果映射找不到，则尝试同名骨骼
            if resting_bone is None:
                resting_bone = resting_armature.pose.bones.get(moving_bone.name)
                if resting_bone is not None:
                    fallback_count += 1

            if resting_bone is None:
                missing_count += 1
                print(
                    f"[Bone Constraint] 未找到对应骨骼: "
                    f"moving={moving_bone.name}, mapping={mapping_name or '<EMPTY>'}"
                )
                continue

            existing_constraints = [
                c for c in moving_bone.constraints
                if (
                    c.type == self.constraint_type
                    and c.target == resting_armature
                    and c.subtarget == resting_bone.name
                )
            ]

            if existing_constraints:
                existed_count += 1
                print(
                    f"[Bone Constraint] 已存在: "
                    f"{moving_bone.name} -> {resting_bone.name} "
                    f"{self.constraint_type}"
                )
                continue

            constraint = moving_bone.constraints.new(self.constraint_type)
            constraint.name = f"{self.constraint_type}_{resting_bone.name}"
            constraint.target = resting_armature
            constraint.subtarget = resting_bone.name

            added_count += 1

            print(
                f"[Bone Constraint] 添加: "
                f"{moving_bone.name} -> {resting_bone.name} "
                f"mapping={mapping_name or '<SAME_NAME>'} "
                f"type={self.constraint_type}"
            )

        if duplicate_resting_mappings:
            print("[Bone Constraint] resting骨架存在重复humanoidMapping:")
            for name in sorted(duplicate_resting_mappings):
                print(f"  {name}")

        msg = (
            f"添加约束完成："
            f"新增 {added_count}，"
            f"已存在 {existed_count}，"
            f"同名回退 {fallback_count}，"
            f"未找到 {missing_count}"
        )

        if skipped_no_mapping_count:
            msg += f"，moving无映射 {skipped_no_mapping_count}"

        if duplicate_resting_mappings:
            msg += f"，resting重复映射 {len(duplicate_resting_mappings)}"

        self.report({'INFO'}, msg)
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
        pose_bones = context.selected_pose_bones

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
    
class OP_movingArmture_clear_constraint(Operator):
    bl_idname = "ho.movingarmture_clear_constraint"
    bl_label = "清空移动骨架中的所有约束"
    bl_description = "清空移动骨架中的所有约束"

    def execute(self, context):
        scene = context.scene
        moving_armature = scene.bone_constraint_moving_armature
        if not moving_armature:
            self.report({'WARNING'}, "需要指定移动骨架")
            return {'CANCELLED'}

        # 遍历目标骨架的每个骨骼，并删除所有指定类型的约束
        for moving_bone in moving_armature.pose.bones:
            # 直接删除目标骨骼上的所有指定类型的约束
            constraints_to_remove = [c for c in moving_bone.constraints]
            for constraint in constraints_to_remove:
                moving_bone.constraints.remove(constraint)
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
        pose_bones = context.selected_pose_bones

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

class OP_Mapping_WriteHumanoidBoneProps(Operator):
    bl_idname = "ho.mapping_write_humanoid_boneprops"
    bl_label = "自动计算选中骨架中的Humanoid映射"
    bl_description = "自动指定Humanoid映射，填入bone的hotools自定义属性"
    bl_options = {'REGISTER', 'UNDO'}

    clear_unmapped: BoolProperty(
        name="清空未匹配",
        default=False,
        description="清空没有自动匹配到的骨骼映射",
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        obj = context.object

        if obj is None or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个Armature")
            return {'CANCELLED'}

        armature = obj.data
        bones = list(armature.bones)

        if not bones:
            self.report({'WARNING'}, "当前Armature没有骨骼")
            return {'CANCELLED'}

        source_names = [bone.name for bone in bones]

        try:
            result = auto_map_source_names_to_humanoid(source_names)
        except Exception as e:
            self.report({'ERROR'}, f"自动Humanoid映射失败: {e}")
            return {'CANCELLED'}

        source_to_target = {
            match.source_name: match.target_name
            for match in result.matches
        }

        written_count = 0
        cleared_count = 0
        skipped_count = 0

        for bone in bones:
            props = getattr(bone, "hotools_boneprops", None)

            if props is None:
                skipped_count += 1
                continue

            target_name = source_to_target.get(bone.name)

            if target_name:
                props.humanoidMapping = target_name
                written_count += 1
            elif self.clear_unmapped:
                props.humanoidMapping = ""
                cleared_count += 1

        unmatched_count = len(result.unmatched_sources)
        low_confidence_count = len(result.low_confidence_matches)

        msg = (
            f"Humanoid映射完成："
            f"写入 {written_count}，"
            f"未匹配源骨骼 {unmatched_count}，"
            f"低置信度 {low_confidence_count}"
        )

        if self.clear_unmapped:
            msg += f"，清空 {cleared_count}"

        if skipped_count:
            msg += f"，跳过无属性骨骼 {skipped_count}"

        self.report({'INFO'}, msg)

        print("[Humanoid Auto Mapping]")
        print(f"Armature: {obj.name}")
        print(f"Written: {written_count}")
        print(f"Unmatched sources: {unmatched_count}")
        print(f"Low confidence: {low_confidence_count}")

        if result.low_confidence_matches:
            print("Low confidence matches:")
            for match in result.low_confidence_matches:
                print(
                    f"  {match.source_name} -> {match.target_name} "
                    f"score={match.score:.1f} "
                    f"reason={match.reason}"
                )

        if result.unmatched_sources:
            print("Unmatched sources:")
            for name in result.unmatched_sources:
                print(f"  {name}")

        return {'FINISHED'}


def drawBoneHumanoidPanel(layout: UILayout, context: Context):
    scene = context.scene

    box = layout.box()
    box.label(text="Humanoid映射")

    row = box.row(align=True)
    row.operator(OP_Mapping_WriteHumanoidBoneProps.bl_idname,text="自动映射",icon="AUTO",).clear_unmapped = False
    row.operator(OP_Mapping_WriteHumanoidBoneProps.bl_idname,text="重新映射",).clear_unmapped = True


    row = box.row(align=True)
    row.prop_search(scene, "bone_constraint_resting_armature",scene,"objects",text="固定",icon="ARMATURE_DATA",)
    row.prop_search(scene,"bone_constraint_moving_armature",scene,"objects",text="移动",icon="ARMATURE_DATA",)

    col = box.column(align=True)
    row = col.row(align=True)

    row.operator(OP_SameNameBone_addConstraint.bl_idname,text="约束-复制位置",).constraint_type = 'COPY_LOCATION'

    row.operator(OP_SameNameBone_addConstraint.bl_idname,text="约束-复制旋转",).constraint_type = 'COPY_ROTATION'

    row.operator(OP_movingArmture_clear_constraint.bl_idname,text="",icon="TRASH",)

    row = box.row(align=True)
    row.operator(OP_BoneApplyConstraint.bl_idname,text="应用约束到骨骼",)
    row.operator(OP_BoneRemoveConstraints.bl_idname,text="移除骨骼约束",)

cls = [
    OP_SameNameBone_addConstraint,
    OP_BoneApplyConstraint,
    OP_movingArmture_clear_constraint,
    OP_BoneRemoveConstraints,
    OP_Mapping_WriteHumanoidBoneProps,
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()

