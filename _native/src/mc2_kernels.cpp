#include "mc2_kernels.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <vector>

namespace hotools {
namespace {

constexpr float kMc2Epsilon = 0.00000001f;
constexpr float kDistanceHorizontalStiffness = 0.5f;
constexpr float kDistanceFixedInverseMass = 1.0f / 50.0f;
constexpr float kDistanceVelocityAttenuation = 0.3f;
constexpr float kFrictionMass = 3.0f;
constexpr float kDepthMass = 5.0f;
constexpr float kSelfCollisionFixedMass = 100.0f;
constexpr float kSelfCollisionFrictionMass = 10.0f;
constexpr float kSelfCollisionClothMass = 50.0f;
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
constexpr float kTriangleBendingFixedInverseMass = 0.01f;
constexpr float kTriangleVolumeScale = 1000.0f;

constexpr float kAngleLimitAttenuation = 0.9f;
constexpr float kAngleRestorationVelocityAttenuation = 0.8f;
constexpr float kAngleRestorationGravityFalloff = 0.0f;
constexpr float kDirectionDotDeadzone = 1.0e-7f;
constexpr float kPi = 3.14159265358979323846f;
constexpr std::uint8_t kMc2AttrMove = 1u << 2u;
constexpr int kColliderSphere = 0;
constexpr int kColliderCapsule = 1;
constexpr int kColliderPlane = 2;
constexpr int kColliderBox = 3;

float clamp_float(float value, float lo, float hi) {
    return std::max(lo, std::min(hi, value));
}

float sample_curve16_values(const float* values, float depth) {
    depth = clamp_float(depth, 0.0f, 1.0f);
    const float scaled = depth * 15.0f;
    const auto lower = static_cast<std::int32_t>(std::floor(scaled));
    const auto upper = std::min(lower + 1, 15);
    const float ratio = scaled - static_cast<float>(lower);
    return values[lower] * (1.0f - ratio) + values[upper] * ratio;
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
    if (half_x <= kMc2Epsilon || half_y <= kMc2Epsilon || half_z <= kMc2Epsilon) {
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
    const float uz_len = std::sqrt(uz_x * uz_x + uz_y * uz_y + uz_z * uz_z);
    if (uz_len <= kMc2Epsilon) {
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
    const float outside_distance = std::sqrt(outside_x * outside_x + outside_y * outside_y + outside_z * outside_z);
    if (outside_distance > kMc2Epsilon) {
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

float closest_point_segment_ratio(float px,
                                  float py,
                                  float pz,
                                  float ax,
                                  float ay,
                                  float az,
                                  float bx,
                                  float by,
                                  float bz) {
    const float ab_x = bx - ax;
    const float ab_y = by - ay;
    const float ab_z = bz - az;
    const float denom = dot3(ab_x, ab_y, ab_z, ab_x, ab_y, ab_z);
    if (denom <= kMc2Epsilon) {
        return 0.0f;
    }
    return clamp_float(dot3(px - ax, py - ay, pz - az, ab_x, ab_y, ab_z) / denom, 0.0f, 1.0f);
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

float intersect_point_plane_dist(float plane_x,
                                 float plane_y,
                                 float plane_z,
                                 float normal_x,
                                 float normal_y,
                                 float normal_z,
                                 float pos_x,
                                 float pos_y,
                                 float pos_z,
                                 float& out_x,
                                 float& out_y,
                                 float& out_z) {
    const float vx = pos_x - plane_x;
    const float vy = pos_y - plane_y;
    const float vz = pos_z - plane_z;
    const float projected = dot3(vx, vy, vz, normal_x, normal_y, normal_z);
    const float gv_x = normal_x * projected;
    const float gv_y = normal_y * projected;
    const float gv_z = normal_z * projected;
    const float len = length3(gv_x, gv_y, gv_z);
    if (dot3(normal_x, normal_y, normal_z, vx, vy, vz) < 0.0f) {
        out_x = pos_x - gv_x;
        out_y = pos_y - gv_y;
        out_z = pos_z - gv_z;
        return -len;
    }
    out_x = pos_x;
    out_y = pos_y;
    out_z = pos_z;
    return len;
}

void quat_normalize(const float in_q[4], float out_q[4]) {
    const float length =
        std::sqrt(in_q[0] * in_q[0] + in_q[1] * in_q[1] + in_q[2] * in_q[2] + in_q[3] * in_q[3]);
    if (length <= kMc2Epsilon) {
        out_q[0] = 0.0f;
        out_q[1] = 0.0f;
        out_q[2] = 0.0f;
        out_q[3] = 1.0f;
        return;
    }
    const float inv_length = 1.0f / length;
    out_q[0] = in_q[0] * inv_length;
    out_q[1] = in_q[1] * inv_length;
    out_q[2] = in_q[2] * inv_length;
    out_q[3] = in_q[3] * inv_length;
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

float quat_dot_abs(const float a[4], const float b[4]) {
    float qa[4];
    float qb[4];
    quat_normalize(a, qa);
    quat_normalize(b, qb);
    return std::fabs(qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3]);
}

void quat_slerp(const float a[4], const float b[4], float ratio, float out_q[4]) {
    const float t = clamp_float(ratio, 0.0f, 1.0f);
    float qa[4];
    float qb[4];
    quat_normalize(a, qa);
    quat_normalize(b, qb);
    float dot = qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3];
    if (dot < 0.0f) {
        qb[0] = -qb[0];
        qb[1] = -qb[1];
        qb[2] = -qb[2];
        qb[3] = -qb[3];
        dot = -dot;
    }
    if (dot > 0.9995f) {
        const float mixed[4] = {
            qa[0] + (qb[0] - qa[0]) * t,
            qa[1] + (qb[1] - qa[1]) * t,
            qa[2] + (qb[2] - qa[2]) * t,
            qa[3] + (qb[3] - qa[3]) * t,
        };
        quat_normalize(mixed, out_q);
        return;
    }
    const float theta0 = std::acos(clamp_float(dot, -1.0f, 1.0f));
    const float theta = theta0 * t;
    const float sin_theta = std::sin(theta);
    const float sin_theta0 = std::sin(theta0);
    const float s0 = std::cos(theta) - dot * sin_theta / sin_theta0;
    const float s1 = sin_theta / sin_theta0;
    const float mixed[4] = {
        s0 * qa[0] + s1 * qb[0],
        s0 * qa[1] + s1 * qb[1],
        s0 * qa[2] + s1 * qb[2],
        s0 * qa[3] + s1 * qb[3],
    };
    quat_normalize(mixed, out_q);
}

void quat_inverse(const float q[4], float out_q[4]) {
    float normalized[4];
    quat_normalize(q, normalized);
    out_q[0] = -normalized[0];
    out_q[1] = -normalized[1];
    out_q[2] = -normalized[2];
    out_q[3] = normalized[3];
}

void quat_multiply(const float a[4], const float b[4], float out_q[4]) {
    const float raw[4] = {
        a[3] * b[0] + b[3] * a[0] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] + b[3] * a[1] + a[2] * b[0] - a[0] * b[2],
        a[3] * b[2] + b[3] * a[2] + a[0] * b[1] - a[1] * b[0],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    };
    quat_normalize(raw, out_q);
}

bool inverse_matrix3(const float matrix[9], float inverse[9]) {
    const float determinant =
        matrix[0] * (matrix[4] * matrix[8] - matrix[5] * matrix[7]) -
        matrix[1] * (matrix[3] * matrix[8] - matrix[5] * matrix[6]) +
        matrix[2] * (matrix[3] * matrix[7] - matrix[4] * matrix[6]);
    if (std::fabs(determinant) <= kMc2Epsilon) return false;
    const float scale = 1.0f / determinant;
    inverse[0] = (matrix[4] * matrix[8] - matrix[5] * matrix[7]) * scale;
    inverse[1] = (matrix[2] * matrix[7] - matrix[1] * matrix[8]) * scale;
    inverse[2] = (matrix[1] * matrix[5] - matrix[2] * matrix[4]) * scale;
    inverse[3] = (matrix[5] * matrix[6] - matrix[3] * matrix[8]) * scale;
    inverse[4] = (matrix[0] * matrix[8] - matrix[2] * matrix[6]) * scale;
    inverse[5] = (matrix[2] * matrix[3] - matrix[0] * matrix[5]) * scale;
    inverse[6] = (matrix[3] * matrix[7] - matrix[4] * matrix[6]) * scale;
    inverse[7] = (matrix[1] * matrix[6] - matrix[0] * matrix[7]) * scale;
    inverse[8] = (matrix[0] * matrix[4] - matrix[1] * matrix[3]) * scale;
    return true;
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

void safe_normal_with_fallback(float x,
                              float y,
                              float z,
                              float fallback_x,
                              float fallback_y,
                              float fallback_z,
                              float& out_x,
                              float& out_y,
                              float& out_z);

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

void perpendicular(float vx, float vy, float vz, float& out_x, float& out_y, float& out_z) {
    float axis_x = 1.0f;
    float axis_y = 0.0f;
    float axis_z = 0.0f;
    float nx = 0.0f;
    float ny = 0.0f;
    float nz = 1.0f;
    safe_normal_or_z(vx, vy, vz, nx, ny, nz);
    if (std::fabs(dot3(nx, ny, nz, axis_x, axis_y, axis_z)) > 0.85f) {
        axis_x = 0.0f;
        axis_y = 1.0f;
        axis_z = 0.0f;
    }
    float cross_x = 0.0f;
    float cross_y = 0.0f;
    float cross_z = 0.0f;
    cross3(nx, ny, nz, axis_x, axis_y, axis_z, cross_x, cross_y, cross_z);
    safe_normal_or_z(cross_x, cross_y, cross_z, out_x, out_y, out_z);
}

void frame_rotation(float forward_x,
                    float forward_y,
                    float forward_z,
                    float normal_x,
                    float normal_y,
                    float normal_z,
                    float out_q[4]) {
    float z_x = 0.0f;
    float z_y = 0.0f;
    float z_z = 1.0f;
    safe_normal_with_fallback(forward_x, forward_y, forward_z, normal_x, normal_y, normal_z, z_x, z_y, z_z);
    float up_x = 0.0f;
    float up_y = 0.0f;
    float up_z = 1.0f;
    safe_normal_or_z(normal_x, normal_y, normal_z, up_x, up_y, up_z);
    float x_x = 0.0f;
    float x_y = 0.0f;
    float x_z = 0.0f;
    cross3(up_x, up_y, up_z, z_x, z_y, z_z, x_x, x_y, x_z);
    if (length3(x_x, x_y, x_z) <= kMc2Epsilon) {
        perpendicular(z_x, z_y, z_z, x_x, x_y, x_z);
    } else {
        safe_normal_or_z(x_x, x_y, x_z, x_x, x_y, x_z);
    }
    float y_x = 0.0f;
    float y_y = 0.0f;
    float y_z = 0.0f;
    cross3(z_x, z_y, z_z, x_x, x_y, x_z, y_x, y_y, y_z);
    safe_normal_with_fallback(y_x, y_y, y_z, up_x, up_y, up_z, y_x, y_y, y_z);
    const float matrix[9] = {
        x_x, y_x, z_x,
        x_y, y_y, z_y,
        x_z, y_z, z_z,
    };
    quat_from_matrix3(matrix, out_q);
}

void motion_axis_vector(int normal_axis, float& out_x, float& out_y, float& out_z) {
    out_x = 0.0f;
    out_y = 1.0f;
    out_z = 0.0f;
    switch (normal_axis) {
    case 0:
        out_x = 1.0f;
        out_y = 0.0f;
        out_z = 0.0f;
        break;
    case 2:
        out_x = 0.0f;
        out_y = 0.0f;
        out_z = 1.0f;
        break;
    case 3:
        out_x = -1.0f;
        out_y = 0.0f;
        out_z = 0.0f;
        break;
    case 4:
        out_x = 0.0f;
        out_y = -1.0f;
        out_z = 0.0f;
        break;
    case 5:
        out_x = 0.0f;
        out_y = 0.0f;
        out_z = -1.0f;
        break;
    default:
        break;
    }
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
    if (dot >= 1.0f - kDirectionDotDeadzone || ratio <= kMc2Epsilon) {
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
    if (dot < -1.0f + kMc2Epsilon) {
        const bool use_y = src_x > src_y && src_x > src_z;
        const float helper_x = use_y ? 0.0f : 1.0f;
        const float helper_y = use_y ? 1.0f : 0.0f;
        const float helper_z = 0.0f;
        float cross_x = 0.0f;
        float cross_y = 0.0f;
        float cross_z = 0.0f;
        cross3(src_x, src_y, src_z, helper_x, helper_y, helper_z, cross_x, cross_y, cross_z);
        safe_normal_or_z(cross_x, cross_y, cross_z, axis_x, axis_y, axis_z);
        angle = kPi * ratio;
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

void clamp_vector_angle(float vx,
                        float vy,
                        float vz,
                        float target_x,
                        float target_y,
                        float target_z,
                        float angle_rad,
                        float& out_x,
                        float& out_y,
                        float& out_z) {
    const float length = std::sqrt(vx * vx + vy * vy + vz * vz);
    if (length <= kMc2Epsilon) {
        out_x = vx;
        out_y = vy;
        out_z = vz;
        return;
    }
    const float target_length = std::sqrt(target_x * target_x + target_y * target_y + target_z * target_z);
    if (target_length <= kMc2Epsilon) {
        out_x = vx;
        out_y = vy;
        out_z = vz;
        return;
    }
    const float v_dir_x = vx / length;
    const float v_dir_y = vy / length;
    const float v_dir_z = vz / length;
    const float t_dir_x = target_x / target_length;
    const float t_dir_y = target_y / target_length;
    const float t_dir_z = target_z / target_length;
    const float dot = clamp_float(dot3(v_dir_x, v_dir_y, v_dir_z, t_dir_x, t_dir_y, t_dir_z), -1.0f, 1.0f);
    const float current_angle = std::acos(dot);
    if (current_angle <= angle_rad) {
        out_x = vx;
        out_y = vy;
        out_z = vz;
        return;
    }
    float q[4];
    from_to_rotation(t_dir_x, t_dir_y, t_dir_z, v_dir_x, v_dir_y, v_dir_z,
                     std::max(angle_rad, 0.0f) / std::max(current_angle, kMc2Epsilon), q);
    float rotated_x = 0.0f;
    float rotated_y = 0.0f;
    float rotated_z = 0.0f;
    quat_rotate(q, t_dir_x, t_dir_y, t_dir_z, rotated_x, rotated_y, rotated_z);
    out_x = rotated_x * length;
    out_y = rotated_y * length;
    out_z = rotated_z * length;
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
            float rest = std::fabs(rest_dist);
            const float animation_pose_ratio = clamp_float(view.animation_pose_ratio, 0.0f, 1.0f);
            if (view.base_positions != nullptr && animation_pose_ratio > kMc2Epsilon) {
                const std::int64_t base_offset = vertex * 3;
                const std::int64_t base_neighbor_offset = static_cast<std::int64_t>(neighbor) * 3;
                const float bdx = view.base_positions[base_neighbor_offset + 0] - view.base_positions[base_offset + 0];
                const float bdy = view.base_positions[base_neighbor_offset + 1] - view.base_positions[base_offset + 1];
                const float bdz = view.base_positions[base_neighbor_offset + 2] - view.base_positions[base_offset + 2];
                const float animated_rest = std::sqrt(bdx * bdx + bdy * bdy + bdz * bdz);
                rest = rest * (1.0f - animation_pose_ratio) + animated_rest * animation_pose_ratio;
            }
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
        view.base_rotations == nullptr || view.inv_masses == nullptr || view.max_distances == nullptr ||
        view.stiffness_values == nullptr || view.backstop_radii == nullptr || view.backstop_distances == nullptr) {
        return;
    }

    bool use_max_distance = view.explicit_enable_flags && view.max_distance_enabled;
    bool use_backstop = view.explicit_enable_flags && view.backstop_enabled;
    bool has_stiffness = false;
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (!view.explicit_enable_flags && view.max_distances[vertex] > kMc2Epsilon) {
            use_max_distance = true;
        }
        if (!view.explicit_enable_flags && view.backstop_radii[vertex] > kMc2Epsilon) {
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
        const float limit = std::max(view.max_distances[vertex], 0.0f);
        const float backstop_radius = std::max(view.backstop_radii[vertex], 0.0f);
        const bool apply_max_distance = use_max_distance &&
            (view.explicit_enable_flags || limit > kMc2Epsilon);
        if (!apply_max_distance && (!use_backstop || backstop_radius <= kMc2Epsilon)) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        const float original_x = view.positions[offset + 0];
        const float original_y = view.positions[offset + 1];
        const float original_z = view.positions[offset + 2];
        float constrained_x = original_x;
        float constrained_y = original_y;
        float constrained_z = original_z;

        if (apply_max_distance) {
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
        const float max_constrained_x = constrained_x;
        const float max_constrained_y = constrained_y;
        const float max_constrained_z = constrained_z;

        if (use_backstop && backstop_radius > kMc2Epsilon) {
            float axis_x = 0.0f;
            float axis_y = 1.0f;
            float axis_z = 0.0f;
            motion_axis_vector(view.normal_axis, axis_x, axis_y, axis_z);
            const float* base_rot = &view.base_rotations[vertex * 4];
            float nx = 0.0f;
            float ny = 1.0f;
            float nz = 0.0f;
            quat_rotate(base_rot, axis_x, axis_y, axis_z, nx, ny, nz);
            safe_normal_with_fallback(nx, ny, nz, 0.0f, 1.0f, 0.0f, nx, ny, nz);
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
        if (view.debug_record_origins != nullptr &&
            view.debug_record_corrections != nullptr &&
            view.debug_record_valid != nullptr) {
            const auto max_record = static_cast<std::size_t>(vertex);
            const auto backstop_record = static_cast<std::size_t>(
                view.vertex_count + vertex
            );
            const auto max_offset = max_record * 3;
            const auto backstop_offset = backstop_record * 3;
            const float max_next_x = original_x * (1.0f - clamped_stiffness) +
                max_constrained_x * clamped_stiffness;
            const float max_next_y = original_y * (1.0f - clamped_stiffness) +
                max_constrained_y * clamped_stiffness;
            const float max_next_z = original_z * (1.0f - clamped_stiffness) +
                max_constrained_z * clamped_stiffness;
            const float max_add_x = max_next_x - original_x;
            const float max_add_y = max_next_y - original_y;
            const float max_add_z = max_next_z - original_z;
            view.debug_record_origins[max_offset + 0] = original_x;
            view.debug_record_origins[max_offset + 1] = original_y;
            view.debug_record_origins[max_offset + 2] = original_z;
            view.debug_record_corrections[max_offset + 0] = max_add_x;
            view.debug_record_corrections[max_offset + 1] = max_add_y;
            view.debug_record_corrections[max_offset + 2] = max_add_z;
            view.debug_record_valid[max_record] = apply_max_distance ? 1 : 0;
            view.debug_record_origins[backstop_offset + 0] = original_x + max_add_x;
            view.debug_record_origins[backstop_offset + 1] = original_y + max_add_y;
            view.debug_record_origins[backstop_offset + 2] = original_z + max_add_z;
            view.debug_record_corrections[backstop_offset + 0] = add_x - max_add_x;
            view.debug_record_corrections[backstop_offset + 1] = add_y - max_add_y;
            view.debug_record_corrections[backstop_offset + 2] = add_z - max_add_z;
            view.debug_record_valid[backstop_record] =
                use_backstop && backstop_radius > kMc2Epsilon ? 1 : 0;
        }
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
            view.velocities[offset + 0] = velocity_x * view.velocity_weight;
            view.velocities[offset + 1] = velocity_y * view.velocity_weight;
            view.velocities[offset + 2] = velocity_z * view.velocity_weight;
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
        const bool soft_sphere = view.soft_sphere && view.velocity_positions != nullptr &&
                                 view.max_lengths != nullptr;
        const float max_length = soft_sphere ? view.max_lengths[vertex] : 0.0f;

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
            float normal_x = 0.0f;
            float normal_y = 0.0f;
            float normal_z = 1.0f;
            float surface_distance = 0.0f;
            const int collider_type = view.collider_types[collider];

            if (collider_type == kColliderPlane) {
                safe_normal_or_z(view.collider_segment_a[collider_offset + 0],
                                 view.collider_segment_a[collider_offset + 1],
                                 view.collider_segment_a[collider_offset + 2],
                                 normal_x,
                                 normal_y,
                                 normal_z);
                const float plane_x = view.collider_centers[collider_offset + 0] + normal_x * hit_radius;
                const float plane_y = view.collider_centers[collider_offset + 1] + normal_y * hit_radius;
                const float plane_z = view.collider_centers[collider_offset + 2] + normal_z * hit_radius;
                surface_distance =
                    dot3(origin_x - plane_x, origin_y - plane_y, origin_z - plane_z, normal_x, normal_y, normal_z);
            } else if (collider_type == kColliderBox) {
                const float center_x = view.collider_centers[collider_offset + 0];
                const float center_y = view.collider_centers[collider_offset + 1];
                const float center_z = view.collider_centers[collider_offset + 2];
                const float axis_xx = view.collider_segment_a[collider_offset + 0];
                const float axis_xy = view.collider_segment_a[collider_offset + 1];
                const float axis_xz = view.collider_segment_a[collider_offset + 2];
                const float axis_yx = view.collider_segment_b[collider_offset + 0];
                const float axis_yy = view.collider_segment_b[collider_offset + 1];
                const float axis_yz = view.collider_segment_b[collider_offset + 2];
                const float signed_half_z = view.collider_radii[collider];
                if (!box_collision_surface(origin_x,
                                           origin_y,
                                           origin_z,
                                           hit_radius,
                                           center_x,
                                           center_y,
                                           center_z,
                                           axis_xx,
                                           axis_xy,
                                           axis_xz,
                                           axis_yx,
                                           axis_yy,
                                           axis_yz,
                                           signed_half_z,
                                           normal_x,
                                           normal_y,
                                           normal_z,
                                           surface_distance)) {
                    continue;
                }
            } else {
                const float collider_radius = std::max(view.collider_radii[collider], 0.0f);
                const float radius = hit_radius + collider_radius;
                if (radius <= kMc2Epsilon) {
                    continue;
                }

                float current_center_x = view.collider_centers[collider_offset + 0];
                float current_center_y = view.collider_centers[collider_offset + 1];
                float current_center_z = view.collider_centers[collider_offset + 2];
                float old_center_x = view.collider_old_centers != nullptr
                                         ? view.collider_old_centers[collider_offset + 0]
                                         : current_center_x;
                float old_center_y = view.collider_old_centers != nullptr
                                         ? view.collider_old_centers[collider_offset + 1]
                                         : current_center_y;
                float old_center_z = view.collider_old_centers != nullptr
                                         ? view.collider_old_centers[collider_offset + 2]
                                         : current_center_z;
                if (collider_type == kColliderCapsule) {
                    const float old_ax = view.collider_old_segment_a != nullptr
                                             ? view.collider_old_segment_a[collider_offset + 0]
                                             : view.collider_segment_a[collider_offset + 0];
                    const float old_ay = view.collider_old_segment_a != nullptr
                                             ? view.collider_old_segment_a[collider_offset + 1]
                                             : view.collider_segment_a[collider_offset + 1];
                    const float old_az = view.collider_old_segment_a != nullptr
                                             ? view.collider_old_segment_a[collider_offset + 2]
                                             : view.collider_segment_a[collider_offset + 2];
                    const float old_bx = view.collider_old_segment_b != nullptr
                                             ? view.collider_old_segment_b[collider_offset + 0]
                                             : view.collider_segment_b[collider_offset + 0];
                    const float old_by = view.collider_old_segment_b != nullptr
                                             ? view.collider_old_segment_b[collider_offset + 1]
                                             : view.collider_segment_b[collider_offset + 1];
                    const float old_bz = view.collider_old_segment_b != nullptr
                                             ? view.collider_old_segment_b[collider_offset + 2]
                                             : view.collider_segment_b[collider_offset + 2];
                    const float old_sx = old_bx - old_ax;
                    const float old_sy = old_by - old_ay;
                    const float old_sz = old_bz - old_az;
                    const float denom = old_sx * old_sx + old_sy * old_sy + old_sz * old_sz;
                    float t = 0.0f;
                    if (denom > kMc2Epsilon) {
                        t = ((origin_x - old_ax) * old_sx + (origin_y - old_ay) * old_sy +
                             (origin_z - old_az) * old_sz) /
                            denom;
                        t = clamp_float(t, 0.0f, 1.0f);
                    }
                    old_center_x = old_ax + old_sx * t;
                    old_center_y = old_ay + old_sy * t;
                    old_center_z = old_az + old_sz * t;

                    const float current_ax = view.collider_segment_a[collider_offset + 0];
                    const float current_ay = view.collider_segment_a[collider_offset + 1];
                    const float current_az = view.collider_segment_a[collider_offset + 2];
                    const float current_bx = view.collider_segment_b[collider_offset + 0];
                    const float current_by = view.collider_segment_b[collider_offset + 1];
                    const float current_bz = view.collider_segment_b[collider_offset + 2];
                    current_center_x = current_ax + (current_bx - current_ax) * t;
                    current_center_y = current_ay + (current_by - current_ay) * t;
                    current_center_z = current_az + (current_bz - current_az) * t;
                }

                const float dx = origin_x - old_center_x;
                const float dy = origin_y - old_center_y;
                const float dz = origin_z - old_center_z;
                safe_normal_with_fallback(dx, dy, dz, fallback_x, fallback_y, fallback_z, normal_x, normal_y, normal_z);
                const float plane_x = current_center_x + normal_x * radius;
                const float plane_y = current_center_y + normal_y * radius;
                const float plane_z = current_center_z + normal_z * radius;
                surface_distance =
                    dot3(origin_x - plane_x, origin_y - plane_y, origin_z - plane_z, normal_x, normal_y, normal_z);
            }
            if (soft_sphere && collider_type == kColliderSphere && max_length > 0.0f) {
                surface_distance *= 3.0f;
            }
            if (surface_distance <= friction_range) {
                const float collider_distance = std::max(surface_distance, 0.0f);
                const float near_friction = 1.0f - clamp_float(collider_distance / friction_range, 0.0f, 1.0f);
                if (near_friction > friction_value) {
                    friction_value = near_friction;
                }
                friction_normal_x += normal_x;
                friction_normal_y += normal_y;
                friction_normal_z += normal_z;
            }
            if (surface_distance >= 0.0f) {
                continue;
            }

            float correction_x = -normal_x * surface_distance;
            float correction_y = -normal_y * surface_distance;
            float correction_z = -normal_z * surface_distance;
            if (soft_sphere && collider_type == kColliderSphere && max_length > 0.0f) {
                correction_x /= 3.0f;
                correction_y /= 3.0f;
                correction_z /= 3.0f;
                float projected_x = origin_x + correction_x;
                float projected_y = origin_y + correction_y;
                float projected_z = origin_z + correction_z;
                const float base_dx = projected_x - view.base_positions[offset + 0];
                const float base_dy = projected_y - view.base_positions[offset + 1];
                const float base_dz = projected_z - view.base_positions[offset + 2];
                const float base_length = length3(base_dx, base_dy, base_dz);
                if (base_length > max_length && base_length > kMc2Epsilon) {
                    const float scale = max_length / base_length;
                    projected_x = view.base_positions[offset + 0] + base_dx * scale;
                    projected_y = view.base_positions[offset + 1] + base_dy * scale;
                    projected_z = view.base_positions[offset + 2] + base_dz * scale;
                }
                const float limited_dx = projected_x - view.base_positions[offset + 0];
                const float limited_dy = projected_y - view.base_positions[offset + 1];
                const float limited_dz = projected_z - view.base_positions[offset + 2];
                const float limited_length = length3(limited_dx, limited_dy, limited_dz);
                const float rebound = clamp_float(limited_length / hit_radius, 0.0f, 1.0f) * 0.85f;
                projected_x += (origin_x - projected_x) * rebound;
                projected_y += (origin_y - projected_y) * rebound;
                projected_z += (origin_z - projected_z) * rebound;
                correction_x = projected_x - origin_x;
                correction_y = projected_y - origin_y;
                correction_z = projected_z - origin_z;
            }
            if (view.debug_contacts != nullptr) {
                Mc2ExternalCollisionDebugRecord record;
                record.primitive_kind = 0;
                record.primitive_index = static_cast<std::int32_t>(vertex);
                record.collider_index = static_cast<std::int32_t>(collider);
                record.position[0] = origin_x + correction_x;
                record.position[1] = origin_y + correction_y;
                record.position[2] = origin_z + correction_z;
                record.normal[0] = normal_x;
                record.normal[1] = normal_y;
                record.normal[2] = normal_z;
                record.correction[0] = correction_x;
                record.correction[1] = correction_y;
                record.correction[2] = correction_z;
                view.debug_contacts->push_back(record);
            }
            add_x += correction_x;
            add_y += correction_y;
            add_z += correction_z;
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
        const float average_add_x = add_x * inv_add_count;
        const float average_add_y = add_y * inv_add_count;
        const float average_add_z = add_z * inv_add_count;
        view.positions[offset + 0] = origin_x + average_add_x * blend;
        view.positions[offset + 1] = origin_y + average_add_y * blend;
        view.positions[offset + 2] = origin_z + average_add_z * blend;
        if (soft_sphere) {
            view.velocity_positions[offset + 0] += average_add_x;
            view.velocity_positions[offset + 1] += average_add_y;
            view.velocity_positions[offset + 2] += average_add_z;
        }
        const float inv_normal_length = 1.0f / normal_length;
        view.collision_normals[offset + 0] = add_normal_x * inv_normal_length;
        view.collision_normals[offset + 1] = add_normal_y * inv_normal_length;
        view.collision_normals[offset + 2] = add_normal_z * inv_normal_length;
        if (view.friction != nullptr && 1.0f > view.friction[vertex]) {
            view.friction[vertex] = 1.0f;
        }
    }
}

bool edge_sphere_detection(const Mc2EdgeCollisionView& view,
                           std::int64_t collider,
                           float p0x,
                           float p0y,
                           float p0z,
                           float p1x,
                           float p1y,
                           float p1z,
                           float radius0,
                           float radius1,
                           float cfr,
                           float& out_dist,
                           float out_p0[3],
                           float out_p1[3],
                           float out_normal[3]) {
    const std::int64_t co = collider * 3;
    const float cold_x = view.collider_old_centers != nullptr ? view.collider_old_centers[co + 0]
                                                              : view.collider_centers[co + 0];
    const float cold_y = view.collider_old_centers != nullptr ? view.collider_old_centers[co + 1]
                                                              : view.collider_centers[co + 1];
    const float cold_z = view.collider_old_centers != nullptr ? view.collider_old_centers[co + 2]
                                                              : view.collider_centers[co + 2];
    const float cpos_x = view.collider_centers[co + 0];
    const float cpos_y = view.collider_centers[co + 1];
    const float cpos_z = view.collider_centers[co + 2];
    const float cradius = std::max(view.collider_radii[collider], 0.0f);
    const float s = closest_point_segment_ratio(cold_x, cold_y, cold_z, p0x, p0y, p0z, p1x, p1y, p1z);
    const float cx = p0x + (p1x - p0x) * s;
    const float cy = p0y + (p1y - p0y) * s;
    const float cz = p0z + (p1z - p0z) * s;
    const float vx = cx - cold_x;
    const float vy = cy - cold_y;
    const float vz = cz - cold_z;
    const float clen = length3(vx, vy, vz);
    if (clen < 1e-9f) {
        return false;
    }
    const float nx = vx / clen;
    const float ny = vy / clen;
    const float nz = vz / clen;
    out_normal[0] = nx;
    out_normal[1] = ny;
    out_normal[2] = nz;
    const float db_x = cpos_x - cold_x;
    const float db_y = cpos_y - cold_y;
    const float db_z = cpos_z - cold_z;
    const float l1 = dot3(nx, ny, nz, db_x, db_y, db_z);
    const float l = clen - l1;
    const float rA = radius0 + (radius1 - radius0) * s;
    const float thickness = rA + cradius;
    if (l > thickness + cfr) {
        return false;
    }
    const float current_l = dot3(nx, ny, nz, cx - cpos_x, cy - cpos_y, cz - cpos_z);
    if (current_l > thickness) {
        out_dist = current_l - thickness;
        out_p0[0] = p0x;
        out_p0[1] = p0y;
        out_p0[2] = p0z;
        out_p1[0] = p1x;
        out_p1[1] = p1y;
        out_p1[2] = p1z;
        return true;
    }
    const float separation = thickness - current_l;
    const float b0 = 1.0f - s;
    const float b1 = s;
    const float denom = b0 * b0 + b1 * b1;
    if (denom == 0.0f) {
        return false;
    }
    const float scale = separation / denom;
    out_p0[0] = p0x + nx * b0 * scale;
    out_p0[1] = p0y + ny * b0 * scale;
    out_p0[2] = p0z + nz * b0 * scale;
    out_p1[0] = p1x + nx * b1 * scale;
    out_p1[1] = p1y + ny * b1 * scale;
    out_p1[2] = p1z + nz * b1 * scale;
    out_dist = -separation;
    return true;
}

bool edge_capsule_detection(const Mc2EdgeCollisionView& view,
                            std::int64_t collider,
                            float p0x,
                            float p0y,
                            float p0z,
                            float p1x,
                            float p1y,
                            float p1z,
                            float radius0,
                            float radius1,
                            float cfr,
                            float& out_dist,
                            float out_p0[3],
                            float out_p1[3],
                            float out_normal[3]) {
    const std::int64_t co = collider * 3;
    const float old_ax = view.collider_old_segment_a != nullptr ? view.collider_old_segment_a[co + 0]
                                                                : view.collider_segment_a[co + 0];
    const float old_ay = view.collider_old_segment_a != nullptr ? view.collider_old_segment_a[co + 1]
                                                                : view.collider_segment_a[co + 1];
    const float old_az = view.collider_old_segment_a != nullptr ? view.collider_old_segment_a[co + 2]
                                                                : view.collider_segment_a[co + 2];
    const float old_bx = view.collider_old_segment_b != nullptr ? view.collider_old_segment_b[co + 0]
                                                                : view.collider_segment_b[co + 0];
    const float old_by = view.collider_old_segment_b != nullptr ? view.collider_old_segment_b[co + 1]
                                                                : view.collider_segment_b[co + 1];
    const float old_bz = view.collider_old_segment_b != nullptr ? view.collider_old_segment_b[co + 2]
                                                                : view.collider_segment_b[co + 2];
    const float cur_ax = view.collider_segment_a[co + 0];
    const float cur_ay = view.collider_segment_a[co + 1];
    const float cur_az = view.collider_segment_a[co + 2];
    const float cur_bx = view.collider_segment_b[co + 0];
    const float cur_by = view.collider_segment_b[co + 1];
    const float cur_bz = view.collider_segment_b[co + 2];
    const float sr = std::max(view.collider_radii[collider], 0.0f);
    const float er = sr;
    float s = 0.0f;
    float t = 0.0f;
    float cax = 0.0f;
    float cay = 0.0f;
    float caz = 0.0f;
    float cbx = 0.0f;
    float cby = 0.0f;
    float cbz = 0.0f;
    const float dist_sq = closest_segment_segment(p0x, p0y, p0z, p1x, p1y, p1z, old_ax, old_ay, old_az, old_bx, old_by,
                                                  old_bz, s, t, cax, cay, caz, cbx, cby, cbz);
    float clen = std::sqrt(std::max(dist_sq, 0.0f));
    if (clen < 1e-9f) {
        return false;
    }
    float nx = (cax - cbx) / clen;
    float ny = (cay - cby) / clen;
    float nz = (caz - cbz) / clen;
    if (sr != er) {
        float dummy_c1x = 0.0f;
        float dummy_c1y = 0.0f;
        float dummy_c1z = 0.0f;
        float dummy_c2x = 0.0f;
        float dummy_c2y = 0.0f;
        float dummy_c2z = 0.0f;
        closest_segment_segment(p0x, p0y, p0z, p1x, p1y, p1z, old_ax + nx * sr, old_ay + ny * sr,
                                old_az + nz * sr, old_bx + nx * er, old_by + ny * er, old_bz + nz * er, s, t,
                                dummy_c1x, dummy_c1y, dummy_c1z, dummy_c2x, dummy_c2y, dummy_c2z);
        cax = p0x + (p1x - p0x) * s;
        cay = p0y + (p1y - p0y) * s;
        caz = p0z + (p1z - p0z) * s;
        cbx = old_ax + (old_bx - old_ax) * t;
        cby = old_ay + (old_by - old_ay) * t;
        cbz = old_az + (old_bz - old_az) * t;
        clen = length3(cax - cbx, cay - cby, caz - cbz);
        if (clen < 1e-9f) {
            return false;
        }
        nx = (cax - cbx) / clen;
        ny = (cay - cby) / clen;
        nz = (caz - cbz) / clen;
    }
    out_normal[0] = nx;
    out_normal[1] = ny;
    out_normal[2] = nz;
    const float d0x = cur_ax - old_ax;
    const float d0y = cur_ay - old_ay;
    const float d0z = cur_az - old_az;
    const float d1x = cur_bx - old_bx;
    const float d1y = cur_by - old_by;
    const float d1z = cur_bz - old_bz;
    const float db_x = d0x + (d1x - d0x) * t;
    const float db_y = d0y + (d1y - d0y) * t;
    const float db_z = d0z + (d1z - d0z) * t;
    const float l = clen - dot3(nx, ny, nz, db_x, db_y, db_z);
    const float rA = radius0 + (radius1 - radius0) * s;
    const float rB = sr + (er - sr) * t;
    const float thickness = rA + rB;
    if (l > thickness + cfr) {
        return false;
    }
    const float current_collider_x = cur_ax + (cur_bx - cur_ax) * t;
    const float current_collider_y = cur_ay + (cur_by - cur_ay) * t;
    const float current_collider_z = cur_az + (cur_bz - cur_az) * t;
    const float current_l = dot3(nx, ny, nz, cax - current_collider_x, cay - current_collider_y,
                                 caz - current_collider_z);
    if (current_l > thickness) {
        out_dist = current_l - thickness;
        out_p0[0] = p0x;
        out_p0[1] = p0y;
        out_p0[2] = p0z;
        out_p1[0] = p1x;
        out_p1[1] = p1y;
        out_p1[2] = p1z;
        return true;
    }
    const float separation = thickness - current_l;
    const float b0 = 1.0f - s;
    const float b1 = s;
    const float denom = b0 * b0 + b1 * b1;
    if (denom == 0.0f) {
        return false;
    }
    const float scale = separation / denom;
    out_p0[0] = p0x + nx * b0 * scale;
    out_p0[1] = p0y + ny * b0 * scale;
    out_p0[2] = p0z + nz * b0 * scale;
    out_p1[0] = p1x + nx * b1 * scale;
    out_p1[1] = p1y + ny * b1 * scale;
    out_p1[2] = p1z + nz * b1 * scale;
    out_dist = -separation;
    return true;
}

bool edge_plane_detection(const Mc2EdgeCollisionView& view,
                          std::int64_t collider,
                          float p0x,
                          float p0y,
                          float p0z,
                          float p1x,
                          float p1y,
                          float p1z,
                          float radius0,
                          float radius1,
                          float& out_dist,
                          float out_p0[3],
                          float out_p1[3],
                          float out_normal[3]) {
    const std::int64_t co = collider * 3;
    float nx = 0.0f;
    float ny = 0.0f;
    float nz = 1.0f;
    safe_normal_or_z(view.collider_segment_a[co + 0], view.collider_segment_a[co + 1],
                     view.collider_segment_a[co + 2], nx, ny, nz);
    out_normal[0] = nx;
    out_normal[1] = ny;
    out_normal[2] = nz;
    const float center_x = view.collider_centers[co + 0];
    const float center_y = view.collider_centers[co + 1];
    const float center_z = view.collider_centers[co + 2];
    const float dist0 = intersect_point_plane_dist(center_x + nx * radius0, center_y + ny * radius0,
                                                   center_z + nz * radius0, nx, ny, nz, p0x, p0y, p0z, out_p0[0],
                                                   out_p0[1], out_p0[2]);
    const float dist1 = intersect_point_plane_dist(center_x + nx * radius1, center_y + ny * radius1,
                                                   center_z + nz * radius1, nx, ny, nz, p1x, p1y, p1z, out_p1[0],
                                                   out_p1[1], out_p1[2]);
    out_dist = std::min(dist0, dist1);
    return true;
}

bool edge_box_detection(const Mc2EdgeCollisionView& view,
                        std::int64_t collider,
                        float p0x,
                        float p0y,
                        float p0z,
                        float p1x,
                        float p1y,
                        float p1z,
                        float radius0,
                        float radius1,
                        float cfr,
                        float& out_dist,
                        float out_p0[3],
                        float out_p1[3],
                        float out_normal[3]) {
    const std::int64_t co = collider * 3;
    const float center_x = view.collider_centers[co + 0];
    const float center_y = view.collider_centers[co + 1];
    const float center_z = view.collider_centers[co + 2];
    const float axis_xx = view.collider_segment_a[co + 0];
    const float axis_xy = view.collider_segment_a[co + 1];
    const float axis_xz = view.collider_segment_a[co + 2];
    const float axis_yx = view.collider_segment_b[co + 0];
    const float axis_yy = view.collider_segment_b[co + 1];
    const float axis_yz = view.collider_segment_b[co + 2];
    const float signed_half_z = view.collider_radii[collider];

    const float candidates[3] = {0.0f, 0.5f, 1.0f};
    bool found = false;
    float best_score = 3.402823466e+38F;
    float best_s = 0.0f;
    float best_dist = 0.0f;
    float best_normal[3] = {0.0f, 0.0f, 1.0f};

    for (float s : candidates) {
        const float point_x = p0x + (p1x - p0x) * s;
        const float point_y = p0y + (p1y - p0y) * s;
        const float point_z = p0z + (p1z - p0z) * s;
        const float radius = radius0 + (radius1 - radius0) * s;
        float normal_x = 0.0f;
        float normal_y = 0.0f;
        float normal_z = 1.0f;
        float dist = 0.0f;
        if (!box_collision_surface(point_x,
                                   point_y,
                                   point_z,
                                   radius,
                                   center_x,
                                   center_y,
                                   center_z,
                                   axis_xx,
                                   axis_xy,
                                   axis_xz,
                                   axis_yx,
                                   axis_yy,
                                   axis_yz,
                                   signed_half_z,
                                   normal_x,
                                   normal_y,
                                   normal_z,
                                   dist)) {
            continue;
        }
        const float score = dist > 0.0f ? dist - cfr : dist;
        if (!found || score < best_score) {
            found = true;
            best_score = score;
            best_s = s;
            best_dist = dist;
            best_normal[0] = normal_x;
            best_normal[1] = normal_y;
            best_normal[2] = normal_z;
        }
    }

    if (!found || best_dist > cfr) {
        return false;
    }

    out_normal[0] = best_normal[0];
    out_normal[1] = best_normal[1];
    out_normal[2] = best_normal[2];
    if (best_dist > 0.0f) {
        out_dist = best_dist;
        out_p0[0] = p0x;
        out_p0[1] = p0y;
        out_p0[2] = p0z;
        out_p1[0] = p1x;
        out_p1[1] = p1y;
        out_p1[2] = p1z;
        return true;
    }

    const float separation = -best_dist;
    const float b0 = 1.0f - best_s;
    const float b1 = best_s;
    const float denom = b0 * b0 + b1 * b1;
    if (denom <= kMc2Epsilon) {
        return false;
    }
    const float scale = separation / denom;
    out_p0[0] = p0x + best_normal[0] * b0 * scale;
    out_p0[1] = p0y + best_normal[1] * b0 * scale;
    out_p0[2] = p0z + best_normal[2] * b0 * scale;
    out_p1[0] = p1x + best_normal[0] * b1 * scale;
    out_p1[1] = p1y + best_normal[1] * b1 * scale;
    out_p1[2] = p1z + best_normal[2] * b1 * scale;
    out_dist = best_dist;
    return true;
}

void project_edge_collisions_mc2(Mc2EdgeCollisionView& view) {
    if (view.vertex_count <= 0 || view.edge_count <= 0 || view.collider_count <= 0 || view.positions == nullptr ||
        view.edges == nullptr || view.attributes == nullptr || view.collision_radii == nullptr ||
        view.collision_normals == nullptr || view.collider_types == nullptr || view.collider_group_bits == nullptr ||
        view.collider_centers == nullptr || view.collider_segment_a == nullptr || view.collider_segment_b == nullptr ||
        view.collider_radii == nullptr || view.collided_by_groups == 0) {
        return;
    }
    std::vector<float> add_positions(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<float> add_normals(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<std::int32_t> add_counts(static_cast<std::size_t>(view.vertex_count), 0);
    std::vector<float> friction_values(static_cast<std::size_t>(view.vertex_count), 0.0f);

    // Edge collision uses mesh edges as collider segments, not structural constraints.
    for (std::int64_t edge_index = 0; edge_index < view.edge_count; ++edge_index) {
        const std::int32_t v0 = view.edges[edge_index * 2 + 0];
        const std::int32_t v1 = view.edges[edge_index * 2 + 1];
        if (v0 < 0 || v1 < 0 || static_cast<std::int64_t>(v0) >= view.vertex_count ||
            static_cast<std::int64_t>(v1) >= view.vertex_count || v0 == v1) {
            continue;
        }
        const bool move0 = (view.attributes[v0] & view.move_attribute_mask) != 0;
        const bool move1 = (view.attributes[v1] & view.move_attribute_mask) != 0;
        if (!move0 && !move1) {
            continue;
        }
        const float radius0 = view.collision_radii[v0];
        const float radius1 = view.collision_radii[v1];
        if (radius0 <= kMc2Epsilon && radius1 <= kMc2Epsilon) {
            continue;
        }
        const float cfr = (radius0 + radius1) * 0.5f;
        const std::int64_t o0 = static_cast<std::int64_t>(v0) * 3;
        const std::int64_t o1 = static_cast<std::int64_t>(v1) * 3;
        const float p0x = view.positions[o0 + 0];
        const float p0y = view.positions[o0 + 1];
        const float p0z = view.positions[o0 + 2];
        const float p1x = view.positions[o1 + 0];
        const float p1y = view.positions[o1 + 1];
        const float p1z = view.positions[o1 + 2];
        float add0[3] = {};
        float add1[3] = {};
        float add_normal[3] = {};
        int add_count = 0;
        bool has_friction_contact = false;
        float min_dist = 3.402823466e+38F;
        float collision_normal[3] = {};

        for (std::int64_t collider = 0; collider < view.collider_count; ++collider) {
            if ((view.collided_by_groups & view.collider_group_bits[collider]) == 0) {
                continue;
            }
            float dist = 0.0f;
            float out0[3] = {p0x, p0y, p0z};
            float out1[3] = {p1x, p1y, p1z};
            float normal[3] = {0.0f, 0.0f, 1.0f};
            bool hit = false;
            const int collider_type = view.collider_types[collider];
            if (collider_type == kColliderSphere) {
                hit = edge_sphere_detection(view, collider, p0x, p0y, p0z, p1x, p1y, p1z, radius0, radius1, cfr,
                                            dist, out0, out1, normal);
            } else if (collider_type == kColliderCapsule) {
                hit = edge_capsule_detection(view, collider, p0x, p0y, p0z, p1x, p1y, p1z, radius0, radius1, cfr,
                                             dist, out0, out1, normal);
            } else if (collider_type == kColliderPlane) {
                hit = edge_plane_detection(view, collider, p0x, p0y, p0z, p1x, p1y, p1z, radius0, radius1, dist,
                                           out0, out1, normal);
            } else if (collider_type == kColliderBox) {
                hit = edge_box_detection(view, collider, p0x, p0y, p0z, p1x, p1y, p1z, radius0, radius1, cfr, dist,
                                         out0, out1, normal);
            }
            if (!hit) {
                continue;
            }
            if (dist <= 0.0f) {
                if (view.debug_contacts != nullptr) {
                    Mc2ExternalCollisionDebugRecord record;
                    record.primitive_kind = 1;
                    record.primitive_index = static_cast<std::int32_t>(edge_index);
                    record.collider_index = static_cast<std::int32_t>(collider);
                    record.position[0] = (out0[0] + out1[0]) * 0.5f;
                    record.position[1] = (out0[1] + out1[1]) * 0.5f;
                    record.position[2] = (out0[2] + out1[2]) * 0.5f;
                    record.normal[0] = normal[0];
                    record.normal[1] = normal[1];
                    record.normal[2] = normal[2];
                    record.correction[0] = (
                        (out0[0] - p0x) + (out1[0] - p1x)
                    ) * 0.5f;
                    record.correction[1] = (
                        (out0[1] - p0y) + (out1[1] - p1y)
                    ) * 0.5f;
                    record.correction[2] = (
                        (out0[2] - p0z) + (out1[2] - p1z)
                    ) * 0.5f;
                    view.debug_contacts->push_back(record);
                }
                add0[0] += out0[0] - p0x;
                add0[1] += out0[1] - p0y;
                add0[2] += out0[2] - p0z;
                add1[0] += out1[0] - p1x;
                add1[1] += out1[1] - p1y;
                add1[2] += out1[2] - p1z;
                add_normal[0] += normal[0];
                add_normal[1] += normal[1];
                add_normal[2] += normal[2];
                ++add_count;
            }
            if (dist <= cfr) {
                has_friction_contact = true;
                collision_normal[0] += normal[0];
                collision_normal[1] += normal[1];
                collision_normal[2] += normal[2];
                min_dist = std::min(min_dist, dist);
            }
        }

        if (add_count > 0) {
            const float inv_count = 1.0f / static_cast<float>(add_count);
            const float avg_nx = add_normal[0] * inv_count;
            const float avg_ny = add_normal[1] * inv_count;
            const float avg_nz = add_normal[2] * inv_count;
            const float normal_len = length3(avg_nx, avg_ny, avg_nz);
            if (normal_len > kMc2Epsilon) {
                const float blend = std::min(normal_len, 1.0f);
                add_positions[o0 + 0] += add0[0] * inv_count * blend;
                add_positions[o0 + 1] += add0[1] * inv_count * blend;
                add_positions[o0 + 2] += add0[2] * inv_count * blend;
                add_positions[o1 + 0] += add1[0] * inv_count * blend;
                add_positions[o1 + 1] += add1[1] * inv_count * blend;
                add_positions[o1 + 2] += add1[2] * inv_count * blend;
                ++add_counts[v0];
                ++add_counts[v1];
            }
        }

        const float collision_normal_len_sq =
            dot3(collision_normal[0], collision_normal[1], collision_normal[2], collision_normal[0],
                 collision_normal[1], collision_normal[2]);
        if (has_friction_contact && cfr > 0.0f && collision_normal_len_sq > 1e-6f) {
            const float friction_value = 1.0f - clamp_float(min_dist / cfr, 0.0f, 1.0f);
            const float inv_len = 1.0f / std::sqrt(collision_normal_len_sq);
            const float nx = collision_normal[0] * inv_len;
            const float ny = collision_normal[1] * inv_len;
            const float nz = collision_normal[2] * inv_len;
            if (move0) {
                friction_values[v0] = std::max(friction_values[v0], friction_value);
                add_normals[o0 + 0] += nx;
                add_normals[o0 + 1] += ny;
                add_normals[o0 + 2] += nz;
            }
            if (move1) {
                friction_values[v1] = std::max(friction_values[v1], friction_value);
                add_normals[o1 + 0] += nx;
                add_normals[o1 + 1] += ny;
                add_normals[o1 + 2] += nz;
            }
        }
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t offset = vertex * 3;
        const int count = add_counts[vertex];
        if (count > 0) {
            const float inv_count = 1.0f / static_cast<float>(count);
            view.positions[offset + 0] += add_positions[offset + 0] * inv_count;
            view.positions[offset + 1] += add_positions[offset + 1] * inv_count;
            view.positions[offset + 2] += add_positions[offset + 2] * inv_count;
        }
        if (view.friction != nullptr && friction_values[vertex] > view.friction[vertex]) {
            view.friction[vertex] = friction_values[vertex];
        }
        const float normal_len = length3(add_normals[offset + 0], add_normals[offset + 1], add_normals[offset + 2]);
        if (normal_len > kMc2Epsilon) {
            const float inv_len = 1.0f / normal_len;
            view.collision_normals[offset + 0] = add_normals[offset + 0] * inv_len;
            view.collision_normals[offset + 1] = add_normals[offset + 1] * inv_len;
            view.collision_normals[offset + 2] = add_normals[offset + 2] * inv_len;
        }
    }
}

void project_triangle_bending_mc2(Mc2TriangleBendingView& view) {
    if (view.vertex_count <= 0 || (view.dihedral_count <= 0 && view.volume_count <= 0) ||
        view.positions == nullptr || view.inv_masses == nullptr || view.stiffness_values == nullptr) {
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

    std::vector<float> add_positions(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<std::int32_t> add_counts(static_cast<std::size_t>(view.vertex_count), 0);

    auto add_correction = [&](const std::int32_t vertices[4], const float corrections[12]) {
        for (int local = 0; local < 4; ++local) {
            const std::int32_t vertex = vertices[local];
            if (view.inv_masses[vertex] <= kMc2Epsilon) {
                continue;
            }
            const std::int64_t offset = static_cast<std::int64_t>(vertex) * 3;
            add_positions[static_cast<std::size_t>(offset + 0)] += corrections[local * 3 + 0];
            add_positions[static_cast<std::size_t>(offset + 1)] += corrections[local * 3 + 1];
            add_positions[static_cast<std::size_t>(offset + 2)] += corrections[local * 3 + 2];
            add_counts[static_cast<std::size_t>(vertex)] += 1;
        }
    };

    for (std::int64_t pair_index = 0; pair_index < view.dihedral_count; ++pair_index) {
        if (view.dihedral_pairs == nullptr || view.dihedral_rest_angles == nullptr || view.dihedral_signs == nullptr) {
            break;
        }
        std::int32_t vertices[4];
        bool valid = true;
        for (int local = 0; local < 4; ++local) {
            vertices[local] = view.dihedral_pairs[pair_index * 4 + local];
            if (vertices[local] < 0 || static_cast<std::int64_t>(vertices[local]) >= view.vertex_count) {
                valid = false;
            }
        }
        if (!valid) {
            continue;
        }

        float local_stiffness = 0.0f;
        float inv_mass_buffer[4];
        float inv_mass_sum = 0.0f;
        for (int local = 0; local < 4; ++local) {
            local_stiffness += clamp_float(view.stiffness_values[vertices[local]], 0.0f, 1.0f);
            const float raw_inv_mass = view.inv_masses[vertices[local]];
            inv_mass_buffer[local] =
                raw_inv_mass <= kMc2Epsilon ? kTriangleBendingFixedInverseMass : raw_inv_mass;
            inv_mass_sum += inv_mass_buffer[local];
        }
        local_stiffness *= 0.25f;
        if (local_stiffness <= kMc2Epsilon || inv_mass_sum <= kMc2Epsilon) {
            continue;
        }

        float p[12];
        for (int local = 0; local < 4; ++local) {
            const std::int64_t offset = static_cast<std::int64_t>(vertices[local]) * 3;
            p[local * 3 + 0] = view.positions[offset + 0];
            p[local * 3 + 1] = view.positions[offset + 1];
            p[local * 3 + 2] = view.positions[offset + 2];
        }

        const float edge_x = p[9] - p[6];
        const float edge_y = p[10] - p[7];
        const float edge_z = p[11] - p[8];
        const float edge_length = std::sqrt(edge_x * edge_x + edge_y * edge_y + edge_z * edge_z);
        if (edge_length < kMc2Epsilon) {
            continue;
        }
        const float inv_edge_length = 1.0f / edge_length;

        float n1_x = 0.0f;
        float n1_y = 0.0f;
        float n1_z = 0.0f;
        float n2_x = 0.0f;
        float n2_y = 0.0f;
        float n2_z = 0.0f;
        cross3(p[6] - p[0], p[7] - p[1], p[8] - p[2], p[9] - p[0], p[10] - p[1], p[11] - p[2],
               n1_x, n1_y, n1_z);
        cross3(p[9] - p[3], p[10] - p[4], p[11] - p[5], p[6] - p[3], p[7] - p[4], p[8] - p[5],
               n2_x, n2_y, n2_z);
        const float n1_len_sq = dot3(n1_x, n1_y, n1_z, n1_x, n1_y, n1_z);
        const float n2_len_sq = dot3(n2_x, n2_y, n2_z, n2_x, n2_y, n2_z);
        if (n1_len_sq <= kMc2Epsilon || n2_len_sq <= kMc2Epsilon) {
            continue;
        }

        const float n1_grad_x = n1_x / n1_len_sq;
        const float n1_grad_y = n1_y / n1_len_sq;
        const float n1_grad_z = n1_z / n1_len_sq;
        const float n2_grad_x = n2_x / n2_len_sq;
        const float n2_grad_y = n2_y / n2_len_sq;
        const float n2_grad_z = n2_z / n2_len_sq;

        float gradients[12];
        gradients[0] = edge_length * n1_grad_x;
        gradients[1] = edge_length * n1_grad_y;
        gradients[2] = edge_length * n1_grad_z;
        gradients[3] = edge_length * n2_grad_x;
        gradients[4] = edge_length * n2_grad_y;
        gradients[5] = edge_length * n2_grad_z;
        const float dot_p0p3_edge =
            dot3(p[0] - p[9], p[1] - p[10], p[2] - p[11], edge_x, edge_y, edge_z) * inv_edge_length;
        const float dot_p1p3_edge =
            dot3(p[3] - p[9], p[4] - p[10], p[5] - p[11], edge_x, edge_y, edge_z) * inv_edge_length;
        gradients[6] = dot_p0p3_edge * n1_grad_x + dot_p1p3_edge * n2_grad_x;
        gradients[7] = dot_p0p3_edge * n1_grad_y + dot_p1p3_edge * n2_grad_y;
        gradients[8] = dot_p0p3_edge * n1_grad_z + dot_p1p3_edge * n2_grad_z;
        const float dot_p2p0_edge =
            dot3(p[6] - p[0], p[7] - p[1], p[8] - p[2], edge_x, edge_y, edge_z) * inv_edge_length;
        const float dot_p2p1_edge =
            dot3(p[6] - p[3], p[7] - p[4], p[8] - p[5], edge_x, edge_y, edge_z) * inv_edge_length;
        gradients[9] = dot_p2p0_edge * n1_grad_x + dot_p2p1_edge * n2_grad_x;
        gradients[10] = dot_p2p0_edge * n1_grad_y + dot_p2p1_edge * n2_grad_y;
        gradients[11] = dot_p2p0_edge * n1_grad_z + dot_p2p1_edge * n2_grad_z;

        float n1_norm_x = 0.0f;
        float n1_norm_y = 0.0f;
        float n1_norm_z = 1.0f;
        float n2_norm_x = 0.0f;
        float n2_norm_y = 0.0f;
        float n2_norm_z = 1.0f;
        safe_normal_or_z(n1_grad_x, n1_grad_y, n1_grad_z, n1_norm_x, n1_norm_y, n1_norm_z);
        safe_normal_or_z(n2_grad_x, n2_grad_y, n2_grad_z, n2_norm_x, n2_norm_y, n2_norm_z);
        const float dot_norm = clamp_float(dot3(n1_norm_x, n1_norm_y, n1_norm_z, n2_norm_x, n2_norm_y, n2_norm_z),
                                           -1.0f, 1.0f);
        float phi = std::acos(dot_norm);

        float lamb = 0.0f;
        for (int local = 0; local < 4; ++local) {
            lamb += inv_mass_buffer[local] *
                     dot3(gradients[local * 3 + 0], gradients[local * 3 + 1], gradients[local * 3 + 2],
                          gradients[local * 3 + 0], gradients[local * 3 + 1], gradients[local * 3 + 2]);
        }
        if (lamb <= kMc2Epsilon) {
            continue;
        }

        float cross_norm_x = 0.0f;
        float cross_norm_y = 0.0f;
        float cross_norm_z = 0.0f;
        cross3(n1_norm_x, n1_norm_y, n1_norm_z, n2_norm_x, n2_norm_y, n2_norm_z, cross_norm_x, cross_norm_y,
               cross_norm_z);
        const float dir_value = dot3(cross_norm_x, cross_norm_y, cross_norm_z, edge_x, edge_y, edge_z);
        const float dir_sign = dir_value < 0.0f ? -1.0f : 1.0f;
        const float sign = view.dihedral_signs[pair_index] < 0 ? -1.0f : 1.0f;
        if (std::fabs(sign) > kMc2Epsilon) {
            phi *= dir_sign;
        } else {
            lamb *= dir_sign;
        }

        const float rest_angle = view.dihedral_rest_angles[pair_index] * sign;
        const float angle_error = rest_angle - phi;
        if (std::fabs(angle_error) <= 1.0e-3f) {
            continue;
        }
        lamb = angle_error / lamb * local_stiffness;
        float corrections[12];
        for (int local = 0; local < 4; ++local) {
            corrections[local * 3 + 0] = -inv_mass_buffer[local] * lamb * gradients[local * 3 + 0];
            corrections[local * 3 + 1] = -inv_mass_buffer[local] * lamb * gradients[local * 3 + 1];
            corrections[local * 3 + 2] = -inv_mass_buffer[local] * lamb * gradients[local * 3 + 2];
        }
        add_correction(vertices, corrections);
    }

    for (std::int64_t pair_index = 0; pair_index < view.volume_count; ++pair_index) {
        if (view.volume_pairs == nullptr || view.volume_rest == nullptr) {
            break;
        }
        std::int32_t vertices[4];
        bool valid = true;
        for (int local = 0; local < 4; ++local) {
            vertices[local] = view.volume_pairs[pair_index * 4 + local];
            if (vertices[local] < 0 || static_cast<std::int64_t>(vertices[local]) >= view.vertex_count) {
                valid = false;
            }
        }
        if (!valid) {
            continue;
        }

        float local_stiffness = 0.0f;
        float inv_mass_buffer[4];
        float inv_mass_sum = 0.0f;
        for (int local = 0; local < 4; ++local) {
            local_stiffness += clamp_float(view.stiffness_values[vertices[local]], 0.0f, 1.0f);
            const float raw_inv_mass = view.inv_masses[vertices[local]];
            inv_mass_buffer[local] =
                raw_inv_mass <= kMc2Epsilon ? kTriangleBendingFixedInverseMass : raw_inv_mass;
            inv_mass_sum += inv_mass_buffer[local];
        }
        local_stiffness *= 0.25f;
        if (local_stiffness <= kMc2Epsilon || inv_mass_sum <= kMc2Epsilon) {
            continue;
        }

        float p[12];
        for (int local = 0; local < 4; ++local) {
            const std::int64_t offset = static_cast<std::int64_t>(vertices[local]) * 3;
            p[local * 3 + 0] = view.positions[offset + 0];
            p[local * 3 + 1] = view.positions[offset + 1];
            p[local * 3 + 2] = view.positions[offset + 2];
        }

        float cross_p1p0_p2p0_x = 0.0f;
        float cross_p1p0_p2p0_y = 0.0f;
        float cross_p1p0_p2p0_z = 0.0f;
        cross3(p[3] - p[0], p[4] - p[1], p[5] - p[2], p[6] - p[0], p[7] - p[1], p[8] - p[2],
               cross_p1p0_p2p0_x, cross_p1p0_p2p0_y, cross_p1p0_p2p0_z);
        const float volume = (1.0f / 6.0f) *
                             dot3(cross_p1p0_p2p0_x, cross_p1p0_p2p0_y, cross_p1p0_p2p0_z,
                                  p[9] - p[0], p[10] - p[1], p[11] - p[2]) *
                             kTriangleVolumeScale;

        float gradients[12];
        cross3(p[3] - p[6], p[4] - p[7], p[5] - p[8], p[9] - p[6], p[10] - p[7], p[11] - p[8],
               gradients[0], gradients[1], gradients[2]);
        cross3(p[6] - p[0], p[7] - p[1], p[8] - p[2], p[9] - p[0], p[10] - p[1], p[11] - p[2],
               gradients[3], gradients[4], gradients[5]);
        cross3(p[0] - p[3], p[1] - p[4], p[2] - p[5], p[9] - p[3], p[10] - p[4], p[11] - p[5],
               gradients[6], gradients[7], gradients[8]);
        cross3(p[3] - p[0], p[4] - p[1], p[5] - p[2], p[6] - p[0], p[7] - p[1], p[8] - p[2],
               gradients[9], gradients[10], gradients[11]);

        float lamb = 0.0f;
        for (int local = 0; local < 4; ++local) {
            lamb += inv_mass_buffer[local] *
                     dot3(gradients[local * 3 + 0], gradients[local * 3 + 1], gradients[local * 3 + 2],
                          gradients[local * 3 + 0], gradients[local * 3 + 1], gradients[local * 3 + 2]);
        }
        lamb *= kTriangleVolumeScale;
        if (std::fabs(lamb) <= kMc2Epsilon) {
            continue;
        }

        const float rest_volume = view.volume_rest[pair_index];
        const float volume_error = rest_volume - volume;
        if (std::fabs(volume_error) <= std::max(1.0e-6f, std::fabs(rest_volume) * 2.0e-6f)) {
            continue;
        }
        lamb = local_stiffness * volume_error / lamb;
        float corrections[12];
        for (int local = 0; local < 4; ++local) {
            corrections[local * 3 + 0] = inv_mass_buffer[local] * lamb * gradients[local * 3 + 0];
            corrections[local * 3 + 1] = inv_mass_buffer[local] * lamb * gradients[local * 3 + 1];
            corrections[local * 3 + 2] = inv_mass_buffer[local] * lamb * gradients[local * 3 + 2];
        }
        add_correction(vertices, corrections);
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int32_t count = add_counts[static_cast<std::size_t>(vertex)];
        if (count <= 0) {
            continue;
        }
        const std::int64_t offset = vertex * 3;
        const float inv_count = 1.0f / static_cast<float>(count);
        view.positions[offset + 0] += add_positions[static_cast<std::size_t>(offset + 0)] * inv_count;
        view.positions[offset + 1] += add_positions[static_cast<std::size_t>(offset + 1)] * inv_count;
        view.positions[offset + 2] += add_positions[static_cast<std::size_t>(offset + 2)] * inv_count;
    }
}

void project_angle_constraints_mc2(Mc2AngleConstraintView& view) {
    if (view.vertex_count <= 0 || view.baseline_data_count <= 0 || view.line_count <= 0 ||
        view.positions == nullptr || view.inv_masses == nullptr || view.parent_indices == nullptr ||
        view.baseline_start == nullptr || view.baseline_count == nullptr || view.baseline_data == nullptr ||
        view.step_basic_positions == nullptr || view.step_basic_rotations == nullptr ||
        view.velocity_positions == nullptr) {
        return;
    }

    bool use_restoration = view.explicit_enable_flags
        ? view.restoration_enabled
        : view.restoration_values != nullptr;
    bool use_limit = view.explicit_enable_flags
        ? view.limit_enabled
        : view.limit_values != nullptr;
    bool has_restoration = false;
    bool has_limit = false;
    if (use_restoration && !view.explicit_enable_flags) {
        for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
            if (view.restoration_values[vertex] > kMc2Epsilon) {
                has_restoration = true;
                break;
            }
        }
    }
    if (use_limit && !view.explicit_enable_flags) {
        for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
            if (view.limit_values[vertex] > kMc2Epsilon) {
                has_limit = true;
                break;
            }
        }
    }
    if (!view.explicit_enable_flags) {
        use_restoration = use_restoration && has_restoration;
        use_limit = use_limit && has_limit;
    }
    if (!use_restoration && !use_limit) {
        return;
    }

    const float limit_stiffness = clamp_float(view.limit_stiffness, 0.0f, 1.0f);
    const bool debug_records =
        view.debug_record_origins != nullptr &&
        view.debug_record_corrections != nullptr &&
        view.debug_record_currents != nullptr &&
        view.debug_record_limits != nullptr &&
        view.debug_record_valid != nullptr;
    const auto debug_record_index = [&](int branch, int iteration, std::int64_t data_index) {
        return (
            (static_cast<std::size_t>(branch) * kMc2AngleIterationCount +
             static_cast<std::size_t>(iteration)) *
                static_cast<std::size_t>(view.baseline_data_count) +
            static_cast<std::size_t>(data_index)
        );
    };
    const auto debug_begin = [&](std::size_t record, std::int32_t parent, std::int32_t child) {
        if (!debug_records) return;
        const auto parent_offset = static_cast<std::size_t>(parent) * 3;
        const auto child_offset = static_cast<std::size_t>(child) * 3;
        const auto debug_offset = record * 2 * 3;
        for (std::size_t component = 0; component < 3; ++component) {
            view.debug_record_origins[debug_offset + component] =
                view.positions[parent_offset + component];
            view.debug_record_origins[debug_offset + 3 + component] =
                view.positions[child_offset + component];
        }
        view.debug_record_valid[record] = 1;
    };
    const auto debug_add = [&] (
        std::size_t record,
        float parent_x, float parent_y, float parent_z,
        float child_x, float child_y, float child_z
    ) {
        if (!debug_records) return;
        const auto debug_offset = record * 2 * 3;
        view.debug_record_corrections[debug_offset + 0] += parent_x;
        view.debug_record_corrections[debug_offset + 1] += parent_y;
        view.debug_record_corrections[debug_offset + 2] += parent_z;
        view.debug_record_corrections[debug_offset + 3] += child_x;
        view.debug_record_corrections[debug_offset + 4] += child_y;
        view.debug_record_corrections[debug_offset + 5] += child_z;
    };

    std::vector<float> length_buffer(static_cast<std::size_t>(view.vertex_count), 0.0f);
    std::vector<float> local_pos_buffer(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);
    std::vector<float> local_rot_buffer(static_cast<std::size_t>(view.vertex_count) * 4, 0.0f);
    std::vector<float> rotation_buffer(static_cast<std::size_t>(view.vertex_count) * 4, 0.0f);
    std::vector<float> restoration_vector_buffer(static_cast<std::size_t>(view.vertex_count) * 3, 0.0f);

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t rot_offset = vertex * 4;
        rotation_buffer[static_cast<std::size_t>(rot_offset + 0)] = view.step_basic_rotations[rot_offset + 0];
        rotation_buffer[static_cast<std::size_t>(rot_offset + 1)] = view.step_basic_rotations[rot_offset + 1];
        rotation_buffer[static_cast<std::size_t>(rot_offset + 2)] = view.step_basic_rotations[rot_offset + 2];
        rotation_buffer[static_cast<std::size_t>(rot_offset + 3)] = view.step_basic_rotations[rot_offset + 3];
        local_rot_buffer[static_cast<std::size_t>(rot_offset + 3)] = 1.0f;
    }

    for (std::int64_t line_index = 0; line_index < view.line_count; ++line_index) {
        const std::int32_t start = view.baseline_start[line_index];
        const std::int32_t count = view.baseline_count[line_index];
        if (start < 0 || count <= 1 || static_cast<std::int64_t>(start) + count > view.baseline_data_count) {
            continue;
        }

        for (std::int32_t local = 0; local < count; ++local) {
            const std::int64_t data_index = static_cast<std::int64_t>(start) + local;
            const std::int32_t vertex_index = view.baseline_data[data_index];
            if (vertex_index < 0 || static_cast<std::int64_t>(vertex_index) >= view.vertex_count) {
                continue;
            }
            const std::int64_t rot_offset = static_cast<std::int64_t>(vertex_index) * 4;
            rotation_buffer[static_cast<std::size_t>(rot_offset + 0)] = view.step_basic_rotations[rot_offset + 0];
            rotation_buffer[static_cast<std::size_t>(rot_offset + 1)] = view.step_basic_rotations[rot_offset + 1];
            rotation_buffer[static_cast<std::size_t>(rot_offset + 2)] = view.step_basic_rotations[rot_offset + 2];
            rotation_buffer[static_cast<std::size_t>(rot_offset + 3)] = view.step_basic_rotations[rot_offset + 3];
            if (local <= 0) {
                continue;
            }
            const std::int32_t parent_index = view.parent_indices[vertex_index];
            if (parent_index < 0 || static_cast<std::int64_t>(parent_index) >= view.vertex_count) {
                continue;
            }
            const std::int64_t vertex_offset = static_cast<std::int64_t>(vertex_index) * 3;
            const std::int64_t parent_offset = static_cast<std::int64_t>(parent_index) * 3;
            const float base_x = view.step_basic_positions[vertex_offset + 0] - view.step_basic_positions[parent_offset + 0];
            const float base_y = view.step_basic_positions[vertex_offset + 1] - view.step_basic_positions[parent_offset + 1];
            const float base_z = view.step_basic_positions[vertex_offset + 2] - view.step_basic_positions[parent_offset + 2];

            if (use_limit) {
                const float cur_x = view.positions[vertex_offset + 0] - view.positions[parent_offset + 0];
                const float cur_y = view.positions[vertex_offset + 1] - view.positions[parent_offset + 1];
                const float cur_z = view.positions[vertex_offset + 2] - view.positions[parent_offset + 2];
                const float current_length = std::sqrt(cur_x * cur_x + cur_y * cur_y + cur_z * cur_z);
                const float base_length = std::sqrt(base_x * base_x + base_y * base_y + base_z * base_z);
                const std::int64_t local_pos_offset = static_cast<std::int64_t>(vertex_index) * 3;
                const std::int64_t local_rot_offset = static_cast<std::int64_t>(vertex_index) * 4;
                if (current_length > kMc2Epsilon && base_length > kMc2Epsilon) {
                    float parent_rot_inv[4];
                    quat_inverse(&view.step_basic_rotations[static_cast<std::int64_t>(parent_index) * 4], parent_rot_inv);
                    length_buffer[static_cast<std::size_t>(vertex_index)] = current_length;
                    float local_x = 0.0f;
                    float local_y = 0.0f;
                    float local_z = 0.0f;
                    quat_rotate(parent_rot_inv, base_x / base_length, base_y / base_length, base_z / base_length,
                                local_x, local_y, local_z);
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 0)] = local_x;
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 1)] = local_y;
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 2)] = local_z;
                    float local_rot[4];
                    quat_mul(parent_rot_inv, &view.step_basic_rotations[rot_offset], local_rot);
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 0)] = local_rot[0];
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 1)] = local_rot[1];
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 2)] = local_rot[2];
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 3)] = local_rot[3];
                } else {
                    length_buffer[static_cast<std::size_t>(vertex_index)] = 0.0f;
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 0)] = 0.0f;
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 1)] = 0.0f;
                    local_pos_buffer[static_cast<std::size_t>(local_pos_offset + 2)] = 0.0f;
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 0)] = 0.0f;
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 1)] = 0.0f;
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 2)] = 0.0f;
                    local_rot_buffer[static_cast<std::size_t>(local_rot_offset + 3)] = 1.0f;
                }
            }
            if (use_restoration) {
                restoration_vector_buffer[static_cast<std::size_t>(vertex_offset + 0)] = base_x;
                restoration_vector_buffer[static_cast<std::size_t>(vertex_offset + 1)] = base_y;
                restoration_vector_buffer[static_cast<std::size_t>(vertex_offset + 2)] = base_z;
            }
        }

        for (int iteration = 0; iteration < kMc2AngleIterationCount; ++iteration) {
            const int iteration_den = std::max(kMc2AngleIterationCount - 1, 1);
            const float iteration_ratio = static_cast<float>(iteration) / static_cast<float>(iteration_den);
            constexpr float limit_rot_ratio = 0.4f;
            const float restoration_rot_ratio = 0.1f + (0.5f - 0.1f) * iteration_ratio;

            for (std::int32_t local = 1; local < count; ++local) {
                const std::int64_t data_index = static_cast<std::int64_t>(start) + local;
                const std::int32_t child_index = view.baseline_data[data_index];
                if (child_index < 0 || static_cast<std::int64_t>(child_index) >= view.vertex_count) {
                    continue;
                }
                const std::int32_t parent_index = view.parent_indices[child_index];
                if (parent_index < 0 || static_cast<std::int64_t>(parent_index) >= view.vertex_count) {
                    continue;
                }
                const float child_inv_mass = view.inv_masses[child_index];
                const float parent_inv_mass = view.inv_masses[parent_index];
                if (child_inv_mass <= kMc2Epsilon) {
                    continue;
                }

                const std::int64_t child_offset = static_cast<std::int64_t>(child_index) * 3;
                const std::int64_t parent_offset = static_cast<std::int64_t>(parent_index) * 3;
                float child_x = view.positions[child_offset + 0];
                float child_y = view.positions[child_offset + 1];
                float child_z = view.positions[child_offset + 2];
                float parent_x = view.positions[parent_offset + 0];
                float parent_y = view.positions[parent_offset + 1];
                float parent_z = view.positions[parent_offset + 2];

                if (use_limit) {
                    const auto debug_record = debug_record_index(0, iteration, data_index);
                    debug_begin(debug_record, parent_index, child_index);
                    const std::int64_t parent_rot_offset = static_cast<std::int64_t>(parent_index) * 4;
                    const std::int64_t child_rot_offset = static_cast<std::int64_t>(child_index) * 4;
                    const std::int64_t child_local_pos_offset = static_cast<std::int64_t>(child_index) * 3;
                    const float* parent_rot = &rotation_buffer[static_cast<std::size_t>(parent_rot_offset)];
                    const float* local_rot = &local_rot_buffer[static_cast<std::size_t>(child_rot_offset)];
                    float vector_x = child_x - parent_x;
                    float vector_y = child_y - parent_y;
                    float vector_z = child_z - parent_z;
                    const float vector_len = std::sqrt(vector_x * vector_x + vector_y * vector_y + vector_z * vector_z);
                    float target_x = 0.0f;
                    float target_y = 0.0f;
                    float target_z = 0.0f;
                    quat_rotate(parent_rot,
                                local_pos_buffer[static_cast<std::size_t>(child_local_pos_offset + 0)],
                                local_pos_buffer[static_cast<std::size_t>(child_local_pos_offset + 1)],
                                local_pos_buffer[static_cast<std::size_t>(child_local_pos_offset + 2)],
                                target_x, target_y, target_z);
                    const float target_len = std::sqrt(target_x * target_x + target_y * target_y + target_z * target_z);
                    bool has_vector = false;
                    float vector_dir_x = 0.0f;
                    float vector_dir_y = 0.0f;
                    float vector_dir_z = 0.0f;
                    float target_dir_x = 0.0f;
                    float target_dir_y = 0.0f;
                    float target_dir_z = 0.0f;
                    if (vector_len > kMc2Epsilon && target_len <= kMc2Epsilon) {
                        const float add_x = parent_x - child_x;
                        const float add_y = parent_y - child_y;
                        const float add_z = parent_z - child_z;
                        child_x = parent_x;
                        child_y = parent_y;
                        child_z = parent_z;
                        view.positions[child_offset + 0] = child_x;
                        view.positions[child_offset + 1] = child_y;
                        view.positions[child_offset + 2] = child_z;
                        view.velocity_positions[child_offset + 0] += add_x;
                        view.velocity_positions[child_offset + 1] += add_y;
                        view.velocity_positions[child_offset + 2] += add_z;
                        debug_add(
                            debug_record,
                            0.0f, 0.0f, 0.0f,
                            add_x, add_y, add_z
                        );
                        float next_rot[4];
                        quat_mul(parent_rot, local_rot, next_rot);
                        rotation_buffer[static_cast<std::size_t>(child_rot_offset + 0)] = next_rot[0];
                        rotation_buffer[static_cast<std::size_t>(child_rot_offset + 1)] = next_rot[1];
                        rotation_buffer[static_cast<std::size_t>(child_rot_offset + 2)] = next_rot[2];
                        rotation_buffer[static_cast<std::size_t>(child_rot_offset + 3)] = next_rot[3];
                    } else if (vector_len > kMc2Epsilon && target_len > kMc2Epsilon) {
                        vector_dir_x = vector_x / vector_len;
                        vector_dir_y = vector_y / vector_len;
                        vector_dir_z = vector_z / vector_len;
                        target_dir_x = target_x / target_len;
                        target_dir_y = target_y / target_len;
                        target_dir_z = target_z / target_len;
                        const float blend_len =
                            vector_len * 0.5f + length_buffer[static_cast<std::size_t>(child_index)] * 0.5f;
                        if (blend_len > kMc2Epsilon) {
                            vector_x = vector_dir_x * blend_len;
                            vector_y = vector_dir_y * blend_len;
                            vector_z = vector_dir_z * blend_len;
                            has_vector = true;
                        }
                    }

                    if (has_vector) {
                        const float max_angle_rad =
                            std::max(0.0f, view.limit_values[child_index]) * kPi / 180.0f;
                        const float angle = std::acos(
                            clamp_float(dot3(vector_dir_x, vector_dir_y, vector_dir_z, target_dir_x, target_dir_y,
                                             target_dir_z),
                                        -1.0f, 1.0f));
                        if (debug_records) {
                            view.debug_record_currents[debug_record] = angle;
                            view.debug_record_limits[debug_record] = max_angle_rad;
                        }
                        float result_x = vector_x;
                        float result_y = vector_y;
                        float result_z = vector_z;
                        if (angle > max_angle_rad) {
                            const float recovery_angle = angle * (1.0f - limit_stiffness) + max_angle_rad * limit_stiffness;
                            clamp_vector_angle(vector_x, vector_y, vector_z, target_x, target_y, target_z,
                                               recovery_angle, result_x, result_y, result_z);
                        }

                        const float rot_pos_x = parent_x + vector_x * limit_rot_ratio;
                        const float rot_pos_y = parent_y + vector_y * limit_rot_ratio;
                        const float rot_pos_z = parent_z + vector_z * limit_rot_ratio;
                        const float parent_final_x = rot_pos_x - result_x * limit_rot_ratio;
                        const float parent_final_y = rot_pos_y - result_y * limit_rot_ratio;
                        const float parent_final_z = rot_pos_z - result_z * limit_rot_ratio;
                        const float child_final_x = rot_pos_x + result_x * (1.0f - limit_rot_ratio);
                        const float child_final_y = rot_pos_y + result_y * (1.0f - limit_rot_ratio);
                        const float child_final_z = rot_pos_z + result_z * (1.0f - limit_rot_ratio);
                        const float parent_add_x = (parent_final_x - parent_x) * parent_inv_mass;
                        const float parent_add_y = (parent_final_y - parent_y) * parent_inv_mass;
                        const float parent_add_z = (parent_final_z - parent_z) * parent_inv_mass;
                        const float child_add_x = (child_final_x - child_x) * child_inv_mass;
                        const float child_add_y = (child_final_y - child_y) * child_inv_mass;
                        const float child_add_z = (child_final_z - child_z) * child_inv_mass;

                        child_x += child_add_x;
                        child_y += child_add_y;
                        child_z += child_add_z;
                        view.positions[child_offset + 0] = child_x;
                        view.positions[child_offset + 1] = child_y;
                        view.positions[child_offset + 2] = child_z;
                        view.velocity_positions[child_offset + 0] += child_add_x * kAngleLimitAttenuation;
                        view.velocity_positions[child_offset + 1] += child_add_y * kAngleLimitAttenuation;
                        view.velocity_positions[child_offset + 2] += child_add_z * kAngleLimitAttenuation;
                        if (parent_inv_mass > kMc2Epsilon) {
                            parent_x += parent_add_x;
                            parent_y += parent_add_y;
                            parent_z += parent_add_z;
                            view.positions[parent_offset + 0] = parent_x;
                            view.positions[parent_offset + 1] = parent_y;
                            view.positions[parent_offset + 2] = parent_z;
                            view.velocity_positions[parent_offset + 0] += parent_add_x * kAngleLimitAttenuation;
                            view.velocity_positions[parent_offset + 1] += parent_add_y * kAngleLimitAttenuation;
                            view.velocity_positions[parent_offset + 2] += parent_add_z * kAngleLimitAttenuation;
                        }
                        debug_add(
                            debug_record,
                            parent_inv_mass > kMc2Epsilon ? parent_add_x : 0.0f,
                            parent_inv_mass > kMc2Epsilon ? parent_add_y : 0.0f,
                            parent_inv_mass > kMc2Epsilon ? parent_add_z : 0.0f,
                            child_add_x, child_add_y, child_add_z
                        );

                        const float corrected_x = child_x - parent_x;
                        const float corrected_y = child_y - parent_y;
                        const float corrected_z = child_z - parent_z;
                        const float corrected_len =
                            std::sqrt(corrected_x * corrected_x + corrected_y * corrected_y + corrected_z * corrected_z);
                        if (corrected_len > kMc2Epsilon) {
                            float next_rot[4];
                            quat_mul(parent_rot, local_rot, next_rot);
                            float q[4];
                            from_to_rotation(target_x / std::max(target_len, kMc2Epsilon),
                                             target_y / std::max(target_len, kMc2Epsilon),
                                             target_z / std::max(target_len, kMc2Epsilon),
                                             corrected_x / corrected_len,
                                             corrected_y / corrected_len,
                                             corrected_z / corrected_len,
                                             1.0f, q);
                            float final_rot[4];
                            quat_mul(q, next_rot, final_rot);
                            rotation_buffer[static_cast<std::size_t>(child_rot_offset + 0)] = final_rot[0];
                            rotation_buffer[static_cast<std::size_t>(child_rot_offset + 1)] = final_rot[1];
                            rotation_buffer[static_cast<std::size_t>(child_rot_offset + 2)] = final_rot[2];
                            rotation_buffer[static_cast<std::size_t>(child_rot_offset + 3)] = final_rot[3];
                        }
                    }
                }

                if (!use_restoration) {
                    continue;
                }
                const auto debug_record = debug_record_index(1, iteration, data_index);
                debug_begin(debug_record, parent_index, child_index);
                const float gravity_falloff = clamp_float(
                    1.0f - (view.restoration_gravity_falloff_values != nullptr
                                ? view.restoration_gravity_falloff_values[child_index]
                                : view.restoration_gravity_falloff),
                    0.0f,
                    1.0f);
                const float restoration_stiffness =
                    clamp_float(view.restoration_values[child_index], 0.0f, 1.0f) * gravity_falloff;
                if (restoration_stiffness <= kMc2Epsilon) {
                    continue;
                }

                child_x = view.positions[child_offset + 0];
                child_y = view.positions[child_offset + 1];
                child_z = view.positions[child_offset + 2];
                parent_x = view.positions[parent_offset + 0];
                parent_y = view.positions[parent_offset + 1];
                parent_z = view.positions[parent_offset + 2];
                const float target_x = restoration_vector_buffer[static_cast<std::size_t>(child_offset + 0)];
                const float target_y = restoration_vector_buffer[static_cast<std::size_t>(child_offset + 1)];
                const float target_z = restoration_vector_buffer[static_cast<std::size_t>(child_offset + 2)];
                const float target_len = std::sqrt(target_x * target_x + target_y * target_y + target_z * target_z);
                const float vector_x = child_x - parent_x;
                const float vector_y = child_y - parent_y;
                const float vector_z = child_z - parent_z;
                const float vector_len = std::sqrt(vector_x * vector_x + vector_y * vector_y + vector_z * vector_z);
                if (target_len <= kMc2Epsilon) {
                    const float add_x = parent_x - child_x;
                    const float add_y = parent_y - child_y;
                    const float add_z = parent_z - child_z;
                    view.positions[child_offset + 0] = parent_x;
                    view.positions[child_offset + 1] = parent_y;
                    view.positions[child_offset + 2] = parent_z;
                    view.velocity_positions[child_offset + 0] += add_x;
                    view.velocity_positions[child_offset + 1] += add_y;
                    view.velocity_positions[child_offset + 2] += add_z;
                    debug_add(
                        debug_record,
                        0.0f, 0.0f, 0.0f,
                        add_x, add_y, add_z
                    );
                    continue;
                }
                if (vector_len <= kMc2Epsilon) {
                    continue;
                }
                const float direction_dot = clamp_float(
                    dot3(vector_x, vector_y, vector_z, target_x, target_y, target_z) /
                        (vector_len * target_len),
                    -1.0f,
                    1.0f
                );
                if (debug_records) {
                    view.debug_record_currents[debug_record] = std::acos(direction_dot);
                    view.debug_record_limits[debug_record] = 0.0f;
                }
                if (direction_dot >= 1.0f - kDirectionDotDeadzone) {
                    continue;
                }

                float q[4];
                from_to_rotation(vector_x / vector_len, vector_y / vector_len, vector_z / vector_len,
                                 target_x / target_len, target_y / target_len, target_z / target_len,
                                 restoration_stiffness, q);
                float result_x = 0.0f;
                float result_y = 0.0f;
                float result_z = 0.0f;
                quat_rotate(q, vector_x, vector_y, vector_z, result_x, result_y, result_z);
                const float rot_pos_x = parent_x + vector_x * restoration_rot_ratio;
                const float rot_pos_y = parent_y + vector_y * restoration_rot_ratio;
                const float rot_pos_z = parent_z + vector_z * restoration_rot_ratio;
                const float parent_final_x = rot_pos_x - result_x * restoration_rot_ratio;
                const float parent_final_y = rot_pos_y - result_y * restoration_rot_ratio;
                const float parent_final_z = rot_pos_z - result_z * restoration_rot_ratio;
                const float child_final_x = rot_pos_x + result_x * (1.0f - restoration_rot_ratio);
                const float child_final_y = rot_pos_y + result_y * (1.0f - restoration_rot_ratio);
                const float child_final_z = rot_pos_z + result_z * (1.0f - restoration_rot_ratio);
                const float parent_add_x = (parent_final_x - parent_x) * parent_inv_mass;
                const float parent_add_y = (parent_final_y - parent_y) * parent_inv_mass;
                const float parent_add_z = (parent_final_z - parent_z) * parent_inv_mass;
                const float child_add_x = (child_final_x - child_x) * child_inv_mass;
                const float child_add_y = (child_final_y - child_y) * child_inv_mass;
                const float child_add_z = (child_final_z - child_z) * child_inv_mass;

                child_x += child_add_x;
                child_y += child_add_y;
                child_z += child_add_z;
                view.positions[child_offset + 0] = child_x;
                view.positions[child_offset + 1] = child_y;
                view.positions[child_offset + 2] = child_z;
                const float restoration_attenuation =
                    clamp_float(view.restoration_velocity_attenuation_values != nullptr
                                    ? view.restoration_velocity_attenuation_values[child_index]
                                    : view.restoration_velocity_attenuation,
                                0.0f,
                                1.0f);
                view.velocity_positions[child_offset + 0] += child_add_x * restoration_attenuation;
                view.velocity_positions[child_offset + 1] += child_add_y * restoration_attenuation;
                view.velocity_positions[child_offset + 2] += child_add_z * restoration_attenuation;
                if (parent_inv_mass > kMc2Epsilon) {
                    parent_x += parent_add_x;
                    parent_y += parent_add_y;
                    parent_z += parent_add_z;
                    view.positions[parent_offset + 0] = parent_x;
                    view.positions[parent_offset + 1] = parent_y;
                    view.positions[parent_offset + 2] = parent_z;
                    view.velocity_positions[parent_offset + 0] += parent_add_x * restoration_attenuation;
                    view.velocity_positions[parent_offset + 1] += parent_add_y * restoration_attenuation;
                    view.velocity_positions[parent_offset + 2] += parent_add_z * restoration_attenuation;
                }
                debug_add(
                    debug_record,
                    parent_inv_mass > kMc2Epsilon ? parent_add_x : 0.0f,
                    parent_inv_mass > kMc2Epsilon ? parent_add_y : 0.0f,
                    parent_inv_mass > kMc2Epsilon ? parent_add_z : 0.0f,
                    child_add_x, child_add_y, child_add_z
                );
            }
        }
    }
}

