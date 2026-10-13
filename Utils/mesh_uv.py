"""UV topology and selection reads shared by edit-mode tools (4.5 and 5.x).

Reading never creates layers or flushes/changes selection. Loop references belong
to the current edit BMesh and must be discarded after mode or layer changes.
"""

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite

import bmesh

from .uv_math import align_points


@dataclass
class UVIsland:
    obj: object
    bm: object
    uv_layer: object
    faces: tuple
    coordinates: tuple
    polygons: tuple
    vertex_loops: tuple
    selected: bool
    complete: bool

    @property
    def key(self):
        return (self.obj.name, min(face.index for face in self.faces))


def iter_edit_uv_meshes(context):
    """Yield unique mesh datablocks with existing active UV layers only."""
    seen = set()
    for obj in sorted(context.objects_in_mode_unique_data, key=lambda item: item.name):
        if obj.type != 'MESH' or obj.mode != 'EDIT':
            continue
        key = obj.data.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is not None:
            yield obj, bm, uv


def selected_uv_loops(bm, uv_layer, settings):
    """Return selected visible corners without losing modern precise UV state.

    In edge mode return BOTH endpoints of selected UV edges, using actual edge
    selection rather than inventing edges between selected vertices.
    """
    sync = settings.use_uv_select_sync
    modern = hasattr(bm, 'uv_select_sync_valid')
    precise = modern and (not sync or bm.uv_select_sync_valid)
    result = set()
    if sync:
        modes = {name for name, enabled in zip(('VERTEX', 'EDGE', 'FACE'), settings.mesh_select_mode) if enabled}
    else:
        modes = {settings.uv_select_mode}
    if getattr(settings, 'use_uv_select_island', False) and (not sync or 'FACE' in modes):
        # Blender 5.x moved island selection out of the uv_select_mode enum.
        modes.add('ISLAND')
    for face in bm.faces:
        if face.hide or (not sync and not face.select):
            continue
        if precise:
            selected_face = face.uv_select
        elif sync:
            selected_face = face.select
        else:
            selected_face = 'FACE' in modes and all(item[uv_layer].select for item in face.loops)
        for loop in face.loops:
            if precise:
                vertex = loop.uv_select_vert
                edge = loop.uv_select_edge
            elif sync:
                vertex = loop.vert.select and not loop.vert.hide
                edge = loop.edge.select and not loop.edge.hide
            else:
                vertex = loop[uv_layer].select
                edge = loop[uv_layer].select_edge
            if ('VERTEX' in modes or 'ISLAND' in modes) and vertex:
                result.add(loop)
            if 'EDGE' in modes and edge:
                result.update((loop, loop.link_loop_next))
            if 'FACE' in modes and selected_face:
                result.update(face.loops)
    return result


def collect_uv_islands(obj, bm, uv_layer, settings, epsilon=1e-7):
    """Find actual UV-contiguous face components, including invisible faces.

    Invisible faces participate in topology so an incomplete island is detected
    and skipped, instead of silently treating its visible part as a full island.
    Equal coordinates on unrelated geometry never join islands or UV vertices.
    """
    bm.faces.index_update()
    faces = list(bm.faces)
    loops = [loop for face in faces for loop in face.loops]
    corner_parent = {loop: loop for loop in loops}
    face_parent = {face: face for face in faces}

    def find(parent, value):
        root = value
        while parent[root] != root:
            root = parent[root]
        while parent[value] != value:
            next_value = parent[value]
            parent[value] = root
            value = next_value
        return root

    def union(parent, a, b):
        parent[find(parent, b)] = find(parent, a)

    edge_loops = defaultdict(list)
    for loop in loops:
        edge_loops[loop.edge].append(loop)
    limit_squared = epsilon * epsilon
    for sides in edge_loops.values():
        for index, a in enumerate(sides):
            for b in sides[index + 1:]:
                a_next, b_next = a.link_loop_next, b.link_loop_next
                if a.vert == b.vert:
                    first, second = b, b_next
                else:
                    first, second = b_next, b
                if ((a[uv_layer].uv - first[uv_layer].uv).length_squared <= limit_squared
                        and (a_next[uv_layer].uv - second[uv_layer].uv).length_squared <= limit_squared):
                    union(face_parent, a.face, b.face)
                    union(corner_parent, a, first)
                    union(corner_parent, a_next, second)

    components = defaultdict(list)
    for face in faces:
        components[find(face_parent, face)].append(face)
    selected = selected_uv_loops(bm, uv_layer, settings)
    result = []
    for component in components.values():
        component.sort(key=lambda face: face.index)
        nodes, vertex_loops, polygons = {}, [], []
        for face in component:
            polygon = []
            for loop in face.loops:
                root = find(corner_parent, loop)
                if root not in nodes:
                    nodes[root] = len(nodes)
                    vertex_loops.append([])
                node = nodes[root]
                vertex_loops[node].append(loop)
                polygon.append(node)
            polygons.append(tuple(polygon))
        result.append(UVIsland(
            obj, bm, uv_layer, tuple(component),
            tuple(tuple(items[0][uv_layer].uv) for items in vertex_loops),
            tuple(polygons), tuple(tuple(items) for items in vertex_loops),
            any(loop in selected for face in component for loop in face.loops),
            all(not face.hide and (settings.use_uv_select_sync or face.select) for face in component),
        ))
    return sorted(result, key=lambda island: island.key)


