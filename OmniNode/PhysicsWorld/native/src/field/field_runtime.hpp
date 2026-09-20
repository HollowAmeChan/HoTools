#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace hotools::field_runtime {

inline constexpr std::uint32_t kRuntimeAbiVersionV1 = 1;
inline constexpr std::uint32_t kWindNoiseAlgorithmVersionV0 = 0;
inline constexpr std::uint32_t kVolumeAttenuationPolicyVersionV0 = 0;
inline constexpr std::uint32_t kCollisionGroupMaskV0 = 0xFFFFu;

enum class FieldTypeV1 : std::int32_t {
    Wind = 0,
};

enum class VolumeShapeV1 : std::int32_t {
    Sphere = 0,
    Box = 1,
};

struct FieldScopeV1 {
    std::vector<std::string> solver_ids;
    std::vector<std::string> collection_ids;
    std::vector<std::string> include_ids;
    std::vector<std::string> exclude_ids;
    std::uint32_t collision_group_mask = 0;
};

struct FieldDefinitionV1 {
    std::string field_id;
    FieldTypeV1 field_type = FieldTypeV1::Wind;
    VolumeShapeV1 volume_shape = VolumeShapeV1::Sphere;
    std::array<double, 16> world_to_local {};
    std::array<double, 3> direction_world {};
    double speed_mps = 0.0;
    double turbulence = 0.0;
    double spatial_scale_m = 1.0;
    double temporal_frequency_hz = 0.0;
    double lacunarity = 2.0;
    double gain = 0.5;
    double blend_weight = 1.0;
    std::uint32_t octaves = 1;
    std::uint32_t seed_u32 = 0;
    std::uint32_t noise_algorithm_version = kWindNoiseAlgorithmVersionV0;
    std::uint32_t attenuation_policy_version = kVolumeAttenuationPolicyVersionV0;
    FieldScopeV1 scope;
};

struct FieldSampleContextV1 {
    std::string consumer_id;
    std::string object_id;
    std::vector<std::string> collection_ids;
    std::uint32_t collision_group_mask = 0;
};

struct FieldSampleOutputV1 {
    std::vector<float> air_velocity_world;
    std::vector<std::uint8_t> participation;
    std::size_t sampled_field_count = 0;
};

struct FieldSampleScratchV1 {
    std::vector<std::array<double, 3>> positions;
    std::vector<double> accumulated;
    std::vector<std::uint8_t> participation;
    std::vector<float> weights;
    std::vector<std::array<float, 3>> raw_values;
    std::vector<std::uint8_t> scope_allowed;
};

class FieldRuntimeV1 final {
public:
    FieldRuntimeV1(
        std::uint32_t abi_version,
        std::string snapshot_signature,
        std::string config_signature,
        std::string value_signature,
        std::int64_t generation,
        std::int64_t frame,
        double sample_time_seconds,
        std::vector<FieldDefinitionV1> fields
    );

    FieldRuntimeV1(const FieldRuntimeV1&) = delete;
    FieldRuntimeV1& operator=(const FieldRuntimeV1&) = delete;
    FieldRuntimeV1(FieldRuntimeV1&&) = delete;
    FieldRuntimeV1& operator=(FieldRuntimeV1&&) = delete;

    void update_frame(
        std::string snapshot_signature,
        std::int64_t generation,
        std::int64_t frame,
        double sample_time_seconds
    );

    FieldSampleOutputV1 sample_air_velocity(
        const double* positions_world,
        std::size_t position_count,
        double sample_time_seconds,
        const FieldSampleContextV1& context
    ) const;

    // 调用方持有输出与 scratch；solver 热路径可在预热后避免 N 规模分配。
    std::size_t sample_air_velocity_partitioned_into(
        const float* positions_world,
        std::size_t position_count,
        double sample_time_seconds,
        const std::uint32_t* particle_context_indices,
        const FieldSampleContextV1* contexts,
        std::size_t context_count,
        float* air_velocity_world,
        std::uint8_t* participation,
        FieldSampleScratchV1& scratch
    ) const;

    // 在进入 N 粒子路径前判断至少一个 consumer context 是否能看到任一 Field。
    bool has_allowed_scope(
        const FieldSampleContextV1* contexts,
        std::size_t context_count
    ) const;

    // MC2 后续可直接传入其 float32 粒子位置，不需要经过 Python readback。
    FieldSampleOutputV1 sample_air_velocity(
        const float* positions_world,
        std::size_t position_count,
        double sample_time_seconds,
        const FieldSampleContextV1& context
    ) const;

    std::uint32_t abi_version() const noexcept { return abi_version_; }
    const std::string& snapshot_signature() const noexcept { return snapshot_signature_; }
    const std::string& config_signature() const noexcept { return config_signature_; }
    const std::string& value_signature() const noexcept { return value_signature_; }
    std::int64_t generation() const noexcept { return generation_; }
    std::int64_t frame() const noexcept { return frame_; }
    double sample_time_seconds() const noexcept { return sample_time_seconds_; }
    const std::vector<FieldDefinitionV1>& fields() const noexcept { return fields_; }

private:
    std::uint32_t abi_version_ = kRuntimeAbiVersionV1;
    std::string snapshot_signature_;
    std::string config_signature_;
    std::string value_signature_;
    std::int64_t generation_ = 0;
    std::int64_t frame_ = 0;
    double sample_time_seconds_ = 0.0;
    std::vector<FieldDefinitionV1> fields_;
};

// 进程内公共 registry 使用单调 ID；native consumer 必须持有调用期租约。
// 句柄注销只会阻止新的借用，不能销毁仍在执行中的采样对象。
std::uint64_t register_runtime_v1(std::unique_ptr<FieldRuntimeV1> runtime);
std::shared_ptr<FieldRuntimeV1> acquire_registered_runtime_v1(std::uint64_t handle);
bool dispose_registered_runtime_v1(std::uint64_t handle) noexcept;
std::size_t live_runtime_count_v1() noexcept;
std::uint64_t next_runtime_handle_v1() noexcept;

}  // namespace hotools::field_runtime
