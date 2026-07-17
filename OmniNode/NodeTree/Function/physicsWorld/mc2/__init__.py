"""Physics World MC2 solver registration manifest.

Public behavior lives in explicit submodules. This package root intentionally
does not re-export solver APIs or provide compatibility attribute forwarding.
"""


COMPONENT_MODULE = {
    "component_id": "mc2",
    "kind": "solver_adapter",
    "depends_on": ("collision",),
    "capabilities": ".setups.mesh_cloth.capabilities:MESH_CLOTH_CAPABILITIES",
    "blender_properties": ".setups.mesh_cloth.properties:MESH_CLOTH_BLENDER_PROPERTIES",
}


SOLVER_MODULE = {
    "domain": "mc2",
    "solver_id": "mc2",
    "declaration": ".declaration:MC2_SOLVER_DECLARATION",
    "nodes": (".nodes",),
    "capabilities": ".capabilities:MC2_CAPABILITIES",
    "debug_draw_modes": ".debug:MC2_DEBUG_DRAW_MODES",
}


__all__ = ["COMPONENT_MODULE", "SOLVER_MODULE"]
