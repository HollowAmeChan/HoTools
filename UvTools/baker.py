import bpy
import sys
import os
import math
import random
import numpy as np

if sys.version_info >= (3, 13):
    from .._Lib.py313.PIL import Image, ImageDraw, ImageFilter
elif sys.version_info >= (3, 11):
    from .._Lib.py311.PIL import Image, ImageDraw, ImageFilter

import bmesh
from bpy.types import Operator, Panel, Menu
from bpy.props import StringProperty, PointerProperty, BoolProperty, CollectionProperty, FloatProperty, IntProperty, EnumProperty, FloatVectorProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d

# region 变量


def reg_props():
    bpy.types.Scene.ho_uvtools_light_cast_object = PointerProperty(
        name="光源",
        type=bpy.types.Object,
        poll=poll_light_object,
        description="用于光源Cast Lightmap烘焙的Light对象"
    )
    return


def ureg_props():
    if hasattr(bpy.types.Scene, "ho_uvtools_light_cast_object"):
        del bpy.types.Scene.ho_uvtools_light_cast_object
    return
# endregion


def dilate_image_with_colors(pil_img, radius):
    """为每个像素保留颜色，使用膨胀传播颜色"""
    if radius <= 0:
        return pil_img

    img_arr = np.array(pil_img)
    alpha = img_arr[:, :, 3]
    mask = (alpha == 0)

    for _ in range(radius):
        dilated = img_arr.copy()
        for dx, dy in [(-1, -1), (-1, 0), (-1, 1),
                       (0, -1),          (0, 1),
                       (1, -1), (1, 0),  (1, 1)]:
            shifted = np.roll(np.roll(img_arr, dx, axis=0), dy, axis=1)
            shifted_alpha = shifted[:, :, 3]
            cond = (shifted_alpha > 0) & mask
            dilated[cond] = shifted[cond]
        img_arr = dilated
        mask = (img_arr[:, :, 3] == 0)

    return Image.fromarray(img_arr, mode="RGBA")


def fill_weight_triangle(img_arr, pts, weights):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    w0, w1, w2 = weights

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))

    for py in range(min_y, max_y + 1):
        sample_y = py + 0.5
        for px in range(min_x, max_x + 1):
            sample_x = px + 0.5
            b0 = ((y1 - y2) * (sample_x - x2) +
                  (x2 - x1) * (sample_y - y2)) / denom
            b1 = ((y2 - y0) * (sample_x - x2) +
                  (x0 - x2) * (sample_y - y2)) / denom
            b2 = 1.0 - b0 - b1

            if b0 < 0.0 or b1 < 0.0 or b2 < 0.0:
                continue

            weight = max(0.0, min(1.0, b0 * w0 + b1 * w1 + b2 * w2))
            gray = int(weight * 255)
            img_arr[py, px] = (gray, gray, gray, 255)


def fill_solid_triangle(img_arr, pts, color, max_bbox_pixels=0, chunk_rows=32):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return False

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return False
    if max_bbox_pixels > 0 and (max_x - min_x + 1) * (max_y - min_y + 1) > max_bbox_pixels:
        return False

    xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
    denom = np.float32(denom)

    for y_start in range(min_y, max_y + 1, chunk_rows):
        y_end = min(max_y, y_start + chunk_rows - 1)
        ys = np.arange(y_start, y_end + 1, dtype=np.float32)[:, None] + 0.5

        b0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        b2 = 1.0 - b0 - b1
        mask = (b0 >= 0.0) & (b1 >= 0.0) & (b2 >= 0.0)
        if not mask.any():
            continue

        img_arr[y_start:y_end + 1, min_x:max_x + 1][mask] = color

    return True


def get_face_edge_uv_pair(face, edge, uv_layer):
    for loop in face.loops:
        if loop.edge == edge:
            return loop[uv_layer].uv.copy(), loop.link_loop_next[uv_layer].uv.copy()
    return None


def uv_edge_connected(face, linked_face, edge, uv_layer, epsilon=1e-5):
    pair_a = get_face_edge_uv_pair(face, edge, uv_layer)
    pair_b = get_face_edge_uv_pair(linked_face, edge, uv_layer)
    if pair_a is None or pair_b is None:
        return False

    a0, a1 = pair_a
    b0, b1 = pair_b
    same_dir = (a0 - b0).length < epsilon and (a1 - b1).length < epsilon
    flip_dir = (a0 - b1).length < epsilon and (a1 - b0).length < epsilon
    return same_dir or flip_dir


def find_uv_islands(bm, uv_layer):
    islands = []
    visited = set()

    for face in bm.faces:
        if face in visited:
            continue

        island_faces = set()
        stack = [face]
        while stack:
            f = stack.pop()
            if f in island_faces:
                continue

            island_faces.add(f)
            visited.add(f)

            for edge in f.edges:
                for linked_face in edge.link_faces:
                    if linked_face == f or linked_face in island_faces or linked_face in visited:
                        continue
                    if uv_edge_connected(f, linked_face, edge, uv_layer):
                        stack.append(linked_face)

        islands.append(island_faces)

    return islands


def fill_local_uv_triangle(img_arr, pts, local_uvs):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    uv0, uv1, uv2 = local_uvs

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))

    for py in range(min_y, max_y + 1):
        sample_y = py + 0.5
        for px in range(min_x, max_x + 1):
            sample_x = px + 0.5
            b0 = ((y1 - y2) * (sample_x - x2) +
                  (x2 - x1) * (sample_y - y2)) / denom
            b1 = ((y2 - y0) * (sample_x - x2) +
                  (x0 - x2) * (sample_y - y2)) / denom
            b2 = 1.0 - b0 - b1

            if b0 < -1e-6 or b1 < -1e-6 or b2 < -1e-6:
                continue

            local_u = max(0.0, min(1.0, b0 * uv0[0] + b1 * uv1[0] + b2 * uv2[0]))
            local_v = max(0.0, min(1.0, b0 * uv0[1] + b1 * uv1[1] + b2 * uv2[1]))
            img_arr[py, px] = (int(local_u * 255 + 0.5),
                               int(local_v * 255 + 0.5),
                               0,
                               255)


TB_FLOW_MAP_AXIS_ITEMS = [
    ('WORLD_Z', "世界Z", "把Blender世界Z上方向投影到T/B平面"),
    ('WORLD_X', "世界X", "把Blender世界X方向投影到T/B平面"),
    ('WORLD_Y', "世界Y", "把Blender世界Y方向投影到T/B平面"),
]


GRAVITY_FIELD_AXIS_ITEMS = [
    ('WORLD_NEG_Z', "世界-Z(重力)", "Blender世界Z为上时的默认重力下方向"),
    ('WORLD_POS_Z', "世界+Z", "沿Blender世界Z上方向"),
    ('WORLD_NEG_X', "世界-X", "沿Blender世界X负方向"),
    ('WORLD_POS_X', "世界+X", "沿Blender世界X正方向"),
    ('WORLD_NEG_Y', "世界-Y", "沿Blender世界Y负方向"),
    ('WORLD_POS_Y', "世界+Y", "沿Blender世界Y正方向"),
]


def get_tb_flow_map_axis_vector(axis_mode):
    axis_name = axis_mode.rsplit("_", 1)[-1]
    if axis_name == 'X':
        axis = Vector((1.0, 0.0, 0.0))
    elif axis_name == 'Y':
        axis = Vector((0.0, 1.0, 0.0))
    else:
        axis = Vector((0.0, 0.0, 1.0))

    if axis.length <= 1e-8:
        return None
    axis.normalize()
    return axis


def get_gravity_field_axis_vector(axis_mode):
    axis_name = axis_mode.rsplit("_", 1)[-1]
    sign = -1.0 if "_NEG_" in axis_mode else 1.0
    if axis_name == 'X':
        axis = Vector((sign, 0.0, 0.0))
    elif axis_name == 'Y':
        axis = Vector((0.0, sign, 0.0))
    else:
        axis = Vector((0.0, 0.0, sign))

    if axis.length <= 1e-8:
        return None
    axis.normalize()
    return axis


def get_loop_bitangent(loop):
    bitangent = loop.normal.cross(loop.tangent)
    bitangent *= loop.bitangent_sign
    if bitangent.length > 1e-8:
        bitangent.normalize()
    return bitangent


def triangulate_mesh_ngons_in_place(mesh):
    ngon_indices = [poly.index for poly in mesh.polygons if len(poly.vertices) > 4]
    if not ngon_indices:
        return 0

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        faces = [
            bm.faces[index]
            for index in ngon_indices
            if index < len(bm.faces) and len(bm.faces[index].verts) > 4
        ]
        if not faces:
            return 0

        bmesh.ops.triangulate(bm, faces=faces)
        bm.to_mesh(mesh)
        mesh.update()
        return len(faces)
    finally:
        bm.free()


def get_loop_tangent_vector(loop, vector_mode):
    if vector_mode == 'BITANGENT':
        if hasattr(loop, "bitangent"):
            vec = loop.bitangent.copy()
        else:
            vec = get_loop_bitangent(loop)
    else:
        vec = loop.tangent.copy()

    if vec.length > 1e-8:
        vec.normalize()
    return vec


def calc_temp_triangulated_loop_vectors(mesh, uv_layer, vector_mode):
    uv_layer_name = uv_layer.name
    tmp_mesh = mesh.copy()
    tangents_ready = False
    try:
        attr_name = "__ho_orig_loop_index"
        existing_attr = tmp_mesh.attributes.get(attr_name)
        if existing_attr is not None:
            tmp_mesh.attributes.remove(existing_attr)
        loop_index_attr = tmp_mesh.attributes.new(
            name=attr_name, type='INT', domain='CORNER')
        for loop_index, attr_item in enumerate(loop_index_attr.data):
            attr_item.value = loop_index

        triangulated_faces = triangulate_mesh_ngons_in_place(tmp_mesh)
        if triangulated_faces <= 0:
            raise RuntimeError("没有可临时三角化的N-gon")

        tmp_uv_layer = tmp_mesh.uv_layers.get(uv_layer_name) or tmp_mesh.uv_layers.active
        if tmp_uv_layer is None:
            raise RuntimeError("三角化后无UV")

        tmp_mesh.calc_tangents(uvmap=tmp_uv_layer.name)
        tangents_ready = True

        loop_index_attr = tmp_mesh.attributes.get(attr_name)
        if loop_index_attr is None:
            raise RuntimeError("临时loop映射丢失")

        vector_sums = {}
        vector_counts = {}
        for tmp_loop in tmp_mesh.loops:
            orig_loop_index = loop_index_attr.data[tmp_loop.index].value
            if orig_loop_index < 0 or orig_loop_index >= len(mesh.loops):
                continue

            vec = get_loop_tangent_vector(tmp_loop, vector_mode)
            if vec.length <= 1e-8:
                continue

            if orig_loop_index in vector_sums:
                vector_sums[orig_loop_index] += vec
                vector_counts[orig_loop_index] += 1
            else:
                vector_sums[orig_loop_index] = vec.copy()
                vector_counts[orig_loop_index] = 1

        loop_vectors = {}
        for loop_index, vec in vector_sums.items():
            if vec.length <= 1e-8:
                continue
            vec.normalize()
            loop_vectors[loop_index] = (vec.x, vec.y, vec.z)

        return loop_vectors, triangulated_faces
    finally:
        if tangents_ready:
            try:
                tmp_mesh.free_tangents()
            except RuntimeError:
                pass
        try:
            bpy.data.meshes.remove(tmp_mesh)
        except RuntimeError:
            pass


def calc_uv_tangent_bitangent_triangle(mesh, uv_layer, polygon, tri_loop_indices):
    p0 = mesh.vertices[mesh.loops[tri_loop_indices[0]].vertex_index].co
    p1 = mesh.vertices[mesh.loops[tri_loop_indices[1]].vertex_index].co
    p2 = mesh.vertices[mesh.loops[tri_loop_indices[2]].vertex_index].co
    uv0 = uv_layer.data[tri_loop_indices[0]].uv
    uv1 = uv_layer.data[tri_loop_indices[1]].uv
    uv2 = uv_layer.data[tri_loop_indices[2]].uv

    q1 = p1 - p0
    q2 = p2 - p0
    du1 = uv1.x - uv0.x
    dv1 = uv1.y - uv0.y
    du2 = uv2.x - uv0.x
    dv2 = uv2.y - uv0.y
    det = du1 * dv2 - dv1 * du2
    if abs(det) <= 1e-12:
        return None

    tangent = (q1 * dv2 - q2 * dv1) / det
    bitangent = (q2 * du1 - q1 * du2) / det
    normal = polygon.normal.copy()
    if normal.length <= 1e-8:
        normal = q1.cross(q2)
    if tangent.length <= 1e-8 or bitangent.length <= 1e-8 or normal.length <= 1e-8:
        return None

    area = q1.cross(q2).length
    tangent.normalize()
    bitangent.normalize()
    normal.normalize()
    return tangent, bitangent, normal, area, abs(det)


def calc_uv_chirality_triangle(mesh, uv_layer, polygon, tri_loop_indices):
    tangent_space = calc_uv_tangent_bitangent_triangle(
        mesh, uv_layer, polygon, tri_loop_indices)
    if tangent_space is None:
        return None

    tangent, bitangent, normal, area, uv_area = tangent_space
    handedness = tangent.cross(bitangent).dot(normal)
    if abs(handedness) <= 1e-8:
        return None

    weight = area
    if weight <= 1e-8:
        weight = uv_area
    return (1 if handedness >= 0.0 else -1), weight


