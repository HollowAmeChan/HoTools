#include "mc2_kernels.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace hotools {
namespace {

constexpr float kMc2Epsilon = 0.00000001f;
constexpr int kSelfCollisionSolverIteration = 4;
constexpr float kSelfCollisionScr = 2.0f;
constexpr float kSelfCollisionPointTriangleAngleCos = 0.5f;
constexpr std::uint8_t kMc2AttrInvalid = 1u << 0u;
constexpr std::uint8_t kMc2AttrMove = 1u << 2u;

float clamp_float(float value, float lo, float hi) {
    return std::max(lo, std::min(hi, value));
}

float dot3(float ax, float ay, float az, float bx, float by, float bz) {
    return ax * bx + ay * by + az * bz;
}

float length3(float x, float y, float z) {
    return std::sqrt(x * x + y * y + z * z);
}

void cross3(float ax, float ay, float az, float bx, float by, float bz, float& out_x, float& out_y, float& out_z) {
    out_x = ay * bz - az * by;
    out_y = az * bx - ax * bz;
    out_z = ax * by - ay * bx;
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

void safe_normal_with_fallback(float x,
                               float y,
                               float z,
                               float fallback_x,
                               float fallback_y,
                               float fallback_z,
                               float& out_x,
                               float& out_y,
                               float& out_z) {
    const float length = std::sqrt(x * x + y * y + z * z);
    if (length > kMc2Epsilon) {
        const float inv_length = 1.0f / length;
        out_x = x * inv_length;
        out_y = y * inv_length;
        out_z = z * inv_length;
        return;
    }
    safe_normal_or_z(fallback_x, fallback_y, fallback_z, out_x, out_y, out_z);
}

float closest_segment_segment(float p1x,
                              float p1y,
                              float p1z,
                              float q1x,
                              float q1y,
                              float q1z,
                              float p2x,
                              float p2y,
                              float p2z,
                              float q2x,
                              float q2y,
                              float q2z,
                              float& out_s,
                              float& out_t,
                              float& out_c1x,
                              float& out_c1y,
                              float& out_c1z,
                              float& out_c2x,
                              float& out_c2y,
                              float& out_c2z) {
    const float d1x = q1x - p1x;
    const float d1y = q1y - p1y;
    const float d1z = q1z - p1z;
    const float d2x = q2x - p2x;
    const float d2y = q2y - p2y;
    const float d2z = q2z - p2z;
    const float rx = p1x - p2x;
    const float ry = p1y - p2y;
    const float rz = p1z - p2z;
    const float a = dot3(d1x, d1y, d1z, d1x, d1y, d1z);
    const float e = dot3(d2x, d2y, d2z, d2x, d2y, d2z);
    const float f = dot3(d2x, d2y, d2z, rx, ry, rz);
    float s = 0.0f;
    float t = 0.0f;
    if (a <= kMc2Epsilon && e <= kMc2Epsilon) {
        s = 0.0f;
        t = 0.0f;
    } else if (a <= kMc2Epsilon) {
        s = 0.0f;
        t = e > kMc2Epsilon ? clamp_float(f / e, 0.0f, 1.0f) : 0.0f;
    } else {
        const float c = dot3(d1x, d1y, d1z, rx, ry, rz);
        if (e <= kMc2Epsilon) {
            t = 0.0f;
            s = clamp_float(-c / a, 0.0f, 1.0f);
        } else {
            const float b = dot3(d1x, d1y, d1z, d2x, d2y, d2z);
            const float denom = a * e - b * b;
            s = denom != 0.0f ? clamp_float((b * f - c * e) / denom, 0.0f, 1.0f) : 0.0f;
            t = (b * s + f) / e;
            if (t < 0.0f) {
                t = 0.0f;
                s = clamp_float(-c / a, 0.0f, 1.0f);
            } else if (t > 1.0f) {
                t = 1.0f;
                s = clamp_float((b - c) / a, 0.0f, 1.0f);
            }
        }
    }
    out_s = s;
    out_t = t;
    out_c1x = p1x + d1x * s;
    out_c1y = p1y + d1y * s;
    out_c1z = p1z + d1z * s;
    out_c2x = p2x + d2x * t;
    out_c2y = p2y + d2y * t;
    out_c2z = p2z + d2z * t;
    const float dx = out_c1x - out_c2x;
    const float dy = out_c1y - out_c2y;
    const float dz = out_c1z - out_c2z;
    return dot3(dx, dy, dz, dx, dy, dz);
}

void triangle_normal(float ax,
                     float ay,
                     float az,
                     float bx,
                     float by,
                     float bz,
                     float cx,
                     float cy,
                     float cz,
                     float& out_x,
                     float& out_y,
                     float& out_z) {
    cross3(bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az, out_x, out_y, out_z);
    safe_normal_or_z(out_x, out_y, out_z, out_x, out_y, out_z);
}

void closest_point_triangle(float px,
                            float py,
                            float pz,
                            float ax,
                            float ay,
                            float az,
                            float bx,
                            float by,
                            float bz,
                            float cx,
                            float cy,
                            float cz,
                            float& out_x,
                            float& out_y,
                            float& out_z,
                            float& out_u,
                            float& out_v,
                            float& out_w) {
    const float abx = bx - ax;
    const float aby = by - ay;
    const float abz = bz - az;
    const float acx = cx - ax;
    const float acy = cy - ay;
    const float acz = cz - az;
    const float apx = px - ax;
    const float apy = py - ay;
    const float apz = pz - az;
    const float d1 = dot3(abx, aby, abz, apx, apy, apz);
    const float d2 = dot3(acx, acy, acz, apx, apy, apz);
    if (d1 <= 0.0f && d2 <= 0.0f) {
        out_x = ax;
        out_y = ay;
        out_z = az;
        out_u = 1.0f;
        out_v = 0.0f;
        out_w = 0.0f;
        return;
    }

    const float bpx = px - bx;
    const float bpy = py - by;
    const float bpz = pz - bz;
    const float d3 = dot3(abx, aby, abz, bpx, bpy, bpz);
    const float d4 = dot3(acx, acy, acz, bpx, bpy, bpz);
    if (d3 >= 0.0f && d4 <= d3) {
        out_x = bx;
        out_y = by;
        out_z = bz;
        out_u = 0.0f;
        out_v = 1.0f;
        out_w = 0.0f;
        return;
    }

    const float vc = d1 * d4 - d3 * d2;
    if (vc <= 0.0f && d1 >= 0.0f && d3 <= 0.0f) {
        const float denom = d1 - d3;
        const float v = std::fabs(denom) > kMc2Epsilon ? d1 / denom : 0.0f;
        out_x = ax + abx * v;
        out_y = ay + aby * v;
        out_z = az + abz * v;
        out_u = 1.0f - v;
        out_v = v;
        out_w = 0.0f;
        return;
    }

    const float cpx = px - cx;
    const float cpy = py - cy;
    const float cpz = pz - cz;
    const float d5 = dot3(abx, aby, abz, cpx, cpy, cpz);
    const float d6 = dot3(acx, acy, acz, cpx, cpy, cpz);
    if (d6 >= 0.0f && d5 <= d6) {
        out_x = cx;
        out_y = cy;
        out_z = cz;
        out_u = 0.0f;
        out_v = 0.0f;
        out_w = 1.0f;
        return;
    }

    const float vb = d5 * d2 - d1 * d6;
    if (vb <= 0.0f && d2 >= 0.0f && d6 <= 0.0f) {
        const float denom = d2 - d6;
        const float w = std::fabs(denom) > kMc2Epsilon ? d2 / denom : 0.0f;
        out_x = ax + acx * w;
        out_y = ay + acy * w;
        out_z = az + acz * w;
        out_u = 1.0f - w;
        out_v = 0.0f;
        out_w = w;
        return;
    }

    const float va = d3 * d6 - d5 * d4;
    if (va <= 0.0f && (d4 - d3) >= 0.0f && (d5 - d6) >= 0.0f) {
        const float denom = (d4 - d3) + (d5 - d6);
        const float w = std::fabs(denom) > kMc2Epsilon ? (d4 - d3) / denom : 0.0f;
        out_x = bx + (cx - bx) * w;
        out_y = by + (cy - by) * w;
        out_z = bz + (cz - bz) * w;
        out_u = 0.0f;
        out_v = 1.0f - w;
        out_w = w;
        return;
    }

    const float denom = va + vb + vc;
    if (std::fabs(denom) <= kMc2Epsilon) {
        out_x = ax;
        out_y = ay;
        out_z = az;
        out_u = 1.0f;
        out_v = 0.0f;
        out_w = 0.0f;
        return;
    }
    const float inv_denom = 1.0f / denom;
    out_v = vb * inv_denom;
    out_w = vc * inv_denom;
    out_u = 1.0f - out_v - out_w;
    out_x = ax * out_u + bx * out_v + cx * out_w;
    out_y = ay * out_u + by * out_v + cy * out_w;
    out_z = az * out_u + bz * out_v + cz * out_w;
}

struct SelfContact {
    int type = 0;
    std::int32_t v[4] = {};
    float a = 0.0f;
    float b = 0.0f;
    float c = 0.0f;
    float thickness = 0.0f;
    float normal[3] = {};
};

}  // namespace

void project_self_collisions_mc2(Mc2SelfCollisionView& view) {
    if (view.contact_count != nullptr) *view.contact_count = 0;
    if (view.candidate_count != nullptr) *view.candidate_count = 0;
    if (view.vertex_count <= 0 || view.positions == nullptr || view.old_positions == nullptr ||
        view.inv_masses == nullptr || view.attributes == nullptr || view.collision_normals == nullptr ||
        (view.particle_thickness == nullptr && view.surface_thickness <= kMc2Epsilon) ||
        (view.edge_count <= 0 && view.triangle_count <= 0)) {
        return;
    }

    const bool partitioned = view.particle_partition_index != nullptr;
    if (partitioned &&
        (view.partition_count <= 0 || view.partition_self_collision_modes == nullptr ||
         view.partition_collision_groups == nullptr || view.partition_collision_masks == nullptr)) {
        return;
    }

    auto partition_enabled = [&](std::uint32_t partition) {
        return !partitioned ||
            (partition < static_cast<std::uint32_t>(view.partition_count) &&
             view.partition_self_collision_modes[partition] == 2u);
    };
    auto owner_pair_allowed = [&](std::int32_t vertex0, std::int32_t vertex1) {
        if (!partitioned) return true;
        const std::uint32_t owner0 = view.particle_partition_index[vertex0];
        const std::uint32_t owner1 = view.particle_partition_index[vertex1];
        if (!partition_enabled(owner0) || !partition_enabled(owner1)) return false;
        if (owner0 == owner1) return true;
        const std::uint32_t mask0 = view.partition_collision_masks[owner0];
        const std::uint32_t mask1 = view.partition_collision_masks[owner1];
        const bool allows0 = mask0 == 0u ||
            (mask0 & view.partition_collision_groups[owner1]) != 0u;
        const bool allows1 = mask1 == 0u ||
            (mask1 & view.partition_collision_groups[owner0]) != 0u;
        return allows0 && allows1;
    };
    auto particle_pair_key = [](std::int32_t first, std::int32_t second) {
        const auto low = static_cast<std::uint32_t>(std::min(first, second));
        const auto high = static_cast<std::uint32_t>(std::max(first, second));
        return (static_cast<std::uint64_t>(low) << 32u) |
            static_cast<std::uint64_t>(high);
    };
    std::unordered_set<std::uint64_t> topology_neighbor_keys;
    topology_neighbor_keys.reserve(
        view.edge_count > 0 ? static_cast<std::size_t>(view.edge_count) : 0u
    );
    if (view.edges != nullptr) {
        for (std::int64_t edge = 0; edge < view.edge_count; ++edge) {
            const std::int32_t first = view.edges[edge * 2];
            const std::int32_t second = view.edges[edge * 2 + 1];
            if (first >= 0 && second >= 0 && first != second) {
                topology_neighbor_keys.insert(particle_pair_key(first, second));
            }
        }
    }
    auto topology_neighbors = [&](std::int32_t first, std::int32_t second) {
        if (partitioned &&
            view.particle_partition_index[first] != view.particle_partition_index[second]) {
            return false;
        }
        return topology_neighbor_keys.find(particle_pair_key(first, second)) !=
            topology_neighbor_keys.end();
    };
    auto particle_side_thickness = [&](std::int32_t vertex) {
        return view.particle_thickness == nullptr
            ? view.surface_thickness
            : std::max(view.particle_thickness[vertex], 0.0f);
    };
    auto primitive_side_thickness = [&](const std::int32_t* vertices, int count) {
        if (view.particle_thickness == nullptr) return view.surface_thickness;
        float total = 0.0f;
        for (int index = 0; index < count; ++index) {
            total += particle_side_thickness(vertices[index]);
        }
        return total / static_cast<float>(count);
    };

    bool has_movable = false;
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if ((view.attributes[vertex] & kMc2AttrMove) != 0) {
            has_movable = true;
            break;
        }
    }
    if (!has_movable) {
        return;
    }

