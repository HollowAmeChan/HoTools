import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from mathutils import Vector


_EPSILON = 1.0e-10


def _edit_mesh(context):
    obj = getattr(context, "active_object", None)
    if (obj is None or obj.type != 'MESH'
            or getattr(obj, "mode", None) != 'EDIT'):
        return None, None
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    return obj, bm


def _selected_vertices(bm):
    return {
        vert for vert in bm.verts
        if vert.is_valid and vert.select and not vert.hide
    }


def _mesh_select_mode(context):
    scene = getattr(context, "scene", None)
    tool_settings = getattr(scene, "tool_settings", None)
    mode = getattr(tool_settings, "mesh_select_mode", ())
    try:
        return tuple(mode)
    except TypeError:
        return ()


def _selected_edge_relax_domain(bm):
    """Return the vertices and anchors for an explicit edge selection.

    The selected edge graph, rather than Blender's propagated vertex flags,
    defines the domain.  Open-chain endpoints are fixed and branch junctions
    are fixed as well so that a branched selection has stable anchors.
    Closed loops have no endpoints, so all of their vertices remain movable.
    """
    selected_edges = [
        edge for edge in bm.edges
        if (edge.is_valid and edge.select and not edge.hide
                and all(vert.is_valid and not vert.hide for vert in edge.verts))
    ]
    if not selected_edges:
        return set(), set(), set(), selected_edges

    adjacency = {}
    for edge in selected_edges:
        first, second = edge.verts
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)

    selected = set(adjacency)
    surface_like = all(edge.link_faces for edge in selected_edges)
    fixed = {
        vertex for vertex, neighbors in adjacency.items()
        if len(neighbors) == 1 or (len(neighbors) > 2 and not surface_like)
    }
    # A branched or cyclic network with more edges than vertices represents a
    # surface-like region rather than one simple edge path.  Its perimeter is
    # the selected graph's contact with unselected topology (or the mesh
    # boundary), so keep those vertices as anchors as well.
    region_like = surface_like and (
        any(len(neighbors) > 2 for neighbors in adjacency.values())
        or len(selected_edges) > len(selected)
    )
    if region_like:
        selected_edge_set = set(selected_edges)
        for vertex in selected:
            for edge in vertex.link_edges:
                if not _usable_edge(edge):
                    continue
                other = edge.other_vert(vertex)
                if edge.is_boundary or edge not in selected_edge_set:
                    fixed.add(vertex)
                    break
    return selected, fixed, selected - fixed, selected_edges


def _selected_components(bm, selected):
    """按选中边将顶点划分为多个连通组。"""
    if not selected:
        return []

    selected_edges = [
        edge for edge in bm.edges
        if edge.is_valid and edge.select and not edge.hide
        and edge.verts[0] in selected and edge.verts[1] in selected
    ]
    if not selected_edges:
        return [sorted(selected, key=lambda vert: vert.index)]

    adjacency = {vert: set() for vert in selected}
    for edge in selected_edges:
        first, second = edge.verts
        adjacency[first].add(second)
        adjacency[second].add(first)

    remaining = set(selected)
    components = []
    while remaining:
        start = min(remaining, key=lambda vert: vert.index)
        stack = [start]
        remaining.remove(start)
        component = []
        while stack:
            vert = stack.pop()
            component.append(vert)
            for neighbor in adjacency[vert]:
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component, key=lambda vert: vert.index))
    return components


def _centroid(vertices):
    center = Vector((0.0, 0.0, 0.0))
    for vert in vertices:
        center += vert.co
    return center / len(vertices)


