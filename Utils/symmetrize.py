"""Mesh-side implementation used by the HoTools symmetrize operator."""

import bmesh
import bpy
from contextlib import contextmanager
from mathutils.kdtree import KDTree


def _element_center(element):
    if isinstance(element, bmesh.types.BMVert):
        return element.co.copy()
    if isinstance(element, bmesh.types.BMEdge):
        return (element.verts[0].co + element.verts[1].co) * 0.5
    return element.calc_center_median()


@contextmanager
def _revealed_geometry(objects, axis, threshold):
    """Include hidden geometry, then restore each side's visibility separately.

    Symmetrize replaces the destination topology. Surviving elements keep their
    exact flags; replacement elements use the nearest original element on their
    own side. A newly created side inherits the source side's visibility.
    """
    component = 'XYZ'.index(axis)

    def side(co):
        value = co[component]
        return 0 if abs(value) <= threshold else (1 if value > 0 else -1)

    snapshots = []
    try:
        for obj in objects:
            bm = bmesh.from_edit_mesh(obj.data)
            if not any(element.hide for elements in (bm.verts, bm.edges, bm.faces)
                       for element in elements):
                continue
            domains = []
            for elements in (bm.verts, bm.edges, bm.faces):
                original = {element: element.hide for element in elements}
                points = {-1: [], 0: [], 1: []}
                for element in elements:
                    co = _element_center(element)
                    points[side(co)].append((co, element.hide))
                trees = {}
                for sign, entries in points.items():
                    if not entries:
                        continue
                    tree = KDTree(len(entries))
                    for index, (co, hidden) in enumerate(entries):
                        tree.insert(co, index)
                    tree.balance()
                    trees[sign] = (tree, [hidden for co, hidden in entries])
                domains.append((original, trees))
            snapshots.append((obj, domains))
            for elements in (bm.faces, bm.edges, bm.verts):
                for element in elements:
                    element.hide = False
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        yield
    finally:
        for obj, domains in snapshots:
            bm = bmesh.from_edit_mesh(obj.data)
            for elements, (original, trees) in zip((bm.verts, bm.edges, bm.faces), domains):
                for element in elements:
                    hidden = original.get(element)
                    if hidden is None:
                        co = _element_center(element)
                        sign = side(co)
                        match = trees.get(sign)
                        if match is None:
                            co[component] *= -1
                            match = trees.get(-sign)
                        if match is None:
                            hidden = False
                        else:
                            tree, flags = match
                            _, index, _ = tree.find(co)
                            hidden = flags[index]
                    element.hide = hidden
                    if hidden:
                        element.select = False
            bmesh.update_edit_mesh(obj.data)


def _axis_value(vert, axis):
    return vert.co['XYZ'.index(axis)]


def _classify(verts, axis, direction, threshold):
    component = 'XYZ'.index(axis)
    original_sign = 1 if direction == 'POSITIVE' else -1
    original, mirror, center = [], [], []
    for vert in verts:
        value = vert.co[component]
        if abs(value) <= threshold:
            vert.co[component] = 0.0
            center.append(vert.index)
        elif value * original_sign > 0:
            original.append(vert.index)
        else:
            mirror.append(vert.index)
    return original, mirror, center


def _center_vertices(bm, axis, threshold, selected_only=False):
    component = 'XYZ'.index(axis)
    return {
        vert
        for vert in bm.verts
        if vert.is_valid
        and (not selected_only or vert.select)
        and abs(vert.co[component]) <= threshold
    }


def _clear_center_sharps(obj, axis, threshold, selected_only=False):
    bm = bmesh.from_edit_mesh(obj.data)
    center = _center_vertices(bm, axis, threshold, selected_only)
    if not center:
        return
    for edge in bm.edges:
        if edge.is_valid and all(vert in center for vert in edge.verts):
            edge.smooth = True
            edge.seam = False
    bmesh.update_edit_mesh(obj.data)


def _remove_vertices(obj, indices):
    if not indices:
        return
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    verts = [bm.verts[index] for index in indices if index < len(bm.verts)]
    if verts:
        bmesh.ops.delete(bm, geom=verts, context='VERTS')
        bmesh.update_edit_mesh(obj.data)


def _remove_redundant_center_edges(
    obj, axis, threshold, selected_only=False
):
    bm = bmesh.from_edit_mesh(obj.data)
    center = _center_vertices(bm, axis, threshold, selected_only)
    if not center:
        return
    edges = [
        edge for edge in bm.edges
        if edge.is_valid
        and edge.is_manifold
        and all(vert in center for vert in edge.verts)
        and abs(edge.calc_face_angle()) < 1e-5
    ]
    if edges:
        bmesh.ops.dissolve_edges(
            bm, edges=edges, use_verts=True, use_face_split=False
        )
        bmesh.update_edit_mesh(obj.data)


def symmetrize(
    obj,
    direction='POSITIVE_X',
    threshold=0.0001,
    partial=False,
    remove=False,
    remove_redundant_center=True,
    mirror_custom_normals=True,
    custom_normal_method='INDEX',
    fix_center=False,
    fix_center_method='CLEAR',
    clear_sharps=True,
    debug=False,
):
    """Apply Blender's symmetrize operation and return affected vertex IDs.

    The MESHmachine operator exposes custom-normal controls. Blender's native
    symmetrize already preserves regular and split normals, so those controls
    remain available for compatibility while center seam cleanup is handled in
    HoTools directly.
    """
    del mirror_custom_normals, custom_normal_method, fix_center_method, debug
    # Native mesh operators skip hidden elements, even after select_all(SELECT).
    # They also act on every mesh in multi-object Edit Mode, so reveal/restore
    # all those meshes together. Selected Only retains its visible-only scope.
    objects = [] if partial else [
        item for item in bpy.context.objects_in_mode_unique_data
        if item.type == 'MESH'
    ]
    with _revealed_geometry(objects, direction.split('_', 1)[1], threshold):
        return _symmetrize_mesh(
            obj, direction, threshold, partial, remove,
            remove_redundant_center, fix_center, clear_sharps,
        )


def _symmetrize_mesh(
    obj, direction, threshold, partial, remove,
    remove_redundant_center, fix_center, clear_sharps,
):
    direction_name, axis = direction.split('_', 1)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    selected = [vert for vert in bm.verts if vert.select]
    source = selected if partial else list(bm.verts)
    original, mirror, center = _classify(source, axis, direction_name, threshold)

    if remove:
        _remove_vertices(obj, mirror)
        if clear_sharps and fix_center:
            _clear_center_sharps(obj, axis, threshold, partial)
        return {
            'original': original,
            'mirror': mirror,
            'center': center,
            'custom_normal': False,
        }

    if not partial:
        bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.symmetrize(direction=direction, threshold=threshold)
    if not partial:
        bpy.ops.mesh.select_all(action='DESELECT')

    if remove_redundant_center:
        _remove_redundant_center_edges(obj, axis, threshold, partial)
    if fix_center and clear_sharps:
        _clear_center_sharps(obj, axis, threshold, partial)

    return {
        'original': original,
        'mirror': mirror,
        'center': center,
        'custom_normal': bool(getattr(obj.data, 'has_custom_normals', False)),
    }
