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
):
    return parameters.make_mc2_particle_profile(
        gravity=0.0 if bone_spring else 3.0,
        gravity_direction=(0.25, -0.5, -1.0),
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
        self_collision_thickness=0.008,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _requests(
    cloth,
    spring,
    *,
    hot: bool = False,
    spring_particle_speed_limit: float | None = None,
):
    cloth_requests, _cloth_names = nodes.physicsMC2BoneClothTask(
        [{"armature": cloth, "bone": "Parent"}],
        profile=_profile(bone_spring=False, hot=hot),
        connection_mode=1,
        cloth_mass=0.4,
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


def _run_once(run_index: int) -> str:
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
        requests = _requests(cloth, spring)
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


if __name__ == "__main__":
    test_bone_product_constraints_900_frame_deterministic_soak()
    print("PASS test_bone_product_constraints_900_frame_deterministic_soak")