def _smallest_eigenvector(matrix):
    """Return the smallest-eigenvalue vector of a symmetric 3x3 matrix."""
    values = [row[:] for row in matrix]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]

    for _ in range(32):
        p, q = 0, 1
        largest = abs(values[p][q])
        for first in range(3):
            for second in range(first + 1, 3):
                if abs(values[first][second]) > largest:
                    p, q = first, second
                    largest = abs(values[first][second])
        if largest <= _EPSILON:
            break

        app = values[p][p]
        aqq = values[q][q]
        apq = values[p][q]
        tau = (aqq - app) / (2.0 * apq)
        sign = 1.0 if tau >= 0.0 else -1.0
        tangent = sign / (abs(tau) + math.sqrt(1.0 + tau * tau))
        cosine = 1.0 / math.sqrt(1.0 + tangent * tangent)
        sine = tangent * cosine

        values[p][p] = app - tangent * apq
        values[q][q] = aqq + tangent * apq
        values[p][q] = values[q][p] = 0.0
        for index in range(3):
            if index in (p, q):
                continue
            aip = values[index][p]
            aiq = values[index][q]
            values[index][p] = values[p][index] = cosine * aip - sine * aiq
            values[index][q] = values[q][index] = sine * aip + cosine * aiq

        for index in range(3):
            vip = vectors[index][p]
            viq = vectors[index][q]
            vectors[index][p] = cosine * vip - sine * viq
            vectors[index][q] = sine * vip + cosine * viq

    axis = min(range(3), key=lambda index: values[index][index])
    result = Vector((vectors[0][axis], vectors[1][axis], vectors[2][axis]))
    if result.length <= _EPSILON:
        return Vector((0.0, 0.0, 1.0))
    return result.normalized()


def _best_fit_plane(vertices):
    center = _centroid(vertices)
    covariance = [[0.0, 0.0, 0.0] for _ in range(3)]
    for vert in vertices:
        delta = vert.co - center
        for row in range(3):
            for column in range(3):
                covariance[row][column] += delta[row] * delta[column]
    normal = _smallest_eigenvector(covariance)
    return center, normal


def _plane_for_vertices(context, obj, vertices, plane):
    center = _centroid(vertices)
    if plane == 'NORMAL':
        normal = Vector((0.0, 0.0, 0.0))
        for vert in vertices:
            normal += vert.normal
        if normal.length <= _EPSILON:
            return _best_fit_plane(vertices)
        return center, normal.normalized()

    if plane == 'VIEW':
        space = getattr(context, "space_data", None)
        region_3d = getattr(space, "region_3d", None)
        view_matrix = getattr(region_3d, "view_matrix", None)
        if view_matrix is not None:
            world_normal = view_matrix.to_3x3().inverted() @ Vector((0.0, 0.0, 1.0))
            local_normal = obj.matrix_world.to_3x3().inverted().transposed() @ world_normal
            if local_normal.length > _EPSILON:
                return center, local_normal.normalized()

    return _best_fit_plane(vertices)


def _locked_target(old, target, lock_x, lock_y, lock_z, influence):
    target = target.copy()
    if lock_x:
        target.x = old.x
    if lock_y:
        target.y = old.y
    if lock_z:
        target.z = old.z
    return old.lerp(target, max(0.0, min(1.0, influence / 100.0)))


def _usable_edge(edge):
    # Non-manifold edges are not allowed to transmit a smoothing update.
    return edge.is_valid and not edge.hide and 0 < len(edge.link_faces) <= 2


def _relax_boundary(selected):
    """Find fixed Dirichlet vertices for a selected mesh patch."""
    fixed = set()
    for vert in selected:
        for edge in vert.link_edges:
            if not _usable_edge(edge):
                fixed.add(vert)
                break
            other = edge.other_vert(vert)
            if edge.is_boundary or other not in selected:
                fixed.add(vert)
                break
    return fixed


def _cotangent_at_opposite(vertex, first, second, positions):
    first_vector = positions[first] - positions[vertex]
    second_vector = positions[second] - positions[vertex]
    cross_length = first_vector.cross(second_vector).length
    if cross_length <= _EPSILON:
        return 0.0
    return first_vector.dot(second_vector) / cross_length


