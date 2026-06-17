#include "hotools_mc2.hpp"

#include <algorithm>
#include <cmath>

namespace hotools {
namespace {

constexpr float kMc2Epsilon = 0.00000001f;
constexpr float kDistanceHorizontalStiffness = 0.5f;
constexpr float kDistanceFixedInverseMass = 1.0f / 50.0f;
constexpr float kTetherStiffnessWidth = 0.3f;
constexpr float kTetherCompressionStiffness = 1.0f;
constexpr float kTetherStretchStiffness = 1.0f;
constexpr float kTetherCompressionVelocityAttenuation = 0.7f;
constexpr float kTetherStretchVelocityAttenuation = 0.7f;
constexpr float kMotionVelocityAttenuation = 0.95f;
constexpr float kFrictionDampingRate = 0.6f;
constexpr float kStaticFrictionIncrease = 0.04f;
constexpr float kStaticFrictionDecay = 0.05f;
constexpr float kStaticFrictionVelocityWidth = 0.2f;

float clamp_float(float value, float lo, float hi) {
    return std::max(lo, std::min(hi, value));
}

void safe_normal_or_z(float x, float y, float z, float& out_x, float& out_y, float& out_z) {
    const float length = std::sqrt(x * x + y * y + z * z);
    if (length > kMc2Epsilon) {
        const float inv_length = 1.0f / length;
        out_x = x * inv_length;
        out_y = y * inv_length;
        out_z = z * inv_length;
        return;
    }
    out_x = 0.0f;
    out_y = 0.0f;
    out_z = 1.0f;
}

}  // namespace

void project_neighbor_constraints_mc2(Mc2NeighborConstraintView& view) {
    if (view.vertex_count <= 0 || view.neighbor_count <= 0 || view.positions == nullptr ||
        view.inv_masses == nullptr || view.starts == nullptr || view.counts == nullptr ||
        view.neighbors == nullptr || view.rest_lengths == nullptr || view.stiffness_values == nullptr) {
        return;
    }

    bool has_stiffness = false;
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.stiffness_values[vertex] > kMc2Epsilon) {
            has_stiffness = true;
            break;
        }
    }
    if (!has_stiffness) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const float wi = view.inv_masses[vertex];
        if (wi <= kMc2Epsilon) {
            continue;
        }

        const float local_stiffness = clamp_float(view.stiffness_values[vertex], 0.0f, 1.0f);
        if (local_stiffness <= kMc2Epsilon) {
            continue;
        }

        const std::int32_t start = view.starts[vertex];
        const std::int32_t count = view.counts[vertex];
        if (start < 0 || count <= 0 || static_cast<std::int64_t>(start) + count > view.neighbor_count) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        const float current_x = view.positions[offset + 0];
        const float current_y = view.positions[offset + 1];
        const float current_z = view.positions[offset + 2];
        float add_x = 0.0f;
        float add_y = 0.0f;
        float add_z = 0.0f;
        int add_count = 0;

        for (std::int32_t local = 0; local < count; ++local) {
            const std::int64_t data_index = static_cast<std::int64_t>(start) + local;
            const std::int32_t neighbor = view.neighbors[data_index];
            if (neighbor < 0 || static_cast<std::int64_t>(neighbor) >= view.vertex_count) {
                continue;
            }

            const float rest_dist = view.rest_lengths[data_index];
            const float rest = std::fabs(rest_dist);
            float final_stiffness = local_stiffness;
            if (rest_dist < 0.0f) {
                final_stiffness = clamp_float(final_stiffness * kDistanceHorizontalStiffness, 0.0f, 1.0f);
            }

            const float raw_wj = view.inv_masses[neighbor];
            const float wj = raw_wj > kMc2Epsilon ? raw_wj : kDistanceFixedInverseMass;
            const float wsum = wi + wj;
            if (wsum <= kMc2Epsilon) {
                continue;
            }

            const std::int64_t neighbor_offset = static_cast<std::int64_t>(neighbor) * 3;
            const float dx = view.positions[neighbor_offset + 0] - current_x;
            const float dy = view.positions[neighbor_offset + 1] - current_y;
            const float dz = view.positions[neighbor_offset + 2] - current_z;
            const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (rest <= kMc2Epsilon) {
                add_x += dx * 0.5f;
                add_y += dy * 0.5f;
                add_z += dz * 0.5f;
                ++add_count;
                continue;
            }
            if (distance <= kMc2Epsilon) {
                continue;
            }

            const float correction_scale = ((distance - rest) * final_stiffness / wsum) * wi / distance;
            add_x += dx * correction_scale;
            add_y += dy * correction_scale;
            add_z += dz * correction_scale;
            ++add_count;
        }

        if (add_count > 0) {
            const float inv_add_count = 1.0f / static_cast<float>(add_count);
            const float add_pos_x = add_x * inv_add_count;
            const float add_pos_y = add_y * inv_add_count;
            const float add_pos_z = add_z * inv_add_count;
            view.positions[offset + 0] = current_x + add_pos_x;
            view.positions[offset + 1] = current_y + add_pos_y;
            view.positions[offset + 2] = current_z + add_pos_z;
            if (view.velocity_positions != nullptr && view.velocity_attenuation > kMc2Epsilon) {
                view.velocity_positions[offset + 0] += add_pos_x * view.velocity_attenuation;
                view.velocity_positions[offset + 1] += add_pos_y * view.velocity_attenuation;
                view.velocity_positions[offset + 2] += add_pos_z * view.velocity_attenuation;
            }
        }
    }
}

