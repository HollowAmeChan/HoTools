// mc2_context.cpp  ——  nanobind 绑定（替换 PyCapsule → nb::class_）
// python_buffer_utils.hpp 不再需要。

#include "mc2_context.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include "hotools_mc2.hpp"

#include <algorithm>
#include <cstdint>
#include <vector>

namespace nb = nanobind;
namespace hotools {

using F1  = nb::ndarray<float,    nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using F2  = nb::ndarray<float,    nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using I1  = nb::ndarray<int32_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using I2  = nb::ndarray<int32_t,  nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using U1  = nb::ndarray<uint8_t,  nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using F2w = F2;
using F1w = F1;

// ---------------------------------------------------------------------------
// 原生 Context 结构体（内容不变，去掉 released 标志：Python 对象析构即释放）
// ---------------------------------------------------------------------------
struct Mc2NativeContext {
    int64_t vertex_count = 0;
    int64_t line_count = 0;
    int64_t baseline_data_count = 0;
    int64_t distance_count = 0;
    int64_t bend_count = 0;
    int64_t collider_radius_count = 0;
    int64_t edge_count = 0;
    int64_t triangle_count = 0;
    int64_t dihedral_count = 0;
    int64_t volume_count = 0;
    int64_t param_slot_count = 0;
    int64_t param_array_count = 0;
    int64_t topology_serial = 0;
    int64_t param_serial = 0;
    bool static_ready = false;
    bool param_arrays_ready = false;

