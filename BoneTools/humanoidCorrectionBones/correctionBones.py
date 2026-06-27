# 本文件用于集中维护 Humanoid 修正骨的自动生成操作。
# 这里会承载大量面向具体 humanoid mapping 的特判逻辑，例如:
# - 给上臂、前臂、大腿、小腿等位置自动生成 Twist 修正骨；
# - 给肩、肘、腕、髋、膝等区域自动生成 fan / spread 一类辅助骨；
# - 根据 hotools 的 HumanoidMapping / DeformTag / 骨骼命名规则决定具体生成策略；
# - 复用 BoneTools.boneTwist 中已经实现的 Twist 骨创建与权重分配方法，避免重复维护。
#
# 当前文件先只搭建 Operator、注册入口和面板绘制入口。后续新增规则时，应优先把
# 单个部位的判断与生成逻辑拆成独立方法，避免把所有 humanoid 特判塞进 execute。

import bpy
from bpy.types import Context, Operator, UILayout
from bpy.props import BoolProperty, FloatProperty, IntProperty

from ..boneTwist import TwistBoneCore


def reg_props():
    return


def ureg_props():
    return


def drawHumanoidCorrectionBonesPanel(layout: UILayout, context: Context):
    row = layout.row(align=True)
    row.operator(
        OP_HumanoidCorrectionBonesGenerate.bl_idname,
        text="生成Humanoid修正骨",
    )


class HumanoidCorrectionBonesCore:
    @staticmethod
    def get_active_armature(context: Context):
        obj = context.active_object
        if obj is None:
            return None

        if obj.type == "ARMATURE":
            return obj

        if obj.type == "MESH":
            for mod in obj.modifiers:
                if mod.type == "ARMATURE" and mod.object:
                    return mod.object

        return None

    @staticmethod
    def iter_humanoid_bones(armature: bpy.types.Object):
        for pose_bone in armature.pose.bones:
            props = getattr(pose_bone.bone, "hotools_boneprops", None)
            if props is None:
                continue

            humanoid_mapping = getattr(props, "humanoidMapping", "").strip()
            if not humanoid_mapping:
                continue

            yield pose_bone, props, humanoid_mapping

    @staticmethod
    def collect_candidate_rules(armature: bpy.types.Object):
        candidates = []

        for pose_bone, props, humanoid_mapping in (
            HumanoidCorrectionBonesCore.iter_humanoid_bones(armature)
        ):
            mapping_key = humanoid_mapping.lower()
            if "twist" in mapping_key:
                candidates.append({
                    "type": "twist",
                    "bone_name": pose_bone.name,
                    "mapping": humanoid_mapping,
                    "props": props,
                })

        return candidates

    @staticmethod
    def generate(context: Context, armature: bpy.types.Object, operator) -> int:
        candidates = HumanoidCorrectionBonesCore.collect_candidate_rules(armature)

        # 后续会在这里按 mapping 调用 TwistBoneCore.objs_bone_twist 或 fan 骨生成逻辑。
        # 先引用一次核心类型，保证本模块和 boneTwist 的依赖关系在框架期就明确。
        _twist_core = TwistBoneCore
        _ = _twist_core

        return len(candidates)


class OP_HumanoidCorrectionBonesGenerate(Operator):
    bl_idname = "ho.humanoid_correction_bones_generate"
    bl_label = "生成Humanoid修正骨"
    bl_description = """
    根据当前骨架的 HumanoidMapping 自动生成修正骨的框架操作。
    计划用途:集中处理人体骨架的 Twist 修正骨、fan 骨和其它辅助修正骨。
            后续会按不同 mapping 写入具体特判，并复用 boneTwist 中的生成与权重处理方法。
            当前版本只扫描当前骨架中带 HumanoidMapping 的骨骼并统计候选规则，不实际修改骨架。"""
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return HumanoidCorrectionBonesCore.get_active_armature(context) is not None

    def execute(self, context):
        armature = HumanoidCorrectionBonesCore.get_active_armature(context)
        if armature is None:
            self.report({"ERROR"}, "没有找到可处理的骨架")
            return {"CANCELLED"}

        candidate_count = HumanoidCorrectionBonesCore.generate(
            context,
            armature,
            self,
        )

        self.report(
            {"INFO"},
            f"Humanoid修正骨框架已就绪，扫描到候选规则 {candidate_count} 个",
        )
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout



cls = [
    OP_HumanoidCorrectionBonesGenerate,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    for item in cls:
        bpy.utils.unregister_class(item)
    ureg_props()

