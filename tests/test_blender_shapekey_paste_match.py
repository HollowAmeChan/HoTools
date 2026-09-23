"""粘贴形态键「尽力匹配」支线的回归测试。

两点背景：

- Blender 在 ``--background`` 下 ``window_manager.clipboard`` 是只读的空串
  （4.5.8 实测：赋值后立刻读回仍是 ''），所以这里**不碰真剪贴板**：
  映射逻辑直接喂 payload，算子链路用 monkeypatch 顶掉 ``parse_payload``。
- 「逐位一致」的断言一律在 double 下按实现里同样的算术算好、再降到 float32，
  这样比的是 Blender 真正会存进去的那个值，不会被二次舍入差异干扰。
"""

import importlib
import json
import sys
import types
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
shapekey_package = types.ModuleType("HoTools.ShapekeyTools")
shapekey_package.__path__ = [str(ADDON_DIR / "ShapekeyTools")]
sys.modules.setdefault("HoTools.ShapekeyTools", shapekey_package)

module = importlib.import_module("HoTools.ShapekeyTools.operators")
geometry = importlib.import_module("HoTools.ShapekeyTools.paste.geometry")
matcher = importlib.import_module("HoTools.ShapekeyTools.paste.matcher")
ShapekeyPasteMatch = matcher.ShapekeyPasteMatch
BASE = module._FullShapekeyPasteBase

INDEX = geometry.MODE_VERTEX_INDEX
WORLD = geometry.MODE_WORLD_POSITION
UV = geometry.MODE_UV_POSITION


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------

def make_object(name, coords, faces=None):
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata([tuple(co) for co in coords], [], list(faces or []))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def add_shape_key(obj, name, deltas):
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis", from_mix=False)
    basis = obj.data.shape_keys.reference_key
    key = obj.shape_key_add(name=name, from_mix=False)
    for index, delta in enumerate(deltas):
        key.data[index].co = basis.data[index].co + Vector(delta)
    # 粘贴链路要求活动键 value == 1（或开 Solo），夹具里显式满足
    key.value = 1.0
    obj.active_shape_key_index = obj.data.shape_keys.key_blocks.find(name)
    return key


def assign_uv_per_vertex(obj, uv_by_vertex):
    layer = obj.data.uv_layers.new(name="UVMap")
    for loop in obj.data.loops:
        layer.data[loop.index].uv = uv_by_vertex[loop.vertex_index]


def select_only(obj):
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def key_positions(obj, name):
    key = obj.data.shape_keys.key_blocks[name]
    return np.array([point.co[:] for point in key.data], dtype=np.float32)


def basis_positions(obj):
    basis = obj.data.shape_keys.reference_key
    return np.array([point.co[:] for point in basis.data], dtype=np.float32)


def expected_positions(obj, deltas):
    """旧实现的算术：基型 + 位移（double 计算后降到 float32）。"""
    basis = obj.data.shape_keys.reference_key
    return np.array(
        [tuple(basis.data[index].co + Vector(delta))
         for index, delta in enumerate(deltas)],
        dtype=np.float32)


def expected_vertex(obj, index, delta):
    """单个顶点的期望值：该顶点基型 + 位移。"""
    basis = obj.data.shape_keys.reference_key
    return np.array(
        tuple(basis.data[index].co + Vector(delta)), dtype=np.float32)


def payload_of(obj, key_name, **kwargs):
    return ShapekeyPasteMatch.build_payload(
        obj, obj.data.shape_keys.key_blocks[key_name], **kwargs)


def clipboard_with(data):
    """顶掉剪贴板解析：算子拿到的数据先经真实解析器处理，和真剪贴板一致。

    ``data`` 可以是 V2 payload 字典，也可以是旧格式的裸数组。
    """
    parsed, error = original_parse(json.dumps(data))
    assert error is None, error

    def fake_parse(text):
        return dict(parsed), None

    return fake_parse


class StubOperator(BASE):
    """算子实例无法直接构造，用真子类拿正确的绑定方法。"""

    def __init__(self, operation, verb, is_abs=False):
        self.operation = operation
        self.success_verb = verb
        self.is_abs = is_abs


def stub_operator(operation, verb, is_abs=False):
    return StubOperator(operation, verb, is_abs)


