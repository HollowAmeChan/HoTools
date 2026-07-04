#pragma once

#include <cstdint>

namespace hotools {

// BoneCloth 后处理旋转写回的输入/输出 View。
// 对应 MC2 SimulationPostProxyMeshUpdateLine（VirtualMeshManager.cs L790）。
//
// 输入数组（只读）：
//   display_positions     (N, 3) float32  模拟后世界空间粒子位置
//   base_positions        (N, 3) float32  当前帧 base pose 粒子位置（step_basic_positions）
//   base_rotations        (N, 4) float32  当前帧 base pose 旋转 [x,y,z,w]（step_basic_rotations）
//   vertex_local_positions(N, 3) float32  子骨在父骨 local 空间的 rest 位置
//   vertex_local_rotations(N, 4) float32  子骨相对父骨的 rest local 旋转 [x,y,z,w]
//   parent_indices        (N,)   int32    每粒子的父粒子索引，-1 表示 root
//   baseline_start        (L,)   int32    每条 baseline 链在 baseline_data 的起始偏移
//   baseline_count        (L,)   int32    每条 baseline 链的长度（顶点数）
//   baseline_data         (M,)   int32    自顶向下遍历顺序的粒子全局索引
//   attributes            (N,)   uint8    MC2_ATTR_MOVE 标记（bit 2），root = 0，move = 4
//
// 标量参数：
//   rotational_interpolation  float  父骨方向修正插值率（averageRate, 0..1）
//   blend_weight              float  模拟结果与 base pose 的混合权重（0..1）
//   anime_ratio               float  rest / animated local pose 插值率（animationPoseRatio）
//
// 输出数组（读写）：
//   world_rotations       (N, 4) float32  计算结果：世界空间四元数 [x,y,z,w]
//                                         初始值应为 base_rotations，函数在原地修改。
struct BoneClothIoView {
    // 输入（只读）
    const float*         display_positions      = nullptr;  // (N, 3)
    const float*         base_positions         = nullptr;  // (N, 3)
    const float*         base_rotations         = nullptr;  // (N, 4) [xyzw]
    const float*         vertex_local_positions = nullptr;  // (N, 3)
    const float*         vertex_local_rotations = nullptr;  // (N, 4) [xyzw]
    const std::int32_t*  parent_indices         = nullptr;  // (N,)
    const std::int32_t*  baseline_start         = nullptr;  // (L,)
    const std::int32_t*  baseline_count         = nullptr;  // (L,)
    const std::int32_t*  baseline_data          = nullptr;  // (M,)
    const std::uint8_t*  attributes             = nullptr;  // (N,)

    // 标量参数
    float  rotational_interpolation = 1.0f;
    float  blend_weight             = 1.0f;
    float  anime_ratio              = 0.0f;

    // 数组长度
    std::int64_t vertex_count   = 0;
    std::int64_t baseline_lines = 0;  // L：baseline 链数
    std::int64_t baseline_total = 0;  // M：baseline_data 总长度

    // 输出（原地修改，调用前应已复制 base_rotations 的内容）
    float* world_rotations = nullptr;  // (N, 4) [xyzw]
};

// 执行 BoneCloth 后处理旋转写回。
// 遍历每条 baseline 链（自顶向下），按 MC2 SimulationPostProxyMeshUpdateLine 语义
// 传播链式旋转，结果写入 view.world_rotations。
void solve_bonecloth_io(BoneClothIoView& view);

}  // namespace hotools
