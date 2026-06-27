#include "hotools_spring_bone_vrm.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace hotools {
namespace {

constexpr float kEpsilon = 0.000001f;

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

        const float radius = std::max(view.collider_radii[collider], 0.0f) + hit_radius;
        if (radius <= kEpsilon) {
            continue;
        }

        float center_x = view.collider_centers[collider * 3 + 0];
        float center_y = view.collider_centers[collider * 3 + 1];
        float center_z = view.collider_centers[collider * 3 + 2];

        if (view.collider_types[collider] == 1) {
            closest_point_on_segment(
                tail[0],
                tail[1],
                tail[2],
                view.collider_segment_a + collider * 3,
                view.collider_segment_b + collider * 3,
                center_x,
                center_y,
                center_z);
        }

        const float dx = tail[0] - center_x;
        const float dy = tail[1] - center_y;
        const float dz = tail[2] - center_z;
        if (dx * dx + dy * dy + dz * dz >= radius * radius) {
            continue;
        }

        float nx = 0.0f;
        float ny = 0.0f;
        float nz = 1.0f;
        safe_normal_with_fallback(dx, dy, dz, fallback_axis[0], fallback_axis[1], fallback_axis[2], nx, ny, nz);
        const float pushed[3] = {
            center_x + nx * radius,
            center_y + ny * radius,
            center_z + nz * radius,
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
    normalize3(gravity_dir[0], gravity_dir[1], gravity_dir[2]);
    const float gravity_scale = std::max(view.gravity_power, 0.0f);

    float root_quaternion[4] = {
        view.root_quaternion[0],
        view.root_quaternion[1],
        view.root_quaternion[2],
        view.root_quaternion[3],
    };
    quat_normalize(root_quaternion, root_quaternion);

    std::vector<float> target_quaternions(static_cast<std::size_t>(view.bone_count) * 4u, 0.0f);

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

}  // namespace hotools
