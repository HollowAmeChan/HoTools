#include "hotools_spring_bone_vrm.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace hotools {
namespace {

constexpr float kEpsilon = 0.000001f;
constexpr int kColliderSphere = 0;
constexpr int kColliderCapsule = 1;
constexpr int kColliderPlane = 2;
constexpr int kColliderBox = 3;

float clamp_float(float value, float lo, float hi) {
    return std::max(lo, std::min(hi, value));
}

float dot3(float ax, float ay, float az, float bx, float by, float bz) {
    return ax * bx + ay * by + az * bz;
}

void cross3(float ax, float ay, float az, float bx, float by, float bz, float& out_x, float& out_y, float& out_z) {
    out_x = ay * bz - az * by;
    out_y = az * bx - ax * bz;
    out_z = ax * by - ay * bx;
}

float length3(float x, float y, float z) {
    return std::sqrt(x * x + y * y + z * z);
}

void safe_normal_or_z(float x, float y, float z, float& out_x, float& out_y, float& out_z);

bool box_collision_surface(float origin_x,
                           float origin_y,
                           float origin_z,
                           float hit_radius,
                           float center_x,
                           float center_y,
                           float center_z,
                           float axis_xx,
                           float axis_xy,
                           float axis_xz,
                           float axis_yx,
                           float axis_yy,
                           float axis_yz,
                           float signed_half_z,
                           float& out_normal_x,
                           float& out_normal_y,
                           float& out_normal_z,
                           float& out_surface_distance) {
    const float half_x = std::sqrt(axis_xx * axis_xx + axis_xy * axis_xy + axis_xz * axis_xz);
    const float half_y = std::sqrt(axis_yx * axis_yx + axis_yy * axis_yy + axis_yz * axis_yz);
    const float half_z = std::fabs(signed_half_z);
    if (half_x <= kEpsilon || half_y <= kEpsilon || half_z <= kEpsilon) {
        return false;
    }

    const float ux_x = axis_xx / half_x;
    const float ux_y = axis_xy / half_x;
    const float ux_z = axis_xz / half_x;
    const float uy_x = axis_yx / half_y;
    const float uy_y = axis_yy / half_y;
    const float uy_z = axis_yz / half_y;
    float uz_x = 0.0f;
    float uz_y = 0.0f;
    float uz_z = 1.0f;
    cross3(ux_x, ux_y, ux_z, uy_x, uy_y, uy_z, uz_x, uz_y, uz_z);
    const float uz_len = length3(uz_x, uz_y, uz_z);
    if (uz_len <= kEpsilon) {
        return false;
    }
    uz_x /= uz_len;
    uz_y /= uz_len;
    uz_z /= uz_len;
    if (signed_half_z < 0.0f) {
        uz_x = -uz_x;
        uz_y = -uz_y;
        uz_z = -uz_z;
    }

    const float rel_x = origin_x - center_x;
    const float rel_y = origin_y - center_y;
    const float rel_z = origin_z - center_z;
    const float local_x = dot3(rel_x, rel_y, rel_z, ux_x, ux_y, ux_z);
    const float local_y = dot3(rel_x, rel_y, rel_z, uy_x, uy_y, uy_z);
    const float local_z = dot3(rel_x, rel_y, rel_z, uz_x, uz_y, uz_z);
    const float expanded_x = half_x + hit_radius;
    const float expanded_y = half_y + hit_radius;
    const float expanded_z = half_z + hit_radius;
    const float outside_x = std::max(std::fabs(local_x) - expanded_x, 0.0f);
    const float outside_y = std::max(std::fabs(local_y) - expanded_y, 0.0f);
    const float outside_z = std::max(std::fabs(local_z) - expanded_z, 0.0f);
    const float outside_distance = length3(outside_x, outside_y, outside_z);
    if (outside_distance > kEpsilon) {
        const float sign_x = local_x >= 0.0f ? 1.0f : -1.0f;
        const float sign_y = local_y >= 0.0f ? 1.0f : -1.0f;
        const float sign_z = local_z >= 0.0f ? 1.0f : -1.0f;
        out_normal_x = ux_x * outside_x * sign_x + uy_x * outside_y * sign_y + uz_x * outside_z * sign_z;
        out_normal_y = ux_y * outside_x * sign_x + uy_y * outside_y * sign_y + uz_y * outside_z * sign_z;
        out_normal_z = ux_z * outside_x * sign_x + uy_z * outside_y * sign_y + uz_z * outside_z * sign_z;
        safe_normal_or_z(out_normal_x, out_normal_y, out_normal_z, out_normal_x, out_normal_y, out_normal_z);
        out_surface_distance = outside_distance;
        return true;
    }

    const float penetration_x = expanded_x - std::fabs(local_x);
    const float penetration_y = expanded_y - std::fabs(local_y);
    const float penetration_z = expanded_z - std::fabs(local_z);
    const float sign_x = local_x >= 0.0f ? 1.0f : -1.0f;
    const float sign_y = local_y >= 0.0f ? 1.0f : -1.0f;
    const float sign_z = local_z >= 0.0f ? 1.0f : -1.0f;
    if (penetration_x <= penetration_y && penetration_x <= penetration_z) {
        out_normal_x = ux_x * sign_x;
        out_normal_y = ux_y * sign_x;
        out_normal_z = ux_z * sign_x;
        out_surface_distance = -penetration_x;
    } else if (penetration_y <= penetration_z) {
        out_normal_x = uy_x * sign_y;
        out_normal_y = uy_y * sign_y;
        out_normal_z = uy_z * sign_y;
        out_surface_distance = -penetration_y;
    } else {
        out_normal_x = uz_x * sign_z;
        out_normal_y = uz_y * sign_z;
        out_normal_z = uz_z * sign_z;
        out_surface_distance = -penetration_z;
    }
    return true;
}

void normalize3(float& x, float& y, float& z) {
    const float len = length3(x, y, z);
    if (len <= kEpsilon) {
        x = 0.0f;
        y = 0.0f;
        z = 1.0f;
        return;
    }
    const float inv_len = 1.0f / len;
    x *= inv_len;
    y *= inv_len;
    z *= inv_len;
}

void safe_normal_or_z(float x, float y, float z, float& out_x, float& out_y, float& out_z) {
    const float len = length3(x, y, z);
    if (len > kEpsilon) {
        const float inv_len = 1.0f / len;
        out_x = x * inv_len;
        out_y = y * inv_len;
        out_z = z * inv_len;
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
    const float len = length3(x, y, z);
    if (len > kEpsilon) {
        const float inv_len = 1.0f / len;
        out_x = x * inv_len;
        out_y = y * inv_len;
        out_z = z * inv_len;
        return;
    }
    safe_normal_or_z(fallback_x, fallback_y, fallback_z, out_x, out_y, out_z);
}

void quat_normalize(const float in_q[4], float out_q[4]) {
    const float len = std::sqrt(in_q[0] * in_q[0] + in_q[1] * in_q[1] + in_q[2] * in_q[2] + in_q[3] * in_q[3]);
    if (len <= kEpsilon) {
        out_q[0] = 0.0f;
        out_q[1] = 0.0f;
        out_q[2] = 0.0f;
        out_q[3] = 1.0f;
        return;
    }
    const float inv_len = 1.0f / len;
    out_q[0] = in_q[0] * inv_len;
    out_q[1] = in_q[1] * inv_len;
    out_q[2] = in_q[2] * inv_len;
    out_q[3] = in_q[3] * inv_len;
}

void quat_mul(const float a[4], const float b[4], float out_q[4]) {
    const float raw[4] = {
        a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    };
    quat_normalize(raw, out_q);
}

void quat_rotate(const float quat[4], float vx, float vy, float vz, float& out_x, float& out_y, float& out_z) {
    float q[4];
    quat_normalize(quat, q);
    float uv_x = 0.0f;
    float uv_y = 0.0f;
    float uv_z = 0.0f;
    cross3(q[0], q[1], q[2], vx, vy, vz, uv_x, uv_y, uv_z);
    float uuv_x = 0.0f;
    float uuv_y = 0.0f;
    float uuv_z = 0.0f;
    cross3(q[0], q[1], q[2], uv_x, uv_y, uv_z, uuv_x, uuv_y, uuv_z);
    out_x = vx + 2.0f * (q[3] * uv_x + uuv_x);
    out_y = vy + 2.0f * (q[3] * uv_y + uuv_y);
    out_z = vz + 2.0f * (q[3] * uv_z + uuv_z);
}

void quat_from_matrix3(const float m[9], float out_q[4]) {
    const float trace = m[0] + m[4] + m[8];
    float raw[4];
    if (trace > 0.0f) {
        const float s = std::sqrt(trace + 1.0f) * 2.0f;
        raw[0] = (m[7] - m[5]) / s;
        raw[1] = (m[2] - m[6]) / s;
        raw[2] = (m[3] - m[1]) / s;
        raw[3] = 0.25f * s;
    } else if (m[0] > m[4] && m[0] > m[8]) {
        const float s = std::sqrt(1.0f + m[0] - m[4] - m[8]) * 2.0f;
        raw[0] = 0.25f * s;
        raw[1] = (m[1] + m[3]) / s;
        raw[2] = (m[2] + m[6]) / s;
        raw[3] = (m[7] - m[5]) / s;
    } else if (m[4] > m[8]) {
        const float s = std::sqrt(1.0f + m[4] - m[0] - m[8]) * 2.0f;
        raw[0] = (m[1] + m[3]) / s;
        raw[1] = 0.25f * s;
        raw[2] = (m[5] + m[7]) / s;
        raw[3] = (m[2] - m[6]) / s;
    } else {
        const float s = std::sqrt(1.0f + m[8] - m[0] - m[4]) * 2.0f;
        raw[0] = (m[2] + m[6]) / s;
        raw[1] = (m[5] + m[7]) / s;
        raw[2] = 0.25f * s;
        raw[3] = (m[3] - m[1]) / s;
    }
    quat_normalize(raw, out_q);
}

void from_to_rotation(float source_x,
                      float source_y,
                      float source_z,
                      float target_x,
                      float target_y,
                      float target_z,
                      float ratio,
                      float out_q[4]) {
    ratio = clamp_float(ratio, 0.0f, 1.0f);
    float src_x = 0.0f;
    float src_y = 0.0f;
    float src_z = 1.0f;
    safe_normal_or_z(source_x, source_y, source_z, src_x, src_y, src_z);
    float dst_x = 0.0f;
    float dst_y = 0.0f;
    float dst_z = 1.0f;
    safe_normal_with_fallback(target_x, target_y, target_z, src_x, src_y, src_z, dst_x, dst_y, dst_z);
    const float dot = clamp_float(dot3(src_x, src_y, src_z, dst_x, dst_y, dst_z), -1.0f, 1.0f);
    if (dot > 1.0f - kEpsilon || ratio <= kEpsilon) {
        out_q[0] = 0.0f;
        out_q[1] = 0.0f;
        out_q[2] = 0.0f;
        out_q[3] = 1.0f;
        return;
    }

    float axis_x = 0.0f;
    float axis_y = 0.0f;
    float axis_z = 1.0f;
    float angle = 0.0f;
    if (dot < -1.0f + kEpsilon) {
        const bool use_y = src_x > src_y && src_x > src_z;
        const float helper_x = use_y ? 0.0f : 1.0f;
        const float helper_y = use_y ? 1.0f : 0.0f;
        const float helper_z = 0.0f;
        float cross_x = 0.0f;
        float cross_y = 0.0f;
        float cross_z = 0.0f;
        cross3(src_x, src_y, src_z, helper_x, helper_y, helper_z, cross_x, cross_y, cross_z);
        safe_normal_or_z(cross_x, cross_y, cross_z, axis_x, axis_y, axis_z);
        angle = 3.14159265358979323846f * ratio;
    } else {
        float cross_x = 0.0f;
        float cross_y = 0.0f;
        float cross_z = 0.0f;
        cross3(src_x, src_y, src_z, dst_x, dst_y, dst_z, cross_x, cross_y, cross_z);
        safe_normal_or_z(cross_x, cross_y, cross_z, axis_x, axis_y, axis_z);
        angle = std::acos(dot) * ratio;
    }

    const float half = angle * 0.5f;
    const float s = std::sin(half);
    out_q[0] = axis_x * s;
    out_q[1] = axis_y * s;
    out_q[2] = axis_z * s;
    out_q[3] = std::cos(half);
}

void mat3_mul_vec3(const float* m, const float& x, const float& y, const float& z, float& out_x, float& out_y, float& out_z) {
    out_x = m[0] * x + m[1] * y + m[2] * z;
    out_y = m[4] * x + m[5] * y + m[6] * z;
    out_z = m[8] * x + m[9] * y + m[10] * z;
}

void mat4_mul_point(const float* m, const float& x, const float& y, const float& z, float& out_x, float& out_y, float& out_z) {
    out_x = m[0] * x + m[1] * y + m[2] * z + m[3];
    out_y = m[4] * x + m[5] * y + m[6] * z + m[7];
    out_z = m[8] * x + m[9] * y + m[10] * z + m[11];
}

void matrix_from_quat_scale(
    const float quat[4],
    const float scale[3],
    const float translation[3],
    float out_m[16]) {
    const float x = quat[0];
    const float y = quat[1];
    const float z = quat[2];
    const float w = quat[3];
    const float x2 = x + x;
    const float y2 = y + y;
    const float z2 = z + z;
    const float xx = x * x2;
    const float xy = x * y2;
    const float xz = x * z2;
    const float yy = y * y2;
    const float yz = y * z2;
    const float zz = z * z2;
    const float wx = w * x2;
    const float wy = w * y2;
    const float wz = w * z2;

    const float r00 = 1.0f - (yy + zz);
    const float r01 = xy - wz;
    const float r02 = xz + wy;
    const float r10 = xy + wz;
    const float r11 = 1.0f - (xx + zz);
    const float r12 = yz - wx;
    const float r20 = xz - wy;
    const float r21 = yz + wx;
    const float r22 = 1.0f - (xx + yy);

    out_m[0] = r00 * scale[0];
    out_m[1] = r01 * scale[1];
    out_m[2] = r02 * scale[2];
    out_m[3] = translation[0];
    out_m[4] = r10 * scale[0];
    out_m[5] = r11 * scale[1];
    out_m[6] = r12 * scale[2];
    out_m[7] = translation[1];
    out_m[8] = r20 * scale[0];
    out_m[9] = r21 * scale[1];
    out_m[10] = r22 * scale[2];
    out_m[11] = translation[2];
    out_m[12] = 0.0f;
    out_m[13] = 0.0f;
    out_m[14] = 0.0f;
    out_m[15] = 1.0f;
}

void copy_matrix16(const float* src, float* dst) {
    for (int index = 0; index < 16; ++index) {
        dst[index] = src[index];
    }
}

void project_tail_to_length(const float head[3], const float tail[3], float length, const float fallback_axis[3], float out_tail[3]) {
    float dx = tail[0] - head[0];
    float dy = tail[1] - head[1];
    float dz = tail[2] - head[2];
    float dir_len = length3(dx, dy, dz);
    if (dir_len <= kEpsilon) {
        float nx = fallback_axis[0];
        float ny = fallback_axis[1];
        float nz = fallback_axis[2];
        normalize3(nx, ny, nz);
        out_tail[0] = head[0] + nx * length;
        out_tail[1] = head[1] + ny * length;
        out_tail[2] = head[2] + nz * length;
        return;
    }
    const float scale = length / dir_len;
    out_tail[0] = head[0] + dx * scale;
    out_tail[1] = head[1] + dy * scale;
    out_tail[2] = head[2] + dz * scale;
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

void project_collision(
    float hit_radius,
    std::int32_t collided_by_groups,
    const SpringBoneVrmChainView& view,
    const float head[3],
    const float fallback_axis[3],
    float length,
    float tail[3]) {
    if (collided_by_groups == 0 || view.collider_count <= 0) {
        return;
    }

    for (std::int64_t collider = 0; collider < view.collider_count; ++collider) {
        const std::int32_t group = view.collider_groups[collider];
        if (group < 1 || group > 16) {
            continue;
        }
        if ((collided_by_groups & (1 << (group - 1))) == 0) {
            continue;
        }

        const std::int64_t collider_offset = collider * 3;
        const int collider_type = view.collider_types[collider];
        const float center_x = view.collider_centers[collider_offset + 0];
        const float center_y = view.collider_centers[collider_offset + 1];
        const float center_z = view.collider_centers[collider_offset + 2];

        if (collider_type == kColliderPlane) {
            float nx = 0.0f;
            float ny = 0.0f;
            float nz = 1.0f;
            safe_normal_or_z(view.collider_segment_a[collider_offset + 0],
                             view.collider_segment_a[collider_offset + 1],
                             view.collider_segment_a[collider_offset + 2],
                             nx,
                             ny,
                             nz);
            const float distance = dot3(tail[0] - center_x, tail[1] - center_y, tail[2] - center_z, nx, ny, nz);
            if (distance >= hit_radius) {
                continue;
            }
            const float push = hit_radius - distance;
            const float pushed[3] = {
                tail[0] + nx * push,
                tail[1] + ny * push,
                tail[2] + nz * push,
            };
            project_tail_to_length(head, pushed, length, fallback_axis, tail);
            continue;
        }

        if (collider_type == kColliderBox) {
            float nx = 0.0f;
            float ny = 0.0f;
            float nz = 1.0f;
            float surface_distance = 0.0f;
            if (!box_collision_surface(tail[0],
                                       tail[1],
                                       tail[2],
                                       hit_radius,
                                       center_x,
                                       center_y,
                                       center_z,
                                       view.collider_segment_a[collider_offset + 0],
                                       view.collider_segment_a[collider_offset + 1],
                                       view.collider_segment_a[collider_offset + 2],
                                       view.collider_segment_b[collider_offset + 0],
                                       view.collider_segment_b[collider_offset + 1],
                                       view.collider_segment_b[collider_offset + 2],
                                       view.collider_radii[collider],
                                       nx,
                                       ny,
                                       nz,
                                       surface_distance)) {
                continue;
            }
            if (surface_distance > 0.0f) {
                continue;
            }
            const float pushed[3] = {
                tail[0] - nx * surface_distance,
                tail[1] - ny * surface_distance,
                tail[2] - nz * surface_distance,
            };
            project_tail_to_length(head, pushed, length, fallback_axis, tail);
            continue;
        }

        if (collider_type != kColliderSphere && collider_type != kColliderCapsule) {
            continue;
        }

        const float radius = std::max(view.collider_radii[collider], 0.0f) + hit_radius;
        if (radius <= kEpsilon) {
            continue;
        }

        float closest_x = center_x;
        float closest_y = center_y;
        float closest_z = center_z;

        if (collider_type == kColliderCapsule) {
            closest_point_on_segment(
                tail[0],
                tail[1],
                tail[2],
                view.collider_segment_a + collider_offset,
                view.collider_segment_b + collider_offset,
                closest_x,
                closest_y,
                closest_z);
        }

        const float dx = tail[0] - closest_x;
        const float dy = tail[1] - closest_y;
        const float dz = tail[2] - closest_z;
        if (dx * dx + dy * dy + dz * dz >= radius * radius) {
            continue;
        }

        float nx = 0.0f;
        float ny = 0.0f;
        float nz = 1.0f;
        safe_normal_with_fallback(dx, dy, dz, fallback_axis[0], fallback_axis[1], fallback_axis[2], nx, ny, nz);
        const float pushed[3] = {
            closest_x + nx * radius,
            closest_y + ny * radius,
            closest_z + nz * radius,
        };
        project_tail_to_length(head, pushed, length, fallback_axis, tail);
    }
}

void solve_spring_bone_vrm_chain(SpringBoneVrmChainView& view) {
    if (view.bone_count <= 0 || view.current_tails == nullptr || view.prev_tails == nullptr ||
        view.target_matrices == nullptr || view.current_heads == nullptr || view.current_pose_matrices == nullptr ||
        view.current_pose_quaternions == nullptr || view.current_pose_tails == nullptr || view.lengths == nullptr || view.init_axis_local == nullptr ||
        view.init_axis_parent == nullptr || view.init_rotations == nullptr || view.init_scales == nullptr ||
        view.parent_indices == nullptr || view.pinned == nullptr || view.use_connect == nullptr ||
        view.root_quaternion == nullptr || view.root_tail_world == nullptr || view.armature_world == nullptr ||
        view.armature_world_inv == nullptr || view.gravity_dir == nullptr || view.hit_radii == nullptr ||
        view.collided_by_groups == nullptr) {
        return;
    }

    const int substep_count = std::max(view.substeps, 1);
    const float step_dt = substep_count > 0 ? view.dt / static_cast<float>(substep_count) : view.dt;
    float gravity_dir[3] = {view.gravity_dir[0], view.gravity_dir[1], view.gravity_dir[2]};
    const float gravity_len = length3(gravity_dir[0], gravity_dir[1], gravity_dir[2]);
    if (gravity_len > kEpsilon) {
        const float inv_gravity_len = 1.0f / gravity_len;
        gravity_dir[0] *= inv_gravity_len;
        gravity_dir[1] *= inv_gravity_len;
        gravity_dir[2] *= inv_gravity_len;
    } else {
        gravity_dir[0] = 0.0f;
        gravity_dir[1] = 0.0f;
        gravity_dir[2] = 0.0f;
    }
    const float gravity_scale = std::max(view.gravity_power, 0.0f);

    float root_quaternion[4] = {
        view.root_quaternion[0],
        view.root_quaternion[1],
        view.root_quaternion[2],
        view.root_quaternion[3],
    };
    quat_normalize(root_quaternion, root_quaternion);

    std::vector<float> owned_target_quaternions;
    float* target_quaternions = view.target_quaternions;
    if (target_quaternions == nullptr) {
        owned_target_quaternions.resize(static_cast<std::size_t>(view.bone_count) * 4u, 0.0f);
        target_quaternions = owned_target_quaternions.data();
    }

    for (int substep = 0; substep < substep_count; ++substep) {
        (void)substep;
        for (std::int64_t bone = 0; bone < view.bone_count; ++bone) {
            const std::int64_t matrix_offset = bone * 16;
            const std::int64_t vec_offset = bone * 3;
            const std::int32_t parent_index = view.parent_indices[bone];
            const bool pinned = view.pinned[bone] != 0;
            const bool use_connect = view.use_connect[bone] != 0;

            float target_quat[4];
            if (pinned) {
                view.current_tails[vec_offset + 0] = view.current_pose_tails[vec_offset + 0];
                view.current_tails[vec_offset + 1] = view.current_pose_tails[vec_offset + 1];
                view.current_tails[vec_offset + 2] = view.current_pose_tails[vec_offset + 2];
                view.prev_tails[vec_offset + 0] = view.current_pose_tails[vec_offset + 0];
                view.prev_tails[vec_offset + 1] = view.current_pose_tails[vec_offset + 1];
                view.prev_tails[vec_offset + 2] = view.current_pose_tails[vec_offset + 2];
                copy_matrix16(view.current_pose_matrices + matrix_offset, view.target_matrices + matrix_offset);
                target_quat[0] = view.current_pose_quaternions[bone * 4 + 0];
                target_quat[1] = view.current_pose_quaternions[bone * 4 + 1];
                target_quat[2] = view.current_pose_quaternions[bone * 4 + 2];
                target_quat[3] = view.current_pose_quaternions[bone * 4 + 3];
                quat_normalize(target_quat, target_quat);

                target_quaternions[bone * 4 + 0] = target_quat[0];
                target_quaternions[bone * 4 + 1] = target_quat[1];
                target_quaternions[bone * 4 + 2] = target_quat[2];
                target_quaternions[bone * 4 + 3] = target_quat[3];
                continue;
            }

            float head[3] = {
                view.current_heads[vec_offset + 0],
                view.current_heads[vec_offset + 1],
                view.current_heads[vec_offset + 2],
            };
            if (use_connect) {
                if (parent_index < 0) {
                    head[0] = view.current_heads[vec_offset + 0];
                    head[1] = view.current_heads[vec_offset + 1];
                    head[2] = view.current_heads[vec_offset + 2];
                } else {
                    const std::int64_t parent_offset = static_cast<std::int64_t>(parent_index) * 3;
                    head[0] = view.current_tails[parent_offset + 0];
                    head[1] = view.current_tails[parent_offset + 1];
                    head[2] = view.current_tails[parent_offset + 2];
                }
            }

            float current_tail[3] = {
                view.current_tails[vec_offset + 0],
                view.current_tails[vec_offset + 1],
                view.current_tails[vec_offset + 2],
            };
            float prev_tail[3] = {
                view.prev_tails[vec_offset + 0],
                view.prev_tails[vec_offset + 1],
                view.prev_tails[vec_offset + 2],
            };
            const float length = std::max(view.lengths[bone], 0.0f);
            if (length <= kEpsilon) {
                view.current_tails[vec_offset + 0] = view.current_pose_tails[vec_offset + 0];
                view.current_tails[vec_offset + 1] = view.current_pose_tails[vec_offset + 1];
                view.current_tails[vec_offset + 2] = view.current_pose_tails[vec_offset + 2];
                view.prev_tails[vec_offset + 0] = view.current_pose_tails[vec_offset + 0];
                view.prev_tails[vec_offset + 1] = view.current_pose_tails[vec_offset + 1];
                view.prev_tails[vec_offset + 2] = view.current_pose_tails[vec_offset + 2];
                copy_matrix16(view.current_pose_matrices + matrix_offset, view.target_matrices + matrix_offset);
                target_quat[0] = view.current_pose_quaternions[bone * 4 + 0];
                target_quat[1] = view.current_pose_quaternions[bone * 4 + 1];
                target_quat[2] = view.current_pose_quaternions[bone * 4 + 2];
                target_quat[3] = view.current_pose_quaternions[bone * 4 + 3];
                quat_normalize(target_quat, target_quat);
                target_quaternions[bone * 4 + 0] = target_quat[0];
                target_quaternions[bone * 4 + 1] = target_quat[1];
                target_quaternions[bone * 4 + 2] = target_quat[2];
                target_quaternions[bone * 4 + 3] = target_quat[3];
                continue;
            }

            float fallback_axis[3] = {
                view.init_axis_parent[vec_offset + 0],
                view.init_axis_parent[vec_offset + 1],
                view.init_axis_parent[vec_offset + 2],
            };
            normalize3(fallback_axis[0], fallback_axis[1], fallback_axis[2]);

            float rest_axis_pose[3];
            if (parent_index < 0) {
                const float* parent_quat = &view.parent_pose_quaternions[bone * 4];
                quat_rotate(parent_quat, fallback_axis[0], fallback_axis[1], fallback_axis[2], rest_axis_pose[0], rest_axis_pose[1], rest_axis_pose[2]);
            } else {
                const float* parent_quat = &target_quaternions[static_cast<std::size_t>(parent_index) * 4u];
                quat_rotate(parent_quat, fallback_axis[0], fallback_axis[1], fallback_axis[2], rest_axis_pose[0], rest_axis_pose[1], rest_axis_pose[2]);
            }

            float rest_axis_world[3];
            mat3_mul_vec3(view.armature_world, rest_axis_pose[0], rest_axis_pose[1], rest_axis_pose[2], rest_axis_world[0], rest_axis_world[1], rest_axis_world[2]);
            normalize3(rest_axis_world[0], rest_axis_world[1], rest_axis_world[2]);

            const float inertia_x = (current_tail[0] - prev_tail[0]) * (1.0f - clamp_float(view.drag_force, 0.0f, 1.0f));
            const float inertia_y = (current_tail[1] - prev_tail[1]) * (1.0f - clamp_float(view.drag_force, 0.0f, 1.0f));
            const float inertia_z = (current_tail[2] - prev_tail[2]) * (1.0f - clamp_float(view.drag_force, 0.0f, 1.0f));

            float next_tail[3] = {
                current_tail[0] + inertia_x + rest_axis_world[0] * view.stiffness_force * step_dt + gravity_dir[0] * gravity_scale * step_dt,
                current_tail[1] + inertia_y + rest_axis_world[1] * view.stiffness_force * step_dt + gravity_dir[1] * gravity_scale * step_dt,
                current_tail[2] + inertia_z + rest_axis_world[2] * view.stiffness_force * step_dt + gravity_dir[2] * gravity_scale * step_dt,
            };

            project_tail_to_length(head, next_tail, length, rest_axis_world, next_tail);
            project_collision(
                view.hit_radii[bone],
                view.collided_by_groups[bone],
                view,
                head,
                rest_axis_world,
                length,
                next_tail);

            view.prev_tails[vec_offset + 0] = current_tail[0];
            view.prev_tails[vec_offset + 1] = current_tail[1];
            view.prev_tails[vec_offset + 2] = current_tail[2];
            view.current_tails[vec_offset + 0] = next_tail[0];
            view.current_tails[vec_offset + 1] = next_tail[1];
            view.current_tails[vec_offset + 2] = next_tail[2];

            float direction_world[3] = {
                next_tail[0] - head[0],
                next_tail[1] - head[1],
                next_tail[2] - head[2],
            };
            float direction_len = length3(direction_world[0], direction_world[1], direction_world[2]);
            if (direction_len <= kEpsilon) {
                copy_matrix16(view.current_pose_matrices + matrix_offset, view.target_matrices + matrix_offset);
                target_quat[0] = view.current_pose_quaternions[bone * 4 + 0];
                target_quat[1] = view.current_pose_quaternions[bone * 4 + 1];
                target_quat[2] = view.current_pose_quaternions[bone * 4 + 2];
                target_quat[3] = view.current_pose_quaternions[bone * 4 + 3];
                quat_normalize(target_quat, target_quat);
                target_quaternions[bone * 4 + 0] = target_quat[0];
                target_quaternions[bone * 4 + 1] = target_quat[1];
                target_quaternions[bone * 4 + 2] = target_quat[2];
                target_quaternions[bone * 4 + 3] = target_quat[3];
                continue;
            }

            float direction_pose[3];
            const float direction_inv[3] = {
                view.armature_world_inv[0] * direction_world[0] + view.armature_world_inv[1] * direction_world[1] + view.armature_world_inv[2] * direction_world[2],
                view.armature_world_inv[4] * direction_world[0] + view.armature_world_inv[5] * direction_world[1] + view.armature_world_inv[6] * direction_world[2],
                view.armature_world_inv[8] * direction_world[0] + view.armature_world_inv[9] * direction_world[1] + view.armature_world_inv[10] * direction_world[2],
            };
            direction_pose[0] = direction_inv[0];
            direction_pose[1] = direction_inv[1];
            direction_pose[2] = direction_inv[2];
            normalize3(direction_pose[0], direction_pose[1], direction_pose[2]);

            float init_axis_local[3] = {
                view.init_axis_local[vec_offset + 0],
                view.init_axis_local[vec_offset + 1],
                view.init_axis_local[vec_offset + 2],
            };
            normalize3(init_axis_local[0], init_axis_local[1], init_axis_local[2]);

            float rotation_delta[4];
            from_to_rotation(
                init_axis_local[0],
                init_axis_local[1],
                init_axis_local[2],
                direction_pose[0],
                direction_pose[1],
                direction_pose[2],
                1.0f,
                rotation_delta);

            float init_rotation[4] = {
                view.init_rotations[bone * 4 + 0],
                view.init_rotations[bone * 4 + 1],
                view.init_rotations[bone * 4 + 2],
                view.init_rotations[bone * 4 + 3],
            };
            float target_rotation[4];
            quat_mul(rotation_delta, init_rotation, target_rotation);

            float head_pose[3];
            mat4_mul_point(view.armature_world_inv, head[0], head[1], head[2], head_pose[0], head_pose[1], head_pose[2]);

            float init_scale[3] = {
                view.init_scales[vec_offset + 0],
                view.init_scales[vec_offset + 1],
                view.init_scales[vec_offset + 2],
            };
            matrix_from_quat_scale(target_rotation, init_scale, head_pose, view.target_matrices + matrix_offset);
            target_quaternions[bone * 4 + 0] = target_rotation[0];
            target_quaternions[bone * 4 + 1] = target_rotation[1];
            target_quaternions[bone * 4 + 2] = target_rotation[2];
            target_quaternions[bone * 4 + 3] = target_rotation[3];
        }
    }
}

}  // namespace

void solve_spring_bone_vrm_cpp(SpringBoneVrmChainView& view) {
    solve_spring_bone_vrm_chain(view);
}

// ─────────────────────────────────────────────────────────────────────────────
// dual-call context 实现
// ─────────────────────────────────────────────────────────────────────────────

namespace {

template <typename T>
static void copy_n(const T* src, std::size_t n, std::vector<T>& dst) {
    dst.assign(src, src + n);
}

template <typename T>
static void fill_n(std::size_t n, T value, std::vector<T>& dst) {
    dst.assign(n, value);
}

}  // namespace

SpringVrmContext* spring_vrm_context_create(
    int            schema,
    std::int64_t   bone_count,
    const float*   lengths,
    const float*   init_axis_local,
    const float*   init_axis_parent,
    const float*   init_rotations,
    const float*   init_scales,
    const std::int32_t* parent_indices,
    const std::uint8_t* pinned,
    const std::uint8_t* use_connect)
{
    if (bone_count <= 0) return nullptr;
    const auto n = static_cast<std::size_t>(bone_count);

    auto* ctx = new SpringVrmContext();
    ctx->schema     = schema;
    ctx->bone_count = bone_count;

    // 静态数组（深拷贝，C++ 完全持有）
    copy_n(lengths,           n,     ctx->lengths);
    copy_n(init_axis_local,   n * 3, ctx->init_axis_local);
    copy_n(init_axis_parent,  n * 3, ctx->init_axis_parent);
    copy_n(init_rotations,    n * 4, ctx->init_rotations);
    copy_n(init_scales,       n * 3, ctx->init_scales);
    copy_n(parent_indices,    n,     ctx->parent_indices);
    copy_n(pinned,            n,     ctx->pinned);
    copy_n(use_connect,       n,     ctx->use_connect);

    // 动态输入缓冲区（分配，等待 update_dynamic 填充）
    ctx->current_heads.resize(n * 3, 0.f);
    ctx->current_pose_matrices.resize(n * 16, 0.f);
    ctx->current_pose_quaternions.resize(n * 4, 0.f);
    ctx->parent_pose_quaternions.resize(n * 4, 0.f);
    ctx->current_pose_tails.resize(n * 3, 0.f);
    ctx->hit_radii.resize(n, 0.f);
    ctx->collided_by_groups.resize(n, 0);

    // 模拟状态（初始为零，reset_state 会从 pose 覆盖）
    ctx->current_tails.resize(n * 3, 0.f);
    ctx->prev_tails.resize(n * 3, 0.f);

    // 结果缓冲区
    ctx->target_matrices.resize(n * 16, 0.f);
    ctx->target_quaternions.resize(n * 4, 0.f);

    return ctx;
}

void spring_vrm_context_reset_state(SpringVrmContext* ctx) {
    if (!ctx || ctx->bone_count <= 0) return;
    // 把 current/prev tails 重置为当前 pose tail（来自最近一次 update_dynamic）
    ctx->current_tails = ctx->current_pose_tails;
    ctx->prev_tails    = ctx->current_pose_tails;
}

void spring_vrm_context_update_dynamic(
    SpringVrmContext*   ctx,
    const float*        current_heads,
    const float*        current_pose_matrices,
    const float*        current_pose_quaternions,
    const float*        parent_pose_quaternions,
    const float*        current_pose_tails,
    const float*        armature_world,
    const float*        armature_world_inv,
    const float*        root_quaternion,
    const float*        root_tail_world,
    const float*        gravity_dir,
    const float*        hit_radii,
    const std::int32_t* collided_by_groups,
    const std::int32_t* collider_types,
    const std::int32_t* collider_groups,
    const float*        collider_centers,
    const float*        collider_segment_a,
    const float*        collider_segment_b,
    const float*        collider_radii,
    std::int64_t        collider_count)
{
    if (!ctx || ctx->bone_count <= 0) return;
    const auto n = static_cast<std::size_t>(ctx->bone_count);
    const auto m = static_cast<std::size_t>(collider_count > 0 ? collider_count : 0);

    copy_n(current_heads,              n * 3,  ctx->current_heads);
    copy_n(current_pose_matrices,      n * 16, ctx->current_pose_matrices);
    copy_n(current_pose_quaternions,   n * 4,  ctx->current_pose_quaternions);
    copy_n(parent_pose_quaternions,    n * 4,  ctx->parent_pose_quaternions);
    copy_n(current_pose_tails,         n * 3,  ctx->current_pose_tails);
    copy_n(hit_radii,                  n,      ctx->hit_radii);
    copy_n(collided_by_groups,         n,      ctx->collided_by_groups);

    for (int i = 0; i < 16; ++i) ctx->armature_world[i]     = armature_world[i];
    for (int i = 0; i < 16; ++i) ctx->armature_world_inv[i] = armature_world_inv[i];
    for (int i = 0; i <  4; ++i) ctx->root_quaternion[i]    = root_quaternion[i];
    for (int i = 0; i <  3; ++i) ctx->root_tail_world[i]    = root_tail_world[i];
    for (int i = 0; i <  3; ++i) ctx->gravity_dir[i]        = gravity_dir[i];

    ctx->collider_count = static_cast<std::int64_t>(m);
    if (m > 0) {
        copy_n(collider_types,    m,     ctx->collider_types);
        copy_n(collider_groups,   m,     ctx->collider_groups);
        copy_n(collider_centers,  m * 3, ctx->collider_centers);
        copy_n(collider_segment_a,m * 3, ctx->collider_segment_a);
        copy_n(collider_segment_b,m * 3, ctx->collider_segment_b);
        copy_n(collider_radii,    m,     ctx->collider_radii);
    } else {
        ctx->collider_types.clear();
        ctx->collider_groups.clear();
        ctx->collider_centers.clear();
        ctx->collider_segment_a.clear();
        ctx->collider_segment_b.clear();
        ctx->collider_radii.clear();
    }
}

void spring_vrm_context_step(
    SpringVrmContext* ctx,
    float dt,
    int   substeps,
    float stiffness_force,
    float drag_force,
    float gravity_power)
{
    if (!ctx || ctx->bone_count <= 0) return;

    ctx->stiffness_force = stiffness_force;
    ctx->drag_force      = drag_force;
    ctx->gravity_power   = gravity_power;

    // 通过旧 View 接口复用已有解算核（无需重写）
    SpringBoneVrmChainView view;
    view.current_tails            = ctx->current_tails.data();
    view.prev_tails               = ctx->prev_tails.data();
    view.target_matrices          = ctx->target_matrices.data();
    view.target_quaternions       = ctx->target_quaternions.data();
    view.current_heads            = ctx->current_heads.data();
    view.current_pose_matrices    = ctx->current_pose_matrices.data();
    view.current_pose_quaternions = ctx->current_pose_quaternions.data();
    view.parent_pose_quaternions  = ctx->parent_pose_quaternions.data();
    view.current_pose_tails       = ctx->current_pose_tails.data();
    view.lengths                  = ctx->lengths.data();
    view.init_axis_local          = ctx->init_axis_local.data();
    view.init_axis_parent         = ctx->init_axis_parent.data();
    view.init_rotations           = ctx->init_rotations.data();
    view.init_scales              = ctx->init_scales.data();
    view.parent_indices           = ctx->parent_indices.data();
    view.pinned                   = ctx->pinned.data();
    view.use_connect              = ctx->use_connect.data();
    view.root_quaternion          = ctx->root_quaternion;
    view.root_tail_world          = ctx->root_tail_world;
    view.armature_world           = ctx->armature_world;
    view.armature_world_inv       = ctx->armature_world_inv;
    view.gravity_dir              = ctx->gravity_dir;
    view.hit_radii                = ctx->hit_radii.data();
    view.collided_by_groups       = ctx->collided_by_groups.data();
    view.collider_count           = ctx->collider_count;
    if (ctx->collider_count > 0) {
        view.collider_types    = ctx->collider_types.data();
        view.collider_groups   = ctx->collider_groups.data();
        view.collider_centers  = ctx->collider_centers.data();
        view.collider_segment_a= ctx->collider_segment_a.data();
        view.collider_segment_b= ctx->collider_segment_b.data();
        view.collider_radii    = ctx->collider_radii.data();
    }
    view.bone_count      = ctx->bone_count;
    view.dt              = dt;
    view.substeps        = substeps;
    view.stiffness_force = stiffness_force;
    view.drag_force      = drag_force;
    view.gravity_power   = gravity_power;

    solve_spring_bone_vrm_chain(view);
}

void spring_vrm_context_read_results(
    const SpringVrmContext* ctx,
    float* out_matrices,
    float* out_quaternions)
{
    if (!ctx || ctx->bone_count <= 0) return;
    if (out_matrices)    std::copy(ctx->target_matrices.begin(),    ctx->target_matrices.end(),    out_matrices);
    if (out_quaternions) std::copy(ctx->target_quaternions.begin(), ctx->target_quaternions.end(), out_quaternions);
}

void spring_vrm_context_read_debug(
    const SpringVrmContext* ctx,
    float* out_current_heads,
    float* out_current_tails,
    float* out_prev_tails,
    float* out_current_pose_tails,
    float* out_hit_radii,
    std::int32_t* out_collided_by_groups,
    std::int32_t* out_collider_types,
    std::int32_t* out_collider_groups,
    float* out_collider_centers,
    float* out_collider_segment_a,
    float* out_collider_segment_b,
    float* out_collider_radii)
{
    if (!ctx || ctx->bone_count <= 0) return;

    if (out_current_heads) {
        std::copy(ctx->current_heads.begin(), ctx->current_heads.end(), out_current_heads);
    }
    if (out_current_tails) {
        std::copy(ctx->current_tails.begin(), ctx->current_tails.end(), out_current_tails);
    }
    if (out_prev_tails) {
        std::copy(ctx->prev_tails.begin(), ctx->prev_tails.end(), out_prev_tails);
    }
    if (out_current_pose_tails) {
        std::copy(ctx->current_pose_tails.begin(), ctx->current_pose_tails.end(), out_current_pose_tails);
    }
    if (out_hit_radii) {
        std::copy(ctx->hit_radii.begin(), ctx->hit_radii.end(), out_hit_radii);
    }
    if (out_collided_by_groups) {
        std::copy(ctx->collided_by_groups.begin(), ctx->collided_by_groups.end(), out_collided_by_groups);
    }

    if (ctx->collider_count <= 0) return;
    if (out_collider_types) {
        std::copy(ctx->collider_types.begin(), ctx->collider_types.end(), out_collider_types);
    }
    if (out_collider_groups) {
        std::copy(ctx->collider_groups.begin(), ctx->collider_groups.end(), out_collider_groups);
    }
    if (out_collider_centers) {
        std::copy(ctx->collider_centers.begin(), ctx->collider_centers.end(), out_collider_centers);
    }
    if (out_collider_segment_a) {
        std::copy(ctx->collider_segment_a.begin(), ctx->collider_segment_a.end(), out_collider_segment_a);
    }
    if (out_collider_segment_b) {
        std::copy(ctx->collider_segment_b.begin(), ctx->collider_segment_b.end(), out_collider_segment_b);
    }
    if (out_collider_radii) {
        std::copy(ctx->collider_radii.begin(), ctx->collider_radii.end(), out_collider_radii);
    }
}

void spring_vrm_context_free(SpringVrmContext* ctx) {
    delete ctx;
}

}  // namespace hotools
