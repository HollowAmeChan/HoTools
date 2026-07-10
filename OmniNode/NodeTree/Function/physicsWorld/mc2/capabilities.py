"""统一 MC2 solver 的 setup profile capability。"""

from .names import MC2_SETUP_TYPES


MC2_SETUP_PROFILE_CAPABILITY_ID = "mc2_setup_profile"

MC2_SETUP_PROFILE_CAPABILITY = {
    "capability_id": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "identifier": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "owner": "physicsWorld.mc2",
    "storage": "normalized MC2TaskSpec",
    "fields": (
        {
            "name": "setup_type",
            "type": "enum",
            "values": MC2_SETUP_TYPES,
            "update_frequency": "topology",
        },
        {
            "name": "enabled",
            "type": "bool",
            "default": True,
            "update_frequency": "frame",
        },
        {
            "name": "task_id",
            "type": "string",
            "update_frequency": "topology",
        },
        {
            "name": "source_signature",
            "type": "sha256",
            "update_frequency": "topology",
        },
        {
            "name": "sources",
            "type": "tuple[source]",
            "update_frequency": "topology",
        },
    ),
    "implementation_status": "framework_only",
}

MC2_CAPABILITIES = {
    MC2_SETUP_PROFILE_CAPABILITY_ID: MC2_SETUP_PROFILE_CAPABILITY,
}

MC2_UPDATE_FREQUENCY_TABLE = {
    "setup_type": "topology",
    "sources": "topology",
    "task_id": "topology",
    "source_signature": "topology",
    "enabled": "frame",
    "solver_parameters": "frame",
    "collider_snapshot": "lazy_by_source_key",
}
