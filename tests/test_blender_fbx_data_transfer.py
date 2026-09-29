"""HoFBX 导出：数据传递修改器必须在预处理最前面应用（回归测试，需要 Blender 后台运行）。

背景（用户实测）：数据传递修改器要“很靠前地”应用才修得好——FBX 导出阶段的求值环境
不完整，晚一步（删除隐藏/几何节点修改器、形态键烘焙穿过修改器、应用骨架姿态）结果就会
和界面里看到的不一致，表现是**传递的法线在 FBX 里退回网格自身法线**。
之前修好过一版，后来形态键烘焙插到它前面又反弹了，所以这里锁死两件事：

  1. 调用顺序：apply_data_transfer_modifiers 的调用点必须在
     bake_shape_keys_through_modifiers 之前（源码级检查，防止再被挪到后面）；
  2. 行为：带形态键的网格也要能被这个前置步骤烘掉 DATA_TRANSFER——
     只烘 DATA_TRANSFER（其它修改器与骨架原样保留）、形态键形态不丢、
     烘完的法线与视口求值一致，并且随后再走形态键烘焙也不会变。
"""

import sys
from pathlib import Path

import bpy
from mathutils import Vector


ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from HoTools.Exporter import FbxExporter as fbx_module  # noqa: E402

EXPORTER_SOURCE = (ADDON_ROOT / "Exporter" / "FbxExporter.py").read_text(encoding="utf-8")

TRANSFERRED_NORMAL = (0.7071068, 0.0, 0.7071068)  # 与目标自身面法线 (0,0,1) 明显不同


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def make_quad(name):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    return link(bpy.data.objects.new(name, mesh))


def corner_normals(mesh):
    return [tuple(normal.vector) for normal in mesh.corner_normals]


def evaluated_normals(obj):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        return corner_normals(mesh)
    finally:
        bpy.data.meshes.remove(mesh)


def mean_angle(normals_a, normals_b):
    if len(normals_a) != len(normals_b) or not normals_a:
        return None
    total, count = 0.0, 0
    for normal_a, normal_b in zip(normals_a, normals_b):
        vector_a, vector_b = Vector(normal_a), Vector(normal_b)
        if vector_a.length < 1e-9 or vector_b.length < 1e-9:
            continue
        total += vector_a.angle(vector_b)
        count += 1
    return total / count if count else None


def auto_normals(mesh):
    """同一网格去掉 custom_normal 属性后的“自身法线”，用来判断传递还在不在。"""
    copy = mesh.copy()
    try:
        attribute = copy.attributes.get("custom_normal")
        if attribute is not None:
            copy.attributes.remove(attribute)
        return corner_normals(copy)
    finally:
        bpy.data.meshes.remove(copy)


def transferred_deviation(mesh):
    """当前法线相对“网格自身法线”的平均夹角：传递还在就应该是大角度（这里约 45°）。"""
    return mean_angle(corner_normals(mesh), auto_normals(mesh))


def build_fixture(tag, *, with_shape_keys):
    """源网格带倾斜自定义法线；目标网格用 DATA_TRANSFER 传递它。"""
    source = make_quad(f"Source_{tag}")
    source.data.normals_split_custom_set(
        [TRANSFERRED_NORMAL] * len(source.data.loops)
    )
    source.data.update()

    target = make_quad(f"Target_{tag}")
    if with_shape_keys:
        target.shape_key_add(name="Basis", from_mix=False)
        wide = target.shape_key_add(name="Wide", from_mix=False)
        wide.data[1].co.x = 2.0
    transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
    transfer.object = source
    transfer.use_loop_data = True
    transfer.data_types_loops = {"CUSTOM_NORMAL"}
    transfer.loop_mapping = "TOPOLOGY"
    transfer.mix_mode = "REPLACE"
    transfer.mix_factor = 1.0
    # 诱饵修改器：这个前置步骤只该动 DATA_TRANSFER，它必须原样保留
    decoy = target.modifiers.new("Decoy", "SIMPLE_DEFORM")
    decoy.deform_method = "TWIST"
    activate(target)
    return source, target, decoy


# ── 1. 源码级：调用顺序必须是“数据传递”在“形态键烘焙”之前 ────────────────────
transfer_call = EXPORTER_SOURCE.index("FBXExporter.apply_data_transfer_modifiers(\n                selection,")
bake_call = EXPORTER_SOURCE.index("FBXExporter.bake_shape_keys_through_modifiers(\n                selection,")
assert transfer_call < bake_call, (
    "apply_data_transfer_modifiers 的调用点排在了形态键烘焙之后："
    "数据传递会被形态键烘焙先吃掉，传递的法线又会退回网格自身法线"
)

# ── 2. 带形态键的网格：前置步骤要能把 DATA_TRANSFER 烘掉 ─────────────────────
_source, target, decoy = build_fixture("keys", with_shape_keys=True)
expected = evaluated_normals(target)
assert mean_angle(expected, [(0.0, 0.0, 1.0)] * 4) > 0.1, "测试场景无效：传递的法线没有区别于自身法线"

