"""Physics World public Scene, Collection, and View Layer ownership helpers."""

from __future__ import annotations

import bpy


_COLLECTION_ROLE_KEY = "hotools_physics_world_collection_role"


def is_live_blender_id(value) -> bool:
    if value is None:
        return False
    try:
        value.as_pointer()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False


def scene_contains_object(scene, obj) -> bool:
    if not is_live_blender_id(scene) or not is_live_blender_id(obj):
        return False
    try:
        return scene.objects.get(obj.name_full) == obj
    except (AttributeError, ReferenceError):
        return False


def resolve_object_scene(
    obj: bpy.types.Object,
    preferred_scene: bpy.types.Scene | None = None,
    *,
    purpose: str = "对象",
) -> bpy.types.Scene:
    if not is_live_blender_id(obj):
        raise ValueError(f"{purpose}必须是有效的Blender对象")
    if preferred_scene is not None:
        if not scene_contains_object(preferred_scene, obj):
            raise ValueError(f"{purpose}的目标Scene不包含该对象")
        return preferred_scene

    context_scene = getattr(bpy.context, "scene", None)
    if scene_contains_object(context_scene, obj):
        return context_scene

    try:
        owner_scenes = tuple(obj.users_scene)
    except (AttributeError, ReferenceError):
        owner_scenes = ()
    if not owner_scenes:
        raise ValueError(f"{purpose}没有归属Scene")
    return min(owner_scenes, key=lambda item: str(item.name_full))


def scene_contains_collection(scene, collection) -> bool:
    if not is_live_blender_id(scene) or not is_live_blender_id(collection):
        return False
    pending = list(getattr(scene.collection, "children", ()))
    while pending:
        child = pending.pop(0)
        if child == collection:
            return True
        pending[0:0] = list(getattr(child, "children", ()))
    return False


def _scene_collection_for_role(scene, logical_name: str):
    pending = list(scene.collection.children)
    while pending:
        collection = pending.pop(0)
        try:
            role = str(collection.get(_COLLECTION_ROLE_KEY, "") or "")
        except (AttributeError, ReferenceError):
            role = ""
        if role == logical_name or collection.name == logical_name:
            return collection
        pending[0:0] = list(collection.children)
    return None


def _collection_owner_scenes(collection) -> tuple[bpy.types.Scene, ...]:
    return tuple(
        scene
        for scene in bpy.data.scenes
        if scene_contains_collection(scene, collection)
    )


def _layer_collection_path(view_layer, collection):
    try:
        view_layer.update()
        pending = [
            (child, (child,))
            for child in view_layer.layer_collection.children
        ]
        while pending:
            child, path = pending.pop(0)
            if child.collection == collection:
                return path
            pending[0:0] = [
                (nested, (*path, nested))
                for nested in child.children
            ]
        return ()
    except (AttributeError, ReferenceError):
        return ()


def ensure_scene_collection(
    scene: bpy.types.Scene,
    collection_name: str,
) -> tuple[bpy.types.Collection, tuple[bpy.types.ViewLayer, ...]]:
    if not is_live_blender_id(scene):
        raise ValueError("目标Scene无效")
    name = str(collection_name or "").strip()
    if not name:
        raise ValueError("Collection名称不能为空")

    collection = _scene_collection_for_role(scene, name)
    if collection is None:
        candidate = bpy.data.collections.get(name)
        if candidate is not None and not _collection_owner_scenes(candidate):
            collection = candidate
        else:
            collection = bpy.data.collections.new(name)
        collection[_COLLECTION_ROLE_KEY] = name
        try:
            scene.collection.children.link(collection)
        except RuntimeError as exc:
            raise ValueError(f"无法把Collection {name}链接到目标Scene") from exc
    else:
        collection[_COLLECTION_ROLE_KEY] = name

    collection.hide_viewport = False
    view_layers = tuple(scene.view_layers)
    for view_layer in view_layers:
        layer_path = _layer_collection_path(view_layer, collection)
        if not layer_path:
            raise ValueError(f"Collection {name}没有进入View Layer {view_layer.name}")
        for layer_collection in layer_path:
            layer_collection.exclude = False
            layer_collection.hide_viewport = False
    return collection, view_layers


def view_layer_contains_object(view_layer, obj) -> bool:
    if view_layer is None or not is_live_blender_id(obj):
        return False
    try:
        view_layer.update()
        return view_layer.objects.get(obj.name_full) == obj
    except (AttributeError, ReferenceError):
        return False


def view_layer_contains_collection(view_layer, collection) -> bool:
    if view_layer is None or not is_live_blender_id(collection):
        return False
    return bool(_layer_collection_path(view_layer, collection))


def link_object_to_scene_collection(
    obj: bpy.types.Object,
    scene: bpy.types.Scene,
    collection_name: str,
    *,
    hide_in_viewport: bool = False,
    unlink_other_collections: bool = False,
) -> bpy.types.Collection:
    if not is_live_blender_id(obj):
        raise ValueError("待链接对象无效")
    collection, view_layers = ensure_scene_collection(scene, collection_name)
    if not any(item == obj for item in collection.objects):
        collection.objects.link(obj)
    if unlink_other_collections:
        for owner in tuple(obj.users_collection):
            if owner != collection:
                owner.objects.unlink(obj)

    obj.hide_viewport = False
    for view_layer in view_layers:
        if not view_layer_contains_object(view_layer, obj):
            raise ValueError(
                f"对象 {obj.name_full}没有进入View Layer {view_layer.name}"
            )
        obj.hide_set(bool(hide_in_viewport), view_layer=view_layer)
        if not view_layer_contains_object(view_layer, obj):
            raise ValueError(
                f"对象 {obj.name_full}在隐藏后脱离View Layer {view_layer.name}"
            )
    return collection


__all__ = [
    "ensure_scene_collection",
    "is_live_blender_id",
    "link_object_to_scene_collection",
    "resolve_object_scene",
    "scene_contains_collection",
    "scene_contains_object",
    "view_layer_contains_collection",
    "view_layer_contains_object",
]
