"""MeshCloth 的纯数组约束投影。

本模块不读取 Blender 对象，也不处理碰撞快照。C++ 后端应优先对齐这里的
distance、tether、motion 行为，再逐步替换 Python 调度层。
"""

import numpy as np

from . import params
from .constants import MC2SystemConstants
from . import math_utils


def project_neighbor_constraints(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    starts: np.ndarray,
    counts: np.ndarray,
    neighbors: np.ndarray,
    rest_lengths: np.ndarray,
    stiffness,
    velocity_positions: np.ndarray | None = None,
    velocity_attenuation: float = 0.0,
) -> None:
    if len(neighbors) == 0:
        return
    if isinstance(stiffness, np.ndarray):
        stiffness_values = np.clip(np.ascontiguousarray(stiffness, dtype=np.float32), 0.0, 1.0)
        if len(stiffness_values) != len(positions):
            return
        if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
            return
    else:
        stiffness_value = max(0.0, min(1.0, float(stiffness)))
        if stiffness_value <= MC2SystemConstants.EPSILON:
            return
        stiffness_values = None

    if stiffness_values is None and stiffness_value <= MC2SystemConstants.EPSILON:
        return

    vertex_count = len(positions)
    for vertex_index in range(vertex_count):
        wi = float(inv_masses[vertex_index])
        if wi <= MC2SystemConstants.EPSILON:
            continue
        local_stiffness = float(stiffness_values[vertex_index]) if stiffness_values is not None else stiffness_value
        if local_stiffness <= MC2SystemConstants.EPSILON:
            continue

        start = int(starts[vertex_index])
        count = int(counts[vertex_index])
        if count <= 0:
            continue

        add = np.zeros(3, dtype=np.float32)
        add_count = 0
        current = positions[vertex_index]
        for offset in range(count):
            data_index = start + offset
            neighbor_index = int(neighbors[data_index])
            rest_dist = float(rest_lengths[data_index])
            rest = abs(rest_dist)
            final_stiffness = local_stiffness
            if rest_dist < 0.0:
                final_stiffness = max(
                    0.0,
                    min(1.0, final_stiffness * MC2SystemConstants.DISTANCE_HORIZONTAL_STIFFNESS),
                )
            raw_wj = float(inv_masses[neighbor_index])
            wj = raw_wj if raw_wj > MC2SystemConstants.EPSILON else MC2SystemConstants.DISTANCE_FIXED_INVERSE_MASS
            wsum = wi + wj
            if wsum <= MC2SystemConstants.EPSILON:
                continue

            delta = positions[neighbor_index] - current
            distance = float(np.linalg.norm(delta))
            if rest <= MC2SystemConstants.EPSILON:
                add += delta * 0.5
                add_count += 1
                continue
            if distance <= MC2SystemConstants.EPSILON:
                continue

            normal = delta / distance
            correction = ((distance - rest) * final_stiffness / wsum) * wi * normal
            add += correction
            add_count += 1

        if add_count > 0:
            add_pos = add / float(add_count)
            positions[vertex_index] = current + add_pos
            if velocity_positions is not None and velocity_attenuation > MC2SystemConstants.EPSILON:
                velocity_positions[vertex_index] += add_pos * float(velocity_attenuation)


