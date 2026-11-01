"""ARP integration: fit reference bones, generate controllers, and bind rigs."""

from contextlib import contextmanager
from pathlib import Path
import sys

import bpy
from bpy.props import PointerProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from .humanoid_auto_mapping import auto_map_source_names_to_humanoid


# ARP reference names and final deformation names are deliberately separate.
# In particular, finger segments 2/3 deform through c_<finger>2/3, not <finger>1.
REFERENCE_BONES = {
    "hips": "root_ref.x",
    "spine": "spine_01_ref.x",
    "chest": "spine_02_ref.x",
    "neck": "neck_ref.x",
    "head": "head_ref.x",
}
DEFORM_BONES = {
    "hips": "root.x",
    "spine": "spine_01.x",
    "chest": "spine_02.x",
    "neck": "neck.x",
    "head": "head.x",
}
for _side in ("L", "R"):
    for _slot, _ref, _deform in (
        ("shoulder", "shoulder_ref", "shoulder"),
        ("upper_arm", "arm_ref", "c_arm_twist_offset"),
        ("lower_arm", "forearm_ref", "forearm_stretch"),
        ("hand", "hand_ref", "hand"),
        ("upper_leg", "thigh_ref", "thigh_twist"),
        ("lower_leg", "leg_ref", "leg_stretch"),
        ("foot", "foot_ref", "foot"),
        ("toes", "toes_ref", "toes_01"),
    ):
        REFERENCE_BONES[f"{_slot}.{_side}"] = f"{_ref}.{_side.lower()}"
        DEFORM_BONES[f"{_slot}.{_side}"] = f"{_deform}.{_side.lower()}"
    DEFORM_BONES[f"arm_twist.{_side}"] = f"c_arm_twist_offset.{_side.lower()}"
    DEFORM_BONES[f"leg_twist.{_side}"] = f"thigh_twist.{_side.lower()}"
    for _finger, _arp_finger in (
        ("thumb", "thumb"), ("index", "index"), ("middle", "middle"),
        ("ring", "ring"), ("little", "pinky"),
    ):
        for _number, _segment in enumerate(
                ("proximal", "intermediate", "distal"), 1):
            _slot = f"{_finger}_{_segment}.{_side}"
            REFERENCE_BONES[_slot] = f"{_arp_finger}{_number}_ref.{_side.lower()}"
            DEFORM_BONES[_slot] = (
                f"{_arp_finger}1.{_side.lower()}" if _number == 1
                else f"c_{_arp_finger}{_number}.{_side.lower()}"
            )

REQUIRED_SLOTS = (
    "hips", "spine", "chest", "neck", "head",
    *(f"{part}.{side}" for side in ("L", "R") for part in (
        "upper_arm", "lower_arm", "hand", "upper_leg", "lower_leg", "foot")),
)
ASSEMBLY_PREFIX = "HoTools_ARP_"
SNAP_PREFIX = "HoTools_Snap_"
EPSILON = 1e-7


def armature_filter(_self, obj):
    return obj.type == "ARMATURE"


def arp_status():
    """Check registered capabilities, including extension-style module names."""
    modules = [
        module for name, module in tuple(sys.modules.items())
        if name == "auto_rig_pro" or name.endswith(".auto_rig_pro")
    ]
    for module in modules:
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        preset = Path(filename).parent / "armature_presets" / "human.blend"
        try:
            bpy.ops.arp.append_arp.get_rna_type()
            bpy.ops.arp.match_to_rig.get_rna_type()
        except (AttributeError, RuntimeError):
            continue
        if preset.is_file():
            return True, ""
        return False, "Auto-Rig Pro 缺少默认人体预设 human.blend"
    return False, "未安装或未启用 Auto-Rig Pro"


