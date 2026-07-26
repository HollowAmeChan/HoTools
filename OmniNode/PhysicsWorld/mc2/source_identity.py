"""MC2 source 与 setup 的稳定身份，不依赖旧 task schema。"""

from __future__ import annotations

import json

from .names import MC2_SETUP_TYPES


def normalize_mc2_setup_type(value: object) -> str:
    setup_type = str(value or "").strip().lower()
    if setup_type not in MC2_SETUP_TYPES:
        raise ValueError(f"未知 MC2 setup_type: {value!r}")
    return setup_type


def mc2_pointer_token(value) -> dict | None:
    pointer = getattr(value, "as_pointer", None)
    if not callable(pointer):
        return None
    try:
        owner_ptr = int(pointer())
    except Exception as exc:
        raise ValueError(f"MC2 source 指针不可读: {value!r}") from exc
    if owner_ptr <= 0:
        raise ValueError(f"MC2 source 指针已失效: {value!r}")
    data = getattr(value, "data", None)
    data_pointer = getattr(data, "as_pointer", None)
    try:
        data_ptr = int(data_pointer()) if callable(data_pointer) else 0
    except Exception:
        data_ptr = 0
    return {
        "kind": "blender_id",
        "owner_ptr": owner_ptr,
        "data_ptr": data_ptr,
        "type": str(
            getattr(value, "type", type(value).__name__) or type(value).__name__
        ),
        "name": str(
            getattr(value, "name_full", getattr(value, "name", "")) or ""
        ),
    }


def mc2_source_token(source) -> dict:
    token_builder = getattr(source, "mc2_source_token", None)
    if callable(token_builder):
        token = token_builder()
        if not isinstance(token, dict) or not str(token.get("kind") or "").strip():
            raise TypeError("MC2 source token provider 必须返回带 kind 的 dict")
        try:
            json.dumps(
                token,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise TypeError("MC2 source token provider 返回了不可序列化数据") from exc
        return token

    pointer_token = mc2_pointer_token(source)
    if pointer_token is not None:
        return pointer_token

    if isinstance(source, dict):
        stable_id = str(
            source.get("stable_id") or source.get("source_id") or ""
        ).strip()
        if stable_id:
            return {"kind": "stable_id", "value": stable_id}

        armature = source.get("armature")
        armature_token = mc2_pointer_token(armature)
        root_bone = str(source.get("root_bone") or source.get("bone") or "").strip()
        bones = tuple(str(name) for name in (source.get("bones") or ()) if str(name))
        if armature_token is not None and (root_bone or bones):
            return {
                "kind": "bone_source",
                "armature": armature_token,
                "root_bone": root_bone,
                "bones": bones,
            }

        proxy = source.get("proxy_obj")
        if proxy is None:
            proxy = source.get("object")
        proxy_token = mc2_pointer_token(proxy)
        if proxy_token is not None:
            return {"kind": "object_source", "object": proxy_token}

        raise TypeError(
            "MC2 dict source 需要 stable_id/source_id、有效 armature+bone，"
            "或 proxy_obj/object"
        )

    if isinstance(source, tuple) and len(source) == 2:
        owner_token = mc2_pointer_token(source[0])
        name = str(source[1] or "").strip()
        if owner_token is not None and name:
            return {"kind": "owner_member", "owner": owner_token, "name": name}

    raise TypeError(f"不支持的 MC2 source: {type(source).__name__}")


__all__ = [
    "mc2_pointer_token",
    "mc2_source_token",
    "normalize_mc2_setup_type",
]
