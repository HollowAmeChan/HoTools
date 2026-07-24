"""编译后 MC2 domain 的 E3 CPU backend 生命周期边界。

本模块只拥有 backend-domain 状态。native/C++ kernel 通过
``MC2CPUKernelV1`` 注入；adapter 不导入 Blender 或已删除的旧 slot owner，
因此无需分配 native 资源也可以测试。
"""

from __future__ import annotations

from typing import Mapping, Protocol

import numpy as np

from .domain_capabilities import MC2BackendCapabilitiesV1
from .domain_capabilities import evaluate_mc2_backend_capabilities
from .domain_compile import MC2CompiledDomainV1
from .domain_ir import MC2DomainFrameOutputV1
from .domain_ir import MC2DomainFramePacketV1
from .domain_ir import MC2PhysicalIndexMapV1
from .domain_ir import make_mc2_domain_frame_output
from .domain_ir import make_mc2_physical_index_map


MC2_CPU_REFERENCE_CAPABILITIES = MC2BackendCapabilitiesV1(
    backend_id="mc2_cpu_domain_v1",
    schema_versions=(1,),
    setup_types=("bone_cloth", "bone_spring", "mesh_cloth"),
    capabilities=("bone_cloth", "bone_spring", "mesh_cloth", "self_collision"),
    max_particles=0xFFFFFFFF,
    index_width_bits=32,
    supports_physical_reorder=True,
)


class MC2CPUKernelV1(Protocol):
    """The narrow native kernel ABI consumed by this adapter."""

    def create_domain(self, program, parameters): ...

    def stage_parameter_update(self, handle, program, parameters): ...

    def apply_parameter_update(self, handle, update) -> None: ...

    def rollback_parameter_update(self, handle, update) -> None: ...

    def finish_parameter_update(self, handle, update) -> None: ...

    def discard_parameter_update(self, update) -> None: ...

    def update_frame(self, handle, frame_packet): ...

    def step(self, handle, frame_packet, scheduler_settings, collider_snapshot): ...

    def read_output(self, handle) -> MC2DomainFrameOutputV1: ...

    def inspect(self, handle) -> Mapping[str, object]: ...

    def dispose(self, handle) -> None: ...


