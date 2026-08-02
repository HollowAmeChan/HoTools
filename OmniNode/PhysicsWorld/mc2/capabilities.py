"""统一 MC2 solver 的参数、setup 与 Field consumer capability。"""

from ..field.names import AIR_VELOCITY_CHANNEL_ID, FIELD_CAPABILITY_ID
from .names import MC2_SETUP_TYPES


MC2_SETUP_PROFILE_CAPABILITY_ID = "mc2_setup_profile"
MC2_FIELD_AIR_VELOCITY_CAPABILITY_ID = "mc2_field_air_velocity"

MC2_SETUP_PROFILE_CAPABILITY = {
    "capability_id": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "identifier": MC2_SETUP_PROFILE_CAPABILITY_ID,
    "owner": "physicsWorld.mc2",
    "storage": "MC2PartitionCollectorPlan + MC2ParticleProfileSpec",
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
            "name": "partition_stable_id",
            "type": "string",
            "update_frequency": "topology",
        },
        {
            "name": "domain_signature",
            "type": "sha256",
            "update_frequency": "topology_or_parameter",
        },
        {
            "name": "output_target",
            "type": "object_data_identity",
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
    "implementation_status": "domain_v1_product",
}

MC2_FIELD_AIR_VELOCITY_CAPABILITY = {
    "capability_id": MC2_FIELD_AIR_VELOCITY_CAPABILITY_ID,
    "identifier": MC2_FIELD_AIR_VELOCITY_CAPABILITY_ID,
    "owner": "physicsWorld.mc2",
    "source_capability_id": FIELD_CAPABILITY_ID,
    "channel": AIR_VELOCITY_CHANNEL_ID,
    "channel_id": AIR_VELOCITY_CHANNEL_ID,
    "rank": "vector",
    "unit": "m/s",
    "value_space": "world",
    "sample_mode": "per_particle",
    "sample_phase": "pre_substep",
    "response": "hotools_relative_air_velocity_v0",
    "runtime": "PhysicsWorld.FieldRuntimeV1",
    "runtime_abi_version": 1,
    "solver_abi": "scalar_handle_and_world_time_only",
    "particle_data_crossing_python_native": 0,
    "implementation_status": "native_direct_cpu_product_v1",
}

MC2_CAPABILITIES = {
    MC2_SETUP_PROFILE_CAPABILITY_ID: MC2_SETUP_PROFILE_CAPABILITY,
    MC2_FIELD_AIR_VELOCITY_CAPABILITY_ID: MC2_FIELD_AIR_VELOCITY_CAPABILITY,
}

MC2_UPDATE_FREQUENCY_TABLE = {
    "setup_type": "topology",
    "sources": "topology",
    "task_id": "topology",
    "partition_stable_id": "topology",
    "domain_signature": "topology_or_parameter_signature",
    "output_target": "object_data_identity",
    "source_signature": "topology",
    "enabled": "frame",
    "profile": "parameter_signature",
    "setup_options": "topology_or_parameter_signature",
    "step_scheduler_settings": "step_settings_signature",
    "collider_snapshot": "lazy_by_source_key",
    "field_runtime": "world_begin_compile_or_metadata_update",
    "field_consumer_scope": "domain_sync",
    "field_air_velocity": "native_pre_substep_from_domain_owned_positions",
    "field_wind_response": "native_center_inertia_before_integration",
}


__all__ = [
    "MC2_CAPABILITIES",
    "MC2_FIELD_AIR_VELOCITY_CAPABILITY",
    "MC2_FIELD_AIR_VELOCITY_CAPABILITY_ID",
    "MC2_SETUP_PROFILE_CAPABILITY",
    "MC2_SETUP_PROFILE_CAPABILITY_ID",
    "MC2_UPDATE_FREQUENCY_TABLE",
]
