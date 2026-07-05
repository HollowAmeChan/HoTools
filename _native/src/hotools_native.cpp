// hotools_native.cpp  ——  nanobind 绑定层
// 替换原始 CPython 手工绑定，所有 Py_buffer / PyArg_ParseTuple 已删除。
// python_buffer_utils.hpp 不再需要。

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>

#include "hotools_mc2.hpp"
#include "hotools_mc2_bonecloth_io.hpp"
#include "hotools_mesh_xpbd.hpp"
#include "hotools_property_curve.hpp"
#include "hotools_spring_bone_vrm.hpp"

#include <cstdint>
#include <stdexcept>
#include <string>

namespace nb = nanobind;

// ---------------------------------------------------------------------------
// ndarray 别名
// float32，只读 / 可写（nanobind 默认接受可写 buffer，不需要 nb::rw 注解）
using F1  = nb::ndarray<float,    nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using F2  = nb::ndarray<float,    nb::ndim<2>, nb::c_contig, nb::device::cpu>;
// int32
using I1  = nb::ndarray<int32_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using I2  = nb::ndarray<int32_t,  nb::ndim<2>, nb::c_contig, nb::device::cpu>;
// uint8
using U1  = nb::ndarray<uint8_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
// 可写别名（与只读同类型；调用方保证传入可写 numpy array）
using F1w = F1;
using F2w = F2;
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// 工具：把 ndarray 的第 0 维长度取成 int64
// ---------------------------------------------------------------------------
template <typename T>
static inline int64_t n64(const T& arr) { return static_cast<int64_t>(arr.shape(0)); }

// ---------------------------------------------------------------------------
// project_neighbor_constraints_mc2
// ---------------------------------------------------------------------------
static void project_neighbor_constraints_mc2(
    F2w positions, F1 inv_masses,
    I1 starts, I1 counts, I1 neighbors,
    F1 rest_lengths, F1 stiffness_values,
    F2w velocity_positions,
    double velocity_attenuation)
{
    hotools::Mc2NeighborConstraintView v{};
    v.positions          = positions.data();
    v.base_positions     = nullptr;   // 不在此路径使用
    v.inv_masses         = inv_masses.data();
    v.starts             = starts.data();
    v.counts             = counts.data();
    v.neighbors          = neighbors.data();
    v.rest_lengths       = rest_lengths.data();
    v.stiffness_values   = stiffness_values.data();
    v.velocity_positions = velocity_positions.data();
    v.vertex_count       = n64(positions);
    v.neighbor_count     = n64(neighbors);
    v.velocity_attenuation = static_cast<float>(velocity_attenuation);
    v.animation_pose_ratio = 0.0f;
    hotools::project_neighbor_constraints_mc2(v);
}

// ---------------------------------------------------------------------------
// project_tether_mc2
// ---------------------------------------------------------------------------
static void project_tether_mc2(
    F2w positions, F1 inv_masses,
    I1 root_indices, F1 root_rest_lengths,
    F2w velocity_positions,
    double stiffness, double compression, double stretch)
{
    hotools::Mc2TetherConstraintView v{};
    v.positions          = positions.data();
    v.inv_masses         = inv_masses.data();
    v.root_indices       = root_indices.data();
    v.root_rest_lengths  = root_rest_lengths.data();
    v.velocity_positions = velocity_positions.data();
    v.vertex_count       = n64(positions);
    v.stiffness          = static_cast<float>(stiffness);
    v.compression        = static_cast<float>(compression);
    v.stretch            = static_cast<float>(stretch);
    hotools::project_tether_mc2(v);
}

// ---------------------------------------------------------------------------
// project_motion_constraints_mc2
// ---------------------------------------------------------------------------
static void project_motion_constraints_mc2(
    F2w positions, F2 base_positions, F2 base_rotations, F1 inv_masses,
    F1 max_distances, F1 stiffness_values,
    F1 backstop_radii, F1 backstop_distances,
    F2w velocity_positions,
    int normal_axis)
{
    hotools::Mc2MotionConstraintView v{};
    v.positions          = positions.data();
    v.base_positions     = base_positions.data();
    v.base_rotations     = base_rotations.data();
    v.inv_masses         = inv_masses.data();
    v.max_distances      = max_distances.data();
    v.stiffness_values   = stiffness_values.data();
    v.backstop_radii     = backstop_radii.data();
    v.backstop_distances = backstop_distances.data();
    v.velocity_positions = velocity_positions.data();
    v.vertex_count       = n64(positions);
    v.normal_axis        = normal_axis;
    hotools::project_motion_constraints_mc2(v);
}

