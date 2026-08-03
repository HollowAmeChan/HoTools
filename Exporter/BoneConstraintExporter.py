"""Standalone Blender operator for exporting the neutral rig constraint IR."""

import traceback

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from .ConstraintIRExporter import ConstraintIRExporter


def reg_props():
    return


def ureg_props():
    return


class OP_exportRigConstraintIR(Operator, ExportHelper):
    bl_idname = "ho.export_rig_constraint_ir"
    bl_label = "导出 Rig 约束 IR"
    bl_description = "导出 Aux 骨、原始 Blender 约束参数和 MCH 绑定；落地方案由导入端决定"
    filename_ext = ".json"

    filter_glob: bpy.props.StringProperty(
        default="*.json",
        options={"HIDDEN"},
        maxlen=255,
    )  # type: ignore

    def execute(self, context):
        armature = context.active_object
        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "请选择一个骨架对象")
            return {"CANCELLED"}

        try:
            constraint_ir = ConstraintIRExporter.build_ir(armature)
            if constraint_ir.is_empty():
                self.report({"WARNING"}, "未找到 Aux 骨、MCH 开关或 MCH 绑定")
                return {"CANCELLED"}

            with open(self.filepath, "w", encoding="utf-8") as output:
                import json

                json.dump(
                    constraint_ir.to_dict(),
                    output,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                output.write("\n")

            self.report(
                {"INFO"},
                "已导出 "
                f"{len(constraint_ir.aux_bones)} 根 Aux 骨、"
                f"{len(constraint_ir.mch_bindings)} 条 MCH 绑定、"
                f"{len(constraint_ir.known_constraints)} 条已知约束、"
                f"{len(constraint_ir.unknown_constraints)} 条未知约束",
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"导出失败: {exc}")
            return {"CANCELLED"}

        return {"FINISHED"}


CLASSES = (OP_exportRigConstraintIR,)


def draw_export_menu(self, _context):
    self.layout.operator_context = "INVOKE_DEFAULT"
    self.layout.operator(
        OP_exportRigConstraintIR.bl_idname,
        text="HoTools - Rig 约束 IR (.json)",
    )


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(draw_export_menu)
    reg_props()


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(draw_export_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    ureg_props()