void update_step_basic_pose_mc2(Mc2StepBasicPoseView& view) {
    if (view.vertex_count <= 0 || view.base_positions == nullptr || view.base_rotations == nullptr ||
        view.parent_indices == nullptr || view.baseline_start == nullptr || view.baseline_count == nullptr ||
        view.baseline_data == nullptr || view.vertex_local_positions == nullptr ||
        view.vertex_local_rotations == nullptr || view.step_positions == nullptr || view.step_rotations == nullptr) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t pos_offset = vertex * 3;
        const std::int64_t rot_offset = vertex * 4;
        view.step_positions[pos_offset + 0] = view.base_positions[pos_offset + 0];
        view.step_positions[pos_offset + 1] = view.base_positions[pos_offset + 1];
        view.step_positions[pos_offset + 2] = view.base_positions[pos_offset + 2];
        view.step_rotations[rot_offset + 0] = view.base_rotations[rot_offset + 0];
        view.step_rotations[rot_offset + 1] = view.base_rotations[rot_offset + 1];
        view.step_rotations[rot_offset + 2] = view.base_rotations[rot_offset + 2];
        view.step_rotations[rot_offset + 3] = view.base_rotations[rot_offset + 3];
    }

    const float ratio = clamp_float(view.animation_pose_ratio, 0.0f, 1.0f);
    if (ratio > 0.99f || view.baseline_data_count <= 0) {
        return;
    }

    for (std::int64_t line_index = 0; line_index < view.line_count; ++line_index) {
        const std::int32_t start = view.baseline_start[line_index];
        const std::int32_t count = view.baseline_count[line_index];
        for (std::int32_t data_offset = 0; data_offset < count; ++data_offset) {
            const std::int64_t data_index = static_cast<std::int64_t>(start) + data_offset;
            if (data_index < 0 || data_index >= view.baseline_data_count) {
                continue;
            }
            const std::int32_t vertex = view.baseline_data[data_index];
            if (vertex < 0 || static_cast<std::int64_t>(vertex) >= view.vertex_count) {
                continue;
            }
            const std::int32_t parent = view.parent_indices[vertex];
            if (parent < 0 || static_cast<std::int64_t>(parent) >= view.vertex_count) {
                continue;
            }

            const std::int64_t vertex_pos_offset = static_cast<std::int64_t>(vertex) * 3;
            const std::int64_t parent_pos_offset = static_cast<std::int64_t>(parent) * 3;
            const std::int64_t vertex_rot_offset = static_cast<std::int64_t>(vertex) * 4;
            const std::int64_t parent_rot_offset = static_cast<std::int64_t>(parent) * 4;
            float rotated_x = 0.0f;
            float rotated_y = 0.0f;
            float rotated_z = 0.0f;
            quat_rotate(&view.step_rotations[parent_rot_offset],
                        view.vertex_local_positions[vertex_pos_offset + 0],
                        view.vertex_local_positions[vertex_pos_offset + 1],
                        view.vertex_local_positions[vertex_pos_offset + 2],
                        rotated_x, rotated_y, rotated_z);
            view.step_positions[vertex_pos_offset + 0] = view.step_positions[parent_pos_offset + 0] + rotated_x;
            view.step_positions[vertex_pos_offset + 1] = view.step_positions[parent_pos_offset + 1] + rotated_y;
            view.step_positions[vertex_pos_offset + 2] = view.step_positions[parent_pos_offset + 2] + rotated_z;
            float next_rotation[4];
            quat_mul(&view.step_rotations[parent_rot_offset], &view.vertex_local_rotations[vertex_rot_offset],
                     next_rotation);
            view.step_rotations[vertex_rot_offset + 0] = next_rotation[0];
            view.step_rotations[vertex_rot_offset + 1] = next_rotation[1];
            view.step_rotations[vertex_rot_offset + 2] = next_rotation[2];
            view.step_rotations[vertex_rot_offset + 3] = next_rotation[3];
        }

        if (ratio <= kMc2Epsilon) {
            continue;
        }
        for (std::int32_t data_offset = 0; data_offset < count; ++data_offset) {
            const std::int64_t data_index = static_cast<std::int64_t>(start) + data_offset;
            if (data_index < 0 || data_index >= view.baseline_data_count) {
                continue;
            }
            const std::int32_t vertex = view.baseline_data[data_index];
            if (vertex < 0 || static_cast<std::int64_t>(vertex) >= view.vertex_count) {
                continue;
            }
            const std::int64_t pos_offset = static_cast<std::int64_t>(vertex) * 3;
            const std::int64_t rot_offset = static_cast<std::int64_t>(vertex) * 4;
            view.step_positions[pos_offset + 0] =
                view.step_positions[pos_offset + 0] * (1.0f - ratio) + view.base_positions[pos_offset + 0] * ratio;
            view.step_positions[pos_offset + 1] =
                view.step_positions[pos_offset + 1] * (1.0f - ratio) + view.base_positions[pos_offset + 1] * ratio;
            view.step_positions[pos_offset + 2] =
                view.step_positions[pos_offset + 2] * (1.0f - ratio) + view.base_positions[pos_offset + 2] * ratio;
            float mixed_rotation[4];
            quat_slerp(&view.step_rotations[rot_offset], &view.base_rotations[rot_offset], ratio, mixed_rotation);
            view.step_rotations[rot_offset + 0] = mixed_rotation[0];
            view.step_rotations[rot_offset + 1] = mixed_rotation[1];
            view.step_rotations[rot_offset + 2] = mixed_rotation[2];
            view.step_rotations[rot_offset + 3] = mixed_rotation[3];
        }
    }
}