// ---------------------------------------------------------------------------
// apply_post_step_mc2
// ---------------------------------------------------------------------------
static void apply_post_step_mc2(
    F2w positions, F2w old_positions, F2w velocity_positions,
    F2w velocities, F2w real_velocities, F1w friction, F1w static_friction,
    F2 collision_normals, F1 inv_masses,
    double step_dt, double dynamic_friction,
    double static_friction_speed, double particle_speed_limit)
{
    hotools::Mc2PostStepView v{};
    v.positions            = positions.data();
    v.old_positions        = old_positions.data();
    v.velocity_positions   = velocity_positions.data();
    v.velocities           = velocities.data();
    v.real_velocities      = real_velocities.data();
    v.friction             = friction.data();
    v.static_friction      = static_friction.data();
    v.collision_normals    = collision_normals.data();
    v.inv_masses           = inv_masses.data();
    v.vertex_count         = n64(positions);
    v.step_dt              = static_cast<float>(step_dt);
    v.dynamic_friction     = static_cast<float>(dynamic_friction);
    v.static_friction_speed   = static_cast<float>(static_friction_speed);
    v.particle_speed_limit = static_cast<float>(particle_speed_limit);
    hotools::apply_post_step_mc2(v);
}

// ---------------------------------------------------------------------------
// project_collisions_mc2
// ---------------------------------------------------------------------------
static void project_collisions_mc2(
    F2w positions, F2 base_positions, F1 inv_masses, F1 collision_radii,
    F2w collision_normals, F1w friction,
    int collided_by_groups,
    I1 collider_types, I1 collider_group_bits,
    F2 collider_centers, F2 collider_segment_a, F2 collider_segment_b,
    F2 collider_old_centers, F2 collider_old_segment_a, F2 collider_old_segment_b,
    F1 collider_radii)
{
    hotools::Mc2CollisionView v{};
    v.positions            = positions.data();
    v.base_positions       = base_positions.data();
    v.inv_masses           = inv_masses.data();
    v.collision_radii      = collision_radii.data();
    v.collision_normals    = collision_normals.data();
    v.friction             = friction.data();
    v.collided_by_groups   = static_cast<int32_t>(collided_by_groups);
    v.collider_types       = collider_types.data();
    v.collider_group_bits  = collider_group_bits.data();
    v.collider_centers     = collider_centers.data();
    v.collider_segment_a   = collider_segment_a.data();
    v.collider_segment_b   = collider_segment_b.data();
    v.collider_old_centers    = collider_old_centers.data();
    v.collider_old_segment_a  = collider_old_segment_a.data();
    v.collider_old_segment_b  = collider_old_segment_b.data();
    v.collider_radii       = collider_radii.data();
    v.vertex_count         = n64(positions);
    v.collider_count       = n64(collider_types);
    hotools::project_collisions_mc2(v);
}

// ---------------------------------------------------------------------------
// project_edge_collisions_mc2
// ---------------------------------------------------------------------------
static void project_edge_collisions_mc2(
    F2w positions, I2 edges, U1 attributes,
    F1 inv_masses, F1 collision_radii,
    F2w collision_normals, F1w friction,
    int collided_by_groups,
    I1 collider_types, I1 collider_group_bits,
    F2 collider_centers, F2 collider_segment_a, F2 collider_segment_b,
    F2 collider_old_centers, F2 collider_old_segment_a, F2 collider_old_segment_b,
    F1 collider_radii)
{
    hotools::Mc2EdgeCollisionView v{};
    v.positions            = positions.data();
    v.edges                = edges.data();
    v.attributes           = attributes.data();
    v.inv_masses           = inv_masses.data();
    v.collision_radii      = collision_radii.data();
    v.collision_normals    = collision_normals.data();
    v.friction             = friction.data();
    v.collided_by_groups   = static_cast<int32_t>(collided_by_groups);
    v.collider_types       = collider_types.data();
    v.collider_group_bits  = collider_group_bits.data();
    v.collider_centers     = collider_centers.data();
    v.collider_segment_a   = collider_segment_a.data();
    v.collider_segment_b   = collider_segment_b.data();
    v.collider_old_centers    = collider_old_centers.data();
    v.collider_old_segment_a  = collider_old_segment_a.data();
    v.collider_old_segment_b  = collider_old_segment_b.data();
    v.collider_radii       = collider_radii.data();
    v.vertex_count         = n64(positions);
    v.edge_count           = n64(edges);
    v.collider_count       = n64(collider_types);
    hotools::project_edge_collisions_mc2(v);
}

// ---------------------------------------------------------------------------
// project_self_collisions_mc2
// ---------------------------------------------------------------------------
static void project_self_collisions_mc2(
    F2w positions, F2 old_positions, F1 inv_masses,
    I2 edges, I2 triangles, U1 attributes,
    F2w collision_normals, F1w friction,
    double surface_thickness)
{
    hotools::Mc2SelfCollisionView v{};
    v.positions         = positions.data();
    v.old_positions     = old_positions.data();
    v.inv_masses        = inv_masses.data();
    v.edges             = edges.data();
    v.triangles         = triangles.data();
    v.attributes        = attributes.data();
    v.collision_normals = collision_normals.data();
    v.friction          = friction.data();
    v.vertex_count      = n64(positions);
    v.edge_count        = n64(edges);
    v.triangle_count    = n64(triangles);
    v.surface_thickness = static_cast<float>(surface_thickness);
    hotools::project_self_collisions_mc2(v);
}