def calc_loop_tb_flow(loop, flow_axis, tangent_matrix):
    tangent = tangent_matrix @ loop.tangent
    if tangent.length <= 1e-8:
        return 0.0, 0.0
    tangent.normalize()

    bitangent = tangent_matrix @ get_loop_bitangent(loop)
    if bitangent.length <= 1e-8:
        return 0.0, 0.0
    bitangent.normalize()

    return flow_axis.dot(tangent), flow_axis.dot(bitangent)


def normalize_tb_flow(flow):
    x, y = flow
    length = (x * x + y * y) ** 0.5
    if length <= 1e-8:
        return None
    return (x / length, y / length)


def rasterize_gravity_field_triangle(img_arr, pts, flows, strength_scale=1.0,
                                     flip_r=False, flip_g=False,
                                     max_bbox_pixels=32_000_000, chunk_rows=32):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    f0, f1, f2 = flows

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return False

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return False
    if (max_x - min_x + 1) * (max_y - min_y + 1) > max_bbox_pixels:
        return False

    xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
    denom = np.float32(denom)
    strength_scale = max(0.0, float(strength_scale))

    for y_start in range(min_y, max_y + 1, chunk_rows):
        y_end = min(max_y, y_start + chunk_rows - 1)
        ys = np.arange(y_start, y_end + 1, dtype=np.float32)[:, None] + 0.5

        b0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        b2 = 1.0 - b0 - b1
        inside = (b0 >= 0.0) & (b1 >= 0.0) & (b2 >= 0.0)
        if not inside.any():
            continue

        mb0 = b0[inside]
        mb1 = b1[inside]
        mb2 = b2[inside]
        gx = mb0 * f0[0] + mb1 * f1[0] + mb2 * f2[0]
        gy = mb0 * f0[1] + mb1 * f1[1] + mb2 * f2[1]

        strength = np.sqrt(gx * gx + gy * gy)
        valid = strength > 1e-8
        dir_x = np.zeros_like(gx, dtype=np.float32)
        dir_y = np.zeros_like(gy, dtype=np.float32)
        dir_x[valid] = gx[valid] / strength[valid]
        dir_y[valid] = gy[valid] / strength[valid]
        if flip_r:
            dir_x *= -1.0
        if flip_g:
            dir_y *= -1.0

        encoded = np.empty((len(gx), 4), dtype=np.uint8)
        encoded[:, 0] = ((np.clip(dir_x, -1.0, 1.0) * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 1] = ((np.clip(dir_y, -1.0, 1.0) * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 2] = (np.clip(strength * strength_scale, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 3] = 255

        target = img_arr[y_start:y_end + 1, min_x:max_x + 1]
        target[inside] = encoded

    return True


def rasterize_surface_sample_triangle(mask, pos_x, pos_y, pos_z, normal_x, normal_y,
                                      normal_z, pts, positions, normals,
                                      max_bbox_pixels=32_000_000, chunk_rows=32):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    p0, p1, p2 = positions
    n0, n1, n2 = normals

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return False

    height, width = mask.shape
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return False
    if (max_x - min_x + 1) * (max_y - min_y + 1) > max_bbox_pixels:
        return False

    xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
    denom = np.float32(denom)

    for y_start in range(min_y, max_y + 1, chunk_rows):
        y_end = min(max_y, y_start + chunk_rows - 1)
        ys = np.arange(y_start, y_end + 1, dtype=np.float32)[:, None] + 0.5

        b0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        b2 = 1.0 - b0 - b1
        inside = (b0 >= 0.0) & (b1 >= 0.0) & (b2 >= 0.0)
        if not inside.any():
            continue

        mb0 = b0[inside]
        mb1 = b1[inside]
        mb2 = b2[inside]
        px = mb0 * p0[0] + mb1 * p1[0] + mb2 * p2[0]
        py = mb0 * p0[1] + mb1 * p1[1] + mb2 * p2[1]
        pz = mb0 * p0[2] + mb1 * p1[2] + mb2 * p2[2]
        nx = mb0 * n0[0] + mb1 * n1[0] + mb2 * n2[0]
        ny = mb0 * n0[1] + mb1 * n1[1] + mb2 * n2[1]
        nz = mb0 * n0[2] + mb1 * n1[2] + mb2 * n2[2]
        normal_length = np.sqrt(nx * nx + ny * ny + nz * nz)
        valid = normal_length > 1e-8
        nx[valid] /= normal_length[valid]
        ny[valid] /= normal_length[valid]
        nz[valid] /= normal_length[valid]

        target_mask = mask[y_start:y_end + 1, min_x:max_x + 1]
        target_x = pos_x[y_start:y_end + 1, min_x:max_x + 1]
        target_y = pos_y[y_start:y_end + 1, min_x:max_x + 1]
        target_z = pos_z[y_start:y_end + 1, min_x:max_x + 1]
        target_nx = normal_x[y_start:y_end + 1, min_x:max_x + 1]
        target_ny = normal_y[y_start:y_end + 1, min_x:max_x + 1]
        target_nz = normal_z[y_start:y_end + 1, min_x:max_x + 1]
        target_mask[inside] = True
        target_x[inside] = px.astype(np.float32)
        target_y[inside] = py.astype(np.float32)
        target_z[inside] = pz.astype(np.float32)
        target_nx[inside] = nx.astype(np.float32)
        target_ny[inside] = ny.astype(np.float32)
        target_nz[inside] = nz.astype(np.float32)

    return True


def collect_lightmap_surface_samples(selected_objs, depsgraph, width, height):
    mask = np.zeros((height, width), dtype=bool)
    pos_x = np.zeros((height, width), dtype=np.float32)
    pos_y = np.zeros((height, width), dtype=np.float32)
    pos_z = np.zeros((height, width), dtype=np.float32)
    normal_x = np.zeros((height, width), dtype=np.float32)
    normal_y = np.zeros((height, width), dtype=np.float32)
    normal_z = np.zeros((height, width), dtype=np.float32)
    exported_tris = 0
    skipped_large_tris = 0
    out_of_range_tris = 0
    skipped_objects = []
    uv_min_u = float("inf")
    uv_min_v = float("inf")
    uv_max_u = float("-inf")
    uv_max_v = float("-inf")

    for obj in selected_objs:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        try:
            uv_layer = mesh.uv_layers.active
            if uv_layer is None:
                skipped_objects.append(f"{obj.name}(无UV)")
                continue

            matrix_world = eval_obj.matrix_world
            try:
                normal_matrix = matrix_world.to_3x3().inverted().transposed()
            except ValueError:
                skipped_objects.append(f"{obj.name}(法线矩阵无效)")
                continue

            for poly in mesh.polygons:
                loop_indices = list(poly.loop_indices)
                if len(loop_indices) < 3:
                    continue

                pts = []
                positions = []
                normals = []
                for loop_index in loop_indices:
                    loop = mesh.loops[loop_index]
                    uv = uv_layer.data[loop_index].uv.copy()
                    uv_min_u = min(uv_min_u, uv.x)
                    uv_min_v = min(uv_min_v, uv.y)
                    uv_max_u = max(uv_max_u, uv.x)
                    uv_max_v = max(uv_max_v, uv.y)
                    pts.append((uv.x * width, (1.0 - uv.y) * height))
                    world_pos = matrix_world @ mesh.vertices[loop.vertex_index].co
                    positions.append((world_pos.x, world_pos.y, world_pos.z))
                    world_normal = normal_matrix @ loop.normal
                    if world_normal.length > 1e-8:
                        world_normal.normalize()
                    normals.append((world_normal.x, world_normal.y, world_normal.z))

                for i in range(1, len(loop_indices) - 1):
                    tri_pts = [pts[0], pts[i], pts[i + 1]]
                    tri_positions = [
                        positions[0],
                        positions[i],
                        positions[i + 1]
                    ]
                    tri_normals = [
                        normals[0],
                        normals[i],
                        normals[i + 1]
                    ]
                    if any(p[0] < 0 or p[0] > width or p[1] < 0 or p[1] > height for p in tri_pts):
                        out_of_range_tris += 1
                    if rasterize_surface_sample_triangle(
                        mask,
                        pos_x,
                        pos_y,
                        pos_z,
                        normal_x,
                        normal_y,
                        normal_z,
                        tri_pts,
                        tri_positions,
                        tri_normals
                    ):
                        exported_tris += 1
                    else:
                        skipped_large_tris += 1
        finally:
            eval_obj.to_mesh_clear()

    return {
        "mask": mask,
        "pos_x": pos_x,
        "pos_y": pos_y,
        "pos_z": pos_z,
        "normal_x": normal_x,
        "normal_y": normal_y,
        "normal_z": normal_z,
        "exported_tris": exported_tris,
        "skipped_large_tris": skipped_large_tris,
        "out_of_range_tris": out_of_range_tris,
        "skipped_objects": skipped_objects,
        "uv_min_u": uv_min_u,
        "uv_min_v": uv_min_v,
        "uv_max_u": uv_max_u,
        "uv_max_v": uv_max_v,
    }


SIX_DIRECTION_VISIBILITY_DIRS = [
    (Vector((1.0, 0.0, 0.0)), 0, True),
    (Vector((0.0, 1.0, 0.0)), 1, True),
    (Vector((0.0, 0.0, 1.0)), 2, True),
    (Vector((-1.0, 0.0, 0.0)), 0, False),
    (Vector((0.0, -1.0, 0.0)), 1, False),
    (Vector((0.0, 0.0, -1.0)), 2, False),
]


def scene_ray_cast(scene, depsgraph, origin, direction, max_distance):
    try:
        return scene.ray_cast(depsgraph, origin, direction, distance=max_distance)
    except TypeError:
        return scene.ray_cast(depsgraph, origin, direction, max_distance)


def scene_ray_is_visible(scene, depsgraph, origin, direction, max_distance,
                         occluder_objects=None, skip_epsilon=1e-4,
                         max_skip_hits=64):
    current_origin = origin
    remaining_distance = max(0.0, float(max_distance))
    occluder_objects = None if occluder_objects is None else set(occluder_objects)

    for _skip_index in range(max_skip_hits):
        if remaining_distance <= 0.0:
            return True

        result = scene_ray_cast(
            scene, depsgraph, current_origin, direction, remaining_distance)
        if not bool(result[0]):
            return True

        hit_location = result[1]
        hit_object = result[4] if len(result) > 4 else None
        if occluder_objects is None or hit_object in occluder_objects:
            return False

        hit_distance = (hit_location - current_origin).length
        advance = max(float(skip_epsilon), 1e-6)
        current_origin = hit_location + direction * advance
        remaining_distance -= hit_distance + advance

    return False


def bake_six_direction_visibility(scene, depsgraph, mask, pos_x, pos_y, pos_z,
                                  normal_x, normal_y, normal_z,
                                  sample_step=2, max_distance=100.0,
                                  ray_bias=0.001, occluder_objects=None):
    height, width = mask.shape
    pos_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    neg_rgb = np.zeros((height, width, 3), dtype=np.uint8)
    sample_step = max(1, int(sample_step))
    max_distance = max(0.0, float(max_distance))
    ray_bias = max(0.0, float(ray_bias))

    for y0 in range(0, height, sample_step):
        y1 = min(height, y0 + sample_step)
        for x0 in range(0, width, sample_step):
            x1 = min(width, x0 + sample_step)
            block_mask = mask[y0:y1, x0:x1]
            if not block_mask.any():
                continue

            ys, xs = np.nonzero(block_mask)
            sample_y = y0 + int(ys[len(ys) // 2])
            sample_x = x0 + int(xs[len(xs) // 2])
            base_origin = Vector((
                float(pos_x[sample_y, sample_x]),
                float(pos_y[sample_y, sample_x]),
                float(pos_z[sample_y, sample_x]),
            ))
            normal = Vector((
                float(normal_x[sample_y, sample_x]),
                float(normal_y[sample_y, sample_x]),
                float(normal_z[sample_y, sample_x]),
            ))
            if normal.length > 1e-8:
                normal.normalize()

            pos_values = [0, 0, 0]
            neg_values = [0, 0, 0]
            for direction, channel, is_positive in SIX_DIRECTION_VISIBILITY_DIRS:
                origin = base_origin + normal * ray_bias
                visible = scene_ray_is_visible(
                    scene,
                    depsgraph,
                    origin,
                    direction,
                    max_distance,
                    occluder_objects=occluder_objects
                )
                value = 255 if visible else 0
                if is_positive:
                    pos_values[channel] = value
                else:
                    neg_values[channel] = value

            pos_block = pos_rgb[y0:y1, x0:x1]
            neg_block = neg_rgb[y0:y1, x0:x1]
            pos_block[block_mask] = pos_values
            neg_block[block_mask] = neg_values

    return pos_rgb, neg_rgb


def get_light_rgb(light_data, intensity_scale):
    color = getattr(light_data, "color", (1.0, 1.0, 1.0))
    energy = max(0.0, float(getattr(light_data, "energy", 1.0)))
    return (
        max(0.0, float(color[0])) * energy * intensity_scale,
        max(0.0, float(color[1])) * energy * intensity_scale,
        max(0.0, float(color[2])) * energy * intensity_scale,
    )


def calc_spot_factor(light_data, light_obj, ray_to_surface):
    spot_size = max(1e-6, float(getattr(light_data, "spot_size", math.pi)))
    spot_blend = max(0.0, min(1.0, float(getattr(light_data, "spot_blend", 0.0))))
    light_forward = light_obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    if light_forward.length <= 1e-8 or ray_to_surface.length <= 1e-8:
        return 0.0
    light_forward.normalize()
    ray_to_surface = ray_to_surface.normalized()
    cos_angle = max(-1.0, min(1.0, light_forward.dot(ray_to_surface)))
    angle = math.acos(cos_angle)
    outer = spot_size * 0.5
    if angle >= outer:
        return 0.0
    inner = outer * (1.0 - spot_blend)
    if angle <= inner:
        return 1.0
    fade_range = max(1e-6, outer - inner)
    return max(0.0, min(1.0, 1.0 - (angle - inner) / fade_range))


def calc_area_light_direction_factor(light_obj, ray_to_surface):
    light_forward = light_obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    if light_forward.length <= 1e-8 or ray_to_surface.length <= 1e-8:
        return 0.0
    light_forward.normalize()
    ray_to_surface = ray_to_surface.normalized()
    return max(0.0, light_forward.dot(ray_to_surface))


def calc_light_sample(light_obj, base_origin, normal, max_distance, ray_bias,
                      use_light_distance, intensity_scale):
    light_data = light_obj.data
    light_type = light_data.type
    light_rgb = get_light_rgb(light_data, intensity_scale)
    origin = base_origin + normal * ray_bias

    if light_type == 'SUN':
        light_forward = light_obj.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
        if light_forward.length <= 1e-8:
            return None
        direction = -light_forward.normalized()
        cast_distance = max_distance
        attenuation = 1.0
    else:
        light_location = light_obj.matrix_world.translation
        vector_to_light = light_location - origin
        distance = vector_to_light.length
        if distance <= 1e-8:
            return None
        direction = vector_to_light / distance
        if use_light_distance:
            cast_distance = max(0.0, distance - ray_bias)
        else:
            cast_distance = min(max_distance, max(0.0, distance - ray_bias))
        if cast_distance <= 0.0:
            return None

        attenuation = 1.0 / max(distance * distance, 1.0e-6)
        if light_type == 'SPOT':
            attenuation *= calc_spot_factor(light_data, light_obj, -vector_to_light)
        elif light_type == 'AREA':
            attenuation *= calc_area_light_direction_factor(light_obj, -vector_to_light)

    ndotl = max(0.0, normal.dot(direction))
    strength = ndotl * attenuation
    if strength <= 0.0:
        return None
    return origin, direction, cast_distance, light_rgb, strength


def bake_light_cast(scene, depsgraph, light_obj, mask, pos_x, pos_y, pos_z,
                    normal_x, normal_y, normal_z, sample_step=2,
                    max_distance=100.0, ray_bias=0.001, occluder_objects=None,
                    intensity_scale=1.0, use_light_distance=True):
    height, width = mask.shape
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    sample_step = max(1, int(sample_step))
    max_distance = max(0.0, float(max_distance))
    ray_bias = max(0.0, float(ray_bias))
    intensity_scale = max(0.0, float(intensity_scale))

    for y0 in range(0, height, sample_step):
        y1 = min(height, y0 + sample_step)
        for x0 in range(0, width, sample_step):
            x1 = min(width, x0 + sample_step)
            block_mask = mask[y0:y1, x0:x1]
            if not block_mask.any():
                continue

            ys, xs = np.nonzero(block_mask)
            sample_y = y0 + int(ys[len(ys) // 2])
            sample_x = x0 + int(xs[len(xs) // 2])
            base_origin = Vector((
                float(pos_x[sample_y, sample_x]),
                float(pos_y[sample_y, sample_x]),
                float(pos_z[sample_y, sample_x]),
            ))
            normal = Vector((
                float(normal_x[sample_y, sample_x]),
                float(normal_y[sample_y, sample_x]),
                float(normal_z[sample_y, sample_x]),
            ))
            if normal.length > 1e-8:
                normal.normalize()
            else:
                continue

            sample = calc_light_sample(
                light_obj,
                base_origin,
                normal,
                max_distance,
                ray_bias,
                use_light_distance,
                intensity_scale
            )
            if sample is None:
                continue

            origin, direction, cast_distance, light_rgb, strength = sample
            visible = scene_ray_is_visible(
                scene,
                depsgraph,
                origin,
                direction,
                cast_distance,
                occluder_objects=occluder_objects
            )
            if not visible:
                continue

            value = [
                int(max(0.0, min(1.0, light_rgb[channel] * strength)) * 255.0 + 0.5)
                for channel in range(3)
            ]
            block = rgb[y0:y1, x0:x1]
            block[block_mask] = value

    return rgb


def finalize_six_direction_visibility_image(rgb_arr, mask, dilate_radius, blur_radius):
    alpha = (mask.astype(np.uint8) * 255)
    rgba = np.dstack((rgb_arr, alpha))
    pil_img = Image.fromarray(rgba, mode="RGBA")
    pil_img = dilate_image_with_colors(pil_img, dilate_radius)
    if blur_radius > 0.0:
        rgb_img = pil_img.convert("RGB").filter(
            ImageFilter.GaussianBlur(radius=float(blur_radius)))
        pil_img = Image.merge("RGBA", (*rgb_img.split(), pil_img.getchannel("A")))
    return pil_img.convert("RGB")


def finalize_light_cast_image(rgb_arr, mask, dilate_radius, blur_radius, image_format):
    alpha = (mask.astype(np.uint8) * 255)
    rgba = np.dstack((rgb_arr, alpha))
    pil_img = Image.fromarray(rgba, mode="RGBA")
    pil_img = dilate_image_with_colors(pil_img, dilate_radius)
    if blur_radius > 0.0:
        rgb_img = pil_img.convert("RGB").filter(
            ImageFilter.GaussianBlur(radius=float(blur_radius)))
        pil_img = Image.merge("RGBA", (*rgb_img.split(), pil_img.getchannel("A")))
    return pil_img if image_format == 'PNG' else pil_img.convert("RGB")


def poll_light_object(self, obj):
    return obj is not None and obj.type == 'LIGHT'


def clean_filename_part(name):
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def rasterize_tb_flow_triangle(mask, flow_x, flow_y, pts, flows, island_ids=None,
                               island_id=1, max_bbox_pixels=32_000_000, chunk_rows=32):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    f0, f1, f2 = flows

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return False

    height, width = mask.shape
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return False
    if (max_x - min_x + 1) * (max_y - min_y + 1) > max_bbox_pixels:
        return False

    xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
    denom = np.float32(denom)

    for y_start in range(min_y, max_y + 1, chunk_rows):
        y_end = min(max_y, y_start + chunk_rows - 1)
        ys = np.arange(y_start, y_end + 1, dtype=np.float32)[:, None] + 0.5

        b0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        b2 = 1.0 - b0 - b1
        inside = (b0 >= 0.0) & (b1 >= 0.0) & (b2 >= 0.0)
        if not inside.any():
            continue

        mb0 = b0[inside]
        mb1 = b1[inside]
        mb2 = b2[inside]
        fx = mb0 * f0[0] + mb1 * f1[0] + mb2 * f2[0]
        fy = mb0 * f0[1] + mb1 * f1[1] + mb2 * f2[1]

        length = np.sqrt(fx * fx + fy * fy)
        valid = length > 1e-8
        fx[valid] /= length[valid]
        fy[valid] /= length[valid]

        target_mask = mask[y_start:y_end + 1, min_x:max_x + 1]
        target_x = flow_x[y_start:y_end + 1, min_x:max_x + 1]
        target_y = flow_y[y_start:y_end + 1, min_x:max_x + 1]
        target_mask[inside] = True
        target_x[inside] = fx.astype(np.float32)
        target_y[inside] = fy.astype(np.float32)
        if island_ids is not None:
            target_ids = island_ids[y_start:y_end + 1, min_x:max_x + 1]
            target_ids[inside] = island_id

    return True


def tb_flow_image_direction(flow_x, flow_y, width, height):
    dir_x = flow_x * float(width)
    dir_y = -flow_y * float(height)
    length = np.sqrt(dir_x * dir_x + dir_y * dir_y)
    valid = length > 1e-8
    dir_x = np.where(valid, dir_x / np.maximum(length, 1e-8), 0.0).astype(np.float32)
    dir_y = np.where(valid, dir_y / np.maximum(length, 1e-8), 0.0).astype(np.float32)
    return dir_x, dir_y


def tb_flow_build_poisson_terms(mask, grad_x, grad_y):
    mask = mask.astype(bool)
    degree = np.zeros(mask.shape, dtype=np.float32)
    delta_sum = np.zeros(mask.shape, dtype=np.float32)

    horizontal = mask[:, :-1] & mask[:, 1:]
    if horizontal.any():
        delta = 0.5 * (grad_x[:, :-1] + grad_x[:, 1:])
        edge_delta = np.where(horizontal, delta, 0.0).astype(np.float32)
        edge_weight = horizontal.astype(np.float32)
        degree[:, :-1] += edge_weight
        degree[:, 1:] += edge_weight
        delta_sum[:, :-1] += edge_delta
        delta_sum[:, 1:] -= edge_delta

    vertical = mask[:-1, :] & mask[1:, :]
    if vertical.any():
        delta = 0.5 * (grad_y[:-1, :] + grad_y[1:, :])
        edge_delta = np.where(vertical, delta, 0.0).astype(np.float32)
        edge_weight = vertical.astype(np.float32)
        degree[:-1, :] += edge_weight
        degree[1:, :] += edge_weight
        delta_sum[:-1, :] += edge_delta
        delta_sum[1:, :] -= edge_delta

    return degree, delta_sum, horizontal, vertical


def tb_flow_neighbor_sum(values, horizontal, vertical):
    out = np.zeros(values.shape, dtype=np.float32)
    if horizontal.any():
        out[:, :-1] += np.where(horizontal, values[:, 1:], 0.0)
        out[:, 1:] += np.where(horizontal, values[:, :-1], 0.0)
    if vertical.any():
        out[:-1, :] += np.where(vertical, values[1:, :], 0.0)
        out[1:, :] += np.where(vertical, values[:-1, :], 0.0)
    return out


def tb_flow_solve_coordinate(mask, grad_x, grad_y, iterations=48, omega=1.35):
    active = mask.astype(bool)
    if not active.any():
        return None

    degree, delta_sum, horizontal, vertical = tb_flow_build_poisson_terms(
        active, grad_x, grad_y)
    solve_mask = active & (degree > 0.0)
    if not solve_mask.any():
        return None

    yy, xx = np.indices(active.shape, dtype=np.float32)
    ref_x = float(grad_x[solve_mask].mean())
    ref_y = float(grad_y[solve_mask].mean())
    values = (xx * ref_x + yy * ref_y).astype(np.float32)
    values[~active] = 0.0

    red = ((xx.astype(np.int32) + yy.astype(np.int32)) & 1) == 0
    black = ~red
    iterations = max(4, int(iterations))
    omega = max(1.0, min(float(omega), 1.8))

    for _iteration in range(iterations):
        for color in (red, black):
            update_mask = solve_mask & color
            if not update_mask.any():
                continue
            neighbor_sum = tb_flow_neighbor_sum(values, horizontal, vertical)
            target = (neighbor_sum - delta_sum) / np.maximum(degree, 1.0)
            values[update_mask] = (
                values[update_mask] * (1.0 - omega) +
                target[update_mask] * omega
            )

        values[solve_mask] -= float(values[solve_mask].mean())
        values[~active] = 0.0

    return values


def tb_flow_normalize_channel(mask, values, fallback_x=1.0, fallback_y=0.0):
    active = mask.astype(bool)
    out = np.zeros(mask.shape, dtype=np.float32)
    if values is None or not active.any():
        return out

    active_values = values[active]
    min_value = float(active_values.min())
    max_value = float(active_values.max())
    value_range = max_value - min_value

    if value_range <= 1e-5:
        yy, xx = np.indices(mask.shape, dtype=np.float32)
        values = xx * float(fallback_x) + yy * float(fallback_y)
        active_values = values[active]
        min_value = float(active_values.min())
        max_value = float(active_values.max())
        value_range = max_value - min_value

    if value_range <= 1e-5:
        out[active] = 0.5
    else:
        out[active] = (values[active] - min_value) / value_range

    return np.clip(out, 0.0, 1.0)


def tb_flow_build_island_channels(mask, flow_x, flow_y, island_ids=None, island_id=1,
                                  image_width=None, image_height=None,
                                  coord_iterations=48, flip_r=False, flip_g=False):
    if island_ids is None:
        island_ids = np.zeros(mask.shape, dtype=np.int32)
        island_ids[mask] = island_id

    flow_len = np.sqrt(flow_x * flow_x + flow_y * flow_y)
    active = island_ids == island_id
    valid = active & (flow_len > 1e-8)
    if not valid.any():
        return None

    ref_x = float(flow_x[valid].mean())
    ref_y = float(flow_y[valid].mean())
    ref = normalize_tb_flow((ref_x, ref_y))
    if ref is None:
        first_index = np.flatnonzero(valid.ravel())[0]
        ref = (
            float(flow_x.ravel()[first_index]),
            float(flow_y.ravel()[first_index]),
        )
        ref = normalize_tb_flow(ref)
    if ref is None:
        return None

    fixed_x = flow_x.copy()
    fixed_y = flow_y.copy()
    fixed_x[~active] = ref[0]
    fixed_y[~active] = ref[1]
    invalid = active & ~valid
    fixed_x[invalid] = ref[0]
    fixed_y[invalid] = ref[1]

    opposing = active & ((fixed_x * ref[0] + fixed_y * ref[1]) < 0.0)
    fixed_x[opposing] *= -1.0
    fixed_y[opposing] *= -1.0

    height, width = mask.shape
    image_width = width if image_width is None else image_width
    image_height = height if image_height is None else image_height
    dir_x, dir_y = tb_flow_image_direction(fixed_x, fixed_y, image_width, image_height)
    g_values = tb_flow_solve_coordinate(active, dir_x, dir_y, coord_iterations)
    g = tb_flow_normalize_channel(active, g_values, ref[0], -ref[1])

    perp_x = -fixed_y
    perp_y = fixed_x
    perp_dir_x, perp_dir_y = tb_flow_image_direction(perp_x, perp_y, image_width, image_height)
    r_values = tb_flow_solve_coordinate(
        active, perp_dir_x, perp_dir_y, coord_iterations)
    r = tb_flow_normalize_channel(active, r_values, -ref[1], -ref[0])

    if flip_r:
        r = 1.0 - r
    if flip_g:
        g = 1.0 - g
    return r, g


def get_mesh_face_edge_uv_pair(mesh, uv_layer, polygon_index, edge_index):
    loop_indices = list(mesh.polygons[polygon_index].loop_indices)
    for offset, loop_index in enumerate(loop_indices):
        if mesh.loops[loop_index].edge_index != edge_index:
            continue
        next_loop_index = loop_indices[(offset + 1) % len(loop_indices)]
        return (
            uv_layer.data[loop_index].uv.copy(),
            uv_layer.data[next_loop_index].uv.copy(),
        )
    return None


def mesh_uv_edge_connected(mesh, uv_layer, polygon_index, linked_polygon_index, edge_index, epsilon=1e-5):
    pair_a = get_mesh_face_edge_uv_pair(
        mesh, uv_layer, polygon_index, edge_index)
    pair_b = get_mesh_face_edge_uv_pair(
        mesh, uv_layer, linked_polygon_index, edge_index)
    if pair_a is None or pair_b is None:
        return False

    a0, a1 = pair_a
    b0, b1 = pair_b
    same_dir = (a0 - b0).length < epsilon and (a1 - b1).length < epsilon
    flip_dir = (a0 - b1).length < epsilon and (a1 - b0).length < epsilon
    return same_dir or flip_dir


def find_mesh_uv_islands(mesh, uv_layer):
    edge_faces = {}
    poly_edges = {}
    for poly in mesh.polygons:
        edges = [mesh.loops[loop_index].edge_index
                 for loop_index in poly.loop_indices]
        poly_edges[poly.index] = edges
        for edge_index in edges:
            edge_faces.setdefault(edge_index, []).append(poly.index)

    islands = []
    visited = set()
    for poly in mesh.polygons:
        if poly.index in visited:
            continue

        island = set()
        stack = [poly.index]
        while stack:
            polygon_index = stack.pop()
            if polygon_index in island:
                continue

            island.add(polygon_index)
            visited.add(polygon_index)

            for edge_index in poly_edges.get(polygon_index, []):
                for linked_polygon_index in edge_faces.get(edge_index, []):
                    if (
                        linked_polygon_index == polygon_index or
                        linked_polygon_index in island or
                        linked_polygon_index in visited
                    ):
                        continue
                    if mesh_uv_edge_connected(
                        mesh,
                        uv_layer,
                        polygon_index,
                        linked_polygon_index,
                        edge_index
                    ):
                        stack.append(linked_polygon_index)

        islands.append(island)

    return islands


def fill_vector_triangle(img_arr, pts, vectors, max_bbox_pixels=4_000_000, chunk_rows=32):
    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    v0, v1, v2 = vectors

    denom = ((y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2))
    if abs(denom) < 1e-8:
        return False

    height, width = img_arr.shape[:2]
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return False
    if (max_x - min_x + 1) * (max_y - min_y + 1) > max_bbox_pixels:
        return False

    xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
    denom = np.float32(denom)

    for y_start in range(min_y, max_y + 1, chunk_rows):
        y_end = min(max_y, y_start + chunk_rows - 1)
        ys = np.arange(y_start, y_end + 1, dtype=np.float32)[:, None] + 0.5

        b0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        b2 = 1.0 - b0 - b1
        mask = (b0 >= 0.0) & (b1 >= 0.0) & (b2 >= 0.0)
        if not mask.any():
            continue

        mb0 = b0[mask]
        mb1 = b1[mask]
        mb2 = b2[mask]
        vx = mb0 * v0[0] + mb1 * v1[0] + mb2 * v2[0]
        vy = mb0 * v0[1] + mb1 * v1[1] + mb2 * v2[1]
        vz = mb0 * v0[2] + mb1 * v1[2] + mb2 * v2[2]

        length = np.sqrt(vx * vx + vy * vy + vz * vz)
        valid = length > 1e-8
        vx[valid] /= length[valid]
        vy[valid] /= length[valid]
        vz[valid] /= length[valid]

        encoded = np.empty((len(vx), 4), dtype=np.uint8)
        encoded[:, 0] = ((np.clip(vx, -1.0, 1.0) * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 1] = ((np.clip(vy, -1.0, 1.0) * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 2] = ((np.clip(vz, -1.0, 1.0) * 0.5 + 0.5) * 255.0 + 0.5).astype(np.uint8)
        encoded[:, 3] = 255

        img_arr[y_start:y_end + 1, min_x:max_x + 1][mask] = encoded

    return True


def distance_transform_1d_into(f, d, v, z, n):
    k = 0
    v[0] = 0
    z[0] = -np.inf
    z[1] = np.inf

    for q in range(1, n):
        q2 = q * q
        while True:
            p = v[k]
            s = ((f[q] + q2) - (f[p] + p * p)) / (2.0 * q - 2.0 * p)
            if s > z[k]:
                break
            k -= 1

        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = np.inf

    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        p = v[k]
        d[q] = (q - p) * (q - p) + f[p]


def euclidean_distance_transform(seeds):
    inf = 1.0e20
    f = np.empty(seeds.shape, dtype=np.float64)
    f[seeds] = 0.0
    f[~seeds] = inf
    height, width = f.shape
    tmp = np.empty_like(f)
    max_len = max(height, width)
    v = np.empty(max_len, dtype=np.int32)
    z = np.empty(max_len + 1, dtype=np.float64)

    for y in range(height):
        distance_transform_1d_into(f[y, :], tmp[y, :], v, z, width)

    tmp_t = np.ascontiguousarray(tmp.T)
    out_t = np.empty_like(tmp_t)
    for x in range(width):
        distance_transform_1d_into(tmp_t[x, :], out_t[x, :], v, z, height)

    return out_t.T


def get_resample_filter():
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


def rasterize_object_uv_mask(obj, depsgraph, draw, width, height):
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh()
    try:
        uv_layer = mesh.uv_layers.active
        if uv_layer is None:
            return None

        drawn_faces = 0

        for poly in mesh.polygons:
            loop_indices = poly.loop_indices
            if len(loop_indices) < 3:
                continue

            pts = []
            for loop_index in loop_indices:
                uv = uv_layer.data[loop_index].uv
                pts.append((uv.x * width, (1.0 - uv.y) * height))

            for i in range(1, len(pts) - 1):
                draw.polygon([pts[0], pts[i], pts[i + 1]], fill=255)
                drawn_faces += 1

        return drawn_faces
    finally:
        eval_obj.to_mesh_clear()


def apply_black_mask(pil_img, mask):
    if mask is None or not mask.any():
        return pil_img

    mask_img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    if mask_img.size != pil_img.size:
        mask_img = mask_img.resize(pil_img.size, get_resample_filter())

    mask_arr = np.array(mask_img, dtype=np.uint8)
    if not mask_arr.any():
        return pil_img

    img_arr = np.array(pil_img)
    cond = mask_arr > 0
    img_arr[cond, 0:3] = 0
    img_arr[cond, 3] = np.maximum(img_arr[cond, 3], mask_arr[cond])
    return Image.fromarray(img_arr, mode="RGBA")


def build_inner_distance_gray(mask, max_distance, scale):
    gray = np.zeros(mask.shape, dtype=np.uint8)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return gray

    min_x = int(xs.min())
    max_x = int(xs.max()) + 1
    min_y = int(ys.min())
    max_y = int(ys.max()) + 1
    crop_mask = mask[min_y:max_y, min_x:max_x]

    padded_mask = np.zeros(
        (crop_mask.shape[0] + 2, crop_mask.shape[1] + 2), dtype=bool)
    padded_mask[1:-1, 1:-1] = crop_mask
    dist_sq = euclidean_distance_transform(~padded_mask)
    dist = dist_sq[1:-1, 1:-1]
    np.sqrt(dist, out=dist)
    dist -= 0.5
    np.maximum(dist, 0.0, out=dist)
    dist /= scale * float(max_distance)
    np.clip(dist, 0.0, 1.0, out=dist)
    crop_gray = dist
    crop_gray = (crop_gray * 255.0 + 0.5).astype(np.uint8)
    crop_gray[~crop_mask] = 0
    gray[min_y:max_y, min_x:max_x] = crop_gray
    return gray


def push_temp_export_undo(message):
    try:
        bpy.ops.ed.undo_push(message=message)
        return True
    except RuntimeError:
        return False


def reset_temp_export_undo(message):
    try:
        bpy.ops.ed.undo_push(message="")
        bpy.ops.ed.undo()
        bpy.ops.ed.undo_push(message=message)
        return True
    except RuntimeError:
        return False


def enter_object_mode_for_export(context):
    active_obj = context.view_layer.objects.active
    previous_mode = active_obj.mode if active_obj is not None else 'OBJECT'
    switched = False

    if active_obj is not None and previous_mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
            switched = True
        except RuntimeError:
            pass

    return active_obj, previous_mode, switched


def restore_export_mode(context, mode_state):
    active_obj, previous_mode, switched = mode_state
    if not switched or previous_mode == 'OBJECT' or active_obj is None:
        return
    if active_obj.name not in bpy.data.objects:
        return

    try:
        context.view_layer.objects.active = active_obj
        if active_obj.select_get():
            bpy.ops.object.mode_set(mode=previous_mode)
    except RuntimeError:
        pass


def set_modifier_enum_if_available(modifier, prop_name, value):
    if not hasattr(modifier, prop_name):
        return
    try:
        setattr(modifier, prop_name, value)
    except TypeError:
        pass


class OT_UVTools_BakeUVIslandImage(Operator, ExportHelper):
    """将所有选中物体的UV岛填充为纯色并导出为一张图像"""
    bl_idname = "ho.uvtools_bakeuvisland_image"
    bl_label = "导出UV岛填充图"
    bl_description = "将所有选中物体的UV岛填充为纯色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore

    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        island_id_counter = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            visited = set()

            for face in bm.faces:
                if face in visited:
                    continue

                # 广度优先搜索，找出一个UV岛
                island_faces = set()
                stack = [face]
                while stack:
                    f = stack.pop()
                    if f in island_faces:
                        continue
                    island_faces.add(f)
                    visited.add(f)

                    f_uvs = [l[uv_layer].uv for l in f.loops]
                    for edge in f.edges:
                        linked_faces = [
                            lf for lf in edge.link_faces if lf not in island_faces]
                        for lf in linked_faces:
                            lf_uvs = [l[uv_layer].uv for l in lf.loops]
                            shared = False
                            for uv1 in f_uvs:
                                for uv2 in lf_uvs:
                                    if (uv1 - uv2).length < 1e-5:
                                        shared = True
                                        break
                                if shared:
                                    break
                            if shared:
                                stack.append(lf)

                # 给这个UV岛分配一个随机颜色
                color = random_color(island_id_counter)
                island_id_counter += 1

                for f in island_faces:
                    if len(f.loops) < 3:
                        continue
                    uvs = [loop[uv_layer].uv for loop in f.loops]
                    pts = [(uv[0] * width, (1-uv[1]) * height) for uv in uvs]
                    for i in range(1, len(pts) - 1):
                        draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀每个区域颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出ID图像:{final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeMeshIslandImage(Operator, ExportHelper):
    """将所有选中物体的网格孤岛填充为纯色并导出为一张图像"""
    bl_idname = "ho.uvtools_bakemeshisland_image"
    bl_label = "导出网格孤岛填充图"
    bl_description = "将所有选中物体的网格孤岛填充为纯色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)

        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        island_id_counter = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            visited = set()

            for face in bm.faces:
                if face in visited:
                    continue

                # 搜索网格孤岛（拓扑连通）
                mesh_island = set()
                stack = [face]
                while stack:
                    f = stack.pop()
                    if f in mesh_island:
                        continue
                    mesh_island.add(f)
                    visited.add(f)
                    for edge in f.edges:
                        for linked_face in edge.link_faces:
                            if linked_face not in mesh_island:
                                stack.append(linked_face)

                # 给该孤岛上色
                color = random_color(island_id_counter)
                island_id_counter += 1
                for f in mesh_island:
                    if len(f.loops) < 3:
                        continue
                    uvs = [loop[uv_layer].uv for loop in f.loops]
                    pts = [(uv[0] * width, (1 - uv[1]) * height) for uv in uvs]
                    for i in range(1, len(pts) - 1):
                        draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀处理
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出网格孤岛图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeFaceIDImage(Operator, ExportHelper):
    """导出相邻面不同色的UV图像,用于面ID选择"""
    bl_idname = "ho.uvtools_bakefaceid_image"
    bl_label = "导出UV面ID图"
    bl_description = "将所有选中物体的面着色,相邻面使用不同颜色,导出为UV贴图图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    # type: ignore # 不限制后缀，由用户选择格式
    filter_glob: StringProperty(default="*", options={'HIDDEN'}) # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        # 初始颜色使用颜色
        self.palette = [
            (255,   0,   0, 255),       # 红
            (0, 255,   0, 255),       # 绿
            (0,   0, 255, 255),       # 蓝
            (255, 255,   0, 255),       # 黄
            (255,   0, 255, 255),       # 品红
            (0, 255, 255, 255),       # 青
            (255, 128,   0, 255),       # 橙
            (128,   0, 255, 255),       # 紫
            (128, 128, 128, 255),       # 灰
            (255, 192, 203, 255),       # 粉红
            (128, 128,   0, 255),       # 橄榄绿
            (0, 128, 128, 255),       # 深青
            (128,   0,   0, 255),       # 深红
            (0, 128,   0, 255),       # 深绿
            (0,   0, 128, 255),       # 深蓝
            (255, 165,   0, 255),       # 橘黄
        ]

        def expand_palette(pal):
            """将颜色列表细分一倍（插值），保持颜色对比度"""
            new_palette = []
            for i in range(len(pal)):
                c1 = pal[i]
                c2 = pal[(i + 1) % len(pal)]
                new_palette.append(c1)
                # 插值
                blended = tuple((a + b) // 2 for a, b in zip(c1, c2))
                new_palette.append(blended)
            return new_palette

        def build_strict_adjacency(bm):
            vert_faces_map = {v: set() for v in bm.verts}
            for f in bm.faces:
                for v in f.verts:
                    vert_faces_map[v].add(f)

            face_neighbors = {}
            for f in bm.faces:
                neighbors = set()
                for v in f.verts:
                    neighbors.update(vert_faces_map[v])
                neighbors.discard(f)
                face_neighbors[f] = neighbors
            return face_neighbors

        def greedy_coloring(faces, neighbors, palette, max_attempts=5):
            for attempt in range(max_attempts):
                color_table = {}
                failed = False
                for f in faces:
                    used_colors = set(color_table.get(n, None)
                                      for n in neighbors[f])
                    for c in range(len(palette)):
                        if c not in used_colors:
                            color_table[f] = c
                            break
                    else:
                        failed = True
                        break
                if not failed:
                    return color_table
                palette[:] = expand_palette(palette)
                self.report({'WARNING'}, f"颜色不足，已扩展颜色数量到 {len(palette)}")
            return None

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            neighbors = build_strict_adjacency(bm)
            face_colors = greedy_coloring(bm.faces, neighbors, self.palette)
            if face_colors is None:
                self.report({'ERROR'}, f"{obj.name}：自动扩展颜色仍不足，导出失败")
                bm.free()
                eval_obj.to_mesh_clear()
                return {'CANCELLED'}

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue
                uvs = [loop[uv_layer].uv for loop in face.loops]
                pts = [(uv[0] * width, (1-uv[1]) * height) for uv in uvs]
                color_idx = face_colors[face]
                color = self.palette[color_idx]
                for i in range(1, len(pts) - 1):
                    tri = [pts[0], pts[i], pts[i + 1]]
                    draw.polygon(tri, fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀每个区域颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出ID图像:{final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeObjectIDImage(Operator, ExportHelper):
    """将每个选中物体填充为不同颜色并导出为一张图像"""
    bl_idname = "ho.uvtools_bake_objectid_image"
    bl_label = "导出物体ID图"
    bl_description = "将每个选中物体的UV填充为不同颜色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore

    image_format: EnumProperty(
        name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    )  # type: ignore

    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)
        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        for idx, obj in enumerate(selected_objs):
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.verify()
            bm.faces.ensure_lookup_table()

            color = random_color(idx)

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue
                uvs = [loop[uv_layer].uv for loop in face.loops]
                pts = [(uv[0] * width, (1 - uv[1]) * height) for uv in uvs]
                for i in range(1, len(pts) - 1):
                    draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀边缘颜色
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出物体ID图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeMaterialIDImage(Operator, ExportHelper):
    """导出按材质区分颜色的UV ID图"""
    bl_idname = "ho.uvtools_bake_materialid_image"
    bl_label = "导出材质ID图"
    bl_description = "将每个材质的UV区域填充为不同颜色并导出为一张图像"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(
        name="图像格式",
        items=[
            ('PNG', "PNG", ""),
            ('JPEG', "JPEG", "")
        ],
        default='PNG'
    )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        def random_color(seed):
            random.seed(seed)
            return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255), 255)

        def material_key(mesh, material_index):
            if 0 <= material_index < len(mesh.materials):
                mat = mesh.materials[material_index]
                if mat is not None:
                    return ("MATERIAL", mat.as_pointer())
            return ("NO_MATERIAL", material_index)

        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        pil_img = Image.new("RGBA", (width, height),
                            (0, 0, 0, background_alpha_255))
        draw = ImageDraw.Draw(pil_img)

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        material_colors = {}
        skipped_objects = []

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            try:
                uv_layer = mesh.uv_layers.active
                if uv_layer is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                for poly in mesh.polygons:
                    loop_indices = poly.loop_indices
                    if len(loop_indices) < 3:
                        continue

                    key = material_key(mesh, poly.material_index)
                    color = material_colors.get(key)
                    if color is None:
                        color = random_color(len(material_colors))
                        material_colors[key] = color

                    pts = []
                    for loop_index in loop_indices:
                        uv = uv_layer.data[loop_index].uv
                        pts.append((uv.x * width, (1.0 - uv.y) * height))

                    for i in range(1, len(pts) - 1):
                        draw.polygon([pts[0], pts[i], pts[i + 1]], fill=color)
            finally:
                eval_obj.to_mesh_clear()

        if not material_colors:
            self.report({'ERROR'}, "没有可导出的材质ID")
            return {'CANCELLED'}

        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出材质ID图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeIslandUVMapImage(Operator, ExportHelper):
    """导出每个UV岛各自归一化的局部UV坐标图"""
    bl_idname = "ho.uvtools_bake_island_uvmap_image"
    bl_label = "导出岛UV图"
    bl_description = "每个UV岛单独归一化到0-1并写入RG通道, R=U, G=V"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 3] = background_alpha_255

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        skipped_objects = []

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer is None:
                skipped_objects.append(f"{obj.name}(无UV)")
                bm.free()
                eval_obj.to_mesh_clear()
                continue

            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            for island_faces in find_uv_islands(bm, uv_layer):
                island_uvs = [
                    loop[uv_layer].uv
                    for face in island_faces
                    for loop in face.loops
                ]
                if not island_uvs:
                    continue

                min_u = min(uv.x for uv in island_uvs)
                max_u = max(uv.x for uv in island_uvs)
                min_v = min(uv.y for uv in island_uvs)
                max_v = max(uv.y for uv in island_uvs)
                u_range = max_u - min_u
                v_range = max_v - min_v
                if abs(u_range) < 1e-8:
                    u_range = 1.0
                if abs(v_range) < 1e-8:
                    v_range = 1.0

                for face in island_faces:
                    if len(face.loops) < 3:
                        continue

                    uvs = [loop[uv_layer].uv.copy() for loop in face.loops]
                    pts = [(uv.x * width, (1.0 - uv.y) * height)
                           for uv in uvs]
                    local_uvs = [((uv.x - min_u) / u_range,
                                  (uv.y - min_v) / v_range)
                                 for uv in uvs]

                    for i in range(1, len(pts) - 1):
                        fill_local_uv_triangle(
                            img_arr,
                            [pts[0], pts[i], pts[i + 1]],
                            [local_uvs[0], local_uvs[i], local_uvs[i + 1]]
                        )

                island_count += 1

            bm.free()
            eval_obj.to_mesh_clear()

        if island_count == 0:
            self.report({'ERROR'}, "没有可导出的UV岛")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出岛UV图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeWorldSpaceTBFlowMapImage(Operator, ExportHelper):
    """导出基于TBN流向的每岛归一化UV平面坐标图"""
    bl_idname = "ho.uvtools_bake_world_space_tbflowmap_image"
    bl_label = "导出World SpaceTBFlowMap"
    bl_description = "用世界坐标轴在T/B平面里的流向作为每个UV岛的局部B轴,按岛归一化输出RG坐标"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    flow_axis: EnumProperty(name="世界流向轴",
                            items=TB_FLOW_MAP_AXIS_ITEMS,
                            default='WORLD_Z'
                            )  # type: ignore
    flip_t: BoolProperty(name="翻转R", default=False)  # type: ignore
    flip_b: BoolProperty(name="翻转G", default=False)  # type: ignore
    coord_iterations: IntProperty(
        name="坐标迭代次数", default=32, min=4, max=256,
        description="弯曲坐标轴场的NumPy迭代次数,越高越贴合TB流向但越慢")  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "flow_axis")
        layout.prop(self, "flip_t")
        layout.prop(self, "flip_b")
        layout.prop(self, "coord_iterations")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 3] = background_alpha_255

        flow_axis = get_tb_flow_map_axis_vector(self.flow_axis)
        if flow_axis is None:
            self.report({'ERROR'}, "无效的世界流向轴")
            return {'CANCELLED'}

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        exported_tris = 0
        skipped_objects = []
        uv_min_u = float("inf")
        uv_min_v = float("inf")
        uv_max_u = float("-inf")
        uv_max_v = float("-inf")
        out_of_range_tris = 0

        for obj in selected_objs:
            loop_flows = {}
            polygon_data = {}
            polygon_points = {}
            island_groups = []
            object_ready = True

            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            tangents_ready = False
            try:
                uv_layer = mesh.uv_layers.active
                if uv_layer is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    object_ready = False
                    continue

                for poly in mesh.polygons:
                    loop_indices = list(poly.loop_indices)
                    if len(loop_indices) < 3:
                        continue

                    uvs = []
                    for loop_index in loop_indices:
                        uv = uv_layer.data[loop_index].uv.copy()
                        uv_min_u = min(uv_min_u, uv.x)
                        uv_min_v = min(uv_min_v, uv.y)
                        uv_max_u = max(uv_max_u, uv.x)
                        uv_max_v = max(uv_max_v, uv.y)
                        uvs.append(uv)

                    polygon_data[poly.index] = (loop_indices, uvs)
                    polygon_points[poly.index] = [
                        (uv.x * width, (1.0 - uv.y) * height)
                        for uv in uvs
                    ]

                island_groups = find_mesh_uv_islands(mesh, uv_layer)
                try:
                    mesh.calc_tangents(uvmap=uv_layer.name)
                    tangents_ready = True
                except RuntimeError as exc:
                    skipped_objects.append(f"{obj.name}(切线失败:{exc})")
                    object_ready = False
                    continue

                tangent_matrix = eval_obj.matrix_world.to_3x3()
                for _poly_index, (loop_indices, _uvs) in polygon_data.items():
                    for loop_index in loop_indices:
                        loop_flows[loop_index] = calc_loop_tb_flow(
                            mesh.loops[loop_index],
                            flow_axis,
                            tangent_matrix
                        )
            finally:
                if tangents_ready:
                    try:
                        mesh.free_tangents()
                    except RuntimeError:
                        pass
                eval_obj.to_mesh_clear()

            if not object_ready:
                continue

            for island_polygon_indices in island_groups:
                island_polygon_indices = [
                    polygon_index
                    for polygon_index in island_polygon_indices
                    if polygon_index in polygon_points
                ]
                if not island_polygon_indices:
                    continue

                island_points = [
                    point
                    for polygon_index in island_polygon_indices
                    for point in polygon_points[polygon_index]
                ]
                min_x = max(0, int(np.floor(min(point[0] for point in island_points))))
                max_x = min(width - 1, int(np.ceil(max(point[0] for point in island_points))))
                min_y = max(0, int(np.floor(min(point[1] for point in island_points))))
                max_y = min(height - 1, int(np.ceil(max(point[1] for point in island_points))))
                if min_x > max_x or min_y > max_y:
                    continue

                crop_width = max_x - min_x + 1
                crop_height = max_y - min_y + 1
                island_mask = np.zeros((crop_height, crop_width), dtype=bool)
                island_flow_x = np.zeros((crop_height, crop_width), dtype=np.float32)
                island_flow_y = np.zeros((crop_height, crop_width), dtype=np.float32)
                island_ids = np.zeros((crop_height, crop_width), dtype=np.int32)
                island_triangles = 0

                for polygon_index in island_polygon_indices:
                    polygon = polygon_data.get(polygon_index)
                    if polygon is None:
                        continue

                    loop_indices, uvs = polygon
                    pts = polygon_points[polygon_index]
                    flows = [loop_flows[loop_index] for loop_index in loop_indices]

                    for i in range(1, len(loop_indices) - 1):
                        tri_pts = [pts[0], pts[i], pts[i + 1]]
                        local_tri_pts = [
                            (point[0] - min_x, point[1] - min_y)
                            for point in tri_pts
                        ]
                        tri_flows = [flows[0], flows[i], flows[i + 1]]
                        if any(p[0] < 0 or p[0] > width or p[1] < 0 or p[1] > height for p in tri_pts):
                            out_of_range_tris += 1
                        if rasterize_tb_flow_triangle(
                            island_mask,
                            island_flow_x,
                            island_flow_y,
                            local_tri_pts,
                            tri_flows,
                            island_ids=island_ids,
                            island_id=1
                        ):
                            island_triangles += 1

                if island_triangles == 0 or not island_mask.any():
                    continue

                channels = tb_flow_build_island_channels(
                    island_mask,
                    island_flow_x,
                    island_flow_y,
                    island_ids=island_ids,
                    island_id=1,
                    image_width=width,
                    image_height=height,
                    coord_iterations=self.coord_iterations,
                    flip_r=self.flip_t,
                    flip_g=self.flip_b
                )
                if channels is None:
                    continue

                r, g = channels
                target = img_arr[min_y:max_y + 1, min_x:max_x + 1]
                target[island_mask, 0] = (r[island_mask] * 255.0 + 0.5).astype(np.uint8)
                target[island_mask, 1] = (g[island_mask] * 255.0 + 0.5).astype(np.uint8)
                target[island_mask, 2] = 0
                target[island_mask, 3] = 255
                island_count += 1
                exported_tris += island_triangles

        if exported_tris == 0:
            self.report({'ERROR'}, "没有可导出的TB流向图数据")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        axis_label = dict((item[0], item[1]) for item in TB_FLOW_MAP_AXIS_ITEMS).get(
            self.flow_axis, self.flow_axis)
        self.report(
            {'INFO'},
            f"已导出TB流向图: {final_path} | 参考轴={axis_label} | UV岛={island_count} | UV范围=({uv_min_u:.4f},{uv_min_v:.4f})-({uv_max_u:.4f},{uv_max_v:.4f}) | 三角={exported_tris} | 越界三角={out_of_range_tris}"
        )
        return {'FINISHED'}


class OT_UVTools_BakeGravityFieldMapImage(Operator, ExportHelper):
    """导出给Unity粒子/雨水使用的表面重力流向图"""
    bl_idname = "ho.uvtools_bake_gravity_fieldmap_image"
    bl_label = "导出Gravity FieldMap"
    bl_description = "把世界重力方向投影到每个像素的T/B平面,R/G为方向,B为投影强度"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0,
        description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    gravity_axis: EnumProperty(name="重力方向",
                               items=GRAVITY_FIELD_AXIS_ITEMS,
                               default='WORLD_NEG_Z'
                               )  # type: ignore
    strength_scale: FloatProperty(
        name="强度倍率", default=1.0, min=0.0, max=8.0,
        description="写入B通道的投影强度倍率")  # type: ignore
    flip_r: BoolProperty(name="翻转R", default=False)  # type: ignore
    flip_g: BoolProperty(name="翻转G", default=False)  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0,
        description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "gravity_axis")
        layout.prop(self, "strength_scale")
        layout.prop(self, "flip_r")
        layout.prop(self, "flip_g")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 0:2] = 128
        img_arr[:, :, 3] = background_alpha_255

        gravity_axis = get_gravity_field_axis_vector(self.gravity_axis)
        if gravity_axis is None:
            self.report({'ERROR'}, "无效的重力方向")
            return {'CANCELLED'}

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        exported_tris = 0
        skipped_objects = []
        uv_min_u = float("inf")
        uv_min_v = float("inf")
        uv_max_u = float("-inf")
        uv_max_v = float("-inf")
        out_of_range_tris = 0
        skipped_large_tris = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            tangents_ready = False
            try:
                uv_layer = mesh.uv_layers.active
                if uv_layer is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                cached_faces = []
                for poly in mesh.polygons:
                    loop_indices = list(poly.loop_indices)
                    if len(loop_indices) < 3:
                        continue

                    pts = []
                    for loop_index in loop_indices:
                        uv = uv_layer.data[loop_index].uv.copy()
                        uv_min_u = min(uv_min_u, uv.x)
                        uv_min_v = min(uv_min_v, uv.y)
                        uv_max_u = max(uv_max_u, uv.x)
                        uv_max_v = max(uv_max_v, uv.y)
                        pts.append((uv.x * width, (1.0 - uv.y) * height))

                    cached_faces.append((loop_indices, pts))

                try:
                    mesh.calc_tangents(uvmap=uv_layer.name)
                    tangents_ready = True
                except RuntimeError as exc:
                    skipped_objects.append(f"{obj.name}(切线失败:{exc})")
                    continue

                tangent_matrix = eval_obj.matrix_world.to_3x3()
                for loop_indices, pts in cached_faces:
                    gravity_flows = []
                    for loop_index in loop_indices:
                        gravity_flows.append(calc_loop_tb_flow(
                            mesh.loops[loop_index],
                            gravity_axis,
                            tangent_matrix
                        ))

                    for i in range(1, len(loop_indices) - 1):
                        tri_pts = [pts[0], pts[i], pts[i + 1]]
                        tri_flows = [
                            gravity_flows[0],
                            gravity_flows[i],
                            gravity_flows[i + 1]
                        ]
                        if any(p[0] < 0 or p[0] > width or p[1] < 0 or p[1] > height for p in tri_pts):
                            out_of_range_tris += 1
                        if rasterize_gravity_field_triangle(
                            img_arr,
                            tri_pts,
                            tri_flows,
                            strength_scale=self.strength_scale,
                            flip_r=self.flip_r,
                            flip_g=self.flip_g
                        ):
                            exported_tris += 1
                        else:
                            skipped_large_tris += 1
            finally:
                if tangents_ready:
                    try:
                        mesh.free_tangents()
                    except RuntimeError:
                        pass
                eval_obj.to_mesh_clear()

        if exported_tris == 0:
            self.report({'ERROR'}, "没有可导出的重力场数据")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        axis_label = dict((item[0], item[1]) for item in GRAVITY_FIELD_AXIS_ITEMS).get(
            self.gravity_axis, self.gravity_axis)
        self.report(
            {'INFO'},
            f"已导出Gravity FieldMap: {final_path} | 重力方向={axis_label} | UV范围=({uv_min_u:.4f},{uv_min_v:.4f})-({uv_max_u:.4f},{uv_max_v:.4f}) | 三角={exported_tris} | 越界三角={out_of_range_tris} | 跳过大三角={skipped_large_tris}"
        )
        return {'FINISHED'}


class OT_UVTools_BakeSixDirectionVisibilityImage(Operator, ExportHelper):
    """导出世界六方向光照可见度,两张RGB分别存+XYZ和-XYZ"""
    bl_idname = "ho.uvtools_bake_six_direction_visibility_image"
    bl_label = "导出六向可见度Lightmap"
    bl_description = "从UV texel还原真实3D世界位置,用Blender场景ray_cast烘焙世界+/-XYZ六方向可见度"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="Lightmap宽度", default=1024, min=1)  # type: ignore
    image_height: IntProperty(name="Lightmap高度", default=1024, min=1)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    sample_step: IntProperty(
        name="采样步长", default=1, min=1, max=16,
        description="每隔多少像素发射一次六向射线,1为逐像素最慢")  # type: ignore
    max_distance: FloatProperty(
        name="射线最大距离", default=100.0, min=0.0,
        description="超过该距离视为可见")  # type: ignore
    ray_bias: FloatProperty(
        name="法线偏移", default=0.001, min=0.0,
        description="沿真实3D表面法线偏移射线起点,避免命中当前表面")  # type: ignore
    include_visible_scene_objects: BoolProperty(
        name="考虑其他可见物体", default=True,
        description="开启时场景中其它可见物体也会遮挡射线;关闭时只考虑当前选中物体集合")  # type: ignore
    blur_radius: FloatProperty(
        name="模糊半径", default=2, min=0.0, max=64.0,
        description="导出前对可见度图做高斯模糊")  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0,
        description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "image_format")
        layout.prop(self, "sample_step")
        layout.prop(self, "max_distance")
        layout.prop(self, "ray_bias")
        layout.prop(self, "include_visible_scene_objects")
        layout.prop(self, "blur_radius")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}
        occluder_objects = None
        if not self.include_visible_scene_objects:
            occluder_objects = set(selected_objs)

        depsgraph = context.evaluated_depsgraph_get()
        surface = collect_lightmap_surface_samples(
            selected_objs, depsgraph, width, height)
        mask = surface["mask"]

        if surface["exported_tris"] == 0 or not mask.any():
            self.report({'ERROR'}, "没有可导出的六向可见度数据")
            return {'CANCELLED'}

        pos_rgb, neg_rgb = bake_six_direction_visibility(
            context.scene,
            depsgraph,
            mask,
            surface["pos_x"],
            surface["pos_y"],
            surface["pos_z"],
            surface["normal_x"],
            surface["normal_y"],
            surface["normal_z"],
            sample_step=self.sample_step,
            max_distance=self.max_distance,
            ray_bias=self.ray_bias,
            occluder_objects=occluder_objects
        )

        pos_img = finalize_six_direction_visibility_image(
            pos_rgb, mask, self.dilate_radius, self.blur_radius)
        neg_img = finalize_six_direction_visibility_image(
            neg_rgb, mask, self.dilate_radius, self.blur_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        base_path = bpy.path.abspath(self.filepath)
        lower_path = base_path.lower()
        if lower_path.endswith(".png") or lower_path.endswith(".jpg") or lower_path.endswith(".jpeg"):
            base_path = os.path.splitext(base_path)[0]
        pos_path = base_path + "_SixDir_PosXYZ" + ext
        neg_path = base_path + "_SixDir_NegXYZ" + ext
        pos_img.save(pos_path)
        neg_img.save(neg_path)

        if surface["skipped_objects"]:
            self.report({'WARNING'}, "已跳过: " + ", ".join(surface["skipped_objects"]))
        self.report(
            {'INFO'},
            f"已导出六向可见度: {pos_path} / {neg_path} | UV范围=({surface['uv_min_u']:.4f},{surface['uv_min_v']:.4f})-({surface['uv_max_u']:.4f},{surface['uv_max_v']:.4f}) | 三角={surface['exported_tris']} | 越界三角={surface['out_of_range_tris']} | 跳过大三角={surface['skipped_large_tris']}"
        )
        return {'FINISHED'}


class OT_UVTools_BakeLightCastImage(Operator, ExportHelper):
    """导出指定光源的直接光照Cast Lightmap"""
    bl_idname = "ho.uvtools_bake_light_cast_image"
    bl_label = "导出光源Cast Lightmap"
    bl_description = "从UV texel还原真实3D世界位置,按指定Light对象ray_cast烘焙直接光照"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="Lightmap宽度", default=1024, min=1)  # type: ignore
    image_height: IntProperty(name="Lightmap高度", default=1024, min=1)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    sample_step: IntProperty(
        name="采样步长", default=1, min=1, max=16,
        description="每隔多少像素发射一次光源射线,1为逐像素最慢")  # type: ignore
    max_distance: FloatProperty(
        name="Sun最大距离", default=100.0, min=0.0,
        description="Sun光源使用的射线最大距离;非Sun光源默认使用到光源的真实距离")  # type: ignore
    ray_bias: FloatProperty(
        name="法线偏移", default=0.001, min=0.0,
        description="沿真实3D表面法线偏移射线起点,避免命中当前表面")  # type: ignore
    include_visible_scene_objects: BoolProperty(
        name="考虑其他可见物体", default=True,
        description="开启时场景中其它可见物体也会遮挡射线;关闭时只考虑当前选中物体集合")  # type: ignore
    use_light_distance: BoolProperty(
        name="点/聚光按光源距离截断", default=True,
        description="开启时Point/Spot/Area只检测到光源中心的距离;关闭时也会受Sun最大距离限制")  # type: ignore
    intensity_scale: FloatProperty(
        name="强度倍率", default=1.0, min=0.0, max=100.0,
        description="写入RGB前对光源能量的缩放")  # type: ignore
    blur_radius: FloatProperty(
        name="模糊半径", default=2, min=0.0, max=64.0,
        description="导出前对光照图做高斯模糊")  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0,
        description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "ho_uvtools_light_cast_object")
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "image_format")
        layout.prop(self, "sample_step")
        layout.prop(self, "max_distance")
        layout.prop(self, "ray_bias")
        layout.prop(self, "include_visible_scene_objects")
        layout.prop(self, "use_light_distance")
        layout.prop(self, "intensity_scale")
        layout.prop(self, "blur_radius")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height

        light_obj = context.scene.ho_uvtools_light_cast_object
        if light_obj is None or light_obj.type != 'LIGHT':
            self.report({'ERROR'}, "请在光源输入口指定一个Light对象")
            return {'CANCELLED'}

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        occluder_objects = None
        if not self.include_visible_scene_objects:
            occluder_objects = set(selected_objs)

        depsgraph = context.evaluated_depsgraph_get()
        surface = collect_lightmap_surface_samples(
            selected_objs, depsgraph, width, height)
        mask = surface["mask"]

        if surface["exported_tris"] == 0 or not mask.any():
            self.report({'ERROR'}, "没有可导出的光源Cast Lightmap数据")
            return {'CANCELLED'}

        rgb = bake_light_cast(
            context.scene,
            depsgraph,
            light_obj,
            mask,
            surface["pos_x"],
            surface["pos_y"],
            surface["pos_z"],
            surface["normal_x"],
            surface["normal_y"],
            surface["normal_z"],
            sample_step=self.sample_step,
            max_distance=self.max_distance,
            ray_bias=self.ray_bias,
            occluder_objects=occluder_objects,
            intensity_scale=self.intensity_scale,
            use_light_distance=self.use_light_distance
        )
        img = finalize_light_cast_image(
            rgb, mask, self.dilate_radius, self.blur_radius, self.image_format)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        base_path = bpy.path.abspath(self.filepath)
        lower_path = base_path.lower()
        if lower_path.endswith(".png") or lower_path.endswith(".jpg") or lower_path.endswith(".jpeg"):
            base_path = os.path.splitext(base_path)[0]
        final_path = base_path + "_LightCast_" + clean_filename_part(light_obj.name) + ext
        img.save(final_path)

        if surface["skipped_objects"]:
            self.report({'WARNING'}, "已跳过: " + ", ".join(surface["skipped_objects"]))
        self.report(
            {'INFO'},
            f"已导出光源Cast Lightmap: {final_path} | 光源={light_obj.name}({light_obj.data.type}) | UV范围=({surface['uv_min_u']:.4f},{surface['uv_min_v']:.4f})-({surface['uv_max_u']:.4f},{surface['uv_max_v']:.4f}) | 三角={surface['exported_tris']} | 越界三角={surface['out_of_range_tris']} | 跳过大三角={surface['skipped_large_tris']}"
        )
        return {'FINISHED'}


class OT_UVTools_BakeIslandSDFImage(Operator, ExportHelper):
    """导出UV岛内部到边缘的欧氏距离场"""
    bl_idname = "ho.uvtools_bake_island_sdf_image"
    bl_label = "导出岛SDF图"
    bl_description = "离线烘焙UV岛内部到边缘的精确欧氏距离场,白色表示离边缘更远"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore
    max_distance: IntProperty(
        name="最大距离像素", default=64, min=1, description="达到此岛内距离后输出纯白")  # type: ignore
    temp_subdivide: BoolProperty(
        name="临时细分2级", default=False, description="烘焙前临时添加2级Subdivision Surface,导出后自动移除")  # type: ignore
    temp_subdivide_uv_smooth: EnumProperty(name="细分UV平滑",
                                           items=[
                                               ('SMOOTH_ALL', "平滑全部", "使用细分后的平滑UV形状"),
                                               ('PRESERVE_BOUNDARIES', "保留边界", "保持UV岛边界锐利")
                                           ],
                                           default='SMOOTH_ALL'
                                           )  # type: ignore
    fill_subdivide_shrink: BoolProperty(
        name="补黑细分收缩", default=True, description="对比原始UV和细分后UV,将细分后收缩掉的像素填黑")  # type: ignore
    supersample: EnumProperty(name="超采样",
                              items=[
                                  ('1', "1x", "最快"),
                                  ('2', "2x", "更平滑"),
                                  ('4', "4x", "最平滑,内存和时间开销较高")
                              ],
                              default='1'
                              )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")
        layout.prop(self, "max_distance")
        layout.prop(self, "temp_subdivide")
        if self.temp_subdivide:
            layout.prop(self, "temp_subdivide_uv_smooth")
            layout.prop(self, "fill_subdivide_shrink")
        layout.prop(self, "supersample")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        width = self.image_width
        height = self.image_height
        scale = int(self.supersample)
        hi_width = width * scale
        hi_height = height * scale
        if hi_width * hi_height > 100_000_000:
            self.report({'ERROR'}, "岛SDF超采样图过大,请降低图像尺寸或超采样倍率")
            return {'CANCELLED'}

        mask_img = Image.new("L", (hi_width, hi_height), 0)
        draw = ImageDraw.Draw(mask_img)
        base_mask_img = None
        base_draw = None
        if self.temp_subdivide and self.fill_subdivide_shrink:
            base_mask_img = Image.new("L", (hi_width, hi_height), 0)
            base_draw = ImageDraw.Draw(base_mask_img)
        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        skipped_objects = []
        undo_restore_needed = False
        temp_modifiers = []

        if self.temp_subdivide:
            undo_restore_needed = push_temp_export_undo(
                "Prepare HoTools Island SDF")

        try:
            raster_objs = selected_objs
            if base_draw is not None:
                raster_objs = []
                for obj in selected_objs:
                    base_island_count = rasterize_object_uv_mask(
                        obj, depsgraph, base_draw, hi_width, hi_height)
                    if base_island_count is None:
                        skipped_objects.append(f"{obj.name}(无UV)")
                        continue
                    raster_objs.append(obj)

            if self.temp_subdivide:
                for obj in raster_objs:
                    temp_modifier = obj.modifiers.new(
                        name="__HoTools_Temp_SDF_Subdivide__",
                        type='SUBSURF'
                    )
                    temp_modifier.levels = 2
                    temp_modifier.render_levels = 2
                    temp_modifier.subdivision_type = 'CATMULL_CLARK'
                    set_modifier_enum_if_available(
                        temp_modifier,
                        "uv_smooth",
                        self.temp_subdivide_uv_smooth
                    )
                    temp_modifiers.append((obj, temp_modifier))
                context.view_layer.update()
                depsgraph = context.evaluated_depsgraph_get()

            for obj in raster_objs:
                object_island_count = rasterize_object_uv_mask(
                    obj, depsgraph, draw, hi_width, hi_height)
                if object_island_count is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                island_count += object_island_count
        finally:
            if self.temp_subdivide:
                restored_by_undo = False
                if undo_restore_needed:
                    restored_by_undo = reset_temp_export_undo(
                        "Bake HoTools Island SDF")
                if not restored_by_undo:
                    for obj, temp_modifier in reversed(temp_modifiers):
                        try:
                            obj.modifiers.remove(temp_modifier)
                        except (ReferenceError, RuntimeError):
                            pass
                    context.view_layer.update()

        if island_count == 0:
            self.report({'ERROR'}, "没有可导出的UV岛")
            return {'CANCELLED'}

        mask = np.array(mask_img, dtype=np.uint8) > 0
        if not mask.any():
            self.report({'ERROR'}, "UV岛没有落在导出图像范围内")
            return {'CANCELLED'}

        shrink_mask = None
        if base_mask_img is not None:
            base_mask = np.array(base_mask_img, dtype=np.uint8) > 0
            shrink_mask = base_mask & ~mask

        gray = build_inner_distance_gray(mask, self.max_distance, scale)

        alpha_inside = np.full_like(gray, 255, dtype=np.uint8)
        alpha_outside = np.full_like(gray, int(self.background_alpha * 255), dtype=np.uint8)
        alpha = np.where(mask, alpha_inside, alpha_outside).astype(np.uint8)
        rgba = np.dstack((gray, gray, gray, alpha))
        pil_img = Image.fromarray(rgba, mode="RGBA")

        if scale > 1:
            pil_img = pil_img.resize((width, height), get_resample_filter())

        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)
        pil_img = apply_black_mask(pil_img, shrink_mask)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出岛SDF图像: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeUVChiralityImage(Operator, ExportHelper):
    """导出黑白UV岛手性图。"""
    bl_idname = "ho.uvtools_bake_uv_chirality_image"
    bl_label = "导出UV手性图"
    bl_description = "白色表示正常手性，黑色表示镜像，灰色表示未定义"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*", options={'HIDDEN'})  # type: ignore
    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(name="背景透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    image_format: EnumProperty(
        name="图像格式",
        items=[('PNG', "PNG", ""), ('JPEG', "JPEG", "")],
        default='PNG')  # type: ignore
    invert: BoolProperty(name="反转", default=False)  # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=1, min=0)  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "invert")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 0:3] = 128
        img_arr[:, :, 3] = background_alpha_255

        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        island_count = 0
        exported_tris = 0
        undefined_tri_count = 0
        mixed_island_count = 0
        undefined_island_count = 0
        out_of_range_tris = 0
        skipped_large_tris = 0
        skipped_objects = []
        uv_min_u = float("inf")
        uv_min_v = float("inf")
        uv_max_u = float("-inf")
        uv_max_v = float("-inf")

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            try:
                uv_layer = mesh.uv_layers.active
                if uv_layer is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                polygon_data = {}
                for poly in mesh.polygons:
                    loop_indices = list(poly.loop_indices)
                    if len(loop_indices) < 3:
                        continue

                    pts = []
                    for loop_index in loop_indices:
                        uv = uv_layer.data[loop_index].uv.copy()
                        uv_min_u = min(uv_min_u, uv.x)
                        uv_min_v = min(uv_min_v, uv.y)
                        uv_max_u = max(uv_max_u, uv.x)
                        uv_max_v = max(uv_max_v, uv.y)
                        pts.append((uv.x * width, (1.0 - uv.y) * height))
                    polygon_data[poly.index] = (poly, loop_indices, pts)

                for island_polygon_indices in find_mesh_uv_islands(mesh, uv_layer):
                    island_score = 0.0
                    island_undefined = 0
                    island_defined = 0
                    island_tris = []

                    for polygon_index in island_polygon_indices:
                        data = polygon_data.get(polygon_index)
                        if data is None:
                            continue
                        poly, loop_indices, pts = data
                        for i in range(1, len(loop_indices) - 1):
                            tri_loop_indices = [loop_indices[0], loop_indices[i], loop_indices[i + 1]]
                            tri_pts = [pts[0], pts[i], pts[i + 1]]
                            chirality = calc_uv_chirality_triangle(mesh, uv_layer, poly, tri_loop_indices)
                            if chirality is None:
                                sign = 0
                                island_undefined += 1
                                undefined_tri_count += 1
                            else:
                                sign, weight = chirality
                                island_score += sign * weight
                                island_defined += 1
                            island_tris.append((tri_pts, sign))

                    if not island_tris:
                        continue

                    if island_defined == 0:
                        island_sign = 0
                        undefined_island_count += 1
                    else:
                        island_sign = 1 if island_score >= 0.0 else -1
                        if island_undefined > 0:
                            mixed_island_count += 1

                    if self.invert:
                        island_sign *= -1

                    if island_sign > 0:
                        color = (255, 255, 255, 255)
                    elif island_sign < 0:
                        color = (0, 0, 0, 255)
                    else:
                        color = (128, 128, 128, 255)

                    for tri_pts, _tri_sign in island_tris:
                        if any(p[0] < 0 or p[0] > width or p[1] < 0 or p[1] > height for p in tri_pts):
                            out_of_range_tris += 1
                        if fill_solid_triangle(img_arr, tri_pts, color):
                            exported_tris += 1
                        else:
                            skipped_large_tris += 1
                    island_count += 1
            finally:
                eval_obj.to_mesh_clear()

        if exported_tris == 0:
            self.report({'ERROR'}, "没有可导出的UV手性数据")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report(
            {'INFO'},
            f"已导出UV手性图: {final_path} | UV岛={island_count} | 混合岛={mixed_island_count} | 未定义岛={undefined_island_count} | 未定义三角面={undefined_tri_count} | UV=({uv_min_u:.4f},{uv_min_v:.4f})-({uv_max_u:.4f},{uv_max_v:.4f}) | 三角面={exported_tris} | 越界={out_of_range_tris} | 跳过大三角={skipped_large_tris}"
        )
        return {'FINISHED'}


class OT_UVTools_BakeTangentImage(Operator, ExportHelper):
    """导出MikkTSpace切线或副切线向量图"""
    bl_idname = "ho.uvtools_bake_tangent_image"
    bl_label = "导出切线/副切线图"
    bl_description = "使用Blender计算的MikkTSpace切线空间导出切线或副切线向量图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0, description="空白区域的透明度")  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore
    vector_mode: EnumProperty(name="图片模式",
                              items=[
                                  ('TANGENT', "切线", "导出MikkTSpace Tangent"),
                                  ('BITANGENT', "副切线", "导出MikkTSpace Bitangent")
                              ],
                              default='TANGENT'
                              )  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", default=2, min=0, description="向外扩张的像素数,用于消除UV边缘缝隙")  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "vector_mode")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        width = self.image_width
        height = self.image_height
        background_alpha_255 = int(self.background_alpha * 255)
        img_arr = np.zeros((height, width, 4), dtype=np.uint8)
        img_arr[:, :, 0:3] = 128
        img_arr[:, :, 3] = background_alpha_255

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']
        if not selected_objs:
            self.report({'ERROR'}, "未选中任何网格物体")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        exported_faces = 0
        skipped_objects = []
        uv_min_u = float("inf")
        uv_min_v = float("inf")
        uv_max_u = float("-inf")
        uv_max_v = float("-inf")
        out_of_range_tris = 0
        skipped_large_tris = 0
        tangent_failed_objects = 0
        triangulated_ngon_objects = 0
        triangulated_ngon_faces = 0

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            tangents_ready = False
            try:
                uv_layer = mesh.uv_layers.active
                if uv_layer is None:
                    skipped_objects.append(f"{obj.name}(无UV)")
                    continue

                cached_faces = []
                for poly in mesh.polygons:
                    loop_indices = list(poly.loop_indices)
                    if len(loop_indices) < 3:
                        continue

                    pts = []
                    for loop_index in loop_indices:
                        uv = uv_layer.data[loop_index].uv.copy()
                        uv_min_u = min(uv_min_u, uv.x)
                        uv_min_v = min(uv_min_v, uv.y)
                        uv_max_u = max(uv_max_u, uv.x)
                        uv_max_v = max(uv_max_v, uv.y)
                        pts.append((uv.x * width, (1.0 - uv.y) * height))

                    cached_faces.append((loop_indices, pts))

                loop_vector_cache = {}
                try:
                    mesh.calc_tangents(uvmap=uv_layer.name)
                    tangents_ready = True
                    for loop_index in range(len(mesh.loops)):
                        vec = get_loop_tangent_vector(
                            mesh.loops[loop_index], self.vector_mode)
                        loop_vector_cache[loop_index] = (vec.x, vec.y, vec.z)
                except RuntimeError:
                    try:
                        mesh.free_tangents()
                    except RuntimeError:
                        pass
                    tangents_ready = False

                    try:
                        loop_vector_cache, triangulated_faces = calc_temp_triangulated_loop_vectors(
                            mesh, uv_layer, self.vector_mode)
                        triangulated_ngon_objects += 1
                        triangulated_ngon_faces += triangulated_faces
                    except RuntimeError as fallback_exc:
                        skipped_objects.append(f"{obj.name}(切线失败:{fallback_exc})")
                        tangent_failed_objects += 1
                        continue

                for loop_indices, pts in cached_faces:
                    vectors = []
                    for loop_index in loop_indices:
                        vec = loop_vector_cache.get(loop_index)
                        if vec is None:
                            continue
                        vectors.append(vec)

                    if len(vectors) != len(loop_indices):
                        continue

                    for i in range(1, len(loop_indices) - 1):
                        tri_pts = [pts[0], pts[i], pts[i + 1]]
                        tri_vectors = [vectors[0], vectors[i], vectors[i + 1]]
                        if any(p[0] < 0 or p[0] > width or p[1] < 0 or p[1] > height for p in tri_pts):
                            out_of_range_tris += 1
                        if fill_vector_triangle(img_arr, tri_pts, tri_vectors):
                            exported_faces += 1
                        else:
                            skipped_large_tris += 1
            finally:
                if tangents_ready:
                    try:
                        mesh.free_tangents()
                    except RuntimeError:
                        pass
                eval_obj.to_mesh_clear()

        if exported_faces == 0:
            self.report({'ERROR'}, "没有可导出的切线数据")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        save_img = pil_img if self.image_format == 'PNG' else pil_img.convert("RGB")
        save_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        label = "副切线" if self.vector_mode == 'BITANGENT' else "切线"
        self.report(
            {'INFO'},
            f"已导出{label}图像: {final_path} | UV范围=({uv_min_u:.4f},{uv_min_v:.4f})-({uv_max_u:.4f},{uv_max_v:.4f}) | 三角={exported_faces} | 越界三角={out_of_range_tris} | 跳过大三角={skipped_large_tris}"
        )
        return {'FINISHED'}


def linear_channel_to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * pow(c, 1.0 / 2.4) - 0.055


def linear_to_srgb(color):
    return [linear_channel_to_srgb(c) for c in color]


class OT_UVTools_BakeVertexColorImage(Operator, ExportHelper):
    """导出选中物体的顶点色贴图（无顶点色则为黑）"""
    bl_idname = "ho.uvtools_bake_vertex_color_image"
    bl_label = "导出顶点色贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        width = self.image_width
        height = self.image_height
        alpha_val = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, alpha_val))
        draw = ImageDraw.Draw(pil_img)

        depsgraph = context.evaluated_depsgraph_get()
        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        for obj in selected_objs:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()

            bm = bmesh.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            color_layer = bm.loops.layers.color.active

            if uv_layer is None:
                bm.free()
                eval_obj.to_mesh_clear()
                self.report({'WARNING'}, f"{obj.name} 没有UV,跳过")
                continue

            bm.faces.ensure_lookup_table()

            for face in bm.faces:
                if len(face.loops) < 3:
                    continue

                uvs = [loop[uv_layer].uv for loop in face.loops]
                if color_layer:
                    cols = [loop[color_layer][:4] for loop in face.loops]
                else:
                    # 没有数据就填充白色，因bl对没有颜色属性的物体显示为白色，有但是没启用的为黑色（极少见）
                    cols = [(1.0, 1.0, 1.0, 1.0)] * len(uvs)

                # 转为 0-255 范围
                cols = [
                    (
                        int(c[0] * 255),
                        int(c[1] * 255),
                        int(c[2] * 255),
                        int(c[3] * 255)
                    ) for c in cols
                ]

                px_uvs = [(int(uv.x * width), int((1.0 - uv.y) * height))
                          for uv in uvs]

                for i in range(1, len(px_uvs) - 1):
                    pts = [px_uvs[0], px_uvs[i], px_uvs[i + 1]]
                    cols_rgb = [cols[0], cols[i], cols[i + 1]]

                    # 用平均颜色填充三角形
                    avg_col = tuple(
                        int(sum(c[j] for c in cols_rgb) / 3) for j in range(4))
                    draw.polygon(pts, fill=avg_col)

            bm.free()
            eval_obj.to_mesh_clear()

        # 膨胀颜色边界
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        # 保存图像
        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        self.report({'INFO'}, f"已导出顶点色贴图: {final_path}")
        return {'FINISHED'}


class OT_UVTools_BakeActiveVertexGroupImage(Operator, ExportHelper):
    """导出选中物体的活动顶点组权重贴图，无活动顶点组则跳过"""
    bl_idname = "ho.uvtools_bake_active_vertex_group_image"
    bl_label = "导出顶点组权重贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore
    background_alpha: FloatProperty(
        name="背景透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(name="膨胀像素数", default=2, min=0)  # type: ignore
    image_format: EnumProperty(name="图像格式",
                               items=[
                                   ('PNG', "PNG", ""),
                                   ('JPEG', "JPEG", "")
                               ],
                               default='PNG'
                               )  # type: ignore

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "image_format")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        def get_vertex_group_weight(obj, vertex_index, group_index):
            try:
                return obj.vertex_groups[group_index].weight(vertex_index)
            except RuntimeError:
                return 0.0

        width = self.image_width
        height = self.image_height
        alpha_val = int(self.background_alpha * 255)

        pil_img = Image.new("RGBA", (width, height), (0, 0, 0, alpha_val))
        img_arr = np.array(pil_img)

        selected_objs = [
            obj for obj in context.selected_objects if obj.type == 'MESH']

        if not selected_objs:
            self.report({'ERROR'}, "请先选中至少一个网格物体")
            return {'CANCELLED'}

        exported_count = 0
        skipped_objects = []

        for obj in selected_objs:
            vertex_group = obj.vertex_groups.active
            if vertex_group is None:
                skipped_objects.append(f"{obj.name}(无活动顶点组)")
                continue

            mesh = obj.data
            uv_layer = mesh.uv_layers.active
            if uv_layer is None:
                skipped_objects.append(f"{obj.name}(无UV)")
                continue

            group_index = vertex_group.index

            for poly in mesh.polygons:
                loop_indices = poly.loop_indices
                if len(loop_indices) < 3:
                    continue

                uvs = []
                weights = []
                for loop_index in loop_indices:
                    loop = mesh.loops[loop_index]
                    uv = uv_layer.data[loop_index].uv
                    uvs.append((int(uv.x * width), int((1.0 - uv.y) * height)))
                    weights.append(
                        get_vertex_group_weight(obj, loop.vertex_index, group_index))

                for i in range(1, len(uvs) - 1):
                    pts = [uvs[0], uvs[i], uvs[i + 1]]
                    tri_weights = [weights[0], weights[i], weights[i + 1]]
                    fill_weight_triangle(img_arr, pts, tri_weights)

            exported_count += 1

        if exported_count == 0:
            self.report({'ERROR'}, "没有可导出的活动顶点组权重")
            return {'CANCELLED'}

        pil_img = Image.fromarray(img_arr, mode="RGBA")
        pil_img = dilate_image_with_colors(pil_img, self.dilate_radius)

        ext = ".png" if self.image_format == 'PNG' else ".jpg"
        final_path = bpy.path.abspath(self.filepath)
        if not final_path.lower().endswith(ext):
            final_path += ext
        pil_img.save(final_path)

        if skipped_objects:
            self.report({'WARNING'}, "已跳过: " + ", ".join(skipped_objects))
        self.report({'INFO'}, f"已导出活动顶点组权重贴图: {final_path}")
        return {'FINISHED'}


class OT_UVTools_FastBakeUVImage(Operator, ExportHelper):
    """快速合并导出psd模板"""
    bl_idname = "ho.uvtools_fastbake_uv_image"
    bl_label = "快速导出"
    bl_description = "快速导出多张贴图"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*.png", options={'HIDDEN'})  # type: ignore

    image_width: IntProperty(name="图像宽度", default=2048, min=1)  # type: ignore
    image_height: IntProperty(name="图像高度", default=2048, min=1)  # type: ignore

    background_alpha: FloatProperty(
        name="背景透明度", description="空白区域的透明度", default=0.0, min=0.0, max=1.0)  # type: ignore
    dilate_radius: IntProperty(
        name="膨胀像素数", description="向外扩张的像素数,用于消除UV边缘缝隙", default=2, min=0)  # type: ignore

    export_UVIslandImage: BoolProperty(
        name="UV岛", default=True)  # type: ignore
    export_MeshIslandImage: BoolProperty(
        name="Mesh岛", default=True)  # type: ignore
    export_FaceIDImage: BoolProperty(name="面", default=True)  # type: ignore
    export_ObjectIDImage: BoolProperty(name="物体", default=True)  # type: ignore
    export_MaterialIDImage: BoolProperty(name="材质", default=True)  # type: ignore
    export_LineImage: BoolProperty(name="线框", default=True)  # type: ignore

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "export_UVIslandImage", toggle=True)
        col.prop(self, "export_MeshIslandImage", toggle=True)
        col.prop(self, "export_FaceIDImage", toggle=True)
        col.prop(self, "export_ObjectIDImage", toggle=True)
        col.prop(self, "export_MaterialIDImage", toggle=True)
        col.prop(self, "export_LineImage", toggle=True)

        layout.prop(self, "image_width")
        layout.prop(self, "image_height")
        layout.prop(self, "background_alpha")
        layout.prop(self, "dilate_radius")

    def execute(self, context):
        mode_state = enter_object_mode_for_export(context)
        try:
            return self.execute_object_mode(context)
        finally:
            restore_export_mode(context, mode_state)

    def execute_object_mode(self, context):
        base_path = os.path.splitext(self.filepath)[0]
        temp_files = []
        width = self.image_width
        height = self.image_height
        alpha = self.background_alpha
        radius = self.dilate_radius

        # 调用UV岛导出
        if self.export_UVIslandImage:
            result = bpy.ops.ho.uvtools_bakeuvisland_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_UVIsland.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "UV岛导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_UVIsland.png")

         # 调用Mesh岛导出
        if self.export_MeshIslandImage:
            result = bpy.ops.ho.uvtools_bakemeshisland_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_MeshIsland.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "Mesh岛导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_MeshIsland.png")

        # 调用FaceID导出
        if self.export_FaceIDImage:
            result = bpy.ops.ho.uvtools_bakefaceid_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_FaceID.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "面ID导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_FaceID.png")

        # 调用ObjectID导出
        if self.export_ObjectIDImage:
            result = bpy.ops.ho.uvtools_bake_objectid_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_ObjectID.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "物体ID导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_ObjectID.png")

        # 调用MaterialID导出
        if self.export_MaterialIDImage:
            result = bpy.ops.ho.uvtools_bake_materialid_image(
                'EXEC_DEFAULT',
                filepath=base_path + "_MaterialID.png",
                image_width=width,
                image_height=height,
                background_alpha=alpha,
                dilate_radius=radius,
                image_format='PNG'
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "材质ID导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_MaterialID.png")

        # 调用线框导出
        if self.export_LineImage:
            result = bpy.ops.uv.export_layout(
                filepath=base_path + "_Wire.png",
                export_all=False,
                modified=False,
                mode='PNG',
                size=(width, height),
                opacity=0.0,
                check_existing=False
            )
            if result != {'FINISHED'}:
                self.report({'ERROR'}, "线框导出失败")
                return {'CANCELLED'}
            temp_files.append(base_path + "_Wire.png")

        self.report({'INFO'}, f"导出完成: {len(temp_files)} 个图像生成")
        return {'FINISHED'}


