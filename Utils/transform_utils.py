"""Object, cursor, and transform helpers shared by HoTools modules."""

import bmesh


def set_cursor_transform(cursor, location, rotation):
    mode = cursor.rotation_mode
    cursor.rotation_mode = 'QUATERNION'
    cursor.location = location
    cursor.rotation_quaternion = rotation
    cursor.rotation_mode = mode


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
