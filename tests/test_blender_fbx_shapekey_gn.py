"""FBX 导出“形态键 + 几何节点修改器”回归测试（需要 Blender 后台运行）。

背景：Blender 原生 FBX 导出在物体还有修改器要应用时走 evaluated mesh
（io_scene_fbx 的 bpy.data.meshes.new_from_object 分支），而求值网格不带形态键
（Blender 议题 #104714），于是“形态键 + 几何节点”的物体导出的 FBX 里 BlendShape
会被静默丢掉。HoTools 现在会在导出前把形态键烘焙穿过修改器栈。

覆盖：
  1. 保留几何节点（ignoreGeometryNodes=False）+ 形态键 → 几何节点结果与形态键都在 FBX 里；
  2. 形态键的形变确实写进了 FBX（该键的顶点坐标和基础键不同）；
  3. 导出结束回滚：工程里的形态键与几何节点修改器恢复原样；
  4. 默认（忽略几何节点）仍然保留形态键；
  5. 只有骨架修改器时不触发烘焙（骨架留给导出做蒙皮），形态键照常保留；
  6. 隐式操作：形态键烘焙与三角化都没有开关，导出流程无条件执行；
  7. 烘焙时骨架可能处于 POSE：烘出来的基础网格不得含骨架形变（双重形变隐患）。
"""

import math
import shutil
import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import register as bonetools_register, unregister as bonetools_unregister
from Exporter import FbxExporter
from ShapekeyTools import operators as shapekey_operators


# 导出结果写在测试目录下的临时文件夹里，结束时删除。
# （不用系统临时目录：受限环境下 FBX 写出可能被拒绝，那是环境问题、与导出功能无关。）
OUT_DIR = Path(__file__).resolve().parent / "_fbx_shapekey_out"
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


def shape_key_x_coords(ob, key_name):
    key = ob.data.shape_keys.key_blocks[key_name]
    return [key.data[i].co.x for i in range(len(key.data))]


bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
bonetools_register()  # 应用骨架姿态需要 ho.apply_rest_pose
try:
    # ── 1. 保留几何节点：几何节点结果与形态键都要在 ──────────────────────────
    armature, ob = build_scene("keep")
    activate_all([armature, ob], armature)
    base_vertices = len(ob.data.vertices)
    evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    expected_vertices = len(evaluated.data.vertices)
    assert expected_vertices > base_vertices, "测试场景的几何节点应当增加顶点"

    filepath = OUT_DIR / "shapekey_gn_keep.fbx"
    assert bpy.ops.ho.final_fbx_export(
        "EXEC_DEFAULT",
        filepath=str(filepath),
        ignoreGeometryNodes=False,
        triangulateMeshes=True,
        **NO_METADATA,
    ) == {"FINISHED"}

    # 导出后工程应回滚：形态键与几何节点修改器都在
    # （导出末尾走 undo，数据块会被重建，必须按名重取对象，不能复用导出前的引用）
    ob_after = bpy.data.objects.get("Mesh_keep")
    assert ob_after is not None
    assert ob_after.data.shape_keys is not None, "导出后工程里的形态键没恢复"
    assert [k.name for k in ob_after.data.shape_keys.key_blocks] == ["Basis", "Wide"]
    assert len(ob_after.data.vertices) == base_vertices, "导出后基础网格没恢复"
    assert [m.type for m in ob_after.modifiers] == ["ARMATURE", "NODES"]
    assert ob_after.data.shape_keys.key_blocks["Wide"].data[1].co.x == 2.0

    imported = readback(filepath)
    assert imported is not None, "FBX 里没有网格"
    assert len(imported.data.vertices) == expected_vertices, (
        f"几何节点结果应当进入 FBX：{len(imported.data.vertices)} != {expected_vertices}"
    )
    assert imported.data.shape_keys is not None, "FBX 里丢了形态键"
    assert [k.name for k in imported.data.shape_keys.key_blocks] == ["Basis", "Wide"]
    wide_x = shape_key_x_coords(imported, "Wide")
    basis_x = shape_key_x_coords(imported, "Basis")
    assert max(abs(a - b) for a, b in zip(wide_x, basis_x)) > 0.1, (
        "Wide 形态键的形变没有写进 FBX"
    )
    assert all(len(polygon.vertices) == 3 for polygon in imported.data.polygons), (
        "带形态键的网格也应当被三角化（烘焙步骤里一并完成）"
    )

    # ── 2. 默认（忽略几何节点）：形态键保留，几何节点被移除 ──────────────────
    armature_default, ob_default = build_scene("default")
    activate_all([armature_default, ob_default], armature_default)
    filepath_default = OUT_DIR / "shapekey_gn_default.fbx"
    assert bpy.ops.ho.final_fbx_export(
        "EXEC_DEFAULT",
        filepath=str(filepath_default),
        triangulateMeshes=True,
        **NO_METADATA,
    ) == {"FINISHED"}

    imported_default = readback(filepath_default)
    assert imported_default is not None
    assert len(imported_default.data.vertices) == base_vertices
    assert [k.name for k in imported_default.data.shape_keys.key_blocks] == ["Basis", "Wide"]
    assert all(len(polygon.vertices) == 3 for polygon in imported_default.data.polygons), (
        "默认路径下带形态键的网格也应当被三角化"
    )

    # ── 3. 只有骨架修改器：不烘焙（骨架留给导出做蒙皮），形态键照常保留 ────────
    armature_bone, ob_bone = build_scene("armatureonly")
    activate_all([armature_bone, ob_bone], armature_bone)
    ob_bone.modifiers.remove(ob_bone.modifiers["GN"])
    filepath_bone = OUT_DIR / "shapekey_armature_only.fbx"
    assert bpy.ops.ho.final_fbx_export(
        "EXEC_DEFAULT",
        filepath=str(filepath_bone),
        **NO_METADATA,
    ) == {"FINISHED"}
    ob_bone_after = bpy.data.objects.get("Mesh_armatureonly")
    assert ob_bone_after is not None
    assert [modifier.type for modifier in ob_bone_after.modifiers] == ["ARMATURE"], (
        "只有骨架修改器时不应触发烘焙"
    )
    imported_bone = readback(filepath_bone)
    assert imported_bone is not None
    assert imported_bone.data.shape_keys is not None
    assert [k.name for k in imported_bone.data.shape_keys.key_blocks] == ["Basis", "Wide"]

    # ── 4. 烘焙时必须排除骨架形变（导出流程此时可能把骨架放在 POSE）────────────
    # 直接调用导出侧的烘焙函数验证：骨架处于 POSE 且骨骼摆过姿态时，烘出来的基础网格
    # 必须是“未经骨架形变”的静置形状，否则导出后会被骨架修改器再形变一次（双重形变）。
    armature_pose, ob_pose = build_scene("poseleak")
    activate_all([armature_pose, ob_pose], armature_pose)
    bpy.ops.object.mode_set(mode="POSE")
    pose_bone = armature_pose.pose.bones["Bone"]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler[0] = math.radians(90.0)  # 绕 X 转 90°：静置网格会被明显抬起
    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode="OBJECT")
    armature_pose.data.pose_position = "POSE"

    baked, skipped, failed = FbxExporter.FBXExporter.bake_shape_keys_through_modifiers(
        [ob_pose], triangulate=True
    )
    assert baked and not skipped and not failed, (baked, skipped, failed)
    assert armature_pose.data.pose_position == "POSE", "烘焙后应还原骨架的 POSE 显示状态"
    pose_leak = max(abs(vertex.co.z) for vertex in ob_pose.data.vertices)
    assert pose_leak < 1e-5, f"当前姿态被烘进了基础网格（双重形变隐患）：z={pose_leak}"
    assert ob_pose.data.shape_keys is not None
    assert [key.name for key in ob_pose.data.shape_keys.key_blocks] == ["Basis", "Wide"]

    # ── 5. 带形态键的网格必须留在 FBX 里（回归：应用骨架姿态替换物体后整块丢失）──
    # ho.apply_rest_pose 对带形态键的网格会走 ho.apply_armature_modifiers_keepshapekeys，
    # 那个操作符会“删掉原物体、用副本顶替”。若副本改名时原名还被原物体占着，副本会变成
    # “xxx.001”，而导出流程按名字跟踪物体 → 该物体直接掉出导出范围，FBX 里整个消失。
    # 这里复现完整链路：网格必须父级到骨架（apply_rest_pose 只处理骨架的子级网格）。
    shapekey_operators.register_keepshapekeys_operator = bpy.utils.register_class(
        shapekey_operators.OP_ApplyArmatureModifiersKeepShapekeys
    )
    try:
        armature_keep, ob_keep = build_scene("keepshapekeys")
        ob_keep.parent = armature_keep
        ob_keep.matrix_parent_inverse = armature_keep.matrix_world.inverted()
        activate_all([armature_keep, ob_keep], armature_keep)
        filepath_keep = OUT_DIR / "shapekey_keepshapekeys.fbx"
        assert bpy.ops.ho.final_fbx_export(
            "EXEC_DEFAULT",
            filepath=str(filepath_keep),
            **NO_METADATA,
        ) == {"FINISHED"}

        # 导出后工程应回滚：物体还在原名下，没有 .001 残留
        assert bpy.data.objects.get("Mesh_keepshapekeys") is not None, (
            "应用骨架姿态后物体没回到原名（副本拿到了 .001 后缀）"
        )
        assert bpy.data.objects.get("Mesh_keepshapekeys.001") is None, (
            "出现了 .001 副本残留，说明改名顺序不对"
        )
        imported_keep = readback(filepath_keep)
        assert imported_keep is not None, "带形态键的网格在 FBX 里整个丢失了"
        assert imported_keep.name.startswith("Mesh_keepshapekeys")
        assert imported_keep.data.shape_keys is not None, "FBX 里丢了形态键"
        assert [k.name for k in imported_keep.data.shape_keys.key_blocks] == ["Basis", "Wide"]
    finally:
        bpy.utils.unregister_class(shapekey_operators.OP_ApplyArmatureModifiersKeepShapekeys)

finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bonetools_unregister()
    shutil.rmtree(OUT_DIR, ignore_errors=True)

print("FBX_SHAPEKEY_GN_OK", bpy.app.version_string)
