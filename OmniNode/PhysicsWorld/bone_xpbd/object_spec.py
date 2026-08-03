"""Bone XPBD 显式骨骼集合 authoring 合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json


def _pointer(value) -> int:
    callback = getattr(value, "as_pointer", None)
    if not callable(callback):
        return 0
    try:
        return int(callback())
    except (ReferenceError, TypeError, ValueError):
        return 0


def _signature(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _bone_collection(value) -> tuple[object, tuple[str, ...], str] | None:
    if not isinstance(value, dict):
        return None
    armature = value.get("armature")
    if getattr(armature, "type", None) != "ARMATURE":
        raise TypeError("Bone XPBD 骨骼输入需要 Armature Object")
    names = tuple(
        str(name or "").strip()
        for name in (value.get("bone_collection") or value.get("bones") or ())
        if str(name or "").strip()
    )
    root = str(
        value.get("bone_collection_root")
        or value.get("root_bone")
        or value.get("bone")
        or ""
    ).strip()
    if not names:
        name = str(value.get("bone") or "").strip()
        if not name:
            raise ValueError("Bone XPBD 骨骼输入缺少 bone name")
        names = (name,)
        root = root or name
    return armature, names, root or names[0]


def _flatten(values) -> tuple[object, ...]:
    pending = [values]
    result = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            pending[0:0] = list(value)
            continue
        result.append(value)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class BoneXpbdObjectSpec:
    """一个 Armature 中由用户显式选出的实际模拟骨集合。"""

    armature: object
    bone_names: tuple[str, ...]
    collection_root: str = ""
    property_origin: str = "panel"
    pin_overrides: tuple[bool | None, ...] = ()
    armature_ptr: int = field(init=False)
    armature_data_ptr: int = field(init=False)
    armature_name: str = field(init=False)
    source_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if getattr(self.armature, "type", None) != "ARMATURE":
            raise TypeError("Bone XPBD 对象需要 Armature Object")
        names = tuple(str(name or "").strip() for name in self.bone_names)
        if not names or any(not name for name in names):
            raise ValueError("Bone XPBD 对象至少需要一根有效骨骼")
        if len(set(names)) != len(names):
            raise ValueError("Bone XPBD 对象不能重复包含同一根骨骼")
        pose_bones = getattr(getattr(self.armature, "pose", None), "bones", None)
        data_bones = getattr(getattr(self.armature, "data", None), "bones", None)
        missing = [
            name for name in names
            if (
                pose_bones is None
                or pose_bones.get(name) is None
                or data_bones is None
                or data_bones.get(name) is None
            )
        ]
        if missing:
            raise ValueError(f"Bone XPBD 找不到骨骼: {', '.join(missing)}")
        connected = [
            name for name in names
            if bool(getattr(data_bones.get(name), "use_connect", False))
        ]
        if connected:
            raise ValueError(
                "Bone XPBD 不支持 use_connect=True 的骨骼: "
                f"{', '.join(connected)}；请先关闭骨骼的连接选项再注册"
            )
        object_ptr = _pointer(self.armature)
        data_ptr = _pointer(getattr(self.armature, "data", None))
        if object_ptr <= 0 or data_ptr <= 0:
            raise ValueError("Bone XPBD Armature 需要稳定 object/data identity")
        origin = str(self.property_origin or "").strip().lower()
        if origin not in {"panel", "socket"}:
            raise ValueError("Bone XPBD property_origin 必须是 panel 或 socket")
        overrides = tuple(self.pin_overrides)
        if not overrides:
            overrides = (None,) * len(names)
        if len(overrides) != len(names):
            raise ValueError("Bone XPBD Pin覆写数量必须与骨骼数量一致")
        if origin == "panel":
            if any(value is not None for value in overrides):
                raise ValueError("Bone XPBD面板对象不能携带socket Pin覆写")
        elif any(type(value) is not bool for value in overrides):
            raise TypeError("Bone XPBD自定义对象必须显式提供bool Pin覆写")
        payload = {
            "armature_ptr": object_ptr,
            "armature_data_ptr": data_ptr,
            "bone_names": names,
        }
        object.__setattr__(self, "bone_names", names)
        object.__setattr__(self, "collection_root", str(self.collection_root or names[0]))
        object.__setattr__(self, "property_origin", origin)
        object.__setattr__(self, "pin_overrides", overrides)
        object.__setattr__(self, "armature_ptr", object_ptr)
        object.__setattr__(self, "armature_data_ptr", data_ptr)
        object.__setattr__(
            self,
            "armature_name",
            str(
                getattr(self.armature, "name_full", "")
                or getattr(self.armature, "name", "")
                or ""
            ),
        )
        object.__setattr__(self, "source_signature", _signature(payload))

    def debug_dict(self) -> dict:
        return {
            "schema": "bone_xpbd_object_v1",
            "armature_name": self.armature_name,
            "armature_ptr": self.armature_ptr,
            "armature_data_ptr": self.armature_data_ptr,
            "bone_names": self.bone_names,
            "collection_root": self.collection_root,
            "property_origin": self.property_origin,
            "pin_overrides": self.pin_overrides,
            "source_signature": self.source_signature,
        }


def _make_bone_xpbd_objects(
    values,
    *,
    property_origin: str,
    pin_override: bool | None,
) -> tuple[BoneXpbdObjectSpec, ...]:
    """保留显式集合顺序；单骨输入按 Armature 合并成一个集合。"""

    collections = []
    loose_by_armature: dict[tuple[int, int], dict] = {}
    seen_collections = set()
    for value in _flatten(values):
        parsed = _bone_collection(value)
        if parsed is None:
            raise TypeError("Bone XPBD 对象只接受 Bone socket 值")
        armature, names, root = parsed
        key = (_pointer(armature), _pointer(getattr(armature, "data", None)))
        is_collection = bool(
            isinstance(value, dict)
            and (value.get("bone_collection") or value.get("bones"))
        )
        if is_collection:
            collection_key = (*key, names)
            if collection_key in seen_collections:
                continue
            seen_collections.add(collection_key)
            collections.append((armature, names, root))
            continue
        group = loose_by_armature.setdefault(key, {
            "armature": armature,
            "names": [],
            "seen": set(),
        })
        for name in names:
            if name not in group["seen"]:
                group["seen"].add(name)
                group["names"].append(name)

    collections.extend(
        (group["armature"], tuple(group["names"]), group["names"][0])
        for group in loose_by_armature.values()
        if group["names"]
    )
    result = tuple(
        BoneXpbdObjectSpec(
            armature,
            names,
            root,
            property_origin=property_origin,
            pin_overrides=(pin_override,) * len(names),
        )
        for armature, names, root in collections
    )
    occupied = set()
    for item in result:
        for name in item.bone_names:
            key = (item.armature_ptr, item.armature_data_ptr, name)
            if key in occupied:
                raise ValueError(f"Bone XPBD 输入集合重复包含骨骼 {name!r}")
            occupied.add(key)
    return result


def read_bone_xpbd_panel_objects(values) -> tuple[BoneXpbdObjectSpec, ...]:
    """读取公共 Bone Pin 与隐式覆写；对象节点本身不修改属性。"""

    return _make_bone_xpbd_objects(
        values,
        property_origin="panel",
        pin_override=None,
    )


def make_bone_xpbd_custom_objects(
    values,
    *,
    pin_enabled: bool = False,
) -> tuple[BoneXpbdObjectSpec, ...]:
    """只使用 socket Pin 值，不读取或修改公共 Bone 面板。"""

    if type(pin_enabled) is not bool:
        raise TypeError("Bone XPBD自定义对象的Pin启用必须是bool")
    return _make_bone_xpbd_objects(
        values,
        property_origin="socket",
        pin_override=pin_enabled,
    )


__all__ = [
    "BoneXpbdObjectSpec",
    "make_bone_xpbd_custom_objects",
    "read_bone_xpbd_panel_objects",
]
