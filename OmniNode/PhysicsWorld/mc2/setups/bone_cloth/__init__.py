"""MC2 BoneCloth setup adapter contract。"""

from ....names import BONE_TRANSFORM_CHANNEL
from ...names import MC2_SETUP_BONE_CLOTH
from ..contracts import MC2SetupAdapterContract


MC2_BONE_CLOTH_SETUP_ADAPTER = MC2SetupAdapterContract(
    setup_type=MC2_SETUP_BONE_CLOTH,
    source_kind="bone_chain",
    writeback_channel=BONE_TRANSFORM_CHANNEL,
    topology_builder_name="build_mc2_bone_source_topology",
)


__all__ = ["MC2_BONE_CLOTH_SETUP_ADAPTER"]
