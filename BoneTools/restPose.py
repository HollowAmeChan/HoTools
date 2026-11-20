"""HoTools 强制应用姿态：逐键烘焙修改器前缀，成功后才修改原资产。"""

import bpy

from Utils import bone_utils, shapekey_utils


def _remove_unused_mesh(mesh):
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _restore_shape_key_settings(source, target):
    if source is None:
        return
    target.use_relative = source.use_relative
    target.eval_time = source.eval_time
    for name in source.keys():
        target[name] = source[name]
        try:
            metadata = source.id_properties_ui(name).as_dict()
            if metadata:
                target.id_properties_ui(name).update(**metadata)
        except TypeError:  # 属性组等非标量 ID 属性没有 UI 元数据。
            pass
    for old_key, new_key in zip(source.key_blocks, target.key_blocks):
        shapekey_utils.copy_shape_key_settings(old_key, new_key)
    for old_key, new_key in zip(source.key_blocks, target.key_blocks):
        new_key.relative_key = target.key_blocks[old_key.relative_key.name]
    animation = source.animation_data
    if animation is not None:
        copied = target.animation_data_create()
        copied.action = animation.action
        if animation.action_slot is not None:
            copied.action_slot = animation.action_slot
        copied.use_nla = animation.use_nla
        for driver in animation.drivers:
            new_driver = copied.drivers.from_existing(src_driver=driver)
            for variable in new_driver.driver.variables:
                for driver_target in variable.targets:
                    if driver_target.id == source:
                        driver_target.id = target


def _prepare_mesh(obj, armature):
    """在副本上烘焙到最后一个目标骨架修改器，返回新网格与要移除的前置修改器。"""
    modifiers = list(obj.modifiers)
    targets = [index for index, modifier in enumerate(modifiers)
               if modifier.type == 'ARMATURE' and modifier.object == armature
               and modifier.show_viewport]
    if not targets:
        return None
    prefix = modifiers[:targets[-1] + 1]
    # 另一骨架不会随本次操作变成静置，不能把它烘进去后又保留一遍。
    for modifier in prefix:
        if (modifier.show_viewport and modifier.type == 'ARMATURE'
                and modifier.object is not None and modifier.object != armature):
            raise RuntimeError(f"{obj.name} 的前置修改器 {modifier.name} 指向另一骨架，无法单独应用姿态")
    remove_names = [modifier.name for modifier in prefix
                    if modifier.show_viewport and modifier.type != 'ARMATURE']
    temp = obj.copy()
    temp.data = obj.data.copy()
    bpy.context.scene.collection.objects.link(temp)
    copied_mesh = temp.data
    result_mesh = None
    try:
        # 非首位 Armature 不能在基础网格上单独应用：Mirror 等前置操作必须先落地。
        # 后面的修改器不参与此次烘焙，以免保留在原物体上时重复形变。
        for modifier in list(temp.modifiers)[targets[-1] + 1:]:
            temp.modifiers.remove(modifier)
        had_shape_keys = obj.data.shape_keys is not None
        if not had_shape_keys:
            temp.shape_key_add(name="Basis", from_mix=False)
        bpy.context.view_layer.update()
        baked, skipped, failed = shapekey_utils.bake_modifiers_keeping_shape_keys([temp])
        if failed:
            raise RuntimeError(f"{obj.name} 烘焙失败：{failed[0][1]}") from failed[0][1]
        if skipped or not baked:
            reason = skipped[0][1] if skipped else "没有生成网格"
            raise RuntimeError(f"{obj.name} 烘焙失败：{reason}")
        if had_shape_keys:
            _restore_shape_key_settings(obj.data.shape_keys, temp.data.shape_keys)
        else:
            temp.shape_key_clear()
        result_mesh = temp.data
        return result_mesh, remove_names
    finally:
        final_mesh = temp.data
        bpy.data.objects.remove(temp, do_unlink=True)
        _remove_unused_mesh(copied_mesh)
        if final_mesh != result_mesh and final_mesh != copied_mesh:
            _remove_unused_mesh(final_mesh)


def apply_rest_pose(context, armature):
    """使用 HoTools 保留形态键烘焙，不使用原生 modifier_apply。

    原物体、原骨架修改器及其设置始终保留；所有网格先在副本上准备，失败时原资产不动。
    只移除已经烘焙的非骨架前缀，原骨架修改器在新的静置姿态下继续负责蒙皮。
    """
    original_mode = armature.mode
    original_selected = list(context.selected_objects)
    original_active = context.view_layer.objects.active
    pose_position = armature.data.pose_position
    prepared = []
    armature_backup = None
    original_meshes = []
    pose_basis = {bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones}
    try:
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        meshes = [obj for obj in armature.children_recursive
                  if obj.type == 'MESH' and obj.name in context.view_layer.objects
                  and bone_utils.object_is_deformed_by_armature(obj, armature)]
        if not meshes:
            raise RuntimeError("没有找到绑定到该骨架的网格对象")
        if armature.data.users > 1:
            raise RuntimeError("骨架数据被多个物体共用，请先创建独立骨架数据再应用姿态")
        armature.data.pose_position = 'POSE'
        context.view_layer.update()
        for obj in meshes:
            result = _prepare_mesh(obj, armature)
            if result is not None:
                prepared.append((obj, *result))

        # 到此所有逐键求值均已成功，才开始固化姿态。保留备份处理原生姿态应用失败。
        armature_backup = armature.data.copy()
        for selected in context.selected_objects:
            selected.select_set(False)
        context.view_layer.objects.active = armature
        armature.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
        result = bpy.ops.pose.armature_apply(selected=False)
        if result != {'FINISHED'}:
            raise RuntimeError(f"应用静置姿态失败：{result}")
        bpy.ops.object.mode_set(mode='OBJECT')
        for obj, mesh, _remove_names in prepared:
            original_meshes.append((obj, obj.data, obj.active_shape_key_index))
            active_index = obj.active_shape_key_index
            obj.data = mesh
            obj.active_shape_key_index = active_index
        # 无需移除或重新添加 Armature，避免追加到栈末尾或重复添加。
        for obj, _mesh, remove_names in prepared:
            for name in remove_names:
                obj.modifiers.remove(obj.modifiers[name])
        context.view_layer.update()
        # 原数据可能仍由另一个实例使用；只释放已无人使用的旧网格。
        old_meshes = {mesh.as_pointer(): mesh for _obj, mesh, _index in original_meshes}
        for mesh in old_meshes.values():
            _remove_unused_mesh(mesh)
        return len(prepared)
    except Exception:
        if context.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj, mesh, active_index in original_meshes:
            obj.data = mesh
            obj.active_shape_key_index = active_index
        if armature_backup is not None:
            changed_data = armature.data
            armature.data = armature_backup
            armature_backup = None
            for name, basis in pose_basis.items():
                armature.pose.bones[name].matrix_basis = basis
            if changed_data.users == 0:
                bpy.data.armatures.remove(changed_data)
        for _obj, mesh, _remove_names in prepared:
            _remove_unused_mesh(mesh)
        raise
    finally:
        armature.data.pose_position = pose_position
        if armature_backup is not None and armature_backup.users == 0:
            bpy.data.armatures.remove(armature_backup)
        for selected in context.selected_objects:
            selected.select_set(False)
        for selected in original_selected:
            selected.select_set(True)
        context.view_layer.objects.active = original_active
        if original_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=original_mode)
