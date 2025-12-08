from  . import  fixOperator
from bpy.types import Object
import bmesh
import re
import math
from mathutils import Vector


#TODO 物体是否是实例化物体

def check_object_shape_keys_with_modifiers(obj: Object) -> bool:
    """检查是否同时存在形态键和未应用的修改器"""
    
    if obj.type != 'MESH':
        return False
    if obj.data.shape_keys and obj.modifiers:
        return True
    return False

def check_object_armature_bones_transformed(obj: Object) -> list[str]:
    """返回所有存在非默认姿态变换的骨骼名（仅检查四元数旋转模式）"""
    if obj.type != 'ARMATURE' or not obj.pose:
        return []

    EPSILON = 1e-4
    result = []

    for bone in obj.pose.bones:
        if bone.rotation_mode != 'QUATERNION':
            continue  # 只检查四元数旋转模式

        # 检查位置
        if any(abs(v) > EPSILON for v in bone.location):
            result.append(bone.name)
            continue

        # 检查缩放
        if any(abs(v - 1.0) > EPSILON for v in bone.scale):
            result.append(bone.name)
            continue

        # 检查旋转（默认是 w=1, x=y=z=0）
        q = bone.rotation_quaternion
        if abs(q.w - 1.0) > EPSILON or any(abs(c) > EPSILON for c in (q.x, q.y, q.z)):
            result.append(bone.name)
            continue

    return result

def check_object_bones_rotation_mode_not_quaternion(obj: Object) -> list[str]:
    """返回所有旋转模式不是四元数(QUATERNION)的骨骼名称"""
    if obj.type != 'ARMATURE' or not obj.pose:
        return []

    result = []
    for bone in obj.pose.bones:
        if bone.rotation_mode != 'QUATERNION':
            result.append(bone.name)

    return result

def check_object_default_material_names(obj: Object) -> bool:
    """检查是否存在默认的材质名称(如Material, Material.001, 材质, 材质.001等)"""
    if obj.type != 'MESH':
        return False
    default_patterns = [
        r"^Material(\.\d+)?$",
        r"^材质(\.\d+)?$"
    ]
    for slot in obj.material_slots:
        if slot.material:
            name = slot.material.name
            if any(re.match(pattern, name) for pattern in default_patterns):
                return True
    return False

def check_object_invalid_bone_names(obj: Object) -> list[str]:
    """返回所有默认命名(如Bone.001)或重复命名的骨骼名"""
    if obj.type != 'ARMATURE' or not obj.data:
        return []

    result = []
    seen = set()
    for bone in obj.data.bones:
        # 默认命名：Bone, Bone.001, Bone.002 等
        if re.match(r"^Bone(\.\d+)?$", bone.name):
            result.append(bone.name)
            continue
        if re.match(r"^骨骼(\.\d+)?$", bone.name):
            result.append(bone.name)
            continue
        # 重复命名（理论上Blender不允许重复名，但保留逻辑以防外部数据导入）
        if bone.name in seen:
            result.append(bone.name)
            continue
        seen.add(bone.name)

    return result

def check_object_not_mesh(obj: Object) -> bool:
    """检查是否是非mesh/armature/empty物体(如Text、Curve等)"""
    return obj.type not in ['MESH',"ARMATURE","EMPTY"]

def check_object_data_is_shared(obj: Object) -> bool:
    """检查本物体的数据是否被多个物体使用(例如多个物体使用相同Mesh)"""
    return obj.data and obj.data.users > 1

def check_object_non_applied_mirror_modifier(obj: Object) -> bool:
    """检查镜像修改器是否未应用"""
    if obj.type != 'MESH':
        return False
    for mod in obj.modifiers:
        if mod.type == 'MIRROR':
            return True
    return False

def check_transform_object_scale_not_applied(obj: Object) -> bool:
    """检查物体的缩放是否未应用(非1)"""
    EPSILON = 1e-4
    return any(abs(s - 1.0) > EPSILON for s in obj.scale)

def check_transform_object_rotation_not_applied(obj: Object) -> bool:
    """检查物体的旋转是否未应用(非0)"""
    EPSILON = 1e-4
    return any(abs(r) > EPSILON for r in obj.rotation_euler)

def check_transform_object_location_not_applied(obj: Object) -> bool:
    """检查物体的位置是否未应用(非0)"""
    EPSILON = 1e-4
    return any(abs(t) > EPSILON for t in obj.location)

