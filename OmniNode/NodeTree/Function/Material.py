from ..OmniNodeSocketMapping import _OmniMaterialSlot
from ..FunctionNodeCore import omni
from . import _Color

import bpy


def _require_material(mat) -> bpy.types.Material:
    if mat is None or not isinstance(mat, bpy.types.Material):
        raise ValueError("材质输入未连接或无效")
    return mat


def _require_material_slot(slot) -> bpy.types.MaterialSlot:
    if slot is None or not isinstance(slot, bpy.types.MaterialSlot):
        raise ValueError("材质槽输入未连接或无效")
    return slot


def _require_object(obj) -> bpy.types.Object:
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError("物体输入未连接或无效")
    return obj


def _find_material_index(obj: bpy.types.Object, mat: bpy.types.Material) -> int:
    for index, slot in enumerate(obj.material_slots):
        if slot.material == mat:
            return index
    return -1


def _get_material_slot_by_index(obj: bpy.types.Object, slot_index: int) -> bpy.types.MaterialSlot:
    obj = _require_object(obj)
    if len(obj.material_slots) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何材质槽")

    slot_index = int(slot_index)
    if slot_index < 0 or slot_index >= len(obj.material_slots):
        raise ValueError(
            f"材质槽索引超出范围: {slot_index}，有效范围是 0 到 {len(obj.material_slots) - 1}"
        )
    return obj.material_slots[slot_index]


def _get_material_slot_by_name(obj: bpy.types.Object, slot_name: str) -> bpy.types.MaterialSlot:
    obj = _require_object(obj)
    slot_name = str(slot_name or "").strip()
    if not slot_name:
        raise ValueError("材质槽名称为空")

    for slot in obj.material_slots:
        if slot.name == slot_name:
            return slot
    raise ValueError(f"物体 '{obj.name}' 上找不到材质槽 '{slot_name}'")


def _get_material_slot_by_material(
    obj: bpy.types.Object,
    mat: bpy.types.Material,
    match_index: int = 0,
) -> bpy.types.MaterialSlot:
    obj = _require_object(obj)
    mat = _require_material(mat)
    match_index = int(match_index)
    if match_index < 0:
        raise ValueError("匹配索引不能小于 0")

    matches = [slot for slot in obj.material_slots if slot.material == mat]
    if not matches:
        raise ValueError(f"物体 '{obj.name}' 上找不到材质 '{mat.name}' 对应的材质槽")
    if match_index >= len(matches):
        raise ValueError(
            f"材质 '{mat.name}' 的匹配索引超出范围: {match_index}，有效范围是 0 到 {len(matches) - 1}"
        )
    return matches[match_index]


@omni(
    enable=True,
    bl_label="添加材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "材质"],
    _OUTPUT_NAME=["物体", "材质槽", "槽索引"],
    bl_icon="MATERIAL",
    omni_description="""
    给目标物体添加一个材质槽并赋予指定材质。
    """,
    mute_passthrough={"_OUTPUT0": "obj"},
)
def objectAddMaterialSlot(
    obj: bpy.types.Object,
    mat: bpy.types.Material,
) -> tuple[bpy.types.Object, bpy.types.MaterialSlot, int]:
    obj = _require_object(obj)
    mat = _require_material(mat)
    obj.data.materials.append(mat)
    slot_index = len(obj.material_slots) - 1
    return obj, obj.material_slots[slot_index], slot_index


