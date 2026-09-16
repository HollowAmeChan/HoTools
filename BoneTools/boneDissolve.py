import bpy
import numpy as np
import math
from bpy.types import Operator
from bpy.props import BoolProperty, EnumProperty, IntProperty, FloatProperty, StringProperty

from Utils import bone_utils,bone_selection

# 简单融并的解析模式
MODE_AUTO = "AUTO"
MODE_SPECIFY = "SPECIFY"
MODE_LABELS = {MODE_AUTO: "自动递归", MODE_SPECIFY: "指定目标"}


def reg_props():
    return


def ureg_props():
    return

class DissolveBoneCore:
    @staticmethod
    def _ensure_object_visible(obj: bpy.types.Object):
        """临时解除物体隐藏，返回可恢复的隐藏状态。"""
        state = {
            "hide_viewport": obj.hide_viewport,
            "hide_get": obj.hide_get(),
        }

        if state["hide_viewport"]:
            obj.hide_viewport = False
        if state["hide_get"]:
            obj.hide_set(False)

        if state["hide_viewport"] or state["hide_get"]:
            bpy.context.view_layer.update()

        return state

    @staticmethod
    def _restore_object_visibility(obj: bpy.types.Object, state):
        if state["hide_get"]:
            obj.hide_set(True)
        if state["hide_viewport"]:
            obj.hide_viewport = True

        if state["hide_viewport"] or state["hide_get"]:
            bpy.context.view_layer.update()

    @staticmethod
    def resolve_bone_chain(edit_bones, bns):
        """校验选中骨骼是否为单条父子链，并返回从根到末端的有序骨名。"""
        bn_set = set(bns)
        missing = [bn for bn in bns if edit_bones.get(bn) is None]
        if missing:
            return [], f"找不到选中的骨骼: {missing}"

        roots = []
        for bn in bns:
            bone = edit_bones[bn]
            if bone.parent is None or bone.parent.name not in bn_set:
                roots.append(bn)

        if len(roots) != 1:
            return [], f"必须只选择一条连续骨链，当前找到 {len(roots)} 个最高父级骨骼: {roots}"

        chain = []
        current = edit_bones[roots[0]]
        while current and current.name in bn_set:
            chain.append(current.name)

            child_in_set = [child for child in current.children if child.name in bn_set]
            if len(child_in_set) > 1:
                names = [child.name for child in child_in_set]
                return [], f"骨链在 {current.name} 处分叉，子骨骼: {names}"

            current = child_in_set[0] if child_in_set else None

        if len(chain) != len(bn_set):
            disconnected = [bn for bn in bns if bn not in chain]
            return [], f"选中骨骼不是一条连续父子链，未连接骨骼: {disconnected}"

        return chain, None

    # ── 简单融并的“权重转移映射计划”（纯计算，不改动任何数据）────────────────
    @staticmethod
    def _drop_mirrored(deleting_order: list[str], mirrored: dict[str, str]) -> None:
        """镜像侧不可用时撤回镜像追加的骨骼（显式选中的骨骼保留）。"""
        for name in [item for item in deleting_order if item in mirrored]:
            deleting_order.remove(name)
            mirrored.pop(name, None)

    @staticmethod
    def build_transfer_plan(parent_of, selected, *, mode=MODE_AUTO, target="",
                            mirror=False, bone_names=None, flip_name=None) -> dict:
        """
        生成融并计划：递归解析每根选中骨骼最终的权重去向，并校验可执行性。

        parent_of：{骨名: 父级骨名}，缺失父级视为根骨，只需覆盖待处理骨骼；
        bone_names：骨架内全部骨名（校验用），缺省取 parent_of 的键集合；
        flip_name：镜像用的翻转名称函数，调用方传 bpy.utils.flip_name。

        计划字段：
          mode / target    ：解析模式与指定目标
          deleting         ：待删骨骼，按深度从深到浅
          steps            ：骨名 → {final_target, parent, new_parent, depth}
          weight_groups    ：最终目标骨名 → 源骨名元组（权重合并映射）
          constraint_map   ：被删骨名 → 最终目标骨名（约束改写映射）
          errors / warnings：校验结果，errors 非空时不允许执行
        """
        known = set(bone_names) if bone_names is not None else set(parent_of)
        target = (target or "").strip() or None
        errors: list[str] = []
        warnings: list[str] = []

        # 展开待删骨骼集合：显式选中的骨骼优先，镜像骨随后追加
        deleting_order: list[str] = []
        for name in selected:
            if name and name not in deleting_order:
                deleting_order.append(name)
        mirrored: dict[str, str] = {}
        if mirror:
            if flip_name is None:
                errors.append("镜像处理缺少骨骼翻转名称函数")
            else:
                for name in tuple(deleting_order):
                    flipped = flip_name(name)
                    if flipped == name:
                        warnings.append(f"「{name}」是中线骨，跳过镜像处理")
                    elif flipped not in known:
                        warnings.append(f"镜像骨「{flipped}」不存在，跳过镜像处理")
                    elif flipped in deleting_order:
                        continue
                    else:
                        deleting_order.append(flipped)
                        mirrored[flipped] = name

        deleting = set(deleting_order)

        # 校验模式与目标骨骼
        if mode not in (MODE_AUTO, MODE_SPECIFY):
            errors.append(f"未知的解析模式: {mode}")

        mirror_target = None
        if mode == MODE_SPECIFY:
            if not target:
                errors.append("目标骨骼名称不能为空")
            elif target not in known:
                errors.append(f"目标骨骼「{target}」不存在于该骨架中")
            elif target in deleting:
                errors.append(f"目标骨骼「{target}」也在融并范围内，无法作为最终目标")
            elif mirror and mirrored and flip_name is not None:
                flipped_target = flip_name(target)
                if flipped_target in deleting:
                    warnings.append(f"镜像目标骨「{flipped_target}」也在融并范围内，跳过镜像处理")
                    DissolveBoneCore._drop_mirrored(deleting_order, mirrored)
                    deleting = set(deleting_order)
                elif flipped_target not in known:
                    warnings.append(f"镜像目标骨「{flipped_target}」不存在，跳过镜像处理")
                    DissolveBoneCore._drop_mirrored(deleting_order, mirrored)
                    deleting = set(deleting_order)
                else:
                    mirror_target = flipped_target

        if not deleting_order:
            errors.append("至少需要选择一根骨骼")

        missing = [name for name in deleting_order if name not in known]
        if missing:
            errors.append(f"找不到选中的骨骼: {missing}")

        plan = {
            "mode": mode,
            "target": target,
            "deleting": tuple(deleting_order),
            "steps": {},
            "weight_groups": {},
            "constraint_map": {},
            "errors": errors,
            "warnings": warnings,
        }
        if errors:
            return plan

        # ── 递归解析：沿父级向上爬，直到落在待删集合之外 ──
        def nearest_surviving_ancestor(name: str):
            limit = len(known) + 1
            current = parent_of.get(name)
            steps = 0
            while current is not None and current in deleting:
                steps += 1
                if steps > limit:  # 理论上不可能出现环，仅作保护
                    return None
                current = parent_of.get(current)
            return current

        def ancestor_depth(name: str) -> int:
            """到根骨的层数，仅按传入的父子关系追索（缺失的祖先视为根骨）。"""
            limit = len(known) + 1
            depth = 0
            current = parent_of.get(name)
            while current is not None:
                depth += 1
                if depth > limit:
                    break
                current = parent_of.get(current)
            return depth

        resolved: dict[str, str | None] = {}
        orphaned: list[str] = []
        for name in deleting_order:
            if mode == MODE_SPECIFY:
                final = mirror_target if name in mirrored else target
            else:
                final = nearest_surviving_ancestor(name)
                if final is None:
                    orphaned.append(name)
            resolved[name] = final

        if orphaned:
            plan["errors"].append(
                "骨骼 " + "、".join(f"「{name}」" for name in orphaned)
                + " 的父级都在融并范围内，没有可用的存活父级；请改用「指定目标」模式"
            )
            return plan

        # ── 组装计划表：深 → 浅，保证父级排在子级之前 ──
        order = sorted(
            range(len(deleting_order)),
            key=lambda index: (-ancestor_depth(deleting_order[index]), index),
        )
        deleting_sorted = [deleting_order[index] for index in order]

        weight_groups: dict[str, list[str]] = {}
        for name in deleting_sorted:
            final = resolved[name]
            plan["steps"][name] = {
                "final_target": final,
                "parent": parent_of.get(name),
                "new_parent": nearest_surviving_ancestor(name),
                "depth": ancestor_depth(name),
            }
            if final is None:
                continue
            weight_groups.setdefault(final, []).append(name)
            plan["constraint_map"][name] = final

        plan["deleting"] = tuple(deleting_sorted)
        plan["weight_groups"] = {key: tuple(value) for key, value in weight_groups.items()}
        return plan

    @staticmethod
    def addNewBone(armature:bpy.types.Object,bns)->str:
        """添加一个新的骨骼（已经提前确认可以添加）"""
        #强制进入骨架编辑模式
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature,'EDIT')

        edit_bones = armature.data.edit_bones
        # 按父子链首尾决定新骨段，不再按世界轴高低推断。
        root_bone = edit_bones.get(bns[0])
        tail_bone = edit_bones.get(bns[-1])
        if root_bone is None or tail_bone is None:
            raise Exception("融并骨链数据无效")

        #添加骨骼
        new_name = bns[0]+"_HoDissolved"
        new_bone = edit_bones.new(new_name)
        new_name = new_bone.name

        head = root_bone.head.copy()
        tail = tail_bone.tail.copy()
        parent = root_bone.parent

        # 收集所有原本连接到 bottom_bone 的子骨骼
        childrens = [b for b in edit_bones if b.parent and b.parent.name in bns and b.name not in bns]

        # 设置新骨骼的属性，以及修改原本最低子级骨骼的父级
        new_bone.head = head
        new_bone.tail = tail
        new_bone.parent = parent
        new_bone.roll = root_bone.roll#取最浅根骨的扭转
        bone_utils.inherit_bone_collections(root_bone, new_bone)

        for child in childrens:
            child.parent = new_bone
            continue

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature,'OBJECT')
        if was_hidden:
            armature.hide_set(True)
        
        return new_name
    
    @staticmethod
    def obj_bone_dissolve(bns,tmp_bn,obj:bpy.types.Object):
        """处理单物体的权重融并"""
        visibility_state = DissolveBoneCore._ensure_object_visible(obj)
        old_active = bpy.context.view_layer.objects.active

        try:
            #切换模式
            if obj.visible_get():
                bpy.context.view_layer.objects.active = obj
                bone_utils.set_object_mode(obj,'OBJECT')
            else:
                return False

            #新建/清空目标组
            if obj.vertex_groups.get(tmp_bn):
                obj.vertex_groups.remove(obj.vertex_groups.get(tmp_bn))
            new_vg = obj.vertex_groups.new(name=tmp_bn)

            verts = obj.data.vertices
            N = len(verts)
            M = len(bns)

            #np矩阵处理
            W = np.zeros((N, M), dtype=float)
            P = np.zeros((N, M), dtype=bool)

            for j, group_name in enumerate(bns):
                vg = obj.vertex_groups.get(group_name)
                if not vg:
                    continue
                # 对于每个顶点，尝试读取权重
                for i, v in enumerate(verts):
                    try:
                        w = vg.weight(i)
                        # 只要没抛异常，就算“显式归属”，即便 w==0
                        P[i, j] = True
                    except RuntimeError:
                        w = 0.0
                    W[i, j] = w

            # 叠加和掩码
            merged = W.sum(axis=1)            # 合并后权重 (N,)
            has_explicit = P.any(axis=1)      # 哪些顶点显式属于至少一个旧组

            # 批量写入：只写那些 has_explicit 的顶点，写入它们的 merged 权重
            idxs = np.nonzero(has_explicit)[0]
            weights = merged[has_explicit]
            for i, w in zip(idxs, weights):
                new_vg.add([int(i)], float(w), 'REPLACE')

            # 删除旧组
            for old in bns:
                vg = obj.vertex_groups.get(old)
                if vg:
                    obj.vertex_groups.remove(vg)
        finally:
            if old_active:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass
            DissolveBoneCore._restore_object_visibility(obj, visibility_state)

        return True
    

    @staticmethod
    def removeOldBones(armature:bpy.types.Object,bns,root_bn,new_bn):
        """删除旧骨骼并改新骨骼名"""
        #强制进入骨架编辑模式
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()  
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature,'EDIT')
        edit_bones = armature.data.edit_bones
        for bn in bns:
            edit_bones.remove(edit_bones.get(bn))
        #改新骨骼名称为原本根骨名称
        if root_bn and new_bn:
            edit_bones.get(new_bn).name = root_bn

        #刷新并回到物体模式
        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature,'OBJECT')
           
        if was_hidden:
            armature.hide_set(True)

        return

