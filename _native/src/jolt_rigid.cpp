/**
 * jolt_rigid.cpp — Jolt Physics nanobind 绑定
 *
 * 暴露给 Python 的模块名：hotools_jolt
 * 主要类型：JoltWorld — 管理一个 Jolt PhysicsSystem 实例
 *
 * 设计原则（对应 HoTools Phase 5 要求）：
 * - JoltWorld 实例只挂在 world.backend_resources["rigid_solver"]，不做全局单例。
 * - body_id / constraint_id 只保存在 rigid solver slot，不写回 Blender 对象。
 * - 公开 API 使用 HoTools 语义（body_type / shape_type），不暴露 Jolt 内部类型名。
 * - dispose 顺序：先 remove 所有 constraints，再 remove 所有 bodies，最后销毁 world。
 */

// Jolt 必须在任何 STL 之前被包含
#include <Jolt/Jolt.h>

JPH_SUPPRESS_WARNINGS

#include <Jolt/RegisterTypes.h>
#include <Jolt/Core/Factory.h>
#include <Jolt/Core/TempAllocator.h>
#include <Jolt/Core/JobSystemSingleThreaded.h>
#include <Jolt/Physics/PhysicsSettings.h>
#include <Jolt/Physics/PhysicsSystem.h>
#include <Jolt/Physics/Body/BodyCreationSettings.h>
#include <Jolt/Physics/Body/BodyInterface.h>
#include <Jolt/Physics/Collision/Shape/BoxShape.h>
#include <Jolt/Physics/Collision/Shape/SphereShape.h>
#include <Jolt/Physics/Collision/Shape/CapsuleShape.h>
#include <Jolt/Physics/Constraints/FixedConstraint.h>
#include <Jolt/Physics/Constraints/HingeConstraint.h>
#include <Jolt/Physics/Constraints/SliderConstraint.h>
#include <Jolt/Physics/Constraints/ConeConstraint.h>
#include <Jolt/Physics/Constraints/PointConstraint.h>

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/unordered_map.h>

#include <array>
#include <atomic>
#include <chrono>
#include <stdexcept>
#include <string>
#include <unordered_map>

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#endif

namespace nb = nanobind;
using namespace JPH;

// ---------------------------------------------------------------------------
// Jolt 全局初始化（lock-free，规避 tbbmalloc_proxy 干扰 MSVCP CRT mutex）
// ---------------------------------------------------------------------------

// 用原子状态替代 std::once_flag，完全避免 MSVCP140 的 Mtx_trylock 路径
// 0 = 未初始化  1 = 初始化中  2 = 已完成
static std::atomic<int> g_jolt_init_state{0};

static void ensure_jolt_initialized() {
    if (g_jolt_init_state.load(std::memory_order_acquire) == 2)
        return;
    int expected = 0;
    if (g_jolt_init_state.compare_exchange_strong(
            expected, 1, std::memory_order_acq_rel)) {
        // 赢得初始化权
        RegisterDefaultAllocator();
        Factory::sInstance = new Factory();
        RegisterTypes();
        g_jolt_init_state.store(2, std::memory_order_release);
    } else {
        // 另一个线程正在初始化，自旋等待（单进程内极少发生）
        while (g_jolt_init_state.load(std::memory_order_acquire) < 2) {}
    }
}

// ---------------------------------------------------------------------------
// 物理层设置（2 层：静止 / 运动中）
// ---------------------------------------------------------------------------

namespace HoLayers {
    static constexpr ObjectLayer NON_MOVING = 0;
    static constexpr ObjectLayer MOVING     = 1;
    static constexpr uint32_t    NUM_LAYERS = 2;
}

namespace HoBPLayers {
    static constexpr BroadPhaseLayer NON_MOVING{0};
    static constexpr BroadPhaseLayer MOVING{1};
    static constexpr uint32_t        NUM_LAYERS = 2;
}