void update_base_pose_from_pose_mc2(Mc2BasePoseFromPoseView& view) {
    if (view.vertex_count <= 0 || view.base_positions == nullptr || view.base_normals == nullptr ||
        view.parent_indices == nullptr || view.base_rotations == nullptr || view.step_positions == nullptr ||
        view.step_rotations == nullptr) {
        return;
    }

    const auto vertex_count = view.vertex_count;
    for (std::int64_t vertex = 0; vertex < vertex_count; ++vertex) {
        const auto offset = vertex * 3;
        float forward_x = 0.0f;
        float forward_y = 0.0f;
        float forward_z = 0.0f;
        bool has_child = false;
        for (std::int64_t child = 0; child < vertex_count; ++child) {
            if (view.parent_indices[child] != vertex) {
                continue;
            }
            const auto child_offset = child * 3;
            forward_x += view.base_positions[child_offset + 0] - view.base_positions[offset + 0];
            forward_y += view.base_positions[child_offset + 1] - view.base_positions[offset + 1];
            forward_z += view.base_positions[child_offset + 2] - view.base_positions[offset + 2];
            has_child = true;
        }
        if (!has_child) {
            const std::int32_t parent = view.parent_indices[vertex];
            if (parent >= 0 && parent < vertex_count) {
                const auto parent_offset = static_cast<std::int64_t>(parent) * 3;
                forward_x = view.base_positions[offset + 0] - view.base_positions[parent_offset + 0];
                forward_y = view.base_positions[offset + 1] - view.base_positions[parent_offset + 1];
                forward_z = view.base_positions[offset + 2] - view.base_positions[parent_offset + 2];
            } else {
                forward_x = view.base_normals[offset + 0];
                forward_y = view.base_normals[offset + 1];
                forward_z = view.base_normals[offset + 2];
            }
        }

        float rotation[4];
        frame_rotation(forward_x,
                       forward_y,
                       forward_z,
                       view.base_normals[offset + 0],
                       view.base_normals[offset + 1],
                       view.base_normals[offset + 2],
                       rotation);
        const auto rot_offset = vertex * 4;
        view.base_rotations[rot_offset + 0] = rotation[0];
        view.base_rotations[rot_offset + 1] = rotation[1];
        view.base_rotations[rot_offset + 2] = rotation[2];
        view.base_rotations[rot_offset + 3] = rotation[3];
    }

    Mc2StepBasicPoseView step_view;
    step_view.base_positions = view.base_positions;
    step_view.base_rotations = view.base_rotations;
    step_view.parent_indices = view.parent_indices;
    step_view.baseline_start = view.baseline_start;
    step_view.baseline_count = view.baseline_count;
    step_view.baseline_data = view.baseline_data;
    step_view.vertex_local_positions = view.vertex_local_positions;
    step_view.vertex_local_rotations = view.vertex_local_rotations;
    step_view.step_positions = view.step_positions;
    step_view.step_rotations = view.step_rotations;
    step_view.vertex_count = view.vertex_count;
    step_view.line_count = view.line_count;
    step_view.baseline_data_count = view.baseline_data_count;
    step_view.animation_pose_ratio = view.animation_pose_ratio;
    update_step_basic_pose_mc2(step_view);
}