@dataclass
class UVPoint:
    obj: object
    bm: object  # keep the Python BMesh owner alive while corner wrappers are used
    uv_layer: object
    loops: tuple
    coordinate: tuple


def uv_edit_poll(context):
    return (context.mode == 'EDIT_MESH'
            and getattr(context.area, 'type', None) == 'IMAGE_EDITOR'
            and getattr(context.area, 'ui_type', None) == 'UV'
            and context.active_object is not None
            and context.active_object.type == 'MESH')


def selected_uv_point_groups(context, per_island=False):
    """Unique topological UV points, writing only the selected visible corners.

    Statistics give each UV vertex one vote, irrespective of face valence. Unlike
    whole-island tools, point transforms can operate on partially visible islands.
    """
    groups = []
    settings = context.scene.tool_settings
    for obj, bm, uv in iter_edit_uv_meshes(context):
        selected = selected_uv_loops(bm, uv, settings)
        if not selected:
            continue
        for island in collect_uv_islands(obj, bm, uv, settings):
            points = []
            for loops in island.vertex_loops:
                visible = tuple(loop for loop in loops if loop in selected)
                if visible:
                    points.append(UVPoint(obj, bm, uv, visible, tuple(visible[0][uv].uv)))
            if points:
                groups.append(points)
    if not groups:
        raise ValueError('没有选中的可见 UV，或编辑网格缺少活动 UV 层')
    return groups if per_island else [[point for group in groups for point in group]]


def write_uv_points(plans):
    """Validate a list of (UVPoint, coordinate), then write/update atomically.

    Leaves selection, pin, seam and topology untouched. Returns changed corners.
    Saves every actual corner for exact rollback, including near-equal UV points.
    """
    plans = list(plans)
    for _, coordinate in plans:
        if len(coordinate) != 2 or not all(isfinite(value) for value in coordinate):
            raise ValueError('UV 计算结果包含无效坐标')
        if any(abs(value) > 3.4028234663852886e38 for value in coordinate):
            raise ValueError('UV 计算结果超出 Blender 浮点坐标范围')
    original, meshes = [], {}
    try:
        for point, coordinate in plans:
            for loop in point.loops:
                old = tuple(loop[point.uv_layer].uv)
                if old == tuple(coordinate):
                    continue
                original.append((loop, point.uv_layer, old))
                meshes[point.obj.data.as_pointer()] = point.obj.data
                loop[point.uv_layer].uv = coordinate
        for mesh in meshes.values():
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    except Exception:
        for loop, uv, coordinate in original:
            loop[uv].uv = coordinate
        for mesh in meshes.values():
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        raise
    return len(original)


def align_uv_selection(context, axis, method, per_island=False):
    axis_index = {'U': 0, 'V': 1}[axis]
    cursor = context.space_data.cursor_location[axis_index] if method == 'CURSOR' else None
    plans = []
    for group in selected_uv_point_groups(context, per_island):
        result = align_points([point.coordinate for point in group], axis_index, method, cursor)
        plans.extend(zip(group, result))
    return write_uv_points(plans)