def _neighbor_weights(vertex, selected, positions, method, edge_subset=None):
    weights = []
    for edge in vertex.link_edges:
        if edge_subset is None:
            if not _usable_edge(edge):
                continue
        elif (edge not in edge_subset or not edge.is_valid or edge.hide
              or len(edge.link_faces) > 2):
            # Edge mode follows the selected edge graph.  Loose selected
            # edges are valid topology too; non-manifold edges remain blocked.
            continue
        neighbor = edge.other_vert(vertex)
        if neighbor not in selected:
            continue

        weight = 1.0
        if method == 'COTANGENT' and edge.link_faces:
            cotangent_sum = 0.0
            triangle_count = 0
            for face in edge.link_faces:
                if len(face.verts) != 3:
                    continue
                third = next(
                    (face_vert for face_vert in face.verts
                     if face_vert != vertex and face_vert != neighbor),
                    None,
                )
                if third is None:
                    continue
                cotangent_sum += _cotangent_at_opposite(
                    third, vertex, neighbor, positions)
                triangle_count += 1
            if triangle_count:
                # Negative cotangents destabilize an explicit smoother.  A
                # zero/obtuse edge falls back to the uniform umbrella weight.
                weight = max(0.0, cotangent_sum)
                if weight <= _EPSILON:
                    weight = 1.0
        weights.append((neighbor, weight))
    if weights and sum(weight for _neighbor, weight in weights) <= _EPSILON:
        return [(neighbor, 1.0) for neighbor, _weight in weights]
    return weights


def _face_normal(face, positions):
    vertices = list(face.verts)
    if len(vertices) < 3:
        return Vector((0.0, 0.0, 0.0))
    origin = positions[vertices[0]]
    normal = Vector((0.0, 0.0, 0.0))
    for index in range(1, len(vertices) - 1):
        normal += (
            positions[vertices[index]] - origin
        ).cross(positions[vertices[index + 1]] - origin)
    return normal


def _candidate_faces_are_valid(faces, old_positions, targets):
    new_positions = dict(old_positions)
    new_positions.update(targets)
    for face in faces:
        old_normal = _face_normal(face, old_positions)
        new_normal = _face_normal(face, new_positions)
        old_length = old_normal.length
        new_length = new_normal.length
        if old_length <= _EPSILON:
            continue
        if (new_length <= old_length * 1.0e-3
                or old_normal.dot(new_normal) <= 0.0):
            return False
    return True


def _laplacian_pass(
        bm, selected, movable, method, factor, edge_subset=None):
    affected_faces = set()
    old_positions = {vertex: vertex.co.copy() for vertex in selected}
    for vertex in movable:
        affected_faces.update(face for face in vertex.link_faces if face.is_valid)
    for face in affected_faces:
        for vertex in face.verts:
            old_positions.setdefault(vertex, vertex.co.copy())

    targets = {}
    for vertex in movable:
        weighted = Vector((0.0, 0.0, 0.0))
        total = 0.0
        for neighbor, weight in _neighbor_weights(
                vertex, selected, old_positions, method, edge_subset):
            weighted += old_positions[neighbor] * weight
            total += weight
        if total > _EPSILON:
            average = weighted / total
            targets[vertex] = old_positions[vertex].lerp(average, factor)
        else:
            targets[vertex] = old_positions[vertex].copy()

    if not _candidate_faces_are_valid(affected_faces, old_positions, targets):
        return False
    for vertex, position in targets.items():
        vertex.co = position
    return True


def _safe_laplacian_pass(
        bm, selected, movable, method, factor, edge_subset=None):
    trial = factor
    for _ in range(8):
        if _laplacian_pass(
                bm, selected, movable, method, trial, edge_subset):
            return True
        trial *= 0.5
    return False


