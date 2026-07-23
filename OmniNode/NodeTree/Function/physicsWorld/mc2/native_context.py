"""Slot- and world-owned Python hosts for the MC2 native contexts."""

from __future__ import annotations

import math

import numpy as np

from .scheduler import derive_mc2_simulation_powers
from .names import MC2_INTERACTION_RESOURCE_KEY

from .center_state import (
    MC2CenterStaticMetadata,
    MC2CenterFrameShiftResult,
    MC2NegativeScaleTransitionResult,
    MC2CenterWorldPoseSpec,
    MC2CenterStepInputSpec,
    MC2CenterStepResult,
)
from .collider_frame import MC2ColliderFrameSpec
from .distance_static import MC2DistanceStaticMetadata
from .frame_state import MC2FrameInputSpec
from .native import require_mc2_native_module
from .runtime_parameters import (
    MC2RuntimeParametersV0,
    pack_mc2_runtime_parameters,
)
from .self_collision_static import (
    MC2SelfCollisionStaticMetadata,
)


MC2_NATIVE_CONTEXT_SCHEMA_VERSION = 0
MC2_STATIC_CHANGE_TOPOLOGY = 1
MC2_STATIC_CHANGE_GEOMETRY = 2
MC2_STATIC_CHANGE_SURFACE = 4
MC2_STATIC_CHANGE_CONFIG = 8
MC2_STATIC_CHANGE_SOURCE = (
    MC2_STATIC_CHANGE_TOPOLOGY
    | MC2_STATIC_CHANGE_GEOMETRY
    | MC2_STATIC_CHANGE_SURFACE
)
MC2_STATIC_CHANGE_ALL = MC2_STATIC_CHANGE_SOURCE | MC2_STATIC_CHANGE_CONFIG
MC2_DEBUG_CONSTRAINT_TETHER = 1 << 0
MC2_DEBUG_CONSTRAINT_DISTANCE = 1 << 1
MC2_DEBUG_CONSTRAINT_ANGLE = 1 << 2
MC2_DEBUG_CONSTRAINT_BENDING = 1 << 3
MC2_DEBUG_CONSTRAINT_MOTION = 1 << 4
MC2_DEBUG_CONSTRAINT_ALL = (1 << 5) - 1

_MC2_NATIVE_TIMING_LABELS = {
    "dispatch": "native · 任务与作用域准备",
    "context_prepare": "native · 上下文与调试准备",
    "center": "native · Center惯性",
    "previous_intersection": "native · 上帧交叉检测",
    "prediction": "native · 粒子预测",
    "tether": "native · Tether牵引",
    "distance_1": "native · Distance第1轮",
    "angle": "native · Angle恢复与限制",
    "bending": "native · Bending约束",
    "point_collision": "native · 点碰撞",
    "edge_collision": "native · 边碰撞",
    "distance_2": "native · Distance第2轮",
    "motion": "native · Motion约束",
    "self_primitive_update": "native · 自碰图元更新",
    "self_grid": "native · 自碰网格排序构建",
    "self_candidates": "native · 自碰候选生成去重",
    "self_contact_build": "native · 自碰接触构建更新",
    "self_solve_prepare": "native · 自碰求解准备",
    "self_solve_round_1": "native · 自碰求解第1轮",
    "self_solve_round_2": "native · 自碰求解第2轮",
    "self_solve_round_3": "native · 自碰求解第3轮",
    "self_solve_round_4": "native · 自碰求解第4轮",
    "interaction_aggregate_build": "native · 跨任务聚合构建",
    "interaction_scatter": "native · 跨任务结果分发",
    "particle_post": "native · 粒子Post",
    "final_intersection": "native · 最终交叉检测处理",
    "result_finalize": "native · 结果与历史收尾",
}


def _normalize_mc2_native_timing(value) -> dict:
    if not isinstance(value, dict) or value.get("schema") != "mc2_native_step_timing_v0":
        raise RuntimeError("MC2 native timing returned an unsupported schema")
    raw_stages = value.get("stages")
    raw_calls = value.get("calls")
    if not isinstance(raw_stages, dict) or not isinstance(raw_calls, dict):
        raise RuntimeError("MC2 native timing payload is incomplete")
    stages = {}
    calls = {}
    for key, raw_seconds in raw_stages.items():
        key = str(key)
        seconds = float(raw_seconds)
        call_count = int(raw_calls.get(key, 0))
        if not math.isfinite(seconds) or seconds < 0.0 or call_count <= 0:
            raise RuntimeError("MC2 native timing contains an invalid stage sample")
        label = _MC2_NATIVE_TIMING_LABELS.get(key, f"native · {key}")
        stages[label] = stages.get(label, 0.0) + seconds
        calls[label] = calls.get(label, 0) + call_count
    return {
        "schema": "mc2_native_step_timing_v0",
        "stages": stages,
        "calls": calls,
        "clock_reads": int(value.get("clock_reads", 0)),
        "covered_seconds": float(value.get("covered_seconds", 0.0)),
    }


