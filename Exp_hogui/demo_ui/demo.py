import bpy

from Exp_hogui.widgets import Button, Frame, Label, ColorPicker, Dropdown, MenuList, Table


def action_print_hello():
    print(">>> HOGUI 控制台 UI: 点击了 [打印日志]")


def action_spawn_cube():
    bpy.ops.mesh.primitive_cube_add()
    print(">>> HOGUI 控制台 UI: 点击了 [创建立方体]")


def action_color_changed(color):
    print(f">>> 颜色已选择: {color}")


def action_dropdown_selected(value):
    print(f">>> 下拉选择: {value}")


def action_menu_selected(item):
    print(f">>> 菜单选择: {item}")


def action_table_row_selected(row, index):
    print(f">>> 选中表格行 {index}: {row}")


def build_demo_ui():
    root = Frame("root", (10, 10, 640, 500), title="HoTools Exp_hogui Demo")

    root.add(Label("demo_title", (20, 24, 260, 24), "Exp_hogui 控件演示", size=16))
    root.add(Button("btn_log", (20, 80, 180, 36), "打印日志", on_click=action_print_hello))
    root.add(Button("btn_cube", (220, 80, 180, 36), "创建立方体", on_click=action_spawn_cube))

    root.add(ColorPicker(
        "color_picker",
        (20, 140, 280, 110),
        "颜色拾取器",
        color=(0.35, 0.55, 0.85, 1.0),
        on_change=action_color_changed,
    ))

    root.add(Dropdown(
        "dropdown",
        (20, 270, 280, 70),
        "下拉菜单",
        ["选项一", "选项二", "选项三"],
        selected_index=0,
        on_select=action_dropdown_selected,
    ))

    root.add(MenuList(
        "menu_list",
        (320, 80, 280, 180),
        "填充菜单",
        ["新建", "打开", "保存", "退出"],
        on_select=action_menu_selected,
    ))

    root.add(Table(
        "demo_table",
        (320, 280, 320, 200),
        ["名称", "类型", "值"],
        [
            ["位置", "Vector3", "(1.0, 2.0, 3.0)"],
            ["缩放", "Vector3", "(1.0, 1.0, 1.0)"],
            ["颜色", "Color", "Blue"],
            ["数量", "Int", "8"],
            ["状态", "Bool", "True"],
        ],
        on_select=action_table_row_selected,
    ))

    return root