class OP_DissolveBoneWithWeight(Operator):
    bl_idname = "ho.dissolvebone_withweight"
    bl_label = "融并骨骼与权重"
    bl_description = """
    将选中的连续父子骨链融并成一根骨骼，并同步合并权重。
    使用方式:在姿态模式或编辑模式选择两根以上连续骨骼，或在权重绘制时使用当前选中的骨骼。
            选中骨骼必须是一条单独父子链；如果出现多个最高父级、断链或分叉，会取消并提示错误。
            新骨从最浅父级骨骼的 head 延伸到最深子级骨骼的 tail，roll 使用最浅父级骨骼。
            所有被融并骨骼的顶点组权重会相加到新骨顶点组，然后删除旧顶点组和旧骨骼。
            隐藏网格会临时显示后处理并恢复隐藏；不在当前视图层的网格会跳过。"""
    bl_options = {'REGISTER', 'UNDO'}

    only_selected:BoolProperty(name="仅选择的物体",description="未被选中的物体将保留权重，但是由于骨骼已经消失将不再受到控制", default=False) # type: ignore

    @classmethod
    def poll(cls, context):
        """保证选择的物体中找得到一个骨架并且选择了至少一个骨,判断逻辑与细分完全一致"""
        
        obj = context.active_object

        # 选择物体不是mesh物体/骨架，跳过
        if not obj or obj.type not in {'MESH', 'ARMATURE'}:
            return False

        #选择骨架时,没有选中骨骼，跳过
        if obj.type == 'ARMATURE':
            if obj.mode in {'POSE', 'EDIT'}:
                return bool(bone_utils.selected_bone_names(context, obj))
            else:
                return False
        
        #选择物体时（仅考虑多选了骨架并且在权重绘制模式的情况）
        else :            
            armature = bone_utils.find_deforming_armature_for_object(obj)
            #没找到骨架跳过
            if not armature:
                return False
            #活动组是骨架的骨权重时，说明有一个骨被选中了
            active_group = obj.vertex_groups.active
            if not active_group:
                return False
            for bone in armature.data.bones:
                if active_group.name == bone.name:
                    return True
            return False

    def execute(self, context):
        original_active = context.active_object
        original_mode = original_active.mode
        #得到待处理的对象
        armature_obj:bpy.types.Object = None #处理的骨架
        mesh_objs :list[bpy.types.Object]= [] #要处理的子级物体
        bones:list[str] = [] #选择的骨骼
            
        if original_active.type == 'ARMATURE':
            armature_obj = original_active
            bones = bone_utils.selected_bone_names(context, armature_obj)
            mesh_objs = bone_utils.collect_mesh_objects_for_armature(armature_obj)

        elif original_active.type == 'MESH':
            mesh_obj = original_active
            armature_obj = bone_utils.find_deforming_armature_for_object(mesh_obj)
            if armature_obj is None:
                self.report({'ERROR'}, "无法唯一确定网格的形变骨架")
                return {'CANCELLED'}
            #直接拿到选择的骨（必定权重绘制模式）
            bones = bone_utils.selected_bone_names(context, armature_obj)

            mesh_objs = bone_utils.collect_mesh_objects_for_armature(armature_obj)

        else:
            self.report({'ERROR'}, "不支持的对象")
            return {'CANCELLED'}
        #清洗处理列表
        if self.only_selected:
            tmp = []
            obj:bpy.types.Object
            for obj in mesh_objs:
                if obj.select_get():
                    tmp.append(obj)
            mesh_objs = tmp

        #检查选择的骨骼是否合乎融并的需求
        if len(bones)==1:
            self.report({'ERROR'}, "只有一个选中的骨骼")
            return {'CANCELLED'}
        bpy.context.view_layer.objects.active = armature_obj
        bone_utils.set_object_mode(armature_obj,'EDIT')

        edit_bones = armature_obj.data.edit_bones
        chain_bones, chain_error = DissolveBoneCore.resolve_bone_chain(edit_bones, bones)
        if chain_error:
            self.report({'ERROR'}, chain_error)
            return {'CANCELLED'}

        root = chain_bones[0]

        #创建新的骨骼
        new_bone_name = DissolveBoneCore.addNewBone(armature_obj,chain_bones)
        #逐物体合并骨骼权重
        for obj in mesh_objs:
            DissolveBoneCore.obj_bone_dissolve(chain_bones,new_bone_name,obj)
        #移除骨架中的原骨骼
        DissolveBoneCore.removeOldBones(armature_obj,chain_bones,root,new_bone_name)

        #还原原本的视图状态
        context.view_layer.objects.active = original_active
        bone_utils.set_object_mode(original_active,mode=original_mode)
        if original_mode == 'WEIGHT_PAINT':
            armature_obj.select_set(True)
            bpy.context.view_layer.objects.active = armature_obj
            bone_utils.set_object_mode(armature_obj,'POSE')
            original_active.select_set(True)
            bpy.context.view_layer.objects.active = original_active
            bone_utils.set_object_mode(original_active,'WEIGHT_PAINT')
        self.report({'INFO'},"融并成功")

    
        return {'FINISHED'}
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def draw(self, context):
        layout = self.layout
        layout.prop(self,"only_selected")