class MC2CPUBackendDomainV1:
    """A slot-independent CPU domain handle with atomic lifecycle updates."""

    def __init__(
        self,
        compiled: MC2CompiledDomainV1,
        kernel: MC2CPUKernelV1,
        handle,
        physical_index_map: MC2PhysicalIndexMapV1,
        backend_id: str,
    ) -> None:
        self._compiled = compiled
        self._kernel = kernel
        self._handle = handle
        self._physical_index_map = physical_index_map
        self._backend_id = str(backend_id)
        self._latest_frame: MC2DomainFramePacketV1 | None = None
        self._last_output: MC2DomainFrameOutputV1 | None = None
        self._step_count = 0
        self._partition_history = {
            partition_id: {"last_frame": None, "generation": None}
            for partition_id in compiled.program.partition_ids
        }

    @property
    def disposed(self) -> bool:
        return self._handle is None

    @property
    def compiled(self) -> MC2CompiledDomainV1:
        return self._compiled

    @property
    def physical_index_map(self) -> MC2PhysicalIndexMapV1:
        return self._physical_index_map

    @property
    def latest_frame(self) -> MC2DomainFramePacketV1 | None:
        return self._latest_frame

    @property
    def last_output(self) -> MC2DomainFrameOutputV1 | None:
        return self._last_output

    @classmethod
    def create(
        cls,
        compiled: MC2CompiledDomainV1,
        kernel: MC2CPUKernelV1,
        *,
        capabilities: MC2BackendCapabilitiesV1 = MC2_CPU_REFERENCE_CAPABILITIES,
    ) -> "MC2CPUBackendDomainV1":
        if not isinstance(compiled, MC2CompiledDomainV1):
            raise TypeError("compiled must be MC2CompiledDomainV1")
        report = evaluate_mc2_backend_capabilities(compiled.program, capabilities)
        if not report.compatible:
            raise RuntimeError(
                "MC2 CPU backend capability gate rejected domain: "
                + ", ".join(report.blockers)
            )
        required_methods = (
            "create_domain", "update_frame", "step", "read_output", "inspect", "dispose"
        )
        if any(not callable(getattr(kernel, name, None)) for name in required_methods):
            raise TypeError("kernel does not implement MC2CPUKernelV1")
        handle = None
        try:
            handle = kernel.create_domain(compiled.program, compiled.parameters)
            if handle is None:
                raise RuntimeError("CPU kernel returned an empty domain handle")
            identity = np.arange(compiled.program.particle_count, dtype=np.uint32)
            physical_index_map = make_mc2_physical_index_map(identity)
            return cls(
                compiled,
                kernel,
                handle,
                physical_index_map,
                capabilities.backend_id,
            )
        except Exception:
            if handle is not None:
                try:
                    kernel.dispose(handle)
                except Exception:
                    pass
            raise

    def update_frame(self, frame_packet: MC2DomainFramePacketV1) -> None:
        self._ensure_live()
        if not isinstance(frame_packet, MC2DomainFramePacketV1):
            raise TypeError("frame_packet must be MC2DomainFramePacketV1")
        self._validate_identity(frame_packet.domain_signature, frame_packet.layout_signature)
        self._kernel.update_frame(self._handle, frame_packet)
        self._latest_frame = frame_packet
        for partition_id in self._partition_history:
            self._partition_history[partition_id] = {
                "last_frame": int(frame_packet.frame),
                "generation": int(frame_packet.generation),
            }

    def update_parameters(self, compiled: MC2CompiledDomainV1, commit_host=None) -> None:
        """Atomically replace same-layout parameters without replacing domain history."""

        self._ensure_live()
        if not isinstance(compiled, MC2CompiledDomainV1):
            raise TypeError("compiled must be MC2CompiledDomainV1")
        if (
            compiled.program.domain_signature
            != self._compiled.program.domain_signature
            or compiled.program.layout_signature
            != self._compiled.program.layout_signature
            or compiled.parameters.parameter_layout_signature
            != self._compiled.parameters.parameter_layout_signature
        ):
            raise ValueError("parameter update must preserve compiled domain layout")
        if commit_host is None:
            commit_host = lambda: None
        if not callable(commit_host):
            raise TypeError("commit_host must be callable")
        methods = {
            name: getattr(self._kernel, name, None)
            for name in (
                "stage_parameter_update",
                "apply_parameter_update",
                "rollback_parameter_update",
                "finish_parameter_update",
                "discard_parameter_update",
            )
        }
        if any(not callable(method) for method in methods.values()):
            raise RuntimeError("CPU kernel does not expose atomic parameter update")

        update = methods["stage_parameter_update"](
            self._handle, compiled.program, compiled.parameters
        )
        try:
            methods["apply_parameter_update"](self._handle, update)
        except Exception:
            methods["discard_parameter_update"](update)
            raise
        try:
            commit_host()
        except Exception:
            try:
                methods["rollback_parameter_update"](self._handle, update)
            finally:
                methods["discard_parameter_update"](update)
            raise
        methods["finish_parameter_update"](self._handle, update)
        self._compiled = compiled

    def step(
        self,
        scheduler_settings: Mapping[str, object],
        collider_snapshot=None,
    ) -> None:
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend step requires update_frame first")
        if not isinstance(scheduler_settings, Mapping):
            raise TypeError("scheduler_settings must be a mapping")
        self._kernel.step(
            self._handle,
            self._latest_frame,
            dict(scheduler_settings),
            collider_snapshot,
        )
        self._step_count += 1

    def step_center_frame_shift(self, anchor_component_local_positions) -> None:
        """Run only the explicit native Center frame-shift data path."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("Center frame shift requires update_frame first")
        step_frame_shift = getattr(self._kernel, "step_center_frame_shift", None)
        if not callable(step_frame_shift):
            raise RuntimeError("CPU kernel does not expose the Center frame-shift pass")
        step_frame_shift(self._handle, anchor_component_local_positions)

    def step_task_reference_teleport(self) -> None:
        """Run the task-local discontinuity pass before Center frame shift."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("task-reference teleport requires update_frame first")
        step_teleport = getattr(self._kernel, "step_task_reference_teleport", None)
        if not callable(step_teleport):
            raise RuntimeError("CPU kernel does not expose task-reference teleport")
        step_teleport(self._handle)

    def step_center(self, settings: Mapping[str, object]) -> None:
        """Evaluate one explicit native Center substep."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("Center step requires update_frame first")
        step_center = getattr(self._kernel, "step_center", None)
        if not callable(step_center):
            raise RuntimeError("CPU kernel does not expose the Center pass")
        step_center(self._handle, settings)

    def step_center_inertia(self) -> None:
        """Consume the latest Center result on the unified particle state."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("Center inertia requires update_frame first")
        step_inertia = getattr(self._kernel, "step_center_inertia", None)
        if not callable(step_inertia):
            raise RuntimeError("CPU kernel does not expose Center inertia")
        step_inertia(self._handle)

    def step_distance(
        self, simulation_power: float = 1.0, debug_phase: int = -1
    ) -> None:
        """Run one explicit native Distance pass with scheduler-owned power."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("Distance step requires update_frame first")
        step_distance = getattr(self._kernel, "step_distance", None)
        if not callable(step_distance):
            raise RuntimeError("CPU kernel does not expose the Distance pass")
        step_distance(self._handle, simulation_power, debug_phase)
        self._step_count += 1

    def step_tether(self, settings: Mapping[str, object]) -> None:
        """Run one explicit native Tether pass."""
        self._run_explicit_pass("step_tether", settings, "Tether")

    def step_bending(self, simulation_power: float = 1.0) -> None:
        """Run one explicit native Bending pass."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("Bending step requires update_frame first")
        step_bending = getattr(self._kernel, "step_bending", None)
        if not callable(step_bending):
            raise RuntimeError("CPU kernel does not expose the Bending pass")
        step_bending(self._handle, simulation_power)
        self._step_count += 1

    def step_angle(self, settings: Mapping[str, object]) -> None:
        """Run one explicit native Angle pass."""
        self._run_explicit_pass("step_angle", settings, "Angle")

    def step_motion(self, settings: Mapping[str, object]) -> None:
        """Run one explicit native Motion pass."""
        self._run_explicit_pass("step_motion", settings, "Motion")

    def step_inertia(self, settings: Mapping[str, object]) -> None:
        """Run one explicit native Inertia pass."""
        self._run_explicit_pass("step_inertia", settings, "Inertia")

    def step_integration(self, settings: Mapping[str, object]) -> None:
        """Run one explicit native Integration pass."""
        self._run_explicit_pass("step_integration", settings, "Integration")

    def _run_explicit_pass(
        self,
        method_name: str,
        settings: Mapping[str, object],
        display_name: str,
    ) -> None:
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError(f"{display_name} step requires update_frame first")
        if not isinstance(settings, Mapping):
            raise TypeError(f"{display_name} settings must be a mapping")
        method = getattr(self._kernel, method_name, None)
        if not callable(method):
            raise RuntimeError(f"CPU kernel does not expose the {display_name} pass")
        method(self._handle, dict(settings))
        self._step_count += 1

    def step_reference_pass_prefix(self, settings: Mapping[str, object]) -> None:
        """Run only the explicit landed native reference pass prefix."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("reference pass prefix requires update_frame first")
        run_reference = getattr(self._kernel, "step_reference_pass_prefix", None)
        if not callable(run_reference):
            raise RuntimeError("CPU kernel does not expose the reference pass prefix")
        run_reference(self._handle, settings)
        self._step_count += 1

    def step_reference_pipeline(self, settings: Mapping[str, object]) -> None:
        """Run the explicit native structural reference order through Motion."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("reference pipeline requires update_frame first")
        run_reference = getattr(self._kernel, "step_reference_pipeline", None)
        if not callable(run_reference):
            raise RuntimeError("CPU kernel does not expose reference pipeline")
        run_reference(self._handle, settings)
        self._step_count += 1

    def step_reference_pipeline_full(self, settings: Mapping[str, object]) -> None:
        """按当前完整顺序执行显式结构、碰撞与后处理 pass。"""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("full reference pipeline requires update_frame first")
        run_reference = getattr(self._kernel, "step_reference_pipeline_full", None)
        if not callable(run_reference):
            raise RuntimeError("CPU kernel does not expose full reference pipeline")
        run_reference(self._handle, settings)
        self._step_count += 1

    def step_compiled_domain_pipeline_full(self, settings: Mapping[str, object]) -> None:
        """Run the E4 compiled structural/external/self/post order in one owner."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("compiled domain pipeline requires update_frame first")
        run_pipeline = getattr(self._kernel, "step_compiled_domain_pipeline_full", None)
        if not callable(run_pipeline):
            raise RuntimeError("CPU kernel does not expose compiled domain pipeline")
        run_pipeline(self._handle, settings)
        self._step_count += 1

    def prepare_step_basic_pose(self, animation_pose_ratio: float | None = None) -> dict:
        """Build StepBasic from compiled ratio unless an explicit test override is supplied."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("StepBasic pose requires update_frame first")
        prepare_pose = getattr(self._kernel, "prepare_step_basic_pose", None)
        if not callable(prepare_pose):
            raise RuntimeError("CPU kernel does not expose StepBasic pose preparation")
        if animation_pose_ratio is None:
            fields = self._compiled.parameters.partition_parameters.fields
            if "animation_pose_ratio" not in fields:
                raise ValueError("compiled parameters lack animation_pose_ratio")
            compiled_ratios = np.asarray(
                self._compiled.parameters.partition_parameters.values[
                    :, fields.index("animation_pose_ratio")
                ],
                dtype=np.float32,
            )
            animation_pose_ratio = (
                float(compiled_ratios[0])
                if len(compiled_ratios) == 1
                else compiled_ratios
            )
        return prepare_pose(self._handle, animation_pose_ratio)

    def step_external_collision(self, settings: Mapping[str, object]) -> None:
        """Run the explicit native point external-collision pass."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("external collision requires update_frame first")
        run_collision = getattr(self._kernel, "step_external_collision", None)
        if not callable(run_collision):
            raise RuntimeError("CPU kernel does not expose external collision")
        run_collision(self._handle, settings)
        self._step_count += 1

    def step_self_collision(self, settings: Mapping[str, object]) -> None:
        """Run the explicit native self-collision pass."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("self collision requires update_frame first")
        run_collision = getattr(self._kernel, "step_self_collision", None)
        if not callable(run_collision):
            raise RuntimeError("CPU kernel does not expose self collision")
        run_collision(self._handle, settings)
        self._step_count += 1

    def step_whole_domain_self(self, old_positions) -> None:
        """Run the E4 self pass over every compiled partition in one native call."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("whole-domain self collision requires update_frame first")
        run_collision = getattr(self._kernel, "step_whole_domain_self", None)
        if not callable(run_collision):
            raise RuntimeError("CPU kernel does not expose whole-domain self collision")
        run_collision(self._handle, old_positions)
        self._step_count += 1

    def step_compiled_external_collision(self, settings: Mapping[str, object]) -> None:
        """Run the E4 external pass once over the compiled particle domain."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("compiled external collision requires update_frame first")
        run_collision = getattr(self._kernel, "step_compiled_external_collision", None)
        if not callable(run_collision):
            raise RuntimeError("CPU kernel does not expose compiled external collision")
        run_collision(self._handle, settings)
        self._step_count += 1

    def step_external_edge_collision(self, settings: Mapping[str, object]) -> None:
        """Run the explicit native edge external-collision pass."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("external edge collision requires update_frame first")
        run_collision = getattr(self._kernel, "step_external_edge_collision", None)
        if not callable(run_collision):
            raise RuntimeError("CPU kernel does not expose external edge collision")
        run_collision(self._handle, settings)
        self._step_count += 1

    def step_post(self, settings: Mapping[str, object]) -> None:
        """执行显式 native 后处理速度与历史阶段。"""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("post step requires update_frame first")
        run_post = getattr(self._kernel, "step_post", None)
        if not callable(run_post):
            raise RuntimeError("CPU kernel does not expose post step")
        run_post(self._handle, settings)
        self._step_count += 1

    def read_output(self) -> MC2DomainFrameOutputV1:
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend read_output requires update_frame first")
        output = self._kernel.read_output(self._handle)
        if not isinstance(output, MC2DomainFrameOutputV1):
            raise TypeError("CPU kernel returned an invalid MC2DomainFrameOutputV1")
        self._validate_identity(output.domain_signature, output.layout_signature)
        if (output.frame, output.generation) != (
            self._latest_frame.frame, self._latest_frame.generation
        ):
            raise RuntimeError("CPU backend output frame identity does not match input")
        if output.index_order == "logical":
            normalized = output
        else:
            physical_to_logical = np.asarray(output.physical_to_logical, dtype=np.uint32)
            logical_to_physical = np.empty_like(physical_to_logical)
            logical_to_physical[physical_to_logical] = np.arange(
                len(physical_to_logical), dtype=np.uint32
            )
            positions = output.world_positions[logical_to_physical]
            rotations = output.world_rotations_xyzw
            if len(rotations):
                rotations = rotations[logical_to_physical]
            normalized = make_mc2_domain_frame_output(
                self._compiled.program,
                self._latest_frame,
                world_positions=positions,
                world_rotations_xyzw=rotations if len(rotations) else None,
                validity_flags=output.validity_flags,
                backend_revision=output.backend_revision,
                backend_kind=output.backend_kind,
                timing_token=output.timing_token,
            )
        self._last_output = normalized
        return normalized

    def read_debug_state(self) -> Mapping[str, object]:
        """Read native dynamics only when a caller explicitly requests it."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend debug state requires update_frame first")
        read_state = getattr(self._kernel, "read_debug_state", None)
        if not callable(read_state):
            raise RuntimeError("CPU kernel does not expose explicit debug state")
        return read_state(self._handle)

    def begin_constraint_debug(self, mask: int) -> None:
        self._ensure_live()
        self._kernel.begin_constraint_debug(self._handle, int(mask))

    def end_constraint_debug(self) -> None:
        self._ensure_live()
        self._kernel.end_constraint_debug(self._handle)

    def read_constraint_debug_state(self) -> Mapping[str, object]:
        self._ensure_live()
        return self._kernel.read_constraint_debug_state(self._handle)

    def clear_constraint_debug(self) -> None:
        self._ensure_live()
        self._kernel.clear_constraint_debug(self._handle)

    def read_center_debug_state(self) -> Mapping[str, object]:
        """Read Center/Teleport state only for an explicit debug request."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("CPU backend Center debug state requires update_frame first")
        read_state = getattr(self._kernel, "read_center_debug_state", None)
        if not callable(read_state):
            raise RuntimeError("CPU kernel does not expose Center debug state")
        return read_state(self._handle)

    def read_task_reference_teleport_state(self) -> Mapping[str, object]:
        """Read the explicit task-reference Teleport observation state."""
        self._ensure_live()
        if self._latest_frame is None:
            raise RuntimeError("task-reference Teleport debug requires update_frame first")
        read_state = getattr(
            self._kernel, "read_task_reference_teleport_state", None
        )
        if not callable(read_state):
            raise RuntimeError("CPU kernel does not expose task-reference Teleport debug")
        return read_state(self._handle)

    def inspect(self) -> dict:
        self._ensure_live()
        kernel_state = self._kernel.inspect(self._handle)
        if not isinstance(kernel_state, Mapping):
            raise TypeError("CPU kernel inspect must return a mapping")
        return {
            "backend_id": self._backend_id,
            "domain_signature": self._compiled.program.domain_signature,
            "layout_signature": self._compiled.program.layout_signature,
            "physical_layout_revision": 1,
            "particle_count": self._compiled.program.particle_count,
            "partition_ids": self._compiled.program.partition_ids,
            "step_count": self._step_count,
            "partition_history": {
                key: dict(value) for key, value in self._partition_history.items()
            },
            "kernel": dict(kernel_state),
        }

    def dispose(self) -> None:
        if self._handle is not None:
            handle = self._handle
            self._handle = None
            try:
                self._kernel.dispose(handle)
            finally:
                self._latest_frame = None
                self._last_output = None
                self._partition_history.clear()

    def __enter__(self) -> "MC2CPUBackendDomainV1":
        self._ensure_live()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.dispose()

    def _validate_identity(self, domain_signature: str, layout_signature: str) -> None:
        if domain_signature != self._compiled.program.domain_signature:
            raise ValueError("CPU backend domain signature mismatch")
        if layout_signature != self._compiled.program.layout_signature:
            raise ValueError("CPU backend layout signature mismatch")

    def _ensure_live(self) -> None:
        if self._handle is None:
            raise RuntimeError("MC2 CPU backend domain has been disposed")


def create_mc2_cpu_backend_domain(
    compiled: MC2CompiledDomainV1,
    kernel: MC2CPUKernelV1,
    *,
    capabilities: MC2BackendCapabilitiesV1 = MC2_CPU_REFERENCE_CAPABILITIES,
) -> MC2CPUBackendDomainV1:
    return MC2CPUBackendDomainV1.create(
        compiled,
        kernel,
        capabilities=capabilities,
    )


__all__ = [
    "MC2_CPU_REFERENCE_CAPABILITIES",
    "MC2CPUBackendDomainV1",
    "MC2CPUKernelV1",
    "create_mc2_cpu_backend_domain",
]
