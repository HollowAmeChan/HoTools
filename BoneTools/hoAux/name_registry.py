"""Name allocation and stable HoAux bone lookup."""


def iter_hoaux_bones(armature_data):
    for bone in armature_data.bones:
        props = getattr(bone, "hotools_boneprops", None)
        info = getattr(props, "hoAux", None) if props else None
        if info is not None and info.isHoAuxBone:
            yield bone


def find_bone_by_key(armature_data, name_key: str):
    if not name_key:
        return None
    for bone in iter_hoaux_bones(armature_data):
        if bone.hotools_boneprops.hoAux.nameKey == name_key:
            return bone
    return None


def allocate_bone_name(armature_data, preferred_name: str) -> str:
    if armature_data.bones.get(preferred_name) is None:
        return preferred_name
    index = 1
    while armature_data.bones.get(f"{preferred_name}.{index:03d}") is not None:
        index += 1
    return f"{preferred_name}.{index:03d}"
