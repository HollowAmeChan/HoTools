import importlib
import sys
import types
from pathlib import Path

import bpy
import gpu


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

# 构造轻量包环境，避开根包注册副作用。后台 Blender 没有 GPU 上下文，
# VertexGroupTools 的类级绘制 shader 与本测试无关，因此只在导入阶段替换。
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
original_from_builtin = gpu.shader.from_builtin
gpu.shader.from_builtin = lambda _name: None
try:
    bone_dissolve = importlib.import_module("HoTools.BoneTools.boneDissolve")
    bone_operators = importlib.import_module("HoTools.BoneTools.boneOperators")
    bone_split = importlib.import_module("HoTools.BoneTools.boneSplit")
    bone_twist = importlib.import_module("HoTools.BoneTools.auxBone.boneTwist")
    checker_define = importlib.import_module("HoTools.Checker.objectChecker.define")
    fbx_exporter = importlib.import_module("HoTools.Exporter.FbxExporter")
    shapekey_operators = importlib.import_module("HoTools.ShapekeyTools.operators")
    vertex_group_operators = importlib.import_module(
        "HoTools.VertexGroupTools.vertexGroupOperators"
    )
finally:
    gpu.shader.from_builtin = original_from_builtin


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_armature(name, bone_name):
    data = bpy.data.armatures.new(f"{name}Data")
    armature = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(armature)
    activate(armature)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new(bone_name)
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 1.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def make_mesh(name, vertices):
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(vertices, [], [])
    mesh = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(mesh)
    return mesh


rig_a = make_armature("ConsumerRigA", "BoneA")
rig_b = make_armature("ConsumerRigB", "BoneB")

# 权重操作器只能接受唯一的真实形变骨架，不能在双修改器时静默取第一个。
weighted_mesh = make_mesh(
    "ConsumerWeightedMesh",
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
)
modifier_a = weighted_mesh.modifiers.new("RigA", "ARMATURE")
modifier_a.object = rig_a
modifier_b = weighted_mesh.modifiers.new("RigB", "ARMATURE")
modifier_b.object = rig_b
group_a = weighted_mesh.vertex_groups.new(name="BoneA")
group_a.add([0], 1.0, "REPLACE")
group_b = weighted_mesh.vertex_groups.new(name="BoneB")
group_b.add([1], 1.0, "REPLACE")
weighted_mesh.vertex_groups.active_index = group_a.index
activate(weighted_mesh)

poll_operators = (
    bone_dissolve.OP_DissolveBoneWithWeight,
    bone_split.OP_SplitBoneWithWeight,
    bone_twist.OP_TwistBoneWithWeight,
)
assert all(not operator.poll(bpy.context) for operator in poll_operators)
weighted_mesh.modifiers.remove(modifier_b)
assert all(operator.poll(bpy.context) for operator in poll_operators)
modifier_b = weighted_mesh.modifiers.new("RigB", "ARMATURE")
modifier_b.object = rig_b

# Checker 必须合并全部真实形变骨架的骨名，否则 BoneB 对应顶点会被误报。
assert checker_define.check_geometry_zero_weight_vertices(weighted_mesh) == []
assert fbx_exporter.FBXExporter.get_weighted_bone_names(rig_a) == {"BoneA"}
assert fbx_exporter.FBXExporter.get_weighted_bone_names(rig_b) == {"BoneB"}

# 普通 LOD Empty 只表达资产归属：顶点组/形态键工具可以找到骨架，
# 但权重清理不能把它误当成真实形变网格。
lod_root = bpy.data.objects.new("ConsumerLOD0", None)
lod_group = bpy.data.objects.new("ConsumerLODGroup", None)
bpy.context.scene.collection.objects.link(lod_root)
bpy.context.scene.collection.objects.link(lod_group)
lod_root.parent = rig_a
lod_group.parent = lod_root
lod_mesh = make_mesh(
    "ConsumerLODMesh",
    [(0.0, 0.0, 0.0), (0.0, 0.5, 0.0)],
)
lod_mesh.parent = lod_group
lod_bone_group = lod_mesh.vertex_groups.new(name="BoneA")
lod_bone_group.add([0], 1.0, "REPLACE")
lod_mesh.vertex_groups.new(name="NotABone")
lod_mesh.vertex_groups.active_index = lod_bone_group.index
activate(lod_mesh)

switch_operator = vertex_group_operators.OP_VertexGroupTools_Switch_VG_byCursor
assert switch_operator._find_rig(lod_mesh) == rig_a
assert checker_define.check_geometry_zero_weight_vertices(lod_mesh) == []
assert fbx_exporter.FBXExporter.clean_export_weights([lod_mesh]) == 0

registered_classes = (
    vertex_group_operators.OP_RemoveNoneWeightGroup,
    shapekey_operators.OP_ShapekeyTools_GenerateHideShapeKey,
    bone_operators.OP_ApplyRestPose,
)
for cls in registered_classes:
    bpy.utils.register_class(cls)

try:
    result = bpy.ops.ho.vertexgrouptools_remove_none_weight_group("EXEC_DEFAULT")
    assert result == {"FINISHED"}
    assert lod_mesh.vertex_groups.get("BoneA") is not None
    assert lod_mesh.vertex_groups.get("NotABone") is None

    result = bpy.ops.ho.shapekeytools_generate_hide_shapekey(
        "EXEC_DEFAULT",
        mode="WEIGHT",
        threshold=0.5,
        slide_smooth=False,
    )
    assert result == {"FINISHED"}
    assert lod_mesh.data.shape_keys.key_blocks.get("Hide_BoneA") is not None

    # 目标骨架层级下若只有指向另一骨架的修改器，静置姿态必须取消且不改修改器。
    wrong_target_mesh = make_mesh("ConsumerWrongTarget", [(0.0, 0.0, 0.0)])
    wrong_target_mesh.parent = rig_a
    wrong_modifier = wrong_target_mesh.modifiers.new("WrongRig", "ARMATURE")
    wrong_modifier.object = rig_b
    activate(rig_a)
    result = bpy.ops.ho.apply_rest_pose("EXEC_DEFAULT")
    assert result == {"CANCELLED"}
    assert wrong_target_mesh.modifiers.get("WrongRig") is not None
finally:
    for cls in reversed(registered_classes):
        bpy.utils.unregister_class(cls)


# 所有本次迁移的消费者都不得再绕回 Blender 内置单结果接口。
consumer_modules = (
    bone_dissolve,
    bone_operators,
    bone_split,
    bone_twist,
    checker_define,
    fbx_exporter,
    shapekey_operators,
    vertex_group_operators,
)
for module in consumer_modules:
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert ".find_armature(" not in source

print("ARMATURE_RESOLUTION_CONSUMERS_OK", bpy.app.version_string)
