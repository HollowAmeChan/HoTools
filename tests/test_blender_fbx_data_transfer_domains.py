"""HoFBX 数据传递：覆盖全部数据域 + 依赖链拓扑的行为测试（需要 Blender 后台运行）。

数据传递能传四个域的数据，任何一个域没做对都算“数据传递没做对”，所以这个测试不是
只看法线：

  顶点：顶点组权重、倒角权重、顶点色
  边：锐边、缝合、折痕、倒角权重、Freestyle
  面拐：自定义法线、角点色、UV
  面：平滑、Freestyle

同时锁死依赖链的几种真实拓扑：
  * 传递之前有改拓扑的修改器（镜像）
  * 传递在栈中间（后面还有镜像）
  * 多个目标共用同一个源，且源本身也有数据传递（顺序不能影响结果）
  * 只在渲染中显示 / 视口隐藏的传递

运行：blender -b --factory-startup --python tests/test_blender_fbx_data_transfer_domains.py
"""

import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fbx_dt_testkit import (  # noqa: E402
    diff_state,
    evaluated_state,
    mesh_state,
    normal_deviation,
    replace_vertex_groups,
    vertex_group_weights,
    vertex_groups_after_mirror,
    without_vertex_groups,
)

ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from HoTools.Exporter import FbxExporter as fbx_module  # noqa: E402

FbxExporter = fbx_module.FBXExporter

SOURCE_COLOR = (0.11, 0.22, 0.33, 1.0)
TARGET_COLOR = (0.9, 0.8, 0.7, 1.0)
SOURCE_WEIGHT = 0.75


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def activate(ob):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    return ob


