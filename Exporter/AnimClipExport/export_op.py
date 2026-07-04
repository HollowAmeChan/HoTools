# -*- coding: utf-8 -*-
# Unity .anim 导出算子：属性勾选 UI + 导出执行。

import os
import bpy
from bpy.types import Operator, PropertyGroup
from bpy_extras.io_utils import ExportHelper
from bpy.props import (
    BoolProperty, FloatProperty, StringProperty,
    CollectionProperty, IntProperty,
)

from . import scan, interpolation, anim_yaml


# ── PropertyGroup：每条候选轨道 ──────────────────────────────

class HO_PG_AnimTrackItem(PropertyGroup):
    """勾选列表里的一条属性动画轨道。"""
    enabled:     BoolProperty(name="导出", default=True)           # type: ignore
    obj_name:    StringProperty()                                   # type: ignore
    data_path:   StringProperty()                                   # type: ignore
    array_index: IntProperty()                                      # type: ignore
    key_count:   IntProperty()                                      # type: ignore
    unity_attr:  StringProperty()                                   # type: ignore
    unity_cls:   IntProperty()                                      # type: ignore
    is_boolean:  BoolProperty()                                     # type: ignore
    label:       StringProperty()                                   # type: ignore
    # 用户可在 UI 里覆盖 Unity 目标路径（留空 = 用算子全局路径）
    path_override: StringProperty(
        name="路径覆盖",
        description="留空则使用全局目标路径；填入后仅此轨道使用该路径",
        default="",
    )                                                               # type: ignore


# ── PropertyGroup：按来源物体分的折叠组头 ────────────────────

class HO_PG_AnimGroupHeader(PropertyGroup):
    """轨道列表的折叠分组标题。"""
    obj_name: StringProperty()  # type: ignore
    expanded: BoolProperty(default=True)  # type: ignore


# ── 主导出算子 ────────────────────────────────────────────────

