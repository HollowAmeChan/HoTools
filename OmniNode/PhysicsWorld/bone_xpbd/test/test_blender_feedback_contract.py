"""Bone XPBD 引用身份、跳帧反馈与 Pose 空间转换的聚焦测试。"""

from __future__ import annotations

import importlib
import os
import sys
import types

import bpy
import mathutils
import numpy as np


BONE_XPBD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHYSICS_WORLD = os.path.dirname(BONE_XPBD_ROOT)
OMNINODE = os.path.dirname(PHYSICS_WORLD)
HOTOOLS = os.path.dirname(OMNINODE)
for package_name, package_path in (
    ("HoTools", HOTOOLS),
    ("HoTools.OmniNode", OMNINODE),
    ("HoTools.OmniNode.Function", os.path.join(OMNINODE, "Function")),
    ("HoTools.OmniNode.PhysicsWorld", PHYSICS_WORLD),
):
    module = types.ModuleType(package_name)
    module.__path__ = [package_path]
    module.__package__ = package_name
    sys.modules.setdefault(package_name, module)


feedback = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.feedback"
)
object_spec = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.bone_xpbd.object_spec"
)
writeback = importlib.import_module("HoTools.OmniNode.PhysicsWorld.writeback")
writeback_pose = importlib.import_module(
    "HoTools.OmniNode.PhysicsWorld.utils.writeback_pose"
)
host_evaluation = importlib.import_module("HoTools.OmniNode.OmniHostEvaluation")


def _make_rig(*, connected: bool = False):
    data = bpy.data.armatures.new("BoneXpbdFeedbackData")
    armature = bpy.data.objects.new("BoneXpbdFeedback", data)
    bpy.context.scene.collection.objects.link(armature)
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = data.edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 1.0, 0.0)
    child = data.edit_bones.new("Child")
    child.head = root.tail
    child.tail = (0.35, 2.0, 0.0)
    child.parent = root
    child.use_connect = bool(connected)
    bone_names = (str(root.name), str(child.name))
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature, bone_names


def _remove_rig(armature) -> None:
    data = armature.data
    bpy.data.objects.remove(armature, do_unlink=True)
    if not data.users:
        bpy.data.armatures.remove(data)


def _matrix_values(matrix):
    return np.asarray(matrix, dtype=np.float64)


def _assert_matrix_close(actual, expected, *, atol=1.0e-6) -> None:
    np.testing.assert_allclose(
        _matrix_values(actual),
        _matrix_values(expected),
        rtol=0.0,
        atol=atol,
    )


def _feedback_spec(armature, names):
    return types.SimpleNamespace(
        armature=armature,
        bone_names=tuple(names),
        object_spec=types.SimpleNamespace(
            armature_ptr=int(armature.as_pointer()),
            armature_data_ptr=int(armature.data.as_pointer()),
        ),
    )


def _world(generation: int, *, restart: bool = False):
    return types.SimpleNamespace(
        generation=int(generation),
        backend_resources={},
        runtime_caches={},
        frame_context=types.SimpleNamespace(
            frame=1,
            restart_required=bool(restart),
        ),
    )


def _pinned_keys(armature, names):
    return {
        (
            int(armature.as_pointer()),
            int(armature.data.as_pointer()),
            str(name),
        )
        for name in names
    }


def _stage_single_expectation(stage, armature, bone_name, matrix_basis) -> dict:
    pose_bone = armature.pose.bones[bone_name]
    result = {
        "solver": "bone_xpbd",
        "slot_id": "feedback-test-slot",
        "transaction_id": "feedback-test-transaction",
        "transaction_index": 0,
        "transaction_size": 1,
        "frame": 1,
        "generation": stage.generation,
        "publication_id": 1,
        "armature_ptr": int(armature.as_pointer()),
        "armature_data_ptr": int(armature.data.as_pointer()),
    }
    stage.stage_writeback_expectations(({
        "armature": armature,
        "batches": ({
            "records": ({
                "bone_name": bone_name,
                "pose_bone": pose_bone,
            },),
            "matrix_bases": (matrix_basis,),
        },),
    },), (result,))
    return result


