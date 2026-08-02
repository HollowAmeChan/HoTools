#include "field_runtime.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace hotools::field_runtime {
namespace {

constexpr std::array<std::uint64_t, 4> kHashAxisSalts {
    0x9E3779B97F4A7C15ull,
    0xD1B54A32D192ED03ull,
    0x94D049BB133111EBull,
    0x8538ECB5BD456EA3ull,
};
constexpr std::array<std::uint64_t, 3> kHashChannelSalts {
    0xA24BAED4963EE407ull,
    0x9FB21C651E98DF25ull,
    0xC13FA9A902A6328Full,
};
constexpr std::uint32_t kOctaveSeedStep = 0x9E3779B9u;

bool contains(const std::vector<std::string>& values, const std::string& target) {
    return std::find(values.begin(), values.end(), target) != values.end();
}

bool intersects(
    const std::vector<std::string>& left,
    const std::vector<std::string>& right
) {
    for (const auto& value : left) {
        if (contains(right, value)) return true;
    }
    return false;
}

void require_scope_ids(
    const std::vector<std::string>& values,
    const char* label
) {
    std::unordered_set<std::string> unique;
    for (const auto& value : values) {
        if (value.empty()) {
            throw std::invalid_argument(std::string(label) + " 不能包含空标识符");
        }
        if (!unique.insert(value).second) {
            throw std::invalid_argument(std::string(label) + " 不能包含重复标识符");
        }
    }
}

void require_metadata(
    const std::string& snapshot_signature,
    std::int64_t generation,
    double sample_time_seconds
) {
    if (snapshot_signature.empty()) {
        throw std::invalid_argument("Field runtime snapshot_signature 不能为空");
    }
    if (generation < 0) {
        throw std::invalid_argument("Field runtime generation 必须是非负整数");
    }
    if (!std::isfinite(sample_time_seconds) || sample_time_seconds < 0.0) {
        throw std::invalid_argument("Field runtime sample_time_seconds 必须是非负有限值");
    }
}

void validate_and_normalize_field(FieldDefinitionV1& field) {
    if (field.field_id.empty()) {
        throw std::invalid_argument("Field runtime field_id 不能为空");
    }
    if (field.field_type != FieldTypeV1::Wind) {
        throw std::invalid_argument("Field runtime V1 只支持 Wind 类型");
    }
    if (
        field.volume_shape != VolumeShapeV1::Sphere &&
        field.volume_shape != VolumeShapeV1::Box
    ) {
        throw std::invalid_argument("Field runtime V1 只支持 Sphere 或 Box Volume");
    }
    for (double value : field.world_to_local) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("Field runtime world_to_local 必须全为有限值");
        }
    }
    constexpr double kAffineTolerance = 1.0e-8;
    if (
        std::abs(field.world_to_local[12]) > kAffineTolerance ||
        std::abs(field.world_to_local[13]) > kAffineTolerance ||
        std::abs(field.world_to_local[14]) > kAffineTolerance ||
        std::abs(field.world_to_local[15] - 1.0) > kAffineTolerance
    ) {
        throw std::invalid_argument("Field runtime world_to_local 必须是 affine 4x4 matrix");
    }

    double direction_length_squared = 0.0;
    for (double value : field.direction_world) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument("Field runtime direction_world 必须全为有限值");
        }
        direction_length_squared += value * value;
    }
    const double direction_length = std::sqrt(direction_length_squared);
    if (!std::isfinite(direction_length) || direction_length <= 1.0e-8) {
        throw std::invalid_argument("Field runtime direction_world 不能是零向量");
    }
    for (double& value : field.direction_world) value /= direction_length;

    const auto finite = [](double value) { return std::isfinite(value); };
    if (!finite(field.speed_mps) || field.speed_mps < 0.0) {
        throw std::invalid_argument("Field runtime speed_mps 必须是非负有限值");
    }
    if (!finite(field.turbulence) || field.turbulence < 0.0 || field.turbulence > 1.0) {
        throw std::invalid_argument("Field runtime turbulence 必须位于 0..1");
    }
    if (!finite(field.spatial_scale_m) || field.spatial_scale_m < 1.0e-6) {
        throw std::invalid_argument("Field runtime spatial_scale_m 必须 >= 1e-6");
    }
    if (!finite(field.temporal_frequency_hz) || field.temporal_frequency_hz < 0.0) {
        throw std::invalid_argument("Field runtime temporal_frequency_hz 必须是非负有限值");
    }
    if (!finite(field.lacunarity) || field.lacunarity < 1.0 || field.lacunarity > 8.0) {
        throw std::invalid_argument("Field runtime lacunarity 必须位于 1..8");
    }
    if (!finite(field.gain) || field.gain < 0.0 || field.gain > 1.0) {
        throw std::invalid_argument("Field runtime gain 必须位于 0..1");
    }
    if (!finite(field.blend_weight) || field.blend_weight < 0.0) {
        throw std::invalid_argument("Field runtime blend_weight 必须是非负有限值");
    }
    if (field.octaves < 1 || field.octaves > 8) {
        throw std::invalid_argument("Field runtime octaves 必须位于 1..8");
    }
    if (field.noise_algorithm_version != kWindNoiseAlgorithmVersionV0) {
        throw std::invalid_argument("Field runtime 不支持该 Wind noise algorithm version");
    }
    if (field.attenuation_policy_version != kVolumeAttenuationPolicyVersionV0) {
        throw std::invalid_argument("Field runtime 不支持该 Volume attenuation version");
    }
    if ((field.scope.collision_group_mask & ~kCollisionGroupMaskV0) != 0) {
        throw std::invalid_argument("Field runtime scope collision group mask 超出 V0 范围");
    }
    require_scope_ids(field.scope.solver_ids, "Field scope solver_ids");
    require_scope_ids(field.scope.collection_ids, "Field scope collection_ids");
    require_scope_ids(field.scope.include_ids, "Field scope include_ids");
    require_scope_ids(field.scope.exclude_ids, "Field scope exclude_ids");
}

