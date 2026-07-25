"""MeshCloth 产品域跨 partition 自碰撞的数值与过滤合同。"""

from __future__ import annotations

import hashlib
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_mixed_output_soak as mixed


bone_soak = mixed.bone_soak
nodes = mixed.nodes
parameters = mixed.parameters
product_slot = mixed.product_slot
world_types = mixed.world_types
physics_blender = mixed.physics_blender
debug_draw = mixed.importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.debug_draw"
)
base_pose = mixed.base_pose
gn_offset = mixed.gn_offset
writeback = mixed.writeback


def _profile(*, cloth_mass: float):
    return parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.1,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=3.5,
        radius=0.04,
        tether_compression=0.35,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        motion_stiffness=0.0,
        collision_mode=0,
        collision_friction=0.0,
        self_collision_mode=2,
        self_collision_sync_mode=2,
        self_collision_thickness=0.05,
        cloth_mass=cloth_mass,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _partition(
    mesh,
    *,
    group: int,
    mask: int,
    mass: float,
    teleport_mode: int = 0,
):
    properties = mesh.hotools_mesh_collision
    objects, count = nodes.physicsMC2MeshCustomObject(
        [mesh],
        mc2_base_pose_proxy=properties.mc2_base_pose_proxy,
        radius_vertex_group=properties.radius_vertex_group,
        pin_enabled=properties.pin_enabled,
        pin_vertex_group=properties.pin_vertex_group,
        primary_collision_group=group,
        collided_by_groups=mask,
    )
    assert count == 1 and len(objects) == 1
    entries, _domain_ids = nodes.physicsMC2MeshClothTask(
        objects,
        profile=_profile(cloth_mass=mass),
        world_inertia=1.0,
        teleport_mode=teleport_mode,
        teleport_distance=0.5,
        teleport_rotation=30.0,
    )
    assert len(entries) == 1
    return entries[0]


def _request(world, meshes, *, accepted: bool, teleport_mode: int = 0):
    masks = (2, 1) if accepted else (1, 2)
    entries = [
        _partition(
            meshes[0], group=1, mask=masks[0], mass=0.25,
            teleport_mode=teleport_mode,
        ),
        _partition(
            meshes[1], group=2, mask=masks[1], mass=0.75,
            teleport_mode=teleport_mode,
        ),
    ]
    requests, report = nodes.physicsMC2MeshCollector(entries)
    assert len(requests) == 1 and report
    return requests[0]


def _cross_contact_count(owner) -> tuple[int, int, int]:
    debug = owner.read_constraint_debug_state()["whole_domain_self_results"]
    primitive_owners = np.asarray(debug["owner_indices"], dtype=np.int32)
    contact_indices = np.asarray(
        debug["contact_indices"], dtype=np.int32
    ).reshape((-1, 2))
    enabled = np.asarray(
        debug["contact_enabled"], dtype=np.uint8
    ).astype(bool)
    assert len(contact_indices) == len(enabled)
    if len(contact_indices) == 0:
        return 0, 0, 0
    cross = (
        primitive_owners[contact_indices[:, 0]]
        != primitive_owners[contact_indices[:, 1]]
    )
    return (
        int(np.count_nonzero(cross)),
        int(np.count_nonzero(cross & enabled)),
        int(np.count_nonzero(enabled)),
    )


