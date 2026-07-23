"""公开产品 request 驱动的 BoneCloth/BoneSpring 约束长程验收。"""

from __future__ import annotations

import hashlib
import importlib
import math
import os
import sys
import types

import bpy
import numpy as np


HOTOOLS = r"C:\Users\hhh12\AppData\Roaming\Blender Foundation\Blender\4.5\scripts\addons\HoTools"
NODETREE = os.path.join(HOTOOLS, "OmniNode", "NodeTree")
FUNCTION = os.path.join(NODETREE, "Function")
PW_ROOT = os.path.join(FUNCTION, "physicsWorld")
PYTHON_ABI = f"py{sys.version_info.major}{sys.version_info.minor}"
NATIVE_PACKAGE = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")

for module_name in tuple(sys.modules):
    if (
        module_name == "hotools_native"
        or module_name == "HoTools"
        or module_name.startswith("HoTools.")
    ):
        sys.modules.pop(module_name, None)
os.environ["HOTOOLS_NATIVE_TEST_DIR"] = NATIVE_PACKAGE
for path in reversed((NATIVE_PACKAGE, HOTOOLS, os.path.dirname(HOTOOLS))):
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

nodes = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.nodes"
)
parameters = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.parameters"
)
product_slot = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_slot"
)
world_types = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.types"
)
writeback = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.writeback"
)
product_bone_authoring = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.product_bone_authoring"
)
topology = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.topology"
)
bone_frame = importlib.import_module(
    "HoTools.OmniNode.NodeTree.Function.physicsWorld.mc2.setups.bone_frame_input"
)
hotools_native = importlib.import_module("hotools_native")

print(f"MC2_BONE_PRODUCT_SOAK_SOURCE {nodes.__file__}")
print(f"MC2_BONE_PRODUCT_SOAK_NATIVE {hotools_native.__file__}")
assert os.path.commonpath((HOTOOLS, os.path.abspath(nodes.__file__))) == HOTOOLS
assert os.path.commonpath((NATIVE_PACKAGE, os.path.abspath(hotools_native.__file__))) == NATIVE_PACKAGE


def _armature(name: str, *, chain_count: int, chain_length: int, x_offset: float):
    data = bpy.data.armatures.new(f"{name}Data")
    obj = bpy.data.objects.new(name, data)
    obj.location.x = x_offset
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    parent = data.edit_bones.new("Parent")
    parent.head = (0.0, 0.0, 0.0)
    parent.tail = (0.0, 0.0, 0.4)
    for chain_index in range(chain_count):
        previous = parent
        x = (float(chain_index) - float(chain_count - 1) * 0.5) * 0.16
        for depth in range(chain_length):
            bone = data.edit_bones.new(f"Chain{chain_index}_{depth}")
            bone.head = (x, depth * 0.18, 0.4 + depth * 0.04)
            bone.tail = (x + depth * 0.01, (depth + 1) * 0.18, 0.44 + depth * 0.04)
            bone.parent = previous
            bone.use_connect = depth > 0 and depth != 3
            previous = bone

    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def _remove_armature(obj) -> None:
    if obj is None or obj.name not in bpy.data.objects:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and not data.users:
        bpy.data.armatures.remove(data)


def _set_frame(world, frame: int, generation: int) -> None:
    context = world.frame_context
    context.previous_frame = frame - 1 if frame > 1 else None
    context.frame = frame
    context.same_frame = False
    context.continuous = frame > 1
    context.raw_dt = 1.0 / 90.0
    context.dt = 1.0 / 90.0
    context.time_scale = 1.0
    context.generation = generation
    context.restart_required = False
    context.reset_requested = False
    world.generation = generation


