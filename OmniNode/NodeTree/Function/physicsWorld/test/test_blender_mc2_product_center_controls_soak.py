"""三种setup公开产品统一域的Center控制长程验收。"""

from __future__ import annotations

import hashlib
import math
import os
import sys

import bpy
import numpy as np


TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
if TEST_ROOT not in sys.path:
    sys.path.insert(0, TEST_ROOT)

import test_blender_mc2_product_mixed_output_soak as mixed_soak


bone_soak = mixed_soak.bone_soak
nodes = mixed_soak.nodes
parameters = mixed_soak.parameters
product_slot = mixed_soak.product_slot
world_types = mixed_soak.world_types
writeback = mixed_soak.writeback

print(f"MC2_PRODUCT_CENTER_SOURCE {__file__}")
print(f"MC2_PRODUCT_CENTER_NODES {nodes.__file__}")
print(f"MC2_PRODUCT_CENTER_NATIVE {bone_soak.hotools_native.__file__}")

_FRAME_RATE = 30.0
_SETUPS = ("mesh_cloth", "bone_cloth", "bone_spring")


def _profile(*, spring: bool):
    return parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.0,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=100.0,
        radius=0.02,
        distance_stiffness=0.0,
        bending_stiffness=0.0,
        angle_restoration_enabled=False,
        angle_limit_enabled=False,
        max_distance_enabled=False,
        backstop_enabled=False,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        wind_influence=0.0,
    )


def _requests(
    world,
    mesh,
    cloth,
    spring,
    *,
    anchor_object=None,
    anchor_inertia: float = 0.0,
    world_inertia: float,
    movement_inertia_smoothing: float,
    movement_speed_limit: float,
    rotation_speed_limit: float,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
):
    task_values = {
        "anchor_inertia": anchor_inertia,
        "world_inertia": world_inertia,
        "movement_inertia_smoothing": movement_inertia_smoothing,
        "movement_speed_limit": movement_speed_limit,
        "rotation_speed_limit": rotation_speed_limit,
        "local_inertia": local_inertia,
        "local_movement_speed_limit": local_movement_speed_limit,
        "local_rotation_speed_limit": local_rotation_speed_limit,
        "depth_inertia": depth_inertia,
        "teleport_mode": 0,
        "teleport_distance": 100.0,
        "teleport_rotation": 180.0,
    }
    entries, count = nodes.physicsMC2MeshObject([mesh])
    assert count == 1 and len(entries) == 1
    entries, count = nodes.physicsMC2MeshOverride(
        entries,
        profile=_profile(spring=False),
        anchor_object=anchor_object,
        **task_values,
    )
    assert count == 1
    mesh_requests, report = nodes.physicsMC2MeshCollector(
        world,
        entries,
        include_implicit=False,
    )
    assert len(mesh_requests) == 1 and report

    cloth_requests, _cloth_report = nodes.physicsMC2BoneClothTask(
        [{"armature": cloth, "bone": "Parent"}],
        profile=_profile(spring=False),
        anchor_object=anchor_object,
        connection_mode=0,
        **task_values,
    )
    spring_requests, _spring_report = nodes.physicsMC2BoneSpringTask(
        [{
            "armature": spring,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
        }],
        profile=_profile(spring=True),
        anchor_object=anchor_object,
        **task_values,
    )
    requests = tuple(mesh_requests + cloth_requests + spring_requests)
    assert tuple(request.setup_type for request in requests) == _SETUPS
    return requests


def _slot_ids(requests):
    return tuple(
        product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for request in requests
    )


def _translation_velocity(frame: int) -> float:
    if frame <= 200:
        return 0.9
    if frame <= 400:
        return -0.45
    return 0.3


def _rotation_degrees(quaternion) -> float:
    cosine = min(1.0, max(0.0, abs(float(quaternion[3]))))
    return math.degrees(2.0 * math.acos(cosine))


