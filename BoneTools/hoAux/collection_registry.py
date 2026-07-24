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
):
    collection = find_collection(armature_data, collection_key)
    if collection is None:
        collection = armature_data.collections.new(preferred_name)
        collection[COLLECTION_KEY_PROP] = collection_key
        collection[COLLECTION_RIG_PROP] = ensure_rig_id(armature_data)
    if parent is not None and collection.parent != parent:
        collection.parent = parent
    return collection


def ensure_base_tree(armature_data):
    root = ensure_collection(armature_data, "HOAUX:ROOT", "HoAux")
    pipelines = ensure_collection(
        armature_data, "HOAUX:PIPELINES", "Pipelines", root
    )
    infrastructure = ensure_collection(
        armature_data, "HOAUX:INFRASTRUCTURE", "Infrastructure", root
    )
    filters = ensure_collection(armature_data, "HOAUX:FILTERS", "Filters", root)
    role = ensure_collection(armature_data, "HOAUX:FILTERS:ROLE", "Role", filters)
    part = ensure_collection(armature_data, "HOAUX:FILTERS:PART", "Part", filters)
    side = ensure_collection(armature_data, "HOAUX:FILTERS:SIDE", "Side", filters)

    # Filter collections are indexes. Keeping the branch hidden prevents their
    # OR visibility semantics from overriding the structural pipeline branch.
    filters.is_visible = False
    return {
        "root": root,
        "pipelines": pipelines,
        "infrastructure": infrastructure,
        "filters": filters,
        "role": role,
        "part": part,
        "side": side,
    }


def _label(value: str, fallback: str) -> str:
    return value.strip() if value and value.strip() else fallback


def collections_for_bone(armature_data, info):
    tree = ensure_base_tree(armature_data)
    result = []

    if info.roleTag == "DIR":
        result.append(
            ensure_collection(
                armature_data,
                "HOAUX:INFRASTRUCTURE:SHARED_DIR",
                "Shared DIR",
                tree["infrastructure"],
            )
        )
    else:
        pipeline_id = _label(info.pipelineId, "UNASSIGNED")
        pipeline = ensure_collection(
            armature_data,
            f"HOAUX:PIPELINE:{pipeline_id}",
            pipeline_id,
            tree["pipelines"],
        )
        module_id = _label(info.moduleId, "UNASSIGNED")
        result.append(
            ensure_collection(
                armature_data,
                f"HOAUX:MODULE:{pipeline_id}:{module_id}",
                _label(info.moduleType, module_id),
                pipeline,
            )
        )

    if info.roleTag != "NONE":
        result.append(
            ensure_collection(
                armature_data,
                f"HOAUX:FILTER:ROLE:{info.roleTag}",
                info.roleTag,
                tree["role"],
            )
        )
    if info.part:
        result.append(
            ensure_collection(
                armature_data,
                f"HOAUX:FILTER:PART:{info.part}",
                info.part,
                tree["part"],
            )
        )
    if info.side != "NONE":
        result.append(
            ensure_collection(
                armature_data,
                f"HOAUX:FILTER:SIDE:{info.side}",
                info.side,
                tree["side"],
            )
        )
    return result


def assign_bone(armature_data, bone):
    info = bone.hotools_boneprops.hoAux
    if not info.isHoAuxBone:
        return []
    assigned = []
    for collection in collections_for_bone(armature_data, info):
        collection.assign(bone)
        assigned.append(collection)
    return assigned


def assign_all(armature_data):
    from .name_registry import iter_hoaux_bones

    ensure_base_tree(armature_data)
    count = 0
    for bone in iter_hoaux_bones(armature_data):
        assign_bone(armature_data, bone)
        count += 1
    return count


def prune_empty_system_collections(armature_data) -> int:
    removed = 0
    while True:
        collections = list(
            getattr(armature_data, "collections_all", armature_data.collections)
        )
        candidate = next(
            (
                collection
                for collection in reversed(collections)
                if collection.get(COLLECTION_KEY_PROP)
                and len(collection.bones) == 0
                and len(collection.children) == 0
            ),
            None,
        )
        if candidate is None:
            break
        armature_data.collections.remove(candidate)
        removed += 1
    return removed