def check_geometry_has_ngons(obj: Object):
    """返回所有五边或更多边面的索引列表；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    bm = bmesh.new()
    bm.from_mesh(obj.data)  # 仅原始网格数据，不含修改器
    bm.faces.ensure_lookup_table()

    ngon_faces = [f.index for f in bm.faces if len(f.verts) > 4]

    bm.free()
    return ngon_faces

def check_geometry_overlapping_faces(obj: Object):
    """返回所有重叠面（共顶点且共面）索引列表；如果没有返回空"""
    if obj.type != 'MESH':
        return []

    mesh = obj.data
    face_keys = {}
    overlapping_faces = set()

    for poly in mesh.polygons:
        # 用排序后的顶点坐标元组作为key（精度5位小数）
        key = tuple(sorted(mesh.vertices[v].co.to_tuple(5) for v in poly.vertices))
        if key in face_keys:
            # 之前出现过，当前面和之前那个面都视为重叠
            overlapping_faces.add(poly.index)
            overlapping_faces.add(face_keys[key])
        else:
            face_keys[key] = poly.index

    return list(overlapping_faces)

def check_geometry_non_manifold_geometry(obj: Object) -> bool:
    """返回 obj.data.edges 中，被超过两个面共用的边的索引"""
    if obj.type != 'MESH':
        return []

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    bm.edges.ensure_lookup_table()

    result = [
        e.index  # 这个 index 对应 mesh.edges[e.index]
        for e in bm.edges
        if len(e.link_faces) > 2
    ]

    bm.free()
    return result

def check_geometry_unmerged_vertices(obj: Object):
    """返回所有与其它顶点距离小于阈值的可能重复顶点索引；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    threshold = 1e-5
    verts = obj.data.vertices
    unmerged = set()

    seen = []

    for i, v in enumerate(verts):
        co = v.co
        for j, s in seen:
            if (co - s).length < threshold:
                unmerged.add(i)
                unmerged.add(j)
        seen.append((i, co))

    return list(unmerged)

def check_geometry_disconnected_elements(obj: Object):
    """返回所有属于没有面的孤岛中的顶点索引列表；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()

    visited = set()
    bad_verts = set()

    def dfs(v, group):
        stack = [v]
        while stack:
            current = stack.pop()
            if current.index in visited:
                continue
            visited.add(current.index)
            group.append(current)
            linked = [e.other_vert(current) for e in current.link_edges if e.is_valid]
            stack.extend([v for v in linked if v.index not in visited])

    for v in bm.verts:
        if v.index not in visited:
            group = []
            dfs(v, group)

            # 如果这个 group 完全没有面（即为孤立点或仅由线连接）
            has_face = any(len(v.link_faces) > 0 for v in group)
            if not has_face:
                bad_verts.update(v.index for v in group)

    bm.free()
    return list(bad_verts)

def check_geometry_hidden_exists(obj: Object) -> bool:
    """检查是否存在隐藏的几何体（顶点/边/面未隐藏）"""
    if obj.type != 'MESH':
        return False
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    result = any(v.hide for v in bm.verts) or any(e.hide for e in bm.edges) or any(f.hide for f in bm.faces)
    bm.free()
    return result

def check_geometry_unnormalized_vertex_weights(obj: Object):
    """返回所有未归一化(权重和不为1)的顶点索引列表；如果全部归一化则返回空"""
    if obj.type != 'MESH':
        return []

    if not obj.vertex_groups:
        return []

    unnormalized = []

    for v in obj.data.vertices:
        total = 0.0
        for g in v.groups:
            try:
                weight = obj.vertex_groups[g.group].weight(v.index)
                total += weight
            except RuntimeError:
                continue  # 某些组可能已经不存在
        if abs(total - 1.0) > 1e-3:
            unnormalized.append(v.index)

    return unnormalized

def check_geometry_zero_weight_vertices(obj: Object):
    """返回所有不受骨骼控制的顶点索引列表（无有效骨骼权重）；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    # 获取骨架对象（modifier 优先，其次 parent）
    armature_obj = None
    for mod in obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object and mod.object.type == 'ARMATURE':
            armature_obj = mod.object
            break
    if not armature_obj and obj.parent and obj.parent.type == 'ARMATURE':
        armature_obj = obj.parent

    # 如果没有骨骼控制，也没有顶点组，则视为通过检查
    if armature_obj is None:
        return []

    # 如果有骨架控制，但没有顶点组，全部顶点都视为不合格
    if not obj.vertex_groups:
        return [v.index for v in obj.data.vertices]

    # 获取所有骨架骨骼名
    bone_names = {bone.name for bone in armature_obj.data.bones}
    group_names = {i: vg.name for i, vg in enumerate(obj.vertex_groups)}

    unweighted_verts = []

    for v in obj.data.vertices:
        influenced = False
        for g in v.groups:
            group_name = group_names.get(g.group)
            if group_name in bone_names:
                try:
                    weight = obj.vertex_groups[g.group].weight(v.index)
                    if weight > 0.0:
                        influenced = True
                        break
                except RuntimeError:
                    continue
        if not influenced:
            unweighted_verts.append(v.index)

    return unweighted_verts