def _remove_object(obj) -> None:
    if obj is not None and obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def _run_world_case(
    case_name: str,
    run_index: int,
    *,
    anchor_enabled: bool = False,
    anchor_inertia: float = 0.0,
    component_translation: bool = True,
    component_rotation_speed: float = 0.0,
    world_inertia: float,
    movement_inertia_smoothing: float,
    movement_speed_limit: float,
    rotation_speed_limit: float,
    local_inertia: float = 1.0,
    local_movement_speed_limit: float = -1.0,
    local_rotation_speed_limit: float = -1.0,
    depth_inertia: float = 0.0,
    read_center_debug: bool = False,
):
    world = world_types.PhysicsWorldCache()
    generation = 1300 + run_index
    mesh = proxy = cloth = spring = driver = anchor = None
    owners = None
    observations = {
        setup: {
            "shift_x": [],
            "shift_rotation_degrees": [],
            "shift_count": [],
            "step_count": [],
            "inertia_x": [],
            "step_x": [],
            "movement_speed_limited": [],
            "anchor_shift_x": [],
        }
        for setup in _SETUPS
    }
    digest = hashlib.sha256()
    try:
        mixed_soak.physics_blender.register()
        mesh, proxy = mixed_soak._mesh_object(
            f"MC2ProductCenter{case_name}Mesh{run_index}"
        )
        cloth = bone_soak._armature(
            f"MC2ProductCenter{case_name}Cloth{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=-0.3,
        )
        spring = bone_soak._armature(
            f"MC2ProductCenter{case_name}Spring{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.3,
        )
        sources = (mesh, cloth, spring)
        base_x = tuple(float(source.location.x) for source in sources)
        if anchor_enabled:
            driver = bpy.data.objects.new(
                f"MC2ProductCenter{case_name}Driver{run_index}", None
            )
            anchor = bpy.data.objects.new(
                f"MC2ProductCenter{case_name}Anchor{run_index}", None
            )
            bpy.context.scene.collection.objects.link(driver)
            bpy.context.scene.collection.objects.link(anchor)
            constraint = anchor.constraints.new("COPY_TRANSFORMS")
            constraint.target = driver
        requests = _requests(
            world,
            mesh,
            cloth,
            spring,
            anchor_object=anchor,
            anchor_inertia=anchor_inertia,
            world_inertia=world_inertia,
            movement_inertia_smoothing=movement_inertia_smoothing,
            movement_speed_limit=movement_speed_limit,
            rotation_speed_limit=rotation_speed_limit,
            local_inertia=local_inertia,
            local_movement_speed_limit=local_movement_speed_limit,
            local_rotation_speed_limit=local_rotation_speed_limit,
            depth_inertia=depth_inertia,
        )
        slot_ids = _slot_ids(requests)
        component_x = 0.0
        component_rotation_degrees = 0.0

        for frame in range(1, 601):
            if frame > 1 and component_translation:
                component_x += _translation_velocity(frame) / _FRAME_RATE
            if frame > 1:
                component_rotation_degrees += (
                    component_rotation_speed / _FRAME_RATE
                )
            for source, initial_x in zip(sources, base_x):
                source.location.x = initial_x + component_x
                source.rotation_mode = "XYZ"
                source.rotation_euler.z = math.radians(
                    component_rotation_degrees
                )
            if driver is not None:
                driver.location.x = component_x
                driver.rotation_mode = "XYZ"
                driver.rotation_euler.z = math.radians(component_rotation_degrees)
            bpy.context.view_layer.update()

            bone_soak._set_frame(world, frame, generation)
            world.frame_context.raw_dt = 1.0 / _FRAME_RATE
            world.frame_context.dt = 1.0 / _FRAME_RATE
            world.collider_snapshot = {"frame": frame, "colliders": []}
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
            else:
                assert current_owners == owners
                assert all(
                    slot.data["last_sync"].native_domain_reused
                    for slot in slots
                )

            for setup, slot, owner in zip(_SETUPS, slots, current_owners):
                assert "native_context" not in slot.data
                assert "spec" not in slot.data
                assert "_debug_draw_snapshot" not in slot.data
                output = owner.read_output()
                assert output.frame == frame
                assert output.generation == generation
                assert np.all(np.isfinite(output.world_positions))
                assert np.all(np.isfinite(output.world_rotations_xyzw))
                if frame > 1:
                    kernel = owner.inspect()["domain"]["kernel"]
                    shift = np.asarray(
                        kernel["center_shift_vectors"],
                        dtype=np.float32,
                    )
                    rotations = np.asarray(
                        kernel["center_shift_rotations"],
                        dtype=np.float32,
                    )
                    assert shift.shape == (1, 3)
                    assert rotations.shape == (1, 4)
                    values = observations[setup]
                    values["shift_x"].append(float(shift[0, 0]))
                    values["shift_rotation_degrees"].append(
                        _rotation_degrees(rotations[0])
                    )
                    values["shift_count"].append(
                        float(kernel["center_shift_count"])
                    )
                    values["step_count"].append(
                        float(kernel["center_step_count"])
                    )
                    if read_center_debug:
                        debug_state = owner.read_center_debug_state()
                        inertia_vectors = np.asarray(
                            debug_state["inertia_vectors"],
                            dtype=np.float32,
                        ).reshape((-1, 3))
                        step_vectors = np.asarray(
                            debug_state["step_vectors"],
                            dtype=np.float32,
                        ).reshape((-1, 3))
                        values["inertia_x"].append(
                            float(inertia_vectors[0, 0])
                        )
                        values["step_x"].append(float(step_vectors[0, 0]))
                        values["movement_speed_limited"].append(
                            bool(np.asarray(
                                debug_state["movement_speed_limited"],
                                dtype=np.uint8,
                            ).reshape((-1,))[0])
                        )
                        values["anchor_shift_x"].append(
                            float(np.asarray(
                                debug_state["anchor_shift_vectors"],
                                dtype=np.float32,
                            ).reshape((-1, 3))[0, 0])
                        )
                digest.update(setup.encode("ascii"))
                digest.update(output.world_positions.tobytes())
                digest.update(output.world_rotations_xyzw.tobytes())

            assert writeback.writeback_gn_attributes(world) == 1
            bone_results = tuple(
                world.result_streams.get("bone_transform", ())
            )
            expected_bones = sum(
                int(result["bone_count"]) for result in bone_results
            )
            assert expected_bones > 0
            assert writeback.writeback_bone_transforms(world) == expected_bones
            bpy.context.view_layer.update()

        frozen = {
            setup: {
                name: np.asarray(values, dtype=np.float32)
                for name, values in setup_values.items()
            }
            for setup, setup_values in observations.items()
        }
        return frozen, digest.hexdigest()
    finally:
        world.omni_cache_dispose(f"product_center_world_{case_name}")
        bone_soak._remove_armature(cloth)
        bone_soak._remove_armature(spring)
        mixed_soak._remove_mesh(mesh)
        mixed_soak._remove_mesh(proxy)
        _remove_object(driver)
        _remove_object(anchor)
        if mixed_soak.physics_blender.is_registered():
            mixed_soak.physics_blender.unregister()


