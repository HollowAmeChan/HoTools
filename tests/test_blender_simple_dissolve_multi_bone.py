"""简单融并的多骨骼递归计划与执行测试（需要 Blender 后台运行）。

覆盖：
  1. DissolveBoneCore.build_transfer_plan 的递归解析、校验与镜像规则（纯字典输入）；
  2. “自动递归”模式下多骨骼端到端融并：权重合并、约束改写、层级调整；
  3. “指定目标”模式 + 镜像处理；
  4. 计划不合法时取消且不改动任何数据。
"""

import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from BoneTools import boneDissolve
from Utils import bone_utils


MODE_AUTO = boneDissolve.MODE_AUTO
MODE_SPECIFY = boneDissolve.MODE_SPECIFY
build_transfer_plan = boneDissolve.DissolveBoneCore.build_transfer_plan


def plan_of(parent_of, selected, **kwargs):
    kwargs.setdefault("bone_names", set(parent_of))
    kwargs.setdefault("flip_name", bpy.utils.flip_name)
    return build_transfer_plan(parent_of, selected, **kwargs)


# ══════════════════════════════════════════════════════════════════════════
# 1. 计划层：递归解析与校验
# ══════════════════════════════════════════════════════════════════════════
CHAIN = {"Q": None, "A": "Q", "B": "A", "C": "B", "D": "C"}

# 连续链：整条链并入最近的未选中父级
chain_plan = plan_of(CHAIN, ["B", "C"], mode=MODE_AUTO)
assert chain_plan["errors"] == []
assert chain_plan["deleting"] == ("C", "B")  # 深 → 浅
assert chain_plan["weight_groups"] == {"A": ("C", "B")}
assert chain_plan["constraint_map"] == {"B": "A", "C": "A"}
assert chain_plan["steps"]["C"]["parent"] == "B"
assert chain_plan["steps"]["C"]["new_parent"] == "A"
assert chain_plan["steps"]["C"]["depth"] == 3  # Q=0 → A=1 → B=2 → C=3

# 不连续选择：各自解析到自己的存活父级
gap_plan = plan_of(CHAIN, ["B", "D"], mode=MODE_AUTO)
assert gap_plan["errors"] == []
assert gap_plan["weight_groups"] == {"A": ("B",), "C": ("D",)}
assert gap_plan["steps"]["D"]["new_parent"] == "C"

# 分叉选择：共用同一个存活父级
fork_plan = plan_of({"root": None, "mid": "root", "left": "mid", "right": "mid"},
                    ["left", "right"], mode=MODE_AUTO)
assert fork_plan["weight_groups"] == {"mid": ("left", "right")}

# 指定目标：全部平铺到同一根骨，但层级仍按链上最近存活祖先
specify_plan = plan_of(CHAIN, ["B", "C"], mode=MODE_SPECIFY, target="Q")
assert specify_plan["weight_groups"] == {"Q": ("C", "B")}
assert specify_plan["steps"]["B"]["new_parent"] == "A"
assert specify_plan["steps"]["C"]["new_parent"] == "A"

# 计划校验：目标为空 / 不存在 / 也在融并范围内
for bad_kwargs, keyword in (
    ({"target": ""}, "不能为空"),
    ({"target": "Missing"}, "不存在于该骨架中"),
    ({"target": "B"}, "也在融并范围内"),
):
    bad = plan_of(CHAIN, ["B", "C"], mode=MODE_SPECIFY, **bad_kwargs)
    assert bad["errors"] and any(keyword in error for error in bad["errors"]), bad
    assert bad["weight_groups"] == {} and bad["steps"] == {}

# 自动递归：整条祖先链都被选中时没有存活父级，必须报错而不是静默丢权重
orphan = plan_of(CHAIN, ["Q", "A", "B"], mode=MODE_AUTO)
assert any("没有可用的存活父级" in error for error in orphan["errors"]), orphan
rescued = plan_of(CHAIN, ["Q", "A", "B"], mode=MODE_SPECIFY, target="D")
assert rescued["weight_groups"] == {"D": ("B", "A", "Q")}
assert rescued["steps"]["Q"]["new_parent"] is None