@contextmanager
def object_context(context):
    """Leave edit mode before reads; always restore selection and active mode."""
    active = context.view_layer.objects.active
    mode = active.mode if active else "OBJECT"
    selected = tuple(context.selected_objects)
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    try:
        yield
    finally:
        current = context.view_layer.objects.active
        if current and current.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in tuple(context.selected_objects):
            obj.select_set(False)
        for obj in selected:
            if context.view_layer.objects.get(obj.name) == obj:
                obj.select_set(True)
        if active and context.view_layer.objects.get(active.name) == active:
            context.view_layer.objects.active = active
            if mode != "OBJECT":
                bpy.ops.object.mode_set(mode=mode)
        else:
            context.view_layer.objects.active = None


def activate(context, obj):
    current = context.view_layer.objects.active
    if current and current.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected in tuple(context.selected_objects):
        selected.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def source_mapping(armature):
    """Honor authored semantic labels; infer only unassigned slots/bones."""
    mapping = {}
    for bone in armature.data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        slot = getattr(props, "humanoidMapping", "").strip()
        if not slot:
            continue
        if slot in mapping:
            raise ValueError(f"Humanoid 映射重复：{slot}")
        mapping[slot] = bone.name
    candidates = [
        bone.name for bone in armature.data.bones
        if bone.name not in mapping.values()
    ]
    for match in auto_map_source_names_to_humanoid(candidates).matches:
        if match.target_name not in mapping:
            mapping[match.target_name] = match.source_name
    return mapping


def validate_main(main, context):
    if main is None or main.type != "ARMATURE":
        raise ValueError("请指定主骨架")
    if context.view_layer.objects.get(main.name) != main:
        raise ValueError("主骨架不在当前视图层")
    if not main.is_editable or not main.data.is_editable:
        raise ValueError("主骨架必须可编辑")
    if abs(main.matrix_world.determinant()) < EPSILON:
        raise ValueError("主骨架缩放为零，无法装配")


def validate_mapping(main, mapping):
    missing = [slot for slot in REQUIRED_SLOTS if slot not in mapping]
    if missing:
        raise ValueError("缺少人体映射：" + "、".join(missing))
    for slot, name in mapping.items():
        if slot not in REFERENCE_BONES:
            continue
        bone = main.data.bones[name]
        if (main.matrix_world @ bone.tail_local
                - main.matrix_world @ bone.head_local).length < EPSILON:
            raise ValueError(f"骨骼长度为零：{name} ({slot})")
    for side in ("L", "R"):
        for finger in ("thumb", "index", "middle", "ring", "little"):
            slots = [f"{finger}_{segment}.{side}" for segment in (
                "proximal", "intermediate", "distal")]
            present = [slot in mapping for slot in slots]
            if any(present) and not all(present):
                raise ValueError("手指映射不完整：" + "、".join(
                    slot for slot in slots if slot not in mapping))


def _snapshot(bone):
    return {
        "head": bone.head_local.copy(), "tail": bone.tail_local.copy(),
        "matrix": bone.matrix_local.copy(), "length": bone.length,
        "parent": bone.parent.name if bone.parent else None,
    }


def _copy_rest(edit_bone, source_bone, world):
    edit_bone.head = world @ source_bone.head_local
    edit_bone.tail = world @ source_bone.tail_local
    # Bone.z_axis uses Bone.matrix (relative to its parent), whereas head_local
    # and tail_local are in armature space. Read all three from the same frame.
    edit_bone.align_roll(
        world.to_3x3() @ source_bone.matrix_local.to_3x3().col[2])