def _run_center_world_suite(run_index: int):
    case_definitions = {
        "follow": {
            "world_inertia": 0.0,
            "movement_inertia_smoothing": 0.0,
            "movement_speed_limit": -1.0,
            "rotation_speed_limit": -1.0,
        },
        "hold": {
            "world_inertia": 1.0,
            "movement_inertia_smoothing": 0.0,
            "movement_speed_limit": -1.0,
            "rotation_speed_limit": -1.0,
        },
        "smooth": {
            "world_inertia": 1.0,
            "movement_inertia_smoothing": 0.8,
            "movement_speed_limit": -1.0,
            "rotation_speed_limit": -1.0,
        },
        "limited": {
            "world_inertia": 1.0,
            "movement_inertia_smoothing": 0.0,
            "movement_speed_limit": 0.2,
            "rotation_speed_limit": -1.0,
        },
        "rotation_limited": {
            "component_translation": False,
            "component_rotation_speed": 90.0,
            "world_inertia": 1.0,
            "movement_inertia_smoothing": 0.0,
            "movement_speed_limit": -1.0,
            "rotation_speed_limit": 30.0,
        },
    }
    cases = {}
    digest = hashlib.sha256()
    for case_index, (case_name, values) in enumerate(
        case_definitions.items()
    ):
        case, case_digest = _run_world_case(
            case_name,
            run_index * 10 + case_index,
            **values,
        )
        cases[case_name] = case
        digest.update(case_name.encode("ascii"))
        digest.update(case_digest.encode("ascii"))

    input_velocity = np.asarray(
        [_translation_velocity(frame) for frame in range(2, 601)],
        dtype=np.float32,
    )
    input_delta = input_velocity / np.float32(_FRAME_RATE)
    for setup in _SETUPS:
        follow = cases["follow"][setup]
        hold = cases["hold"][setup]
        smooth = cases["smooth"][setup]
        limited = cases["limited"][setup]
        rotation_limited = cases["rotation_limited"][setup]
        np.testing.assert_array_equal(
            follow["shift_count"],
            np.arange(1, 600, dtype=np.float32),
        )
        step_deltas = np.diff(
            np.concatenate(
                (np.zeros(1, dtype=np.float32), follow["step_count"])
            )
        )
        assert np.all((step_deltas >= 2.0) & (step_deltas <= 3.0))
        assert int(follow["step_count"][-1]) >= 1790
        np.testing.assert_allclose(
            follow["shift_x"],
            input_delta,
            rtol=0.0,
            atol=2.0e-6,
        )
        hold_transient = np.abs(hold["shift_x"]) > 2.0e-6
        assert int(np.count_nonzero(hold_transient)) <= 3
        assert np.all(np.abs(hold["shift_x"][hold_transient]) <= 0.010001)
        np.testing.assert_allclose(
            hold["shift_x"][~hold_transient],
            0.0,
            rtol=0.0,
            atol=2.0e-6,
        )
        residual_speed = (
            np.abs(input_delta - limited["shift_x"]) * _FRAME_RATE
        )
        limited_transient = np.abs(residual_speed - 0.2) > 2.0e-4
        assert int(np.count_nonzero(limited_transient)) <= 3
        assert np.all(
            (residual_speed[limited_transient] >= 0.0)
            & (residual_speed[limited_transient] <= 0.200001)
        )
        np.testing.assert_allclose(
            residual_speed[~limited_transient],
            0.2,
            rtol=0.0,
            atol=2.0e-4,
        )
        assert np.max(np.abs(smooth["shift_x"] - hold["shift_x"])) > 1.0e-4
        assert np.max(
            np.abs(smooth["shift_x"] - follow["shift_x"])
        ) > 1.0e-4
        assert np.all(
            np.abs(follow["shift_x"]) + 2.0e-6
            >= np.abs(limited["shift_x"])
        )
        assert np.all(
            np.abs(limited["shift_x"]) + 2.0e-6
            >= np.abs(hold["shift_x"])
        )
        rotation_values = rotation_limited["shift_rotation_degrees"]
        rotation_transient = np.abs(rotation_values - 2.0) > 2.0e-3
        assert int(np.count_nonzero(rotation_transient)) <= 3
        assert np.all(
            (rotation_values[rotation_transient] >= 0.0)
            & (rotation_values[rotation_transient] <= 2.3331)
        )
        np.testing.assert_allclose(
            rotation_values[~rotation_transient],
            2.0,
            rtol=0.0,
            atol=2.0e-3,
        )
        for case_name in cases:
            for array in cases[case_name][setup].values():
                assert np.all(np.isfinite(array))
    return digest.hexdigest()