class SimpleDissolveCore:
    """简单融并的核心算法：先生成权重转移映射计划，再按计划执行，均与 UI 解耦。"""

    # ── 计划阶段：只读，不修改任何数据 ─────────────────────────────────────
    @staticmethod
    def bone_context(armature: bpy.types.Object) -> tuple[dict[str, str | None], set[str]]:
        """返回当前模式下的 {骨名: 父级骨名} 与骨名集合（编辑模式读 edit_bones）。"""
        bones = armature.data.edit_bones if armature.mode == 'EDIT' else armature.data.bones
        parent_of: dict[str, str | None] = {}
        for bone in bones:
            parent = bone.parent
            parent_of[bone.name] = parent.name if parent else None
        return parent_of, set(parent_of)

    @staticmethod
    def build_plan(armature: bpy.types.Object, selected, *, mode=MODE_AUTO,
                   target="", mirror=False) -> dict:
        """按当前骨架与选中骨骼生成权重转移映射计划。"""
        parent_of, known = SimpleDissolveCore.bone_context(armature)
        return DissolveBoneCore.build_transfer_plan(
            parent_of,
            selected,
            mode=mode,
            target=target,
            mirror=mirror,
            bone_names=known,
            flip_name=bpy.utils.flip_name,
        )

    @staticmethod
    def plan_mapping_lines(plan: dict) -> list[str]:
        """权重映射文本，例如 ``A ← B、C``（每个最终目标一行）。"""
        return [
            f"{target} ← " + "、".join(src_bns)
            for target, src_bns in plan["weight_groups"].items()
        ]

    @staticmethod
    def plan_report_lines(plan: dict) -> list[str]:
        """计划阶段的报告文本（执行前打印，保证“先计划后动手”可追溯）。"""
        mode = plan["mode"]
        lines = [
            f"  模式：{MODE_LABELS.get(mode, mode)}"
            + (f"「{plan['target']}」" if mode == MODE_SPECIFY and plan["target"] else ""),
            f"  待融并骨骼（深→浅）：{'、'.join(plan['deleting']) or '（无）'}",
            "  权重映射：",
        ]
        mapping = SimpleDissolveCore.plan_mapping_lines(plan)
        if mapping:
            lines.extend(f"    {line}" for line in mapping)
        else:
            lines.append("    （无）")
        lines.append("  层级调整（存活子骨骼挂到链上最近存活祖先）：")
        for name in plan["deleting"]:
            new_parent = plan["steps"].get(name, {}).get("new_parent")
            lines.append(f"    {name} 的子骨骼 → {new_parent or '（无，成为根骨）'}")
        if plan["warnings"]:
            lines.append("  警告：" + "；".join(plan["warnings"]))
        if plan["errors"]:
            lines.append("  错误：" + "；".join(plan["errors"]))
        return lines

    # ── 执行阶段：权重 ─────────────────────────────────────────────────────
    @staticmethod
    def merge_weight_groups(obj: bpy.types.Object, weight_groups) -> bool:
        """
        按计划把多个源骨骼顶点组并入各自的目标组：
        每个网格只扫一趟顶点，把所有源组权重（含目标组已有权重）求和后统一 clamp 到 1.0，
        最后再删除全部源组。与逐对合并的数值结果一致，但不受处理顺序影响。
        物体不可见时跳过并返回 False；正常处理返回 True。
        """
        visibility_state = DissolveBoneCore._ensure_object_visible(obj)
        old_active = bpy.context.view_layer.objects.active
        try:
            if not obj.visible_get():
                return False
            bpy.context.view_layer.objects.active = obj
            bone_utils.set_object_mode(obj, 'OBJECT')

            groups = obj.vertex_groups
            # 顶点组索引 → 最终目标骨名；目标组自身的已有权重也计入求和
            owner_of: dict[int, str] = {}
            targets: list[str] = []
            for final_bn, src_bns in weight_groups.items():
                present = [groups[src_bn] for src_bn in src_bns if groups.get(src_bn)]
                if not present:
                    continue
                targets.append(final_bn)
                target_vg = groups.get(final_bn)
                if target_vg:
                    owner_of[target_vg.index] = final_bn
                for src_vg in present:
                    owner_of[src_vg.index] = final_bn

            if not targets:
                return True  # 无源组，视为已处理

            verts = obj.data.vertices
            totals = {final_bn: np.zeros(len(verts), dtype=float) for final_bn in targets}
            touched = {final_bn: np.zeros(len(verts), dtype=bool) for final_bn in targets}

            for i, vert in enumerate(verts):
                for member in vert.groups:
                    final_bn = owner_of.get(member.group)
                    if final_bn is None:
                        continue
                    totals[final_bn][i] += member.weight
                    touched[final_bn][i] = True

            # 先写入目标组，再删除源组：避免中途删除造成顶点组索引失效
            for final_bn in targets:
                target_vg = groups.get(final_bn) or groups.new(name=final_bn)
                for i in np.nonzero(touched[final_bn])[0]:
                    target_vg.add([int(i)], float(min(1.0, totals[final_bn][i])), 'REPLACE')

            for src_bns in weight_groups.values():
                for src_bn in src_bns:
                    src_vg = groups.get(src_bn)
                    if src_vg:
                        groups.remove(src_vg)
        finally:
            if old_active:
                try:
                    bpy.context.view_layer.objects.active = old_active
                except Exception:
                    pass
            DissolveBoneCore._restore_object_visibility(obj, visibility_state)
        return True

    # ── 执行阶段：约束 ─────────────────────────────────────────────────────
    @staticmethod
    def apply_constraint_plan(armature: bpy.types.Object,
                              constraint_map: dict[str, str]) -> list[str]:
        """
        按计划改写约束引用：存活骨骼上 subtarget 指向被删骨骼的约束改为其最终目标。
        返回被修改的约束描述列表（每项一行）。骨架需处于可访问 pose 数据的状态。
        """
        changed: list[str] = []
        pose = getattr(armature, 'pose', None)
        if not pose:
            return changed
        for pose_bone in pose.bones:
            if pose_bone.name in constraint_map:
                continue  # 该骨骼本身会被删除，其约束随之消失
            for con in pose_bone.constraints:
                if getattr(con, 'target', None) is not armature:
                    continue
                src_bn = getattr(con, 'subtarget', None)
                if src_bn in constraint_map:
                    final_bn = constraint_map[src_bn]
                    con.subtarget = final_bn
                    changed.append(
                        f"    {pose_bone.name} → 约束「{con.name}」: subtarget {src_bn} → {final_bn}"
                    )
        return changed

    # ── 执行阶段：删除骨骼 ─────────────────────────────────────────────────
    @staticmethod
    def delete_bones(armature: bpy.types.Object, plan: dict) -> list[str]:
        """
        按计划（深→浅）删除骨骼：存活子骨骼挂到链上最近的存活祖先并断开连接，
        然后删除骨骼本身。返回逐条执行记录。
        """
        lines: list[str] = []
        was_hidden = armature.hide_viewport
        if was_hidden:
            armature.hide_set(False)
            bpy.context.view_layer.update()
        armature.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature, 'EDIT')

        edit_bones = armature.data.edit_bones
        deleting = set(plan["deleting"])
        for src_bn in plan["deleting"]:
            bone = edit_bones.get(src_bn)
            if not bone:
                lines.append(f"    {src_bn}: 删除失败（未找到骨骼）")
                continue
            new_parent_name = plan["steps"].get(src_bn, {}).get("new_parent")
            for child in list(bone.children):
                if child.name in deleting:
                    continue  # 待删子骨骼不需要改挂
                child.parent = edit_bones.get(new_parent_name) if new_parent_name else None
                child.use_connect = False
                lines.append(
                    f"    子骨骼 {child.name} → 新父级 "
                    f"{new_parent_name or '（无，成为根骨）'}"
                )
            edit_bones.remove(bone)
            lines.append(f"    删除骨骼 {src_bn}")

        bpy.context.view_layer.objects.active = armature
        bone_utils.set_object_mode(armature, 'OBJECT')
        if was_hidden:
            armature.hide_set(True)
        return lines


