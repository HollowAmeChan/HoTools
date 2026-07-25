"""Additive nested Bone Collection management for HoAux."""

from .properties import ensure_rig_id


COLLECTION_KEY_PROP = "hoaux_key"
COLLECTION_RIG_PROP = "hoaux_rig_id"


def find_collection(armature_data, collection_key: str):
    collections = getattr(armature_data, "collections_all", armature_data.collections)
    for collection in collections:
        if collection.get(COLLECTION_KEY_PROP) == collection_key:
            return collection
    return None


def ensure_collection(
    armature_data,
    collection_key: str,
    preferred_name: str,
    parent=None,
    *,
    visible_on_create=True,
):
    collection = find_collection(armature_data, collection_key)
    if collection is None:
        collection = armature_data.collections.new(preferred_name)
        collection[COLLECTION_KEY_PROP] = collection_key
        collection[COLLECTION_RIG_PROP] = ensure_rig_id(armature_data)
        collection.is_visible = visible_on_create
    if parent is not None and collection.parent != parent:
        collection.parent = parent
    return collection


def ensure_base_tree(armature_data):
    root = ensure_collection(
        armature_data,
        "HOAUX:ROOT",
        "HoAux",
        visible_on_create=True,
    )
    return {"root": root}


def collections_for_bone(armature_data, info):
    tree = ensure_base_tree(armature_data)
    tag = info.roleTag if info.roleTag in {"DEF", "TRK", "DIR"} else "OTHER"
    return [
        ensure_collection(
            armature_data,
            f"HOAUX:TAG:{tag}",
            tag,
            tree["root"],
            visible_on_create=tag == "DEF",
        )
    ]


def assign_bone(armature_data, bone):
    info = bone.hotools_boneprops.hoAux
    if not info.isHoAuxBone:
        return []
    assigned = []
    for collection in collections_for_bone(armature_data, info):
        collection.assign(bone)
        assigned.append(collection)
    return assigned