def _profile(
    *,
    bone_spring: bool,
    hot: bool = False,
    particle_speed_limit: float | None = None,
    self_collision_thickness: float = 0.008,
    gravity: float | None = None,
    gravity_direction: tuple[float, float, float] | None = None,
    gravity_falloff: float = 0.0,
):
    return parameters.make_mc2_particle_profile(
        gravity=(0.0 if bone_spring else 3.0) if gravity is None else gravity,
        gravity_direction=(0.25, -0.5, -1.0) if gravity_direction is None else gravity_direction,
        gravity_falloff=gravity_falloff,
        damping=0.31 if hot else 0.08,
        stabilization_time_after_reset=0.18 if hot else 0.0,
        particle_speed_limit=(
            0.09 if hot else 3.5
        ) if particle_speed_limit is None else particle_speed_limit,
        radius=0.032 if hot else 0.025,
        tether_compression=0.35,
        distance_stiffness=0.43 if hot else 0.72,
        bending_stiffness=0.0 if bone_spring else 0.55,
        angle_restoration_enabled=not hot,
        angle_restoration_stiffness=0.62,
        angle_restoration_velocity_attenuation=0.3,
        angle_restoration_gravity_falloff=0.2,
        angle_limit_enabled=not hot,
        angle_limit=42.0,
        angle_limit_stiffness=0.8,
        max_distance_enabled=not bone_spring and not hot,
        max_distance=0.28,
        backstop_enabled=not bone_spring and not hot,
        backstop_radius=0.2,
        backstop_distance=0.04,
        motion_stiffness=0.7,
        collision_mode=1,
        collision_friction=0.2,
        collision_limit_distance=0.035,
        self_collision_mode=0 if bone_spring else 2,
        self_collision_thickness=self_collision_thickness,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _requests(
    cloth,
    spring,
    *,
    hot: bool = False,
    spring_particle_speed_limit: float | None = None,
    self_collision_thickness: float = 0.008,
    cloth_mass: float = 0.4,
):
    cloth_requests, _cloth_names = nodes.physicsMC2BoneClothTask(
        [{"armature": cloth, "bone": "Parent"}],
        profile=_profile(
            bone_spring=False,
            hot=hot,
            self_collision_thickness=self_collision_thickness,
        ),
        connection_mode=1,
        cloth_mass=cloth_mass,
        collided_by_groups=1,
        teleport_mode=2,
        teleport_distance=0.24 if hot else 0.5,
        teleport_rotation=35.0 if hot else 90.0,
    )
    spring_requests, _spring_names = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": spring,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
        }],
        profile=_profile(
            bone_spring=True,
            hot=hot,
            particle_speed_limit=spring_particle_speed_limit,
        ),
        collided_by_groups=1,
        teleport_mode=2,
        teleport_distance=0.24 if hot else 0.5,
        teleport_rotation=35.0 if hot else 90.0,
    )
    requests = tuple(cloth_requests + spring_requests)
    assert len(requests) == 2
    return requests


def _slot_ids(requests) -> tuple[str, ...]:
    return tuple(
        product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for request in requests
    )


def _constraint_kinds(owner) -> set[str]:
    return {table.kind for table in owner.compiled.program.constraint_tables}