class HoBPLayerInterface final : public BroadPhaseLayerInterface {
public:
    HoBPLayerInterface() {
        mObjToBP[HoLayers::NON_MOVING] = HoBPLayers::NON_MOVING;
        mObjToBP[HoLayers::MOVING]     = HoBPLayers::MOVING;
    }
    uint GetNumBroadPhaseLayers() const override {
        return HoBPLayers::NUM_LAYERS;
    }
    BroadPhaseLayer GetBroadPhaseLayer(ObjectLayer layer) const override {
        return mObjToBP[layer];
    }
#if defined(JPH_EXTERNAL_PROFILE) || defined(JPH_PROFILE_ENABLED)
    const char* GetBroadPhaseLayerName(BroadPhaseLayer layer) const override {
        return (layer == HoBPLayers::NON_MOVING) ? "NON_MOVING" : "MOVING";
    }
#endif
private:
    BroadPhaseLayer mObjToBP[HoLayers::NUM_LAYERS];
};

class HoObjVsBPFilter final : public ObjectVsBroadPhaseLayerFilter {
public:
    bool ShouldCollide(ObjectLayer obj, BroadPhaseLayer bp) const override {
        if (obj == HoLayers::NON_MOVING)
            return bp == HoBPLayers::MOVING;
        return true; // MOVING collides with everything
    }
};

class HoObjLayerFilter final : public ObjectLayerPairFilter {
public:
    bool ShouldCollide(ObjectLayer a, ObjectLayer b) const override {
        if (a == HoLayers::NON_MOVING && b == HoLayers::NON_MOVING)
            return false; // 静态-静态不碰
        return true;
    }
};

// ---------------------------------------------------------------------------
// 辅助：Python tuple → Jolt Vec3 / Quat
// ---------------------------------------------------------------------------

static RVec3 to_vec3(const std::array<float, 3>& v) {
    return RVec3(v[0], v[1], v[2]);
}

static Quat to_quat(const std::array<float, 4>& q) {
    // 传入顺序 (w, x, y, z)
    return Quat(q[1], q[2], q[3], q[0]);
}

static std::array<float, 3> from_vec3(RVec3 v) {
    return {static_cast<float>(v.GetX()),
            static_cast<float>(v.GetY()),
            static_cast<float>(v.GetZ())};
}

static std::array<float, 4> from_quat(Quat q) {
    // 返回顺序 (w, x, y, z)
    return {q.GetW(), q.GetX(), q.GetY(), q.GetZ()};
}

// ---------------------------------------------------------------------------
// JoltWorld — 封装单个 Jolt PhysicsSystem
// ---------------------------------------------------------------------------

struct BodyRecord {
    BodyID  id;
    EMotionType motion_type;
};

class JoltWorld {
public:
    explicit JoltWorld(uint32_t max_bodies = 2048,
                       uint32_t max_body_pairs = 4096,
                       uint32_t max_contact_constraints = 2048)
    {
        // ensure_jolt_initialized() 已在模块加载时调用，此处为保险再调一次（幂等）
        ensure_jolt_initialized();
        mTempAllocator = std::make_unique<TempAllocatorImpl>(8 * 1024 * 1024);
        mJobSystem     = std::make_unique<JobSystemSingleThreaded>(cMaxPhysicsJobs);
        mPhysicsSystem = std::make_unique<PhysicsSystem>();
        mPhysicsSystem->Init(
            max_bodies, 0,
            max_body_pairs,
            max_contact_constraints,
            mBPLayerInterface,
            mObjVsBPFilter,
            mObjLayerFilter
        );
        mPhysicsSystem->SetGravity(Vec3(0.f, -9.81f, 0.f));
        fprintf(stderr, "[HoJolt] ctor done\n"); fflush(stderr);
    }

    ~JoltWorld() { clear(); }

    // ---- Body management -----------------------------------------------