bool scope_allows(const FieldScopeV1& scope, const FieldSampleContextV1& context) {
    if (!scope.solver_ids.empty() && !contains(scope.solver_ids, context.consumer_id)) {
        return false;
    }
    if (!scope.include_ids.empty() && !contains(scope.include_ids, context.object_id)) {
        return false;
    }
    if (!context.object_id.empty() && contains(scope.exclude_ids, context.object_id)) {
        return false;
    }
    if (!scope.collection_ids.empty() && !intersects(scope.collection_ids, context.collection_ids)) {
        return false;
    }
    if (
        scope.collision_group_mask != 0 &&
        (scope.collision_group_mask & context.collision_group_mask) == 0
    ) {
        return false;
    }
    return true;
}

std::uint64_t mix_u64(std::uint64_t value) noexcept {
    value = (value ^ (value >> 30u)) * 0xBF58476D1CE4E5B9ull;
    value = (value ^ (value >> 27u)) * 0x94D049BB133111EBull;
    return value ^ (value >> 31u);
}

double lattice_value_v0(
    const std::array<std::int64_t, 4>& coordinates,
    std::uint32_t seed_u32,
    std::size_t channel
) noexcept {
    std::uint64_t state = static_cast<std::uint64_t>(seed_u32) ^ kHashChannelSalts[channel];
    for (std::size_t axis = 0; axis < 4; ++axis) {
        const auto coordinate_bits = static_cast<std::uint64_t>(coordinates[axis]);
        const auto salted_coordinate = coordinate_bits + kHashAxisSalts[axis];
        state = mix_u64(state ^ mix_u64(salted_coordinate));
    }
    const auto mantissa = state >> 40u;
    const double inv_sqrt_three = 1.0 / std::sqrt(3.0);
    return (
        static_cast<double>(mantissa) * (2.0 / static_cast<double>(1u << 24u)) - 1.0
    ) * inv_sqrt_three;
}

std::array<double, 3> vector_value_noise4_v0(
    const std::array<double, 4>& coordinate,
    std::uint32_t seed_u32
) {
    std::array<std::int64_t, 4> base {};
    std::array<double, 4> fade {};
    const double min_lattice = -std::ldexp(1.0, 63);
    const double max_lattice = std::nextafter(std::ldexp(1.0, 63), 0.0);
    for (std::size_t axis = 0; axis < 4; ++axis) {
        if (!std::isfinite(coordinate[axis])) {
            throw std::overflow_error("Field WindV0 采样坐标产生了非有限值");
        }
        const double floored = std::floor(coordinate[axis]);
        if (floored < min_lattice || floored > max_lattice) {
            throw std::overflow_error("Field WindV0 采样坐标超出可寻址晶格范围");
        }
        base[axis] = static_cast<std::int64_t>(floored);
        const double fraction = coordinate[axis] - static_cast<double>(base[axis]);
        fade[axis] = fraction * fraction * fraction * (
            fraction * (fraction * 6.0 - 15.0) + 10.0
        );
    }

    std::array<double, 3> result {};
    for (std::uint32_t corner = 0; corner < 16; ++corner) {
        std::array<std::int64_t, 4> lattice {};
        double weight = 1.0;
        for (std::size_t axis = 0; axis < 4; ++axis) {
            const auto bit = static_cast<std::int64_t>((corner >> axis) & 1u);
            lattice[axis] = base[axis] + bit;
            weight *= bit != 0 ? fade[axis] : 1.0 - fade[axis];
        }
        for (std::size_t channel = 0; channel < 3; ++channel) {
            result[channel] += weight * lattice_value_v0(lattice, seed_u32, channel);
        }
    }
    return result;
}