def _component_edge_order(component):
    """按拓扑返回顶点顺序，并判断选中边是否组成闭合环。"""
    vertices = set(component)
    adjacency = {vertex: [] for vertex in vertices}
    for vertex in vertices:
        for edge in vertex.link_edges:
            if (edge.is_valid and edge.select and not edge.hide
                    and edge.verts[0] in vertices
                    and edge.verts[1] in vertices):
                adjacency[vertex].append(edge.other_vert(vertex))

    if not any(adjacency.values()):
        return sorted(component, key=lambda vertex: vertex.index), False

    degrees = [len(neighbors) for neighbors in adjacency.values()]
    is_chain = sum(degree == 1 for degree in degrees) == 2 and all(
        degree <= 2 for degree in degrees)
    is_loop = all(degree == 2 for degree in degrees)
    if not (is_chain or is_loop):
        return sorted(component, key=lambda vertex: vertex.index), False

    start = (min((vertex for vertex in vertices if len(adjacency[vertex]) == 1),
                 key=lambda vertex: vertex.index)
             if is_chain else min(vertices, key=lambda vertex: vertex.index))
    ordered = [start]
    previous = None
    current = start
    while True:
        candidates = [neighbor for neighbor in adjacency[current]
                      if neighbor is not previous]
        if not candidates:
            break
        next_vertex = min(candidates, key=lambda vertex: vertex.index)
        if next_vertex is start:
            break
        if next_vertex in ordered:
            return sorted(component, key=lambda vertex: vertex.index), False
        ordered.append(next_vertex)
        previous, current = current, next_vertex
    if len(ordered) != len(component):
        return sorted(component, key=lambda vertex: vertex.index), False
    return ordered, is_loop


def _solve_linear_3x3(matrix, values):
    """使用克拉默法则求解 3x3 线性方程组，避免引入额外依赖。"""
    determinant = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2]
                        - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2]
                          - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1]
                          - matrix[1][1] * matrix[2][0])
    )
    if abs(determinant) <= _EPSILON:
        return None
    result = []
    for column in range(3):
        replaced = [row[:] for row in matrix]
        for row in range(3):
            replaced[row][column] = values[row]
        result.append((
            replaced[0][0] * (replaced[1][1] * replaced[2][2]
                              - replaced[1][2] * replaced[2][1])
            - replaced[0][1] * (replaced[1][0] * replaced[2][2]
                                - replaced[1][2] * replaced[2][0])
            + replaced[0][2] * (replaced[1][0] * replaced[2][1]
                                - replaced[1][1] * replaced[2][0])
        ) / determinant)
    return result


def _circle_target_positions(context, obj, component, plane):
    """在拟合平面内求圆，并返回等间距的目标位置。"""
    center, normal = _plane_for_vertices(context, obj, component, plane)
    reference = (Vector((1.0, 0.0, 0.0))
                 if abs(normal.x) < 0.9 else Vector((0.0, 1.0, 0.0)))
    axis_u = normal.cross(reference)
    if axis_u.length <= _EPSILON:
        return None
    axis_u.normalize()
    axis_v = normal.cross(axis_u).normalized()
    points = [((vertex.co - center).dot(axis_u),
               (vertex.co - center).dot(axis_v)) for vertex in component]

    matrix = [[0.0, 0.0, 0.0] for _ in range(3)]
    rhs = [0.0, 0.0, 0.0]
    for x, y in points:
        row = (2.0 * x, 2.0 * y, 1.0)
        value = x * x + y * y
        for first in range(3):
            rhs[first] += row[first] * value
            for second in range(3):
                matrix[first][second] += row[first] * row[second]
    solution = _solve_linear_3x3(matrix, rhs)
    if solution is None:
        circle_x = circle_y = 0.0
        radius = sum(math.hypot(x, y) for x, y in points) / len(points)
    else:
        circle_x, circle_y, constant = solution
        radius = math.sqrt(max(0.0, constant + circle_x * circle_x
                               + circle_y * circle_y))
    if radius <= _EPSILON:
        return None

    ordered, closed = _component_edge_order(component)
    has_selected_edges = any(
        edge.is_valid and edge.select and not edge.hide
        and edge.verts[0] in component and edge.verts[1] in component
        for vertex in component for edge in vertex.link_edges
    )
    if not has_selected_edges:
        ordered = sorted(
            component,
            key=lambda vertex: math.atan2(
                (vertex.co - center).dot(axis_v) - circle_y,
                (vertex.co - center).dot(axis_u) - circle_x,
            ),
        )
        closed = True

    raw_angles = [math.atan2(
        (vertex.co - center).dot(axis_v) - circle_y,
        (vertex.co - center).dot(axis_u) - circle_x,
    ) for vertex in ordered]
    if closed:
        signed_area = 0.0
        for index, angle in enumerate(raw_angles):
            next_angle = raw_angles[(index + 1) % len(raw_angles)]
            signed_area += math.sin(next_angle - angle)
        direction = 1.0 if signed_area >= 0.0 else -1.0
        target_angles = [raw_angles[0] + direction * 2.0 * math.pi * index
                         / len(ordered) for index in range(len(ordered))]
    else:
        unwrapped = [raw_angles[0]]
        for angle in raw_angles[1:]:
            delta = (angle - unwrapped[-1] + math.pi) % (2.0 * math.pi) - math.pi
            unwrapped.append(unwrapped[-1] + delta)
        span = unwrapped[-1] - unwrapped[0]
        if abs(span) <= _EPSILON:
            span = 2.0 * math.pi
        target_angles = [unwrapped[0] + span * index / (len(ordered) - 1)
                         for index in range(len(ordered))]

    targets = {}
    circle_center = center + axis_u * circle_x + axis_v * circle_y
    for vertex, angle in zip(ordered, target_angles):
        targets[vertex] = circle_center + radius * (
            axis_u * math.cos(angle) + axis_v * math.sin(angle))
    return targets