def test_receipt_store_keeps_each_slots_latest_unacknowledged_success():
    world = _world(1)
    diagnostics = {"frame": 1, "generation": 1, "receipts": []}
    for index in range(4097):
        writeback._append_bone_writeback_receipt(world, diagnostics, {
            "solver": "bone_xpbd",
            "slot_id": f"slot-{index}",
            "transaction_id": f"transaction-{index}",
            "transaction_index": 0,
            "transaction_size": 1,
            "frame": 1,
            "generation": 1,
            "publication_id": index + 1,
            "armature_ptr": 1001,
            "armature_data_ptr": 2002,
            "bone_count": 1,
        })
    receipts = writeback.get_bone_writeback_receipts(world)
    assert len(receipts) == 4097
    assert receipts[0]["slot_id"] == "slot-0"
    assert receipts[-1]["slot_id"] == "slot-4096"


def test_feedback_rejects_result_for_another_armature_identity():
    armature, bone_names = _make_rig()
    world = _world(1)
    try:
        stage = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names[:1]),),
        )
        pose_bone = armature.pose.bones[bone_names[0]]
        bad_result = {
            "solver": "bone_xpbd",
            "slot_id": "feedback-test-slot",
            "transaction_id": "feedback-test-transaction",
            "transaction_index": 0,
            "transaction_size": 1,
            "frame": 1,
            "generation": 1,
            "publication_id": 1,
            "armature_ptr": int(armature.as_pointer()),
            "armature_data_ptr": int(armature.data.as_pointer()) + 1,
        }
        plan = {
            "armature": armature,
            "batches": ({
                "records": ({
                    "bone_name": bone_names[0],
                    "pose_bone": pose_bone,
                },),
                "matrix_bases": (mathutils.Matrix.Identity(4),),
            },),
        }
        try:
            stage.stage_writeback_expectations((plan,), (bad_result,))
        except ReferenceError as exc:
            assert "Armature identity" in str(exc)
        else:
            raise AssertionError("反馈 stage 接受了其它 Armature identity 的 result")
    finally:
        _remove_rig(armature)


def test_feedback_uses_pose_channels_for_own_sheared_writeback_identity():
    armature, bone_names = _make_rig()
    bone_name = bone_names[-1]
    pose_bone = armature.pose.bones[bone_name]
    world = _world(1)
    try:
        source_basis = feedback._pose_channel_basis(pose_bone)
        source_pose = pose_bone.matrix.copy()
        stage = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, (bone_name,)),),
        )
        # matrix_basis 可以携带 shear，但 Blender 独立变换通道只能保存其
        # location/rotation/scale 分解。旧反馈直接比较矩阵，会把自己的成功
        # 写回误判成外部动画输入。
        sheared_output = mathutils.Matrix((
            (1.0, 0.35, 0.0, 0.25),
            (0.0, 1.0, 0.2, -0.15),
            (0.1, 0.0, 1.0, 0.05),
            (0.0, 0.0, 0.0, 1.0),
        ))
        result = _stage_single_expectation(
            stage,
            armature,
            bone_name,
            sheared_output,
        )
        stage.commit(world)
        diagnostics = {"frame": 1, "generation": 1, "receipts": []}
        writeback._append_bone_writeback_receipt(world, diagnostics, result)
        pose_bone.matrix_basis = sheared_output
        bpy.context.view_layer.update()

        world.frame_context.frame = 2
        restored = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, (bone_name,)),),
        )
        _assert_matrix_close(
            restored.logical_pose_matrices[(int(armature.as_pointer()), bone_name)],
            source_pose,
        )
        key = (
            int(armature.as_pointer()),
            int(armature.data.as_pointer()),
            bone_name,
        )
        _assert_matrix_close(restored.state["bones"][key]["source_basis"], source_basis)
        restored.commit(world)

        # 真正修改独立通道仍必须成为新一帧宿主输入，不能被 receipt 吞掉。
        pose_bone.location = (0.6, -0.2, 0.1)
        pose_bone.rotation_mode = "QUATERNION"
        pose_bone.rotation_quaternion = mathutils.Quaternion(
            (0.0, 0.0, 1.0),
            0.4,
        )
        bpy.context.view_layer.update()
        external_basis = feedback._pose_channel_basis(pose_bone)
        external_pose = writeback_pose.pose_matrix_from_matrix_basis(
            pose_bone,
            external_basis,
            {},
        )
        world.frame_context.frame = 3
        overridden = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, (bone_name,)),),
        )
        _assert_matrix_close(
            overridden.logical_pose_matrices[(int(armature.as_pointer()), bone_name)],
            external_pose,
        )
        _assert_matrix_close(
            overridden.state["bones"][key]["source_basis"],
            external_basis,
        )
    finally:
        _remove_rig(armature)


