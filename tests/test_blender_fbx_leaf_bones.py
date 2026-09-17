"""FBX 导出“添加叶骨”回归测试（需要 Blender 后台运行）。

覆盖：
  1. 左右对称、两侧都有真实权重 → 两侧都加叶骨；
  2. 半身几何 + 镜像修改器（翻转顶点组，两侧顶点组都存在）→ 两侧都加叶骨
     （回归“只给 _R 一侧加叶骨”）；
  3. 无权重末端骨 / 有子级的骨 → 不加叶骨；
  4. HoTools 辅助骨即使有权重也不加叶骨；
  5. 已有遗留 _end 子骨骼 → 不重复添加。
"""

import sys
from pathlib import Path

import bpy
from bpy.props import BoolProperty, PointerProperty
from bpy.types import PropertyGroup


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from Exporter import FbxExporter


class TestAuxInfo(PropertyGroup):
    isAuxBone: BoolProperty(default=False)


class TestBoneProps(PropertyGroup):
    auxBone: PointerProperty(type=TestAuxInfo)


for cls in (TestAuxInfo, TestBoneProps):
    bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops = PointerProperty(type=TestBoneProps)


SIDE_BONES = ("hand", "foot", "toe")


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_rig(name):
    armature = bpy.data.objects.new(name, bpy.data.armatures.new(f"{name}Data"))
    bpy.context.scene.collection.objects.link(armature)
    activate(armature)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    root = edit_bones.new("root")
    root.head, root.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    for index, base in enumerate(SIDE_BONES):
        for sign, suffix in ((-1.0, "_R"), (1.0, "_L")):
            bone = edit_bones.new(base + suffix)
            z = float(index + 1)
            bone.head = (sign, 0.0, z)
            bone.tail = (sign, 0.0, z + 1.0)
            bone.parent = root
            bone.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def make_mesh(name, armature, vertex_weights, extra_groups=()):
    """vertex_weights：顶点下标 → {顶点组名: 权重}；extra_groups 建空组。"""
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata([(0.0, float(i), 0.0) for i in range(len(vertex_weights))], [], [])
    mesh = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(mesh)
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    for group_name in extra_groups:
        mesh.vertex_groups.new(name=group_name)
    for index, weights in enumerate(vertex_weights):
        for group_name, weight in weights.items():
            group = mesh.vertex_groups.get(group_name) or mesh.vertex_groups.new(name=group_name)
            group.add([index], weight, "REPLACE")
    return mesh


def add_mirror(mesh):
    mirror = mesh.modifiers.new("Mirror", "MIRROR")
    mirror.use_axis = (True, False, False)
    mirror.use_mirror_vertex_groups = True
    return mirror


def leaf_names(armature):
    return sorted(b.name for b in armature.data.bones if b.name.endswith("_end"))


def grow_leaves(armature):
    FbxExporter.FBXExporter.add_leaf_bones_to_armatures([armature], [], None)
    return leaf_names(armature)


ALL_SIDES = [f"{base}{suffix}" for base in SIDE_BONES for suffix in ("_L", "_R")]


# ── 1. 对称网格、两侧都有真实权重 ────────────────────────────────────────────
rig_a = make_rig("LeafRigA")
mesh_a = make_mesh("LeafMeshA", rig_a, [{group_name: 1.0} for group_name in ALL_SIDES])
assert grow_leaves(rig_a) == sorted(f"{name}_end" for name in ALL_SIDES)


# ── 2. 半身几何 + 镜像修改器：_L 权重只存在于求值网格里 ──────────────────────
# 注意：镜像修改器的“翻转顶点组”只在对侧顶点组已存在时才翻转（自动权重绑定一般会给两侧
# 都建组）。只有 _R 组时，镜像出的左半身会继续引用 _R，导出结果本身就没有 _L 权重，
# 那种资源只给 _R 加叶骨才是对的。
rig_b = make_rig("LeafRigB")
mesh_b = make_mesh(
    "LeafMeshB",
    rig_b,
    [{f"{base}_R": 1.0} for base in SIDE_BONES],          # 原始几何只有右半身
    extra_groups=[f"{base}_L" for base in SIDE_BONES],     # 自动权重会为左侧建好空组
)
add_mirror(mesh_b)
weighted_b = FbxExporter.FBXExporter.get_weighted_bone_names(rig_b)
assert set(ALL_SIDES) <= weighted_b, weighted_b
assert grow_leaves(rig_b) == sorted(f"{name}_end" for name in ALL_SIDES)


# ── 3. 无权重末端骨 / 有子级的骨不加叶骨 ────────────────────────────────────
rig_c = make_rig("LeafRigC")
mesh_c = make_mesh("LeafMeshC", rig_c, [
    {"hand_R": 1.0}, {"foot_R": 1.0},          # toe_R 无权重
    {"hand_L": 1.0}, {"foot_L": 1.0},
])
assert grow_leaves(rig_c) == sorted([
    "hand_R_end", "foot_R_end", "hand_L_end", "foot_L_end",
])

rig_d = make_rig("LeafRigD")
activate(rig_d)
bpy.ops.object.mode_set(mode="EDIT")
parent_bone = rig_d.data.edit_bones["hand_R"]
child = rig_d.data.edit_bones.new("hand_R_tip")
child.head, child.tail = parent_bone.tail, (parent_bone.tail.x, 0.0, 3.0)
child.parent = parent_bone
bpy.ops.object.mode_set(mode="OBJECT")
mesh_d = make_mesh("LeafMeshD", rig_d, [{"hand_R": 1.0}, {"hand_L": 1.0}])
assert grow_leaves(rig_d) == ["hand_L_end"]  # hand_R 有子级，不当末端骨


# ── 4. 辅助骨即使有权重也不加叶骨 ───────────────────────────────────────────
rig_e = make_rig("LeafRigE")
mesh_e = make_mesh("LeafMeshE", rig_e, [{"hand_R": 1.0}, {"hand_L": 1.0}])
rig_e.data.bones["hand_L"].hotools_boneprops.auxBone.isAuxBone = True
assert grow_leaves(rig_e) == ["hand_R_end"]


# ── 5. 已有遗留 _end 子骨骼：不重复添加，保留原有 ───────────────────────────
rig_f = make_rig("LeafRigF")
mesh_f = make_mesh("LeafMeshF", rig_f, [{"hand_R": 1.0}, {"hand_L": 1.0}])
activate(rig_f)
bpy.ops.object.mode_set(mode="EDIT")
leftover_parent = rig_f.data.edit_bones["hand_L"]
leftover = rig_f.data.edit_bones.new("hand_L_end")
leftover.head, leftover.tail = leftover_parent.tail, (leftover_parent.tail.x, 0.0, 3.0)
leftover.parent = leftover_parent
leftover.use_connect = True
bpy.ops.object.mode_set(mode="OBJECT")
assert grow_leaves(rig_f) == ["hand_L_end", "hand_R_end"]

for cls in (TestBoneProps, TestAuxInfo):
    bpy.utils.unregister_class(cls)
if hasattr(bpy.types.Bone, "hotools_boneprops"):
    del bpy.types.Bone.hotools_boneprops

print("FBX_LEAF_BONES_OK", bpy.app.version_string)
