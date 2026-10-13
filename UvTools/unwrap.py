"""Pinned line unwrap with a temporary state transaction and orientation guard."""

from math import hypot, isfinite

import bmesh
import bpy

from Utils.mesh_uv import UVPoint, write_uv_points
from Utils.uv_chains import ensure_orientation_anchor, ensure_region_anchors, line_constraints
from Utils.uv_state import UVSceneState


def _unwrap(method):
    result = bpy.ops.uv.unwrap(method=method, margin=0, correct_aspect=False, fill_holes=True)
    if result != {'FINISHED'}:
        raise ValueError('Blender 展开没有完成')


def _area(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _validate(before, after, triangles, constraints):
    if any(not all(isfinite(value) for value in point) for point in after):
        raise ValueError('展开产生无效 UV 坐标')
    scale = max(hypot(p[0]-before[0][0], p[1]-before[0][1]) for p in before)
    tolerance = max(scale*2e-6, 1e-8)
    for vertex, point in constraints.items():
        if hypot(after[vertex][0]-point[0], after[vertex][1]-point[1]) > tolerance:
            raise ValueError('展开未保持直线或固定点约束')
    for triangle in triangles:
        old = _area(*(before[v] for v in triangle))
        new = _area(*(after[v] for v in triangle))
        if abs(old) <= max(scale*scale*1e-12, 1e-24):
            raise ValueError('原 UV 存在退化三角形，无法确定朝向')
        if old*new <= 0 or abs(new) <= max(scale*scale*1e-12, 1e-24):
            raise ValueError('展开产生局部翻面或退化，已恢复该岛')


def _prepare(context, scene_state, target, keys, frame, constraints):
    settings = context.scene.tool_settings
    settings.use_uv_select_sync = False
    settings.uv_select_mode = 'VERTEX'
    if hasattr(settings, 'use_uv_select_island'):
        settings.use_uv_select_island = False
    target_faces = {face for vertex in keys for face, corner in vertex}
    coordinate_by_corner = {key: frame[v] for v, vertex in enumerate(keys) for key in vertex}
    pinned_corners = {key for v in constraints for key in keys[v]}
    for saved in scene_state.meshes:
        obj = saved['obj']
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv.get(saved['uv_name']) if saved['uv_name'] else None
        is_target = obj.data == target.obj.data
        for v in bm.verts:
            v.select = False
        for e in bm.edges:
            e.select = False
        for f in bm.faces:
            f.select = False
        if is_target:
            for index in target_faces:
                bm.faces[index].select_set(True)
        modern = hasattr(bm, 'uv_select_sync_valid')
        if uv is not None:
            if modern:
                bm.uv_select_sync_from_mesh()
            for face in bm.faces:
                selected = is_target and face.index in target_faces
                if modern:
                    face.uv_select_set(selected)
                for corner, loop in enumerate(face.loops):
                    if modern:
                        loop.uv_select_vert_set(selected)
                        loop.uv_select_edge_set(selected)
                    else:
                        loop[uv].select = selected
                        loop[uv].select_edge = selected
                    if selected:
                        key = face.index, corner
                        loop[uv].uv = coordinate_by_corner[key]
                        loop[uv].pin_uv = key in pinned_corners
            if is_target:
                # Respect actual UV island boundaries, not preexisting seam flags.
                for edge in bm.edges:
                    attached = [face for face in edge.link_faces if face.index in target_faces]
                    if attached:
                        edge.seam = len(attached) != 2
                for vertex, point in constraints.items():
                    for face_index, corner in keys[vertex]:
                        bm.faces[face_index].loops[corner][uv].uv = point
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


def _descriptor(island, chains, direction, respect_pins, preserve_lengths):
    if not island.complete:
        raise ValueError('岛隐藏或未完整显示')
    loop_keys = {loop: (face.index, corner) for face in island.faces for corner, loop in enumerate(face.loops)}
    keys = tuple(tuple(loop_keys[loop] for loop in loops) for loops in island.vertex_loops)
    loop_node = {loop: v for v, loops in enumerate(island.vertex_loops) for loop in loops}
    face_set = set(island.faces)
    triangles = tuple(tuple(loop_node[l] for l in triangle) for triangle in island.bm.calc_loop_triangles()
                      if triangle[0].face in face_set)
    frame, constraints = line_constraints(island.coordinates, chains, direction, preserve_lengths)
    if respect_pins:
        scale = max(hypot(p[0]-frame[0][0], p[1]-frame[0][1]) for p in frame)
        for vertex, loops in enumerate(island.vertex_loops):
            if not any(loop[island.uv_layer].pin_uv for loop in loops):
                continue
            point = island.coordinates[vertex]
            if vertex in constraints and hypot(point[0]-constraints[vertex][0], point[1]-constraints[vertex][1]) > max(scale*1e-6, 1e-8):
                raise ValueError('原固定点与直线目标冲突；可取消尊重原固定点')
            constraints[vertex] = point
    constraints = ensure_orientation_anchor(frame, constraints)
    constraints = ensure_region_anchors(frame, constraints, island.polygons, chains)
    if any(not isfinite(value) or abs(value) > 3.4028234663852886e38
           for point in tuple(frame)+tuple(constraints.values()) for value in point):
        raise ValueError('直线约束超出 Blender 浮点坐标范围')
    return keys, triangles, frame, constraints


def unwrap_line_islands(context, requests, method='ANGLE_BASED', direction='AUTO',
                        respect_pins=True, preserve_lengths=True):
    """Solve requests independently; failed islands roll back, successes commit.

    Each request is (UVIsland, ordered chains). Returns (island_count, failures).
    All temporary user state is restored even if native unwrap raises.
    """
    prepared, failures = [], []
    for island, chains in requests:
        try:
            prepared.append((island, island.key, island.uv_layer.name,
                             _descriptor(island, chains, direction, respect_pins, preserve_lengths)))
        except ValueError as exc:
            failures.append((island.key, str(exc)))
    if not prepared:
        return 0, failures
    scene_state = UVSceneState(context)
    accepted = []
    try:
        for island, island_key, uv_name, (keys, triangles, frame, constraints) in prepared:
            try:
                _prepare(context, scene_state, island, keys, frame, constraints)
                with context.temp_override(object=island.obj, active_object=island.obj):
                    _unwrap(method)
                bm = bmesh.from_edit_mesh(island.obj.data)
                bm.faces.ensure_lookup_table()
                uv = bm.loops.layers.uv.get(uv_name)
                after = tuple(tuple(bm.faces[group[0][0]].loops[group[0][1]][uv].uv) for group in keys)
                _validate(island.coordinates, after, triangles, constraints)
                for vertex, corners in enumerate(keys):
                    for face_index, corner in corners:
                        point = bm.faces[face_index].loops[corner][uv].uv
                        if hypot(point.x-after[vertex][0], point.y-after[vertex][1]) > 1e-6:
                            raise ValueError('展开意外拆开岛内的共享 UV 点')
                accepted.append((island.obj, uv.name, keys, after))
            except (ValueError, RuntimeError) as exc:
                failures.append((island_key, str(exc)))
            finally:
                scene_state.restore()
    finally:
        scene_state.restore()
    plans = []
    for obj, uv_name, keys, coordinates in accepted:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv.get(uv_name)
        for corners, coordinate in zip(keys, coordinates):
            loops = tuple(bm.faces[face_index].loops[corner] for face_index, corner in corners)
            plans.append((UVPoint(obj, bm, uv, loops, tuple(loops[0][uv].uv)), coordinate))
    write_uv_points(plans)
    return len(accepted), failures