def test_feedback_key_contains_object_data_and_bone_and_prunes_inactive_entries():
    armature, bone_names = _make_rig()
    world = _world(1)
    try:
        stage = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names),),
        )
        stage.commit(world)
        expected_keys = {
            (
                int(armature.as_pointer()),
                int(armature.data.as_pointer()),
                name,
            )
            for name in bone_names
        }
        assert set(world.backend_resources[
            feedback.BONE_XPBD_FRAME_STATE_KEY
        ]["bones"]) == expected_keys
        assert all(
            "armature" not in entry and "pose_bone" not in entry
            for entry in world.backend_resources[
                feedback.BONE_XPBD_FRAME_STATE_KEY
            ]["bones"].values()
        )

        pruned = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names[:1]),),
        )
        assert set(pruned.state["bones"]) == {(
            int(armature.as_pointer()),
            int(armature.data.as_pointer()),
            bone_names[0],
        )}
    finally:
        _remove_rig(armature)


def test_frame_jump_uses_current_rna_basis_after_writeback_clear():
    armature, bone_names = _make_rig()
    bone_name = bone_names[0]
    pose_bone = armature.pose.bones[bone_name]
    previous = _world(1)
    current = _world(2, restart=True)
    override_world = _world(2, restart=True)
    pins = _pinned_keys(armature, (bone_name,))
    try:
        source_basis = mathutils.Matrix.LocRotScale(
            (0.15, -0.1, 0.05),
            mathutils.Quaternion((0.0, 0.0, 1.0), 0.35),
            (1.0, 1.0, 1.0),
        )
        pose_bone.matrix_basis = source_basis
        bpy.context.view_layer.update()
        stage = feedback.prepare_bone_xpbd_feedback(
            previous,
            (_feedback_spec(armature, (bone_name,)),),
            pinned_bone_keys=pins,
        )
        output_basis = mathutils.Matrix.Rotation(-0.7, 4, "X")
        result = _stage_single_expectation(
            stage,
            armature,
            bone_name,
            output_basis,
        )
        stage.commit(previous)
        diagnostics = {"frame": 1, "generation": 1, "receipts": []}
        writeback._append_bone_writeback_receipt(previous, diagnostics, result)
        assert diagnostics["receipts"][0]["schema"] == "bone_writeback_receipt_v1"

        pose_bone.matrix_basis = output_basis
        previous.backend_resources["_writeback_touched_pose_bones"] = {
            (int(armature.as_pointer()), bone_name): (armature, bone_name)
        }
        with host_evaluation.frame_evaluation_scope(None):
            writeback.clear_all_deltas(previous)
        assert previous.backend_resources["_writeback_touched_pose_bones"] == {}

        feedback.carry_bone_xpbd_feedback(previous, current, "frame_jump")
        restored = feedback.prepare_bone_xpbd_feedback(
            current,
            (_feedback_spec(armature, (bone_name,)),),
            pinned_bone_keys=pins,
        )
        identity_pose = writeback_pose.pose_matrix_from_matrix_basis(
            pose_bone,
            mathutils.Matrix.Identity(4),
            {},
        )
        _assert_matrix_close(
            restored.logical_pose_matrices[(int(armature.as_pointer()), bone_name)],
            identity_pose,
        )

        # 单位矩阵也是合法的目标帧输入，不能据此猜测并恢复上一帧source。
        # 目标帧给出非单位动画 basis 时同样由新的宿主输入优先。
        feedback.carry_bone_xpbd_feedback(previous, override_world, "frame_jump")
        override_basis = mathutils.Matrix.Rotation(0.9, 4, "Y")
        pose_bone.matrix_basis = override_basis
        bpy.context.view_layer.update()
        override_pose = pose_bone.matrix.copy()
        overridden = feedback.prepare_bone_xpbd_feedback(
            override_world,
            (_feedback_spec(armature, (bone_name,)),),
            pinned_bone_keys=pins,
        )
        _assert_matrix_close(
            overridden.logical_pose_matrices[(int(armature.as_pointer()), bone_name)],
            override_pose,
        )
    finally:
        _remove_rig(armature)


