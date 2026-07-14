"""Source-aligned Center static, frame-pose, and persistent reset contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .mesh_baseline import MC2_VERTEX_MOVE
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


def _quaternion_multiply(left, right):
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return (
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    )


def _quaternion_inverse(value):
    x, y, z, w = value
    return (-x, -y, -z, w)


def _rotate(value, vector):
    q = _unit_quaternion(value, "quaternion")
    vx, vy, vz = vector
    rotated = _quaternion_multiply(
        _quaternion_multiply(q, (vx, vy, vz, 0.0)),
        _quaternion_inverse(q),
    )
    return rotated[:3]


def _signature(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class MC2CenterStaticSpec:
    task_id: str
    proxy_signature: str
    fixed_indices: tuple[int, ...]
    local_center_position: tuple[float, float, float]
    initial_local_gravity_direction: tuple[float, float, float]
    center_static_signature: str
    schema_version: int = 0

    def debug_dict(self) -> dict:
        return {
            "fixed_indices": self.fixed_indices,
            "local_center_position": self.local_center_position,
            "initial_local_gravity_direction": self.initial_local_gravity_direction,
            "center_static_signature": self.center_static_signature,
        }


def build_mc2_center_static(
    proxy: MC2ProxyStaticSpec,
    *,
    vertex_bind_pose_rotations,
    world_gravity_direction,
) -> MC2CenterStaticSpec:
    if not isinstance(proxy, MC2ProxyStaticSpec):
        raise TypeError("proxy must be MC2ProxyStaticSpec")
    bind_rotations = tuple(
        _unit_quaternion(value, f"vertex_bind_pose_rotations[{index}]")
        for index, value in enumerate(vertex_bind_pose_rotations)
    )
    if len(bind_rotations) != proxy.vertex_count:
        raise ValueError("vertex bind rotation count mismatch")

    neighbors = [set() for _ in range(proxy.vertex_count)]
    for first, second in proxy.edges:
        neighbors[first].add(second)
        neighbors[second].add(first)
    fixed = []
    for index, attribute in enumerate(proxy.vertex_attributes):
        if attribute & MC2_VERTEX_MOVE:
            continue
        adjacent = neighbors[index]
        if adjacent and all(not (proxy.vertex_attributes[item] & MC2_VERTEX_MOVE) for item in adjacent):
            continue
        fixed.append(index)

    if fixed:
        center = tuple(
            sum(proxy.local_positions[index][axis] for index in fixed) / len(fixed)
            for axis in range(3)
        )
        normal_sum = np.zeros(3, dtype=np.float64)
        tangent_sum = np.zeros(3, dtype=np.float64)
        for index in fixed:
            local_rotation = mc2_world_rotation_xyzw(
                proxy.local_normals[index], proxy.local_tangents[index]
            )
            corrected = _unit_quaternion(
                _quaternion_multiply(local_rotation, bind_rotations[index]),
                "corrected center rotation",
            )
            normal_sum += _rotate(corrected, (0.0, 1.0, 0.0))
            tangent_sum += _rotate(corrected, (0.0, 0.0, 1.0))
        center_rotation = mc2_world_rotation_xyzw(
            _normalize3(normal_sum, "center normal"),
            _normalize3(tangent_sum, "center tangent"),
        )
        gravity = _rotate(
            _quaternion_inverse(center_rotation),
            _normalize3(world_gravity_direction, "world_gravity_direction"),
        )
    else:
        center = (0.0, 0.0, 0.0)
        gravity = (0.0, -1.0, 0.0)

    payload = {
        "schema_version": 0,
        "task_id": proxy.task_id,
        "proxy_signature": proxy.proxy_signature,
        "fixed_indices": fixed,
        "local_center_position": center,
        "initial_local_gravity_direction": gravity,
    }
    return MC2CenterStaticSpec(
        task_id=proxy.task_id,
        proxy_signature=proxy.proxy_signature,
        fixed_indices=tuple(fixed),
        local_center_position=tuple(float(value) for value in center),
        initial_local_gravity_direction=tuple(float(value) for value in gravity),
        center_static_signature=_signature(payload),
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
    bind_rotations = tuple(
        _require_unit_quaternion(value, f"vertex_bind_pose_rotations[{index}]")
        for index, value in enumerate(vertex_bind_pose_rotations)
    )
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("world_positions must have shape [N,3]")
    if rotations.shape != (len(positions), 4):
        raise ValueError("world_rotations_xyzw must have shape [N,4]")
    if len(bind_rotations) != len(positions):
        raise ValueError("Center bind rotation count mismatch")
    if not np.isfinite(positions).all() or not np.isfinite(rotations).all():
        raise ValueError("Center frame arrays cannot contain NaN/Inf")
    for index, rotation in enumerate(rotations):
        _require_unit_quaternion(rotation, f"world_rotations_xyzw[{index}]")

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
            _quaternion_multiply(rotation, bind_rotations[index]),
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
        self.anchor_identity = frame_pose.anchor_identity
        self.old_component_world_position = tuple(frame_pose.component_world_position)
        self.old_component_world_rotation_xyzw = _unit_quaternion(
            frame_pose.component_world_rotation_xyzw, "component_world_rotation_xyzw"
        )
        self.old_component_world_scale = tuple(frame_pose.component_world_scale)
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
        self.reset_count += 1
        self.initialized = True

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
        simulation_delta_time: float,
        frame_delta_time: float,
        world_inertia: float,
        movement_speed_limit: float = -1.0,
        rotation_speed_limit: float = -1.0,
        now_time_scale: float = 1.0,
        skip_count: int = 0,
    ) -> MC2CenterFrameShiftInputSpec:
        if not self.initialized:
            raise RuntimeError("Center persistent state must be reset before frame shift")
        if not isinstance(frame_pose, MC2CenterFramePoseSpec):
            raise TypeError("frame_pose must be MC2CenterFramePoseSpec")
        if frame_pose.component_identity != self.component_identity:
            raise ValueError("Center component identity changed without reset")
        return MC2CenterFrameShiftInputSpec(
            simulation_delta_time=float(simulation_delta_time),
            frame_delta_time=float(frame_delta_time),
            now_time_scale=float(now_time_scale),
            velocity_weight=float(self.velocity_weight),
            skip_count=skip_count,
            world_inertia=float(world_inertia),
            movement_speed_limit=float(movement_speed_limit),
            rotation_speed_limit=float(rotation_speed_limit),
            old_component_world_position=self.old_component_world_position,
            old_component_world_rotation_xyzw=self.old_component_world_rotation_xyzw,
            component_world_position=frame_pose.component_world_position,
            component_world_rotation_xyzw=frame_pose.component_world_rotation_xyzw,
            old_frame_world_position=self.old_frame_world_position,
            old_frame_world_rotation_xyzw=self.old_frame_world_rotation_xyzw,
            now_world_position=self.old_world_position,
            now_world_rotation_xyzw=self.old_world_rotation_xyzw,
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
        self.anchor_identity = frame_pose.anchor_identity
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
            "initialized": self.initialized,
            "reset_count": self.reset_count,
            "last_frame": self.last_frame,
            "last_generation": self.last_generation,
            "velocity_weight": self.velocity_weight,
            "old_frame_world_position": self.old_frame_world_position,
            "old_world_position": self.old_world_position,
        }


@dataclass(frozen=True)
class MC2CenterFrameShiftInputSpec:
    """Source-aligned world-inertia inputs before Center substep derivation.

    V0 deliberately covers no fixed list and unit positive scale, and excludes
    anchor, smoothing, teleport, synchronization, culling, and stabilization.
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

    def __post_init__(self) -> None:
        for name in ("simulation_delta_time", "frame_delta_time", "now_time_scale"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not 0.0 <= float(self.velocity_weight) <= 1.0:
            raise ValueError("velocity_weight must be in 0..1")
        if isinstance(self.skip_count, bool) or int(self.skip_count) != self.skip_count:
            raise ValueError("skip_count must be an integer")
        if self.skip_count < 0:
            raise ValueError("skip_count cannot be negative")
        if not 0.0 <= float(self.world_inertia) <= 1.0:
            raise ValueError("world_inertia must be in 0..1")
        for name in ("movement_speed_limit", "rotation_speed_limit"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        for name in (
            "old_component_world_position",
            "component_world_position",
            "old_frame_world_position",
            "now_world_position",
        ):
            _vector(getattr(self, name), 3, name)
        for name in (
            "old_component_world_rotation_xyzw",
            "component_world_rotation_xyzw",
            "old_frame_world_rotation_xyzw",
            "now_world_rotation_xyzw",
        ):
            _require_unit_quaternion(getattr(self, name), name)


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
    length = _f32(np.linalg.norm(value))
    if length <= _f32(1.0e-8):
        raise ValueError("Center quaternion cannot be zero")
    return np.asarray(value / length, dtype=np.float32)


def _quaternion_slerp_f32(first: np.ndarray, second: np.ndarray, ratio) -> np.ndarray:
    ratio = _f32(ratio)
    target = second.copy()
    cosine = _f32(np.dot(first, target))
    if cosine < 0.0:
        target = -target
        cosine = -cosine
    if cosine > _f32(0.9995):
        return _normalize_quaternion_f32(first + (target - first) * ratio)
    angle = _f32(np.arccos(np.clip(cosine, -1.0, 1.0)))
    sine = _f32(np.sin(angle))
    first_weight = _f32(np.sin((_f32(1.0) - ratio) * angle) / sine)
    second_weight = _f32(np.sin(ratio * angle) / sine)
    return _normalize_quaternion_f32(first * first_weight + target * second_weight)


def _quaternion_multiply_f32(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = left
    rx, ry, rz, rw = right
    return np.asarray((
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    ), dtype=np.float32)


def _rotate_f32(rotation: np.ndarray, vector: np.ndarray) -> np.ndarray:
    xyz = rotation[:3]
    twice_cross = _f32(2.0) * np.cross(xyz, vector)
    return np.asarray(
        vector + rotation[3] * twice_cross + np.cross(xyz, twice_cross),
        dtype=np.float32,
    )


def _inverse_quaternion_f32(rotation: np.ndarray) -> np.ndarray:
    return np.asarray(
        (-rotation[0], -rotation[1], -rotation[2], rotation[3]),
        dtype=np.float32,
    )


def _shift_position_f32(position, pivot, shift_vector, shift_rotation) -> np.ndarray:
    return np.asarray(
        pivot + _rotate_f32(shift_rotation, position - pivot) + shift_vector,
        dtype=np.float32,
    )


def evaluate_mc2_center_frame_shift(
    frame: MC2CenterFrameShiftInputSpec,
) -> MC2CenterFrameShiftResult:
    """Evaluate the verified no-fixed-list, unit-positive-scale shift domain."""
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
    full_shift_vector = np.asarray(component - old_component, dtype=np.float32)
    full_shift_rotation = _normalize_quaternion_f32(
        _quaternion_multiply_f32(
            component_rotation,
            _inverse_quaternion_f32(old_component_rotation),
        )
    )
    move_shift_ratio = _f32(1.0) - _f32(frame.world_inertia)
    rotation_shift_ratio = move_shift_ratio
    work_old_component = np.asarray(
        old_component + full_shift_vector * move_shift_ratio,
        dtype=np.float32,
    )
    work_old_rotation = _quaternion_slerp_f32(
        old_component_rotation,
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
        skip_ratio = np.clip(
            (_f32(frame.skip_count) * simulation_dt) / (frame_dt * time_scale),
            _f32(0.0),
            _f32(1.0),
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

    shift_vector = np.asarray(full_shift_vector * move_shift_ratio, dtype=np.float32)
    identity = np.asarray(IDENTITY_QUATERNION, dtype=np.float32)
    shift_rotation = _quaternion_slerp_f32(
        identity,
        full_shift_rotation,
        rotation_shift_ratio,
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
        _quaternion_multiply_f32(shift_rotation, old_frame_rotation)
    )
    shifted_now_rotation = _normalize_quaternion_f32(
        _quaternion_multiply_f32(shift_rotation, now_rotation)
    )
    moving_vector = np.asarray(component - work_old_component, dtype=np.float32)
    moving_length = _f32(np.linalg.norm(moving_vector))
    moving_direction = (
        np.asarray(moving_vector / moving_length, dtype=np.float32)
        if moving_length > _f32(1.0e-6)
        else np.zeros(3, dtype=np.float32)
    )
    moving_speed = moving_length / frame_dt
    moving_speed *= _f32(1.0) / time_scale
    return MC2CenterFrameShiftResult(
        frame_component_shift_vector=tuple(float(value) for value in shift_vector),
        frame_component_shift_rotation_xyzw=tuple(float(value) for value in shift_rotation),
        old_frame_world_position=tuple(float(value) for value in shifted_old_frame),
        old_frame_world_rotation_xyzw=tuple(float(value) for value in shifted_old_rotation),
        now_world_position=tuple(float(value) for value in shifted_now),
        now_world_rotation_xyzw=tuple(float(value) for value in shifted_now_rotation),
        frame_world_position=tuple(float(value) for value in component),
        frame_world_rotation_xyzw=tuple(float(value) for value in component_rotation),
        frame_moving_direction=tuple(float(value) for value in moving_direction),
        frame_moving_speed=float(moving_speed),
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
        _quaternion_multiply_f32(now_rotation, inverse_previous)
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
    world_falloff = _rotate_f32(now_rotation, initial_gravity)
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
