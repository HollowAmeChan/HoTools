"""Source-aligned Center static, frame-pose, and persistent reset contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from ..utils.math3d import (
    normalize_quaternion_f32,
    quaternion_conjugate_xyzw_tuple,
    quaternion_conjugate_f32,
    quaternion_matrix_unit_f32,
    quaternion_multiply_f32,
    quaternion_multiply_xyzw_tuple,
    quaternion_slerp_unit_f32,
    rotate_vector_unit_quaternion_f32,
    rotate_vector_xyzw_tuple,
    transform_point_matrix_f32,
    transform_vector_matrix_f32,
)
from .static_data import MC2ProxyStaticSpec
from .setups.mesh_cloth.final_proxy import mc2_world_rotation_xyzw


IDENTITY_QUATERNION = (0.0, 0.0, 0.0, 1.0)


def _f32(value) -> np.float32:
    result = np.float32(value)
    if not np.isfinite(result):
        raise ValueError("Center value cannot contain NaN/Inf")
    return result


def _vector(values, width: int, name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != width or not all(math.isfinite(value) for value in result):
        raise ValueError(f"{name} must contain {width} finite values")
    return result


def _normalize3(values, name: str) -> tuple[float, float, float]:
    value = _vector(values, 3, name)
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1.0e-8:
        raise ValueError(f"{name} must be non-zero")
    return tuple(component / length for component in value)


def _unit_quaternion(values, name: str) -> tuple[float, float, float, float]:
    value = _vector(values, 4, name)
    length = math.sqrt(sum(component * component for component in value))
    if length <= 1.0e-8:
        raise ValueError(f"{name} must be non-zero")
    return tuple(component / length for component in value)


def _require_unit_quaternion(values, name: str) -> tuple[float, float, float, float]:
    value = _vector(values, 4, name)
    length = math.sqrt(sum(component * component for component in value))
    if not math.isclose(length, 1.0, rel_tol=1.0e-5, abs_tol=1.0e-6):
        raise ValueError(f"{name} must be a unit quaternion")
    return value


def _rotate(value, vector):
    q = _unit_quaternion(value, "quaternion")
    return rotate_vector_xyzw_tuple(q, vector)


def _center_static_signature(
    *,
    task_id,
    proxy_signature,
    fixed_indices,
    local_center_position,
    initial_local_gravity_direction,
) -> str:
    digest = hashlib.sha256(b"mc2_center_static_v0\0")
    digest.update(str(task_id or "").encode("ascii"))
    digest.update(str(proxy_signature or "").encode("ascii"))
    for values, dtype in (
        (fixed_indices, np.int32),
        (local_center_position, np.float32),
        (initial_local_gravity_direction, np.float32),
    ):
        digest.update(np.ascontiguousarray(values, dtype=dtype).tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class MC2CenterStaticSpec:
    task_id: str
    proxy_signature: str
    fixed_indices: tuple[int, ...]
    local_center_position: tuple[float, float, float]
    initial_local_gravity_direction: tuple[float, float, float]
    center_static_signature: str
    schema_version: int = 0

    @property
    def fixed_count(self) -> int:
        return len(self.fixed_indices)

    def debug_dict(self) -> dict:
        return {
            "fixed_indices": self.fixed_indices,
            "local_center_position": self.local_center_position,
            "initial_local_gravity_direction": self.initial_local_gravity_direction,
            "center_static_signature": self.center_static_signature,
        }


@dataclass(frozen=True)
class MC2CenterStaticMetadata:
    task_id: str
    proxy_signature: str
    fixed_count: int
    center_static_signature: str
    schema_version: int = 0

    def __post_init__(self) -> None:
        if not self.task_id or not self.proxy_signature or not self.center_static_signature:
            raise ValueError("Center static metadata requires stable signatures")
        if self.fixed_count < 0:
            raise ValueError("Center fixed_count cannot be negative")

    def debug_dict(self) -> dict:
        return {
            "fixed_count": self.fixed_count,
            "center_static_signature": self.center_static_signature,
            "native_owned": True,
        }


def build_mc2_center_static(
    proxy: MC2ProxyStaticSpec,
    *,
    vertex_bind_pose_rotations,
    world_gravity_direction,
    native_context=None,
) -> MC2CenterStaticSpec | MC2CenterStaticMetadata:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    bind_rotations = np.ascontiguousarray(vertex_bind_pose_rotations, dtype=np.float64)
    if bind_rotations.shape != (proxy.vertex_count, 4):
        raise ValueError("vertex bind rotation count mismatch")

    from .native import native_module

    derived = native_module().mc2_build_center_static_derived_v0(
        np.ascontiguousarray(proxy.local_positions, dtype=np.float64),
        np.ascontiguousarray(proxy.local_normals, dtype=np.float64),
        np.ascontiguousarray(proxy.local_tangents, dtype=np.float64),
        np.ascontiguousarray(proxy.vertex_attributes, dtype=np.uint8),
        bind_rotations,
        np.ascontiguousarray(proxy.edges, dtype=np.int32).reshape((-1, 2)),
        np.ascontiguousarray(world_gravity_direction, dtype=np.float64),
    )
    fixed = tuple(int(value) for value in derived["fixed_indices"])
    center = tuple(float(value) for value in derived["local_center_position"])
    gravity = tuple(float(value) for value in derived["initial_local_gravity_direction"])
    signature = _center_static_signature(
        task_id=proxy.task_id,
        proxy_signature=proxy.proxy_signature,
        fixed_indices=derived["fixed_indices"],
        local_center_position=derived["local_center_position"],
        initial_local_gravity_direction=derived["initial_local_gravity_direction"],
    )
    if native_context is not None:
        metadata = MC2CenterStaticMetadata(
            task_id=proxy.task_id,
            proxy_signature=proxy.proxy_signature,
            fixed_count=len(derived["fixed_indices"]),
            center_static_signature=signature,
        )
        native_context.update_center_derived(derived)
        return metadata
    return MC2CenterStaticSpec(
        task_id=proxy.task_id,
        proxy_signature=proxy.proxy_signature,
        fixed_indices=fixed,
        local_center_position=center,
        initial_local_gravity_direction=gravity,
        center_static_signature=signature,
    )


def pack_mc2_center_static(spec: MC2CenterStaticSpec) -> dict[str, np.ndarray]:
    if not isinstance(spec, MC2CenterStaticSpec):
        raise TypeError("spec must be MC2CenterStaticSpec")
    arrays = {
        "fixed_indices": np.ascontiguousarray(spec.fixed_indices, dtype=np.int32),
        "local_center_position": np.ascontiguousarray(spec.local_center_position, dtype=np.float32),
        "initial_local_gravity_direction": np.ascontiguousarray(
            spec.initial_local_gravity_direction, dtype=np.float32
        ),
    }
    for value in arrays.values():
        value.setflags(write=False)
    return arrays


@dataclass(frozen=True)
class MC2CenterFramePoseSpec:
    frame: int
    generation: int
    component_identity: str
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_scale: tuple[float, float, float]
    anchor_identity: str = ""
    anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION

    def __post_init__(self) -> None:
        if not self.component_identity:
            raise ValueError("Center frame requires stable component identity")
        _vector(self.component_world_position, 3, "component_world_position")
        _require_unit_quaternion(self.component_world_rotation_xyzw, "component_world_rotation_xyzw")
        _vector(self.component_world_scale, 3, "component_world_scale")
        _vector(self.anchor_world_position, 3, "anchor_world_position")
        _require_unit_quaternion(self.anchor_world_rotation_xyzw, "anchor_world_rotation_xyzw")


@dataclass(frozen=True)
class MC2CenterWorldPoseSpec:
    position: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    negative_scale_direction: tuple[float, float, float]

    def __post_init__(self) -> None:
        _vector(self.position, 3, "Center world position")
        _require_unit_quaternion(self.rotation_xyzw, "Center world rotation")
        scale = _vector(self.scale, 3, "Center world scale")
        if any(abs(value) <= 1.0e-8 for value in scale):
            raise ValueError("Center world scale cannot contain zero")
        if any(float(value) not in (-1.0, 1.0) for value in self.negative_scale_direction):
            raise ValueError("negative_scale_direction must contain only -1 or 1")


def derive_mc2_center_world_pose(
    center_static: MC2CenterStaticSpec,
    frame_pose: MC2CenterFramePoseSpec,
    *,
    world_positions,
    world_rotations_xyzw,
    vertex_bind_pose_rotations,
) -> MC2CenterWorldPoseSpec:
    """Reproduce TeamManager's fixed-point/component Center frame pose producer."""
    if not isinstance(center_static, MC2CenterStaticSpec):
        raise TypeError("center_static must be MC2CenterStaticSpec")
    if not isinstance(frame_pose, MC2CenterFramePoseSpec):
        raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
    positions = np.asarray(world_positions, dtype=np.float32)
    rotations = np.asarray(world_rotations_xyzw, dtype=np.float32)
    bind_rotations = np.asarray(vertex_bind_pose_rotations, dtype=np.float32)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("world_positions must have shape [N,3]")
    if rotations.shape != (len(positions), 4):
        raise ValueError("world_rotations_xyzw must have shape [N,4]")
    if bind_rotations.shape != (len(positions), 4):
        raise ValueError("Center bind rotation count mismatch")
    if (
        not np.isfinite(positions).all()
        or not np.isfinite(rotations).all()
        or not np.isfinite(bind_rotations).all()
    ):
        raise ValueError("Center frame arrays cannot contain NaN/Inf")
    rotation_lengths = np.linalg.norm(rotations, axis=1)
    invalid = np.flatnonzero(~np.isclose(rotation_lengths, 1.0, rtol=1.0e-5, atol=1.0e-6))
    if len(invalid):
        raise ValueError(f"world_rotations_xyzw[{int(invalid[0])}] must be a unit quaternion")
    bind_lengths = np.linalg.norm(bind_rotations, axis=1)
    invalid = np.flatnonzero(~np.isclose(bind_lengths, 1.0, rtol=1.0e-5, atol=1.0e-6))
    if len(invalid):
        raise ValueError(f"vertex_bind_pose_rotations[{int(invalid[0])}] must be a unit quaternion")

    scale = tuple(float(value) for value in frame_pose.component_world_scale)
    negative_direction = tuple(-1.0 if value < 0.0 else 1.0 for value in scale)
    fixed = center_static.fixed_indices
    if not fixed:
        return MC2CenterWorldPoseSpec(
            position=tuple(frame_pose.component_world_position),
            rotation_xyzw=tuple(frame_pose.component_world_rotation_xyzw),
            scale=scale,
            negative_scale_direction=negative_direction,
        )
    if min(fixed) < 0 or max(fixed) >= len(positions):
        raise ValueError("Center fixed index is outside the frame particle range")

    center_position = tuple(
        float(np.mean(positions[np.asarray(fixed, dtype=np.intp), axis], dtype=np.float32))
        for axis in range(3)
    )
    normal_sum = np.zeros(3, dtype=np.float32)
    tangent_sum = np.zeros(3, dtype=np.float32)
    has_negative_scale = any(value < 0.0 for value in scale)
    for index in fixed:
        rotation = tuple(float(value) for value in rotations[index])
        if has_negative_scale:
            normal = _rotate(rotation, (0.0, 1.0, 0.0))
            tangent = _rotate(rotation, (0.0, 0.0, 1.0))
            rotation = mc2_world_rotation_xyzw(
                tuple(-value for value in normal),
                tuple(-value for value in tangent),
            )
        corrected = _unit_quaternion(
            quaternion_multiply_xyzw_tuple(rotation, bind_rotations[index]),
            "corrected Center frame rotation",
        )
        normal_sum += np.asarray(_rotate(corrected, (0.0, 1.0, 0.0)), dtype=np.float32)
        tangent_sum += np.asarray(_rotate(corrected, (0.0, 0.0, 1.0)), dtype=np.float32)
    if negative_direction[0] < 0.0 or negative_direction[2] < 0.0:
        normal_sum *= np.float32(-1.0)
    if negative_direction[0] < 0.0 or negative_direction[1] < 0.0:
        tangent_sum *= np.float32(-1.0)
    center_rotation = mc2_world_rotation_xyzw(
        _normalize3(normal_sum, "Center frame normal"),
        _normalize3(tangent_sum, "Center frame tangent"),
    )
    return MC2CenterWorldPoseSpec(
        position=center_position,
        rotation_xyzw=tuple(center_rotation),
        scale=scale,
        negative_scale_direction=negative_direction,
    )