class MC2NativeContextV0:
    """The slot-owned resource; the capsule never leaves this object."""

    def __init__(self, vertex_count: int, *, setup_type: str = "mesh_cloth", module=None) -> None:
        vertex_count = int(vertex_count)
        if vertex_count <= 0:
            raise ValueError("MC2 native context vertex_count must be positive")
        self._module = require_mc2_native_module(module)
        self._handle = self._module.mc2_context_v0_create(
            MC2_NATIVE_CONTEXT_SCHEMA_VERSION,
            vertex_count,
        )
        if self._handle is None:
            raise RuntimeError("mc2_context_v0_create returned None")
        try:
            setup_kinds = {"mesh_cloth": 0, "bone_cloth": 1, "bone_spring": 2}
            try:
                setup_kind = setup_kinds[str(setup_type)]
            except KeyError as exc:
                raise ValueError(f"unsupported MC2 setup_type: {setup_type!r}") from exc
            self._module.mc2_context_v0_set_setup_kind(self._handle, setup_kind)
            # MC2 always schedules Tether; the native gate only isolates scoped fixtures.
            self._module.mc2_context_v0_set_tether_enabled(self._handle, True)
        except Exception:
            self._module.mc2_context_v0_free(self._handle)
            self._handle = None
            raise
        self.vertex_count = vertex_count
        self.setup_type = str(setup_type)
        self.parameter_signature = ""
        self.proxy_signature = ""
        self.baseline_signature = ""
        self.bone_static_signature = ""
        self.distance_signature = ""
        self.bending_signature = ""
        self.center_signature = ""
        self.self_collision_signature = ""
        self.collider_signature = ""
        self.last_frame: tuple[int, int] | None = None
        self._out_positions = np.empty((vertex_count, 3), dtype=np.float32)
        self._out_rotations = np.empty((vertex_count, 4), dtype=np.float32)
        self._bone_out_positions = np.empty((vertex_count, 3), dtype=np.float32)
        self._bone_out_rotations = np.empty((vertex_count, 4), dtype=np.float32)
        self._step_basic_positions = np.empty((vertex_count, 3), dtype=np.float32)
        self._step_basic_rotations = np.empty((vertex_count, 4), dtype=np.float32)
        self._center_frame_dt: float | None = None
        self._center_step_dt: float | None = None
        self._center_now_position = np.empty(3, dtype=np.float32)
        self._center_now_rotation = np.empty(4, dtype=np.float32)
        self._center_step_vector = np.empty(3, dtype=np.float32)
        self._center_step_rotation = np.empty(4, dtype=np.float32)
        self._center_inertia_vector = np.empty(3, dtype=np.float32)
        self._center_inertia_rotation = np.empty(4, dtype=np.float32)
        self._center_rotation_axis = np.empty(3, dtype=np.float32)
        self._debug_draw_snapshot = None
        self._derived_center_pose_values = None
        self._debug_external_contacts_requested = False
        self._debug_self_contacts_requested = False
        self._debug_constraint_request_mask = 0
        self.debug_capture_count = 0
        self.debug_readback_count = 0

    @property
    def disposed(self) -> bool:
        return self._handle is None

    def __enter__(self):
        self._ensure_live()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.dispose()

    def update_parameters(
        self,
        spec: MC2RuntimeParametersV0,
        *,
        animation_pose_ratio: float = 0.0,
    ) -> None:
        if not isinstance(spec, MC2RuntimeParametersV0):
            raise TypeError("spec must be MC2RuntimeParametersV0")
        self._ensure_live()
        self.update_team_options(animation_pose_ratio)
        packed = pack_mc2_runtime_parameters(spec)
        self._module.mc2_context_v0_update_parameters(
            self._handle,
            packed["float_values"],
            packed["int_values"],
            packed["curve_values"],
        )
        self.parameter_signature = spec.parameter_signature

    def update_team_options(self, animation_pose_ratio: float) -> None:
        self._ensure_live()
        animation_pose_ratio = float(animation_pose_ratio)
        if not math.isfinite(animation_pose_ratio) or not 0.0 <= animation_pose_ratio <= 1.0:
            raise ValueError("animation_pose_ratio must be finite and in 0..1")
        self._module.mc2_context_v0_update_team_options(
            self._handle,
            animation_pose_ratio,
        )

    def classify_static_fingerprint(self, fingerprint) -> int:
        self._ensure_live()
        values = fingerprint.native_values()
        mask = int(self._module.mc2_context_v0_classify_static_fingerprint(
            self._handle,
            *values,
        ))
        if mask < 0 or mask & ~MC2_STATIC_CHANGE_ALL:
            raise RuntimeError(f"native MC2 static change mask is invalid: {mask}")
        return mask

    def update_static_fingerprint(self, fingerprint) -> None:
        self._ensure_live()
        self._module.mc2_context_v0_update_static_fingerprint(
            self._handle,
            *fingerprint.native_values(),
        )

    def _clone_config_center(self, source, static, gravity_direction):
        if not isinstance(source, MC2NativeContextV0):
            raise TypeError("source must be MC2NativeContextV0")
        if source.disposed:
            raise RuntimeError("source MC2 native context has been disposed")
        if source.vertex_count != self.vertex_count or source.setup_type != self.setup_type:
            raise ValueError("MC2 config clone context mismatch")
        self._ensure_live()
        result = self._module.mc2_context_v0_clone_config_static(
            self._handle,
            source._handle,
            np.ascontiguousarray(gravity_direction, dtype=np.float32),
            static.center.task_id,
            static.final_proxy.proxy_signature,
        )
        center = MC2CenterStaticMetadata(
            task_id=static.center.task_id,
            proxy_signature=static.center.proxy_signature,
            fixed_count=int(result["fixed_count"]),
            center_static_signature=str(result["center_static_signature"]),
        )
        return center

    def clone_bone_config_static(self, source, static, gravity_direction):
        from .setups.bone_cloth.static_build import MC2BoneClothStaticMetadata

        if not isinstance(static, MC2BoneClothStaticMetadata):
            raise TypeError("static must be compact Bone static metadata")
        center = self._clone_config_center(source, static, gravity_direction)
        self.proxy_signature = source.proxy_signature
        self.baseline_signature = source.baseline_signature
        self.bone_static_signature = source.bone_static_signature
        self.distance_signature = source.distance_signature
        self.bending_signature = source.bending_signature
        self.center_signature = center.center_static_signature
        self.self_collision_signature = source.self_collision_signature
        return static.with_center(center)

    def clone_mesh_config_static(self, source, static, gravity_direction):
        from .setups.mesh_cloth.static_build import MC2MeshClothStaticBuildResult

        if not isinstance(static, MC2MeshClothStaticBuildResult):
            raise TypeError("static must be compact Mesh static data")
        center = self._clone_config_center(source, static, gravity_direction)
        self.proxy_signature = source.proxy_signature
        self.baseline_signature = source.baseline_signature
        self.distance_signature = source.distance_signature
        self.bending_signature = source.bending_signature
        self.center_signature = center.center_static_signature
        self.self_collision_signature = source.self_collision_signature
        return static.with_center(center)

    def set_tether_enabled(self, enabled: bool) -> None:
        self._ensure_live()
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        self._module.mc2_context_v0_set_tether_enabled(self._handle, enabled)

    def update_colliders(self, spec: MC2ColliderFrameSpec) -> None:
        if not isinstance(spec, MC2ColliderFrameSpec):
            raise TypeError("spec must be MC2ColliderFrameSpec")
        self._ensure_live()
        self._module.mc2_context_v0_update_colliders(
            self._handle,
            spec.collided_by_groups,
            spec.collider_types,
            spec.collider_group_bits,
            spec.collider_centers,
            spec.collider_segment_a,
            spec.collider_segment_b,
            spec.collider_old_centers,
            spec.collider_old_segment_a,
            spec.collider_old_segment_b,
            spec.collider_radii,
        )
        self.collider_signature = spec.frame_signature

    def initialize_bone_proxy_baseline(self, bone) -> None:
        from .bone_static import MC2BoneNativeData, MC2BoneStaticSpec

        if not isinstance(bone, (MC2BoneStaticSpec, MC2BoneNativeData)):
            raise TypeError("bone must be MC2 Bone static data")
        if bone.proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native Bone static vertex count mismatch")
        baseline_registration = bone.baseline_native_registration
        proxy_registration = bone.proxy_native_registration
        if not isinstance(proxy_registration, dict) or not proxy_registration:
            raise TypeError("staged Bone proxy native registration is missing")
        if not isinstance(baseline_registration, dict) or not baseline_registration:
            raise TypeError("staged Bone baseline native registration is missing")
        self.update_proxy_derived(bone.proxy, proxy_registration)
        proxy_registration.clear()
        self.update_baseline_derived({
            "attributes": np.asarray(
                bone.proxy.vertex_attributes,
                dtype=np.uint8,
            ),
            "native_registration": baseline_registration,
        })
        baseline_registration.clear()
        self.proxy_signature = bone.proxy.proxy_signature
        self.baseline_signature = bone.baseline.baseline_signature

    def update_proxy_finalizer_derived(
        self,
        *,
        proxy,
        finalizer,
        radius_multipliers=None,
    ) -> None:
        self._ensure_live()
        proxy_registration = getattr(proxy, "native_registration", None)
        frame_registration = getattr(finalizer, "native_frame_registration", None)
        if not isinstance(proxy_registration, dict) or not isinstance(
            frame_registration, dict
        ):
            raise TypeError("staged proxy/finalizer native registration is missing")
        self.update_proxy_derived(
            proxy,
            proxy_registration,
            radius_multipliers=radius_multipliers,
        )
        proxy_registration.clear()
        self._module.mc2_context_v0_update_frame_producer_static(
            self._handle,
            frame_registration["triangle_ranges"],
            frame_registration["triangle_records"],
            frame_registration["bind_rotations"],
            frame_registration["triangle_uvs"],
            *frame_registration["owners"],
        )
        frame_registration.clear()

    def update_proxy_derived(
        self,
        proxy,
        registration: dict,
        *,
        radius_multipliers=None,
    ) -> None:
        self._ensure_live()
        if not isinstance(registration, dict) or not registration:
            raise TypeError("staged proxy native registration is missing")
        registration["attributes"][:] = np.asarray(
            proxy.vertex_attributes,
            dtype=np.uint8,
        )
        arguments = [
            self._handle,
            registration["positions"],
            registration["normals"],
            registration["tangents"],
            registration["uvs"],
            registration["attributes"],
            registration["edges"],
            registration["triangles"],
        ]
        if radius_multipliers is not None:
            values = np.ascontiguousarray(radius_multipliers, dtype=np.float32)
            if values.shape != (self.vertex_count,):
                raise ValueError("radius_multipliers must contain one value per vertex")
            if not np.all(np.isfinite(values)) or np.any(values < 0.0) or np.any(values > 1.0):
                raise ValueError("radius_multipliers must be finite values in 0..1")
            arguments.append(values)
        arguments.extend(registration["owners"])
        self._module.mc2_context_v0_update_proxy_static(*arguments)

    def update_baseline_derived(
        self,
        derived,
        *,
        finalize_attributes: bool = True,
    ) -> None:
        self._ensure_live()
        if finalize_attributes:
            self._module.mc2_context_v0_finalize_proxy_attributes(
                self._handle,
                derived["attributes"],
            )
        registration = (
            derived.get("native_registration")
            if isinstance(derived, dict)
            else getattr(derived, "native_registration", None)
        )
        if isinstance(registration, dict):
            self._module.mc2_context_v0_update_baseline_static(
                self._handle,
                registration["parents"],
                registration["child_ranges"],
                registration["child_data"],
                registration["baseline_flags"],
                registration["baseline_ranges"],
                registration["baseline_data"],
                registration["roots"],
                registration["depths"],
                registration["local_positions"],
                registration["local_rotations"],
                *registration["owners"],
            )
            return
        self._module.mc2_context_v0_update_baseline_static(
            self._handle,
            derived["parents"],
            derived["child_ranges"],
            derived["child_data"],
            derived["baseline_flags"],
            derived["baseline_ranges"],
            derived["baseline_data"],
            derived["roots"],
            np.ascontiguousarray(derived["depths"], dtype=np.float32),
            np.ascontiguousarray(derived["local_positions"], dtype=np.float32),
            np.ascontiguousarray(derived["local_rotations"], dtype=np.float32),
        )

    def update_distance_derived(self, derived: dict) -> None:
        self._ensure_live()
        arguments = (
            self._handle,
            derived["distance_ranges"],
            derived["distance_targets"],
            derived["distance_rest_signed"],
        )
        owners = (
            derived.get("_distance_ranges_owner"),
            derived.get("_distance_targets_owner"),
            derived.get("_distance_rests_owner"),
        )
        self._module.mc2_context_v0_update_distance_static(
            *arguments,
            *(owners if all(value is not None for value in owners) else ()),
        )

    def update_bending_derived(self, derived: dict) -> None:
        self._ensure_live()
        arguments = (
            self._handle,
            derived["bending_quads"],
            derived["bending_rest_angle_or_volume"],
            derived["bending_sign_or_volume"],
        )
        owners = (
            derived.get("_bending_quads_owner"),
            derived.get("_bending_rests_owner"),
            derived.get("_bending_markers_owner"),
        )
        self._module.mc2_context_v0_update_bending_static(
            *arguments,
            *(owners if all(value is not None for value in owners) else ()),
        )

    def update_self_collision_derived(self, derived: dict) -> None:
        self._ensure_live()
        arguments = (
            self._handle,
            derived["primitive_flags"],
            derived["particle_indices"],
            derived["primitive_depths"],
            int(derived["point_count"]),
            int(derived["edge_count"]),
            int(derived["triangle_count"]),
        )
        owners = (
            derived.get("_self_flags_owner"),
            derived.get("_self_indices_owner"),
            derived.get("_self_depths_owner"),
        )
        self._module.mc2_context_v0_update_self_collision_static(
            *arguments,
            *(owners if all(value is not None for value in owners) else ()),
        )

    def update_center_derived(self, derived: dict) -> None:
        self._ensure_live()
        arguments = (
            self._handle,
            derived["fixed_indices"],
            derived["local_center_position"],
            derived["initial_local_gravity_direction"],
        )
        owners = (
            derived.get("_center_fixed_owner"),
            derived.get("_center_position_owner"),
            derived.get("_center_gravity_owner"),
        )
        self._module.mc2_context_v0_update_center_static(
            *arguments,
            *(owners if all(value is not None for value in owners) else ()),
        )

    def initialize_mesh_static_from_builders(self, static) -> None:
        from .setups.mesh_cloth.static_build import MC2MeshClothStaticBuildResult

        if not isinstance(static, MC2MeshClothStaticBuildResult):
            raise TypeError("static must be MC2MeshClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native static vertex count mismatch")
        self.proxy_signature = static.final_proxy.proxy_signature
        self.baseline_signature = static.baseline.baseline.baseline_signature
        self.distance_signature = static.distance.distance_signature
        self.bending_signature = (
            static.bending.bending_signature if static.bending is not None else "empty"
        )
        self.center_signature = static.center.center_static_signature
        self.self_collision_signature = static.self_collision.static_signature

    def update_bone_static(self, static) -> None:
        from .setups.bone_cloth.static_build import MC2BoneClothStaticBuildResult

        if not isinstance(static, MC2BoneClothStaticBuildResult):
            raise TypeError("static must be MC2BoneClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native Bone static vertex count mismatch")
        if (
            self.proxy_signature != static.final_proxy.proxy_signature
            or self.baseline_signature != static.baseline.baseline_signature
        ):
            raise RuntimeError("Bone Proxy/Baseline must be staged before registration")
        if not isinstance(static.distance, MC2DistanceStaticMetadata):
            raise TypeError("staged Bone Distance metadata is required")
        if static.bending is not None:
            from .bending_static import MC2BendingStaticMetadata

            if not isinstance(static.bending, MC2BendingStaticMetadata):
                raise TypeError("staged Bone Bending metadata is required")
        if not isinstance(static.center, MC2CenterStaticMetadata):
            raise TypeError("staged Bone Center metadata is required")
        if not isinstance(static.self_collision, MC2SelfCollisionStaticMetadata):
            raise TypeError("staged Bone self-collision metadata is required")
        registration = static.bone.bone_native_registration
        if not isinstance(registration, dict) or not registration:
            raise TypeError("staged Bone registration owners are missing")
        self._module.mc2_context_v0_update_bone_static(
            self._handle,
            registration["vertex_to_vertex_ranges"],
            registration["vertex_to_vertex_data"],
            registration["vertex_to_triangle_ranges"],
            registration["vertex_to_triangle_data"],
            registration["vertex_bind_pose_positions"],
            registration["vertex_bind_pose_rotations"],
            registration["normal_adjustment_rotations"],
            registration["vertex_to_transform_rotations"],
            *registration["owners"],
        )
        registration.clear()
        if static.bending is None:
            self._module.mc2_context_v0_update_bending_static(
                self._handle,
                np.empty((0, 4), dtype=np.int32),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.int8),
            )
        self.proxy_signature = static.final_proxy.proxy_signature
        self.baseline_signature = static.baseline.baseline_signature
        self.bone_static_signature = static.bone.static_signature
        self.distance_signature = static.distance.distance_signature
        self.bending_signature = (
            static.bending.bending_signature if static.bending is not None else "empty"
        )
        self.center_signature = static.center.center_static_signature
        self.self_collision_signature = static.self_collision.static_signature

    def update_dynamic(self, frame_input: MC2FrameInputSpec) -> None:
        if not isinstance(frame_input, MC2FrameInputSpec):
            raise TypeError("frame_input must be MC2FrameInputSpec")
        if frame_input.particle_count != self.vertex_count:
            raise ValueError("MC2 native frame particle count mismatch")
        self._ensure_live()
        producer_kind = frame_input.native_producer_kind
        if producer_kind == "host":
            self._module.mc2_context_v0_update_dynamic(
                self._handle,
                frame_input.frame,
                frame_input.generation,
                frame_input.world_positions,
                frame_input.world_rotations_xyzw,
                frame_input.velocity_weight,
                frame_input.gravity_ratio,
                frame_input.scale_ratio,
                frame_input.negative_scale_sign,
                frame_input.frame_interpolation,
            )
            frame_pose = frame_input.center_frame_pose
            if frame_pose is None:
                self._derived_center_pose_values = None
            else:
                values = self._module.mc2_context_v0_derive_center_pose_raw(
                    self._handle,
                    np.ascontiguousarray(frame_pose.component_world_position, dtype=np.float32),
                    np.ascontiguousarray(
                        (frame_pose.component_world_rotation_xyzw,), dtype=np.float32
                    ),
                    np.ascontiguousarray(frame_pose.component_world_scale, dtype=np.float32),
                )
                self._derived_center_pose_values = tuple(float(value) for value in values)
        else:
            frame_pose = frame_input.center_frame_pose
            if frame_pose is None:
                raise ValueError("native-produced MC2 frame requires a component pose")
            component_position = np.ascontiguousarray(
                frame_pose.component_world_position,
                dtype=np.float32,
            )
            component_rotation = np.ascontiguousarray(
                frame_pose.component_world_rotation_xyzw,
                dtype=np.float32,
            )
            component_scale = np.ascontiguousarray(
                frame_pose.component_world_scale,
                dtype=np.float32,
            )
            common = (
                self._handle,
                frame_input.frame,
                frame_input.generation,
                frame_input.world_positions,
            )
            scalars = (
                frame_input.velocity_weight,
                frame_input.gravity_ratio,
                frame_input.scale_ratio,
                frame_input.negative_scale_sign,
                frame_input.frame_interpolation,
            )
            if producer_kind == "mesh":
                values = self._module.mc2_context_v0_update_mesh_dynamic_raw(
                    *common,
                    *scalars,
                    component_position,
                    component_rotation,
                    component_scale,
                )
            elif producer_kind == "bone":
                values = self._module.mc2_context_v0_update_bone_dynamic_raw(
                    *common,
                    frame_input.raw_pose_matrices,
                    *scalars,
                    component_position,
                    component_rotation,
                    component_scale,
                )
            else:
                raise RuntimeError(f"unknown MC2 frame producer kind: {producer_kind!r}")
            self._derived_center_pose_values = tuple(float(value) for value in values)
        self.last_frame = (frame_input.frame, frame_input.generation)
        self._center_frame_dt = None
        self._center_step_dt = None

    def derived_center_pose(self) -> MC2CenterWorldPoseSpec:
        values = self._derived_center_pose_values
        if values is None or len(values) != 10:
            raise RuntimeError("native MC2 frame has no derived Center pose")
        scale = tuple(values[7:10])
        return MC2CenterWorldPoseSpec(
            position=tuple(values[0:3]),
            rotation_xyzw=tuple(values[3:7]),
            scale=scale,
            negative_scale_direction=tuple(
                -1.0 if value < 0.0 else 1.0 for value in scale
            ),
        )

    def update_center_dynamic(self, step: MC2CenterStepInputSpec) -> None:
        if not isinstance(step, MC2CenterStepInputSpec):
            raise TypeError("step must be MC2CenterStepInputSpec")
        self._ensure_live()
        array = lambda values: np.ascontiguousarray(values, dtype=np.float32)
        self._module.mc2_context_v0_update_center_dynamic(
            self._handle,
            array(step.old_frame_world_position),
            array(step.frame_world_position),
            array(step.old_frame_world_rotation_xyzw),
            array(step.frame_world_rotation_xyzw),
            array(step.old_frame_world_scale),
            array(step.frame_world_scale),
            array(step.old_world_position),
            array(step.old_world_rotation_xyzw),
            array(step.initial_scale),
            array(step.negative_scale_direction),
            step.distance_weight,
            step.frame_interpolation,
            step.velocity_weight,
        )
        self._center_frame_dt = float(step.simulation_delta_time)
        self._center_step_dt = self._center_frame_dt

    def update_step_interpolation(self, frame_interpolation: float) -> None:
        self._ensure_live()
        frame_interpolation = float(frame_interpolation)
        if not math.isfinite(frame_interpolation) or not 0.0 <= frame_interpolation <= 1.0:
            raise ValueError("frame_interpolation must be finite and in 0..1")
        if self._center_frame_dt is None:
            raise RuntimeError("step interpolation requires a complete Center frame update")
        self._module.mc2_context_v0_update_step_interpolation(
            self._handle,
            frame_interpolation,
        )
        self._center_step_dt = self._center_frame_dt

    def apply_center_frame_shift(
        self,
        pivot,
        result: MC2CenterFrameShiftResult,
    ) -> None:
        if not isinstance(result, MC2CenterFrameShiftResult):
            raise TypeError("result must be MC2CenterFrameShiftResult")
        self._ensure_live()
        array = lambda values: np.ascontiguousarray(values, dtype=np.float32)
        self._module.mc2_context_v0_apply_center_frame_shift(
            self._handle,
            array(pivot),
            array(result.frame_component_shift_vector),
            array(result.frame_component_shift_rotation_xyzw),
        )

    def apply_center_negative_scale_teleport(
        self,
        result: MC2NegativeScaleTransitionResult,
    ) -> None:
        if not isinstance(result, MC2NegativeScaleTransitionResult):
            raise TypeError("result must be MC2NegativeScaleTransitionResult")
        if not result.active:
            return
        self._ensure_live()
        matrix = np.ascontiguousarray(
            result.center_negative_matrix,
            dtype=np.float32,
        )
        self._module.mc2_context_v0_apply_center_negative_scale_teleport(
            self._handle,
            matrix,
        )

    def apply_task_teleport(self) -> dict:
        self._ensure_live()
        result = self._module.mc2_context_v0_apply_task_teleport(
            self._handle,
        )
        if not isinstance(result, dict):
            raise RuntimeError("MC2 native task teleport returned an invalid result")
        return result

    def reset(self) -> None:
        self._ensure_live()
        self._module.mc2_context_v0_reset(self._handle)
        self._center_frame_dt = None
        self._center_step_dt = None

    def step_no_collision(self, dt: float, *, is_final_substep: bool = True) -> None:
        self._ensure_live()
        dt = float(dt)
        if self._center_step_dt is not None and not math.isclose(
            dt, self._center_step_dt, rel_tol=0.0, abs_tol=1.0e-9
        ):
            raise ValueError("Center step simulation_delta_time does not match native step dt")
        powers = derive_mc2_simulation_powers(dt)
        self._module.mc2_context_v0_step(
            self._handle,
            dt,
            powers.distance_bending,
            powers.integration,
            powers.angle,
            bool(is_final_substep),
        )
        self._center_step_dt = None

    def read(self) -> tuple[np.ndarray, np.ndarray]:
        self._ensure_live()
        self._module.mc2_context_v0_read(
            self._handle,
            self._out_positions,
            self._out_rotations,
        )
        return self._out_positions, self._out_rotations

    def read_bone_output(self) -> tuple[np.ndarray, np.ndarray]:
        self._ensure_live()
        self._module.mc2_context_v0_read_bone_output(
            self._handle,
            self._bone_out_positions,
            self._bone_out_rotations,
        )
        return self._bone_out_positions, self._bone_out_rotations

    def read_step_basic(self) -> tuple[np.ndarray, np.ndarray]:
        self._ensure_live()
        self._module.mc2_context_v0_read_step_basic(
            self._handle,
            self._step_basic_positions,
            self._step_basic_rotations,
        )
        return self._step_basic_positions, self._step_basic_rotations

    def read_center_step(self) -> MC2CenterStepResult:
        self._ensure_live()
        scalar = self._module.mc2_context_v0_read_center_step(
            self._handle,
            self._center_now_position,
            self._center_now_rotation,
            self._center_step_vector,
            self._center_step_rotation,
            self._center_inertia_vector,
            self._center_inertia_rotation,
            self._center_rotation_axis,
        )
        vector = lambda values: tuple(float(value) for value in values)
        return MC2CenterStepResult(
            frame_interpolation=float(scalar["frame_interpolation"]),
            now_world_position=vector(self._center_now_position),
            now_world_rotation_xyzw=vector(self._center_now_rotation),
            step_vector=vector(self._center_step_vector),
            step_rotation_xyzw=vector(self._center_step_rotation),
            step_move_inertia_ratio=float(scalar["step_move_inertia_ratio"]),
            step_rotation_inertia_ratio=float(scalar["step_rotation_inertia_ratio"]),
            inertia_vector=vector(self._center_inertia_vector),
            inertia_rotation_xyzw=vector(self._center_inertia_rotation),
            angular_velocity=float(scalar["angular_velocity"]),
            rotation_axis=vector(self._center_rotation_axis),
            scale_ratio=float(scalar["scale_ratio"]),
            gravity_dot=float(scalar["gravity_dot"]),
            gravity_ratio=float(scalar["gravity_ratio"]),
            velocity_weight=float(scalar["velocity_weight"]),
            blend_weight=float(scalar["blend_weight"]),
        )

    def inspect(self) -> dict:
        if self._handle is None:
            return {
                "schema": "mc2_context_v0",
                "schema_version": MC2_NATIVE_CONTEXT_SCHEMA_VERSION,
                "vertex_count": self.vertex_count,
                "released": True,
            }
        result = dict(self._module.mc2_context_v0_inspect(self._handle))
        result["debug_capture_count"] = self.debug_capture_count
        result["debug_readback_count"] = self.debug_readback_count
        return result

    def set_debug_external_contacts(self, requested: bool) -> None:
        self._ensure_live()
        requested = bool(requested)
        if requested == self._debug_external_contacts_requested:
            return
        self._module.mc2_context_v0_set_debug_external_contacts(
            self._handle,
            requested,
        )
        self._debug_external_contacts_requested = requested

    def set_debug_self_contacts(self, requested: bool) -> None:
        self._ensure_live()
        requested = bool(requested)
        if requested == self._debug_self_contacts_requested:
            return
        self._module.mc2_context_v0_set_debug_self_contacts(
            self._handle,
            requested,
        )
        self._debug_self_contacts_requested = requested

    def set_debug_constraint_results(self, request_mask: int) -> None:
        self._ensure_live()
        request_mask = int(request_mask)
        if request_mask < 0 or request_mask & ~MC2_DEBUG_CONSTRAINT_ALL:
            raise ValueError("MC2 constraint debug mask has unsupported bits")
        if request_mask == self._debug_constraint_request_mask:
            return
        self._module.mc2_context_v0_set_debug_constraint_results(
            self._handle,
            request_mask,
        )
        self._debug_constraint_request_mask = request_mask

    @property
    def has_debug_capture_request(self) -> bool:
        return (
            self._debug_external_contacts_requested
            or self._debug_self_contacts_requested
            or self._debug_constraint_request_mask != 0
        )

    def clear_debug_capture_requests(self) -> None:
        self.set_debug_external_contacts(False)
        self.set_debug_self_contacts(False)
        self.set_debug_constraint_results(0)

    @staticmethod
    def _debug_array(values) -> np.ndarray:
        result = np.array(values, copy=True, order="C")
        result.flags.writeable = False
        return result

    def refresh_debug_draw_snapshot(
        self,
        *,
        include_baseline: bool = False,
        include_step_basic: bool = False,
        include_motion_base: bool = False,
        include_angle_restoration: bool = False,
        include_angle_limit: bool = False,
        include_teleport_threshold: bool = False,
        include_teleport_status: bool = False,
        include_dynamics: bool = False,
        include_distance_tether: bool = False,
        include_bending: bool = False,
        include_constraint_results: bool = False,
        include_external_contacts: bool = False,
        include_self_primitives: bool = False,
        include_self_grid: bool = False,
        include_self_candidates: bool = False,
        include_self_contacts: bool = False,
    ) -> dict:
        self._ensure_live()
        info = self.inspect()
        positions, rotations = self.read()
        readbacks = 1
        snapshot = {
            "source": "cpp_context",
            "schema": "mc2_debug_native_v0",
            "native": info,
            "positions": self._debug_array(positions),
            "rotations_xyzw": self._debug_array(rotations),
        }
        if include_baseline:
            parents = np.empty((self.vertex_count,), dtype=np.int32)
            roots = np.empty((self.vertex_count,), dtype=np.int32)
            depths = np.empty((self.vertex_count,), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_baseline(
                self._handle, parents, roots, depths
            )
            snapshot["baseline"] = {
                "parent_indices": self._debug_array(parents),
                "root_indices": self._debug_array(roots),
                "depths": self._debug_array(depths),
            }
            readbacks += 1
        if include_step_basic and bool(info.get("step_basic_ready", False)):
            basic_positions, basic_rotations = self.read_step_basic()
            snapshot["step_basic_positions"] = self._debug_array(basic_positions)
            snapshot["step_basic_rotations_xyzw"] = self._debug_array(basic_rotations)
            readbacks += 1
        if include_motion_base and bool(info.get("step_basic_ready", False)):
            motion_base_positions = np.empty((self.vertex_count, 3), dtype=np.float32)
            motion_base_rotations = np.empty((self.vertex_count, 4), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_motion_base(
                self._handle,
                motion_base_positions,
                motion_base_rotations,
            )
            snapshot.update({
                "motion_base_positions": self._debug_array(motion_base_positions),
                "motion_base_rotations_xyzw": self._debug_array(motion_base_rotations),
            })
            readbacks += 1
        if include_angle_restoration and bool(info.get("step_basic_ready", False)):
            angle_targets = np.empty((self.vertex_count, 3), dtype=np.float32)
            angle_vectors = np.empty((self.vertex_count, 3), dtype=np.float32)
            angle_valid = np.empty((self.vertex_count,), dtype=np.uint8)
            self._module.mc2_context_v0_read_debug_angle_restoration(
                self._handle,
                angle_targets,
                angle_vectors,
                angle_valid,
            )
            snapshot.update({
                "angle_restoration_target_positions": self._debug_array(angle_targets),
                "angle_restoration_target_vectors": self._debug_array(angle_vectors),
                "angle_restoration_target_valid": self._debug_array(angle_valid),
            })
            readbacks += 1
        if include_angle_limit and bool(info.get("step_basic_ready", False)):
            limit_targets = np.empty((self.vertex_count, 3), dtype=np.float32)
            limit_vectors = np.empty((self.vertex_count, 3), dtype=np.float32)
            limit_valid = np.empty((self.vertex_count,), dtype=np.uint8)
            self._module.mc2_context_v0_read_debug_angle_limit(
                self._handle,
                limit_targets,
                limit_vectors,
                limit_valid,
            )
            snapshot.update({
                "angle_limit_target_positions": self._debug_array(limit_targets),
                "angle_limit_target_vectors": self._debug_array(limit_vectors),
                "angle_limit_target_valid": self._debug_array(limit_valid),
            })
            readbacks += 1
        if include_dynamics:
            velocities = np.empty((self.vertex_count, 3), dtype=np.float32)
            real_velocities = np.empty((self.vertex_count, 3), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_dynamics(
                self._handle, velocities, real_velocities
            )
            snapshot["dynamics"] = {
                "velocities": self._debug_array(velocities),
                "real_velocities": self._debug_array(real_velocities),
            }
            readbacks += 1
        if include_distance_tether:
            record_count = int(info.get("distance_record_count", 0) or 0)
            roots = np.empty((self.vertex_count,), dtype=np.int32)
            ranges = np.empty((self.vertex_count, 2), dtype=np.int32)
            targets = np.empty((record_count,), dtype=np.int32)
            rests = np.empty((record_count,), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_distance_tether(
                self._handle, roots, ranges, targets, rests
            )
            snapshot["distance_tether"] = {
                "baseline_roots": self._debug_array(roots),
                "distance_ranges": self._debug_array(ranges),
                "distance_targets": self._debug_array(targets),
                "distance_rest_signed": self._debug_array(rests),
            }
            readbacks += 1
        if include_bending:
            record_count = int(info.get("bending_record_count", 0) or 0)
            quads = np.empty((record_count, 4), dtype=np.int32)
            rests = np.empty((record_count,), dtype=np.float32)
            markers = np.empty((record_count,), dtype=np.int32)
            self._module.mc2_context_v0_read_debug_bending(
                self._handle, quads, rests, markers
            )
            snapshot["bending"] = {
                "quads": self._debug_array(quads),
                "rests": self._debug_array(rests),
                "markers": self._debug_array(markers),
            }
            readbacks += 1
        constraint_ready_mask = int(info.get("debug_constraint_ready_mask", 0) or 0)
        if include_constraint_results and constraint_ready_mask:
            mode_layout = (
                ("tether", MC2_DEBUG_CONSTRAINT_TETHER),
                ("distance", MC2_DEBUG_CONSTRAINT_DISTANCE),
                ("angle", MC2_DEBUG_CONSTRAINT_ANGLE),
                ("bending", MC2_DEBUG_CONSTRAINT_BENDING),
                ("motion", MC2_DEBUG_CONSTRAINT_MOTION),
            )
            pass_layout = (
                ("tether", MC2_DEBUG_CONSTRAINT_TETHER),
                ("distance", MC2_DEBUG_CONSTRAINT_DISTANCE),
                ("angle", MC2_DEBUG_CONSTRAINT_ANGLE),
                ("bending", MC2_DEBUG_CONSTRAINT_BENDING),
                ("distance", MC2_DEBUG_CONSTRAINT_DISTANCE),
                ("motion", MC2_DEBUG_CONSTRAINT_MOTION),
            )
            active_passes = tuple(
                item for item in pass_layout if constraint_ready_mask & item[1]
            )
            rows = len(active_passes) * self.vertex_count
            origins = np.empty((rows, 3), dtype=np.float32)
            corrections = np.empty((rows, 3), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_constraint_results(
                self._handle,
                origins,
                corrections,
            )
            origins = origins.reshape((len(active_passes), self.vertex_count, 3))
            corrections = corrections.reshape(
                (len(active_passes), self.vertex_count, 3)
            )
            constraint_results = {
                "ready_mask": constraint_ready_mask,
            }
            for name, bit in mode_layout:
                if not constraint_ready_mask & bit:
                    continue
                indices = tuple(
                    index
                    for index, (pass_name, _pass_bit) in enumerate(active_passes)
                    if pass_name == name
                )
                selected_origins = origins[list(indices)]
                selected_corrections = corrections[list(indices)]
                if len(indices) == 1:
                    selected_origins = selected_origins[0]
                    selected_corrections = selected_corrections[0]
                constraint_results[name] = {
                    "origins": self._debug_array(selected_origins),
                    "corrections": self._debug_array(selected_corrections),
                }
            snapshot["constraint_results"] = constraint_results
            readbacks += 1
            if (
                constraint_ready_mask & MC2_DEBUG_CONSTRAINT_DISTANCE
                and bool(info.get("debug_distance_record_ready", False))
            ):
                record_count = int(info.get("distance_record_count", 0) or 0)
                distance_origins = np.empty(
                    (record_count * 2, 3), dtype=np.float32
                )
                distance_corrections = np.empty(
                    (record_count * 2, 3), dtype=np.float32
                )
                distance_lengths = np.empty((2, record_count), dtype=np.float32)
                distance_rests = np.empty((2, record_count), dtype=np.float32)
                distance_valid = np.empty((record_count * 2,), dtype=np.uint8)
                self._module.mc2_context_v0_read_debug_distance_results(
                    self._handle,
                    distance_origins,
                    distance_corrections,
                    distance_lengths,
                    distance_rests,
                    distance_valid,
                )
                snapshot["distance_results"] = {
                    "origins": self._debug_array(
                        distance_origins.reshape((2, record_count, 3))
                    ),
                    "corrections": self._debug_array(
                        distance_corrections.reshape((2, record_count, 3))
                    ),
                    "lengths": self._debug_array(distance_lengths),
                    "rests": self._debug_array(distance_rests),
                    "valid": self._debug_array(
                        distance_valid.reshape((2, record_count))
                    ),
                }
                readbacks += 1
            if (
                constraint_ready_mask & MC2_DEBUG_CONSTRAINT_BENDING
                and bool(info.get("debug_bending_record_ready", False))
            ):
                record_count = int(info.get("bending_record_count", 0) or 0)
                bending_origins = np.empty(
                    (record_count * 4, 3), dtype=np.float32
                )
                bending_corrections = np.empty(
                    (record_count * 4, 3), dtype=np.float32
                )
                bending_valid = np.empty((record_count,), dtype=np.uint8)
                self._module.mc2_context_v0_read_debug_bending_results(
                    self._handle,
                    bending_origins,
                    bending_corrections,
                    bending_valid,
                )
                snapshot["bending_results"] = {
                    "origins": self._debug_array(
                        bending_origins.reshape((record_count, 4, 3))
                    ),
                    "corrections": self._debug_array(
                        bending_corrections.reshape((record_count, 4, 3))
                    ),
                    "valid": self._debug_array(bending_valid),
                }
                readbacks += 1
            if (
                constraint_ready_mask & MC2_DEBUG_CONSTRAINT_MOTION
                and bool(info.get("debug_motion_record_ready", False))
            ):
                record_count = self.vertex_count * 2
                motion_origins = np.empty((record_count, 3), dtype=np.float32)
                motion_corrections = np.empty(
                    (record_count, 3), dtype=np.float32
                )
                motion_valid = np.empty((record_count,), dtype=np.uint8)
                self._module.mc2_context_v0_read_debug_motion_results(
                    self._handle,
                    motion_origins,
                    motion_corrections,
                    motion_valid,
                )
                snapshot["motion_results"] = {
                    "origins": self._debug_array(
                        motion_origins.reshape((2, self.vertex_count, 3))
                    ),
                    "corrections": self._debug_array(
                        motion_corrections.reshape((2, self.vertex_count, 3))
                    ),
                    "valid": self._debug_array(
                        motion_valid.reshape((2, self.vertex_count))
                    ),
                }
                readbacks += 1
            if (
                constraint_ready_mask & MC2_DEBUG_CONSTRAINT_ANGLE
                and bool(info.get("debug_angle_record_ready", False))
            ):
                record_count = int(info.get("debug_angle_record_count", 0) or 0)
                if record_count % 6 != 0:
                    raise RuntimeError("MC2 angle record count is not divisible by 6")
                data_count = record_count // 6
                angle_origins = np.empty((record_count * 2, 3), dtype=np.float32)
                angle_corrections = np.empty(
                    (record_count * 2, 3), dtype=np.float32
                )
                angle_currents = np.empty((record_count,), dtype=np.float32)
                angle_limits = np.empty((record_count,), dtype=np.float32)
                angle_children = np.empty((record_count,), dtype=np.int32)
                angle_parents = np.empty((record_count,), dtype=np.int32)
                angle_valid = np.empty((record_count,), dtype=np.uint8)
                self._module.mc2_context_v0_read_debug_angle_results(
                    self._handle,
                    angle_origins,
                    angle_corrections,
                    angle_currents,
                    angle_limits,
                    angle_children,
                    angle_parents,
                    angle_valid,
                )
                record_shape = (2, 3, data_count)
                snapshot["angle_results"] = {
                    "origins": self._debug_array(
                        angle_origins.reshape((*record_shape, 2, 3))
                    ),
                    "corrections": self._debug_array(
                        angle_corrections.reshape((*record_shape, 2, 3))
                    ),
                    "currents": self._debug_array(
                        angle_currents.reshape(record_shape)
                    ),
                    "limits": self._debug_array(angle_limits.reshape(record_shape)),
                    "children": self._debug_array(
                        angle_children.reshape(record_shape)
                    ),
                    "parents": self._debug_array(
                        angle_parents.reshape(record_shape)
                    ),
                    "valid": self._debug_array(angle_valid.reshape(record_shape)),
                }
                readbacks += 1
        if include_external_contacts and bool(
            info.get("external_contact_debug_ready", False)
        ):
            contact_count = int(info.get("external_contact_debug_count", 0) or 0)
            primitive_kinds = np.empty((contact_count,), dtype=np.int32)
            primitive_indices = np.empty((contact_count,), dtype=np.int32)
            collider_indices = np.empty((contact_count,), dtype=np.int32)
            contact_positions = np.empty((contact_count, 3), dtype=np.float32)
            contact_normals = np.empty((contact_count, 3), dtype=np.float32)
            contact_corrections = np.empty((contact_count, 3), dtype=np.float32)
            self._module.mc2_context_v0_read_debug_external_contacts(
                self._handle,
                primitive_kinds,
                primitive_indices,
                collider_indices,
                contact_positions,
                contact_normals,
                contact_corrections,
            )
            snapshot["external_contacts"] = {
                "primitive_kinds": self._debug_array(primitive_kinds),
                "primitive_indices": self._debug_array(primitive_indices),
                "collider_indices": self._debug_array(collider_indices),
                "positions": self._debug_array(contact_positions),
                "normals": self._debug_array(contact_normals),
                "corrections": self._debug_array(contact_corrections),
            }
            readbacks += 1
        include_any_self = bool(
            include_self_primitives
            or include_self_grid
            or include_self_candidates
            or include_self_contacts
        )
        if include_any_self and bool(info.get("self_primitive_dynamic_ready", False)):
            primitive_count = int(info.get("self_primitive_count", 0) or 0)
            particle_indices = np.empty((primitive_count, 3), dtype=np.int32)
            self._module.mc2_context_v0_read_debug_self_indices(
                self._handle, particle_indices
            )
            self_state = {
                "particle_indices": self._debug_array(particle_indices),
            }
            readbacks += 1
            if include_self_grid and bool(info.get("self_grid_dynamic_ready", False)):
                grids = np.empty((primitive_count, 3), dtype=np.int32)
                hashes = np.empty((primitive_count,), dtype=np.int32)
                starts = np.empty((primitive_count,), dtype=np.int32)
                counts = np.empty((primitive_count,), dtype=np.int32)
                self._module.mc2_context_v0_read_debug_self_grid(
                    self._handle, grids, hashes, starts, counts
                )
                self_state.update({
                    "primitive_grids": self._debug_array(grids),
                    "grid_hashes": self._debug_array(hashes),
                    "grid_starts": self._debug_array(starts),
                    "grid_counts": self._debug_array(counts),
                })
                readbacks += 1
            if include_self_candidates and bool(info.get("self_candidate_ready", False)):
                candidate_count = int(info.get("self_contact_candidate_count", 0) or 0)
                candidates = np.empty((candidate_count, 3), dtype=np.int32)
                self._module.mc2_context_v0_read_debug_self_candidates(
                    self._handle, candidates
                )
                self_state["candidates"] = self._debug_array(candidates)
                readbacks += 1
            if include_self_contacts and bool(info.get("self_contact_ready", False)):
                contact_count = int(info.get("self_contact_cache_count", 0) or 0)
                indices = np.empty((contact_count, 2), dtype=np.int32)
                types = np.empty((contact_count,), dtype=np.int32)
                enabled = np.empty((contact_count,), dtype=np.uint8)
                contact_thickness = np.empty((contact_count,), dtype=np.float32)
                normals = np.empty((contact_count, 3), dtype=np.float32)
                corrections = np.empty((contact_count, 2, 3), dtype=np.float32)
                self._module.mc2_context_v0_read_debug_self_contacts(
                    self._handle,
                    indices,
                    types,
                    enabled,
                    contact_thickness,
                    normals,
                    corrections,
                )
                self_state.update({
                    "contact_indices": self._debug_array(indices),
                    "contact_types": self._debug_array(types),
                    "contact_enabled": self._debug_array(enabled),
                    "contact_thickness": self._debug_array(contact_thickness),
                    "contact_normals": self._debug_array(normals),
                    "contact_corrections": self._debug_array(corrections),
                })
                readbacks += 1
            if include_self_contacts and bool(
                info.get("self_intersect_flags_ready", False)
            ):
                record_count = int(info.get("self_intersect_record_count", 0) or 0)
                records = np.empty((record_count, 5), dtype=np.int32)
                self._module.mc2_context_v0_read_debug_self_intersections(
                    self._handle, records
                )
                self_state.update({
                    "intersect_records": self._debug_array(records),
                })
                readbacks += 1
            snapshot["self_collision"] = self_state
        self.debug_capture_count += 1
        self.debug_readback_count += readbacks
        snapshot["capture_index"] = self.debug_capture_count
        snapshot["readback_count"] = readbacks
        self._debug_draw_snapshot = snapshot
        return snapshot

    def debug_draw_snapshot(self) -> dict | None:
        return self._debug_draw_snapshot

    def dispose(self) -> None:
        if self._handle is not None:
            try:
                self._module.mc2_context_v0_free(self._handle)
            finally:
                self._handle = None
        self.parameter_signature = ""
        self.proxy_signature = ""
        self.baseline_signature = ""
        self.bone_static_signature = ""
        self.distance_signature = ""
        self.bending_signature = ""
        self.center_signature = ""
        self.last_frame = None
        self._out_positions = np.empty((0, 3), dtype=np.float32)
        self._out_rotations = np.empty((0, 4), dtype=np.float32)
        self._step_basic_positions = np.empty((0, 3), dtype=np.float32)
        self._step_basic_rotations = np.empty((0, 4), dtype=np.float32)
        self._center_frame_dt = None
        self._center_step_dt = None
        self._center_now_position = np.empty(0, dtype=np.float32)
        self._center_now_rotation = np.empty(0, dtype=np.float32)
        self._center_step_vector = np.empty(0, dtype=np.float32)
        self._center_step_rotation = np.empty(0, dtype=np.float32)
        self._center_inertia_vector = np.empty(0, dtype=np.float32)
        self._center_inertia_rotation = np.empty(0, dtype=np.float32)
        self._center_rotation_axis = np.empty(0, dtype=np.float32)
        self._debug_draw_snapshot = None

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 native context owner has been disposed")


class MC2NativeInteractionV0:
    """World-owned coordinator for lockstep MC2 context interaction."""

    def __init__(self, *, module=None) -> None:
        self._module = require_mc2_native_module(module)
        self._handle = self._module.mc2_interaction_v0_create(
            MC2_NATIVE_CONTEXT_SCHEMA_VERSION
        )
        if self._handle is None:
            raise RuntimeError("mc2_interaction_v0_create returned None")
        self._debug_scope = ()
        self._debug_draw_snapshot = None
        self._debug_capture_state = {}
        self._debug_self_temporal_history = {}
        self.debug_capture_count = 0
        self.debug_readback_count = 0

    @property
    def disposed(self) -> bool:
        return self._handle is None

    def invalidate(self) -> None:
        self._ensure_live()
        self._module.mc2_interaction_v0_invalidate(self._handle)
        self._debug_draw_snapshot = None
        self._debug_self_temporal_history.clear()

    def step_group(
        self,
        contexts,
        primary_group_bits,
        collided_by_groups,
        dt: float,
        *,
        is_final_substep: bool = True,
        capture_timing: bool = False,
    ) -> dict | None:
        self._ensure_live()
        contexts = tuple(contexts)
        primary_group_bits = tuple(int(value) for value in primary_group_bits)
        collided_by_groups = tuple(int(value) for value in collided_by_groups)
        if len(primary_group_bits) != len(contexts) or len(collided_by_groups) != len(contexts):
            raise ValueError("MC2 interaction metadata length mismatch")
        for context in contexts:
            if not isinstance(context, MC2NativeContextV0):
                raise TypeError("contexts must contain MC2NativeContextV0 values")
            context._ensure_live()
        dt = float(dt)
        for context in contexts:
            if context._center_step_dt is not None and not math.isclose(
                dt,
                context._center_step_dt,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError(
                    "Center step simulation_delta_time does not match native group step dt"
                )
        powers = derive_mc2_simulation_powers(dt)
        native_timing = self._module.mc2_interaction_v0_step_group(
            self._handle,
            tuple(context._handle for context in contexts),
            primary_group_bits,
            collided_by_groups,
            dt,
            powers.distance_bending,
            powers.integration,
            powers.angle,
            bool(is_final_substep),
            bool(
                self._debug_capture_state.get("requested", False)
                and (
                    (self._debug_capture_state.get("filters") or {}).get(
                        "show_self_contacts", False
                    )
                    or (self._debug_capture_state.get("filters") or {}).get(
                        "show_interaction_contacts", False
                    )
                )
            ),
            bool(capture_timing),
        )
        for context in contexts:
            context._center_step_dt = None
        if not capture_timing:
            if native_timing is not None:
                raise RuntimeError("MC2 native timing was published while disabled")
            return None
        return _normalize_mc2_native_timing(native_timing)

    def inspect(self) -> dict:
        if self._handle is None:
            return {
                "schema": "mc2_interaction_v0",
                "schema_version": MC2_NATIVE_CONTEXT_SCHEMA_VERSION,
                "released": True,
            }
        result = dict(self._module.mc2_interaction_v0_inspect(self._handle))
        result["debug_capture_count"] = self.debug_capture_count
        result["debug_readback_count"] = self.debug_readback_count
        return result

    def set_debug_scope(self, values) -> None:
        self._debug_scope = tuple(dict(value) for value in values)

    def request_debug_capture(self, frame: int, filters: dict | None = None) -> None:
        self._debug_capture_state.update({
            "requested": True,
            "request_frame": int(frame),
            "filters": dict(filters or {}),
        })

    def cancel_debug_capture(self, filters: dict | None = None) -> None:
        self._debug_capture_state.update({
            "requested": False,
            "filters": dict(filters or {}),
        })

    def debug_capture_state(self) -> dict:
        return self._debug_capture_state

    def debug_self_temporal_history(self) -> dict:
        return self._debug_self_temporal_history

    def clear_debug_self_temporal_history(self) -> None:
        self._debug_self_temporal_history.clear()

    def refresh_debug_draw_snapshot(
        self,
        *,
        include_primitives: bool = False,
        include_grid: bool = False,
        include_candidates: bool = False,
        include_contacts: bool = False,
    ) -> dict:
        self._ensure_live()
        info = self.inspect()
        vertex_count = int(info.get("vertex_count", 0) or 0)
        primitive_count = int(info.get("primitive_count", 0) or 0)
        candidate_count = int(info.get("candidate_count", 0) or 0)
        contact_count = int(info.get("contact_count", 0) or 0)
        intersect_count = int(info.get("intersect_record_count", 0) or 0)
        if primitive_count == 0:
            self.debug_capture_count += 1
            snapshot = {
                "source": "cpp_interaction",
                "schema": "mc2_debug_interaction_v0",
                "native": info,
                "participants": tuple(self._debug_scope),
                "capture_index": self.debug_capture_count,
                "readback_count": 0,
            }
            self._debug_draw_snapshot = snapshot
            return snapshot
        flags = (
            (1 if include_primitives else 0)
            | (2 if include_grid else 0)
            | (4 if include_candidates else 0)
            | (8 if include_contacts else 0)
        )
        arrays = {
            "positions": np.empty((vertex_count, 3), dtype=np.float32),
            "particle_indices": np.empty((primitive_count, 3), dtype=np.int32),
            "owner_indices": np.empty((primitive_count,), dtype=np.int32),
            "primitive_grids": np.empty(
                (primitive_count if include_grid else 0, 3), dtype=np.int32
            ),
            "candidates": np.empty(
                (candidate_count if include_candidates else 0, 3), dtype=np.int32
            ),
            "contact_indices": np.empty(
                (contact_count if include_contacts else 0, 2), dtype=np.int32
            ),
            "contact_types": np.empty(
                (contact_count if include_contacts else 0,), dtype=np.int32
            ),
            "contact_enabled": np.empty(
                (contact_count if include_contacts else 0,), dtype=np.uint8
            ),
            "contact_thickness": np.empty(
                (contact_count if include_contacts else 0,), dtype=np.float32
            ),
            "contact_normals": np.empty(
                (contact_count if include_contacts else 0, 3), dtype=np.float32
            ),
            "contact_corrections": np.empty(
                (contact_count if include_contacts else 0, 2, 3), dtype=np.float32
            ),
            "intersect_records": np.empty(
                (intersect_count if include_contacts else 0, 5), dtype=np.int32
            ),
        }
        self._module.mc2_interaction_v0_read_debug(
            self._handle,
            flags,
            *arrays.values(),
        )
        self.debug_capture_count += 1
        self.debug_readback_count += 1
        snapshot = {
            "source": "cpp_interaction",
            "schema": "mc2_debug_interaction_v0",
            "native": info,
            "participants": tuple(self._debug_scope),
            "capture_index": self.debug_capture_count,
            "readback_count": 1,
        }
        for name in ("positions", "particle_indices", "owner_indices"):
            snapshot[name] = MC2NativeContextV0._debug_array(arrays[name])
        if include_grid:
            snapshot["primitive_grids"] = MC2NativeContextV0._debug_array(
                arrays["primitive_grids"]
            )
        if include_candidates:
            snapshot["candidates"] = MC2NativeContextV0._debug_array(
                arrays["candidates"]
            )
        if include_contacts:
            for name in (
                "contact_indices", "contact_types", "contact_enabled",
                "contact_thickness", "contact_normals", "contact_corrections",
                "intersect_records",
            ):
                snapshot[name] = MC2NativeContextV0._debug_array(arrays[name])
        self._debug_draw_snapshot = snapshot
        return snapshot

    def debug_draw_snapshot(self) -> dict | None:
        return self._debug_draw_snapshot

    def dispose(self) -> None:
        if self._handle is not None:
            try:
                self._module.mc2_interaction_v0_free(self._handle)
            finally:
                self._handle = None
        self._debug_scope = ()
        self._debug_draw_snapshot = None
        self._debug_capture_state.clear()
        self._debug_self_temporal_history.clear()

    def omni_cache_dispose(self, _reason: str = "") -> None:
        self.dispose()

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 native interaction owner has been disposed")


__all__ = [
    "MC2_STATIC_CHANGE_ALL",
    "MC2_STATIC_CHANGE_CONFIG",
    "MC2_STATIC_CHANGE_GEOMETRY",
    "MC2_STATIC_CHANGE_SOURCE",
    "MC2_STATIC_CHANGE_SURFACE",
    "MC2_STATIC_CHANGE_TOPOLOGY",
    "MC2_DEBUG_CONSTRAINT_ALL",
    "MC2_DEBUG_CONSTRAINT_ANGLE",
    "MC2_DEBUG_CONSTRAINT_BENDING",
    "MC2_DEBUG_CONSTRAINT_DISTANCE",
    "MC2_DEBUG_CONSTRAINT_MOTION",
    "MC2_DEBUG_CONSTRAINT_TETHER",
    "MC2_INTERACTION_RESOURCE_KEY",
    "MC2_NATIVE_CONTEXT_SCHEMA_VERSION",
    "MC2NativeContextV0",
    "MC2NativeInteractionV0",
]
