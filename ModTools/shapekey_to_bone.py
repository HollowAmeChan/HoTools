"""Use shape-key motion to transfer ancestor weights onto existing bones."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
import textwrap

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, PropertyGroup
from mathutils.kdtree import KDTree

from ..Utils import bone_utils
from ..Utils.bone_selection import selected_bone_names


_EPSILON = 1e-12


class ShapeKeyToBoneError(RuntimeError):
    pass


def _armature_filter(_self, obj):
    return obj.type == 'ARMATURE'


def _mesh_filter(_self, obj):
    return obj.type == 'MESH'


def _clear_analysis(settings, _context):
    settings.analysis_summary = ""
    settings.analysis_warning = ""


@dataclass
class WeightTransferPlan:
    mesh_object: bpy.types.Object
    armature_object: bpy.types.Object
    shape_key_names: tuple[str, ...]
    target_bone_names: tuple[str, ...]
    donor_names: tuple[str, ...]
    affected_indices: tuple[int, ...]
    output_weights: dict[str, list[float]]
    warnings: tuple[str, ...]
    max_motion: float

    @property
    def summary(self) -> str:
        return (
            f"形态键 {len(self.shape_key_names)}，目标骨 {len(self.target_bone_names)}，"
            f"顶点 {len(self.affected_indices)}，来源组 {len(self.donor_names)}"
        )


class PG_ShapeKeyToBoneSettings(PropertyGroup):
    armature_object: PointerProperty(
        name="骨架",
        description="提供已摆放好的目标变形骨骼",
        type=bpy.types.Object,
        poll=_armature_filter,
        update=_clear_analysis,
    )  # type: ignore
    mesh_object: PointerProperty(
        name="形态键物体",
        description="具有形态键并需要写入骨骼权重的网格物体",
        type=bpy.types.Object,
        poll=_mesh_filter,
        update=_clear_analysis,
    )  # type: ignore
    only_selected_bones: BoolProperty(
        name="仅选中骨骼",
        description="只把骨架中当前选中的变形骨作为权重目标",
        default=True,
        update=_clear_analysis,
    )  # type: ignore
    shape_key_scope: EnumProperty(
        name="形态键范围",
        items=[
            ('ACTIVE', "活动", "只使用网格当前活动的非基型形态键"),
            ('ALL', "全部", "使用全部非基型形态键的最大逐顶点位移"),
        ],
        default='ACTIVE',
        update=_clear_analysis,
    )  # type: ignore
    motion_threshold_ratio: FloatProperty(
        name="位移阈值",
        description="相对于网格世界空间包围盒对角线的最小有效位移",
        default=0.0001,
        min=0.0,
        max=0.1,
        precision=5,
        update=_clear_analysis,
    )  # type: ignore
    smooth_iterations: IntProperty(
        name="蒙版平滑",
        description="形态键位移蒙版的拓扑平滑次数",
        default=3,
        min=0,
        max=30,
        update=_clear_analysis,
    )  # type: ignore
    falloff_radius_ratio: FloatProperty(
        name="骨骼混合半径",
        description="控制相邻目标骨之间的权重混合，相对于网格包围盒对角线",
        default=0.05,
        min=0.0001,
        max=1.0,
        precision=4,
        update=_clear_analysis,
    )  # type: ignore
    transfer_strength: FloatProperty(
        name="转移强度",
        description="放大从来源祖先组转移给目标骨的总权重，最终权重会封顶为1",
        default=1.0,
        min=0.1,
        max=5.0,
        soft_min=0.5,
        soft_max=3.0,
        precision=2,
        update=_clear_analysis,
    )  # type: ignore
    max_influences: IntProperty(
        name="最大目标骨影响",
        description="一次转移中每个顶点最多分配给多少根目标骨",
        default=4,
        min=1,
        max=16,
        update=_clear_analysis,
    )  # type: ignore
    show_advanced: BoolProperty(
        name="高级设置",
        default=False,
    )  # type: ignore
    analysis_summary: StringProperty(default="")  # type: ignore
    analysis_warning: StringProperty(default="")  # type: ignore


def _selected_shape_keys(mesh_object, scope: str):
    shape_keys = mesh_object.data.shape_keys
    if shape_keys is None or len(shape_keys.key_blocks) < 2:
        raise ShapeKeyToBoneError("形态键物体没有可转换的非基型形态键")

    reference = shape_keys.reference_key
    if scope == 'ACTIVE':
        key = mesh_object.active_shape_key
        if key is None or key == reference:
            raise ShapeKeyToBoneError("请在形态键物体上激活一个非基型形态键")
        return (key,)

    return tuple(key for key in shape_keys.key_blocks if key != reference)


def _world_basis_coordinates(mesh_object):
    shape_keys = mesh_object.data.shape_keys
    basis = shape_keys.reference_key if shape_keys is not None else None
    matrix = mesh_object.matrix_world
    if basis is not None:
        return [matrix @ point.co for point in basis.data]
    return [matrix @ vertex.co for vertex in mesh_object.data.vertices]


def _bounding_diagonal(coordinates) -> float:
    if not coordinates:
        return 0.0
    minimum = coordinates[0].copy()
    maximum = coordinates[0].copy()
    for co in coordinates[1:]:
        minimum.x = min(minimum.x, co.x)
        minimum.y = min(minimum.y, co.y)
        minimum.z = min(minimum.z, co.z)
        maximum.x = max(maximum.x, co.x)
        maximum.y = max(maximum.y, co.y)
        maximum.z = max(maximum.z, co.z)
    return (maximum - minimum).length


def _coincident_groups(coordinates, diagonal: float):
    tolerance = max(diagonal * 1e-6, 1e-8)
    buckets = {}
    for index, co in enumerate(coordinates):
        key = (
            round(co.x / tolerance),
            round(co.y / tolerance),
            round(co.z / tolerance),
        )
        buckets.setdefault(key, []).append(index)
    return tuple(tuple(group) for group in buckets.values() if len(group) > 1)


def _build_adjacency(mesh_object, coordinates, coincident_groups):
    adjacency_maps = [dict() for _ in coordinates]

    def add_edge(first: int, second: int, length: float):
        previous = adjacency_maps[first].get(second)
        if previous is None or length < previous:
            adjacency_maps[first][second] = length
            adjacency_maps[second][first] = length

    for edge in mesh_object.data.edges:
        first, second = edge.vertices
        add_edge(first, second, (coordinates[first] - coordinates[second]).length)

    # UV seam duplicates are separate vertices. Zero-cost links let surface distance and
    # smoothing cross those seams without joining unrelated nearby surfaces.
    for group in coincident_groups:
        first = group[0]
        for second in group[1:]:
            add_edge(first, second, 0.0)

    return tuple(tuple(items.items()) for items in adjacency_maps)


def _sync_coincident(values, coincident_groups):
    for group in coincident_groups:
        average = sum(values[index] for index in group) / len(group)
        for index in group:
            values[index] = average


def _motion_activation(
    mesh_object,
    shape_keys,
    coordinates,
    adjacency,
    coincident_groups,
    threshold_ratio: float,
    smooth_iterations: int,
):
    vertex_count = len(coordinates)
    raw = [0.0] * vertex_count
    direction_matrix = mesh_object.matrix_world.to_3x3()

    for key in shape_keys:
        relative = key.relative_key or mesh_object.data.shape_keys.reference_key
        if len(key.data) != vertex_count or len(relative.data) != vertex_count:
            raise ShapeKeyToBoneError(f"形态键 {key.name} 的顶点数量与网格不一致")
        for index in range(vertex_count):
            displacement = direction_matrix @ (
                key.data[index].co - relative.data[index].co
            )
            raw[index] = max(raw[index], displacement.length)

    diagonal = _bounding_diagonal(coordinates)
    if diagonal <= _EPSILON:
        raise ShapeKeyToBoneError("网格包围盒尺寸为零")
    threshold = max(diagonal * threshold_ratio, _EPSILON)
    valid = sorted(value for value in raw if value > threshold)
    if not valid:
        raise ShapeKeyToBoneError("所选形态键没有超过位移阈值的顶点")

    percentile_index = min(len(valid) - 1, math.floor((len(valid) - 1) * 0.95))
    scale = max(valid[percentile_index], threshold + _EPSILON)
    activation = [
        min(1.0, max(0.0, (value - threshold) / (scale - threshold)))
        for value in raw
    ]
    _sync_coincident(activation, coincident_groups)

    for _ in range(smooth_iterations):
        smoothed = activation.copy()
        for index, neighbors in enumerate(adjacency):
            if not neighbors:
                continue
            average = sum(activation[other] for other, _length in neighbors)
            average /= len(neighbors)
            smoothed[index] = activation[index] * 0.5 + average * 0.5
        _sync_coincident(smoothed, coincident_groups)
        activation = smoothed

    return activation, max(raw), diagonal


def _read_group_weights(mesh_object, group_names):
    arrays = {name: [0.0] * len(mesh_object.data.vertices) for name in group_names}
    index_to_name = {
        group.index: group.name
        for group in mesh_object.vertex_groups
        if group.name in arrays
    }
    for vertex in mesh_object.data.vertices:
        for membership in vertex.groups:
            name = index_to_name.get(membership.group)
            if name is not None:
                arrays[name][vertex.index] = membership.weight
    return arrays


def _candidate_bones(context, settings, activation, coordinates, diagonal):
    armature = settings.armature_object
    mesh_object = settings.mesh_object
    deform_bones = tuple(bone for bone in armature.data.bones if bone.use_deform)
    warnings = []

    if settings.only_selected_bones:
        selected = set(selected_bone_names(context, armature))
        if not selected:
            raise ShapeKeyToBoneError("已开启仅选中骨骼，但目标骨架没有选中的骨骼")
        candidates = tuple(bone for bone in deform_bones if bone.name in selected)
        skipped = len(selected) - len(candidates)
        if skipped:
            warnings.append(f"跳过 {skipped} 根非变形或不可用骨骼")
    else:
        affected = [coordinates[i] for i, value in enumerate(activation) if value > 0.001]
        kd = KDTree(len(affected))
        for index, co in enumerate(affected):
            kd.insert(co, index)
        kd.balance()
        radius = max(diagonal * 0.15, _EPSILON)
        candidates = []
        for bone in deform_bones:
            head = armature.matrix_world @ bone.head_local
            _co, _index, distance = kd.find(head)
            if distance <= radius:
                candidates.append(bone)

        # In automatic mode, a weighted ancestor is a source pool, not a new target.
        existing_names = {group.name for group in mesh_object.vertex_groups}
        weighted_names = set()
        relevant_names = existing_names & {bone.name for bone in candidates}
        if relevant_names:
            current = _read_group_weights(mesh_object, relevant_names)
            affected_indices = [i for i, value in enumerate(activation) if value > 0.001]
            for name, weights in current.items():
                if any(weights[index] > _EPSILON for index in affected_indices):
                    weighted_names.add(name)
        candidates = tuple(bone for bone in candidates if bone.name not in weighted_names)
        if weighted_names:
            warnings.append(f"自动排除 {len(weighted_names)} 根已有承载权重的来源骨")

    if not candidates:
        raise ShapeKeyToBoneError("没有可用的目标变形骨骼")
    return tuple(candidates), warnings


def _resolve_donors(mesh_object, candidate_bones):
    target_names = {bone.name for bone in candidate_bones}
    existing_groups = {group.name for group in mesh_object.vertex_groups}
    donors = {}
    missing = []
    for bone in candidate_bones:
        parent = bone.parent
        while parent is not None:
            if parent.name not in target_names and parent.name in existing_groups:
                donors[bone.name] = parent.name
                break
            parent = parent.parent
        if bone.name not in donors:
            missing.append(bone.name)
    if missing:
        preview = "、".join(missing[:5])
        suffix = "…" if len(missing) > 5 else ""
        raise ShapeKeyToBoneError(
            f"以下目标骨找不到具有顶点组的非目标祖先骨：{preview}{suffix}"
        )
    return donors


def _connected_components(adjacency):
    components = []
    component_by_vertex = [-1] * len(adjacency)
    for start_index in range(len(adjacency)):
        if component_by_vertex[start_index] != -1:
            continue
        component_index = len(components)
        component = []
        stack = [start_index]
        component_by_vertex[start_index] = component_index
        while stack:
            vertex_index = stack.pop()
            component.append(vertex_index)
            for other, _edge_length in adjacency[vertex_index]:
                if component_by_vertex[other] != -1:
                    continue
                component_by_vertex[other] = component_index
                stack.append(other)
        components.append(tuple(component))
    return tuple(components), tuple(component_by_vertex)


def _component_sources(
    coordinates,
    adjacency,
    armature,
    candidate_bones,
    affected_indices,
):
    components, component_by_vertex = _connected_components(adjacency)
    affected_components = {
        component_by_vertex[index] for index in affected_indices
    }
    component_trees = {}
    for component_index in affected_components:
        component = components[component_index]
        kd = KDTree(len(component))
        for vertex_index in component:
            kd.insert(coordinates[vertex_index], vertex_index)
        kd.balance()
        component_trees[component_index] = kd

    sources = {}
    for bone in candidate_bones:
        head = armature.matrix_world @ bone.head_local
        bone_sources = []
        for component_index in sorted(affected_components):
            _co, vertex_index, distance = component_trees[component_index].find(head)
            bone_sources.append((vertex_index, distance))
        sources[bone.name] = tuple(bone_sources)
    return sources


def _multi_source_distances(adjacency, sources):
    distances = [math.inf] * len(adjacency)
    queue = []
    for source_index, initial_distance in sources:
        if initial_distance < distances[source_index]:
            distances[source_index] = initial_distance
            heapq.heappush(queue, (initial_distance, source_index))
    while queue:
        distance, vertex_index = heapq.heappop(queue)
        if distance != distances[vertex_index]:
            continue
        for other, edge_length in adjacency[vertex_index]:
            candidate = distance + edge_length
            if candidate + _EPSILON < distances[other]:
                distances[other] = candidate
                heapq.heappush(queue, (candidate, other))
    return distances


def _insert_nearest(items, entry, limit: int):
    items.append(entry)
    items.sort(key=lambda item: (item[1], item[0]))
    if len(items) > limit:
        del items[limit:]


def _solve_output_weights(
    mesh_object,
    armature,
    candidate_bones,
    donors,
    activation,
    affected_indices,
    coordinates,
    adjacency,
    diagonal,
    falloff_radius_ratio: float,
    transfer_strength: float,
    max_influences: int,
):
    target_names = tuple(bone.name for bone in candidate_bones)
    donor_names = tuple(dict.fromkeys(donors.values()))
    relevant_names = set(target_names) | set(donor_names)
    original = _read_group_weights(mesh_object, relevant_names)
    output = {name: weights.copy() for name, weights in original.items()}

    for name in relevant_names:
        group = mesh_object.vertex_groups.get(name)
        if group is not None and group.lock_weight:
            raise ShapeKeyToBoneError(f"顶点组 {name} 已锁定，无法安全转移权重")

    by_donor = {}
    for bone in candidate_bones:
        by_donor.setdefault(donors[bone.name], []).append(bone)

    sources = _component_sources(
        coordinates,
        adjacency,
        armature,
        candidate_bones,
        affected_indices,
    )
    nearest_by_donor = {
        donor: {index: [] for index in affected_indices}
        for donor in by_donor
    }
    for bone in candidate_bones:
        distances = _multi_source_distances(adjacency, sources[bone.name])
        donor = donors[bone.name]
        nearest = nearest_by_donor[donor]
        limit = min(max_influences, len(by_donor[donor]))
        for index in affected_indices:
            distance = distances[index]
            if math.isfinite(distance):
                _insert_nearest(nearest[index], (bone.name, distance), limit)

    radius = max(diagonal * falloff_radius_ratio, _EPSILON)
    transferred_indices = set()
    for donor, bones in by_donor.items():
        target_group_names = tuple(bone.name for bone in bones)
        nearest = nearest_by_donor[donor]
        for index in affected_indices:
            candidates = nearest[index]
            if not candidates:
                continue
            pool = original[donor][index]
            pool += sum(original[name][index] for name in target_group_names)
            if pool <= _EPSILON:
                continue

            transfer_ratio = min(1.0, activation[index] * transfer_strength)
            transfer_total = pool * transfer_ratio
            output[donor][index] = pool - transfer_total
            nearest_distance = candidates[0][1]
            factors = [
                math.exp(-(distance - nearest_distance) / radius)
                for _name, distance in candidates
            ]
            factor_sum = sum(factors)
            shares = {
                name: transfer_total * factor / factor_sum
                for (name, _distance), factor in zip(candidates, factors)
            }
            for name in target_group_names:
                output[name][index] = shares.get(name, 0.0)
            transferred_indices.add(index)

    if not transferred_indices:
        raise ShapeKeyToBoneError("形变区域在来源祖先组中没有可转移的权重")
    skipped_no_pool = len(set(affected_indices) - transferred_indices)
    return output, donor_names, skipped_no_pool


class ShapeKeyWeightSolver:
    @staticmethod
    def build_plan(context, settings) -> WeightTransferPlan:
        mesh_object = settings.mesh_object
        armature = settings.armature_object
        if mesh_object is None or mesh_object.type != 'MESH':
            raise ShapeKeyToBoneError("请选择形态键网格物体")
        if armature is None or armature.type != 'ARMATURE':
            raise ShapeKeyToBoneError("请选择目标骨架")
        if mesh_object.data.users > 1:
            raise ShapeKeyToBoneError("形态键网格数据被多个物体共享，请先转为单用户")

        shape_keys = _selected_shape_keys(mesh_object, settings.shape_key_scope)
        coordinates = _world_basis_coordinates(mesh_object)
        coincident = _coincident_groups(coordinates, _bounding_diagonal(coordinates))
        adjacency = _build_adjacency(mesh_object, coordinates, coincident)
        activation, max_motion, diagonal = _motion_activation(
            mesh_object,
            shape_keys,
            coordinates,
            adjacency,
            coincident,
            settings.motion_threshold_ratio,
            settings.smooth_iterations,
        )
        affected = tuple(i for i, value in enumerate(activation) if value > 0.001)
        if not affected:
            raise ShapeKeyToBoneError("平滑后没有可转移权重的顶点")

        candidate_bones, warnings = _candidate_bones(
            context,
            settings,
            activation,
            coordinates,
            diagonal,
        )
        donors = _resolve_donors(mesh_object, candidate_bones)

        if not bone_utils.object_is_deformed_by_armature(mesh_object, armature):
            warnings.append("网格尚未通过修改器或骨架父级绑定到所选骨架")

        output, donor_names, skipped_no_pool = _solve_output_weights(
            mesh_object,
            armature,
            candidate_bones,
            donors,
            activation,
            affected,
            coordinates,
            adjacency,
            diagonal,
            settings.falloff_radius_ratio,
            settings.transfer_strength,
            settings.max_influences,
        )
        if skipped_no_pool:
            warnings.append(
                f"{skipped_no_pool} 个形变顶点在来源祖先组中没有权重，已保留原状"
            )

        return WeightTransferPlan(
            mesh_object=mesh_object,
            armature_object=armature,
            shape_key_names=tuple(key.name for key in shape_keys),
            target_bone_names=tuple(bone.name for bone in candidate_bones),
            donor_names=donor_names,
            affected_indices=affected,
            output_weights=output,
            warnings=tuple(warnings),
            max_motion=max_motion,
        )


class WeightTransferTransaction:
    def __init__(self, plan: WeightTransferPlan):
        self.plan = plan
        self.mesh_object = plan.mesh_object
        self.group_names = tuple(plan.output_weights)
        self.existing_names = {
            group.name for group in self.mesh_object.vertex_groups
            if group.name in self.group_names
        }
        self.snapshot = _read_group_weights(self.mesh_object, self.group_names)
        self.locks = {
            name: self.mesh_object.vertex_groups[name].lock_weight
            for name in self.existing_names
        }

    def _write(self, weights_by_name):
        indices = list(self.plan.affected_indices)
        current_weights = _read_group_weights(
            self.mesh_object,
            tuple(weights_by_name),
        )
        for name, weights in weights_by_name.items():
            group = self.mesh_object.vertex_groups.get(name)
            if group is None:
                group = self.mesh_object.vertex_groups.new(name=name)
            group.lock_weight = False
            current = current_weights[name]
            current_members = [index for index in indices if current[index] > _EPSILON]
            if current_members:
                group.remove(current_members)
            for index in indices:
                weight = weights[index]
                if weight > _EPSILON:
                    group.add([index], min(1.0, max(0.0, weight)), 'REPLACE')

    def rollback(self):
        self._write(self.snapshot)
        for name in self.group_names:
            group = self.mesh_object.vertex_groups.get(name)
            if group is None:
                continue
            if name not in self.existing_names:
                self.mesh_object.vertex_groups.remove(group)
            else:
                group.lock_weight = self.locks[name]

    def commit(self):
        try:
            self._write(self.plan.output_weights)
        except Exception:
            self.rollback()
            raise
        for name, locked in self.locks.items():
            group = self.mesh_object.vertex_groups.get(name)
            if group is not None:
                group.lock_weight = locked
        self.mesh_object.data.update()


def _settings(context):
    return getattr(context.scene, "ho_mod_shapekey_to_bone", None)


class OP_AnalyzeShapeKeyToBoneWeights(Operator):
    bl_idname = "ho.mod_analyze_shapekey_to_bone_weights"
    bl_label = "分析形态键转权重"
    bl_description = "只读分析形态键、目标骨骼、来源顶点组和受影响顶点"

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(settings and settings.mesh_object and settings.armature_object)

    def execute(self, context):
        settings = _settings(context)
        try:
            plan = ShapeKeyWeightSolver.build_plan(context, settings)
        except ShapeKeyToBoneError as error:
            settings.analysis_summary = ""
            settings.analysis_warning = str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        except Exception as error:
            settings.analysis_summary = ""
            settings.analysis_warning = str(error)
            self.report({'ERROR'}, f"分析失败：{error}")
            return {'CANCELLED'}

        settings.analysis_summary = plan.summary
        settings.analysis_warning = "；".join(plan.warnings)
        self.report({'INFO'}, plan.summary)
        return {'FINISHED'}


class OP_TransferShapeKeyToBoneWeights(Operator):
    bl_idname = "ho.mod_transfer_shapekey_to_bone_weights"
    bl_label = "自动转移权重"
    bl_description = "按形态键位移和网格表面距离将祖先骨权重转移给目标骨骼"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(settings and settings.mesh_object and settings.armature_object)

    def execute(self, context):
        settings = _settings(context)
        mesh_object = settings.mesh_object
        previous_active = context.view_layer.objects.active
        previous_selected = tuple(obj for obj in context.selected_objects)
        previous_mode = previous_active.mode if previous_active is not None else 'OBJECT'

        try:
            if mesh_object.mode != 'OBJECT':
                context.view_layer.objects.active = mesh_object
                bpy.ops.object.mode_set(mode='OBJECT')

            plan = ShapeKeyWeightSolver.build_plan(context, settings)
            WeightTransferTransaction(plan).commit()
        except ShapeKeyToBoneError as error:
            settings.analysis_warning = str(error)
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        except Exception as error:
            settings.analysis_warning = str(error)
            self.report({'ERROR'}, f"权重转移失败：{error}")
            return {'CANCELLED'}
        finally:
            for obj in context.view_layer.objects:
                try:
                    obj.select_set(obj in previous_selected)
                except RuntimeError:
                    pass
            context.view_layer.objects.active = previous_active
            if previous_active is not None and previous_mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode=previous_mode)
                except RuntimeError:
                    pass

        settings.analysis_summary = plan.summary
        settings.analysis_warning = "；".join(plan.warnings)
        self.report({'INFO'}, f"自动转移完成：{plan.summary}")
        return {'FINISHED'}


def drawShapeKeyToBonePanel(layout, context):
    settings = _settings(context)
    if settings is None:
        return

    box = layout.box()
    box.label(text="形态键转脸骨权重", icon='SHAPEKEY_DATA')
    column = box.column(align=True)
    column.prop(settings, "armature_object")
    column.prop(settings, "mesh_object")
    row = column.row(align=True)
    row.prop(settings, "only_selected_bones", toggle=True)
    row.prop(settings, "shape_key_scope", text="")

    advanced = box.row(align=True)
    advanced.prop(
        settings,
        "show_advanced",
        text="高级设置",
        icon='TRIA_DOWN' if settings.show_advanced else 'TRIA_RIGHT',
        emboss=False,
    )
    if settings.show_advanced:
        advanced_column = box.column(align=True)
        advanced_column.prop(settings, "motion_threshold_ratio")
        advanced_column.prop(settings, "smooth_iterations")
        advanced_column.prop(settings, "transfer_strength")
        advanced_column.prop(settings, "falloff_radius_ratio")
        advanced_column.prop(settings, "max_influences")

    row = box.row(align=True)
    row.operator(OP_AnalyzeShapeKeyToBoneWeights.bl_idname, icon='VIEWZOOM')
    row.operator(OP_TransferShapeKeyToBoneWeights.bl_idname, icon='MOD_VERTEX_WEIGHT')

    if settings.analysis_summary:
        box.label(text=settings.analysis_summary, icon='INFO')
    if settings.analysis_warning:
        for line_index, line in enumerate(
            textwrap.wrap(settings.analysis_warning, width=34)
        ):
            warning = box.row()
            warning.alert = True
            warning.label(
                text=line,
                icon='ERROR' if line_index == 0 else 'BLANK1',
            )


classes = (
    PG_ShapeKeyToBoneSettings,
    OP_AnalyzeShapeKeyToBoneWeights,
    OP_TransferShapeKeyToBoneWeights,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_mod_shapekey_to_bone = PointerProperty(
        type=PG_ShapeKeyToBoneSettings,
    )


def unregister():
    if hasattr(bpy.types.Scene, "ho_mod_shapekey_to_bone"):
        del bpy.types.Scene.ho_mod_shapekey_to_bone
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