class OP_SimpleDissolveBone(Operator):
    bl_idname = "ho.simple_dissolve_bone"
    bl_label = "简单融并"
    bl_description = (
        "把选中的一根或多根骨骼融并到目标骨骼：先生成权重转移映射计划，再按计划合并权重、"
        "改写约束引用并删除骨骼。\n"
        "自动递归：每根选中骨骼沿父级向上递归，权重并入最近的未选中父级，"
        "同一批选择里的多条骨链会各自落到各自的存活父级。\n"
        "指定目标：所有选中骨骼的权重并入同一根目标骨骼（单选时默认，自动填入父级名）。\n"
        "被删骨骼的存活子骨骼挂到链上最近的存活祖先并断开连接；镜像处理会同时处理翻转名骨骼。\n"
        "姿态模式或骨架编辑模式均可触发。"
    )
    bl_options = {'REGISTER', 'UNDO'}

    resolve_mode: EnumProperty(
        name="解析模式",
        description="决定选中骨骼的权重最终并入哪根骨骼",
        items=[
            (MODE_AUTO, "自动递归",
             "每根选中骨骼沿父级向上递归，权重并入最近的未选中父级"),
            (MODE_SPECIFY, "指定目标",
             "所有选中骨骼的权重并入“目标骨骼”指定的同一根骨骼"),
        ],
        default=MODE_SPECIFY,
    )  # type: ignore

    target_bone: StringProperty(
        name="目标骨骼",
        description="“指定目标”模式下权重和约束引用的最终去向（单选时默认填入父级骨骼名）",
        default="",
    )  # type: ignore

    process_weights: BoolProperty(
        name="处理权重",
        description="将被删除骨骼的顶点组权重叠加到目标骨骼的顶点组",
        default=True,
    )  # type: ignore

    only_selected_objects: BoolProperty(
        name="仅选中物体",
        description="处理权重时只遍历当前选中的网格物体",
        default=False,
    )  # type: ignore

    mirror: BoolProperty(
        name="镜像处理",
        description="同时对翻转名（bpy.utils.flip_name）对应的镜像骨骼执行相同操作；"
                    "“指定目标”模式下目标骨骼也自动翻转",
        default=False,
    )  # type: ignore

    transfer_constraints: BoolProperty(
        name="转移约束引用",
        description="扫描骨架内全部骨骼的约束，将 subtarget 为被删骨骼的改为其最终目标",
        default=True,
    )  # type: ignore

    # ── 选中至少一根骨时可触发 ──────────────────────────────────────────────
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return False
        if obj.mode == 'EDIT':
            return len(bone_selection.selected_edit_bones(context, obj)) >= 1
        if obj.mode == 'POSE':
            return len(bone_selection.selected_pose_bones(context, obj)) >= 1
        return False

    # ── 打开对话框前选定默认模式与目标 ──────────────────────────────────────
    def invoke(self, context, event):
        obj = context.active_object
        parent_of: dict[str, str | None] = {}
        selected: list[str] = []
        if obj is not None and obj.type == 'ARMATURE':
            parent_of, known = SimpleDissolveCore.bone_context(obj)
            selected = [bn for bn in bone_utils.selected_bone_names(context, obj) if bn in known]
        if len(selected) == 1:
            # 单选保持原行为：默认“指定目标”，并预填父级名
            self.resolve_mode = MODE_SPECIFY
            self.target_bone = parent_of.get(selected[0]) or ""
        else:
            # 多选默认递归，让每根骨骼各回各家
            self.resolve_mode = MODE_AUTO
            self.target_bone = ""
        return context.window_manager.invoke_props_dialog(self, width=380)

    # ── 对话框布局：先看计划，再决定执行 ────────────────────────────────────
    def draw(self, context):
        layout = self.layout
        layout.prop(self, "resolve_mode", expand=True)

        col = layout.column(align=True)
        sub = col.column()
        sub.enabled = self.resolve_mode == MODE_SPECIFY
        sub.prop(self, "target_bone")

        col.separator()
        col.prop(self, "process_weights")
        sub = col.column()
        sub.enabled = self.process_weights
        sub.prop(self, "only_selected_objects")
        col.separator()
        col.prop(self, "mirror")
        col.prop(self, "transfer_constraints")

        box = layout.box()
        box.label(text="权重转移映射计划", icon='INFO')
        plan = self._preview_plan(context)
        if plan is None:
            box.label(text="无法读取当前骨架的选中骨骼", icon='CANCEL')
            return
        for error in plan["errors"]:
            box.label(text=error, icon='CANCEL')
        for warning in plan["warnings"]:
            box.label(text=warning, icon='INFO')
        if plan["errors"]:
            return
        box.label(text=f"待融并 {len(plan['deleting'])} 根骨骼，"
                       f"并入 {len(plan['weight_groups'])} 个目标组")
        mapping = SimpleDissolveCore.plan_mapping_lines(plan)
        for line in mapping[:8]:
            box.label(text=line)
        if len(mapping) > 8:
            box.label(text=f"… 另有 {len(mapping) - 8} 组，详见控制台")

    def _preview_plan(self, context) -> dict | None:
        """对话框内实时生成计划；draw 阶段只读，任何异常都不应打断界面。"""
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            return None
        try:
            selected = bone_utils.selected_bone_names(context, obj)
            return SimpleDissolveCore.build_plan(
                obj,
                selected,
                mode=self.resolve_mode,
                target=self.target_bone,
                mirror=self.mirror,
            )
        except Exception:
            return None

    # ── 执行：先出计划，再按计划动手 ────────────────────────────────────────
    def execute(self, context):
        armature_obj: bpy.types.Object = context.active_object
        original_mode = armature_obj.mode

        # ── 阶段一：取选中骨骼（切模式前读取）并生成最终权重转移映射计划 ──
        selected = bone_utils.selected_bone_names(context, armature_obj)
        plan = SimpleDissolveCore.build_plan(
            armature_obj,
            selected,
            mode=self.resolve_mode,
            target=self.target_bone,
            mirror=self.mirror,
        )

        print("=" * 60)
        print("  简单融并 · 权重转移映射计划")
        print("=" * 60)
        for line in SimpleDissolveCore.plan_report_lines(plan):
            print(line)
        print("=" * 60)

        for warning in plan["warnings"]:
            self.report({'WARNING'}, warning)
        if plan["errors"]:
            # 计划不合法：不动任何数据
            for error in plan["errors"]:
                print(f"  [取消] {error}")
            self.report({'ERROR'}, plan["errors"][0])
            return {'CANCELLED'}

        # ── 阶段二：按计划执行 ──
        bpy.context.view_layer.objects.active = armature_obj
        bone_utils.set_object_mode(armature_obj, 'OBJECT')

        all_mesh = bone_utils.collect_mesh_objects_for_armature(armature_obj)
        mesh_objs = [o for o in all_mesh if o.select_get()] if self.only_selected_objects else all_mesh

        report_lines: list[str] = []
        weight_objs = 0
        if self.process_weights:
            weight_objs = sum(
                1 for obj in mesh_objs
                if SimpleDissolveCore.merge_weight_groups(obj, plan["weight_groups"])
            )
            report_lines.append(
                f"  权重：{weight_objs} 个网格物体并入 "
                f"{len(plan['weight_groups'])} 个目标组"
            )

        constraint_count = 0
        if self.transfer_constraints:
            bpy.context.view_layer.objects.active = armature_obj
            bone_utils.set_object_mode(armature_obj, 'OBJECT')
            changed = SimpleDissolveCore.apply_constraint_plan(armature_obj, plan["constraint_map"])
            constraint_count = len(changed)
            report_lines.append(f"  约束：转移 {constraint_count} 处" if changed else "  约束：无引用被删骨骼的约束")
            report_lines.extend(changed)

        report_lines.append("  骨骼删除与层级调整：")
        report_lines.extend(SimpleDissolveCore.delete_bones(armature_obj, plan))

        # ── 还原模式 ──
        try:
            bpy.context.view_layer.objects.active = armature_obj
            bone_utils.set_object_mode(armature_obj, original_mode)
        except Exception:
            pass

        # ── 控制台执行报告 ──
        print("=" * 60)
        print("  简单融并 · 执行结果")
        print("=" * 60)
        for line in report_lines:
            print(line)
        print("=" * 60)

        # ── INFO 摘要 ──
        summary = (
            f"简单融并完成 | 删除骨骼: {len(plan['deleting'])} | "
            f"权重目标: {len(plan['weight_groups'])} | "
            f"权重物体: {weight_objs} | "
            f"约束转移: {constraint_count}"
        )
        self.report({'INFO'}, summary)
        return {'FINISHED'}


cls = [
    OP_DissolveBoneWithWeight,
    OP_SimpleDissolveBone,
]

def register():
    for i in cls:
        bpy.utils.register_class(i)
    reg_props()


def unregister():
    for i in cls:
        bpy.utils.unregister_class(i)
    ureg_props()