class FakeLayout:
    """记录调用的假 layout。

    后台模式没法真的开弹窗，但 draw() 里的属性名/常量写错必须能被测出来
    （``ShapekeyPasteMatch.UV_MODE_HINT`` 就曾经是个模块级常量而被当成类属性用了）。
    """

    def __init__(self, records=None):
        self.alert = False
        self.records = records if records is not None else []

    def box(self):
        return FakeLayout(self.records)

    def row(self, align=False):
        return FakeLayout(self.records)

    def column(self, align=False):
        return FakeLayout(self.records)

    def label(self, text="", **kwargs):
        self.records.append(("label", text))

    def prop(self, data, name, **kwargs):
        self.records.append(("prop", name))

    def separator(self):
        self.records.append(("separator", ""))

    def texts(self):
        return [value for kind, value in self.records if kind == "label"]

    def props(self):
        return [value for kind, value in self.records if kind == "prop"]


def draw_dialog(data, objects, error=None):
    """跑一遍真实的 draw()，返回假 layout 记录。"""
    harness = stub_operator('replace', "已粘贴到")
    harness.layout = FakeLayout()
    if error is None:
        ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(data))
    else:
        ShapekeyPasteMatch.parse_payload = staticmethod(
            lambda text: (None, error))
    context = types.SimpleNamespace(
        window_manager=bpy.context.window_manager,
        selected_objects=list(objects))
    BASE.draw(harness, context)
    return harness.layout


# ----------------------------------------------------------------------
# 测试
# ----------------------------------------------------------------------

created = []
registered = (
    module.OP_ShapekeyTools_copyShapekey2ShearPlate,
    module.OP_ShapekeyTools_importShapekeyFromShearPlate,
    module.OP_ShapekeyTools_importShapekeyFromShearPlate_Relative_add,
    module.OP_ShapekeyTools_importShapekeyFromShearPlate_Relative_sub,
)
for operator in registered:
    bpy.utils.register_class(operator)
module.reg_props()

PASTE = bpy.ops.ho.shapekeytools_importshapekey_from_shearplate
ADD = bpy.ops.ho.shapekeytools_importshapekey_from_shearplate_relatove_add
original_parse = ShapekeyPasteMatch.parse_payload

LINE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
DELTAS = [(0.0, 1.0, 0.0), (0.0, 2.0, 0.0), (0.0, 3.0, 0.0), (0.0, 4.0, 0.0)]
ORDER = [3, 0, 2, 1]

