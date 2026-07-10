"""MeshCloth solver/domain capability。"""

from .schema import MESH_COLLISION_RNA_FIELDS


MESH_COLLISION_CAPABILITY_ID = "mesh_collision"


def _capability_fields() -> list[dict]:
    semantic_types = {
        "pointer": "Object",
        "bool": "bool",
        "float": "float",
        "string": "string",
        "int": "int",
    }
    result = []
    for declaration in MESH_COLLISION_RNA_FIELDS:
        name = str(declaration["name"])
        kwargs = dict(declaration.get("kwargs") or {})
        result.append({
            "name": name,
            "type": "bitmask" if name == "collided_by_groups" else semantic_types[str(declaration["property"])],
            "default": kwargs.get("default"),
            "explicit_property": f"Object.hotools_mesh_collision.{name}",
            "rna": kwargs,
            "update_policy": "restart_only" if name in {"pin_enabled", "pin_vertex_group"} else "solver_spec_or_live_snapshot",
        })
    return result


MESH_COLLISION_CAPABILITY = {
    "capability_id": MESH_COLLISION_CAPABILITY_ID,
    "display_name": "网格布料碰撞",
    "semantic_owner": "physicsWorld.mesh_cloth",
    "explicit_storage": "Object.hotools_mesh_collision",
    "fields": _capability_fields(),
}

MESH_CLOTH_CAPABILITIES = {
    MESH_COLLISION_CAPABILITY_ID: MESH_COLLISION_CAPABILITY,
}


__all__ = [
    "MESH_COLLISION_CAPABILITY",
    "MESH_COLLISION_CAPABILITY_ID",
    "MESH_CLOTH_CAPABILITIES",
]