def center_world_controls():
    first = _run_center_world_suite(0)
    second = _run_center_world_suite(1)
    assert second == first, (first, second)
    print(
        "PASS 产品Center World惯性/平滑/平移与旋转限速："
        "3 setup x 5 case x 2 run x 600 frame"
    )


def center_local_controls():
    case_definitions = {
        "inertia_zero": {
            "component_rotation_speed": 90.0,
            "world_inertia": 1.0,
            "local_inertia": 0.0,
            "local_movement_speed_limit": -1.0,
            "local_rotation_speed_limit": -1.0,
        },
        "inertia_one": {
            "component_rotation_speed": 90.0,
            "world_inertia": 1.0,
            "local_inertia": 1.0,
            "local_movement_speed_limit": -1.0,
            "local_rotation_speed_limit": -1.0,
        },
        "movement_limited": {
            "component_rotation_speed": 0.0,
            "world_inertia": 1.0,
            "local_inertia": 1.0,
            "local_movement_speed_limit": 0.2,
            "local_rotation_speed_limit": -1.0,
        },
        "rotation_limited": {
            "component_translation": False,
            "component_rotation_speed": 90.0,
            "world_inertia": 1.0,
            "local_inertia": 1.0,
            "local_movement_speed_limit": -1.0,
            "local_rotation_speed_limit": 30.0,
        },
    }

    def run(run_index):
        cases = {}
        for case_index, (case_name, values) in enumerate(
            case_definitions.items()
        ):
            cases[case_name] = _run_world_case(
                f"Local{case_name}",
                run_index * 10 + case_index,
                read_center_debug=True,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                **values,
            )
        return cases

    first = run(0)
    second = run(1)
    for name in case_definitions:
        for setup in _SETUPS:
            for field in first[name][0][setup]:
                np.testing.assert_array_equal(
                    first[name][0][setup][field],
                    second[name][0][setup][field],
                )
    for setup in _SETUPS:
        zero = first["inertia_zero"][0][setup]
        one = first["inertia_one"][0][setup]
        np.testing.assert_allclose(zero["inertia_x"], zero["step_x"], atol=2.0e-6)
        np.testing.assert_allclose(one["inertia_x"], 0.0, atol=2.0e-6)
        movement = first["movement_limited"][0][setup]
        movement_speed = np.abs(movement["step_x"]) * _FRAME_RATE
        active = movement_speed > 0.2001
        if setup == "mesh_cloth":
            np.testing.assert_allclose(movement["inertia_x"], 0.0, atol=2.0e-6)
        else:
            assert np.max(np.abs(movement["inertia_x"])) > 1.0e-4
            assert np.max(np.abs(movement["inertia_x"])) < np.max(
                np.abs(movement["step_x"])
            )
    print("PASS 产品Center Local惯性/平移与旋转限速")


