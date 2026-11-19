"""Compare per-output and whole-rule caching in Blender's dependency graph.

blender --background --factory-startup --enable-autoexec --python this_file.py -- OUTPUT.json
"""
import json
import math
import statistics
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bpy.ops.preferences.addon_enable(module="HoTools")
from HoTools.Rbf import bs_corrective as bs


def run(point_count, copies):
    arm_data = bpy.data.armatures.new("BenchRigData")
    arm = bpy.data.objects.new("BenchRig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = arm_data.edit_bones.new("Main")
    bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    data = bpy.data.meshes.new("BenchMesh")
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    meshes = []
    rule = arm.hotools_bs_corrective.rules.add()
    rule.id, rule.bone = "benchmark", "Main"
    bs._ensure_base_point(rule)
    rng = np.random.default_rng(71)
    for pose in rng.uniform(-1.3, 1.3, (point_count, 3)):
        bs._add_point(arm, rule, tuple(pose))
    for i in range(copies):
        mesh = bpy.data.objects.new(f"Output{i}", data.copy())
        bpy.context.scene.collection.objects.link(mesh)
        mesh.shape_key_add(name="Basis")
        rule.influence_objects.add().mesh = mesh
        for point in bs._authored_points(rule):
            mesh.shape_key_add(name=point.bs_name)
        meshes.append(mesh)
    bs.generate_native_drivers(arm)
    item = bs._RBF_RUNTIME[rule.id]
    legacy_rows = {task_id: (item[0][index], item[2][index], item[3][index], item[4][index])
                   for task_id, index in item[1].items()}
    legacy_cache, counts = {}, [0, 0]
    def old(rule_id, task_id, x, y, z):
        current = (x, y, z)
        hit = legacy_cache.get(task_id)
        if hit is not None and hit[0] == current:
            return hit[1]
        counts[0] += 1
        pose, radius, weight, neutral = legacy_rows[task_id]
        value = bs.pose_weight(bs.euler_xyz_quaternion(current), pose, radius, weight, neutral)
        legacy_cache[task_id] = (current, value)
        return value
    original_evaluate = bs._evaluate_rbf_outputs
    def count_evaluate(item, current):
        counts[1] += 1
        return original_evaluate(item, current)
    bs._evaluate_rbf_outputs = count_evaluate
    poses = [Euler(tuple(p), "XYZ").to_quaternion() for p in rng.uniform(-1.2, 1.2, (60, 3))]
    results = {}
    for name, function in [("previous_per_task_cache", old), ("whole_rule_cache", bs._driver_namespace_rbf)]:
        bpy.app.driver_namespace[bs._DRIVER_NAMESPACE_FUNCTION] = function
        for keys in (mesh.data.shape_keys for mesh in meshes):
            for fc in keys.animation_data.drivers:
                fc.driver.expression = fc.driver.expression
            keys.update_tag()
        rounds = []
        for repeat in range(5):
            start = time.perf_counter()
            for quaternion in poses:
                arm.pose.bones['Main'].rotation_quaternion = quaternion
                bpy.context.view_layer.update()
            rounds.append((time.perf_counter() - start) * 1000 / len(poses))
        results[name] = {"median_ms_per_update": statistics.median(rounds), "rounds": rounds}
        # Compare the output actually produced by Blender against independent
        # scalar evaluation, not just two direct Python calls.
        pose = arm.pose.bones['Main'].matrix_basis.to_euler('XYZ')
        for point in bs._authored_points(rule):
            expected = old(rule.id, point.id, *pose)
            for mesh in meshes:
                actual = mesh.data.shape_keys.key_blocks[point.bs_name].value
                assert abs(actual - expected) < 5e-5, (name, actual, expected)
    results['scalar_solves'], results['whole_rule_solves'] = counts
    bs._evaluate_rbf_outputs = original_evaluate
    bpy.app.driver_namespace[bs._DRIVER_NAMESPACE_FUNCTION] = bs._driver_namespace_rbf
    bs.remove_native_drivers(arm)
    for mesh in meshes:
        bpy.data.objects.remove(mesh, do_unlink=True)
    bpy.data.objects.remove(arm, do_unlink=True)
    return {"points": point_count, "outputs": point_count * copies, **results}


results = {"blender": bpy.app.version_string, "cases": [run(3, 4), run(12, 4), run(24, 4), run(48, 4)]}
path = Path(sys.argv[sys.argv.index('--') + 1])
path.write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
print("BS_RBF_BENCHMARK_OK", json.dumps(results))
