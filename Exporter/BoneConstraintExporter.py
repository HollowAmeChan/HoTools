import bpy
import os
import json
import mathutils
import math
from bpy.types import PropertyGroup, UIList, Operator, Panel
from mathutils import Vector
from types import SimpleNamespace
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty

def reg_props():
    return


def ureg_props():
    return


class OP_2unity_exportJsonBoneConstraint(Operator, ExportHelper):
    bl_idname = "ho.exportboneconstraint_unityjson"
    bl_label = "导出约束"
    bl_description = "导出活动骨架内的约束为json文件,仅约束到本骨架的其他骨的约束可以被导出"
    filename_ext = ".json"

    filter_glob: bpy.props.StringProperty(
        default="constraint.json",
        options={'HIDDEN'},
        maxlen=255,
    )  # type: ignore

    def execute(self, context):
        armature = context.active_object

        # 验证选择对象是否为骨架
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "活动物体不是骨架")
            return {'CANCELLED'}

        constraint_mapping = {
            'COPY_LOCATION': 'Location',
            'COPY_ROTATION': 'Rotation',
            'COPY_SCALE': 'Scale',
            'CHILD_OF': 'Child'
        }

        bones_data = []

        # 遍历所有姿势骨骼
        for pose_bone in armature.pose.bones:
            constraints_list = []

            # 检查每个骨骼的约束
            for constraint in pose_bone.constraints:
                constraint: bpy.types.Constraint
                # 跳过未启用的约束
                if not constraint.enabled:
                    continue

                # 筛选支持的约束类型
                if constraint.type not in constraint_mapping:
                    continue

                # 获取约束目标信息
                target_obj = constraint.target
                if not target_obj:
                    continue

                # 处理骨骼目标路径
                if target_obj and target_obj.type == 'ARMATURE' and target_obj == armature:
                    if constraint.subtarget:
                        target_path = constraint.subtarget  # 仅约束到本骨架的其他骨的约束可以被导出
                    else:
                        continue  # 如果子目标为空，跳过这个约束
                else:
                    continue  # 如果目标不是当前骨架，跳过这个约束

                # 收集约束数据
                constraints_list.append({
                    'type': constraint_mapping[constraint.type],
                    'targetPath': target_path,
                    'weight': constraint.influence
                })

            # 仅添加有约束的骨骼
            if constraints_list:
                bones_data.append({
                    'boneName': pose_bone.name,
                    'constraints': constraints_list
                })

        # 构建最终数据结构
        export_data = {"bones": bones_data}

        # 写入JSON文件
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=4, ensure_ascii=False)
            self.report({'INFO'}, f"成功导出 {len(bones_data)} 个骨骼的约束")
        except Exception as e:
            self.report({'ERROR'}, f"导出失败: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}



cls = [
    OP_2unity_exportJsonBoneConstraint
]

def OPF_2unity_exportJsonBoneConstraint(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(OP_2unity_exportJsonBoneConstraint.bl_idname, text="Hotools-BoneConstraint(.json)")



def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.TOPBAR_MT_file_export.append(OPF_2unity_exportJsonBoneConstraint)#导出菜单添加操作
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.TOPBAR_MT_file_export.remove(OPF_2unity_exportJsonBoneConstraint)
    ureg_props()