def drawBakePanel(layout: bpy.types.UILayout, context):
    box = layout.box()
    col = box.column(align=True)
    row = col.row(align=True)
    row.operator(OT_UVTools_FastBakeUVImage.bl_idname, text="", icon="FUND")
    row.operator(OT_UVTools_BakeUVIslandImage.bl_idname, text="UV岛")
    row.operator(OT_UVTools_BakeMeshIslandImage.bl_idname, text="Mesh岛")
    row.operator(OT_UVTools_BakeFaceIDImage.bl_idname, text="面ID")
    row.operator(OT_UVTools_BakeObjectIDImage.bl_idname, text="物体ID")
    row.operator(OT_UVTools_BakeMaterialIDImage.bl_idname, text="材质ID")
    row.operator("uv.export_layout", text="网格")

    row = col.row(align=True)
    row.operator(OT_UVTools_BakeVertexColorImage.bl_idname, text="活动顶点色")
    row.operator(OT_UVTools_BakeActiveVertexGroupImage.bl_idname, text="活动顶点组")

    row = col.row(align=True)
    row.operator(OT_UVTools_BakeIslandUVMapImage.bl_idname, text="每岛UV")
    row.operator(OT_UVTools_BakeIslandSDFImage.bl_idname, text="岛SDF")
    row.operator(OT_UVTools_BakeTangentImage.bl_idname, text="切/副切线")
    row.operator(OT_UVTools_BakeUVChiralityImage.bl_idname, text="UV手性")

    row = col.row(align=True)
    row.operator(OT_UVTools_BakeWorldSpaceTBFlowMapImage.bl_idname, text="TB流向图")
    row.operator(OT_UVTools_BakeGravityFieldMapImage.bl_idname, text="重力场图")

    row = col.row(align=True)
    row.prop(context.scene, "ho_uvtools_light_cast_object", text="光源")
    row.operator(OT_UVTools_BakeLightCastImage.bl_idname, text="光源Cast")
    row.operator(OT_UVTools_BakeSixDirectionVisibilityImage.bl_idname, text="六向Lightmap")



    # box = layout.box()
    # box.label(text="检查UV")

    return


cls = [OT_UVTools_BakeUVIslandImage, OT_UVTools_BakeIslandUVMapImage, OT_UVTools_BakeWorldSpaceTBFlowMapImage, OT_UVTools_BakeGravityFieldMapImage, OT_UVTools_BakeSixDirectionVisibilityImage, OT_UVTools_BakeLightCastImage, OT_UVTools_BakeIslandSDFImage, OT_UVTools_BakeUVChiralityImage, OT_UVTools_BakeTangentImage, OT_UVTools_BakeFaceIDImage, OT_UVTools_BakeObjectIDImage, OT_UVTools_BakeMaterialIDImage, OT_UVTools_BakeMeshIslandImage,
       OT_UVTools_BakeVertexColorImage,
       OT_UVTools_BakeActiveVertexGroupImage,
       OT_UVTools_FastBakeUVImage,
       ]


def register():
    for i in cls:
        bpy.utils.register_class(i)

    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)

    ureg_props()