def make_quad(name, *, offset=(0.0, 0.0, 0.0)):
    """默认放在 X 正半轴：镜像修改器会把它翻到负半轴，顶点数才会翻倍。

    注意不要跨在镜像平面上（例如以原点为中心），否则镜像的合并会把顶点焊掉，
    顶点数不翻倍，测试就失去意义。
    """
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    ox, oy, oz = offset
    mesh.from_pydata(
        [(ox, oy, oz), (ox + 0.5, oy, oz), (ox + 0.5, oy + 0.5, oz), (ox, oy + 0.5, oz)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    return link(bpy.data.objects.new(name, mesh))


def add_full_data(ob, *, tag, weight, color, uv_base, smooth, crease,
                  layer_names=("UV", "CCol", "VCol"), group_name="Weight"):
    """给网格加上四个域的“自定义”数据，让每个域都能看出来自哪一边。

    数据层（UV/色层/顶点组）在源与目标上**用同一个名字**：数据传递本来就有按名对齐的
    语义（``layers_*_select_dst='NAME'``），名字不同就不该传过去——那是另一条测试。
    """
    mesh = ob.data
    # 顶点组权重（挂在物体上，按组名对齐）
    group = ob.vertex_groups.new(name=group_name)
    group.add([0, 1], weight, "REPLACE")
    # 顶点色（点域）与角点色（面拐域）
    vertex_color = mesh.color_attributes.new(
        name=layer_names[2], type="FLOAT_COLOR", domain="POINT"
    )
    for item in vertex_color.data:
        item.color = color
    corner_color = mesh.color_attributes.new(
        name=layer_names[1], type="FLOAT_COLOR", domain="CORNER"
    )
    for index, item in enumerate(corner_color.data):
        item.color = (color[0], color[1], color[2], index / 8.0)
    # UV
    uv_layer = mesh.uv_layers.new(name=layer_names[0])
    for index, item in enumerate(uv_layer.data):
        item.uv = (uv_base + index * 0.05, uv_base)
    # 边数据：折痕、锐边、缝合
    crease_attribute = mesh.attributes.get("crease_edge")
    if crease_attribute is None:
        crease_attribute = mesh.attributes.new(
            name="crease_edge", type="FLOAT", domain="EDGE"
        )
    for index, item in enumerate(crease_attribute.data):
        item.value = crease
    mesh.edges[0].use_edge_sharp = True
    mesh.edges[1].use_seam = True
    # 面平滑
    for polygon in mesh.polygons:
        polygon.use_smooth = smooth
    mesh.update()


def configure_transfer(transfer, source, *, loop_mapping="TOPOLOGY",
                       vert_mapping="TOPOLOGY", edge_mapping="TOPOLOGY",
                       poly_mapping="TOPOLOGY", verts=True, edges=True,
                       loops=True, polys=True):
    transfer.object = source
    transfer.use_object_transform = True
    transfer.mix_mode = "REPLACE"
    transfer.mix_factor = 1.0
    transfer.layers_vgroup_select_src = "ALL"
    transfer.layers_vgroup_select_dst = "NAME"
    transfer.layers_uv_select_src = "ALL"
    transfer.layers_uv_select_dst = "NAME"
    transfer.layers_vcol_vert_select_src = "ALL"
    transfer.layers_vcol_vert_select_dst = "NAME"
    transfer.layers_vcol_loop_select_src = "ALL"
    transfer.layers_vcol_loop_select_dst = "NAME"
    if verts:
        transfer.use_vert_data = True
        transfer.data_types_verts = {"VGROUP_WEIGHTS", "COLOR_VERTEX"}
        transfer.vert_mapping = vert_mapping
    if edges:
        transfer.use_edge_data = True
        transfer.data_types_edges = {"SHARP_EDGE", "SEAM", "CREASE"}
        transfer.edge_mapping = edge_mapping
    if loops:
        transfer.use_loop_data = True
        transfer.data_types_loops = {"CUSTOM_NORMAL", "COLOR_CORNER", "UV"}
        transfer.loop_mapping = loop_mapping
    if polys:
        transfer.use_poly_data = True
        transfer.data_types_polys = {"SMOOTH"}
        transfer.poly_mapping = poly_mapping
    if loops:
        # 必须放在最后：Blender 里给 DATA_TRANSFER 打开“面数据”会把面拐里的 UV 从
        # data_types_loops 里静默去掉（实测 use_poly_data=True 之后 UV 就没了），
        # 所以面拐那一组要在所有域都配好之后再设一次。
        transfer.data_types_loops = {"CUSTOM_NORMAL", "COLOR_CORNER", "UV"}
    return transfer


def build_full_fixture(tag, *, with_mirror_before=False, with_mirror_after=False,
                       loop_mapping="TOPOLOGY"):
    """源与目标都带四个域的数据；目标的每个域都与源不同，方便判断“传过来了没有”。"""
    offset = (0.25, 0.0, 0.0) if (with_mirror_before or with_mirror_after) else (0.0, 0.0, 0.0)
    source = make_quad(f"Src_{tag}", offset=offset)
    add_full_data(
        source, tag="Src", weight=SOURCE_WEIGHT, color=SOURCE_COLOR,
        uv_base=0.1, smooth=True, crease=0.9,
    )
    target = make_quad(f"Tgt_{tag}", offset=offset)
    add_full_data(
        target, tag="Tgt", weight=0.2, color=TARGET_COLOR,
        uv_base=0.6, smooth=False, crease=0.1,
    )
    if with_mirror_before:
        # 数据传递要求源与目标在“传递那一刻”的拓扑对得上，所以两边都要有同样的镜像；
        # 源侧镜像同时也是“源自己也有前置修改器”的覆盖点（顶点组权重最容易在这里丢）。
        source.modifiers.new("SourceMirror", "MIRROR")
        target.modifiers.new("BeforeMirror", "MIRROR")
    transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
    configure_transfer(transfer, source, loop_mapping=loop_mapping)
    if with_mirror_after:
        target.modifiers.new("AfterMirror", "MIRROR")
    activate(target)
    return source, target


def capture_baseline(ob, *, with_vertex_groups=True):
    """把“界面里看到的数据传递结果”取下来。

    顶点组有个特殊性质：依赖图求值**不算** DATA_TRANSFER 的权重组，所以基准的权重只能
    从物体上的实际权重来（对本测试的物体，传递之后没有改拓扑的修改器时它就是最终权重）。
    用 :meth:`viewport_reference_object` 复制一套临时结构求值原始物体一个字节都不动。
    """
    cache = {}
    reference = FbxExporter.viewport_reference_object(ob, cache)
    assert reference is not None, f"取基准失败：{ob.name}"
    try:
        state = evaluated_state(reference, with_vertex_groups=False)
    finally:
        FbxExporter.clear_viewport_references()
        FbxExporter.release_transfer_stages(cache)
    if with_vertex_groups:
        state["vertex_groups"] = vertex_group_weights(ob)
    return state


def check(tag, expected_baseline, ob, *, tolerance=1e-4, skip_vertex_groups=False,
          expected_vertex_groups=None):
    """求值状态下与“没被动过的视口口径”逐域比对。

    顶点组要单独给期望值：依赖图求值不算 DATA_TRANSFER 的权重组，所以“基准”里拿到的是
    传递**之前**的权重。传进来的 ``expected_vertex_groups`` 才是应得的结果（没有改拓扑
    的后置修改器时就是物体上的权重；有镜像时由 :func:`vertex_groups_after_mirror` 推）。
    """
    final = evaluated_state(ob)
    # 顶点组只存在于物体上（依赖图求值不算），所以两边都用同一份“应得权重”来比：
    # 显式给了 expected_vertex_groups 就用它，否则用物体上当前的权重。
    weights = (
        vertex_group_weights(ob) if expected_vertex_groups is None
        else expected_vertex_groups
    )
    if skip_vertex_groups:
        expected = without_vertex_groups(expected_baseline)
        final = without_vertex_groups(final)
    else:
        expected = replace_vertex_groups(expected_baseline, weights)
        final = replace_vertex_groups(final, weights)
    problems = diff_state(expected, final, tolerance=tolerance)
    assert not problems, (
        f"[{tag}] 数据传递链接管后与视口不一致，共 {len(problems)} 处：\n  "
        + "\n  ".join(problems[:12])
    )
    return final


def check_group_weights(tag, ob, group_name, expected_pairs):
    """按 {顶点索引: 权重} 精确校验某个顶点组（用于推演镜像后的权重）。"""
    weights = vertex_group_weights(ob).get(group_name, {})
    for index, weight in expected_pairs.items():
        assert index in weights, f"[{tag}] 顶点 {index} 在组 {group_name} 里没有权重"
        assert abs(weights[index] - weight) < 1e-4, (
            f"[{tag}] 组 {group_name} 顶点 {index} 权重期望 {weight} 实际 {weights[index]}"
        )
    assert len(weights) == len(expected_pairs), (
        f"[{tag}] 组 {group_name} 权重数量期望 {len(expected_pairs)} 实际 {len(weights)}：{weights}"
    )


# ── 1. 四个域全开：传递必须逐域与视口一致 ────────────────────────────────────
clear_scene()
_source, target = build_full_fixture("all")
baseline = capture_baseline(target)
assert baseline["custom_normals"] is not None, "测试场景无效：基准没有自定义法线"
applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
assert [mod.name for mod in target.modifiers] == [], (
    f"数据传递链应当被应用掉，剩余 {[m.name for m in target.modifiers]}"
)
final = check("1-四域全开", baseline, target,
              expected_vertex_groups={"Weight": {0: SOURCE_WEIGHT, 1: SOURCE_WEIGHT}})

# 数据确实来自源（而不是目标自身的旧值）
assert final["vertex_groups"], "顶点组权重没有被传过来"
group_name = "Weight"
assert group_name in final["vertex_groups"], f"权重组丢了：{final['vertex_groups']}"
assert abs(final["vertex_groups"][group_name][0] - SOURCE_WEIGHT) < 1e-4, (
    f"权重没换成源的值：{final['vertex_groups']}"
)
assert abs(final["face_smooth"][0] - 1) < 1e-6, "面平滑没传过来"
layer_names = set(final["uv_layers"]) | set(final["color_attributes"])
assert "UV" in layer_names, f"UV 层丢了：{layer_names}"
# 源与目标的数据层同名，所以传递之后值应该变成源的
assert abs(final["uv_layers"]["UV"][0][0] - 0.1) < 1e-4, (
    f"UV 没换成源的值：{final['uv_layers']['UV'][:2]}"
)
assert abs(final["color_attributes"]["CCol"][0][0] - SOURCE_COLOR[0]) < 1e-4, (
    f"角点色没换成源的值：{final['color_attributes']['CCol'][:2]}"
)
assert abs(final["color_attributes"]["VCol"][0][0] - SOURCE_COLOR[0]) < 1e-4, (
    f"顶点色没换成源的值：{final['color_attributes']['VCol'][:2]}"
)
# 边数据：源上第 0 条锐边、第 1 条缝合，目标上正好相反 → 传过来后应变成源的形态
assert final["edge_flags"] == [(1, 0), (0, 1), (0, 0), (0, 0)], (
    f"锐边/缝合没传对：{final['edge_flags']}"
)
crease_key = "crease_edge"
if crease_key in final["edge_attributes"]:
    assert abs(final["edge_attributes"][crease_key][0] - 0.9) < 1e-4, (
        f"折痕没传过来：{final['edge_attributes'][crease_key]}"
    )
print("[domains] 1 四域全开：顶点组/顶点色/角点色/UV/锐边/缝合/折痕/平滑 全部与视口一致")

# ── 2. 传递之前有改拓扑的修改器（镜像）：整层接管后仍要与视口一致 ────────────
clear_scene()
_source, target = build_full_fixture("before_mirror", with_mirror_before=True)
baseline = capture_baseline(target)
assert len(baseline["verts"]) == 8, f"测试场景无效：镜像后应有 8 个顶点，实际 {len(baseline['verts'])}"
applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
assert [mod.name for mod in target.modifiers] == [], (
    "数据传递之前的前置修改器也应该被这一层接管掉："
    f"{[m.name for m in target.modifiers]}"
)
check("2-前置镜像", baseline, target,
      expected_vertex_groups=vertex_groups_after_mirror(
          {"Weight": {0: SOURCE_WEIGHT, 1: SOURCE_WEIGHT}}, 8))
# 镜像后的权重：源是 0.75（同名组），镜像把顶点连同权重复制成两半
mirrored = vertex_groups_after_mirror({"Weight": {0: SOURCE_WEIGHT, 1: SOURCE_WEIGHT}}, 8)
check_group_weights("2-前置镜像", target, "Weight", mirrored["Weight"])
print("[domains] 2 前置镜像：整层接管后 8 个顶点/全部数据域与视口一致，权重也按镜像展开")

# ── 3. 传递在栈中间（后面还有镜像）：后面的修改器必须保留，结果与视口一致 ─────
clear_scene()
_source, target = build_full_fixture("after_mirror", with_mirror_after=True)
baseline = capture_baseline(target)
assert len(baseline["verts"]) == 8, "测试场景无效：镜像后应有 8 个顶点"
applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
assert [mod.name for mod in target.modifiers] == ["AfterMirror"], (
    "数据传递之后的镜像必须留在栈上："
    f"{[m.name for m in target.modifiers]}"
)
check("3-传递在栈中间", baseline, target, skip_vertex_groups=True)
# 基础网格（4 顶点）应当已经拿到源的权重；镜像会把它们展开成 8 个
check_group_weights(
    "3-传递在栈中间（基础网格）", target, "Weight",
    {0: SOURCE_WEIGHT, 1: SOURCE_WEIGHT},
)
print("[domains] 3 传递在栈中间：后置镜像保留，栈上结果与视口一致")

# ── 4. 多个目标共用一个源，且源自己也有数据传递：顺序不能影响结果 ───────────
clear_scene()
# A 有源数据；B 的传递源是 A（B 是“中间层”）；C、D 的传递源都是 B。
a = make_quad("ChainA")
add_full_data(a, tag="A", weight=0.9, color=(0.9, 0.1, 0.1, 1.0),
              uv_base=0.0, smooth=True, crease=0.8)
b = make_quad("ChainB")
add_full_data(b, tag="B", weight=0.1, color=(0.1, 0.9, 0.1, 1.0),
              uv_base=0.5, smooth=False, crease=0.2)
configure_transfer(b.modifiers.new("BTransfer", "DATA_TRANSFER"), a)
c = make_quad("ChainC")
add_full_data(c, tag="C", weight=0.1, color=(0.1, 0.1, 0.9, 1.0),
              uv_base=0.5, smooth=False, crease=0.2)
configure_transfer(c.modifiers.new("CTransfer", "DATA_TRANSFER"), b)
d = make_quad("ChainD")
add_full_data(d, tag="D", weight=0.1, color=(0.1, 0.1, 0.9, 1.0),
              uv_base=0.5, smooth=False, crease=0.2)
configure_transfer(d.modifiers.new("DTransfer", "DATA_TRANSFER"), b)
activate(d)
baseline_b = capture_baseline(b)
baseline_c = capture_baseline(c)
baseline_d = capture_baseline(d)

# 顺序故意打乱：把下游排在源前面
order = FbxExporter._upstream_first(["ChainC", "ChainD", "ChainB", "ChainA"])
assert order.index("ChainA") < order.index("ChainB"), f"源 A 必须排在 B 之前：{order}"
assert order.index("ChainB") < order.index("ChainC"), f"源 B 必须排在 C 之前：{order}"
assert order.index("ChainB") < order.index("ChainD"), f"源 B 必须排在 D 之前：{order}"

applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [a, c, d, b], [a, c, d, b], b
)
assert applied == 3 and not failed, (applied, failed)
check("4-互为源 B", baseline_b, b,
      expected_vertex_groups={"Weight": {0: 0.9, 1: 0.9}})
check("4-互为源 C", baseline_c, c,
      expected_vertex_groups={"Weight": {0: 0.9, 1: 0.9}})
check("4-互为源 D", baseline_d, d,
      expected_vertex_groups={"Weight": {0: 0.9, 1: 0.9}})
print("[domains] 4 互为源的下游：整层接管结果与视口一致，且与处理顺序无关")

# ── 5. 只在渲染中显示的传递：导出按渲染口径，整层接管也必须按渲染口径 ────────
clear_scene()
source = make_quad("RenderSrc")
add_full_data(source, tag="RSrc", weight=0.85, color=(0.2, 0.4, 0.6, 1.0),
              uv_base=0.05, smooth=True, crease=0.7)
target = make_quad("RenderTgt")
add_full_data(target, tag="RTgt", weight=0.15, color=(0.7, 0.5, 0.3, 1.0),
              uv_base=0.55, smooth=False, crease=0.15)
transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
configure_transfer(transfer, source)
transfer.show_viewport = False
transfer.show_render = True
activate(target)
# 渲染口径基准：临时打开视口开关取一次（求值图口径与渲染口径一致）
transfer.show_viewport = True
bpy.context.view_layer.update()
baseline = capture_baseline(target)
transfer.show_viewport = False
bpy.context.view_layer.update()

applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
# 只在渲染中显示的传递，导出是按渲染口径算的，所以它必须被这一层吃掉；
# 但过程里临时借用的视口开关不能被改坏 —— 这里改成“接管前记录、接管后确认已摘除”。
assert [mod.name for mod in target.modifiers] == [], (
    "只在渲染中显示的数据传递也应当被这一层接管："
    f"{[m.name for m in target.modifiers]}"
)
check("5-只在渲染中显示", baseline, target,
      expected_vertex_groups={"Weight": {0: 0.85, 1: 0.85}})
print("[domains] 5 只在渲染中显示的传递：按渲染口径整层接管，与渲染口径一致")

# ── 6. 传递源对象被隐藏（hided_get）也不能影响结果 ───────────────────────────
clear_scene()
source = make_quad("HiddenSrc")
add_full_data(source, tag="HSrc", weight=0.65, color=(0.3, 0.6, 0.2, 1.0),
              uv_base=0.2, smooth=True, crease=0.6)
target = make_quad("HiddenTgt")
add_full_data(target, tag="HTgt", weight=0.25, color=(0.6, 0.3, 0.4, 1.0),
              uv_base=0.5, smooth=False, crease=0.2)
configure_transfer(target.modifiers.new("DataTransfer", "DATA_TRANSFER"), source)
activate(target)
baseline = capture_baseline(target)
source.hide_set(True)  # 视口里看不到源，但导出时会被全显
bpy.context.view_layer.update()
applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
check("6-源被隐藏", baseline, target,
      expected_vertex_groups={"Weight": {0: 0.65, 1: 0.65}})
print("[domains] 6 源被隐藏：结果不受影响")

# ── 7. 各映射模式：顶点/边/面拐/面 的映射枚举都要能整层接管 ──────────────────
clear_scene()
mapping_cases = [
    ("循环-最近法线", {"loop_mapping": "NEAREST_NORMAL"}),
    ("循环-多边形插值", {"loop_mapping": "POLYINTERP_LNORPROJ"}),
    ("顶点-最近", {"vert_mapping": "NEAREST"}),
    ("顶点-多边形插值", {"vert_mapping": "POLYINTERP_VNORPROJ"}),
    ("边-最近", {"edge_mapping": "NEAREST"}),
    ("面-最近", {"poly_mapping": "NEAREST"}),
]
for case_index, (case_name, overrides) in enumerate(mapping_cases):
    source = make_quad(f"MapSrc{case_index}")
    add_full_data(source, tag="MSrc", weight=0.8, color=(0.2, 0.3, 0.9, 1.0),
                  uv_base=0.1, smooth=True, crease=0.75)
    target = make_quad(f"MapTgt{case_index}")
    add_full_data(target, tag="MTgt", weight=0.2, color=(0.8, 0.6, 0.2, 1.0),
                  uv_base=0.6, smooth=False, crease=0.2)
    transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
    configure_transfer(transfer, source)
    for key, value in overrides.items():
        setattr(transfer, key, value)
    activate(target)
    baseline = capture_baseline(target)
    applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
        [target], [target], target
    )
    assert applied == 1 and not failed, (case_name, applied, failed)
    check(f"7-{case_name}", baseline, target,
          expected_vertex_groups={"Weight": {0: 0.8, 1: 0.8}})
