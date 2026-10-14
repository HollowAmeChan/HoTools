"""HoFBX 测试工具：把网格的“全部数据层”序列化成可比较的结构。

数据传递能传的东西覆盖四个域，任何一个域出问题都算“数据传递没做对”，所以测试不能
只看法线。这里把四个域都抓下来：

* 顶点：坐标、顶点组权重（按组名对齐）、点属性（顶点色/倒角权重等）
* 边：折痕、锐边、缝合、边属性
* 面拐：UV（按活动层 + 全部层名）、角点色、自定义法线
* 面：平滑、面属性

用法（在测试脚本里）::

    from _fbx_dt_testkit import mesh_state, diff_state, evaluated_state
"""

import math

import bpy
from mathutils import Vector

# 浮点比较容差：求值/复制本身会有 1e-6 量级的误差
EPS = 1e-4


def _round(value):
    return round(float(value), 5)


def _vec(value, dim=None):
    items = [_round(component) for component in value]
    if dim is not None:
        items = (items + [0.0] * dim)[:dim]
    return tuple(items)


def _point_attributes(mesh):
    """点域的自定义属性（排除 Blender 内部与位置）。"""
    out = {}
    for attribute in mesh.attributes:
        if attribute.domain != "POINT":
            continue
        if attribute.name.startswith(".") or attribute.name == "position":
            continue
        try:
            if attribute.data_type == "FLOAT":
                out[attribute.name] = [_round(item.value) for item in attribute.data]
            elif attribute.data_type in {"FLOAT_VECTOR", "FLOAT2"}:
                out[attribute.name] = [_vec(item.vector) for item in attribute.data]
            elif attribute.data_type in {"INT", "BOOLEAN"}:
                out[attribute.name] = [int(item.value) for item in attribute.data]
        except (AttributeError, TypeError):
            continue
    return out


def _edge_attributes(mesh):
    out = {}
    for attribute in mesh.attributes:
        if attribute.domain != "EDGE":
            continue
        if attribute.name.startswith("."):
            continue
        try:
            if attribute.data_type == "FLOAT":
                out[attribute.name] = [_round(item.value) for item in attribute.data]
            elif attribute.data_type in {"INT", "BOOLEAN"}:
                out[attribute.name] = [int(item.value) for item in attribute.data]
        except (AttributeError, TypeError):
            continue
    return out


def _face_attributes(mesh):
    out = {}
    for attribute in mesh.attributes:
        if attribute.domain != "FACE":
            continue
        if attribute.name.startswith("."):
            continue
        try:
            if attribute.data_type == "FLOAT":
                out[attribute.name] = [_round(item.value) for item in attribute.data]
            elif attribute.data_type in {"INT", "BOOLEAN"}:
                out[attribute.name] = [int(item.value) for item in attribute.data]
        except (AttributeError, TypeError):
            continue
    return out


def _vertex_group_weights_from_object(ob):
    """按“组名 → {顶点索引: 权重}”取物体上的权重，避免依赖组顺序。"""
    try:
        groups = {group.index: group.name for group in ob.vertex_groups}
        vertices = ob.data.vertices
    except (ReferenceError, AttributeError):
        return {}
    out = {}
    for vertex in vertices:
        for element in vertex.groups:
            name = groups.get(element.group)
            if name is None:
                continue
            if element.weight <= 1e-6:
                continue
            out.setdefault(name, {})[vertex.index] = _round(element.weight)
    return out


def vertex_group_weights(ob):
    """按“组名 → {顶点索引: 权重}”取权重（顶点组是物体级数据，从物体上读）。"""
    return _vertex_group_weights_from_object(ob)


def _custom_normals(mesh):
    try:
        return [_vec(normal.vector) for normal in mesh.corner_normals]
    except (AttributeError, RuntimeError):
        return None


def mesh_state(ob, *, with_vertex_groups=True):
    """把物体当前网格 + 顶点组序列化成可比较的字典。"""
    mesh = ob.data
    state = {
        "verts": [_vec(v.co) for v in mesh.vertices],
        "edges": [tuple(e.vertices) for e in mesh.edges],
        "polys": [tuple(p.vertices) for p in mesh.polygons],
        "loops": [tuple(loop.vertex_index for loop in mesh.loops)],
        "uv_layers": {},
        "color_attributes": {},
        "point_attributes": _point_attributes(mesh),
        "edge_attributes": _edge_attributes(mesh),
        "face_attributes": _face_attributes(mesh),
        "edge_flags": [
            (int(e.use_edge_sharp), int(e.use_seam)) for e in mesh.edges
        ],
        "face_smooth": [int(p.use_smooth) for p in mesh.polygons],
        "materials": [slot.material.name if slot.material else None
                      for slot in ob.material_slots],
        "custom_normals": _custom_normals(mesh),
        "uv_names": [layer.name for layer in mesh.uv_layers],
        "color_names": [attribute.name for attribute in mesh.color_attributes],
    }
    for layer in mesh.uv_layers:
        state["uv_layers"][layer.name] = [_vec(item.uv) for item in layer.data]
    for attribute in mesh.color_attributes:
        try:
            state["color_attributes"][attribute.name] = [
                _vec(item.color) for item in attribute.data
            ]
        except (AttributeError, TypeError):
            continue
    if with_vertex_groups:
        state["vertex_groups"] = _vertex_group_weights_from_object(ob)
    return state


