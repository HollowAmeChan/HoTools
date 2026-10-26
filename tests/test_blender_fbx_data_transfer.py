"""HoFBX 导出：数据传递修改器必须在预处理最前面应用（回归测试，需要 Blender 后台运行）。

背景（用户实测）：数据传递修改器要“很靠前地”应用才修得好——FBX 导出阶段的求值环境
不完整，晚一步（删除几何节点修改器、形态键烘焙穿过修改器、应用骨架姿态）结果就会
和界面里看到的不一致，表现是**传递的法线在 FBX 里退回网格自身法线**。
之前修好过一版，后来形态键烘焙插到它前面又反弹了，所以这里锁死三件事：

  1. 调用顺序：apply_data_transfer_modifiers 的调用点必须在
     bake_shape_keys_through_modifiers 之前（源码级检查，防止再被挪到后面）；
  2. 行为：带形态键的网格也要能被这个前置步骤烘掉 DATA_TRANSFER——
     只烘 DATA_TRANSFER（其它修改器与骨架原样保留）、形态键形态不丢、
     烘完的法线与视口求值一致，并且随后再走形态键烘焙也不会变；
  3. 前置修改器必须一起烘：数据传递评估的是“它所在位置的网格”（前置镜像/缩裹已经
     生效）。只应用 DATA_TRANSFER 会让它作用在**基础网格**上，源/目标面拐数对不上时
     Blender 直接报“源网格与目标网格面拐数量不一致，此类情形无法使用 '拓扑' 映射”
     并**丢弃自定义法线**（实测 Body），对得上时也会按错误的源求值结果传递（实测
     睫毛下/鼻尖，与视口差 0.14~0.6 rad）。真实资产里数据传递前面几乎总有镜像，
     所以这条是“全选导出后传递的法线又不见了”的真正原因。
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

# ── 5. 关闭“删除隐藏修改器”时，底层仍支持只在渲染中显示的数据传递 ────────────
# 主流程默认先排除隐藏修改器（见 test_blender_fbx_hidden_modifiers.py）；
# 此处直接调用底层，覆盖 removeHiddenModifiers=False 时保留的渲染口径。
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

# ── 7. 前置修改器必须与 DATA_TRANSFER 一起烘（真实资产的现场） ────────────────
# 目标：数据传递前面有镜像修改器，源网格也有镜像修改器（Body 那套的真实结构）。
# 数据传递只在“镜像已生效”的网格上成立（源/目标面拐数才一致），所以必须整条链一起应用。
def build_chained_fixture(tag, mapping):
    source = make_quad(f"ChainSource_{tag}")
    # 源的自定义法线与自身面法线明显不同，且逐拐不同：镜像后传过去的结果与
    # “只烘数据传递”的结果必须能区分开。
    source.data.normals_split_custom_set(
        [TRANSFERRED_NORMAL, TRANSFERRED_NORMAL, (0.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
    )
    source.data.update()
    source.modifiers.new("SourceMirror", "MIRROR")

    target = make_quad(f"ChainTarget_{tag}")
    target.modifiers.new("TargetMirror", "MIRROR")
    transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
    transfer.object = source
    transfer.use_loop_data = True
    transfer.data_types_loops = {"CUSTOM_NORMAL"}
    transfer.loop_mapping = mapping
    transfer.mix_mode = "REPLACE"
    transfer.mix_factor = 1.0
    # 诱饵修改器用“不变形”的 SimpleDeform（BEND + 0 角度），这样它留在栈上
    # 不会改变求值结果，末尾的严格断言不用放宽。
    decoy = target.modifiers.new("Decoy", "SIMPLE_DEFORM")
    decoy.deform_method = "BEND"
    decoy.deform_axis = "X"
    decoy.angle = 0.0
    activate(target)
    return source, target, decoy


for mapping in ("TOPOLOGY", "POLYINTERP_LNORPROJ"):
    tag = f"chain_{mapping}"
    _src, target, _decoy = build_chained_fixture(tag, mapping)
    expected_chain = evaluated_normals(target)
    assert len(expected_chain) == 8, f"测试场景无效：镜像后应有 8 个面拐，实际 {len(expected_chain)}"
    assert mean_angle(expected_chain, [(0.0, 0.0, 1.0)] * 8) > 0.2, (
        f"{mapping}：测试场景无效，传递在视口里看不出效果"
    )

    # (a) 只应用 DATA_TRANSFER（旧实现的口径）：只有前 4 个面拐有传递结果，后 4 个丢失
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    result = bpy.ops.object.modifier_apply(modifier="DataTransfer", merge_customdata=True)
    assert "FINISHED" in result
    broken = corner_normals(target.data)
    assert len(broken) == 4, "测试场景无效：基础网格应是 4 个面拐"
    # 链口径的期望结果是 8 个（镜像后）。旧口径只留 4 个，镜像一复制就对不上视口。
    assert len(broken) != len(expected_chain), "测试场景无效：两种口径应产生不同的面拐数"

    # (b) 整条链一起应用（新实现）：结果必须与视口口径完全一致
    _src2, target2, _decoy2 = build_chained_fixture(f"{tag}_fix", mapping)
    expected2 = evaluated_normals(target2)
    chain = fbx_module.FBXExporter.data_transfer_chain(target2)
    assert [mod.type for mod in chain] == ["MIRROR", "DATA_TRANSFER"], (
        f"{mapping}：数据传递链应当是“镜像 + 数据传递”，实际 "
        f"{[mod.type for mod in chain]}"
    )
    # 诱饵在数据传递之后，不该进链
    applied7, failed7, _s7, _a7 = fbx_module.FBXExporter.apply_data_transfer_modifiers(
        [target2], [target2], target2
    )
    assert applied7 == 1 and not failed7, (applied7, failed7)
    assert [modifier.name for modifier in target2.modifiers] == ["Decoy"], (
        "数据传递链要一起烘掉，数据传递之后的修改器（诱饵）必须保留："
        f"{[m.name for m in target2.modifiers]}"
    )
    got2 = corner_normals(target2.data)
    assert len(got2) == len(expected2), (
        f"{mapping}：烘完的面拐数（{len(got2)}）与视口口径（{len(expected2)}）不一致"
    )
    angle2 = mean_angle(got2, expected2)
    assert angle2 is not None and angle2 < 1e-4, (
        f"{mapping}：前置修改器没有和数据传递一起烘，结果与视口差 {angle2} rad —— "
        "传递的法线又是错的"
    )
    assert transferred_deviation(target2.data) > 0.2, f"{mapping}：传递的法线没有真的传过来"

# ── 8. 数据传递的源本身也是数据传递物体：处理顺序不能影响结果 ────────────────
# 真实文件里的链条：Body 有数据传递（源是另一个网格），睫毛下 / 鼻尖 / NurbsPath 的
# 数据传递源又都是 Body。如果边应用边求值，处理 Body 时会把它自己的数据传递烘进网格，
# 后面这些物体就传递到“已经被改过的 Body”，结果随处理顺序变化（实测差 0.24 rad，
# 多次导出数值还各不相同）。必须先记录、再应用、后写回。
#
# 源：一半面拐是 (1,0,0)，一半是 (0,1,0)，逐拐不同 —— 源被改掉时下游必然看得出来。
source_a = make_quad("OrderSourceA")
source_a.data.normals_split_custom_set([(1.0, 0.0, 0.0)] * 2 + [(0.0, 1.0, 0.0)] * 2)
source_a.data.update()
source_b = make_quad("OrderSourceB")  # Body 扮演的角色
source_b.data.normals_split_custom_set([(1.0, 0.0, 0.0)] * 2 + [(0.0, 1.0, 0.0)] * 2)
source_b.data.update()
transfer_b = source_b.modifiers.new("SourceBTransfer", "DATA_TRANSFER")
transfer_b.object = source_a
transfer_b.use_loop_data = True
transfer_b.data_types_loops = {"CUSTOM_NORMAL"}
transfer_b.loop_mapping = "TOPOLOGY"
transfer_b.mix_mode = "REPLACE"
transfer_b.mix_factor = 1.0

target_c = make_quad("OrderTargetC")
transfer_c = target_c.modifiers.new("TargetCTransfer", "DATA_TRANSFER")
transfer_c.object = source_b
transfer_c.use_loop_data = True
transfer_c.data_types_loops = {"CUSTOM_NORMAL"}
transfer_c.loop_mapping = "TOPOLOGY"
transfer_c.mix_mode = "REPLACE"
transfer_c.mix_factor = 1.0

target_d = make_quad("OrderTargetD")
transfer_d = target_d.modifiers.new("TargetDTransfer", "DATA_TRANSFER")
transfer_d.object = source_b
transfer_d.use_loop_data = True
transfer_d.data_types_loops = {"CUSTOM_NORMAL"}
transfer_d.loop_mapping = "TOPOLOGY"
transfer_d.mix_mode = "REPLACE"
transfer_d.mix_factor = 1.0

activate(target_c)
expected_c = evaluated_normals(target_c)
activate(target_d)
expected_d = evaluated_normals(target_d)
assert mean_angle(expected_c, [(0.0, 0.0, 1.0)] * 4) > 0.2, "测试场景无效：C 看不到传递"
assert mean_angle(expected_d, [(0.0, 0.0, 1.0)] * 4) > 0.2, "测试场景无效：D 看不到传递"

# 记录顺序必须把“源”排在“下游”前面
order = fbx_module.FBXExporter._upstream_first(
    [target_c.name, target_d.name, source_b.name, source_a.name]
)
assert order.index(source_a.name) < order.index(source_b.name), (
    f"源 A 必须排在依赖它的 B 之前，实际顺序 {order}"
)
assert order.index(source_b.name) < order.index(target_c.name), (
    f"源 B 必须排在依赖它的 C 之前，实际顺序 {order}"
)
assert order.index(source_b.name) < order.index(target_d.name), (
    f"源 B 必须排在依赖它的 D 之前，实际顺序 {order}"
)
# 有环时不能死循环
assert set(fbx_module.FBXExporter._upstream_first(
    [source_b.name, source_b.name, "不存在的物体"]
)) == {source_b.name}

# 故意把“源”排在前、两个下游排在后：这是导出时的真实顺序。
applied8, failed8, _s8, _a8 = fbx_module.FBXExporter.apply_data_transfer_modifiers(
    [source_b, target_c, target_d], [source_b, target_c, target_d], source_b
)
assert applied8 == 3 and not failed8, (applied8, failed8)
angle_c = mean_angle(corner_normals(target_c.data), expected_c)
angle_d = mean_angle(corner_normals(target_d.data), expected_d)
assert angle_c is not None and angle_c < 1e-4, (
    f"下游物体 C 的记录/写回没生效，与视口差 {angle_c} rad —— "
    "数据传递的结果取决于处理顺序（源被先处理改掉了）"
)
assert angle_d is not None and angle_d < 1e-4, (
    f"下游物体 D 的记录/写回没生效，与视口差 {angle_d} rad"
)

# ── 9. 数据传递之后还有改拓扑的修改器：面拐数只能按“数据传递那一层”记录 ──────
# 真实文件里的 NurbsPath.064：缩裹 → 数据传递 → 镜像。整栈求值是 328 个面拐，
# 而数据传递那一层只有 164 个；如果按整栈记录，写回时面拐数对不上就整条退回错误结果。
def build_downstream_mirror_fixture():
    src = make_quad("DownSource")
    # 逐拐不同，方便用“第一个面拐是不是倾斜法线”做精确校验
    src.data.normals_split_custom_set([
        Vector((0.0, 0.0, 1.0)),
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.7071068, 0.0, 0.7071068)),
    ])
    src.data.update()

    tgt = make_quad("DownTarget")
    transfer = tgt.modifiers.new("DownTransfer", "DATA_TRANSFER")
    transfer.object = src
    transfer.use_loop_data = True
    transfer.data_types_loops = {"CUSTOM_NORMAL"}
    transfer.loop_mapping = "TOPOLOGY"
    transfer.mix_mode = "REPLACE"
    transfer.mix_factor = 1.0
    # 数据传递**之后**还有一个改拓扑的修改器：整栈求值是 8 个面拐，
    # 而数据传递那一层只有 4 个 —— 记录的必须是后者。
    tgt.modifiers.new("DownMirror", "MIRROR")
    activate(tgt)
    return src, tgt


_src9, target9 = build_downstream_mirror_fixture()
expected9 = evaluated_normals(target9)
assert len(expected9) == 8, f"测试场景无效：镜像后应有 8 个面拐，实际 {len(expected9)}"
# 源上那 4 个逐拐法线（TOPOLOGY + REPLACE 应当原样搬过来）
expected_corners = [
    Vector((0.0, 0.0, 1.0)),
    Vector((1.0, 0.0, 0.0)),
    Vector((0.0, 1.0, 0.0)),
    Vector((0.7071068, 0.0, 0.7071068)),
]
stage9 = fbx_module.FBXExporter.transfer_stage_mesh(target9)
assert stage9 is not None, "取“数据传递那一刻”的网格失败"
stage_mesh9 = stage9[0]
assert len(stage_mesh9.loops) == 4, (
    f"取到的应当是“数据传递那一层”的 4 个面拐，实际 {len(stage_mesh9.loops)} —— "
    "按整栈（8）取会让接管后的网格与后面的镜像重复计算"
)
stage_corners = [normal.vector.copy() for normal in stage_mesh9.corner_normals]
assert mean_angle(stage_corners, expected_corners) < 1e-3, (
    "取到的不是源上那 4 个逐拐法线（TOPOLOGY + REPLACE 应当原样搬过来）"
)
applied9, failed9, _s9, _a9 = fbx_module.FBXExporter.apply_data_transfer_modifiers(
    [target9], [target9], target9
)
assert applied9 == 1 and not failed9, (applied9, failed9)
assert [mod.name for mod in target9.modifiers] == ["DownMirror"], (
    "数据传递之后的镜像必须保留："
    f"{[m.name for m in target9.modifiers]}"
)
after9 = [normal.vector.copy() for normal in target9.data.corner_normals]
assert len(after9) == 4, f"接管后基础网格应回到数据传递那一层的 4 个面拐，实际 {len(after9)}"
written_angle = mean_angle(after9, expected_corners)
assert written_angle is not None and written_angle < 1e-3, (
    f"数据传递那一层的结果没有落回基础网格（与源差 {written_angle} rad），传递的法线丢了"
)
# 再走一遍整栈求值（此时栈上只剩数据传递之后的镜像）：结果必须与最初的视口一致
final9 = evaluated_normals(target9)
assert len(final9) == len(expected9), (
    f"接管后整栈求值应有 {len(expected9)} 个面拐，实际 {len(final9)}"
)
chain_angle = mean_angle(final9, expected9)
assert chain_angle is not None and chain_angle < 1e-4, (
    f"数据传递之后还有修改器时，结果与视口差 {chain_angle} rad"
)

print("FBX_DATA_TRANSFER_ORDER_OK", bpy.app.version_string)
