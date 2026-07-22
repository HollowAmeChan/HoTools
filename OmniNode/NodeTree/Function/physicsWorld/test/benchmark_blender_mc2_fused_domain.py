"""Blender 5.2/Python 3.13 下 MC2 同夹具性能证据。"""

from __future__ import annotations

import hashlib
import importlib
import os
import statistics
import sys
import time
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", "py313", "HotoolsPackage")
# Blender 5.2 can have a second HoTools checkout on its default addon path.
# This runner is intentionally isolated to the current worktree and py313 ABI.
for module_name in tuple(sys.modules):
    if module_name == "hotools_native" or module_name == "HoTools" or module_name.startswith("HoTools."):
        del sys.modules[module_name]
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
sys.path[:] = [path for path in sys.path if path != NATIVE_PACKAGE]
sys.path.insert(0, NATIVE_PACKAGE)
for path in (HOTOOLS, os.path.dirname(HOTOOLS)):
    if path not in sys.path:
        sys.path.insert(0, path)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.NodeTree", NODETREE),
    ("HoTools.OmniNode.NodeTree.Function", FUNCTION),
    ("HoTools.OmniNode.NodeTree.Function.physicsWorld", PW_ROOT),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules[package_name] = module


mc2_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.names"
)
mc2_specs = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.specs"
)
mc2_parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
mc2_topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
mc2_static_build = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.static_build"
)
mc2_frame_state = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.frame_state"
)
mc2_native = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native_context"
)
mc2_native_loader = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.native"
)
print("MC2_FUSED_DOMAIN_NATIVE", mc2_native_loader.native_module().__file__)
mc2_runtime = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.runtime_parameters"
)
mc2_product_collect = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_collect"
)
mc2_product_slot = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
mc2_base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
mc2_gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)


GRID_SIZE = int(os.environ.get("MC2_FUSED_BENCH_GRID_SIZE", "21"))
SOURCE_COUNT = int(os.environ.get("MC2_FUSED_BENCH_SOURCES", "4"))
FRAMES = int(os.environ.get("MC2_FUSED_BENCH_FRAMES", "35"))
WARMUP = int(os.environ.get("MC2_FUSED_BENCH_WARMUP", "5"))
FORCE_CONTACTS = os.environ.get("MC2_FUSED_BENCH_FORCE_CONTACTS", "0") == "1"
DT = 1.0 / 90.0
SELF_CONTINUOUS_MAX_ABS_TOLERANCE = 5.0e-4
SELF_CONTINUOUS_RMS_TOLERANCE = 5.0e-5
if GRID_SIZE < 3 or SOURCE_COUNT < 2 or FRAMES <= WARMUP + 2:
    raise ValueError("MC2 fused benchmark 的夹具或帧数无效")