def test_terminal_pin_keeps_independent_pose_when_only_parent_source_moves():
    armature, bone_names = _make_rig()
    root_name, child_name = bone_names
    world = _world(1)
    pins = _pinned_keys(armature, (child_name,))
    try:
        child = armature.pose.bones[child_name]
        stage = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names),),
            pinned_bone_keys=pins,
        )
        anchor = stage.logical_pose_matrices[
            (int(armature.as_pointer()), child_name)
        ].copy()
        output_basis = child.matrix_basis.copy()
        result = _stage_single_expectation(
            stage,
            armature,
            child_name,
            output_basis,
        )
        stage.commit(world)
        diagnostics = {"frame": 1, "generation": 1, "receipts": []}
        writeback._append_bone_writeback_receipt(world, diagnostics, result)

        # 子骨没有直接输入变化，仅祖先发生宿主动画。Pin 必须继续拥有原世界锚，
        # 不能把保存的局部 basis 重新叠到新父姿态上。
        armature.pose.bones[root_name].matrix_basis = mathutils.Matrix.LocRotScale(
            (1.8, -0.4, 0.2),
            mathutils.Quaternion((0.0, 0.0, 1.0), 1.1),
            (1.0, 1.0, 1.0),
        )
        child.matrix_basis = output_basis
        bpy.context.view_layer.update()
        live_pose = child.matrix.copy()
        assert float((live_pose.translation - anchor.translation).length) > 0.5

        restored = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names),),
            pinned_bone_keys=pins,
        )
        _assert_matrix_close(
            restored.logical_pose_matrices[
                (int(armature.as_pointer()), child_name)
            ],
            anchor,
        )
        _assert_matrix_close(
            restored.state["bones"][
                (
                    int(armature.as_pointer()),
                    int(armature.data.as_pointer()),
                    child_name,
                )
            ]["source_pose_matrix"],
            anchor,
        )
    finally:
        _remove_rig(armature)


def test_terminal_pin_refreshes_anchor_when_its_own_channels_change():
    armature, bone_names = _make_rig()
    child_name = bone_names[-1]
    child = armature.pose.bones[child_name]
    world = _world(1)
    pins = _pinned_keys(armature, (child_name,))
    try:
        stage = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names),),
            pinned_bone_keys=pins,
        )
        previous_anchor = stage.logical_pose_matrices[
            (int(armature.as_pointer()), child_name)
        ].copy()
        output_basis = feedback._pose_channel_basis(child)
        result = _stage_single_expectation(
            stage,
            armature,
            child_name,
            output_basis,
        )
        stage.commit(world)
        diagnostics = {"frame": 1, "generation": 1, "receipts": []}
        writeback._append_bone_writeback_receipt(world, diagnostics, result)

        child.location = (0.45, -0.25, 0.15)
        child.rotation_mode = "QUATERNION"
        child.rotation_quaternion = mathutils.Quaternion(
            (1.0, 0.0, 0.0),
            0.55,
        )
        bpy.context.view_layer.update()
        external_pose = child.matrix.copy()
        assert float(
            (external_pose.translation - previous_anchor.translation).length
        ) > 0.1

        refreshed = feedback.prepare_bone_xpbd_feedback(
            world,
            (_feedback_spec(armature, bone_names),),
            pinned_bone_keys=pins,
        )
        _assert_matrix_close(
            refreshed.logical_pose_matrices[
                (int(armature.as_pointer()), child_name)
            ],
            external_pose,
        )
    finally:
        _remove_rig(armature)


