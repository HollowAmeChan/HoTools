#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace hotools::mc2_domain_cpu {

struct ProgramViewV1 {
    std::uint32_t schema_version = 0;
    std::size_t particle_count = 0;
    const float* bind_positions = nullptr;
    const float* bind_rotations = nullptr;
    const char* domain_signature = nullptr;
    const char* layout_signature = nullptr;
};

struct FrameViewV1 {
    std::size_t particle_count = 0;
    const float* world_positions = nullptr;
    const float* world_normals = nullptr;
    std::int64_t frame = 0;
    std::int64_t generation = 0;
    const char* domain_signature = nullptr;
    const char* layout_signature = nullptr;
};

class DomainV1 {
public:
    explicit DomainV1(const ProgramViewV1& program);
    ~DomainV1() = default;

    DomainV1(const DomainV1&) = delete;
    DomainV1& operator=(const DomainV1&) = delete;

    void update_frame(const FrameViewV1& frame);
    void step();
    void configure_distance(
        const std::int32_t* starts,
        const std::int32_t* counts,
        const std::int32_t* neighbors,
        const float* rest_lengths,
        const float* stiffness_values,
        std::size_t neighbor_count
    );
    void step_distance();
    void configure_inertia(
        const float* depths,
        const float* inv_masses
    );
    void step_inertia(
        const float* old_world_position,
        const float* step_vector,
        const float* step_rotation,
        const float* inertia_vector,
        const float* inertia_rotation,
        float depth_inertia
    );
    void dispose() noexcept;

    bool disposed() const noexcept { return disposed_; }
    std::size_t particle_count() const noexcept { return particle_count_; }
    std::int64_t frame() const noexcept { return frame_; }
    std::int64_t generation() const noexcept { return generation_; }
    std::int64_t step_count() const noexcept { return step_count_; }
    const std::string& domain_signature() const noexcept { return domain_signature_; }
    const std::string& layout_signature() const noexcept { return layout_signature_; }
    const std::vector<float>& world_positions() const noexcept { return world_positions_; }
    const std::vector<float>& world_normals() const noexcept { return world_normals_; }

private:
    void ensure_live() const;
    void validate_identity(const char* domain_signature, const char* layout_signature) const;

    std::size_t particle_count_ = 0;
    std::string domain_signature_;
    std::string layout_signature_;
    std::vector<float> bind_positions_;
    std::vector<float> bind_rotations_;
    std::vector<float> world_positions_;
    std::vector<float> world_normals_;
    std::vector<float> velocity_positions_;
    std::vector<std::int32_t> distance_starts_;
    std::vector<std::int32_t> distance_counts_;
    std::vector<std::int32_t> distance_neighbors_;
    std::vector<float> distance_rest_lengths_;
    std::vector<float> distance_stiffness_values_;
    bool distance_ready_ = false;
    std::vector<float> inertia_depths_;
    std::vector<float> inertia_inv_masses_;
    bool inertia_ready_ = false;
    std::int64_t frame_ = -1;
    std::int64_t generation_ = -1;
    std::int64_t step_count_ = 0;
    bool disposed_ = false;
};

}  // namespace hotools::mc2_domain_cpu