def align_reference_bones(context, main, rig, mapping):
    """Share the character's object axes; bake its scale into new references."""
    activate(context, rig)
    location, rotation, _scale = main.matrix_world.decompose()
    rig.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
    source_to_rig = rig.matrix_world.inverted() @ main.matrix_world
    # Editing both sides explicitly while X Mirror is on silently overwrites
    # the opposite side, especially for translated/asymmetric characters.
    rig.data.use_mirror_x = False
    original = {
        bone.name: _snapshot(bone) for bone in rig.data.bones
        if "_ref" in bone.name
    }
    expected = [REFERENCE_BONES[slot] for slot in mapping
                if slot in REFERENCE_BONES]
    missing = [name for name in expected if name not in original]
    if missing:
        raise ValueError("ARP 默认参考骨不兼容：" + "、".join(missing))
    bpy.ops.object.mode_set(mode="EDIT")
    bones = rig.data.edit_bones
    for name in original:
        bones[name].use_connect = False
    mapped_refs = {}
    for slot, source_name in mapping.items():
        ref_name = REFERENCE_BONES.get(slot)
        if ref_name:
            _copy_rest(bones[ref_name], main.data.bones[source_name], source_to_rig)
            if slot.startswith("toes."):
                # ARP generates toes_01 with the opposite roll to toes_ref.
                # Account for that fixed convention before Match to Rig.
                source_z = main.data.bones[source_name].matrix_local.to_3x3().col[2]
                bones[ref_name].align_roll(-(source_to_rig.to_3x3() @ source_z))
            mapped_refs[ref_name] = source_name

    # Children keep the template's relative placement, rather than being left
    # behind at the original human preset position after their parent moves.
    for name, saved in original.items():
        if name in mapped_refs:
            continue
        anchor = saved["parent"]
        # Foot banks and heel are siblings of foot_ref, but belong to its frame.
        if name.startswith(("foot_bank_", "foot_heel_")):
            anchor = "foot_ref" + name[-2:]
        while anchor and anchor not in mapped_refs:
            anchor = original.get(anchor, {}).get("parent")
        if not anchor:
            raise ValueError(f"无法确定参考骨的对齐基准：{name}")
        parent = bones[anchor]
        scale = parent.length / original[anchor]["length"]
        transform = (parent.matrix @ Matrix.Scale(scale, 4)
                     @ original[anchor]["matrix"].inverted())
        bone = bones[name]
        bone.head = transform @ saved["head"]
        bone.tail = transform @ saved["tail"]
        bone.align_roll(transform.to_3x3() @ saved["matrix"].to_3x3().col[2])

    palm_count = 0
    for side in ("L", "R"):
        suffix = "." + side.lower()
        hand_name = "hand_ref" + suffix
        hand = bones[hand_name]
        hand_original = original[hand_name]
        finger_pairs = [
            (finger, arp_finger, mapping.get(f"{finger}_proximal.{side}"))
            for finger, arp_finger in (
                ("index", "index"), ("middle", "middle"),
                ("ring", "ring"), ("little", "pinky"))
        ]
        present = [(finger, arp_finger, name)
                   for finger, arp_finger, name in finger_pairs if name]
        scale = hand.length / hand_original["length"]
        if present:
            before = sum(
                (original[f"{arp_finger}1_ref{suffix}"]["head"]
                 - hand_original["head"]).length
                for _, arp_finger, _ in present)
            after = sum(
                (source_to_rig @ main.data.bones[name].head_local
                 - hand.head).length for _, _, name in present)
            if before > EPSILON:
                scale = after / before
        transform = (hand.matrix @ Matrix.Scale(scale, 4)
                     @ hand_original["matrix"].inverted())
        for _, arp_finger, source_name in finger_pairs:
            palm_name = f"{arp_finger}1_base_ref{suffix}"
            palm = bones[palm_name]
            if source_name:
                proximal = main.data.bones[source_name]
                source_palm = proximal.parent
                if (source_palm and source_palm.name not in mapping.values()
                        and any(marker in source_palm.name.lower() for marker in
                                ("metacarp", "palm", "base_ref", "掌"))):
                    _copy_rest(palm, source_palm, source_to_rig)
                else:
                    palm.head = transform @ original[palm_name]["head"]
                    palm.tail = source_to_rig @ proximal.head_local
                    palm.align_roll(hand.z_axis)
                # Exact continuity is required even with an authored palm bone.
                palm.tail = bones[f"{arp_finger}1_ref{suffix}"].head
                palm_count += 1
            if palm.length < EPSILON:
                raise ValueError(f"掌骨长度退化：{palm_name}")
    bpy.ops.object.mode_set(mode="OBJECT")
    return palm_count


