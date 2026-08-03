"""区分 Blender 动画输入与 Bone XPBD 上一帧写回。"""

from __future__ import annotations

from dataclasses import dataclass

from ..utils.writeback_pose import pose_matrix_from_matrix_basis


BONE_XPBD_FRAME_STATE_KEY = "bone_xpbd.frame_state"
_MATCH_EPSILON = 1.0e-6


def _copy(value):
    callback = getattr(value, "copy", None)
    return callback() if callable(callback) else value


def _matrix_matches(left, right) -> bool:
    if left is None or right is None:
        return False
    try:
        return all(
            abs(float(left[row][column]) - float(right[row][column]))
            <= _MATCH_EPSILON
            for row in range(4)
            for column in range(4)
        )
    except Exception:
        return False


def _clone_state(
    state,
    generation: int,
    *,
    accept_previous=False,
) -> dict:
    if (
        not isinstance(state, dict)
        or (not accept_previous and int(state.get("generation", -1)) != generation)
    ):
        return {
            "generation": generation,
            "bones": {},
        }
    bones = {}
    for key, entry in dict(state.get("bones") or {}).items():
        if not isinstance(entry, dict):
            continue
        cloned = dict(entry)
        # 跨帧状态只能保留稳定值身份，不能持有 Blender ID/RNA 活引用。
        cloned.pop("armature", None)
        cloned.pop("pose_bone", None)
        cloned["source_basis"] = _copy(entry.get("source_basis"))
        for name in (
            "confirmed_writeback_basis",
            "pending_writeback_basis",
        ):
            cloned[name] = _copy(entry.get(name))
        for name in ("confirmed_receipt_key", "pending_receipt_key"):
            value = entry.get(name)
            cloned[name] = tuple(value) if isinstance(value, (list, tuple)) else None
        bones[key] = cloned
    return {
        "generation": generation,
        "bones": bones,
    }


def _identity_key(armature) -> tuple[int, int]:
    try:
        armature_ptr = int(armature.as_pointer())
        data_ptr = int(armature.data.as_pointer())
    except Exception:
        raise ReferenceError("Bone XPBD Armature 或数据块引用已失效") from None
    if armature_ptr <= 0 or data_ptr <= 0:
        raise ReferenceError("Bone XPBD Armature 或数据块引用已失效")
    return armature_ptr, data_ptr


def _receipt_key(value) -> tuple | None:
    if not isinstance(value, dict):
        return None
    transaction_id = str(value.get("transaction_id") or "")
    slot_id = str(value.get("slot_id") or "")
    solver = str(value.get("solver") or "")
    armature_ptr = int(value.get("armature_ptr", 0) or 0)
    armature_data_ptr = int(value.get("armature_data_ptr", 0) or 0)
    if (
        not transaction_id
        or not slot_id
        or not solver
        or armature_ptr <= 0
        or armature_data_ptr <= 0
    ):
        return None
    return (
        solver,
        transaction_id,
        int(value.get("transaction_index", -1)),
        int(value.get("transaction_size", 0)),
        slot_id,
        int(value.get("frame", 0)),
        int(value.get("generation", 0)),
        int(value.get("publication_id", 0)),
        armature_ptr,
        armature_data_ptr,
    )


def _receipt_keys(world) -> set[tuple]:
    from ..writeback import get_bone_writeback_receipts

    return {
        key
        for receipt in get_bone_writeback_receipts(world)
        if (key := _receipt_key(receipt)) is not None
    }


def _promote_confirmed_writebacks(
    state_bones,
    receipts,
    *,
    frame: int,
    generation: int,
) -> None:
    """只有公共写回成功 receipt 才能把 pending 指纹升级为已写入。"""

    for entry in state_bones.values():
        if not isinstance(entry, dict):
            continue
        pending_key = entry.get("pending_receipt_key")
        pending_key = (
            tuple(pending_key)
            if isinstance(pending_key, (list, tuple))
            else None
        )
        if pending_key is None:
            continue
        if pending_key in receipts:
            entry["confirmed_writeback_basis"] = _copy(
                entry.get("pending_writeback_basis")
            )
            entry["confirmed_receipt_key"] = pending_key
            entry["pending_writeback_basis"] = None
            entry["pending_receipt_key"] = None
            continue
        pending_frame = int(pending_key[5])
        pending_generation = int(pending_key[6])
        if pending_generation != generation or pending_frame < frame:
            # 结果流已经进入后续帧/代，未出现 receipt 的命令不可能再成功写回。
            entry["pending_writeback_basis"] = None
            entry["pending_receipt_key"] = None


