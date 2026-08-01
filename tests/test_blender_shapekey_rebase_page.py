import importlib
import math
import sys
import tempfile
import types
import uuid
from pathlib import Path

import bpy


ADDON_DIR = Path(__file__).resolve().parents[1]
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))
package = types.ModuleType("HoTools")
package.__path__ = [str(ADDON_DIR)]
sys.modules.setdefault("HoTools", package)
shapekey_package = types.ModuleType("HoTools.ShapekeyTools")
shapekey_package.__path__ = [str(ADDON_DIR / "ShapekeyTools")]
sys.modules.setdefault("HoTools.ShapekeyTools", shapekey_package)

rebase = importlib.import_module("HoTools.ShapekeyTools.rebase")


def activate(obj):
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_mesh(name, vertex_count=4):
    data = bpy.data.meshes.new(f"{name}Data")
    data.from_pydata(
        [(float(index) - 1.5, 0.0, 0.0) for index in range(vertex_count)],
        [],
        [],
    )
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    activate(obj)
    return obj


rebase.register()
probe_path = Path(tempfile.gettempdir()) / f"hotools_rebase_{uuid.uuid4().hex}.blend"
try:
    obj = make_mesh("PersistentRebase")
    basis = obj.shape_key_add(name="Basis", from_mix=False)
    source = obj.shape_key_add(name="EyeSculpt", from_mix=False)
    blink = obj.shape_key_add(name="eyeBlinkLeft", from_mix=False)
    surprised = obj.shape_key_add(name="eye_surprised_L", from_mix=False)
    source.value = 0.75
    for point in source.data:
        point.co.y += 1.0
    for point in blink.data[2:]:
        point.co.y += 1.0
    for point in surprised.data[2:]:
        point.co.z += 1.0

    assert rebase.sync_rebase_items(obj) == 3
    shape_keys = obj.data.shape_keys
    assert shape_keys.ho_rebase_schema == rebase.REBASE_SCHEMA_VERSION
    items = {
        item.shape_key_name: item for item in shape_keys.ho_rebase_items
    }
    assert items["EyeSculpt"].merge
    assert items["EyeSculpt"].weight == 0.75
    assert items["eyeBlinkLeft"].initialized
    assert items["eye_surprised_L"].initialized
    assert items["eye_surprised_L"].function_tag == 'OTHERS'
    assert rebase._rebase_configuration_error(shape_keys) is None
    assert [
        item.shape_key_name for item in rebase._merge_rebase_items(shape_keys)
    ] == ["EyeSculpt"]

    # 刷新使用保守推断；显式推断只覆盖选中行，并允许更积极的名称和几何判断。
    items["EyeSculpt"].function_tag = 'MOUTH'
    items["eye_surprised_L"].selected = True
    assert bpy.ops.ho.rebase_fbsf_infer_selected(
        "EXEC_DEFAULT") == {'FINISHED'}
    assert items["eye_surprised_L"].function_tag == 'LEFT_EYE'
    assert items["EyeSculpt"].function_tag == 'MOUTH'
    items["eye_surprised_L"].selected = False

    # 活动键配置行直接指向持久列表中的同一个条目。
    obj.active_shape_key_index = shape_keys.key_blocks.find("eyeBlinkLeft")
    active_item = rebase._active_rebase_item(obj)
    assert active_item is not None
    assert active_item.shape_key_name == "eyeBlinkLeft"
    active_item.function_tag = 'RIGHT_EYE'
    assert items["eyeBlinkLeft"].function_tag == 'RIGHT_EYE'
    obj.active_shape_key_index = 0
    assert rebase._active_rebase_item(obj) is None

    # 点击持久列表行时，活动索引回调同步 Blender 的活动形态键。
    shape_keys.ho_rebase_item_index = 1
    assert obj.active_shape_key == blink
    assert rebase._active_rebase_item(obj).shape_key_name == "eyeBlinkLeft"

    # 批量选择与批量权能只修改选中行。
    assert bpy.ops.ho.rebase_fbsf_select_all("EXEC_DEFAULT") == {'FINISHED'}
    assert all(item.selected for item in shape_keys.ho_rebase_items)
    assert bpy.ops.ho.rebase_fbsf_deselect_all("EXEC_DEFAULT") == {'FINISHED'}
    assert not any(item.selected for item in shape_keys.ho_rebase_items)
    items["EyeSculpt"].selected = True
    shape_keys.ho_rebase_batch_function_tag = 'MOUTH'
    assert bpy.ops.ho.rebase_fbsf_apply_batch_function(
        "EXEC_DEFAULT") == {'FINISHED'}
    assert items["EyeSculpt"].function_tag == 'MOUTH'
    assert items["eyeBlinkLeft"].function_tag == 'RIGHT_EYE'

    # 刷新只保守推断新增行；用户最终确认的旧值始终具有最高优先级。
    items["EyeSculpt"].function_tag = 'BOTH_EYES'
    items["EyeSculpt"].weight = 0.4
    items["eyeBlinkLeft"].function_tag = 'RIGHT_EYE'
    items["eyeBlinkLeft"].merge = False
    rebase.sync_rebase_items(obj)
    items = {
        item.shape_key_name: item for item in shape_keys.ho_rebase_items
    }
    assert items["EyeSculpt"].function_tag == 'BOTH_EYES'
    assert math.isclose(items["EyeSculpt"].weight, 0.4, abs_tol=1e-6)
    assert items["eyeBlinkLeft"].function_tag == 'RIGHT_EYE'

    # ShapeKey 没有稳定的自定义属性身份，改名后按新键处理，避免误继承替代键配置。
    blink.name = "RenamedBlink"
    rebase.sync_rebase_items(obj)
    items = {
        item.shape_key_name: item for item in shape_keys.ho_rebase_items
    }
    assert items["RenamedBlink"].function_tag == 'OTHERS'
    assert not items["RenamedBlink"].merge

    # 新键只推断一次，已有手调行保持不变。
    obj.shape_key_add(name="custom_wink", from_mix=False)
    rebase.sync_rebase_items(obj)
    items = {
        item.shape_key_name: item for item in shape_keys.ho_rebase_items
    }
    assert items["RenamedBlink"].function_tag == 'OTHERS'
    assert items["custom_wink"].initialized

    # 列表和执行字段都保存在 Key 数据块中，并随 .blend 保存和读取。
    bpy.ops.wm.save_as_mainfile(filepath=str(probe_path), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(probe_path))
    obj = bpy.data.objects["PersistentRebase"]
    shape_keys = obj.data.shape_keys
    items = {
        item.shape_key_name: item for item in shape_keys.ho_rebase_items
    }
    assert items["EyeSculpt"].function_tag == 'BOTH_EYES'
    assert math.isclose(items["EyeSculpt"].weight, 0.4, abs_tol=1e-6)
    assert items["RenamedBlink"].function_tag == 'OTHERS'
    assert items["custom_wink"].initialized
    assert shape_keys.ho_rebase_left_is_positive in {-1, 1}

    # 应用时拒绝过期列表，不在执行阶段静默分类新增键。
    activate(obj)
    obj.shape_key_add(name="AddedAfterRefresh", from_mix=False)
    assert bpy.ops.ho.rebase_fbsf_apply("EXEC_DEFAULT") == {'CANCELLED'}
    assert obj.data.shape_keys.key_blocks.get("EyeSculpt") is not None

    print("SHAPEKEY_REBASE_PAGE_OK", bpy.app.version_string)
finally:
    rebase.unregister()
    probe_path.unlink(missing_ok=True)