def _configure_constraint(constraint, target, target_name, slot=""):
    constraint.target = target
    constraint.subtarget = target_name
    constraint.owner_space = "WORLD"
    constraint.target_space = "WORLD"
    constraint.mute = False
    constraint.influence = 1.0
    if constraint.type == "COPY_LOCATION":
        constraint.head_tail = 1.0 if slot == "hips" else 0.0
        constraint.use_offset = False
    else:
        constraint.mix_mode = "REPLACE"
        # Preserve the established hips/twist compatibility conventions.
        if slot == "hips" or ("arm" in slot and "twist" in slot):
            constraint.owner_space = "LOCAL_WITH_PARENT"
            constraint.target_space = "LOCAL_OWNER_ORIENT"
        elif "leg" in slot and "twist" in slot:
            constraint.owner_space = "LOCAL"
            constraint.target_space = "LOCAL_OWNER_ORIENT"


def bind_pairs(owner, target, pairs, prefix):
    """Update only our own constraints; repeating an operation is idempotent."""
    plan = []
    for name, target_name, _slot in pairs:
        if name not in owner.pose.bones or target_name not in target.pose.bones:
            raise ValueError(f"约束目标不存在：{name} → {target_name}")
        types = ("COPY_ROTATION",) if "twist" in _slot else (
            "COPY_LOCATION", "COPY_ROTATION")
        for constraint_type in types:
            label = prefix + constraint_type
            constraint = owner.pose.bones[name].constraints.get(label)
            if constraint and constraint.type != constraint_type:
                raise ValueError(f"已有同名约束类型不匹配：{name}/{label}")
            plan.append((name, target_name, _slot, constraint_type, constraint))
    created = []
    snapshots = []
    attributes = (
        "target", "subtarget", "owner_space", "target_space", "mute",
        "influence", "head_tail", "use_offset", "mix_mode",
    )
    try:
        for name, target_name, slot, constraint_type, constraint in plan:
            bone = owner.pose.bones[name]
            if constraint is None:
                constraint = bone.constraints.new(constraint_type)
                constraint.name = prefix + constraint_type
                created.append((bone, constraint))
            else:
                snapshots.append((constraint, {
                    key: getattr(constraint, key)
                    for key in attributes if hasattr(constraint, key)
                }))
            _configure_constraint(constraint, target, target_name, slot)
    except Exception:
        for bone, constraint in reversed(created):
            bone.constraints.remove(constraint)
        for constraint, saved in snapshots:
            for key, value in saved.items():
                setattr(constraint, key, value)
        raise
    for name, _, slot in pairs:
        bone = owner.pose.bones[name]
        types = ("COPY_ROTATION",) if "twist" in slot else (
            "COPY_LOCATION", "COPY_ROTATION")
        for constraint in list(bone.constraints):
            if (constraint.name.startswith(prefix)
                    and constraint.type not in types):
                bone.constraints.remove(constraint)
    return len(pairs)


def would_create_cycle(owner, target):
    pending = [target]
    seen = set()
    while pending:
        obj = pending.pop()
        if obj == owner:
            return True
        if obj in seen:
            continue
        seen.add(obj)
        if obj.parent:
            pending.append(obj.parent)
        constraints = list(obj.constraints)
        if obj.type == "ARMATURE":
            constraints.extend(c for bone in obj.pose.bones for c in bone.constraints)
        pending.extend(
            c.target for c in constraints
            if not c.mute and c.influence and getattr(c, "target", None)
            and c.target != obj
        )
    return False


@contextmanager
def arp_operator_context(context):
    """ARP's append operator accesses VIEW_3D overlays, including in batch tests."""
    if context.area and context.area.type == "VIEW_3D":
        yield
        return
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(window=window, area=area, region=region):
                    yield
                return
    raise ValueError("生成 ARP 控制器需要一个 3D 视图")


def _data_inventory():
    return {name: set(getattr(bpy.data, name)) for name in (
        "objects", "collections", "armatures", "meshes", "curves", "actions")}


