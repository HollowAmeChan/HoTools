#include "mc2_domain_cpu.hpp"
#include "mc2_kernels.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>

#include <cstdint>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace nb = nanobind;

namespace hotools {
namespace {

using cf32_2d = nb::ndarray<const float, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using cf32_3d = nb::ndarray<const float, nb::ndim<3>, nb::c_contig, nb::device::cpu>;
using cf32_1d = nb::ndarray<const float, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const std::int32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using ci32_2d = nb::ndarray<const std::int32_t, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using cu32_1d = nb::ndarray<const std::uint32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

// Every DomainV1 binding retains the Python GIL. Keep this registry GIL-serial;
// MSVC std::mutex is not safe under Blender's tbbmalloc_proxy interception.
std::unordered_set<mc2_domain_cpu::DomainV1*> live_domains;

mc2_domain_cpu::DomainV1* require_domain(std::uint64_t handle) {
    if (handle == 0) {
        throw nb::value_error("MC2 CPU domain handle is null");
    }
    auto* domain = reinterpret_cast<mc2_domain_cpu::DomainV1*>(handle);
    if (live_domains.find(domain) == live_domains.end()) {
        throw std::runtime_error("MC2 CPU domain handle is not live");
    }
    return domain;
}

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_2d(
    std::vector<T>&& values,
    std::size_t rows,
    std::size_t columns
) {
    if (values.size() != rows * columns) {
        throw nb::value_error("MC2 CPU output shape mismatch");
    }
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T>(
        owner_data->data(), {rows, columns}, owner
    );
}

template<typename T>
nb::ndarray<nb::numpy, T> owned_array_1d(std::vector<T>&& values) {
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T>(owner_data->data(), {owner_data->size()}, owner);
}

}  // namespace

void bind_mc2_domain_cpu(nb::module_& module) {
    module.def(
        "mc2_domain_cpu_v1_create",
        [](std::uint32_t schema_version,
           std::size_t particle_count,
           std::size_t partition_count,
           const std::string& domain_signature,
           const std::string& layout_signature,
           cf32_2d bind_positions,
           cf32_2d bind_rotations,
           cu32_1d particle_partition_index,
           cu32_1d particle_attribute_flags,
           cf32_2d partition_center_local_positions,
           cf32_2d partition_initial_local_gravity_directions) {
            if (static_cast<std::size_t>(bind_positions.shape(0)) != particle_count ||
                bind_positions.shape(1) != 3) {
                throw nb::value_error("bind_positions must be [particle_count,3]");
            }
            if (static_cast<std::size_t>(bind_rotations.shape(0)) != particle_count ||
                bind_rotations.shape(1) != 4) {
                throw nb::value_error("bind_rotations must be [particle_count,4]");
            }
            if (static_cast<std::size_t>(particle_partition_index.shape(0)) != particle_count ||
                static_cast<std::size_t>(particle_attribute_flags.shape(0)) != particle_count) {
                throw nb::value_error("particle metadata must match particle_count");
            }
            if (static_cast<std::size_t>(partition_center_local_positions.shape(0)) != partition_count ||
                partition_center_local_positions.shape(1) != 3 ||
                static_cast<std::size_t>(partition_initial_local_gravity_directions.shape(0)) != partition_count ||
                partition_initial_local_gravity_directions.shape(1) != 3) {
                throw nb::value_error("partition Center static arrays must be [partition_count,3]");
            }
            mc2_domain_cpu::ProgramViewV1 program {
                schema_version,
                particle_count,
                partition_count,
                bind_positions.data(),
                bind_rotations.data(),
                particle_partition_index.data(),
                particle_attribute_flags.data(),
                partition_center_local_positions.data(),
                partition_initial_local_gravity_directions.data(),
                domain_signature.c_str(),
                layout_signature.c_str(),
            };
            auto* domain = new mc2_domain_cpu::DomainV1(program);
            live_domains.insert(domain);
            return reinterpret_cast<std::uint64_t>(domain);
        },
        nb::arg("schema_version"),
        nb::arg("particle_count"),
        nb::arg("partition_count"),
        nb::arg("domain_signature"),
        nb::arg("layout_signature"),
        nb::arg("bind_positions"),
        nb::arg("bind_rotations"),
        nb::arg("particle_partition_index"),
        nb::arg("particle_attribute_flags"),
        nb::arg("partition_center_local_positions"),
        nb::arg("partition_initial_local_gravity_directions"),
        "Create an independent E3 MC2 CPU domain data-path owner."
    );
    module.def(
        "mc2_domain_cpu_v1_create_parameter_staging",
        [](std::uint64_t handle) {
            auto staging = require_domain(handle)->create_parameter_staging_domain();
            auto* staging_domain = staging.get();
            live_domains.insert(staging_domain);
            staging.release();
            return reinterpret_cast<std::uint64_t>(staging_domain);
        },
        nb::arg("handle"),
        "Create an isolated same-layout domain for atomic parameter staging."
    );
    module.def(
        "mc2_domain_cpu_v1_swap_parameter_staging",
        [](std::uint64_t handle, std::uint64_t staging_handle) {
            auto* domain = require_domain(handle);
            auto* staging = require_domain(staging_handle);
            domain->swap_parameter_configuration(*staging);
        },
        nb::arg("handle"),
        nb::arg("staging_handle"),
        "Reversibly swap staged parameter configuration with a live domain."
    );
    module.def(
        "mc2_domain_cpu_v1_update_frame",
        [](std::uint64_t handle,
           const std::string& domain_signature,
           const std::string& layout_signature,
           std::int64_t frame,
           std::int64_t generation,
           cf32_2d world_positions,
           cf32_2d world_rotations,
           cf32_2d world_normals,
           cf32_2d partition_world_positions,
           cf32_2d partition_world_rotations,
           cf32_2d partition_world_scales,
           cf32_3d partition_world_linear,
           cf32_2d anchor_world_positions,
           cf32_2d anchor_world_rotations,
           cu32_1d anchor_present,
           cu32_1d partition_frame_flags,
           cf32_1d velocity_weights,
           cf32_1d gravity_ratios,
           float frame_delta_time,
           float simulation_delta_time,
           float time_scale,
           std::int64_t skip_count,
           bool is_running) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(world_positions.shape(0)) != domain->particle_count() ||
                world_positions.shape(1) != 3 ||
                static_cast<std::size_t>(world_rotations.shape(0)) != domain->particle_count() ||
                world_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(world_normals.shape(0)) != domain->particle_count() ||
                world_normals.shape(1) != 3) {
                throw nb::value_error("MC2 CPU particle frame arrays have incompatible shapes");
            }
            const auto partition_count = domain->partition_count();
            if (static_cast<std::size_t>(partition_world_positions.shape(0)) != partition_count ||
                partition_world_positions.shape(1) != 3 ||
                static_cast<std::size_t>(partition_world_rotations.shape(0)) != partition_count ||
                partition_world_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(partition_world_scales.shape(0)) != partition_count ||
                partition_world_scales.shape(1) != 3 ||
                static_cast<std::size_t>(partition_world_linear.shape(0)) != partition_count ||
                partition_world_linear.shape(1) != 3 || partition_world_linear.shape(2) != 3 ||
                static_cast<std::size_t>(anchor_world_positions.shape(0)) != partition_count ||
                anchor_world_positions.shape(1) != 3 ||
                static_cast<std::size_t>(anchor_world_rotations.shape(0)) != partition_count ||
                anchor_world_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(anchor_present.shape(0)) != partition_count ||
                static_cast<std::size_t>(partition_frame_flags.shape(0)) != partition_count ||
                static_cast<std::size_t>(velocity_weights.shape(0)) != partition_count ||
                static_cast<std::size_t>(gravity_ratios.shape(0)) != partition_count) {
                throw nb::value_error("MC2 CPU partition frame arrays have incompatible shapes");
            }
            domain->update_frame({
                domain->particle_count(),
                partition_count,
                world_positions.data(),
                world_rotations.data(),
                world_normals.data(),
                partition_world_positions.data(),
                partition_world_rotations.data(),
                partition_world_scales.data(),
                partition_world_linear.data(),
                anchor_world_positions.data(),
                anchor_world_rotations.data(),
                anchor_present.data(),
                partition_frame_flags.data(),
                velocity_weights.data(),
                gravity_ratios.data(),
                frame,
                generation,
                domain_signature.c_str(),
                layout_signature.c_str(),
                frame_delta_time,
                simulation_delta_time,
                time_scale,
                skip_count,
                is_running,
            });
        },
        nb::arg("handle"),
        nb::arg("domain_signature"),
        nb::arg("layout_signature"),
        nb::arg("frame"),
        nb::arg("generation"),
        nb::arg("world_positions"),
        nb::arg("world_rotations"),
        nb::arg("world_normals"),
        nb::arg("partition_world_positions"),
        nb::arg("partition_world_rotations"),
        nb::arg("partition_world_scales"),
        nb::arg("partition_world_linear"),
        nb::arg("anchor_world_positions"),
        nb::arg("anchor_world_rotations"),
        nb::arg("anchor_present"),
        nb::arg("partition_frame_flags"),
        nb::arg("velocity_weights"),
        nb::arg("gravity_ratios"),
        nb::arg("frame_delta_time") = 0.0f,
        nb::arg("simulation_delta_time") = 0.0f,
        nb::arg("time_scale") = 1.0f,
        nb::arg("skip_count") = 0,
        nb::arg("is_running") = false,
        "Update one validated frame without touching Blender state."
    );
    module.def(
        "mc2_domain_cpu_v1_step",
        [](std::uint64_t handle) { require_domain(handle)->step(); },
        nb::arg("handle"),
        "Run the E3 data-path step slice."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_distance",
        [](std::uint64_t handle,
           ci32_1d starts,
           ci32_1d counts,
           ci32_1d neighbors,
           cf32_1d rest_lengths,
           cf32_1d stiffness_values,
           cf32_1d depth_values,
           cf32_1d friction_values,
           cf32_1d velocity_attenuation_values) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(starts.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(counts.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(depth_values.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(friction_values.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(velocity_attenuation_values.shape(0)) != domain->particle_count() ||
                neighbors.shape(0) != rest_lengths.shape(0) ||
                neighbors.shape(0) != stiffness_values.shape(0)) {
                throw nb::value_error("MC2 CPU distance arrays have incompatible lengths");
            }
            domain->configure_distance(
                starts.data(), counts.data(), neighbors.data(),
                rest_lengths.data(), stiffness_values.data(),
                depth_values.data(), friction_values.data(), velocity_attenuation_values.data(),
                static_cast<std::size_t>(neighbors.shape(0))
            );
        },
        nb::arg("handle"),
        nb::arg("starts"),
        nb::arg("counts"),
        nb::arg("neighbors"),
        nb::arg("rest_lengths"),
        nb::arg("stiffness_values"),
        nb::arg("depth_values"),
        nb::arg("friction_values"),
        nb::arg("velocity_attenuation_values"),
        "Configure the explicit E3 Distance kernel slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_distance",
        [](std::uint64_t handle, float simulation_power) {
            require_domain(handle)->step_distance(simulation_power);
        },
        nb::arg("handle"),
        nb::arg("simulation_power") = 1.0f,
        "Run the explicit Distance kernel slice using the existing native kernel."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_baseline",
        [](std::uint64_t handle,
           ci32_1d parent_indices,
           ci32_1d line_starts,
           ci32_1d line_counts,
           ci32_1d line_data) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(parent_indices.shape(0)) != domain->particle_count() ||
                line_starts.shape(0) != line_counts.shape(0)) {
                throw nb::value_error("MC2 CPU baseline arrays have incompatible lengths");
            }
            domain->configure_baseline(
                parent_indices.data(), line_starts.data(), line_counts.data(),
                static_cast<std::size_t>(line_starts.shape(0)), line_data.data(),
                static_cast<std::size_t>(line_data.shape(0))
            );
        },
        nb::arg("handle"), nb::arg("parent_indices"), nb::arg("line_starts"),
        nb::arg("line_counts"), nb::arg("line_data"),
        "Configure the explicit backend-neutral baseline line SoA."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_baseline_pose",
        [](std::uint64_t handle,
           cf32_2d vertex_local_positions,
           cf32_2d vertex_local_rotations) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(vertex_local_positions.shape(0)) != domain->particle_count() ||
                vertex_local_positions.shape(1) != 3 ||
                static_cast<std::size_t>(vertex_local_rotations.shape(0)) != domain->particle_count() ||
                vertex_local_rotations.shape(1) != 4) {
                throw nb::value_error(
                    "MC2 CPU baseline local pose arrays must match particle_count"
                );
            }
            domain->configure_baseline_pose(
                vertex_local_positions.data(), vertex_local_rotations.data()
            );
        },
        nb::arg("handle"), nb::arg("vertex_local_positions"),
        nb::arg("vertex_local_rotations"),
        "Configure baseline-local pose data used by the native StepBasic preparation."
    );
    module.def(
        "mc2_domain_cpu_v1_prepare_step_basic_pose",
        [](std::uint64_t handle, float animation_pose_ratio) {
            auto* domain = require_domain(handle);
            domain->prepare_step_basic_pose(animation_pose_ratio);
            nb::dict result;
            result["positions"] = owned_array_2d<float>(
                std::vector<float>(domain->step_basic_positions()),
                domain->particle_count(), 3
            );
            result["rotations"] = owned_array_2d<float>(
                std::vector<float>(domain->step_basic_rotations()),
                domain->particle_count(), 4
            );
            return result;
        },
        nb::arg("handle"), nb::arg("animation_pose_ratio") = 0.0f,
        "Prepare StepBasic positions and rotations through the native baseline kernel."
    );
    module.def(
        "mc2_domain_cpu_v1_prepare_step_basic_pose_partitioned",
        [](std::uint64_t handle, cf32_1d animation_pose_ratios) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(animation_pose_ratios.shape(0)) !=
                domain->partition_count()) {
                throw nb::value_error(
                    "MC2 CPU animation_pose_ratios must match partition_count"
                );
            }
            domain->prepare_step_basic_pose_partitioned(animation_pose_ratios.data());
            nb::dict result;
            result["positions"] = owned_array_2d<float>(
                std::vector<float>(domain->step_basic_positions()),
                domain->particle_count(), 3
            );
            result["rotations"] = owned_array_2d<float>(
                std::vector<float>(domain->step_basic_rotations()),
                domain->particle_count(), 4
            );
            return result;
        },
        nb::arg("handle"), nb::arg("animation_pose_ratios"),
        "Prepare StepBasic with one animation pose ratio per domain partition."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_tether",
        [](std::uint64_t handle, ci32_1d root_indices) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(root_indices.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU tether root_indices must match particle_count");
            }
            domain->configure_tether(root_indices.data());
        },
        nb::arg("handle"), nb::arg("root_indices"),
        "Configure the explicit E3 Tether topology slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_angle",
        [](std::uint64_t handle,
           cf32_2d step_basic_positions,
           cf32_2d step_basic_rotations,
           cf32_1d restoration_values,
           cf32_1d limit_values,
           float restoration_velocity_attenuation,
           float restoration_gravity_falloff,
           float limit_stiffness,
           bool restoration_enabled,
           bool limit_enabled) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(step_basic_positions.shape(0)) != domain->particle_count() ||
                step_basic_positions.shape(1) != 3 ||
                static_cast<std::size_t>(step_basic_rotations.shape(0)) != domain->particle_count() ||
                step_basic_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(restoration_values.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(limit_values.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU Angle arrays have incompatible shapes");
            }
            domain->step_angle(
                step_basic_positions.data(), step_basic_rotations.data(),
                restoration_values.data(), limit_values.data(),
                restoration_velocity_attenuation, restoration_gravity_falloff,
                limit_stiffness, restoration_enabled, limit_enabled
            );
        },
        nb::arg("handle"), nb::arg("step_basic_positions"), nb::arg("step_basic_rotations"),
        nb::arg("restoration_values"), nb::arg("limit_values"),
        nb::arg("restoration_velocity_attenuation"), nb::arg("restoration_gravity_falloff"),
        nb::arg("limit_stiffness"), nb::arg("restoration_enabled"), nb::arg("limit_enabled"),
        "Run the explicit native Angle restoration/limit slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_angle_partitioned",
        [](std::uint64_t handle,
           cf32_2d step_basic_positions,
           cf32_2d step_basic_rotations,
           cf32_1d restoration_values,
           cf32_1d limit_values,
           cf32_1d restoration_velocity_attenuation_values,
           cf32_1d restoration_gravity_falloff_values,
           cf32_1d limit_stiffness_values,
           cu32_1d restoration_enabled_values,
           cu32_1d limit_enabled_values) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(step_basic_positions.shape(0)) != count ||
                step_basic_positions.shape(1) != 3 ||
                static_cast<std::size_t>(step_basic_rotations.shape(0)) != count ||
                step_basic_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(restoration_values.shape(0)) != count ||
                static_cast<std::size_t>(limit_values.shape(0)) != count ||
                static_cast<std::size_t>(restoration_velocity_attenuation_values.shape(0)) != count ||
                static_cast<std::size_t>(restoration_gravity_falloff_values.shape(0)) != count ||
                static_cast<std::size_t>(limit_stiffness_values.shape(0)) != count ||
                static_cast<std::size_t>(restoration_enabled_values.shape(0)) != count ||
                static_cast<std::size_t>(limit_enabled_values.shape(0)) != count) {
                throw nb::value_error("MC2 CPU partitioned Angle arrays have incompatible shapes");
            }
            domain->step_angle_partitioned(
                step_basic_positions.data(), step_basic_rotations.data(),
                restoration_values.data(), limit_values.data(),
                restoration_velocity_attenuation_values.data(),
                restoration_gravity_falloff_values.data(), limit_stiffness_values.data(),
                restoration_enabled_values.data(), limit_enabled_values.data()
            );
        },
        nb::arg("handle"), nb::arg("step_basic_positions"), nb::arg("step_basic_rotations"),
        nb::arg("restoration_values"), nb::arg("limit_values"),
        nb::arg("restoration_velocity_attenuation_values"),
        nb::arg("restoration_gravity_falloff_values"), nb::arg("limit_stiffness_values"),
        nb::arg("restoration_enabled_values"), nb::arg("limit_enabled_values"),
        "Run Angle with per-particle parameters compiled from domain partitions."
    );
    module.def(
        "mc2_domain_cpu_v1_step_tether",
        [](std::uint64_t handle, cf32_2d step_basic_positions, float compression, float stretch) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(step_basic_positions.shape(0)) != domain->particle_count() ||
                step_basic_positions.shape(1) != 3) {
                throw nb::value_error("MC2 CPU tether StepBasic positions have incompatible shape");
            }
            domain->step_tether(step_basic_positions.data(), compression, stretch);
        },
        nb::arg("handle"), nb::arg("step_basic_positions"),
        nb::arg("compression"), nb::arg("stretch"),
        "Run the explicit Tether kernel slice using StepBasic rest lengths."
    );
    module.def(
        "mc2_domain_cpu_v1_step_tether_partitioned",
        [](std::uint64_t handle, cf32_2d step_basic_positions,
           cf32_1d compression_values, cf32_1d stretch_values) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(step_basic_positions.shape(0)) != count ||
                step_basic_positions.shape(1) != 3 ||
                static_cast<std::size_t>(compression_values.shape(0)) != count ||
                static_cast<std::size_t>(stretch_values.shape(0)) != count) {
                throw nb::value_error("MC2 CPU partitioned Tether arrays have incompatible shapes");
            }
            domain->step_tether_partitioned(
                step_basic_positions.data(), compression_values.data(), stretch_values.data()
            );
        },
        nb::arg("handle"), nb::arg("step_basic_positions"),
        nb::arg("compression_values"), nb::arg("stretch_values"),
        "Run Tether with per-particle limits compiled from domain partitions."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_bending",
        [](std::uint64_t handle,
           ci32_2d dihedral_pairs,
           cf32_1d dihedral_rest_angles,
           ci32_1d dihedral_signs,
           ci32_2d volume_pairs,
           cf32_1d volume_rest,
           cf32_1d stiffness_values) {
            auto* domain = require_domain(handle);
            if (dihedral_pairs.shape(1) != 4 || volume_pairs.shape(1) != 4 ||
                dihedral_pairs.shape(0) != dihedral_rest_angles.shape(0) ||
                dihedral_pairs.shape(0) != dihedral_signs.shape(0) ||
                volume_pairs.shape(0) != volume_rest.shape(0) ||
                static_cast<std::size_t>(stiffness_values.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU bending arrays have incompatible shapes");
            }
            domain->configure_bending(
                dihedral_pairs.data(), dihedral_rest_angles.data(), dihedral_signs.data(),
                static_cast<std::size_t>(dihedral_pairs.shape(0)), volume_pairs.data(),
                volume_rest.data(), static_cast<std::size_t>(volume_pairs.shape(0)),
                stiffness_values.data()
            );
        },
        nb::arg("handle"), nb::arg("dihedral_pairs"), nb::arg("dihedral_rest_angles"),
        nb::arg("dihedral_signs"), nb::arg("volume_pairs"), nb::arg("volume_rest"),
        nb::arg("stiffness_values"),
        "Configure the explicit Bending topology and per-particle stiffness slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_motion",
        [](std::uint64_t handle,
           cf32_2d base_positions,
           cf32_2d base_rotations,
           cf32_1d max_distances,
           cf32_1d stiffness_values,
           cf32_1d backstop_radii,
           cf32_1d backstop_distances,
           std::int32_t normal_axis,
           bool max_distance_enabled,
           bool backstop_enabled) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(base_positions.shape(0)) != count || base_positions.shape(1) != 3 ||
                static_cast<std::size_t>(base_rotations.shape(0)) != count || base_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(max_distances.shape(0)) != count ||
                static_cast<std::size_t>(stiffness_values.shape(0)) != count ||
                static_cast<std::size_t>(backstop_radii.shape(0)) != count ||
                static_cast<std::size_t>(backstop_distances.shape(0)) != count) {
                throw nb::value_error("MC2 CPU Motion arrays have incompatible shapes");
            }
            domain->step_motion(
                base_positions.data(), base_rotations.data(), max_distances.data(),
                stiffness_values.data(), backstop_radii.data(), backstop_distances.data(),
                normal_axis, max_distance_enabled, backstop_enabled
            );
        },
        nb::arg("handle"), nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("max_distances"), nb::arg("stiffness_values"), nb::arg("backstop_radii"),
        nb::arg("backstop_distances"), nb::arg("normal_axis"),
        nb::arg("max_distance_enabled"), nb::arg("backstop_enabled"),
        "Run the explicit native Motion max-distance/backstop slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_motion_partitioned",
        [](std::uint64_t handle,
           cf32_2d base_positions,
           cf32_2d base_rotations,
           cf32_1d max_distances,
           cf32_1d stiffness_values,
           cf32_1d backstop_radii,
           cf32_1d backstop_distances,
           ci32_1d normal_axis_values,
           cu32_1d max_distance_enabled_values,
           cu32_1d backstop_enabled_values) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(base_positions.shape(0)) != count || base_positions.shape(1) != 3 ||
                static_cast<std::size_t>(base_rotations.shape(0)) != count || base_rotations.shape(1) != 4 ||
                static_cast<std::size_t>(max_distances.shape(0)) != count ||
                static_cast<std::size_t>(stiffness_values.shape(0)) != count ||
                static_cast<std::size_t>(backstop_radii.shape(0)) != count ||
                static_cast<std::size_t>(backstop_distances.shape(0)) != count ||
                static_cast<std::size_t>(normal_axis_values.shape(0)) != count ||
                static_cast<std::size_t>(max_distance_enabled_values.shape(0)) != count ||
                static_cast<std::size_t>(backstop_enabled_values.shape(0)) != count) {
                throw nb::value_error("MC2 CPU partitioned Motion arrays have incompatible shapes");
            }
            domain->step_motion_partitioned(
                base_positions.data(), base_rotations.data(), max_distances.data(),
                stiffness_values.data(), backstop_radii.data(), backstop_distances.data(),
                normal_axis_values.data(), max_distance_enabled_values.data(),
                backstop_enabled_values.data()
            );
        },
        nb::arg("handle"), nb::arg("base_positions"), nb::arg("base_rotations"),
        nb::arg("max_distances"), nb::arg("stiffness_values"), nb::arg("backstop_radii"),
        nb::arg("backstop_distances"), nb::arg("normal_axis_values"),
        nb::arg("max_distance_enabled_values"), nb::arg("backstop_enabled_values"),
        "Run Motion with per-particle switches compiled from domain partitions."
    );
    module.def(
        "mc2_domain_cpu_v1_step_external_collision",
        [](std::uint64_t handle,
           cf32_2d base_positions,
           cf32_1d collision_radii,
           cf32_1d friction,
           std::int32_t collided_by_groups,
           ci32_1d collider_types,
           ci32_1d collider_group_bits,
           cf32_2d collider_centers,
           cf32_2d collider_segment_a,
           cf32_2d collider_segment_b,
           cf32_2d collider_old_centers,
           cf32_2d collider_old_segment_a,
           cf32_2d collider_old_segment_b,
           cf32_1d collider_radii) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(base_positions.shape(0)) != count || base_positions.shape(1) != 3 ||
                static_cast<std::size_t>(collision_radii.shape(0)) != count ||
                static_cast<std::size_t>(friction.shape(0)) != count ||
                collider_centers.shape(1) != 3 || collider_segment_a.shape(1) != 3 ||
                collider_segment_b.shape(1) != 3 || collider_old_centers.shape(1) != 3 ||
                collider_old_segment_a.shape(1) != 3 || collider_old_segment_b.shape(1) != 3 ||
                collider_types.shape(0) != collider_group_bits.shape(0) ||
                collider_types.shape(0) != collider_radii.shape(0) ||
                collider_centers.shape(0) != collider_types.shape(0) ||
                collider_segment_a.shape(0) != collider_types.shape(0) ||
                collider_segment_b.shape(0) != collider_types.shape(0) ||
                collider_old_centers.shape(0) != collider_types.shape(0) ||
                collider_old_segment_a.shape(0) != collider_types.shape(0) ||
                collider_old_segment_b.shape(0) != collider_types.shape(0)) {
                throw nb::value_error("MC2 CPU external collision arrays have incompatible shapes");
            }
            domain->step_external_collision(
                base_positions.data(), collision_radii.data(), friction.data(), collided_by_groups,
                collider_types.data(), collider_group_bits.data(), collider_centers.data(),
                collider_segment_a.data(), collider_segment_b.data(), collider_old_centers.data(),
                collider_old_segment_a.data(), collider_old_segment_b.data(), collider_radii.data(),
                static_cast<std::size_t>(collider_types.shape(0))
            );
        },
        nb::arg("handle"), nb::arg("base_positions"), nb::arg("collision_radii"),
        nb::arg("friction"), nb::arg("collided_by_groups"), nb::arg("collider_types"),
        nb::arg("collider_group_bits"), nb::arg("collider_centers"),
        nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Run the explicit native point external-collision slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_self_collision",
        [](std::uint64_t handle,
           cf32_2d old_positions,
           ci32_2d edges,
           ci32_2d triangles,
           cf32_1d friction,
           float surface_thickness) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(old_positions.shape(0)) != count || old_positions.shape(1) != 3 ||
                edges.shape(1) != 2 || triangles.shape(1) != 3 ||
                static_cast<std::size_t>(friction.shape(0)) != count) {
                throw nb::value_error("MC2 CPU self collision arrays have incompatible shapes");
            }
            domain->step_self_collision(
                old_positions.data(), edges.data(), static_cast<std::size_t>(edges.shape(0)),
                triangles.data(), static_cast<std::size_t>(triangles.shape(0)),
                friction.data(), surface_thickness
            );
        },
        nb::arg("handle"), nb::arg("old_positions"), nb::arg("edges"),
        nb::arg("triangles"), nb::arg("friction"), nb::arg("surface_thickness"),
        "Run the explicit native self-collision slice."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_whole_domain_self",
        [](std::uint64_t handle,
           ci32_1d points,
           ci32_2d edges,
           ci32_2d triangles,
           cu32_1d partition_self_collision_modes,
           cu32_1d partition_collision_groups,
           cu32_1d partition_collision_masks,
           cf32_1d particle_friction,
           cf32_1d particle_thickness,
           cf32_1d particle_cloth_mass) {
            auto* domain = require_domain(handle);
            const auto particle_count = domain->particle_count();
            const auto partition_count = domain->partition_count();
            if (edges.shape(1) != 2 || triangles.shape(1) != 3 ||
                static_cast<std::size_t>(partition_self_collision_modes.shape(0)) != partition_count ||
                static_cast<std::size_t>(partition_collision_groups.shape(0)) != partition_count ||
                static_cast<std::size_t>(partition_collision_masks.shape(0)) != partition_count ||
                static_cast<std::size_t>(particle_friction.shape(0)) != particle_count ||
                static_cast<std::size_t>(particle_thickness.shape(0)) != particle_count ||
                static_cast<std::size_t>(particle_cloth_mass.shape(0)) != particle_count) {
                throw nb::value_error(
                    "MC2 whole-domain self configuration arrays have incompatible shapes"
                );
            }
            domain->configure_whole_domain_self(
                points.data(), static_cast<std::size_t>(points.shape(0)),
                edges.data(), static_cast<std::size_t>(edges.shape(0)),
                triangles.data(), static_cast<std::size_t>(triangles.shape(0)),
                partition_self_collision_modes.data(), partition_collision_groups.data(),
                partition_collision_masks.data(), particle_friction.data(),
                particle_thickness.data(), particle_cloth_mass.data()
            );
        },
        nb::arg("handle"), nb::arg("points"), nb::arg("edges"), nb::arg("triangles"),
        nb::arg("partition_self_collision_modes"),
        nb::arg("partition_collision_groups"), nb::arg("partition_collision_masks"),
        nb::arg("particle_friction"), nb::arg("particle_thickness"),
        nb::arg("particle_cloth_mass"),
        "Configure the compiled whole-domain self-collision pass."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_whole_domain_self",
        [](std::uint64_t handle,
           ci32_1d points,
           ci32_2d edges,
           ci32_2d triangles,
           cu32_1d partition_self_collision_modes,
           cu32_1d partition_collision_groups,
           cu32_1d partition_collision_masks,
           cf32_1d particle_friction,
           cf32_1d particle_thickness) {
            auto* domain = require_domain(handle);
            const auto particle_count = domain->particle_count();
            const auto partition_count = domain->partition_count();
            if (edges.shape(1) != 2 || triangles.shape(1) != 3 ||
                static_cast<std::size_t>(partition_self_collision_modes.shape(0)) != partition_count ||
                static_cast<std::size_t>(partition_collision_groups.shape(0)) != partition_count ||
                static_cast<std::size_t>(partition_collision_masks.shape(0)) != partition_count ||
                static_cast<std::size_t>(particle_friction.shape(0)) != particle_count ||
                static_cast<std::size_t>(particle_thickness.shape(0)) != particle_count) {
                throw nb::value_error(
                    "MC2 whole-domain self configuration arrays have incompatible shapes"
                );
            }
            std::vector<float> particle_cloth_mass(particle_count, 0.0f);
            domain->configure_whole_domain_self(
                points.data(), static_cast<std::size_t>(points.shape(0)),
                edges.data(), static_cast<std::size_t>(edges.shape(0)),
                triangles.data(), static_cast<std::size_t>(triangles.shape(0)),
                partition_self_collision_modes.data(), partition_collision_groups.data(),
                partition_collision_masks.data(), particle_friction.data(),
                particle_thickness.data(), particle_cloth_mass.data()
            );
        },
        nb::arg("handle"), nb::arg("points"), nb::arg("edges"), nb::arg("triangles"),
        nb::arg("partition_self_collision_modes"),
        nb::arg("partition_collision_groups"), nb::arg("partition_collision_masks"),
        nb::arg("particle_friction"), nb::arg("particle_thickness"),
        "Configure whole-domain self collision with zero cloth mass."
    );
    module.def(
        "mc2_domain_cpu_v1_step_whole_domain_self",
        [](std::uint64_t handle, cf32_2d old_positions) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(old_positions.shape(0)) != domain->particle_count() ||
                old_positions.shape(1) != 3) {
                throw nb::value_error(
                    "MC2 whole-domain self old positions must match particle_count x 3"
                );
            }
            domain->step_whole_domain_self(old_positions.data());
        },
        nb::arg("handle"), nb::arg("old_positions"),
        "Run one compiled whole-domain self-collision pass."
    );
    module.def(
        "mc2_domain_cpu_v1_step_whole_domain_self_owned",
        [](std::uint64_t handle) {
            require_domain(handle)->step_whole_domain_self_owned();
        },
        nb::arg("handle"),
        "Run compiled whole-domain self collision from the owned substep snapshot."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_compiled_external_collision",
        [](std::uint64_t handle,
           ci32_2d edges,
           cu32_1d partition_collision_modes,
           cu32_1d partition_collided_by_groups,
           cf32_1d particle_radii,
           cf32_1d particle_friction) {
            auto* domain = require_domain(handle);
            if (edges.shape(1) != 2 ||
                static_cast<std::size_t>(partition_collision_modes.shape(0)) !=
                    domain->partition_count() ||
                static_cast<std::size_t>(partition_collided_by_groups.shape(0)) !=
                    domain->partition_count() ||
                static_cast<std::size_t>(particle_radii.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(particle_friction.shape(0)) != domain->particle_count()) {
                throw nb::value_error(
                    "MC2 compiled external collision configuration arrays have incompatible shapes"
                );
            }
            domain->configure_compiled_external_collision(
                edges.data(), static_cast<std::size_t>(edges.shape(0)),
                partition_collision_modes.data(), partition_collided_by_groups.data(),
                particle_radii.data(), particle_friction.data()
            );
        },
        nb::arg("handle"), nb::arg("edges"), nb::arg("partition_collision_modes"),
        nb::arg("partition_collided_by_groups"), nb::arg("particle_radii"),
        nb::arg("particle_friction"),
        "Configure the compiled whole-domain external collision pass."
    );
    module.def(
        "mc2_domain_cpu_v1_step_compiled_external_collision",
        [](std::uint64_t handle,
           ci32_1d collider_types,
           ci32_1d collider_group_bits,
           cf32_2d collider_centers,
           cf32_2d collider_segment_a,
           cf32_2d collider_segment_b,
           cf32_2d collider_old_centers,
           cf32_2d collider_old_segment_a,
           cf32_2d collider_old_segment_b,
           cf32_1d collider_radii) {
            const auto collider_count = static_cast<std::size_t>(collider_types.shape(0));
            if (static_cast<std::size_t>(collider_group_bits.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_centers.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_segment_a.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_segment_b.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_old_centers.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_old_segment_a.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_old_segment_b.shape(0)) != collider_count ||
                static_cast<std::size_t>(collider_radii.shape(0)) != collider_count ||
                collider_centers.shape(1) != 3 || collider_segment_a.shape(1) != 3 ||
                collider_segment_b.shape(1) != 3 || collider_old_centers.shape(1) != 3 ||
                collider_old_segment_a.shape(1) != 3 || collider_old_segment_b.shape(1) != 3) {
                throw nb::value_error(
                    "MC2 compiled external collider arrays have incompatible shapes"
                );
            }
            require_domain(handle)->step_compiled_external_collision(
                collider_types.data(), collider_group_bits.data(), collider_centers.data(),
                collider_segment_a.data(), collider_segment_b.data(), collider_old_centers.data(),
                collider_old_segment_a.data(), collider_old_segment_b.data(), collider_radii.data(),
                collider_count
            );
        },
        nb::arg("handle"), nb::arg("collider_types"), nb::arg("collider_group_bits"),
        nb::arg("collider_centers"), nb::arg("collider_segment_a"),
        nb::arg("collider_segment_b"), nb::arg("collider_old_centers"),
        nb::arg("collider_old_segment_a"), nb::arg("collider_old_segment_b"),
        nb::arg("collider_radii"),
        "Run one compiled whole-domain external collision pass."
    );
    module.def(
        "mc2_domain_cpu_v1_step_external_edge_collision",
        [](std::uint64_t handle,
           cf32_1d collision_radii,
           ci32_2d edges,
           cf32_1d friction,
           std::int32_t collided_by_groups,
           ci32_1d collider_types,
           ci32_1d collider_group_bits,
           cf32_2d collider_centers,
           cf32_2d collider_segment_a,
           cf32_2d collider_segment_b,
           cf32_2d collider_old_centers,
           cf32_2d collider_old_segment_a,
           cf32_2d collider_old_segment_b,
           cf32_1d collider_radii) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(collision_radii.shape(0)) != count ||
                static_cast<std::size_t>(friction.shape(0)) != count || edges.shape(1) != 2 ||
                collider_centers.shape(1) != 3 || collider_segment_a.shape(1) != 3 ||
                collider_segment_b.shape(1) != 3 || collider_old_centers.shape(1) != 3 ||
                collider_old_segment_a.shape(1) != 3 || collider_old_segment_b.shape(1) != 3 ||
                collider_types.shape(0) != collider_group_bits.shape(0) ||
                collider_types.shape(0) != collider_radii.shape(0) ||
                collider_centers.shape(0) != collider_types.shape(0) ||
                collider_segment_a.shape(0) != collider_types.shape(0) ||
                collider_segment_b.shape(0) != collider_types.shape(0) ||
                collider_old_centers.shape(0) != collider_types.shape(0) ||
                collider_old_segment_a.shape(0) != collider_types.shape(0) ||
                collider_old_segment_b.shape(0) != collider_types.shape(0)) {
                throw nb::value_error("MC2 CPU external edge collision arrays have incompatible shapes");
            }
            domain->step_external_edge_collision(
                collision_radii.data(), edges.data(), static_cast<std::size_t>(edges.shape(0)),
                friction.data(), collided_by_groups, collider_types.data(), collider_group_bits.data(),
                collider_centers.data(), collider_segment_a.data(), collider_segment_b.data(),
                collider_old_centers.data(), collider_old_segment_a.data(), collider_old_segment_b.data(),
                collider_radii.data(), static_cast<std::size_t>(collider_types.shape(0))
            );
        },
        nb::arg("handle"), nb::arg("collision_radii"), nb::arg("edges"),
        nb::arg("friction"), nb::arg("collided_by_groups"), nb::arg("collider_types"),
        nb::arg("collider_group_bits"), nb::arg("collider_centers"),
        nb::arg("collider_segment_a"), nb::arg("collider_segment_b"),
        nb::arg("collider_old_centers"), nb::arg("collider_old_segment_a"),
        nb::arg("collider_old_segment_b"), nb::arg("collider_radii"),
        "Run the explicit native edge external-collision slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_bending",
        [](std::uint64_t handle, float simulation_power) {
            require_domain(handle)->step_bending(simulation_power);
        },
        nb::arg("handle"),
        nb::arg("simulation_power") = 1.0f,
        "Run the explicit native Bending kernel slice."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_inertia",
        [](std::uint64_t handle, cf32_1d depths, cf32_1d inv_masses) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(depths.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(inv_masses.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU inertia arrays must match particle_count");
            }
            domain->configure_inertia(depths.data(), inv_masses.data());
        },
        nb::arg("handle"),
        nb::arg("depths"),
        nb::arg("inv_masses"),
        "Configure the explicit E3 Center inertia kernel slice."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_constraint_friction",
        [](std::uint64_t handle, cf32_1d friction_values) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(friction_values.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU constraint friction must match particle_count");
            }
            domain->configure_constraint_friction(friction_values.data());
        },
        nb::arg("handle"), nb::arg("friction_values"),
        "Configure the explicit native Angle/Bending friction mass slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_inertia",
        [](std::uint64_t handle,
           cf32_1d old_world_position,
           cf32_1d step_vector,
           cf32_1d step_rotation,
           cf32_1d inertia_vector,
           cf32_1d inertia_rotation,
           float depth_inertia) {
            auto* domain = require_domain(handle);
            if (old_world_position.shape(0) != 3 || step_vector.shape(0) != 3 ||
                step_rotation.shape(0) != 4 || inertia_vector.shape(0) != 3 ||
                inertia_rotation.shape(0) != 4) {
                throw nb::value_error("MC2 CPU inertia vectors have invalid lengths");
            }
            domain->step_inertia(
                old_world_position.data(), step_vector.data(), step_rotation.data(),
                inertia_vector.data(), inertia_rotation.data(), depth_inertia
            );
        },
        nb::arg("handle"),
        nb::arg("old_world_position"),
        nb::arg("step_vector"),
        nb::arg("step_rotation"),
        nb::arg("inertia_vector"),
        nb::arg("inertia_rotation"),
        nb::arg("depth_inertia"),
        "Run the explicit Center inertia kernel slice using the existing native kernel."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_center",
        [](std::uint64_t handle,
           cf32_1d local_inertia,
           cf32_1d local_movement_speed_limits,
           cf32_1d local_rotation_speed_limits,
           cf32_1d depth_inertia,
           cf32_1d gravity,
           cf32_2d gravity_directions,
           cf32_1d gravity_falloff,
           cf32_1d stabilization_time,
           cf32_1d blend_weight) {
            auto* domain = require_domain(handle);
            const auto partition_count = domain->partition_count();
            if (static_cast<std::size_t>(local_inertia.shape(0)) != partition_count ||
                static_cast<std::size_t>(local_movement_speed_limits.shape(0)) != partition_count ||
                static_cast<std::size_t>(local_rotation_speed_limits.shape(0)) != partition_count ||
                static_cast<std::size_t>(depth_inertia.shape(0)) != partition_count ||
                static_cast<std::size_t>(gravity.shape(0)) != partition_count ||
                static_cast<std::size_t>(gravity_directions.shape(0)) != partition_count ||
                gravity_directions.shape(1) != 3 ||
                static_cast<std::size_t>(gravity_falloff.shape(0)) != partition_count ||
                static_cast<std::size_t>(stabilization_time.shape(0)) != partition_count ||
                static_cast<std::size_t>(blend_weight.shape(0)) != partition_count) {
                throw nb::value_error("MC2 CPU Center parameter arrays have incompatible shapes");
            }
            domain->configure_center(
                local_inertia.data(), local_movement_speed_limits.data(),
                local_rotation_speed_limits.data(), depth_inertia.data(), gravity.data(),
                gravity_directions.data(), gravity_falloff.data(),
                stabilization_time.data(), blend_weight.data()
            );
        },
        nb::arg("handle"),
        nb::arg("local_inertia"),
        nb::arg("local_movement_speed_limits"),
        nb::arg("local_rotation_speed_limits"),
        nb::arg("depth_inertia"),
        nb::arg("gravity"),
        nb::arg("gravity_directions"),
        nb::arg("gravity_falloff"),
        nb::arg("stabilization_time"),
        nb::arg("blend_weight"),
        "Configure the explicit per-partition Center evaluator slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_center",
        [](std::uint64_t handle, float dt, float frame_interpolation, cf32_1d distance_weights) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(distance_weights.shape(0)) != domain->partition_count()) {
                throw nb::value_error("MC2 CPU Center distance_weights must match partition_count");
            }
            domain->step_center(dt, frame_interpolation, distance_weights.data());
        },
        nb::arg("handle"),
        nb::arg("dt"),
        nb::arg("frame_interpolation"),
        nb::arg("distance_weights"),
        "Run the explicit per-partition Center evaluator slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_center_inertia",
        [](std::uint64_t handle) {
            require_domain(handle)->step_center_inertia();
        },
        nb::arg("handle"),
        "Apply the per-partition Center result to the unified particle state."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_center_frame_shift",
        [](std::uint64_t handle,
           cf32_1d anchor_inertia,
           cf32_1d world_inertia,
           cf32_1d movement_inertia_smoothing,
           cf32_1d movement_speed_limits,
           cf32_1d rotation_speed_limits,
           ci32_1d teleport_modes,
           cf32_1d teleport_distances,
           cf32_1d teleport_rotations) {
            auto* domain = require_domain(handle);
            const auto partition_count = domain->partition_count();
            if (static_cast<std::size_t>(anchor_inertia.shape(0)) != partition_count ||
                static_cast<std::size_t>(world_inertia.shape(0)) != partition_count ||
                static_cast<std::size_t>(movement_inertia_smoothing.shape(0)) != partition_count ||
                static_cast<std::size_t>(movement_speed_limits.shape(0)) != partition_count ||
                static_cast<std::size_t>(rotation_speed_limits.shape(0)) != partition_count ||
                static_cast<std::size_t>(teleport_modes.shape(0)) != partition_count ||
                static_cast<std::size_t>(teleport_distances.shape(0)) != partition_count ||
                static_cast<std::size_t>(teleport_rotations.shape(0)) != partition_count) {
                throw nb::value_error("MC2 CPU Center frame-shift arrays have incompatible shapes");
            }
            domain->configure_center_frame_shift(
                anchor_inertia.data(), world_inertia.data(), movement_inertia_smoothing.data(),
                movement_speed_limits.data(), rotation_speed_limits.data(), teleport_modes.data(),
                teleport_distances.data(), teleport_rotations.data()
            );
        },
        nb::arg("handle"), nb::arg("anchor_inertia"), nb::arg("world_inertia"),
        nb::arg("movement_inertia_smoothing"), nb::arg("movement_speed_limits"),
        nb::arg("rotation_speed_limits"), nb::arg("teleport_modes"),
        nb::arg("teleport_distances"), nb::arg("teleport_rotations"),
        "Configure the explicit per-partition Center frame-shift slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_center_frame_shift",
        [](std::uint64_t handle, cf32_2d anchor_component_local_positions) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(anchor_component_local_positions.shape(0)) != domain->partition_count() ||
                anchor_component_local_positions.shape(1) != 3) {
                throw nb::value_error("MC2 CPU Center anchor local positions have incompatible shape");
            }
            domain->step_center_frame_shift(anchor_component_local_positions.data());
        },
        nb::arg("handle"), nb::arg("anchor_component_local_positions"),
        "Run the explicit per-partition Center frame-shift slice."
    );
    module.def(
        "mc2_domain_cpu_v1_configure_integration",
        [](std::uint64_t handle, cf32_1d damping_values) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(damping_values.shape(0)) != domain->particle_count()) {
                throw nb::value_error("MC2 CPU damping values must match particle_count");
            }
            domain->configure_integration(damping_values.data());
        },
        nb::arg("handle"),
        nb::arg("damping_values"),
        "Configure the explicit E3 particle integration kernel slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_integration",
        [](std::uint64_t handle,
           float dt,
           float simulation_power,
           float velocity_weight,
           cf32_1d gravity) {
            if (gravity.shape(0) != 3) {
                throw nb::value_error("MC2 CPU integration gravity must have length 3");
            }
            require_domain(handle)->step_integration(
                dt, simulation_power, velocity_weight, gravity.data()
            );
        },
        nb::arg("handle"),
        nb::arg("dt"),
        nb::arg("simulation_power"),
        nb::arg("velocity_weight"),
        nb::arg("gravity"),
        "Run the explicit particle integration slice using the shared native kernel."
    );
    module.def(
        "mc2_domain_cpu_v1_step_integration_partitioned",
        [](std::uint64_t handle,
           float dt,
           float simulation_power) {
            require_domain(handle)->step_integration_partitioned(dt, simulation_power);
        },
        nb::arg("handle"), nb::arg("dt"), nb::arg("simulation_power"),
        "Run integration from native-owned per-partition Center outputs."
    );
    module.def(
        "mc2_domain_cpu_v1_step_post",
        [](std::uint64_t handle,
           cf32_2d old_positions,
           float dt,
           float dynamic_friction,
           float static_friction_speed,
           float particle_speed_limit,
           float velocity_weight) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(old_positions.shape(0)) != domain->particle_count() ||
                old_positions.shape(1) != 3) {
                throw nb::value_error("MC2 CPU post old_positions must be [particle_count,3]");
            }
            domain->step_post(
                old_positions.data(), dt, dynamic_friction,
                static_friction_speed, particle_speed_limit, velocity_weight
            );
        },
        nb::arg("handle"), nb::arg("old_positions"), nb::arg("dt"),
        nb::arg("dynamic_friction"), nb::arg("static_friction_speed"),
        nb::arg("particle_speed_limit"), nb::arg("velocity_weight"),
        "Run the explicit V0 post-step velocity/friction transaction."
    );
    module.def(
        "mc2_domain_cpu_v1_step_post_owned",
        [](std::uint64_t handle,
           float dt,
           float dynamic_friction,
           float static_friction_speed,
           float particle_speed_limit,
           float velocity_weight) {
            require_domain(handle)->step_post_owned(
                dt, dynamic_friction, static_friction_speed,
                particle_speed_limit, velocity_weight
            );
        },
        nb::arg("handle"), nb::arg("dt"), nb::arg("dynamic_friction"),
        nb::arg("static_friction_speed"), nb::arg("particle_speed_limit"),
        nb::arg("velocity_weight"),
        "Run post/history from the owned substep snapshot."
    );
    module.def(
        "mc2_domain_cpu_v1_step_post_owned_partitioned",
        [](std::uint64_t handle,
           float dt,
           cf32_1d dynamic_friction_values,
           cf32_1d static_friction_speed_values,
           cf32_1d particle_speed_limit_values) {
            auto* domain = require_domain(handle);
            const auto count = domain->particle_count();
            if (static_cast<std::size_t>(dynamic_friction_values.shape(0)) != count ||
                static_cast<std::size_t>(static_friction_speed_values.shape(0)) != count ||
                static_cast<std::size_t>(particle_speed_limit_values.shape(0)) != count) {
                throw nb::value_error("MC2 CPU partitioned post arrays have incompatible shapes");
            }
            domain->step_post_owned_partitioned(
                dt, dynamic_friction_values.data(), static_friction_speed_values.data(),
                particle_speed_limit_values.data()
            );
        },
        nb::arg("handle"), nb::arg("dt"), nb::arg("dynamic_friction_values"),
        nb::arg("static_friction_speed_values"), nb::arg("particle_speed_limit_values"),
        "Run owned post/history with per-particle partition parameters."
    );
    module.def(
        "mc2_domain_cpu_v1_read",
        [](std::uint64_t handle) {
            auto* domain = require_domain(handle);
            nb::dict result;
            result["world_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->world_positions()), domain->particle_count(), 3
            );
            result["world_rotations_xyzw"] = owned_array_2d<float>(
                std::vector<float>(domain->world_rotations()), domain->particle_count(), 4
            );
            result["world_normals"] = owned_array_2d<float>(
                std::vector<float>(domain->world_normals()), domain->particle_count(), 3
            );
            result["real_velocities"] = owned_array_2d<float>(
                std::vector<float>(domain->real_velocities()), domain->particle_count(), 3
            );
            result["frame"] = domain->frame();
            result["generation"] = domain->generation();
            result["frame_delta_time"] = domain->frame_delta_time();
            result["simulation_delta_time"] = domain->simulation_delta_time();
            result["time_scale"] = domain->time_scale();
            result["skip_count"] = domain->skip_count();
            result["is_running"] = domain->is_running();
            result["step_count"] = domain->step_count();
            result["backend_kind"] = "mc2_domain_cpu_v1_datapath";
            return result;
        },
        nb::arg("handle"),
        "Read the logical pass-through output of the E3 data-path slice."
    );
    module.def(
        "mc2_domain_cpu_v1_inspect",
        [](std::uint64_t handle) {
            auto* domain = require_domain(handle);
            nb::dict result;
            result["particle_count"] = domain->particle_count();
            result["partition_count"] = domain->partition_count();
            result["domain_signature"] = domain->domain_signature();
            result["layout_signature"] = domain->layout_signature();
            result["frame"] = domain->frame();
            result["generation"] = domain->generation();
            result["frame_delta_time"] = domain->frame_delta_time();
            result["simulation_delta_time"] = domain->simulation_delta_time();
            result["time_scale"] = domain->time_scale();
            result["skip_count"] = domain->skip_count();
            result["is_running"] = domain->is_running();
            result["step_count"] = domain->step_count();
            result["disposed"] = domain->disposed();
            result["baseline_ready"] = domain->baseline_ready();
            result["baseline_line_count"] = domain->baseline_line_count();
            result["baseline_data_count"] = domain->baseline_data_count();
            result["baseline_pose_ready"] = domain->baseline_pose_ready();
            result["whole_domain_self_ready"] = domain->whole_domain_self_ready();
            result["whole_domain_self_point_count"] = domain->whole_domain_self_point_count();
            result["whole_domain_self_edge_count"] = domain->whole_domain_self_edge_count();
            result["whole_domain_self_triangle_count"] = domain->whole_domain_self_triangle_count();
            result["whole_domain_self_step_count"] = domain->whole_domain_self_step_count();
            result["whole_domain_self_last_contact_count"] =
                domain->whole_domain_self_last_contact_count();
            result["whole_domain_self_last_candidate_count"] =
                domain->whole_domain_self_last_candidate_count();
            result["compiled_external_ready"] = domain->compiled_external_ready();
            result["compiled_external_edge_count"] = domain->compiled_external_edge_count();
            result["compiled_external_step_count"] = domain->compiled_external_step_count();
            result["partition_world_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->partition_world_positions()),
                domain->partition_count(), 3
            );
            result["partition_center_local_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->partition_center_local_positions()),
                domain->partition_count(), 3
            );
            result["partition_initial_local_gravity_directions"] = owned_array_2d<float>(
                std::vector<float>(domain->partition_initial_local_gravity_directions()),
                domain->partition_count(), 3
            );
            result["partition_reset_counts"] = owned_array_1d<std::int64_t>(
                std::vector<std::int64_t>(domain->partition_reset_counts())
            );
            result["partition_keep_counts"] = owned_array_1d<std::int64_t>(
                std::vector<std::int64_t>(domain->partition_keep_counts())
            );
            result["center_step_vectors"] = owned_array_2d<float>(
                std::vector<float>(domain->center_step_vectors()), domain->partition_count(), 3
            );
            result["center_inertia_vectors"] = owned_array_2d<float>(
                std::vector<float>(domain->center_inertia_vectors()), domain->partition_count(), 3
            );
            result["center_frame_world_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->center_frame_world_positions()),
                domain->partition_count(), 3
            );
            result["center_frame_world_rotations"] = owned_array_2d<float>(
                std::vector<float>(domain->center_frame_world_rotations()),
                domain->partition_count(), 4
            );
            result["center_shift_vectors"] = owned_array_2d<float>(
                std::vector<float>(domain->center_shift_vectors()),
                domain->partition_count(), 3
            );
            result["center_shift_rotations"] = owned_array_2d<float>(
                std::vector<float>(domain->center_shift_rotations()),
                domain->partition_count(), 4
            );
            result["center_shift_now_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->center_shift_now_positions()),
                domain->partition_count(), 3
            );
            result["center_shift_now_rotations"] = owned_array_2d<float>(
                std::vector<float>(domain->center_shift_now_rotations()),
                domain->partition_count(), 4
            );
            result["center_shift_teleport_flags"] = owned_array_1d<std::uint32_t>(
                std::vector<std::uint32_t>(domain->center_shift_teleport_flags())
            );
            result["center_shift_count"] = domain->center_shift_count();
            result["center_step_count"] = domain->center_step_count();
            return result;
        },
        nb::arg("handle"),
        "Inspect the read-only E3 data-path owner state, including frame timing contract."
    );
    module.def(
        "mc2_domain_cpu_v1_dispose",
        [](std::uint64_t handle) {
            if (handle == 0) return;
            auto* domain = reinterpret_cast<mc2_domain_cpu::DomainV1*>(handle);
            if (live_domains.erase(domain) == 0) return;
            domain->dispose();
            delete domain;
        },
        nb::arg("handle"),
        "Dispose an independent E3 MC2 CPU domain owner."
    );
    module.def(
        "mc2_center_frame_shift_v1_evaluate",
        [](cf32_1d old_component_position, cf32_1d component_position,
           cf32_1d old_component_rotation, cf32_1d component_rotation,
           cf32_1d component_scale, cf32_1d initial_scale,
           cf32_1d frame_world_position, cf32_1d frame_world_rotation,
           cf32_1d old_frame_world_position, cf32_1d old_frame_world_rotation,
           cf32_1d now_world_position, cf32_1d now_world_rotation,
           cf32_1d old_anchor_position, cf32_1d old_anchor_rotation,
           cf32_1d anchor_position, cf32_1d anchor_rotation,
           cf32_1d anchor_component_local_position, cf32_1d smoothing_velocity,
           bool use_anchor, bool is_running, float anchor_inertia, float world_inertia,
           float movement_speed_limit, float rotation_speed_limit,
           float movement_inertia_smoothing, float frame_delta_time,
           float simulation_delta_time, float time_scale, std::int64_t skip_count,
           float velocity_weight, std::int32_t teleport_mode,
           float teleport_distance, float teleport_rotation) {
            const auto require_shape = [](const auto& array, std::size_t size) {
                if (static_cast<std::size_t>(array.shape(0)) != size) {
                    throw nb::value_error("Center frame-shift vector has an invalid width");
                }
            };
            require_shape(old_component_position, 3); require_shape(component_position, 3);
            require_shape(old_component_rotation, 4); require_shape(component_rotation, 4);
            require_shape(component_scale, 3); require_shape(initial_scale, 3);
            require_shape(frame_world_position, 3); require_shape(frame_world_rotation, 4);
            require_shape(old_frame_world_position, 3); require_shape(old_frame_world_rotation, 4);
            require_shape(now_world_position, 3); require_shape(now_world_rotation, 4);
            require_shape(old_anchor_position, 3); require_shape(old_anchor_rotation, 4);
            require_shape(anchor_position, 3); require_shape(anchor_rotation, 4);
            require_shape(anchor_component_local_position, 3); require_shape(smoothing_velocity, 3);
            Mc2CenterFrameShiftView view;
            view.old_component_position = old_component_position.data();
            view.component_position = component_position.data();
            view.old_component_rotation = old_component_rotation.data();
            view.component_rotation = component_rotation.data();
            view.component_scale = component_scale.data(); view.initial_scale = initial_scale.data();
            view.frame_world_position = frame_world_position.data(); view.frame_world_rotation = frame_world_rotation.data();
            view.old_frame_world_position = old_frame_world_position.data(); view.old_frame_world_rotation = old_frame_world_rotation.data();
            view.now_world_position = now_world_position.data(); view.now_world_rotation = now_world_rotation.data();
            view.old_anchor_position = old_anchor_position.data(); view.old_anchor_rotation = old_anchor_rotation.data();
            view.anchor_position = anchor_position.data(); view.anchor_rotation = anchor_rotation.data();
            view.anchor_component_local_position = anchor_component_local_position.data(); view.smoothing_velocity = smoothing_velocity.data();
            view.use_anchor = use_anchor; view.is_running = is_running;
            view.anchor_inertia = anchor_inertia; view.world_inertia = world_inertia;
            view.movement_speed_limit = movement_speed_limit; view.rotation_speed_limit = rotation_speed_limit;
            view.movement_inertia_smoothing = movement_inertia_smoothing;
            view.frame_delta_time = frame_delta_time; view.simulation_delta_time = simulation_delta_time;
            view.time_scale = time_scale; view.skip_count = skip_count; view.velocity_weight = velocity_weight;
            view.teleport_mode = teleport_mode; view.teleport_distance = teleport_distance; view.teleport_rotation = teleport_rotation;
            if (!evaluate_center_frame_shift_mc2(view)) {
                throw nb::value_error("MC2 Center frame-shift input is invalid or degenerate");
            }
            nb::dict result;
            const auto output3 = [](const float* values) {
                return owned_array_1d<float>(std::vector<float>(values, values + 3));
            };
            const auto output4 = [](const float* values) {
                return owned_array_1d<float>(std::vector<float>(values, values + 4));
            };
            result["frame_component_shift_vector"] = output3(view.frame_component_shift_vector);
            result["frame_component_shift_rotation_xyzw"] = output4(view.frame_component_shift_rotation);
            result["old_frame_world_position"] = output3(view.shifted_old_frame_position);
            result["old_frame_world_rotation_xyzw"] = output4(view.shifted_old_frame_rotation);
            result["now_world_position"] = output3(view.shifted_now_position);
            result["now_world_rotation_xyzw"] = output4(view.shifted_now_rotation);
            result["smoothing_velocity"] = output3(view.smoothing_velocity_output);
            result["frame_moving_direction"] = output3(view.frame_moving_direction);
            result["raw_component_delta"] = output3(view.raw_component_delta);
            result["anchor_shift_vector"] = output3(view.anchor_shift_vector);
            result["smoothing_shift_vector"] = output3(view.smoothing_shift_vector);
            result["world_shift_vector"] = output3(view.world_shift_vector);
            result["teleport_rotation_axis"] = output3(view.teleport_rotation_axis);
            result["frame_moving_speed"] = view.frame_moving_speed;
            result["pre_limit_moving_speed"] = view.pre_limit_moving_speed;
            result["teleport_measured_distance"] = view.teleport_measured_distance;
            result["teleport_distance_threshold"] = view.teleport_distance_threshold;
            result["teleport_measured_rotation_degrees"] = view.teleport_measured_rotation_degrees;
            result["movement_speed_limited"] = view.movement_speed_limited;
            result["rotation_speed_limited"] = view.rotation_speed_limited;
            result["teleport_triggered"] = view.teleport_triggered;
            result["keep_teleport"] = view.keep_teleport;
            result["reset_teleport"] = view.reset_teleport;
            return result;
        },
        nb::arg("old_component_position"), nb::arg("component_position"),
        nb::arg("old_component_rotation"), nb::arg("component_rotation"),
        nb::arg("component_scale"), nb::arg("initial_scale"),
        nb::arg("frame_world_position"), nb::arg("frame_world_rotation"),
        nb::arg("old_frame_world_position"), nb::arg("old_frame_world_rotation"),
        nb::arg("now_world_position"), nb::arg("now_world_rotation"),
        nb::arg("old_anchor_position"), nb::arg("old_anchor_rotation"),
        nb::arg("anchor_position"), nb::arg("anchor_rotation"),
        nb::arg("anchor_component_local_position"), nb::arg("smoothing_velocity"),
        nb::arg("use_anchor"), nb::arg("is_running"), nb::arg("anchor_inertia"),
        nb::arg("world_inertia"), nb::arg("movement_speed_limit"),
        nb::arg("rotation_speed_limit"), nb::arg("movement_inertia_smoothing"),
        nb::arg("frame_delta_time"), nb::arg("simulation_delta_time"),
        nb::arg("time_scale"), nb::arg("skip_count"), nb::arg("velocity_weight"),
        nb::arg("teleport_mode"), nb::arg("teleport_distance"), nb::arg("teleport_rotation"),
        "Evaluate the explicit native Center frame-shift data path."
    );
    module.def(
        "mc2_domain_cpu_v1_stats",
        []() {
            nb::dict result;
            result["live_domain_count"] = live_domains.size();
            return result;
        },
        "Inspect process-local E3 MC2 CPU domain resource counts."
    );
}

}  // namespace hotools