def evaluated_state(ob, *, with_vertex_groups=True):
    """按 FBX 导出的口径（求值网格）取状态。

    顶点组是物体级数据，依赖图求值**不会**计算 DATA_TRANSFER 的权重组（实测求值物体的
    权重与基础网格一模一样），所以这里读的是物体当前网格上的权重：对“传递结果就是最终
    结果”的物体（传递之后没有改拓扑的修改器）它正好等于应得的权重；有后置修改器时
    顶点数对不上，调用方要用 :func:`vertex_groups_after_mirror` 自己推。
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = bpy.data.meshes.new_from_object(
        ob.evaluated_get(depsgraph),
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    probe = ob.copy()
    probe.data = evaluated
    try:
        state = mesh_state(probe, with_vertex_groups=False)
    finally:
        probe.data = None
        bpy.data.objects.remove(probe, do_unlink=True)
        if evaluated.users == 0:
            bpy.data.meshes.remove(evaluated)
    if with_vertex_groups:
        state["vertex_groups"] = _vertex_group_weights_from_object(ob)
    else:
        state["vertex_groups"] = {}
    return state


def vertex_groups_after_mirror(weights, vertex_count):
    """把“镜像修改器还有效”时的顶点组权重推出来。

    镜像会把每个顶点复制一份（前一半 = 原顶点，后一半 = 镜像顶点，按顶点序），权重与
    顶点组一起复制。传入 ``{组名: {顶点索引: 权重}}`` 与最终顶点数，返回展开后的权重。
    """
    half = vertex_count // 2
    out = {}
    for name, entries in (weights or {}).items():
        expanded = {}
        for index, weight in entries.items():
            if index < half:
                expanded[index] = weight
            if index + half < vertex_count:
                expanded[index + half] = weight
        if expanded:
            out[name] = expanded
    return out


def replace_vertex_groups(state, weights):
    """复制一份状态并替换其中的顶点组权重（用于构造精确的期望值）。"""
    clone = dict(state)
    clone["vertex_groups"] = weights
    return clone


def without_vertex_groups(state):
    """复制一份状态并去掉顶点组（顶点数会变的场景下没法逐索引比较）。"""
    clone = dict(state)
    clone.pop("vertex_groups", None)
    return clone



_TOPOLOGY_KEYS = {
    "verts", "edges", "polys", "loops",
    "point_attributes", "edge_attributes", "face_attributes",
    "edge_flags", "face_smooth", "custom_normals", "vertex_groups",
}
_EXACT_KEYS = {"materials", "uv_names", "color_names"}
_VALUE_KEYS = {"uv_layers", "color_attributes"}


def diff_state(expected, actual, *, tolerance=EPS, keys=None):
    """返回两个状态之间的差异描述列表（空列表 = 一致）。"""
    problems = []

    def compare_tuples(label, want, got, tol):
        if want is None and got is None:
            return
        if want is None or got is None:
            problems.append(f"{label}: 一边有数据一边没有（期望 {want is not None}，实际 {got is not None}）")
            return
        if len(want) != len(got):
            problems.append(f"{label}: 数量不一致（期望 {len(want)}，实际 {len(got)}）")
            return
        for index, (a, b) in enumerate(zip(want, got)):
            if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
                if len(a) != len(b):
                    problems.append(f"{label}[{index}]: 维度不一致 期望 {a} 实际 {b}")
                    break
                if any(abs(x - y) > tol for x, y in zip(a, b)):
                    problems.append(f"{label}[{index}]: 期望 {a} 实际 {b}")
                    break
            elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if abs(a - b) > tol:
                    problems.append(f"{label}[{index}]: 期望 {a} 实际 {b}")
                    break
            elif a != b:
                problems.append(f"{label}[{index}]: 期望 {a!r} 实际 {b!r}")
                break

    for key in (keys or list(expected)):
        want, got = expected.get(key), actual.get(key)
        if key in _EXACT_KEYS:
            if want != got:
                problems.append(f"{key}: 期望 {want} 实际 {got}")
            continue
        if key in _TOPOLOGY_KEYS:
            if key == "vertex_groups":
                if want != got:
                    names = set(want or {}) | set(got or {})
                    details = []
                    for name in sorted(names):
                        w = (want or {}).get(name, {})
                        g = (got or {}).get(name, {})
                        if w == g:
                            continue
                        details.append(
                            f"     组 {name}: 缺失 {sorted(set(w) - set(g))[:4]} "
                            f"多余 {sorted(set(g) - set(w))[:4]}"
                        )
                        common = set(w) & set(g)
                        bad = [i for i in sorted(common) if abs(w[i] - g[i]) > tolerance]
                        if bad:
                            details.append(
                                f"      权重不同 {bad[:4]}: "
                                f"{[(w[i], g[i]) for i in bad[:2]]}"
                            )
                    problems.append(f"{key}: 权重不一致\n" + "\n".join(details[:6]))
                continue
            compare_tuples(key, want, got, tolerance)
            continue
        if key in _VALUE_KEYS:
            if set(want or {}) != set(got or {}):
                problems.append(f"{key}: 层名不一致（期望 {sorted(want or {})} 实际 {sorted(got or {})}）")
                continue
            for name in want or {}:
                compare_tuples(f"{key}[{name}]", want[name], got[name], tolerance)
            continue
        if want != got:
            problems.append(f"{key}: 期望 {want} 实际 {got}")
    return problems


def normal_deviation(normals_a, normals_b):
    """两组法线的平均夹角（弧度）；长度不一致返回 None。"""
    if not normals_a or not normals_b or len(normals_a) != len(normals_b):
        return None
    total = count = 0
    for a, b in zip(normals_a, normals_b):
        va, vb = Vector(a), Vector(b)
        if va.length < 1e-9 or vb.length < 1e-9:
            continue
        total += va.angle(vb)
        count += 1
    return total / count if count else None


def degrees(radians):
    return None if radians is None else math.degrees(radians)