@dataclass
class MC2CenterPersistentState:
    center_static_signature: str
    component_identity: str = ""
    anchor_identity: str = ""
    initialized: bool = False
    reset_count: int = 0
    old_component_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_component_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    old_component_world_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    old_anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_anchor_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    anchor_component_local_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_frame_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_frame_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    old_frame_world_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    old_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    initial_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    velocity_weight: float = 1.0
    last_frame: int | None = None
    last_generation: int | None = None
    smoothing_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    negative_scale_direction: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def reset(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        center_position,
        center_rotation_xyzw,
        *,
        velocity_weight: float = 0.0,
    ) -> None:
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        center_position = _vector(center_position, 3, "center_position")
        center_rotation = _unit_quaternion(center_rotation_xyzw, "center_rotation_xyzw")
        if not 0.0 <= float(velocity_weight) <= 1.0:
            raise ValueError("velocity_weight must be in 0..1")
        self.component_identity = frame_pose.component_identity
        self.old_component_world_position = tuple(frame_pose.component_world_position)
        self.old_component_world_rotation_xyzw = _unit_quaternion(
            frame_pose.component_world_rotation_xyzw, "component_world_rotation_xyzw"
        )
        self.old_component_world_scale = tuple(frame_pose.component_world_scale)
        self._commit_anchor_pose(frame_pose)
        self.old_frame_world_position = center_position
        self.old_frame_world_rotation_xyzw = center_rotation
        self.old_frame_world_scale = tuple(frame_pose.component_world_scale)
        self.old_world_position = center_position
        self.old_world_rotation_xyzw = center_rotation
        if not self.initialized:
            self.initial_scale = tuple(frame_pose.component_world_scale)
        self.velocity_weight = float(velocity_weight)
        self.last_frame = int(frame_pose.frame)
        self.last_generation = int(frame_pose.generation)
        self.smoothing_velocity = (0.0, 0.0, 0.0)
        self.negative_scale_direction = tuple(
            -1.0 if value < 0.0 else 1.0
            for value in frame_pose.component_world_scale
        )
        self.reset_count += 1
        self.initialized = True

    def make_negative_scale_transition(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        center_pose: MC2CenterWorldPoseSpec,
    ) -> MC2NegativeScaleTransitionResult:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before scale transition")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if not isinstance(center_pose, MC2CenterWorldPoseSpec):
            raise TypeError("center_pose must be MC2CenterWorldPoseSpec")
        return evaluate_mc2_negative_scale_transition(
            MC2NegativeScaleTransitionInputSpec(
                old_negative_scale_direction=self.negative_scale_direction,
                old_component_world_position=self.old_component_world_position,
                old_component_world_rotation_xyzw=self.old_component_world_rotation_xyzw,
                old_component_world_scale=self.old_component_world_scale,
                component_world_position=frame_pose.component_world_position,
                component_world_rotation_xyzw=frame_pose.component_world_rotation_xyzw,
                component_world_scale=frame_pose.component_world_scale,
                old_frame_world_position=self.old_frame_world_position,
                old_frame_world_rotation_xyzw=self.old_frame_world_rotation_xyzw,
                old_frame_world_scale=self.old_frame_world_scale,
                frame_world_position=center_pose.position,
                frame_world_rotation_xyzw=center_pose.rotation_xyzw,
                frame_world_scale=center_pose.scale,
                old_anchor_world_position=self.old_anchor_world_position,
                smoothing_velocity=self.smoothing_velocity,
            )
        )

    def apply_negative_scale_transition(
        self,
        result: MC2NegativeScaleTransitionResult,
    ) -> None:
        if not isinstance(result, MC2NegativeScaleTransitionResult):
            raise TypeError("result must be MC2NegativeScaleTransitionResult")
        self.negative_scale_direction = tuple(result.negative_scale_direction)
        if not result.active:
            return
        self.old_component_world_position = tuple(result.old_component_world_position)
        self.old_component_world_scale = tuple(result.old_component_world_scale)
        self.old_anchor_world_position = tuple(result.old_anchor_world_position)
        self.smoothing_velocity = tuple(result.smoothing_velocity)

    def make_step_input(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        center_pose: MC2CenterWorldPoseSpec,
        *,
        simulation_delta_time: float,
        frame_interpolation: float,
        distance_weight: float = 1.0,
        frame_shift: MC2CenterFrameShiftResult | None = None,
    ) -> MC2CenterStepInputSpec:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before stepping")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if not isinstance(center_pose, MC2CenterWorldPoseSpec):
            raise TypeError("center_pose must be MC2CenterWorldPoseSpec")
        if frame_pose.component_identity != self.component_identity:
            raise ValueError("Center component identity changed without reset")
        if frame_shift is not None and not isinstance(frame_shift, MC2CenterFrameShiftResult):
            raise TypeError("frame_shift must be MC2CenterFrameShiftResult")
        return MC2CenterStepInputSpec(
            simulation_delta_time=float(simulation_delta_time),
            frame_interpolation=float(frame_interpolation),
            old_frame_world_position=(
                frame_shift.old_frame_world_position
                if frame_shift is not None
                else self.old_frame_world_position
            ),
            frame_world_position=center_pose.position,
            old_frame_world_rotation_xyzw=(
                frame_shift.old_frame_world_rotation_xyzw
                if frame_shift is not None
                else self.old_frame_world_rotation_xyzw
            ),
            frame_world_rotation_xyzw=center_pose.rotation_xyzw,
            old_frame_world_scale=self.old_frame_world_scale,
            frame_world_scale=center_pose.scale,
            old_world_position=(
                frame_shift.now_world_position
                if frame_shift is not None
                else self.old_world_position
            ),
            old_world_rotation_xyzw=(
                frame_shift.now_world_rotation_xyzw
                if frame_shift is not None
                else self.old_world_rotation_xyzw
            ),
            initial_scale=self.initial_scale,
            negative_scale_direction=center_pose.negative_scale_direction,
            velocity_weight=self.velocity_weight,
            distance_weight=float(distance_weight),
        )

    def make_frame_shift_input(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        *,
        center_pose: MC2CenterWorldPoseSpec | None = None,
        simulation_delta_time: float,
        frame_delta_time: float,
        world_inertia: float,
        movement_speed_limit: float = -1.0,
        rotation_speed_limit: float = -1.0,
        anchor_inertia: float = 0.0,
        movement_inertia_smoothing: float = 0.0,
        is_running: bool = True,
        now_time_scale: float = 1.0,
        skip_count: int = 0,
        teleport_mode: int = 0,
        teleport_distance: float = 0.5,
        teleport_rotation: float = 90.0,
        negative_scale_transition: MC2NegativeScaleTransitionResult | None = None,
    ) -> MC2CenterFrameShiftInputSpec:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before frame shift")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if frame_pose.component_identity != self.component_identity:
            raise ValueError("Center component identity changed without reset")
        if center_pose is not None and not isinstance(center_pose, MC2CenterWorldPoseSpec):
            raise TypeError("center_pose must be MC2CenterWorldPoseSpec")
        if negative_scale_transition is not None and not isinstance(
            negative_scale_transition, MC2NegativeScaleTransitionResult
        ):
            raise TypeError(
                "negative_scale_transition must be MC2NegativeScaleTransitionResult"
            )
        transition = (
            negative_scale_transition
            if negative_scale_transition is not None and negative_scale_transition.active
            else None
        )
        if transition is not None and center_pose is None:
            raise ValueError(
                "active negative_scale_transition requires the current Center pose"
            )
        return MC2CenterFrameShiftInputSpec(
            simulation_delta_time=float(simulation_delta_time),
            frame_delta_time=float(frame_delta_time),
            now_time_scale=float(now_time_scale),
            velocity_weight=float(self.velocity_weight),
            skip_count=skip_count,
            world_inertia=float(world_inertia),
            movement_speed_limit=float(movement_speed_limit),
            rotation_speed_limit=float(rotation_speed_limit),
            old_component_world_position=(
                transition.old_component_world_position
                if transition is not None
                else self.old_component_world_position
            ),
            old_component_world_rotation_xyzw=self.old_component_world_rotation_xyzw,
            component_world_position=frame_pose.component_world_position,
            component_world_rotation_xyzw=frame_pose.component_world_rotation_xyzw,
            old_frame_world_position=(
                center_pose.position
                if transition is not None
                else self.old_frame_world_position
            ),
            old_frame_world_rotation_xyzw=(
                center_pose.rotation_xyzw
                if transition is not None
                else self.old_frame_world_rotation_xyzw
            ),
            now_world_position=(
                center_pose.position
                if transition is not None
                else self.old_world_position
            ),
            now_world_rotation_xyzw=(
                center_pose.rotation_xyzw
                if transition is not None
                else self.old_world_rotation_xyzw
            ),
            use_anchor=bool(
                self.anchor_identity
                and self.anchor_identity == frame_pose.anchor_identity
            ),
            anchor_inertia=float(anchor_inertia),
            old_anchor_world_position=(
                transition.old_anchor_world_position
                if transition is not None
                else self.old_anchor_world_position
            ),
            old_anchor_world_rotation_xyzw=self.old_anchor_world_rotation_xyzw,
            anchor_world_position=frame_pose.anchor_world_position,
            anchor_world_rotation_xyzw=frame_pose.anchor_world_rotation_xyzw,
            anchor_component_local_position=self.anchor_component_local_position,
            movement_inertia_smoothing=float(movement_inertia_smoothing),
            smoothing_velocity=(
                transition.smoothing_velocity
                if transition is not None
                else self.smoothing_velocity
            ),
            is_running=is_running,
            frame_world_position=(center_pose.position if center_pose is not None else None),
            frame_world_rotation_xyzw=(
                center_pose.rotation_xyzw if center_pose is not None else None
            ),
            component_world_scale=frame_pose.component_world_scale,
            initial_scale=self.initial_scale,
            teleport_mode=teleport_mode,
            teleport_distance=teleport_distance,
            teleport_rotation=teleport_rotation,
        )

    def commit_frame_shift(self, result: MC2CenterFrameShiftResult | None) -> None:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before commit")
        if result is None:
            return
        if not isinstance(result, MC2CenterFrameShiftResult):
            raise TypeError("result must be MC2CenterFrameShiftResult")
        self.smoothing_velocity = tuple(result.smoothing_velocity)

    def commit_paused_frame(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        result: MC2CenterFrameShiftResult,
    ) -> None:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before commit")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if not isinstance(result, MC2CenterFrameShiftResult):
            raise TypeError("result must be MC2CenterFrameShiftResult")
        self.old_component_world_position = tuple(frame_pose.component_world_position)
        self.old_component_world_rotation_xyzw = tuple(
            frame_pose.component_world_rotation_xyzw
        )
        self.old_component_world_scale = tuple(frame_pose.component_world_scale)
        self.negative_scale_direction = tuple(
            -1.0 if value < 0.0 else 1.0
            for value in frame_pose.component_world_scale
        )
        self._commit_anchor_pose(frame_pose)
        self.smoothing_velocity = tuple(result.smoothing_velocity)
        self.old_frame_world_position = tuple(result.old_frame_world_position)
        self.old_frame_world_rotation_xyzw = tuple(
            result.old_frame_world_rotation_xyzw
        )
        self.old_world_position = tuple(result.now_world_position)
        self.old_world_rotation_xyzw = tuple(result.now_world_rotation_xyzw)
        self.last_frame = int(frame_pose.frame)
        self.last_generation = int(frame_pose.generation)

    def _commit_anchor_pose(self, frame_pose: MC2CenterFramePoseSpec) -> None:
        self.anchor_identity = frame_pose.anchor_identity
        if not frame_pose.anchor_identity:
            self.old_anchor_world_position = (0.0, 0.0, 0.0)
            self.old_anchor_world_rotation_xyzw = IDENTITY_QUATERNION
            self.anchor_component_local_position = (0.0, 0.0, 0.0)
            return
        self.old_anchor_world_position = tuple(frame_pose.anchor_world_position)
        self.old_anchor_world_rotation_xyzw = tuple(frame_pose.anchor_world_rotation_xyzw)
        self.anchor_component_local_position = tuple(
            float(value)
            for value in _inverse_transform_point_unit_scale_f32(
                frame_pose.component_world_position,
                frame_pose.anchor_world_position,
                frame_pose.anchor_world_rotation_xyzw,
            )
        )

    def commit_step(
        self,
        frame_pose: MC2CenterFramePoseSpec,
        center_pose: MC2CenterWorldPoseSpec,
        result: MC2CenterStepResult,
    ) -> None:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before commit")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if not isinstance(center_pose, MC2CenterWorldPoseSpec):
            raise TypeError("center_pose must be MC2CenterWorldPoseSpec")
        if not isinstance(result, MC2CenterStepResult):
            raise TypeError("result must be MC2CenterStepResult")
        self.old_component_world_position = tuple(frame_pose.component_world_position)
        self.old_component_world_rotation_xyzw = tuple(frame_pose.component_world_rotation_xyzw)
        self.old_component_world_scale = tuple(frame_pose.component_world_scale)
        self.negative_scale_direction = tuple(center_pose.negative_scale_direction)
        self._commit_anchor_pose(frame_pose)
        self.old_frame_world_position = tuple(center_pose.position)
        self.old_frame_world_rotation_xyzw = tuple(center_pose.rotation_xyzw)
        self.old_frame_world_scale = tuple(center_pose.scale)
        self.old_world_position = tuple(result.now_world_position)
        self.old_world_rotation_xyzw = tuple(result.now_world_rotation_xyzw)
        self.velocity_weight = float(result.velocity_weight)
        self.last_frame = int(frame_pose.frame)
        self.last_generation = int(frame_pose.generation)

    def debug_dict(self) -> dict:
        return {
            "center_static_signature": self.center_static_signature,
            "component_identity": self.component_identity,
            "anchor_identity": self.anchor_identity,
            "old_anchor_world_position": self.old_anchor_world_position,
            "old_anchor_world_rotation_xyzw": self.old_anchor_world_rotation_xyzw,
            "anchor_component_local_position": self.anchor_component_local_position,
            "initialized": self.initialized,
            "reset_count": self.reset_count,
            "last_frame": self.last_frame,
            "last_generation": self.last_generation,
            "velocity_weight": self.velocity_weight,
            "smoothing_velocity": self.smoothing_velocity,
            "negative_scale_direction": self.negative_scale_direction,
            "old_frame_world_position": self.old_frame_world_position,
            "old_world_position": self.old_world_position,
        }