class HO_OT_MeshCircleEven(bpy.types.Operator):
    """将选中顶点圆化，并保证顶点间距均匀。"""

    bl_idname = "ho.mesh_circle_even"
    bl_label = "均匀圆化"
    bl_description = "将选中顶点拟合为圆，并按等间距重新分布"
    bl_options = {'REGISTER', 'UNDO'}

    plane: EnumProperty(
        name="平面", items=(
            ('BEST_FIT', "最佳拟合", "根据选中顶点拟合平面"),
            ('NORMAL', "平均法线", "使用选中顶点的平均法线"),
            ('VIEW', "视图", "使用当前视图平面"),
        ), default='BEST_FIT',
    ) # type: ignore
    influence: FloatProperty(
        name="程度", default=100.0, min=0.0, max=100.0,
        subtype='PERCENTAGE',
        description="控制从原位置向均匀圆化结果的混合程度",
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return (obj is not None and obj.type == 'MESH'
                and getattr(context, "mode", None) == 'EDIT_MESH')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "plane")
        layout.prop(self, "influence")

    def execute(self, context):
        obj, bm = _edit_mesh(context)
        selected = _selected_vertices(bm) if bm is not None else set()
        if not selected:
            self.report({'WARNING'}, "请先选择要圆化的顶点")
            return {'CANCELLED'}

        moved = 0
        for component in _selected_components(bm, selected):
            if len(component) < 3:
                continue
            targets = _circle_target_positions(context, obj, component, self.plane)
            if targets is None:
                continue
            for vertex, target in targets.items():
                vertex.co = vertex.co.lerp(
                    target, max(0.0, min(1.0, self.influence / 100.0)),
                )
                moved += 1
        if not moved:
            self.report({'WARNING'}, "至少需要三个不共线的顶点")
            return {'CANCELLED'}
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        return {'FINISHED'}