void apply_substep_inertia_mc2(Mc2SubstepInertiaView& view) {
    if (view.vertex_count <= 0 || view.old_positions == nullptr || view.velocities == nullptr ||
        view.depths == nullptr || view.inv_masses == nullptr) {
        return;
    }

    const float depth_inertia = clamp_float(view.depth_inertia, 0.0f, 1.0f);
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kMc2Epsilon) {
            continue;
        }
        const float depth = clamp_float(view.depths[vertex], 0.0f, 1.0f);
        const float ratio = depth_inertia * (1.0f - depth * std::sqrt(depth));
        const float inertia_vector_x = view.inertia_vector[0] * (1.0f - ratio) + view.step_vector[0] * ratio;
        const float inertia_vector_y = view.inertia_vector[1] * (1.0f - ratio) + view.step_vector[1] * ratio;
        const float inertia_vector_z = view.inertia_vector[2] * (1.0f - ratio) + view.step_vector[2] * ratio;
        float inertia_rotation[4];
        quat_slerp(view.inertia_rotation, view.step_rotation, ratio, inertia_rotation);

        const std::int64_t offset = vertex * 3;
        const float local_x = view.old_positions[offset + 0] - view.old_world_position[0];
        const float local_y = view.old_positions[offset + 1] - view.old_world_position[1];
        const float local_z = view.old_positions[offset + 2] - view.old_world_position[2];
        float rotated_x = 0.0f;
        float rotated_y = 0.0f;
        float rotated_z = 0.0f;
        quat_rotate(inertia_rotation, local_x, local_y, local_z, rotated_x, rotated_y, rotated_z);
        view.old_positions[offset + 0] = view.old_world_position[0] + rotated_x + inertia_vector_x;
        view.old_positions[offset + 1] = view.old_world_position[1] + rotated_y + inertia_vector_y;
        view.old_positions[offset + 2] = view.old_world_position[2] + rotated_z + inertia_vector_z;

        quat_rotate(inertia_rotation, view.velocities[offset + 0], view.velocities[offset + 1],
                    view.velocities[offset + 2], rotated_x, rotated_y, rotated_z);
        view.velocities[offset + 0] = rotated_x;
        view.velocities[offset + 1] = rotated_y;
        view.velocities[offset + 2] = rotated_z;
    }
}

