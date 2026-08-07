"""
Blender headless regression: rewinding the timeline must clear delta writeback
before Jolt cold-starts from Object.matrix_world.

Usage:
  blender.exe --factory-startup --background --python test_blender_jolt_rewind.py
"""

import importlib.util
import os
import sys
import types as _types

TEST_ROOT = os.path.dirname(os.path.abspath(__file__))
HOTOOLS = os.path.abspath(os.path.join(TEST_ROOT, *(("..",) * 4)))
ADDONS = os.path.dirname(HOTOOLS)
PYTHON_ABI = f"py{sys.version_info.major}{sys.version_info.minor}"
JOLT_LIB = os.path.join(HOTOOLS, "_Lib", PYTHON_ABI, "HotoolsPackage")
NT_DIR = os.path.join(HOTOOLS, "OmniNode")
PW_ROOT = os.path.join(NT_DIR, "PhysicsWorld")

for path in (JOLT_LIB, ADDONS, HOTOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bpy
import mathutils


def _register_physics_props():
    PG_Hotools_RigidBody = sys.modules[
        f"{PKG_PREFIX}.rigid.properties"
    ].PG_Hotools_RigidBody

    try:
        bpy.utils.register_class(PG_Hotools_RigidBody)
    except Exception:
        pass
    if not hasattr(bpy.types.Object, "hotools_rigid_body"):
        bpy.types.Object.hotools_rigid_body = bpy.props.PointerProperty(
            type=PG_Hotools_RigidBody
        )


PKG_PREFIX = "HoTools.OmniNode.PhysicsWorld"


def _load_pw(suffix: str, file_rel: str):
    full = f"{PKG_PREFIX}.{suffix}" if suffix else PKG_PREFIX
    if full in sys.modules:
        return sys.modules[full]
    path = os.path.join(PW_ROOT, *file_rel.split("/"))
    spec = importlib.util.spec_from_file_location(full, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = full.rsplit(".", 1)[0]
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


for pkg, folder in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", os.path.join(HOTOOLS, "OmniNode")),
    ("HoTools.OmniNode.Function", os.path.join(NT_DIR, "Function")),
    (PKG_PREFIX, PW_ROOT),
    (f"{PKG_PREFIX}.rigid", os.path.join(PW_ROOT, "rigid")),
    (f"{PKG_PREFIX}.rigid.backends", os.path.join(PW_ROOT, "rigid", "backends")),
):
    if pkg not in sys.modules:
        module = _types.ModuleType(pkg)
        module.__path__ = [folder]
        module.__package__ = pkg
        sys.modules[pkg] = module

socket_mapping_key = "HoTools.OmniNode.OmniNodeSocketMapping"
if socket_mapping_key not in sys.modules:
    socket_mapping = _types.ModuleType(socket_mapping_key)
    socket_mapping.__package__ = "HoTools.OmniNode"

    class _OmniCache:
        def __init__(self, value=None):
            self.value = value

        @classmethod
        def replace(cls, value):
            return cls(value)

        @classmethod
        def mutate(cls, value):
            return cls(value)

    socket_mapping._OmniCache = _OmniCache
    sys.modules[socket_mapping_key] = socket_mapping

_load_pw("types", "types.py")
_load_pw("scope", "scope.py")
_load_pw("writeback", "writeback.py")
_load_pw("world", "world.py")
_load_pw("rigid.schema", "rigid/schema.py")
_load_pw("rigid.properties", "rigid/properties.py")
_register_physics_props()
_load_pw("rigid.specs", "rigid/specs.py")
_load_pw("rigid.results", "rigid/results.py")
_load_pw("rigid.solver", "rigid/solver.py")
_load_pw("rigid.backends.jolt", "rigid/backends/jolt.py")

make_scope = sys.modules[f"{PKG_PREFIX}.scope"].make_scope
physicsWorldBegin = sys.modules[f"{PKG_PREFIX}.world"].physicsWorldBegin
physicsWorldCommit = sys.modules[f"{PKG_PREFIX}.world"].physicsWorldCommit
apply_all_writebacks = sys.modules[f"{PKG_PREFIX}.writeback"].apply_all_writebacks
build_rigid_body_spec = sys.modules[f"{PKG_PREFIX}.rigid.specs"].build_rigid_body_spec
get_rigid_transform_result = sys.modules[f"{PKG_PREFIX}.rigid.results"].get_rigid_transform_result
step_rigid_bodies = sys.modules[f"{PKG_PREFIX}.rigid.solver"].step_rigid_bodies


def _make_ball():
    mesh = bpy.data.meshes.new("Rewind_Ball_Mesh")
    obj = bpy.data.objects.new("Rewind_Ball", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 5.0)
    rb = obj.hotools_rigid_body
    rb.enabled = True
    rb.body_type = "DYNAMIC"
    rb.mass = 1.0
    rb.shape_type = "SPHERE"
    rb.shape_radius = 0.5
    rb.rigid_collision_group = 3
    rb.rigid_collides_with_groups = 0x0004
    rb.gravity_factor = 1.0
    return obj


def _run():
    scene = bpy.context.scene
    scene.frame_set(1)
    ball = _make_ball()
    scope = make_scope(
        [ball],
        include_passive_collision=False,
        include_bone_collision=False,
        include_rigid_body=True,
        include_rigid_constraint=False,
        include_hidden=False,
    )

    cache_state = None
    world = None
    initial_spec = build_rigid_body_spec(ball)
    if (
        initial_spec is None
        or initial_spec.rigid_collision_group != 3
        or initial_spec.rigid_collides_with_groups != 0x0004
    ):
        raise RuntimeError("rigid spec did not read rigid-owned collision filter fields")

    for frame in range(1, 25):
        scene.frame_set(frame)
        world, _, _, restart = physicsWorldBegin(
            cache_state=cache_state,
            scene=scene,
            object_scope=scope,
            enabled=True,
        )
        step_rigid_bodies(world, enabled=True)
        slot = next((s for s in world.solver_slots.values() if s.kind == "rigid_body"), None)
        result = get_rigid_transform_result(world, frame=frame, generation=world.generation) if slot else None
        if result is None:
            raise RuntimeError(f"rigid solver did not publish transform result on frame {frame}")
        apply_all_writebacks(world, restart=restart)
        cache_state, _, _ = physicsWorldCommit(world, enabled=True)

    bpy.context.view_layer.update()
    stale_z = float(ball.matrix_world.translation.z)
    if abs(float(ball.delta_location.z)) < 0.01:
        raise RuntimeError("test setup failed: simulation did not produce delta writeback")
    touched_objects = world.backend_resources.get("_writeback_touched_objects")
    if not isinstance(touched_objects, dict) or not all(
        isinstance(key, tuple) and len(key) == 2
        for key in touched_objects
    ):
        raise RuntimeError("rigid writeback did not retain stable Object/Data identities")
    ball.delta_rotation_euler = (0.1, -0.2, 0.3)
    ball.delta_rotation_quaternion = mathutils.Quaternion((0.98, 0.1, 0.0, 0.0))
    ball.delta_scale = (1.2, 0.8, 1.1)
    previous_world = world
    previous_adapter = previous_world.backend_resources.get("rigid_solver")
    if previous_adapter is None:
        raise RuntimeError("test setup failed: previous Jolt adapter is missing")

    scene.frame_set(1)
    rewound_world, _, _, restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    bpy.context.view_layer.update()

    if not restart:
        raise RuntimeError("rewind should mark restart_required=True")
    if abs(float(ball.delta_location.z)) > 1e-6:
        raise RuntimeError(f"delta was not cleared before solver sync: {ball.delta_location.z:.6f}")
    if mathutils.Vector(ball.delta_rotation_euler).length > 1e-7:
        raise RuntimeError("Euler delta was not cleared before solver sync")
    if abs(float(ball.delta_rotation_quaternion.angle)) > 1e-7:
        raise RuntimeError("quaternion delta was not cleared before solver sync")
    if (mathutils.Vector(ball.delta_scale) - mathutils.Vector((1.0, 1.0, 1.0))).length > 1e-7:
        raise RuntimeError("scale delta was not cleared before solver sync")
    if previous_world.backend_resources.get("rigid_solver") is not None:
        raise RuntimeError("frame jump did not detach the previous Jolt adapter")
    if bool(getattr(previous_adapter, "_valid", True)):
        raise RuntimeError("frame jump did not dispose the previous Jolt native world")

    reset_z = float(ball.matrix_world.translation.z)
    if abs(reset_z - 5.0) > 1e-4:
        raise RuntimeError(f"object did not return to authored height: reset_z={reset_z:.6f}")

    step_rigid_bodies(rewound_world, enabled=True)
    adapter = rewound_world.backend_resources.get("rigid_solver")
    if adapter is previous_adapter:
        raise RuntimeError("frame jump reused the previous Jolt adapter")
    spec = build_rigid_body_spec(ball)
    pos, _rot = adapter.get_body_transform(spec.slot_id)
    if float(pos[2]) < 4.5:
        raise RuntimeError(
            f"Jolt cold-started from stale pose: stale_z={stale_z:.4f}, jolt_z={pos[2]:.4f}"
        )
    rewound_slot = rewound_world.solver_slots.get(spec.slot_id)
    rewound_result = get_rigid_transform_result(
        rewound_world,
        frame=scene.frame_current,
        generation=rewound_world.generation,
    )
    if rewound_result is None or float(rewound_result["position"][2]) < 4.5:
        raise RuntimeError("rewind did not publish a fresh rigid transform result")
    apply_all_writebacks(rewound_world, restart=restart)
    if ball.delta_location.length > 1e-7:
        raise RuntimeError(
            "restart frame writeback restored a non-zero object delta: "
            f"{tuple(ball.delta_location)}"
        )
    if mathutils.Vector(ball.delta_rotation_euler).length > 1e-7:
        raise RuntimeError("restart frame writeback restored a non-zero Euler delta")
    if abs(float(ball.delta_rotation_quaternion.angle)) > 1e-7:
        raise RuntimeError("restart frame writeback restored a non-identity quaternion delta")
    if (mathutils.Vector(ball.delta_scale) - mathutils.Vector((1.0, 1.0, 1.0))).length > 1e-7:
        raise RuntimeError("restart frame writeback restored a non-identity scale delta")

    cache_state, _, _ = physicsWorldCommit(rewound_world, enabled=True)

    same_world, _, _, same_restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    if same_restart:
        raise RuntimeError("same-frame begin should not request restart")
    if not bool(getattr(same_world.frame_context, "same_frame", False)):
        raise RuntimeError("same-frame begin did not set frame_context.same_frame")

    before = adapter.get_body_transform(spec.slot_id)
    body_count, step_ms = step_rigid_bodies(same_world, enabled=True)
    after = adapter.get_body_transform(spec.slot_id)
    if body_count != 1 or abs(float(step_ms)) > 1e-9:
        raise RuntimeError(f"same-frame step should be skipped: bodies={body_count}, step_ms={step_ms}")
    if before is None or after is None or abs(float(after[0][2]) - float(before[0][2])) > 1e-7:
        raise RuntimeError("same-frame solver advanced Jolt state")

    cache_state, _, _ = physicsWorldCommit(same_world, enabled=True)
    ball.hotools_rigid_body.shape_radius = 0.75
    dirty_world, _, _, dirty_restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    if dirty_restart:
        raise RuntimeError("same-frame spec edit should sync without restart")
    dirty_body_count, dirty_step_ms = step_rigid_bodies(dirty_world, enabled=True)
    dirty_spec = build_rigid_body_spec(ball)
    dirty_slot = dirty_world.solver_slots.get(dirty_spec.slot_id)
    if dirty_body_count != 1 or abs(float(dirty_step_ms)) > 1e-9:
        raise RuntimeError("same-frame dirty sync should not advance simulation")
    if dirty_slot is None or dirty_slot.data.get("_jolt_generation") != dirty_world.generation:
        raise RuntimeError("same-frame spec edit did not resync Jolt slot")
    dirty_result = get_rigid_transform_result(
        dirty_world,
        frame=scene.frame_current,
        generation=dirty_world.generation,
    )
    if dirty_result is None:
        raise RuntimeError("same-frame dirty sync did not refresh rigid transform result")

    cache_state, _, _ = physicsWorldCommit(dirty_world, enabled=True)
    reset_adapter = dirty_world.backend_resources.get("rigid_solver")
    reset_world, _, _, reset_restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
        reset=True,
    )
    if not reset_restart:
        raise RuntimeError("explicit reset did not enter the public restart contract")
    if reset_world.backend_resources.get("rigid_solver") is not reset_adapter:
        raise RuntimeError("explicit reset unexpectedly replaced the Jolt adapter owner")
    if int(getattr(reset_adapter, "body_count", -1)) != 0:
        raise RuntimeError("explicit reset did not clear Jolt native bodies before step")
    if abs(float(ball.delta_location.z)) > 1e-6:
        raise RuntimeError("explicit reset did not clear rigid delta writeback")
    step_rigid_bodies(reset_world, enabled=True)
    apply_all_writebacks(reset_world, restart=reset_restart)
    if abs(float(ball.delta_location.z)) > 1e-6:
        raise RuntimeError("explicit reset frame rewrote rigid delta")
    cache_state, _, _ = physicsWorldCommit(reset_world, enabled=True)

    forward_previous_world = reset_world
    forward_previous_adapter = reset_world.backend_resources.get("rigid_solver")
    scene.frame_set(10)
    forward_world, _, _, forward_restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    if not forward_restart or forward_world is forward_previous_world:
        raise RuntimeError("forward jump did not replace the world owner")
    if bool(getattr(forward_previous_adapter, "_valid", True)):
        raise RuntimeError("forward jump did not dispose the previous Jolt adapter")
    step_rigid_bodies(forward_world, enabled=True)
    apply_all_writebacks(forward_world, restart=forward_restart)
    if ball.delta_location.length > 1e-7:
        raise RuntimeError("forward jump frame rewrote rigid delta")
    cache_state, _, _ = physicsWorldCommit(forward_world, enabled=True)

    combined_previous_world = forward_world
    combined_previous_adapter = forward_world.backend_resources.get("rigid_solver")
    scene.frame_set(20)
    combined_world, _, _, combined_restart = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
        reset=True,
    )
    if not combined_restart or combined_world is combined_previous_world:
        raise RuntimeError("jump + reset did not replace the world owner")
    if bool(getattr(combined_previous_adapter, "_valid", True)):
        raise RuntimeError("jump + reset did not dispose the previous Jolt adapter")
    step_rigid_bodies(combined_world, enabled=True)
    apply_all_writebacks(combined_world, restart=combined_restart)
    if abs(float(ball.delta_location.z)) > 1e-6:
        raise RuntimeError("jump + reset frame rewrote rigid delta")
    cache_state, _, _ = physicsWorldCommit(combined_world, enabled=True)

    ball.hotools_rigid_body.enabled = False
    pruned_world, _, _, _ = physicsWorldBegin(
        cache_state=cache_state,
        scene=scene,
        object_scope=scope,
        enabled=True,
    )
    if any(slot.kind == "rigid_body" for slot in pruned_world.solver_slots.values()):
        raise RuntimeError("disabled rigid body left a stale solver slot")
    pruned_body_count, _ = step_rigid_bodies(pruned_world, enabled=True)
    if pruned_body_count != 0:
        raise RuntimeError(f"disabled rigid body left native Jolt bodies: {pruned_body_count}")

    cache_state, _, _ = physicsWorldCommit(pruned_world, enabled=True)

    rewound_world.omni_cache_dispose("test_done")
    if world is not None and world is not rewound_world:
        world.omni_cache_dispose("test_done_old_world")
    bpy.data.objects.remove(ball, do_unlink=True)

    print("[TEST] rewind/same-frame/prune Jolt lifecycle: PASS")


try:
    _run()
except Exception as exc:
    import traceback

    print("[TEST] rewind regression FAILED:", exc)
    traceback.print_exc()
    sys.exit(1)
