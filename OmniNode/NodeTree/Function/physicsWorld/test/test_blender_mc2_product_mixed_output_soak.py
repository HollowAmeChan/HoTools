"""三种 setup 公开产品 request 的 mixed-output 长程验收。"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_bone_product_constraint_soak as bone_soak


nodes = bone_soak.nodes
parameters = bone_soak.parameters
product_slot = bone_soak.product_slot
world_types = bone_soak.world_types
writeback = bone_soak.writeback

physics_blender = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.blender"
)
base_pose = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.mesh_cloth.base_pose"
)
gn_offset = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.gn_offset"
)
world_names = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.names"
)


def _mesh_object(name: str):
    vertices = tuple(
        (float(x) * 0.08, float(y) * 0.08, 0.0)
        for y in range(4)
        for x in range(4)
    )
    triangles = []
    for y in range(3):
        for x in range(3):
            a = y * 4 + x
            b = a + 1
            c = a + 4
            d = c + 1
            triangles.extend(((a, b, d), (a, d, c)))
    mesh = bpy.data.meshes.new(f"{name}Data")
    mesh.from_pydata(vertices, (), triangles)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        x, y, _z = vertices[loop.vertex_index]
        uv_layer.data[loop.index].uv = (x / 0.24, y / 0.24)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = (-0.7, -0.1, 0.2)
    bpy.context.scene.collection.objects.link(obj)
    pin = obj.vertex_groups.new(name="MC2Pin")
    pin.add((0, 1, 2, 3), 1.0, "REPLACE")
    obj.hotools_mesh_collision.pin_enabled = True
    obj.hotools_mesh_collision.pin_vertex_group = pin.name
    obj.hotools_mesh_collision.collided_by_groups = 1
    gn_offset.write_gn_local_offsets(
        obj,
        np.zeros((len(mesh.vertices), 3), dtype=np.float32),
    )
    topology_signature = base_pose.mesh_topology_signature(obj)
    proxy = base_pose.ensure_base_pose_proxy(
        obj,
        expected_mesh_topology_signature=topology_signature,
    )
    return obj, proxy


def _remove_mesh(obj) -> None:
    if obj is None or obj.name not in bpy.data.objects:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and not mesh.users:
        bpy.data.meshes.remove(mesh)


def _mesh_offsets(obj) -> np.ndarray:
    attribute = obj.data.attributes.get(world_names.GN_OFFSET_ATTRIBUTE_NAME)
    assert attribute is not None
    values = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    attribute.data.foreach_get("vector", values)
    return values.reshape((-1, 3))


def _mesh_request(world, mesh, *, hot: bool = False):
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, override_count = nodes.physicsMC2MeshOverride(
        entries,
        profile=parameters.make_mc2_particle_profile(
            gravity=4.0,
            gravity_direction=(0.0, 0.0, -1.0),
            damping=0.29 if hot else 0.06,
            particle_speed_limit=0.08 if hot else 3.5,
            radius=0.026 if hot else 0.018,
            tether_compression=0.35,
            distance_stiffness=0.41 if hot else 0.76,
            bending_stiffness=0.48,
            angle_restoration_enabled=False,
            angle_limit_enabled=False,
            max_distance_enabled=True,
            max_distance=0.32,
            backstop_enabled=True,
            backstop_radius=0.16,
            backstop_distance=0.03,
            motion_stiffness=0.65,
            collision_mode=1,
            collision_friction=0.18,
            self_collision_mode=2,
            self_collision_thickness=0.006,
            spring_enabled=False,
            wind_influence=0.0,
        ),
    )
    assert override_count == 1
    requests, report = nodes.physicsMC2MeshCollector(
        world,
        entries,
        include_implicit=False,
    )
    assert len(requests) == 1 and report
    return requests[0]


def _slot_id(request) -> str:
    return product_slot.make_mc2_product_slot_id(
        request.setup_type,
        request.domain_signature,
    )


def _run_once(run_index: int) -> str:
    world = world_types.PhysicsWorldCache()
    generation = 920 + run_index
    mesh = proxy = cloth = spring = None
    owners = None
    schedulers = None
    digest = hashlib.sha256()
    try:
        physics_blender.register()
        mesh, proxy = _mesh_object(f"MC2ProductMixedMesh{run_index}")
        cloth = bone_soak._armature(
            f"MC2ProductMixedCloth{run_index}",
            chain_count=2,
            chain_length=6,
            x_offset=-0.2,
        )
        spring = bone_soak._armature(
            f"MC2ProductMixedSpring{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.45,
        )
        bone_soak._set_frame(world, 1, generation)
        world.collider_snapshot = {"frame": 1, "colliders": []}
        mesh_request = _mesh_request(world, mesh)
        bone_requests = bone_soak._requests(cloth, spring)
        requests = (mesh_request, *bone_requests)
        slot_ids = tuple(_slot_id(request) for request in requests)
        assert len(set(slot_ids)) == 3
        expected_bones = None

        for frame in range(1, 901):
            phase = frame * 0.017
            mesh.rotation_euler.z = 0.1 * math.sin(phase * 0.5)
            mesh.location.y = -0.1 + 0.02 * math.sin(phase * 0.3)
            for index, armature in enumerate((cloth, spring)):
                parent = armature.pose.bones["Parent"]
                parent.rotation_mode = "XYZ"
                parent.rotation_euler.z = (0.16 + index * 0.04) * math.sin(phase)
                parent.location.x = 0.012 * math.cos(phase * 0.6 + index)
            bpy.context.view_layer.update()

            bone_soak._set_frame(world, frame, generation)
            world.collider_snapshot = {
                "frame": frame,
                "colliders": [{
                    "key": "mixed-product-sphere",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": (60.0, 0.0, 0.0),
                    "radius": 1.0,
                }],
            }
            if frame in (301, 601):
                hot = frame == 301
                previous_signatures = tuple(
                    owner.compiled.parameters.parameter_signature for owner in owners
                )
                mesh_request = _mesh_request(world, mesh, hot=hot)
                bone_requests = bone_soak._requests(cloth, spring, hot=hot)
                requests = (mesh_request, *bone_requests)
                assert tuple(_slot_id(request) for request in requests) == slot_ids
            returned, ready, status = nodes.physicsMC2Step(
                world,
                list(requests),
                simulation_frequency=90,
                max_simulation_count_per_frame=3,
            )
            assert returned is world and ready is True, status

            slots = tuple(world.solver_slots[slot_id] for slot_id in slot_ids)
            current_owners = tuple(slot.data["owner"] for slot in slots)
            if owners is None:
                owners = current_owners
                schedulers = tuple(slot.data["scheduler_state"] for slot in slots)
                assert tuple(request.setup_type for request in requests) == (
                    "mesh_cloth",
                    "bone_cloth",
                    "bone_spring",
                )
                expected_bones = sum(
                    owner.compiled.program.particle_count
                    for request, owner in zip(requests, owners)
                    if request.setup_type != "mesh_cloth"
                )
            else:
                assert current_owners == owners
                assert all(
                    slot.data["scheduler_state"] is scheduler
                    for slot, scheduler in zip(slots, schedulers)
                )
                assert all(slot.data["last_sync"].native_domain_reused for slot in slots)
                if frame in (301, 601):
                    assert all(
                        slot.data["last_sync"].action == "parameters_updated"
                        for slot in slots
                    )
                    assert all(
                        owner.compiled.parameters.parameter_signature != previous
                        for owner, previous in zip(owners, previous_signatures)
                    )

            for slot, owner in zip(slots, current_owners):
                assert "native_context" not in slot.data
                assert "spec" not in slot.data
                output = owner.read_output()
                assert output.frame == frame and output.generation == generation
                assert np.all(np.isfinite(output.world_positions))
                assert np.all(np.isfinite(output.world_rotations_xyzw))
                digest.update(output.world_positions.tobytes())
                digest.update(output.world_rotations_xyzw.tobytes())

            gn_results = tuple(world.result_streams.get("gn_attribute", ()))
            bone_results = tuple(world.result_streams.get("bone_transform", ()))
            assert len(gn_results) == 1
            assert bone_results
            assert sum(int(result["bone_count"]) for result in bone_results) == expected_bones
            assert writeback.writeback_gn_attributes(world) == 1
            assert writeback.writeback_bone_transforms(world) == expected_bones
            bpy.context.view_layer.update()

            offsets = _mesh_offsets(mesh)
            assert np.all(np.isfinite(offsets))
            digest.update(offsets.tobytes())
            digest.update(np.asarray(frame, dtype=np.int32).tobytes())

        assert owners is not None
        assert all(owner.inspect()["domain"]["step_count"] >= 899 for owner in owners)
        return digest.hexdigest()
    finally:
        world.omni_cache_dispose("mc2_product_mixed_output_soak_cleanup")
        bone_soak._remove_armature(cloth)
        bone_soak._remove_armature(spring)
        _remove_mesh(mesh)
        _remove_mesh(proxy)


def test_three_setup_product_mixed_output_900_frame_deterministic_soak() -> None:
    first = _run_once(0)
    second = _run_once(1)
    assert first == second, (first, second)
    print(f"MC2_PRODUCT_MIXED_OUTPUT_DIGEST {first}")


if __name__ == "__main__":
    test_three_setup_product_mixed_output_900_frame_deterministic_soak()
    print("PASS test_three_setup_product_mixed_output_900_frame_deterministic_soak")