void project_tether_mc2(Mc2TetherConstraintView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.inv_masses == nullptr ||
        view.root_indices == nullptr || view.root_rest_lengths == nullptr) {
        return;
    }

    const float stiffness = clamp_float(view.stiffness, 0.0f, 1.0f);
    if (stiffness <= kMc2Epsilon) {
        return;
    }

    const float compression_limit = 1.0f - clamp_float(view.compression, 0.0f, 1.0f);
    const float stretch_limit = 1.0f + std::max(view.stretch, 0.0f);
    const float stiffness_width = std::max(kTetherStiffnessWidth, kMc2Epsilon);

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kMc2Epsilon) {
            continue;
        }

        const std::int32_t root_index = view.root_indices[vertex];
        if (root_index < 0 || static_cast<std::int64_t>(root_index) >= view.vertex_count) {
            continue;
        }

        const float rest_length = view.root_rest_lengths[vertex];
        if (rest_length <= kMc2Epsilon) {
            continue;
        }

        const std::int64_t vertex_offset = vertex * 3;
        const std::int64_t root_offset = static_cast<std::int64_t>(root_index) * 3;
        const float dx = view.positions[root_offset + 0] - view.positions[vertex_offset + 0];
        const float dy = view.positions[root_offset + 1] - view.positions[vertex_offset + 1];
        const float dz = view.positions[root_offset + 2] - view.positions[vertex_offset + 2];
        const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (distance <= kMc2Epsilon) {
            continue;
        }

        const float ratio = distance / rest_length;
        float dist = 0.0f;
        float solve_stiffness = 0.0f;
        float velocity_attenuation = 0.0f;
        if (ratio < compression_limit) {
            dist = distance - compression_limit * rest_length;
            const float fade = clamp_float((compression_limit - ratio) / stiffness_width, 0.0f, 1.0f);
            solve_stiffness = stiffness * kTetherCompressionStiffness * fade;
            velocity_attenuation = kTetherCompressionVelocityAttenuation;
        } else if (ratio > stretch_limit) {
            dist = distance - stretch_limit * rest_length;
            const float fade = clamp_float((ratio - stretch_limit) / stiffness_width, 0.0f, 1.0f);
            solve_stiffness = stiffness * kTetherStretchStiffness * fade;
            velocity_attenuation = kTetherStretchVelocityAttenuation;
        }

        if (solve_stiffness <= kMc2Epsilon) {
            continue;
        }

        const float correction_scale = dist * solve_stiffness / distance;
        const float add_x = dx * correction_scale;
        const float add_y = dy * correction_scale;
        const float add_z = dz * correction_scale;
        view.positions[vertex_offset + 0] += add_x;
        view.positions[vertex_offset + 1] += add_y;
        view.positions[vertex_offset + 2] += add_z;
        if (view.velocity_positions != nullptr && velocity_attenuation > kMc2Epsilon) {
            view.velocity_positions[vertex_offset + 0] += add_x * velocity_attenuation;
            view.velocity_positions[vertex_offset + 1] += add_y * velocity_attenuation;
            view.velocity_positions[vertex_offset + 2] += add_z * velocity_attenuation;
        }
    }
}