namespace {

void center_rotate_vector(
    const float* rotation,
    const float* value,
    float* output
);

void center_quaternion_from_forward_up(
    const float* forward,
    const float* up,
    float* output
) {
    const float forward_length = std::sqrt(
        forward[0] * forward[0] + forward[1] * forward[1] + forward[2] * forward[2]
    );
    const float f[3] = {
        forward[0] / forward_length,
        forward[1] / forward_length,
        forward[2] / forward_length,
    };
    float right[3] = {
        up[1] * f[2] - up[2] * f[1],
        up[2] * f[0] - up[0] * f[2],
        up[0] * f[1] - up[1] * f[0],
    };
    const float right_length = std::sqrt(
        right[0] * right[0] + right[1] * right[1] + right[2] * right[2]
    );
    right[0] /= right_length;
    right[1] /= right_length;
    right[2] /= right_length;
    const float corrected_up[3] = {
        f[1] * right[2] - f[2] * right[1],
        f[2] * right[0] - f[0] * right[2],
        f[0] * right[1] - f[1] * right[0],
    };
    const float matrix[9] = {
        right[0], corrected_up[0], f[0],
        right[1], corrected_up[1], f[1],
        right[2], corrected_up[2], f[2],
    };
    const float trace = matrix[0] + matrix[4] + matrix[8];
    float raw[4];
    if (trace > 0.0f) {
        const float s = std::sqrt(trace + 1.0f) * 2.0f;
        raw[0] = (matrix[7] - matrix[5]) / s;
        raw[1] = (matrix[2] - matrix[6]) / s;
        raw[2] = (matrix[3] - matrix[1]) / s;
        raw[3] = 0.25f * s;
    } else if (matrix[0] > matrix[4] && matrix[0] > matrix[8]) {
        const float s = std::sqrt(1.0f + matrix[0] - matrix[4] - matrix[8]) * 2.0f;
        raw[0] = 0.25f * s;
        raw[1] = (matrix[1] + matrix[3]) / s;
        raw[2] = (matrix[2] + matrix[6]) / s;
        raw[3] = (matrix[7] - matrix[5]) / s;
    } else if (matrix[4] > matrix[8]) {
        const float s = std::sqrt(1.0f + matrix[4] - matrix[0] - matrix[8]) * 2.0f;
        raw[0] = (matrix[1] + matrix[3]) / s;
        raw[1] = 0.25f * s;
        raw[2] = (matrix[5] + matrix[7]) / s;
        raw[3] = (matrix[2] - matrix[6]) / s;
    } else {
        const float s = std::sqrt(1.0f + matrix[8] - matrix[0] - matrix[4]) * 2.0f;
        raw[0] = (matrix[2] + matrix[6]) / s;
        raw[1] = (matrix[5] + matrix[7]) / s;
        raw[2] = 0.25f * s;
        raw[3] = (matrix[3] - matrix[1]) / s;
    }
    quat_normalize(raw, output);
}

void center_slerp_xyzw(
    const float* first,
    const float* second,
    float ratio,
    float* output
) {
    float target[4] = {second[0], second[1], second[2], second[3]};
    float cosine = first[0] * target[0] + first[1] * target[1] +
        first[2] * target[2] + first[3] * target[3];
    if (cosine < 0.0f) {
        cosine = -cosine;
        for (float& value : target) value = -value;
    }
    float first_weight = 1.0f - ratio;
    float second_weight = ratio;
    if (cosine < 0.9995f) {
        const float angle = std::acos(std::max(-1.0f, std::min(1.0f, cosine)));
        const float sine = std::sin(angle);
        first_weight = std::sin((1.0f - ratio) * angle) / sine;
        second_weight = std::sin(ratio * angle) / sine;
    }
    float length_squared = 0.0f;
    for (int component = 0; component < 4; ++component) {
        output[component] = first[component] * first_weight + target[component] * second_weight;
        length_squared += output[component] * output[component];
    }
    const float inverse_length = length_squared > kMc2Epsilon
        ? 1.0f / std::sqrt(length_squared)
        : 1.0f;
    for (int component = 0; component < 4; ++component) output[component] *= inverse_length;
}

void center_rotate_vector(
    const float* rotation,
    const float* value,
    float* output
) {
    const float cross_x = rotation[1] * value[2] - rotation[2] * value[1];
    const float cross_y = rotation[2] * value[0] - rotation[0] * value[2];
    const float cross_z = rotation[0] * value[1] - rotation[1] * value[0];
    const float twice_cross_x = 2.0f * cross_x;
    const float twice_cross_y = 2.0f * cross_y;
    const float twice_cross_z = 2.0f * cross_z;
    output[0] = value[0] + rotation[3] * twice_cross_x +
        (rotation[1] * twice_cross_z - rotation[2] * twice_cross_y);
    output[1] = value[1] + rotation[3] * twice_cross_y +
        (rotation[2] * twice_cross_x - rotation[0] * twice_cross_z);
    output[2] = value[2] + rotation[3] * twice_cross_z +
        (rotation[0] * twice_cross_y - rotation[1] * twice_cross_x);
}

}  // namespace

