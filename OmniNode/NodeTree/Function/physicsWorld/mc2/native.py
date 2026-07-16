"""Owner for the new Physics World MC2 native context V0."""

from __future__ import annotations

import importlib
import math
import os
from pathlib import Path
import sys

import numpy as np

from .bending_static import pack_mc2_bending_static
from .bone_static import pack_mc2_bone_static
from .center_state import (
    MC2CenterFrameShiftResult,
    MC2NegativeScaleTransitionResult,
    MC2CenterWorldPoseSpec,
    MC2CenterStepInputSpec,
    MC2CenterStepResult,
    pack_mc2_center_static,
)
from .collider_frame import MC2ColliderFrameSpec
from .distance_static import pack_mc2_distance_static
from .frame_state import MC2FrameInputSpec
from .runtime_parameters import (
    MC2RuntimeParametersV0,
    pack_mc2_runtime_parameters,
)
from .self_collision_static import pack_mc2_self_collision_static
from .static_data import pack_mc2_baseline_static, pack_mc2_proxy_static


MC2_NATIVE_CONTEXT_SCHEMA_VERSION = 0
MC2_INTERACTION_RESOURCE_KEY = "mc2_interaction_v0"
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
_NATIVE_MODULE = None
_REQUIRED_SYMBOLS = (
    "mc2_interaction_v0_create",
    "mc2_interaction_v0_inspect",
    "mc2_interaction_v0_step_group",
    "mc2_interaction_v0_read_debug",
    "mc2_interaction_v0_free",
    "mc2_context_v0_create",
    "mc2_context_v0_inspect",
    "mc2_context_v0_classify_static_fingerprint",
    "mc2_context_v0_update_static_fingerprint",
    "mc2_context_v0_update_proxy_static",
    "mc2_context_v0_update_baseline_static",
    "mc2_context_v0_update_bone_static",
    "mc2_context_v0_update_frame_producer_static",
    "mc2_context_v0_update_distance_static",
    "mc2_context_v0_update_bending_static",
    "mc2_context_v0_update_center_static",
    "mc2_context_v0_update_self_collision_static",
    "mc2_context_v0_update_center_dynamic",
    "mc2_context_v0_update_step_interpolation",
    "mc2_context_v0_update_team_options",
    "mc2_context_v0_set_setup_kind",
    "mc2_context_v0_set_tether_enabled",
    "mc2_context_v0_apply_center_frame_shift",
    "mc2_context_v0_apply_center_negative_scale_teleport",
    "mc2_context_v0_update_parameters",
    "mc2_context_v0_update_dynamic",
    "mc2_context_v0_update_mesh_dynamic_raw",
    "mc2_context_v0_update_bone_dynamic_raw",
    "mc2_context_v0_update_colliders",
    "mc2_context_v0_reset",
    "mc2_context_v0_step",
    "mc2_context_v0_read",
    "mc2_context_v0_read_self_collision_primitives",
    "mc2_context_v0_read_self_collision_grid",
    "mc2_context_v0_read_self_collision_candidates",
    "mc2_context_v0_read_self_collision_contacts",
    "mc2_context_v0_read_self_collision_intersections",
    "mc2_context_v0_read_bone_output",
    "mc2_context_v0_read_step_basic",
    "mc2_context_v0_read_center_step",
    "mc2_context_v0_free",
    "mc2_context_v0_stats",
    "mc2_mesh_static_fingerprint_v0",
    "mc2_bone_static_fingerprint_v0",
    "mc2_optimize_triangle_direction_v0",
    "mc2_build_mesh_final_proxy_derived_v0",
    "mc2_build_mesh_baseline_derived_v0",
    "mc2_build_baseline_pose_depth_derived_v0",
    "mc2_build_distance_derived_v0",
    "mc2_build_bending_derived_v0",
)


