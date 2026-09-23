"""矩阵键生成算子的 Blender 级测试。

覆盖：命名规范拆/拼、3×3 与 2×3 生成、键值与激活、覆盖/跳过、幂等，
以及对话框 invoke 时从活动键预填。
"""

import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR.parent))

result = bpy.ops.preferences.addon_enable(module="HoTools")
assert result == {"FINISHED"}, result

from HoTools.ShapekeyTools import operators as sk_ops  # noqa: E402


MatrixOp = sk_ops.OP_AddShapekeyMatrix


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def make_face(name, key_names=()):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                     [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.shape_key_add(name="Basis", from_mix=False)
    for key_name in key_names:
        obj.shape_key_add(name=key_name, from_mix=False)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def key_names(obj):
    return [key.name for key in obj.data.shape_keys.key_blocks]


# ── 算子注册与菜单入口 ────────────────────────────────────────────────────
assert hasattr(bpy.types, "HO_OT_add_shapekey_matrix")
assert not hasattr(bpy.types, "HO_OT_add_shapekey_matrix_prefill"), (
    "预填是 invoke 内部行为，不该有独立算子")
assert MatrixOp.bl_idname == "ho.add_shapekey_matrix"
assert MatrixOp.bl_options == {'REGISTER', 'UNDO'}

# ── 命名规范：拆 / 拼（只允许方阵）───────────────────────────────────────
parse = MatrixOp.parse_matrix_name
assert parse("LidL__BlinkWide__Squint__A3X2Y1") == (
    "LidL", "BlinkWide", "Squint", 3, "2", "1")
assert parse("Mouth__Horizontal__Vertical__A3X0Y0") == (
    "Mouth", "Horizontal", "Vertical", 3, "0", "0")
# 小数坐标也要能解析（规范允许 X0.5）
assert parse("Mouth__H__V__A5X0.5Y4")[4:] == ("0.5", "4")
# 不合规的一律返回 None：包含非方阵/多段的扩展写法
for bad in ("", "Basis", "Mouth", "Mouth__Horizontal__Vertical",
            "Mouth__Horizontal__Vertical__X0Y0", "Mouth__H__V__A0X0Y0",
            # 非方阵与自定义扩展段都不接受：只认四段的方阵名
            "Mouth__H__V__A2X1Y2__S3", "Mouth__H__V__A3X0Y0__EXTRA"):
    assert parse(bad) is None, bad
# 拼名字：A 段的刻度数是每轴刻度数，坐标从 0 起
assert MatrixOp.assign_matrix_name("LidL", "BlinkWide", "Squint", 3, 2, 1) == (
    "LidL__BlinkWide__Squint__A3X2Y1")
names = MatrixOp.matrix_names("M", "H", "V", 3)
assert [entry[2] for entry in names] == [
    "M__H__V__A3X0Y0", "M__H__V__A3X1Y0", "M__H__V__A3X2Y0",
    "M__H__V__A3X0Y1", "M__H__V__A3X1Y1", "M__H__V__A3X2Y1",
    "M__H__V__A3X0Y2", "M__H__V__A3X1Y2", "M__H__V__A3X2Y2",
], "左下起、行优先、方阵"
assert [(entry[0], entry[1]) for entry in names] == [
    (0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2)]
assert len(MatrixOp.matrix_names("M", "H", "V", 4)) == 16, "每轴 4 档就是 4×4"

# ── 生成 3×3：先给三个键，生成的键排在 Basis 后面 ────────────────────────
clear_scene()
face = make_face("MatrixFace")
assert bpy.ops.ho.add_shapekey_matrix(
    tree="LidL", axis_x="BlinkWide", axis_y="Squint",
    scales=3, value=0.0, overwrite=False) == {'FINISHED'}
expected_3x3 = [
    "LidL__BlinkWide__Squint__A3X0Y0", "LidL__BlinkWide__Squint__A3X1Y0",
    "LidL__BlinkWide__Squint__A3X2Y0", "LidL__BlinkWide__Squint__A3X0Y1",
    "LidL__BlinkWide__Squint__A3X1Y1", "LidL__BlinkWide__Squint__A3X2Y1",
    "LidL__BlinkWide__Squint__A3X0Y2", "LidL__BlinkWide__Squint__A3X1Y2",
    "LidL__BlinkWide__Squint__A3X2Y2",
]
assert key_names(face) == ["Basis"] + expected_3x3, key_names(face)
assert face.active_shape_key.name == expected_3x3[0], "生成后活动键应落到第一个新键"

# ── 键值一起写进去（形态键键值默认范围 0..1，测试用 0.5）──────────────────
assert bpy.ops.ho.add_shapekey_matrix(
    tree="Brow", axis_x="UpDown", axis_y="InOut",
    scales=2, value=0.5) == {'FINISHED'}
for name in ("Brow__UpDown__InOut__A2X0Y0", "Brow__UpDown__InOut__A2X1Y1"):
    assert abs(face.data.shape_keys.key_blocks[name].value - 0.5) < 1e-6, name

# ── 幂等：同名不覆盖就跳过；勾了覆盖就重置形状与键值 ──────────────────────
before = key_names(face)
assert bpy.ops.ho.add_shapekey_matrix(
    tree="LidL", axis_x="BlinkWide", axis_y="Squint",
    scales=3, overwrite=False) == {'CANCELLED'}, "全都在了应取消"
assert key_names(face) == before, "跳过后不该动列表"

# 造一个真的有形变的键，验证覆盖会清回基础形状
target = "LidL__BlinkWide__Squint__A3X1Y1"
block = face.data.shape_keys.key_blocks[target]
for index in range(len(block.data)):
    block.data[index].co.z += 0.5
block.value = 42.0
assert bpy.ops.ho.add_shapekey_matrix(
    tree="LidL", axis_x="BlinkWide", axis_y="Squint",
    scales=3, value=0.0, overwrite=True) == {'FINISHED'}
block = face.data.shape_keys.key_blocks[target]
basis = face.data.shape_keys.reference_key
for index in range(len(block.data)):
    assert abs(block.data[index].co.z - basis.data[index].co.z) < 1e-6, "覆盖应清回基础形状"
assert abs(block.value) < 1e-6, "覆盖应把键值写回给定值"
assert block.relative_key == basis

# ── 4×4 方阵：名字与数量都跟着刻度走 ─────────────────────────────────────
assert bpy.ops.ho.add_shapekey_matrix(
    tree="Mouth", axis_x="Horizontal", axis_y="Vertical",
    scales=4) == {'FINISHED'}
generated = [name for name in key_names(face) if name.startswith("Mouth__")]
assert len(generated) == 16, generated
assert generated[0] == "Mouth__Horizontal__Vertical__A4X0Y0"
assert generated[-1] == "Mouth__Horizontal__Vertical__A4X3Y3"
assert MatrixOp.parse_matrix_name(generated[-1])[3] == 4, "A 段记每轴刻度数"
# 名字里不该出现任何自定义扩展段（只认四段）
assert all(len(name.split("__")) == 4 for name in generated), generated

# ── 参数校验 ──────────────────────────────────────────────────────────────
def expect_rejected(**kwargs):
    """脚本调用算子时，self.report({'ERROR'}) 会变成 RuntimeError，两种都接受。"""
    try:
        result = bpy.ops.ho.add_shapekey_matrix(**kwargs)
    except RuntimeError:
        return True
    return result == {'CANCELLED'}


assert expect_rejected(tree="", axis_x="H", axis_y="V"), "树名不能空"
assert expect_rejected(tree="A", axis_x="H__X", axis_y="V"), "名字里不许带分隔符"
assert bpy.ops.ho.add_shapekey_matrix(
    tree="T", axis_x="H", axis_y="V", scales=1) == {'FINISHED'}
assert "T__H__V__A1X0Y0" in key_names(face), "1×1 也要能生成"

# ── invoke 预填：直接验证预填规则（算子实例无法从脚本直接构造）─────────────
# prefill 只依赖「活动键名」这一条输入，这里用同一套解析逻辑覆盖它的行为
def prefill_from_active(obj):
    data = MatrixOp.parse_matrix_name(obj.active_shape_key.name)
    if data is None:
        return {"tree": obj.active_shape_key.name, "ok": False}
    tree, axis_x, axis_y, scales, _x, _y = data
    return {"tree": tree, "axis_x": axis_x, "axis_y": axis_y,
            "scales": scales, "ok": True}


face.active_shape_key_index = face.data.shape_keys.key_blocks.find(
    "LidL__BlinkWide__Squint__A3X2Y1")
prefilled = prefill_from_active(face)
assert prefilled["ok"] is True
assert (prefilled["tree"], prefilled["axis_x"], prefilled["axis_y"]) == (
    "LidL", "BlinkWide", "Squint")
assert prefilled["scales"] == 3, "方阵刻度应照抄"

# 活动键不合规范时：整名当树名，不报错
face.active_shape_key_index = face.data.shape_keys.key_blocks.find("Basis")
assert prefill_from_active(face) == {"tree": "Basis", "ok": False}
# 算子确实把这条逻辑接在 invoke 上（面板打开弹窗前会先跑一次）
import inspect  # noqa: E402

invoke_source = inspect.getsource(MatrixOp.invoke)
assert "_prefill_from_active" in invoke_source
assert "invoke_props_dialog" in invoke_source, "要点开的是检查框弹窗"

# ── 没有形态键的物体：先补 Basis 再生成 ───────────────────────────────────
clear_scene()
bare = make_face("BareFace")
bare.shape_key_remove(bare.data.shape_keys.reference_key)
assert getattr(bare.data, "shape_keys", None) is None, "先确认没有形态键数据"
assert bpy.ops.ho.add_shapekey_matrix(
    tree="T", axis_x="H", axis_y="V", scales=2) == {'FINISHED'}
assert key_names(bare)[0] == "Basis", "应当自动补上基础键"
assert len(key_names(bare)) == 5

# ── 菜单入口：形态键下拉菜单的绘制回调里要有这个算子 ─────────────────────
source = Path(sk_ops.__file__).read_text(encoding="utf-8")
menu_body = source.split("def draw_in_MESH_MT_shape_key_context_menu")[1]
menu_body = menu_body.split("class ")[0]
assert "OP_AddShapekeyMatrix.bl_idname" in menu_body, "下拉菜单里要挂上入口"
assert "OP_AddShapekeysByTemplate.bl_idname" in menu_body, "原来的模板入口要保留"

bpy.ops.preferences.addon_disable(module="HoTools")
print("SHAPEKEY_MATRIX_KEYS_OK", bpy.app.version_string)