float volume_weight_v0(
    const FieldDefinitionV1& field,
    const std::array<double, 3>& position
) {
    std::array<double, 3> local {};
    for (std::size_t row = 0; row < 3; ++row) {
        const std::size_t offset = row * 4;
        local[row] =
            field.world_to_local[offset] * position[0] +
            field.world_to_local[offset + 1] * position[1] +
            field.world_to_local[offset + 2] * position[2] +
            field.world_to_local[offset + 3];
    }
    if (field.volume_shape == VolumeShapeV1::Sphere) {
        const double radius = std::sqrt(
            local[0] * local[0] + local[1] * local[1] + local[2] * local[2]
        );
        return static_cast<float>(std::clamp(1.0 - radius, 0.0, 1.0));
    }
    return static_cast<float>(
        std::abs(local[0]) <= 1.0 &&
        std::abs(local[1]) <= 1.0 &&
        std::abs(local[2]) <= 1.0
    );
}

std::array<float, 3> wind_raw_v0(
    const FieldDefinitionV1& field,
    const std::array<double, 3>& position,
    double sample_time_seconds
) {
    std::array<double, 3> base {
        field.direction_world[0] * field.speed_mps,
        field.direction_world[1] * field.speed_mps,
        field.direction_world[2] * field.speed_mps,
    };
    if (field.turbulence == 0.0 || field.speed_mps == 0.0) {
        return {
            static_cast<float>(base[0]),
            static_cast<float>(base[1]),
            static_cast<float>(base[2]),
        };
    }

    std::array<double, 3> turbulence_sum {};
    double amplitude = 1.0;
    double amplitude_sum = 0.0;
    double spatial_frequency = 1.0;
    const double time_coordinate = sample_time_seconds * field.temporal_frequency_hz;
    if (!std::isfinite(time_coordinate)) {
        throw std::overflow_error("Field WindV0 时间坐标产生了非有限值");
    }
    for (std::uint32_t octave = 0; octave < field.octaves; ++octave) {
        std::array<double, 4> coordinate {
            position[0] / field.spatial_scale_m * spatial_frequency,
            position[1] / field.spatial_scale_m * spatial_frequency,
            position[2] / field.spatial_scale_m * spatial_frequency,
            time_coordinate,
        };
        const std::uint32_t octave_seed = field.seed_u32 + octave * kOctaveSeedStep;
        const auto noise = vector_value_noise4_v0(coordinate, octave_seed);
        for (std::size_t channel = 0; channel < 3; ++channel) {
            turbulence_sum[channel] += amplitude * noise[channel];
        }
        amplitude_sum += amplitude;
        amplitude *= field.gain;
        spatial_frequency *= field.lacunarity;
    }
    const double scale = field.speed_mps * field.turbulence / amplitude_sum;
    std::array<float, 3> result {};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        const double value = base[channel] + scale * turbulence_sum[channel];
        if (!std::isfinite(value)) {
            throw std::overflow_error("Field WindV0 采样产生了非有限空气速度");
        }
        result[channel] = static_cast<float>(value);
    }
    return result;
}

