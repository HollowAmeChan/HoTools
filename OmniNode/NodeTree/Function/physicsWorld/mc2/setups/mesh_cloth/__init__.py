"""统一 MC2 solver 的 MeshCloth setup Blender adapter。"""

from importlib import import_module

from ....names import GN_ATTRIBUTE_CHANNEL
from ...names import MC2_SETUP_MESH_CLOTH
from ...topology import build_mc2_mesh_source_topology
from ...initial_state import build_mc2_mesh_initial_state
from ..contracts import MC2SetupAdapterContract


MC2_MESH_CLOTH_SETUP_ADAPTER = MC2SetupAdapterContract(
    setup_type=MC2_SETUP_MESH_CLOTH,
    source_kind="mesh_object",
    writeback_channel=GN_ATTRIBUTE_CHANNEL,
    topology_builder=build_mc2_mesh_source_topology,
    initial_state_builder=build_mc2_mesh_initial_state,
)


_EXPORTS = {
    "MC2MeshFinalProxyBuildResult": ".final_proxy",
    "MESH_COLLISION_CAPABILITY": ".capabilities",
    "MESH_COLLISION_CAPABILITY_ID": ".capabilities",
    "MESH_CLOTH_CAPABILITIES": ".capabilities",
    "MESH_COLLISION_RNA_FIELDS": ".schema",
    "MESH_CLOTH_BLENDER_PROPERTIES": ".properties",
    "PG_Hotools_MeshCollision": ".properties",
    "build_blender_mesh_final_proxy": ".final_proxy",
    "build_mc2_mesh_final_proxy": ".final_proxy",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = ["MC2_MESH_CLOTH_SETUP_ADAPTER", *sorted(_EXPORTS)]