    uint32_t add_body(
        const std::string&        body_type_str,
        float                     mass,
        float                     friction,
        float                     restitution,
        const std::array<float,3>& position,
        const std::array<float,4>& rotation_wxyz,   // (w,x,y,z)
        const std::string&        shape_type_str,
        float                     shape_radius,      // SPHERE / CAPSULE
        float                     shape_half_height, // CAPSULE
        const std::array<float,3>& shape_half_extents // BOX
    )
    {
        // 形状
        Ref<Shape> shape;
        if (shape_type_str == "SPHERE") {
            shape = new SphereShape(shape_radius);
        } else if (shape_type_str == "CAPSULE") {
            shape = new CapsuleShape(shape_half_height, shape_radius);
        } else { // BOX (default)
            shape = new BoxShape(Vec3(shape_half_extents[0],
                                     shape_half_extents[1],
                                     shape_half_extents[2]));
        }

        // 运动类型
        EMotionType motion = EMotionType::Dynamic;
        ObjectLayer layer  = HoLayers::MOVING;
        if (body_type_str == "STATIC") {
            motion = EMotionType::Static;
            layer  = HoLayers::NON_MOVING;
        } else if (body_type_str == "KINEMATIC") {
            motion = EMotionType::Kinematic;
        }

        BodyCreationSettings settings(
            shape,
            to_vec3(position),
            to_quat(rotation_wxyz),
            motion,
            layer
        );
        settings.mFriction    = friction;
        settings.mRestitution = restitution;
        if (motion == EMotionType::Dynamic && mass > 0.f)
            settings.mMassPropertiesOverride.mMass = mass;

        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        Body* body = bi.CreateBody(settings);
        if (!body)
            throw std::runtime_error("Jolt CreateBody failed（超出 max_bodies？）");

        bi.AddBody(body->GetID(), EActivation::Activate);

        uint32_t handle = mNextHandle++;
        mBodies[handle] = {body->GetID(), motion};
        return handle;
    }

