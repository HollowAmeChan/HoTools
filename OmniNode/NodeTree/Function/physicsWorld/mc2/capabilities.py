"""统一 MC2 solver 的参数与 setup capability。"""

from .names import MC2_SETUP_TYPES


MC2_SETUP_PROFILE_CAPABILITY_ID = "mc2_setup_profile"

MC2_SETUP_PROFILE_CAPABILITY = {
    "capability_id": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "identifier": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "owner": "physicsWorld.mc2",
    "storage": "immutable MC2TaskSpec + MC2ParticleProfileSpec",
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
        {
            "name": "profile",
            "type": "MC2ParticleProfileSpec",
            "update_frequency": "parameter",
        },
        {
            "name": "setup_options",
            "type": "MC2SetupOptionsSpec",
            "update_frequency": "topology_or_parameter",
        },
        {
            "name": "topology_signature",
            "type": "sha256",
            "update_frequency": "topology",
        },
        {
            "name": "parameter_signature",
            "type": "sha256",
            "update_frequency": "parameter",
        },
    ),
    "implementation_status": "native_context_framework",
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
    "profile": "parameter_signature",
    "setup_options": "topology_or_parameter_signature",
    "step_scheduler_settings": "step_settings_signature",
    "collider_snapshot": "lazy_by_source_key",
}
