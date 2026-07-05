// spring_bone_vrm_bindings.cpp  ——  nanobind 绑定
// 替换原始 CPython 手工绑定，python_buffer_utils.hpp 不再需要。

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include "hotools_spring_bone_vrm.hpp"

#include <cstdint>

namespace nb = nanobind;
namespace hotools {

using F1  = nb::ndarray<float,    nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using F2  = nb::ndarray<float,    nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using I1  = nb::ndarray<int32_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using U1  = nb::ndarray<uint8_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using F2w = F2;

// ---------------------------------------------------------------------------
// solve_spring_bone_vrm_cpp — 35 个位置参数（前30个 ndarray，后5个标量）
// ---------------------------------------------------------------------------
static void solve_spring_bone_vrm_impl(
    F2w current_tails,           // 0
    F2w prev_tails,              // 1
    F2w target_matrices,         // 2  (n, 16)
    F2w target_quaternions,      // 3
    F2  current_heads,           // 4
    F2  current_pose_matrices,   // 5  (n, 16)
    F2  current_pose_quaternions,// 6
    F2  parent_pose_quaternions, // 7
    F2  current_pose_tails,      // 8
    F1  lengths,                 // 9
    F2  init_axis_local,         // 10
    F2  init_axis_parent,        // 11
    F2  init_rotations,          // 12
    F2  init_scales,             // 13
    I1  parent_indices,          // 14
    U1  pinned,                  // 15
    U1  use_connect,             // 16
    F1  root_quaternion,         // 17  (4,)
    F1  root_tail_world,         // 18  (3,)
    F1  armature_world,          // 19  (16,)
    F1  armature_world_inv,      // 20  (16,)
    F1  gravity_dir,             // 21  (3,)
    F1  hit_radii,               // 22
    I1  collided_by_groups,      // 23
    I1  collider_types,          // 24
    I1  collider_groups,         // 25
    F2  collider_centers,        // 26
    F2  collider_segment_a,      // 27
    F2  collider_segment_b,      // 28
    F1  collider_radii,          // 29
    double dt,                   // 30
    int    substeps,             // 31
    double stiffness_force,      // 32
    double drag_force,           // 33
    double gravity_power)        // 34
{
    hotools::SpringBoneVrmChainView v{};
    v.current_tails            = current_tails.data();
    v.prev_tails               = prev_tails.data();
    v.target_matrices          = target_matrices.data();
    v.target_quaternions       = target_quaternions.data();
    v.current_heads            = current_heads.data();
    v.current_pose_matrices    = current_pose_matrices.data();
    v.current_pose_quaternions = current_pose_quaternions.data();
    v.parent_pose_quaternions  = parent_pose_quaternions.data();
    v.current_pose_tails       = current_pose_tails.data();
    v.lengths                  = lengths.data();
    v.init_axis_local          = init_axis_local.data();
    v.init_axis_parent         = init_axis_parent.data();
    v.init_rotations           = init_rotations.data();
    v.init_scales              = init_scales.data();
    v.parent_indices           = parent_indices.data();
    v.pinned                   = pinned.data();
    v.use_connect              = use_connect.data();
    v.root_quaternion          = root_quaternion.data();
    v.root_tail_world          = root_tail_world.data();
    v.armature_world           = armature_world.data();
    v.armature_world_inv       = armature_world_inv.data();
    v.gravity_dir              = gravity_dir.data();
    v.hit_radii                = hit_radii.data();
    v.collided_by_groups       = collided_by_groups.data();
    v.collider_types           = collider_types.data();
    v.collider_groups          = collider_groups.data();
    v.collider_centers         = collider_centers.data();
    v.collider_segment_a       = collider_segment_a.data();
    v.collider_segment_b       = collider_segment_b.data();
    v.collider_radii           = collider_radii.data();
    v.bone_count               = static_cast<int64_t>(current_tails.shape(0));
    v.collider_count           = static_cast<int64_t>(collider_types.shape(0));
    v.substeps                 = substeps;
    v.dt                       = static_cast<float>(dt);
    v.stiffness_force          = static_cast<float>(stiffness_force);
    v.drag_force               = static_cast<float>(drag_force);
    v.gravity_power            = static_cast<float>(gravity_power);
    hotools::solve_spring_bone_vrm_cpp(v);
}

void register_spring_bone_vrm(nb::module_& m)
{
    m.def("solve_spring_bone_vrm_cpp", &solve_spring_bone_vrm_impl);
}

}  // namespace hotools