@dataclass(frozen=True)
class MC2CenterFrameShiftInputSpec:
    """Source-aligned world-inertia inputs before Center substep derivation.

    V0 covers component or fixed-derived Center frames after any verified
    negative-scale transition, with optional anchor, movement smoothing, and
    configured Keep/Reset teleport. Synchronization and culling remain outside
    this evaluator.
    """

    simulation_delta_time: float
    frame_delta_time: float
    now_time_scale: float
    velocity_weight: float
    skip_count: int
    world_inertia: float
    movement_speed_limit: float
    rotation_speed_limit: float
    old_component_world_position: tuple[float, float, float]
    old_component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    old_frame_world_position: tuple[float, float, float]
    old_frame_world_rotation_xyzw: tuple[float, float, float, float]
    now_world_position: tuple[float, float, float]
    now_world_rotation_xyzw: tuple[float, float, float, float]
    use_anchor: bool = False
    anchor_inertia: float = 0.0
    old_anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    old_anchor_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    anchor_world_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    anchor_world_rotation_xyzw: tuple[float, float, float, float] = IDENTITY_QUATERNION
    anchor_component_local_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    movement_inertia_smoothing: float = 0.0
    smoothing_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_running: bool = True
    frame_world_position: tuple[float, float, float] | None = None
    frame_world_rotation_xyzw: tuple[float, float, float, float] | None = None
    component_world_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    initial_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    teleport_mode: int = 0
    teleport_distance: float = 0.5
    teleport_rotation: float = 90.0

    def __post_init__(self) -> None:
        simulation_dt = float(self.simulation_delta_time)
        if not math.isfinite(simulation_dt) or simulation_dt < 0.0:
            raise ValueError("simulation_delta_time must be finite and non-negative")
        frame_dt = float(self.frame_delta_time)
        if not math.isfinite(frame_dt) or frame_dt <= 0.0:
            raise ValueError("frame_delta_time must be finite and positive")
        time_scale = float(self.now_time_scale)
        if not math.isfinite(time_scale) or time_scale < 0.0:
            raise ValueError("now_time_scale must be finite and non-negative")
        if not 0.0 <= float(self.velocity_weight) <= 1.0:
            raise ValueError("velocity_weight must be in 0..1")
        if isinstance(self.skip_count, bool) or int(self.skip_count) != self.skip_count:
            raise ValueError("skip_count must be an integer")
        if self.skip_count < 0:
            raise ValueError("skip_count cannot be negative")
        if not 0.0 <= float(self.world_inertia) <= 1.0:
            raise ValueError("world_inertia must be in 0..1")
        if not isinstance(self.use_anchor, bool):
            raise TypeError("use_anchor must be bool")
        if not 0.0 <= float(self.anchor_inertia) <= 1.0:
            raise ValueError("anchor_inertia must be in 0..1")
        if not 0.0 <= float(self.movement_inertia_smoothing) <= 1.0:
            raise ValueError("movement_inertia_smoothing must be in 0..1")
        if not isinstance(self.is_running, bool):
            raise TypeError("is_running must be bool")
        if (
            isinstance(self.teleport_mode, bool)
            or int(self.teleport_mode) != self.teleport_mode
            or int(self.teleport_mode) not in (0, 1, 2)
        ):
            raise ValueError("teleport_mode must be 0, 1, or 2")
        for name in ("teleport_distance", "teleport_rotation"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in ("movement_speed_limit", "rotation_speed_limit"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        for name in (
            "old_component_world_position",
            "component_world_position",
            "old_frame_world_position",
            "now_world_position",
            "old_anchor_world_position",
            "anchor_world_position",
            "anchor_component_local_position",
            "smoothing_velocity",
            "component_world_scale",
            "initial_scale",
        ):
            _vector(getattr(self, name), 3, name)
        for name in ("component_world_scale", "initial_scale"):
            if any(abs(float(value)) <= 1.0e-8 for value in getattr(self, name)):
                raise ValueError(f"{name} cannot contain zero")
        if self.frame_world_position is not None:
            _vector(self.frame_world_position, 3, "frame_world_position")
        for name in (
            "old_component_world_rotation_xyzw",
            "component_world_rotation_xyzw",
            "old_frame_world_rotation_xyzw",
            "now_world_rotation_xyzw",
            "old_anchor_world_rotation_xyzw",
            "anchor_world_rotation_xyzw",
        ):
            _require_unit_quaternion(getattr(self, name), name)
        if self.frame_world_rotation_xyzw is not None:
            _require_unit_quaternion(
                self.frame_world_rotation_xyzw,
                "frame_world_rotation_xyzw",
            )


@dataclass(frozen=True)
class MC2CenterFrameShiftResult:
    frame_component_shift_vector: tuple[float, float, float]
    frame_component_shift_rotation_xyzw: tuple[float, float, float, float]
    old_frame_world_position: tuple[float, float, float]
    old_frame_world_rotation_xyzw: tuple[float, float, float, float]
    now_world_position: tuple[float, float, float]
    now_world_rotation_xyzw: tuple[float, float, float, float]
    frame_world_position: tuple[float, float, float]
    frame_world_rotation_xyzw: tuple[float, float, float, float]
    frame_moving_direction: tuple[float, float, float]
    frame_moving_speed: float
    smoothing_velocity: tuple[float, float, float]
    keep_teleport: bool = False
    reset_teleport: bool = False


@dataclass(frozen=True)
class MC2NegativeScaleTransitionInputSpec:
    old_negative_scale_direction: tuple[float, float, float]
    old_component_world_position: tuple[float, float, float]
    old_component_world_rotation_xyzw: tuple[float, float, float, float]
    old_component_world_scale: tuple[float, float, float]
    component_world_position: tuple[float, float, float]
    component_world_rotation_xyzw: tuple[float, float, float, float]
    component_world_scale: tuple[float, float, float]
    old_frame_world_position: tuple[float, float, float]
    old_frame_world_rotation_xyzw: tuple[float, float, float, float]
    old_frame_world_scale: tuple[float, float, float]
    frame_world_position: tuple[float, float, float]
    frame_world_rotation_xyzw: tuple[float, float, float, float]
    frame_world_scale: tuple[float, float, float]
    old_anchor_world_position: tuple[float, float, float]
    smoothing_velocity: tuple[float, float, float]

    def __post_init__(self) -> None:
        for name in (
            "old_negative_scale_direction",
            "old_component_world_position", "old_component_world_scale",
            "component_world_position", "component_world_scale",
            "old_frame_world_position", "old_frame_world_scale",
            "frame_world_position", "frame_world_scale",
            "old_anchor_world_position", "smoothing_velocity",
        ):
            _vector(getattr(self, name), 3, name)
        for name in (
            "old_component_world_rotation_xyzw",
            "component_world_rotation_xyzw",
            "old_frame_world_rotation_xyzw",
            "frame_world_rotation_xyzw",
        ):
            _require_unit_quaternion(getattr(self, name), name)
        if any(value not in (-1.0, 1.0) for value in self.old_negative_scale_direction):
            raise ValueError("old_negative_scale_direction must contain only -1 or 1")
        for name in (
            "old_component_world_scale", "component_world_scale",
            "old_frame_world_scale", "frame_world_scale",
        ):
            if any(abs(value) <= 1.0e-8 for value in getattr(self, name)):
                raise ValueError(f"{name} cannot contain zero")


@dataclass(frozen=True)
class MC2NegativeScaleTransitionResult:
    active: bool
    negative_scale_sign: float
    negative_scale_direction: tuple[float, float, float]
    negative_scale_change: tuple[float, float, float]
    negative_scale_triangle_sign: tuple[float, float]
    negative_scale_quaternion_value: tuple[float, float, float, float]
    component_negative_matrix: tuple[tuple[float, float, float, float], ...]
    center_negative_matrix: tuple[tuple[float, float, float, float], ...]
    old_component_world_position: tuple[float, float, float]
    old_component_world_scale: tuple[float, float, float]
    old_anchor_world_position: tuple[float, float, float]
    smoothing_velocity: tuple[float, float, float]


@dataclass(frozen=True)
class MC2CenterStepInputSpec:
    simulation_delta_time: float
    frame_interpolation: float
    old_frame_world_position: tuple[float, float, float]
    frame_world_position: tuple[float, float, float]
    old_frame_world_rotation_xyzw: tuple[float, float, float, float]
    frame_world_rotation_xyzw: tuple[float, float, float, float]
    old_frame_world_scale: tuple[float, float, float]
    frame_world_scale: tuple[float, float, float]
    old_world_position: tuple[float, float, float]
    old_world_rotation_xyzw: tuple[float, float, float, float]
    initial_scale: tuple[float, float, float]
    negative_scale_direction: tuple[float, float, float]
    velocity_weight: float
    distance_weight: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.simulation_delta_time) or self.simulation_delta_time <= 0.0:
            raise ValueError("simulation_delta_time must be finite and positive")
        if not 0.0 <= self.frame_interpolation <= 1.0:
            raise ValueError("frame_interpolation must be in 0..1")
        for name in (
            "old_frame_world_position", "frame_world_position",
            "old_frame_world_scale", "frame_world_scale",
            "old_world_position", "initial_scale", "negative_scale_direction",
        ):
            _vector(getattr(self, name), 3, name)
        for name in ("old_frame_world_rotation_xyzw", "frame_world_rotation_xyzw", "old_world_rotation_xyzw"):
            _require_unit_quaternion(getattr(self, name), name)
        if any(abs(value) <= 1.0e-8 for value in self.initial_scale):
            raise ValueError("initial_scale cannot contain zero")
        if any(float(value) not in (-1.0, 1.0) for value in self.negative_scale_direction):
            raise ValueError("negative_scale_direction must contain only -1 or 1")
        if not 0.0 <= self.velocity_weight <= 1.0 or not 0.0 <= self.distance_weight <= 1.0:
            raise ValueError("Center weights must be in 0..1")


@dataclass(frozen=True)
class MC2CenterStepResult:
    frame_interpolation: float
    now_world_position: tuple[float, float, float]
    now_world_rotation_xyzw: tuple[float, float, float, float]
    step_vector: tuple[float, float, float]
    step_rotation_xyzw: tuple[float, float, float, float]
    step_move_inertia_ratio: float
    step_rotation_inertia_ratio: float
    inertia_vector: tuple[float, float, float]
    inertia_rotation_xyzw: tuple[float, float, float, float]
    angular_velocity: float
    rotation_axis: tuple[float, float, float]
    scale_ratio: float
    gravity_dot: float
    gravity_ratio: float
    velocity_weight: float
    blend_weight: float


def _f32_vector(values, width: int, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=np.float32)
    if result.shape != (width,) or not np.isfinite(result).all():
        raise ValueError(f"{name} must contain {width} finite values")
    return result


def _normalize_quaternion_f32(value: np.ndarray) -> np.ndarray:
    _f32(np.linalg.norm(value))
    return normalize_quaternion_f32(
        value,
        zero_epsilon=1.0e-8,
        zero_message="Center quaternion cannot be zero",
    )


def _quaternion_slerp_f32(first: np.ndarray, second: np.ndarray, ratio) -> np.ndarray:
    ratio = _f32(ratio)
    return quaternion_slerp_unit_f32(
        first,
        second,
        ratio,
        zero_epsilon=1.0e-8,
        zero_message="Center quaternion cannot be zero",
    )


def _inverse_quaternion_f32(rotation: np.ndarray) -> np.ndarray:
    return quaternion_conjugate_f32(rotation)


def _shift_position_f32(position, pivot, shift_vector, shift_rotation) -> np.ndarray:
    return np.asarray(
        pivot + rotate_vector_unit_quaternion_f32(shift_rotation, position - pivot) + shift_vector,
        dtype=np.float32,
    )


def _inverse_transform_point_unit_scale_f32(position, origin, rotation) -> np.ndarray:
    position = _f32_vector(position, 3, "position")
    origin = _f32_vector(origin, 3, "origin")
    rotation = _f32_vector(rotation, 4, "rotation")
    return rotate_vector_unit_quaternion_f32(_inverse_quaternion_f32(rotation), position - origin)


def _quaternion_matrix_f32(rotation) -> np.ndarray:
    return quaternion_matrix_unit_f32(_f32_vector(rotation, 4, "rotation"))


def _trs_matrix_f32(position, rotation, scale) -> np.ndarray:
    result = np.eye(4, dtype=np.float32)
    result[:3, :3] = _quaternion_matrix_f32(rotation) * _f32_vector(
        scale, 3, "scale"
    )[np.newaxis, :]
    result[:3, 3] = _f32_vector(position, 3, "position")
    return result


def _transform_point_matrix_f32(position, matrix: np.ndarray) -> np.ndarray:
    return transform_point_matrix_f32(
        _f32_vector(position, 3, "position"),
        matrix,
    )


def _transform_vector_matrix_f32(vector, matrix: np.ndarray) -> np.ndarray:
    return transform_vector_matrix_f32(
        _f32_vector(vector, 3, "vector"),
        matrix,
    )


def _matrix_tuple(matrix: np.ndarray) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)


