# -*- coding: utf-8 -*-
"""三种 MC2 setup 消费公共 Field 风的长程产品验收。"""

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

import test_blender_mc2_product_mixed_output_soak as mixed


bone_soak = mixed.bone_soak
mc2_nodes = mixed.nodes
parameters = mixed.parameters
product_slot = mixed.product_slot
physics_blender = mixed.physics_blender
world_types = mixed.world_types

physics_nodes = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.nodes"
)
field_names = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.field.names"
)


SETUPS = ("mesh_cloth", "bone_cloth", "bone_spring")
SCENARIOS = (
    "baseline",
    "profile_disabled",
    "uniform",
    "scope_mesh_cloth",
    "scope_bone_cloth",
    "scope_bone_spring",
)
FRAME_COUNT = 600
OUTPUT_FPS = 60
WIND_SPEED_MPS = 6.0
WIND_RESPONSE_STRENGTH = 2.0


def _field_profile(*, setup_type: str, enabled: bool):
    bone_spring = setup_type == "bone_spring"
    return parameters.make_mc2_particle_profile(
        gravity=0.0,
        damping=0.04,
        stabilization_time_after_reset=0.0,
        particle_speed_limit=20.0,
        radius=0.02,
        tether_compression=0.35,
        distance_stiffness=0.72,
        bending_stiffness=0.0 if bone_spring else 0.45,
        angle_restoration_enabled=not bone_spring,
        angle_restoration_stiffness=0.55,
        angle_limit_enabled=not bone_spring,
        angle_limit=55.0,
        max_distance_enabled=False,
        backstop_enabled=False,
        motion_stiffness=0.0,
        collision_mode=0,
        self_collision_mode=0,
        spring_enabled=False,
        field_wind_enabled=enabled,
        field_wind_strength=WIND_RESPONSE_STRENGTH,
    )


def _requests(mesh, cloth, spring, *, field_wind_enabled: bool):
    mesh_objects, mesh_count = mc2_nodes.physicsMC2MeshObject([mesh])
    assert mesh_count == 1
    mesh_entries, _mesh_domain_ids = mc2_nodes.physicsMC2MeshClothTask(
        mesh_objects,
        profile=_field_profile(
            setup_type="mesh_cloth",
            enabled=field_wind_enabled,
        ),
    )
    mesh_requests, _mesh_report = mc2_nodes.physicsMC2MeshCollector(mesh_entries)

    cloth_objects, cloth_count = mc2_nodes.physicsMC2BoneClothCustomObject(
        [{"armature": cloth, "bone": "Parent"}],
        collided_by_groups=1,
    )
    assert cloth_count == 1
    cloth_entries, _cloth_names = mc2_nodes.physicsMC2BoneClothTask(
        cloth_objects,
        profile=_field_profile(
            setup_type="bone_cloth",
            enabled=field_wind_enabled,
        ),
        connection_mode=1,
        teleport_mode=0,
    )
    cloth_requests, _cloth_report = mc2_nodes.physicsMC2BoneCollector(
        cloth_entries
    )

    spring_requests, _spring_names = mc2_nodes.physicsMC2BoneSpringTask(
        [{
            "armature": spring,
            "root_bone": "Chain0_0",
            "bones": tuple(f"Chain0_{depth}" for depth in range(6)),
        }],
        profile=_field_profile(
            setup_type="bone_spring",
            enabled=field_wind_enabled,
        ),
        collided_by_groups=1,
        teleport_mode=0,
    )
    requests = tuple(mesh_requests + cloth_requests + spring_requests)
    assert tuple(request.setup_type for request in requests) == SETUPS
    return requests


def _slot_ids(requests) -> tuple[str, ...]:
    return tuple(
        product_slot.make_mc2_product_slot_id(
            request.setup_type,
            request.domain_signature,
        )
        for request in requests
    )


def _field_empty(name: str):
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    obj.empty_display_type = "CUBE"
    obj.scale = (100.0, 100.0, 100.0)
    props = obj.hotools_field
    props.enabled = True
    props.field_type = field_names.FIELD_TYPE_WIND
    props.shape = field_names.VOLUME_SHAPE_BOX
    props.speed_mps = WIND_SPEED_MPS
    props.turbulence = 0.0
    props.scope_solver_ids = "mc2"
    props.scope_collision_groups = "1"
    return obj


