#include "hotools_mc2.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
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
    float normal[3] = {};
};

}  // namespace

void project_self_collisions_mc2(Mc2SelfCollisionView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.old_positions == nullptr ||
        view.inv_masses == nullptr || view.attributes == nullptr || view.collision_normals == nullptr ||
        view.surface_thickness <= kMc2Epsilon || (view.edge_count <= 0 && view.triangle_count <= 0)) {
        return;
    }

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

    const float thickness = std::max(view.surface_thickness, 0.0f);
    std::vector<SelfContact> contacts;
    contacts.reserve(static_cast<std::size_t>(view.vertex_count + view.edge_count));

    if (view.triangles != nullptr && view.triangle_count > 0) {
        for (std::int64_t point = 0; point < view.vertex_count; ++point) {
            if ((view.attributes[point] & kMc2AttrInvalid) != 0) {
                continue;
            }
            const std::int64_t po = point * 3;
            for (std::int64_t tri_index = 0; tri_index < view.triangle_count; ++tri_index) {
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
                if (current_dist >= thickness + thickness * kSelfCollisionScr) {
                    continue;
                }

                const float tri_x = view.positions[ao + 0] * u + view.positions[bo + 0] * v + view.positions[co + 0] * w;
                const float tri_y = view.positions[ao + 1] * u + view.positions[bo + 1] * v + view.positions[co + 1] * w;
                const float tri_z = view.positions[ao + 2] * u + view.positions[bo + 2] * v + view.positions[co + 2] * w;
                const float signed_dist = dot3(nx, ny, nz, view.positions[po + 0] - tri_x, view.positions[po + 1] - tri_y,
                                               view.positions[po + 2] - tri_z);
                if (signed_dist >= thickness) {
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
                contact.normal[0] = nx;
                contact.normal[1] = ny;
                contact.normal[2] = nz;
                contacts.push_back(contact);
            }
        }
    }

    if (view.edges != nullptr && view.edge_count > 1) {
        for (std::int64_t edge_a = 0; edge_a < view.edge_count; ++edge_a) {
            const std::int32_t a0 = view.edges[edge_a * 2 + 0];
            const std::int32_t a1 = view.edges[edge_a * 2 + 1];
            if (a0 < 0 || a1 < 0 || static_cast<std::int64_t>(a0) >= view.vertex_count ||
                static_cast<std::int64_t>(a1) >= view.vertex_count || a0 == a1) {
                continue;
            }
            if ((view.attributes[a0] & kMc2AttrInvalid) != 0 || (view.attributes[a1] & kMc2AttrInvalid) != 0) {
                continue;
            }
            for (std::int64_t edge_b = edge_a + 1; edge_b < view.edge_count; ++edge_b) {
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
                const std::int64_t a0o = static_cast<std::int64_t>(a0) * 3;
                const std::int64_t a1o = static_cast<std::int64_t>(a1) * 3;
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
                if (movement_adjusted > thickness + thickness * kSelfCollisionScr) {
                    continue;
                }
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
                SelfContact contact;
                contact.type = 2;
                contact.v[0] = a0;
                contact.v[1] = a1;
                contact.v[2] = b0;
                contact.v[3] = b1;
                contact.a = s;
                contact.b = t;
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