// ---------------------------------------------------------------------------
// project_triangle_bending_mc2
// ---------------------------------------------------------------------------
static void project_triangle_bending_mc2(
    F2w positions, F1 inv_masses,
    I2 dihedral_pairs, F1 dihedral_rest_angles, I1 dihedral_signs,
    I2 volume_pairs, F1 volume_rest,
    F1 stiffness_values)
{
    hotools::Mc2TriangleBendingView v{};
    v.positions           = positions.data();
    v.inv_masses          = inv_masses.data();
    v.dihedral_pairs      = dihedral_pairs.data();
    v.dihedral_rest_angles = dihedral_rest_angles.data();
    v.dihedral_signs      = dihedral_signs.data();
    v.volume_pairs        = volume_pairs.data();
    v.volume_rest         = volume_rest.data();
    v.stiffness_values    = stiffness_values.data();
    v.vertex_count        = n64(positions);
    v.dihedral_count      = n64(dihedral_pairs);
    v.volume_count        = n64(volume_pairs);
    hotools::project_triangle_bending_mc2(v);
}

// ---------------------------------------------------------------------------
// project_angle_constraints_mc2
// ---------------------------------------------------------------------------
static void project_angle_constraints_mc2(
    F2w positions, F1 inv_masses,
    I1 parent_indices, I1 baseline_start, I1 baseline_count, I1 baseline_data,
    F2 step_basic_positions, F2 step_basic_rotations,
    F1 restoration_values, F1 limit_values,
    F2w velocity_positions,
    double restoration_velocity_attenuation,
    double restoration_gravity_falloff,
    double limit_stiffness)
{
    hotools::Mc2AngleConstraintView v{};
    v.positions             = positions.data();
    v.inv_masses            = inv_masses.data();
    v.parent_indices        = parent_indices.data();
    v.baseline_start        = baseline_start.data();
    v.baseline_count        = baseline_count.data();
    v.baseline_data         = baseline_data.data();
    v.step_basic_positions  = step_basic_positions.data();
    v.step_basic_rotations  = step_basic_rotations.data();
    v.restoration_values    = restoration_values.data();
    v.restoration_velocity_attenuation_values = nullptr; // per-vertex 版本通过 restoration_values 覆盖
    v.restoration_gravity_falloff_values      = nullptr;
    v.limit_values          = limit_values.data();
    v.velocity_positions    = velocity_positions.data();
    v.vertex_count          = n64(positions);
    v.line_count            = n64(parent_indices);
    v.baseline_data_count   = n64(baseline_data);
    v.restoration_velocity_attenuation = static_cast<float>(restoration_velocity_attenuation);
    v.restoration_gravity_falloff      = static_cast<float>(restoration_gravity_falloff);
    v.limit_stiffness       = static_cast<float>(limit_stiffness);
    hotools::project_angle_constraints_mc2(v);
}

// ---------------------------------------------------------------------------
// update_step_basic_pose_mc2
// ---------------------------------------------------------------------------
static void update_step_basic_pose_mc2(
    F2 base_positions, F2 base_rotations,
    I1 parent_indices, I1 baseline_start, I1 baseline_count, I1 baseline_data,
    F2 vertex_local_positions, F2 vertex_local_rotations,
    F2w step_positions, F2w step_rotations,
    double animation_pose_ratio)
{
    hotools::Mc2StepBasicPoseView v{};
    v.base_positions          = base_positions.data();
    v.base_rotations          = base_rotations.data();
    v.parent_indices          = parent_indices.data();
    v.baseline_start          = baseline_start.data();
    v.baseline_count          = baseline_count.data();
    v.baseline_data           = baseline_data.data();
    v.vertex_local_positions  = vertex_local_positions.data();
    v.vertex_local_rotations  = vertex_local_rotations.data();
    v.step_positions          = step_positions.data();
    v.step_rotations          = step_rotations.data();
    v.vertex_count            = n64(base_positions);
    v.line_count              = n64(parent_indices);
    v.baseline_data_count     = n64(baseline_data);
    v.animation_pose_ratio    = static_cast<float>(animation_pose_ratio);
    hotools::update_step_basic_pose_mc2(v);
}

