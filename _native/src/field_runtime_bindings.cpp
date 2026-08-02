#include "field_runtime_bindings.hpp"

#include "field_runtime.hpp"

#include <nanobind/ndarray.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace nb = nanobind;

namespace hotools {
namespace {

using cf64_2d = nb::ndarray<const double, nb::ndim<2>, nb::c_contig, nb::device::cpu>;
using cf64_3d = nb::ndarray<const double, nb::ndim<3>, nb::c_contig, nb::device::cpu>;
using ci32_1d = nb::ndarray<const std::int32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using cu32_1d = nb::ndarray<const std::uint32_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

// 所有当前 binding 都持有 GIL；registry 因而保持 GIL 串行访问。
// handle 只用于查找当前可见 runtime；uint64 ID 永不复用，避免 ABA。
// shared_ptr 是调用期租约：注销只摘除 map，不销毁已取得的 runtime。
// 这里不能引入 std::mutex：Blender 的 tbbmalloc_proxy / MSVC CRT 组合
// 已在 MC2 binding 中验证会触发 Mtx_trylock 访问冲突。未来 native worker
// 接入时必须另行设计不依赖 MSVC mutex 的 registry 同步方案。
std::unordered_map<
    std::uint64_t,
    std::shared_ptr<field_runtime::FieldRuntimeV1>
> live_field_runtimes;
std::uint64_t next_field_runtime_handle = 1;

template<typename T>
nb::ndarray<nb::numpy, T, nb::ro> owned_readonly_array_1d(
    std::vector<T>&& values
) {
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T, nb::ro>(
        owner_data->data(), {owner_data->size()}, owner
    );
}

template<typename T>
nb::ndarray<nb::numpy, T, nb::ro> owned_readonly_array_2d(
    std::vector<T>&& values,
    std::size_t rows,
    std::size_t columns
) {
    if (values.size() != rows * columns) {
        throw nb::value_error("Field runtime 输出 shape 不匹配");
    }
    auto* owner_data = new std::vector<T>(std::move(values));
    nb::capsule owner(owner_data, [](void* pointer) noexcept {
        delete static_cast<std::vector<T>*>(pointer);
    });
    return nb::ndarray<nb::numpy, T, nb::ro>(
        owner_data->data(), {rows, columns}, owner
    );
}

void require_field_count(std::size_t actual, std::size_t expected, const char* label) {
    if (actual != expected) {
        throw nb::value_error((std::string(label) + " 必须匹配 field_count").c_str());
    }
}

}  // namespace

namespace field_runtime {

std::uint64_t register_runtime_v1(std::unique_ptr<FieldRuntimeV1> runtime) {
    if (!runtime) {
        throw std::invalid_argument("Field runtime registry 不能注册空 owner");
    }
    if (next_field_runtime_handle == 0) {
        throw std::overflow_error("Field runtime handle 空间已耗尽");
    }
    const std::uint64_t handle = next_field_runtime_handle++;
    const auto owner = std::shared_ptr<FieldRuntimeV1>(std::move(runtime));
    const auto inserted = live_field_runtimes.emplace(handle, owner);
    if (!inserted.second) {
        throw std::logic_error("Field runtime handle registry 冲突");
    }
    return handle;
}

std::shared_ptr<FieldRuntimeV1> acquire_registered_runtime_v1(std::uint64_t handle) {
    if (handle == 0) {
        throw std::invalid_argument("Field runtime handle 不能为空");
    }
    const auto found = live_field_runtimes.find(handle);
    if (found == live_field_runtimes.end()) {
        throw std::runtime_error("Field runtime handle 已失效");
    }
    return found->second;
}

bool dispose_registered_runtime_v1(std::uint64_t handle) noexcept {
    if (handle == 0) {
        return false;
    }
    return live_field_runtimes.erase(handle) != 0;
}

std::size_t live_runtime_count_v1() noexcept {
    return live_field_runtimes.size();
}

std::uint64_t next_runtime_handle_v1() noexcept {
    return next_field_runtime_handle;
}

}  // namespace field_runtime

void bind_field_runtime(nb::module_& module) {
    module.def(
        "field_runtime_v1_create",
        [](
            std::uint32_t abi_version,
            const std::string& snapshot_signature,
            const std::string& config_signature,
            const std::string& value_signature,
            std::int64_t generation,
            std::int64_t frame,
            double sample_time_seconds,
            std::vector<std::string> field_ids,
            ci32_1d field_type_codes,
            ci32_1d volume_shape_codes,
            cf64_3d world_to_local,
            cf64_2d direction_world,
            cf64_2d wind_values,
            cu32_1d octaves,
            cu32_1d seed_u32,
            std::vector<std::vector<std::string>> scope_solver_ids,
            std::vector<std::vector<std::string>> scope_collection_ids,
            std::vector<std::vector<std::string>> scope_include_ids,
            std::vector<std::vector<std::string>> scope_exclude_ids,
            cu32_1d scope_collision_group_masks
        ) {
            const std::size_t field_count = field_ids.size();
            require_field_count(
                static_cast<std::size_t>(field_type_codes.shape(0)), field_count,
                "field_type_codes"
            );
            require_field_count(
                static_cast<std::size_t>(volume_shape_codes.shape(0)), field_count,
                "volume_shape_codes"
            );
            if (
                static_cast<std::size_t>(world_to_local.shape(0)) != field_count ||
                world_to_local.shape(1) != 4 || world_to_local.shape(2) != 4
            ) {
                throw nb::value_error("world_to_local 必须是 [field_count,4,4]");
            }
            if (
                static_cast<std::size_t>(direction_world.shape(0)) != field_count ||
                direction_world.shape(1) != 3
            ) {
                throw nb::value_error("direction_world 必须是 [field_count,3]");
            }
            if (
                static_cast<std::size_t>(wind_values.shape(0)) != field_count ||
                wind_values.shape(1) != 7
            ) {
                throw nb::value_error("wind_values 必须是 [field_count,7]");
            }
            require_field_count(
                static_cast<std::size_t>(octaves.shape(0)), field_count, "octaves"
            );
            require_field_count(
                static_cast<std::size_t>(seed_u32.shape(0)), field_count, "seed_u32"
            );
            require_field_count(scope_solver_ids.size(), field_count, "scope_solver_ids");
            require_field_count(
                scope_collection_ids.size(), field_count, "scope_collection_ids"
            );
            require_field_count(scope_include_ids.size(), field_count, "scope_include_ids");
            require_field_count(scope_exclude_ids.size(), field_count, "scope_exclude_ids");
            require_field_count(
                static_cast<std::size_t>(scope_collision_group_masks.shape(0)),
                field_count,
                "scope_collision_group_masks"
            );

            std::vector<field_runtime::FieldDefinitionV1> fields(field_count);
            for (std::size_t index = 0; index < field_count; ++index) {
                auto& field = fields[index];
                field.field_id = std::move(field_ids[index]);
                const auto field_type_code = field_type_codes.data()[index];
                if (field_type_code != static_cast<std::int32_t>(
                    field_runtime::FieldTypeV1::Wind
                )) {
                    throw nb::value_error("Field runtime V1 不支持该 field_type code");
                }
                field.field_type = field_runtime::FieldTypeV1::Wind;

                const auto shape_code = volume_shape_codes.data()[index];
                if (shape_code == static_cast<std::int32_t>(
                    field_runtime::VolumeShapeV1::Sphere
                )) {
                    field.volume_shape = field_runtime::VolumeShapeV1::Sphere;
                } else if (shape_code == static_cast<std::int32_t>(
                    field_runtime::VolumeShapeV1::Box
                )) {
                    field.volume_shape = field_runtime::VolumeShapeV1::Box;
                } else {
                    throw nb::value_error("Field runtime V1 不支持该 volume_shape code");
                }

                const double* matrix = world_to_local.data() + index * 16;
                std::copy_n(matrix, 16, field.world_to_local.begin());
                const double* direction = direction_world.data() + index * 3;
                std::copy_n(direction, 3, field.direction_world.begin());
                const double* wind = wind_values.data() + index * 7;
                field.speed_mps = wind[0];
                field.turbulence = wind[1];
                field.spatial_scale_m = wind[2];
                field.temporal_frequency_hz = wind[3];
                field.lacunarity = wind[4];
                field.gain = wind[5];
                field.blend_weight = wind[6];
                field.octaves = octaves.data()[index];
                field.seed_u32 = seed_u32.data()[index];
                field.scope.solver_ids = std::move(scope_solver_ids[index]);
                field.scope.collection_ids = std::move(scope_collection_ids[index]);
                field.scope.include_ids = std::move(scope_include_ids[index]);
                field.scope.exclude_ids = std::move(scope_exclude_ids[index]);
                field.scope.collision_group_mask = scope_collision_group_masks.data()[index];
            }

            auto runtime = std::make_unique<field_runtime::FieldRuntimeV1>(
                abi_version,
                snapshot_signature,
                config_signature,
                value_signature,
                generation,
                frame,
                sample_time_seconds,
                std::move(fields)
            );
            return field_runtime::register_runtime_v1(std::move(runtime));
        },
        nb::arg("abi_version"),
        nb::arg("snapshot_signature"),
        nb::arg("config_signature"),
        nb::arg("value_signature"),
        nb::arg("generation"),
        nb::arg("frame"),
        nb::arg("sample_time_seconds"),
        nb::arg("field_ids"),
        nb::arg("field_type_codes"),
        nb::arg("volume_shape_codes"),
        nb::arg("world_to_local"),
        nb::arg("direction_world"),
        nb::arg("wind_values"),
        nb::arg("octaves"),
        nb::arg("seed_u32"),
        nb::arg("scope_solver_ids"),
        nb::arg("scope_collection_ids"),
        nb::arg("scope_include_ids"),
        nb::arg("scope_exclude_ids"),
        nb::arg("scope_collision_group_masks"),
        "创建一个深拷贝、与 Blender 对象解耦的公共 Field runtime。"
    );

    module.def(
        "field_runtime_v1_update_frame",
        [](
            std::uint64_t handle,
            const std::string& snapshot_signature,
            std::int64_t generation,
            std::int64_t frame,
            double sample_time_seconds
        ) {
            auto runtime = field_runtime::acquire_registered_runtime_v1(handle);
            runtime->update_frame(
                snapshot_signature, generation, frame, sample_time_seconds
            );
        },
        nb::arg("handle"),
        nb::arg("snapshot_signature"),
        nb::arg("generation"),
        nb::arg("frame"),
        nb::arg("sample_time_seconds"),
        "只更新同一 Field 配置的帧身份与 Physics World 时间。"
    );

    module.def(
        "field_runtime_v1_sample_air_velocity",
        [](
            std::uint64_t handle,
            cf64_2d positions_world,
            double sample_time_seconds,
            const std::string& consumer_id,
            const std::string& object_id,
            std::vector<std::string> collection_ids,
            std::uint32_t collision_group_mask
        ) {
            if (positions_world.shape(1) != 3) {
                throw nb::value_error("positions_world 必须是 [N,3]");
            }
            field_runtime::FieldSampleContextV1 context;
            context.consumer_id = consumer_id;
            context.object_id = object_id;
            context.collection_ids = std::move(collection_ids);
            context.collision_group_mask = collision_group_mask;
            const std::size_t position_count = static_cast<std::size_t>(
                positions_world.shape(0)
            );
            auto runtime = field_runtime::acquire_registered_runtime_v1(handle);
            auto output = runtime->sample_air_velocity(
                positions_world.data(), position_count, sample_time_seconds, context
            );
            nb::dict result;
            result["air_velocity_world"] = owned_readonly_array_2d<float>(
                std::move(output.air_velocity_world), position_count, 3
            );
            result["participation"] = owned_readonly_array_1d<std::uint8_t>(
                std::move(output.participation)
            );
            result["sample_time_seconds"] = sample_time_seconds;
            result["sampled_field_count"] = output.sampled_field_count;
            return result;
        },
        nb::arg("handle"),
        nb::arg("positions_world"),
        nb::arg("sample_time_seconds"),
        nb::arg("consumer_id"),
        nb::arg("object_id"),
        nb::arg("collection_ids"),
        nb::arg("collision_group_mask"),
        "按显式消费上下文批量采样 world-space air_velocity 与 participation。"
    );

    module.def(
        "field_runtime_v1_inspect",
        [](std::uint64_t handle) {
            auto runtime = field_runtime::acquire_registered_runtime_v1(handle);
            std::size_t sphere_count = 0;
            std::size_t box_count = 0;
            std::size_t turbulent_count = 0;
            nb::list field_ids;
            for (const auto& field : runtime->fields()) {
                field_ids.append(field.field_id);
                sphere_count += field.volume_shape == field_runtime::VolumeShapeV1::Sphere;
                box_count += field.volume_shape == field_runtime::VolumeShapeV1::Box;
                turbulent_count += field.turbulence > 0.0;
            }
            nb::dict result;
            result["schema"] = "field_runtime_v1";
            result["backend_kind"] = "field_runtime_native_v1";
            result["handle"] = handle;
            result["live"] = true;
            result["abi_version"] = runtime->abi_version();
            result["snapshot_signature"] = runtime->snapshot_signature();
            result["config_signature"] = runtime->config_signature();
            result["value_signature"] = runtime->value_signature();
            result["generation"] = runtime->generation();
            result["frame"] = runtime->frame();
            result["sample_time_seconds"] = runtime->sample_time_seconds();
            result["field_count"] = runtime->fields().size();
            result["field_ids"] = std::move(field_ids);
            result["sphere_field_count"] = sphere_count;
            result["box_field_count"] = box_count;
            result["turbulent_field_count"] = turbulent_count;
            result["scope_mode"] = "field_scope_context_v0";
            result["noise_algorithm_version"] =
                field_runtime::kWindNoiseAlgorithmVersionV0;
            result["attenuation_policy_version"] =
                field_runtime::kVolumeAttenuationPolicyVersionV0;
            return result;
        },
        nb::arg("handle"),
        "读取 Field runtime 的不可变配置与当前帧身份。"
    );

    module.def(
        "field_runtime_v1_dispose",
        [](std::uint64_t handle) {
            if (handle == 0) return;
            field_runtime::dispose_registered_runtime_v1(handle);
        },
        nb::arg("handle"),
        "幂等释放 Field runtime；已释放 handle 永远不会重新指向新 runtime。"
    );

    module.def(
        "field_runtime_v1_stats",
        []() {
            nb::dict result;
            result["live_runtime_count"] = field_runtime::live_runtime_count_v1();
            result["next_handle"] = field_runtime::next_runtime_handle_v1();
            result["registry_kind"] = "monotonic_uint64_v1";
            return result;
        },
        "读取 Field runtime registry 的生命周期统计。"
    );
}

}  // namespace hotools
