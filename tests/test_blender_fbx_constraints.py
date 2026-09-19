"""FBX 导出约束处理回归测试（需要 Blender 后台运行）。

背景：HoTools 的约束只通过 JSON（Rig 约束 IR）中转给运行时，而 Blender 内置 FBX 导出
不会删掉约束，而是把约束结果当成物体/骨骼的实际变换写进 FBX，导致两边内外不一致。
所以导出侧提供「应用约束」开关（默认关闭 = 删除）：

  1. 关（默认）：约束 JSON 写完后删除导出范围内的约束，导出后随 undo 还原；
  2. 关（默认）：应用骨架姿态时不把约束结果固化进静置/网格（先临时静音再还原）；
  3. 开：约束参与应用姿态的求值，并保留到内置导出（约束结果写进 FBX 变换）。
"""

import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import register as bonetools_register, unregister as bonetools_unregister
from Exporter import FbxExporter


# 导出结果写在测试目录下的临时文件夹里，结束时删除。
# （不用系统临时目录：受限环境下 FBX 写出可能被拒绝，那是环境问题、与导出功能无关。）
OUT_DIR = Path(__file__).resolve().parent / "_fbx_constraints_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 关掉随 FBX 一起生成的 Unity 元数据 JSON：测试只关心 FBX 内容
NO_METADATA = {
    "exportUnityMetadata": False,
    "exportBoneConstraint": False,
    "exportBoneCollection": False,
    "exportHumanoidMapping": False,
}


def activate_all(objs, active):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def make_gn_group(name):
    """建一个会改变拓扑的几何节点组（细分一级）。"""
    node_group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    node_group.interface.new_socket(
        "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"
    )
    node_group.interface.new_socket(
        "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"
    )
    group_in = node_group.nodes.new("NodeGroupInput")
    group_out = node_group.nodes.new("NodeGroupOutput")
    subdivide = node_group.nodes.new("GeometryNodeSubdivisionSurface")
    subdivide.inputs["Level"].default_value = 1
    node_group.links.new(group_in.outputs["Geometry"], subdivide.inputs["Mesh"])
    node_group.links.new(subdivide.outputs["Mesh"], group_out.inputs["Geometry"])
    return node_group


def build_scene(tag):
    armature = bpy.data.objects.new(f"Rig_{tag}", bpy.data.armatures.new(f"RigData_{tag}"))
    bpy.context.scene.collection.objects.link(armature)
    activate_all([armature], armature)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.data.edit_bones.new("Bone")
    bone.head, bone.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh = bpy.data.meshes.new(f"MeshData_{tag}")
    # 基础网格用一个四边形：细分后是 4 个四边面，便于验证三角化确实生效
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    ob = bpy.data.objects.new(f"Mesh_{tag}", mesh)
    bpy.context.scene.collection.objects.link(ob)
    group = ob.vertex_groups.new(name="Bone")
    group.add([0, 1, 2, 3], 1.0, "REPLACE")
    modifier = ob.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature

    ob.shape_key_add(name="Basis", from_mix=False)
    wide = ob.shape_key_add(name="Wide", from_mix=False)
    wide.data[1].co.x = 2.0

    gn = ob.modifiers.new("GN", "NODES")
    gn.node_group = make_gn_group(f"GNGroup_{tag}")
    return armature, ob


def readback(filepath):
    """把导出的 FBX 导回空场景，返回其中的网格物体。"""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(filepath))
    for ob in bpy.data.objects:
        if ob.type == "MESH":
            return ob
    return None


bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
bonetools_register()  # 应用骨架姿态需要 ho.apply_rest_pose
try:
    # ── 1. 约束：JSON 扫描导出完成后必须清空，再调用内置导出 ─────────────────
    # 内置 FBX 导出不会删约束、会把约束结果当成实际变换写进 FBX，而约束只走 JSON 中转，
    # 所以导出前必须清干净；这里验证清理逻辑本身，以及导出后工程里的约束能回滚回来。
    armature_c, ob_c = build_scene("constraints")
    activate_all([armature_c, ob_c], armature_c)
    bone_target = armature_c.pose.bones["Bone"]
    pose_constraint = bone_target.constraints.new("COPY_LOCATION")
    pose_constraint.target = armature_c
    pose_constraint.subtarget = "Bone"
    object_constraint = ob_c.constraints.new("COPY_ROTATION")
    object_constraint.target = armature_c

    cleared_objects, cleared_constraints = FbxExporter.FBXExporter.clear_exported_constraints(
        [armature_c, ob_c]
    )
    assert cleared_objects == 2, cleared_objects
    assert cleared_constraints == 2, cleared_constraints
    assert len(armature_c.pose.bones["Bone"].constraints) == 0
    assert len(ob_c.constraints) == 0

    # 重新加上约束后跑一次完整导出：约束文件应当生成，导出结束工程里的约束要回来
    retry_constraint = armature_c.pose.bones["Bone"].constraints.new("COPY_LOCATION")
    retry_constraint.target = armature_c
    retry_constraint.subtarget = "Bone"
    filepath_constraints = OUT_DIR / "shapekey_gn_constraints.fbx"
    assert bpy.ops.ho.final_fbx_export(
        "EXEC_DEFAULT",
        filepath=str(filepath_constraints),
        **{**NO_METADATA, "exportBoneConstraint": True},
    ) == {"FINISHED"}

    armature_after = bpy.data.objects.get("Rig_constraints")
    assert armature_after is not None
    assert len(armature_after.pose.bones["Bone"].constraints) == 1, (
        "导出前的约束清空必须随 undo 一起回滚"
    )
    constraint_json = OUT_DIR / "HoFBX"
    assert constraint_json.is_dir(), "约束 IR 应当写进 HoFBX 目录"

    # ── 6. 开关语义：关（默认）=删除约束，开=应用约束（内置导出把结果写进变换）─────
    # 用“被约束摆位的网格”来观察：约束把它从原点推到 x=5。
    # （不能用空物体：导出参数 object_types 只要 MESH/ARMATURE。）
    # 关：约束被删除 → FBX 里它还在原点；开：约束保留 → FBX 里它在被推到的位置。
    def build_constrained_mesh(tag):
        target = bpy.data.objects.new(f"Target_{tag}", None)
        bpy.context.scene.collection.objects.link(target)
        target.location = (5.0, 0.0, 0.0)
        mesh = bpy.data.meshes.new(f"DrivenData_{tag}")
        mesh.from_pydata(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0)], [], [(0, 1, 2)]
        )
        driven = bpy.data.objects.new(f"Driven_{tag}", mesh)
        bpy.context.scene.collection.objects.link(driven)
        constraint = driven.constraints.new("COPY_LOCATION")
        constraint.target = target
        return driven, target

    def exported_location(tag, **operator_kwargs):
        driven, target = build_constrained_mesh(tag)
        activate_all([driven, target], driven)
        filepath = OUT_DIR / f"constraint_switch_{tag}.fbx"
        assert bpy.ops.ho.final_fbx_export(
            "EXEC_DEFAULT",
            filepath=str(filepath),
            **{**NO_METADATA, **operator_kwargs},
        ) == {"FINISHED"}
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(filepath))
        return bpy.data.objects.get(f"Driven_{tag}")

    driven_cleared = exported_location("cleared")
    assert driven_cleared is not None
    cleared_position = max(abs(value) for value in driven_cleared.matrix_world.translation)
    assert cleared_position < 1e-4, (
        f"默认（关）应当删除约束：约束结果不该进 FBX，实际位置 {cleared_position}"
    )

    driven_applied = exported_location("applied", applyExportConstraints=True)
    assert driven_applied is not None
    applied_position = max(
        abs(value) for value in driven_applied.matrix_world.translation
    )
    assert applied_position > 4.0, (
        f"开着「应用约束」时内置导出应把约束结果写进变换，实际位置 {applied_position}"
    )

    # ── 7. 形态骨+约束＋应用骨架姿态：关=约束不参与固化，开=参与 ──────────────
    # 网格必须父级到骨架，ho.apply_rest_pose 才会处理它（它只遍历骨架的子级网格）。
    # 约束把被约束骨推开 3 个单位：关闭开关时约束先被静音，网格不该被推走；
    # 开启时约束参与求值，网格会被推走。
    def build_constrained_rig(tag):
        rig = bpy.data.objects.new(f"Rig_{tag}", bpy.data.armatures.new(f"RigData_{tag}"))
        bpy.context.scene.collection.objects.link(rig)
        activate_all([rig], rig)
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = rig.data.edit_bones
        driver = edit_bones.new("Driver")
        driver.head, driver.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        driven_bone = edit_bones.new("Driven")
        driven_bone.head, driven_bone.tail = (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)
        # 刻意不做父子关系：否则被约束骨会通过父子继承也跟着动，看不出约束本身的差别
        bpy.ops.object.mode_set(mode="OBJECT")

        mesh = bpy.data.meshes.new(f"Data_{tag}")
        mesh.from_pydata(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            [],
            [(0, 1, 2, 3)],
        )
        ob = bpy.data.objects.new(f"Mesh_{tag}", mesh)
        bpy.context.scene.collection.objects.link(ob)
        group = ob.vertex_groups.new(name="Driven")
        group.add([0, 1, 2, 3], 1.0, "REPLACE")
        modifier = ob.modifiers.new("Armature", "ARMATURE")
        modifier.object = rig
        ob.parent = rig  # ho.apply_rest_pose 只处理骨架的子级网格

        bpy.ops.object.mode_set(mode="POSE")
        rig.pose.bones["Driver"].location = (0.0, 0.0, 3.0)
        constraint = rig.pose.bones["Driven"].constraints.new("COPY_LOCATION")
        constraint.target = rig
        constraint.subtarget = "Driver"
        bpy.context.view_layer.update()
        bpy.ops.object.mode_set(mode="OBJECT")
        return rig, ob

    def exported_mesh_center(tag, **operator_kwargs):
        rig, ob = build_constrained_rig(tag)
        activate_all([rig, ob], rig)
        filepath = OUT_DIR / f"pose_constraint_{tag}.fbx"
        assert bpy.ops.ho.final_fbx_export(
            "EXEC_DEFAULT",
            filepath=str(filepath),
            **{**NO_METADATA, **operator_kwargs},
        ) == {"FINISHED"}
        # 导出后约束要还原（静音与删除都随 undo 回滚）
        rig_after = bpy.data.objects.get(f"Rig_{tag}")
        assert rig_after is not None
        assert len(rig_after.pose.bones["Driven"].constraints) == 1, (
            "导出后约束应当还原"
        )
        assert rig_after.pose.bones["Driven"].constraints[0].mute is False, (
            "临时静音必须还原"
        )
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(filepath))
        imported = next(
            (item for item in bpy.data.objects if item.type == "MESH"), None
        )
        assert imported is not None, "FBX 里没有网格"
        corners = [imported.matrix_world @ vertex.co for vertex in imported.data.vertices]
        center = sum(corners, Vector()) / len(corners)
        return center.length

    kept = exported_mesh_center("constraint_off")
    applied = exported_mesh_center("constraint_on", applyExportConstraints=True)
    assert applied - kept > 1.5, (
        f"开时应把约束位移固化进网格（推动约 3 个单位）：关={kept} 开={applied}"
    )
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bonetools_unregister()
    shutil.rmtree(OUT_DIR, ignore_errors=True)

print("FBX_CONSTRAINTS_OK", bpy.app.version_string)
