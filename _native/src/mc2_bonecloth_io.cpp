// BoneCloth 后处理旋转写回（C++ 实现）。
//
// 对应 MC2 SimulationPostProxyMeshUpdateLine（VirtualMeshManager.cs L790-950）。
// 自顶向下遍历每条 baseline 链，把模拟后的粒子位置转换为链式传播的世界空间旋转。

#include "hotools_mc2_bonecloth_io.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace hotools {
namespace {

constexpr float kBcEpsilon = 1e-8f;
constexpr std::uint8_t kMc2AttrMove = 1u << 2u;

// ---------------------------------------------------------------------------
// 四元数工具（格式统一为 [x,y,z,w]）
// ---------------------------------------------------------------------------

struct Quat {
    float x, y, z, w;
};

struct Vec3 {
    float x, y, z;
};

inline float dot3(const Vec3& a, const Vec3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

inline float len3(const Vec3& v) {
    return std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

inline Vec3 normalize3(const Vec3& v) {
    const float n = len3(v);
    if (n <= kBcEpsilon) { return {0.f, 0.f, 1.f}; }
    return {v.x / n, v.y / n, v.z / n};
}

inline Vec3 cross3(const Vec3& a, const Vec3& b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

inline Quat qnorm(const Quat& q) {
    const float n = std::sqrt(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w);
    if (n <= kBcEpsilon) { return {0.f, 0.f, 0.f, 1.f}; }
    return {q.x/n, q.y/n, q.z/n, q.w/n};
}

inline Quat qmul(const Quat& a, const Quat& b) {
    return qnorm(Quat{
        a.w*b.x + a.x*b.w + a.y*b.z - a.z*b.y,
        a.w*b.y - a.x*b.z + a.y*b.w + a.z*b.x,
        a.w*b.z + a.x*b.y - a.y*b.x + a.z*b.w,
        a.w*b.w - a.x*b.x - a.y*b.y - a.z*b.z,
    });
}

inline Quat qinv(const Quat& q) {
    const Quat n = qnorm(q);
    return {-n.x, -n.y, -n.z, n.w};
}

// 用四元数旋转向量
inline Vec3 qrot(const Quat& q, const Vec3& v) {
    const Quat nq = qnorm(q);
    const Vec3 qv = {nq.x, nq.y, nq.z};
    const Vec3 uv = cross3(qv, v);
    const Vec3 uuv = cross3(qv, uv);
    return {
        v.x + 2.f * (nq.w * uv.x + uuv.x),
        v.y + 2.f * (nq.w * uv.y + uuv.y),
        v.z + 2.f * (nq.w * uv.z + uuv.z),
    };
}

// 球面线性插值
inline Quat qslerp(const Quat& a, const Quat& b, float t) {
    t = std::max(0.f, std::min(1.f, t));
    Quat qa = qnorm(a);
    Quat qb = qnorm(b);
    float d = qa.x*qb.x + qa.y*qb.y + qa.z*qb.z + qa.w*qb.w;
    if (d < 0.f) { qb = {-qb.x, -qb.y, -qb.z, -qb.w}; d = -d; }
    if (d > 0.9995f) {
        return qnorm({
            qa.x + (qb.x - qa.x) * t,
            qa.y + (qb.y - qa.y) * t,
            qa.z + (qb.z - qa.z) * t,
            qa.w + (qb.w - qa.w) * t,
        });
    }
    const float theta0 = std::acos(std::max(-1.f, std::min(1.f, d)));
    const float theta  = theta0 * t;
    const float st     = std::sin(theta);
    const float st0    = std::sin(theta0);
    const float s0 = std::cos(theta) - d * st / st0;
    const float s1 = st / st0;
    return qnorm({
        s0*qa.x + s1*qb.x,
        s0*qa.y + s1*qb.y,
        s0*qa.z + s1*qb.z,
        s0*qa.w + s1*qb.w,
    });
}

// MC2 MathUtility.FromToRotation：从向量 v1 旋转到 v2，角度乘以 t
// 对应 VirtualMeshManager.cs L932 使用的 MathUtility.FromToRotation(ctv, cv, t)
inline Quat from_to_rotation(const Vec3& v1_in, const Vec3& v2_in, float t = 1.f) {
    const Vec3 nv1 = normalize3(v1_in);
    const Vec3 nv2 = normalize3(v2_in);

    float c = dot3(nv1, nv2);
    c = std::max(-1.f, std::min(1.f, c));

    // 完全相反：180° 绕垂直轴旋转
    if (std::abs(1.f + c) < 1e-6f) {
        Vec3 axis;
        if (std::abs(nv1.x) > std::abs(nv1.y) && std::abs(nv1.x) > std::abs(nv1.z)) {
            axis = cross3(nv1, {0.f, 1.f, 0.f});
        } else {
            axis = cross3(nv1, {1.f, 0.f, 0.f});
        }
        const float an = len3(axis);
        if (an <= kBcEpsilon) { return {0.f, 0.f, 0.f, 1.f}; }
        const float angle = 3.14159265f * t * 0.5f;
        const float s = std::sin(angle);
        const float cw = std::cos(angle);
        return qnorm({axis.x/an * s, axis.y/an * s, axis.z/an * s, cw});
    }
    // 完全相同：identity
    if (std::abs(1.f - c) < 1e-6f) { return {0.f, 0.f, 0.f, 1.f}; }

    const float angle = std::acos(c) * t;
    const Vec3 axis = cross3(nv1, nv2);
    const float an = len3(axis);
    if (an <= kBcEpsilon) { return {0.f, 0.f, 0.f, 1.f}; }
    const float s  = std::sin(angle * 0.5f);
    const float cw = std::cos(angle * 0.5f);
    return qnorm({axis.x/an * s, axis.y/an * s, axis.z/an * s, cw});
}

// ---------------------------------------------------------------------------
// 数组访问辅助
// ---------------------------------------------------------------------------

inline Vec3 load3(const float* arr, std::int64_t i) {
    return {arr[i*3], arr[i*3+1], arr[i*3+2]};
}

inline Quat load4(const float* arr, std::int64_t i) {
    return {arr[i*4], arr[i*4+1], arr[i*4+2], arr[i*4+3]};
}

inline void store4(float* arr, std::int64_t i, const Quat& q) {
    arr[i*4]   = q.x;
    arr[i*4+1] = q.y;
    arr[i*4+2] = q.z;
    arr[i*4+3] = q.w;
}

}  // namespace

// ---------------------------------------------------------------------------
// 主函数：SimulationPostProxyMeshUpdateLine 移植
// ---------------------------------------------------------------------------

void solve_bonecloth_io(BoneClothIoView& view) {
    const auto N  = view.vertex_count;
    const auto NL = view.baseline_lines;
    if (N <= 0 || NL <= 0) { return; }

    // 预建子骨列表（parent_indices → children）
    std::vector<std::vector<std::int32_t>> children_of(static_cast<std::size_t>(N));
    for (std::int64_t ci = 0; ci < N; ++ci) {
        const std::int32_t pi = view.parent_indices[ci];
        if (pi >= 0 && pi < N) {
            children_of[static_cast<std::size_t>(pi)].push_back(static_cast<std::int32_t>(ci));
        }
    }

    const float average_rate = view.rotational_interpolation;
    const float bw           = std::max(0.f, std::min(1.f, view.blend_weight));
    const float ar           = std::max(0.f, std::min(1.f, view.anime_ratio));

    // 按 baseline 链自顶向下遍历（与 Python 版逻辑完全一致）
    for (std::int64_t line_idx = 0; line_idx < NL; ++line_idx) {
        const std::int32_t start = view.baseline_start[line_idx];
        const std::int32_t count = view.baseline_count[line_idx];

        for (std::int32_t data_off = 0; data_off < count; ++data_off) {
            const std::int32_t data_idx = start + data_off;
            if (data_idx < 0 || data_idx >= view.baseline_total) { continue; }
            const std::int32_t lindex = view.baseline_data[data_idx];
            if (lindex < 0 || lindex >= N) { continue; }

            const Vec3 pos      = load3(view.display_positions, lindex);
            Quat       rot      = load4(view.world_rotations,   lindex);
            const Vec3 base_pos = load3(view.base_positions,    lindex);
            const Quat base_rot = load4(view.base_rotations,    lindex);
            const Quat base_inv = qinv(base_rot);

            const bool is_move  = (view.attributes[lindex] & kMc2AttrMove) != 0;
            const auto& ch_list = children_of[static_cast<std::size_t>(lindex)];

            if (!ch_list.empty()) {
                Vec3 ctv = {0.f, 0.f, 0.f};
                Vec3 cv  = {0.f, 0.f, 0.f};

                for (const std::int32_t clindex : ch_list) {
                    if (clindex < 0 || clindex >= N) { continue; }

                    const bool c_is_move = (view.attributes[clindex] & kMc2AttrMove) != 0;
                    const Vec3 cpos      = load3(view.display_positions,      clindex);
                    const Vec3 cbase_pos = load3(view.base_positions,         clindex);
                    const Quat cbase_rot = load4(view.base_rotations,         clindex);

                    // 子骨在父骨 base pose local 空间的位置和旋转
                    const Vec3 cbase_local_pos = qrot(base_inv, {
                        cbase_pos.x - base_pos.x,
                        cbase_pos.y - base_pos.y,
                        cbase_pos.z - base_pos.z,
                    });
                    const Quat cbase_local_rot = qmul(base_inv, cbase_rot);

                    // rest local 与 animated local 按 anime_ratio 插值
                    const Vec3 vl_pos = load3(view.vertex_local_positions, clindex);
                    const Quat vl_rot = load4(view.vertex_local_rotations, clindex);
                    const Vec3 lpos = {
                        vl_pos.x * (1.f - ar) + cbase_local_pos.x * ar,
                        vl_pos.y * (1.f - ar) + cbase_local_pos.y * ar,
                        vl_pos.z * (1.f - ar) + cbase_local_pos.z * ar,
                    };
                    const Quat lrot = qslerp(vl_rot, cbase_local_rot, ar);

                    // rest 方向（tv）= rot * lpos
                    const Vec3 tv = qrot(rot, lpos);
                    ctv = {ctv.x + tv.x, ctv.y + tv.y, ctv.z + tv.z};

                    if (c_is_move) {
                        const Vec3 v = {
                            cpos.x - pos.x,
                            cpos.y - pos.y,
                            cpos.z - pos.z,
                        };
                        cv = {cv.x + v.x, cv.y + v.y, cv.z + v.z};

                        // 子骨旋转：rot * lrot，再由 FromToRotation(tv, v) 修正
                        Quat crot = qmul(rot, lrot);
                        if (len3(tv) > kBcEpsilon && len3(v) > kBcEpsilon) {
                            const Quat q_corr = from_to_rotation(tv, v);
                            crot = qmul(q_corr, crot);
                        }
                        store4(view.world_rotations, clindex, crot);
                    } else {
                        // 固定子骨：sim 方向同 rest 方向
                        cv = {cv.x + tv.x, cv.y + tv.y, cv.z + tv.z};
                    }
                }

                // 父骨方向修正
                const float t_parent = is_move ? average_rate : 1.f;
                if (len3(ctv) > kBcEpsilon && len3(cv) > kBcEpsilon) {
                    const Quat cq = from_to_rotation(ctv, cv, t_parent);
                    rot = qmul(cq, rot);
                }
            }

            // blendWeight：混合 base pose 与模拟旋转
            rot = qslerp(base_rot, rot, bw);
            store4(view.world_rotations, lindex, rot);
        }
    }
}

}  // namespace hotools