# 空选择 / 未知骨骼 / 重复选择
assert any("至少需要选择一根骨骼" in error
           for error in plan_of(CHAIN, [], mode=MODE_AUTO)["errors"])
assert any("找不到选中的骨骼" in error
           for error in plan_of(CHAIN, ["B", "ZZ"], mode=MODE_AUTO)["errors"])
assert plan_of(CHAIN, ["B", "B"], mode=MODE_AUTO)["deleting"] == ("B",)

# 镜像：自动递归时两侧各自落到自己的镜像父级
LIMB = {
    "root": None,
    "arm.L": "root", "arm.R": "root",
    "twist.L": "arm.L", "twist.R": "arm.R",
    "hand.L": "twist.L", "hand.R": "twist.R",
}
mirror_plan = plan_of(LIMB, ["twist.L"], mode=MODE_AUTO, mirror=True)
assert mirror_plan["deleting"] == ("twist.L", "twist.R")
assert mirror_plan["weight_groups"] == {"arm.L": ("twist.L",), "arm.R": ("twist.R",)}
assert mirror_plan["warnings"] == []

# 镜像 + 指定目标：镜像补齐的一侧并入翻转目标
specify_mirror = plan_of(LIMB, ["twist.L"], mode=MODE_SPECIFY, target="hand.L", mirror=True)
assert specify_mirror["weight_groups"] == {"hand.L": ("twist.L",), "hand.R": ("twist.R",)}

# 镜像 + 指定目标：显式选中的两侧一律并入显式指定的目标
both_sides = plan_of(LIMB, ["twist.L", "twist.R"], mode=MODE_SPECIFY, target="arm.L", mirror=True)
assert both_sides["weight_groups"] == {"arm.L": ("twist.L", "twist.R")}

# 镜像：翻转目标不存在时只处理显式选择
missing_target = build_transfer_plan(
    {"root": None, "arm.L": "root", "twist.L": "arm.L", "twist.R": "arm.L"},
    ["twist.L"],
    mode=MODE_SPECIFY,
    target="arm.L",
    mirror=True,
    bone_names={"root", "arm.L", "twist.L", "twist.R"},
    flip_name=bpy.utils.flip_name,
)
assert missing_target["deleting"] == ("twist.L",)
assert missing_target["weight_groups"] == {"arm.L": ("twist.L",)}
assert any("镜像目标骨" in warning for warning in missing_target["warnings"])


# ══════════════════════════════════════════════════════════════════════════
# 测试脚手架
# ══════════════════════════════════════════════════════════════════════════
def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_bone(edit_bones, name, head_z, tail_z, parent=None, connect=False):
    bone = edit_bones.new(name)
    bone.head = (0.0, 0.0, head_z)
    bone.tail = (0.0, 0.0, tail_z)
    if parent is not None:
        bone.parent = parent
        bone.use_connect = connect
    return bone


def make_rig(name, chain, extra_bones=(), connect=False):
    """chain：从根到末端的骨骼名列表；extra_bones：附加在根骨下的对称骨骼。"""
    armature = bpy.data.objects.new(name, bpy.data.armatures.new(f"{name}Data"))
    bpy.context.scene.collection.objects.link(armature)
    activate(armature)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.data.edit_bones
    parent = None
    for index, bone_name in enumerate(chain):
        parent = make_bone(edit_bones, bone_name, float(index), float(index + 1),
                           parent, connect=connect)
    root = edit_bones.get(chain[0])
    for offset, bone_name in enumerate(extra_bones, start=1):
        bone_z = float(len(chain) - 1 + offset)
        make_bone(edit_bones, bone_name, bone_z, bone_z + 1.0, root)
    bpy.ops.object.mode_set(mode="OBJECT")
    return armature