    std::vector<uint8_t>  attributes;
    std::vector<float>    depths;
    std::vector<int32_t>  root_indices;
    std::vector<float>    tether_rest_lengths;
    std::vector<int32_t>  parent_indices;
    std::vector<int32_t>  baseline_start;
    std::vector<int32_t>  baseline_count;
    std::vector<int32_t>  baseline_data;
    std::vector<float>    vertex_local_positions;
    std::vector<float>    vertex_local_rotations;
    std::vector<int32_t>  distance_start;
    std::vector<int32_t>  distance_count_values;
    std::vector<int32_t>  distance_data;
    std::vector<float>    distance_rest;
    std::vector<int32_t>  bend_distance_start;
    std::vector<int32_t>  bend_distance_count;
    std::vector<int32_t>  bend_distance_data;
    std::vector<float>    bend_distance_rest;
    std::vector<int32_t>  dihedral_pairs;
    std::vector<float>    dihedral_rest_angles;
    std::vector<int32_t>  dihedral_signs;
    std::vector<int32_t>  volume_pairs;
    std::vector<float>    volume_rest;
    std::vector<int32_t>  edges;
    std::vector<int32_t>  triangles;
    std::vector<float>    distance_stiffness_values;
    std::vector<float>    bend_stiffness_values;
    std::vector<float>    angle_restoration_values;
    std::vector<float>    angle_restoration_velocity_attenuation_values;
    std::vector<float>    angle_restoration_gravity_falloff_values;
    std::vector<float>    angle_limit_values;
    std::vector<float>    substep_damping_values;
    std::vector<float>    max_distances;
    std::vector<float>    motion_stiffness_values;
    std::vector<float>    backstop_radii;
    std::vector<float>    backstop_distances;
};

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------
namespace {

template <typename T>
static const T* data_or_dummy(const std::vector<T>& v) {
    static const T z{};
    return v.empty() ? &z : v.data();
}

template <typename T>
static void copy_nb(const nb::ndarray<T, nb::ndim<1>, nb::c_contig, nb::device::cpu>& src,
                    std::vector<T>& dst)
{
    dst.assign(src.data(), src.data() + src.shape(0));
}

template <typename T>
static void copy_nb2(const nb::ndarray<T, nb::ndim<2>, nb::c_contig, nb::device::cpu>& src,
                     std::vector<T>& dst)
{
    const size_t total = src.shape(0) * src.shape(1);
    dst.assign(src.data(), src.data() + total);
}

static void clear_param(Mc2NativeContext& ctx) {
    ctx.param_arrays_ready = false;
    ctx.param_array_count  = 0;
    ctx.distance_stiffness_values.clear();
    ctx.bend_stiffness_values.clear();
    ctx.angle_restoration_values.clear();
    ctx.angle_restoration_velocity_attenuation_values.clear();
    ctx.angle_restoration_gravity_falloff_values.clear();
    ctx.angle_limit_values.clear();
    ctx.substep_damping_values.clear();
    ctx.max_distances.clear();
    ctx.motion_stiffness_values.clear();
    ctx.backstop_radii.clear();
    ctx.backstop_distances.clear();
}

static void clear_static(Mc2NativeContext& ctx) {
    ctx.static_ready = false;
    ctx.line_count = ctx.baseline_data_count = ctx.distance_count = ctx.bend_count = 0;
    ctx.edge_count = ctx.triangle_count = ctx.dihedral_count = ctx.volume_count = 0;
    ctx.attributes.clear();     ctx.depths.clear();
    ctx.root_indices.clear();   ctx.tether_rest_lengths.clear();
    ctx.parent_indices.clear(); ctx.baseline_start.clear();
    ctx.baseline_count.clear(); ctx.baseline_data.clear();
    ctx.vertex_local_positions.clear(); ctx.vertex_local_rotations.clear();
    ctx.distance_start.clear(); ctx.distance_count_values.clear();
    ctx.distance_data.clear();  ctx.distance_rest.clear();
    ctx.bend_distance_start.clear(); ctx.bend_distance_count.clear();
    ctx.bend_distance_data.clear();  ctx.bend_distance_rest.clear();
    ctx.dihedral_pairs.clear(); ctx.dihedral_rest_angles.clear();
    ctx.dihedral_signs.clear(); ctx.volume_pairs.clear();
    ctx.volume_rest.clear();    ctx.edges.clear();
    ctx.triangles.clear();
    clear_param(ctx);
}

}  // namespace

// ---------------------------------------------------------------------------
// Mc2Context Python 类方法
// ---------------------------------------------------------------------------

static void ctx_update_static(Mc2NativeContext& ctx,
                               int64_t vertex_count, int64_t distance_count,
                               int64_t bend_count, int64_t collider_radius_count)
{
    clear_static(ctx);
    ctx.vertex_count          = vertex_count;
    ctx.distance_count        = distance_count;
    ctx.bend_count            = bend_count;
    ctx.collider_radius_count = collider_radius_count;
    ctx.topology_serial      += 1;
}

// 25 个静态拓扑数组
static void ctx_update_static_arrays(
    Mc2NativeContext& ctx,
    U1 attributes, F1 depths, I1 root_indices, F1 tether_rest_lengths,
    I1 parent_indices, I1 baseline_start, I1 baseline_count, I1 baseline_data,
    F2 vertex_local_positions, F2 vertex_local_rotations,
    I1 distance_start, I1 distance_count, I1 distance_data, F1 distance_rest,
    I1 bend_distance_start, I1 bend_distance_count, I1 bend_distance_data, F1 bend_distance_rest,
    I2 dihedral_pairs, F1 dihedral_rest_angles, I1 dihedral_signs,
    I2 volume_pairs, F1 volume_rest,
    I2 edges, I2 triangles)
{
    copy_nb(attributes, ctx.attributes);
    copy_nb(depths, ctx.depths);
    copy_nb(root_indices, ctx.root_indices);
    copy_nb(tether_rest_lengths, ctx.tether_rest_lengths);
    copy_nb(parent_indices, ctx.parent_indices);
    copy_nb(baseline_start, ctx.baseline_start);
    copy_nb(baseline_count, ctx.baseline_count);
    copy_nb(baseline_data, ctx.baseline_data);
    copy_nb2(vertex_local_positions, ctx.vertex_local_positions);
    copy_nb2(vertex_local_rotations, ctx.vertex_local_rotations);
    copy_nb(distance_start, ctx.distance_start);
    copy_nb(distance_count, ctx.distance_count_values);
    copy_nb(distance_data, ctx.distance_data);
    copy_nb(distance_rest, ctx.distance_rest);
    copy_nb(bend_distance_start, ctx.bend_distance_start);
    copy_nb(bend_distance_count, ctx.bend_distance_count);
    copy_nb(bend_distance_data, ctx.bend_distance_data);
    copy_nb(bend_distance_rest, ctx.bend_distance_rest);
    copy_nb2(dihedral_pairs, ctx.dihedral_pairs);
    copy_nb(dihedral_rest_angles, ctx.dihedral_rest_angles);
    copy_nb(dihedral_signs, ctx.dihedral_signs);
    copy_nb2(volume_pairs, ctx.volume_pairs);
    copy_nb(volume_rest, ctx.volume_rest);
    copy_nb2(edges, ctx.edges);
    copy_nb2(triangles, ctx.triangles);
    ctx.line_count            = static_cast<int64_t>(baseline_start.shape(0));
    ctx.baseline_data_count   = static_cast<int64_t>(baseline_data.shape(0));
    ctx.dihedral_count        = static_cast<int64_t>(dihedral_pairs.shape(0));
    ctx.volume_count          = static_cast<int64_t>(volume_pairs.shape(0));
    ctx.edge_count            = static_cast<int64_t>(edges.shape(0));
    ctx.triangle_count        = static_cast<int64_t>(triangles.shape(0));
    ctx.static_ready          = true;
}

static void ctx_update_params(Mc2NativeContext& ctx, int64_t param_slot_count) {
    clear_param(ctx);
    ctx.param_slot_count = param_slot_count;
    ctx.param_serial    += 1;
}

// 11 个参数数组
static void ctx_update_param_arrays(
    Mc2NativeContext& ctx,
    F1 distance_stiffness, F1 bend_stiffness,
    F1 angle_restoration, F1 angle_restoration_vel_atten,
    F1 angle_restoration_grav_falloff, F1 angle_limit,
    F1 substep_damping, F1 max_distances,
    F1 motion_stiffness, F1 backstop_radii, F1 backstop_distances)
{
    copy_nb(distance_stiffness,          ctx.distance_stiffness_values);
    copy_nb(bend_stiffness,              ctx.bend_stiffness_values);
    copy_nb(angle_restoration,           ctx.angle_restoration_values);
    copy_nb(angle_restoration_vel_atten, ctx.angle_restoration_velocity_attenuation_values);
    copy_nb(angle_restoration_grav_falloff, ctx.angle_restoration_gravity_falloff_values);
    copy_nb(angle_limit,                 ctx.angle_limit_values);
    copy_nb(substep_damping,             ctx.substep_damping_values);
    copy_nb(max_distances,               ctx.max_distances);
    copy_nb(motion_stiffness,            ctx.motion_stiffness_values);
    copy_nb(backstop_radii,              ctx.backstop_radii);
    copy_nb(backstop_distances,          ctx.backstop_distances);
    ctx.param_array_count = static_cast<int64_t>(distance_stiffness.shape(0));
    ctx.param_arrays_ready = true;
}

static nb::dict ctx_info(const Mc2NativeContext& ctx) {
    nb::dict d;
    d["vertex_count"]        = ctx.vertex_count;
    d["line_count"]          = ctx.line_count;
    d["baseline_data_count"] = ctx.baseline_data_count;
    d["distance_count"]      = ctx.distance_count;
    d["bend_count"]          = ctx.bend_count;
    d["collider_radius_count"] = ctx.collider_radius_count;
    d["edge_count"]          = ctx.edge_count;
    d["triangle_count"]      = ctx.triangle_count;
    d["dihedral_count"]      = ctx.dihedral_count;
    d["volume_count"]        = ctx.volume_count;
    d["param_slot_count"]    = ctx.param_slot_count;
    d["param_array_count"]   = ctx.param_array_count;
    d["topology_serial"]     = ctx.topology_serial;
    d["param_serial"]        = ctx.param_serial;
    d["static_ready"]        = ctx.static_ready;
    d["param_arrays_ready"]  = ctx.param_arrays_ready;
    return d;
}

// ---------------------------------------------------------------------------
// 公共辅助：从 nb::args 填充 Mc2MeshClothSolveView 的 context 部分
// ---------------------------------------------------------------------------
static void fill_view_from_context(Mc2MeshClothSolveView& v, const Mc2NativeContext& ctx,
                                   bool use_cached)
{
    v.attributes            = data_or_dummy(ctx.attributes);
    v.depths                = data_or_dummy(ctx.depths);
    v.root_indices          = data_or_dummy(ctx.root_indices);
    v.tether_rest_lengths   = data_or_dummy(ctx.tether_rest_lengths);
    v.parent_indices        = data_or_dummy(ctx.parent_indices);
    v.baseline_start        = data_or_dummy(ctx.baseline_start);
    v.baseline_count        = data_or_dummy(ctx.baseline_count);
    v.baseline_data         = data_or_dummy(ctx.baseline_data);
    v.vertex_local_positions = data_or_dummy(ctx.vertex_local_positions);
    v.vertex_local_rotations = data_or_dummy(ctx.vertex_local_rotations);
    v.distance_start        = data_or_dummy(ctx.distance_start);
    v.distance_count        = data_or_dummy(ctx.distance_count_values);
    v.distance_data         = data_or_dummy(ctx.distance_data);
    v.distance_rest         = data_or_dummy(ctx.distance_rest);
    v.bend_distance_start   = data_or_dummy(ctx.bend_distance_start);
    v.bend_distance_count   = data_or_dummy(ctx.bend_distance_count);
    v.bend_distance_data    = data_or_dummy(ctx.bend_distance_data);
    v.bend_distance_rest    = data_or_dummy(ctx.bend_distance_rest);
    v.dihedral_pairs        = data_or_dummy(ctx.dihedral_pairs);
    v.dihedral_rest_angles  = data_or_dummy(ctx.dihedral_rest_angles);
    v.dihedral_signs        = data_or_dummy(ctx.dihedral_signs);
    v.volume_pairs          = data_or_dummy(ctx.volume_pairs);
    v.volume_rest           = data_or_dummy(ctx.volume_rest);
    v.edges                 = data_or_dummy(ctx.edges);
    v.triangles             = data_or_dummy(ctx.triangles);
    v.vertex_count          = ctx.vertex_count;
    v.line_count            = ctx.line_count;
    v.baseline_data_count   = ctx.baseline_data_count;
    v.edge_count            = ctx.edge_count;
    v.triangle_count        = ctx.triangle_count;
    v.dihedral_count        = ctx.dihedral_count;
    v.volume_count          = ctx.volume_count;
    if (use_cached) {
        v.distance_stiffness_values = data_or_dummy(ctx.distance_stiffness_values);
        v.bend_stiffness_values     = data_or_dummy(ctx.bend_stiffness_values);
        v.angle_restoration_values  = data_or_dummy(ctx.angle_restoration_values);
        v.angle_restoration_velocity_attenuation_values =
            data_or_dummy(ctx.angle_restoration_velocity_attenuation_values);
        v.angle_restoration_gravity_falloff_values =
            data_or_dummy(ctx.angle_restoration_gravity_falloff_values);
        v.angle_limit_values        = data_or_dummy(ctx.angle_limit_values);
        v.substep_damping_values    = data_or_dummy(ctx.substep_damping_values);
        v.max_distances             = data_or_dummy(ctx.max_distances);
        v.motion_stiffness_values   = data_or_dummy(ctx.motion_stiffness_values);
        v.backstop_radii            = data_or_dummy(ctx.backstop_radii);
        v.backstop_distances        = data_or_dummy(ctx.backstop_distances);
    }
}

// ---------------------------------------------------------------------------
// solve 公共逻辑（参数顺序与 native_bridge.py 完全对应）
//
// 非缓存（68个）：
//   [0..14]  动态 buffer (15)  positions..base_rotations
//   [15..25] param 数组 (11)
//   [26..44] collider + inertia (19)
//   [45..67] 标量 (23，其中 gravity 是 1d buffer)
//
// 缓存（57个）：
//   [0..14]  动态 buffer (15)
//   [15..33] collider + inertia (19)
//   [34..56] 标量 (23)
// ---------------------------------------------------------------------------
static void ctx_solve_impl(const Mc2NativeContext& ctx, nb::args a, bool use_cached_params)
{
    auto f2w = [&](size_t i) -> float*         { return nb::cast<F2w>(a[i]).data(); };
    auto f1w = [&](size_t i) -> float*         { return nb::cast<F1w>(a[i]).data(); };
    auto f2  = [&](size_t i) -> const float*   { return nb::cast<F2>(a[i]).data();  };
    auto f1  = [&](size_t i) -> const float*   { return nb::cast<F1>(a[i]).data();  };
    auto i1  = [&](size_t i) -> const int32_t* { return nb::cast<I1>(a[i]).data();  };

    size_t i = 0;  // 当前参数索引
    Mc2MeshClothSolveView v{};

    // ---- 动态 buffer（15个，0‥14）----
    v.positions            = f2w(i++);  // 0
    v.old_positions        = f2w(i++);  // 1
    v.velocity_positions   = f2w(i++);  // 2
    v.velocities           = f2w(i++);  // 3
    v.real_velocities      = f2w(i++);  // 4
    v.friction             = f1w(i++);  // 5
    v.static_friction      = f1w(i++);  // 6
    v.collision_normals    = f2w(i++);  // 7
    v.inv_masses           = f1w(i++);  // 8
    v.step_basic_positions = f2w(i++);  // 9
    v.step_basic_rotations = f2w(i++);  // 10
    v.display_positions    = f2w(i++);  // 11
    v.base_positions       = f2(i++);   // 12
    v.base_normals         = f2(i++);   // 13
    v.base_rotations       = f2(i++);   // 14  ← 之前漏掉此行

    // ---- 参数数组（11个，仅非缓存路径）----
    if (!use_cached_params) {
        v.distance_stiffness_values = f1(i++);
        v.bend_stiffness_values     = f1(i++);
        v.angle_restoration_values  = f1(i++);
        v.angle_restoration_velocity_attenuation_values = f1(i++);
        v.angle_restoration_gravity_falloff_values      = f1(i++);
        v.angle_limit_values        = f1(i++);
        v.substep_damping_values    = f1(i++);
        v.max_distances             = f1(i++);
        v.motion_stiffness_values   = f1(i++);
        v.backstop_radii            = f1(i++);
        v.backstop_distances        = f1(i++);
    }

    // ---- collider + inertia（19个）----
    v.collision_radii          = f1(i++);
    const size_t collider_types_idx = i;
    v.collider_types           = i1(i++);
    v.collider_group_bits      = i1(i++);
    v.collider_centers         = f2(i++);
    v.collider_segment_a       = f2(i++);
    v.collider_segment_b       = f2(i++);
    v.collider_old_centers     = f2(i++);
    v.collider_old_segment_a   = f2(i++);
    v.collider_old_segment_b   = f2(i++);
    v.collider_radii           = f1(i++);
    v.substep_old_world_positions = f2(i++);
    v.substep_step_vectors        = f2(i++);
    v.substep_step_rotations      = f2(i++);
    v.substep_inertia_vectors     = f2(i++);
    v.substep_inertia_rotations   = f2(i++);
    v.substep_now_world_positions = f2(i++);
    v.substep_rotation_axes       = f2(i++);
    v.substep_angular_velocities  = f1(i++);
    v.substep_velocity_weights    = f1(i++);

    // ---- 标量（23个）----
    const float  frame_dt   = static_cast<float>(nb::cast<double>(a[i++]));
    const float  step_dt    = static_cast<float>(nb::cast<double>(a[i++]));
    const int    substeps   = nb::cast<int>(a[i++]);
    const int    iterations = nb::cast<int>(a[i++]);
    const float* grav       = f1(i++);   // gravity shape (3,)
    v.gravity[0] = grav[0]; v.gravity[1] = grav[1]; v.gravity[2] = grav[2];
    v.depth_inertia         = static_cast<float>(nb::cast<double>(a[i++]));
    v.centrifugal           = static_cast<float>(nb::cast<double>(a[i++]));
    v.use_tether            = nb::cast<bool>(a[i++]);
    v.tether_compression    = static_cast<float>(nb::cast<double>(a[i++]));
    v.tether_stretch        = static_cast<float>(nb::cast<double>(a[i++]));
    v.dynamic_friction      = static_cast<float>(nb::cast<double>(a[i++]));
    v.static_friction_speed = static_cast<float>(nb::cast<double>(a[i++]));
    v.particle_speed_limit  = static_cast<float>(nb::cast<double>(a[i++]));
    v.angle_limit_stiffness = static_cast<float>(nb::cast<double>(a[i++]));
    v.normal_axis           = nb::cast<int>(a[i++]);
    v.collided_by_groups    = nb::cast<int32_t>(a[i++]);
    v.collider_collision_mode = nb::cast<int>(a[i++]);
    v.display_max_distance_ratio = static_cast<float>(nb::cast<double>(a[i++]));
    v.animation_pose_ratio  = static_cast<float>(nb::cast<double>(a[i++]));
    v.blend_weight          = static_cast<float>(nb::cast<double>(a[i++]));
    v.self_collision_enabled = nb::cast<bool>(a[i++]);
    v.self_collision_surface_thickness = static_cast<float>(nb::cast<double>(a[i++]));
    v.self_collision_mass   = static_cast<float>(nb::cast<double>(a[i++]));

    // ---- 派生维度 ----
    v.substeps       = std::max(1, std::min(16, substeps));
    v.iterations     = iterations;
    v.frame_dt       = frame_dt;
    v.step_dt        = step_dt;
    v.collider_count = static_cast<int64_t>(
        nb::cast<I1>(a[collider_types_idx]).shape(0));
    v.distance_count_total =
        static_cast<int64_t>(ctx.distance_data.size());
    v.bend_distance_count_total =
        static_cast<int64_t>(ctx.bend_distance_data.size());

    // ---- context 提供的静态数组 ----
    fill_view_from_context(v, ctx, use_cached_params);

    hotools::solve_meshcloth_mc2(v);
}

// ---------------------------------------------------------------------------
// register_mc2_context_class — 在 NB_MODULE 里调用
// ---------------------------------------------------------------------------
void register_mc2_context_class(nb::module_& m)
{
    nb::class_<Mc2NativeContext>(m, "Mc2Context",
        "MC2 布料模拟原生 Context（保存静态拓扑和参数缓存）")
        .def(nb::init<>())   // 默认构造，字段由 update_static 填充
        .def("__init__", [](Mc2NativeContext* ctx,
                             int64_t vertex_count, int64_t distance_count,
                             int64_t bend_count, int64_t collider_radius_count) {
            new (ctx) Mc2NativeContext();
            ctx->vertex_count          = vertex_count;
            ctx->distance_count        = distance_count;
            ctx->bend_count            = bend_count;
            ctx->collider_radius_count = collider_radius_count;
            ctx->topology_serial       = 1;
        }, nb::arg("vertex_count"), nb::arg("distance_count"),
           nb::arg("bend_count"), nb::arg("collider_radius_count"))
        .def("update_static",        &ctx_update_static,
             nb::arg("vertex_count"), nb::arg("distance_count"),
             nb::arg("bend_count"), nb::arg("collider_radius_count"))
        .def("update_static_arrays", &ctx_update_static_arrays)
        .def("update_params",        &ctx_update_params,
             nb::arg("param_slot_count"))
        .def("update_param_arrays",  &ctx_update_param_arrays)
        .def("free", [](Mc2NativeContext& ctx) { clear_static(ctx); })
        .def("info",                 &ctx_info)
        .def_ro("vertex_count",      &Mc2NativeContext::vertex_count)
        .def_ro("topology_serial",   &Mc2NativeContext::topology_serial)
        .def_ro("param_serial",      &Mc2NativeContext::param_serial)
        .def_ro("static_ready",      &Mc2NativeContext::static_ready)
        .def_ro("param_arrays_ready",&Mc2NativeContext::param_arrays_ready);

    // context 求解函数：暴露为模块级函数（与旧 API 一致）
    m.def("solve_meshcloth_mc2_context",
        [](Mc2NativeContext& ctx, nb::args a) {
            ctx_solve_impl(ctx, a, false);
        });
    m.def("solve_meshcloth_mc2_context_cached_params",
        [](Mc2NativeContext& ctx, nb::args a) {
            ctx_solve_impl(ctx, a, true);
        });
}

}  // namespace hotools