def _ensure_bundled_native_path() -> None:
    override = os.environ.get("HOTOOLS_NATIVE_TEST_DIR")
    package_dir = Path(override) if override else None
    if package_dir is None:
        package_root = Path(__file__).resolve().parents[5]
        py_lib = "py313" if sys.version_info >= (3, 13) else "py311"
        package_dir = package_root / "_Lib" / py_lib / "HotoolsPackage"
    if package_dir.exists():
        path = str(package_dir)
        if path not in sys.path:
            sys.path.insert(0, path)


def native_module():
    global _NATIVE_MODULE
    if _NATIVE_MODULE is None:
        _ensure_bundled_native_path()
        _NATIVE_MODULE = importlib.import_module("hotools_native")
    return _NATIVE_MODULE


def is_available() -> bool:
    try:
        module = native_module()
    except Exception:
        return False
    return all(hasattr(module, name) for name in _REQUIRED_SYMBOLS)


class MC2NativeContextV0:
    """The slot-owned resource; the capsule never leaves this object."""

    def __init__(self, vertex_count: int, *, setup_type: str = "mesh_cloth", module=None) -> None:
        vertex_count = int(vertex_count)
        if vertex_count <= 0:
            raise ValueError("MC2 native context vertex_count must be positive")
        self._module = native_module() if module is None else module
        if not all(hasattr(self._module, name) for name in _REQUIRED_SYMBOLS):
            raise RuntimeError("hotools_native is missing MC2 context V0 symbols")
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

    def _update_proxy_and_baseline(self, proxy_spec, baseline_spec) -> None:
        self._ensure_live()
        proxy = pack_mc2_proxy_static(proxy_spec)
        baseline = pack_mc2_baseline_static(baseline_spec)
        self._module.mc2_context_v0_update_proxy_static(
            self._handle,
            proxy["local_positions"],
            proxy["local_normals"],
            proxy["local_tangents"],
            proxy["uvs"],
            proxy["vertex_attributes"],
            proxy["edges"],
            proxy["triangles"],
        )
        self._module.mc2_context_v0_update_baseline_static(
            self._handle,
            baseline["parent_indices"],
            baseline["child_ranges"],
            baseline["child_data"],
            baseline["baseline_flags"],
            baseline["baseline_ranges"],
            baseline["baseline_data"],
            baseline["root_indices"],
            baseline["depths"],
            baseline["vertex_local_positions"],
            baseline["vertex_local_rotations"],
        )

    def _update_self_collision_static(self, spec) -> None:
        packed = pack_mc2_self_collision_static(spec)
        self._module.mc2_context_v0_update_self_collision_static(
            self._handle,
            packed["primitive_flags"],
            packed["particle_indices"],
            packed["primitive_depths"],
            spec.point_count,
            spec.edge_count,
            spec.triangle_count,
        )
        self.self_collision_signature = spec.static_signature

    def update_mesh_static(self, static) -> None:
        from .setups.mesh_cloth.static_build import MC2MeshClothStaticBuildResult

        if not isinstance(static, MC2MeshClothStaticBuildResult):
            raise TypeError("static must be MC2MeshClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native static vertex count mismatch")
        self._update_proxy_and_baseline(static.final_proxy, static.baseline.baseline)
        records = tuple(static.finalizer.vertex_to_triangle_records)
        ranges = np.empty((self.vertex_count, 2), dtype=np.int32)
        packed_records = []
        cursor = 0
        for vertex, vertex_records in enumerate(records):
            ranges[vertex] = (cursor, len(vertex_records))
            packed_records.extend(vertex_records)
            cursor += len(vertex_records)
        self._module.mc2_context_v0_update_frame_producer_static(
            self._handle,
            ranges,
            np.ascontiguousarray(packed_records, dtype=np.int32).reshape((-1, 2)),
            np.ascontiguousarray(
                static.finalizer.vertex_bind_pose_rotations,
                dtype=np.float32,
            ),
        )
        distance = pack_mc2_distance_static(static.distance)
        self._module.mc2_context_v0_update_distance_static(
            self._handle,
            distance["distance_ranges"],
            distance["distance_targets"],
            distance["distance_rest_signed"],
        )
        if static.bending is None:
            bending = {
                "bending_quads": np.empty((0, 4), dtype=np.int32),
                "bending_rest_angle_or_volume": np.empty((0,), dtype=np.float32),
                "bending_sign_or_volume": np.empty((0,), dtype=np.int8),
            }
        else:
            bending = pack_mc2_bending_static(static.bending)
        self._module.mc2_context_v0_update_bending_static(
            self._handle,
            bending["bending_quads"],
            bending["bending_rest_angle_or_volume"],
            bending["bending_sign_or_volume"],
        )
        center = pack_mc2_center_static(static.center)
        self._module.mc2_context_v0_update_center_static(
            self._handle,
            center["fixed_indices"],
            center["local_center_position"],
            center["initial_local_gravity_direction"],
        )
        self._update_self_collision_static(static.self_collision)
        self.proxy_signature = static.final_proxy.proxy_signature
        self.baseline_signature = static.baseline.baseline.baseline_signature
        self.distance_signature = static.distance.distance_signature
        self.bending_signature = (
            static.bending.bending_signature if static.bending is not None else "empty"
        )
        self.center_signature = static.center.center_static_signature

    def update_bone_static(self, static) -> None:
        from .setups.bone_cloth.static_build import MC2BoneClothStaticBuildResult

        if not isinstance(static, MC2BoneClothStaticBuildResult):
            raise TypeError("static must be MC2BoneClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native Bone static vertex count mismatch")
        self._update_proxy_and_baseline(static.final_proxy, static.baseline)
        packed = pack_mc2_bone_static(static.bone)
        self._module.mc2_context_v0_update_bone_static(
            self._handle,
            packed["vertex_to_vertex_ranges"],
            packed["vertex_to_vertex_data"],
            packed["vertex_to_triangle_ranges"],
            packed["vertex_to_triangle_data"],
            packed["vertex_bind_pose_positions"],
            packed["vertex_bind_pose_rotations"],
            packed["normal_adjustment_rotations"],
            packed["vertex_to_transform_rotations"],
        )
        distance = pack_mc2_distance_static(static.distance)
        self._module.mc2_context_v0_update_distance_static(
            self._handle,
            distance["distance_ranges"],
            distance["distance_targets"],
            distance["distance_rest_signed"],
        )
        self._module.mc2_context_v0_update_bending_static(
            self._handle,
            np.empty((0, 4), dtype=np.int32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int8),
        )
        center = pack_mc2_center_static(static.center)
        self._module.mc2_context_v0_update_center_static(
            self._handle,
            center["fixed_indices"],
            center["local_center_position"],
            center["initial_local_gravity_direction"],
        )
        self._update_self_collision_static(static.self_collision)
        self.proxy_signature = static.final_proxy.proxy_signature
        self.baseline_signature = static.baseline.baseline_signature
        self.bone_static_signature = static.bone.static_signature
        self.distance_signature = static.distance.distance_signature
        self.bending_signature = "empty"
        self.center_signature = static.center.center_static_signature

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
            self._derived_center_pose_values = None
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
        frequency_ratio = 90.0 * dt
        simulation_power_z = (
            math.pow(frequency_ratio, 0.3)
            if frequency_ratio > 1.0
            else frequency_ratio
        )
        simulation_power_y = (
            math.sqrt(frequency_ratio)
            if frequency_ratio > 1.0
            else frequency_ratio
        )
        simulation_power_w = math.pow(frequency_ratio, 1.8)
        self._module.mc2_context_v0_step(
            self._handle,
            dt,
            simulation_power_y,
            simulation_power_z,
            simulation_power_w,
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

    @staticmethod
    def _debug_array(values) -> np.ndarray:
        result = np.array(values, copy=True, order="C")
        result.flags.writeable = False
        return result

    def refresh_debug_draw_snapshot(
        self,
        *,
        include_step_basic: bool = True,
        include_self: bool = True,
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
        if include_step_basic and bool(info.get("step_basic_ready", False)):
            basic_positions, basic_rotations = self.read_step_basic()
            snapshot["step_basic_positions"] = self._debug_array(basic_positions)
            snapshot["step_basic_rotations_xyzw"] = self._debug_array(basic_rotations)
            readbacks += 1
        if include_self and bool(info.get("self_primitive_dynamic_ready", False)):
            primitive_count = int(info.get("self_primitive_count", 0) or 0)
            inverse_masses = np.empty((primitive_count, 3), dtype=np.float32)
            aabb_min = np.empty((primitive_count, 3), dtype=np.float32)
            aabb_max = np.empty((primitive_count, 3), dtype=np.float32)
            thickness = np.empty((primitive_count,), dtype=np.float32)
            self._module.mc2_context_v0_read_self_collision_primitives(
                self._handle, inverse_masses, aabb_min, aabb_max, thickness
            )
            self_state = {
                "inverse_masses": self._debug_array(inverse_masses),
                "aabb_min": self._debug_array(aabb_min),
                "aabb_max": self._debug_array(aabb_max),
                "thickness": self._debug_array(thickness),
            }
            readbacks += 1
            if bool(info.get("self_grid_dynamic_ready", False)):
                particle_indices = np.empty((primitive_count, 3), dtype=np.int32)
                grids = np.empty((primitive_count, 3), dtype=np.int32)
                hashes = np.empty((primitive_count,), dtype=np.int32)
                starts = np.empty((primitive_count,), dtype=np.int32)
                counts = np.empty((primitive_count,), dtype=np.int32)
                self._module.mc2_context_v0_read_self_collision_grid(
                    self._handle, particle_indices, grids, hashes, starts, counts
                )
                self_state.update({
                    "particle_indices": self._debug_array(particle_indices),
                    "primitive_grids": self._debug_array(grids),
                    "grid_hashes": self._debug_array(hashes),
                    "grid_starts": self._debug_array(starts),
                    "grid_counts": self._debug_array(counts),
                })
                readbacks += 1
            if bool(info.get("self_candidate_ready", False)):
                candidate_count = int(info.get("self_contact_candidate_count", 0) or 0)
                candidates = np.empty((candidate_count, 3), dtype=np.int32)
                self._module.mc2_context_v0_read_self_collision_candidates(
                    self._handle, candidates
                )
                self_state["candidates"] = self._debug_array(candidates)
                readbacks += 1
            if bool(info.get("self_contact_ready", False)):
                contact_count = int(info.get("self_contact_cache_count", 0) or 0)
                indices = np.empty((contact_count, 2), dtype=np.int32)
                types = np.empty((contact_count,), dtype=np.int32)
                enabled = np.empty((contact_count,), dtype=np.uint8)
                contact_thickness = np.empty((contact_count,), dtype=np.float32)
                s = np.empty((contact_count,), dtype=np.float32)
                t = np.empty((contact_count,), dtype=np.float32)
                normals = np.empty((contact_count, 3), dtype=np.float32)
                self._module.mc2_context_v0_read_self_collision_contacts(
                    self._handle,
                    indices,
                    types,
                    enabled,
                    contact_thickness,
                    s,
                    t,
                    normals,
                )
                self_state.update({
                    "contact_indices": self._debug_array(indices),
                    "contact_types": self._debug_array(types),
                    "contact_enabled": self._debug_array(enabled),
                    "contact_thickness": self._debug_array(contact_thickness),
                    "contact_s": self._debug_array(s),
                    "contact_t": self._debug_array(t),
                    "contact_normals": self._debug_array(normals),
                })
                readbacks += 1
            if bool(info.get("self_intersect_detection_ready", False)) or bool(
                info.get("self_intersect_flags_ready", False)
            ):
                record_count = int(info.get("self_intersect_record_count", 0) or 0)
                records = np.empty((record_count, 5), dtype=np.int32)
                particle_flags = np.empty((self.vertex_count,), dtype=np.uint8)
                primitive_flags = np.empty((primitive_count,), dtype=np.uint32)
                self._module.mc2_context_v0_read_self_collision_intersections(
                    self._handle, records, particle_flags, primitive_flags
                )
                self_state.update({
                    "intersect_records": self._debug_array(records),
                    "particle_intersect_flags": self._debug_array(particle_flags),
                    "primitive_flags": self._debug_array(primitive_flags),
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
        self._module = native_module() if module is None else module
        if not all(hasattr(self._module, name) for name in _REQUIRED_SYMBOLS):
            raise RuntimeError("hotools_native is missing MC2 interaction V0 symbols")
        self._handle = self._module.mc2_interaction_v0_create(
            MC2_NATIVE_CONTEXT_SCHEMA_VERSION
        )
        if self._handle is None:
            raise RuntimeError("mc2_interaction_v0_create returned None")
        self._debug_scope = ()
        self._debug_draw_snapshot = None
        self._debug_capture_state = {}
        self.debug_capture_count = 0
        self.debug_readback_count = 0

    @property
    def disposed(self) -> bool:
        return self._handle is None

    def step_group(
        self,
        contexts,
        primary_group_bits,
        collided_by_groups,
        dt: float,
        *,
        is_final_substep: bool = True,
    ) -> None:
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
        frequency_ratio = 90.0 * dt
        simulation_power_z = (
            math.pow(frequency_ratio, 0.3)
            if frequency_ratio > 1.0
            else frequency_ratio
        )
        simulation_power_y = (
            math.sqrt(frequency_ratio)
            if frequency_ratio > 1.0
            else frequency_ratio
        )
        simulation_power_w = math.pow(frequency_ratio, 1.8)
        self._module.mc2_interaction_v0_step_group(
            self._handle,
            tuple(context._handle for context in contexts),
            primary_group_bits,
            collided_by_groups,
            dt,
            simulation_power_y,
            simulation_power_z,
            simulation_power_w,
            bool(is_final_substep),
        )
        for context in contexts:
            context._center_step_dt = None

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

    def debug_capture_state(self) -> dict:
        return self._debug_capture_state

    def refresh_debug_draw_snapshot(self) -> dict:
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
        arrays = {
            "positions": np.empty((vertex_count, 3), dtype=np.float32),
            "particle_indices": np.empty((primitive_count, 3), dtype=np.int32),
            "owner_indices": np.empty((primitive_count,), dtype=np.int32),
            "aabb_min": np.empty((primitive_count, 3), dtype=np.float32),
            "aabb_max": np.empty((primitive_count, 3), dtype=np.float32),
            "thickness": np.empty((primitive_count,), dtype=np.float32),
            "primitive_grids": np.empty((primitive_count, 3), dtype=np.int32),
            "grid_hashes": np.empty((primitive_count,), dtype=np.int32),
            "grid_starts": np.empty((primitive_count,), dtype=np.int32),
            "grid_counts": np.empty((primitive_count,), dtype=np.int32),
            "candidates": np.empty((candidate_count, 3), dtype=np.int32),
            "contact_indices": np.empty((contact_count, 2), dtype=np.int32),
            "contact_types": np.empty((contact_count,), dtype=np.int32),
            "contact_enabled": np.empty((contact_count,), dtype=np.uint8),
            "contact_normals": np.empty((contact_count, 3), dtype=np.float32),
            "intersect_records": np.empty((intersect_count, 5), dtype=np.int32),
            "particle_intersect_flags": np.empty((vertex_count,), dtype=np.uint8),
        }
        self._module.mc2_interaction_v0_read_debug(
            self._handle,
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
        snapshot.update({
            name: MC2NativeContextV0._debug_array(value)
            for name, value in arrays.items()
        })
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
    "MC2_INTERACTION_RESOURCE_KEY",
    "MC2_NATIVE_CONTEXT_SCHEMA_VERSION",
    "MC2NativeContextV0",
    "MC2NativeInteractionV0",
    "is_available",
    "native_module",
]
