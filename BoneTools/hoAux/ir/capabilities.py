"""Capability derivation from one-to-one Source IR records."""


def derive_capabilities(resource) -> list[str]:
    kind = resource.resource_kind
    payload = resource.payload
    capabilities = set()

    if kind == "CONSTRAINT":
        constraint_type = payload.get("type")
        if constraint_type:
            capabilities.add(f"CONSTRAINT:{constraint_type}")
        for field in ("ownerSpace", "targetSpace"):
            value = payload.get(field)
            if value:
                capabilities.add(f"SPACE:{value}")
        if payload.get("headTail") == 1.0:
            capabilities.add("TARGET_POINT:TAIL")
        if constraint_type == "STRETCH_TO":
            keep_axis = payload.get("keepAxis")
            volume = payload.get("volume")
            if keep_axis:
                capabilities.add(f"STRETCH:{keep_axis}")
            if volume:
                capabilities.add(f"STRETCH:{volume}")
    elif kind == "DRIVER":
        capabilities.add(f"DRIVER:{payload.get('type', 'UNKNOWN')}")
        if payload.get("expression"):
            capabilities.add("DRIVER:SCRIPTED_EXPRESSION")
    elif kind == "DRIVER_VARIABLE":
        variable_type = payload.get("type")
        if variable_type:
            capabilities.add(f"DRIVER_VARIABLE:{variable_type}")
        transform_space = payload.get("transformSpace")
        if transform_space:
            capabilities.add(f"DRIVER_TARGET:{transform_space}")
    elif kind == "BONE_COLLECTION":
        capabilities.add("ORGANIZATION:BONE_COLLECTION")
        if payload.get("parentCollectionKey"):
            capabilities.add("ORGANIZATION:NESTED_COLLECTION")

    return sorted(capabilities)
