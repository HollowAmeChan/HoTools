#include "mc2_domain_cpu.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>

#include <cstdint>
#include <mutex>
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
using cu32_1d = nb::ndarray<const std::uint32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

std::mutex domain_registry_mutex;
std::unordered_set<mc2_domain_cpu::DomainV1*> live_domains;

mc2_domain_cpu::DomainV1* require_domain(std::uint64_t handle) {
    if (handle == 0) {
        throw nb::value_error("MC2 CPU domain handle is null");
    }
    auto* domain = reinterpret_cast<mc2_domain_cpu::DomainV1*>(handle);
    {
        const std::lock_guard<std::mutex> lock(domain_registry_mutex);
        if (live_domains.find(domain) == live_domains.end()) {
            throw std::runtime_error("MC2 CPU domain handle is not live");
        }
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
            {
                const std::lock_guard<std::mutex> lock(domain_registry_mutex);
                live_domains.insert(domain);
            }
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
           cf32_1d stiffness_values) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(starts.shape(0)) != domain->particle_count() ||
                static_cast<std::size_t>(counts.shape(0)) != domain->particle_count() ||
                neighbors.shape(0) != rest_lengths.shape(0) ||
                neighbors.shape(0) != stiffness_values.shape(0)) {
                throw nb::value_error("MC2 CPU distance arrays have incompatible lengths");
            }
            domain->configure_distance(
                starts.data(), counts.data(), neighbors.data(),
                rest_lengths.data(), stiffness_values.data(),
                static_cast<std::size_t>(neighbors.shape(0))
            );
        },
        nb::arg("handle"),
        nb::arg("starts"),
        nb::arg("counts"),
        nb::arg("neighbors"),
        nb::arg("rest_lengths"),
        nb::arg("stiffness_values"),
        "Configure the explicit E3 Distance kernel slice."
    );
    module.def(
        "mc2_domain_cpu_v1_step_distance",
        [](std::uint64_t handle) { require_domain(handle)->step_distance(); },
        nb::arg("handle"),
        "Run the explicit Distance kernel slice using the existing native kernel."
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
                local_rotation_speed_limits.data(), gravity.data(),
                gravity_directions.data(), gravity_falloff.data(),
                stabilization_time.data(), blend_weight.data()
            );
        },
        nb::arg("handle"),
        nb::arg("local_inertia"),
        nb::arg("local_movement_speed_limits"),
        nb::arg("local_rotation_speed_limits"),
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
            {
                const std::lock_guard<std::mutex> lock(domain_registry_mutex);
                if (live_domains.erase(domain) == 0) return;
            }
            domain->dispose();
            delete domain;
        },
        nb::arg("handle"),
        "Dispose an independent E3 MC2 CPU domain owner."
    );
    module.def(
        "mc2_domain_cpu_v1_stats",
        []() {
            const std::lock_guard<std::mutex> lock(domain_registry_mutex);
            nb::dict result;
            result["live_domain_count"] = live_domains.size();
            return result;
        },
        "Inspect process-local E3 MC2 CPU domain resource counts."
    );
}

}  // namespace hotools
