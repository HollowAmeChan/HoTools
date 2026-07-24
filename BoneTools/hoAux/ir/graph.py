"""Derived reverse edges and scope traversal for a Source IR snapshot."""

from .model import ResourceEdge


def build_reverse_edges(resources) -> None:
    by_key = {resource.resource_key: resource for resource in resources}
    for resource in resources:
        resource.used_by.clear()
    for resource in resources:
        for edge in resource.uses:
            target = by_key.get(edge.resource_key)
            if target is None:
                continue
            target.used_by.append(
                ResourceEdge(
                    relation=edge.relation,
                    resource_key=resource.resource_key,
                    details=dict(edge.details),
                )
            )


def dependency_closure(resources, roots) -> set[str]:
    by_key = {resource.resource_key: resource for resource in resources}
    pending = list(roots)
    result = set()
    while pending:
        key = pending.pop()
        if key in result:
            continue
        result.add(key)
        resource = by_key.get(key)
        if resource is None:
            continue
        pending.extend(resource.owns)
        pending.extend(edge.resource_key for edge in resource.uses)
    return result