def make_weighted_mesh(name, armature, weights):
    """weights：顶点下标 → {顶点组名: 权重}。"""
    vertex_count = max(weights) + 1
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata([(0.0, float(i), 0.0) for i in range(vertex_count)], [], [])
    mesh = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(mesh)
    modifier = mesh.modifiers.new("Armature", "ARMATURE")
    modifier.object = armature
    for index, group_weights in weights.items():
        for group_name, weight in group_weights.items():
            group = mesh.vertex_groups.get(group_name) or mesh.vertex_groups.new(name=group_name)
            group.add([index], weight, "REPLACE")
    return mesh


def weight_of(mesh, group_name, index):
    group = mesh.vertex_groups.get(group_name)
    if group is None:
        return None
    try:
        return group.weight(index)
    except RuntimeError:
        return None


def assert_weight(mesh, group_name, index, expected):
    actual = weight_of(mesh, group_name, index)
    assert actual is not None, f"{group_name}[{index}] 不存在"
    assert abs(actual - expected) < 1e-6, f"{group_name}[{index}] = {actual}, 期望 {expected}"


def dissolve(execution="EXEC_DEFAULT", **kwargs):
    """调用操作符：self.report({'ERROR'}) 在 Python 侧会转成 RuntimeError，等价于取消。"""
    try:
        return bpy.ops.ho.simple_dissolve_bone(execution, **kwargs)
    except RuntimeError as error:
        print(f"[预期取消] {error}")
        return {"CANCELLED"}


bpy.utils.register_class(boneDissolve.OP_SimpleDissolveBone)