// ---------------------------------------------------------------------------
// update_base_pose_from_pose_mc2
// ---------------------------------------------------------------------------
static void update_base_pose_from_pose_mc2(
    F2 base_positions, F2 base_normals,
    I1 parent_indices, I1 baseline_start, I1 baseline_count, I1 baseline_data,
    F2 vertex_local_positions, F2 vertex_local_rotations,
    F2w base_rotations, F2w step_positions, F2w step_rotations,
    double animation_pose_ratio)
{
    hotools::Mc2BasePoseFromPoseView v{};
    v.base_positions         = base_positions.data();
    v.base_normals           = base_normals.data();
    v.parent_indices         = parent_indices.data();
    v.baseline_start         = baseline_start.data();
    v.baseline_count         = baseline_count.data();
    v.baseline_data          = baseline_data.data();
    v.vertex_local_positions = vertex_local_positions.data();
    v.vertex_local_rotations = vertex_local_rotations.data();
    v.base_rotations         = base_rotations.data();
    v.step_positions         = step_positions.data();
    v.step_rotations         = step_rotations.data();
    v.vertex_count           = n64(base_positions);
    v.line_count             = n64(parent_indices);
    v.baseline_data_count    = n64(baseline_data);
    v.animation_pose_ratio   = static_cast<float>(animation_pose_ratio);
    hotools::update_base_pose_from_pose_mc2(v);
}

// ---------------------------------------------------------------------------
// apply_substep_inertia_mc2
// ---------------------------------------------------------------------------
static void apply_substep_inertia_mc2(
    F2w old_positions, F2w velocities,
    F1 depths, F1 inv_masses,
    F1 old_world_position,  // shape (3,)
    F1 step_vector,         // shape (3,)
    F1 step_rotation,       // shape (4,)
    F1 inertia_vector,      // shape (3,)
    F1 inertia_rotation,    // shape (4,)
    double depth_inertia)
{
    hotools::Mc2SubstepInertiaView v{};
    v.old_positions     = old_positions.data();
    v.velocities        = velocities.data();
    v.depths            = depths.data();
    v.inv_masses        = inv_masses.data();
    v.vertex_count      = n64(old_positions);
    const float* owp = old_world_position.data();
    v.old_world_position[0] = owp[0]; v.old_world_position[1] = owp[1]; v.old_world_position[2] = owp[2];
    const float* sv = step_vector.data();
    v.step_vector[0] = sv[0]; v.step_vector[1] = sv[1]; v.step_vector[2] = sv[2];
    const float* sr = step_rotation.data();
    v.step_rotation[0] = sr[0]; v.step_rotation[1] = sr[1]; v.step_rotation[2] = sr[2]; v.step_rotation[3] = sr[3];
    const float* iv = inertia_vector.data();
    v.inertia_vector[0] = iv[0]; v.inertia_vector[1] = iv[1]; v.inertia_vector[2] = iv[2];
    const float* ir = inertia_rotation.data();
    v.inertia_rotation[0] = ir[0]; v.inertia_rotation[1] = ir[1]; v.inertia_rotation[2] = ir[2]; v.inertia_rotation[3] = ir[3];
    v.depth_inertia     = static_cast<float>(depth_inertia);
    hotools::apply_substep_inertia_mc2(v);
}

// ---------------------------------------------------------------------------
// apply_centrifugal_velocity_mc2
// ---------------------------------------------------------------------------
static void apply_centrifugal_velocity_mc2(
    F2 positions, F2w velocities,
    F1 depths, F1 inv_masses,
    F1 now_world_position,  // shape (3,)
    F1 rotation_axis,       // shape (3,)
    double angular_velocity, double centrifugal)
{
    hotools::Mc2CentrifugalView v{};
    v.positions      = positions.data();
    v.velocities     = velocities.data();
    v.depths         = depths.data();
    v.inv_masses     = inv_masses.data();
    v.vertex_count   = n64(positions);
    const float* nwp = now_world_position.data();
    v.now_world_position[0] = nwp[0]; v.now_world_position[1] = nwp[1]; v.now_world_position[2] = nwp[2];
    const float* ra = rotation_axis.data();
    v.rotation_axis[0] = ra[0]; v.rotation_axis[1] = ra[1]; v.rotation_axis[2] = ra[2];
    v.angular_velocity = static_cast<float>(angular_velocity);
    v.centrifugal      = static_cast<float>(centrifugal);
    hotools::apply_centrifugal_velocity_mc2(v);
}

// ---------------------------------------------------------------------------
// calculate_display_positions_mc2
// ---------------------------------------------------------------------------
static void calculate_display_positions_mc2(
    F2 positions, F2 real_velocities, I1 root_indices,
    F2w display_positions,
    double frame_dt, double max_distance_ratio)
{
    hotools::Mc2DisplayPredictionView v{};
    v.positions          = positions.data();
    v.real_velocities    = real_velocities.data();
    v.root_indices       = root_indices.data();
    v.display_positions  = display_positions.data();
    v.vertex_count       = n64(positions);
    v.frame_dt           = static_cast<float>(frame_dt);
    v.max_distance_ratio = static_cast<float>(max_distance_ratio);
    hotools::calculate_display_positions_mc2(v);
}