void project_motion_constraints_mc2(Mc2MotionConstraintView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.base_positions == nullptr ||
        view.base_normals == nullptr || view.inv_masses == nullptr || view.max_distances == nullptr ||
        view.stiffness_values == nullptr || view.backstop_radii == nullptr || view.backstop_distances == nullptr) {
        return;
    }

    bool use_max_distance = false;
    bool use_backstop = false;
    bool has_stiffness = false;
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.max_distances[vertex] > kMc2Epsilon) {
            use_max_distance = true;
        }
        if (view.backstop_radii[vertex] > kMc2Epsilon) {
            use_backstop = true;
        }
        if (view.stiffness_values[vertex] > kMc2Epsilon) {
            has_stiffness = true;
        }
    }
    if ((!use_max_distance && !use_backstop) || !has_stiffness) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kMc2Epsilon) {
            continue;
        }

        const float stiffness = view.stiffness_values[vertex];
        if (stiffness <= kMc2Epsilon) {
            continue;
        }
        const float limit = view.max_distances[vertex];
        const float backstop_radius = std::max(view.backstop_radii[vertex], 0.0f);
        if (limit <= kMc2Epsilon && backstop_radius <= kMc2Epsilon) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        const float original_x = view.positions[offset + 0];
        const float original_y = view.positions[offset + 1];
        const float original_z = view.positions[offset + 2];
        float constrained_x = original_x;
        float constrained_y = original_y;
        float constrained_z = original_z;

        if (use_max_distance && limit > kMc2Epsilon) {
            const float dx = constrained_x - view.base_positions[offset + 0];
            const float dy = constrained_y - view.base_positions[offset + 1];
            const float dz = constrained_z - view.base_positions[offset + 2];
            const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (distance > limit && distance > kMc2Epsilon) {
                const float scale = limit / distance;
                constrained_x = view.base_positions[offset + 0] + dx * scale;
                constrained_y = view.base_positions[offset + 1] + dy * scale;
                constrained_z = view.base_positions[offset + 2] + dz * scale;
            }
        }

        if (use_backstop && backstop_radius > kMc2Epsilon) {
            float nx = 0.0f;
            float ny = 0.0f;
            float nz = 1.0f;
            safe_normal_or_z(view.base_normals[offset + 0], view.base_normals[offset + 1], view.base_normals[offset + 2],
                             nx, ny, nz);
            const float backstop_distance = std::max(view.backstop_distances[vertex], 0.0f);
            const float center_x = view.base_positions[offset + 0] - nx * (backstop_distance + backstop_radius);
            const float center_y = view.base_positions[offset + 1] - ny * (backstop_distance + backstop_radius);
            const float center_z = view.base_positions[offset + 2] - nz * (backstop_distance + backstop_radius);
            const float dx = constrained_x - center_x;
            const float dy = constrained_y - center_y;
            const float dz = constrained_z - center_z;
            const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            if (distance > kMc2Epsilon && distance < backstop_radius) {
                const float scale = backstop_radius / distance;
                constrained_x = center_x + dx * scale;
                constrained_y = center_y + dy * scale;
                constrained_z = center_z + dz * scale;
            }
        }

        const float clamped_stiffness = clamp_float(stiffness, 0.0f, 1.0f);
        const float next_x = original_x * (1.0f - clamped_stiffness) + constrained_x * clamped_stiffness;
        const float next_y = original_y * (1.0f - clamped_stiffness) + constrained_y * clamped_stiffness;
        const float next_z = original_z * (1.0f - clamped_stiffness) + constrained_z * clamped_stiffness;
        const float add_x = next_x - original_x;
        const float add_y = next_y - original_y;
        const float add_z = next_z - original_z;
        view.positions[offset + 0] = next_x;
        view.positions[offset + 1] = next_y;
        view.positions[offset + 2] = next_z;
        if (view.velocity_positions != nullptr) {
            view.velocity_positions[offset + 0] += add_x * kMotionVelocityAttenuation;
            view.velocity_positions[offset + 1] += add_y * kMotionVelocityAttenuation;
            view.velocity_positions[offset + 2] += add_z * kMotionVelocityAttenuation;
        }
    }
}