    void remove_body(uint32_t handle) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end()) return;
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        bi.RemoveBody(it->second.id);
        bi.DestroyBody(it->second.id);
        mBodies.erase(it);
    }

    // 运动学 body 每帧由动画驱动
    void set_kinematic_transform(
        uint32_t                  handle,
        const std::array<float,3>& position,
        const std::array<float,4>& rotation_wxyz,
        float                     dt
    ) {
        auto it = mBodies.find(handle);
        if (it == mBodies.end()) return;
        mPhysicsSystem->GetBodyInterface().MoveKinematic(
            it->second.id, to_vec3(position), to_quat(rotation_wxyz), dt);
    }

    std::tuple<std::array<float,3>, std::array<float,4>>
    get_body_transform(uint32_t handle) const {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            return {{0,0,0}, {1,0,0,0}};
        RVec3 pos; Quat rot;
        mPhysicsSystem->GetBodyInterface().GetPositionAndRotation(
            it->second.id, pos, rot);
        return {from_vec3(pos), from_quat(rot)};
    }

    // ---- Constraint management -----------------------------------------

    uint32_t add_constraint(
        const std::string&        constraint_type_str,
        uint32_t                  body_a_handle,
        uint32_t                  body_b_handle,
        const std::array<float,3>& anchor_pos,
        const std::array<float,4>& anchor_rot_wxyz   // (w,x,y,z)
    ) {
        BodyID id_a = body_a_handle == UINT32_MAX
            ? Body::sFixedToWorld.GetID()
            : lookup_body_id(body_a_handle);
        BodyID id_b = body_b_handle == UINT32_MAX
            ? Body::sFixedToWorld.GetID()
            : lookup_body_id(body_b_handle);

        RVec3 pos = to_vec3(anchor_pos);
        Quat  rot = to_quat(anchor_rot_wxyz);

        Ref<TwoBodyConstraint> c;
        if (constraint_type_str == "FIXED") {
            FixedConstraintSettings s;
            s.mAutoDetectPoint = false;
            s.mPoint1 = s.mPoint2 = pos;
            s.mAxisX1 = s.mAxisX2 = rot.RotateAxisX();
            s.mAxisY1 = s.mAxisY2 = rot.RotateAxisY();
            c = static_cast<TwoBodyConstraint*>(
                    s.Create(*get_body(id_a), *get_body(id_b)));
        } else if (constraint_type_str == "HINGE") {
            HingeConstraintSettings s;
            s.mPoint1 = s.mPoint2 = pos;
            s.mHingeAxis1 = s.mHingeAxis2 = rot.RotateAxisZ();
            s.mNormalAxis1 = s.mNormalAxis2 = rot.RotateAxisX();
            c = static_cast<TwoBodyConstraint*>(
                    s.Create(*get_body(id_a), *get_body(id_b)));
        } else if (constraint_type_str == "SLIDER") {
            SliderConstraintSettings s;
            s.mAutoDetectPoint = false;
            s.mPoint1 = s.mPoint2 = pos;
            s.mSliderAxis1 = s.mSliderAxis2 = rot.RotateAxisZ();
            s.mNormalAxis1 = s.mNormalAxis2 = rot.RotateAxisX();
            c = static_cast<TwoBodyConstraint*>(
                    s.Create(*get_body(id_a), *get_body(id_b)));
        } else if (constraint_type_str == "CONE") {
            ConeConstraintSettings s;
            s.mPoint1 = s.mPoint2 = pos;
            s.mTwistAxis1 = s.mTwistAxis2 = rot.RotateAxisZ();
            c = static_cast<TwoBodyConstraint*>(
                    s.Create(*get_body(id_a), *get_body(id_b)));
        } else { // POINT
            PointConstraintSettings s;
            s.mPoint1 = s.mPoint2 = pos;
            c = static_cast<TwoBodyConstraint*>(
                    s.Create(*get_body(id_a), *get_body(id_b)));
        }

        mPhysicsSystem->AddConstraint(c);
        uint32_t handle = mNextHandle++;
        mConstraints[handle] = c;
        return handle;
    }

    void remove_constraint(uint32_t handle) {
        auto it = mConstraints.find(handle);
        if (it == mConstraints.end()) return;
        mPhysicsSystem->RemoveConstraint(it->second);
        mConstraints.erase(it);
    }

    // ---- Simulation step -----------------------------------------------

    float step(float dt, int substeps) {
        auto t0 = std::chrono::high_resolution_clock::now();
        mPhysicsSystem->Update(dt, substeps, mTempAllocator.get(), mJobSystem.get());
        auto t1 = std::chrono::high_resolution_clock::now();
        return std::chrono::duration<float, std::milli>(t1 - t0).count();
    }

    // ---- Info ------------------------------------------------------

    uint32_t body_count()       const { return static_cast<uint32_t>(mBodies.size()); }
    uint32_t constraint_count() const { return static_cast<uint32_t>(mConstraints.size()); }

    void set_gravity(const std::array<float,3>& g) {
        mPhysicsSystem->SetGravity(Vec3(g[0], g[1], g[2]));
    }

    void clear() {
        BodyInterface& bi = mPhysicsSystem->GetBodyInterface();
        for (auto& [h, r] : mBodies) {
            bi.RemoveBody(r.id);
            bi.DestroyBody(r.id);
        }
        mBodies.clear();
        for (auto& [h, c] : mConstraints)
            mPhysicsSystem->RemoveConstraint(c);
        mConstraints.clear();
    }

private:
    BodyID lookup_body_id(uint32_t handle) const {
        auto it = mBodies.find(handle);
        if (it == mBodies.end())
            throw std::runtime_error("无效的 body handle");
        return it->second.id;
    }

    Body* get_body(BodyID id) const {
        // BodyInterface 只提供 lock/unlock，直接用 BodyLockInterface
        BodyLockRead lock(mPhysicsSystem->GetBodyLockInterface(), id);
        if (!lock.Succeeded())
            throw std::runtime_error("无法锁定 Jolt Body");
        return const_cast<Body*>(&lock.GetBody());
    }

    HoBPLayerInterface  mBPLayerInterface;
    HoObjVsBPFilter     mObjVsBPFilter;
    HoObjLayerFilter    mObjLayerFilter;

    std::unique_ptr<TempAllocatorImpl>        mTempAllocator;
    std::unique_ptr<JobSystemSingleThreaded>  mJobSystem;
    std::unique_ptr<PhysicsSystem>            mPhysicsSystem;

    std::unordered_map<uint32_t, BodyRecord>           mBodies;
    std::unordered_map<uint32_t, Ref<TwoBodyConstraint>> mConstraints;
    uint32_t mNextHandle = 1; // 0 保留为 invalid
};