def _remove_empty(obj) -> None:
    if obj is not None and obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)


def _configure_field(field, scenario: str, source_names: dict[str, str]) -> None:
    props = field.hotools_field
    props.enabled = scenario != "baseline"
    if scenario.startswith("scope_"):
        props.scope_include_ids = source_names[scenario.removeprefix("scope_")]
    else:
        props.scope_include_ids = ""


def _step_scenario(
    world,
    *,
    scene,
    scope,
    requests,
):
    world, frame, _collider_count, _restart = physics_nodes.physicsWorldBegin(
        world,
        scene,
        scope,
        time_scale=1.0,
        substeps=1,
    )
    returned, ready, status = mc2_nodes.physicsMC2Step(
        world,
        list(requests),
        simulation_frequency=90,
        max_simulation_count_per_frame=3,
    )
    assert returned is world and ready is True, status
    assert frame == scene.frame_current
    return world


def _scenario_outputs(world, slot_ids) -> tuple[np.ndarray, ...]:
    outputs = []
    for slot_id in slot_ids:
        slot = world.solver_slots[slot_id]
        output = slot.data["owner"].read_output()
        assert output.frame == world.frame_context.frame
        assert output.generation == world.generation
        assert np.isfinite(output.world_positions).all()
        assert np.isfinite(output.world_rotations_xyzw).all()
        outputs.append(output.world_positions.copy())
    return tuple(outputs)


def _assert_field_time_and_native_state(
    world, slot_ids, *, uniform: bool, responsive_setups: frozenset[str]
) -> None:
    frame_context = world.frame_context
    assert math.isclose(
        frame_context.raw_dt,
        1.0 / OUTPUT_FPS,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    )
    for setup_type, slot_id in zip(SETUPS, slot_ids, strict=True):
        slot = world.solver_slots[slot_id]
        scheduled = slot.data["scheduled_frame"]
        update_count = scheduled.schedule.update_count
        assert slot.data["frame_complete"] is True
        state = slot.data["owner"].inspect()["domain"]["kernel"]
        runtime = world.runtime_cache(
            field_names.FIELD_NATIVE_RUNTIME_CACHE_KEY_V1
        )
        if update_count == 0:
            assert state["field_prepared_active"] is False
            continue
        if runtime is None:
            assert state["field_runtime_handle"] == 0
            continue
        # runtime 只在单次 prepare -> step/cancel 窗口借用；帧结束不得残留身份。
        assert state["field_runtime_handle"] == 0
        assert state["field_sample_time_seconds"] == -1.0
        assert state["field_prepared_active"] is False
        responsive = setup_type in responsive_setups
        if responsive:
            assert state["field_sample_count"] > 0
        else:
            # Scope 未命中的 Domain 必须走 native O(1) 快路径，不做逐粒子采样。
            assert state["field_sample_count"] == 0
            assert state["field_apply_count"] == 0
        if uniform:
            air = state["field_air_velocity_world"]
            expected = np.zeros_like(air)
            if responsive:
                expected[:, 2] = np.float32(WIND_SPEED_MPS)
            np.testing.assert_array_equal(air, expected)