def check_geometry_overly_distorted_spatialquad(obj: Object):
    """使用两种不同三角形划分法线夹角差异判断四边形畸变，返回畸变面索引列表，没有返回 None"""
    if obj.type != 'MESH':
        return None

    threshold_angle_diff = 40  # 夹角差异阈值，单位度

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()

    def calc_normal(a: Vector, b: Vector, c: Vector) -> Vector:
        # 计算三角形法线，自动归一化
        normal = (b - a).cross(c - a)
        if normal.length == 0:
            return Vector((0, 0, 0))
        return normal.normalized()

    def angle_between_vectors(u: Vector, v: Vector) -> float:
        if u.length == 0 or v.length == 0:
            return 0.0
        cos_theta = u.dot(v) / (u.length * v.length)
        cos_theta = max(min(cos_theta, 1.0), -1.0)
        return math.degrees(math.acos(cos_theta))

    distorted_face_indices = []

    for f in bm.faces:
        if len(f.verts) == 4:
            v = [vert.co for vert in f.verts]
            v0, v1, v2, v3 = v[0], v[1], v[2], v[3]

            # 划分A: (v0, v1, v2), (v0, v2, v3)
            nA1 = calc_normal(v0, v1, v2)
            nA2 = calc_normal(v0, v2, v3)
            angleA = angle_between_vectors(nA1, nA2)

            # 划分B: (v1, v2, v3), (v1, v3, v0)
            nB1 = calc_normal(v1, v2, v3)
            nB2 = calc_normal(v1, v3, v0)
            angleB = angle_between_vectors(nB1, nB2)

            # 计算两个划分的法线夹角差异
            angle_diff = abs(angleA - angleB)

            if angle_diff > threshold_angle_diff:
                distorted_face_indices.append(f.index)

    bm.free()

    if distorted_face_indices:
        return distorted_face_indices
    else:
        return None