@dataclass
class BoneXpbdFeedbackStage:
    generation: int
    base_present: bool
    base_state: object
    state: dict
    logical_pose_matrices: dict[tuple[int, str], object]

    def stage_writeback_expectations(self, plans, results) -> None:
        import mathutils

        plans = tuple(plans)
        results = tuple(results)
        if len(plans) != len(results):
            raise ValueError("Bone XPBD feedback plan/result 数量不一致")
        bones = self.state["bones"]
        staged = set()
        for plan, result in zip(plans, results):
            if not isinstance(plan, dict):
                continue
            receipt_key = _receipt_key(result)
            if receipt_key is None:
                raise ValueError("Bone XPBD 写回结果缺少反馈 receipt identity")
            armature = plan.get("armature")
            armature_ptr, data_ptr = _identity_key(armature)
            if receipt_key[-2:] != (armature_ptr, data_ptr):
                raise ReferenceError(
                    "Bone XPBD result 与 writeback plan 的 Armature identity 不一致"
                )
            for batch in plan.get("batches") or ():
                records = tuple(batch.get("records") or ())
                matrix_bases = tuple(batch.get("matrix_bases") or ())
                for record, matrix_basis in zip(records, matrix_bases):
                    if not isinstance(record, dict) or matrix_basis is None:
                        continue
                    name = str(record.get("bone_name") or "")
                    pose_bone = record.get("pose_bone")
                    if not name or pose_bone is None:
                        continue
                    key = (armature_ptr, data_ptr, name)
                    if key in staged:
                        raise ValueError(f"Bone XPBD 重复写回骨骼 {name!r}")
                    staged.add(key)
                    location, rotation, scale = matrix_basis.decompose()
                    canonical = mathutils.Matrix.LocRotScale(
                        location,
                        rotation,
                        scale,
                    )
                    entry = bones.setdefault(key, {
                        "bone_name": name,
                        "source_basis": pose_bone.matrix_basis.copy(),
                        "confirmed_writeback_basis": None,
                        "confirmed_receipt_key": None,
                        "pending_writeback_basis": None,
                        "pending_receipt_key": None,
                    })
                    entry["pending_writeback_basis"] = canonical
                    entry["pending_receipt_key"] = receipt_key

    def commit(self, world) -> None:
        if int(getattr(world, "generation", 0) or 0) != self.generation:
            raise RuntimeError("Bone XPBD feedback stage 属于另一代 Physics World")
        resources = world.backend_resources
        if self.base_present:
            if resources.get(BONE_XPBD_FRAME_STATE_KEY) is not self.base_state:
                raise RuntimeError("Bone XPBD feedback state 在提交前被并发替换")
        elif BONE_XPBD_FRAME_STATE_KEY in resources:
            raise RuntimeError("Bone XPBD feedback state 在提交前意外出现")
        resources[BONE_XPBD_FRAME_STATE_KEY] = self.state


def _resolved_pose_matrices(
    armature,
    names,
    state_bones,
    armature_ptr: int,
    data_ptr: int,
    *,
    restart_required: bool,
):
    pose_bones = armature.pose.bones
    selected = set(names)
    logical_bases = {}
    for name in names:
        pose_bone = pose_bones.get(name)
        if pose_bone is None:
            raise ValueError(f"Bone XPBD PoseBone 已失效: {name!r}")
        key = (armature_ptr, data_ptr, name)
        current = pose_bone.matrix_basis.copy()
        entry = state_bones.get(key)
        if entry is None:
            entry = {
                "bone_name": name,
                "source_basis": current.copy(),
                "confirmed_writeback_basis": None,
                "confirmed_receipt_key": None,
                "pending_writeback_basis": None,
                "pending_receipt_key": None,
            }
            state_bones[key] = entry
            logical_bases[name] = current
            continue
        expected = entry.get("confirmed_writeback_basis")
        restore_saved = (
            not restart_required
            and _matrix_matches(current, expected)
        )
        if restore_saved:
            saved_source = _copy(entry.get("source_basis"))
            logical_bases[name] = current if saved_source is None else saved_source
        else:
            entry["source_basis"] = current.copy()
            entry["confirmed_writeback_basis"] = None
            entry["confirmed_receipt_key"] = None
            entry["pending_writeback_basis"] = None
            entry["pending_receipt_key"] = None
            logical_bases[name] = current

    resolved = {}
    resolving = set()

    def resolve(name: str):
        if name in resolved:
            return resolved[name]
        if name in resolving:
            raise ValueError("Bone XPBD 骨架父级包含循环")
        resolving.add(name)
        pose_bone = pose_bones.get(name)
        basis = logical_bases[name]
        parent = pose_bone.parent
        target_parents = {}
        if parent is not None:
            target_parents[parent.name] = (
                resolve(parent.name)
                if parent.name in selected
                else parent.matrix.copy()
            )
        pose_matrix = pose_matrix_from_matrix_basis(
            pose_bone,
            basis,
            target_parents,
        )
        resolving.remove(name)
        resolved[name] = pose_matrix
        return pose_matrix

    for name in names:
        resolve(name)
    return resolved


