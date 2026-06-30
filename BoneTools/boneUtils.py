import bpy
from mathutils import Vector


class BoneUtils:
    """骨骼命名与对称的通用工具。

    split / fan / twist 共用的「方向后缀解析 + 对称骨获取 + 对称合法性检查」逻辑都
    收在这里，作为唯一实现。这个类不依赖任何插件内部模块（只用 bpy），避免与
    boneSplit / boneTwist / boneFan 之间产生循环导入。
    """

    # 方向后缀的连接符与左右标记。后缀形如 ".L" / "_R" / "-l"。
    _SIDE_SEPARATORS = "._-"
    _SIDE_LETTERS = "LRlr"

    @staticmethod
    def split_side_suffix(name: str) -> tuple[str, str]:
        """把骨名拆成 (主干, 方向后缀)。没有方向后缀时后缀为 ""。

        后缀判定：最后两个字符是「连接符 + L/R（大小写均可）」，如 ".L"、"_r"。
        """
        if (
            len(name) >= 2
            and name[-2] in BoneUtils._SIDE_SEPARATORS
            and name[-1] in BoneUtils._SIDE_LETTERS
        ):
            return name[:-2], name[-2:]
        return name, ""

    @staticmethod
    def has_side_suffix(name: str) -> bool:
        """骨名是否带方向后缀（.L/.R 等）。"""
        return BoneUtils.split_side_suffix(name)[1] != ""

    @staticmethod
    def pair_side_suffix(*names: str) -> str:
        """从一组骨名里取出方向后缀（.L/.R 等）。

        对称生成时，若命名基名是无后缀的中线骨（如 pelvis），左右两侧会拼出同名而
        冲突；此时改用选中骨里带后缀的那根的后缀来区分两侧。多根都带后缀时取第一根
        带后缀的；都没有则返回 ""。
        """
        for name in names:
            suffix = BoneUtils.split_side_suffix(name)[1]
            if suffix:
                return suffix
        return ""

    @staticmethod
    def find_suffixless(bone_names) -> list[str]:
        """返回这批骨名里没有方向后缀的那些（保持原顺序）。

        对称生成需要方向后缀来区分左右：无后缀的中线骨（spine、pelvis 等）翻转后还是
        自己，镜像不会产生对侧骨，对称形同虚设。调用方据此报错退出。
        """
        return [name for name in bone_names if not BoneUtils.has_side_suffix(name)]

    @staticmethod
    def get_mirrored_bone(bone_name: str, armature_data) -> list[str]:
        """返回 [本骨] 或 [本骨, 镜像骨]。

        只有当镜像骨名与本骨不同、且镜像骨在骨架里真实存在时才追加镜像骨；中线骨
        （翻转后同名）只返回自身。armature_data 传骨架数据块（armature.data），用其
        .bones 容器判定存在性。
        """
        names = [bone_name]
        mirrored_name = bpy.utils.flip_name(bone_name)
        bone_container = getattr(armature_data, "bones", armature_data)
        if mirrored_name != bone_name and bone_container.get(mirrored_name):
            names.append(mirrored_name)
        return names

    @staticmethod
    def mirror_pair(armature: bpy.types.Object, pair_names) -> list[str] | None:
        """把一对骨名整体翻转到对侧，返回镜像骨对；无可镜像对象时返回 None。

        只有当镜像骨对真实存在、且是一对不同于原骨对的骨时才返回；否则返回 None
        （比如其中一根是中线骨、镜像骨缺失、或翻转后坍缩/回到原骨对本身）。
        按当前模式取骨判定存在性：EDIT 模式查 edit_bones，否则查 pose.bones（预览常
        在姿态/物体模式触发，此时 edit_bones 为空，不能拿它判定）。
        """
        if armature.mode == "EDIT":
            def _bone_exists(name):
                return armature.data.edit_bones.get(name) is not None
        else:
            def _bone_exists(name):
                return armature.pose.bones.get(name) is not None

        mirrored = []
        for name in pair_names:
            flipped = bpy.utils.flip_name(name)
            if flipped == name or not _bone_exists(flipped):
                return None
            mirrored.append(flipped)

        # 防止退化的翻转坍缩成单根骨，或翻回到原骨对本身（那会重复生成）。
        if len(set(mirrored)) != 2:
            return None
        if set(mirrored) == set(pair_names):
            return None
        return mirrored

    @staticmethod
    def set_object_mode(obj, mode):
        """暴力设置物体模式。

        在 VIEW_3D 区域上临时建一个上下文覆盖再调 mode_set，避免从非 3D 区域
        （如脚本/属性面板）触发时报「context incorrect」。找不到 3D 区域时退回
        直接调用。
        """
        ctx = bpy.context
        view3d_ctx = bpy.context.copy()
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        view3d_ctx = {
                            "area": area,
                            "region": region,
                            "window": bpy.context.window,
                            "screen": bpy.context.screen,
                            "active_object": obj,
                        }
        if "area" in view3d_ctx and "region" in view3d_ctx:
            if hasattr(ctx, "temp_override"):
                with ctx.temp_override(**view3d_ctx):
                    bpy.ops.object.mode_set(mode=mode)
            else:
                bpy.ops.object.mode_set(view3d_ctx, mode=mode)
        else:
            bpy.ops.object.mode_set(mode=mode)

    @staticmethod
    def collect_mesh_objects_for_armature(armature_obj: bpy.types.Object) -> list[bpy.types.Object]:
        """收集所有用骨架修改器绑定到指定骨架的网格物体。"""
        mesh_objs = []
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            for mod in obj.modifiers:
                if mod.type == "ARMATURE" and mod.object == armature_obj:
                    mesh_objs.append(obj)
                    break
        return mesh_objs

    @staticmethod
    def set_temp_mesh_mirror_off(obj: bpy.types.Object) -> dict:
        """临时关闭网格的 X/Y/Z 镜像，返回原始状态以便恢复。

        属性可能挂在物体上，也可能挂在网格数据块上（不同 Blender 版本/场景），
        所以两处都探测。返回值映射 prop_name -> (owner, 原值)。
        """
        mirror_state = {}
        for prop_name in ("use_mesh_mirror_x", "use_mesh_mirror_y", "use_mesh_mirror_z"):
            owner = None
            if hasattr(obj, prop_name):
                owner = obj
            elif getattr(obj, "data", None) is not None and hasattr(obj.data, prop_name):
                owner = obj.data

            if owner is None:
                continue

            mirror_state[prop_name] = (owner, getattr(owner, prop_name))
            setattr(owner, prop_name, False)
        return mirror_state

    @staticmethod
    def restore_mesh_mirror_state(mirror_state: dict) -> None:
        """恢复 set_temp_mesh_mirror_off 保存的网格镜像状态。"""
        for prop_name, (owner, value) in mirror_state.items():
            setattr(owner, prop_name, value)

    @staticmethod
    def set_temp_armature_mirror_off(armature: bpy.types.Object) -> dict:
        """临时关闭骨架的 X 轴镜像（数据块的编辑镜像 + pose 镜像），返回原状态。"""
        mirror_state = {}

        data = getattr(armature, "data", None)
        if data is not None and hasattr(data, "use_mirror_x"):
            mirror_state["data.use_mirror_x"] = (data, data.use_mirror_x)
            data.use_mirror_x = False

        pose = getattr(armature, "pose", None)
        if pose is not None and hasattr(pose, "use_mirror_x"):
            mirror_state["pose.use_mirror_x"] = (pose, pose.use_mirror_x)
            pose.use_mirror_x = False

        return mirror_state

    @staticmethod
    def restore_armature_mirror_state(mirror_state: dict) -> None:
        """恢复 set_temp_armature_mirror_off 保存的骨架镜像状态。"""
        for _, (owner, value) in mirror_state.items():
            owner.use_mirror_x = value

    @staticmethod
    def ensure_bone_collection(armature: bpy.types.Object, collection_name: str):
        """取得指定名字的骨骼集合，没有就新建；集合名为空时返回 None。

        老版本 Blender 没有 armature.data.collections，此时也返回 None。
        """
        if not collection_name:
            return None

        collections = getattr(armature.data, "collections", None)
        if collections is None:
            return None

        collection = collections.get(collection_name)
        if collection is None:
            collection = collections.new(collection_name)
        return collection

    @staticmethod
    def assign_bones_to_collection(
        armature: bpy.types.Object,
        bone_names,
        collection_name: str,
    ) -> None:
        """把若干骨骼移入指定集合：先从原集合移除，再加入目标集合（需 EDIT 模式）。"""
        collection = BoneUtils.ensure_bone_collection(armature, collection_name)
        if collection is None:
            return

        edit_bones = armature.data.edit_bones
        for bone_name in bone_names:
            bone = edit_bones.get(bone_name)
            if bone is None:
                continue
            for old_collection in list(bone.collections):
                old_collection.unassign(bone)
            collection.assign(bone)

    @staticmethod
    def selected_bone_names(context, armature: bpy.types.Object) -> list[str]:
        """返回当前选中骨骼的名字列表。

        POSE 模式优先取 selected_pose_bones_from_active_object（多骨架场景下只拿活动
        骨架的选择），取不到再退回 selected_pose_bones；EDIT 模式遍历 edit_bones 的
        选中位。其它模式返回空列表。
        """
        if armature.mode == "POSE":
            pose_bones = getattr(context, "selected_pose_bones_from_active_object", None)
            if pose_bones is None:
                pose_bones = context.selected_pose_bones or []
            return [bone.name for bone in pose_bones if getattr(bone, "name", None)]
        if armature.mode == "EDIT":
            return [bone.name for bone in armature.data.edit_bones if bone.select]
        return []

    @staticmethod
    def selected_bones(context, armature: bpy.types.Object):
        """返回当前选中的骨骼对象（而非名字）：POSE 取 pose_bone、EDIT 取 edit_bone。

        与 selected_bone_names 同样的取选规则；POSE 模式过滤掉没有底层 bone 的项。
        其它模式返回空列表。
        """
        if armature.mode == "POSE":
            pose_bones = getattr(context, "selected_pose_bones_from_active_object", None)
            if pose_bones is None:
                pose_bones = context.selected_pose_bones or []
            return [pb for pb in pose_bones if getattr(pb, "bone", None) is not None]
        if armature.mode == "EDIT":
            return [bone for bone in armature.data.edit_bones if bone.select]
        return []

    @staticmethod
    def bone_head_tail(bone):
        """取骨骼的 (head, tail) 世界/编辑坐标副本，兼容 edit_bone 与 pose_bone。

        edit_bone 直接有 head/tail；pose_bone 用其 matrix 与 rest 长度推算尾端。
        两者都不匹配时抛异常。
        """
        if hasattr(bone, "head") and hasattr(bone, "tail"):
            return bone.head.copy(), bone.tail.copy()
        if hasattr(bone, "bone") and hasattr(bone, "matrix"):
            rest_bone = bone.bone
            head = bone.matrix.translation.copy()
            tail = bone.matrix @ Vector((0.0, rest_bone.length, 0.0))
            return head, tail
        raise Exception("不支持的骨骼类型")
