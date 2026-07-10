"""MC2 BoneSpring setup adapter contract。"""

from ....names import BONE_TRANSFORM_CHANNEL
from ...names import MC2_SETUP_BONE_SPRING
from ..contracts import MC2SetupAdapterContract


MC2_BONE_SPRING_SETUP_ADAPTER = MC2SetupAdapterContract(
    setup_type=MC2_SETUP_BONE_SPRING,
    source_kind="bone_chain",
    writeback_channel=BONE_TRANSFORM_CHANNEL,
)


__all__ = ["MC2_BONE_SPRING_SETUP_ADAPTER"]