def prepare_bone_xpbd_feedback(world, specs) -> BoneXpbdFeedbackStage:
    generation = int(getattr(world, "generation", 0) or 0)
    resources = world.backend_resources
    base_present = BONE_XPBD_FRAME_STATE_KEY in resources
    base_state = resources.get(BONE_XPBD_FRAME_STATE_KEY)
    state = _clone_state(base_state, generation)
    frame_context = getattr(world, "frame_context", None)
    frame = int(getattr(frame_context, "frame", 0) or 0)
    restart_required = bool(getattr(frame_context, "restart_required", False))
    _promote_confirmed_writebacks(
        state["bones"],
        _receipt_keys(world),
        frame=frame,
        generation=generation,
    )
    groups: dict[tuple[int, int], dict] = {}
    active_bones = set()
    for spec in specs:
        key = _identity_key(spec.armature)
        expected_key = (
            int(spec.object_spec.armature_ptr),
            int(spec.object_spec.armature_data_ptr),
        )
        if key != expected_key:
            raise ReferenceError(
                "Bone XPBD Armature object/data 身份已变化，请重新编译对象注册"
            )
        group = groups.setdefault(key, {
            "armature": spec.armature,
            "names": [],
            "seen": set(),
        })
        for name in spec.bone_names:
            if name not in group["seen"]:
                group["seen"].add(name)
                group["names"].append(name)
            active_bones.add((
                key[0],
                key[1],
                name,
            ))
    state["bones"] = {
        key: entry
        for key, entry in state["bones"].items()
        if key in active_bones
    }
    logical = {}
    for (armature_ptr, _data_ptr), group in groups.items():
        resolved = _resolved_pose_matrices(
            group["armature"],
            tuple(group["names"]),
            state["bones"],
            armature_ptr,
            _data_ptr,
            restart_required=restart_required,
        )
        logical.update(
            ((armature_ptr, name), matrix)
            for name, matrix in resolved.items()
        )
    return BoneXpbdFeedbackStage(
        generation,
        base_present,
        base_state,
        state,
        logical,
    )


def clear_bone_xpbd_feedback(world, _scope=None) -> None:
    world.backend_resources.pop(BONE_XPBD_FRAME_STATE_KEY, None)


def carry_bone_xpbd_feedback(previous_world, world, reason: str = "replace") -> None:
    if str(reason or "") != "frame_jump":
        return
    state = getattr(previous_world, "backend_resources", {}).get(
        BONE_XPBD_FRAME_STATE_KEY
    )
    if not isinstance(state, dict):
        return
    previous_generation = int(getattr(previous_world, "generation", 0) or 0)
    previous_frame = int(
        getattr(getattr(previous_world, "frame_context", None), "frame", 0) or 0
    )
    resolved = _clone_state(
        state,
        previous_generation,
        accept_previous=True,
    )
    _promote_confirmed_writebacks(
        resolved["bones"],
        _receipt_keys(previous_world),
        frame=previous_frame,
        generation=previous_generation,
    )
    for entry in resolved["bones"].values():
        entry["pending_writeback_basis"] = None
        entry["pending_receipt_key"] = None
    generation = int(getattr(world, "generation", 0) or 0)
    world.backend_resources[BONE_XPBD_FRAME_STATE_KEY] = _clone_state(
        resolved,
        generation,
        accept_previous=True,
    )


__all__ = [
    "BONE_XPBD_FRAME_STATE_KEY",
    "BoneXpbdFeedbackStage",
    "carry_bone_xpbd_feedback",
    "clear_bone_xpbd_feedback",
    "prepare_bone_xpbd_feedback",
]