void apply_post_step_mc2(Mc2PostStepView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.old_positions == nullptr ||
        view.velocity_positions == nullptr || view.velocities == nullptr || view.real_velocities == nullptr ||
        view.friction == nullptr || view.static_friction == nullptr || view.collision_normals == nullptr ||
        view.inv_masses == nullptr || view.step_dt <= kMc2Epsilon) {
        return;
    }

    const float dynamic_friction = clamp_float(view.dynamic_friction, 0.0f, 1.0f);
    const float static_friction_speed = std::max(view.static_friction_speed, 0.0f);
    const float particle_speed_limit = view.particle_speed_limit;

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t offset = vertex * 3;
        float next_x = view.positions[offset + 0];
        float next_y = view.positions[offset + 1];
        float next_z = view.positions[offset + 2];
        const float old_x = view.old_positions[offset + 0];
        const float old_y = view.old_positions[offset + 1];
        const float old_z = view.old_positions[offset + 2];

        if (view.inv_masses[vertex] > kMc2Epsilon) {
            float velocity_old_x = view.velocity_positions[offset + 0];
            float velocity_old_y = view.velocity_positions[offset + 1];
            float velocity_old_z = view.velocity_positions[offset + 2];
            const float contact_x = view.collision_normals[offset + 0];
            const float contact_y = view.collision_normals[offset + 1];
            const float contact_z = view.collision_normals[offset + 2];
            const float contact_normal_len_sq = contact_x * contact_x + contact_y * contact_y + contact_z * contact_z;
            const float contact_friction = view.friction[vertex];
            const bool has_collision = contact_normal_len_sq > kMc2Epsilon && contact_friction > kMc2Epsilon;

            float static_value = view.static_friction[vertex];
            if (has_collision && static_friction_speed > 0.0f) {
                float normal_x = 0.0f;
                float normal_y = 0.0f;
                float normal_z = 1.0f;
                safe_normal_or_z(contact_x, contact_y, contact_z, normal_x, normal_y, normal_z);

                float tangent_x = next_x - old_x;
                float tangent_y = next_y - old_y;
                float tangent_z = next_z - old_z;
                const float normal_dot = tangent_x * normal_x + tangent_y * normal_y + tangent_z * normal_z;
                tangent_x -= normal_x * normal_dot;
                tangent_y -= normal_y * normal_dot;
                tangent_z -= normal_z * normal_dot;

                const float tangent_len = std::sqrt(tangent_x * tangent_x + tangent_y * tangent_y + tangent_z * tangent_z);
                const float tangent_velocity = tangent_len / view.step_dt;
                if (tangent_velocity < static_friction_speed) {
                    static_value = std::min(1.0f, static_value + kStaticFrictionIncrease);
                } else {
                    const float excess = tangent_velocity - static_friction_speed;
                    const float decay = std::max(excess / kStaticFrictionVelocityWidth, 0.05f);
                    static_value = std::max(0.0f, static_value - decay);
                }

                tangent_x *= static_value;
                tangent_y *= static_value;
                tangent_z *= static_value;
                next_x -= tangent_x;
                next_y -= tangent_y;
                next_z -= tangent_z;
                velocity_old_x -= tangent_x;
                velocity_old_y -= tangent_y;
                velocity_old_z -= tangent_z;
                view.positions[offset + 0] = next_x;
                view.positions[offset + 1] = next_y;
                view.positions[offset + 2] = next_z;
            } else {
                static_value = std::max(0.0f, static_value - kStaticFrictionDecay);
            }
            view.static_friction[vertex] = static_value;

            float velocity_x = (next_x - velocity_old_x) / view.step_dt;
            float velocity_y = (next_y - velocity_old_y) / view.step_dt;
            float velocity_z = (next_z - velocity_old_z) / view.step_dt;
            float speed_sq = velocity_x * velocity_x + velocity_y * velocity_y + velocity_z * velocity_z;
            if (has_collision && dynamic_friction > 0.0f && speed_sq >= kMc2Epsilon) {
                float normal_x = 0.0f;
                float normal_y = 0.0f;
                float normal_z = 1.0f;
                safe_normal_or_z(contact_x, contact_y, contact_z, normal_x, normal_y, normal_z);
                const float speed = std::max(std::sqrt(speed_sq), kMc2Epsilon);
                const float velocity_normal_x = velocity_x / speed;
                const float velocity_normal_y = velocity_y / speed;
                const float velocity_normal_z = velocity_z / speed;
                float dot = 0.5f + 0.5f * (normal_x * velocity_normal_x + normal_y * velocity_normal_y +
                                           normal_z * velocity_normal_z);
                dot *= dot;
                const float attenuation =
                    (1.0f - dot) * clamp_float(contact_friction * dynamic_friction, 0.0f, 1.0f);
                velocity_x -= velocity_x * attenuation;
                velocity_y -= velocity_y * attenuation;
                velocity_z -= velocity_z * attenuation;
                speed_sq = velocity_x * velocity_x + velocity_y * velocity_y + velocity_z * velocity_z;
            }

            if (particle_speed_limit >= 0.0f && particle_speed_limit > kMc2Epsilon) {
                const float speed = std::sqrt(speed_sq);
                if (speed > particle_speed_limit && speed > kMc2Epsilon) {
                    const float scale = particle_speed_limit / speed;
                    velocity_x *= scale;
                    velocity_y *= scale;
                    velocity_z *= scale;
                }
            }
            view.velocities[offset + 0] = velocity_x;
            view.velocities[offset + 1] = velocity_y;
            view.velocities[offset + 2] = velocity_z;
            view.friction[vertex] = contact_friction * kFrictionDampingRate;
        } else {
            view.velocities[offset + 0] = 0.0f;
            view.velocities[offset + 1] = 0.0f;
            view.velocities[offset + 2] = 0.0f;
            view.static_friction[vertex] = 0.0f;
            view.friction[vertex] = 0.0f;
        }

        view.real_velocities[offset + 0] = (view.positions[offset + 0] - old_x) / view.step_dt;
        view.real_velocities[offset + 1] = (view.positions[offset + 1] - old_y) / view.step_dt;
        view.real_velocities[offset + 2] = (view.positions[offset + 2] - old_z) / view.step_dt;
        view.old_positions[offset + 0] = view.positions[offset + 0];
        view.old_positions[offset + 1] = view.positions[offset + 1];
        view.old_positions[offset + 2] = view.positions[offset + 2];
        view.velocity_positions[offset + 0] = view.positions[offset + 0];
        view.velocity_positions[offset + 1] = view.positions[offset + 1];
        view.velocity_positions[offset + 2] = view.positions[offset + 2];
    }
}