// ---------------------------------------------------------------------------
// solve_mesh_shape_key_xpbd  (旧名 solve_mesh_shape_key_xpbd / solve_mesh_delta_xpbd)
// ---------------------------------------------------------------------------
static void solve_mesh_shape_key_xpbd(
    F2w positions, F2w prev_positions,
    F2 rest_positions, F1 inv_masses,
    I1 edge_i, I1 edge_j, F1 edge_rest,
    I1 bend_i, I1 bend_j, F1 bend_rest,
    F1 gravity,          // shape (3,)
    double dt, double damping,
    int substeps, int iterations,
    double stretch_compliance, double bend_compliance,
    F1 collision_radii,
    int collided_by_groups,
    I1 collider_types, I1 collider_groups,
    F2 collider_centers, F2 collider_segment_a, F2 collider_segment_b,
    F1 collider_radii)
{
    hotools::MeshXpbdView v{};
    v.positions         = positions.data();
    v.prev_positions    = prev_positions.data();
    v.rest_positions    = rest_positions.data();
    v.inv_masses        = inv_masses.data();
    v.vertex_count      = n64(positions);
    v.edge_i            = edge_i.data();
    v.edge_j            = edge_j.data();
    v.edge_rest         = edge_rest.data();
    v.edge_count        = n64(edge_i);
    v.bend_i            = bend_i.data();
    v.bend_j            = bend_j.data();
    v.bend_rest         = bend_rest.data();
    v.bend_count        = n64(bend_i);
    const float* g = gravity.data();
    v.gravity[0] = g[0]; v.gravity[1] = g[1]; v.gravity[2] = g[2];
    v.dt                = static_cast<float>(dt);
    v.damping           = static_cast<float>(damping);
    v.substeps          = substeps;
    v.iterations        = iterations;
    v.stretch_compliance = static_cast<float>(stretch_compliance);
    v.bend_compliance   = static_cast<float>(bend_compliance);
    v.collision_radii   = collision_radii.data();
    v.collided_by_groups = static_cast<int32_t>(collided_by_groups);
    v.collider_types    = collider_types.data();
    v.collider_groups   = collider_groups.data();
    v.collider_centers  = collider_centers.data();
    v.collider_segment_a = collider_segment_a.data();
    v.collider_segment_b = collider_segment_b.data();
    v.collider_radii    = collider_radii.data();
    v.collider_count    = n64(collider_types);
    hotools::solve_mesh_shape_key_xpbd(v);
}

// ---------------------------------------------------------------------------
// solve_mc2_bonecloth_io
// ---------------------------------------------------------------------------
static void solve_mc2_bonecloth_io(
    F2w world_rotations,
    F2 display_positions, F2 base_positions, F2 base_rotations,
    F2 vertex_local_positions, F2 vertex_local_rotations,
    I1 parent_indices,
    I1 baseline_start, I1 baseline_count, I1 baseline_data,
    U1 attributes,
    double rotational_interpolation, double blend_weight,
    double anime_ratio, double root_rotation)
{
    hotools::BoneClothIoView v{};
    v.world_rotations            = world_rotations.data();
    v.display_positions          = display_positions.data();
    v.base_positions             = base_positions.data();
    v.base_rotations             = base_rotations.data();
    v.vertex_local_positions     = vertex_local_positions.data();
    v.vertex_local_rotations     = vertex_local_rotations.data();
    v.parent_indices             = parent_indices.data();
    v.baseline_start             = baseline_start.data();
    v.baseline_count             = baseline_count.data();
    v.baseline_data              = baseline_data.data();
    v.attributes                 = attributes.data();
    v.rotational_interpolation   = static_cast<float>(rotational_interpolation);
    v.blend_weight               = static_cast<float>(blend_weight);
    v.anime_ratio                = static_cast<float>(anime_ratio);
    v.root_rotation              = static_cast<float>(root_rotation);
    v.vertex_count               = n64(world_rotations);
    v.baseline_lines             = n64(baseline_start);
    v.baseline_total             = n64(baseline_data);
    hotools::solve_bonecloth_io(v);
}