applied, failed, _selection, _active = fbx_module.FBXExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1, f"带形态键的网格没有烘掉数据传递修改器：applied={applied} failed={failed}"
assert not failed, failed
assert [modifier.name for modifier in target.modifiers] == ["Decoy"], (
    "只该烘 DATA_TRANSFER，诱饵修改器必须保留："
    f"{[modifier.name for modifier in target.modifiers]}"
)
shape_keys = target.data.shape_keys
assert shape_keys is not None, "形态键丢了"
assert [key.name for key in shape_keys.key_blocks] == ["Basis", "Wide"], "形态键名称变了"
assert abs(shape_keys.key_blocks["Wide"].data[1].co.x - 2.0) < 1e-6, "形态键形态被改坏"
assert transferred_deviation(target.data) > 0.3, "传递的法线没有真的传过来"
# ── 3. 后续处理不能把传递效果冲掉（这正是之前反弹的地方） ────────────────────
# 这一步把诱饵修改器也烘掉（模拟导出的后续步骤），烘完应当与界面里看到的完全一致：
# 传递的法线在被后续修改器形变之后依然保留，而不是退回网格自身法线。
baked, skipped, bake_failed = fbx_module.FBXExporter.bake_shape_keys_through_modifiers([target])
assert not bake_failed, bake_failed
assert baked, "诱饵修改器应当被这一步骤烘掉，测试场景无效"
assert [modifier.name for modifier in target.modifiers] == [], (
    f"诱饵修改器没被烘掉：{[m.name for m in target.modifiers]}"
)
after = corner_normals(target.data)
assert mean_angle(after, expected) < 1e-4, (
    f"走完整链路后与界面里看到的法线不一致（{mean_angle(after, expected)}）——"
    "传递的法线在后续步骤里被冲掉了"
)

# ── 4. 不带形态键的网格：仍然走原生 modifier_apply，只动 DATA_TRANSFER ───────
_source2, target2, _decoy2 = build_fixture("plain", with_shape_keys=False)
expected2 = evaluated_normals(target2)
applied2, failed2, _s2, _a2 = fbx_module.FBXExporter.apply_data_transfer_modifiers(
    [target2], [target2], target2
)
assert applied2 == 1 and not failed2, (applied2, failed2)
assert [modifier.name for modifier in target2.modifiers] == ["Decoy"]
assert transferred_deviation(target2.data) > 0.3, "原生路径没有把传递的法线留下"
# 再把诱饵也应用掉，结果应当与界面里看到的一致
bpy.context.view_layer.objects.active = target2
with bpy.context.temp_override(object=target2, modifier=target2.modifiers["Decoy"]):
    bpy.ops.object.modifier_apply(modifier="Decoy")
assert mean_angle(corner_normals(target2.data), expected2) < 1e-4

# ── 5. 只在渲染中显示的数据传递也要在“删隐藏修改器”之前被应用 ────────────────
# 导出默认会删掉视口隐藏的修改器（removeHiddenModifiers）。数据传递若是视口关、
# 渲染开，晚于这一步就什么都不剩了：这正是“传递的法线在导出后消失”的现场。
# 放到最前面之后，它仍在栈上，按 (show_viewport or show_render) 口径被正常应用。
_source3, target3, decoy3 = build_fixture("render_only", with_shape_keys=True)
render_only_transfer = target3.modifiers["DataTransfer"]
render_only_transfer.show_viewport = False
render_only_transfer.show_render = True
# 期望值按“渲染口径”：导出用的是 use_mesh_modifiers_render，即这个修改器应当生效。
# 视口求值看不到它，所以临时打开视口开关取一次参照再关回去。
render_only_transfer.show_viewport = True
expected3 = evaluated_normals(target3)
render_only_transfer.show_viewport = False
applied3, failed3, _s3, _a3 = fbx_module.FBXExporter.apply_data_transfer_modifiers(
    [target3], [target3], target3
)
assert applied3 == 1 and not failed3, (applied3, failed3)
assert [modifier.name for modifier in target3.modifiers] == ["Decoy"]
assert transferred_deviation(target3.data) > 0.3, "渲染可见的数据传递没被应用"
baked3, _skipped3, failed3b = fbx_module.FBXExporter.bake_shape_keys_through_modifiers([target3])
assert not failed3b and baked3
assert mean_angle(corner_normals(target3.data), expected3) < 1e-4, (
    "渲染可见的数据传递走完整链路后与渲染口径的结果不一致"
)

# ── 6. 失效物体引用不能再打断导出（应用骨架姿态会删原物体、用副本顶替） ───────
dead = link(bpy.data.objects.new("Dead", bpy.data.meshes.new("DeadMesh")))
dead_reference = dead
bpy.data.objects.remove(dead, do_unlink=True)
assert not fbx_module.FBXExporter.object_is_alive(dead_reference)
fbx_module.FBXExporter.clear_exported_constraints([dead_reference])  # 不应抛 ReferenceError
fbx_module.FBXExporter.restore_selection([dead_reference], dead_reference)
fbx_module.FBXExporter.restore_selection_by_names(["不存在的物体"], "也不存在")

print("FBX_DATA_TRANSFER_ORDER_OK", bpy.app.version_string)
