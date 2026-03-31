import bpy
import importlib.util
import os

from .core.ui_manager import UIManager


def load_demo_ui():
    addon_dir = os.path.dirname(__file__)
    demo_path = os.path.join(addon_dir, "demo_ui", "demo.py")
    spec = importlib.util.spec_from_file_location("exp_hogui_demo", demo_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_demo_ui()


manager = UIManager()
manager.root = load_demo_ui()


# --- 定时器，用于保持 UI 刷新 ---
def redraw_timer():
    wm = bpy.context.window_manager
    if not getattr(wm, "my_console_ui_active", False):
        return 0.2

    for w in bpy.data.window_managers:
        for win in w.windows:
            for area in win.screen.areas:
                if area.type == 'CONSOLE':
                    area.tag_redraw()

    return 0.03


# --- 绘制回调 ---
def draw_callback_px(_self=None, _context=None):
    context = bpy.context
    area = context.area
    if not area or area.type != 'CONSOLE':
        return

    wm = context.window_manager
    if not getattr(wm, "my_console_ui_active", False):
        return

    region = context.region
    if not region:
        return

    manager.renderer.draw_background(region)
    manager.draw(context)

    if getattr(wm, "my_console_ui_debug", False):
        info_lines = [
            f"region: {region.width}x{region.height} @ ({region.x},{region.y})",
            f"mouse: {manager.ctx.mouse_x},{manager.ctx.mouse_y}",
            f"mouse_abs: {manager.ctx.mouse_x_abs},{manager.ctx.mouse_y_abs}",
            f"hovered={manager.ctx.hovered_id}",
            f"pressed={manager.ctx.pressed_id}",
        ]
        base_y = region.height - 20
        for line in info_lines:
            manager.renderer.draw_text_abs(line, 12, base_y, (0.9, 0.9, 0.9, 1.0))
            base_y -= 16

        manager.renderer.draw_crosshair((manager.ctx.mouse_x, manager.ctx.mouse_y), (1.0, 0.3, 0.1, 1.0), size=6)


# --- 模态交互算子 ---
class HOGUI_OT_ConsoleModal(bpy.types.Operator):
    bl_idname = "console.hogui_modal"
    bl_label = "HOGUI Console Modal"

    def modal(self, context, event):
        wm = context.window_manager
        if not getattr(wm, "my_console_ui_active", False):
            return {'FINISHED'}

        if not hasattr(event, 'mouse_x') or not hasattr(event, 'mouse_y'):
            return {'PASS_THROUGH'}

        mx = event.mouse_x
        my = event.mouse_y

        console_area = None
        console_region = None
        if context.window and context.window.screen:
            for area in context.window.screen.areas:
                if area.type != 'CONSOLE':
                    continue
                for region in area.regions:
                    if region.type != 'WINDOW':
                        continue
                    if region.x <= mx <= region.x + region.width and region.y <= my <= region.y + region.height:
                        console_area = area
                        console_region = region
                        break
                if console_area:
                    break

        if not console_area or not console_region:
            return {'PASS_THROUGH'}

        manager.ctx.region_x = console_region.x
        manager.ctx.region_y = console_region.y
        manager.ctx.begin_frame(event)

        consumed = manager.handle_event(event)
        console_area.tag_redraw()
        console_region.tag_redraw()

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            return {'RUNNING_MODAL'}

        if consumed:
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


# --- header UI ---

def draw_header_btn(self, context):
    wm = context.window_manager
    row = self.layout.row(align=True)
    row.prop(wm, "my_console_ui_active", text="Console UI", toggle=True, icon='CONSOLE')
    row.prop(wm, "my_console_ui_debug", text="Debug", toggle=True, icon='INFO')


def on_toggle_update(self, context):
    wm = context.window_manager
    if wm.my_console_ui_active:
        bpy.ops.console.hogui_modal('INVOKE_DEFAULT')
    else:
        wm.my_console_ui_hover = ""
        wm.my_console_ui_pressed = ""


# --- 注册 / 反注册 ---
_HANDLE = None


def register():
    bpy.types.WindowManager.my_console_ui_active = bpy.props.BoolProperty(default=False, update=on_toggle_update)
    bpy.types.WindowManager.my_console_ui_debug = bpy.props.BoolProperty(default=False)
    bpy.types.WindowManager.my_console_ui_hover = bpy.props.StringProperty(default="")
    bpy.types.WindowManager.my_console_ui_pressed = bpy.props.StringProperty(default="")
    bpy.types.WindowManager.my_console_ui_mouse_x = bpy.props.IntProperty(default=0)
    bpy.types.WindowManager.my_console_ui_mouse_y = bpy.props.IntProperty(default=0)
    bpy.types.WindowManager.my_console_ui_mouse_x_abs = bpy.props.IntProperty(default=0)
    bpy.types.WindowManager.my_console_ui_mouse_y_abs = bpy.props.IntProperty(default=0)

    global _HANDLE
    _HANDLE = bpy.types.SpaceConsole.draw_handler_add(draw_callback_px, (), 'WINDOW', 'POST_PIXEL')

    bpy.utils.register_class(HOGUI_OT_ConsoleModal)
    bpy.types.CONSOLE_HT_header.append(draw_header_btn)

    if not bpy.app.timers.is_registered(redraw_timer):
        bpy.app.timers.register(redraw_timer)


def unregister():
    global _HANDLE
    if _HANDLE:
        bpy.types.SpaceConsole.draw_handler_remove(_HANDLE, 'WINDOW')
        _HANDLE = None

    bpy.utils.unregister_class(HOGUI_OT_ConsoleModal)
    bpy.types.CONSOLE_HT_header.remove(draw_header_btn)

    for name in [
        "my_console_ui_active",
        "my_console_ui_debug",
        "my_console_ui_hover",
        "my_console_ui_pressed",
        "my_console_ui_mouse_x",
        "my_console_ui_mouse_y",
        "my_console_ui_mouse_x_abs",
        "my_console_ui_mouse_y_abs",
    ]:
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)

    if bpy.app.timers.is_registered(redraw_timer):
        bpy.app.timers.unregister(redraw_timer)


if __name__ == '__main__':
    register()