template<typename PositionScalar>
std::size_t sample_impl_into(
    const std::vector<FieldDefinitionV1>& fields,
    const PositionScalar* positions_world,
    std::size_t position_count,
    double sample_time_seconds,
    const std::uint32_t* particle_context_indices,
    const FieldSampleContextV1* contexts,
    std::size_t context_count,
    float* air_velocity_world,
    std::uint8_t* participation,
    FieldSampleScratchV1& scratch
) {
    if (positions_world == nullptr && position_count != 0) {
        throw std::invalid_argument("Field runtime positions_world 不能为空");
    }
    if (
        (air_velocity_world == nullptr || participation == nullptr) &&
        position_count != 0
    ) {
        throw std::invalid_argument("Field runtime 输出缓冲不能为空");
    }
    if (contexts == nullptr || context_count == 0) {
        throw std::invalid_argument("Field runtime 至少需要一个采样上下文");
    }
    if (particle_context_indices == nullptr && context_count != 1) {
        throw std::invalid_argument("多个 Field 上下文需要逐粒子 context index");
    }
    if (!std::isfinite(sample_time_seconds) || sample_time_seconds < 0.0) {
        throw std::invalid_argument("Field runtime 采样时间必须是非负有限值");
    }
    for (std::size_t context_index = 0; context_index < context_count; ++context_index) {
        const auto& context = contexts[context_index];
        if ((context.collision_group_mask & ~kCollisionGroupMaskV0) != 0) {
            throw std::invalid_argument(
                "Field sample context collision group mask 超出 V0 范围"
            );
        }
        require_scope_ids(
            context.collection_ids,
            "Field sample context collection_ids"
        );
    }

    scratch.positions.resize(position_count);
    scratch.accumulated.assign(position_count * 3, 0.0);
    scratch.participation.assign(position_count, std::uint8_t {0});
    scratch.weights.resize(position_count);
    scratch.raw_values.resize(position_count);
    scratch.scope_allowed.resize(context_count);
    for (std::size_t index = 0; index < position_count; ++index) {
        const std::size_t context_index = particle_context_indices == nullptr
            ? 0
            : static_cast<std::size_t>(particle_context_indices[index]);
        if (context_index >= context_count) {
            throw std::invalid_argument("Field particle context index 超出范围");
        }
        for (std::size_t axis = 0; axis < 3; ++axis) {
            const double value = static_cast<double>(positions_world[index * 3 + axis]);
            if (!std::isfinite(value)) {
                throw std::invalid_argument("Field runtime positions_world 必须全为有限值");
            }
            scratch.positions[index][axis] = value;
        }
    }

    std::size_t sampled_field_count = 0;

    // 固定按 Field 顺序叠加；每个 Field 只做一次 scope 判定表。
    for (const auto& field : fields) {
        bool has_allowed_context = false;
        for (std::size_t context_index = 0; context_index < context_count; ++context_index) {
            const bool allowed = scope_allows(field.scope, contexts[context_index]);
            scratch.scope_allowed[context_index] = allowed ? 1u : 0u;
            has_allowed_context = has_allowed_context || allowed;
        }
        if (!has_allowed_context) continue;

        bool has_positive_weight = false;
        for (std::size_t index = 0; index < position_count; ++index) {
            const std::size_t context_index = particle_context_indices == nullptr
                ? 0
                : static_cast<std::size_t>(particle_context_indices[index]);
            const float weight = scratch.scope_allowed[context_index] != 0u
                ? volume_weight_v0(field, scratch.positions[index])
                : 0.0f;
            scratch.weights[index] = weight;
            has_positive_weight = has_positive_weight || weight > 0.0f;
        }
        if (!has_positive_weight) continue;

        for (std::size_t index = 0; index < position_count; ++index) {
            const std::size_t context_index = particle_context_indices == nullptr
                ? 0
                : static_cast<std::size_t>(particle_context_indices[index]);
            // Volume 外的粒子贡献恒为零，尤其不能为它们执行昂贵的四维紊流采样。
            if (
                scratch.scope_allowed[context_index] != 0u &&
                scratch.weights[index] > 0.0f
            ) {
                scratch.raw_values[index] = wind_raw_v0(
                    field, scratch.positions[index], sample_time_seconds
                );
            } else {
                scratch.raw_values[index] = {};
            }
        }
        for (std::size_t index = 0; index < position_count; ++index) {
            if (scratch.weights[index] > 0.0f && field.blend_weight > 0.0) {
                scratch.participation[index] = 1;
            }
            for (std::size_t channel = 0; channel < 3; ++channel) {
                const double contribution =
                    static_cast<double>(scratch.raw_values[index][channel]) *
                    static_cast<double>(scratch.weights[index]) *
                    field.blend_weight;
                if (!std::isfinite(contribution)) {
                    throw std::overflow_error("Field runtime contribution 产生了非有限值");
                }
                scratch.accumulated[index * 3 + channel] += contribution;
                if (!std::isfinite(scratch.accumulated[index * 3 + channel])) {
                    throw std::overflow_error("Field runtime 空气速度叠加产生了非有限值");
                }
            }
        }
        ++sampled_field_count;
    }

    const double max_float = static_cast<double>(
        std::numeric_limits<float>::max()
    );
    for (double value : scratch.accumulated) {
        if (!std::isfinite(value) || std::abs(value) > max_float) {
            throw std::overflow_error(
                "Field runtime 空气速度超出 float32 可表示范围"
            );
        }
    }
    // 整批通过后才写 caller buffer，异常不能留下半提交的采样结果。
    for (std::size_t index = 0; index < position_count * 3; ++index) {
        air_velocity_world[index] = static_cast<float>(scratch.accumulated[index]);
    }
    if (position_count != 0) {
        std::copy_n(scratch.participation.data(), position_count, participation);
    }
    return sampled_field_count;
}