// ---------------------------------------------------------------------------
// nanobind 模块
// ---------------------------------------------------------------------------

NB_MODULE(hotools_jolt, m) {
    m.doc() = "HoTools Jolt Physics binding（nanobind）";

    // tbbmalloc_proxy compatibility warmup: force Win32 thread primitives to initialize
    // before any Jolt call, ensuring CRITICAL_SECTION/SRWLOCK state is valid.
#ifdef _WIN32
    {
        CRITICAL_SECTION cs;
        InitializeCriticalSection(&cs);
        EnterCriticalSection(&cs);
        LeaveCriticalSection(&cs);
        DeleteCriticalSection(&cs);
    }
#endif

    // Initialize Jolt eagerly at module import time (not lazily in JoltWorld constructor)
    ensure_jolt_initialized();

    nb::class_<JoltWorld>(m, "JoltWorld")
        .def(nb::init<uint32_t, uint32_t, uint32_t>(),
             nb::arg("max_bodies")              = 2048,
             nb::arg("max_body_pairs")          = 4096,
             nb::arg("max_contact_constraints") = 2048,
             "创建 Jolt PhysicsSystem 实例。")

        // body
        .def("add_body", &JoltWorld::add_body,
             nb::arg("body_type"),
             nb::arg("mass"),
             nb::arg("friction"),
             nb::arg("restitution"),
             nb::arg("position"),
             nb::arg("rotation_wxyz"),
             nb::arg("shape_type"),
             nb::arg("shape_radius")       = 0.5f,
             nb::arg("shape_half_height")  = 0.5f,
             nb::arg("shape_half_extents") = std::array<float,3>{0.5f, 0.5f, 0.5f},
             "注册刚体，返回 handle（uint32）。")

        .def("remove_body", &JoltWorld::remove_body,
             nb::arg("handle"),
             "从世界中移除并销毁刚体。")

        .def("set_kinematic_transform", &JoltWorld::set_kinematic_transform,
             nb::arg("handle"),
             nb::arg("position"),
             nb::arg("rotation_wxyz"),
             nb::arg("dt"),
             "每帧驱动运动学刚体位置/旋转（由 Blender 动画提供）。")

        .def("get_body_transform", &JoltWorld::get_body_transform,
             nb::arg("handle"),
             "返回 (position, rotation_wxyz) 元组，用于写回 Blender 对象变换。")

        // constraint
        .def("add_constraint", &JoltWorld::add_constraint,
             nb::arg("constraint_type"),
             nb::arg("body_a_handle"),
             nb::arg("body_b_handle"),
             nb::arg("anchor_pos"),
             nb::arg("anchor_rot_wxyz"),
             "注册约束（FIXED/HINGE/SLIDER/CONE/POINT），返回 handle。\n"
             "body_a_handle 或 body_b_handle 传 0xFFFFFFFF 表示固定到世界。")

        .def("remove_constraint", &JoltWorld::remove_constraint,
             nb::arg("handle"),
             "移除约束。")

        // step
        .def("step", &JoltWorld::step,
             nb::arg("dt"),
             nb::arg("substeps") = 1,
             "执行一帧物理模拟，返回耗时（毫秒，float）。")

        // info
        .def_prop_ro("body_count",       &JoltWorld::body_count)
        .def_prop_ro("constraint_count", &JoltWorld::constraint_count)
        .def("set_gravity",              &JoltWorld::set_gravity,
             nb::arg("gravity"),
             "设置重力向量，默认 (0, -9.81, 0)。")

        .def("clear", &JoltWorld::clear,
             "移除所有刚体和约束（dispose 时调用）。");

    // 常量：无效 handle
    m.attr("INVALID_HANDLE") = nb::int_(0u);
    m.attr("WORLD_HANDLE")   = nb::int_(0xFFFFFFFFu);

    fprintf(stderr, "[HoJolt] NB_MODULE: complete\n"); fflush(stderr);
}
