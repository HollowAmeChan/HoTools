import bpy
from bpy.types import Operator,UILayout


# region 变量
def reg_props():
    return


def ureg_props():
    return
# endregion


class OP_FixScaledAnimatedArmatureActions(Operator):
    bl_idname = "ho.fix_scaled_animated_armature_actions"
    bl_label = "修复缩放导致的动画位移错误"
    bl_description = "修复因骨架 Object 缩放导致的所有骨骼位移动画错误（破坏性操作）"
    bl_options = {'REGISTER', 'UNDO'}

    # --------------------------------------------------
    # 警告文本
    # --------------------------------------------------

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

    # --------------------------------------------------
    # Poll
    # --------------------------------------------------

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj and obj.type == 'ARMATURE'

    # --------------------------------------------------
    # 弹窗
    # --------------------------------------------------

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        for line in self.warning_text.split("\n"):
            col.label(text=line)

    # --------------------------------------------------
    # 执行
    # --------------------------------------------------

    def execute(self, context):
        arm = context.object

        # --------------------------------------------------
        # 检查缩放（仅支持等比）
        # --------------------------------------------------

        sx, sy, sz = arm.scale
        if not (abs(sx - sy) < 1e-6 and abs(sx - sz) < 1e-6):
            self.report({'ERROR'}, "检测到非等比缩放，该操作不支持非等比 Scale")
            return {'CANCELLED'}

        scale = sx
        if abs(scale - 1.0) < 1e-6:
            self.report({'INFO'}, "骨架 Scale 已为 1，无需修复")
            return {'CANCELLED'}

        # --------------------------------------------------
        # 遍历并修复所有 Action
        # --------------------------------------------------

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

        # --------------------------------------------------
        # 应用骨架缩放
        # --------------------------------------------------

        view_layer = context.view_layer
        view_layer.objects.active = arm

        bpy.ops.object.transform_apply(
            location=False,
            rotation=False,
            scale=True
        )

        # --------------------------------------------------
        # 结果提示
        # --------------------------------------------------

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
        OP_FixScaledAnimatedArmatureActions.bl_idname, text="修复缩放导致的动画位移错误", icon='ARMATURE_DATA')


cls = [OP_FixScaledAnimatedArmatureActions,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