def _run_field_wind_matrix(run_index: int):
    scene = bpy.context.scene
    old_frame = int(scene.frame_current)
    old_fps = int(scene.render.fps)
    old_fps_base = float(scene.render.fps_base)
    worlds = {name: None for name in SCENARIOS}
    mesh = proxy = cloth = spring = field = None
    digest = hashlib.sha256()
    uniform_changed = {setup: False for setup in SETUPS}
    scoped_changed = {setup: False for setup in SETUPS}
    try:
        physics_blender.register()
        scene.render.fps = OUTPUT_FPS
        scene.render.fps_base = 1.0
        mesh, proxy = mixed._mesh_object(f"MC2FieldMesh{run_index}")
        cloth = bone_soak._armature(
            f"MC2FieldBoneCloth{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=-0.2,
        )
        spring = bone_soak._armature(
            f"MC2FieldBoneSpring{run_index}",
            chain_count=1,
            chain_length=6,
            x_offset=0.45,
        )
        field = _field_empty(f"MC2FieldWind{run_index}")
        scope_collection = bpy.data.collections.new(f"MC2FieldScope{run_index}")
        scene.collection.children.link(scope_collection)
        for obj in (mesh, cloth, spring, field):
            scope_collection.objects.link(obj)
        source_names = {
            "mesh_cloth": mesh.name_full,
            "bone_cloth": cloth.name_full,
            "bone_spring": spring.name_full,
        }
        scope = physics_nodes.physicsObjectScope(
            [scope_collection],
            include_passive_collision=False,
            include_bone_collision=False,
            include_rigid_body=False,
            include_rigid_constraint=False,
        )
        enabled_requests = _requests(
            mesh, cloth, spring, field_wind_enabled=True
        )
        disabled_requests = _requests(
            mesh, cloth, spring, field_wind_enabled=False
        )
        enabled_slot_ids = _slot_ids(enabled_requests)
        disabled_slot_ids = _slot_ids(disabled_requests)

        for frame in range(1, FRAME_COUNT + 1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            outputs = {}
            for scenario in SCENARIOS:
                _configure_field(field, scenario, source_names)
                requests = (
                    disabled_requests
                    if scenario == "profile_disabled"
                    else enabled_requests
                )
                worlds[scenario] = _step_scenario(
                    worlds[scenario],
                    scene=scene,
                    scope=scope,
                    requests=requests,
                )
                slot_ids = (
                    disabled_slot_ids
                    if scenario == "profile_disabled"
                    else enabled_slot_ids
                )
                outputs[scenario] = _scenario_outputs(
                    worlds[scenario], slot_ids
                )
                _assert_field_time_and_native_state(
                    worlds[scenario],
                    slot_ids,
                    uniform=scenario in {"profile_disabled", "uniform"},
                    responsive_setups=(
                        frozenset(SETUPS)
                        if scenario == "uniform"
                        else frozenset({scenario.removeprefix("scope_")})
                        if scenario.startswith("scope_")
                        else frozenset()
                    ),
                )
                for positions in outputs[scenario]:
                    digest.update(positions.tobytes())

            baseline = outputs["baseline"]
            for setup_index, setup_type in enumerate(SETUPS):
                np.testing.assert_array_equal(
                    outputs["profile_disabled"][setup_index],
                    baseline[setup_index],
                )
                uniform_changed[setup_type] |= bool(np.any(
                    outputs["uniform"][setup_index] != baseline[setup_index]
                ))
                for scoped_setup in SETUPS:
                    scoped = outputs[f"scope_{scoped_setup}"][setup_index]
                    if setup_type == scoped_setup:
                        scoped_changed[setup_type] |= bool(np.any(
                            scoped != baseline[setup_index]
                        ))
                    else:
                        np.testing.assert_array_equal(
                            scoped,
                            baseline[setup_index],
                        )
            digest.update(np.asarray(frame, dtype=np.int32).tobytes())

        assert all(uniform_changed.values()), uniform_changed
        assert all(scoped_changed.values()), scoped_changed
        return (
            digest.hexdigest(),
            tuple(sorted(uniform_changed.items())),
            tuple(sorted(scoped_changed.items())),
        )
    finally:
        for scenario, world in worlds.items():
            if isinstance(world, world_types.PhysicsWorldCache):
                world.omni_cache_dispose(f"mc2_field_wind_{scenario}_cleanup")
        _remove_empty(field)
        if "scope_collection" in locals() and scope_collection.name in bpy.data.collections:
            bpy.data.collections.remove(scope_collection)
        bone_soak._remove_armature(cloth)
        bone_soak._remove_armature(spring)
        mixed._remove_mesh(mesh)
        mixed._remove_mesh(proxy)
        scene.render.fps = old_fps
        scene.render.fps_base = old_fps_base
        scene.frame_set(old_frame)


def test_three_setup_field_wind_600_frame_deterministic_scope_matrix() -> None:
    first = _run_field_wind_matrix(0)
    second = _run_field_wind_matrix(1)
    assert first == second, (first, second)
    print(f"MC2_FIELD_WIND_SOAK_DIGEST {first[0]}")


if __name__ == "__main__":
    test_three_setup_field_wind_600_frame_deterministic_scope_matrix()
    print("PASS test_three_setup_field_wind_600_frame_deterministic_scope_matrix")