// ---------------------------------------------------------------------------
// solve_meshcloth_mc2  ——93 个位置参数
// 用 nb::args 接收，避免93个 ndarray 模板参数引发的编译器递归深度问题。
// 参数顺序与原 CPython 版本完全一致，Python 侧无需改动。
// ---------------------------------------------------------------------------
static void solve_meshcloth_mc2_impl(nb::args a)
{
    if (a.size() != 93) {
        throw nb::value_error("solve_meshcloth_mc2 需要恰好 93 个位置参数");
    }

    // ----- 辅助 lambda：从 args 中取 ndarray 数据指针 -----
    auto f  = [&](size_t i) -> float*       { return nb::cast<F2w>(a[i]).data(); };
    auto fc = [&](size_t i) -> const float* { return nb::cast<F2>(a[i]).data();  };
    auto fc1 = [&](size_t i)-> const float* { return nb::cast<F1>(a[i]).data();  };
    auto ic = [&](size_t i) -> const int32_t* { return nb::cast<I1>(a[i]).data(); };
    auto ic2 = [&](size_t i)-> const int32_t* { return nb::cast<I2>(a[i]).data(); };
    auto uc = [&](size_t i) -> const uint8_t* { return nb::cast<U1>(a[i]).data(); };

    // idx 70 起为标量
    const int    substeps           = nb::cast<int>(a[70]);
    const int    iterations         = nb::cast<int>(a[71]);
    const float  frame_dt           = static_cast<float>(nb::cast<double>(a[72]));
    const float  step_dt            = static_cast<float>(nb::cast<double>(a[73]));
    const float* gravity_buf        = fc1(74);              // shape (3,)
    const float  depth_inertia      = static_cast<float>(nb::cast<double>(a[75]));
    const float  centrifugal        = static_cast<float>(nb::cast<double>(a[76]));
    const bool   use_tether         = nb::cast<bool>(a[77]);
    const float  tether_compression = static_cast<float>(nb::cast<double>(a[78]));
    const float  tether_stretch     = static_cast<float>(nb::cast<double>(a[79]));
    const float  dynamic_friction   = static_cast<float>(nb::cast<double>(a[80]));
    const float  static_friction_speed = static_cast<float>(nb::cast<double>(a[81]));
    const float  particle_speed_limit  = static_cast<float>(nb::cast<double>(a[82]));
    const float  angle_limit_stiffness = static_cast<float>(nb::cast<double>(a[83]));
    const int    normal_axis        = nb::cast<int>(a[84]);
    const float  display_max_dist   = static_cast<float>(nb::cast<double>(a[85]));
    const float  animation_ratio    = static_cast<float>(nb::cast<double>(a[86]));
    const float  blend_weight       = static_cast<float>(nb::cast<double>(a[87]));
    const int32_t collided_by_groups = nb::cast<int32_t>(a[88]);
    const int    collider_mode      = nb::cast<int>(a[89]);
    const bool   self_collision     = nb::cast<bool>(a[90]);
    const float  self_col_thickness = static_cast<float>(nb::cast<double>(a[91]));
    const float  self_col_mass      = static_cast<float>(nb::cast<double>(a[92]));

    hotools::Mc2MeshClothSolveView v{};
    // ---- 可写 buffer（0‥11）----
    v.positions             = f(0);
    v.old_positions         = f(1);
    v.velocity_positions    = f(2);
    v.velocities            = f(3);
    v.real_velocities       = f(4);
    v.friction              = nb::cast<F1w>(a[5]).data();
    v.static_friction       = nb::cast<F1w>(a[6]).data();
    v.collision_normals     = f(7);
    v.inv_masses            = nb::cast<F1w>(a[8]).data();
    v.step_basic_positions  = f(9);
    v.step_basic_rotations  = f(10);
    v.display_positions     = f(11);
    // ---- 只读 float buffer（12‥）----
    v.base_positions        = fc(12);
    v.base_normals          = fc(13);
    v.base_rotations        = fc(14);
    v.attributes            = uc(15);
    v.depths                = fc1(16);
    v.root_indices          = ic(17);
    v.tether_rest_lengths   = fc1(18);
    v.parent_indices        = ic(19);
    v.baseline_start        = ic(20);
    v.baseline_count        = ic(21);
    v.baseline_data         = ic(22);
    v.vertex_local_positions  = fc(23);
    v.vertex_local_rotations  = fc(24);
    v.distance_start        = ic(25);
    v.distance_count        = ic(26);
    v.distance_data         = ic(27);
    v.distance_rest         = fc1(28);
    v.distance_stiffness_values = fc1(29);
    v.bend_distance_start   = ic(30);
    v.bend_distance_count   = ic(31);
    v.bend_distance_data    = ic(32);
    v.bend_distance_rest    = fc1(33);
    v.bend_stiffness_values = fc1(34);
    v.dihedral_pairs        = ic2(35);
    v.dihedral_rest_angles  = fc1(36);
    v.dihedral_signs        = ic(37);
    v.volume_pairs          = ic2(38);
    v.volume_rest           = fc1(39);
    v.angle_restoration_values = fc1(40);
    v.angle_restoration_velocity_attenuation_values = fc1(41);
    v.angle_restoration_gravity_falloff_values      = fc1(42);
    v.angle_limit_values    = fc1(43);
    v.substep_damping_values = fc1(44);
    v.max_distances         = fc1(45);
    v.motion_stiffness_values = fc1(46);
    v.backstop_radii        = fc1(47);
    v.backstop_distances    = fc1(48);
    v.edges                 = ic2(49);
    v.triangles             = ic2(50);
    v.collision_radii       = fc1(51);
    v.collider_types        = ic(52);
    v.collider_group_bits   = ic(53);
    v.collider_centers      = fc(54);
    v.collider_segment_a    = fc(55);
    v.collider_segment_b    = fc(56);
    v.collider_old_centers  = fc(57);
    v.collider_old_segment_a = fc(58);
    v.collider_old_segment_b = fc(59);
    v.collider_radii        = fc1(60);
    v.substep_old_world_positions = fc(61);
    v.substep_step_vectors  = fc(62);
    v.substep_step_rotations = fc(63);
    v.substep_inertia_vectors = fc(64);
    v.substep_inertia_rotations = fc(65);
    v.substep_now_world_positions = fc(66);
    v.substep_rotation_axes = fc(67);
    v.substep_angular_velocities = fc1(68);
    v.substep_velocity_weights   = fc1(69);
    // ---- 维度（从 buffer 推算）----
    v.vertex_count          = static_cast<int64_t>(nb::cast<F2w>(a[0]).shape(0));
    v.line_count            = static_cast<int64_t>(nb::cast<I1>(a[19]).shape(0));
    v.baseline_data_count   = static_cast<int64_t>(nb::cast<I1>(a[22]).shape(0));
    v.distance_count_total  = static_cast<int64_t>(nb::cast<I1>(a[27]).shape(0));
    v.bend_distance_count_total = static_cast<int64_t>(nb::cast<I1>(a[32]).shape(0));
    v.edge_count            = static_cast<int64_t>(nb::cast<I2>(a[49]).shape(0));
    v.triangle_count        = static_cast<int64_t>(nb::cast<I2>(a[50]).shape(0));
    v.dihedral_count        = static_cast<int64_t>(nb::cast<I2>(a[35]).shape(0));
    v.volume_count          = static_cast<int64_t>(nb::cast<I2>(a[38]).shape(0));
    v.collider_count        = static_cast<int64_t>(nb::cast<I1>(a[52]).shape(0));
    // ---- 标量 ----
    v.substeps              = substeps;
    v.iterations            = iterations;
    v.frame_dt              = frame_dt;
    v.step_dt               = step_dt;
    v.gravity[0] = gravity_buf[0]; v.gravity[1] = gravity_buf[1]; v.gravity[2] = gravity_buf[2];
    v.depth_inertia         = depth_inertia;
    v.centrifugal           = centrifugal;
    v.use_tether            = use_tether;
    v.tether_compression    = tether_compression;
    v.tether_stretch        = tether_stretch;
    v.dynamic_friction      = dynamic_friction;
    v.static_friction_speed = static_friction_speed;
    v.particle_speed_limit  = particle_speed_limit;
    v.angle_limit_stiffness = angle_limit_stiffness;
    v.normal_axis           = normal_axis;
    v.display_max_distance_ratio = display_max_dist;
    v.animation_pose_ratio  = animation_ratio;
    v.blend_weight          = blend_weight;
    v.collided_by_groups    = collided_by_groups;
    v.collider_collision_mode = collider_mode;
    v.self_collision_enabled = self_collision;
    v.self_collision_surface_thickness = self_col_thickness;
    v.self_collision_mass   = self_col_mass;

    hotools::solve_meshcloth_mc2(v);
}

