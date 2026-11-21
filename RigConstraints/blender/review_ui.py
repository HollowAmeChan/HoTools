"""Armature Data review UI: all scans are explicit operator actions."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from . import review


def _armature(context):
    obj = context.object
    return obj if obj and obj.type == "ARMATURE" else None


class OT_RigConstraintReviewRefresh(Operator):
    bl_idname = "hotools.constraint_review_refresh"
    bl_label = "检查 / 刷新"
    bl_description = "只读检查当前骨架的普通约束和语义登记；不会修复或改写"

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None and context.object.mode != "EDIT"

    def execute(self, context):
        try:
            report = review.scan(context.object)
        except (ValueError, TypeError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已知 {len(report['known'])}，Unknown {len(report['unknown'])}，损坏 {len(report['broken'])}")
        return {"FINISHED"}


class OT_RigConstraintReviewSelect(Operator):
    bl_idname = "hotools.constraint_review_select"
    bl_label = "定位骨骼"
    bone: StringProperty()

    def execute(self, context):
        obj = _armature(context)
        if obj is None or self.bone not in obj.data.bones:
            return {"CANCELLED"}
        from Utils.bone_selection import select_bones
        select_bones(obj, [self.bone])
        return {"FINISHED"}


def draw_review(layout, context):
    obj = _armature(context)
    layout.operator("hotools.constraint_review_refresh", icon="FILE_REFRESH")
    if obj.mode == "EDIT":
        layout.label(text="请退出编辑模式后检查", icon="INFO")
    report = review.cached(obj)
    if report is None:
        layout.label(text="尚未检查 / 结果已失效", icon="INFO")
        return
    layout.label(text="上次检查：" + report["timestamp"])
    layout.label(text="手动修改后请重新刷新")
    for key, title, icon in (("broken", "损坏", "ERROR"), ("known", "已知", "CHECKMARK"), ("unknown", "Unknown", "QUESTION")):
        rows = report[key]
        header, body = layout.panel("ho_constraint_review_" + key, default_closed=key != "broken")
        header.label(text=f"{title}：{len(rows)}", icon=icon)
        if body is None:
            continue
        for item in rows:
            box = body.box()
            row = box.row(align=True)
            row.alert = key == "broken"
            owner = item["ownerBone"]
            row.label(text=owner + (" / " + item["label"] if item.get("label") else ""))
            if owner in obj.data.bones:
                row.operator("hotools.constraint_review_select", text="", icon="BONE_DATA").bone = owner
            box.label(text=item["message"])
    if report["mchPlans"]:
        layout.label(text=f"导出时生成 MCH：{len(report['mchPlans'])} 根（当前无 MCH 不算损坏）")
    if report["excludedCount"]:
        layout.label(text=f"未审查大型 HoAux 骨：{report['excludedCount']}")


class PT_RigConstraintReview(Panel):
    bl_idname = "DATA_PT_Hotools_ConstraintReview"
    bl_label = "HoTools 约束 IR 审查"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "data"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def draw(self, context):
        draw_review(self.layout, context)


CLASSES = (OT_RigConstraintReviewRefresh, OT_RigConstraintReviewSelect, PT_RigConstraintReview)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    review.clear_cache()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