def _run_scope_case(*, accepted: bool, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 4700 + run_index
    meshes = [None, None]
    digest = hashlib.sha256()
    samples = []
    owner = None
    try:
        physics_blender.register()
        meshes[0], _proxy_a = mixed._mesh_object(
            f"MC2ProductMeshSelfA{run_index}"
        )
        meshes[1], proxy_b = mixed._mesh_object(
            f"MC2ProductMeshSelfB{run_index}"
        )
        meshes[1].location.x += 0.01
        meshes[1].location.z += 0.005
        proxy_b.location.x += 0.01
        proxy_b.location.z += 0.005
        bpy.context.view_layer.update()

        request = _request(world, meshes, accepted=accepted)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, 601):
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            capture = frame in (2, 600)
            if capture:
                assert owner is not None
                owner.begin_constraint_debug(64)
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
                assert owner.compiled.program.partition_count == 2
                assert set(owner.compiled.program.particle_partition_index) == {0, 1}
                uint_table = owner.compiled.parameters.partition_uint_parameters
                uint_rows = [
                    dict(zip(uint_table.fields, row)) for row in uint_table.values
                ]
                assert [int(row["self_collision_mode"]) for row in uint_rows] == [2, 2]
                assert [int(row["self_collision_sync_mode"]) for row in uint_rows] == [2, 2]
                assert [int(row["collision_group"]) for row in uint_rows] == [1, 2]
                expected_masks = [3, 3] if accepted else [1, 2]
                assert [int(row["collision_mask"]) for row in uint_rows] == expected_masks

                particle = owner.compiled.parameters.particle_parameters
                fields = {name: index for index, name in enumerate(particle.fields)}
                radius = particle.values[:, fields["radius"]]
                thickness = particle.values[:, fields["self_collision_thickness"]]
                multipliers = particle.values[:, fields["radius_multiplier"]]
                masses = particle.values[:, fields["cloth_mass"]]
                np.testing.assert_allclose(
                    thickness,
                    radius * 0.25,
                    rtol=0.0,
                    atol=1.0e-7,
                )
                np.testing.assert_allclose(
                    multipliers, 1.0, rtol=0.0, atol=1.0e-7
                )
                partition_indices = owner.compiled.program.particle_partition_index
                np.testing.assert_allclose(
                    masses[partition_indices == 0], 0.25, rtol=0.0, atol=1.0e-7
                )
                np.testing.assert_allclose(
                    masses[partition_indices == 1], 0.75, rtol=0.0, atol=1.0e-7
                )
            else:
                assert current_owner is owner

            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            digest.update(output.world_positions.tobytes())
            kernel = owner.inspect()["domain"]["kernel"]
            assert kernel["whole_domain_self_ready"] is True
            primitive_count = sum(
                int(kernel[f"whole_domain_self_{kind}_count"])
                for kind in ("point", "edge", "triangle")
            )
            candidate_count = int(
                kernel.get("whole_domain_self_last_candidate_count", 0)
            )
            contact_count = int(
                kernel.get("whole_domain_self_last_contact_count", 0)
            )
            cache_count = int(kernel.get("self_contact_cache_count", 0))
            assert primitive_count > 0
            assert 0 <= contact_count <= candidate_count <= primitive_count ** 2
            assert 0 <= cache_count <= primitive_count ** 2
            if frame > 1:
                assert kernel["whole_domain_self_step_count"] > 0
            if capture:
                owner.end_constraint_debug()
                cross_candidates, cross_enabled, enabled = _cross_contact_count(owner)
                if frame == 2:
                    if accepted:
                        assert cross_candidates > 0
                        assert cross_enabled > 0
                    else:
                        assert cross_enabled == 0
                samples.append((
                    frame,
                    primitive_count,
                    candidate_count,
                    contact_count,
                    cache_count,
                    cross_candidates,
                    cross_enabled,
                    enabled,
                ))
                digest.update(np.asarray(samples[-1], dtype=np.int64).tobytes())

        assert owner is not None and len(samples) == 2
        return digest.hexdigest(), tuple(samples)
    finally:
        world.omni_cache_dispose("mesh_product_self_scope_cleanup")
        for mesh in meshes:
            mixed._remove_mesh(mesh)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_self_collision_cross_partition_scope_and_cache() -> None:
    rejected = _run_scope_case(accepted=False, run_index=0)
    rejected_repeat = _run_scope_case(accepted=False, run_index=1)
    accepted = _run_scope_case(accepted=True, run_index=2)
    accepted_repeat = _run_scope_case(accepted=True, run_index=3)
    assert rejected == rejected_repeat, (rejected, rejected_repeat)
    assert accepted == accepted_repeat, (accepted, accepted_repeat)
    assert rejected[0] != accepted[0]
    print("MC2_MESH_PRODUCT_SELF_SCOPE", rejected, accepted)
    print("PASS test_mesh_product_self_collision_cross_partition_scope_and_cache")


