#include <Python.h>

#include <nanobind/nanobind.h>

#include "hotools_mc2.hpp"
#include "hotools_mc2_bonecloth_io.hpp"
#include "hotools_property_curve.hpp"
#include "mc2_context.hpp"
#include "python_buffer_utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

PyObject* solve_spring_bone_vrm_cpp(PyObject*, PyObject*);

namespace nb = nanobind;

namespace {

using namespace hotools::py;  // Buffer, expect_*, as_double, as_long

// nb::object 版本结果转换：nullptr → 抛出 python_error
nb::object steal_or_throw(PyObject* result) {
    if (result == nullptr) throw nb::python_error();
    return nb::steal<nb::object>(result);
}

// 对于接受 (PyObject*, PyObject* args) 的旧式函数，用 nb::args 直接传递
// nb::args 在 nanobind 内部就是一个 Python tuple，ptr() 可直接传给旧函数
inline void call_legacy(PyObject* (*fn)(PyObject*, PyObject*), nb::args a) {
    PyObject* r = fn(nullptr, a.ptr());
    if (!r) throw nb::python_error();
    Py_DECREF(r);  // 函数返回 Py_None（已 INCREF），需要释放
}

PyObject* project_neighbor_constraints_mc2_object(PyObject* positions_object,
                                                  PyObject* inv_masses_object,
                                                  PyObject* starts_object,
                                                  PyObject* counts_object,
                                                  PyObject* neighbors_object,
                                                  PyObject* rest_lengths_object,
                                                  PyObject* stiffness_values_object,
                                                  PyObject* velocity_positions_object,
                                                  double velocity_attenuation) {
    Buffer positions;
    Buffer inv_masses;
    Buffer starts;
    Buffer counts;
    Buffer neighbors;
    Buffer rest_lengths;
    Buffer stiffness_values;
    Buffer velocity_positions;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !starts.get(starts_object, PyBUF_FORMAT | PyBUF_ND, "starts") ||
        !counts.get(counts_object, PyBUF_FORMAT | PyBUF_ND, "counts") ||
        !neighbors.get(neighbors_object, PyBUF_FORMAT | PyBUF_ND, "neighbors") ||
        !rest_lengths.get(rest_lengths_object, PyBUF_FORMAT | PyBUF_ND, "rest_lengths") ||
        !stiffness_values.get(stiffness_values_object, PyBUF_FORMAT | PyBUF_ND, "stiffness_values") ||
        !velocity_positions.get(velocity_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                                "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(starts, "starts") ||
        !expect_1d_array(starts, "starts", vertex_count) ||
        !expect_int32_scalar_array(counts, "counts") ||
        !expect_1d_array(counts, "counts", vertex_count) ||
        !expect_int32_scalar_array(neighbors, "neighbors") ||
        !expect_indices_in_range(neighbors, "neighbors", vertex_count) ||
        !expect_float32(rest_lengths, "rest_lengths") ||
        !expect_1d_array(rest_lengths, "rest_lengths", neighbors.view.shape[0]) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count)) {
        return nullptr;
    }
    hotools::Mc2NeighborConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.starts = static_cast<const std::int32_t*>(starts.view.buf);
    view.counts = static_cast<const std::int32_t*>(counts.view.buf);
    view.neighbors = static_cast<const std::int32_t*>(neighbors.view.buf);
    view.rest_lengths = static_cast<const float*>(rest_lengths.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.neighbor_count = static_cast<std::int64_t>(neighbors.view.shape[0]);
    view.velocity_attenuation = static_cast<float>(velocity_attenuation);

    hotools::project_neighbor_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_tether_mc2_object(PyObject* positions_object,
                                    PyObject* inv_masses_object,
                                    PyObject* root_indices_object,
                                    PyObject* root_rest_lengths_object,
                                    PyObject* velocity_positions_object,
                                    double stiffness,
                                    double compression,
                                    double stretch) {
    Buffer positions;
    Buffer inv_masses;
    Buffer root_indices;
    Buffer root_rest_lengths;
    Buffer velocity_positions;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !root_indices.get(root_indices_object, PyBUF_FORMAT | PyBUF_ND, "root_indices") ||
        !root_rest_lengths.get(root_rest_lengths_object, PyBUF_FORMAT | PyBUF_ND, "root_rest_lengths") ||
        !velocity_positions.get(velocity_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                                "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(root_indices, "root_indices") ||
        !expect_1d_array(root_indices, "root_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(root_indices, "root_indices", vertex_count) ||
        !expect_float32(root_rest_lengths, "root_rest_lengths") ||
        !expect_1d_array(root_rest_lengths, "root_rest_lengths", vertex_count)) {
        return nullptr;
    }

    hotools::Mc2TetherConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.root_indices = static_cast<const std::int32_t*>(root_indices.view.buf);
    view.root_rest_lengths = static_cast<const float*>(root_rest_lengths.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.stiffness = static_cast<float>(stiffness);
    view.compression = static_cast<float>(compression);
    view.stretch = static_cast<float>(stretch);

    hotools::project_tether_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_motion_constraints_mc2_object(PyObject* positions_object,
                                                PyObject* base_positions_object,
                                                PyObject* base_rotations_object,
                                                PyObject* inv_masses_object,
                                                PyObject* max_distances_object,
                                                PyObject* stiffness_values_object,
                                                PyObject* backstop_radii_object,
                                                PyObject* backstop_distances_object,
                                                PyObject* velocity_positions_object,
                                                int normal_axis) {
    Buffer positions;
    Buffer base_positions;
    Buffer base_rotations;
    Buffer inv_masses;
    Buffer max_distances;
    Buffer stiffness_values;
    Buffer backstop_radii;
    Buffer backstop_distances;
    Buffer velocity_positions;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !base_positions.get(base_positions_object, PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_rotations.get(base_rotations_object, PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !max_distances.get(max_distances_object, PyBUF_FORMAT | PyBUF_ND, "max_distances") ||
        !stiffness_values.get(stiffness_values_object, PyBUF_FORMAT | PyBUF_ND, "stiffness_values") ||
        !backstop_radii.get(backstop_radii_object, PyBUF_FORMAT | PyBUF_ND, "backstop_radii") ||
        !backstop_distances.get(backstop_distances_object, PyBUF_FORMAT | PyBUF_ND, "backstop_distances") ||
        !velocity_positions.get(velocity_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                                "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(max_distances, "max_distances") ||
        !expect_1d_array(max_distances, "max_distances", vertex_count) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count) ||
        !expect_float32(backstop_radii, "backstop_radii") ||
        !expect_1d_array(backstop_radii, "backstop_radii", vertex_count) ||
        !expect_float32(backstop_distances, "backstop_distances") ||
        !expect_1d_array(backstop_distances, "backstop_distances", vertex_count)) {
        return nullptr;
    }

    hotools::Mc2MotionConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_rotations = static_cast<const float*>(base_rotations.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.max_distances = static_cast<const float*>(max_distances.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.backstop_radii = static_cast<const float*>(backstop_radii.view.buf);
    view.backstop_distances = static_cast<const float*>(backstop_distances.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.normal_axis = std::max(0, std::min(5, normal_axis));

    hotools::project_motion_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_post_step_mc2_object(PyObject* positions_object,
                                     PyObject* old_positions_object,
                                     PyObject* velocity_positions_object,
                                     PyObject* velocities_object,
                                     PyObject* real_velocities_object,
                                     PyObject* friction_object,
                                     PyObject* static_friction_object,
                                     PyObject* collision_normals_object,
                                     PyObject* inv_masses_object,
                                     double step_dt,
                                     double dynamic_friction,
                                     double static_friction_speed,
                                     double particle_speed_limit) {
    Buffer positions;
    Buffer old_positions;
    Buffer velocity_positions;
    Buffer velocities;
    Buffer real_velocities;
    Buffer friction;
    Buffer static_friction;
    Buffer collision_normals;
    Buffer inv_masses;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !old_positions.get(old_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "old_positions") ||
        !velocity_positions.get(velocity_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                                "velocity_positions") ||
        !velocities.get(velocities_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !real_velocities.get(real_velocities_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "real_velocities") ||
        !friction.get(friction_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !static_friction.get(static_friction_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "static_friction") ||
        !collision_normals.get(collision_normals_object, PyBUF_FORMAT | PyBUF_ND, "collision_normals") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(old_positions, "old_positions", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_same_vertex_count(real_velocities, "real_velocities", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_float32(static_friction, "static_friction") ||
        !expect_1d_array(static_friction, "static_friction", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count)) {
        return nullptr;
    }

    hotools::Mc2PostStepView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.old_positions = static_cast<float*>(old_positions.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.real_velocities = static_cast<float*>(real_velocities.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.static_friction = static_cast<float*>(static_friction.view.buf);
    view.collision_normals = static_cast<const float*>(collision_normals.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.step_dt = static_cast<float>(step_dt);
    view.dynamic_friction = static_cast<float>(dynamic_friction);
    view.static_friction_speed = static_cast<float>(static_friction_speed);
    view.particle_speed_limit = static_cast<float>(particle_speed_limit);

    hotools::apply_post_step_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_collisions_mc2_object(PyObject* positions_object,
                                        PyObject* base_positions_object,
                                        PyObject* inv_masses_object,
                                        PyObject* collision_radii_object,
                                        PyObject* collision_normals_object,
                                        PyObject* friction_object,
                                        int collided_by_groups,
                                        PyObject* collider_types_object,
                                        PyObject* collider_group_bits_object,
                                        PyObject* collider_centers_object,
                                        PyObject* collider_segment_a_object,
                                        PyObject* collider_segment_b_object,
                                        PyObject* collider_old_centers_object,
                                        PyObject* collider_old_segment_a_object,
                                        PyObject* collider_old_segment_b_object,
                                        PyObject* collider_radii_object) {
    Buffer positions;
    Buffer base_positions;
    Buffer inv_masses;
    Buffer collision_radii;
    Buffer collision_normals;
    Buffer friction;
    Buffer collider_types;
    Buffer collider_group_bits;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_old_centers;
    Buffer collider_old_segment_a;
    Buffer collider_old_segment_b;
    Buffer collider_radii;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !base_positions.get(base_positions_object, PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !collision_radii.get(collision_radii_object, PyBUF_FORMAT | PyBUF_ND, "collision_radii") ||
        !collision_normals.get(collision_normals_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "collision_normals") ||
        !friction.get(friction_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !collider_types.get(collider_types_object, PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_group_bits.get(collider_group_bits_object, PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !collider_centers.get(collider_centers_object, PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(collider_segment_a_object, PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(collider_segment_b_object, PyBUF_FORMAT | PyBUF_ND, "collider_segment_b")) {
        return nullptr;
    }
    if (!collider_old_centers.get(collider_old_centers_object, PyBUF_FORMAT | PyBUF_ND,
                                  "collider_old_centers") ||
        !collider_old_segment_a.get(collider_old_segment_a_object, PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_a") ||
        !collider_old_segment_b.get(collider_old_segment_b_object, PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_b") ||
        !collider_radii.get(collider_radii_object, PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(collision_radii, "collision_radii") ||
        !expect_1d_array(collision_radii, "collision_radii", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_int32_scalar_array(collider_types, "collider_types") ||
        !expect_int32_scalar_array(collider_group_bits, "collider_group_bits") ||
        !expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    const Py_ssize_t collider_count = collider_types.view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = collider_count;
    Py_ssize_t collider_old_segment_a_count = collider_count;
    Py_ssize_t collider_old_segment_b_count = collider_count;
    if (!expect_1d_array(collider_group_bits, "collider_group_bits", collider_count) ||
        !expect_1d_array(collider_radii, "collider_radii", collider_count) ||
        !expect_vector3_array(collider_centers, "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count)) {
        return nullptr;
    }
    if (!expect_vector3_array(collider_old_centers, "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(collider_old_segment_a, "collider_old_segment_a", &collider_old_segment_a_count) ||
        !expect_vector3_array(collider_old_segment_b, "collider_old_segment_b", &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    hotools::Mc2CollisionView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.collision_radii = static_cast<const float*>(collision_radii.view.buf);
    view.collision_normals = static_cast<float*>(collision_normals.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.collider_types = static_cast<const std::int32_t*>(collider_types.view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(collider_group_bits.view.buf);
    view.collider_centers = static_cast<const float*>(collider_centers.view.buf);
    view.collider_segment_a = static_cast<const float*>(collider_segment_a.view.buf);
    view.collider_segment_b = static_cast<const float*>(collider_segment_b.view.buf);
    view.collider_old_centers = static_cast<const float*>(collider_old_centers.view.buf);
    view.collider_old_segment_a = static_cast<const float*>(collider_old_segment_a.view.buf);
    view.collider_old_segment_b = static_cast<const float*>(collider_old_segment_b.view.buf);
    view.collider_radii = static_cast<const float*>(collider_radii.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);

    hotools::project_collisions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_edge_collisions_mc2_object(PyObject* positions_object,
                                             PyObject* edges_object,
                                             PyObject* attributes_object,
                                             PyObject* inv_masses_object,
                                             PyObject* collision_radii_object,
                                             PyObject* collision_normals_object,
                                             PyObject* friction_object,
                                             int collided_by_groups,
                                             PyObject* collider_types_object,
                                             PyObject* collider_group_bits_object,
                                             PyObject* collider_centers_object,
                                             PyObject* collider_segment_a_object,
                                             PyObject* collider_segment_b_object,
                                             PyObject* collider_old_centers_object,
                                             PyObject* collider_old_segment_a_object,
                                             PyObject* collider_old_segment_b_object,
                                             PyObject* collider_radii_object) {
    Buffer positions;
    Buffer edges;
    Buffer attributes;
    Buffer inv_masses;
    Buffer collision_radii;
    Buffer collision_normals;
    Buffer friction;
    Buffer collider_types;
    Buffer collider_group_bits;
    Buffer collider_centers;
    Buffer collider_segment_a;
    Buffer collider_segment_b;
    Buffer collider_old_centers;
    Buffer collider_old_segment_a;
    Buffer collider_old_segment_b;
    Buffer collider_radii;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !edges.get(edges_object, PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !attributes.get(attributes_object, PyBUF_FORMAT | PyBUF_ND, "attributes") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !collision_radii.get(collision_radii_object, PyBUF_FORMAT | PyBUF_ND, "collision_radii") ||
        !collision_normals.get(collision_normals_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "collision_normals") ||
        !friction.get(friction_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction") ||
        !collider_types.get(collider_types_object, PyBUF_FORMAT | PyBUF_ND, "collider_types") ||
        !collider_group_bits.get(collider_group_bits_object, PyBUF_FORMAT | PyBUF_ND, "collider_group_bits") ||
        !collider_centers.get(collider_centers_object, PyBUF_FORMAT | PyBUF_ND, "collider_centers") ||
        !collider_segment_a.get(collider_segment_a_object, PyBUF_FORMAT | PyBUF_ND, "collider_segment_a") ||
        !collider_segment_b.get(collider_segment_b_object, PyBUF_FORMAT | PyBUF_ND, "collider_segment_b") ||
        !collider_old_centers.get(collider_old_centers_object, PyBUF_FORMAT | PyBUF_ND,
                                  "collider_old_centers") ||
        !collider_old_segment_a.get(collider_old_segment_a_object, PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_a") ||
        !collider_old_segment_b.get(collider_old_segment_b_object, PyBUF_FORMAT | PyBUF_ND,
                                    "collider_old_segment_b") ||
        !collider_radii.get(collider_radii_object, PyBUF_FORMAT | PyBUF_ND, "collider_radii")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t edge_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_int32_pair_array(edges, "edges", &edge_count) ||
        !expect_pair_indices_in_range(edges, "edges", vertex_count) ||
        !expect_uint8_scalar_array(attributes, "attributes") ||
        !expect_1d_array(attributes, "attributes", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(collision_radii, "collision_radii") ||
        !expect_1d_array(collision_radii, "collision_radii", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count) ||
        !expect_int32_scalar_array(collider_types, "collider_types") ||
        !expect_int32_scalar_array(collider_group_bits, "collider_group_bits") ||
        !expect_float32(collider_radii, "collider_radii")) {
        return nullptr;
    }

    const Py_ssize_t collider_count = collider_types.view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = 0;
    Py_ssize_t collider_old_segment_a_count = 0;
    Py_ssize_t collider_old_segment_b_count = 0;
    if (!expect_1d_array(collider_group_bits, "collider_group_bits", collider_count) ||
        !expect_1d_array(collider_radii, "collider_radii", collider_count) ||
        !expect_vector3_array(collider_centers, "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(collider_segment_a, "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(collider_segment_b, "collider_segment_b", &collider_segment_b_count) ||
        !expect_vector3_array(collider_old_centers, "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(collider_old_segment_a, "collider_old_segment_a", &collider_old_segment_a_count) ||
        !expect_vector3_array(collider_old_segment_b, "collider_old_segment_b", &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    hotools::Mc2EdgeCollisionView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.edges = static_cast<const std::int32_t*>(edges.view.buf);
    view.attributes = static_cast<const std::uint8_t*>(attributes.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.collision_radii = static_cast<const float*>(collision_radii.view.buf);
    view.collision_normals = static_cast<float*>(collision_normals.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.collider_types = static_cast<const std::int32_t*>(collider_types.view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(collider_group_bits.view.buf);
    view.collider_centers = static_cast<const float*>(collider_centers.view.buf);
    view.collider_segment_a = static_cast<const float*>(collider_segment_a.view.buf);
    view.collider_segment_b = static_cast<const float*>(collider_segment_b.view.buf);
    view.collider_old_centers = static_cast<const float*>(collider_old_centers.view.buf);
    view.collider_old_segment_a = static_cast<const float*>(collider_old_segment_a.view.buf);
    view.collider_old_segment_b = static_cast<const float*>(collider_old_segment_b.view.buf);
    view.collider_radii = static_cast<const float*>(collider_radii.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);

    hotools::project_edge_collisions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_self_collisions_mc2_object(PyObject* positions_object,
                                             PyObject* old_positions_object,
                                             PyObject* inv_masses_object,
                                             PyObject* edges_object,
                                             PyObject* triangles_object,
                                             PyObject* attributes_object,
                                             PyObject* collision_normals_object,
                                             PyObject* friction_object,
                                             double surface_thickness) {
    Buffer positions;
    Buffer old_positions;
    Buffer inv_masses;
    Buffer edges;
    Buffer triangles;
    Buffer attributes;
    Buffer collision_normals;
    Buffer friction;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !old_positions.get(old_positions_object, PyBUF_FORMAT | PyBUF_ND, "old_positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !edges.get(edges_object, PyBUF_FORMAT | PyBUF_ND, "edges") ||
        !triangles.get(triangles_object, PyBUF_FORMAT | PyBUF_ND, "triangles") ||
        !attributes.get(attributes_object, PyBUF_FORMAT | PyBUF_ND, "attributes") ||
        !collision_normals.get(collision_normals_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "collision_normals") ||
        !friction.get(friction_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "friction")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t edge_count = 0;
    Py_ssize_t triangle_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(old_positions, "old_positions", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_pair_array(edges, "edges", &edge_count) ||
        !expect_int32_triple_array(triangles, "triangles", &triangle_count) ||
        !expect_uint8_scalar_array(attributes, "attributes") ||
        !expect_1d_array(attributes, "attributes", vertex_count) ||
        !expect_same_vertex_count(collision_normals, "collision_normals", vertex_count) ||
        !expect_float32(friction, "friction") ||
        !expect_1d_array(friction, "friction", vertex_count)) {
        return nullptr;
    }
    if ((edge_count > 0 && !expect_pair_indices_in_range(edges, "edges", vertex_count)) ||
        (triangle_count > 0 && !expect_triple_indices_in_range(triangles, "triangles", vertex_count))) {
        return nullptr;
    }

    hotools::Mc2SelfCollisionView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.old_positions = static_cast<const float*>(old_positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.edges = static_cast<const std::int32_t*>(edges.view.buf);
    view.triangles = static_cast<const std::int32_t*>(triangles.view.buf);
    view.attributes = static_cast<const std::uint8_t*>(attributes.view.buf);
    view.collision_normals = static_cast<float*>(collision_normals.view.buf);
    view.friction = static_cast<float*>(friction.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.triangle_count = static_cast<std::int64_t>(triangle_count);
    view.surface_thickness = static_cast<float>(surface_thickness);

    hotools::project_self_collisions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_triangle_bending_mc2_object(PyObject* positions_object,
                                              PyObject* inv_masses_object,
                                              PyObject* dihedral_pairs_object,
                                              PyObject* dihedral_rest_angles_object,
                                              PyObject* dihedral_signs_object,
                                              PyObject* volume_pairs_object,
                                              PyObject* volume_rest_object,
                                              PyObject* stiffness_values_object) {
    Buffer positions;
    Buffer inv_masses;
    Buffer dihedral_pairs;
    Buffer dihedral_rest_angles;
    Buffer dihedral_signs;
    Buffer volume_pairs;
    Buffer volume_rest;
    Buffer stiffness_values;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !dihedral_pairs.get(dihedral_pairs_object, PyBUF_FORMAT | PyBUF_ND, "dihedral_pairs") ||
        !dihedral_rest_angles.get(dihedral_rest_angles_object, PyBUF_FORMAT | PyBUF_ND, "dihedral_rest_angles") ||
        !dihedral_signs.get(dihedral_signs_object, PyBUF_FORMAT | PyBUF_ND, "dihedral_signs") ||
        !volume_pairs.get(volume_pairs_object, PyBUF_FORMAT | PyBUF_ND, "volume_pairs") ||
        !volume_rest.get(volume_rest_object, PyBUF_FORMAT | PyBUF_ND, "volume_rest") ||
        !stiffness_values.get(stiffness_values_object, PyBUF_FORMAT | PyBUF_ND, "stiffness_values")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    Py_ssize_t dihedral_count = 0;
    Py_ssize_t volume_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_quad_array(dihedral_pairs, "dihedral_pairs", &dihedral_count) ||
        !expect_float32(dihedral_rest_angles, "dihedral_rest_angles") ||
        !expect_1d_array(dihedral_rest_angles, "dihedral_rest_angles", dihedral_count) ||
        !expect_int32_scalar_array(dihedral_signs, "dihedral_signs") ||
        !expect_1d_array(dihedral_signs, "dihedral_signs", dihedral_count) ||
        !expect_int32_quad_array(volume_pairs, "volume_pairs", &volume_count) ||
        !expect_float32(volume_rest, "volume_rest") ||
        !expect_1d_array(volume_rest, "volume_rest", volume_count) ||
        !expect_float32(stiffness_values, "stiffness_values") ||
        !expect_1d_array(stiffness_values, "stiffness_values", vertex_count)) {
        return nullptr;
    }
    if ((dihedral_count > 0 && !expect_quad_indices_in_range(dihedral_pairs, "dihedral_pairs", vertex_count)) ||
        (volume_count > 0 && !expect_quad_indices_in_range(volume_pairs, "volume_pairs", vertex_count))) {
        return nullptr;
    }

    hotools::Mc2TriangleBendingView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.dihedral_pairs = static_cast<const std::int32_t*>(dihedral_pairs.view.buf);
    view.dihedral_rest_angles = static_cast<const float*>(dihedral_rest_angles.view.buf);
    view.dihedral_signs = static_cast<const std::int32_t*>(dihedral_signs.view.buf);
    view.volume_pairs = static_cast<const std::int32_t*>(volume_pairs.view.buf);
    view.volume_rest = static_cast<const float*>(volume_rest.view.buf);
    view.stiffness_values = static_cast<const float*>(stiffness_values.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.dihedral_count = static_cast<std::int64_t>(dihedral_count);
    view.volume_count = static_cast<std::int64_t>(volume_count);

    hotools::project_triangle_bending_mc2(view);
    Py_RETURN_NONE;
}

PyObject* project_angle_constraints_mc2_object(PyObject* positions_object,
                                               PyObject* inv_masses_object,
                                               PyObject* parent_indices_object,
                                               PyObject* baseline_start_object,
                                               PyObject* baseline_count_object,
                                               PyObject* baseline_data_object,
                                               PyObject* step_basic_positions_object,
                                               PyObject* step_basic_rotations_object,
                                               PyObject* restoration_values_object,
                                               PyObject* limit_values_object,
                                               PyObject* velocity_positions_object,
                                               double restoration_velocity_attenuation,
                                               double restoration_gravity_falloff,
                                               double limit_stiffness) {
    Buffer positions;
    Buffer inv_masses;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer step_basic_positions;
    Buffer step_basic_rotations;
    Buffer restoration_values;
    Buffer limit_values;
    Buffer velocity_positions;

    if (!positions.get(positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !parent_indices.get(parent_indices_object, PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(baseline_start_object, PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(baseline_count_object, PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(baseline_data_object, PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !step_basic_positions.get(step_basic_positions_object, PyBUF_FORMAT | PyBUF_ND, "step_basic_positions") ||
        !step_basic_rotations.get(step_basic_rotations_object, PyBUF_FORMAT | PyBUF_ND, "step_basic_rotations") ||
        !restoration_values.get(restoration_values_object, PyBUF_FORMAT | PyBUF_ND, "restoration_values") ||
        !limit_values.get(limit_values_object, PyBUF_FORMAT | PyBUF_ND, "limit_values") ||
        !velocity_positions.get(velocity_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                                "velocity_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(step_basic_positions, "step_basic_positions", vertex_count) ||
        !expect_same_vertex_count(velocity_positions, "velocity_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_basic_rotations, "step_basic_rotations", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count) ||
        !expect_float32(restoration_values, "restoration_values") ||
        !expect_1d_array(restoration_values, "restoration_values", vertex_count) ||
        !expect_float32(limit_values, "limit_values") ||
        !expect_1d_array(limit_values, "limit_values", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    hotools::Mc2AngleConstraintView view;
    view.positions = static_cast<float*>(positions.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.step_basic_positions = static_cast<const float*>(step_basic_positions.view.buf);
    view.step_basic_rotations = static_cast<const float*>(step_basic_rotations.view.buf);
    view.restoration_values = static_cast<const float*>(restoration_values.view.buf);
    view.limit_values = static_cast<const float*>(limit_values.view.buf);
    view.velocity_positions = static_cast<float*>(velocity_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.restoration_velocity_attenuation = static_cast<float>(restoration_velocity_attenuation);
    view.restoration_gravity_falloff = static_cast<float>(restoration_gravity_falloff);
    view.limit_stiffness = static_cast<float>(limit_stiffness);

    hotools::project_angle_constraints_mc2(view);
    Py_RETURN_NONE;
}

PyObject* update_step_basic_pose_mc2_object(PyObject* base_positions_object,
                                            PyObject* base_rotations_object,
                                            PyObject* parent_indices_object,
                                            PyObject* baseline_start_object,
                                            PyObject* baseline_count_object,
                                            PyObject* baseline_data_object,
                                            PyObject* vertex_local_positions_object,
                                            PyObject* vertex_local_rotations_object,
                                            PyObject* step_positions_object,
                                            PyObject* step_rotations_object,
                                            double animation_pose_ratio) {
    Buffer base_positions;
    Buffer base_rotations;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer vertex_local_positions;
    Buffer vertex_local_rotations;
    Buffer step_positions;
    Buffer step_rotations;

    if (!base_positions.get(base_positions_object, PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_rotations.get(base_rotations_object, PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !parent_indices.get(parent_indices_object, PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(baseline_start_object, PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(baseline_count_object, PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(baseline_data_object, PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !vertex_local_positions.get(vertex_local_positions_object, PyBUF_FORMAT | PyBUF_ND,
                                    "vertex_local_positions") ||
        !vertex_local_rotations.get(vertex_local_rotations_object, PyBUF_FORMAT | PyBUF_ND,
                                    "vertex_local_rotations") ||
        !step_positions.get(step_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_positions") ||
        !step_rotations.get(step_rotations_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_rotations")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(base_positions, "base_positions", &vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(vertex_local_positions, "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(vertex_local_rotations, "vertex_local_rotations", vertex_count) ||
        !expect_same_vertex_count(step_positions, "step_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_rotations, "step_rotations", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    hotools::Mc2StepBasicPoseView view;
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_rotations = static_cast<const float*>(base_rotations.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.vertex_local_positions = static_cast<const float*>(vertex_local_positions.view.buf);
    view.vertex_local_rotations = static_cast<const float*>(vertex_local_rotations.view.buf);
    view.step_positions = static_cast<float*>(step_positions.view.buf);
    view.step_rotations = static_cast<float*>(step_rotations.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);

    hotools::update_step_basic_pose_mc2(view);
    Py_RETURN_NONE;
}

PyObject* update_base_pose_from_pose_mc2_object(PyObject* base_positions_object,
                                                PyObject* base_normals_object,
                                                PyObject* parent_indices_object,
                                                PyObject* baseline_start_object,
                                                PyObject* baseline_count_object,
                                                PyObject* baseline_data_object,
                                                PyObject* vertex_local_positions_object,
                                                PyObject* vertex_local_rotations_object,
                                                PyObject* base_rotations_object,
                                                PyObject* step_positions_object,
                                                PyObject* step_rotations_object,
                                                double animation_pose_ratio) {
    Buffer base_positions;
    Buffer base_normals;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer vertex_local_positions;
    Buffer vertex_local_rotations;
    Buffer base_rotations;
    Buffer step_positions;
    Buffer step_rotations;

    if (!base_positions.get(base_positions_object, PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_normals.get(base_normals_object, PyBUF_FORMAT | PyBUF_ND, "base_normals") ||
        !parent_indices.get(parent_indices_object, PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(baseline_start_object, PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(baseline_count_object, PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(baseline_data_object, PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !vertex_local_positions.get(vertex_local_positions_object, PyBUF_FORMAT | PyBUF_ND,
                                    "vertex_local_positions") ||
        !vertex_local_rotations.get(vertex_local_rotations_object, PyBUF_FORMAT | PyBUF_ND,
                                    "vertex_local_rotations") ||
        !base_rotations.get(base_rotations_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !step_positions.get(step_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_positions") ||
        !step_rotations.get(step_rotations_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "step_rotations")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(base_positions, "base_positions", &vertex_count) ||
        !expect_same_vertex_count(base_normals, "base_normals", vertex_count) ||
        !expect_same_vertex_count(vertex_local_positions, "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(vertex_local_rotations, "vertex_local_rotations", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(step_positions, "step_positions", vertex_count) ||
        !expect_same_quat_vertex_count(step_rotations, "step_rotations", vertex_count) ||
        !expect_int32_scalar_array(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_indices_in_range(baseline_data, "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = baseline_start.view.shape[0];
    if (!expect_1d_array(baseline_count, "baseline_count", line_count)) {
        return nullptr;
    }

    hotools::Mc2BasePoseFromPoseView view;
    view.base_positions = static_cast<const float*>(base_positions.view.buf);
    view.base_normals = static_cast<const float*>(base_normals.view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.vertex_local_positions = static_cast<const float*>(vertex_local_positions.view.buf);
    view.vertex_local_rotations = static_cast<const float*>(vertex_local_rotations.view.buf);
    view.base_rotations = static_cast<float*>(base_rotations.view.buf);
    view.step_positions = static_cast<float*>(step_positions.view.buf);
    view.step_rotations = static_cast<float*>(step_rotations.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(baseline_data.view.shape[0]);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);

    hotools::update_base_pose_from_pose_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_substep_inertia_mc2_object(PyObject* old_positions_object,
                                           PyObject* velocities_object,
                                           PyObject* depths_object,
                                           PyObject* inv_masses_object,
                                           PyObject* old_world_position_object,
                                           PyObject* step_vector_object,
                                           PyObject* step_rotation_object,
                                           PyObject* inertia_vector_object,
                                           PyObject* inertia_rotation_object,
                                           double depth_inertia) {
    Buffer old_positions;
    Buffer velocities;
    Buffer depths;
    Buffer inv_masses;
    Buffer old_world_position;
    Buffer step_vector;
    Buffer step_rotation;
    Buffer inertia_vector;
    Buffer inertia_rotation;

    if (!old_positions.get(old_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "old_positions") ||
        !velocities.get(velocities_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !depths.get(depths_object, PyBUF_FORMAT | PyBUF_ND, "depths") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !old_world_position.get(old_world_position_object, PyBUF_FORMAT | PyBUF_ND, "old_world_position") ||
        !step_vector.get(step_vector_object, PyBUF_FORMAT | PyBUF_ND, "step_vector") ||
        !step_rotation.get(step_rotation_object, PyBUF_FORMAT | PyBUF_ND, "step_rotation") ||
        !inertia_vector.get(inertia_vector_object, PyBUF_FORMAT | PyBUF_ND, "inertia_vector") ||
        !inertia_rotation.get(inertia_rotation_object, PyBUF_FORMAT | PyBUF_ND, "inertia_rotation")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(old_positions, "old_positions", &vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_float32(depths, "depths") ||
        !expect_1d_array(depths, "depths", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(old_world_position, "old_world_position") ||
        !expect_1d_array(old_world_position, "old_world_position", 3) ||
        !expect_float32(step_vector, "step_vector") ||
        !expect_1d_array(step_vector, "step_vector", 3) ||
        !expect_float32(step_rotation, "step_rotation") ||
        !expect_1d_array(step_rotation, "step_rotation", 4) ||
        !expect_float32(inertia_vector, "inertia_vector") ||
        !expect_1d_array(inertia_vector, "inertia_vector", 3) ||
        !expect_float32(inertia_rotation, "inertia_rotation") ||
        !expect_1d_array(inertia_rotation, "inertia_rotation", 4)) {
        return nullptr;
    }

    hotools::Mc2SubstepInertiaView view;
    view.old_positions = static_cast<float*>(old_positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.depths = static_cast<const float*>(depths.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    const float* old_world_position_values = static_cast<const float*>(old_world_position.view.buf);
    const float* step_vector_values = static_cast<const float*>(step_vector.view.buf);
    const float* step_rotation_values = static_cast<const float*>(step_rotation.view.buf);
    const float* inertia_vector_values = static_cast<const float*>(inertia_vector.view.buf);
    const float* inertia_rotation_values = static_cast<const float*>(inertia_rotation.view.buf);
    for (int index = 0; index < 3; ++index) {
        view.old_world_position[index] = old_world_position_values[index];
        view.step_vector[index] = step_vector_values[index];
        view.inertia_vector[index] = inertia_vector_values[index];
    }
    for (int index = 0; index < 4; ++index) {
        view.step_rotation[index] = step_rotation_values[index];
        view.inertia_rotation[index] = inertia_rotation_values[index];
    }
    view.depth_inertia = static_cast<float>(depth_inertia);

    hotools::apply_substep_inertia_mc2(view);
    Py_RETURN_NONE;
}

PyObject* apply_centrifugal_velocity_mc2_object(PyObject* positions_object,
                                                PyObject* velocities_object,
                                                PyObject* depths_object,
                                                PyObject* inv_masses_object,
                                                PyObject* now_world_position_object,
                                                PyObject* rotation_axis_object,
                                                double angular_velocity,
                                                double centrifugal) {
    Buffer positions;
    Buffer velocities;
    Buffer depths;
    Buffer inv_masses;
    Buffer now_world_position;
    Buffer rotation_axis;

    if (!positions.get(positions_object, PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !velocities.get(velocities_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "velocities") ||
        !depths.get(depths_object, PyBUF_FORMAT | PyBUF_ND, "depths") ||
        !inv_masses.get(inv_masses_object, PyBUF_FORMAT | PyBUF_ND, "inv_masses") ||
        !now_world_position.get(now_world_position_object, PyBUF_FORMAT | PyBUF_ND, "now_world_position") ||
        !rotation_axis.get(rotation_axis_object, PyBUF_FORMAT | PyBUF_ND, "rotation_axis")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(velocities, "velocities", vertex_count) ||
        !expect_float32(depths, "depths") ||
        !expect_1d_array(depths, "depths", vertex_count) ||
        !expect_float32(inv_masses, "inv_masses") ||
        !expect_1d_array(inv_masses, "inv_masses", vertex_count) ||
        !expect_float32(now_world_position, "now_world_position") ||
        !expect_1d_array(now_world_position, "now_world_position", 3) ||
        !expect_float32(rotation_axis, "rotation_axis") ||
        !expect_1d_array(rotation_axis, "rotation_axis", 3)) {
        return nullptr;
    }

    hotools::Mc2CentrifugalView view;
    view.positions = static_cast<const float*>(positions.view.buf);
    view.velocities = static_cast<float*>(velocities.view.buf);
    view.depths = static_cast<const float*>(depths.view.buf);
    view.inv_masses = static_cast<const float*>(inv_masses.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    const float* now_world_position_values = static_cast<const float*>(now_world_position.view.buf);
    const float* rotation_axis_values = static_cast<const float*>(rotation_axis.view.buf);
    for (int index = 0; index < 3; ++index) {
        view.now_world_position[index] = now_world_position_values[index];
        view.rotation_axis[index] = rotation_axis_values[index];
    }
    view.angular_velocity = static_cast<float>(angular_velocity);
    view.centrifugal = static_cast<float>(centrifugal);

    hotools::apply_centrifugal_velocity_mc2(view);
    Py_RETURN_NONE;
}

PyObject* calculate_display_positions_mc2_object(PyObject* positions_object,
                                                 PyObject* real_velocities_object,
                                                 PyObject* root_indices_object,
                                                 PyObject* display_positions_object,
                                                 double frame_dt,
                                                 double max_distance_ratio) {
    Buffer positions;
    Buffer real_velocities;
    Buffer root_indices;
    Buffer display_positions;

    if (!positions.get(positions_object, PyBUF_FORMAT | PyBUF_ND, "positions") ||
        !real_velocities.get(real_velocities_object, PyBUF_FORMAT | PyBUF_ND, "real_velocities") ||
        !root_indices.get(root_indices_object, PyBUF_FORMAT | PyBUF_ND, "root_indices") ||
        !display_positions.get(display_positions_object, PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND,
                               "display_positions")) {
        return nullptr;
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(positions, "positions", &vertex_count) ||
        !expect_same_vertex_count(real_velocities, "real_velocities", vertex_count) ||
        !expect_same_vertex_count(display_positions, "display_positions", vertex_count) ||
        !expect_int32_scalar_array(root_indices, "root_indices") ||
        !expect_1d_array(root_indices, "root_indices", vertex_count)) {
        return nullptr;
    }

    hotools::Mc2DisplayPredictionView view;
    view.positions = static_cast<const float*>(positions.view.buf);
    view.real_velocities = static_cast<const float*>(real_velocities.view.buf);
    view.root_indices = static_cast<const std::int32_t*>(root_indices.view.buf);
    view.display_positions = static_cast<float*>(display_positions.view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.frame_dt = static_cast<float>(frame_dt);
    view.max_distance_ratio = static_cast<float>(max_distance_ratio);

    hotools::calculate_display_positions_mc2(view);
    Py_RETURN_NONE;
}

PyObject* solve_meshcloth_mc2(PyObject*, PyObject* args) {
    enum SolveArg {
        APositions = 0,
        AOldPositions,
        AVelocityPositions,
        AVelocities,
        ARealVelocities,
        AFriction,
        AStaticFriction,
        ACollisionNormals,
        AInvMasses,
        AStepBasicPositions,
        AStepBasicRotations,
        ADisplayPositions,
        ABasePositions,
        ABaseNormals,
        ABaseRotations,
        AAttributes,
        ADepths,
        ARootIndices,
        ATetherRestLengths,
        AParentIndices,
        ABaselineStart,
        ABaselineCount,
        ABaselineData,
        AVertexLocalPositions,
        AVertexLocalRotations,
        ADistanceStart,
        ADistanceCount,
        ADistanceData,
        ADistanceRest,
        ADistanceStiffnessValues,
        ABendDistanceStart,
        ABendDistanceCount,
        ABendDistanceData,
        ABendDistanceRest,
        ABendStiffnessValues,
        ADihedralPairs,
        ADihedralRestAngles,
        ADihedralSigns,
        AVolumePairs,
        AVolumeRest,
        AAngleRestorationValues,
        AAngleRestorationVelocityAttenuationValues,
        AAngleRestorationGravityFalloffValues,
        AAngleLimitValues,
        ASubstepDampingValues,
        AMaxDistances,
        AMotionStiffnessValues,
        ABackstopRadii,
        ABackstopDistances,
        AEdges,
        ATriangles,
        ACollisionRadii,
        AColliderTypes,
        AColliderGroupBits,
        AColliderCenters,
        AColliderSegmentA,
        AColliderSegmentB,
        AColliderOldCenters,
        AColliderOldSegmentA,
        AColliderOldSegmentB,
        AColliderRadii,
        ASubstepOldWorldPositions,
        ASubstepStepVectors,
        ASubstepStepRotations,
        ASubstepInertiaVectors,
        ASubstepInertiaRotations,
        ASubstepNowWorldPositions,
        ASubstepRotationAxes,
        ASubstepAngularVelocities,
        ASubstepVelocityWeights,
        kSolveBufferCount,
    };
    constexpr Py_ssize_t kArgCount = 93;
    if (PyTuple_GET_SIZE(args) != kArgCount) {
        PyErr_Format(PyExc_TypeError, "solve_meshcloth_mc2 expects %zd arguments", kArgCount);
        return nullptr;
    }

    const char* names[kSolveBufferCount] = {
        "positions",
        "old_positions",
        "velocity_positions",
        "velocities",
        "real_velocities",
        "friction",
        "static_friction",
        "collision_normals",
        "inv_masses",
        "step_basic_positions",
        "step_basic_rotations",
        "display_positions",
        "base_positions",
        "base_normals",
        "base_rotations",
        "attributes",
        "depths",
        "root_indices",
        "tether_rest_lengths",
        "parent_indices",
        "baseline_start",
        "baseline_count",
        "baseline_data",
        "vertex_local_positions",
        "vertex_local_rotations",
        "distance_start",
        "distance_count",
        "distance_data",
        "distance_rest",
        "distance_stiffness_values",
        "bend_distance_start",
        "bend_distance_count",
        "bend_distance_data",
        "bend_distance_rest",
        "bend_stiffness_values",
        "dihedral_pairs",
        "dihedral_rest_angles",
        "dihedral_signs",
        "volume_pairs",
        "volume_rest",
        "angle_restoration_values",
        "angle_restoration_velocity_attenuation_values",
        "angle_restoration_gravity_falloff_values",
        "angle_limit_values",
        "substep_damping_values",
        "max_distances",
        "motion_stiffness_values",
        "backstop_radii",
        "backstop_distances",
        "edges",
        "triangles",
        "collision_radii",
        "collider_types",
        "collider_group_bits",
        "collider_centers",
        "collider_segment_a",
        "collider_segment_b",
        "collider_old_centers",
        "collider_old_segment_a",
        "collider_old_segment_b",
        "collider_radii",
        "substep_old_world_positions",
        "substep_step_vectors",
        "substep_step_rotations",
        "substep_inertia_vectors",
        "substep_inertia_rotations",
        "substep_now_world_positions",
        "substep_rotation_axes",
        "substep_angular_velocities",
        "substep_velocity_weights",
    };

    Buffer buffers[kSolveBufferCount];
    for (int index = 0; index < kSolveBufferCount; ++index) {
        const int flags = index <= ADisplayPositions ? (PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND)
                                                     : (PyBUF_FORMAT | PyBUF_ND);
        if (!buffers[index].get(PyTuple_GET_ITEM(args, index), flags, names[index])) {
            return nullptr;
        }
    }

    Py_ssize_t vertex_count = 0;
    if (!expect_vector3_array(buffers[APositions], "positions", &vertex_count) ||
        !expect_same_vertex_count(buffers[AOldPositions], "old_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[AVelocityPositions], "velocity_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[AVelocities], "velocities", vertex_count) ||
        !expect_same_vertex_count(buffers[ARealVelocities], "real_velocities", vertex_count) ||
        !expect_same_vertex_count(buffers[ACollisionNormals], "collision_normals", vertex_count) ||
        !expect_same_vertex_count(buffers[AStepBasicPositions], "step_basic_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ADisplayPositions], "display_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ABasePositions], "base_positions", vertex_count) ||
        !expect_same_vertex_count(buffers[ABaseNormals], "base_normals", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[AStepBasicRotations], "step_basic_rotations", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[ABaseRotations], "base_rotations", vertex_count) ||
        !expect_same_vertex_count(buffers[AVertexLocalPositions], "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(buffers[AVertexLocalRotations], "vertex_local_rotations", vertex_count)) {
        return nullptr;
    }

    if (!expect_float32(buffers[AFriction], "friction") ||
        !expect_1d_array(buffers[AFriction], "friction", vertex_count) ||
        !expect_float32(buffers[AStaticFriction], "static_friction") ||
        !expect_1d_array(buffers[AStaticFriction], "static_friction", vertex_count) ||
        !expect_float32(buffers[AInvMasses], "inv_masses") ||
        !expect_1d_array(buffers[AInvMasses], "inv_masses", vertex_count) ||
        !expect_uint8_scalar_array(buffers[AAttributes], "attributes") ||
        !expect_1d_array(buffers[AAttributes], "attributes", vertex_count) ||
        !expect_float32(buffers[ADepths], "depths") ||
        !expect_1d_array(buffers[ADepths], "depths", vertex_count) ||
        !expect_int32_scalar_array(buffers[ARootIndices], "root_indices") ||
        !expect_1d_array(buffers[ARootIndices], "root_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(buffers[ARootIndices], "root_indices", vertex_count) ||
        !expect_float32(buffers[ATetherRestLengths], "tether_rest_lengths") ||
        !expect_1d_array(buffers[ATetherRestLengths], "tether_rest_lengths", vertex_count) ||
        !expect_int32_scalar_array(buffers[AParentIndices], "parent_indices") ||
        !expect_1d_array(buffers[AParentIndices], "parent_indices", vertex_count) ||
        !expect_root_indices_or_minus_one(buffers[AParentIndices], "parent_indices", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ABaselineStart], "baseline_start") ||
        !expect_int32_scalar_array(buffers[ABaselineCount], "baseline_count") ||
        !expect_int32_scalar_array(buffers[ABaselineData], "baseline_data") ||
        !expect_indices_in_range(buffers[ABaselineData], "baseline_data", vertex_count)) {
        return nullptr;
    }
    const Py_ssize_t line_count = buffers[ABaselineStart].view.shape[0];
    if (!expect_1d_array(buffers[ABaselineCount], "baseline_count", line_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ADistanceStart], "distance_start") ||
        !expect_1d_array(buffers[ADistanceStart], "distance_start", vertex_count) ||
        !expect_int32_scalar_array(buffers[ADistanceCount], "distance_count") ||
        !expect_1d_array(buffers[ADistanceCount], "distance_count", vertex_count) ||
        !expect_int32_scalar_array(buffers[ADistanceData], "distance_data") ||
        !expect_indices_in_range(buffers[ADistanceData], "distance_data", vertex_count) ||
        !expect_float32(buffers[ADistanceRest], "distance_rest") ||
        !expect_1d_array(buffers[ADistanceRest], "distance_rest", buffers[ADistanceData].view.shape[0]) ||
        !expect_float32(buffers[ADistanceStiffnessValues], "distance_stiffness_values") ||
        !expect_1d_array(buffers[ADistanceStiffnessValues], "distance_stiffness_values", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[ABendDistanceStart], "bend_distance_start") ||
        !expect_1d_array(buffers[ABendDistanceStart], "bend_distance_start", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceCount], "bend_distance_count") ||
        !expect_1d_array(buffers[ABendDistanceCount], "bend_distance_count", vertex_count) ||
        !expect_int32_scalar_array(buffers[ABendDistanceData], "bend_distance_data") ||
        !expect_indices_in_range(buffers[ABendDistanceData], "bend_distance_data", vertex_count) ||
        !expect_float32(buffers[ABendDistanceRest], "bend_distance_rest") ||
        !expect_1d_array(buffers[ABendDistanceRest], "bend_distance_rest", buffers[ABendDistanceData].view.shape[0]) ||
        !expect_float32(buffers[ABendStiffnessValues], "bend_stiffness_values") ||
        !expect_1d_array(buffers[ABendStiffnessValues], "bend_stiffness_values", vertex_count)) {
        return nullptr;
    }

    Py_ssize_t dihedral_count = 0;
    Py_ssize_t volume_count = 0;
    if (!expect_int32_quad_array(buffers[ADihedralPairs], "dihedral_pairs", &dihedral_count) ||
        !expect_float32(buffers[ADihedralRestAngles], "dihedral_rest_angles") ||
        !expect_1d_array(buffers[ADihedralRestAngles], "dihedral_rest_angles", dihedral_count) ||
        !expect_int32_scalar_array(buffers[ADihedralSigns], "dihedral_signs") ||
        !expect_1d_array(buffers[ADihedralSigns], "dihedral_signs", dihedral_count) ||
        !expect_int32_quad_array(buffers[AVolumePairs], "volume_pairs", &volume_count) ||
        !expect_float32(buffers[AVolumeRest], "volume_rest") ||
        !expect_1d_array(buffers[AVolumeRest], "volume_rest", volume_count)) {
        return nullptr;
    }
    if ((dihedral_count > 0 && !expect_quad_indices_in_range(buffers[ADihedralPairs], "dihedral_pairs", vertex_count)) ||
        (volume_count > 0 && !expect_quad_indices_in_range(buffers[AVolumePairs], "volume_pairs", vertex_count))) {
        return nullptr;
    }

    Py_ssize_t edge_count = 0;
    Py_ssize_t triangle_count = 0;
    if (!expect_float32(buffers[AAngleRestorationValues], "angle_restoration_values") ||
        !expect_1d_array(buffers[AAngleRestorationValues], "angle_restoration_values", vertex_count) ||
        !expect_float32(buffers[AAngleRestorationVelocityAttenuationValues],
                        "angle_restoration_velocity_attenuation_values") ||
        !expect_1d_array(buffers[AAngleRestorationVelocityAttenuationValues],
                         "angle_restoration_velocity_attenuation_values", vertex_count) ||
        !expect_float32(buffers[AAngleRestorationGravityFalloffValues],
                        "angle_restoration_gravity_falloff_values") ||
        !expect_1d_array(buffers[AAngleRestorationGravityFalloffValues],
                         "angle_restoration_gravity_falloff_values", vertex_count) ||
        !expect_float32(buffers[AAngleLimitValues], "angle_limit_values") ||
        !expect_1d_array(buffers[AAngleLimitValues], "angle_limit_values", vertex_count) ||
        !expect_float32(buffers[ASubstepDampingValues], "substep_damping_values") ||
        !expect_1d_array(buffers[ASubstepDampingValues], "substep_damping_values", vertex_count) ||
        !expect_float32(buffers[AMaxDistances], "max_distances") ||
        !expect_1d_array(buffers[AMaxDistances], "max_distances", vertex_count) ||
        !expect_float32(buffers[AMotionStiffnessValues], "motion_stiffness_values") ||
        !expect_1d_array(buffers[AMotionStiffnessValues], "motion_stiffness_values", vertex_count) ||
        !expect_float32(buffers[ABackstopRadii], "backstop_radii") ||
        !expect_1d_array(buffers[ABackstopRadii], "backstop_radii", vertex_count) ||
        !expect_float32(buffers[ABackstopDistances], "backstop_distances") ||
        !expect_1d_array(buffers[ABackstopDistances], "backstop_distances", vertex_count) ||
        !expect_int32_pair_array(buffers[AEdges], "edges", &edge_count) ||
        !expect_pair_indices_in_range(buffers[AEdges], "edges", vertex_count) ||
        !expect_int32_triple_array(buffers[ATriangles], "triangles", &triangle_count) ||
        !expect_triple_indices_in_range(buffers[ATriangles], "triangles", vertex_count) ||
        !expect_float32(buffers[ACollisionRadii], "collision_radii") ||
        !expect_1d_array(buffers[ACollisionRadii], "collision_radii", vertex_count)) {
        return nullptr;
    }

    if (!expect_int32_scalar_array(buffers[AColliderTypes], "collider_types") ||
        !expect_int32_scalar_array(buffers[AColliderGroupBits], "collider_group_bits") ||
        !expect_float32(buffers[AColliderRadii], "collider_radii")) {
        return nullptr;
    }
    const Py_ssize_t collider_count = buffers[AColliderTypes].view.shape[0];
    Py_ssize_t collider_centers_count = 0;
    Py_ssize_t collider_segment_a_count = 0;
    Py_ssize_t collider_segment_b_count = 0;
    Py_ssize_t collider_old_centers_count = 0;
    Py_ssize_t collider_old_segment_a_count = 0;
    Py_ssize_t collider_old_segment_b_count = 0;
    if (!expect_1d_array(buffers[AColliderGroupBits], "collider_group_bits", collider_count) ||
        !expect_1d_array(buffers[AColliderRadii], "collider_radii", collider_count) ||
        !expect_vector3_array(buffers[AColliderCenters], "collider_centers", &collider_centers_count) ||
        !expect_vector3_array(buffers[AColliderSegmentA], "collider_segment_a", &collider_segment_a_count) ||
        !expect_vector3_array(buffers[AColliderSegmentB], "collider_segment_b", &collider_segment_b_count) ||
        !expect_vector3_array(buffers[AColliderOldCenters], "collider_old_centers", &collider_old_centers_count) ||
        !expect_vector3_array(buffers[AColliderOldSegmentA], "collider_old_segment_a",
                              &collider_old_segment_a_count) ||
        !expect_vector3_array(buffers[AColliderOldSegmentB], "collider_old_segment_b",
                              &collider_old_segment_b_count)) {
        return nullptr;
    }
    if (collider_centers_count != collider_count || collider_segment_a_count != collider_count ||
        collider_segment_b_count != collider_count || collider_old_centers_count != collider_count ||
        collider_old_segment_a_count != collider_count || collider_old_segment_b_count != collider_count) {
        PyErr_SetString(PyExc_ValueError, "collider array length mismatch");
        return nullptr;
    }

    constexpr Py_ssize_t kScalarStart = kSolveBufferCount;
    const double frame_dt = as_double(PyTuple_GET_ITEM(args, kScalarStart + 0), "frame_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double step_dt = as_double(PyTuple_GET_ITEM(args, kScalarStart + 1), "step_dt");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long raw_substeps = as_long(PyTuple_GET_ITEM(args, kScalarStart + 2), "substeps");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long raw_iterations = as_long(PyTuple_GET_ITEM(args, kScalarStart + 3), "iterations");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    Buffer gravity;
    if (!gravity.get(PyTuple_GET_ITEM(args, kScalarStart + 4), PyBUF_FORMAT | PyBUF_ND, "gravity") ||
        !expect_float32(gravity, "gravity") ||
        !expect_1d_array(gravity, "gravity", 3)) {
        return nullptr;
    }
    const int substeps = std::max(1, std::min(16, static_cast<int>(raw_substeps)));
    Py_ssize_t substep_vec_count = 0;
    Py_ssize_t substep_quat_count = 0;
    if (!expect_vector3_array(buffers[ASubstepOldWorldPositions], "substep_old_world_positions", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector3_array(buffers[ASubstepStepVectors], "substep_step_vectors", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector4_array(buffers[ASubstepStepRotations], "substep_step_rotations", &substep_quat_count) ||
        substep_quat_count != substeps ||
        !expect_vector3_array(buffers[ASubstepInertiaVectors], "substep_inertia_vectors", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector4_array(buffers[ASubstepInertiaRotations], "substep_inertia_rotations", &substep_quat_count) ||
        substep_quat_count != substeps ||
        !expect_vector3_array(buffers[ASubstepNowWorldPositions], "substep_now_world_positions", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_vector3_array(buffers[ASubstepRotationAxes], "substep_rotation_axes", &substep_vec_count) ||
        substep_vec_count != substeps ||
        !expect_float32(buffers[ASubstepAngularVelocities], "substep_angular_velocities") ||
        !expect_1d_array(buffers[ASubstepAngularVelocities], "substep_angular_velocities", substeps) ||
        !expect_float32(buffers[ASubstepVelocityWeights], "substep_velocity_weights") ||
        !expect_1d_array(buffers[ASubstepVelocityWeights], "substep_velocity_weights", substeps)) {
        PyErr_SetString(PyExc_ValueError, "substep inertia array length mismatch");
        return nullptr;
    }

    const double depth_inertia = as_double(PyTuple_GET_ITEM(args, kScalarStart + 5), "depth_inertia");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double centrifugal = as_double(PyTuple_GET_ITEM(args, kScalarStart + 6), "centrifugal");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const bool use_tether = PyObject_IsTrue(PyTuple_GET_ITEM(args, kScalarStart + 7)) == 1;
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double tether_compression = as_double(PyTuple_GET_ITEM(args, kScalarStart + 8), "tether_compression");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double tether_stretch = as_double(PyTuple_GET_ITEM(args, kScalarStart + 9), "tether_stretch");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double dynamic_friction = as_double(PyTuple_GET_ITEM(args, kScalarStart + 10), "dynamic_friction");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double static_friction_speed = as_double(PyTuple_GET_ITEM(args, kScalarStart + 11), "static_friction_speed");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double particle_speed_limit = as_double(PyTuple_GET_ITEM(args, kScalarStart + 12), "particle_speed_limit");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double angle_limit_stiffness =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 13), "angle_limit_stiffness");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long normal_axis = as_long(PyTuple_GET_ITEM(args, kScalarStart + 14), "normal_axis");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long collided_by_groups = as_long(PyTuple_GET_ITEM(args, kScalarStart + 15), "collided_by_groups");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const long collider_collision_mode =
        as_long(PyTuple_GET_ITEM(args, kScalarStart + 16), "collider_collision_mode");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double display_max_distance_ratio =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 17), "display_max_distance_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double animation_pose_ratio = as_double(PyTuple_GET_ITEM(args, kScalarStart + 18), "animation_pose_ratio");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double blend_weight = as_double(PyTuple_GET_ITEM(args, kScalarStart + 19), "blend_weight");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const bool self_collision_enabled = PyObject_IsTrue(PyTuple_GET_ITEM(args, kScalarStart + 20)) == 1;
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double self_collision_surface_thickness =
        as_double(PyTuple_GET_ITEM(args, kScalarStart + 21), "self_collision_surface_thickness");
    if (PyErr_Occurred()) {
        return nullptr;
    }
    const double self_collision_mass = as_double(PyTuple_GET_ITEM(args, kScalarStart + 22), "self_collision_mass");
    if (PyErr_Occurred()) {
        return nullptr;
    }

    hotools::Mc2MeshClothSolveView view;
    view.positions = static_cast<float*>(buffers[APositions].view.buf);
    view.old_positions = static_cast<float*>(buffers[AOldPositions].view.buf);
    view.velocity_positions = static_cast<float*>(buffers[AVelocityPositions].view.buf);
    view.velocities = static_cast<float*>(buffers[AVelocities].view.buf);
    view.real_velocities = static_cast<float*>(buffers[ARealVelocities].view.buf);
    view.friction = static_cast<float*>(buffers[AFriction].view.buf);
    view.static_friction = static_cast<float*>(buffers[AStaticFriction].view.buf);
    view.collision_normals = static_cast<float*>(buffers[ACollisionNormals].view.buf);
    view.inv_masses = static_cast<float*>(buffers[AInvMasses].view.buf);
    view.step_basic_positions = static_cast<float*>(buffers[AStepBasicPositions].view.buf);
    view.step_basic_rotations = static_cast<float*>(buffers[AStepBasicRotations].view.buf);
    view.display_positions = static_cast<float*>(buffers[ADisplayPositions].view.buf);
    view.base_positions = static_cast<const float*>(buffers[ABasePositions].view.buf);
    view.base_normals = static_cast<const float*>(buffers[ABaseNormals].view.buf);
    view.base_rotations = static_cast<const float*>(buffers[ABaseRotations].view.buf);
    view.attributes = static_cast<const std::uint8_t*>(buffers[AAttributes].view.buf);
    view.depths = static_cast<const float*>(buffers[ADepths].view.buf);
    view.root_indices = static_cast<const std::int32_t*>(buffers[ARootIndices].view.buf);
    view.tether_rest_lengths = static_cast<const float*>(buffers[ATetherRestLengths].view.buf);
    view.parent_indices = static_cast<const std::int32_t*>(buffers[AParentIndices].view.buf);
    view.baseline_start = static_cast<const std::int32_t*>(buffers[ABaselineStart].view.buf);
    view.baseline_count = static_cast<const std::int32_t*>(buffers[ABaselineCount].view.buf);
    view.baseline_data = static_cast<const std::int32_t*>(buffers[ABaselineData].view.buf);
    view.vertex_local_positions = static_cast<const float*>(buffers[AVertexLocalPositions].view.buf);
    view.vertex_local_rotations = static_cast<const float*>(buffers[AVertexLocalRotations].view.buf);
    view.distance_start = static_cast<const std::int32_t*>(buffers[ADistanceStart].view.buf);
    view.distance_count = static_cast<const std::int32_t*>(buffers[ADistanceCount].view.buf);
    view.distance_data = static_cast<const std::int32_t*>(buffers[ADistanceData].view.buf);
    view.distance_rest = static_cast<const float*>(buffers[ADistanceRest].view.buf);
    view.distance_stiffness_values = static_cast<const float*>(buffers[ADistanceStiffnessValues].view.buf);
    view.bend_distance_start = static_cast<const std::int32_t*>(buffers[ABendDistanceStart].view.buf);
    view.bend_distance_count = static_cast<const std::int32_t*>(buffers[ABendDistanceCount].view.buf);
    view.bend_distance_data = static_cast<const std::int32_t*>(buffers[ABendDistanceData].view.buf);
    view.bend_distance_rest = static_cast<const float*>(buffers[ABendDistanceRest].view.buf);
    view.bend_stiffness_values = static_cast<const float*>(buffers[ABendStiffnessValues].view.buf);
    view.dihedral_pairs = static_cast<const std::int32_t*>(buffers[ADihedralPairs].view.buf);
    view.dihedral_rest_angles = static_cast<const float*>(buffers[ADihedralRestAngles].view.buf);
    view.dihedral_signs = static_cast<const std::int32_t*>(buffers[ADihedralSigns].view.buf);
    view.volume_pairs = static_cast<const std::int32_t*>(buffers[AVolumePairs].view.buf);
    view.volume_rest = static_cast<const float*>(buffers[AVolumeRest].view.buf);
    view.angle_restoration_values = static_cast<const float*>(buffers[AAngleRestorationValues].view.buf);
    view.angle_restoration_velocity_attenuation_values =
        static_cast<const float*>(buffers[AAngleRestorationVelocityAttenuationValues].view.buf);
    view.angle_restoration_gravity_falloff_values =
        static_cast<const float*>(buffers[AAngleRestorationGravityFalloffValues].view.buf);
    view.angle_limit_values = static_cast<const float*>(buffers[AAngleLimitValues].view.buf);
    view.substep_damping_values = static_cast<const float*>(buffers[ASubstepDampingValues].view.buf);
    view.max_distances = static_cast<const float*>(buffers[AMaxDistances].view.buf);
    view.motion_stiffness_values = static_cast<const float*>(buffers[AMotionStiffnessValues].view.buf);
    view.backstop_radii = static_cast<const float*>(buffers[ABackstopRadii].view.buf);
    view.backstop_distances = static_cast<const float*>(buffers[ABackstopDistances].view.buf);
    view.edges = static_cast<const std::int32_t*>(buffers[AEdges].view.buf);
    view.triangles = static_cast<const std::int32_t*>(buffers[ATriangles].view.buf);
    view.collision_radii = static_cast<const float*>(buffers[ACollisionRadii].view.buf);
    view.collider_types = static_cast<const std::int32_t*>(buffers[AColliderTypes].view.buf);
    view.collider_group_bits = static_cast<const std::int32_t*>(buffers[AColliderGroupBits].view.buf);
    view.collider_centers = static_cast<const float*>(buffers[AColliderCenters].view.buf);
    view.collider_segment_a = static_cast<const float*>(buffers[AColliderSegmentA].view.buf);
    view.collider_segment_b = static_cast<const float*>(buffers[AColliderSegmentB].view.buf);
    view.collider_old_centers = static_cast<const float*>(buffers[AColliderOldCenters].view.buf);
    view.collider_old_segment_a = static_cast<const float*>(buffers[AColliderOldSegmentA].view.buf);
    view.collider_old_segment_b = static_cast<const float*>(buffers[AColliderOldSegmentB].view.buf);
    view.collider_radii = static_cast<const float*>(buffers[AColliderRadii].view.buf);
    view.substep_old_world_positions = static_cast<const float*>(buffers[ASubstepOldWorldPositions].view.buf);
    view.substep_step_vectors = static_cast<const float*>(buffers[ASubstepStepVectors].view.buf);
    view.substep_step_rotations = static_cast<const float*>(buffers[ASubstepStepRotations].view.buf);
    view.substep_inertia_vectors = static_cast<const float*>(buffers[ASubstepInertiaVectors].view.buf);
    view.substep_inertia_rotations = static_cast<const float*>(buffers[ASubstepInertiaRotations].view.buf);
    view.substep_now_world_positions = static_cast<const float*>(buffers[ASubstepNowWorldPositions].view.buf);
    view.substep_rotation_axes = static_cast<const float*>(buffers[ASubstepRotationAxes].view.buf);
    view.substep_angular_velocities = static_cast<const float*>(buffers[ASubstepAngularVelocities].view.buf);
    view.substep_velocity_weights = static_cast<const float*>(buffers[ASubstepVelocityWeights].view.buf);
    view.vertex_count = static_cast<std::int64_t>(vertex_count);
    view.line_count = static_cast<std::int64_t>(line_count);
    view.baseline_data_count = static_cast<std::int64_t>(buffers[ABaselineData].view.shape[0]);
    view.distance_count_total = static_cast<std::int64_t>(buffers[ADistanceData].view.shape[0]);
    view.bend_distance_count_total = static_cast<std::int64_t>(buffers[ABendDistanceData].view.shape[0]);
    view.edge_count = static_cast<std::int64_t>(edge_count);
    view.triangle_count = static_cast<std::int64_t>(triangle_count);
    view.dihedral_count = static_cast<std::int64_t>(dihedral_count);
    view.volume_count = static_cast<std::int64_t>(volume_count);
    view.collider_count = static_cast<std::int64_t>(collider_count);
    view.substeps = substeps;
    view.iterations = std::max(0, std::min(64, static_cast<int>(raw_iterations)));
    view.frame_dt = static_cast<float>(frame_dt);
    view.step_dt = static_cast<float>(step_dt);
    const float* gravity_values = static_cast<const float*>(gravity.view.buf);
    view.gravity[0] = gravity_values[0];
    view.gravity[1] = gravity_values[1];
    view.gravity[2] = gravity_values[2];
    view.depth_inertia = static_cast<float>(depth_inertia);
    view.centrifugal = static_cast<float>(centrifugal);
    view.use_tether = use_tether;
    view.tether_compression = static_cast<float>(tether_compression);
    view.tether_stretch = static_cast<float>(tether_stretch);
    view.dynamic_friction = static_cast<float>(dynamic_friction);
    view.static_friction_speed = static_cast<float>(static_friction_speed);
    view.particle_speed_limit = static_cast<float>(particle_speed_limit);
    view.angle_limit_stiffness = static_cast<float>(angle_limit_stiffness);
    view.normal_axis = std::max(0, std::min(5, static_cast<int>(normal_axis)));
    view.display_max_distance_ratio = static_cast<float>(display_max_distance_ratio);
    view.animation_pose_ratio = static_cast<float>(animation_pose_ratio);
    view.blend_weight = static_cast<float>(blend_weight);
    view.collided_by_groups = static_cast<std::int32_t>(collided_by_groups);
    view.collider_collision_mode = std::max(0, std::min(2, static_cast<int>(collider_collision_mode)));
    view.self_collision_enabled = self_collision_enabled;
    view.self_collision_surface_thickness = static_cast<float>(self_collision_surface_thickness);
    view.self_collision_mass = static_cast<float>(self_collision_mass);

    hotools::solve_meshcloth_mc2(view);
    Py_RETURN_NONE;
}

// ---------------------------------------------------------------------------
// BoneCloth IO 绑定：solve_mc2_bonecloth_io
// ---------------------------------------------------------------------------
// 参数顺序（15个）：
//   world_rotations(rw), display_positions, base_positions, base_rotations,
//   vertex_local_positions, vertex_local_rotations,
//   parent_indices, baseline_start, baseline_count, baseline_data, attributes,
//   rotational_interpolation, blend_weight, anime_ratio, root_rotation
PyObject* solve_mc2_bonecloth_io_object(
    PyObject* world_rotations_object,
    PyObject* display_positions_object,
    PyObject* base_positions_object,
    PyObject* base_rotations_object,
    PyObject* vertex_local_positions_object,
    PyObject* vertex_local_rotations_object,
    PyObject* parent_indices_object,
    PyObject* baseline_start_object,
    PyObject* baseline_count_object,
    PyObject* baseline_data_object,
    PyObject* attributes_object,
    double rot_interp,
    double blend_w,
    double anime_r,
    double root_rot) {
    Buffer world_rotations;
    Buffer display_positions;
    Buffer base_positions;
    Buffer base_rotations;
    Buffer vertex_local_positions;
    Buffer vertex_local_rotations;
    Buffer parent_indices;
    Buffer baseline_start;
    Buffer baseline_count;
    Buffer baseline_data;
    Buffer attributes;

    if (!world_rotations.get(world_rotations_object,
            PyBUF_WRITABLE | PyBUF_FORMAT | PyBUF_ND, "world_rotations") ||
        !display_positions.get(display_positions_object,
            PyBUF_FORMAT | PyBUF_ND, "display_positions") ||
        !base_positions.get(base_positions_object,
            PyBUF_FORMAT | PyBUF_ND, "base_positions") ||
        !base_rotations.get(base_rotations_object,
            PyBUF_FORMAT | PyBUF_ND, "base_rotations") ||
        !vertex_local_positions.get(vertex_local_positions_object,
            PyBUF_FORMAT | PyBUF_ND, "vertex_local_positions") ||
        !vertex_local_rotations.get(vertex_local_rotations_object,
            PyBUF_FORMAT | PyBUF_ND, "vertex_local_rotations") ||
        !parent_indices.get(parent_indices_object,
            PyBUF_FORMAT | PyBUF_ND, "parent_indices") ||
        !baseline_start.get(baseline_start_object,
            PyBUF_FORMAT | PyBUF_ND, "baseline_start") ||
        !baseline_count.get(baseline_count_object,
            PyBUF_FORMAT | PyBUF_ND, "baseline_count") ||
        !baseline_data.get(baseline_data_object,
            PyBUF_FORMAT | PyBUF_ND, "baseline_data") ||
        !attributes.get(attributes_object,
            PyBUF_FORMAT | PyBUF_ND, "attributes")) {
        return nullptr;
    }

    // 形状校验
    Py_ssize_t vertex_count = 0;
    if (!expect_vector4_array(world_rotations, "world_rotations", &vertex_count) ||
        !expect_same_vertex_count(display_positions, "display_positions", vertex_count) ||
        !expect_same_vertex_count(base_positions, "base_positions", vertex_count) ||
        !expect_same_quat_vertex_count(base_rotations, "base_rotations", vertex_count) ||
        !expect_same_vertex_count(vertex_local_positions, "vertex_local_positions", vertex_count) ||
        !expect_same_quat_vertex_count(vertex_local_rotations, "vertex_local_rotations", vertex_count) ||
        !expect_int32(parent_indices, "parent_indices") ||
        !expect_1d_array(parent_indices, "parent_indices", vertex_count) ||
        !expect_int32(baseline_start, "baseline_start") ||
        !expect_int32_scalar_array(baseline_start, "baseline_start") ||
        !expect_int32(baseline_count, "baseline_count") ||
        !expect_int32_scalar_array(baseline_count, "baseline_count") ||
        !expect_int32(baseline_data, "baseline_data") ||
        !expect_int32_scalar_array(baseline_data, "baseline_data") ||
        !expect_uint8(attributes, "attributes") ||
        !expect_1d_array(attributes, "attributes", vertex_count)) {
        return nullptr;
    }

    // baseline_start 和 baseline_count 必须等长
    const Py_ssize_t baseline_lines = baseline_start.view.shape[0];
    if (baseline_count.view.shape[0] != baseline_lines) {
        PyErr_SetString(PyExc_ValueError,
            "baseline_start and baseline_count must have the same length");
        return nullptr;
    }

    hotools::BoneClothIoView view;
    view.world_rotations         = static_cast<float*>(world_rotations.view.buf);
    view.display_positions       = static_cast<const float*>(display_positions.view.buf);
    view.base_positions          = static_cast<const float*>(base_positions.view.buf);
    view.base_rotations          = static_cast<const float*>(base_rotations.view.buf);
    view.vertex_local_positions  = static_cast<const float*>(vertex_local_positions.view.buf);
    view.vertex_local_rotations  = static_cast<const float*>(vertex_local_rotations.view.buf);
    view.parent_indices          = static_cast<const std::int32_t*>(parent_indices.view.buf);
    view.baseline_start          = static_cast<const std::int32_t*>(baseline_start.view.buf);
    view.baseline_count          = static_cast<const std::int32_t*>(baseline_count.view.buf);
    view.baseline_data           = static_cast<const std::int32_t*>(baseline_data.view.buf);
    view.attributes              = static_cast<const std::uint8_t*>(attributes.view.buf);
    view.rotational_interpolation = static_cast<float>(rot_interp);
    view.blend_weight             = static_cast<float>(blend_w);
    view.anime_ratio              = static_cast<float>(anime_r);
    view.root_rotation            = static_cast<float>(root_rot);
    view.vertex_count             = static_cast<std::int64_t>(vertex_count);
    view.baseline_lines           = static_cast<std::int64_t>(baseline_lines);
    view.baseline_total           = static_cast<std::int64_t>(baseline_data.view.shape[0]);

    hotools::solve_bonecloth_io(view);
    Py_RETURN_NONE;
}

}  // namespace

NB_MODULE(hotools_native, m) {
    m.doc() = "Native acceleration backend for HoTools (nanobind module shell).";

    // ---- 属性曲线 ----
    m.def("compile_property_float_curve",
        [](nb::object p) { return steal_or_throw(hotools::compile_property_float_curve_object(p.ptr())); },
        nb::arg("payload"), "Compile a float curve payload into a native capsule.");
    m.def("compile_property_color_curve",
        [](nb::object p) { return steal_or_throw(hotools::compile_property_color_curve_object(p.ptr())); },
        nb::arg("payload"), "Compile a color curve payload into a native capsule.");
    m.def("sample_property_float_curve",
        [](nb::object c, double pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_object(c.ptr(), pos, ext.ptr()));
        }, nb::arg("curve"), nb::arg("position"), nb::arg("extend").none(),
        "Sample a native float curve or payload at one position.");
    m.def("sample_property_color_curve",
        [](nb::object c, double pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_object(c.ptr(), pos, ext.ptr()));
        }, nb::arg("curve"), nb::arg("position"), nb::arg("extend").none(),
        "Sample a native color curve or payload at one position.");
    m.def("sample_property_float_curve_many",
        [](nb::object c, int n, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_many_object(c.ptr(), n, ext.ptr()));
        }, nb::arg("curve"), nb::arg("count"), nb::arg("extend").none(),
        "Sample a native float curve or payload at evenly spaced positions.");
    m.def("sample_property_color_curve_many",
        [](nb::object c, int n, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_many_object(c.ptr(), n, ext.ptr()));
        }, nb::arg("curve"), nb::arg("count"), nb::arg("extend").none(),
        "Sample a native color curve or payload at evenly spaced positions.");
    m.def("sample_property_float_curve_positions",
        [](nb::object c, nb::object pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_float_curve_positions_object(c.ptr(), pos.ptr(), ext.ptr()));
        }, nb::arg("curve"), nb::arg("positions"), nb::arg("extend").none(),
        "Sample a native float curve or payload at explicit positions.");
    m.def("sample_property_color_curve_positions",
        [](nb::object c, nb::object pos, nb::object ext) {
            return steal_or_throw(hotools::sample_property_color_curve_positions_object(c.ptr(), pos.ptr(), ext.ptr()));
        }, nb::arg("curve"), nb::arg("positions"), nb::arg("extend").none(),
        "Sample a native color curve or payload at explicit positions.");

    // ---- VRM spring bone ----
    m.def("solve_spring_bone_vrm_cpp",
        [](nb::args a) { call_legacy(solve_spring_bone_vrm_cpp, a); },
        "Solve one VRM spring bone chain in-place.");

    // ---- MC2 上下文管理 ----
    m.def("create_meshcloth_mc2_context",
        [](long vc, long dc, long bc, long crc) {
            return steal_or_throw(hotools::create_meshcloth_mc2_context_object(vc, dc, bc, crc));
        }, nb::arg("vertex_count"), nb::arg("distance_count"),
        nb::arg("bend_count"), nb::arg("collider_radius_count"),
        "Create an MC2 MeshCloth native context handle.");
    m.def("update_meshcloth_mc2_context_static",
        [](nb::object h, long vc, long dc, long bc, long crc) {
            PyObject* r = hotools::update_meshcloth_mc2_context_static_object(h.ptr(), vc, dc, bc, crc);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), nb::arg("vertex_count"), nb::arg("distance_count"),
        nb::arg("bend_count"), nb::arg("collider_radius_count"),
        "Update MC2 MeshCloth native context static metadata.");
    m.def("update_meshcloth_mc2_context_static_arrays",
        [](nb::args a) { call_legacy(hotools::update_meshcloth_mc2_context_static_arrays, a); },
        "Upload MC2 MeshCloth static topology arrays into a native context.");
    m.def("update_meshcloth_mc2_context_params",
        [](nb::object h, long n) {
            PyObject* r = hotools::update_meshcloth_mc2_context_params_object(h.ptr(), n);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), nb::arg("param_slot_count"),
        "Update MC2 MeshCloth native context parameter metadata.");
    m.def("update_meshcloth_mc2_context_param_arrays",
        [](nb::args a) { call_legacy(hotools::update_meshcloth_mc2_context_param_arrays, a); },
        "Upload MC2 MeshCloth parameter sample arrays into a native context.");
    m.def("meshcloth_mc2_context_info",
        [](nb::object h) { return steal_or_throw(hotools::meshcloth_mc2_context_info_object(h.ptr())); },
        nb::arg("handle"), "Return MC2 MeshCloth native context metadata.");
    m.def("free_meshcloth_mc2_context",
        [](nb::object h) {
            PyObject* r = hotools::free_meshcloth_mc2_context_object(h.ptr());
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        }, nb::arg("handle"), "Release MC2 MeshCloth native context resources.");
    // ---- MC2 单步约束求解器 ----
    m.def("project_neighbor_constraints_mc2",
        [](nb::object pos, nb::object inv, nb::object starts, nb::object counts,
           nb::object nbrs, nb::object rest, nb::object stiff, nb::object vel, double attn) {
            PyObject* r = project_neighbor_constraints_mc2_object(
                pos.ptr(), inv.ptr(), starts.ptr(), counts.ptr(),
                nbrs.ptr(), rest.ptr(), stiff.ptr(), vel.ptr(), attn);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("starts"), nb::arg("counts"),
        nb::arg("neighbors"), nb::arg("rest_lengths"), nb::arg("stiffness_values"),
        nb::arg("velocity_positions"), nb::arg("velocity_attenuation"),
        "Project MC2 neighbor constraints in-place.");
    m.def("project_tether_mc2",
        [](nb::object pos, nb::object inv, nb::object ri, nb::object rrl, nb::object vel,
           double stiff, double comp, double stretch) {
            PyObject* r = project_tether_mc2_object(
                pos.ptr(), inv.ptr(), ri.ptr(), rrl.ptr(), vel.ptr(), stiff, comp, stretch);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("root_indices"),
        nb::arg("root_rest_lengths"), nb::arg("velocity_positions"),
        nb::arg("stiffness"), nb::arg("compression"), nb::arg("stretch"),
        "Project MC2 tether constraints in-place.");
    m.def("project_motion_constraints_mc2",
        [](nb::object pos, nb::object bp, nb::object br, nb::object inv,
           nb::object md, nb::object sv, nb::object bkr, nb::object bkd, nb::object vel, int axis) {
            PyObject* r = project_motion_constraints_mc2_object(
                pos.ptr(), bp.ptr(), br.ptr(), inv.ptr(),
                md.ptr(), sv.ptr(), bkr.ptr(), bkd.ptr(), vel.ptr(), axis);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("inv_masses"), nb::arg("max_distances"), nb::arg("stiffness_values"),
        nb::arg("backstop_radii"), nb::arg("backstop_distances"),
        nb::arg("velocity_positions"), nb::arg("normal_axis"),
        "Project MC2 motion constraints in-place.");
    m.def("apply_post_step_mc2",
        [](nb::object pos, nb::object old, nb::object vp, nb::object vel,
           nb::object rvel, nb::object fric, nb::object sfric, nb::object cn,
           nb::object inv, double dt, double dfric, double sfs, double psl) {
            PyObject* r = apply_post_step_mc2_object(
                pos.ptr(), old.ptr(), vp.ptr(), vel.ptr(), rvel.ptr(),
                fric.ptr(), sfric.ptr(), cn.ptr(), inv.ptr(), dt, dfric, sfs, psl);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("old_positions"), nb::arg("velocity_positions"),
        nb::arg("velocities"), nb::arg("real_velocities"), nb::arg("friction"),
        nb::arg("static_friction"), nb::arg("collision_normals"), nb::arg("inv_masses"),
        nb::arg("step_dt"), nb::arg("dynamic_friction"),
        nb::arg("static_friction_speed"), nb::arg("particle_speed_limit"),
        "Apply MC2 post-step velocity and friction update in-place.");
    m.def("project_collisions_mc2",
        [](nb::object pos, nb::object bp, nb::object inv, nb::object cr, nb::object cn,
           nb::object fric, int cbg, nb::object ct, nb::object cgb,
           nb::object cc, nb::object csa, nb::object csb,
           nb::object coc, nb::object cosa, nb::object cosb, nb::object crad) {
            PyObject* r = project_collisions_mc2_object(
                pos.ptr(), bp.ptr(), inv.ptr(), cr.ptr(), cn.ptr(), fric.ptr(),
                cbg, ct.ptr(), cgb.ptr(), cc.ptr(), csa.ptr(), csb.ptr(),
                coc.ptr(), cosa.ptr(), cosb.ptr(), crad.ptr());
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("base_positions"), nb::arg("inv_masses"),
        nb::arg("collision_radii"), nb::arg("collision_normals"), nb::arg("friction"),
        nb::arg("collided_by_groups"), nb::arg("collider_types"), nb::arg("collider_group_bits"),
        nb::arg("collider_centers"), nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Project MC2 point collisions in-place.");
    m.def("project_edge_collisions_mc2",
        [](nb::object pos, nb::object edges, nb::object attr, nb::object inv,
           nb::object cr, nb::object cn, nb::object fric, int cbg,
           nb::object ct, nb::object cgb, nb::object cc, nb::object csa, nb::object csb,
           nb::object coc, nb::object cosa, nb::object cosb, nb::object crad) {
            PyObject* r = project_edge_collisions_mc2_object(
                pos.ptr(), edges.ptr(), attr.ptr(), inv.ptr(), cr.ptr(), cn.ptr(), fric.ptr(),
                cbg, ct.ptr(), cgb.ptr(), cc.ptr(), csa.ptr(), csb.ptr(),
                coc.ptr(), cosa.ptr(), cosb.ptr(), crad.ptr());
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("edges"), nb::arg("attributes"),
        nb::arg("inv_masses"), nb::arg("collision_radii"), nb::arg("collision_normals"),
        nb::arg("friction"), nb::arg("collided_by_groups"), nb::arg("collider_types"),
        nb::arg("collider_group_bits"), nb::arg("collider_centers"),
        nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Project MC2 edge collisions in-place.");
    m.def("project_self_collisions_mc2",
        [](nb::object pos, nb::object old, nb::object inv, nb::object edges,
           nb::object tri, nb::object attr, nb::object cn, nb::object fric, double st) {
            PyObject* r = project_self_collisions_mc2_object(
                pos.ptr(), old.ptr(), inv.ptr(), edges.ptr(), tri.ptr(),
                attr.ptr(), cn.ptr(), fric.ptr(), st);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("old_positions"), nb::arg("inv_masses"),
        nb::arg("edges"), nb::arg("triangles"), nb::arg("attributes"),
        nb::arg("collision_normals"), nb::arg("friction"), nb::arg("surface_thickness"),
        "Project MC2 self collisions in-place.");
    m.def("project_triangle_bending_mc2",
        [](nb::object pos, nb::object inv, nb::object dp, nb::object dra,
           nb::object ds, nb::object vp, nb::object vr, nb::object sv) {
            PyObject* r = project_triangle_bending_mc2_object(
                pos.ptr(), inv.ptr(), dp.ptr(), dra.ptr(), ds.ptr(), vp.ptr(), vr.ptr(), sv.ptr());
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("dihedral_pairs"),
        nb::arg("dihedral_rest_angles"), nb::arg("dihedral_signs"),
        nb::arg("volume_pairs"), nb::arg("volume_rest"), nb::arg("stiffness_values"),
        "Project MC2 triangle bending constraints in-place.");
    m.def("project_angle_constraints_mc2",
        [](nb::object pos, nb::object inv, nb::object pi, nb::object bs,
           nb::object bc, nb::object bd, nb::object sbp, nb::object sbr,
           nb::object rv, nb::object lv, nb::object vel, double rva, double rgf, double ls) {
            PyObject* r = project_angle_constraints_mc2_object(
                pos.ptr(), inv.ptr(), pi.ptr(), bs.ptr(), bc.ptr(), bd.ptr(),
                sbp.ptr(), sbr.ptr(), rv.ptr(), lv.ptr(), vel.ptr(), rva, rgf, ls);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("inv_masses"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("step_basic_positions"), nb::arg("step_basic_rotations"),
        nb::arg("restoration_values"), nb::arg("limit_values"), nb::arg("velocity_positions"),
        nb::arg("restoration_velocity_attenuation"), nb::arg("restoration_gravity_falloff"),
        nb::arg("limit_stiffness"),
        "Project MC2 angle restoration and limit constraints in-place.");
    m.def("update_step_basic_pose_mc2",
        [](nb::object bp, nb::object br, nb::object pi, nb::object bstart, nb::object bcount,
           nb::object bd, nb::object vlp, nb::object vlr, nb::object sp, nb::object sr, double apr) {
            PyObject* r = update_step_basic_pose_mc2_object(
                bp.ptr(), br.ptr(), pi.ptr(), bstart.ptr(), bcount.ptr(), bd.ptr(),
                vlp.ptr(), vlr.ptr(), sp.ptr(), sr.ptr(), apr);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("base_positions"), nb::arg("base_rotations"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("step_positions"), nb::arg("step_rotations"), nb::arg("animation_pose_ratio"),
        "Update MC2 step basic pose in-place.");
    m.def("update_base_pose_from_pose_mc2",
        [](nb::object bp, nb::object bn, nb::object pi, nb::object bstart, nb::object bcount,
           nb::object bd, nb::object vlp, nb::object vlr, nb::object br2, nb::object sp,
           nb::object sr, double apr) {
            PyObject* r = update_base_pose_from_pose_mc2_object(
                bp.ptr(), bn.ptr(), pi.ptr(), bstart.ptr(), bcount.ptr(), bd.ptr(),
                vlp.ptr(), vlr.ptr(), br2.ptr(), sp.ptr(), sr.ptr(), apr);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("base_positions"), nb::arg("base_normals"), nb::arg("parent_indices"),
        nb::arg("baseline_start"), nb::arg("baseline_count"), nb::arg("baseline_data"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("base_rotations"), nb::arg("step_positions"), nb::arg("step_rotations"),
        nb::arg("animation_pose_ratio"),
        "Update MC2 base rotations and step basic pose from BasePose positions/normals in-place.");
    m.def("apply_substep_inertia_mc2",
        [](nb::object old, nb::object vel, nb::object dep, nb::object inv,
           nb::object owp, nb::object sv, nb::object sr, nb::object iv, nb::object ir, double di) {
            PyObject* r = apply_substep_inertia_mc2_object(
                old.ptr(), vel.ptr(), dep.ptr(), inv.ptr(),
                owp.ptr(), sv.ptr(), sr.ptr(), iv.ptr(), ir.ptr(), di);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("old_positions"), nb::arg("velocities"), nb::arg("depths"),
        nb::arg("inv_masses"), nb::arg("old_world_position"), nb::arg("step_vector"),
        nb::arg("step_rotation"), nb::arg("inertia_vector"), nb::arg("inertia_rotation"),
        nb::arg("depth_inertia"),
        "Apply MC2 substep inertia in-place.");
    m.def("apply_centrifugal_velocity_mc2",
        [](nb::object pos, nb::object vel, nb::object dep, nb::object inv,
           nb::object nwp, nb::object ra, double av, double cf) {
            PyObject* r = apply_centrifugal_velocity_mc2_object(
                pos.ptr(), vel.ptr(), dep.ptr(), inv.ptr(), nwp.ptr(), ra.ptr(), av, cf);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("velocities"), nb::arg("depths"), nb::arg("inv_masses"),
        nb::arg("now_world_position"), nb::arg("rotation_axis"),
        nb::arg("angular_velocity"), nb::arg("centrifugal"),
        "Apply MC2 centrifugal velocity in-place.");
    m.def("calculate_display_positions_mc2",
        [](nb::object pos, nb::object rvel, nb::object ri, nb::object dp, double fdt, double mdr) {
            PyObject* r = calculate_display_positions_mc2_object(
                pos.ptr(), rvel.ptr(), ri.ptr(), dp.ptr(), fdt, mdr);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("positions"), nb::arg("real_velocities"), nb::arg("root_indices"),
        nb::arg("display_positions"), nb::arg("frame_dt"), nb::arg("max_distance_ratio"),
        "Calculate MC2 display future prediction in-place.");
    // ---- MC2 网格布料大函数 ----
    m.def("solve_meshcloth_mc2",
        [](nb::args a) { call_legacy(solve_meshcloth_mc2, a); },
        "Solve one MC2 MeshCloth array frame in-place.");
    m.def("solve_meshcloth_mc2_context",
        [](nb::args a) { call_legacy(hotools::solve_meshcloth_mc2_context, a); },
        "Solve one MC2 MeshCloth frame using a native context for static arrays.");
    m.def("solve_meshcloth_mc2_context_cached_params",
        [](nb::args a) { call_legacy(hotools::solve_meshcloth_mc2_context_cached_params, a); },
        "Solve one MC2 MeshCloth frame using native context static and parameter arrays.");

    // ---- 骨骼布料 IO ----
    m.def("solve_mc2_bonecloth_io",
        [](nb::object wr, nb::object dp, nb::object bp, nb::object br,
           nb::object vlp, nb::object vlr, nb::object pi, nb::object bstart,
           nb::object bc, nb::object bd, nb::object attr,
           double ri, double bw, double ar, double rr) {
            PyObject* r = solve_mc2_bonecloth_io_object(
                wr.ptr(), dp.ptr(), bp.ptr(), br.ptr(), vlp.ptr(), vlr.ptr(),
                pi.ptr(), bstart.ptr(), bc.ptr(), bd.ptr(), attr.ptr(),
                ri, bw, ar, rr);
            if (!r) throw nb::python_error();
            Py_DECREF(r);
        },
        nb::arg("world_rotations"), nb::arg("display_positions"),
        nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("vertex_local_positions"), nb::arg("vertex_local_rotations"),
        nb::arg("parent_indices"), nb::arg("baseline_start"),
        nb::arg("baseline_count"), nb::arg("baseline_data"), nb::arg("attributes"),
        nb::arg("rotational_interpolation"), nb::arg("blend_weight"),
        nb::arg("anime_ratio"), nb::arg("root_rotation"),
        "Compute MC2 BoneCloth chain-propagated world rotations in-place.");
}