class OP_ExportUnityAnimClip(Operator, ExportHelper):
    """把 FBX 无法携带的属性动画轨道导出为 Unity .anim。

    invoke 时扫描选中物体，列出所有非骨骼变换、非形态键的动画属性，
    用户勾选后确认导出。
    """
    bl_idname = "ho.export_unity_anim_clip"
    bl_label  = "导出 Unity 属性动画 (.anim)"
    bl_description = "把 FBX 无法携带的属性动画轨道导出为 Unity .anim（勾选所需轨道）"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".anim"
    filter_glob: StringProperty(default="*.anim", options={'HIDDEN'}, maxlen=255)  # type: ignore

    # 轨道列表（invoke 时填充，SKIP_SAVE 避免跨会话污染）
    tracks: CollectionProperty(
        type=HO_PG_AnimTrackItem, options={'SKIP_SAVE', 'HIDDEN'},
    )  # type: ignore
    groups: CollectionProperty(
        type=HO_PG_AnimGroupHeader, options={'SKIP_SAVE', 'HIDDEN'},
    )  # type: ignore

    # 全局参数
    fps: FloatProperty(
        name="帧率 (fps)",
        description="导出时间轴所用帧率，默认取项目渲染帧率",
        default=30.0, min=1.0, max=960.0, step=100,
    )  # type: ignore
    target_path: StringProperty(
        name="全局目标路径",
        description=(
            "Unity 里被动画驱动的 GameObject 相对 Animator 的层级路径。\n"
            "留空 = Animator 根物体自身。\n"
            "注意：Animator 所在物体不能被自己的 m_IsActive 动画关闭，\n"
            "请将 Animator 挂在父物体，填子物体路径（如 Body）。"
        ),
        default="",
    )  # type: ignore
    align_to_start: BoolProperty(
        name="对齐到起始帧",
        description="以场景起始帧为 t=0；关闭则直接用 帧号/fps 作时间",
        default=True,
    )  # type: ignore
    loop_time: BoolProperty(
        name="循环 (Loop Time)",
        description="生成的 clip 打开 Loop Time",
        default=False,
    )  # type: ignore

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects) or context.active_object is not None

    # ── 数据填充 ──────────────────────────────────────────────

    def _populate(self, context):
        """扫描场景，填充 tracks / groups。每次 invoke 都重新填。"""
        self.tracks.clear()
        self.groups.clear()

        # 默认帧率 = 项目渲染帧率
        render = context.scene.render
        self.fps = render.fps / render.fps_base

        selected = list(context.selected_objects)
        if context.active_object and context.active_object not in selected:
            selected.append(context.active_object)

        found = scan.scan(selected)

        # 按来源物体分组
        obj_order: list[str] = []
        by_obj: dict[str, list[scan.AnimTrackInfo]] = {}
        for info in found:
            if info.obj_name not in by_obj:
                obj_order.append(info.obj_name)
                by_obj[info.obj_name] = []
            by_obj[info.obj_name].append(info)

        for obj_name in obj_order:
            grp = self.groups.add()
            grp.obj_name = obj_name
            grp.expanded = True

            for info in by_obj[obj_name]:
                item = self.tracks.add()
                item.enabled     = True
                item.obj_name    = info.obj_name
                item.data_path   = info.data_path
                item.array_index = info.array_index
                item.key_count   = info.key_count
                item.unity_attr  = info.unity_attr
                item.unity_cls   = info.unity_cls
                item.is_boolean  = info.is_boolean
                item.label       = info.label

    def invoke(self, context, event):
        self._populate(context)
        # 弹出文件浏览器
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    # ── 执行导出 ──────────────────────────────────────────────

    def execute(self, context):
        enabled = [t for t in self.tracks if t.enabled]
        if not enabled:
            self.report({'ERROR'}, "没有勾选任何轨道")
            return {'CANCELLED'}

        fps         = self.fps
        start_frame = context.scene.frame_start if self.align_to_start else 0.0
        global_path = self.target_path.strip()

        curves_out: list[tuple] = []  # (keys, attribute, path, class_id)
        stop_time = 0.0

        for item in enabled:
            obj = bpy.data.objects.get(item.obj_name)
            if obj is None:
                self.report({'WARNING'}, f"物体 {item.obj_name!r} 不存在，已跳过")
                continue

            fc = scan.find_fcurve(obj, item.data_path, item.array_index)
            if fc is None:
                self.report({'WARNING'}, f"{item.obj_name}/{item.data_path}[{item.array_index}] 找不到 fcurve，已跳过")
                continue

            keys = interpolation.convert_fcurve(
                fc, fps, start_frame,
                force_stepped=item.is_boolean,
                snap_binary=item.is_boolean,
            )
            if not keys:
                continue

            target_path = item.path_override.strip() or global_path
            curves_out.append((keys, item.unity_attr, target_path, item.unity_cls))
            stop_time = max(stop_time, max(k.time for k in keys))

        if not curves_out:
            self.report({'ERROR'}, "所有勾选轨道均无有效关键帧")
            return {'CANCELLED'}

        clip_name = os.path.splitext(os.path.basename(self.filepath))[0]
        doc = anim_yaml.build_document(clip_name, curves_out, stop_time, fps, self.loop_time)

        try:
            with open(self.filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(doc)
        except OSError as exc:
            self.report({'ERROR'}, f"写入失败：{exc}")
            return {'CANCELLED'}

        # 控制台打印摘要
        print(f"[HoTools .anim] 导出：{len(curves_out)} 条轨道 → {os.path.basename(self.filepath)}  (fps={fps})")
        for _, attr, path, cls in curves_out:
            print(f"    {attr}  path={path!r}  classID={cls}")

        self.report({'INFO'}, f"导出成功：{len(curves_out)} 条轨道 → {os.path.basename(self.filepath)}")
        return {'FINISHED'}

    # ── 侧边栏 UI ─────────────────────────────────────────────

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        # 全局参数区
        param_box = layout.box()
        param_box.label(text="导出参数", icon='SETTINGS')
        col = param_box.column(align=True)
        col.prop(self, "fps")
        col.prop(self, "target_path")
        col.prop(self, "align_to_start")
        col.prop(self, "loop_time")

        # 轨道勾选列表
        track_box = layout.box()
        if not self.tracks:
            track_box.label(text="未找到可导出的属性动画轨道", icon='INFO')
            return

        track_box.label(
            text=f"属性动画轨道（共 {len(self.tracks)} 条）",
            icon='ACTION',
        )

        # 按物体分组折叠渲染
        group_map = {g.obj_name: g for g in self.groups}
        cur_obj   = None
        grp       = None
        grp_col   = None

        for item in self.tracks:
            # 物体分组标题行
            if item.obj_name != cur_obj:
                cur_obj = item.obj_name
                grp = group_map.get(cur_obj)
                header = track_box.row(align=True)
                if grp is not None:
                    header.prop(
                        grp, "expanded", text="", emboss=False,
                        icon='DISCLOSURE_TRI_DOWN' if grp.expanded else 'DISCLOSURE_TRI_RIGHT',
                    )
                header.label(text=cur_obj, icon='OBJECT_DATA')
                grp_col = track_box.column(align=True)

            if grp is not None and not grp.expanded:
                continue
            if grp_col is None:
                continue

            # 轨道行：勾选框 + 标签(label 帧数 → unity属性) + 可选路径覆盖输入
            row = grp_col.row(align=True)
            row.prop(item, "enabled", text="")
            sub = row.row(align=True)
            sub.enabled = item.enabled
            icon = 'KEYFRAME' if item.is_boolean else 'FCURVE'
            sub.label(
                text=f"{item.label}  [{item.key_count}K → {item.unity_attr}]",
                icon=icon,
            )
            sub.prop(item, "path_override", text="", placeholder="路径覆盖…")


# ── 导出菜单挂钩 ──────────────────────────────────────────────

def _menu_draw(self, context):
    self.layout.operator(
        OP_ExportUnityAnimClip.bl_idname,
        text="HoTools-属性动画 (.anim)",
    )


# ── 注册 ──────────────────────────────────────────────────────

cls_list = [
    HO_PG_AnimTrackItem,
    HO_PG_AnimGroupHeader,
    OP_ExportUnityAnimClip,
]


def register():
    for c in cls_list:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(_menu_draw)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_draw)
    for c in reversed(cls_list):
        bpy.utils.unregister_class(c)
