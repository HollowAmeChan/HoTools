"""简单布料公共 capability。"""

from .schema import SIMPLE_CLOTH_RNA_FIELDS


SIMPLE_CLOTH_CAPABILITY_ID = "simple_cloth"


def _capability_fields() -> list[dict]:
    semantic_types = {
        "pointer": "Object",
        "bool": "bool",
        "float": "float",
        "string": "string",
        "int": "int",
    }
    result = []
    for declaration in SIMPLE_CLOTH_RNA_FIELDS:
        name = str(declaration["name"])
        kwargs = dict(declaration.get("kwargs") or {})
        result.append({
            "name": name,
            "type": (
                "bitmask"
                if name == "collided_by_groups"
                else semantic_types[str(declaration["property"])]
            ),
            "default": kwargs.get("default"),
            "explicit_property": f"Object.hotools_mesh_collision.{name}",
            "rna": kwargs,
            "update_policy": (
                "authoring_filter"
                if name == "enabled"
                else "restart_only"
                if name in {"pin_enabled", "pin_vertex_group"}
                else "public_object_resource_or_solver_snapshot"
            ),
        })
    return result


SIMPLE_CLOTH_CAPABILITY = {
    "capability_id": SIMPLE_CLOTH_CAPABILITY_ID,
    "display_name": "简单布料",
    "semantic_owner": "physicsWorld.simple_cloth",
    "explicit_storage": "Object.hotools_mesh_collision",
    "fields": _capability_fields(),
    "managed_resources": (
        "BasePose只读对象",
        "HoPhysicsCache Scene/View Layer归属",
        "共享GN最终顶点offset",
    ),
}

SIMPLE_CLOTH_CAPABILITIES = {
    SIMPLE_CLOTH_CAPABILITY_ID: SIMPLE_CLOTH_CAPABILITY,
}

# 兼容旧适配器名称；capability identifier 不再误称 mesh_collision。
MESH_COLLISION_CAPABILITY_ID = SIMPLE_CLOTH_CAPABILITY_ID
MESH_COLLISION_CAPABILITY = SIMPLE_CLOTH_CAPABILITY
MESH_CLOTH_CAPABILITIES = SIMPLE_CLOTH_CAPABILITIES


__all__ = [
    "MESH_CLOTH_CAPABILITIES",
    "MESH_COLLISION_CAPABILITY",
    "MESH_COLLISION_CAPABILITY_ID",
    "SIMPLE_CLOTH_CAPABILITIES",
    "SIMPLE_CLOTH_CAPABILITY",
    "SIMPLE_CLOTH_CAPABILITY_ID",
]