def _remove_created_data(before):
    created = [
        item for name, existing in before.items()
        for item in getattr(bpy.data, name) if item not in existing
    ]
    if created:
        bpy.data.batch_remove(ids=created)


def generate_controller(context, main):
    validate_main(main, context)
    ready, message = arp_status()
    if not ready:
        raise ValueError(message)
    with object_context(context):
        mapping = source_mapping(main)
        validate_mapping(main, mapping)
        existing = main.ho_arp_controller
        if existing:
            if context.view_layer.objects.get(existing.name) != existing:
                raise ValueError("关联的 ARP 控制器不在当前视图层")
            # A repeat click refreshes the binding without rebuilding an animated
            # controller or adding another complete rig to the scene.
            pairs = [(name, DEFORM_BONES[slot], slot)
                     for slot, name in mapping.items() if slot in DEFORM_BONES]
            return existing, bind_pairs(main, existing, pairs, ASSEMBLY_PREFIX), 0
        before = _data_inventory()
        rig = None
        try:
            activate(context, main)
            with arp_operator_context(context):
                result = bpy.ops.arp.append_arp("EXEC_DEFAULT", rig_preset="human")
            if "FINISHED" not in result:
                raise ValueError("ARP 默认人体创建失败")
            rigs = [
                obj for obj in bpy.data.objects
                if obj not in before["objects"] and obj.type == "ARMATURE"
                and "root_ref.x" in obj.data.bones
            ]
            if len(rigs) != 1:
                raise ValueError("无法唯一确定新建的 ARP 人体骨架")
            rig = rigs[0]
            rig.name = main.name + "_ARP"
            palm_count = align_reference_bones(context, main, rig, mapping)
            # Some ARP validation failures return FINISHED. The preset can
            # already contain a true flag, so require this run to set it again.
            rig.data["has_match_to_rig"] = False
            with arp_operator_context(context):
                result = bpy.ops.arp.match_to_rig("EXEC_DEFAULT")
            if ("FINISHED" not in result
                    or not rig.data.get("has_match_to_rig", False)):
                raise ValueError("ARP Match to Rig 未完成")
            pairs = [(name, DEFORM_BONES[slot], slot)
                     for slot, name in mapping.items() if slot in DEFORM_BONES]
            # Validate every target before modifying any source constraints.
            missing = [target for _, target, _ in pairs if target not in rig.pose.bones]
            if missing:
                raise ValueError("ARP 形变骨缺失：" + "、".join(missing))
            count = bind_pairs(main, rig, pairs, ASSEMBLY_PREFIX)
        except Exception:
            current = context.view_layer.objects.active
            if current and current.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _remove_created_data(before)
            raise
        for slot, name in mapping.items():
            if slot in DEFORM_BONES:
                main.data.bones[name].hotools_boneprops.humanoidMapping = slot
        main.ho_arp_controller = rig
        return rig, count, palm_count