def evaluate_mc2_negative_scale_transition(
    transition: MC2NegativeScaleTransitionInputSpec,
) -> MC2NegativeScaleTransitionResult:
    """Build MC2's component/Center matrices for a scale-sign transition."""
    if not isinstance(transition, MC2NegativeScaleTransitionInputSpec):
        raise TypeError("transition must be MC2NegativeScaleTransitionInputSpec")
    old_direction = _f32_vector(
        transition.old_negative_scale_direction, 3, "old_negative_scale_direction"
    )
    scale = _f32_vector(
        transition.component_world_scale, 3, "component_world_scale"
    )
    direction = np.where(scale < _f32(0.0), _f32(-1.0), _f32(1.0)).astype(
        np.float32
    )
    change = np.asarray(old_direction * direction, dtype=np.float32)
    active = not np.array_equal(old_direction, direction)
    negative = bool(np.any(scale < _f32(0.0)))
    negative_sign = -1.0 if negative else 1.0
    triangle_sign = (
        -1.0 if scale[0] < 0.0 or scale[2] < 0.0 else 1.0,
        -1.0 if scale[0] < 0.0 else 1.0,
    ) if negative else (1.0, 1.0)
    quaternion_value = tuple(
        float(value)
        for value in (
            np.concatenate((-direction, np.asarray((1.0,), dtype=np.float32)))
            if negative
            else np.ones(4, dtype=np.float32)
        )
    )
    identity = np.eye(4, dtype=np.float32)
    if not active:
        return MC2NegativeScaleTransitionResult(
            active=False,
            negative_scale_sign=negative_sign,
            negative_scale_direction=tuple(float(value) for value in direction),
            negative_scale_change=tuple(float(value) for value in change),
            negative_scale_triangle_sign=triangle_sign,
            negative_scale_quaternion_value=quaternion_value,
            component_negative_matrix=_matrix_tuple(identity),
            center_negative_matrix=_matrix_tuple(identity),
            old_component_world_position=tuple(transition.old_component_world_position),
            old_component_world_scale=tuple(transition.old_component_world_scale),
            old_anchor_world_position=tuple(transition.old_anchor_world_position),
            smoothing_velocity=tuple(transition.smoothing_velocity),
        )

    component_matrix = np.asarray(
        _trs_matrix_f32(
            transition.component_world_position,
            transition.component_world_rotation_xyzw,
            transition.component_world_scale,
        )
        @ np.linalg.inv(
            _trs_matrix_f32(
                transition.old_component_world_position,
                transition.old_component_world_rotation_xyzw,
                transition.old_component_world_scale,
            )
        ).astype(np.float32),
        dtype=np.float32,
    )
    center_matrix = np.asarray(
        _trs_matrix_f32(
            transition.frame_world_position,
            transition.frame_world_rotation_xyzw,
            transition.frame_world_scale,
        )
        @ np.linalg.inv(
            _trs_matrix_f32(
                transition.old_frame_world_position,
                transition.old_frame_world_rotation_xyzw,
                transition.old_frame_world_scale,
            )
        ).astype(np.float32),
        dtype=np.float32,
    )
    return MC2NegativeScaleTransitionResult(
        active=True,
        negative_scale_sign=negative_sign,
        negative_scale_direction=tuple(float(value) for value in direction),
        negative_scale_change=tuple(float(value) for value in change),
        negative_scale_triangle_sign=triangle_sign,
        negative_scale_quaternion_value=quaternion_value,
        component_negative_matrix=_matrix_tuple(component_matrix),
        center_negative_matrix=_matrix_tuple(center_matrix),
        old_component_world_position=tuple(
            float(value)
            for value in _transform_point_matrix_f32(
                transition.old_component_world_position, component_matrix
            )
        ),
        old_component_world_scale=tuple(float(value) for value in scale),
        old_anchor_world_position=tuple(
            float(value)
            for value in _transform_point_matrix_f32(
                transition.old_anchor_world_position, component_matrix
            )
        ),
        smoothing_velocity=tuple(
            float(value)
            for value in _transform_vector_matrix_f32(
                transition.smoothing_velocity, component_matrix
            )
        ),
    )