def _grid(name, z, size=GRID_SIZE, spacing=0.02):
    vertices = [(x * spacing, y * spacing, z) for y in range(size) for x in range(size)]
    faces = []
    for y in range(size - 1):
        for x in range(size - 1):
            a = y * size + x
            b = a + 1
            c = a + size
            d = c + 1
            faces.extend(((a, b, d), (a, d, c)))
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    extent = max((size - 1) * spacing, 1.0e-6)
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv_layer.data[loop.index].uv = (x / extent, y / extent)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _joined_grid(name, objects):
    vertices = []
    faces = []
    pins = []
    offset = 0
    for obj in objects:
        local = [tuple(vertex.co) for vertex in obj.data.vertices]
        vertices.extend(local)
        pins.append(offset)
        for polygon in obj.data.polygons:
            faces.append(tuple(offset + index for index in polygon.vertices))
        offset += len(local)
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(vertices, [], faces)
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        vertex = mesh.vertices[loop.vertex_index].co
        uv_layer.data[loop.index].uv = (float(vertex.x), float(vertex.y))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add(pins, 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    mc2_gn_offset.write_gn_local_offsets(
        obj, np.zeros((len(mesh.vertices), 3), dtype=np.float32)
    )
    signature = mc2_base_pose.mesh_topology_signature(obj)
    proxy = mc2_base_pose.ensure_base_pose_proxy(
        obj, expected_mesh_topology_signature=signature
    )
    return obj, proxy


def _prepare_product_object(obj):
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add((0,), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    mc2_gn_offset.write_gn_local_offsets(
        obj, np.zeros((len(obj.data.vertices), 3), dtype=np.float32)
    )
    signature = mc2_base_pose.mesh_topology_signature(obj)
    proxy = mc2_base_pose.ensure_base_pose_proxy(
        obj, expected_mesh_topology_signature=signature
    )
    return proxy


def _profile(sync_mode):
    return mc2_parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        radius=0.02,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        collision_mode=0,
        self_collision_mode=2,
        self_collision_sync_mode=sync_mode,
        self_collision_thickness=0.02,
    )


def _bundle(obj, sync_mode):
    profile = _profile(sync_mode)
    task = mc2_specs.make_mc2_task_spec(
        mc2_names.MC2_SETUP_MESH_CLOTH,
        [obj],
        profile=profile,
        setup_options=mc2_parameters.make_mc2_setup_options(
            mc2_names.MC2_SETUP_MESH_CLOTH,
            self_collision_radius_model="derived_radius",
        ),
    )
    topology = mc2_topology.build_mc2_topology_spec(task)
    positions = np.asarray(
        [tuple(vertex.co) for vertex in obj.data.vertices], dtype=np.float32
    )
    rotations = np.zeros((len(positions), 4), dtype=np.float32)
    rotations[:, 3] = 1.0
    context = mc2_native.MC2NativeContextV0(len(positions))
    mc2_static_build.build_mc2_mesh_cloth_static_for_task(
        task, topology, native_context=context
    )
    context.update_parameters(
        mc2_runtime.make_mc2_runtime_parameters(profile, task.setup_options)
    )
    context.update_dynamic(mc2_frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=1,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))
    context.reset()
    return context, task, topology, positions, rotations


def _advance(bundle, frame):
    context, task, topology, positions, rotations = bundle
    context.update_dynamic(mc2_frame_state.make_mc2_frame_input(
        task_id=task.task_id,
        topology_signature=topology.topology_signature,
        frame=frame,
        generation=1,
        world_positions=positions,
        world_rotations_xyzw=rotations,
    ))
    if FORCE_CONTACTS:
        context.reset()