class HO_OT_MeshFlatten(bpy.types.Operator):
    """Flatten selected vertices onto a fitted plane."""

    bl_idname = "ho.mesh_flatten"
    bl_label = "平化"
    bl_description = "将选中顶点投影到最佳拟合平面"
    bl_options = {'REGISTER', 'UNDO'}

    plane: EnumProperty(
        name="平面", items=(
            ('BEST_FIT', "最佳拟合", "根据选中顶点计算最佳拟合平面"),
            ('NORMAL', "平均法线", "使用选中顶点平均法线"),
            ('VIEW', "视图", "使用垂直于当前视图的平面"),
        ), default='BEST_FIT',
    ) # type: ignore
    influence: FloatProperty(
        name="影响", default=100.0, min=0.0, max=100.0,
        subtype='PERCENTAGE',
    ) # type: ignore
    lock_x: BoolProperty(name="锁定 X", default=False) # type: ignore
    lock_y: BoolProperty(name="锁定 Y", default=False) # type: ignore
    lock_z: BoolProperty(name="锁定 Z", default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return (
            obj is not None and obj.type == 'MESH'
            and getattr(context, "mode", None) == 'EDIT_MESH'
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "plane")
        layout.prop(self, "influence")
        row = layout.row(align=True)
        row.prop(self, "lock_x", text="X")
        row.prop(self, "lock_y", text="Y")
        row.prop(self, "lock_z", text="Z")

    def execute(self, context):
        obj, bm = _edit_mesh(context)
        selected = _selected_vertices(bm) if bm is not None else set()
        if not selected:
            self.report({'WARNING'}, "请先选择要平化的顶点")
            return {'CANCELLED'}

        moved = 0
        for component in _selected_components(bm, selected):
            if len(component) < 3:
                continue
            center, normal = _plane_for_vertices(
                context, obj, component, self.plane)
            for vertex in component:
                target = vertex.co - normal * (vertex.co - center).dot(normal)
                vertex.co = _locked_target(
                    vertex.co, target, self.lock_x, self.lock_y, self.lock_z,
                    self.influence,
                )
                moved += 1

        if not moved:
            self.report({'WARNING'}, "至少需要三个有效顶点")
            return {'CANCELLED'}
        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        return {'FINISHED'}


class HO_OT_MeshRelax(bpy.types.Operator):
    """Relax selected mesh patches or edge paths with fixed anchors."""

    bl_idname = "ho.mesh_relax"
    bl_label = "松弛"
    bl_description = "点、边、面模式统一使用 Laplacian 松弛，并固定选区边界"
    bl_options = {'REGISTER', 'UNDO'}

    iterations: IntProperty(name="迭代", default=3, min=1, max=100) # type: ignore
    strength: FloatProperty(
        name="强度", default=1.0, min=0.0, max=1.0,
        subtype='FACTOR',
    ) # type: ignore
    method: EnumProperty(
        name="权重", items=(
            ('UNIFORM', "均匀", "均匀邻域平均，适合任意多边形"),
            ('COTANGENT', "余切", "三角网格使用余切 Laplacian，其他面回退均匀权重"),
        ), default='COTANGENT',
    ) # type: ignore
    preserve_shape: BoolProperty(
        name="抑制收缩", default=False,
        description="使用 Taubin 反向步骤抑制普通 Laplacian 的整体收缩",
    ) # type: ignore

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return (
            obj is not None and obj.type == 'MESH'
            and getattr(context, "mode", None) == 'EDIT_MESH'
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "iterations")
        layout.prop(self, "strength")
        layout.prop(self, "method")
        layout.prop(self, "preserve_shape")
        layout.label(text="选区边界、网格边界和非流形点固定")

    def execute(self, context):
        obj, bm = _edit_mesh(context)
        edge_mode = _mesh_select_mode(context) == (False, True, False)
        edge_subset = None
        if edge_mode and bm is not None:
            selected, fixed, movable, edge_subset = _selected_edge_relax_domain(bm)
        else:
            selected = _selected_vertices(bm) if bm is not None else set()
            fixed = _relax_boundary(selected)
            movable = selected - fixed

        if not selected:
            self.report({"WARNING"}, "请先选择要松弛的边" if edge_mode
                        else "请先选择要松弛的顶点")
            return {'CANCELLED'}

        if not movable:
            if edge_mode:
                message = "选中的边没有可松弛的内部点"
            else:
                message = "选区没有可松弛的内部流形顶点"
            self.report({'WARNING'}, message)
            return {'CANCELLED'}

        factor = max(0.0, min(1.0, self.strength))
        reverse_factor = -min(0.95, factor * 1.06)
        for _iteration in range(self.iterations):
            _safe_laplacian_pass(
                bm, selected, movable, self.method, factor, edge_subset,
            )
            if self.preserve_shape and reverse_factor < 0.0:
                _safe_laplacian_pass(
                    bm, selected, movable, self.method, reverse_factor,
                    edge_subset,
                )

        bm.normal_update()
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
        return {'FINISHED'}


HO_MESH_CLASSES = (HO_OT_MeshFlatten, HO_OT_MeshRelax, HO_OT_MeshCircleEven)


__all__ = [
    "HO_OT_MeshFlatten", "HO_OT_MeshRelax", "HO_OT_MeshCircleEven",
    "HO_MESH_CLASSES",
]
