"""「形态键 + 修改器」提示行（修改器面板顶部）的可见性回归测试（需要 Blender 后台运行）。

用户反馈的坑：这一行过去只在“存在视口可见的非形变修改器”时才画出来，于是
“形态键 + 骨架/波浪”这类只有形变修改器的物体两个应用入口都够不着——
Blender 原生「应用」按钮对带形态键的网格一律禁用（形变修改器也一样，报
“Modifier cannot be applied to a mesh with shape keys”），
本插件的「保持形态键应用」按钮又没被画出来。

本测试锁住绘制门控与按钮可用性：

  1. 可见的形变修改器（骨架/波浪/缩裹…）也要画出提示行，按钮可点；
  2. 可见的非形变修改器画出告警行（提示烘焙会重建拓扑）；
  3. 只有视口隐藏的修改器时不画（按钮语义是“应用视图显示中的修改器”）；
  4. 没有形态键、或只剩基型时不画；
  5. 只要画出这一行，按钮的 poll 就必须通过（不能画一个点不动的按钮）。
"""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ADDON_ROOT.parent
for _path in (str(ADDONS_DIR), str(ADDON_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ModifierTools 用 ..Checker / ..ShapekeyTools 这类包内相对导入，必须按包名导入。
modifier_tools = importlib.import_module(f"{ADDON_ROOT.name}.ModifierTools")

APPLY_KEEP_ID = modifier_tools.OP_applyShowingModifiersKeepShapekeys.bl_idname
FORCE_REMOVE_ID = modifier_tools.OP_ForceRemoveAll.bl_idname

DEFORM_LABEL = "形态键与形变修改器共存"
NON_DEFORM_LABEL = "形态键与非形变修改器共存"


class RecordingRow:
    """记录 label / operator 调用的假行，连带记下当时的 alert 状态。"""

    def __init__(self, owner):
        self.owner = owner
        self.alert = False

    def label(self, **kwargs):
        self.owner.labels.append((kwargs, self.alert))

    def operator(self, idname, **kwargs):
        self.owner.operators.append((idname, kwargs))
        return SimpleNamespace()


class RecordingLayout:
    def __init__(self):
        self.labels = []
        self.operators = []

    @property
    def row_count(self):
        return len(self.labels)

    def row(self, **_kwargs):
        return RecordingRow(self)


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def build_object(tag, modifiers, *, shape_keys=True, basis_only=False):
    """建一个网格；modifiers 是 (修改器类型, 是否视口可见) 序列。"""
    mesh = bpy.data.meshes.new(f"MeshData_{tag}")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    obj = bpy.data.objects.new(f"Mesh_{tag}", mesh)
    bpy.context.scene.collection.objects.link(obj)
    if shape_keys:
        obj.shape_key_add(name="Basis", from_mix=False)
        if not basis_only:
            obj.shape_key_add(name="Wide", from_mix=False)
    for modifier_type, visible in modifiers:
        modifier = obj.modifiers.new(name=modifier_type, type=modifier_type)
        modifier.show_viewport = visible
    activate(obj)
    return obj


def draw_row(obj):
    layout = RecordingLayout()
    modifier_tools._draw_shape_key_warning(layout, obj)
    return layout


def assert_drawn(obj, *, alert, label_text, icon):
    """画出提示行：文案/图标/告警态正确，且按钮真的可点。"""
    layout = draw_row(obj)
    assert layout.row_count == 1, f"{obj.name} 应当画出提示行，实际 {layout.row_count}"
    (label_kwargs, label_alert), = layout.labels
    assert label_kwargs["text"] == label_text, label_kwargs
    assert label_kwargs["icon"] == icon, label_kwargs
    assert label_alert is alert, f"告警态应为 {alert}，实际 {label_alert}"
    assert [idname for idname, _ in layout.operators] == [
        APPLY_KEEP_ID,
        FORCE_REMOVE_ID,
    ], layout.operators
    assert bpy.ops.ho.apply_showing_modifiers_keepshapekeys.poll(), (
        f"{obj.name} 画出了按钮，但按钮的 poll 不通过（会变成点不动的灰按钮）"
    )


def assert_not_drawn(obj, reason):
    layout = draw_row(obj)
    assert layout.row_count == 0, f"{obj.name} 不应画出提示行（{reason}）"
    assert layout.operators == []


bpy.utils.register_class(modifier_tools.OP_applyShowingModifiersKeepShapekeys)
try:
    # ── 1. 只有形变修改器：也要画出提示行，但不按告警提示 ────────────────────
    assert_drawn(
        build_object("armature_only", [("ARMATURE", True)]),
        alert=False,
        label_text=DEFORM_LABEL,
        icon="INFO",
    )
    assert_drawn(
        build_object(
            "deform_mix",
            [("WAVE", True), ("SHRINKWRAP", True), ("SIMPLE_DEFORM", True)],
        ),
        alert=False,
        label_text=DEFORM_LABEL,
        icon="INFO",
    )

    # ── 2. 有非形变修改器：告警行 ───────────────────────────────────────────
    assert_drawn(
        build_object("nodes_only", [("NODES", True)]),
        alert=True,
        label_text=NON_DEFORM_LABEL,
        icon="ERROR",
    )
    # 形变 + 非形变混在一起时，按更重的那一类提示
    assert_drawn(
        build_object("mixed", [("ARMATURE", True), ("SOLIDIFY", True)]),
        alert=True,
        label_text=NON_DEFORM_LABEL,
        icon="ERROR",
    )

    # ── 3. 只有视口隐藏的修改器：不画（按钮只应用视图显示中的修改器） ────────
    assert_not_drawn(
        build_object("hidden_only", [("WAVE", False), ("SOLIDIFY", False)]),
        "没有视口可见的修改器",
    )
    # 隐藏的非形变修改器也不再压过可见的形变修改器
    assert_drawn(
        build_object("hidden_solidify", [("WAVE", True), ("SOLIDIFY", False)]),
        alert=False,
        label_text=DEFORM_LABEL,
        icon="INFO",
    )

    # ── 4. 没有形态键 / 只剩基型：没有共存问题 ──────────────────────────────
    assert_not_drawn(
        build_object("no_keys", [("SOLIDIFY", True)], shape_keys=False),
        "网格没有形态键",
    )
    assert_not_drawn(
        build_object("basis_only", [("SOLIDIFY", True)], basis_only=True),
        "只剩基型，没有可保持的形变",
    )
    assert_not_drawn(
        build_object("no_modifiers", []),
        "没有修改器",
    )

    # ── 5. 常见修改器类型逐个过一遍：画出行就必须点得动 ─────────────────────
    for modifier_type in (
        "ARMATURE",
        "WAVE",
        "SIMPLE_DEFORM",
        "LAPLACIANSMOOTH",
        "SHRINKWRAP",
        "SOLIDIFY",
        "NODES",
    ):
        obj = build_object(f"poll_{modifier_type}", [(modifier_type, True)])
        assert draw_row(obj).row_count == 1, f"{modifier_type} 没有画出提示行"
        assert bpy.ops.ho.apply_showing_modifiers_keepshapekeys.poll(), (
            f"{modifier_type}：提示行画了按钮，poll 却不通过"
        )
finally:
    bpy.utils.unregister_class(modifier_tools.OP_applyShowingModifiersKeepShapekeys)

print("MODIFIER_SHAPEKEY_ROW_OK", bpy.app.version_string)