def _stats(samples):
    stable = samples[WARMUP:]
    ordered = sorted(stable)
    return {
        "mean_ms": statistics.fmean(stable),
        "p50_ms": ordered[len(ordered) // 2],
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "max_ms": max(stable),
    }


def _prefixed_stats(samples, prefix):
    return {f"{prefix}_{name}": value for name, value in _stats(samples).items()}


def _digest(values):
    array = np.ascontiguousarray(values, dtype=np.float32)
    return hashlib.sha256(array.tobytes()).hexdigest()[:16]


def _output_summary(values):
    array = np.asarray(values, dtype=np.float32)
    return {
        "output_digest": _digest(array),
        "output_abs_max": float(np.max(np.abs(array))),
        "output_extent": tuple(float(value) for value in np.ptp(array, axis=0)),
    }


def _output_difference(reference, candidate):
    reference = np.asarray(reference, dtype=np.float32)
    candidate = np.asarray(candidate, dtype=np.float32)
    if reference.shape != candidate.shape:
        raise AssertionError(
            f"输出形状不一致: reference={reference.shape}, candidate={candidate.shape}"
        )
    delta = candidate.astype(np.float64) - reference.astype(np.float64)
    finite = bool(np.isfinite(delta).all())
    return {
        "finite": finite,
        "max_abs": float(np.max(np.abs(delta))) if delta.size else 0.0,
        "rms": float(np.sqrt(np.mean(np.square(delta)))) if delta.size else 0.0,
    }


def _trajectory_difference(reference, candidate):
    reference = np.asarray(reference, dtype=np.float32)
    candidate = np.asarray(candidate, dtype=np.float32)
    if reference.shape != candidate.shape:
        raise AssertionError(
            f"轨迹形状不一致: reference={reference.shape}, candidate={candidate.shape}"
        )
    delta = candidate.astype(np.float64) - reference.astype(np.float64)
    frame_max = np.max(np.abs(delta), axis=(1, 2))
    divergent = np.flatnonzero(frame_max > 1.0e-7)
    peak = int(np.argmax(frame_max))
    return {
        "first_divergent_frame": int(divergent[0] + 1) if divergent.size else None,
        "peak_frame": peak + 1,
        "peak_max_abs": float(frame_max[peak]),
        "final_max_abs": float(frame_max[-1]),
        "trajectory_rms": float(np.sqrt(np.mean(np.square(delta)))),
    }


def _context_counts(contexts):
    infos = [context.inspect() for context in contexts]
    return {
        "primitive_count": sum(int(item.get("self_primitive_count", 0)) for item in infos),
        "candidate_peak": max((int(item.get("self_contact_candidate_count", 0)) for item in infos), default=0),
        "contact_peak": max((int(item.get("self_contact_enabled_count", 0)) for item in infos), default=0),
        "estimated_bytes": sum(int(item.get("estimated_bytes", 0)) for item in infos),
    }


def _run_independent(objects):
    bundles = [_bundle(obj, 0) for obj in objects]
    try:
        samples = []
        candidates = []
        contacts = []
        trajectory = []
        for frame in range(2, FRAMES + 2):
            for bundle in bundles:
                _advance(bundle, frame)
            start = time.perf_counter_ns()
            for bundle in bundles:
                bundle[0].step_no_collision(DT)
            samples.append((time.perf_counter_ns() - start) / 1.0e6)
            infos = [bundle[0].inspect() for bundle in bundles]
            candidates.append(sum(
                int(item.get("self_contact_candidate_count", 0)) for item in infos
            ))
            contacts.append(sum(
                int(item.get("self_contact_enabled_count", 0)) for item in infos
            ))
            trajectory.append(np.concatenate([
                bundle[0].read()[0] for bundle in bundles
            ]))
        output = np.concatenate([bundle[0].read()[0] for bundle in bundles])
        counts = _context_counts([bundle[0] for bundle in bundles])
        counts.update({
            "candidate_peak": max(candidates, default=0),
            "contact_peak": max(contacts, default=0),
        })
        return (
            {"model": "A_independent_v0", **_stats(samples), **counts, **_output_summary(output)},
            np.ascontiguousarray(output, dtype=np.float32),
            np.ascontiguousarray(trajectory, dtype=np.float32),
        )
    finally:
        for bundle in bundles:
            bundle[0].dispose()


def _run_aggregate(objects):
    bundles = [_bundle(obj, 2) for obj in objects]
    interaction = mc2_native.MC2NativeInteractionV0()
    try:
        samples = []
        candidates = []
        contacts = []
        trajectory = []
        groups = tuple(1 << index for index in range(len(bundles)))
        masks = tuple((1 << len(bundles)) - 1 ^ group for group in groups)
        for frame in range(2, FRAMES + 2):
            for bundle in bundles:
                _advance(bundle, frame)
            start = time.perf_counter_ns()
            interaction.step_group(
                [bundle[0] for bundle in bundles], groups, masks, DT
            )
            samples.append((time.perf_counter_ns() - start) / 1.0e6)
            frame_info = interaction.inspect()
            candidates.append(int(frame_info["candidate_count"]))
            contacts.append(int(frame_info["contact_count"]))
            trajectory.append(np.concatenate([
                bundle[0].read()[0] for bundle in bundles
            ]))
        info = interaction.inspect()
        output = np.concatenate([bundle[0].read()[0] for bundle in bundles])
        return (
            {
                "model": "B_v0_aggregate",
                **_stats(samples),
                "primitive_count": int(info["primitive_count"]),
                "candidate_peak": max(candidates, default=0),
                "contact_peak": max(contacts, default=0),
                "estimated_bytes": int(info["estimated_bytes"]),
                "pair_count": int(info["pair_count"]),
                **_output_summary(output),
            },
            np.ascontiguousarray(output, dtype=np.float32),
            np.ascontiguousarray(trajectory, dtype=np.float32),
        )
    finally:
        interaction.dispose()
        for bundle in bundles:
            bundle[0].dispose()


def _run_joined(objects):
    joined, proxy = _joined_grid("MC2FusedBenchmarkJoined", objects)
    bundle = _bundle(joined, 0)
    try:
        samples = []
        candidates = []
        contacts = []
        trajectory = []
        for frame in range(2, FRAMES + 2):
            _advance(bundle, frame)
            start = time.perf_counter_ns()
            bundle[0].step_no_collision(DT)
            samples.append((time.perf_counter_ns() - start) / 1.0e6)
            info = bundle[0].inspect()
            candidates.append(int(info.get("self_contact_candidate_count", 0)))
            contacts.append(int(info.get("self_contact_enabled_count", 0)))
            trajectory.append(bundle[0].read()[0].copy())
        output = bundle[0].read()[0]
        counts = _context_counts([bundle[0]])
        counts.update({
            "candidate_peak": max(candidates, default=0),
            "contact_peak": max(contacts, default=0),
        })
        return (
            {"model": "C_manual_join_v0", **_stats(samples), **counts, **_output_summary(output)},
            np.ascontiguousarray(output, dtype=np.float32),
            np.ascontiguousarray(trajectory, dtype=np.float32),
        )
    finally:
        bundle[0].dispose()
        _remove_object(proxy)
        _remove_object(joined)


def _set_world_frame(world, frame, previous_frame):
    world.generation = 1
    context = world.frame_context
    context.previous_frame = previous_frame
    context.frame = frame
    context.continuous = previous_frame is not None and frame == previous_frame + 1
    context.same_frame = previous_frame == frame
    context.reset_requested = False
    context.restart_required = previous_frame is None
    context.raw_dt = 1.0 / 60.0
    context.dt = 1.0 / 60.0
    context.time_scale = 1.0
    context.substeps = 1
    context.generation = 1
    world.collider_snapshot = {"frame": frame, "colliders": []}


def _run_fused(objects):
    world = world_types.PhysicsWorldCache()
    proxies = []
    try:
        for obj in objects:
            proxies.append(_prepare_product_object(obj))
        tasks = tuple(
            mc2_specs.make_mc2_task_spec(
                mc2_names.MC2_SETUP_MESH_CLOTH,
                [obj],
                profile=_profile(2),
                setup_options=mc2_parameters.make_mc2_setup_options(
                    mc2_names.MC2_SETUP_MESH_CLOTH,
                    self_collision_radius_model="derived_radius",
                ),
            )
            for obj in objects
        )
        _set_world_frame(world, 1, None)
        start = time.perf_counter_ns()
        collection = mc2_product_collect.collect_mc2_mesh_product_domain(world, tasks)
        mc2_product_slot.sync_mc2_mesh_fused_slot(world, collection)
        compile_ms = (time.perf_counter_ns() - start) / 1.0e6
        slot = world.solver_slots[mc2_product_slot.MC2_FUSED_MESH_SLOT_ID]
        owner = slot.data["owner"]
        owner_step_samples = []
        original_owner_step = owner.step

        def _timed_owner_step(step_settings):
            owner_start = time.perf_counter_ns()
            try:
                return original_owner_step(step_settings)
            finally:
                owner_step_samples.append(
                    (time.perf_counter_ns() - owner_start) / 1.0e6
                )

        owner.step = _timed_owner_step
        settings = mc2_parameters.make_mc2_solver_settings(
            simulation_frequency=90, max_simulation_count_per_frame=1
        )
        product_step_samples = []
        transaction_residual_samples = []
        capture_samples = []
        candidates = []
        contacts = []
        trajectory = []
        previous = None
        final_output = None
        # restart 发布不产生子步；额外推进一个世界帧，使四条路径都执行 FRAMES 次。
        for frame in range(1, FRAMES + 2):
            _set_world_frame(world, frame, previous)
            start = time.perf_counter_ns()
            published = mc2_product_slot.capture_and_publish_mc2_mesh_fused_frame(
                world,
                settings=settings,
                partition_frame_flags=(1,) * len(tasks) if FORCE_CONTACTS else None,
            )
            capture_samples.append((time.perf_counter_ns() - start) / 1.0e6)
            if published.update_count:
                owner_sample_count = len(owner_step_samples)
                start = time.perf_counter_ns()
                mc2_product_slot.step_mc2_mesh_fused_substep(
                    world, slot
                )
                product_elapsed = (time.perf_counter_ns() - start) / 1.0e6
                if len(owner_step_samples) != owner_sample_count + 1:
                    raise AssertionError("产品子步没有且仅有一次 owner.step")
                product_step_samples.append(product_elapsed)
                transaction_residual_samples.append(
                    max(product_elapsed - owner_step_samples[-1], 0.0)
                )
                final_output = owner.read_output().world_positions
                trajectory.append(final_output.copy())
                frame_info = owner.domain.inspect()["kernel"]
                candidates.append(int(
                    frame_info["whole_domain_self_last_candidate_count"]
                ))
                contacts.append(int(
                    frame_info["whole_domain_self_last_contact_count"]
                ))
            previous = frame
        info = owner.domain.inspect()
        kernel_info = info.get("kernel", info)
        parameter_fields = {
            name: index
            for index, name in enumerate(owner.compiled.parameters.particle_parameters.fields)
        }
        parameter_values = owner.compiled.parameters.particle_parameters.values
        if len(owner_step_samples) != len(product_step_samples):
            raise AssertionError("owner 与产品子步样本数量不一致")
        if len(owner_step_samples) != FRAMES:
            raise AssertionError(
                f"fused Domain 有效子步数量错误: {len(owner_step_samples)} != {FRAMES}"
            )
        result = {
            "model": "D_fused_domain",
            **_stats(owner_step_samples),
            **_prefixed_stats(product_step_samples, "product_step"),
            **_prefixed_stats(transaction_residual_samples, "transaction_residual"),
            "capture_mean_ms": statistics.fmean(capture_samples[WARMUP + 1:]),
            "compile_ms": compile_ms,
            "primitive_count": int(kernel_info["whole_domain_self_point_count"] + kernel_info["whole_domain_self_edge_count"] + kernel_info["whole_domain_self_triangle_count"]),
            "candidate_peak": max(candidates, default=0),
            "contact_peak": max(contacts, default=0),
            "particle_count": int(info["particle_count"]),
            "thickness_min": float(np.min(
                parameter_values[:, parameter_fields["self_collision_thickness"]]
                * parameter_values[:, parameter_fields["radius_multiplier"]]
            )),
            "thickness_max": float(np.max(
                parameter_values[:, parameter_fields["self_collision_thickness"]]
                * parameter_values[:, parameter_fields["radius_multiplier"]]
            )),
            **_output_summary(final_output),
        }
        if not owner_step_samples or not np.isfinite(final_output).all():
            raise AssertionError("fused Domain 性能夹具没有产生有限输出")
        return (
            result,
            np.ascontiguousarray(final_output, dtype=np.float32),
            np.ascontiguousarray(trajectory, dtype=np.float32),
        )
    finally:
        world.omni_cache_dispose("MC2 fused benchmark cleanup")
        for proxy in proxies:
            _remove_object(proxy)


def _remove_object(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


physics_blender.register()
objects = tuple(
    _grid(f"MC2FusedBenchmarkSource{index}", index * 0.006)
    for index in range(SOURCE_COUNT)
)
try:
    runs = (
        _run_independent(objects),
        _run_aggregate(objects),
        _run_joined(objects),
        _run_fused(objects),
    )
    results = tuple(run[0] for run in runs)
    outputs = {result["model"]: run[1] for result, run in zip(results, runs)}
    trajectories = {result["model"]: run[2] for result, run in zip(results, runs)}
    total_particles = SOURCE_COUNT * GRID_SIZE * GRID_SIZE
    print("MC2_FUSED_DOMAIN_BENCH", {"grid_size": GRID_SIZE, "sources": SOURCE_COUNT, "particles": total_particles, "frames": FRAMES, "warmup": WARMUP, "force_contacts": FORCE_CONTACTS})
    for result in results:
        print("MC2_FUSED_DOMAIN_RESULT", result)
    by_model = {item["model"]: item for item in results}
    d_over_b = by_model["D_fused_domain"]["p50_ms"] / by_model["B_v0_aggregate"]["p50_ms"]
    d_over_c = by_model["D_fused_domain"]["p50_ms"] / by_model["C_manual_join_v0"]["p50_ms"]
    c_d_output = _output_difference(
        outputs["C_manual_join_v0"], outputs["D_fused_domain"]
    )
    c_d_trajectory = _trajectory_difference(
        trajectories["C_manual_join_v0"], trajectories["D_fused_domain"]
    )
    c_result = by_model["C_manual_join_v0"]
    d_result = by_model["D_fused_domain"]
    workload_equal = all(
        c_result[name] == d_result[name]
        for name in ("primitive_count", "candidate_peak", "contact_peak")
    )
    self_equivalent = (
        c_d_output["finite"]
        and workload_equal
        and c_d_trajectory["peak_max_abs"] <= SELF_CONTINUOUS_MAX_ABS_TOLERANCE
        and c_d_trajectory["trajectory_rms"] <= SELF_CONTINUOUS_RMS_TOLERANCE
    )
    print("MC2_FUSED_DOMAIN_RATIO", {
        "D_over_B_p50": d_over_b,
        "D_over_C_p50": d_over_c,
    })
    print("MC2_FUSED_DOMAIN_OUTPUT_DIFF", {
        "B_vs_D": _output_difference(
            outputs["B_v0_aggregate"], outputs["D_fused_domain"]
        ),
        "C_vs_D": c_d_output,
    })
    print("MC2_FUSED_DOMAIN_TRAJECTORY_DIFF", {
        "C_vs_D": c_d_trajectory,
    })
    print("MC2_FUSED_DOMAIN_SELF_GATE", {
        "passed": self_equivalent,
        "workload_equal": workload_equal,
        "max_abs_tolerance": SELF_CONTINUOUS_MAX_ABS_TOLERANCE,
        "rms_tolerance": SELF_CONTINUOUS_RMS_TOLERANCE,
    })
    p2_passed = d_over_b < 0.8 and 0.5 <= d_over_c <= 2.0
    print("MC2_FUSED_DOMAIN_P2_GATE", {
        "passed": p2_passed,
        "faster_than_aggregate": d_over_b < 0.8,
        "same_class_as_manual_join": 0.5 <= d_over_c <= 2.0,
    })
    print("MC2_FUSED_DOMAIN_E4_GATE", {
        "passed": p2_passed and self_equivalent,
        "performance_passed": p2_passed,
        "self_equivalent": self_equivalent,
    })
finally:
    for obj in objects:
        _remove_object(obj)

print("MC2 fused domain benchmark: completed")