def _run_once(
    run_index: int,
    *,
    self_collision_thickness: float = 0.008,
    cloth_mass: float = 0.4,
) -> str:
    world = world_types.PhysicsWorldCache()
    generation = 810 + run_index
    cloth = spring = None
    owners = None
    digest = hashlib.sha256()
    try:
        cloth = _armature(
            f"MC2ProductConstraintCloth{run_index}",
            chain_count=2,
            chain_length=6,
            x_offset=-0.35,
        )
        spring = _armature(
            f"MC2ProductConstraintSpring{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.35,
        )
        requests = _requests(
            cloth,
            spring,
            self_collision_thickness=self_collision_thickness,
            cloth_mass=cloth_mass,
        )
        slot_ids = _slot_ids(requests)
        expected_particles = None

        for frame in range(1, 901):
            phase = frame * 0.019
            for index, armature in enumerate((cloth, spring)):
                parent = armature.pose.bones["Parent"]
                parent.rotation_mode = "XYZ"
                parent.rotation_euler.z = (0.18 + index * 0.05) * math.sin(phase)
                parent.rotation_euler.x = 0.08 * math.cos(phase * 0.7)
                parent.location.x = 0.015 * math.sin(phase * 0.5 + index)
            bpy.context.view_layer.update()

            _set_frame(world, frame, generation)
            world.collider_snapshot = {
                "frame": frame,
                "colliders": [{
                    "key": "bone-product-soak-sphere",
                    "type": "SPHERE",
                    "primary_group": 1,
                    "center": (50.0, 0.0, 0.0),
                    "radius": 1.0,
                }],
            }
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
                cloth_kinds = _constraint_kinds(owners[0])
                spring_kinds = _constraint_kinds(owners[1])
                print("MC2_BONE_PRODUCT_CONSTRAINT_KINDS", cloth_kinds, spring_kinds)
                assert cloth_kinds == {"distance", "tether", "bending"}
                assert spring_kinds == {"distance", "tether"}
                partition_fields = set(
                    owners[0].compiled.parameters.partition_parameters.fields
                )
                particle_fields = set(
                    owners[0].compiled.parameters.particle_parameters.fields
                )
                particle_parameters = owners[0].compiled.parameters.particle_parameters
                self_thickness_index = particle_parameters.fields.index(
                    "self_collision_thickness"
                )
                np.testing.assert_allclose(
                    particle_parameters.values[:, self_thickness_index],
                    0.025 * 0.25,
                    atol=1.0e-6,
                )
                cloth_mass_table = next(
                    table
                    for table in (
                        owners[0].compiled.parameters.domain_scalars,
                        owners[0].compiled.parameters.partition_parameters,
                        owners[0].compiled.parameters.particle_parameters,
                    )
                    if "cloth_mass" in table.fields
                )
                cloth_mass_index = cloth_mass_table.fields.index("cloth_mass")
                np.testing.assert_allclose(
                    cloth_mass_table.values[:, cloth_mass_index],
                    cloth_mass,
                    atol=1.0e-6,
                )
                assert {
                    "angle_restoration_velocity_attenuation",
                    "angle_restoration_gravity_falloff",
                    "angle_limit_stiffness",
                    "motion_stiffness",
                    "backstop_radius",
                } <= partition_fields
                assert {
                    "angle_restoration_stiffness",
                    "angle_limit",
                    "max_distance",
                    "backstop_distance",
                } <= particle_fields
                expected_particles = sum(
                    owner.compiled.program.particle_count for owner in owners
                )
            else:
                assert current_owners == owners
                assert all(slot.data["last_sync"].native_domain_reused for slot in slots)

            for request, slot, owner in zip(requests, slots, current_owners):
                assert "native_context" not in slot.data
                assert "spec" not in slot.data
                output = owner.read_output()
                assert output.frame == frame and output.generation == generation
                assert np.all(np.isfinite(output.world_positions))
                assert np.all(np.isfinite(output.world_rotations_xyzw))
                inspection = owner.inspect()
                kernel = inspection["domain"]["kernel"]
                assert kernel["compiled_external_ready"] is True
                if frame > 1:
                    assert inspection["domain"]["step_count"] > 0
                    assert kernel["compiled_external_step_count"] > 0
                if request.setup_type == "bone_cloth":
                    assert kernel["whole_domain_self_ready"] is True
                    if frame > 1:
                        assert kernel["whole_domain_self_step_count"] > 0
                if frame in (1, 450, 900):
                    dynamics = owner.read_debug_state()
                    real_velocities = dynamics["real_velocities"]
                    assert real_velocities.shape == output.world_positions.shape
                    assert np.all(np.isfinite(real_velocities))
                    digest.update(real_velocities.tobytes())
                digest.update(output.world_positions.tobytes())
                digest.update(output.world_rotations_xyzw.tobytes())

            results = tuple(world.result_streams.get("bone_transform", ()))
            assert results
            assert sum(int(result["bone_count"]) for result in results) == expected_particles
            assert writeback.writeback_bone_transforms(world) == expected_particles
            bpy.context.view_layer.update()
            digest.update(np.asarray(frame, dtype=np.int32).tobytes())

        assert owners is not None
        assert all(owner.inspect()["domain"]["step_count"] >= 899 for owner in owners)
        return digest.hexdigest()
    finally:
        world.omni_cache_dispose("bone_product_constraint_soak_cleanup")
        _remove_armature(cloth)
        _remove_armature(spring)


def test_bone_product_constraints_900_frame_deterministic_soak() -> None:
    first = _run_once(0)
    second = _run_once(1)
    assert first == second, (first, second)
    print(f"MC2_BONE_PRODUCT_CONSTRAINT_DIGEST {first}")


