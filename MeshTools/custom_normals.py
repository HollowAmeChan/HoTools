"""Mesh custom split-normal import/export."""

import json

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector


class OP_CustomSplitNormals_Export(Operator, ExportHelper):
    bl_idname = "ho.custom_splitnormal_export"
    bl_label = "导出自定义拆边法向为文件"
    bl_description = "如果没有添加自定义法线则跳过"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        obj = context.object
        mesh = obj.data
        if not mesh.has_custom_normals:
            self.report({"WARNING"}, "当前网格没有自定义法线")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            with open(self.filepath, "w") as stream:
                json.dump([list(loop.normal) for loop in mesh.loops], stream)
        except Exception as error:
            self.report({"ERROR"}, f"导出失败: {error}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已导出 {len(mesh.loops)} 个自定义法线")
        return {"FINISHED"}


class OP_CustomSplitNormals_Import(Operator, ImportHelper):
    bl_idname = "ho.custom_splitnormal_import"
    bl_label = "导入自定义拆边法向文件"
    bl_description = "覆盖当前的自定义法向"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".json"

    @classmethod
    def poll(cls, context):
        return bool(context.object and context.object.type == "MESH")

    def execute(self, context):
        mesh = context.object.data
        try:
            with open(self.filepath, "r") as stream:
                normal_data = json.load(stream)
        except Exception as error:
            self.report({"ERROR"}, f"读取文件失败: {error}")
            return {"CANCELLED"}
        if len(normal_data) != len(mesh.loops):
            self.report({"ERROR"}, f"法线数量不匹配 ({len(normal_data)} vs {len(mesh.loops)})")
            return {"CANCELLED"}
        mesh.normals_split_custom_set([Vector(value).normalized() for value in normal_data])
        self.report({"INFO"}, f"成功导入并应用 {len(normal_data)} 个法线")
        return {"FINISHED"}

__all__ = ["OP_CustomSplitNormals_Export", "OP_CustomSplitNormals_Import"]