@omni(
    enable=True,
    bl_label="按索引获取材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "槽索引"],
    _OUTPUT_NAME=["材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    按索引获取目标物体上的材质槽。
    """,
)
def objectGetMaterialSlotByIndex(
    obj: bpy.types.Object,
    slot_index: int,
) -> bpy.types.MaterialSlot:
    return _get_material_slot_by_index(obj, slot_index)


@omni(
    enable=True,
    bl_label="按名称获取材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "槽名称"],
    _OUTPUT_NAME=["材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    按名称获取目标物体上的材质槽。
    """,
)
def objectGetMaterialSlotByName(
    obj: bpy.types.Object,
    slot_name: str,
) -> bpy.types.MaterialSlot:
    return _get_material_slot_by_name(obj, slot_name)


@omni(
    enable=True,
    bl_label="按材质获取材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "材质", "匹配索引"],
    _OUTPUT_NAME=["材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    按材质获取目标物体上的材质槽。
    如果同一材质被重复使用，可以通过匹配索引指定第几个。
    """,
)
def objectGetMaterialSlotByMaterial(
    obj: bpy.types.Object,
    mat: bpy.types.Material,
    match_index: int = 0,
) -> bpy.types.MaterialSlot:
    return _get_material_slot_by_material(obj, mat, match_index)


@omni(
    enable=True,
    bl_label="获取激活材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体"],
    _OUTPUT_NAME=["材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    获取物体的激活材质槽。
    """,
)
def objectGetActiveMaterialSlot(
    obj: bpy.types.Object,
) -> bpy.types.MaterialSlot:
    obj = _require_object(obj)
    if len(obj.material_slots) == 0:
        raise ValueError(f"物体 '{obj.name}' 没有任何材质槽")
    return obj.material_slots[obj.active_material_index]


@omni(
    enable=True,
    bl_label="获取材质槽材质",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["材质"],
    bl_icon="MATERIAL",
    omni_description="""
    获取材质槽中的材质。
    """,
)
def materialSlotGetMaterial(
    slot: _OmniMaterialSlot,
) -> bpy.types.Material:
    slot = _require_material_slot(slot)
    mat = slot.material
    if mat is None:
        raise ValueError("材质槽没有绑定材质")
    return mat


@omni(
    enable=True,
    bl_label="获取材质槽索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["槽索引"],
    bl_icon="MATERIAL",
    omni_description="""
    获取材质槽在物体上的索引。
    """,
)
def materialSlotGetIndex(
    slot: _OmniMaterialSlot,
) -> int:
    slot = _require_material_slot(slot)
    obj = slot.id_data
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError("材质槽没有有效的所属物体")
    for index, item in enumerate(obj.material_slots):
        if item == slot:
            return index
    raise ValueError("找不到材质槽索引")


@omni(
    enable=True,
    bl_label="获取材质槽名称",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["槽名称"],
    bl_icon="MATERIAL",
    omni_description="""
    获取材质槽的名称。
    """,
)
def materialSlotGetName(
    slot: _OmniMaterialSlot,
) -> str:
    slot = _require_material_slot(slot)
    return slot.name


@omni(
    enable=True,
    bl_label="获取材质槽物体",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MATERIAL",
    omni_description="""
    获取材质槽所属的物体。
    """,
)
def materialSlotGetObject(
    slot: _OmniMaterialSlot,
) -> bpy.types.Object:
    slot = _require_material_slot(slot)
    obj = slot.id_data
    if obj is None or not isinstance(obj, bpy.types.Object):
        raise ValueError("材质槽没有有效的所属物体")
    return obj


@omni(
    enable=True,
    bl_label="设置材质槽材质",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽", "材质"],
    _OUTPUT_NAME=["材质槽", "材质"],
    bl_icon="MATERIAL",
    omni_description="""
    设置材质槽的材质。
    """,
)
def materialSlotSetMaterial(
    slot: _OmniMaterialSlot,
    mat: bpy.types.Material,
) -> tuple[bpy.types.MaterialSlot, bpy.types.Material]:
    slot = _require_material_slot(slot)
    mat = _require_material(mat)
    slot.material = mat
    return slot, mat


@omni(
    enable=True,
    bl_label="清空材质槽材质",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    清空材质槽中的材质。
    """,
)
def materialSlotClearMaterial(
    slot: _OmniMaterialSlot,
) -> bpy.types.MaterialSlot:
    slot = _require_material_slot(slot)
    slot.material = None
    return slot


@omni(
    enable=True,
    bl_label="设置活动材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "槽索引"],
    _OUTPUT_NAME=["物体", "材质槽"],
    bl_icon="MATERIAL",
    omni_description="""
    设置活动材质槽。
    """,
    mute_passthrough={"_OUTPUT0": "obj"},
)
def objectSetActiveMaterialSlot(
    obj: bpy.types.Object,
    slot_index: int,
) -> tuple[bpy.types.Object, bpy.types.MaterialSlot]:
    obj = _require_object(obj)
    slot = _get_material_slot_by_index(obj, slot_index)
    obj.active_material_index = int(slot_index)
    return obj, slot


@omni(
    enable=True,
    bl_label="移除材质槽",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "槽索引"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MATERIAL",
    omni_description="""
    移除指定物体上的材质槽。
    """,
    mute_passthrough={"_OUTPUT0": "obj"},
)
def objectRemoveMaterialSlotByIndex(
    obj: bpy.types.Object,
    slot_index: int,
) -> bpy.types.Object:
    obj = _require_object(obj)
    _get_material_slot_by_index(obj, slot_index)
    obj.active_material_index = int(slot_index)
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.material_slot_remove()
    return obj


@omni(
    enable=True,
    bl_label="移除材质槽对象",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["材质槽"],
    _OUTPUT_NAME=["物体"],
    bl_icon="MATERIAL",
    omni_description="""
    移除指定的材质槽所属的物体上的该材质槽。
    """,
)
def materialSlotRemove(
    slot: _OmniMaterialSlot,
) -> bpy.types.Object:
    slot = _require_material_slot(slot)
    obj = materialSlotGetObject(slot)
    slot_index = materialSlotGetIndex(slot)
    obj.active_material_index = slot_index
    with bpy.context.temp_override(object=obj, active_object=obj):
        bpy.ops.object.material_slot_remove()
    return obj


@omni(
    enable=True,
    bl_label="获取材质所在槽索引",
    base_color=_Color.colorCat["Operator"],
    is_output_node=False,
    _INPUT_NAME=["物体", "材质"],
    _OUTPUT_NAME=["槽索引"],
    bl_icon="MATERIAL",
    omni_description="""
    在指定物体上查找材质所在的槽索引。
    """,
)
def objectFindMaterialSlotIndex(
    obj: bpy.types.Object,
    mat: bpy.types.Material,
) -> int:
    obj = _require_object(obj)
    mat = _require_material(mat)
    slot_index = _find_material_index(obj, mat)
    if slot_index < 0:
        raise ValueError(f"物体 '{obj.name}' 上找不到材质 '{mat.name}'")
    return slot_index
