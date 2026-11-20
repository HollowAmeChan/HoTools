"""HoTools 强制应用姿态与 HoFBX 回归；在独立 Blender 4.5 后台进程运行。"""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from BoneTools.boneOperators import OP_ApplyRestPose
from BoneTools import restPose
from Exporter import FbxExporter


def activate(objects, active):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return sorted(tuple(evaluated.matrix_world @ vertex.co) for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def assert_points(actual, expected, tolerance=3e-5):
    assert len(actual) == len(expected), (len(actual), len(expected))
    error = max((Vector(a) - Vector(b)).length for a, b in zip(actual, expected))
    assert error < tolerance, error


def build(*, shape_keys=True, mirror=True, posed=True, parented=True, tag=""):
    rig = bpy.data.objects.new("Rig" + tag, bpy.data.armatures.new("RigData" + tag))
    bpy.context.scene.collection.objects.link(rig)
    activate([rig], rig)
    bpy.ops.object.mode_set(mode='EDIT')
    for side, x in (("L", .5), ("R", -.5)):
        bone = rig.data.edit_bones.new("Bone." + side)
        bone.head, bone.tail = (x, 0, 0), (x, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    for side, angle in (("L", .5), ("R", -.3)):
        bone = rig.pose.bones["Bone." + side]
        bone.rotation_mode = 'XYZ'
        bone.rotation_euler.x = angle if posed else 0
    mesh = bpy.data.meshes.new("MeshData" + tag)
    mesh.from_pydata([(.2, 0, .1), (.8, 0, .1), (.8, .1, 1.5), (.2, .1, 1.5)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new("Mesh" + tag, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if parented:
        obj.parent = rig
    obj.vertex_groups.new(name="Bone.L").add(list(range(4)), 1, 'REPLACE')
    obj.vertex_groups.new(name="Bone.R")
    if shape_keys:
        obj.shape_key_add(name="基型")
        key = obj.shape_key_add(name="Corrective")
        key.data[2].co.y += .2
        key.value = .35
        extra = obj.shape_key_add(name="Driven")
        extra.data[3].co.x += .1
        obj.data.shape_keys['gain'] = .25
        driver = extra.driver_add("value").driver
        variable = driver.variables.new()
        variable.name = 'gain'
        variable.type = 'SINGLE_PROP'
        variable.targets[0].id_type = 'KEY'
        variable.targets[0].id = obj.data.shape_keys
        variable.targets[0].data_path = '["gain"]'
        driver.expression = 'gain'
        obj.active_shape_key_index = 1
    if mirror:
        obj.modifiers.new("Mirror", 'MIRROR')
    armature = obj.modifiers.new("Skin", 'ARMATURE')
    armature.object = rig
    armature.use_deform_preserve_volume = True
    # 后置非骨架修改器不能被烘进基础网格后再留在栈上应用一遍。
    solidify = obj.modifiers.new("Thickness", 'SOLIDIFY')
    solidify.thickness = .03
    activate([rig, obj], rig)
    return rig, obj


def source_snapshot(rig, meshes):
    return (
        [[tuple(row) for row in bone.matrix_local] for bone in rig.data.bones],
        [[tuple(row) for row in bone.matrix_basis] for bone in rig.pose.bones],
        [(obj.data.as_pointer(), [(mod.name, mod.type) for mod in obj.modifiers], points(obj))
         for obj in meshes],
        sorted(obj.name for obj in bpy.data.objects),
    )


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


bpy.utils.register_class(OP_ApplyRestPose)
bpy.utils.register_class(FbxExporter.OP_FinalFBXExport)
try:
    for shape_keys, mirror, posed, parented in (
            (True, True, True, True), (False, True, True, True),
            (True, False, True, True), (False, True, False, True),
            (True, True, False, True)):
        reset()
        rig, obj = build(shape_keys=shape_keys, mirror=mirror, posed=posed, parented=parented)
        expected = points(obj)
        pointer = obj.as_pointer()
        skin_pointer = obj.modifiers['Skin'].as_pointer()
        count = len(bpy.data.objects)
        # 骨架层级中的未绑定网格不能被追加 Armature。
        decoration = bpy.data.objects.new("Decoration", bpy.data.meshes.new("DecorationData"))
        bpy.context.scene.collection.objects.link(decoration)
        decoration.parent = rig
        # 本来隐藏的骨架修改器不能在收尾被替换成启用的新修改器。
        hidden = obj.modifiers.new("HiddenSkin", 'ARMATURE')
        hidden.object = rig
        hidden.show_viewport = False
        data_count = len(bpy.data.meshes)
        assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'FINISHED'}
        assert obj.as_pointer() == pointer
        assert obj.modifiers['Skin'].as_pointer() == skin_pointer
        assert obj.modifiers['Skin'].use_deform_preserve_volume
        assert [(m.name, m.type) for m in obj.modifiers] == [
            ('Skin', 'ARMATURE'), ('Thickness', 'SOLIDIFY'), ('HiddenSkin', 'ARMATURE')]
        assert not obj.modifiers['HiddenSkin'].show_viewport
        assert not decoration.modifiers
        assert len(bpy.data.objects) == count + 1
        assert len(bpy.data.meshes) == data_count
        assert_points(points(obj), expected)
        assert bpy.context.active_object == rig
        assert set(bpy.context.selected_objects) == {rig, obj}
        if shape_keys:
            keys = obj.data.shape_keys
            assert [key.name for key in keys.key_blocks] == ['基型', 'Corrective', 'Driven']
            assert abs(keys.key_blocks['Corrective'].value - .35) < 1e-6
            assert obj.active_shape_key_index == 1
            assert len(keys.animation_data.drivers) == 1
            driver = keys.animation_data.drivers[0].driver
            assert driver.expression == 'gain'
            assert driver.variables[0].targets[0].id == keys
            assert abs(keys.key_blocks['Driven'].value - .25) < 1e-6
        else:
            assert obj.data.shape_keys is None
        print('PASS pose bake', shape_keys, mirror, posed, parented, flush=True)

    # 保持按钮原有资产范围：不处理骨架层级外的网格。
    reset()
    rig, obj = build(parented=False)
    before = source_snapshot(rig, [obj])
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'CANCELLED'}
    assert source_snapshot(rig, [obj]) == before

    # 从姿态模式点击时，完成后仍停留在原模式和选择。
    reset()
    rig, obj = build()
    expected = points(obj)
    bpy.ops.object.mode_set(mode='POSE')
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'FINISHED'}
    assert rig.mode == 'POSE'
    assert bpy.context.active_object == rig
    assert_points(points(obj), expected)
    bpy.ops.object.mode_set(mode='OBJECT')
    print('PASS pose mode context restored', flush=True)

    # 各键拓扑不一致时取消，不能拿基础键顶点套到其它形态键上。
    reset()
    rig, obj = build()
    weld = obj.modifiers.new('TopologyDependsOnKey', 'WELD')
    weld.merge_threshold = .5
    obj.modifiers.move(len(obj.modifiers) - 1, 1)
    before = source_snapshot(rig, [obj])
    data_count = len(bpy.data.meshes)
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'CANCELLED'}
    assert source_snapshot(rig, [obj]) == before
    assert len(bpy.data.meshes) == data_count
    print('PASS incompatible topology cancelled', flush=True)

    # 一个网格准备失败：前面已经准备好的网格不能提前修改原资产。
    reset()
    rig, first = build(tag="Failure")
    second = first.copy()
    second.data = first.data.copy()
    bpy.context.scene.collection.objects.link(second)
    activate([rig, first], rig)
    before = source_snapshot(rig, [first, second])
    real_bake = restPose.shapekey_utils.bake_modifiers_keeping_shape_keys
    calls = []

    def fail_second(objects, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            return [], [], [(objects[0].name, RuntimeError("injected failure"))]
        return real_bake(objects, **kwargs)

    with patch.object(restPose.shapekey_utils, 'bake_modifiers_keeping_shape_keys', side_effect=fail_second):
        assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'CANCELLED'}
    assert source_snapshot(rig, [first, second]) == before
    print('PASS atomic preparation failure', flush=True)

    # 已准备全部网格但静置姿态应用失败时，也要清理副本并保留原网格。
    failed_pose_bpy = SimpleNamespace(
        context=bpy.context, data=bpy.data,
        ops=SimpleNamespace(object=bpy.ops.object,
                            pose=SimpleNamespace(armature_apply=lambda **kwargs: {'CANCELLED'})))
    with patch.object(restPose, 'bpy', failed_pose_bpy):
        assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'CANCELLED'}
    assert source_snapshot(rig, [first, second]) == before
    print('PASS rest pose failure rollback', flush=True)

    # 多选两个骨架时，原生多物体姿态操作只能作用于本次已准备的活动骨架。
    reset()
    rig, obj = build(tag='Active')
    other_rig, other_mesh = build(tag='Other')
    other_before = source_snapshot(other_rig, [other_mesh])
    activate([rig, other_rig, obj], rig)
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'FINISHED'}
    assert source_snapshot(other_rig, [other_mesh]) == other_before
    assert set(bpy.context.selected_objects) == {rig, other_rig, obj}
    print('PASS multiple selected rigs stay isolated', flush=True)

    # 两个绑定实例共享网格时分别烘焙；原数据只清理一次，不影响未绑定的实例。
    reset()
    rig, first = build(tag='Shared')
    second = first.copy()
    bpy.context.scene.collection.objects.link(second)
    outside = first.copy()
    outside.modifiers.clear()
    outside.parent = None
    bpy.context.scene.collection.objects.link(outside)
    shared_data = first.data
    expected_first, expected_second = points(first), points(second)
    activate([rig, first], rig)
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'FINISHED'}
    assert outside.data == shared_data
    assert first.data != second.data
    assert_points(points(first), expected_first)
    assert_points(points(second), expected_second)
    # 再次应用零姿态会释放两个独立旧网格，且不会因原共享网格被提前释放而失败。
    outside.data = shared_data
    second.data = first.data
    count_before = len(bpy.data.meshes)
    assert bpy.ops.ho.apply_rest_pose('EXEC_DEFAULT') == {'FINISHED'}
    assert len(bpy.data.meshes) == count_before + 1
    print('PASS shared mesh instances stay isolated', flush=True)

    # HoFBX 默认关闭；显式开启时走修复后的 HoTools 强制应用，导回后位置对齐。
    assert not bpy.ops.ho.final_fbx_export.get_rna_type().properties['applyArmaturePose'].default
    reset()
    rig, obj = build(tag="Export")
    # 非线性后置修改器按每个形态键烘焙；以一个完整形态做几何参照，避免把混合近似算成姿态误差。
    obj.data.shape_keys.key_blocks['Corrective'].value = 1
    obj.data.shape_keys.animation_data.drivers[0].driver.expression = '0'
    bend = obj.modifiers.new("AfterSkinBend", 'SIMPLE_DEFORM')
    bend.deform_method = 'BEND'
    bend.angle = .6
    expected = points(obj)
    before = source_snapshot(rig, [obj])
    options = dict(exportUnityMetadata=False, exportHumanoidMapping=False,
                   exportBsCorrective=False, addLeafBones=False,
                   generateMCHBones=False, fixObjectTransform=False)
    with tempfile.TemporaryDirectory(prefix='hotools_rest_pose_') as directory:
        path = Path(directory) / 'pose.fbx'
        assert bpy.ops.ho.final_fbx_export('EXEC_DEFAULT', filepath=str(path),
                                         applyArmaturePose=True, **options) == {'FINISHED'}
        rig = bpy.data.objects['RigExport']
        obj = bpy.data.objects['MeshExport']
        # undo 会重建 ID，单独比对几何、修改器和姿态。
        after = source_snapshot(rig, [obj])
        assert after[:2] == before[:2] and after[3] == before[3]
        assert after[2][0][1:] == before[2][0][1:]
        reset()
        bpy.ops.import_scene.fbx(filepath=str(path))
        assert_points(points(bpy.data.objects['MeshExport']), expected, tolerance=3e-4)
        print('PASS HoFBX posed export round trip', flush=True)

        # 显式开启后若应用失败，必须中止且不生成 FBX，源场景由导出事务还原。
        reset()
        rig, obj = build(tag="ExportFailure")
        before = source_snapshot(rig, [obj])
        failed_path = Path(directory) / 'failed.fbx'
        with patch.object(restPose, '_prepare_mesh', side_effect=RuntimeError('injected failure')):
            try:
                result = bpy.ops.ho.final_fbx_export('EXEC_DEFAULT', filepath=str(failed_path),
                                                    applyArmaturePose=True, **options)
            except RuntimeError:
                result = {'CANCELLED'}
        assert result == {'CANCELLED'}
        assert not failed_path.exists()
        after = source_snapshot(bpy.data.objects['RigExportFailure'], [bpy.data.objects['MeshExportFailure']])
        assert after[:2] == before[:2] and after[3] == before[3]
        assert after[2][0][1:] == before[2][0][1:]
        print('PASS HoFBX failed export rollback', flush=True)
finally:
    bpy.utils.unregister_class(FbxExporter.OP_FinalFBXExport)
    bpy.utils.unregister_class(OP_ApplyRestPose)

print('APPLY_REST_POSE_OK', bpy.app.version_string, flush=True)
