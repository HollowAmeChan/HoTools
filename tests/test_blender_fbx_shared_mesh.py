"""HoFBX 导出：实例化资产（Alt+D 共享网格）不能把导出打断（需要 Blender 后台运行）。

用户现场：导出到一半弹出
``导出失败: RuntimeError: 错误: 无法应用一个多用户：物体 "Cube.106", Mesh "Cube.017", 中止``。

原因：矫正物体变换（fix_object）会对**全场景顶级物体**做 transform_apply，
而 Blender 拒绝对多用户数据应用变换；这一步没有错误处理，于是整个导出中止。
同一类问题还会让数据传递/形态键烘焙在共享网格上失败或静默跳过（多用户数据不让应用修改器）。

本测试锁住：
  1. 导出范围里有共享网格的顶级物体（哪怕没被选中）时，导出必须照常完成；
  2. 选中的 Alt+D 实例要先把网格数据拆成单用户，再应用数据传递等修改器；
  3. fix_object 对多用户数据不能抛异常，且不留“矩阵转了、数据没转”的半成品。
"""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import bpy
from mathutils import Matrix


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Exporter import FbxExporter  # noqa: E402


OUT_DIR = Path(__file__).resolve().parent / "_fbx_shared_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

NO_METADATA = {
    "exportUnityMetadata": False,
    "exportBoneConstraint": False,
    "exportBoneCollection": False,
    "exportHumanoidMapping": False,
}

MULTI_USER_MARKERS = ("多用户", "multi user", "Multi user")


def activate_all(objs, active):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def make_quad(name):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    # 新链接的物体要等一次求值刷新才出现在 view_layer.objects 里，
    # 而导出流程的各步骤都按这个名字集合判定“在不在导出范围”。
    bpy.context.view_layer.update()
    return obj


def make_linked_pair(tag):
    """建一对 Alt+D 实例（共享同一份 Mesh 数据）。"""
    original = make_quad(f"Shared_{tag}")
    clone = original.copy()
    clone.name = f"Shared_{tag}_clone"
    bpy.context.scene.collection.objects.link(clone)
    bpy.context.view_layer.update()
    assert original.data == clone.data and original.data.users == 2
    return original, clone


def export_and_capture(tag):
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
    # ── 1. 单元：共享网格拆分后两个物体各自独立，且都只剩一个用户 ────────────────
    first, second = make_linked_pair("split")
    made, failed = FbxExporter.FBXExporter.split_shared_mesh_data([first, second])
    assert not failed, failed
    assert made == 1, f"只需给一个用户换数据，实际 {made}"
    assert first.data != second.data, "拆分后不应再共享同一份 Mesh 数据"
    assert first.data.users == 1 and second.data.users == 1, (
        first.data.users,
        second.data.users,
    )

    # ── 2. 单元：fix_object 对多用户数据不能抛异常，也不能留半成品矩阵 ───────────
    root_a, root_b = make_linked_pair("fix")
    root_a.rotation_euler.z = 0.4
    activate_all([root_a], root_a)
    bpy.context.view_layer.update()

    def world_positions(obj):
        return [
            tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices
        ]

    before = world_positions(root_a)
    FbxExporter.FBXExporter.fix_object(root_a)  # 之前这里会抛“无法应用一个多用户”
    bpy.context.view_layer.update()
    after = world_positions(root_a)
    # 这一步是“把 -90°X 烘进数据、再把物体矩阵补 +90°X”，
    # 所以物体矩阵本身会变，不变的是世界空间里的几何。
    delta = max(
        abs(a - b) for pa, pb in zip(before, after) for a, b in zip(pa, pb)
    )
    assert delta < 1e-5, f"矫正物体变换后世界空间几何变了（最大差 {delta}）"
    assert root_a.data != root_b.data, "矫正变换时应把多用户数据拆开"
    assert abs(root_a.rotation_euler.z - 0.4) < 1e-6, "物体自身旋转应当被保留下来"

    # ── 3. 整链路：导出范围之外还有实例化资产时，导出必须照常完成 ────────────────
    exported = make_quad("Exported")
    asset_a, asset_b = make_linked_pair("asset")
    asset_a.rotation_euler.z = 0.3
    asset_b.rotation_euler.z = 0.7
    activate_all([exported], exported)
    result, output = export_and_capture("unselected_asset")
    assert result == {"FINISHED"}, result
    assert not any(marker in output for marker in MULTI_USER_MARKERS), output

    # ── 4. 整链路：选中的 Alt+D 实例上的数据传递要能真的应用上 ──────────────────
    source = make_quad("TransferSource")
    source.data.normals_split_custom_set(
        [(0.7071068, 0.0, 0.7071068)] * len(source.data.loops)
    )
    source.data.update()
    instance_a, instance_b = make_linked_pair("transfer")
    for instance in (instance_a, instance_b):
        transfer = instance.modifiers.new("DataTransfer", "DATA_TRANSFER")
        transfer.object = source
        transfer.use_loop_data = True
        transfer.data_types_loops = {"CUSTOM_NORMAL"}
        transfer.loop_mapping = "TOPOLOGY"
        transfer.mix_mode = "REPLACE"
        transfer.mix_factor = 1.0
    activate_all([instance_a, instance_b], instance_a)
    result, output = export_and_capture("instanced_transfer")
    assert result == {"FINISHED"}, result
    assert not any(marker in output for marker in MULTI_USER_MARKERS), output
    assert "[HoTools FBX] 数据传递修改器隐式修复：手动应用了 2 个修改器" in output, output
    assert "数据传递修改器隐式修复失败" not in output, output
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)

import shutil  # noqa: E402

shutil.rmtree(OUT_DIR, ignore_errors=True)
print("FBX_SHARED_MESH_OK", bpy.app.version_string)