try:
    # ══════════════════════════════════════════════════════════════════════
    # 2. 自动递归：一次融并多根骨骼
    # ══════════════════════════════════════════════════════════════════════
    rig = make_rig("SimpleDissolveRig", ["root", "A", "B", "C", "D"])
    mesh = make_weighted_mesh(
        "SimpleDissolveMesh",
        rig,
        {
            0: {"A": 0.3, "B": 0.5, "C": 0.4},
            1: {"B": 0.2},
            2: {"C": 1.0},
            3: {"A": 0.25, "keep": 0.75},
        },
    )
    activate(rig)
    bpy.ops.object.mode_set(mode="POSE")
    for bone_name in ("B", "C", "D"):
        constraint = rig.pose.bones[bone_name].constraints.new("COPY_LOCATION")
        constraint.target = rig
        constraint.subtarget = "B"
    # 被删骨骼自身的约束：随骨骼一起消失，不应报错
    deleted_constraint = rig.pose.bones["C"].constraints.new("COPY_ROTATION")
    deleted_constraint.target = rig
    deleted_constraint.subtarget = "B"

    bone_utils.select_bones(rig, ["B", "C"])

    # 计划阶段可以先单独验证一遍：读取真实骨架、不修改数据
    record_plan = boneDissolve.SimpleDissolveCore.build_plan(rig, ["B", "C"], mode=MODE_AUTO)
    assert record_plan["weight_groups"] == {"A": ("C", "B")}, record_plan
    assert boneDissolve.SimpleDissolveCore.plan_report_lines(record_plan)
    assert rig.data.bones.get("B") is not None  # 计划阶段不动数据

    assert dissolve("EXEC_DEFAULT", resolve_mode=MODE_AUTO) == {"FINISHED"}

    # 权重：B、C 并入 A，超 1.0 的部分被 clamp
    assert mesh.vertex_groups.get("B") is None
    assert mesh.vertex_groups.get("C") is None
    assert_weight(mesh, "A", 0, 1.0)
    assert_weight(mesh, "A", 1, 0.2)
    assert_weight(mesh, "A", 2, 1.0)
    assert_weight(mesh, "A", 3, 0.25)
    assert_weight(mesh, "keep", 3, 0.75)

    # 骨骼：B、C 被删，D 挂到链上最近存活祖先 A 并断开连接
    assert rig.data.bones.get("B") is None
    assert rig.data.bones.get("C") is None
    assert rig.data.bones.get("A") is not None
    assert rig.data.bones["D"].parent.name == "A"
    assert not rig.data.bones["D"].use_connect

    # 约束：D 的 subtarget B → A
    assert rig.pose.bones["D"].constraints[0].subtarget == "A"

    # ══════════════════════════════════════════════════════════════════════
    # 3. 指定目标 + 镜像
    # ══════════════════════════════════════════════════════════════════════
    mirror_rig = make_rig(
        "SimpleDissolveMirrorRig",
        ["root2"],
        extra_bones=("upperarm.L", "upperarm.R"),
    )
    activate(mirror_rig)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = mirror_rig.data.edit_bones
    for side in ("L", "R"):
        make_bone(edit_bones, f"twist.{side}", 10.0, 11.0, edit_bones[f"upperarm.{side}"])
    for side in ("L", "R"):
        make_bone(edit_bones, f"hand.{side}", 11.0, 12.0, edit_bones[f"twist.{side}"])
    bpy.ops.object.mode_set(mode="OBJECT")

    mirror_mesh = make_weighted_mesh(
        "SimpleDissolveMirrorMesh",
        mirror_rig,
        {
            0: {"twist.L": 0.6, "upperarm.L": 0.5},
            1: {"twist.R": 0.25, "upperarm.R": 0.25},
            2: {"twist.L": 0.4},
        },
    )
    activate(mirror_rig)
    bpy.ops.object.mode_set(mode="POSE")
    for side in ("L", "R"):
        constraint = mirror_rig.pose.bones[f"hand.{side}"].constraints.new("COPY_LOCATION")
        constraint.target = mirror_rig
        constraint.subtarget = f"twist.{side}"

    bone_utils.select_bones(mirror_rig, ["twist.L"])
    assert dissolve(
        "EXEC_DEFAULT",
        resolve_mode=MODE_SPECIFY,
        target_bone="upperarm.L",
        mirror=True,
    ) == {"FINISHED"}

    assert mirror_mesh.vertex_groups.get("twist.L") is None
    assert mirror_mesh.vertex_groups.get("twist.R") is None
    assert_weight(mirror_mesh, "upperarm.L", 0, 1.0)
    assert_weight(mirror_mesh, "upperarm.L", 2, 0.4)
    assert_weight(mirror_mesh, "upperarm.R", 1, 0.5)

    assert mirror_rig.data.bones.get("twist.L") is None
    assert mirror_rig.data.bones.get("twist.R") is None
    assert mirror_rig.data.bones["hand.L"].parent.name == "upperarm.L"
    assert mirror_rig.data.bones["hand.R"].parent.name == "upperarm.R"
    assert mirror_rig.pose.bones["hand.L"].constraints[0].subtarget == "upperarm.L"
    assert mirror_rig.pose.bones["hand.R"].constraints[0].subtarget == "upperarm.R"

    # ══════════════════════════════════════════════════════════════════════
    # 4. 计划不合法：取消且不改动任何数据
    # ══════════════════════════════════════════════════════════════════════
    orphan_rig = make_rig("SimpleDissolveOrphanRig", ["only_root", "mid", "leaf"])
    orphan_mesh = make_weighted_mesh("SimpleDissolveOrphanMesh", orphan_rig, {0: {"mid": 1.0}})
    activate(orphan_rig)
    bpy.ops.object.mode_set(mode="POSE")
    bone_utils.select_bones(orphan_rig, ["only_root", "mid", "leaf"])
    assert dissolve("EXEC_DEFAULT", resolve_mode=MODE_AUTO) == {"CANCELLED"}
    for bone_name in ("only_root", "mid", "leaf"):
        assert orphan_rig.data.bones.get(bone_name) is not None
    assert orphan_mesh.vertex_groups.get("mid") is not None
    assert_weight(orphan_mesh, "mid", 0, 1.0)

    # 目标骨骼也在融并范围内：同样取消
    bone_utils.select_bones(orphan_rig, ["mid", "leaf"])
    assert dissolve(
        "EXEC_DEFAULT",
        resolve_mode=MODE_SPECIFY,
        target_bone="leaf",
    ) == {"CANCELLED"}
    assert orphan_rig.data.bones.get("leaf") is not None

    # 空目标：取消
    assert dissolve(
        "EXEC_DEFAULT",
        resolve_mode=MODE_SPECIFY,
        target_bone="",
    ) == {"CANCELLED"}
    assert orphan_rig.data.bones.get("mid") is not None

    # poll：未选骨骼时不可触发（旧实现允许 0 选中，会在 invoke 里越界）
    bone_utils.select_bones(orphan_rig, [])
    assert not boneDissolve.OP_SimpleDissolveBone.poll(bpy.context)
    bone_utils.select_bones(orphan_rig, ["mid"])
    assert boneDissolve.OP_SimpleDissolveBone.poll(bpy.context)
    bone_utils.select_bones(orphan_rig, ["mid", "leaf"])
    assert boneDissolve.OP_SimpleDissolveBone.poll(bpy.context)

    # ══════════════════════════════════════════════════════════════════════
    # 5. 老用法回归：单选 + 指定目标（父级）仍与旧版行为一致
    # ══════════════════════════════════════════════════════════════════════
    bone_utils.select_bones(orphan_rig, ["mid"])
    assert dissolve(
        "EXEC_DEFAULT",
        resolve_mode=MODE_SPECIFY,
        target_bone="only_root",
    ) == {"FINISHED"}

    assert orphan_rig.data.bones.get("mid") is None
    assert orphan_rig.data.bones["leaf"].parent.name == "only_root"
    assert orphan_mesh.vertex_groups.get("mid") is None
    assert_weight(orphan_mesh, "only_root", 0, 1.0)

    # ══════════════════════════════════════════════════════════════════════
    # 6. 编辑模式 + 相连骨：共享关节不能把父级带进融并计划
    # ══════════════════════════════════════════════════════════════════════
    joint_rig = make_rig(
        "SimpleDissolveJointRig",
        ["joint_root", "joint_mid", "joint_leaf"],
        connect=True,
    )
    joint_mesh = make_weighted_mesh("SimpleDissolveJointMesh", joint_rig, {0: {"joint_mid": 0.8}})
    activate(joint_rig)
    bpy.ops.object.mode_set(mode="EDIT")
    joint_edit_bones = joint_rig.data.edit_bones
    assert joint_edit_bones["joint_mid"].use_connect

    bone_utils.select_bones(joint_rig, ["joint_mid"])
    # Blender 选中相连子骨骼时会同时点亮父级尾端（共享关节）
    joint_edit_bones["joint_root"].select_tail = True
    assert bone_utils.selected_bone_names(bpy.context, joint_rig) == ["joint_mid"]

    assert dissolve("EXEC_DEFAULT", resolve_mode=MODE_AUTO) == {"FINISHED"}
    bpy.ops.object.mode_set(mode="OBJECT")

    assert joint_rig.data.bones.get("joint_root") is not None  # 父级没有被误融并
    assert joint_rig.data.bones.get("joint_mid") is None
    assert joint_rig.data.bones["joint_leaf"].parent.name == "joint_root"
    assert joint_mesh.vertex_groups.get("joint_mid") is None
    assert_weight(joint_mesh, "joint_root", 0, 0.8)
finally:
    bpy.utils.unregister_class(boneDissolve.OP_SimpleDissolveBone)

print("SIMPLE_DISSOLVE_MULTI_BONE_OK", bpy.app.version_string)
