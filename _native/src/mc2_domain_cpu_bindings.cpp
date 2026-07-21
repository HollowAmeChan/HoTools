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
using cf32_1d = nb::ndarray<const float, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const std::int32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

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

}  // namespace

void bind_mc2_domain_cpu(nb::module_& module) {
    module.def(
        "mc2_domain_cpu_v1_create",
        [](std::uint32_t schema_version,
           std::size_t particle_count,
           const std::string& domain_signature,
           const std::string& layout_signature,
           cf32_2d bind_positions,
           cf32_2d bind_rotations) {
            if (static_cast<std::size_t>(bind_positions.shape(0)) != particle_count ||
                bind_positions.shape(1) != 3) {
                throw nb::value_error("bind_positions must be [particle_count,3]");
            }
            if (static_cast<std::size_t>(bind_rotations.shape(0)) != particle_count ||
                bind_rotations.shape(1) != 4) {
                throw nb::value_error("bind_rotations must be [particle_count,4]");
            }
            mc2_domain_cpu::ProgramViewV1 program {
                schema_version,
                particle_count,
                bind_positions.data(),
                bind_rotations.data(),
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
        nb::arg("domain_signature"),
        nb::arg("layout_signature"),
        nb::arg("bind_positions"),
        nb::arg("bind_rotations"),
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
           cf32_2d world_normals) {
            auto* domain = require_domain(handle);
            if (static_cast<std::size_t>(world_positions.shape(0)) != domain->particle_count() ||
                world_positions.shape(1) != 3 ||
                static_cast<std::size_t>(world_normals.shape(0)) != domain->particle_count() ||
                world_normals.shape(1) != 3) {
                throw nb::value_error("MC2 CPU frame arrays must be [particle_count,3]");
            }
            domain->update_frame({
                domain->particle_count(),
                world_positions.data(),
                world_normals.data(),
                frame,
                generation,
                domain_signature.c_str(),
                layout_signature.c_str(),
            });
        },
        nb::arg("handle"),
        nb::arg("domain_signature"),
        nb::arg("layout_signature"),
        nb::arg("frame"),
        nb::arg("generation"),
        nb::arg("world_positions"),
        nb::arg("world_normals"),
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
        "mc2_domain_cpu_v1_read",
        [](std::uint64_t handle) {
            auto* domain = require_domain(handle);
            nb::dict result;
            result["world_positions"] = owned_array_2d<float>(
                std::vector<float>(domain->world_positions()), domain->particle_count(), 3
            );
            result["world_normals"] = owned_array_2d<float>(
                std::vector<float>(domain->world_normals()), domain->particle_count(), 3
            );
            result["frame"] = domain->frame();
            result["generation"] = domain->generation();
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
            result["domain_signature"] = domain->domain_signature();
            result["layout_signature"] = domain->layout_signature();
            result["frame"] = domain->frame();
            result["generation"] = domain->generation();
            result["step_count"] = domain->step_count();
            result["disposed"] = domain->disposed();
            return result;
        },
        nb::arg("handle"),
        "Inspect the read-only E3 data-path owner state."
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
