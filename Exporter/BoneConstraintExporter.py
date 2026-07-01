"""
HoTools 骨骼约束导出器 — 导出 Unity 可用的约束 JSON 文件。

导出流程:
1. ConstraintAnalyzer 识别语义约束(fan/twist/通用)
2. UnityConstraintMapper 映射为 Unity JSON 格式
3. 写入文件

只导出约束到当前骨架内部骨的约束;跨骨架约束被过滤。
"""

import bpy
import os
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper
from .ConstraintAnalyzer import ConstraintAnalyzer
from .UnityConstraintMapper import UnityConstraintMapper


def reg_props():
    return


def ureg_props():
    return


class OP_2unity_exportJsonBoneConstraint(Operator, ExportHelper):
    bl_idname = "ho.exportboneconstraint_unityjson"
    bl_label = "导出骨骼约束"
    bl_description = "导出活动骨架内的约束为 Unity JSON 文件。只导出约束到骨架内部骨的 HoTools 辅助骨约束(fan/twist)"
    filename_ext = ".json"

    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={'HIDDEN'},
        maxlen=255,
    )  # type: ignore

    def execute(self, context):
        armature = context.active_object

        # 验证选择
        if armature is None or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "请选择一个骨架对象")
            return {'CANCELLED'}

        try:
            # 1. 语义识别
            constraints_list, twist_chains = ConstraintAnalyzer.analyze(armature)

            # 统计信息
            total_constraints = len(constraints_list)
            total_twist_bones = sum(len(chain.twist_bones) for chain in twist_chains)
            total_exported = total_constraints + total_twist_bones

            if total_exported == 0:
                self.report({'WARNING'}, "未找到可导出的约束(辅助骨约束必须约束到骨架内部骨)")
                return {'CANCELLED'}

            # 2. Unity 映射
            json_str = UnityConstraintMapper.export_to_json(
                armature.name, constraints_list, twist_chains
            )

            # 3. 写入文件
            with open(self.filepath, 'w', encoding='utf-8') as f:
                f.write(json_str)

            # 报告成功
            fan_count = sum(1 for c in constraints_list if hasattr(c, 'fan_type'))
            twist_chain_count = len(twist_chains)
            self.report(
                {'INFO'},
                f"成功导出 {total_exported} 个约束 "
                f"(Fan: {fan_count}, Twist链: {twist_chain_count}共{total_twist_bones}骨)"
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"导出失败: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}


cls = [
    OP_2unity_exportJsonBoneConstraint
]


def OPF_2unity_exportJsonBoneConstraint(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(
        OP_2unity_exportJsonBoneConstraint.bl_idname,
        text="HoTools - 骨骼约束 (.json)"
    )


def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.TOPBAR_MT_file_export.append(OPF_2unity_exportJsonBoneConstraint)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.TOPBAR_MT_file_export.remove(OPF_2unity_exportJsonBoneConstraint)
    ureg_props()
