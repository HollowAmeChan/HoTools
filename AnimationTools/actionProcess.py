import bpy
from bpy.types import Operator,UILayout


# region 变量
def reg_props():
    return


def ureg_props():
    return
# endregion


def _copy_action_setting(source_anim, target_anim, prop_name):
    if hasattr(source_anim, prop_name) and hasattr(target_anim, prop_name):
        setattr(target_anim, prop_name, getattr(source_anim, prop_name))


class OP_CopyActiveAnimationToSelected(Operator):
    bl_idname = "ho.copy_active_animation_to_selected"
    bl_label = "应用活动物体动画到选中物体"
    bl_description = "将活动物体当前 Action、Action 槽和 Action 设置应用到其他选中物体"
    bl_options = {'REGISTER', 'UNDO'}

    copy_action_settings: bpy.props.BoolProperty(
        name="同步 Action 设置",
        description="同步 Action 的混合、外推、影响值和 NLA 开关",
        default=True,
        options={'SKIP_SAVE'},
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        active = getattr(context, "active_object", None)
        selected = getattr(context, "selected_objects", ())
        return active is not None and any(obj != active for obj in selected)

    def execute(self, context):
        source = context.active_object
        source_anim = getattr(source, "animation_data", None)

        if source_anim is None or source_anim.action is None:
            self.report({'ERROR'}, "活动物体没有当前 Action，无法应用动画")
            return {'CANCELLED'}

        source_action = source_anim.action
        source_slot = getattr(source_anim, "action_slot", None)
        targets = [obj for obj in context.selected_objects if obj != source]

        copied_count = 0
        failed = []

        for target in targets:
            try:
                target_anim = target.animation_data_create()
                target_anim.action = source_action

                if hasattr(target_anim, "action_slot"):
                    target_anim.action_slot = source_slot
                elif hasattr(target_anim, "action_slot_handle"):
                    target_anim.action_slot_handle = getattr(
                        source_anim, "action_slot_handle", 0
                    )

                if self.copy_action_settings:
                    for prop_name in (
                        "action_blend_type",
                        "action_extrapolation",
                        "action_influence",
                        "use_nla",
                    ):
                        _copy_action_setting(source_anim, target_anim, prop_name)

            except Exception as ex:
                failed.append(f"{target.name}: {ex}")
                continue

            copied_count += 1

        if copied_count == 0:
            message = "未能应用到任何选中物体"
            if failed:
                message += f"；{failed[0]}"
            self.report({'ERROR'}, message)
            return {'CANCELLED'}

        if failed:
            self.report(
                {'WARNING'},
                f"已应用到 {copied_count} 个物体，失败 {len(failed)} 个：{failed[0]}"
            )
        else:
            slot_text = (
                getattr(source_slot, "name_display", None)
                or getattr(source_slot, "identifier", None)
                or "无槽"
            )
            self.report(
                {'INFO'},
                f"已将 Action「{source_action.name}」和槽「{slot_text}」应用到 {copied_count} 个物体"
            )

        return {'FINISHED'}


class OP_ClearSelectedAnimationSlots(Operator):
    bl_idname = "ho.clear_selected_animation_slots"
    bl_label = "批量清除动画槽"
    bl_description = "清除选中物体当前 Action 的槽绑定，不删除 Action 本身"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(getattr(context, "selected_objects", ()))

    def execute(self, context):
        cleared_count = 0
        skipped_count = 0
        failed = []

        for obj in context.selected_objects:
            anim = getattr(obj, "animation_data", None)
            if anim is None:
                skipped_count += 1
                continue

            try:
                had_slot = False

                if hasattr(anim, "action_slot"):
                    if anim.action_slot is not None:
                        anim.action_slot = None
                        had_slot = True
                elif hasattr(anim, "action_slot_handle"):
                    if anim.action_slot_handle != 0:
                        anim.action_slot_handle = 0
                        had_slot = True

                if hasattr(anim, "last_slot_identifier") and anim.last_slot_identifier:
                    anim.last_slot_identifier = ""
                    had_slot = True

                if not had_slot:
                    skipped_count += 1
                    continue

            except Exception as ex:
                failed.append(f"{obj.name}: {ex}")
                continue

            cleared_count += 1

        if cleared_count == 0:
            message = "未清除任何动画槽"
            if failed:
                message += f"；{failed[0]}"
            self.report({'WARNING'}, message)
            return {'CANCELLED'}

        if failed:
            self.report(
                {'WARNING'},
                f"已清除 {cleared_count} 个物体的动画槽，跳过 {skipped_count} 个，失败 {len(failed)} 个：{failed[0]}"
            )
        else:
            self.report(
                {'INFO'},
                f"已清除 {cleared_count} 个物体的动画槽，跳过 {skipped_count} 个"
            )

        return {'FINISHED'}


class OP_FixScaledAnimatedArmatureActions(Operator):
    bl_idname = "ho.fix_scaled_animated_armature_actions"
    bl_label = "修复缩放导致的动画位移错误"
    bl_description = "修复因骨架 Object 缩放导致的所有骨骼位移动画错误（破坏性操作）"
    bl_options = {'REGISTER', 'UNDO'}

    warning_text: bpy.props.StringProperty(
        name="⚠ 警告",
        default=(
            "该操作会【直接修改当前文件中的动画数据以及骨架变换】，属于不可逆的破坏性操作。\n\n"
            "在继续之前请确认以下事项：\n\n"
            "• 你已经【完整备份】了当前文件或动画数据\n"
            "• 本操作会处理【当前文件中的全部 Action】\n"
            "  （包括未绑定到当前骨架、或曾被其他物体使用的 Action）\n"
            "• 如文件中存在不属于该骨架的 Action，请务必提前拆分文件\n"
            "• 当前选中的对象是需要修复的【目标骨架 Armature】\n"
            "• 骨架 Object 原点位于【世界中心 (0,0,0)】\n"
            "• 骨架 Object 为【等比缩放 (n, n, n)】\n"
            "• 动画中包含真实空间意义的骨骼位移（pose.bones[].location）\n\n"
            "完成修复后：\n"
            "• 所有 Action 将【仅适用于修复后的骨架尺寸】\n"
            "• 不可再用于原始缩放尺寸的骨架\n"
            "• 如果修复后rig位置奇怪为正常现象，所有的rig都需要重新装配\n"
            "• （因为涉及到ik及其他控制器的位置，都需要重新计算） \n\n"
            "确认无误后，点击【确认】继续。"
        ),
        options={'SKIP_SAVE'}
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'ARMATURE'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        for line in self.warning_text.split("\n"):
            col.label(text=line)

    def execute(self, context):
        arm = context.object

        sx, sy, sz = arm.scale
        if not (abs(sx - sy) < 1e-6 and abs(sx - sz) < 1e-6):
            self.report({'ERROR'}, "检测到非等比缩放，该操作不支持非等比 Scale")
            return {'CANCELLED'}

        scale = sx
        if abs(scale - 1.0) < 1e-6:
            self.report({'INFO'}, "骨架 Scale 已为 1，无需修复")
            return {'CANCELLED'}


        fixed_actions = 0
        fixed_curves = 0
        fixed_keys = 0

        for action in bpy.data.actions:
            has_fix = False

            for fcu in action.fcurves:
                if not fcu.data_path.startswith('pose.bones["'):
                    continue
                if not fcu.data_path.endswith('"].location'):
                    continue

                for kp in fcu.keyframe_points:
                    kp.co.y *= scale
                    kp.handle_left.y *= scale
                    kp.handle_right.y *= scale
                    fixed_keys += 1

                fixed_curves += 1
                has_fix = True

            if has_fix:
                fixed_actions += 1

        if fixed_actions == 0:
            self.report(
                {'WARNING'},
                "未在任何 Action 中检测到可修复的骨骼位移动画（pose.bones[].location）"
            )
            return {'CANCELLED'}

        view_layer = context.view_layer
        view_layer.objects.active = arm

        bpy.ops.object.transform_apply(
            location=False,
            rotation=False,
            scale=True
        )


        self.report(
            {'INFO'},
            f"修复完成：{fixed_actions} 个 Action，"
            f"{fixed_curves} 条位移曲线，"
            f"{fixed_keys} 个关键帧"
        )

        return {'FINISHED'}



def drawActionProcessPanel(layout:UILayout, context):
    row = layout.row(align=True)
    row.operator(
        OP_CopyActiveAnimationToSelected.bl_idname, text="应用活动物体动画/槽到选中物体", icon='ACTION')
    row.operator(
        OP_ClearSelectedAnimationSlots.bl_idname, text="批量清除选中物体动画槽", icon='X')

    row = layout.row(align=True)
    row.operator(
        OP_FixScaledAnimatedArmatureActions.bl_idname, text="修复缩放导致的动画位移错误", icon='ARMATURE_DATA')


cls = [OP_CopyActiveAnimationToSelected,
       OP_ClearSelectedAnimationSlots,
       OP_FixScaledAnimatedArmatureActions,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