def test_bone_product_self_collision_domain_contract() -> None:
    first = _run_once(20, self_collision_thickness=0.008, cloth_mass=0.4)
    second = _run_once(21, self_collision_thickness=0.008, cloth_mass=0.4)
    assert first == second, (first, second)
    print(f"MC2_BONE_PRODUCT_SELF_CONTRACT_DIGEST {first}")


def test_bone_product_frame_transform_contract() -> None:
    armature = None
    parent = None
    try:
        armature = _armature(
            "MC2ProductFrameTransform",
            chain_count=1,
            chain_length=1,
            x_offset=0.0,
        )
        request = product_bone_authoring.make_mc2_bone_cloth_product_request(
            [{
                "armature": armature,
                "bones": ("Parent", "Chain0_0"),
            }],
            profile=_profile(bone_spring=False),
            setup_options=parameters.make_mc2_setup_options(
                "bone_cloth",
                connection_mode=0,
            ),
        )
        partition = request.plan.active_partitions[0]
        fingerprint, snapshots = topology.prepare_static_inputs_for_partition(
            partition
        )
        product_topology = topology.build_mc2_partition_topology_spec(
            partition,
            static_input_fingerprint=fingerprint,
            static_input_snapshots=snapshots,
        )
        bpy.context.view_layer.update()
        frame_input = bone_frame.build_mc2_bone_partition_frame_input(
            partition,
            product_topology,
            frame=12,
            generation=4,
        )
        assert frame_input.native_producer_kind == "bone"
        assert frame_input.particle_count == 2
        assert frame_input.world_positions.flags.writeable is False
        assert frame_input.world_rotations_xyzw.flags.writeable is False
        assert frame_input.raw_pose_matrices.shape == (2, 3, 3)
        assert frame_input.raw_pose_matrices.flags.writeable is False
        names = tuple(product_topology.sources[0].bone_names)
        parent_index = names.index("Parent")
        expected_root = armature.matrix_world @ armature.pose.bones["Parent"].head
        np.testing.assert_allclose(
            frame_input.world_positions[parent_index],
            (expected_root.x, expected_root.y, expected_root.z),
            rtol=1.0e-6,
            atol=1.0e-6,
        )
        assert frame_input.center_frame_pose is not None

        armature.scale = (-1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        negative = bone_frame.build_mc2_bone_partition_frame_input(
            partition,
            product_topology,
            frame=13,
            generation=4,
        )
        assert negative.negative_scale_sign == -1.0
        np.testing.assert_allclose(
            negative.center_frame_pose.component_world_scale,
            (-1.0, 1.0, 1.0),
            atol=1.0e-6,
        )

        armature.scale = (0.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        try:
            bone_frame.build_mc2_bone_partition_frame_input(
                partition,
                product_topology,
                frame=13,
                generation=4,
            )
        except ValueError as exc:
            assert "zero scale" in str(exc)
        else:
            raise AssertionError("zero-scale Bone product frame was accepted")

        armature.scale = (1.0, 1.0, 1.0)
        parent = bpy.data.objects.new("MC2ProductFrameTransformParent", None)
        bpy.context.scene.collection.objects.link(parent)
        armature.parent = parent
        armature.matrix_parent_inverse.identity()
        parent.scale = (-1.0, 1.0, 1.0)
        bpy.context.view_layer.update()
        try:
            bone_frame.build_mc2_bone_partition_frame_input(
                partition,
                product_topology,
                frame=14,
                generation=4,
            )
        except ValueError as exc:
            assert "negative scale inherited from a parent" in str(exc)
        else:
            raise AssertionError("negative parent scale reached Bone product frame")

        parent.scale = (2.0, 1.0, 0.5)
        armature.rotation_mode = "XYZ"
        armature.rotation_euler.y = 0.5
        bpy.context.view_layer.update()
        try:
            bone_frame.build_mc2_bone_partition_frame_input(
                partition,
                product_topology,
                frame=14,
                generation=4,
            )
        except ValueError as exc:
            assert "shear-free" in str(exc)
        else:
            raise AssertionError("sheared Bone component reached product frame")
        print("PASS test_bone_product_frame_transform_contract")
    finally:
        if parent is not None:
            armature.parent = None
            bpy.data.objects.remove(parent, do_unlink=True)
        _remove_armature(armature)


def _run_bone_gravity_case(
    run_index: int,
    *,
    gravity_direction: tuple[float, float, float],
    gravity_falloff: float,
) -> tuple[str, np.ndarray]:
    world = world_types.PhysicsWorldCache()
    generation = 1500 + run_index
    armature = None
    digest = hashlib.sha256()
    trajectory = []
    try:
        armature = _armature(
            f"MC2ProductGravity{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.0,
        )
        requests, _names = nodes.physicsMC2BoneClothTask(
            [{"armature": armature, "bone": "Parent"}],
            profile=_profile(
                bone_spring=False,
                gravity=4.0,
                gravity_direction=gravity_direction,
                gravity_falloff=gravity_falloff,
            ),
            connection_mode=0,
            normal_axis=2,
            teleport_mode=0,
        )
        assert len(requests) == 1
        request = requests[0]
        slot_id = product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        owner = None
        for frame in range(1, 601):
            parent = armature.pose.bones["Parent"]
            parent.rotation_mode = "XYZ"
            parent.rotation_euler.z = 0.25 * math.sin(frame * 0.09)
            bpy.context.view_layer.update()
            _set_frame(world, frame, generation)
            world.collider_snapshot = {"frame": frame, "colliders": []}
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
                table = owner.compiled.parameters.partition_parameters
                values = dict(zip(table.fields, table.values[0]))
                np.testing.assert_allclose(
                    [values["gravity_direction_x"], values["gravity_direction_y"], values["gravity_direction_z"]],
                    np.asarray(gravity_direction, dtype=np.float32) / np.linalg.norm(gravity_direction),
                    rtol=0.0, atol=1.0e-6,
                )
                np.testing.assert_allclose(values["gravity"], 4.0, rtol=0.0, atol=1.0e-6)
                np.testing.assert_allclose(values["gravity_falloff"], gravity_falloff, rtol=0.0, atol=1.0e-6)
            else:
                assert current_owner is owner
            output = owner.read_output()
            assert np.all(np.isfinite(output.world_positions))
            assert np.all(np.isfinite(output.world_rotations_xyzw))
            trajectory.append(np.array(output.world_positions, copy=True))
            digest.update(output.world_positions.tobytes())
            digest.update(output.world_rotations_xyzw.tobytes())
            assert writeback.writeback_bone_transforms(world) == output.world_positions.shape[0]
            bpy.context.view_layer.update()
        assert owner is not None
        assert owner.inspect()["domain"]["step_count"] >= 599
        return digest.hexdigest(), np.asarray(trajectory, dtype=np.float32)
    finally:
        world.omni_cache_dispose("bone_product_gravity_cleanup")
        _remove_armature(armature)


def test_bone_product_gravity_axes_falloff() -> None:
    direction = (1.0, -0.25, -0.5)
    first_digest, first = _run_bone_gravity_case(0, gravity_direction=direction, gravity_falloff=0.35)
    second_digest, second = _run_bone_gravity_case(1, gravity_direction=direction, gravity_falloff=0.35)
    assert first_digest == second_digest, (first_digest, second_digest)
    np.testing.assert_array_equal(first, second)
    x_digest, x_axis = _run_bone_gravity_case(2, gravity_direction=(1.0, 0.0, 0.0), gravity_falloff=0.0)
    z_digest, z_axis = _run_bone_gravity_case(3, gravity_direction=(0.0, 0.0, -1.0), gravity_falloff=0.0)
    assert x_digest != z_digest
    assert not np.array_equal(x_axis, z_axis)
    print("MC2_BONE_PRODUCT_GRAVITY_DIGESTS", first_digest, x_digest, z_digest)
    print("PASS test_bone_product_gravity_axes_falloff")


if __name__ == "__main__":
    test_bone_product_constraints_900_frame_deterministic_soak()
    print("PASS test_bone_product_constraints_900_frame_deterministic_soak")