bool derive_center_world_pose_mc2(Mc2CenterPoseView& view) {
    if (view.particle_count <= 0 || view.world_positions == nullptr ||
        view.world_rotations == nullptr || view.partition_index < 0 ||
        (!view.use_fixed_particle_indices &&
         (view.particle_partition_index == nullptr || view.particle_attribute_flags == nullptr))) {
        return false;
    }
    std::int64_t fixed_count = 0;
    float position_sum[3] = {};
    float normal_sum[3] = {};
    float tangent_sum[3] = {};
    const bool has_negative_scale = view.component_scale[0] < 0.0f ||
        view.component_scale[1] < 0.0f || view.component_scale[2] < 0.0f;
    const auto visit_particle = [&](std::int64_t particle) {
        if (particle < 0 || particle >= view.particle_count) return false;
        const auto position_offset = particle * 3;
        const auto rotation_offset = particle * 4;
        for (std::size_t component = 0; component < 3; ++component) {
            position_sum[component] += view.world_positions[position_offset + component];
        }
        float frame_rotation[4] = {
            view.world_rotations[rotation_offset + 0],
            view.world_rotations[rotation_offset + 1],
            view.world_rotations[rotation_offset + 2],
            view.world_rotations[rotation_offset + 3],
        };
        if (has_negative_scale) {
            const float normal_input[3] = {0.0f, 1.0f, 0.0f};
            const float tangent_input[3] = {0.0f, 0.0f, 1.0f};
            float normal[3] {};
            float tangent[3] {};
            center_rotate_vector(frame_rotation, normal_input, normal);
            center_rotate_vector(frame_rotation, tangent_input, tangent);
            const float neg_tangent[3] = {-tangent[0], -tangent[1], -tangent[2]};
            const float neg_normal[3] = {-normal[0], -normal[1], -normal[2]};
            center_quaternion_from_forward_up(neg_tangent, neg_normal, frame_rotation);
        }
        float corrected[4];
        quat_multiply(frame_rotation, view.bind_rotations + rotation_offset, corrected);
        const float normal_input[3] = {0.0f, 1.0f, 0.0f};
        const float tangent_input[3] = {0.0f, 0.0f, 1.0f};
        float normal[3] {};
        float tangent[3] {};
        center_rotate_vector(corrected, normal_input, normal);
        center_rotate_vector(corrected, tangent_input, tangent);
        for (std::size_t component = 0; component < 3; ++component) {
            normal_sum[component] += normal[component];
            tangent_sum[component] += tangent[component];
        }
        ++fixed_count;
        return true;
    };
    if (view.use_fixed_particle_indices) {
        if (view.fixed_particle_count > 0 && view.fixed_particle_indices == nullptr) return false;
        if (view.fixed_particle_count > 0 && view.bind_rotations == nullptr) return false;
        for (std::int64_t index = 0; index < view.fixed_particle_count; ++index) {
            if (!visit_particle(view.fixed_particle_indices[index])) return false;
        }
    } else {
        if (view.bind_rotations == nullptr) return false;
        for (std::int64_t particle = 0; particle < view.particle_count; ++particle) {
            if (static_cast<std::int64_t>(view.particle_partition_index[particle]) != view.partition_index ||
                (view.particle_attribute_flags[particle] & 1u) == 0u) {
                continue;
            }
            if (!visit_particle(particle)) return false;
        }
    }
    if (fixed_count == 0) {
        std::copy_n(view.component_position, 3, view.center_position);
        std::copy_n(view.component_rotation, 4, view.center_rotation);
        return true;
    }
    const float inverse_count = 1.0f / static_cast<float>(fixed_count);
    for (std::size_t component = 0; component < 3; ++component) {
        view.center_position[component] = position_sum[component] * inverse_count;
    }
    if (view.component_scale[0] < 0.0f || view.component_scale[2] < 0.0f) {
        for (float& value : normal_sum) value = -value;
    }
    if (view.component_scale[0] < 0.0f || view.component_scale[1] < 0.0f) {
        for (float& value : tangent_sum) value = -value;
    }
    const float normal_length = std::sqrt(
        normal_sum[0] * normal_sum[0] + normal_sum[1] * normal_sum[1] + normal_sum[2] * normal_sum[2]
    );
    const float tangent_length = std::sqrt(
        tangent_sum[0] * tangent_sum[0] + tangent_sum[1] * tangent_sum[1] + tangent_sum[2] * tangent_sum[2]
    );
    if (normal_length <= kMc2Epsilon || tangent_length <= kMc2Epsilon) return false;
    center_quaternion_from_forward_up(tangent_sum, normal_sum, view.center_rotation);
    return true;
}

