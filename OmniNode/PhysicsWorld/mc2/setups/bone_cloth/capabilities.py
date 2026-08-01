"""MC2 BoneCloth adapters for shared Physics World capabilities."""

from ....collision.capabilities import BONE_COLLISION_CAPABILITY_ID


MC2_BONE_CLOTH_BONE_COLLISION_ADAPTER = {
    "capability_id": BONE_COLLISION_CAPABILITY_ID,
    "setup_type": "bone_cloth",
    "source_scope": "simulated_chain_bones",
    "activation": "panel_object_only",
    "consumes": {
        "radius": {
            "target": "particle.radius",
            "conversion": "absolute_blender_units",
            "terminal_policy": "inherit_last_real_bone",
            "update_policy": "static_fragment_rebuild",
        },
        "collided_by_groups": {
            "target": "particle.external_collision_mask",
            "conversion": "direct_16_bit_mask_per_simulated_bone",
            "granularity": "particle",
            "terminal_policy": "inherit_last_real_bone",
            "update_policy": "static_fragment_rebuild",
        },
    },
    "not_consumed_as_particle_radius": (
        "collision_type",
        "length",
        "offset",
    ),
    "custom_object_fallback": "MC2ParticleProfileSpec.radius_curve",
}


__all__ = ["MC2_BONE_CLOTH_BONE_COLLISION_ADAPTER"]
