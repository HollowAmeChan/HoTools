#include "hotools_mesh_xpbd.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

namespace hotools {
namespace {

constexpr float kEpsilon = 0.000001f;
constexpr std::int32_t kColliderCapsule = 1;

float clamp_float(float value, float lo, float hi) {
    return std::max(lo, std::min(hi, value));
}

int clamp_int(int value, int lo, int hi) {
    return std::max(lo, std::min(hi, value));
}

void apply_pin_constraints(MeshXpbdView& view) {
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] > kEpsilon) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        view.positions[offset + 0] = view.rest_positions[offset + 0];
        view.positions[offset + 1] = view.rest_positions[offset + 1];
        view.positions[offset + 2] = view.rest_positions[offset + 2];
        view.prev_positions[offset + 0] = view.rest_positions[offset + 0];
        view.prev_positions[offset + 1] = view.rest_positions[offset + 1];
        view.prev_positions[offset + 2] = view.rest_positions[offset + 2];
    }
}

void project_distance_constraints(
    float* positions,
    const float* inv_masses,
    const std::int32_t* index_i,
    const std::int32_t* index_j,
    const float* rest_lengths,
    std::int64_t constraint_count,
    float compliance,
    float dt) {
    const float alpha = dt > kEpsilon ? std::max(compliance, 0.0f) / (dt * dt) : 0.0f;

    for (std::int64_t constraint = 0; constraint < constraint_count; ++constraint) {
        const std::int32_t i = index_i[constraint];
        const std::int32_t j = index_j[constraint];
        const float wi = inv_masses[i];
        const float wj = inv_masses[j];
        const float wsum = wi + wj;
        if (wsum <= kEpsilon) {
            continue;
        }

        const std::int64_t oi = static_cast<std::int64_t>(i) * 3;
        const std::int64_t oj = static_cast<std::int64_t>(j) * 3;
        const float dx = positions[oi + 0] - positions[oj + 0];
        const float dy = positions[oi + 1] - positions[oj + 1];
        const float dz = positions[oi + 2] - positions[oj + 2];
        const float length = std::sqrt(dx * dx + dy * dy + dz * dz);
        if (length <= kEpsilon) {
            continue;
        }

        const float c = length - rest_lengths[constraint];
        const float dlambda = -c / (wsum + alpha);
        const float nx = dx / length;
        const float ny = dy / length;
        const float nz = dz / length;

        if (wi > 0.0f) {
            const float scale = wi * dlambda;
            positions[oi + 0] += scale * nx;
            positions[oi + 1] += scale * ny;
            positions[oi + 2] += scale * nz;
        }
        if (wj > 0.0f) {
            const float scale = wj * dlambda;
            positions[oj + 0] -= scale * nx;
            positions[oj + 1] -= scale * ny;
            positions[oj + 2] -= scale * nz;
        }
    }
}

bool has_pinned_vertices(const MeshXpbdView& view) {
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kEpsilon) {
            return true;
        }
    }
    return false;
}

bool collision_group_enabled(std::int32_t mask, std::int32_t group) {
    if (group < 1 || group > 16) {
        return false;
    }
    return (mask & (1 << (group - 1))) != 0;
}

bool has_collision_constraints(const MeshXpbdView& view) {
    return view.collision_radii != nullptr &&
        view.collider_types != nullptr &&
        view.collider_groups != nullptr &&
        view.collider_centers != nullptr &&
        view.collider_segment_a != nullptr &&
        view.collider_segment_b != nullptr &&
        view.collider_radii != nullptr &&
        view.collider_count > 0 &&
        view.collided_by_groups != 0;
}

void closest_point_on_segment(
    float px,
    float py,
    float pz,
    const float* segment_a,
    const float* segment_b,
    float& out_x,
    float& out_y,
    float& out_z) {
    const float sx = segment_b[0] - segment_a[0];
    const float sy = segment_b[1] - segment_a[1];
    const float sz = segment_b[2] - segment_a[2];
    const float denom = sx * sx + sy * sy + sz * sz;
    if (denom <= kEpsilon) {
        out_x = segment_a[0];
        out_y = segment_a[1];
        out_z = segment_a[2];
        return;
    }

    float t = ((px - segment_a[0]) * sx + (py - segment_a[1]) * sy + (pz - segment_a[2]) * sz) / denom;
    t = clamp_float(t, 0.0f, 1.0f);
    out_x = segment_a[0] + sx * t;
    out_y = segment_a[1] + sy * t;
    out_z = segment_a[2] + sz * t;
}

void safe_normal(
    float dx,
    float dy,
    float dz,
    float fallback_x,
    float fallback_y,
    float fallback_z,
    float& out_x,
    float& out_y,
    float& out_z) {
    float length = std::sqrt(dx * dx + dy * dy + dz * dz);
    if (length > kEpsilon) {
        out_x = dx / length;
        out_y = dy / length;
        out_z = dz / length;
        return;
    }

    length = std::sqrt(fallback_x * fallback_x + fallback_y * fallback_y + fallback_z * fallback_z);
    if (length > kEpsilon) {
        out_x = fallback_x / length;
        out_y = fallback_y / length;
        out_z = fallback_z / length;
        return;
    }

    out_x = 0.0f;
    out_y = 0.0f;
    out_z = 1.0f;
}

