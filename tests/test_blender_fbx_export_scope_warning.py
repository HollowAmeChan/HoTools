"""FBX 导出「脱离导出范围」告警回归测试（需要 Blender 后台运行）。

这条告警用来把“预处理中物体被替换/改名后悄悄掉出导出范围”变成可见提示。
它必须满足两点，否则就是噪音：

  1. 正常导出（含空物体、非导出类型的选中项）不能误报；
  2. 物体真的脱离导出范围时必须报出来。

回归背景：最初用 ``ob.name in bpy.context.selected_objects`` 判断，而 selected_objects
是 Object 的 list，字符串成员判断恒为 False → 任何导出都会把所有物体报成“脱离范围”。
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Exporter import FbxExporter


OUT_DIR = Path(__file__).resolve().parent / "_fbx_scope_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NO_METADATA = {
    "exportUnityMetadata": False,
    "exportBoneConstraint": False,
    "exportBoneCollection": False,
    "exportHumanoidMapping": False,
}

WARNING_PREFIX = "[HoTools FBX] 警告：以下物体在预处理中脱离了导出范围"


def activate_all(objs, active):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def build_rig(tag):
    armature = bpy.data.objects.new(f"Rig_{tag}", bpy.data.armatures.new(f"RigData_{tag}"))
    bpy.context.scene.collection.objects.link(armature)
    activate_all([armature], armature)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("Bone")
    bone.head, bone.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh = bpy.data.meshes.new(f"Data_{tag}")
    mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)], [], [(0, 1, 2)])
    ob = bpy.data.objects.new(f"Mesh_{tag}", mesh)
    bpy.context.scene.collection.objects.link(ob)
    group = ob.vertex_groups.new(name="Bone")
    group.add([0, 1, 2], 1.0, "REPLACE")
    modifier = ob.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature

    empty = bpy.data.objects.new(f"Empty_{tag}", None)
    bpy.context.scene.collection.objects.link(empty)
    return armature, ob, empty


def export_and_capture(tag):
    """导出并抓取控制台输出，返回 (结果, 输出文本)。"""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = bpy.ops.ho.final_fbx_export(
            "EXEC_DEFAULT",
            filepath=str(OUT_DIR / f"{tag}.fbx"),
            **NO_METADATA,
        )
    return result, buffer.getvalue()


bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
try:
    # ── 1. 正常导出：不误报（选中里带空物体，属于非导出类型，也不该报）─────────
    armature, ob, empty = build_rig("clean")
    clean_names = (armature.name, ob.name)  # 导出末尾 undo 回滚会让旧引用失效
    activate_all([armature, ob, empty], armature)
    result, output = export_and_capture("clean")
    assert result == {"FINISHED"}, result
    assert WARNING_PREFIX not in output, f"正常导出不该出现脱离范围告警：\n{output}"
    for name in clean_names:
        assert bpy.data.objects.get(name) is not None, f"{name} 不该消失"

    # ── 2. 真的脱离导出范围：必须报出来 ──────────────────────────────────────
    # 模拟“物体被替换成副本、副本拿到 .001 后缀”的故障：临时把 restore_selection
    # 换成一个会把物体改名的版本，导出流程的按名跟踪就会丢掉它。
    original_restore = FbxExporter.FBXExporter.restore_selection

    def sabotage_restore(selection, active_object=None):
        result = original_restore(selection, active_object)
        for target in selection:
            if target.type == "MESH":
                target.select_set(False)
        return result

    armature_bad, ob_bad, empty_bad = build_rig("vanished")
    vanished_name = ob_bad.name  # 导出末尾的 undo 回滚会让旧引用失效，先把名字取出来
    activate_all([armature_bad, ob_bad, empty_bad], armature_bad)
    FbxExporter.FBXExporter.restore_selection = staticmethod(sabotage_restore)
    try:
        result, output = export_and_capture("vanished")
    finally:
        FbxExporter.FBXExporter.restore_selection = original_restore

    assert result == {"FINISHED"}, result
    assert WARNING_PREFIX in output, f"物体脱离导出范围时必须告警：\n{output}"
    assert vanished_name in output, output
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)

import shutil

shutil.rmtree(OUT_DIR, ignore_errors=True)
print("FBX_EXPORT_SCOPE_WARNING_OK", bpy.app.version_string)
