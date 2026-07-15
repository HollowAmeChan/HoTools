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
from .static_data import pack_mc2_baseline_static, pack_mc2_proxy_static


MC2_NATIVE_CONTEXT_SCHEMA_VERSION = 0
_NATIVE_MODULE = None
_REQUIRED_SYMBOLS = (
    "mc2_context_v0_create",
    "mc2_context_v0_inspect",
    "mc2_context_v0_update_proxy_static",
    "mc2_context_v0_update_baseline_static",
    "mc2_context_v0_update_bone_static",
    "mc2_context_v0_update_distance_static",
    "mc2_context_v0_update_bending_static",
    "mc2_context_v0_update_center_static",
    "mc2_context_v0_update_center_dynamic",
    "mc2_context_v0_update_step_interpolation",
    "mc2_context_v0_update_team_options",
    "mc2_context_v0_set_setup_kind",
    "mc2_context_v0_set_tether_enabled",
    "mc2_context_v0_apply_center_frame_shift",
    "mc2_context_v0_apply_center_negative_scale_teleport",
    "mc2_context_v0_update_parameters",
    "mc2_context_v0_update_dynamic",
    "mc2_context_v0_update_colliders",
    "mc2_context_v0_reset",
    "mc2_context_v0_step",
    "mc2_context_v0_read",
    "mc2_context_v0_read_bone_output",
    "mc2_context_v0_read_step_basic",
    "mc2_context_v0_read_center_step",
    "mc2_context_v0_free",
    "mc2_context_v0_stats",
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

    def update_mesh_static(self, static) -> None:
        from .setups.mesh_cloth.static_build import MC2MeshClothStaticBuildResult

        if not isinstance(static, MC2MeshClothStaticBuildResult):
            raise TypeError("static must be MC2MeshClothStaticBuildResult")
        if static.final_proxy.vertex_count != self.vertex_count:
            raise ValueError("MC2 native static vertex count mismatch")
        self._update_proxy_and_baseline(static.final_proxy, static.baseline.baseline)
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
        self.last_frame = (frame_input.frame, frame_input.generation)
        self._center_frame_dt = None
        self._center_step_dt = None

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

    def step_no_collision(self, dt: float) -> None:
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
        return dict(self._module.mc2_context_v0_inspect(self._handle))

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

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 native context owner has been disposed")


__all__ = [
    "MC2_NATIVE_CONTEXT_SCHEMA_VERSION",
    "MC2NativeContextV0",
    "is_available",
    "native_module",
]
