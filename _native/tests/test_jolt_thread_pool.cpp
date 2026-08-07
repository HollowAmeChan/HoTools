// Jolt 线程池独立探针。
// 该程序不加载 Python，专门验证 JobSystemThreadPool 的初始化、Update 和析构边界。

#ifndef NOMINMAX
#  define NOMINMAX
#endif
#include <Jolt/Jolt.h>

JPH_SUPPRESS_WARNINGS

#include <Jolt/Core/Factory.h>
#include <Jolt/Core/JobSystemThreadPool.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Body/BodyInterface.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <Jolt/RegisterTypes.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace JPH;

namespace {

namespace Layers {
static constexpr ObjectLayer NonMoving = 0;
static constexpr ObjectLayer Moving = 1;
static constexpr uint NumLayers = 2;
}

namespace BroadPhaseLayers {
static constexpr BroadPhaseLayer NonMoving{0};
static constexpr BroadPhaseLayer Moving{1};
static constexpr uint NumLayers = 2;
}

class ProbeBroadPhaseLayerInterface final : public BroadPhaseLayerInterface {
public:
    ProbeBroadPhaseLayerInterface() {
        mObjectToBroadPhase[Layers::NonMoving] = BroadPhaseLayers::NonMoving;
        mObjectToBroadPhase[Layers::Moving] = BroadPhaseLayers::Moving;
    }

    uint GetNumBroadPhaseLayers() const override { return BroadPhaseLayers::NumLayers; }

    BroadPhaseLayer GetBroadPhaseLayer(ObjectLayer inLayer) const override {
        return mObjectToBroadPhase[inLayer];
    }

#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char *GetBroadPhaseLayerName(BroadPhaseLayer inLayer) const override {
        return inLayer == BroadPhaseLayers::NonMoving ? "NonMoving" : "Moving";
    }
#endif

private:
    BroadPhaseLayer mObjectToBroadPhase[Layers::NumLayers]{};
};

class ProbeObjectVsBroadPhaseFilter final : public ObjectVsBroadPhaseLayerFilter {
public:
    bool ShouldCollide(ObjectLayer inLayer, BroadPhaseLayer inBroadPhaseLayer) const override {
        if (inLayer == Layers::NonMoving)
            return inBroadPhaseLayer == BroadPhaseLayers::Moving;
        return true;
    }
};

class ProbeObjectLayerPairFilter final : public ObjectLayerPairFilter {
public:
    bool ShouldCollide(ObjectLayer inObject1, ObjectLayer inObject2) const override {
        return inObject1 != Layers::NonMoving || inObject2 != Layers::NonMoving;
    }
};

void initialize_jolt() {
    RegisterDefaultAllocator();
    Factory::sInstance = new Factory();
    RegisterTypes();
}

bool finite_position(const RVec3 &inPosition) {
    return std::isfinite(double(inPosition.GetX()))
        && std::isfinite(double(inPosition.GetY()))
        && std::isfinite(double(inPosition.GetZ()));
}

double run_case(int inWorkerCount, int inBodyCount) {
    constexpr uint max_physics_jobs = 4096;
    constexpr uint max_physics_barriers = 256;
    ProbeBroadPhaseLayerInterface broad_phase_layers;
    ProbeObjectVsBroadPhaseFilter object_vs_broad_phase;
    ProbeObjectLayerPairFilter object_layer_pairs;
    TempAllocatorImpl temp_allocator(32 * 1024 * 1024);
    JobSystemThreadPool job_system(max_physics_jobs, max_physics_barriers, inWorkerCount);
    PhysicsSystem physics;
    physics.Init(
        uint(std::max(inBodyCount + 1, 128)),
        0,
        uint(std::max(inBodyCount * 8, 1024)),
        uint(std::max(inBodyCount * 4, 512)),
        broad_phase_layers,
        object_vs_broad_phase,
        object_layer_pairs
    );
    physics.SetGravity(Vec3(0.0f, 0.0f, -9.81f));

    BodyInterface &body_interface = physics.GetBodyInterface();
    BodyCreationSettings floor_settings(
        new BoxShape(Vec3(50.0f, 50.0f, 0.5f)),
        RVec3(0.0, 0.0, -0.5),
        Quat::sIdentity(),
        EMotionType::Static,
        Layers::NonMoving
    );
    const BodyID floor_id = body_interface.CreateAndAddBody(floor_settings, EActivation::DontActivate);
    if (floor_id.IsInvalid())
        throw std::runtime_error("failed to create floor");

    std::vector<BodyID> body_ids;
    body_ids.reserve(size_t(inBodyCount));
    const int side = std::max(1, int(std::ceil(std::sqrt(double(inBodyCount)))));
    for (int index = 0; index < inBodyCount; ++index) {
        const int x = index % side;
        const int y = index / side;
        BodyCreationSettings body_settings(
            new SphereShape(0.22f),
            RVec3(float((x - side / 2) * 0.55f), float((y - side / 2) * 0.55f), 2.0f + float(index / side) * 0.55f),
            Quat::sIdentity(),
            EMotionType::Dynamic,
            Layers::Moving
        );
        const BodyID body_id = body_interface.CreateAndAddBody(body_settings, EActivation::Activate);
        if (body_id.IsInvalid())
            throw std::runtime_error("failed to create dynamic body");
        body_ids.push_back(body_id);
    }

    constexpr int step_count = 120;
    const auto start = std::chrono::steady_clock::now();
    for (int step = 0; step < step_count; ++step)
        physics.Update(1.0f / 60.0f, 1, &temp_allocator, &job_system);
    const auto end = std::chrono::steady_clock::now();

    for (const BodyID &body_id : body_ids) {
        if (!finite_position(body_interface.GetPosition(body_id)))
            throw std::runtime_error("non-finite body position");
    }

    body_interface.RemoveBodies(body_ids.data(), int(body_ids.size()));
    body_interface.DestroyBodies(body_ids.data(), int(body_ids.size()));
    body_interface.RemoveBody(floor_id);
    body_interface.DestroyBody(floor_id);

    return std::chrono::duration<double, std::milli>(end - start).count();
}

} // namespace

int main(int argc, char **argv) {
    try {
        initialize_jolt();
        const int body_count = argc > 1 ? std::max(8, std::atoi(argv[1])) : 256;
        const uint hardware_threads = std::max(1u, std::thread::hardware_concurrency());
        const int max_workers = std::max(1, int(hardware_threads > 1 ? hardware_threads - 1 : 1));
        std::vector<int> worker_counts{1};
        if (max_workers >= 2)
            worker_counts.push_back(2);
        if (max_workers >= 4)
            worker_counts.push_back(4);

        for (int workers : worker_counts) {
            const double elapsed_ms = run_case(workers, body_count);
            std::cout << "workers=" << workers << " bodies=" << body_count
                      << " steps=120 elapsed_ms=" << elapsed_ms << '\n';
        }
        return EXIT_SUCCESS;
    } catch (const std::exception &error) {
        std::cerr << "Jolt thread probe failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