def test_pose_round_trip_uses_blender_bone_inheritance_contract():
    armature, bone_names = _make_rig()
    try:
        root = armature.pose.bones[bone_names[0]]
        child = armature.pose.bones[bone_names[1]]
        child.bone.inherit_scale = "NONE"
        child.bone.use_local_location = False
        root.matrix_basis = mathutils.Matrix.LocRotScale(
            (0.2, 0.1, -0.3),
            mathutils.Quaternion((0.0, 0.0, 1.0), 0.45),
            (1.7, 0.6, 1.2),
        )
        child.matrix_basis = mathutils.Matrix.LocRotScale(
            (0.3, -0.2, 0.1),
            mathutils.Quaternion((1.0, 0.0, 0.0), -0.25),
            (0.9, 1.1, 1.0),
        )
        bpy.context.view_layer.update()
        root_target = root.matrix.copy()
        child_target = child.matrix.copy()
        child_basis = child.matrix_basis.copy()

        reconstructed = writeback_pose.pose_matrix_from_matrix_basis(
            child,
            child_basis,
            {root.name: root_target},
        )
        _assert_matrix_close(reconstructed, child_target)
        inverted = writeback_pose.matrix_basis_from_pose_matrix(
            child,
            child_target,
            {root.name: root_target},
        )
        _assert_matrix_close(inverted, child_basis)
    finally:
        _remove_rig(armature)


def test_object_registration_rejects_connected_bones():
    armature, bone_names = _make_rig(connected=True)
    try:
        try:
            object_spec.BoneXpbdObjectSpec(armature, bone_names)
        except ValueError as exc:
            assert "use_connect=True" in str(exc)
            assert bone_names[1] in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了 use_connect=True 的骨骼")
    finally:
        _remove_rig(armature)


def test_object_registration_rejects_pose_bone_constraints():
    armature, bone_names = _make_rig()
    try:
        armature.pose.bones[bone_names[-1]].constraints.new("COPY_LOCATION")
        try:
            object_spec.BoneXpbdObjectSpec(armature, bone_names)
        except ValueError as exc:
            assert "Constraint/IK" in str(exc)
            assert bone_names[-1] in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了无法隔离反馈的 PoseBone Constraint")
    finally:
        _remove_rig(armature)


def test_object_registration_rejects_nonuniform_pose_scale_in_parent_chain():
    armature, bone_names = _make_rig()
    try:
        armature.pose.bones[bone_names[0]].scale = (1.9, 0.45, 1.3)
        bpy.context.view_layer.update()
        try:
            object_spec.BoneXpbdObjectSpec(armature, bone_names[-1:])
        except ValueError as exc:
            assert "完整 Pose 祖先链" in str(exc)
            assert bone_names[0] in str(exc)
        else:
            raise AssertionError("Bone XPBD 接受了非均匀 Pose scale 的父链")
    finally:
        _remove_rig(armature)


def test_feedback_rejects_pose_scale_animated_nonuniform_after_registration():
    armature, bone_names = _make_rig()
    child_name = bone_names[-1]
    world = _world(1)
    spec = _feedback_spec(armature, bone_names)
    pins = _pinned_keys(armature, (child_name,))
    try:
        initial = feedback.prepare_bone_xpbd_feedback(
            world,
            (spec,),
            pinned_bone_keys=pins,
        )
        initial.commit(world)

        armature.pose.bones[bone_names[0]].scale = (1.9, 0.45, 1.3)
        bpy.context.view_layer.update()
        world.frame_context.frame = 2
        try:
            feedback.prepare_bone_xpbd_feedback(
                world,
                (spec,),
                pinned_bone_keys=pins,
            )
        except ValueError as exc:
            assert "Blender L/R/S 无法表达的 shear" in str(exc)
            assert bone_names[0] in str(exc)
        else:
            raise AssertionError("Bone XPBD 运行中接受了非均匀 Pose scale")
    finally:
        _remove_rig(armature)


if __name__ == "__main__":
    tests = tuple(
        (name, value)
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    )
    for name, test in tests:
        test()
        print(f"PASS {name}")
    print(f"Bone XPBD feedback contract: {len(tests)} passed")