// ---------------------------------------------------------------------------
// property_curve 系列
// compile_* 和 sample_* 都是 METH_VARARGS 签名，用 PyTuple_Pack 构造参数元组后调用。
// ---------------------------------------------------------------------------
static nb::object call_meth_varargs(PyObject* (*fn)(PyObject*, PyObject*),
                                    std::initializer_list<PyObject*> args_list)
{
    PyObject* args = PyTuple_New(static_cast<Py_ssize_t>(args_list.size()));
    Py_ssize_t idx = 0;
    for (PyObject* a : args_list) {
        Py_INCREF(a);
        PyTuple_SET_ITEM(args, idx++, a);
    }
    PyObject* result = fn(nullptr, args);
    Py_DECREF(args);
    if (result == nullptr)
        throw nb::python_error();
    return nb::steal<nb::object>(result);
}

static nb::object compile_property_float_curve(nb::object payload)
{
    return call_meth_varargs(hotools::compile_property_float_curve, {payload.ptr()});
}

static nb::object compile_property_color_curve(nb::object payload)
{
    return call_meth_varargs(hotools::compile_property_color_curve, {payload.ptr()});
}

static nb::object sample_property_float_curve(nb::object compiled, double position, nb::object extend)
{
    PyObject* pos = PyFloat_FromDouble(position);
    auto result = call_meth_varargs(hotools::sample_property_float_curve,
                                    {compiled.ptr(), pos, extend.ptr()});
    Py_DECREF(pos);
    return result;
}

