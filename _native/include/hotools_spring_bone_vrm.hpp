#pragma once

#include <cstdint>
#include <cstddef>
#include <vector>

namespace hotools {

// ─────────────────────────────────────────────────────────────────────────────
// 旧接口（保留，bindings.cpp 还在用）
// ─────────────────────────────────────────────────────────────────────────────

struct SpringBoneVrmChainView {
    float* current_tails = nullptr;
    float* prev_tails = nullptr;
    float* target_matrices = nullptr;
    float* target_quaternions = nullptr;

    const float* current_heads = nullptr;
    const float* current_pose_matrices = nullptr;
    const float* current_pose_quaternions = nullptr;
    const float* parent_pose_quaternions = nullptr;
    const float* current_pose_tails = nullptr;
    const float* lengths = nullptr;
    const float* init_axis_local = nullptr;
    const float* init_axis_parent = nullptr;
    const float* init_rotations = nullptr;
    const float* init_scales = nullptr;
    const std::int32_t* parent_indices = nullptr;
    const std::uint8_t* pinned = nullptr;
    const std::uint8_t* use_connect = nullptr;

    const float* root_quaternion = nullptr;
    const float* root_tail_world = nullptr;
    const float* armature_world = nullptr;
    const float* armature_world_inv = nullptr;
    const float* gravity_dir = nullptr;

    const float* hit_radii = nullptr;
    const std::int32_t* collided_by_groups = nullptr;
    const std::int32_t* collider_types = nullptr;
    const std::int32_t* collider_groups = nullptr;
    const float* collider_centers = nullptr;
    const float* collider_segment_a = nullptr;
    const float* collider_segment_b = nullptr;
    const float* collider_radii = nullptr;

    std::int64_t bone_count = 0;
    std::int64_t collider_count = 0;

    int substeps = 1;
    float dt = 0.0f;
    float stiffness_force = 0.0f;
    float drag_force = 0.0f;
    float gravity_power = 0.0f;
};

void solve_spring_bone_vrm_cpp(SpringBoneVrmChainView& view);


// ─────────────────────────────────────────────────────────────────────────────
// 新 dual-call 接口
//
// 生命周期：
//   ctx = spring_vrm_context_create(schema, bone_count, static_arrays...)
//   spring_vrm_context_reset_state(ctx)          // 可选：restart 时把 tail 重置为 pose tail
//   spring_vrm_context_update_dynamic(ctx, ...)  // 每帧：上传 pose + collider
//   spring_vrm_context_step(ctx, dt, substeps, stiffness, drag, gravity_power)
//   spring_vrm_context_read_results(ctx, out_matrices, out_quaternions)
//   spring_vrm_context_free(ctx)
// ─────────────────────────────────────────────────────────────────────────────

struct SpringVrmContext {
    int schema = 1;
    std::int64_t bone_count = 0;

    // 静态数组（topology dirty / restart 才重填，C++ 持有副本）
    std::vector<float>        lengths;          // (N,)
    std::vector<float>        init_axis_local;  // (N*3,)
    std::vector<float>        init_axis_parent; // (N*3,)
    std::vector<float>        init_rotations;   // (N*4,)
    std::vector<float>        init_scales;      // (N*3,)
    std::vector<std::int32_t> parent_indices;   // (N,)
    std::vector<std::uint8_t> pinned;           // (N,)
    std::vector<std::uint8_t> use_connect;      // (N,)

    // 模拟状态（C++ 持有，每帧由 step 更新）
    std::vector<float> current_tails;           // (N*3,)
    std::vector<float> prev_tails;              // (N*3,)

    // 每帧动态输入（由 update_dynamic 填充）
    std::vector<float>        current_heads;             // (N*3,)
    std::vector<float>        current_pose_matrices;     // (N*16,)
    std::vector<float>        current_pose_quaternions;  // (N*4,)
    std::vector<float>        parent_pose_quaternions;   // (N*4,)
    std::vector<float>        current_pose_tails;        // (N*3,)
    float                     armature_world[16]         = {};
    float                     armature_world_inv[16]     = {};
    float                     root_quaternion[4]         = {0.f, 0.f, 0.f, 1.f};
    float                     root_tail_world[3]         = {};
    float                     gravity_dir[3]             = {};

    // 每帧骨骼碰撞配置（由 update_dynamic 填充）
    std::vector<float>        hit_radii;         // (N,)
    std::vector<std::int32_t> collided_by_groups;// (N,)

    // 每帧碰撞体（由 update_dynamic 填充，数量可变）
    std::vector<std::int32_t> collider_types;    // (M,)
    std::vector<std::int32_t> collider_groups;   // (M,)
    std::vector<float>        collider_centers;  // (M*3,)
    std::vector<float>        collider_segment_a;// (M*3,)
    std::vector<float>        collider_segment_b;// (M*3,)
    std::vector<float>        collider_radii;    // (M,)
    std::int64_t              collider_count = 0;

    // 每帧标量参数（由 step 使用）
    float stiffness_force = 0.f;
    float drag_force      = 0.f;
    float gravity_power   = 0.f;

    // 结果缓冲区（step 写入，read_results 读取）
    std::vector<float> target_matrices;    // (N*16,)
    std::vector<float> target_quaternions; // (N*4,)
};

// 创建并初始化 context（分配内存 + 上传静态数组）
// 返回裸指针，调用方负责传给 spring_vrm_context_free。
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
    const std::uint8_t* use_connect
);

// 重置模拟状态（将 current/prev tails 置为 current_pose_tails）
// restart 时调用，使弹簧从当前 pose tail 位置重新开始。
void spring_vrm_context_reset_state(SpringVrmContext* ctx);

// 更新每帧动态输入（pose arrays + collider arrays + armature matrix）
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
    std::int64_t        collider_count
);

// 推进模拟（消费 dynamic 数据，更新 current/prev tails，写 target_matrices/quaternions）
void spring_vrm_context_step(
    SpringVrmContext* ctx,
    float dt,
    int   substeps,
    float stiffness_force,
    float drag_force,
    float gravity_power
);

// 把结果写入调用方预分配的 buffer（避免每帧在 Python 侧 allocate）
// out_matrices:    (N, 16) float32
// out_quaternions: (N,  4) float32
void spring_vrm_context_read_results(
    const SpringVrmContext* ctx,
    float* out_matrices,
    float* out_quaternions
);

// 释放 context（delete）
void spring_vrm_context_free(SpringVrmContext* ctx);

}  // namespace hotools
