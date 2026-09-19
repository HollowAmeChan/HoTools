"""「保持形态键应用修改器」按钮回归测试（需要 Blender 后台运行）。

这条路径与 FBX 导出前的隐式烘焙共用
``Utils.shapekey_utils.bake_modifiers_keeping_shape_keys``，本测试锁住按钮侧语义：

  1. 就地完成：物体身份/名称不变，不新建也不删除任何物体（旧实现会删原物体、用副本顶替）；
  2. 形态键全部保留，且名称、顺序、相对键、取值、mute 都按原样（含自定义基型名）；
  3. 视图显示中（show_viewport）的修改器被应用掉，视口隐藏的修改器保留；
  4. 骨架修改器按按钮语义一并烘焙；
  5. 拓扑依赖形态键（各键求值后顶点数不一致）时报错取消且不改动网格；
  6. 网格数据被多个物体共用时跳过并报错，不做就地替换。
"""

import sys
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from ShapekeyTools import operators as shapekey_operators


BASIS_NAME = "基型"
KEY_NAME = "Wide"


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_gn_group(name):
    """建一个改变拓扑的几何节点组（细分一级）。"""
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


def build_object(tag, *, with_armature=True, hidden_modifier=True, with_gn=True):
    armature = None
    if with_armature:
        armature = bpy.data.objects.new(f"Rig_{tag}", bpy.data.armatures.new(f"RigData_{tag}"))
        bpy.context.scene.collection.objects.link(armature)
        activate(armature)
        bpy.ops.object.mode_set(mode="EDIT")
        bone = armature.data.edit_bones.new("Bone")
        bone.head, bone.tail = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        bpy.ops.object.mode_set(mode="OBJECT")

    mesh = bpy.data.meshes.new(f"MeshData_{tag}")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    ob = bpy.data.objects.new(f"Mesh_{tag}", mesh)
    bpy.context.scene.collection.objects.link(ob)

    if armature is not None:
        group = ob.vertex_groups.new(name="Bone")
        group.add([0, 1, 2, 3], 1.0, "REPLACE")
        armature_modifier = ob.modifiers.new("Armature", "ARMATURE")
        armature_modifier.object = armature

    ob.shape_key_add(name=BASIS_NAME, from_mix=False)
    wide = ob.shape_key_add(name=KEY_NAME, from_mix=False)
    wide.data[1].co.x = 2.0
    wide.relative_key = ob.data.shape_keys.key_blocks[BASIS_NAME]
    wide.value = 0.35

    gn = ob.modifiers.new("GN", "NODES")
    gn.node_group = make_gn_group(f"GNGroup_{tag}")
    if not with_gn:
        ob.modifiers.remove(gn)

    if hidden_modifier:
        hidden = ob.modifiers.new("HiddenGN", "NODES")
        hidden.node_group = make_gn_group(f"HiddenGNGroup_{tag}")
        hidden.show_viewport = False
        hidden.show_render = True

    return armature, ob


def run_button():
    """点按钮：ERROR 报告在 Python 侧会转成 RuntimeError，等价于取消。"""
    try:
        return bpy.ops.ho.apply_showing_modifiers_keepshapekeys("EXEC_DEFAULT")
    except RuntimeError as error:
        print(f"[预期取消] {error}")
        return {"CANCELLED"}