void project_collision_constraints(MeshXpbdView& view) {
    if (!has_collision_constraints(view)) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kEpsilon) {
            continue;
        }

        const float hit_radius = view.collision_radii[vertex];
        if (hit_radius <= kEpsilon) {
            continue;
        }

        const std::int64_t vertex_offset = vertex * 3;
        float px = view.positions[vertex_offset + 0];
        float py = view.positions[vertex_offset + 1];
        float pz = view.positions[vertex_offset + 2];
        const float fallback_x = px - view.rest_positions[vertex_offset + 0];
        const float fallback_y = py - view.rest_positions[vertex_offset + 1];
        const float fallback_z = pz - view.rest_positions[vertex_offset + 2];

        for (std::int64_t collider = 0; collider < view.collider_count; ++collider) {
            if (!collision_group_enabled(view.collided_by_groups, view.collider_groups[collider])) {
                continue;
            }

            const float radius = std::max(view.collider_radii[collider], 0.0f) + hit_radius;
            if (radius <= kEpsilon) {
                continue;
            }

            const std::int64_t collider_offset = collider * 3;
            float cx = view.collider_centers[collider_offset + 0];
            float cy = view.collider_centers[collider_offset + 1];
            float cz = view.collider_centers[collider_offset + 2];
            if (view.collider_types[collider] == kColliderCapsule) {
                closest_point_on_segment(
                    px,
                    py,
                    pz,
                    view.collider_segment_a + collider_offset,
                    view.collider_segment_b + collider_offset,
                    cx,
                    cy,
                    cz);
            }

            const float dx = px - cx;
            const float dy = py - cy;
            const float dz = pz - cz;
            if (dx * dx + dy * dy + dz * dz >= radius * radius) {
                continue;
            }

            float nx = 0.0f;
            float ny = 0.0f;
            float nz = 1.0f;
            safe_normal(dx, dy, dz, fallback_x, fallback_y, fallback_z, nx, ny, nz);
            px = cx + nx * radius;
            py = cy + ny * radius;
            pz = cz + nz * radius;
        }

        view.positions[vertex_offset + 0] = px;
        view.positions[vertex_offset + 1] = py;
        view.positions[vertex_offset + 2] = pz;
    }
}

}  // namespace

void solve_mesh_shape_key_xpbd(MeshXpbdView& view) {
    if (view.vertex_count <= 0) {
        return;
    }

    const int substep_count = clamp_int(view.substeps, 1, 16);
    const int iteration_count = clamp_int(view.iterations, 0, 64);
    const float damping = clamp_float(view.damping, 0.0f, 1.0f);
    const float substep_damping = 1.0f - std::pow(1.0f - damping, 1.0f / static_cast<float>(substep_count));
    const float velocity_keep = 1.0f - substep_damping;
    const float step_dt = substep_count > 0 ? view.dt / static_cast<float>(substep_count) : view.dt;
    const float step_dt_sq = step_dt * step_dt;
    const bool has_pinned = has_pinned_vertices(view);
    const bool has_collision = has_collision_constraints(view);

    std::vector<float> old_positions(static_cast<std::size_t>(view.vertex_count) * 3U);

    for (int substep = 0; substep < substep_count; ++substep) {
        std::copy(
            view.positions,
            view.positions + static_cast<std::size_t>(view.vertex_count) * 3U,
            old_positions.begin());

        for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
            const std::int64_t offset = vertex * 3;
            const float px = view.positions[offset + 0];
            const float py = view.positions[offset + 1];
            const float pz = view.positions[offset + 2];

            view.positions[offset + 0] +=
                (px - view.prev_positions[offset + 0]) * velocity_keep + view.gravity[0] * step_dt_sq;
            view.positions[offset + 1] +=
                (py - view.prev_positions[offset + 1]) * velocity_keep + view.gravity[1] * step_dt_sq;
            view.positions[offset + 2] +=
                (pz - view.prev_positions[offset + 2]) * velocity_keep + view.gravity[2] * step_dt_sq;

            view.prev_positions[offset + 0] = old_positions[static_cast<std::size_t>(offset + 0)];
            view.prev_positions[offset + 1] = old_positions[static_cast<std::size_t>(offset + 1)];
            view.prev_positions[offset + 2] = old_positions[static_cast<std::size_t>(offset + 2)];
        }

        if (has_pinned) {
            apply_pin_constraints(view);
        }

        if (has_collision) {
            project_collision_constraints(view);
        }

        for (int iteration = 0; iteration < iteration_count; ++iteration) {
            project_distance_constraints(
                view.positions,
                view.inv_masses,
                view.edge_i,
                view.edge_j,
                view.edge_rest,
                view.edge_count,
                view.stretch_compliance,
                step_dt);

            project_distance_constraints(
                view.positions,
                view.inv_masses,
                view.bend_i,
                view.bend_j,
                view.bend_rest,
                view.bend_count,
                view.bend_compliance,
                step_dt);

            if (has_pinned) {
                apply_pin_constraints(view);
            }

            if (has_collision) {
                project_collision_constraints(view);
            }
        }
    }
}

}  // namespace hotools
