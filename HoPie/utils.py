import bmesh
import bpy
from mathutils import Matrix, Vector


def average_locations(locations):
    locations = list(locations)
    return sum(locations, Vector()) / len(locations) if locations else Vector()


def world_normal(normal, matrix):
    return (matrix.inverted_safe().transposed().to_3x3() @ normal).normalized()


def component_rotation(context, obj, bm):
    """Build an orientation for the active vertex, edge or face selection."""
    selection = tuple(context.scene.tool_settings.mesh_select_mode)
    mx = obj.matrix_world
    if selection == (True, False, False):
        verts = [v for v in bm.verts if v.select]
        active = bm.select_history[-1] if bm.select_history and isinstance(bm.select_history[-1], bmesh.types.BMVert) else verts[0]
        normal = (mx.to_3x3() @ active.normal).normalized()
        if active.link_edges:
            edge = max(active.link_edges, key=lambda item: item.calc_length())
            tangent = (mx.to_3x3() @ (edge.other_vert(active).co - active.co)).normalized()
        else:
            tangent = mx.to_3x3() @ Vector((1, 0, 0))
    elif selection == (False, True, False):
        edges = [e for e in bm.edges if e.select]
        edge = bm.select_history[-1] if bm.select_history and isinstance(bm.select_history[-1], bmesh.types.BMEdge) else edges[0]
        tangent = (mx.to_3x3() @ (edge.verts[1].co - edge.verts[0].co)).normalized()
        normal = average_locations([world_normal(f.normal, mx) for f in edge.link_faces]) if edge.link_faces else mx.to_3x3() @ Vector((0, 0, 1))
        if normal.length_squared < 1e-12:
            normal = mx.to_3x3() @ Vector((0, 0, 1))
        normal.normalize()
    else:
        faces = [f for f in bm.faces if f.select]
        face = bm.faces.active if bm.faces.active in faces else faces[0]
        normal = world_normal(face.normal, mx)
        tangent = (mx.to_3x3() @ face.calc_tangent_edge_pair()).normalized()
    tangent = (tangent - normal * tangent.dot(normal)).normalized()
    binormal = normal.cross(tangent).normalized()
    region_3d = getattr(getattr(context, 'space_data', None), 'region_3d', None)
    if region_3d:
        view_up = region_3d.view_rotation @ Vector((0, 1, 0))
        if binormal.dot(view_up) < 0:
            tangent.negate()
            binormal.negate()
    rotation = Matrix.Identity(3)
    rotation.col[0] = tangent
    rotation.col[1] = binormal
    rotation.col[2] = normal
    return rotation.to_4x4()


def set_cursor_transform(cursor, location, rotation):
    mode = cursor.rotation_mode
    cursor.rotation_mode = 'QUATERNION'
    cursor.location = location
    cursor.rotation_quaternion = rotation
    cursor.rotation_mode = mode


def popup_error(operator, message):
    operator.report({'ERROR'}, message)


def edit_bmesh(context):
    active = context.active_object
    return active, bmesh.from_edit_mesh(active.data) if active and active.type == 'MESH' else None


def selected_verts(bm):
    return [v for v in bm.verts if v.select]


def compensate_children(obj, old_matrix, new_matrix):
    delta = new_matrix.inverted_safe() @ old_matrix
    for child in list(obj.children):
        child.matrix_parent_inverse = delta @ child.matrix_parent_inverse


def set_obj_origin(obj, matrix, bm=None):
    old = obj.matrix_world.copy()
    compensate_children(obj, old, matrix)
    delta = matrix.inverted_safe() @ old
    obj.matrix_world = matrix
    if bm is not None:
        bmesh.ops.transform(bm, verts=list(bm.verts), matrix=delta)
        bmesh.update_edit_mesh(obj.data)
    elif obj.data and hasattr(obj.data, 'transform'):
        obj.data.transform(delta)
        obj.data.update()