// E3-C keeps the verified frame-shift order in one backend-neutral kernel.
bool evaluate_center_frame_shift_mc2(Mc2CenterFrameShiftView& view) {
    if (view.old_component_position == nullptr || view.component_position == nullptr ||
        view.old_component_rotation == nullptr || view.component_rotation == nullptr ||
        view.component_scale == nullptr || view.initial_scale == nullptr ||
        view.frame_world_position == nullptr || view.frame_world_rotation == nullptr ||
        view.old_frame_world_position == nullptr || view.old_frame_world_rotation == nullptr ||
        view.now_world_position == nullptr || view.now_world_rotation == nullptr ||
        view.smoothing_velocity == nullptr || view.frame_delta_time <= kMc2Epsilon ||
        view.frame_delta_time < 0.0f ||
        view.simulation_delta_time < 0.0f || view.time_scale < 0.0f || view.skip_count < 0 ||
        view.velocity_weight < 0.0f || view.velocity_weight > 1.0f ||
        view.anchor_inertia < 0.0f || view.anchor_inertia > 1.0f ||
        view.world_inertia < 0.0f || view.world_inertia > 1.0f ||
        view.movement_inertia_smoothing < 0.0f || view.movement_inertia_smoothing > 1.0f ||
        view.teleport_mode < 0 || view.teleport_mode > 2 ||
        view.teleport_distance < 0.0f || view.teleport_rotation < 0.0f ||
        !std::isfinite(view.frame_delta_time) || !std::isfinite(view.simulation_delta_time) ||
        !std::isfinite(view.time_scale) || !std::isfinite(view.anchor_inertia) ||
        !std::isfinite(view.world_inertia) || !std::isfinite(view.movement_speed_limit) ||
        !std::isfinite(view.rotation_speed_limit) ||
        !std::isfinite(view.movement_inertia_smoothing) ||
        !std::isfinite(view.velocity_weight) || !std::isfinite(view.teleport_distance) ||
        !std::isfinite(view.teleport_rotation)) {
        return false;
    }
    const auto finite_values = [](const float* values, std::size_t count) {
        for (std::size_t index = 0; index < count; ++index) {
            if (!std::isfinite(values[index])) return false;
        }
        return true;
    };
    const auto unit_quaternion = [&](const float* values) {
        const float length = length3(values[0], values[1], values[2]);
        return finite_values(values, 4) && std::fabs(length * length + values[3] * values[3] - 1.0f) <= 2.0e-4f;
    };
    for (const auto* values : {
        view.old_component_position, view.component_position, view.frame_world_position,
        view.old_frame_world_position, view.now_world_position, view.smoothing_velocity,
    }) {
        if (!finite_values(values, 3)) return false;
    }
    if (!unit_quaternion(view.old_component_rotation) ||
        !unit_quaternion(view.component_rotation) ||
        !unit_quaternion(view.frame_world_rotation) ||
        !unit_quaternion(view.old_frame_world_rotation) ||
        !unit_quaternion(view.now_world_rotation)) {
        return false;
    }
    for (int component = 0; component < 3; ++component) {
        if (!std::isfinite(view.component_scale[component]) ||
            std::fabs(view.component_scale[component]) <= kMc2Epsilon ||
            !std::isfinite(view.initial_scale[component]) ||
            std::fabs(view.initial_scale[component]) <= kMc2Epsilon) {
            return false;
        }
    }
    const float identity[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    float old_component[3] {};
    float component[3] {};
    float old_component_rotation[4] {};
    float component_rotation[4] {};
    std::copy_n(view.old_component_position, 3, old_component);
    std::copy_n(view.component_position, 3, component);
    std::copy_n(view.old_component_rotation, 4, old_component_rotation);
    std::copy_n(view.component_rotation, 4, component_rotation);
    float raw_component_delta[3] {};
    for (int axis = 0; axis < 3; ++axis) {
        raw_component_delta[axis] = component[axis] - old_component[axis];
        view.raw_component_delta[axis] = raw_component_delta[axis];
    }
    float frame_world_position[3] {};
    float frame_world_rotation[4] {};
    std::copy_n(view.frame_world_position, 3, frame_world_position);
    std::copy_n(view.frame_world_rotation, 4, frame_world_rotation);
    float adjusted_old_component[3] {};
    float adjusted_old_component_rotation[4] {};
    std::copy_n(old_component, 3, adjusted_old_component);
    std::copy_n(old_component_rotation, 4, adjusted_old_component_rotation);
    std::fill_n(view.anchor_shift_vector, 3, 0.0f);
    float anchor_shift_rotation[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    if (view.use_anchor) {
        if (view.old_anchor_position == nullptr || view.old_anchor_rotation == nullptr ||
            view.anchor_position == nullptr || view.anchor_rotation == nullptr ||
            view.anchor_component_local_position == nullptr) {
            return false;
        }
        if (!finite_values(view.old_anchor_position, 3) ||
            !finite_values(view.anchor_position, 3) ||
            !finite_values(view.anchor_component_local_position, 3) ||
            !unit_quaternion(view.old_anchor_rotation) ||
            !unit_quaternion(view.anchor_rotation)) {
            return false;
        }
        float anchor_local_world[3] {};
        center_rotate_vector(
            view.anchor_rotation,
            view.anchor_component_local_position,
            anchor_local_world
        );
        float anchor_center[3] {};
        for (int axis = 0; axis < 3; ++axis) {
            anchor_center[axis] = view.anchor_position[axis] + anchor_local_world[axis];
            view.anchor_shift_vector[axis] =
                (anchor_center[axis] - old_component[axis]) * (1.0f - view.anchor_inertia);
            adjusted_old_component[axis] += view.anchor_shift_vector[axis];
        }
        float old_anchor_inverse[4] {};
        quat_inverse(view.old_anchor_rotation, old_anchor_inverse);
        float full_anchor_rotation[4] {};
        quat_multiply(view.anchor_rotation, old_anchor_inverse, full_anchor_rotation);
        center_slerp_xyzw(identity, full_anchor_rotation, 1.0f - view.anchor_inertia, anchor_shift_rotation);
        quat_multiply(anchor_shift_rotation, adjusted_old_component_rotation, adjusted_old_component_rotation);
    }
    const float component_scale_length = length3(
        view.component_scale[0], view.component_scale[1], view.component_scale[2]
    );
    const float initial_scale_length = length3(
        view.initial_scale[0], view.initial_scale[1], view.initial_scale[2]
    );
    if (initial_scale_length <= kMc2Epsilon) return false;
    const float component_scale_ratio = component_scale_length / initial_scale_length;
    const float teleport_delta[3] = {
        component[0] - adjusted_old_component[0],
        component[1] - adjusted_old_component[1],
        component[2] - adjusted_old_component[2],
    };
    const float teleport_measured_distance = length3(
        teleport_delta[0], teleport_delta[1], teleport_delta[2]
    );
    const float teleport_distance_threshold = view.teleport_distance * component_scale_ratio;
    float teleport_cosine = std::fabs(quat_dot_abs(adjusted_old_component_rotation, component_rotation));
    teleport_cosine = clamp_float(teleport_cosine, 0.0f, 1.0f);
    const float teleport_angle = 2.0f * std::acos(teleport_cosine);
    const float teleport_measured_rotation_degrees = teleport_angle * 180.0f / kPi;
    float old_component_inverse[4] {};
    quat_inverse(adjusted_old_component_rotation, old_component_inverse);
    float teleport_rotation_delta[4] {};
    quat_multiply(component_rotation, old_component_inverse, teleport_rotation_delta);
    if (teleport_rotation_delta[3] < 0.0f) {
        for (float& value : teleport_rotation_delta) value = -value;
    }
    const float teleport_axis_length = length3(
        teleport_rotation_delta[0], teleport_rotation_delta[1], teleport_rotation_delta[2]
    );
    if (teleport_axis_length > kMc2Epsilon) {
        for (int axis = 0; axis < 3; ++axis) {
            view.teleport_rotation_axis[axis] = teleport_rotation_delta[axis] / teleport_axis_length;
        }
    } else {
        std::copy_n(identity, 3, view.teleport_rotation_axis);
        view.teleport_rotation_axis[2] = 1.0f;
    }
    view.teleport_measured_distance = teleport_measured_distance;
    view.teleport_distance_threshold = teleport_distance_threshold;
    view.teleport_measured_rotation_degrees = teleport_measured_rotation_degrees;
    view.teleport_triggered = view.teleport_mode != 0 &&
        (teleport_measured_distance >= teleport_distance_threshold ||
         teleport_measured_rotation_degrees >= view.teleport_rotation);
    view.keep_teleport = view.teleport_triggered && view.teleport_mode == 2;
    view.reset_teleport = view.teleport_triggered && view.teleport_mode == 1;
    if (view.reset_teleport) {
        std::copy_n(frame_world_position, 3, view.shifted_old_frame_position);
        std::copy_n(frame_world_position, 3, view.shifted_now_position);
        std::copy_n(frame_world_rotation, 4, view.shifted_old_frame_rotation);
        std::copy_n(frame_world_rotation, 4, view.shifted_now_rotation);
        std::fill_n(view.frame_component_shift_vector, 3, 0.0f);
        std::copy_n(identity, 4, view.frame_component_shift_rotation);
        std::fill_n(view.smoothing_velocity_output, 3, 0.0f);
        std::fill_n(view.frame_moving_direction, 3, 0.0f);
        view.frame_moving_speed = 0.0f;
        return true;
    }
    float smooth_shift[3] = {};
    float smoothing_velocity[3] {};
    std::copy_n(view.smoothing_velocity, 3, smoothing_velocity);
    if (view.movement_inertia_smoothing >= 1.0e-6f && !view.keep_teleport) {
        if (view.is_running) {
            float frame_delta_velocity[3] {};
            for (int axis = 0; axis < 3; ++axis) {
                frame_delta_velocity[axis] =
                    (component[axis] - adjusted_old_component[axis]) / view.frame_delta_time;
            }
            const float frame_delta_speed = length3(
                frame_delta_velocity[0], frame_delta_velocity[1], frame_delta_velocity[2]
            );
            if (view.movement_speed_limit >= 0.0f && frame_delta_speed > view.movement_speed_limit) {
                const float ratio = view.movement_speed_limit / frame_delta_speed;
                for (float& value : frame_delta_velocity) value *= ratio;
            }
            const float one_minus_smoothing = 1.0f - view.movement_inertia_smoothing;
            const float average_ratio = clamp_float(
                one_minus_smoothing * one_minus_smoothing * one_minus_smoothing * 0.99f + 0.01f,
                0.0f, 1.0f
            );
            for (int axis = 0; axis < 3; ++axis) {
                smoothing_velocity[axis] +=
                    (frame_delta_velocity[axis] - smoothing_velocity[axis]) * average_ratio;
            }
        }
        for (int axis = 0; axis < 3; ++axis) {
            const float smooth_position = component[axis] - smoothing_velocity[axis] * view.frame_delta_time;
            smooth_shift[axis] = smooth_position - adjusted_old_component[axis];
            adjusted_old_component[axis] = smooth_position;
        }
    }
    std::copy_n(smooth_shift, 3, view.smoothing_shift_vector);
    float full_shift[3] {};
    for (int axis = 0; axis < 3; ++axis) full_shift[axis] = component[axis] - adjusted_old_component[axis];
    float full_shift_rotation[4] {};
    float adjusted_old_inverse[4] {};
    quat_inverse(adjusted_old_component_rotation, adjusted_old_inverse);
    quat_multiply(component_rotation, adjusted_old_inverse, full_shift_rotation);
    float move_shift_ratio = view.keep_teleport ? 1.0f : 1.0f - view.world_inertia;
    float rotation_shift_ratio = move_shift_ratio;
    float work_old_component[3] {};
    for (int axis = 0; axis < 3; ++axis) {
        work_old_component[axis] = adjusted_old_component[axis] + full_shift[axis] * move_shift_ratio;
    }
    float work_old_rotation[4] {};
    center_slerp_xyzw(adjusted_old_component_rotation, component_rotation, rotation_shift_ratio, work_old_rotation);
    float delta_vector[3] {};
    for (int axis = 0; axis < 3; ++axis) delta_vector[axis] = component[axis] - work_old_component[axis];
    const float frame_speed = length3(delta_vector[0], delta_vector[1], delta_vector[2]) / view.frame_delta_time;
    view.pre_limit_moving_speed = frame_speed;
    view.movement_speed_limited = view.movement_speed_limit >= 0.0f && frame_speed > view.movement_speed_limit;
    if (view.movement_speed_limited) {
        const float limit_ratio = clamp_float(
            (frame_speed - view.movement_speed_limit) / frame_speed, 0.0f, 1.0f
        );
        move_shift_ratio += (1.0f - move_shift_ratio) * limit_ratio;
        for (int axis = 0; axis < 3; ++axis) {
            work_old_component[axis] += (component[axis] - work_old_component[axis]) * limit_ratio;
        }
    }
    const float rotation_cosine = clamp_float(
        std::fabs(quat_dot_abs(work_old_rotation, component_rotation)), 0.0f, 1.0f
    );
    const float rotation_speed = (2.0f * std::acos(rotation_cosine) * 180.0f / kPi) /
        view.frame_delta_time;
    view.rotation_speed_limited = view.rotation_speed_limit >= 0.0f && rotation_speed > view.rotation_speed_limit;
    if (view.rotation_speed_limited) {
        const float limit_ratio = clamp_float(
            (rotation_speed - view.rotation_speed_limit) / rotation_speed, 0.0f, 1.0f
        );
        rotation_shift_ratio += (1.0f - rotation_shift_ratio) * limit_ratio;
        center_slerp_xyzw(work_old_rotation, component_rotation, limit_ratio, work_old_rotation);
    }
    float other_shift_ratio = 0.0f;
    if (view.skip_count > 0) {
        const float denominator = view.frame_delta_time * view.time_scale;
        const float skip_ratio = denominator <= kMc2Epsilon
            ? 1.0f
            : clamp_float((static_cast<float>(view.skip_count) * view.simulation_delta_time) / denominator, 0.0f, 1.0f);
        other_shift_ratio += (1.0f - other_shift_ratio) * skip_ratio;
    }
    if (view.velocity_weight < 1.0f) {
        const float ratio = 1.0f - view.velocity_weight;
        other_shift_ratio += (1.0f - other_shift_ratio) * ratio;
    }
    if (view.time_scale < 1.0f) {
        const float ratio = 1.0f - view.time_scale;
        other_shift_ratio += (1.0f - other_shift_ratio) * ratio;
    }
    if (other_shift_ratio > 0.0f) {
        move_shift_ratio += (1.0f - move_shift_ratio) * other_shift_ratio;
        rotation_shift_ratio += (1.0f - rotation_shift_ratio) * other_shift_ratio;
        for (int axis = 0; axis < 3; ++axis) {
            work_old_component[axis] += (component[axis] - work_old_component[axis]) * other_shift_ratio;
        }
        center_slerp_xyzw(work_old_rotation, component_rotation, other_shift_ratio, work_old_rotation);
    }
    float world_shift[3] {};
    for (int axis = 0; axis < 3; ++axis) world_shift[axis] = full_shift[axis] * move_shift_ratio;
    std::copy_n(world_shift, 3, view.world_shift_vector);
    for (int axis = 0; axis < 3; ++axis) {
        view.frame_component_shift_vector[axis] =
            world_shift[axis] + view.anchor_shift_vector[axis] + smooth_shift[axis];
    }
    float world_shift_rotation[4] {};
    center_slerp_xyzw(identity, full_shift_rotation, rotation_shift_ratio, world_shift_rotation);
    quat_multiply(anchor_shift_rotation, world_shift_rotation, view.frame_component_shift_rotation);
    auto shift_position = [&](const float* position, float* output) {
        float relative[3] {};
        for (int axis = 0; axis < 3; ++axis) relative[axis] = position[axis] - old_component[axis];
        float rotated[3] {};
        center_rotate_vector(view.frame_component_shift_rotation, relative, rotated);
        for (int axis = 0; axis < 3; ++axis) {
            output[axis] = old_component[axis] + rotated[axis] + view.frame_component_shift_vector[axis];
        }
    };
    shift_position(view.old_frame_world_position, view.shifted_old_frame_position);
    shift_position(view.now_world_position, view.shifted_now_position);
    quat_multiply(view.frame_component_shift_rotation, view.old_frame_world_rotation, view.shifted_old_frame_rotation);
    quat_multiply(view.frame_component_shift_rotation, view.now_world_rotation, view.shifted_now_rotation);
    for (int axis = 0; axis < 3; ++axis) {
        const float moving = component[axis] - work_old_component[axis];
        view.frame_moving_direction[axis] = moving;
    }
    const float moving_length = length3(
        view.frame_moving_direction[0], view.frame_moving_direction[1], view.frame_moving_direction[2]
    );
    if (moving_length > kMc2Epsilon) {
        for (float& value : view.frame_moving_direction) value /= moving_length;
    } else {
        std::fill_n(view.frame_moving_direction, 3, 0.0f);
    }
    view.frame_moving_speed = moving_length / view.frame_delta_time;
    if (view.time_scale > kMc2Epsilon) view.frame_moving_speed /= view.time_scale;
    else view.frame_moving_speed = 0.0f;
    std::copy_n(smoothing_velocity, 3, view.smoothing_velocity_output);
    return true;
}

bool evaluate_center_step_mc2(Mc2CenterStepView& view) {
    if (view.dt <= kMc2Epsilon) return false;
    const float ratio = view.frame_interpolation;
    for (std::size_t component = 0; component < 3; ++component) {
        view.now_world_position[component] =
            view.old_frame_world_position[component] * (1.0f - ratio) +
            view.frame_world_position[component] * ratio;
        view.step_vector[component] =
            view.now_world_position[component] - view.old_world_position[component];
    }
    center_slerp_xyzw(
        view.old_frame_world_rotation,
        view.frame_world_rotation,
        ratio,
        view.now_world_rotation
    );
    float inverse_old[4];
    quat_inverse(view.old_world_rotation, inverse_old);
    quat_multiply(view.now_world_rotation, inverse_old, view.step_rotation);
    float rotation_cosine = 0.0f;
    for (std::size_t component = 0; component < 4; ++component) {
        rotation_cosine += view.old_world_rotation[component] *
            view.now_world_rotation[component];
    }
    const float step_angle = 2.0f * std::acos(
        std::max(0.0f, std::min(1.0f, std::fabs(rotation_cosine)))
    );

    float move_inertia = 1.0f - view.local_inertia;
    float rotation_inertia = 1.0f - view.local_inertia;
    const float local_speed = std::sqrt(
        view.step_vector[0] * view.step_vector[0] +
        view.step_vector[1] * view.step_vector[1] +
        view.step_vector[2] * view.step_vector[2]
    ) * (1.0f - move_inertia) / view.dt;
    if (local_speed > view.local_movement_speed_limit && view.local_movement_speed_limit >= 0.0f) {
        const float limit_ratio = view.local_movement_speed_limit / local_speed;
        move_inertia = 1.0f + (move_inertia - 1.0f) * limit_ratio;
    }
    const float local_angle_speed =
        step_angle * (1.0f - rotation_inertia) / view.dt * 57.29577951308232f;
    if (local_angle_speed > view.local_rotation_speed_limit && view.local_rotation_speed_limit >= 0.0f) {
        const float limit_ratio = view.local_rotation_speed_limit / local_angle_speed;
        rotation_inertia = 1.0f + (rotation_inertia - 1.0f) * limit_ratio;
    }
    view.move_inertia_ratio = move_inertia;
    view.rotation_inertia_ratio = rotation_inertia;
    for (std::size_t component = 0; component < 3; ++component) {
        view.inertia_vector[component] = view.step_vector[component] * move_inertia;
    }
    const float identity[4] = {0.0f, 0.0f, 0.0f, 1.0f};
    quat_slerp(identity, view.step_rotation, rotation_inertia, view.inertia_rotation);
    view.angular_velocity = step_angle / view.dt;
    const float axis_length = std::sqrt(
        view.step_rotation[0] * view.step_rotation[0] +
        view.step_rotation[1] * view.step_rotation[1] +
        view.step_rotation[2] * view.step_rotation[2]
    );
    for (std::size_t component = 0; component < 3; ++component) {
        view.rotation_axis[component] =
            view.angular_velocity > kMc2Epsilon && axis_length > kMc2Epsilon
            ? view.step_rotation[component] / axis_length
            : 0.0f;
    }

    float world_scale[3] {};
    float world_scale_length_squared = 0.0f;
    float initial_scale_length_squared = 0.0f;
    for (std::size_t component = 0; component < 3; ++component) {
        world_scale[component] =
            view.old_frame_world_scale[component] * (1.0f - ratio) +
            view.frame_world_scale[component] * ratio;
        world_scale_length_squared += world_scale[component] * world_scale[component];
        initial_scale_length_squared += view.initial_scale[component] * view.initial_scale[component];
    }
    view.scale_ratio = std::max(
        std::sqrt(world_scale_length_squared / initial_scale_length_squared),
        1.0e-6f
    );

    float initial_gravity[3] = {
        view.initial_local_gravity_direction[0],
        view.initial_local_gravity_direction[1] * view.negative_scale_direction[1],
        view.initial_local_gravity_direction[2],
    };
    float world_falloff[3] {};
    center_rotate_vector(view.now_world_rotation, initial_gravity, world_falloff);
    const float gravity_length_squared =
        view.world_gravity[0] * view.world_gravity[0] +
        view.world_gravity[1] * view.world_gravity[1] +
        view.world_gravity[2] * view.world_gravity[2];
    view.gravity_dot = 1.0f;
    if (gravity_length_squared > kMc2Epsilon) {
        const float dot = world_falloff[0] * view.world_gravity[0] +
            world_falloff[1] * view.world_gravity[1] +
            world_falloff[2] * view.world_gravity[2];
        view.gravity_dot = clamp_float(dot * 0.5f + 0.5f, 0.0f, 1.0f);
    }
    view.gravity_ratio = 1.0f;
    if (view.gravity > 1.0e-6f && view.gravity_falloff > 1.0e-6f) {
        const float minimum = clamp_float(1.0f - view.gravity_falloff, 0.0f, 1.0f);
        view.gravity_ratio = minimum + (1.0f - minimum) *
            clamp_float(1.0f - view.gravity_dot, 0.0f, 1.0f);
    }
    view.output_velocity_weight = view.velocity_weight;
    if (view.output_velocity_weight < 1.0f) {
        const float added = view.stabilization_time > 1.0e-6f
            ? view.dt / view.stabilization_time
            : 1.0f;
        view.output_velocity_weight = clamp_float(
            view.output_velocity_weight + added, 0.0f, 1.0f
        );
    }
    view.output_blend_weight = clamp_float(
        view.output_velocity_weight * view.blend_weight * view.distance_weight,
        0.0f,
        1.0f
    );
    return true;
}

void integrate_particles_mc2(Mc2ParticleIntegrationView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.velocities == nullptr) {
        return;
    }
    if (view.inv_masses == nullptr &&
        (view.attributes == nullptr || view.move_attribute_mask == 0)) {
        return;
    }
    if (view.damping_values == nullptr &&
        (view.damping_curve16 == nullptr || view.depths == nullptr)) {
        return;
    }
    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const bool movable = view.inv_masses != nullptr
            ? view.inv_masses[vertex] > kMc2Epsilon
            : (view.attributes[vertex] & view.move_attribute_mask) != 0u;
        if (!movable) continue;
        const float damping = view.damping_values != nullptr
            ? view.damping_values[vertex]
            : sample_curve16_values(view.damping_curve16, view.depths[vertex]);
        const float damping_factor = clamp_float(
            1.0f - damping * view.simulation_power, 0.0f, 1.0f
        );
        const auto offset = vertex * 3;
        for (std::int64_t component = 0; component < 3; ++component) {
            float velocity = view.velocities[offset + component] *
                view.velocity_weight * damping_factor;
            velocity += view.gravity[component] * view.dt;
            view.velocities[offset + component] = velocity;
            view.positions[offset + component] += velocity * view.dt;
        }
    }
}

