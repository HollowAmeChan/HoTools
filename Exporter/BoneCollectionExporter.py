"""
HoTools 骨骼集合导出器 — 导出骨架的骨骼集合(Bone Collections)为 JSON 文件。

导出内容:
- 骨架下持有的所有骨骼集合(直接读取 Blender 原生的骨骼集合)
- 每个集合的名称、层级(父集合)以及该集合直接持有的骨骼名称列表

JSON 格式:
{
  "version": "1.0",
  "exportTime": "ISO8601字符串",
  "armatureName": "骨架名",
  "collections": [
    {
      "name": "集合名",
      "parent": "父集合名(顶层为空字符串)",
      "bones": ["骨名1", "骨名2", ...]
    },
    ...
  ]
}

说明:
- bones 只包含该集合**直接持有**的骨骼(不含子集合递归),与 Blender 界面显示一致。
- Blender 4.0+ 才有骨骼集合(BoneCollection)。低版本无 collections_all 属性时导出空列表。
"""

import bpy
import json
from datetime import datetime, timezone
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper


def reg_props():
    return


def ureg_props():
    return


class BoneCollectionExporter:
    """骨骼集合导出器 — 纯静态工具类。

    只依赖 armature.data(bpy.types.Armature),不依赖 Operator/文件系统,
    方便 FBX 导出等其他流程直接复用(如打包一并导出)。
    """

    VERSION = "1.0"

    @staticmethod
    def iter_bone_collections(armature):
        """返回骨架的所有骨骼集合(含嵌套)。兼容无 collections_all 的旧版本。"""
        collections = getattr(armature, "collections_all", None)
        if collections is not None:
            return list(collections)

        result = []
        pending = list(getattr(armature, "collections", []))
        while pending:
            collection = pending.pop(0)
            result.append(collection)
            pending.extend(getattr(collection, "children", []))
        return result

    @staticmethod
    def build_collections_list(armature):
        """构造骨骼集合列表(不含外层 version/armatureName 等元信息)。

        便于 FBX 导出等场景把该列表直接嵌入到更大的导出结构里。
        """
        collections_list = []
        for collection in BoneCollectionExporter.iter_bone_collections(armature):
            parent = getattr(collection, "parent", None)
            parent_name = parent.name if parent is not None else ""
            bone_names = [bone.name for bone in collection.bones]
            collections_list.append({
                "name": collection.name,
                "parent": parent_name,
                "bones": bone_names,
            })
        return collections_list

    @staticmethod
    def build_export_dict(armature):
        """构造完整的骨骼集合导出字典结构(含元信息)。"""
        return {
            "version": BoneCollectionExporter.VERSION,
            "exportTime": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "armatureName": armature.name,
            "collections": BoneCollectionExporter.build_collections_list(armature),
        }

    @staticmethod
    def export_to_json(armature) -> str:
        """导出为 JSON 字符串(格式化,缩进2空格)。"""
        data = BoneCollectionExporter.build_export_dict(armature)
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def export_to_file(armature, filepath):
        """导出骨骼集合到指定文件,返回导出字典结构。"""
        data = BoneCollectionExporter.build_export_dict(armature)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        return data


class OP_2unity_exportJsonBoneCollection(Operator, ExportHelper):
    bl_idname = "ho.exportbonecollection_unityjson"
    bl_label = "导出骨骼集合"
    bl_description = "导出活动骨架的骨骼集合(Bone Collections)为 JSON 文件,记录每个集合持有的骨骼名称"
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
            collections_list = BoneCollectionExporter.build_collections_list(armature.data)

            if not collections_list:
                self.report({'WARNING'}, "该骨架没有骨骼集合")
                return {'CANCELLED'}

            BoneCollectionExporter.export_to_file(armature.data, self.filepath)

            total_bones = sum(len(c["bones"]) for c in collections_list)
            self.report(
                {'INFO'},
                f"成功导出 {len(collections_list)} 个骨骼集合(共 {total_bones} 条骨骼引用)"
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"导出失败: {str(e)}")
            return {'CANCELLED'}

        return {'FINISHED'}


cls = [
    OP_2unity_exportJsonBoneCollection
]


def OPF_2unity_exportJsonBoneCollection(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator(
        OP_2unity_exportJsonBoneCollection.bl_idname,
        text="HoTools - 骨骼集合 (.json)"
    )


def register():
    for i in cls:
        bpy.utils.register_class(i)

    bpy.types.TOPBAR_MT_file_export.append(OPF_2unity_exportJsonBoneCollection)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    bpy.types.TOPBAR_MT_file_export.remove(OPF_2unity_exportJsonBoneCollection)
    ureg_props()
