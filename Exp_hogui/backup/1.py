import bpy
import gpu
import blf
import time
from gpu_extras.batch import batch_for_shader

# --- 1. 全局配置与命名空间 ---
# 用于在 draw 和 modal 之间传递数据的全局桥梁
UI_MAP_KEY = "MY_CUSTOM_UI_MAP"
TIMER_KEY = "MY_REDRAW_TICK"

# --- 2. 核心功能函数 ---
def action_print_hello():
    print(">>> 成功点击：执行了 Hello")

def action_spawn_cube():
    bpy.ops.mesh.primitive_cube_add()
    print(">>> 成功点击：创建了立方体")

# 定义我们的按钮 (本地坐标: x, y, 宽, 高)
MY_BUTTONS = [
    {"id": "BTN_1", "text": "打印日志", "rect": (50, 150, 150, 40), "func": action_print_hello},
    {"id": "BTN_2", "text": "创建立方体", "rect": (50, 90, 150, 40), "func": action_spawn_cube},
]

# --- 3. 定时刷新器 (模仿 main.py 的 redraw_timer) ---
def redraw_timer():
    wm = bpy.context.window_manager
    # 如果没开启面板，降低刷新率
    if not getattr(wm, "my_absolute_ui_active", False):
        return 0.2 
    
    # 强制重绘 Python Console
    try:
        for w in bpy.data.window_managers:
            for win in w.windows:
                if not win.screen: continue
                for area in win.screen.areas:
                    if area.type == 'CONSOLE':
                        area.tag_redraw()
    except Exception:
        pass
    
    # 高频刷新保证 Hover 体验
    return 0.03

# --- 4. 绘制与坐标计算 (The Draw Callback) ---
def draw_callback_px(self, context):
    if not context.window_manager.my_absolute_ui_active:
        return

    # 准备着色器
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    region = context.region
    
    # 绘制全屏背景
    bg_verts = [(0, 0), (region.width, 0), (region.width, region.height), (0, region.height)]
    batch_bg = batch_for_shader(shader, 'TRI_FAN', {"pos": bg_verts})
    shader.bind()
    shader.uniform_float("color", (0.08, 0.09, 0.11, 1.0))
    batch_bg.draw(shader)

    # --- 核心：提取状态与计算绝对坐标 ---
    wm = context.window_manager
    hover_id = getattr(wm, "my_ui_hover_id", "")
    pressed_id = getattr(wm, "my_ui_pressed_id", "")
    
    # 初始化数据桥梁
    ns = bpy.app.driver_namespace
    if UI_MAP_KEY not in ns:
        ns[UI_MAP_KEY] = {}
    
    area_ptr = context.area.as_pointer()
    ui_data = {"buttons_abs": []}

    # 遍历并绘制按钮
    for btn in MY_BUTTONS:
        lx, ly, lw, lh = btn["rect"]
        
        # 计算窗口绝对坐标 (Window Absolute Coordinates) !这是点击成功的关键!
        abs_x0 = region.x + lx
        abs_y0 = region.y + ly
        abs_x1 = abs_x0 + lw
        abs_y1 = abs_y0 + lh
        
        # 将绝对坐标存入字典，供 modal 读取
        ui_data["buttons_abs"].append({
            "id": btn["id"],
            "rect_abs": (abs_x0, abs_y0, abs_x1, abs_y1),
            "func": btn["func"]
        })

        # 视觉状态判定
        is_pressed = (pressed_id == btn["id"])
        is_hover = (hover_id == btn["id"])
        
        if is_pressed:
            color = (0.1, 0.3, 0.6, 1.0)
        elif is_hover:
            color = (0.2, 0.5, 0.8, 1.0)
        else:
            color = (0.24, 0.28, 0.36, 1.0)
            
        # 绘制按钮
        btn_verts = [(lx, ly), (lx + lw, ly), (lx + lw, ly + lh), (lx, ly + lh)]
        batch_btn = batch_for_shader(shader, 'TRI_FAN', {"pos": btn_verts})
        shader.uniform_float("color", color)
        batch_btn.draw(shader)

        # 绘制文字
        blf.size(0, 18)
        blf.color(0, 1, 1, 1, 1)
        blf.position(0, lx + 20, ly + 12, 0)
        blf.draw(0, btn["text"])

    # 将当前 Area 的数据更新到全局
    ns[UI_MAP_KEY][area_ptr] = ui_data