bpy.utils.register_class(shapekey_operators.OP_applyShowingModifiersKeepShapekeys)
try:
    # ── 1. 就地应用：身份/名称不变，形态键与设置原样保留 ─────────────────────
    armature, ob = build_object("apply")
    activate(ob)
    object_count_before = len(bpy.data.objects)
    evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    expected_vertices = len(evaluated.data.vertices)
    assert expected_vertices > 4, "测试场景的几何节点应当增加顶点"

    assert run_button() == {"FINISHED"}

    # 就地修改：同一个物体、同一个名字，没有临时物体残留
    assert bpy.data.objects.get(ob.name) == ob, "物体身份被替换了（旧实现会删原物体）"
    assert len(bpy.data.objects) == object_count_before, "不应残留临时物体"

    # 形态键：名称（含自定义基型名）、顺序、相对键、取值全部保留
    shape_keys = ob.data.shape_keys
    assert shape_keys is not None, "形态键丢了"
    assert [key.name for key in shape_keys.key_blocks] == [BASIS_NAME, KEY_NAME]
    wide = shape_keys.key_blocks[KEY_NAME]
    assert wide.relative_key.name == BASIS_NAME
    assert abs(wide.value - 0.35) < 1e-6, "形态键取值没保留"
    assert len(ob.data.vertices) == expected_vertices, "修改器结果没有进入基础网格"

    # 修改器：视图显示中的（含骨架）都被应用掉，视口隐藏的保留
    assert [modifier.name for modifier in ob.modifiers] == ["HiddenGN"], (
        [modifier.name for modifier in ob.modifiers]
    )
    assert ob.modifiers["HiddenGN"].show_viewport is False

    # 形态键形变仍在：Wide 与基型的顶点位置不同
    basis_key = shape_keys.key_blocks[BASIS_NAME]
    delta = max(
        abs(basis_key.data[i].co.x - wide.data[i].co.x)
        for i in range(len(basis_key.data))
    )
    assert delta > 0.1, "应用修改器后形态键形变丢失"

    # ── 2. 拓扑依赖形态键：报错取消，且网格不被改动 ──────────────────────────
    # 用“按距离合并”（Weld）造出拓扑依赖：基型里 0/1 两点相距 1.0 会被合并，
    # 而 Wide 键把 1 号点移到 x=2 后不再合并，于是两个键求值后的顶点数不同。
    _armature_bad, ob_bad = build_object(
        "bad", with_armature=False, hidden_modifier=False, with_gn=False
    )
    activate(ob_bad)
    weld = ob_bad.modifiers.new("Weld", "WELD")
    weld.merge_threshold = 1.5

    vertices_before = len(ob_bad.data.vertices)
    keys_before = [key.name for key in ob_bad.data.shape_keys.key_blocks]
    assert run_button() == {"CANCELLED"}
    assert len(ob_bad.data.vertices) == vertices_before, "取消时不应改动网格"
    assert [key.name for key in ob_bad.data.shape_keys.key_blocks] == keys_before
    assert [modifier.name for modifier in ob_bad.modifiers] == ["Weld"]
    assert ob_bad.data.shape_keys.key_blocks[KEY_NAME].data[1].co.x == 2.0

    # ── 3. 网格数据被共用：跳过并报错，不做就地替换 ──────────────────────────
    armature_shared, ob_shared = build_object("shared")
    other = ob_shared.copy()
    other.name = "Mesh_shared_copy"
    bpy.context.scene.collection.objects.link(other)
    assert ob_shared.data.users > 1
    activate(ob_shared)
    assert run_button() == {"CANCELLED"}
    assert len(ob_shared.modifiers) == 3, "被共用时不应烘焙修改器"
    assert ob_shared.data.shape_keys is not None

    # ── 4. 实体化修改器（点数翻倍）：形态键与形变都要保留 ────────────────────
    # 回归：曾经用“改 value 再求值”的做法，遇到实体化/静音键/驱动器会取到基型，
    # 表现就是应用完之后形态键形变全平。
    _armature_solid, ob_solid = build_object(
        "solidify", with_armature=False, hidden_modifier=False, with_gn=False
    )
    solidify = ob_solid.modifiers.new("Solidify", "SOLIDIFY")
    solidify.thickness = 0.2
    activate(ob_solid)
    assert run_button() == {"FINISHED"}
    assert len(ob_solid.data.vertices) == 8, "实体化应当让顶点翻倍"
    assert [key.name for key in ob_solid.data.shape_keys.key_blocks] == [BASIS_NAME, KEY_NAME]
    assert [modifier.name for modifier in ob_solid.modifiers] == []
    key_delta = max(
        abs(
            ob_solid.data.shape_keys.key_blocks[BASIS_NAME].data[i].co.x
            - ob_solid.data.shape_keys.key_blocks[KEY_NAME].data[i].co.x
        )
        for i in range(len(ob_solid.data.vertices))
    )
    assert key_delta > 0.1, f"实体化后形态键形变丢失（最大差异 {key_delta}）"

    # ── 5. 被静音的形态键：也要取到它自己的形状 ──────────────────────────────
    _armature_mute, ob_mute = build_object(
        "muted", with_armature=False, hidden_modifier=False, with_gn=False
    )
    mute_solidify = ob_mute.modifiers.new("Solidify", "SOLIDIFY")
    mute_solidify.thickness = 0.2
    ob_mute.data.shape_keys.key_blocks[KEY_NAME].mute = True
    activate(ob_mute)
    assert run_button() == {"FINISHED"}
    muted_delta = max(
        abs(
            ob_mute.data.shape_keys.key_blocks[BASIS_NAME].data[i].co.x
            - ob_mute.data.shape_keys.key_blocks[KEY_NAME].data[i].co.x
        )
        for i in range(len(ob_mute.data.vertices))
    )
    assert muted_delta > 0.1, f"静音的形态键被抹平了（最大差异 {muted_delta}）"
    assert ob_mute.data.shape_keys.key_blocks[KEY_NAME].mute is True, "静音状态应当保留"

    # ── 6. 形态键数值被驱动器驱动：同样要取到该键自己的形状 ──────────────────
    _armature_drv, ob_drv = build_object(
        "driven", with_armature=False, hidden_modifier=False, with_gn=False
    )
    drv_solidify = ob_drv.modifiers.new("Solidify", "SOLIDIFY")
    drv_solidify.thickness = 0.2
    driver_curve = ob_drv.data.shape_keys.key_blocks[KEY_NAME].driver_add("value")
    driver_curve.driver.type = "SCRIPTED"
    driver_curve.driver.expression = "0.0"
    bpy.context.view_layer.update()
    activate(ob_drv)
    assert run_button() == {"FINISHED"}
    driven_delta = max(
        abs(
            ob_drv.data.shape_keys.key_blocks[BASIS_NAME].data[i].co.x
            - ob_drv.data.shape_keys.key_blocks[KEY_NAME].data[i].co.x
        )
        for i in range(len(ob_drv.data.vertices))
    )
    assert driven_delta > 0.1, f"被驱动器驱动的形态键被抹平了（最大差异 {driven_delta}）"
finally:
    bpy.utils.unregister_class(shapekey_operators.OP_applyShowingModifiersKeepShapekeys)

print("SHAPEKEY_APPLY_KEEP_OK", bpy.app.version_string)