static nb::object sample_property_color_curve(nb::object compiled, double position, nb::object extend)
{
    PyObject* pos = PyFloat_FromDouble(position);
    auto result = call_meth_varargs(hotools::sample_property_color_curve,
                                    {compiled.ptr(), pos, extend.ptr()});
    Py_DECREF(pos);
    return result;
}

static nb::object sample_property_float_curve_many(nb::object compiled, int count, nb::object extend)
{
    PyObject* cnt = PyLong_FromLong(count);
    auto result = call_meth_varargs(hotools::sample_property_float_curve_many,
                                    {compiled.ptr(), cnt, extend.ptr()});
    Py_DECREF(cnt);
    return result;
}

static nb::object sample_property_color_curve_many(nb::object compiled, int count, nb::object extend)
{
    PyObject* cnt = PyLong_FromLong(count);
    auto result = call_meth_varargs(hotools::sample_property_color_curve_many,
                                    {compiled.ptr(), cnt, extend.ptr()});
    Py_DECREF(cnt);
    return result;
}

static nb::object sample_property_float_curve_positions(nb::object compiled, nb::object positions, nb::object extend)
{
    return call_meth_varargs(hotools::sample_property_float_curve_positions,
                             {compiled.ptr(), positions.ptr(), extend.ptr()});
}

static nb::object sample_property_color_curve_positions(nb::object compiled, nb::object positions, nb::object extend)
{
    return call_meth_varargs(hotools::sample_property_color_curve_positions,
                             {compiled.ptr(), positions.ptr(), extend.ptr()});
}

// mc2_context.hpp 中的 Context 类在 mc2_context.cpp 里通过
// register_mc2_context_class(m) 注册，此处仅声明。
namespace hotools { void register_mc2_context_class(nb::module_& m); }

// solve_meshcloth_mc2_context / _context_cached_params 同样在
// mc2_context.cpp 里定义并通过 register_mc2_context_class 注册。

// ---------------------------------------------------------------------------
// spring_bone_vrm —— 由 spring_bone_vrm_bindings.cpp 提供
// ---------------------------------------------------------------------------
namespace hotools { void register_spring_bone_vrm(nb::module_& m); }

// ---------------------------------------------------------------------------
// NB_MODULE
// ---------------------------------------------------------------------------
NB_MODULE(hotools_native, m)
{
    m.doc() = "HoTools native acceleration backend (nanobind).";

    // MC2 小函数
    m.def("project_neighbor_constraints_mc2",  &project_neighbor_constraints_mc2);
    m.def("project_tether_mc2",                &project_tether_mc2);
    m.def("project_motion_constraints_mc2",    &project_motion_constraints_mc2);
    m.def("apply_post_step_mc2",               &apply_post_step_mc2);
    m.def("project_collisions_mc2",            &project_collisions_mc2);
    m.def("project_edge_collisions_mc2",       &project_edge_collisions_mc2);
    m.def("project_self_collisions_mc2",       &project_self_collisions_mc2);
    m.def("project_triangle_bending_mc2",      &project_triangle_bending_mc2);
    m.def("project_angle_constraints_mc2",     &project_angle_constraints_mc2);
    m.def("update_step_basic_pose_mc2",        &update_step_basic_pose_mc2);
    m.def("update_base_pose_from_pose_mc2",    &update_base_pose_from_pose_mc2);
    m.def("apply_substep_inertia_mc2",         &apply_substep_inertia_mc2);
    m.def("apply_centrifugal_velocity_mc2",    &apply_centrifugal_velocity_mc2);
    m.def("calculate_display_positions_mc2",   &calculate_display_positions_mc2);

    // MC2 大函数（nb::args 接收全部93个参数）
    m.def("solve_meshcloth_mc2",               &solve_meshcloth_mc2_impl);

    // XPBD / BoneCloth
    m.def("solve_mesh_shape_key_xpbd",         &solve_mesh_shape_key_xpbd);
    m.def("solve_mesh_delta_xpbd",             &solve_mesh_shape_key_xpbd);   // 兼容别名
    m.def("solve_mc2_bonecloth_io",            &solve_mc2_bonecloth_io);

    // property curve
    m.def("compile_property_float_curve",         &compile_property_float_curve);
    m.def("compile_property_color_curve",         &compile_property_color_curve);
    m.def("sample_property_float_curve",          &sample_property_float_curve);
    m.def("sample_property_color_curve",          &sample_property_color_curve);
    m.def("sample_property_float_curve_many",     &sample_property_float_curve_many);
    m.def("sample_property_color_curve_many",     &sample_property_color_curve_many);
    m.def("sample_property_float_curve_positions",&sample_property_float_curve_positions);
    m.def("sample_property_color_curve_positions",&sample_property_color_curve_positions);

    // Mc2Context 类 + context 求解函数（在 mc2_context.cpp 里注册）
    hotools::register_mc2_context_class(m);

    // SpringBone VRM（在 spring_bone_vrm_bindings.cpp 里注册）
    hotools::register_spring_bone_vrm(m);
}