def check_geometry_vertexgroup_over_four(obj: Object):
    """返回所有权重分配超过四个顶点组的顶点索引列表；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    too_many_groups = []
    for v in obj.data.vertices:
        if len(v.groups) > 4:
            too_many_groups.append(v.index)

    return too_many_groups

def check_uv_layer_count(obj: Object) -> bool:
    """检查物体UV层数量是否为1"""
    if obj.type != 'MESH':
        return False
    return len(obj.data.uv_layers) != 1

def check_uv_name_is_not_uvmap(obj: Object) -> bool:
    """检查活动UV层名称是否不是默认的'UVMap'"""
    if obj.type != 'MESH':
        return False
    uv_layers = obj.data.uv_layers
    if not uv_layers:
        return False  # 没有UV层则不算问题
    active_uv = uv_layers.active
    if active_uv is None:
        return False
    return active_uv.name != "UVMap"

def check_uv_out_of_bounds(obj: Object):
    """返回UV超出第一象限(0~1)范围的顶点索引列表，允许浮点误差；如果没有则返回空"""
    if obj.type != 'MESH':
        return []

    mesh = obj.data
    if not mesh.uv_layers:
        return []

    epsilon = 1e-6
    uv_layer = mesh.uv_layers.active.data

    out_of_bounds_verts = set()  # 用set避免重复索引

    for i, uv in enumerate(uv_layer):
        u, v = uv.uv.x, uv.uv.y
        if u < -epsilon or u > 1.0 + epsilon or v < -epsilon or v > 1.0 + epsilon:
            loop = mesh.loops[i]
            out_of_bounds_verts.add(loop.vertex_index)

    return list(out_of_bounds_verts)

# def check_uv_island_overlap(obj:Object):
#     """检查UV岛与岛之间是否存在重叠"""

# def check_uv_internal_overlap(obj:Object):
#     """检查单个UV岛内部是否存在自我重叠"""


ICON_MAP_LEVEL = {
            "ERROR": 'CANCEL',
            "WARNING": 'ERROR',
            "INFO": 'DOT',
        }
ICON_MAP_OBJ_TYPE = {
    'MESH': 'MESH_DATA',
    'CURVE': 'CURVE_DATA',
    'ARMATURE': 'ARMATURE_DATA',
    'EMPTY': 'EMPTY_DATA'
}

CHECK_FUNCTIONS = [
    # Object
    {
        "func": check_object_shape_keys_with_modifiers,
        "message":"修改器与形态键共存",
        "level": "WARNING",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_object_armature_bones_transformed,
        "message":"骨架在姿态模式且有骨骼变换不为空",
        "level": "ERROR",
        "select_operator_id": fixOperator.OP_Checker_selectBones.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_object_bones_rotation_mode_not_quaternion,
        "message":"骨架中有骨骼的旋转方式不是四元数",
        "level": "ERROR",
        "select_operator_id": fixOperator.OP_Checker_selectBones.bl_idname,
        "fix_operator_id": "",
    },

    {
        "func": check_object_default_material_names,
        "message":"存在默认命名的材质名(如Material, Material.001,材质,材质.001等)",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_object_invalid_bone_names,
        "message":"存在默认命名的骨骼(如Bone.001)",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectBones.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_object_not_mesh,
        "message":"非传统物体(网格/骨架/空物体)",
        "level": "WARNING",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_object_data_is_shared,
        "message":"物体数据有多个使用者",
        "level": "WARNING",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_object_non_applied_mirror_modifier,
        "message":"镜像修改器未应用",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },

    # Transform
    {
        "func": check_transform_object_scale_not_applied,
        "message":"物体缩放未应用",
        "level": "WARNING",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_transform_object_rotation_not_applied,
        "message":"物体旋转未应用",
        "level": "WARNING",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_transform_object_location_not_applied,
        "message":"物体位置未应用",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },

    # Geometry
    {
        "func": check_geometry_has_ngons,
        "message":"存在五边面/ngon",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectFace.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_overlapping_faces,
        "message":"存在重叠面",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectFace.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_non_manifold_geometry,
        "message":"存在非流形结构",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectEdges.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_unmerged_vertices,
        "message":"存在未合并重叠顶点",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_disconnected_elements,
        "message":"存在孤立顶点/线",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_hidden_exists,
        "message":"存在隐藏的网格",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_unnormalized_vertex_weights,
        "message":"存在未归一化顶点权重",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_zero_weight_vertices,
        "message":"存在没有权重的顶点",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_overly_distorted_spatialquad,
        "message":"存在过于扭曲的空间四边形",
        "level": "INFO",
        "select_operator_id": fixOperator.OP_Checker_selectFace.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_geometry_vertexgroup_over_four,
        "message":"存在超过四个顶点权重控制的顶点",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },

    # UV
    {
        "func": check_uv_name_is_not_uvmap,
        "message":"UV层名不是默认的'UVMap'",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    {
        "func": check_uv_out_of_bounds,
        "message":"活动UV层内,有顶点不在默认象限",
        "level": "WARNING",
        "select_operator_id": fixOperator.OP_Checker_selectVerts.bl_idname,
        "fix_operator_id": "",
    },
    {
        "func": check_uv_layer_count,
        "message":"UV层数量不为1",
        "level": "INFO",
        "select_operator_id": "",
        "fix_operator_id": "",
    },
    # {
    #     "func": check_uv_island_overlap,
    #     "message":"活动UV层内,岛间有重叠",
    #     "level": "WARNING",
    #     "select_operator_id": "",
    #     "fix_operator_id": "",
    # },
    # {
    #     "func": check_uv_internal_overlap,
    #     "message":"活动UV层内,有岛内部有重叠",
    #     "level": "WARNING",
    #     "select_operator_id": "",
    #     "fix_operator_id": "",
    # },
    
]