def center_anchor_controls():
    def run(run_index):
        result = {}
        for case_index, anchor_inertia in enumerate((0.0, 1.0)):
            result[anchor_inertia] = _run_world_case(
                f"Anchor{int(anchor_inertia)}",
                run_index * 10 + case_index,
                anchor_enabled=True,
                anchor_inertia=anchor_inertia,
                world_inertia=1.0,
                movement_inertia_smoothing=0.0,
                movement_speed_limit=-1.0,
                rotation_speed_limit=-1.0,
                read_center_debug=True,
            )
        return result

    first = run(0)
    second = run(1)
    for anchor_inertia in first:
        for setup in _SETUPS:
            for field in first[anchor_inertia][0][setup]:
                np.testing.assert_array_equal(
                    first[anchor_inertia][0][setup][field],
                    second[anchor_inertia][0][setup][field],
                )
            values = first[anchor_inertia][0][setup]
            print(
                "MC2_PRODUCT_CENTER_ANCHOR",
                anchor_inertia,
                setup,
                float(np.max(np.abs(values["anchor_shift_x"]))),
            )
    print("PASS 产品Center Anchor端点与确定性")


if __name__ == "__main__":
    if os.environ.get("MC2_CENTER_ANCHOR_ONLY"):
        center_anchor_controls()
    elif os.environ.get("MC2_CENTER_LOCAL_ONLY"):
        center_local_controls()
    else:
        center_world_controls()
        center_local_controls()