# --- 5. 模态交互算子 (The Modal Operator) ---
class MY_OT_AbsoluteModal(bpy.types.Operator):
    bl_idname = "view3d.my_absolute_modal"
    bl_label = "Absolute UI Modal"

    def modal(self, context, event):
        wm = context.window_manager
        if not wm.my_absolute_ui_active:
            return {'FINISHED'}

        # 使用 event.mouse_x / y 获取绝对窗口坐标
        mx_abs = event.mouse_x
        my_abs = event.mouse_y

        # Header 避让：计算当前区域的 Header 高度 (通常在区域顶部)
        region = context.region
        if event.mouse_region_y > region.height - 30:
            return {'PASS_THROUGH'}

        # 获取当前 Area 的按钮绝对坐标数据
        ns = bpy.app.driver_namespace
        ui_map = ns.get(UI_MAP_KEY, {})
        area_ptr = context.area.as_pointer() if context.area else 0
        ui = ui_map.get(area_ptr, {})

        # --- 碰撞检测 (Hit Testing) ---
        hovered_token = ""
        hovered_func = None
        
        for btn in ui.get("buttons_abs", []):
            x0, y0, x1, y1 = btn["rect_abs"]
            if x0 <= mx_abs <= x1 and y0 <= my_abs <= y1:
                hovered_token = btn["id"]
                hovered_func = btn["func"]
                break
        
        # 更新 Hover 状态
        wm.my_ui_hover_id = hovered_token

        # --- 点击处理 ---
        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if hovered_token:
                    # 点中了按钮
                    wm.my_ui_pressed_id = hovered_token
                    hovered_func() # 真正执行按钮绑定的函数
                    return {'RUNNING_MODAL'}
                else:
                    # 点到了面板空白处，拦截
                    wm.my_ui_pressed_id = ""
                    return {'RUNNING_MODAL'}
                    
            elif event.value == 'RELEASE':
                wm.my_ui_pressed_id = ""
                # 如果鼠标在面板内，拦截释放事件
                return {'RUNNING_MODAL'}

        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


# --- 6. 注册与卸载 ---
_HANDLE = None

def draw_header_btn(self, context):
    self.layout.prop(context.window_manager, "my_absolute_ui_active", text="绝对坐标面板", toggle=True, icon='MODIFIER')

def on_toggle_update(self, context):
    if self.my_absolute_ui_active:
        bpy.ops.view3d.my_absolute_modal('INVOKE_DEFAULT')
    else:
        # 清除状态
        self.my_ui_hover_id = ""
        self.my_ui_pressed_id = ""

def register():
    bpy.types.WindowManager.my_absolute_ui_active = bpy.props.BoolProperty(default=False, update=on_toggle_update)
    bpy.types.WindowManager.my_ui_hover_id = bpy.props.StringProperty(default="")
    bpy.types.WindowManager.my_ui_pressed_id = bpy.props.StringProperty(default="")
    
    global _HANDLE
    _HANDLE = bpy.types.SpaceConsole.draw_handler_add(draw_callback_px, (None, bpy.context), 'WINDOW', 'POST_PIXEL')
    
    bpy.utils.register_class(MY_OT_AbsoluteModal)
    bpy.types.CONSOLE_HT_header.append(draw_header_btn)
    
    # 注册定时器
    if not bpy.app.timers.is_registered(redraw_timer):
        bpy.app.timers.register(redraw_timer)

def unregister():
    global _HANDLE
    if _HANDLE:
        bpy.types.SpaceConsole.draw_handler_remove(_HANDLE, 'WINDOW')
    
    bpy.utils.unregister_class(MY_OT_AbsoluteModal)
    bpy.types.CONSOLE_HT_header.remove(draw_header_btn)
    
    del bpy.types.WindowManager.my_absolute_ui_active
    del bpy.types.WindowManager.my_ui_hover_id
    del bpy.types.WindowManager.my_ui_pressed_id
    
    if bpy.app.timers.is_registered(redraw_timer):
        bpy.app.timers.unregister(redraw_timer)

if __name__ == "__main__":
    register()