def evaluate_mc2_center_frame_shift(
    frame: MC2CenterFrameShiftInputSpec,
) -> MC2CenterFrameShiftResult:
    """Evaluate verified Center shift and configured teleport domains."""
    if not isinstance(frame, MC2CenterFrameShiftInputSpec):
        raise TypeError("frame must be MC2CenterFrameShiftInputSpec")
    simulation_dt = _f32(frame.simulation_delta_time)
    frame_dt = _f32(frame.frame_delta_time)
    time_scale = _f32(frame.now_time_scale)
    old_component = _f32_vector(
        frame.old_component_world_position, 3, "old_component_world_position"
    )
    component = _f32_vector(
        frame.component_world_position, 3, "component_world_position"
    )
    old_component_rotation = _f32_vector(
        frame.old_component_world_rotation_xyzw,
        4,
        "old_component_world_rotation_xyzw",
    )
    component_rotation = _f32_vector(
        frame.component_world_rotation_xyzw, 4, "component_world_rotation_xyzw"
    )
    frame_world_position = (
        component
        if frame.frame_world_position is None
        else _f32_vector(frame.frame_world_position, 3, "frame_world_position")
    )
    frame_world_rotation = (
        component_rotation
        if frame.frame_world_rotation_xyzw is None
        else _f32_vector(
            frame.frame_world_rotation_xyzw,
            4,
            "frame_world_rotation_xyzw",
        )
    )
    anchor_shift_vector = np.zeros(3, dtype=np.float32)
    identity = np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
    anchor_shift_rotation = identity.copy()
    adjusted_old_component = old_component.copy()
    adjusted_old_component_rotation = old_component_rotation.copy()
    if frame.use_anchor:
        anchor_position = _f32_vector(
            frame.anchor_world_position, 3, "anchor_world_position"
        )
        anchor_rotation = _f32_vector(
            frame.anchor_world_rotation_xyzw, 4, "anchor_world_rotation_xyzw"
        )
        old_anchor_rotation = _f32_vector(
            frame.old_anchor_world_rotation_xyzw,
            4,
            "old_anchor_world_rotation_xyzw",
        )
        anchor_local = _f32_vector(
            frame.anchor_component_local_position,
            3,
            "anchor_component_local_position",
        )
        anchor_center = np.asarray(
            anchor_position + rotate_vector_unit_quaternion_f32(anchor_rotation, anchor_local),
            dtype=np.float32,
        )
        anchor_ratio = _f32(1.0) - _f32(frame.anchor_inertia)
        anchor_shift_vector = np.asarray(
            (anchor_center - old_component) * anchor_ratio,
            dtype=np.float32,
        )
        full_anchor_rotation = _normalize_quaternion_f32(
            quaternion_multiply_f32(
                anchor_rotation,
                _inverse_quaternion_f32(old_anchor_rotation),
            )
        )
        anchor_shift_rotation = _quaternion_slerp_f32(
            identity,
            full_anchor_rotation,
            anchor_ratio,
        )
        adjusted_old_component += anchor_shift_vector
        adjusted_old_component_rotation = _normalize_quaternion_f32(
            quaternion_multiply_f32(
                anchor_shift_rotation,
                adjusted_old_component_rotation,
            )
        )

    component_scale = _f32_vector(
        frame.component_world_scale, 3, "component_world_scale"
    )
    initial_scale = _f32_vector(frame.initial_scale, 3, "initial_scale")
    component_scale_ratio = _f32(
        _f32(np.linalg.norm(component_scale))
        / _f32(np.linalg.norm(initial_scale))
    )
    teleport_delta = np.asarray(component - adjusted_old_component, dtype=np.float32)
    teleport_cosine = np.clip(
        abs(_f32(np.dot(adjusted_old_component_rotation, component_rotation))),
        _f32(0.0),
        _f32(1.0),
    )
    teleport_angle = _f32(2.0) * _f32(np.arccos(teleport_cosine))
    teleport_triggered = bool(
        int(frame.teleport_mode) != 0
        and (
            _f32(np.linalg.norm(teleport_delta))
            >= _f32(frame.teleport_distance) * component_scale_ratio
            or _f32(np.degrees(teleport_angle)) >= _f32(frame.teleport_rotation)
        )
    )
    keep_teleport = teleport_triggered and int(frame.teleport_mode) == 2
    reset_teleport = teleport_triggered and int(frame.teleport_mode) == 1
    if reset_teleport:
        return MC2CenterFrameShiftResult(
            frame_component_shift_vector=(0.0, 0.0, 0.0),
            frame_component_shift_rotation_xyzw=IDENTITY_QUATERNION,
            old_frame_world_position=tuple(
                float(value) for value in frame_world_position
            ),
            old_frame_world_rotation_xyzw=tuple(
                float(value) for value in frame_world_rotation
            ),
            now_world_position=tuple(float(value) for value in frame_world_position),
            now_world_rotation_xyzw=tuple(
                float(value) for value in frame_world_rotation
            ),
            frame_world_position=tuple(float(value) for value in frame_world_position),
            frame_world_rotation_xyzw=tuple(
                float(value) for value in frame_world_rotation
            ),
            frame_moving_direction=(0.0, 0.0, 0.0),
            frame_moving_speed=0.0,
            smoothing_velocity=(0.0, 0.0, 0.0),
            keep_teleport=False,
            reset_teleport=True,
        )

    smooth_shift_vector = np.zeros(3, dtype=np.float32)
    smoothing_velocity = _f32_vector(
        frame.smoothing_velocity, 3, "smoothing_velocity"
    )
    smoothing = _f32(frame.movement_inertia_smoothing)
    if smoothing >= _f32(1.0e-6) and not keep_teleport:
        if frame.is_running:
            frame_delta_velocity = np.asarray(
                (component - adjusted_old_component) / frame_dt,
                dtype=np.float32,
            )
            movement_limit = _f32(frame.movement_speed_limit)
            frame_delta_speed = _f32(np.linalg.norm(frame_delta_velocity))
            if movement_limit >= _f32(0.0) and frame_delta_speed > movement_limit:
                frame_delta_velocity *= movement_limit / frame_delta_speed
            one_minus_smoothing = _f32(1.0) - smoothing
            average_ratio = np.clip(
                one_minus_smoothing
                * one_minus_smoothing
                * one_minus_smoothing
                * _f32(0.99)
                + _f32(0.01),
                _f32(0.0),
                _f32(1.0),
            )
            smoothing_velocity += (
                frame_delta_velocity - smoothing_velocity
            ) * average_ratio
        smooth_position = np.asarray(
            component - smoothing_velocity * frame_dt,
            dtype=np.float32,
        )
        smooth_shift_vector = np.asarray(
            smooth_position - adjusted_old_component,
            dtype=np.float32,
        )
        adjusted_old_component = smooth_position

    full_shift_vector = np.asarray(component - adjusted_old_component, dtype=np.float32)
    full_shift_rotation = _normalize_quaternion_f32(
        quaternion_multiply_f32(
            component_rotation,
            _inverse_quaternion_f32(adjusted_old_component_rotation),
        )
    )
    move_shift_ratio = (
        _f32(1.0)
        if keep_teleport
        else _f32(1.0) - _f32(frame.world_inertia)
    )
    rotation_shift_ratio = move_shift_ratio
    work_old_component = np.asarray(
        adjusted_old_component + full_shift_vector * move_shift_ratio,
        dtype=np.float32,
    )
    work_old_rotation = _quaternion_slerp_f32(
        adjusted_old_component_rotation,
        component_rotation,
        rotation_shift_ratio,
    )

    delta_vector = np.asarray(component - work_old_component, dtype=np.float32)
    frame_speed = _f32(np.linalg.norm(delta_vector)) / frame_dt
    movement_limit = _f32(frame.movement_speed_limit)
    if frame_speed > movement_limit and movement_limit >= 0.0:
        limit_ratio = np.clip(
            (frame_speed - movement_limit) / frame_speed,
            _f32(0.0),
            _f32(1.0),
        )
        move_shift_ratio += (_f32(1.0) - move_shift_ratio) * limit_ratio
        work_old_component += (component - work_old_component) * limit_ratio

    rotation_cosine = np.clip(
        abs(_f32(np.dot(work_old_rotation, component_rotation))),
        _f32(0.0),
        _f32(1.0),
    )
    delta_angle = _f32(2.0) * _f32(np.arccos(rotation_cosine))
    rotation_speed = _f32(np.degrees(delta_angle)) / frame_dt
    rotation_limit = _f32(frame.rotation_speed_limit)
    if rotation_speed > rotation_limit and rotation_limit >= 0.0:
        limit_ratio = np.clip(
            (rotation_speed - rotation_limit) / rotation_speed,
            _f32(0.0),
            _f32(1.0),
        )
        rotation_shift_ratio += (
            _f32(1.0) - rotation_shift_ratio
        ) * limit_ratio
        work_old_rotation = _quaternion_slerp_f32(
            work_old_rotation,
            component_rotation,
            limit_ratio,
        )

    other_shift_ratio = _f32(0.0)
    if frame.skip_count > 0:
        skip_denominator = frame_dt * time_scale
        skip_ratio = (
            _f32(1.0)
            if skip_denominator <= _f32(1.0e-8)
            else np.clip(
                (_f32(frame.skip_count) * simulation_dt) / skip_denominator,
                _f32(0.0),
                _f32(1.0),
            )
        )
        other_shift_ratio += (_f32(1.0) - other_shift_ratio) * skip_ratio
    velocity_weight = _f32(frame.velocity_weight)
    if velocity_weight < _f32(1.0):
        ratio = _f32(1.0) - velocity_weight
        other_shift_ratio += (_f32(1.0) - other_shift_ratio) * ratio
    if time_scale < _f32(1.0):
        ratio = _f32(1.0) - time_scale
        other_shift_ratio += (_f32(1.0) - other_shift_ratio) * ratio
    if other_shift_ratio > _f32(0.0):
        move_shift_ratio += (
            _f32(1.0) - move_shift_ratio
        ) * other_shift_ratio
        rotation_shift_ratio += (
            _f32(1.0) - rotation_shift_ratio
        ) * other_shift_ratio
        work_old_component += (
            component - work_old_component
        ) * other_shift_ratio
        work_old_rotation = _quaternion_slerp_f32(
            work_old_rotation,
            component_rotation,
            other_shift_ratio,
        )

    shift_vector = np.asarray(
        full_shift_vector * move_shift_ratio
        + anchor_shift_vector
        + smooth_shift_vector,
        dtype=np.float32,
    )
    world_shift_rotation = _quaternion_slerp_f32(
        identity,
        full_shift_rotation,
        rotation_shift_ratio,
    )
    shift_rotation = _normalize_quaternion_f32(
        quaternion_multiply_f32(anchor_shift_rotation, world_shift_rotation)
    )
    old_frame_position = _f32_vector(
        frame.old_frame_world_position, 3, "old_frame_world_position"
    )
    now_position = _f32_vector(frame.now_world_position, 3, "now_world_position")
    old_frame_rotation = _f32_vector(
        frame.old_frame_world_rotation_xyzw, 4, "old_frame_world_rotation_xyzw"
    )
    now_rotation = _f32_vector(
        frame.now_world_rotation_xyzw, 4, "now_world_rotation_xyzw"
    )
    shifted_old_frame = _shift_position_f32(
        old_frame_position,
        old_component,
        shift_vector,
        shift_rotation,
    )
    shifted_now = _shift_position_f32(
        now_position,
        old_component,
        shift_vector,
        shift_rotation,
    )
    shifted_old_rotation = _normalize_quaternion_f32(
        quaternion_multiply_f32(shift_rotation, old_frame_rotation)
    )
    shifted_now_rotation = _normalize_quaternion_f32(
        quaternion_multiply_f32(shift_rotation, now_rotation)
    )
    moving_vector = np.asarray(component - work_old_component, dtype=np.float32)
    moving_length = _f32(np.linalg.norm(moving_vector))
    moving_direction = (
        np.asarray(moving_vector / moving_length, dtype=np.float32)
        if moving_length > _f32(1.0e-6)
        else np.zeros(3, dtype=np.float32)
    )
    moving_speed = moving_length / frame_dt
    moving_speed *= (
        _f32(1.0) / time_scale
        if time_scale > _f32(1.0e-6)
        else _f32(0.0)
    )
    return MC2CenterFrameShiftResult(
        frame_component_shift_vector=tuple(float(value) for value in shift_vector),
        frame_component_shift_rotation_xyzw=tuple(float(value) for value in shift_rotation),
        old_frame_world_position=tuple(float(value) for value in shifted_old_frame),
        old_frame_world_rotation_xyzw=tuple(float(value) for value in shifted_old_rotation),
        now_world_position=tuple(float(value) for value in shifted_now),
        now_world_rotation_xyzw=tuple(float(value) for value in shifted_now_rotation),
        frame_world_position=tuple(float(value) for value in frame_world_position),
        frame_world_rotation_xyzw=tuple(float(value) for value in frame_world_rotation),
        frame_moving_direction=tuple(float(value) for value in moving_direction),
        frame_moving_speed=float(moving_speed),
        smoothing_velocity=tuple(float(value) for value in smoothing_velocity),
        keep_teleport=keep_teleport,
        reset_teleport=reset_teleport,
    )


