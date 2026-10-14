"""UV topology and selection reads shared by mesh tools (4.5 and 5.x).

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


def selected_uv_edge_loops(bm, uv_layer, settings):
    """Real selected edge starts; do not infer edges from selected endpoints."""
    sync = settings.use_uv_select_sync
    precise = hasattr(bm, 'uv_select_sync_valid') and (not sync or bm.uv_select_sync_valid)
    result = set()
    for face in bm.faces:
        if face.hide or (not sync and not face.select):
            continue
        for loop in face.loops:
            selected = loop.uv_select_edge if precise else loop.edge.select if sync else loop[uv_layer].select_edge
            if selected and not loop.edge.hide:
                result.add(loop)
    return result


def _uv_face_orientations(faces, uv_layer):
    orientations = {}
    for face in faces:
        coordinates = [tuple(loop[uv_layer].uv) for loop in face.loops]
        origin = coordinates[0]
        orientations[face] = sum(
            (a[0]-origin[0])*(b[1]-origin[1])-(a[1]-origin[1])*(b[0]-origin[0])
            for a, b in zip(coordinates[1:], coordinates[2:]))
    return orientations


def _uv_edge_sides_match(a, b, uv_layer, limit_squared, orientations=None):
    a_next, b_next = a.link_loop_next, b.link_loop_next
    first, second = (b, b_next) if a.vert == b.vert else (b_next, b)
    if not ((a[uv_layer].uv-first[uv_layer].uv).length_squared <= limit_squared
            and (a_next[uv_layer].uv-second[uv_layer].uv).length_squared <= limit_squared):
        return False
    if orientations is not None:
        # Compare polygon orientation in the SAME directed edge frame, handling
        # even inconsistent mesh face winding.
        product = orientations[a.face]*orientations[b.face]
        same_side = product > 0 if a.vert == b.vert else product < 0
        if same_side:
            return False
    return True


def uv_boundary_edges(bm, uv_layer, epsilon=1e-7, split_overlaps=True):
    """Return every active-layer UV cut and surface border, ignoring selection.

    Compares BOTH endpoints by mesh vertex identity. Detects cuts even when their
    faces reconnect elsewhere in the same island. Existing seams do not affect
    detection. Loose edges have no UV face and are excluded. Non-manifold edges
    are boundaries if any radial face pair has a UV discontinuity/fold.
    """
    orientations = _uv_face_orientations(bm.faces, uv_layer) if split_overlaps else None
    limit_squared = epsilon*epsilon
    boundaries = []
    for edge in bm.edges:
        sides = tuple(edge.link_loops)
        if len(sides) == 1 or any(
                not _uv_edge_sides_match(a, b, uv_layer, limit_squared, orientations)
                for index, a in enumerate(sides) for b in sides[index+1:]):
            boundaries.append(edge)
    return boundaries


def collect_uv_islands(obj, bm, uv_layer, settings, epsilon=1e-7, visible_only=False, split_overlaps=False):
    """Find actual UV-contiguous face components, including invisible faces.

    By default invisible faces participate so whole-topology tools can detect
    incomplete islands. visible_only=True follows the editor's displayed scope,
    for everyday UV transforms that must work with partial mesh selections.
    Equal coordinates on unrelated geometry never join islands or UV vertices.
    split_overlaps=True cuts coincident shared edges whose faces fold onto the
    same UV side. It recovers stacked charts that Blender's linked selection
    intentionally joins without a winding delimiter, without moving coordinates.
    """
    bm.faces.index_update()
    faces = [face for face in bm.faces if not visible_only or (
        not face.hide and (settings.use_uv_select_sync or face.select))]
    orientations = _uv_face_orientations(faces, uv_layer) if split_overlaps else None
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
                if _uv_edge_sides_match(a, b, uv_layer, limit_squared, orientations):
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