    float broadphase_thickness = std::max(view.surface_thickness, 0.0f);
    if (view.particle_thickness != nullptr) {
        broadphase_thickness = 0.0f;
        for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
            broadphase_thickness = std::max(
                broadphase_thickness, particle_side_thickness(static_cast<std::int32_t>(vertex))
            );
        }
    }
    if (broadphase_thickness <= kMc2Epsilon) return;
    constexpr float kSelfCollisionGridScale = 3.0f;

    struct GridCell {
        std::int64_t x = 0;
        std::int64_t y = 0;
        std::int64_t z = 0;

        bool operator==(const GridCell& other) const noexcept {
            return x == other.x && y == other.y && z == other.z;
        }
    };

    struct GridCellHash {
        std::size_t operator()(const GridCell& cell) const noexcept {
            std::uint64_t hash = 1469598103934665603ull;
            auto mix = [&hash](std::int64_t value) {
                hash ^= static_cast<std::uint64_t>(value);
                hash *= 1099511628211ull;
            };
            mix(cell.x);
            mix(cell.y);
            mix(cell.z);
            return static_cast<std::size_t>(hash ^ (hash >> 32u));
        }
    };

    struct PrimitiveBounds {
        float min_x = 0.0f;
        float min_y = 0.0f;
        float min_z = 0.0f;
        float max_x = 0.0f;
        float max_y = 0.0f;
        float max_z = 0.0f;
        bool valid = false;
    };

    auto bounds_overlap = [](const PrimitiveBounds& left, const PrimitiveBounds& right) {
        return left.valid && right.valid &&
            left.max_x >= right.min_x && left.min_x <= right.max_x &&
            left.max_y >= right.min_y && left.min_y <= right.max_y &&
            left.max_z >= right.min_z && left.min_z <= right.max_z;
    };

    auto grid_coord = [](float value, float cell_size) -> std::int64_t {
        return static_cast<std::int64_t>(std::floor(value / cell_size));
    };

    auto for_grid_cells = [&](float min_x,
                              float min_y,
                              float min_z,
                              float max_x,
                              float max_y,
                              float max_z,
                              float cell_size,
                              auto&& visitor) {
        const float safe_cell_size = std::max(cell_size, kMc2Epsilon);
        const std::int64_t min_grid_x = grid_coord(min_x, safe_cell_size);
        const std::int64_t min_grid_y = grid_coord(min_y, safe_cell_size);
        const std::int64_t min_grid_z = grid_coord(min_z, safe_cell_size);
        const std::int64_t max_grid_x = grid_coord(max_x, safe_cell_size);
        const std::int64_t max_grid_y = grid_coord(max_y, safe_cell_size);
        const std::int64_t max_grid_z = grid_coord(max_z, safe_cell_size);
        for (std::int64_t grid_z = min_grid_z; grid_z <= max_grid_z; ++grid_z) {
            for (std::int64_t grid_y = min_grid_y; grid_y <= max_grid_y; ++grid_y) {
                for (std::int64_t grid_x = min_grid_x; grid_x <= max_grid_x; ++grid_x) {
                    visitor(grid_x, grid_y, grid_z);
                }
            }
        }
    };

    const std::size_t edge_count = view.edge_count > 0 ? static_cast<std::size_t>(view.edge_count) : 0;
    const std::size_t triangle_count = view.triangle_count > 0 ? static_cast<std::size_t>(view.triangle_count) : 0;
    std::vector<PrimitiveBounds> edge_bounds(edge_count);
    std::vector<PrimitiveBounds> triangle_bounds(triangle_count);
    std::unordered_map<GridCell, std::vector<std::int32_t>, GridCellHash> edge_cells;
    std::unordered_map<GridCell, std::vector<std::int32_t>, GridCellHash> triangle_cells;
    float max_primitive_size = broadphase_thickness;

    if (view.edges != nullptr && view.edge_count > 0) {
        for (std::int64_t edge_index = 0; edge_index < view.edge_count; ++edge_index) {
            const std::int32_t a = view.edges[edge_index * 2 + 0];
            const std::int32_t b = view.edges[edge_index * 2 + 1];
            if (a < 0 || b < 0 || static_cast<std::int64_t>(a) >= view.vertex_count ||
                static_cast<std::int64_t>(b) >= view.vertex_count || a == b) {
                continue;
            }
            if ((view.attributes[a] & kMc2AttrInvalid) != 0 || (view.attributes[b] & kMc2AttrInvalid) != 0) {
                continue;
            }
            if (!partition_enabled(partitioned ? view.particle_partition_index[a] : 0u)) continue;
            const std::int32_t edge_vertices[] = {a, b};
            const float primitive_thickness = primitive_side_thickness(edge_vertices, 2);
            const std::int64_t ao = static_cast<std::int64_t>(a) * 3;
            const std::int64_t bo = static_cast<std::int64_t>(b) * 3;
            const float cur_a_x = view.positions[ao + 0];
            const float cur_a_y = view.positions[ao + 1];
            const float cur_a_z = view.positions[ao + 2];
            const float cur_b_x = view.positions[bo + 0];
            const float cur_b_y = view.positions[bo + 1];
            const float cur_b_z = view.positions[bo + 2];
            const float old_a_x = view.old_positions[ao + 0];
            const float old_a_y = view.old_positions[ao + 1];
            const float old_a_z = view.old_positions[ao + 2];
            const float old_b_x = view.old_positions[bo + 0];
            const float old_b_y = view.old_positions[bo + 1];
            const float old_b_z = view.old_positions[bo + 2];
            const float size = std::max(length3(cur_b_x - cur_a_x, cur_b_y - cur_a_y, cur_b_z - cur_a_z),
                                        length3(old_b_x - old_a_x, old_b_y - old_a_y, old_b_z - old_a_z));
            max_primitive_size = std::max(max_primitive_size, size);
            PrimitiveBounds bounds;
            bounds.min_x = std::min(std::min(cur_a_x, cur_b_x), std::min(old_a_x, old_b_x)) - primitive_thickness;
            bounds.min_y = std::min(std::min(cur_a_y, cur_b_y), std::min(old_a_y, old_b_y)) - primitive_thickness;
            bounds.min_z = std::min(std::min(cur_a_z, cur_b_z), std::min(old_a_z, old_b_z)) - primitive_thickness;
            bounds.max_x = std::max(std::max(cur_a_x, cur_b_x), std::max(old_a_x, old_b_x)) + primitive_thickness;
            bounds.max_y = std::max(std::max(cur_a_y, cur_b_y), std::max(old_a_y, old_b_y)) + primitive_thickness;
            bounds.max_z = std::max(std::max(cur_a_z, cur_b_z), std::max(old_a_z, old_b_z)) + primitive_thickness;
            bounds.valid = true;
            edge_bounds[static_cast<std::size_t>(edge_index)] = bounds;
        }
    }

    if (view.triangles != nullptr && view.triangle_count > 0) {
        for (std::int64_t tri_index = 0; tri_index < view.triangle_count; ++tri_index) {
            const std::int32_t a = view.triangles[tri_index * 3 + 0];
            const std::int32_t b = view.triangles[tri_index * 3 + 1];
            const std::int32_t c = view.triangles[tri_index * 3 + 2];
            if (a < 0 || b < 0 || c < 0 || static_cast<std::int64_t>(a) >= view.vertex_count ||
                static_cast<std::int64_t>(b) >= view.vertex_count || static_cast<std::int64_t>(c) >= view.vertex_count) {
                continue;
            }
            if ((view.attributes[a] & kMc2AttrInvalid) != 0 || (view.attributes[b] & kMc2AttrInvalid) != 0 ||
                (view.attributes[c] & kMc2AttrInvalid) != 0) {
                continue;
            }
            if (!partition_enabled(partitioned ? view.particle_partition_index[a] : 0u)) continue;
            const std::int32_t triangle_vertices[] = {a, b, c};
            const float primitive_thickness = primitive_side_thickness(triangle_vertices, 3);
            const std::int64_t ao = static_cast<std::int64_t>(a) * 3;
            const std::int64_t bo = static_cast<std::int64_t>(b) * 3;
            const std::int64_t co = static_cast<std::int64_t>(c) * 3;
            const float cur_a_x = view.positions[ao + 0];
            const float cur_a_y = view.positions[ao + 1];
            const float cur_a_z = view.positions[ao + 2];
            const float cur_b_x = view.positions[bo + 0];
            const float cur_b_y = view.positions[bo + 1];
            const float cur_b_z = view.positions[bo + 2];
            const float cur_c_x = view.positions[co + 0];
            const float cur_c_y = view.positions[co + 1];
            const float cur_c_z = view.positions[co + 2];
            const float old_a_x = view.old_positions[ao + 0];
            const float old_a_y = view.old_positions[ao + 1];
            const float old_a_z = view.old_positions[ao + 2];
            const float old_b_x = view.old_positions[bo + 0];
            const float old_b_y = view.old_positions[bo + 1];
            const float old_b_z = view.old_positions[bo + 2];
            const float old_c_x = view.old_positions[co + 0];
            const float old_c_y = view.old_positions[co + 1];
            const float old_c_z = view.old_positions[co + 2];
            const float size = std::max(
                std::max(length3(cur_b_x - cur_a_x, cur_b_y - cur_a_y, cur_b_z - cur_a_z),
                         length3(cur_c_x - cur_a_x, cur_c_y - cur_a_y, cur_c_z - cur_a_z)),
                std::max(length3(cur_c_x - cur_b_x, cur_c_y - cur_b_y, cur_c_z - cur_b_z),
                         std::max(length3(old_b_x - old_a_x, old_b_y - old_a_y, old_b_z - old_a_z),
                                  std::max(length3(old_c_x - old_a_x, old_c_y - old_a_y, old_c_z - old_a_z),
                                           length3(old_c_x - old_b_x, old_c_y - old_b_y, old_c_z - old_b_z)))));
            max_primitive_size = std::max(max_primitive_size, size);
            PrimitiveBounds bounds;
            bounds.min_x = std::min(std::min(std::min(cur_a_x, cur_b_x), cur_c_x), std::min(std::min(old_a_x, old_b_x), old_c_x)) - primitive_thickness;
            bounds.min_y = std::min(std::min(std::min(cur_a_y, cur_b_y), cur_c_y), std::min(std::min(old_a_y, old_b_y), old_c_y)) - primitive_thickness;
            bounds.min_z = std::min(std::min(std::min(cur_a_z, cur_b_z), cur_c_z), std::min(std::min(old_a_z, old_b_z), old_c_z)) - primitive_thickness;
            bounds.max_x = std::max(std::max(std::max(cur_a_x, cur_b_x), cur_c_x), std::max(std::max(old_a_x, old_b_x), old_c_x)) + primitive_thickness;
            bounds.max_y = std::max(std::max(std::max(cur_a_y, cur_b_y), cur_c_y), std::max(std::max(old_a_y, old_b_y), old_c_y)) + primitive_thickness;
            bounds.max_z = std::max(std::max(std::max(cur_a_z, cur_b_z), cur_c_z), std::max(std::max(old_a_z, old_b_z), old_c_z)) + primitive_thickness;
            bounds.valid = true;
            triangle_bounds[static_cast<std::size_t>(tri_index)] = bounds;
        }
    }

    float cell_size = max_primitive_size * kSelfCollisionGridScale;
    cell_size = std::max(cell_size, broadphase_thickness);
    cell_size = std::max(cell_size, kMc2Epsilon);

    for (std::int64_t edge_index = 0; edge_index < view.edge_count; ++edge_index) {
        const PrimitiveBounds& bounds = edge_bounds[static_cast<std::size_t>(edge_index)];
        if (!bounds.valid) {
            continue;
        }
        for_grid_cells(
            bounds.min_x, bounds.min_y, bounds.min_z,
            bounds.max_x, bounds.max_y, bounds.max_z, cell_size,
            [&](std::int64_t grid_x, std::int64_t grid_y, std::int64_t grid_z) {
                edge_cells[GridCell{grid_x, grid_y, grid_z}].push_back(
                    static_cast<std::int32_t>(edge_index)
                );
            }
        );
    }

    for (std::int64_t tri_index = 0; tri_index < view.triangle_count; ++tri_index) {
        const PrimitiveBounds& bounds = triangle_bounds[static_cast<std::size_t>(tri_index)];
        if (!bounds.valid) {
            continue;
        }
        for_grid_cells(
            bounds.min_x, bounds.min_y, bounds.min_z,
            bounds.max_x, bounds.max_y, bounds.max_z, cell_size,
            [&](std::int64_t grid_x, std::int64_t grid_y, std::int64_t grid_z) {
                triangle_cells[GridCell{grid_x, grid_y, grid_z}].push_back(
                    static_cast<std::int32_t>(tri_index)
                );
            }
        );
    }

    std::vector<SelfContact> contacts;
    contacts.reserve(static_cast<std::size_t>(view.vertex_count + view.edge_count));

    if (view.triangles != nullptr && view.triangle_count > 0) {
        std::unordered_set<std::int32_t> candidate_triangles;
        candidate_triangles.reserve(64);
        const bool has_explicit_points = view.point_count >= 0;
        if (has_explicit_points && view.point_count > 0 && view.points == nullptr) {
            return;
        }
        const std::int64_t point_count = has_explicit_points
            ? view.point_count : view.vertex_count;
        for (std::int64_t point_record = 0; point_record < point_count; ++point_record) {
            const std::int64_t point = has_explicit_points
                ? static_cast<std::int64_t>(view.points[point_record]) : point_record;
            if (point < 0 || point >= view.vertex_count) continue;
            if ((view.attributes[point] & kMc2AttrInvalid) != 0) {
                continue;
            }
            if (!partition_enabled(partitioned ? view.particle_partition_index[point] : 0u)) continue;
            const std::int64_t po = point * 3;
            candidate_triangles.clear();
            const float point_thickness = particle_side_thickness(static_cast<std::int32_t>(point));
            const float point_min_x = std::min(view.positions[po + 0], view.old_positions[po + 0]) - point_thickness;
            const float point_min_y = std::min(view.positions[po + 1], view.old_positions[po + 1]) - point_thickness;
            const float point_min_z = std::min(view.positions[po + 2], view.old_positions[po + 2]) - point_thickness;
            const float point_max_x = std::max(view.positions[po + 0], view.old_positions[po + 0]) + point_thickness;
            const float point_max_y = std::max(view.positions[po + 1], view.old_positions[po + 1]) + point_thickness;
            const float point_max_z = std::max(view.positions[po + 2], view.old_positions[po + 2]) + point_thickness;
            const PrimitiveBounds point_bounds {
                point_min_x, point_min_y, point_min_z,
                point_max_x, point_max_y, point_max_z,
                true,
            };
            for_grid_cells(point_min_x, point_min_y, point_min_z, point_max_x, point_max_y, point_max_z, cell_size,
                           [&](std::int64_t grid_x, std::int64_t grid_y, std::int64_t grid_z) {
                               const auto found = triangle_cells.find(GridCell{grid_x, grid_y, grid_z});
                               if (found == triangle_cells.end()) {
                                   return;
                               }
                               candidate_triangles.insert(found->second.begin(), found->second.end());
                           });
            if (candidate_triangles.empty()) {
                continue;
            }
            for (const std::int32_t tri_index_value : candidate_triangles) {
                const std::int64_t tri_index = static_cast<std::int64_t>(tri_index_value);
                const std::int32_t ta = view.triangles[tri_index * 3 + 0];
                const std::int32_t tb = view.triangles[tri_index * 3 + 1];
                const std::int32_t tc = view.triangles[tri_index * 3 + 2];
                if (ta < 0 || tb < 0 || tc < 0 || static_cast<std::int64_t>(ta) >= view.vertex_count ||
                    static_cast<std::int64_t>(tb) >= view.vertex_count ||
                    static_cast<std::int64_t>(tc) >= view.vertex_count || point == ta || point == tb || point == tc) {
                    continue;
                }
                if ((view.attributes[ta] & kMc2AttrInvalid) != 0 || (view.attributes[tb] & kMc2AttrInvalid) != 0 ||
                    (view.attributes[tc] & kMc2AttrInvalid) != 0) {
                    continue;
                }
                if (!owner_pair_allowed(static_cast<std::int32_t>(point), ta)) continue;
                if (topology_neighbors(static_cast<std::int32_t>(point), ta) ||
                    topology_neighbors(static_cast<std::int32_t>(point), tb) ||
                    topology_neighbors(static_cast<std::int32_t>(point), tc)) {
                    continue;
                }
                if (!bounds_overlap(
                        point_bounds,
                        triangle_bounds[static_cast<std::size_t>(tri_index)]
                    )) {
                    continue;
                }
                if (view.candidate_count != nullptr) ++*view.candidate_count;
                const std::int32_t triangle_vertices[] = {ta, tb, tc};
                const float contact_thickness = view.particle_thickness == nullptr
                    ? view.surface_thickness
                    : point_thickness + primitive_side_thickness(triangle_vertices, 3);
                if (contact_thickness <= kMc2Epsilon) continue;
                const std::int64_t ao = static_cast<std::int64_t>(ta) * 3;
                const std::int64_t bo = static_cast<std::int64_t>(tb) * 3;
                const std::int64_t co = static_cast<std::int64_t>(tc) * 3;

                float closest[3] = {};
                float u = 0.0f;
                float v = 0.0f;
                float w = 0.0f;
                closest_point_triangle(view.old_positions[po + 0], view.old_positions[po + 1], view.old_positions[po + 2],
                                       view.old_positions[ao + 0], view.old_positions[ao + 1], view.old_positions[ao + 2],
                                       view.old_positions[bo + 0], view.old_positions[bo + 1], view.old_positions[bo + 2],
                                       view.old_positions[co + 0], view.old_positions[co + 1], view.old_positions[co + 2],
                                       closest[0], closest[1], closest[2], u, v, w);
                const float dx = closest[0] - view.old_positions[po + 0];
                const float dy = closest[1] - view.old_positions[po + 1];
                const float dz = closest[2] - view.old_positions[po + 2];
                const float delta_len = length3(dx, dy, dz);
                if (delta_len <= kMc2Epsilon) {
                    continue;
                }

                float old_nx = 0.0f;
                float old_ny = 0.0f;
                float old_nz = 1.0f;
                triangle_normal(view.old_positions[ao + 0], view.old_positions[ao + 1], view.old_positions[ao + 2],
                                view.old_positions[bo + 0], view.old_positions[bo + 1], view.old_positions[bo + 2],
                                view.old_positions[co + 0], view.old_positions[co + 1], view.old_positions[co + 2],
                                old_nx, old_ny, old_nz);
                float dir_x = view.old_positions[po + 0] - closest[0];
                float dir_y = view.old_positions[po + 1] - closest[1];
                float dir_z = view.old_positions[po + 2] - closest[2];
                safe_normal_with_fallback(dir_x, dir_y, dir_z, old_nx, old_ny, old_nz, dir_x, dir_y, dir_z);
                const float dot = dot3(old_nx, old_ny, old_nz, dir_x, dir_y, dir_z);
                if (std::fabs(dot) < kSelfCollisionPointTriangleAngleCos) {
                    continue;
                }
                const float sign = dot >= 0.0f ? 1.0f : -1.0f;
                const float nx = old_nx * sign;
                const float ny = old_ny * sign;
                const float nz = old_nz * sign;

                const float dpx = view.positions[po + 0] - view.old_positions[po + 0];
                const float dpy = view.positions[po + 1] - view.old_positions[po + 1];
                const float dpz = view.positions[po + 2] - view.old_positions[po + 2];
                const float dtx = (view.positions[ao + 0] - view.old_positions[ao + 0]) * u +
                                  (view.positions[bo + 0] - view.old_positions[bo + 0]) * v +
                                  (view.positions[co + 0] - view.old_positions[co + 0]) * w;
                const float dty = (view.positions[ao + 1] - view.old_positions[ao + 1]) * u +
                                  (view.positions[bo + 1] - view.old_positions[bo + 1]) * v +
                                  (view.positions[co + 1] - view.old_positions[co + 1]) * w;
                const float dtz = (view.positions[ao + 2] - view.old_positions[ao + 2]) * u +
                                  (view.positions[bo + 2] - view.old_positions[bo + 2]) * v +
                                  (view.positions[co + 2] - view.old_positions[co + 2]) * w;
                const float current_dist = delta_len - dot3(nx, ny, nz, dpx, dpy, dpz) + dot3(nx, ny, nz, dtx, dty, dtz);
                if (current_dist >= contact_thickness + contact_thickness * kSelfCollisionScr) {
                    continue;
                }

                const float tri_x = view.positions[ao + 0] * u + view.positions[bo + 0] * v + view.positions[co + 0] * w;
                const float tri_y = view.positions[ao + 1] * u + view.positions[bo + 1] * v + view.positions[co + 1] * w;
                const float tri_z = view.positions[ao + 2] * u + view.positions[bo + 2] * v + view.positions[co + 2] * w;
                const float signed_dist = dot3(nx, ny, nz, view.positions[po + 0] - tri_x, view.positions[po + 1] - tri_y,
                                               view.positions[po + 2] - tri_z);
                if (signed_dist >= contact_thickness) {
                    continue;
                }
                const float denom = view.inv_masses[point] + view.inv_masses[ta] * u * u + view.inv_masses[tb] * v * v +
                                    view.inv_masses[tc] * w * w;
                if (denom <= kMc2Epsilon) {
                    continue;
                }
                SelfContact contact;
                contact.type = 1;
                contact.v[0] = static_cast<std::int32_t>(point);
                contact.v[1] = ta;
                contact.v[2] = tb;
                contact.v[3] = tc;
                contact.a = u;
                contact.b = v;
                contact.c = w;
                contact.thickness = contact_thickness;
                contact.normal[0] = nx;
                contact.normal[1] = ny;
                contact.normal[2] = nz;
                contacts.push_back(contact);
            }
        }
    }

    if (view.edges != nullptr && view.edge_count > 1) {
        std::unordered_set<std::int32_t> candidate_edges;
        candidate_edges.reserve(64);
        for (std::int64_t edge_a = 0; edge_a < view.edge_count; ++edge_a) {
            const PrimitiveBounds& bounds = edge_bounds[static_cast<std::size_t>(edge_a)];
            if (!bounds.valid) {
                continue;
            }
            candidate_edges.clear();
            for_grid_cells(bounds.min_x, bounds.min_y, bounds.min_z, bounds.max_x, bounds.max_y, bounds.max_z, cell_size,
                           [&](std::int64_t grid_x, std::int64_t grid_y, std::int64_t grid_z) {
                               const auto found = edge_cells.find(GridCell{grid_x, grid_y, grid_z});
                               if (found == edge_cells.end()) {
                                   return;
                               }
                               candidate_edges.insert(found->second.begin(), found->second.end());
                           });
            if (candidate_edges.empty()) {
                continue;
            }
            const std::int32_t a0 = view.edges[edge_a * 2 + 0];
            const std::int32_t a1 = view.edges[edge_a * 2 + 1];
            if (a0 < 0 || a1 < 0 || static_cast<std::int64_t>(a0) >= view.vertex_count ||
                static_cast<std::int64_t>(a1) >= view.vertex_count || a0 == a1) {
                continue;
            }
            if ((view.attributes[a0] & kMc2AttrInvalid) != 0 || (view.attributes[a1] & kMc2AttrInvalid) != 0) {
                continue;
            }
            const std::int64_t a0o = static_cast<std::int64_t>(a0) * 3;
            const std::int64_t a1o = static_cast<std::int64_t>(a1) * 3;
            for (const std::int32_t edge_b_value : candidate_edges) {
                const std::int64_t edge_b = static_cast<std::int64_t>(edge_b_value);
                if (edge_b <= edge_a) {
                    continue;
                }
                const std::int32_t b0 = view.edges[edge_b * 2 + 0];
                const std::int32_t b1 = view.edges[edge_b * 2 + 1];
                if (b0 < 0 || b1 < 0 || static_cast<std::int64_t>(b0) >= view.vertex_count ||
                    static_cast<std::int64_t>(b1) >= view.vertex_count || b0 == b1 || a0 == b0 || a0 == b1 ||
                    a1 == b0 || a1 == b1) {
                    continue;
                }
                if ((view.attributes[b0] & kMc2AttrInvalid) != 0 || (view.attributes[b1] & kMc2AttrInvalid) != 0) {
                    continue;
                }
                if (!owner_pair_allowed(a0, b0)) continue;
                if (topology_neighbors(a0, b0) || topology_neighbors(a0, b1) ||
                    topology_neighbors(a1, b0) || topology_neighbors(a1, b1)) {
                    continue;
                }
                if (!bounds_overlap(
                        bounds,
                        edge_bounds[static_cast<std::size_t>(edge_b)]
                    )) {
                    continue;
                }
                if (view.candidate_count != nullptr) ++*view.candidate_count;
                const std::int32_t edge_a_vertices[] = {a0, a1};
                const std::int32_t edge_b_vertices[] = {b0, b1};
                const float contact_thickness = view.particle_thickness == nullptr
                    ? view.surface_thickness
                    : primitive_side_thickness(edge_a_vertices, 2) +
                      primitive_side_thickness(edge_b_vertices, 2);
                if (contact_thickness <= kMc2Epsilon) continue;
                const std::int64_t b0o = static_cast<std::int64_t>(b0) * 3;
                const std::int64_t b1o = static_cast<std::int64_t>(b1) * 3;
                float s = 0.0f;
                float t = 0.0f;
                float ca[3] = {};
                float cb[3] = {};
                const float dist_sq = closest_segment_segment(
                    view.old_positions[a0o + 0], view.old_positions[a0o + 1], view.old_positions[a0o + 2],
                    view.old_positions[a1o + 0], view.old_positions[a1o + 1], view.old_positions[a1o + 2],
                    view.old_positions[b0o + 0], view.old_positions[b0o + 1], view.old_positions[b0o + 2],
                    view.old_positions[b1o + 0], view.old_positions[b1o + 1], view.old_positions[b1o + 2],
                    s, t, ca[0], ca[1], ca[2], cb[0], cb[1], cb[2]);
                const float dist = std::sqrt(std::max(dist_sq, 0.0f));
                if (dist <= kMc2Epsilon) {
                    continue;
                }
                const float nx = (ca[0] - cb[0]) / dist;
                const float ny = (ca[1] - cb[1]) / dist;
                const float nz = (ca[2] - cb[2]) / dist;
                const float da_x = (view.positions[a0o + 0] - view.old_positions[a0o + 0]) * (1.0f - s) +
                                   (view.positions[a1o + 0] - view.old_positions[a1o + 0]) * s;
                const float da_y = (view.positions[a0o + 1] - view.old_positions[a0o + 1]) * (1.0f - s) +
                                   (view.positions[a1o + 1] - view.old_positions[a1o + 1]) * s;
                const float da_z = (view.positions[a0o + 2] - view.old_positions[a0o + 2]) * (1.0f - s) +
                                   (view.positions[a1o + 2] - view.old_positions[a1o + 2]) * s;
                const float db_x = (view.positions[b0o + 0] - view.old_positions[b0o + 0]) * (1.0f - t) +
                                   (view.positions[b1o + 0] - view.old_positions[b1o + 0]) * t;
                const float db_y = (view.positions[b0o + 1] - view.old_positions[b0o + 1]) * (1.0f - t) +
                                   (view.positions[b1o + 1] - view.old_positions[b1o + 1]) * t;
                const float db_z = (view.positions[b0o + 2] - view.old_positions[b0o + 2]) * (1.0f - t) +
                                   (view.positions[b1o + 2] - view.old_positions[b1o + 2]) * t;
                const float movement_adjusted = dist + dot3(nx, ny, nz, da_x, da_y, da_z) - dot3(nx, ny, nz, db_x, db_y, db_z);
                if (movement_adjusted > contact_thickness + contact_thickness * kSelfCollisionScr) {
                    continue;
                }
                const float cur_ax = view.positions[a0o + 0] * (1.0f - s) + view.positions[a1o + 0] * s;
                const float cur_ay = view.positions[a0o + 1] * (1.0f - s) + view.positions[a1o + 1] * s;
                const float cur_az = view.positions[a0o + 2] * (1.0f - s) + view.positions[a1o + 2] * s;
                const float cur_bx = view.positions[b0o + 0] * (1.0f - t) + view.positions[b1o + 0] * t;
                const float cur_by = view.positions[b0o + 1] * (1.0f - t) + view.positions[b1o + 1] * t;
                const float cur_bz = view.positions[b0o + 2] * (1.0f - t) + view.positions[b1o + 2] * t;
                const float current_dist = dot3(nx, ny, nz, cur_ax - cur_bx, cur_ay - cur_by, cur_az - cur_bz);
                if (current_dist >= contact_thickness) {
                    continue;
                }
                const float b0w = 1.0f - s;
                const float b1w = s;
                const float b2w = 1.0f - t;
                const float b3w = t;
                const float denom = view.inv_masses[a0] * b0w * b0w + view.inv_masses[a1] * b1w * b1w +
                                    view.inv_masses[b0] * b2w * b2w + view.inv_masses[b1] * b3w * b3w;
                if (denom <= kMc2Epsilon) {
                    continue;
                }
                SelfContact contact;
                contact.type = 2;
                contact.v[0] = a0;
                contact.v[1] = a1;
                contact.v[2] = b0;
                contact.v[3] = b1;
                contact.a = s;
                contact.b = t;
                contact.thickness = contact_thickness;
                contact.normal[0] = nx;
                contact.normal[1] = ny;
                contact.normal[2] = nz;
                contacts.push_back(contact);
            }
        }
    }

    if (contacts.empty()) {
        return;
    }
    if (view.contact_count != nullptr) {
        *view.contact_count = static_cast<std::int64_t>(contacts.size());
    }

    std::vector<float> add_positions(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<float> add_normals(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<std::int32_t> add_counts(static_cast<std::size_t>(view.vertex_count), 0);
    std::vector<float> normal_totals(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<std::int32_t> normal_counts(static_cast<std::size_t>(view.vertex_count), 0);
    std::vector<float> friction_values(static_cast<std::size_t>(view.vertex_count), 0.0f);

    for (int iteration = 0; iteration < kSelfCollisionSolverIteration; ++iteration) {
        std::fill(add_positions.begin(), add_positions.end(), 0.0f);
        std::fill(add_normals.begin(), add_normals.end(), 0.0f);
        std::fill(add_counts.begin(), add_counts.end(), 0);
        std::fill(friction_values.begin(), friction_values.end(), 0.0f);

        for (const SelfContact& contact : contacts) {
            const float thickness = contact.thickness;
            if (contact.type == 1) {
                const std::int32_t point = contact.v[0];
                const std::int32_t ta = contact.v[1];
                const std::int32_t tb = contact.v[2];
                const std::int32_t tc = contact.v[3];
                const float u = contact.a;
                const float v = contact.b;
                const float w = contact.c;
                const std::int64_t po = static_cast<std::int64_t>(point) * 3;
                const std::int64_t ao = static_cast<std::int64_t>(ta) * 3;
                const std::int64_t bo = static_cast<std::int64_t>(tb) * 3;
                const std::int64_t co = static_cast<std::int64_t>(tc) * 3;
                float nx = 0.0f;
                float ny = 0.0f;
                float nz = 1.0f;
                triangle_normal(view.positions[ao + 0], view.positions[ao + 1], view.positions[ao + 2],
                                view.positions[bo + 0], view.positions[bo + 1], view.positions[bo + 2],
                                view.positions[co + 0], view.positions[co + 1], view.positions[co + 2], nx, ny, nz);
                const float sign = dot3(nx, ny, nz, contact.normal[0], contact.normal[1], contact.normal[2]) >= 0.0f ? 1.0f : -1.0f;
                nx *= sign;
                ny *= sign;
                nz *= sign;
                const float tri_x = view.positions[ao + 0] * u + view.positions[bo + 0] * v + view.positions[co + 0] * w;
                const float tri_y = view.positions[ao + 1] * u + view.positions[bo + 1] * v + view.positions[co + 1] * w;
                const float tri_z = view.positions[ao + 2] * u + view.positions[bo + 2] * v + view.positions[co + 2] * w;
                const float current_dist = dot3(nx, ny, nz, view.positions[po + 0] - tri_x, view.positions[po + 1] - tri_y,
                                                view.positions[po + 2] - tri_z);
                if (current_dist >= thickness) {
                    continue;
                }
                const float denom = view.inv_masses[point] + view.inv_masses[ta] * u * u + view.inv_masses[tb] * v * v +
                                    view.inv_masses[tc] * w * w;
                if (denom <= kMc2Epsilon) {
                    continue;
                }
                const float lambda = (thickness - current_dist) / denom;
                const float friction_value = 1.0f - clamp_float(current_dist / std::max(thickness, kMc2Epsilon), 0.0f, 1.0f);
                auto add_vertex = [&](std::int32_t vertex, float scale, float normal_sign) {
                    if (view.inv_masses[vertex] <= kMc2Epsilon || (view.attributes[vertex] & kMc2AttrMove) == 0) {
                        return;
                    }
                    const std::int64_t offset = static_cast<std::int64_t>(vertex) * 3;
                    add_positions[offset + 0] += nx * scale;
                    add_positions[offset + 1] += ny * scale;
                    add_positions[offset + 2] += nz * scale;
                    add_normals[offset + 0] += nx * normal_sign;
                    add_normals[offset + 1] += ny * normal_sign;
                    add_normals[offset + 2] += nz * normal_sign;
                    ++add_counts[vertex];
                    friction_values[vertex] = std::max(friction_values[vertex], friction_value);
                };
                add_vertex(point, lambda * view.inv_masses[point], 1.0f);
                add_vertex(ta, -lambda * view.inv_masses[ta] * u, -1.0f);
                add_vertex(tb, -lambda * view.inv_masses[tb] * v, -1.0f);
                add_vertex(tc, -lambda * view.inv_masses[tc] * w, -1.0f);
            } else if (contact.type == 2) {
                const std::int32_t a0 = contact.v[0];
                const std::int32_t a1 = contact.v[1];
                const std::int32_t b0 = contact.v[2];
                const std::int32_t b1 = contact.v[3];
                const float s = contact.a;
                const float t = contact.b;
                const float nx = contact.normal[0];
                const float ny = contact.normal[1];
                const float nz = contact.normal[2];
                const std::int64_t a0o = static_cast<std::int64_t>(a0) * 3;
                const std::int64_t a1o = static_cast<std::int64_t>(a1) * 3;
                const std::int64_t b0o = static_cast<std::int64_t>(b0) * 3;
                const std::int64_t b1o = static_cast<std::int64_t>(b1) * 3;
                const float cur_ax = view.positions[a0o + 0] * (1.0f - s) + view.positions[a1o + 0] * s;
                const float cur_ay = view.positions[a0o + 1] * (1.0f - s) + view.positions[a1o + 1] * s;
                const float cur_az = view.positions[a0o + 2] * (1.0f - s) + view.positions[a1o + 2] * s;
                const float cur_bx = view.positions[b0o + 0] * (1.0f - t) + view.positions[b1o + 0] * t;
                const float cur_by = view.positions[b0o + 1] * (1.0f - t) + view.positions[b1o + 1] * t;
                const float cur_bz = view.positions[b0o + 2] * (1.0f - t) + view.positions[b1o + 2] * t;
                const float current_dist = dot3(nx, ny, nz, cur_ax - cur_bx, cur_ay - cur_by, cur_az - cur_bz);
                if (current_dist >= thickness) {
                    continue;
                }
                const float b0w = 1.0f - s;
                const float b1w = s;
                const float b2w = 1.0f - t;
                const float b3w = t;
                const float denom = view.inv_masses[a0] * b0w * b0w + view.inv_masses[a1] * b1w * b1w +
                                    view.inv_masses[b0] * b2w * b2w + view.inv_masses[b1] * b3w * b3w;
                if (denom <= kMc2Epsilon) {
                    continue;
                }
                const float lambda = (thickness - current_dist) / denom;
                const float friction_value = 1.0f - clamp_float(current_dist / std::max(thickness, kMc2Epsilon), 0.0f, 1.0f);
                auto add_vertex = [&](std::int32_t vertex, float scale, float normal_sign) {
                    if (view.inv_masses[vertex] <= kMc2Epsilon || (view.attributes[vertex] & kMc2AttrMove) == 0) {
                        return;
                    }
                    const std::int64_t offset = static_cast<std::int64_t>(vertex) * 3;
                    add_positions[offset + 0] += nx * scale;
                    add_positions[offset + 1] += ny * scale;
                    add_positions[offset + 2] += nz * scale;
                    add_normals[offset + 0] += nx * normal_sign;
                    add_normals[offset + 1] += ny * normal_sign;
                    add_normals[offset + 2] += nz * normal_sign;
                    ++add_counts[vertex];
                    friction_values[vertex] = std::max(friction_values[vertex], friction_value);
                };
                add_vertex(a0, lambda * view.inv_masses[a0] * b0w, 1.0f);
                add_vertex(a1, lambda * view.inv_masses[a1] * b1w, 1.0f);
                add_vertex(b0, -lambda * view.inv_masses[b0] * b2w, -1.0f);
                add_vertex(b1, -lambda * view.inv_masses[b1] * b3w, -1.0f);
            }
        }

        for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
            const int count = add_counts[vertex];
            if (count <= 0) {
                continue;
            }
            const std::int64_t offset = vertex * 3;
            const float inv_count = 1.0f / static_cast<float>(count);
            view.positions[offset + 0] += add_positions[offset + 0] * inv_count;
            view.positions[offset + 1] += add_positions[offset + 1] * inv_count;
            view.positions[offset + 2] += add_positions[offset + 2] * inv_count;
            normal_totals[offset + 0] += add_normals[offset + 0] * inv_count;
            normal_totals[offset + 1] += add_normals[offset + 1] * inv_count;
            normal_totals[offset + 2] += add_normals[offset + 2] * inv_count;
            ++normal_counts[vertex];
            if (view.friction != nullptr && friction_values[vertex] > view.friction[vertex]) {
                view.friction[vertex] = friction_values[vertex];
            }
        }
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const int count = normal_counts[vertex];
        if (count <= 0) {
            continue;
        }
        const std::int64_t offset = vertex * 3;
        const float inv_count = 1.0f / static_cast<float>(count);
        float nx = normal_totals[offset + 0] * inv_count;
        float ny = normal_totals[offset + 1] * inv_count;
        float nz = normal_totals[offset + 2] * inv_count;
        const float len = length3(nx, ny, nz);
        if (len <= kMc2Epsilon) {
            continue;
        }
        const float inv_len = 1.0f / len;
        view.collision_normals[offset + 0] += nx * inv_len;
        view.collision_normals[offset + 1] += ny * inv_len;
        view.collision_normals[offset + 2] += nz * inv_len;
    }
}

}  // namespace hotools
