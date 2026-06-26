"""Cold restart helpers for MC2 frame discontinuities."""

from __future__ import annotations

import bpy
import numpy as np

from .. import inertia, state as mc2_state


def _restart_particle_state_from_base_pose(
    state: dict,
    center_state: mc2_state.MC2CenterState | mc2_state.MC2RuntimeOwner | None,
) -> dict:
    base_positions = np.ascontiguousarray(state.get("base_positions"), dtype=np.float32)
    if base_positions.ndim != 2 or base_positions.shape[1] != 3:
        return state
    vertex_count = int(base_positions.shape[0])
    zero_vec3 = np.zeros((vertex_count, 3), dtype=np.float32)
    zero_scalar = np.zeros(vertex_count, dtype=np.float32)
    inv_masses = np.ascontiguousarray(state.get("inv_masses"), dtype=np.float32)
    particle_state = mc2_state.commit_particle_state_for_center(
        state,
        center_state,
        next_positions=base_positions.copy(),
        old_positions=base_positions.copy(),
        velocity_positions=base_positions.copy(),
        display_positions=base_positions.copy(),
        velocity=zero_vec3.copy(),
        real_velocity=zero_vec3.copy(),
        friction=zero_scalar.copy(),
        static_friction=zero_scalar.copy(),
        collision_normals=zero_vec3.copy(),
        inv_masses=inv_masses,
    )
    if particle_state is None:
        state["next_positions"] = base_positions.copy()
        state["old_positions"] = base_positions.copy()
        state["velocity_positions"] = base_positions.copy()
        state["display_positions"] = base_positions.copy()
        state["velocity"] = zero_vec3.copy()
        state["real_velocity"] = zero_vec3.copy()
        state["friction"] = zero_scalar.copy()
        state["static_friction"] = zero_scalar.copy()
        state["collision_normals"] = zero_vec3.copy()
        state["inv_masses"] = inv_masses
    return state


def cold_restart_runtime_state(
    state: dict,
    obj: bpy.types.Object,
    center_state: mc2_state.MC2CenterState | mc2_state.MC2RuntimeOwner | None,
    team_state: mc2_state.MC2TeamState | mc2_state.MC2RuntimeOwner | None,
    blend_weight: float,
) -> dict:
    """Reset per-frame dynamic state after first frame, reset, or frame jump."""

    cold_state = _restart_particle_state_from_base_pose(state, center_state)
    mc2_state.set_inertia_state_for_center(cold_state, inertia.make_runtime_state(obj), center_state)
    mc2_state.set_previous_collider_snapshot_for_center(cold_state, None, center_state)
    team = mc2_state.coerce_team_state(team_state)
    if team is not None:
        team.apply_frame_context(0.0, 0.0, 0, 0, 1.0, cold_state, substep_count=1)
        team.apply_blend_context(0.0, blend_weight, cold_state)
        team.apply_gravity_context(1.0, 1.0, cold_state)
    else:
        cold_state["gravity_dot"] = 1.0
        cold_state["gravity_ratio"] = 1.0
        cold_state["velocity_weight"] = 0.0
        cold_state["blend_weight"] = max(0.0, min(1.0, float(blend_weight)))
        cold_state["frame_delta_time"] = 0.0
        cold_state["step_delta_time"] = 0.0
        cold_state["update_count"] = 0
        cold_state["skip_count"] = 0
        cold_state["substep_count"] = 1
        cold_state["frame_interpolation"] = 1.0
    return cold_state