print(f"[domains] 7 映射模式：{len(mapping_cases)} 种（顶点/边/面拐/面）全部一致")

# ── 8. 不传某些域时，未参与传递的域不能被改坏 ────────────────────────────────
clear_scene()
source = make_quad("PartialSrc")
add_full_data(source, tag="PSrc", weight=0.85, color=(0.9, 0.3, 0.3, 1.0),
              uv_base=0.1, smooth=True, crease=0.8)
target = make_quad("PartialTgt")
add_full_data(target, tag="PTgt", weight=0.15, color=(0.3, 0.3, 0.9, 1.0),
              uv_base=0.6, smooth=False, crease=0.2)
# 只传面拐（法线/UV/角点色），顶点与边数据不参与
transfer = target.modifiers.new("DataTransfer", "DATA_TRANSFER")
configure_transfer(transfer, source, verts=False, edges=False, polys=False)
activate(target)
baseline = capture_baseline(target)
applied, failed, _s, _a = FbxExporter.apply_data_transfer_modifiers(
    [target], [target], target
)
assert applied == 1 and not failed, (applied, failed)
final = check("8-只传面拐", baseline, target,
              expected_vertex_groups={"Weight": {0: 0.15, 1: 0.15}})
# 目标自己的顶点权重必须还是自己的 0.15（源是同名组、值为 0.85，不能传过来覆盖）
assert "Weight" in final["vertex_groups"], f"权重组丢了：{final['vertex_groups']}"
assert abs(final["vertex_groups"]["Weight"][0] - 0.15) < 1e-4, (
    f"未参与传递的顶点权重被改坏了：{final['vertex_groups']}"
)
assert abs(final["face_smooth"][0]) < 1e-6, "未参与传递的面平滑被改坏了"
print("[domains] 8 只传面拐：未参与传递的域保持目标自身数据")

print("FBX_DATA_TRANSFER_DOMAINS_OK", bpy.app.version_string)