void apply_partition_keep_transform_mc2(Mc2PartitionKeepTransformView& view) {
    if (view.particle_count <= 0 || view.partition_count <= 0 ||
        view.positions == nullptr || view.rotations == nullptr || view.velocities == nullptr ||
        view.particle_partition_index == nullptr || view.particle_attribute_flags == nullptr ||
        view.partition_frame_flags == nullptr || view.old_partition_positions == nullptr ||
        view.old_partition_rotations == nullptr || view.old_partition_linear == nullptr ||
        view.new_partition_positions == nullptr || view.new_partition_rotations == nullptr ||
        view.new_partition_linear == nullptr) {
        return;
    }
    std::vector<float> inverse_linear(static_cast<std::size_t>(view.partition_count) * 9);
    std::vector<float> delta_rotations(static_cast<std::size_t>(view.partition_count) * 4);
    std::vector<std::uint8_t> active(static_cast<std::size_t>(view.partition_count), 0u);
    for (std::int64_t partition = 0; partition < view.partition_count; ++partition) {
        if ((view.partition_frame_flags[partition] & view.keep_frame_mask) == 0u) continue;
        float* inverse = inverse_linear.data() + partition * 9;
        if (!inverse_matrix3(view.old_partition_linear + partition * 9, inverse)) continue;
        float old_inverse[4];
        quat_inverse(view.old_partition_rotations + partition * 4, old_inverse);
        quat_multiply(
            view.new_partition_rotations + partition * 4,
            old_inverse,
            delta_rotations.data() + partition * 4
        );
        active[partition] = 1u;
    }
    for (std::int64_t particle = 0; particle < view.particle_count; ++particle) {
        if ((view.particle_attribute_flags[particle] & view.fixed_attribute_mask) != 0u) continue;
        const auto partition = static_cast<std::int64_t>(view.particle_partition_index[particle]);
        if (partition < 0 || partition >= view.partition_count || !active[partition]) continue;
        const auto offset = particle * 3;
        const float* old_position = view.old_partition_positions + partition * 3;
        const float* new_position = view.new_partition_positions + partition * 3;
        const float* inverse = inverse_linear.data() + partition * 9;
        const float* linear = view.new_partition_linear + partition * 9;
        const float relative[3] = {
            view.positions[offset + 0] - old_position[0],
            view.positions[offset + 1] - old_position[1],
            view.positions[offset + 2] - old_position[2],
        };
        const float local[3] = {
            inverse[0] * relative[0] + inverse[1] * relative[1] + inverse[2] * relative[2],
            inverse[3] * relative[0] + inverse[4] * relative[1] + inverse[5] * relative[2],
            inverse[6] * relative[0] + inverse[7] * relative[1] + inverse[8] * relative[2],
        };
        view.positions[offset + 0] = new_position[0] +
            linear[0] * local[0] + linear[1] * local[1] + linear[2] * local[2];
        view.positions[offset + 1] = new_position[1] +
            linear[3] * local[0] + linear[4] * local[1] + linear[5] * local[2];
        view.positions[offset + 2] = new_position[2] +
            linear[6] * local[0] + linear[7] * local[1] + linear[8] * local[2];
        float velocity_x = 0.0f;
        float velocity_y = 0.0f;
        float velocity_z = 0.0f;
        quat_rotate(
            delta_rotations.data() + partition * 4,
            view.velocities[offset + 0],
            view.velocities[offset + 1],
            view.velocities[offset + 2],
            velocity_x, velocity_y, velocity_z
        );
        view.velocities[offset + 0] = velocity_x;
        view.velocities[offset + 1] = velocity_y;
        view.velocities[offset + 2] = velocity_z;
        const auto rotation_offset = particle * 4;
        float transformed_rotation[4];
        quat_multiply(
            delta_rotations.data() + partition * 4,
            view.rotations + rotation_offset,
            transformed_rotation
        );
        std::copy_n(transformed_rotation, 4, view.rotations + rotation_offset);
    }
}

void apply_centrifugal_velocity_mc2(Mc2CentrifugalView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.velocities == nullptr ||
        view.depths == nullptr || view.inv_masses == nullptr) {
        return;
    }

    const float centrifugal = clamp_float(view.centrifugal, 0.0f, 1.0f);
    if (centrifugal <= kMc2Epsilon || view.angular_velocity <= kMc2Epsilon) {
        return;
    }
    const float raw_axis_len =
        std::sqrt(view.rotation_axis[0] * view.rotation_axis[0] + view.rotation_axis[1] * view.rotation_axis[1] +
                  view.rotation_axis[2] * view.rotation_axis[2]);
    if (raw_axis_len <= kMc2Epsilon) {
        return;
    }
    float axis_x = 0.0f;
    float axis_y = 1.0f;
    float axis_z = 0.0f;
    safe_normal_with_fallback(view.rotation_axis[0], view.rotation_axis[1], view.rotation_axis[2],
                              0.0f, 1.0f, 0.0f, axis_x, axis_y, axis_z);

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        if (view.inv_masses[vertex] <= kMc2Epsilon) {
            continue;
        }
        const std::int64_t offset = vertex * 3;
        const float velocity_x = view.velocities[offset + 0];
        const float velocity_y = view.velocities[offset + 1];
        const float velocity_z = view.velocities[offset + 2];
        const float speed = std::sqrt(velocity_x * velocity_x + velocity_y * velocity_y + velocity_z * velocity_z);
        if (speed <= kMc2Epsilon) {
            continue;
        }

        const float local_x = view.positions[offset + 0] - view.now_world_position[0];
        const float local_y = view.positions[offset + 1] - view.now_world_position[1];
        const float local_z = view.positions[offset + 2] - view.now_world_position[2];
        const float radial_dot = dot3(local_x, local_y, local_z, axis_x, axis_y, axis_z);
        const float radial_x = local_x - axis_x * radial_dot;
        const float radial_y = local_y - axis_y * radial_dot;
        const float radial_z = local_z - axis_z * radial_dot;
        const float radius = std::sqrt(radial_x * radial_x + radial_y * radial_y + radial_z * radial_z);
        if (radius <= kMc2Epsilon) {
            continue;
        }

        const float n_x = radial_x / radius;
        const float n_y = radial_y / radius;
        const float n_z = radial_z / radius;
        float tangent_x = 0.0f;
        float tangent_y = 0.0f;
        float tangent_z = 0.0f;
        cross3(axis_x, axis_y, axis_z, n_x, n_y, n_z, tangent_x, tangent_y, tangent_z);
        safe_normal_with_fallback(tangent_x, tangent_y, tangent_z, 0.0f, 0.0f, 0.0f,
                                  tangent_x, tangent_y, tangent_z);
        const float forward_x = velocity_x / speed;
        const float forward_y = velocity_y / speed;
        const float forward_z = velocity_z / speed;
        const float strength = std::max(0.0f, dot3(forward_x, forward_y, forward_z, tangent_x, tangent_y, tangent_z));
        const float depth = clamp_float(view.depths[vertex], 0.0f, 1.0f);
        const float mass = 1.0f + (1.0f - depth);
        const float force = mass * view.angular_velocity * view.angular_velocity * radius;
        const float add = force * centrifugal * 0.02f * strength;
        view.velocities[offset + 0] = velocity_x + n_x * add;
        view.velocities[offset + 1] = velocity_y + n_y * add;
        view.velocities[offset + 2] = velocity_z + n_z * add;
    }
}

void calculate_display_positions_mc2(Mc2DisplayPredictionView& view) {
    if (view.vertex_count <= 0 || view.positions == nullptr || view.real_velocities == nullptr ||
        view.root_indices == nullptr || view.display_positions == nullptr) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t offset = vertex * 3;
        view.display_positions[offset + 0] = view.positions[offset + 0];
        view.display_positions[offset + 1] = view.positions[offset + 1];
        view.display_positions[offset + 2] = view.positions[offset + 2];
    }
    if (view.frame_dt <= kMc2Epsilon) {
        return;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int64_t offset = vertex * 3;
        view.display_positions[offset + 0] = view.positions[offset + 0] + view.real_velocities[offset + 0] * view.frame_dt;
        view.display_positions[offset + 1] = view.positions[offset + 1] + view.real_velocities[offset + 1] * view.frame_dt;
        view.display_positions[offset + 2] = view.positions[offset + 2] + view.real_velocities[offset + 2] * view.frame_dt;
    }

    for (std::int64_t vertex = 0; vertex < view.vertex_count; ++vertex) {
        const std::int32_t root_index = view.root_indices[vertex];
        if (root_index < 0 || static_cast<std::int64_t>(root_index) >= view.vertex_count) {
            continue;
        }

        const std::int64_t offset = vertex * 3;
        const std::int64_t root_offset = static_cast<std::int64_t>(root_index) * 3;
        const float root_x = view.positions[root_offset + 0];
        const float root_y = view.positions[root_offset + 1];
        const float root_z = view.positions[root_offset + 2];
        const float original_x = view.positions[offset + 0] - root_x;
        const float original_y = view.positions[offset + 1] - root_y;
        const float original_z = view.positions[offset + 2] - root_z;
        const float original_dist =
            std::sqrt(original_x * original_x + original_y * original_y + original_z * original_z);
        const float clamp_dist = original_dist * view.max_distance_ratio;
        if (clamp_dist <= kMc2Epsilon) {
            continue;
        }

        const float delta_x = view.display_positions[offset + 0] - root_x;
        const float delta_y = view.display_positions[offset + 1] - root_y;
        const float delta_z = view.display_positions[offset + 2] - root_z;
        const float length = std::sqrt(delta_x * delta_x + delta_y * delta_y + delta_z * delta_z);
        if (length > clamp_dist && length > kMc2Epsilon) {
            const float scale = clamp_dist / length;
            view.display_positions[offset + 0] = root_x + delta_x * scale;
            view.display_positions[offset + 1] = root_y + delta_y * scale;
            view.display_positions[offset + 2] = root_z + delta_z * scale;
        }
    }
}

}  // namespace hotools