try:
    # ---------- 剪贴板协议 ----------
    src = make_object("MatchSrc", LINE)
    created.append(src)
    add_shape_key(src, "Smile", DELTAS)
    payload = payload_of(src, "Smile", is_abs=False, value=1.0)

    assert payload["type"] == matcher.CLIPBOARD_TYPE
    assert payload["source_object"] == "MatchSrc"
    assert payload["vertex_count"] == 4
    # 只存引用与位移，不存基型/UV 快照
    assert set(payload) == {
        "type", "shape_key", "value", "is_abs", "vertex_count",
        "source_object", "coords"}
    assert payload["coords"] == [list(delta) for delta in DELTAS]

    parsed, error = ShapekeyPasteMatch.parse_payload(json.dumps(payload))
    assert error is None
    assert parsed["coords"] == payload["coords"] and parsed["legacy"] is False

    # 位移算术与旧复制实现一致：相对模式减基型再乘键值
    scaled = ShapekeyPasteMatch.extract_coords(src, src.active_shape_key,
                                              is_abs=False, value=0.5)
    assert np.allclose(scaled, np.array(DELTAS) * 0.5, atol=1e-6)

    # 旧格式（裸数组）仍然认得，且不带引用
    legacy, error = ShapekeyPasteMatch.parse_payload(json.dumps(DELTAS))
    assert error is None and legacy["legacy"] is True
    assert legacy["source_object"] == "" and legacy["vertex_count"] == 4

    # 局部粘贴的数据被明确拒绝，不会当成全量数据
    _, error = ShapekeyPasteMatch.parse_payload(json.dumps(
        {"type": "HoToolsPartialRelativeShapeKeyV1", "vertices": []}))
    assert error is not None and "局部" in error
    _, error = ShapekeyPasteMatch.parse_payload("{not json")
    assert error is not None
    _, error = ShapekeyPasteMatch.parse_payload(json.dumps([[0.0, 0.0]]))
    assert error is not None

    # ---------- 同拓扑：按点序直填，与旧实现逐位一致 ----------
    same = make_object("MatchSame", LINE)
    created.append(same)
    add_shape_key(same, "Smile", [(0.0, 0.0, 0.0)] * 4)
    mapping = ShapekeyPasteMatch.build_mapping(src, same, payload, mode=INDEX)
    assert mapping.exact == 4 and mapping.rescued == 0 and mapping.unmatched == 0
    assert mapping.pairs == {index: [(index, 1.0)] for index in range(4)}

    report = ShapekeyPasteMatch.inspect(payload, [same])
    assert report.mismatch is False
    assert report.entries[0].agreement == 1.0
    assert report.entries[0].source_count == 4 and report.entries[0].dest_count == 4

    select_only(same)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    assert PASTE("EXEC_DEFAULT") == {'FINISHED'}
    assert np.array_equal(
        key_positions(same, "Smile"), expected_positions(same, DELTAS))

    # 旧格式剪贴板走同一条直填路径
    add_shape_key(same, "Legacy", [(0.0, 0.0, 0.0)] * 4)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(DELTAS))
    assert PASTE("EXEC_DEFAULT") == {'FINISHED'}
    assert np.array_equal(
        key_positions(same, "Legacy"), expected_positions(same, DELTAS))

    # 同拓扑走叠加也是旧路径
    add_shape_key(same, "Add", [(0.0, 0.0, 0.0)] * 4)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    assert ADD("EXEC_DEFAULT") == {'FINISHED'}
    assert np.array_equal(key_positions(same, "Add"), expected_positions(same, DELTAS))

    # ---------- 删掉一个顶点：点序校验 + 最近邻修正 ----------
    deleted = make_object("MatchDeleted", [LINE[0], LINE[1], LINE[3]])
    created.append(deleted)
    add_shape_key(deleted, "Smile", [(0.0, 0.0, 0.0)] * 3)

    report = ShapekeyPasteMatch.inspect(payload, [deleted])
    assert report.mismatch is True
    assert report.entries[0].source_count == 4
    assert report.entries[0].dest_count == 3
    assert abs(report.entries[0].agreement - 2 / 3) < 1e-6  # 前两点还对得上

    mapping = ShapekeyPasteMatch.build_mapping(src, deleted, payload, mode=INDEX)
    assert mapping.exact == 2 and mapping.rescued == 1 and mapping.unmatched == 0
    assert mapping.pairs[2] == [(3, 1.0)]

    select_only(deleted)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    # 显式钉住模式：默认模式是产品选择（现在是 UV），测试不该跟着它漂
    assert PASTE("EXEC_DEFAULT", match_mode=INDEX) == {'FINISHED'}
    assert np.array_equal(
        key_positions(deleted, "Smile"),
        expected_positions(deleted, [DELTAS[0], DELTAS[1], DELTAS[3]]))

    # ---------- 合并进来的新顶点：够不到就保持原值 ----------
    merged = make_object("MatchMerged", LINE + [(100.0, 0.0, 0.0)])
    created.append(merged)
    add_shape_key(merged, "Smile", [(0.0, 0.0, 0.0)] * 5)
    mapping = ShapekeyPasteMatch.build_mapping(src, merged, payload, mode=INDEX)
    assert mapping.exact == 4 and mapping.rescued == 0 and mapping.unmatched == 1
    assert 4 not in mapping.pairs

    select_only(merged)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    assert PASTE("EXEC_DEFAULT", match_mode=INDEX) == {'FINISHED'}
    merged_positions = key_positions(merged, "Smile")
    assert np.array_equal(
        merged_positions[:4], expected_positions(merged, DELTAS))
    # 未匹配的点保持基型，没被写入
    assert np.array_equal(merged_positions[4], basis_positions(merged)[4])

    # ---------- 点数相等但点序被打乱 ----------
    scrambled = make_object(
        "MatchScrambled", [LINE[index] for index in ORDER])
    created.append(scrambled)
    add_shape_key(scrambled, "Smile", [(0.0, 0.0, 0.0)] * 4)

    report = ShapekeyPasteMatch.inspect(payload, [scrambled])
    assert report.mismatch is True
    assert report.entries[0].agreement < matcher.MISMATCH_AGREEMENT

    # 点序模式只能偶然命中一个点，世界位置模式能把顺序修回来
    assert ShapekeyPasteMatch.build_mapping(
        src, scrambled, payload, mode=INDEX).exact == 1
    world_mapping = ShapekeyPasteMatch.build_mapping(
        src, scrambled, payload, mode=WORLD)
    assert world_mapping.matched == 4 and world_mapping.unmatched == 0
    assert world_mapping.pairs == {j: [(ORDER[j], 1.0)] for j in range(4)}

    select_only(scrambled)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    assert PASTE("EXEC_DEFAULT", match_mode=WORLD) == {'FINISHED'}
    restored = key_positions(scrambled, "Smile")
    for dest_index, source_index in enumerate(ORDER):
        assert np.array_equal(
            restored[dest_index],
            expected_vertex(scrambled, dest_index, DELTAS[source_index]))

    # ---------- 点序模式比本地空间：复制体被挪到别处也照样能用 ----------
    moved_copy = make_object("MatchMovedCopy", LINE)
    created.append(moved_copy)
    add_shape_key(moved_copy, "Smile", [(0.0, 0.0, 0.0)] * 4)
    moved_copy.matrix_world = Matrix.Translation((5.0, 0.0, 0.0))

    assert ShapekeyPasteMatch.inspect(payload, [moved_copy]).mismatch is False
    moved_mapping = ShapekeyPasteMatch.build_mapping(
        src, moved_copy, payload, mode=INDEX)
    assert moved_mapping.exact == 4 and moved_mapping.unmatched == 0

    # 混选：拓扑一致（只是被挪到别处）的物体仍然按点序直填，不被同一个模式连累。
    # 这里故意用世界位置模式——如果它也跟着走世界匹配，挪远之后会一个点都对不上。
    select_only(moved_copy)
    deleted.select_set(True)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(payload))
    assert PASTE("EXEC_DEFAULT", match_mode=WORLD) == {'FINISHED'}
    assert np.array_equal(
        key_positions(moved_copy, "Smile"), expected_positions(moved_copy, DELTAS))
    assert np.array_equal(
        key_positions(deleted, "Smile"),
        expected_positions(deleted, [DELTAS[0], DELTAS[1], DELTAS[3]]))

    # 源物体自己被移动/缩放，点序模式照样全中
    src.matrix_world = Matrix.Translation((2.0, 0.0, 0.0)) @ Matrix.Scale(3.0, 4)
    assert ShapekeyPasteMatch.build_mapping(
        src, src, payload, mode=INDEX).exact == 4
    assert ShapekeyPasteMatch.inspect(payload, [src]).mismatch is False
    src.matrix_world = Matrix.Identity(4)

    # ---------- UV 模式 ----------
    faces = [(0, 1, 2), (0, 2, 3)]
    uv_src = make_object("MatchUvSrc", LINE, faces)
    created.append(uv_src)
    add_shape_key(uv_src, "Smile", DELTAS)
    assign_uv_per_vertex(uv_src, {index: (0.1 * index, 0.0) for index in range(4)})

    uv_dest = make_object(
        "MatchUvDest", [LINE[index] for index in ORDER], faces)
    created.append(uv_dest)
    add_shape_key(uv_dest, "Smile", [(0.0, 0.0, 0.0)] * 4)
    assign_uv_per_vertex(
        uv_dest, {j: (0.1 * ORDER[j], 0.0) for j in range(4)})

    uv_payload = payload_of(uv_src, "Smile", is_abs=False, value=1.0)
    uv_mapping = ShapekeyPasteMatch.build_mapping(
        uv_src, uv_dest, uv_payload, mode=UV)
    assert uv_mapping.matched == 4 and uv_mapping.unmatched == 0
    assert uv_mapping.pairs == {j: [(ORDER[j], 1.0)] for j in range(4)}

    # 目标没有活动 UV 层时给出明确错误，而不是静默算错
    no_uv = make_object("MatchNoUv", LINE)
    created.append(no_uv)
    add_shape_key(no_uv, "Smile", [(0.0, 0.0, 0.0)] * 4)
    try:
        ShapekeyPasteMatch.build_mapping(uv_src, no_uv, uv_payload, mode=UV)
    except geometry.ShapekeyMatchError as exc:
        assert "UV" in str(exc)
    else:
        raise AssertionError("目标没有 UV 层时应当报错")

    # ---------- UV 重合：按模型原点分左右象限，优先取同侧点 ----------
    assert list(geometry.side_mask(
        [[0.0, 0.0, 0.0], [-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])) == [True, False, True]

    # 左右两侧共用同一片 UV：0/1 同 UV、2/3 同 UV，靠 UV 本身分不开，只能靠 X 的正负
    sym_line = [(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (-2.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
    sym_uv = {0: (0.3, 0.0), 1: (0.3, 0.0), 2: (0.6, 0.0), 3: (0.6, 0.0)}
    sym_order = [1, 0, 3, 2]

    side_src = make_object("MatchSideSrc", sym_line, faces)
    created.append(side_src)
    add_shape_key(side_src, "Smile", DELTAS)
    assign_uv_per_vertex(side_src, sym_uv)

    side_dest = make_object(
        "MatchSideDest", [sym_line[index] for index in sym_order], faces)
    created.append(side_dest)
    add_shape_key(side_dest, "Smile", [(0.0, 0.0, 0.0)] * 4)
    assign_uv_per_vertex(
        side_dest, {j: sym_uv[sym_order[j]] for j in range(4)})

    side_payload = payload_of(side_src, "Smile", is_abs=False, value=1.0)
    side_mapping = ShapekeyPasteMatch.build_mapping(
        side_src, side_dest, side_payload, mode=UV)
    assert side_mapping.matched == 4 and side_mapping.unmatched == 0
    # 同 UV 的两侧点里必须挑到同侧的那个，而不是谁先插入就挑谁
    assert side_mapping.pairs == {
        j: [(sym_order[j], 1.0)] for j in range(4)}, side_mapping.pairs

    # 同侧树为空（源全在正侧、目标有负侧点）时必须退回另一侧，等价于原来的全局最近邻
    one_sided = make_object(
        "MatchOneSided", [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                          (3.0, 0.0, 0.0), (4.0, 0.0, 0.0)], faces)
    created.append(one_sided)
    add_shape_key(one_sided, "Smile", DELTAS)
    assign_uv_per_vertex(one_sided, {i: (0.1 * i, 0.0) for i in range(4)})

    crossed = make_object(
        "MatchCrossed", [(1.0, 0.0, 0.0), (-2.0, 0.0, 0.0),
                         (3.0, 0.0, 0.0), (4.0, 0.0, 0.0)], faces)
    created.append(crossed)
    add_shape_key(crossed, "Smile", [(0.0, 0.0, 0.0)] * 4)
    assign_uv_per_vertex(crossed, {i: (0.1 * i, 0.0) for i in range(4)})

    crossed_payload = payload_of(one_sided, "Smile", is_abs=False, value=1.0)
    crossed_mapping = ShapekeyPasteMatch.build_mapping(
        one_sided, crossed, crossed_payload, mode=UV)
    assert crossed_mapping.matched == 4 and crossed_mapping.unmatched == 0
    assert crossed_mapping.pairs[1] == [(1, 1.0)]

    # ---------- 引用失效：给出原因并退出 ----------
    reference = ShapekeyPasteMatch.resolve_source(payload)
    assert reference.ok is True and reference.obj == src

    renamed = make_object("MatchRenamed", LINE)
    created.append(renamed)
    add_shape_key(renamed, "Smile", DELTAS)
    renamed_payload = payload_of(renamed, "Smile", is_abs=False, value=1.0)
    renamed.name = "MatchRenamedAfterCopy"
    reference = ShapekeyPasteMatch.resolve_source(renamed_payload)
    assert reference.ok is False and "已不存在" in reference.reason

    # 源网格在复制后被改过（顶点数变了）：直接按 payload 模拟
    stale = dict(payload)
    stale["vertex_count"] = payload["vertex_count"] + 1
    reference = ShapekeyPasteMatch.resolve_source(stale)
    assert reference.ok is False and "顶点数已变化" in reference.reason

    doomed = make_object("MatchDoomed", LINE)
    created.append(doomed)
    add_shape_key(doomed, "Smile", DELTAS)
    doomed_payload = payload_of(doomed, "Smile", is_abs=False, value=1.0)
    bpy.data.objects.remove(doomed)
    created.remove(doomed)
    reference = ShapekeyPasteMatch.resolve_source(doomed_payload)
    assert reference.ok is False and "MatchDoomed" in reference.reason

    # 引用失效时算子什么都不写，并且返回 CANCELLED
    target = make_object("MatchAbortTarget", LINE)
    created.append(target)
    add_shape_key(target, "Smile", [(0.0, 0.0, 0.0)] * 4)
    before = key_positions(target, "Smile").copy()
    select_only(target)
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(doomed_payload))
    assert PASTE("EXEC_DEFAULT") == {'CANCELLED'}
    assert np.array_equal(key_positions(target, "Smile"), before)

    # 旧格式 + 点数不一致：保持旧行为的报警告不处理
    select_only(deleted)
    deleted_before = key_positions(deleted, "Smile").copy()
    ShapekeyPasteMatch.parse_payload = staticmethod(clipboard_with(DELTAS))
    assert PASTE("EXEC_DEFAULT") == {'CANCELLED'}
    assert np.array_equal(key_positions(deleted, "Smile"), deleted_before)

    # ---------- 弹窗绘制：后台开不了窗，但 draw() 本身必须能跑通 ----------
    mismatch_layout = draw_dialog(payload, [deleted])
    texts = mismatch_layout.texts()
    assert any("拓扑不一致" in text for text in texts), texts
    assert any("点序吻合" in text for text in texts), texts
    assert set(mismatch_layout.props()) == {"match_mode", "max_distance"}

    abort_layout = draw_dialog(doomed_payload, [target])
    abort_texts = abort_layout.texts()
    assert any("无法尽力匹配" in text for text in abort_texts), abort_texts
    assert any("粘贴已取消" in text for text in abort_texts), abort_texts
    # 引用失效那条分支不该画出可改的选项
    assert abort_layout.props() == []

    error_layout = draw_dialog(payload, [target], error="剪贴板数据解析失败")
    assert any("剪贴板数据解析失败" in text for text in error_layout.texts())

    # ---------- 基础校验的状态与旧实现一致 ----------
    not_mesh = bpy.data.objects.new("MatchEmpty", None)
    bpy.context.scene.collection.objects.link(not_mesh)
    created.append(not_mesh)
    replace_stub = stub_operator('replace', "已粘贴到")
    assert BASE.paste_to_object(replace_stub, not_mesh, [])[0] == 'skipped'

    no_keys = make_object("MatchNoKeys", LINE)
    created.append(no_keys)
    assert BASE.paste_to_object(replace_stub, no_keys, [])[1] == "没有 ShapeKey"

    add_shape_key(no_keys, "Smile", [(0.0, 0.0, 0.0)] * 4)
    no_keys.data.shape_keys.key_blocks["Smile"].value = 0.5
    status, message = BASE.paste_to_object(
        replace_stub, no_keys, [list(delta) for delta in DELTAS])
    assert status == 'warnings' and "Solo" in message

    # 叠加：只写映射里列出的点，其余保持原值
    no_keys.data.shape_keys.key_blocks["Smile"].value = 1.0
    add_stub = stub_operator('add', "已叠加到")
    before = key_positions(no_keys, "Smile").copy()
    status, _ = BASE.paste_to_object(
        add_stub, no_keys, [list(delta) for delta in DELTAS], {0: [(0, 1.0)]})
    assert status == 'success'
    after = key_positions(no_keys, "Smile")
    assert np.array_equal(after[0], expected_vertex(no_keys, 0, DELTAS[0]))
    assert np.array_equal(after[1:], before[1:])
finally:
    ShapekeyPasteMatch.parse_payload = original_parse
    module.ureg_props()
    for operator in reversed(registered):
        bpy.utils.unregister_class(operator)
    for obj in created:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass

print("SHAPEKEY_PASTE_MATCH_OK", bpy.app.version_string)
