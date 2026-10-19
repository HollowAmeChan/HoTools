"""Read-only quad plans followed by atomic direct UV coordinate writes."""

import bmesh

from Utils.mesh_uv import UVPoint
from Utils.uv_quad import quadrify_coordinates
from Utils.uv_topology import IslandTopology


def quadrify_island_plan(context, island, direction='KEEP', respect_pins=True, topology=None):
    if not island.complete:
        raise ValueError('岛隐藏或未完整显示')
    topology = topology if topology is not None else IslandTopology(island.coordinates, island.polygons)
    active_face = island.bm.faces.active
    if active_face in island.faces:
        seed = island.faces.index(active_face)
    else:
        center = tuple((min(p[a] for p in island.coordinates)+max(p[a] for p in island.coordinates))/2 for a in (0, 1))
        seed = min(range(len(island.faces)), key=lambda i: sum(
            (sum(island.coordinates[v][a] for v in island.polygons[i])/len(island.polygons[i])-center[a])**2
            for a in (0, 1)))
    active = context.active_object
    obj = active if active is not None and active.data == island.obj.data else island.obj
    basis = obj.matrix_world.to_3x3()
    vertices = [loops[0].vert for loops in island.vertex_loops]
    lengths = {edge: (basis @ (vertices[edge[1]].co-vertices[edge[0]].co)).length for edge in topology.edge_faces}
    pins = {v: island.coordinates[v] for v, loops in enumerate(island.vertex_loops)
            if respect_pins and any(loop[island.uv_layer].pin_uv for loop in loops)}
    coordinates = quadrify_coordinates(topology, lengths, seed, direction, pins)
    loop_keys = {loop: (face.index, corner) for face in island.faces for corner, loop in enumerate(face.loops)}
    keys = tuple(tuple(loop_keys[loop] for loop in loops) for loops in island.vertex_loops)
    # Store indices rather than loop wrappers across any legacy native unwrap.
    return island.obj, island.uv_layer.name, keys, coordinates


def quad_uv_points(plans):
    """Reacquire current BMesh owners after all native operators have finished."""
    points = []
    for obj, uv_name, keys, coordinates in plans:
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv.get(uv_name)
        if uv is None:
            raise ValueError('四边化目标 UV 层已不存在')
        for corners, coordinate in zip(keys, coordinates):
            loops = tuple(bm.faces[face_index].loops[corner] for face_index, corner in corners)
            points.append((UVPoint(obj, bm, uv, loops, tuple(loops[0][uv].uv)), coordinate))
    return points