class OP_GenerateArpController(Operator):
    bl_idname = "ho.generate_arp_controller"
    bl_label = "生成 ARP 控制器"
    bl_description = (
        "创建默认 ARP 人体、对齐参考骨并补齐掌骨，生成控制器后约束主骨架；"
        "已有控制器时刷新绑定，不重复生成或改写控制器动画"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene.ho_arp_main_armature is not None and arp_status()[0]

    def execute(self, context):
        try:
            rig, count, palms = generate_controller(
                context, context.scene.ho_arp_main_armature)
        except Exception as error:
            self.report({"ERROR"}, f"ARP 装配失败：{error}")
            return {"CANCELLED"}
        unsupported = sorted({
            bone.hotools_boneprops.humanoidMapping.strip()
            for bone in context.scene.ho_arp_main_armature.data.bones
            if bone.hotools_boneprops.humanoidMapping.strip()
            and bone.hotools_boneprops.humanoidMapping.strip() not in DEFORM_BONES
        })
        if unsupported:
            self.report({"WARNING"}, "默认 ARP 人体未绑定的槽位：" + "、".join(unsupported))
        self.report({"INFO"}, f"ARP 装配完成：{rig.name}，绑定 {count} 根骨，补齐 {palms} 根掌骨")
        return {"FINISHED"}


class OP_SnapToMainArmature(Operator):
    bl_idname = "ho.snap_to_main_armature"
    bl_label = "吸附到主骨架"
    bl_description = "在待吸附骨架的所有同名骨上添加复制位置、复制旋转约束，目标为主骨架"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        main = context.scene.ho_arp_main_armature
        follower = context.scene.ho_arp_follower_armature
        try:
            validate_main(main, context)
            validate_main(follower, context)
            if follower == main or follower.data == main.data:
                raise ValueError("主骨架与待吸附骨架必须是两个独立骨架")
            if would_create_cycle(follower, main):
                raise ValueError("吸附将产生循环依赖，请检查现有约束和父子关系")
            pairs = [(bone.name, bone.name, "") for bone in follower.pose.bones
                     if bone.name in main.pose.bones]
            if not pairs:
                raise ValueError("两个骨架没有同名骨骼")
            with object_context(context):
                count = bind_pairs(follower, main, pairs, SNAP_PREFIX)
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已吸附 {count} 根同名骨到 {main.name}")
        return {"FINISHED"}


class OP_ClearHumanoidConstraints(Operator):
    bl_idname = "ho.clear_humanoid_constraints"
    bl_label = "删除 Humanoid 骨全部约束"
    bl_description = "删除主骨架中带 Humanoid 映射的骨上的全部约束，包括手工约束；可撤销"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        main = context.scene.ho_arp_main_armature
        try:
            validate_main(main, context)
            count = 0
            with object_context(context):
                for bone in main.pose.bones:
                    props = getattr(bone.bone, "hotools_boneprops", None)
                    if not getattr(props, "humanoidMapping", "").strip():
                        continue
                    for constraint in list(bone.constraints):
                        bone.constraints.remove(constraint)
                        count += 1
        except (ValueError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"已删除 Humanoid 骨上的 {count} 个约束")
        return {"FINISHED"}


def draw_panel(layout, context):
    scene = context.scene
    box = layout.box()
    box.label(text="ARP 装配", icon="ARMATURE_DATA")
    box.prop(scene, "ho_arp_main_armature", text="主骨架")
    ready, message = arp_status()
    if not ready:
        warning = box.column(align=True)
        warning.alert = True
        warning.label(text=message, icon="ERROR")
    row = box.row()
    row.enabled = ready and scene.ho_arp_main_armature is not None
    row.operator(OP_GenerateArpController.bl_idname, icon="ARMATURE_DATA")
    controller = getattr(scene.ho_arp_main_armature, "ho_arp_controller", None)
    if controller:
        box.label(text=f"控制器：{controller.name}", icon="LINKED")
    box.separator()
    box.prop(scene, "ho_arp_follower_armature", text="待吸附骨架")
    row = box.row()
    row.enabled = bool(scene.ho_arp_main_armature and scene.ho_arp_follower_armature)
    row.operator(OP_SnapToMainArmature.bl_idname, icon="CONSTRAINT_BONE")
    row = box.row()
    row.enabled = scene.ho_arp_main_armature is not None
    row.operator(OP_ClearHumanoidConstraints.bl_idname, icon="TRASH")


CLASSES = (
    OP_GenerateArpController, OP_SnapToMainArmature, OP_ClearHumanoidConstraints,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ho_arp_main_armature = PointerProperty(
        name="主骨架", type=bpy.types.Object, poll=armature_filter)
    bpy.types.Scene.ho_arp_follower_armature = PointerProperty(
        name="待吸附骨架", type=bpy.types.Object, poll=armature_filter)
    bpy.types.Object.ho_arp_controller = PointerProperty(
        name="ARP 控制器", type=bpy.types.Object, poll=armature_filter)


def unregister():
    del bpy.types.Object.ho_arp_controller
    del bpy.types.Scene.ho_arp_follower_armature
    del bpy.types.Scene.ho_arp_main_armature
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