def evaluate_mc2_center_step(
    step: MC2CenterStepInputSpec,
    runtime_parameters,
    *,
    initial_local_gravity_direction,
) -> MC2CenterStepResult:
    from .runtime_parameters import MC2_RUNTIME_FLOAT_FIELDS, MC2RuntimeParametersV0

    if not isinstance(step, MC2CenterStepInputSpec):
        raise TypeError("step must be MC2CenterStepInputSpec")
    if not isinstance(runtime_parameters, MC2RuntimeParametersV0):
        raise TypeError("runtime_parameters must be MC2RuntimeParametersV0")
    parameter = dict(zip(MC2_RUNTIME_FLOAT_FIELDS, runtime_parameters.float_values))
    dt = _f32(step.simulation_delta_time)
    ratio = _f32(step.frame_interpolation)
    old_position = _f32_vector(step.old_frame_world_position, 3, "old_frame_world_position")
    frame_position = _f32_vector(step.frame_world_position, 3, "frame_world_position")
    now_position = old_position + (frame_position - old_position) * ratio
    old_rotation = _f32_vector(step.old_frame_world_rotation_xyzw, 4, "old_frame_world_rotation_xyzw")
    frame_rotation = _f32_vector(step.frame_world_rotation_xyzw, 4, "frame_world_rotation_xyzw")
    now_rotation = _quaternion_slerp_f32(old_rotation, frame_rotation, ratio)
    previous_position = _f32_vector(step.old_world_position, 3, "old_world_position")
    previous_rotation = _f32_vector(step.old_world_rotation_xyzw, 4, "old_world_rotation_xyzw")
    step_vector = np.asarray(now_position - previous_position, dtype=np.float32)
    inverse_previous = np.asarray(
        (-previous_rotation[0], -previous_rotation[1], -previous_rotation[2], previous_rotation[3]),
        dtype=np.float32,
    )
    step_rotation = _normalize_quaternion_f32(
        quaternion_multiply_f32(now_rotation, inverse_previous)
    )
    cosine = np.clip(abs(_f32(np.dot(previous_rotation, now_rotation))), 0.0, 1.0)
    step_angle = _f32(2.0) * _f32(np.arccos(cosine))

    move_inertia = _f32(1.0) - _f32(parameter["local_inertia"])
    local_vector = step_vector * (_f32(1.0) - move_inertia)
    local_speed = _f32(np.linalg.norm(local_vector)) / dt
    movement_limit = _f32(parameter["local_movement_speed_limit"])
    if local_speed > movement_limit and movement_limit >= 0.0:
        limit_ratio = movement_limit / local_speed
        move_inertia = _f32(1.0) + (move_inertia - _f32(1.0)) * limit_ratio

    rotation_inertia = _f32(1.0) - _f32(parameter["local_inertia"])
    local_angle_speed = _f32(np.degrees(step_angle * (_f32(1.0) - rotation_inertia) / dt))
    rotation_limit = _f32(parameter["local_rotation_speed_limit"])
    if local_angle_speed > rotation_limit and rotation_limit >= 0.0:
        limit_ratio = rotation_limit / local_angle_speed
        rotation_inertia = _f32(1.0) + (rotation_inertia - _f32(1.0)) * limit_ratio

    inertia_vector = np.asarray(step_vector * move_inertia, dtype=np.float32)
    identity = np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
    inertia_rotation = _quaternion_slerp_f32(identity, step_rotation, rotation_inertia)
    angular_velocity = step_angle / dt
    if angular_velocity > _f32(1.0e-8):
        axis_length = _f32(np.linalg.norm(step_rotation[:3]))
        rotation_axis = (
            np.asarray(step_rotation[:3] / axis_length, dtype=np.float32)
            if axis_length > _f32(1.0e-8)
            else np.zeros(3, dtype=np.float32)
        )
    else:
        rotation_axis = np.zeros(3, dtype=np.float32)

    old_scale = _f32_vector(step.old_frame_world_scale, 3, "old_frame_world_scale")
    frame_scale = _f32_vector(step.frame_world_scale, 3, "frame_world_scale")
    world_scale = old_scale + (frame_scale - old_scale) * ratio
    initial_scale = _f32_vector(step.initial_scale, 3, "initial_scale")
    scale_ratio = max(
        _f32(np.linalg.norm(world_scale)) / _f32(np.linalg.norm(initial_scale)),
        _f32(1.0e-6),
    )

    initial_gravity = _f32_vector(
        initial_local_gravity_direction, 3, "initial_local_gravity_direction"
    )
    initial_gravity[1] *= _f32(step.negative_scale_direction[1])
    world_falloff = rotate_vector_unit_quaternion_f32(now_rotation, initial_gravity)
    world_gravity = np.asarray(
        (parameter["gravity_direction_x"], parameter["gravity_direction_y"], parameter["gravity_direction_z"]),
        dtype=np.float32,
    )
    gravity_dot = _f32(1.0)
    if _f32(np.dot(world_gravity, world_gravity)) > _f32(1.0e-8):
        gravity_dot = np.clip(
            _f32(np.dot(world_falloff, world_gravity)) * _f32(0.5) + _f32(0.5),
            _f32(0.0),
            _f32(1.0),
        )
    gravity_ratio = _f32(1.0)
    gravity = _f32(parameter["gravity"])
    gravity_falloff = _f32(parameter["gravity_falloff"])
    if gravity > _f32(1.0e-6) and gravity_falloff > _f32(1.0e-6):
        minimum = np.clip(_f32(1.0) - gravity_falloff, _f32(0.0), _f32(1.0))
        falloff = np.clip(_f32(1.0) - gravity_dot, _f32(0.0), _f32(1.0))
        gravity_ratio = minimum + (_f32(1.0) - minimum) * falloff

    velocity_weight = _f32(step.velocity_weight)
    if velocity_weight < _f32(1.0):
        stabilization = _f32(parameter["stabilization_time_after_reset"])
        added = dt / stabilization if stabilization > _f32(1.0e-6) else _f32(1.0)
        velocity_weight = np.clip(velocity_weight + added, _f32(0.0), _f32(1.0))
    blend_weight = np.clip(
        velocity_weight * _f32(parameter["blend_weight"]) * _f32(step.distance_weight),
        _f32(0.0),
        _f32(1.0),
    )

    vector = lambda value: tuple(float(item) for item in value)
    return MC2CenterStepResult(
        frame_interpolation=float(ratio),
        now_world_position=vector(now_position),
        now_world_rotation_xyzw=vector(now_rotation),
        step_vector=vector(step_vector),
        step_rotation_xyzw=vector(step_rotation),
        step_move_inertia_ratio=float(move_inertia),
        step_rotation_inertia_ratio=float(rotation_inertia),
        inertia_vector=vector(inertia_vector),
        inertia_rotation_xyzw=vector(inertia_rotation),
        angular_velocity=float(angular_velocity),
        rotation_axis=vector(rotation_axis),
        scale_ratio=float(scale_ratio),
        gravity_dot=float(gravity_dot),
        gravity_ratio=float(gravity_ratio),
        velocity_weight=float(velocity_weight),
        blend_weight=float(blend_weight),
    )


__all__ = [
    "MC2CenterStaticMetadata",
    "MC2CenterFramePoseSpec",
    "MC2CenterFrameShiftInputSpec",
    "MC2CenterFrameShiftResult",
    "MC2CenterPersistentState",
    "MC2CenterStepInputSpec",
    "MC2CenterStepResult",
    "MC2CenterStaticSpec",
    "MC2CenterWorldPoseSpec",
    "build_mc2_center_static",
    "derive_mc2_center_world_pose",
    "evaluate_mc2_center_frame_shift",
    "evaluate_mc2_center_step",
    "pack_mc2_center_static",
]