def _dihedral_angle_correction(
    pos_buffer: np.ndarray,
    inv_mass_buffer: np.ndarray,
    rest_angle: float,
    sign: float,
    stiffness: float,
) -> np.ndarray | None:
    p0 = pos_buffer[0]
    p1 = pos_buffer[1]
    p2 = pos_buffer[2]
    p3 = pos_buffer[3]
    edge = p3 - p2
    edge_length = float(np.linalg.norm(edge))
    if edge_length < 1.0e-8:
        return None
    inv_edge_length = 1.0 / edge_length

    n1 = np.cross(p2 - p0, p3 - p0)
    n2 = np.cross(p3 - p1, p2 - p1)
    n1_len_sq = float(np.dot(n1, n1))
    n2_len_sq = float(np.dot(n2, n2))
    if n1_len_sq <= MC2SystemConstants.EPSILON or n2_len_sq <= MC2SystemConstants.EPSILON:
        return None

    n1_grad = n1 / n1_len_sq
    n2_grad = n2 / n2_len_sq
    d0 = edge_length * n1_grad
    d1 = edge_length * n2_grad
    d2 = (
        float(np.dot(p0 - p3, edge)) * inv_edge_length * n1_grad
        + float(np.dot(p1 - p3, edge)) * inv_edge_length * n2_grad
    )
    d3 = (
        float(np.dot(p2 - p0, edge)) * inv_edge_length * n1_grad
        + float(np.dot(p2 - p1, edge)) * inv_edge_length * n2_grad
    )

    n1_norm = math_utils.safe_normal_np(n1_grad, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    n2_norm = math_utils.safe_normal_np(n2_grad, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
    dot = max(-1.0, min(1.0, float(np.dot(n1_norm, n2_norm))))
    phi = float(np.arccos(dot))

    gradients = (d0, d1, d2, d3)
    lamb = 0.0
    for i in range(4):
        lamb += float(inv_mass_buffer[i]) * float(np.dot(gradients[i], gradients[i]))
    if lamb <= MC2SystemConstants.EPSILON:
        return None

    dir_value = float(np.dot(np.cross(n1_norm, n2_norm), edge))
    dir_sign = -1.0 if dir_value < 0.0 else 1.0
    if abs(sign) > MC2SystemConstants.EPSILON:
        phi *= dir_sign
    else:
        lamb *= dir_sign

    lamb = (float(rest_angle) - phi) / lamb * float(stiffness)
    corrections = np.zeros((4, 3), dtype=np.float32)
    for i in range(4):
        corrections[i] = -float(inv_mass_buffer[i]) * lamb * gradients[i]
    return corrections


def project_dihedral_bending(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    pairs: np.ndarray,
    rest_angles: np.ndarray,
    signs: np.ndarray,
    stiffness,
) -> None:
    if len(pairs) == 0:
        return
    if isinstance(stiffness, np.ndarray):
        stiffness_values = np.clip(np.ascontiguousarray(stiffness, dtype=np.float32), 0.0, 1.0)
        if len(stiffness_values) != len(positions):
            return
        if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
            return
    else:
        stiffness_value = max(0.0, min(1.0, float(stiffness)))
        if stiffness_value <= MC2SystemConstants.EPSILON:
            return
        stiffness_values = None

    add_positions = np.zeros_like(positions, dtype=np.float32)
    add_counts = np.zeros(len(positions), dtype=np.int32)
    for pair_index, pair in enumerate(pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        if int(np.min(vertices)) < 0 or int(np.max(vertices)) >= len(positions):
            continue

        if stiffness_values is None:
            local_stiffness = stiffness_value
        else:
            local_stiffness = float(np.mean(stiffness_values[vertices]))
        if local_stiffness <= MC2SystemConstants.EPSILON:
            continue

        sign = -1.0 if int(signs[pair_index]) < 0 else 1.0
        rest_angle = float(rest_angles[pair_index]) * sign
        inv_mass_buffer = np.asarray(
            [
                (
                    MC2SystemConstants.TRIANGLE_BENDING_FIXED_INVERSE_MASS
                    if float(inv_masses[int(v)]) <= MC2SystemConstants.EPSILON
                    else float(inv_masses[int(v)])
                )
                for v in vertices
            ],
            dtype=np.float32,
        )
        if float(np.sum(inv_mass_buffer)) <= MC2SystemConstants.EPSILON:
            continue
        pos_buffer = np.ascontiguousarray(positions[vertices], dtype=np.float32)
        corrections = _dihedral_angle_correction(
            pos_buffer,
            inv_mass_buffer,
            rest_angle,
            sign,
            local_stiffness,
        )
        if corrections is None:
            continue
        for local_index, vertex_index in enumerate(vertices):
            if float(inv_masses[int(vertex_index)]) <= MC2SystemConstants.EPSILON:
                continue
            add_positions[int(vertex_index)] += corrections[local_index]
            add_counts[int(vertex_index)] += 1

    active = add_counts > 0
    if bool(np.any(active)):
        positions[active] += add_positions[active] / add_counts[active, None].astype(np.float32)


def _volume_correction(
    pos_buffer: np.ndarray,
    inv_mass_buffer: np.ndarray,
    rest_volume: float,
    stiffness: float,
) -> np.ndarray | None:
    p0 = pos_buffer[0]
    p1 = pos_buffer[1]
    p2 = pos_buffer[2]
    p3 = pos_buffer[3]
    scale = float(MC2SystemConstants.TRIANGLE_VOLUME_SCALE)
    volume = (1.0 / 6.0) * float(np.dot(np.cross(p1 - p0, p2 - p0), p3 - p0)) * scale
    grad0 = np.cross(p1 - p2, p3 - p2)
    grad1 = np.cross(p2 - p0, p3 - p0)
    grad2 = np.cross(p0 - p1, p3 - p1)
    grad3 = np.cross(p1 - p0, p2 - p0)
    gradients = (grad0, grad1, grad2, grad3)

    lamb = 0.0
    for i in range(4):
        lamb += float(inv_mass_buffer[i]) * float(np.dot(gradients[i], gradients[i]))
    lamb *= scale
    if abs(lamb) <= MC2SystemConstants.EPSILON:
        return None

    lamb = float(stiffness) * (float(rest_volume) - volume) / lamb
    corrections = np.zeros((4, 3), dtype=np.float32)
    for i in range(4):
        corrections[i] = float(inv_mass_buffer[i]) * lamb * gradients[i]
    return corrections


def project_volume_bending(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    pairs: np.ndarray,
    rest_volumes: np.ndarray,
    stiffness,
) -> None:
    if len(pairs) == 0:
        return
    if isinstance(stiffness, np.ndarray):
        stiffness_values = np.clip(np.ascontiguousarray(stiffness, dtype=np.float32), 0.0, 1.0)
        if len(stiffness_values) != len(positions):
            return
        if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
            return
    else:
        stiffness_value = max(0.0, min(1.0, float(stiffness)))
        if stiffness_value <= MC2SystemConstants.EPSILON:
            return
        stiffness_values = None

    add_positions = np.zeros_like(positions, dtype=np.float32)
    add_counts = np.zeros(len(positions), dtype=np.int32)
    for pair_index, pair in enumerate(pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        if int(np.min(vertices)) < 0 or int(np.max(vertices)) >= len(positions):
            continue
        if stiffness_values is None:
            local_stiffness = stiffness_value
        else:
            local_stiffness = float(np.mean(stiffness_values[vertices]))
        if local_stiffness <= MC2SystemConstants.EPSILON:
            continue

        inv_mass_buffer = np.asarray(
            [
                (
                    MC2SystemConstants.TRIANGLE_BENDING_FIXED_INVERSE_MASS
                    if float(inv_masses[int(v)]) <= MC2SystemConstants.EPSILON
                    else float(inv_masses[int(v)])
                )
                for v in vertices
            ],
            dtype=np.float32,
        )
        if float(np.sum(inv_mass_buffer)) <= MC2SystemConstants.EPSILON:
            continue
        corrections = _volume_correction(
            np.ascontiguousarray(positions[vertices], dtype=np.float32),
            inv_mass_buffer,
            float(rest_volumes[pair_index]),
            local_stiffness,
        )
        if corrections is None:
            continue
        for local_index, vertex_index in enumerate(vertices):
            if float(inv_masses[int(vertex_index)]) <= MC2SystemConstants.EPSILON:
                continue
            add_positions[int(vertex_index)] += corrections[local_index]
            add_counts[int(vertex_index)] += 1

    active = add_counts > 0
    if bool(np.any(active)):
        positions[active] += add_positions[active] / add_counts[active, None].astype(np.float32)


def _resolve_stiffness(positions: np.ndarray, stiffness):
    if isinstance(stiffness, np.ndarray):
        stiffness_values = np.clip(np.ascontiguousarray(stiffness, dtype=np.float32), 0.0, 1.0)
        if len(stiffness_values) != len(positions):
            return None, None
        if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
            return None, None
        return stiffness_values, None

    stiffness_value = max(0.0, min(1.0, float(stiffness)))
    if stiffness_value <= MC2SystemConstants.EPSILON:
        return None, None
    return None, stiffness_value


def _pair_stiffness(stiffness_values: np.ndarray | None, stiffness_value, vertices: np.ndarray) -> float:
    if stiffness_values is None:
        return float(stiffness_value)
    return float(np.mean(stiffness_values[vertices]))


def _bending_inv_mass_buffer(inv_masses: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    return np.asarray(
        [
            (
                MC2SystemConstants.TRIANGLE_BENDING_FIXED_INVERSE_MASS
                if float(inv_masses[int(v)]) <= MC2SystemConstants.EPSILON
                else float(inv_masses[int(v)])
            )
            for v in vertices
        ],
        dtype=np.float32,
    )


def _add_bending_corrections(
    add_positions: np.ndarray,
    add_counts: np.ndarray,
    inv_masses: np.ndarray,
    vertices: np.ndarray,
    corrections: np.ndarray | None,
) -> None:
    if corrections is None:
        return
    for local_index, vertex_index in enumerate(vertices):
        if float(inv_masses[int(vertex_index)]) <= MC2SystemConstants.EPSILON:
            continue
        add_positions[int(vertex_index)] += corrections[local_index]
        add_counts[int(vertex_index)] += 1


def project_triangle_bending(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    dihedral_pairs: np.ndarray,
    rest_angles: np.ndarray,
    signs: np.ndarray,
    volume_pairs: np.ndarray,
    rest_volumes: np.ndarray,
    stiffness,
) -> None:
    if len(dihedral_pairs) == 0 and len(volume_pairs) == 0:
        return
    stiffness_values, stiffness_value = _resolve_stiffness(positions, stiffness)
    if stiffness_values is None and stiffness_value is None:
        return

    add_positions = np.zeros_like(positions, dtype=np.float32)
    add_counts = np.zeros(len(positions), dtype=np.int32)

    for pair_index, pair in enumerate(dihedral_pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        if int(np.min(vertices)) < 0 or int(np.max(vertices)) >= len(positions):
            continue
        local_stiffness = _pair_stiffness(stiffness_values, stiffness_value, vertices)
        if local_stiffness <= MC2SystemConstants.EPSILON:
            continue
        inv_mass_buffer = _bending_inv_mass_buffer(inv_masses, vertices)
        if float(np.sum(inv_mass_buffer)) <= MC2SystemConstants.EPSILON:
            continue
        sign = -1.0 if int(signs[pair_index]) < 0 else 1.0
        corrections = _dihedral_angle_correction(
            np.ascontiguousarray(positions[vertices], dtype=np.float32),
            inv_mass_buffer,
            float(rest_angles[pair_index]) * sign,
            sign,
            local_stiffness,
        )
        _add_bending_corrections(add_positions, add_counts, inv_masses, vertices, corrections)

    for pair_index, pair in enumerate(volume_pairs):
        vertices = np.asarray(pair, dtype=np.int32)
        if int(np.min(vertices)) < 0 or int(np.max(vertices)) >= len(positions):
            continue
        local_stiffness = _pair_stiffness(stiffness_values, stiffness_value, vertices)
        if local_stiffness <= MC2SystemConstants.EPSILON:
            continue
        inv_mass_buffer = _bending_inv_mass_buffer(inv_masses, vertices)
        if float(np.sum(inv_mass_buffer)) <= MC2SystemConstants.EPSILON:
            continue
        corrections = _volume_correction(
            np.ascontiguousarray(positions[vertices], dtype=np.float32),
            inv_mass_buffer,
            float(rest_volumes[pair_index]),
            local_stiffness,
        )
        _add_bending_corrections(add_positions, add_counts, inv_masses, vertices, corrections)

    active = add_counts > 0
    if bool(np.any(active)):
        positions[active] += add_positions[active] / add_counts[active, None].astype(np.float32)


def project_tether(
    positions: np.ndarray,
    inv_masses: np.ndarray,
    root_indices: np.ndarray,
    root_rest_lengths: np.ndarray,
    stiffness: float,
    compression: float,
    stretch: float,
    velocity_positions: np.ndarray | None = None,
) -> None:
    stiffness = max(0.0, min(1.0, float(stiffness)))
    if stiffness <= MC2SystemConstants.EPSILON:
        return

    compression_limit = 1.0 - max(0.0, min(1.0, float(compression)))
    stretch_limit = 1.0 + max(0.0, float(stretch))
    stiffness_width = max(float(MC2SystemConstants.TETHER_STIFFNESS_WIDTH), MC2SystemConstants.EPSILON)

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= MC2SystemConstants.EPSILON:
            continue
        root_index = int(root_indices[vertex_index])
        if root_index < 0:
            continue
        rest_length = float(root_rest_lengths[vertex_index])
        if rest_length <= MC2SystemConstants.EPSILON:
            continue

        delta = positions[root_index] - positions[vertex_index]
        distance = float(np.linalg.norm(delta))
        if distance <= MC2SystemConstants.EPSILON:
            continue

        ratio = distance / rest_length
        dist = 0.0
        solve_stiffness = 0.0
        velocity_attenuation = 0.0
        if ratio < compression_limit:
            dist = distance - compression_limit * rest_length
            fade = max(0.0, min(1.0, (compression_limit - ratio) / stiffness_width))
            solve_stiffness = stiffness * MC2SystemConstants.TETHER_COMPRESSION_STIFFNESS * fade
            velocity_attenuation = MC2SystemConstants.TETHER_COMPRESSION_VELOCITY_ATTENUATION
        elif ratio > stretch_limit:
            dist = distance - stretch_limit * rest_length
            fade = max(0.0, min(1.0, (ratio - stretch_limit) / stiffness_width))
            solve_stiffness = stiffness * MC2SystemConstants.TETHER_STRETCH_STIFFNESS * fade
            velocity_attenuation = MC2SystemConstants.TETHER_STRETCH_VELOCITY_ATTENUATION

        if solve_stiffness <= MC2SystemConstants.EPSILON:
            continue

        add = (delta / distance) * (dist * solve_stiffness)
        positions[vertex_index] += add
        if velocity_positions is not None and velocity_attenuation > MC2SystemConstants.EPSILON:
            velocity_positions[vertex_index] += add * velocity_attenuation


def project_motion_constraint(
    positions: np.ndarray,
    base_positions: np.ndarray,
    base_normals: np.ndarray,
    inv_masses: np.ndarray,
    depths: np.ndarray,
    max_distance_param: dict,
    motion_stiffness_param: dict,
    backstop_radius_param: dict,
    backstop_distance_param: dict,
    world_scale: float,
    velocity_positions: np.ndarray | None = None,
) -> None:
    motion_depths = np.clip(np.ascontiguousarray(depths, dtype=np.float32) ** 2, 0.0, 1.0)
    max_distances = params.sample_param(max_distance_param, motion_depths) * max(float(world_scale), 0.0)
    stiffness_values = np.clip(params.sample_param(motion_stiffness_param, motion_depths), 0.0, 1.0)
    backstop_radii = params.sample_param(backstop_radius_param, motion_depths) * max(float(world_scale), 0.0)
    backstop_distances = params.sample_param(backstop_distance_param, motion_depths) * max(float(world_scale), 0.0)
    use_max_distance = bool(np.any(max_distances > MC2SystemConstants.EPSILON))
    use_backstop = bool(np.any(backstop_radii > MC2SystemConstants.EPSILON))
    if not use_max_distance and not use_backstop:
        return
    if not bool(np.any(stiffness_values > MC2SystemConstants.EPSILON)):
        return

    for vertex_index in range(len(positions)):
        if float(inv_masses[vertex_index]) <= MC2SystemConstants.EPSILON:
            continue
        stiffness = float(stiffness_values[vertex_index])
        if stiffness <= MC2SystemConstants.EPSILON:
            continue
        limit = float(max_distances[vertex_index])
        backstop_radius = max(float(backstop_radii[vertex_index]), 0.0)
        if limit <= MC2SystemConstants.EPSILON and backstop_radius <= MC2SystemConstants.EPSILON:
            continue
        original_position = positions[vertex_index].copy()
        constrained = original_position.copy()

        if use_max_distance and limit > MC2SystemConstants.EPSILON:
            delta = constrained - base_positions[vertex_index]
            distance = float(np.linalg.norm(delta))
            if distance > limit and distance > MC2SystemConstants.EPSILON:
                constrained = base_positions[vertex_index] + (delta / distance) * limit

        if use_backstop:
            if backstop_radius > MC2SystemConstants.EPSILON:
                normal = math_utils.safe_normal_np(
                    base_normals[vertex_index],
                    np.asarray((0.0, 0.0, 1.0), dtype=np.float32),
                )
                backstop_distance = max(float(backstop_distances[vertex_index]), 0.0)
                center = base_positions[vertex_index] - normal * (backstop_distance + backstop_radius)
                delta = constrained - center
                distance = float(np.linalg.norm(delta))
                if MC2SystemConstants.EPSILON < distance < backstop_radius:
                    constrained = center + (delta / distance) * backstop_radius

        next_position = original_position * (1.0 - stiffness) + constrained * stiffness
        add = next_position - original_position
        positions[vertex_index] = next_position
        if velocity_positions is not None:
            velocity_positions[vertex_index] += add * MC2SystemConstants.MOTION_VELOCITY_ATTENUATION


def apply_post_step(
    positions: np.ndarray,
    old_positions: np.ndarray,
    velocity_positions: np.ndarray,
    velocities: np.ndarray,
    real_velocities: np.ndarray,
    friction: np.ndarray,
    static_friction: np.ndarray,
    collision_normals: np.ndarray,
    inv_masses: np.ndarray,
    step_dt: float,
    dynamic_friction: float,
    static_friction_speed: float,
    particle_speed_limit: float,
) -> None:
    if step_dt <= MC2SystemConstants.EPSILON:
        return

    dynamic_friction = max(0.0, min(1.0, float(dynamic_friction)))
    static_friction_speed = max(float(static_friction_speed), 0.0)
    particle_speed_limit = max(float(particle_speed_limit), 0.0)

    for vertex_index in range(len(positions)):
        next_position = positions[vertex_index].copy()
        old_position = old_positions[vertex_index].copy()

        if float(inv_masses[vertex_index]) > MC2SystemConstants.EPSILON:
            velocity_old_position = velocity_positions[vertex_index].copy()
            contact_normal = collision_normals[vertex_index]
            contact_friction = float(friction[vertex_index])
            has_collision = (
                float(np.dot(contact_normal, contact_normal)) > MC2SystemConstants.EPSILON
                and contact_friction > MC2SystemConstants.EPSILON
            )

            static_value = float(static_friction[vertex_index])
            if has_collision and static_friction_speed > 0.0:
                normal = math_utils.safe_normal_np(contact_normal, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
                tangent_delta = math_utils.project_on_plane(next_position - old_position, normal)
                tangent_velocity = float(np.linalg.norm(tangent_delta)) / step_dt
                if tangent_velocity < static_friction_speed:
                    static_value = min(1.0, static_value + MC2SystemConstants.STATIC_FRICTION_INCREASE)
                else:
                    excess = tangent_velocity - static_friction_speed
                    decay = max(excess / MC2SystemConstants.STATIC_FRICTION_VELOCITY_WIDTH, 0.05)
                    static_value = max(0.0, static_value - decay)
                tangent_delta *= static_value
                next_position -= tangent_delta
                velocity_old_position -= tangent_delta
                positions[vertex_index] = next_position
            else:
                static_value = max(0.0, static_value - MC2SystemConstants.STATIC_FRICTION_DECAY)
            static_friction[vertex_index] = static_value

            velocity = (next_position - velocity_old_position) / step_dt
            speed_sq = float(np.dot(velocity, velocity))
            if has_collision and dynamic_friction > 0.0 and speed_sq >= MC2SystemConstants.EPSILON:
                normal = math_utils.safe_normal_np(contact_normal, np.asarray((0.0, 0.0, 1.0), dtype=np.float32))
                velocity_normal = velocity / max(float(np.sqrt(speed_sq)), MC2SystemConstants.EPSILON)
                dot = 0.5 + 0.5 * float(np.dot(normal, velocity_normal))
                dot = dot * dot
                attenuation = (1.0 - dot) * max(0.0, min(1.0, contact_friction * dynamic_friction))
                velocity -= velocity * attenuation

            if particle_speed_limit > MC2SystemConstants.EPSILON:
                velocity = math_utils.clamp_vector(velocity, particle_speed_limit)
            velocities[vertex_index] = velocity
            friction[vertex_index] = contact_friction * MC2SystemConstants.FRICTION_DAMPING_RATE
        else:
            velocities[vertex_index] = np.zeros(3, dtype=np.float32)
            static_friction[vertex_index] = 0.0
            friction[vertex_index] = 0.0

        real_velocities[vertex_index] = (positions[vertex_index] - old_position) / step_dt
        old_positions[vertex_index] = positions[vertex_index]
        velocity_positions[vertex_index] = positions[vertex_index]
