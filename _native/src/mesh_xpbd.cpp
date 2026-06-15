#include "hotools_mesh_xpbd.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

namespace hotools {
namespace {

constexpr float kEpsilon = 0.000001f;

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

}  // namespace

void solve_mesh_shape_key_xpbd(MeshXpbdView& view) {
    if (view.vertex_count <= 0) {
        return;
    }

    const int substep_count = clamp_int(view.substeps, 1, 16);
    const int iteration_count = clamp_int(view.iterations, 0, 64);
    const float damping = clamp_float(view.damping, 0.0f, 1.0f);
    const float step_dt = substep_count > 0 ? view.dt / static_cast<float>(substep_count) : view.dt;
    const float step_dt_sq = step_dt * step_dt;
    const bool has_pinned = has_pinned_vertices(view);

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
                (px - view.prev_positions[offset + 0]) * (1.0f - damping) + view.gravity[0] * step_dt_sq;
            view.positions[offset + 1] +=
                (py - view.prev_positions[offset + 1]) * (1.0f - damping) + view.gravity[1] * step_dt_sq;
            view.positions[offset + 2] +=
                (pz - view.prev_positions[offset + 2]) * (1.0f - damping) + view.gravity[2] * step_dt_sq;

            view.prev_positions[offset + 0] = old_positions[static_cast<std::size_t>(offset + 0)];
            view.prev_positions[offset + 1] = old_positions[static_cast<std::size_t>(offset + 1)];
            view.prev_positions[offset + 2] = old_positions[static_cast<std::size_t>(offset + 2)];
        }

        if (has_pinned) {
            apply_pin_constraints(view);
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
        }
    }
}

}  // namespace hotools