void project_collisions_mc2(Mc2CollisionView& view) {
    if (view.vertex_count <= 0 || view.collider_count <= 0 || view.positions == nullptr ||
        view.base_positions == nullptr || view.inv_masses == nullptr || view.collision_radii == nullptr ||
        view.collision_normals == nullptr || view.collider_types == nullptr ||
        view.collider_group_bits == nullptr || view.collider_centers == nullptr ||
        view.collider_segment_a == nullptr || view.collider_segment_b == nullptr ||
        view.collider_radii == nullptr || view.collided_by_groups == 0) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kMc2Epsilon) {
            continue;
        }
        const float hit_radius = view.collision_radii[vertex];
        if (hit_radius <= kMc2Epsilon) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        const float origin_x = view.positions[offset + 0];
        const float origin_y = view.positions[offset + 1];
        const float origin_z = view.positions[offset + 2];
        const float fallback_x = origin_x - view.base_positions[offset + 0];
        const float fallback_y = origin_y - view.base_positions[offset + 1];
        const float fallback_z = origin_z - view.base_positions[offset + 2];

        float add_x = 0.0f;
        float add_y = 0.0f;
        float add_z = 0.0f;
        float add_normal_x = 0.0f;
        float add_normal_y = 0.0f;
        float add_normal_z = 0.0f;
        int add_count = 0;
        float friction_normal_x = 0.0f;
        float friction_normal_y = 0.0f;
        float friction_normal_z = 0.0f;
        float friction_value = 0.0f;
        const float friction_range = std::max(hit_radius, kMc2Epsilon);

        for (std::int64_t collider = 0; collider < view.collider_count; ++collider) {
            if ((view.collided_by_groups & view.collider_group_bits[collider]) == 0) {
                continue;
            }

            const std::int64_t collider_offset = collider * 3;
            const float collider_radius = std::max(view.collider_radii[collider], 0.0f);
            const float radius = hit_radius + collider_radius;
            if (radius <= kMc2Epsilon) {
                continue;
            }

            float center_x = view.collider_centers[collider_offset + 0];
            float center_y = view.collider_centers[collider_offset + 1];
            float center_z = view.collider_centers[collider_offset + 2];
            if (view.collider_types[collider] == 1) {
                const float ax = view.collider_segment_a[collider_offset + 0];
                const float ay = view.collider_segment_a[collider_offset + 1];
                const float az = view.collider_segment_a[collider_offset + 2];
                const float bx = view.collider_segment_b[collider_offset + 0];
                const float by = view.collider_segment_b[collider_offset + 1];
                const float bz = view.collider_segment_b[collider_offset + 2];
                const float sx = bx - ax;
                const float sy = by - ay;
                const float sz = bz - az;
                const float denom = sx * sx + sy * sy + sz * sz;
                float t = 0.0f;
                if (denom > kMc2Epsilon) {
                    t = ((origin_x - ax) * sx + (origin_y - ay) * sy + (origin_z - az) * sz) / denom;
                    t = clamp_float(t, 0.0f, 1.0f);
                }
                center_x = ax + sx * t;
                center_y = ay + sy * t;
                center_z = az + sz * t;
            }

            const float dx = origin_x - center_x;
            const float dy = origin_y - center_y;
            const float dz = origin_z - center_z;
            const float distance = std::sqrt(dx * dx + dy * dy + dz * dz);
            float normal_x = 0.0f;
            float normal_y = 0.0f;
            float normal_z = 1.0f;
            if (distance <= radius + friction_range) {
                if (distance > kMc2Epsilon) {
                    const float inv_distance = 1.0f / distance;
                    normal_x = dx * inv_distance;
                    normal_y = dy * inv_distance;
                    normal_z = dz * inv_distance;
                } else {
                    safe_normal_or_z(fallback_x, fallback_y, fallback_z, normal_x, normal_y, normal_z);
                }
                const float collider_distance = std::max(distance - radius, 0.0f);
                const float near_friction = 1.0f - clamp_float(collider_distance / friction_range, 0.0f, 1.0f);
                if (near_friction > friction_value) {
                    friction_value = near_friction;
                }
                friction_normal_x += normal_x;
                friction_normal_y += normal_y;
                friction_normal_z += normal_z;
            }
            if (distance >= radius) {
                continue;
            }

            add_x += center_x + normal_x * radius - origin_x;
            add_y += center_y + normal_y * radius - origin_y;
            add_z += center_z + normal_z * radius - origin_z;
            add_normal_x += normal_x;
            add_normal_y += normal_y;
            add_normal_z += normal_z;
            ++add_count;
        }

        if (add_count <= 0) {
            const float friction_length =
                std::sqrt(friction_normal_x * friction_normal_x + friction_normal_y * friction_normal_y +
                          friction_normal_z * friction_normal_z);
            if (friction_length <= kMc2Epsilon) {
                view.collision_normals[offset + 0] = 0.0f;
                view.collision_normals[offset + 1] = 0.0f;
                view.collision_normals[offset + 2] = 0.0f;
                continue;
            }
            const float inv_length = 1.0f / friction_length;
            view.collision_normals[offset + 0] = friction_normal_x * inv_length;
            view.collision_normals[offset + 1] = friction_normal_y * inv_length;
            view.collision_normals[offset + 2] = friction_normal_z * inv_length;
            if (view.friction != nullptr && friction_value > view.friction[vertex]) {
                view.friction[vertex] = friction_value;
            }
            continue;
        }

        const float inv_add_count = 1.0f / static_cast<float>(add_count);
        add_normal_x *= inv_add_count;
        add_normal_y *= inv_add_count;
        add_normal_z *= inv_add_count;
        const float normal_length =
            std::sqrt(add_normal_x * add_normal_x + add_normal_y * add_normal_y + add_normal_z * add_normal_z);
        if (normal_length <= kMc2Epsilon) {
            view.collision_normals[offset + 0] = 0.0f;
            view.collision_normals[offset + 1] = 0.0f;
            view.collision_normals[offset + 2] = 0.0f;
            if (view.friction != nullptr && friction_value > view.friction[vertex]) {
                view.friction[vertex] = friction_value;
            }
            continue;
        }

        const float blend = std::min(normal_length, 1.0f);
        view.positions[offset + 0] = origin_x + add_x * inv_add_count * blend;
        view.positions[offset + 1] = origin_y + add_y * inv_add_count * blend;
        view.positions[offset + 2] = origin_z + add_z * inv_add_count * blend;
        const float inv_normal_length = 1.0f / normal_length;
        view.collision_normals[offset + 0] = add_normal_x * inv_normal_length;
        view.collision_normals[offset + 1] = add_normal_y * inv_normal_length;
        view.collision_normals[offset + 2] = add_normal_z * inv_normal_length;
        if (view.friction != nullptr && 1.0f > view.friction[vertex]) {
            view.friction[vertex] = 1.0f;
        }
    }
}

}  // namespace hotools
