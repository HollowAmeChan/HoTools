import bpy
from bpy.props import PointerProperty
from bpy.types import Operator
from mathutils import Vector

from ..BoneTools.boneHumanoid import OP_MoveHumanoidBonesToCollection
from ..BoneTools.boneOperators import OP_ApplyRestPose
from ..BoneTools.boneDissolve import OP_SimpleDissolveBone


def _armature_filter(_self, obj):
    return obj.type == 'ARMATURE'


def reg_props():
    bpy.types.Scene.ho_mod_weight_reference_armature = PointerProperty(
        name="参考骨架",
        description="提供同名骨骼Head目标位置的参考骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    bpy.types.Scene.ho_mod_weight_moving_armature = PointerProperty(
        name="移动骨架",
        description="需要移动同名骨骼的骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    bpy.types.Scene.ho_mod_weight_merge_main_armature = PointerProperty(
        name="主骨架",
        description="保留现有骨骼及其自定义信息的目标骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )
    bpy.types.Scene.ho_mod_weight_merge_asset_armature = PointerProperty(
        name="素材骨架",
        description="融合到主骨架并在完成后移除的素材骨架",
        type=bpy.types.Object,
        poll=_armature_filter,
    )


def ureg_props():
    del bpy.types.Scene.ho_mod_weight_merge_asset_armature
    del bpy.types.Scene.ho_mod_weight_merge_main_armature
    del bpy.types.Scene.ho_mod_weight_moving_armature
    del bpy.types.Scene.ho_mod_weight_reference_armature


def _copy_custom_properties(source, target):
    try:
        keys = source.keys()
    except (AttributeError, RuntimeError, TypeError):
        return

    for key in keys:
        try:
            target[key] = source[key]
        except (AttributeError, KeyError, TypeError, ValueError):
            continue

        try:
            ui_data = source.id_properties_ui(key).as_dict()
            if ui_data:
                target.id_properties_ui(key).update(**ui_data)
        except (AttributeError, KeyError, TypeError, ValueError):
            pass


def _copy_writable_rna_properties(source, target, skip=()):
    skipped = set(skip)
    skipped.add("rna_type")

    for prop in source.bl_rna.properties:
        identifier = prop.identifier
        if identifier in skipped or prop.is_readonly:
            continue
        if not hasattr(target, identifier):
            continue

        try:
            value = getattr(source, identifier)
            if prop.is_array:
                value = value[:]
            setattr(target, identifier, value)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass


def _copy_bone_color(source, target):
    try:
        target.color.palette = source.color.palette
        if source.color.palette == 'CUSTOM':
            for attr in ("normal", "select", "active"):
                setattr(target.color.custom, attr, getattr(source.color.custom, attr)[:])
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


class OP_SnapMatchingBoneHeads(Operator):
    bl_idname = "ho.mod_weight_snap_matching_bone_heads"
    bl_label = "吸附同名骨骼Head"
    bl_description = (
        "按当前姿态的视觉位置，将移动骨架中所有同名骨骼的Head吸附到参考骨架；"
        "只平移骨骼并保持原有长度、方向和Roll"
    )
    bl_options = {'REGISTER', 'UNDO'}

    _MAX_CORRECTION_PASSES = 4
    _WORLD_TOLERANCE = 1e-5

    @classmethod
    def poll(cls, context):
        scene = context.scene
        reference = scene.ho_mod_weight_reference_armature
        moving = scene.ho_mod_weight_moving_armature
        return (
            reference is not None
            and moving is not None
            and reference.type == 'ARMATURE'
            and moving.type == 'ARMATURE'
        )

    @staticmethod
    def _restore_context(context, previous_active, previous_selected, previous_mode):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            try:
                obj.select_set(obj in previous_selected)
            except RuntimeError:
                pass

        context.view_layer.objects.active = previous_active

        if previous_active is not None and previous_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass

    @staticmethod
    def _collect_pose_snapshot(obj, depsgraph):
        """读取依赖图评估后的姿态Head世界坐标和姿态矩阵。"""
        evaluated = obj.evaluated_get(depsgraph)
        world = evaluated.matrix_world
        heads_world = {
            pose_bone.name: world @ pose_bone.head
            for pose_bone in evaluated.pose.bones
        }
        pose_matrices = {
            pose_bone.name: pose_bone.matrix.copy()
            for pose_bone in evaluated.pose.bones
        }
        return heads_world, pose_matrices

    @staticmethod
    def _bone_depth(bone):
        depth = 0
        parent = bone.parent
        while parent is not None:
            depth += 1
            parent = parent.parent
        return depth

    @staticmethod
    def _enter_edit_mode(context, moving):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            if obj.select_get():
                obj.select_set(False)

        moving.select_set(True)
        context.view_layer.objects.active = moving
        bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def _pose_residual_to_edit_offset(
        moving,
        parent_name,
        residual_world,
        pose_matrices,
        moving_world_inv_3x3,
    ):
        residual_armature = moving_world_inv_3x3 @ residual_world
        if parent_name is None:
            return residual_armature

        parent_pose_matrix = pose_matrices.get(parent_name)
        parent_bone = moving.data.bones.get(parent_name)
        if parent_pose_matrix is None or parent_bone is None:
            return residual_armature

        # 子骨静置坐标会先经过父骨当前的姿态形变；反变换后才能得到
        # 真正应写入EditBone的位移，尤其用于父骨已有旋转/缩放的情况。
        parent_deform = (
            parent_pose_matrix
            @ parent_bone.matrix_local.inverted_safe()
        )
        return parent_deform.to_3x3().inverted_safe() @ residual_armature

    def execute(self, context):
        scene = context.scene
        reference = scene.ho_mod_weight_reference_armature
        moving = scene.ho_mod_weight_moving_armature

        if reference == moving:
            self.report({'ERROR'}, "参考骨架与移动骨架不能是同一个对象")
            return {'CANCELLED'}

        if moving.name not in context.view_layer.objects:
            self.report({'ERROR'}, "移动骨架不在当前视图层中")
            return {'CANCELLED'}

        previous_active = context.view_layer.objects.active
        previous_selected = {
            obj for obj in context.view_layer.objects if obj.select_get()
        }
        previous_mode = (
            previous_active.mode if previous_active is not None else 'OBJECT'
        )

        aligned_count = 0
        moved_count = 0
        unchanged_count = 0
        unmatched_count = 0
        inherited_count = 0
        disconnected_count = 0
        correction_passes = 0
        max_world_error = 0.0
        original_edit_state = {}
        operation_error = None

        try:
            active = context.view_layer.objects.active
            if active is not None and active.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            depsgraph = context.evaluated_depsgraph_get()
            reference_heads_world, _reference_pose_matrices = (
                self._collect_pose_snapshot(
                    reference,
                    depsgraph,
                )
            )
            moving_heads_world, _moving_pose_matrices = (
                self._collect_pose_snapshot(
                    moving,
                    depsgraph,
                )
            )
            matching_names = {
                bone.name
                for bone in moving.data.bones
                if (
                    bone.name in reference_heads_world
                    and bone.name in moving_heads_world
                )
            }

            if not matching_names:
                self.report({'WARNING'}, "两个骨架中没有同名骨骼")
                return {'CANCELLED'}

            parent_names = {
                bone.name: bone.parent.name if bone.parent else None
                for bone in moving.data.bones
            }
            bones_by_depth = {}
            for bone in moving.data.bones:
                depth = self._bone_depth(bone)
                bones_by_depth.setdefault(depth, []).append(bone.name)

            self._enter_edit_mode(context, moving)

            edit_bones = moving.data.edit_bones
            original_edit_state = {
                bone.name: (
                    bone.head.copy(),
                    bone.tail.copy(),
                    bone.use_connect,
                )
                for bone in edit_bones
            }

            # 断开全部编辑骨，避免移动父骨或子骨Head时被连接关系拉回。
            for bone in edit_bones:
                if bone.use_connect:
                    bone.use_connect = False
                    disconnected_count += 1

            bpy.ops.object.mode_set(mode='OBJECT')

            moving_world_inv_3x3 = (
                moving.matrix_world.inverted_safe().to_3x3()
            )
            total_offsets = {
                bone.name: Vector((0.0, 0.0, 0.0))
                for bone in moving.data.bones
            }
            inherited_names = set()

            for pass_index in range(self._MAX_CORRECTION_PASSES):
                pass_offsets = {}

                for depth in sorted(bones_by_depth):
                    context.view_layer.update()
                    depsgraph = context.evaluated_depsgraph_get()
                    moving_heads_world, moving_pose_matrices = (
                        self._collect_pose_snapshot(
                            moving,
                            depsgraph,
                        )
                    )

                    depth_offsets = {}
                    for bone_name in bones_by_depth[depth]:
                        parent_name = parent_names[bone_name]

                        if bone_name in matching_names:
                            target_head_world = reference_heads_world[bone_name]
                            current_head_world = moving_heads_world.get(bone_name)
                            if current_head_world is None:
                                continue

                            residual_world = (
                                target_head_world - current_head_world
                            )
                            offset = self._pose_residual_to_edit_offset(
                                moving,
                                parent_name,
                                residual_world,
                                moving_pose_matrices,
                                moving_world_inv_3x3,
                            )
                        else:
                            # 无同名目标时，沿层级继承父骨本轮使用的同一offset。
                            offset = pass_offsets.get(parent_name)
                            if offset is None:
                                offset = Vector((0.0, 0.0, 0.0))
                            elif offset.length_squared > 1e-20:
                                inherited_names.add(bone_name)

                        pass_offsets[bone_name] = offset.copy()
                        if offset.length_squared > 1e-20:
                            depth_offsets[bone_name] = offset

                    if not depth_offsets:
                        continue

                    self._enter_edit_mode(context, moving)
                    for bone_name, offset in depth_offsets.items():
                        bone = moving.data.edit_bones.get(bone_name)
                        if bone is None:
                            continue

                        bone_vector = bone.tail - bone.head
                        target_head = bone.head + offset
                        bone.head = target_head
                        bone.tail = target_head + bone_vector
                        total_offsets[bone_name] += offset

                    bpy.ops.object.mode_set(mode='OBJECT')

                correction_passes = pass_index + 1
                context.view_layer.update()
                depsgraph = context.evaluated_depsgraph_get()
                moving_heads_world, _moving_pose_matrices = (
                    self._collect_pose_snapshot(
                        moving,
                        depsgraph,
                    )
                )
                errors = [
                    (
                        reference_heads_world[bone_name]
                        - moving_heads_world[bone_name]
                    ).length
                    for bone_name in matching_names
                    if bone_name in moving_heads_world
                ]
                max_world_error = max(errors, default=0.0)
                if max_world_error <= self._WORLD_TOLERANCE:
                    break

            aligned_count = len(matching_names)
            moved_count = sum(
                1
                for bone_name in matching_names
                if total_offsets[bone_name].length_squared > 1e-20
            )
            unchanged_count = aligned_count - moved_count
            unmatched_count = len(moving.data.bones) - aligned_count
            inherited_count = len(inherited_names)

        except Exception as error:
            operation_error = error

            if original_edit_state:
                try:
                    self._enter_edit_mode(context, moving)
                except Exception:
                    pass

            if moving.mode == 'EDIT' and original_edit_state:
                for bone_name, state in original_edit_state.items():
                    bone = moving.data.edit_bones.get(bone_name)
                    if bone is None:
                        continue
                    bone.head, bone.tail, bone.use_connect = state

                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass

        finally:
            try:
                self._restore_context(
                    context,
                    previous_active,
                    previous_selected,
                    previous_mode,
                )
            except Exception as restore_error:
                print(
                    "[Mod Weight Head Snap] failed to restore context: "
                    f"{restore_error}"
                )

        if operation_error is not None:
            self.report({'ERROR'}, f"吸附同名骨骼Head失败：{operation_error}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"同名骨骼Head吸附完成：对齐 {aligned_count}，"
            f"移动 {moved_count}，未变化 {unchanged_count}，"
            f"子级跟随 {inherited_count}，无同名 {unmatched_count}，"
            f"断开连接 {disconnected_count}，校正 {correction_passes} 轮，"
            f"最大视觉误差 {max_world_error:.6g}",
        )
        return {'FINISHED'}


class OP_MergeArmatures(Operator):
    bl_idname = "ho.mod_weight_merge_armatures"
    bl_label = "融合骨架"
    bl_description = (
        "保留主骨架的同名骨，将素材骨架的非同名骨原地复制到主骨架，"
        "并把父级转接到主骨架的同名骨；完成后移除素材骨架"
    )
    bl_options = {'REGISTER', 'UNDO'}

    _BONE_SKIP_PROPERTIES = {
        "name",
        "parent",
        "children",
        "collections",
        "color",
        "head",
        "head_local",
        "tail",
        "tail_local",
        "center",
        "vector",
        "length",
        "matrix",
        "matrix_local",
    }
    _POSE_SKIP_PROPERTIES = {
        "name",
        "bone",
        "parent",
        "children",
        "constraints",
        "custom_shape_transform",
        "head",
        "tail",
        "center",
        "vector",
        "length",
        "matrix",
        "matrix_basis",
        "channel_matrix",
        "location",
        "rotation_axis_angle",
        "rotation_euler",
        "rotation_quaternion",
        "scale",
    }

    @classmethod
    def poll(cls, context):
        scene = context.scene
        main = scene.ho_mod_weight_merge_main_armature
        asset = scene.ho_mod_weight_merge_asset_armature
        return (
            main is not None
            and asset is not None
            and main.type == 'ARMATURE'
            and asset.type == 'ARMATURE'
        )

    @staticmethod
    def _object_in_view_layer(context, obj):
        return obj is not None and obj.name in context.view_layer.objects

    @staticmethod
    def _enter_object_mode(context):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

    @classmethod
    def _enter_edit_mode(cls, context, obj):
        cls._enter_object_mode(context)
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')

    @staticmethod
    def _snapshot_bones(asset):
        snapshots = []
        for bone in asset.data.bones:
            snapshots.append({
                "name": bone.name,
                "parent_name": bone.parent.name if bone.parent else None,
                "head": bone.head_local.copy(),
                "tail": bone.tail_local.copy(),
                "roll_axis": bone.z_axis.copy(),
                "use_connect": bone.use_connect,
                "collection_names": [
                    collection.name for collection in bone.collections
                ],
            })
        return snapshots

    @staticmethod
    def _restore_context(
        context,
        previous_active,
        previous_active_was_asset,
        previous_selected,
        asset_was_selected,
        previous_mode,
        main,
        merge_succeeded,
    ):
        active = context.view_layer.objects.active
        if active is not None and active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        for obj in context.view_layer.objects:
            try:
                should_select = obj in previous_selected
                if merge_succeeded and obj == main and asset_was_selected:
                    should_select = True
                obj.select_set(should_select)
            except RuntimeError:
                pass

        if merge_succeeded and previous_active_was_asset:
            target_active = main
        elif OP_MergeArmatures._object_in_view_layer(context, previous_active):
            target_active = previous_active
        else:
            target_active = main

        context.view_layer.objects.active = target_active
        if target_active is not None and previous_mode != 'OBJECT':
            try:
                target_active.select_set(True)
                bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass

    @classmethod
    def _remove_created_bones(cls, context, main, created_names):
        if not created_names or not cls._object_in_view_layer(context, main):
            return

        cls._enter_edit_mode(context, main)
        for bone_name in created_names:
            bone = main.data.edit_bones.get(bone_name)
            if bone is not None:
                main.data.edit_bones.remove(bone)
        bpy.ops.object.mode_set(mode='OBJECT')

    @staticmethod
    def _copy_bone_collections(main, source_bone, target_bone, created_collections):
        for source_collection in source_bone.collections:
            target_collection = main.data.collections.get(source_collection.name)
            if target_collection is None:
                target_collection = main.data.collections.new(source_collection.name)
                created_collections.add(source_collection.name)
                _copy_custom_properties(source_collection, target_collection)
            target_collection.assign(target_bone)

    @classmethod
    def _copy_bone_data(cls, main, asset, copied_names, created_collections):
        for bone_name in copied_names:
            source_bone = asset.data.bones[bone_name]
            target_bone = main.data.bones[bone_name]
            _copy_writable_rna_properties(
                source_bone,
                target_bone,
                cls._BONE_SKIP_PROPERTIES,
            )
            for handle_property in (
                "bbone_custom_handle_start",
                "bbone_custom_handle_end",
            ):
                source_handle = getattr(source_bone, handle_property, None)
                if source_handle is None:
                    continue
                target_handle = main.data.bones.get(source_handle.name)
                if target_handle is not None:
                    try:
                        setattr(target_bone, handle_property, target_handle)
                    except (AttributeError, RuntimeError, TypeError):
                        pass
            _copy_custom_properties(source_bone, target_bone)
            _copy_bone_color(source_bone, target_bone)
            cls._copy_bone_collections(
                main,
                source_bone,
                target_bone,
                created_collections,
            )

    @classmethod
    def _copy_pose_data(cls, main, asset, copied_names):
        custom_shape_transform_names = {}

        for bone_name in copied_names:
            source_pose_bone = asset.pose.bones.get(bone_name)
            target_pose_bone = main.pose.bones.get(bone_name)
            if source_pose_bone is None or target_pose_bone is None:
                continue

            _copy_writable_rna_properties(
                source_pose_bone,
                target_pose_bone,
                cls._POSE_SKIP_PROPERTIES,
            )
            _copy_custom_properties(source_pose_bone, target_pose_bone)

            transform_bone = source_pose_bone.custom_shape_transform
            if transform_bone is not None:
                custom_shape_transform_names[bone_name] = transform_bone.name

            for source_constraint in source_pose_bone.constraints:
                target_constraint = target_pose_bone.constraints.new(
                    source_constraint.type
                )
                _copy_writable_rna_properties(
                    source_constraint,
                    target_constraint,
                    {"type"},
                )
                if hasattr(source_constraint, "target"):
                    try:
                        target_constraint.target = (
                            main
                            if source_constraint.target == asset
                            else source_constraint.target
                        )
                    except (AttributeError, RuntimeError, TypeError):
                        pass
                if hasattr(source_constraint, "subtarget"):
                    try:
                        target_constraint.subtarget = source_constraint.subtarget
                    except (AttributeError, RuntimeError, TypeError):
                        pass
                _copy_custom_properties(source_constraint, target_constraint)

        for bone_name, transform_name in custom_shape_transform_names.items():
            transform_bone = main.pose.bones.get(transform_name)
            if transform_bone is not None:
                main.pose.bones[bone_name].custom_shape_transform = transform_bone

    @staticmethod
    def _remove_empty_created_collections(main, created_collections):
        for collection_name in created_collections:
            collection = main.data.collections.get(collection_name)
            if collection is None or collection.bones:
                continue
            try:
                main.data.collections.remove(collection)
            except RuntimeError:
                pass

    @staticmethod
    def _remap_object_references(asset, main):
        """Some RNA pointers created during the merge are not covered by ID.user_remap."""
        for obj in bpy.data.objects:
            for modifier in obj.modifiers:
                if hasattr(modifier, "object") and modifier.object == asset:
                    modifier.object = main

            for constraint in obj.constraints:
                if hasattr(constraint, "target") and constraint.target == asset:
                    constraint.target = main

            if obj.pose is None:
                continue
            for pose_bone in obj.pose.bones:
                for constraint in pose_bone.constraints:
                    if (
                        hasattr(constraint, "target")
                        and constraint.target == asset
                    ):
                        constraint.target = main

    def execute(self, context):
        scene = context.scene
        main = scene.ho_mod_weight_merge_main_armature
        asset = scene.ho_mod_weight_merge_asset_armature

        if main == asset:
            self.report({'ERROR'}, "主骨架与素材骨架不能是同一个对象")
            return {'CANCELLED'}
        if not self._object_in_view_layer(context, main):
            self.report({'ERROR'}, "主骨架不在当前视图层中")
            return {'CANCELLED'}
        if not self._object_in_view_layer(context, asset):
            self.report({'ERROR'}, "素材骨架不在当前视图层中")
            return {'CANCELLED'}
        if not main.data.is_editable:
            self.report({'ERROR'}, "主骨架数据不可编辑")
            return {'CANCELLED'}
        if not asset.is_editable:
            self.report({'ERROR'}, "素材骨架对象不可编辑")
            return {'CANCELLED'}

        previous_active = context.view_layer.objects.active
        previous_active_was_asset = previous_active == asset
        previous_selected = {
            obj for obj in context.view_layer.objects if obj.select_get()
        }
        asset_was_selected = asset in previous_selected
        previous_mode = (
            previous_active.mode if previous_active is not None else 'OBJECT'
        )

        existing_names = {bone.name for bone in main.data.bones}
        source_snapshots = self._snapshot_bones(asset)
        copied_snapshots = [
            snapshot
            for snapshot in source_snapshots
            if snapshot["name"] not in existing_names
        ]
        copied_names = [snapshot["name"] for snapshot in copied_snapshots]
        duplicate_count = len(source_snapshots) - len(copied_snapshots)
        created_names = []
        created_collections = set()
        disconnected_count = 0
        merge_succeeded = False
        operation_error = None
        asset_data = asset.data
        parented_world_matrices = {
            obj: obj.matrix_world.copy()
            for obj in bpy.data.objects
            if obj.parent == asset
        }

        try:
            source_to_main = main.matrix_world.inverted_safe() @ asset.matrix_world
            direction_to_main = source_to_main.to_3x3()

            self._enter_edit_mode(context, main)
            edit_bones = main.data.edit_bones

            for snapshot in copied_snapshots:
                bone = edit_bones.new(snapshot["name"])
                created_names.append(bone.name)
                bone.head = source_to_main @ snapshot["head"]
                bone.tail = source_to_main @ snapshot["tail"]
                roll_axis = direction_to_main @ snapshot["roll_axis"]
                if roll_axis.length_squared > 1e-20:
                    bone.align_roll(roll_axis)

            for snapshot in copied_snapshots:
                bone = edit_bones[snapshot["name"]]
                parent_name = snapshot["parent_name"]
                if parent_name is not None:
                    bone.parent = edit_bones.get(parent_name)

                if snapshot["use_connect"] and bone.parent is not None:
                    if (bone.head - bone.parent.tail).length <= 1e-6:
                        bone.use_connect = True
                    else:
                        disconnected_count += 1

            bpy.ops.object.mode_set(mode='OBJECT')
            context.view_layer.update()

            self._copy_bone_data(
                main,
                asset,
                copied_names,
                created_collections,
            )
            self._copy_pose_data(main, asset, copied_names)

            self._remap_object_references(asset, main)
            asset.user_remap(main)
            self._remap_object_references(asset, main)
            for child, world_matrix in parented_world_matrices.items():
                try:
                    child.matrix_world = world_matrix
                except (ReferenceError, RuntimeError):
                    pass
            scene.ho_mod_weight_merge_asset_armature = None
            bpy.data.objects.remove(asset, do_unlink=True)
            if asset_data.users == 0:
                bpy.data.armatures.remove(asset_data)

            merge_succeeded = True
        except Exception as error:
            operation_error = error
            try:
                self._remove_created_bones(context, main, created_names)
                self._remove_empty_created_collections(main, created_collections)
            except Exception as rollback_error:
                print(
                    "[Mod Weight Armature Merge] failed to roll back: "
                    f"{rollback_error}"
                )
        finally:
            try:
                self._restore_context(
                    context,
                    previous_active,
                    previous_active_was_asset,
                    previous_selected,
                    asset_was_selected,
                    previous_mode,
                    main,
                    merge_succeeded,
                )
            except Exception as restore_error:
                print(
                    "[Mod Weight Armature Merge] failed to restore context: "
                    f"{restore_error}"
                )

        if operation_error is not None:
            self.report({'ERROR'}, f"融合骨架失败：{operation_error}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"骨架融合完成：新增 {len(copied_names)} 根骨，"
            f"忽略同名骨 {duplicate_count} 根，"
            f"为保持原位断开连接 {disconnected_count} 根",
        )
        return {'FINISHED'}


def drawWeightPanel(layout, context):
    column = layout.column(align=True)
    column.operator(OP_MoveHumanoidBonesToCollection.bl_idname,)
    column.operator(
        OP_ApplyRestPose.bl_idname,
        text="强制应用姿态与Mesh",
    )
    column.operator(
        OP_SimpleDissolveBone.bl_idname,
        text="简单融并",
    )

    layout.separator()
    box = layout.box()
    box.label(text="同名骨骼Head吸附")
    row = box.row(align=True)
    row.prop(
        context.scene,
        "ho_mod_weight_reference_armature",
        text="参考骨架",
    )
    row.prop(
        context.scene,
        "ho_mod_weight_moving_armature",
        text="移动骨架",
    )
    box.operator(
        OP_SnapMatchingBoneHeads.bl_idname,
        text="吸附同名骨骼Head",
    )

    layout.separator()
    box = layout.box()
    box.label(text="融合骨架")
    row = box.row(align=True)
    row.prop(
        context.scene,
        "ho_mod_weight_merge_main_armature",
        text="主骨架",
    )
    row.prop(
        context.scene,
        "ho_mod_weight_merge_asset_armature",
        text="素材骨架",
    )
    box.operator(
        OP_MergeArmatures.bl_idname,
        text="融合骨架",
    )


cls = [
    OP_SnapMatchingBoneHeads,
    OP_MergeArmatures,
]


def register():
    for item in cls:
        bpy.utils.register_class(item)
    reg_props()


def unregister():
    ureg_props()
    for item in reversed(cls):
        bpy.utils.unregister_class(item)