def test_mesh_product_self_collision_keep_teleport_large_jump() -> None:
    world = world_types.PhysicsWorldCache()
    generation = 4750
    meshes = [None, None]
    proxies = [None, None]
    owner = None
    captures = {}
    try:
        physics_blender.register()
        meshes[0], proxies[0] = mixed._mesh_object("MC2ProductSelfKeepA")
        meshes[1], proxies[1] = mixed._mesh_object("MC2ProductSelfKeepB")
        meshes[1].location.x += 0.01
        meshes[1].location.z += 0.005
        bpy.context.view_layer.update()

        request = _request(
            world, meshes, accepted=True, teleport_mode=2
        )
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, 6):
            if frame == 3:
                meshes[0].location.x += 100.0
            bpy.context.view_layer.update()
            bone_soak._set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / 30.0
            world.frame_context.dt = 1.0 / 30.0
            world.collider_snapshot = {"frame": frame, "colliders": []}
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            slot = world.solver_slots[slot_id]
            current_owner = slot.data["owner"]
            if owner is None:
                owner = current_owner
            else:
                assert current_owner is owner
            output = owner.read_output()
            dynamics = owner.read_debug_state()
            task_state = owner.read_task_reference_teleport_state()
            captures[frame] = {
                "positions": np.array(output.world_positions, copy=True),
                "velocities": np.array(dynamics["velocities"], copy=True),
                "real_velocities": np.array(
                    dynamics["real_velocities"], copy=True
                ),
                "flags": np.array(task_state["flags"], copy=True),
                "old_references": np.array(
                    task_state["old_reference_positions"], copy=True
                ),
                "references": np.array(
                    task_state["reference_positions"], copy=True
                ),
                "invalidations": int(
                    task_state["self_history_invalidation_count"]
                ),
            }

        program = owner.compiled.program
        partitions = np.asarray(
            program.particle_partition_index, dtype=np.uint32
        )
        moved = partitions == 0
        np.testing.assert_array_equal(captures[3]["flags"], (3, 0))
        np.testing.assert_array_equal(captures[4]["flags"], (0, 0))
        assert captures[3]["invalidations"] == 1
        delta = captures[3]["references"][0] - captures[3]["old_references"][0]
        residual = np.linalg.norm(
            captures[3]["positions"][moved]
            - (captures[2]["positions"][moved] + delta),
            axis=1,
        )
        assert float(np.max(residual, initial=0.0)) < 0.1
        for frame in (3, 4):
            assert float(np.max(np.linalg.norm(
                captures[frame]["velocities"][moved], axis=1
            ), initial=0.0)) <= 3.5 + 1.0e-5
            assert float(np.max(np.linalg.norm(
                captures[frame]["real_velocities"][moved], axis=1
            ), initial=0.0)) < 10.0
        print("PASS Mesh自碰统一域单分区Keep瞬移100米")
    finally:
        world.omni_cache_dispose("mesh_product_self_keep_teleport_cleanup")
        for obj in (*meshes, *proxies):
            mixed._remove_mesh(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()


def _teleport_equivalence_grid(name: str, size: int = 30):
    spacing = 0.02
    layer_gap = 0.012
    vertices = []
    faces = []
    layer_vertex_count = size * size
    for layer, z in enumerate((0.0, layer_gap)):
        offset = layer * layer_vertex_count
        for y in range(size):
            for x in range(size):
                vertices.append((x * spacing, y * spacing, z))
        for y in range(size - 1):
            for x in range(size - 1):
                a = offset + y * size + x
                b = a + 1
                c = a + size
                d = c + 1
                faces.extend(
                    ((a, b, d), (a, d, c))
                    if layer == 0
                    else ((a, d, b), (a, c, d))
                )
    mesh_data = bpy.data.meshes.new(f"{name}Mesh")
    mesh_data.from_pydata(vertices, (), faces)
    mesh_data.uv_layers.new(name="UVMap")
    mesh_data.update()
    obj = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(obj)
    armature_data = bpy.data.armatures.new(f"{name}ArmatureData")
    armature = bpy.data.objects.new(f"{name}Armature", armature_data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature_data.edit_bones.new("TeleportDriver")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    skin = obj.vertex_groups.new(name="TeleportDriver")
    skin.add(tuple(range(len(vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new("TeleportDriver", "ARMATURE")
    modifier.object = armature
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add(tuple(range(size)), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    obj.hotools_mesh_collision.collided_by_groups = 1
    gn_offset.write_gn_local_offsets(
        obj, np.zeros((len(mesh_data.vertices), 3), dtype=np.float32)
    )
    signature = base_pose.mesh_topology_signature(obj)
    proxy = base_pose.ensure_base_pose_proxy(
        obj, expected_mesh_topology_signature=signature
    )
    return obj, proxy, armature


def _remove_armature(obj) -> None:
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and not data.users:
        bpy.data.armatures.remove(data)


def _run_self_keep_equivalence_case(*, jump: float, run_index: int):
    world = world_types.PhysicsWorldCache()
    generation = 4760 + run_index
    obj = proxy = armature = owner = None
    captures = {}
    try:
        physics_blender.register()
        obj, proxy, armature = _teleport_equivalence_grid(
            f"MC2SelfKeepEquivalence{run_index}"
        )
        objects, count = nodes.physicsMC2MeshObject([obj])
        assert count == 1 and len(objects) == 1
        entries, _domain_ids = nodes.physicsMC2MeshClothTask(
            objects,
            profile=parameters.make_mc2_particle_profile(
                gravity=5.0,
                gravity_direction=(0.0, 0.0, -1.0),
                damping=0.05,
                radius=0.02,
                distance_stiffness=0.8,
                bending_stiffness=0.4,
                collision_mode=2,
                collision_friction=0.2,
                self_collision_mode=2,
                particle_speed_limit=4.0,
            ),
            world_inertia=1.0,
            teleport_mode=2,
            teleport_distance=0.5,
            teleport_rotation=30.0,
        )
        requests, report = nodes.physicsMC2MeshCollector(entries)
        assert len(requests) == 1 and report
        request = requests[0]
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )
        for frame in range(1, 21):
            if frame == 12:
                armature.pose.bones["TeleportDriver"].location.x += float(jump)
            bpy.context.view_layer.update()
            bone_soak._set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / 30.0
            world.frame_context.dt = 1.0 / 30.0
            collider_shift = float(jump) if frame >= 12 else 0.0
            old_collider_shift = float(jump) if frame >= 13 else 0.0
            center = (0.3 + collider_shift, 0.3, -0.08)
            old_center = (0.3 + old_collider_shift, 0.3, -0.08)
            world.previous_collider_snapshot = {
                "colliders": {
                    "teleport-driver-sphere": {
                        "center": old_center,
                        "segment_a": old_center,
                        "segment_b": old_center,
                    }
                }
            }
            world.collider_snapshot = {
                "frame": frame,
                "colliders": [{
                    "key": "teleport-driver-sphere",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": center,
                    "radius": 0.15,
                }],
            }
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            current_owner = world.solver_slots[slot_id].data["owner"]
            if owner is None:
                owner = current_owner
                assert owner.compiled.program.particle_count == 1800
            else:
                assert current_owner is owner
            output = owner.read_output()
            dynamics = owner.read_debug_state()
            teleport = owner.read_task_reference_teleport_state()
            kernel = owner.inspect()["domain"]["kernel"]
            assert writeback.writeback_gn_attributes(world) == 1
            captures[frame] = {
                "positions": np.array(output.world_positions, copy=True),
                "velocities": np.array(dynamics["velocities"], copy=True),
                "real_velocities": np.array(
                    dynamics["real_velocities"], copy=True
                ),
                "offsets": np.array(mixed._mesh_offsets(obj), copy=True),
                "flags": np.array(teleport["flags"], copy=True),
                "candidates": int(
                    kernel["whole_domain_self_last_candidate_count"]
                ),
                "contacts": int(
                    kernel["whole_domain_self_last_contact_count"]
                ),
            }
        return captures
    finally:
        world.omni_cache_dispose("mesh_self_keep_equivalence_cleanup")
        mixed._remove_mesh(obj)
        mixed._remove_mesh(proxy)
        _remove_armature(armature)
        if physics_blender.is_registered():
            physics_blender.unregister()


def test_mesh_product_self_keep_matches_stationary_control() -> None:
    control = _run_self_keep_equivalence_case(jump=0.0, run_index=0)
    teleported = _run_self_keep_equivalence_case(jump=2.0, run_index=1)
    translation = np.asarray((2.0, 0.0, 0.0), dtype=np.float32)
    np.testing.assert_array_equal(teleported[12]["flags"], (3,))
    np.testing.assert_array_equal(teleported[13]["flags"], (0,))
    for frame in range(12, 21):
        position_tolerance = 1.0e-3 if frame == 12 else 5.0e-2
        np.testing.assert_allclose(
            teleported[frame]["positions"] - translation,
            control[frame]["positions"],
            rtol=0.0,
            atol=position_tolerance,
            err_msg=f"1800粒子Keep位置不等价: frame={frame}",
        )
        if frame == 12:
            np.testing.assert_allclose(
                teleported[frame]["velocities"],
                control[frame]["velocities"],
                rtol=0.0,
                atol=1.0e-1,
                err_msg=f"1800粒子Keep保存速度不等价: frame={frame}",
            )
            np.testing.assert_allclose(
                teleported[frame]["real_velocities"],
                control[frame]["real_velocities"],
                rtol=0.0,
                atol=1.0e-1,
                err_msg=f"1800粒子Keep真实速度不等价: frame={frame}",
            )
        else:
            speed = np.linalg.norm(teleported[frame]["velocities"], axis=1)
            real_speed = np.linalg.norm(
                teleported[frame]["real_velocities"], axis=1
            )
            assert float(np.max(speed, initial=0.0)) <= 4.0 + 1.0e-4
            assert float(np.max(real_speed, initial=0.0)) < 10.0
        np.testing.assert_allclose(
            teleported[frame]["offsets"],
            control[frame]["offsets"],
            rtol=0.0,
            atol=position_tolerance,
            err_msg=f"1800粒子Keep GN offset不等价: frame={frame}",
        )
        candidate_delta = abs(
            teleported[frame]["candidates"] - control[frame]["candidates"]
        )
        contact_delta = abs(
            teleported[frame]["contacts"] - control[frame]["contacts"]
        )
        assert teleported[frame]["candidates"] > 0
        assert 0 <= teleported[frame]["contacts"] <= teleported[frame]["candidates"]
        if frame == 12:
            candidate_limit = max(100, control[frame]["candidates"] // 100)
            contact_limit = max(100, control[frame]["contacts"] // 100)
            assert candidate_delta <= candidate_limit, (
                frame, candidate_delta, candidate_limit
            )
            assert contact_delta <= contact_limit, (
                frame, contact_delta, contact_limit
            )
    print("PASS 1800粒子Mesh自碰Keep与静止控制组等价")


def test_mesh_product_debug_draw_emits_requested_native_layers() -> None:
    world = world_types.PhysicsWorldCache()
    generation = 4800
    meshes = [None, None]
    proxies = [None, None]
    node_uid = str(id(world))
    try:
        physics_blender.register()
        meshes[0], proxies[0] = mixed._mesh_object("MC2ProductDebugDrawA")
        meshes[1], proxies[1] = mixed._mesh_object("MC2ProductDebugDrawB")
        for obj in (meshes[1], proxies[1]):
            obj.location.x += 0.01
            obj.location.z += 0.005
        bpy.context.view_layer.update()
        request = _request(world, meshes, accepted=True)
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type, request.domain_signature
        )

        for frame in (1, 2):
            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
            returned, ready, status = nodes.physicsMC2Step(
                world,
                [request],
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status
            status_world, _status = nodes.physicsMC2DebugDraw(
                world,
                show_velocity=True,
                show_teleport_threshold=True,
                show_teleport_status=True,
                show_self_primitives=True,
                show_self_grid=True,
                show_self_candidates=True,
                show_self_contacts=True,
            )
            assert status_world is world

        slot = world.solver_slots[slot_id]
        snapshot = slot.data["_debug_draw_snapshot"]
        dynamics = snapshot["native"]["dynamics"]
        assert len(dynamics["velocities"]) > 0
        assert np.max(np.linalg.norm(dynamics["real_velocities"], axis=1)) > 0.0
        teleport = snapshot["teleport"]
        assert teleport["schema"] == "mc2_product_task_teleport_debug_v1"
        assert all(item["eligible"] for item in teleport["partitions"])
        self_state = snapshot["self_collision"]
        assert len(self_state["particle_indices"]) > 0
        assert len(self_state["primitive_grids"]) > 0
        assert len(self_state["candidates"]) > 0
        assert len(self_state["contact_indices"]) > 0

        draw = debug_draw.mc2_debug_draw_store_snapshot(node_uid)
        assert draw is not None and draw["batch_count"] > 0
        line_colors = set(draw["line_batch_colors"])
        point_colors = set(draw["point_batch_colors"])
        colors = debug_draw._COLORS
        assert line_colors.intersection({
            colors["velocity"], colors["real_velocity"],
            colors["velocity_delta"], colors["velocity_clamped"],
        })
        assert colors["teleport_threshold"] in line_colors
        assert colors["teleport_measure"] in point_colors
        assert colors["primitive"] in line_colors | point_colors
        assert colors["grid"] in line_colors
        assert colors["candidate"] in line_colors
        assert line_colors.intersection({
            colors["contact"], colors["contact_new"],
            colors["disabled_contact"], colors["intersection"],
            colors["intersection_new"],
        })
    finally:
        debug_draw.clear_mc2_debug_draw_store(node_uid=node_uid)
        world.omni_cache_dispose("mesh_product_debug_draw_cleanup")
        for obj in (*meshes, *proxies):
            mixed._remove_mesh(obj)
        if physics_blender.is_registered():
            physics_blender.unregister()


if __name__ == "__main__":
    if os.environ.get("MC2_SELF_KEEP_EQUIVALENCE_ONLY"):
        test_mesh_product_self_keep_matches_stationary_control()
    elif os.environ.get("MC2_SELF_KEEP_TELEPORT_ONLY"):
        test_mesh_product_self_collision_keep_teleport_large_jump()
    else:
        test_mesh_product_self_collision_cross_partition_scope_and_cache()
        test_mesh_product_self_collision_keep_teleport_large_jump()
        test_mesh_product_self_keep_matches_stationary_control()
        test_mesh_product_debug_draw_emits_requested_native_layers()