template<typename PositionScalar>
FieldSampleOutputV1 sample_impl(
    const std::vector<FieldDefinitionV1>& fields,
    const PositionScalar* positions_world,
    std::size_t position_count,
    double sample_time_seconds,
    const FieldSampleContextV1& context
) {
    FieldSampleOutputV1 output;
    output.air_velocity_world.resize(position_count * 3);
    output.participation.resize(position_count);
    FieldSampleScratchV1 scratch;
    output.sampled_field_count = sample_impl_into(
        fields,
        positions_world,
        position_count,
        sample_time_seconds,
        nullptr,
        &context,
        1,
        output.air_velocity_world.data(),
        output.participation.data(),
        scratch
    );
    return output;
}

}  // namespace

FieldRuntimeV1::FieldRuntimeV1(
    std::uint32_t abi_version,
    std::string snapshot_signature,
    std::string config_signature,
    std::string value_signature,
    std::int64_t generation,
    std::int64_t frame,
    double sample_time_seconds,
    std::vector<FieldDefinitionV1> fields
) :
    abi_version_(abi_version),
    snapshot_signature_(std::move(snapshot_signature)),
    config_signature_(std::move(config_signature)),
    value_signature_(std::move(value_signature)),
    generation_(generation),
    frame_(frame),
    sample_time_seconds_(sample_time_seconds),
    fields_(std::move(fields)) {
    if (abi_version_ != kRuntimeAbiVersionV1) {
        throw std::invalid_argument("Field runtime ABI version 不受支持");
    }
    require_metadata(snapshot_signature_, generation_, sample_time_seconds_);
    if (config_signature_.empty() || value_signature_.empty()) {
        throw std::invalid_argument("Field runtime config/value signature 不能为空");
    }
    std::unordered_set<std::string> field_ids;
    for (auto& field : fields_) {
        validate_and_normalize_field(field);
        if (!field_ids.insert(field.field_id).second) {
            throw std::invalid_argument("Field runtime 不允许重复 field_id");
        }
    }
}

void FieldRuntimeV1::update_frame(
    std::string snapshot_signature,
    std::int64_t generation,
    std::int64_t frame,
    double sample_time_seconds
) {
    require_metadata(snapshot_signature, generation, sample_time_seconds);
    snapshot_signature_ = std::move(snapshot_signature);
    generation_ = generation;
    frame_ = frame;
    sample_time_seconds_ = sample_time_seconds;
}

FieldSampleOutputV1 FieldRuntimeV1::sample_air_velocity(
    const double* positions_world,
    std::size_t position_count,
    double sample_time_seconds,
    const FieldSampleContextV1& context
) const {
    return sample_impl(fields_, positions_world, position_count, sample_time_seconds, context);
}

FieldSampleOutputV1 FieldRuntimeV1::sample_air_velocity(
    const float* positions_world,
    std::size_t position_count,
    double sample_time_seconds,
    const FieldSampleContextV1& context
) const {
    return sample_impl(fields_, positions_world, position_count, sample_time_seconds, context);
}

std::size_t FieldRuntimeV1::sample_air_velocity_partitioned_into(
    const float* positions_world,
    std::size_t position_count,
    double sample_time_seconds,
    const std::uint32_t* particle_context_indices,
    const FieldSampleContextV1* contexts,
    std::size_t context_count,
    float* air_velocity_world,
    std::uint8_t* participation,
    FieldSampleScratchV1& scratch
) const {
    return sample_impl_into(
        fields_,
        positions_world,
        position_count,
        sample_time_seconds,
        particle_context_indices,
        contexts,
        context_count,
        air_velocity_world,
        participation,
        scratch
    );
}

bool FieldRuntimeV1::has_allowed_scope(
    const FieldSampleContextV1* contexts,
    std::size_t context_count
) const {
    if (contexts == nullptr || context_count == 0) {
        throw std::invalid_argument("Field runtime 至少需要一个采样上下文");
    }
    for (std::size_t context_index = 0; context_index < context_count; ++context_index) {
        for (const auto& field : fields_) {
            if (scope_allows(field.scope, contexts[context_index])) return true;
        }
    }
    return false;
}

}  // namespace hotools::field_runtime
