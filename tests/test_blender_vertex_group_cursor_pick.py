"""回归测试：快切顶点组的候选会不会被"骨架未应用变换"这类数据问题挡掉。

覆盖 OP_VertexGroupTools_Switch_VG_byCursor 的数据诊断：
- 骨骼与网格对齐时不给任何提示；
- 骨架的物体变换没有应用（缩放/旋转）时提示"骨骼与网格错位"；
- 网格上没有与该骨架骨骼同名的顶点组时提示"可能解析到了错误的骨架"；
- 常规情况下拾取仍然按光标位置选中最近的骨骼。
"""
import importlib
import math
import sys
import types
from pathlib import Path

import bpy
import gpu
from mathutils import Matrix, Vector


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

# 构造轻量包环境，避开根包注册副作用；后台 Blender 没有 GPU 上下文，
# VertexGroupTools 的类级 shader 与本测试无关，因此只在导入阶段替换。
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
_original_from_builtin = gpu.shader.from_builtin
gpu.shader.from_builtin = lambda _name: None
try:
    vertex_group_operators = importlib.import_module(
        "HoTools.VertexGroupTools.vertexGroupOperators"
    )
finally:
    gpu.shader.from_builtin = _original_from_builtin

switch_operator = vertex_group_operators.OP_VertexGroupTools_Switch_VG_byCursor


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_rig(name, bones):
    data = bpy.data.armatures.new(f"{name}Data")
    rig = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(rig)
    activate(rig)
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, head, tail in bones:
        edit_bone = data.edit_bones.new(bone_name)
        edit_bone.head = head
        edit_bone.tail = tail
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def make_mesh(name, vertices, groups, rig):
    """groups: {组名: [顶点索引]}，权重统一给 1.0。"""
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(vertices, [], [])
    mesh = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(mesh)
    for group_name, indices in groups.items():
        group = mesh.vertex_groups.new(name=group_name)
        if indices:
            group.add(list(indices), 1.0, "REPLACE")
    if rig is not None:
        modifier = mesh.modifiers.new("Armature", "ARMATURE")
        modifier.object = rig
    return mesh


# 与网格原始坐标对齐的骨骼链：Low 覆盖 z=0..1，High 覆盖 z=1..2。
rig = make_rig("CursorPickRig", [
    ("Low", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ("High", (0.0, 0.0, 1.0), (0.0, 0.0, 2.0)),
])
low_z = (0.2, 0.4, 0.6, 0.8)
high_z = (1.2, 1.4, 1.6, 1.8)
mesh = make_mesh(
    "CursorPickMesh",
    [(0.0, 0.0, z) for z in low_z + high_z],
    {"Low": range(0, len(low_z)), "High": range(len(low_z), len(low_z) + len(high_z))},
    rig,
)
activate(mesh)

assert switch_operator._find_rig(mesh) is rig

# 对齐时不能有任何提示。
assert switch_operator._vertex_group_name_mismatch(mesh, rig) is False
assert switch_operator._mesh_armature_misalignment(mesh, rig) is False
assert switch_operator._data_problem_hint(mesh, rig) is None

# 骨架的缩放没有应用：骨骼被缩到原点附近，和网格错位。
rig.scale = (0.01, 0.01, 0.01)
bpy.context.view_layer.update()
hint = switch_operator._data_problem_hint(mesh, rig)
assert hint is not None and "错位" in hint, hint
rig.scale = (1.0, 1.0, 1.0)
bpy.context.view_layer.update()
assert switch_operator._data_problem_hint(mesh, rig) is None

# 骨架的旋转没有应用：骨骼整体躺倒，同样错位。
rig.rotation_euler = (math.radians(90.0), 0.0, 0.0)
bpy.context.view_layer.update()
hint = switch_operator._data_problem_hint(mesh, rig)
assert hint is not None and "错位" in hint, hint
rig.rotation_euler = (0.0, 0.0, 0.0)
bpy.context.view_layer.update()
assert switch_operator._data_problem_hint(mesh, rig) is None

# 网格与骨架世界矩阵一致（网格是骨架的子级）时，骨架自身带缩放也不算错位。
scaled_mesh = make_mesh(
    "CursorPickScaledMesh",
    [(0.0, 0.0, z) for z in low_z + high_z],
    {"Low": range(0, len(low_z)), "High": range(len(low_z), len(low_z) + len(high_z))},
    rig,
)
scaled_mesh.parent = rig
scaled_mesh.matrix_parent_inverse = Matrix.Identity(4)
rig.scale = (0.01, 0.01, 0.01)
bpy.context.view_layer.update()
assert scaled_mesh.matrix_world.to_scale() == rig.matrix_world.to_scale()
assert switch_operator._data_problem_hint(scaled_mesh, rig) is None
rig.scale = (1.0, 1.0, 1.0)
bpy.context.view_layer.update()

# 网格上有顶点组，但没有一个和该骨架同名：解析到了错误的骨架。
mismatch_mesh = make_mesh(
    "CursorPickMismatchMesh",
    [(0.0, 0.0, z) for z in low_z + high_z],
    {"NotABone": range(0, len(low_z) + len(high_z))},
    rig,
)
activate(mismatch_mesh)
hint = switch_operator._data_problem_hint(mismatch_mesh, rig)
assert hint is not None and "同名的顶点组" in hint, hint

# 完全没有顶点组的静态网格（例如挂在骨架下的道具）不报"命名不一致"。
plain_mesh = make_mesh(
    "CursorPickPlainMesh",
    [(0.0, 0.0, z) for z in low_z + high_z],
    {},
    rig,
)
activate(plain_mesh)
assert switch_operator._vertex_group_name_mismatch(plain_mesh, rig) is False
assert switch_operator._data_problem_hint(plain_mesh, rig) is None

# 拾取本身仍然按光标位置工作（用假投影把 z 轴映射到屏幕 x 轴）。
projection_calls = []


def fake_project(_region, _rv3d, coord):
    projection_calls.append(tuple(coord))
    return Vector((coord.z * 100.0, coord.x * 100.0))


class _Picker:
    _MAX_PICK_DISTANCE_PX = switch_operator._MAX_PICK_DISTANCE_PX
    _TIE_BREAK_MARGIN_PX = switch_operator._TIE_BREAK_MARGIN_PX
    _distance_point_to_segment = staticmethod(switch_operator._distance_point_to_segment)


original_view3d_utils = vertex_group_operators.view3d_utils
vertex_group_operators.view3d_utils = types.SimpleNamespace(
    location_3d_to_region_2d=fake_project
)
try:
    activate(mesh)
    # Low 投影到 x=0..100，High 投影到 x=100..200。
    picked = switch_operator._pick_bone_from_mouse(
        _Picker(), mesh, rig, None, None, Vector((140.0, 0.0))
    )
    assert picked == "High", picked
    picked = switch_operator._pick_bone_from_mouse(
        _Picker(), mesh, rig, None, None, Vector((40.0, 0.0))
    )
    assert picked == "Low", picked
finally:
    vertex_group_operators.view3d_utils = original_view3d_utils

assert projection_calls, "假投影没有被调用，测试没有真正覆盖拾取路径"

print("VERTEX_GROUP_CURSOR_PICK_OK", bpy.app.version_string)
