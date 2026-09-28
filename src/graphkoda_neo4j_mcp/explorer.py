from __future__ import annotations

from collections import deque
import re
from typing import Any

from .limits import ServerLimits
from .serialization import enforce_output_budget
from .store import GraphStore


NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_PROPERTIES = [
    "stableId",
    "nodeid",
    "name",
    "kind",
    "runId",
    "sessionId",
    "traceId",
    "timestamp",
    "duration",
    "status",
]


class BoundedExplorer:
    def __init__(
        self,
        store: GraphStore,
        limits: ServerLimits,
        allowed_relationship_types: set[str],
    ):
        self.store = store
        self.limits = limits
        self.allowed_relationship_types = allowed_relationship_types

    def _validate_common(
        self,
        *,
        start_ids: list[str],
        id_property: str,
        relationship_types: list[str] | None,
        direction: str,
        property_names: list[str] | None,
    ) -> tuple[list[str], list[str]]:
        if not start_ids or len(start_ids) > self.limits.max_seeds:
            raise ValueError(f"start_ids must contain between 1 and {self.limits.max_seeds} values")
        if any(not isinstance(value, str) or not value or len(value) > 1_000 for value in start_ids):
            raise ValueError("Every start identifier must be a non-empty string of at most 1000 characters")
        if id_property not in {"stableId", "nodeid"}:
            raise ValueError("id_property must be stableId or nodeid")
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("direction must be outgoing, incoming or both")

        selected_types = relationship_types or sorted(self.allowed_relationship_types)
        if not selected_types:
            raise ValueError("At least one relationship type is required")
        unknown = set(selected_types) - self.allowed_relationship_types
        if unknown:
            raise ValueError(f"Relationship types are not allowed: {', '.join(sorted(unknown))}")

        selected_properties = list(property_names or DEFAULT_PROPERTIES)
        if id_property not in selected_properties:
            selected_properties.insert(0, id_property)
        if len(selected_properties) > self.limits.max_properties:
            raise ValueError(f"property_names cannot contain more than {self.limits.max_properties} values")
        if any(not NAME.fullmatch(name) for name in selected_properties):
            raise ValueError("property_names must contain simple Neo4j property names")
        return list(dict.fromkeys(selected_types)), list(dict.fromkeys(selected_properties))

    def inspect_neighborhood(
        self,
        *,
        start_ids: list[str],
        id_property: str = "stableId",
        relationship_types: list[str] | None = None,
        direction: str = "both",
        max_depth: int = 3,
        max_nodes: int = 100,
        max_edges: int = 200,
        property_names: list[str] | None = None,
        node_filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        types, properties = self._validate_common(
            start_ids=start_ids,
            id_property=id_property,
            relationship_types=relationship_types,
            direction=direction,
            property_names=property_names,
        )
        request_limits = self.limits.resolve(
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        filters = node_filters or {}
        if len(filters) > 5 or any(not NAME.fullmatch(name) for name in filters):
            raise ValueError("node_filters supports at most five simple Neo4j property names")
        if any(not isinstance(value, str) or len(value) > 1_000 for value in filters.values()):
            raise ValueError("node_filters values must be strings of at most 1000 characters")
        reasons: list[str] = []
        resolved = self.store.resolve_nodes(
            list(dict.fromkeys(start_ids)),
            id_property,
            properties,
            request_limits.max_nodes + 1,
            request_limits.query_timeout_seconds,
        )
        if len(resolved) > request_limits.max_nodes:
            reasons.append("node-limit")
            resolved = resolved[: request_limits.max_nodes]

        nodes = {node["elementId"]: node for node in resolved}
        seed_element_ids = list(nodes)
        frontier = list(nodes)
        visited = set(frontier)
        edges: dict[str, dict[str, Any]] = {}
        depth_reached = 0

        for depth in range(1, request_limits.max_depth + 1):
            if not frontier:
                break
            remaining_edges = request_limits.max_edges - len(edges)
            if remaining_edges <= 0:
                reasons.append("edge-limit")
                break
            rows = self.store.fetch_neighbors(
                frontier,
                types,
                direction,
                properties,
                filters,
                remaining_edges + 1,
                request_limits.query_timeout_seconds,
            )
            if len(rows) > remaining_edges:
                reasons.append("edge-limit")
                rows = rows[:remaining_edges]

            next_frontier: list[str] = []
            node_limit_hit = False
            for row in rows:
                edge = row["relationship"]
                if edge["elementId"] in edges:
                    continue
                endpoints = [row["source"], row["target"]]
                missing = [node for node in endpoints if node["elementId"] not in nodes]
                if len(nodes) + len({node["elementId"] for node in missing}) > request_limits.max_nodes:
                    node_limit_hit = True
                    continue
                edges[edge["elementId"]] = edge
                for node in missing:
                    nodes[node["elementId"]] = node
                    if node["elementId"] not in visited:
                        visited.add(node["elementId"])
                        next_frontier.append(node["elementId"])
            depth_reached = depth
            if node_limit_hit:
                reasons.append("node-limit")
                break
            frontier = next_frontier

        payload = {
            "startIds": start_ids,
            "idProperty": id_property,
            "relationshipTypes": types,
            "direction": direction,
            "nodeFilters": filters,
            "depthReached": depth_reached,
            "seedElementIds": seed_element_ids,
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "limits": request_limits.as_dict(),
            "truncation": {"truncated": bool(reasons), "reasons": list(dict.fromkeys(reasons))},
        }
        return enforce_output_budget(payload, request_limits.max_output_bytes)

    def find_paths(
        self,
        *,
        from_id: str,
        to_id: str,
        id_property: str = "stableId",
        relationship_types: list[str] | None = None,
        direction: str = "outgoing",
        max_depth: int = 4,
        max_paths: int = 20,
        max_nodes: int = 150,
        max_edges: int = 300,
        property_names: list[str] | None = None,
        node_filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_limits = self.limits.resolve(
            max_depth=max_depth,
            max_paths=max_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        graph = self.inspect_neighborhood(
            start_ids=[from_id],
            id_property=id_property,
            relationship_types=relationship_types,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            property_names=property_names,
            node_filters=node_filters,
        )
        target_ids = {
            node["elementId"]
            for node in graph.get("nodes", [])
            if node.get("properties", {}).get(id_property) == to_id
        }
        adjacency: dict[str, list[tuple[str, str]]] = {}
        for edge in graph.get("edges", []):
            source, target = edge["source"], edge["target"]
            if direction in {"outgoing", "both"}:
                adjacency.setdefault(source, []).append((target, edge["elementId"]))
            if direction in {"incoming", "both"}:
                adjacency.setdefault(target, []).append((source, edge["elementId"]))

        queue = deque((seed, [seed], []) for seed in graph.get("seedElementIds", []))
        paths: list[dict[str, list[str]]] = []
        while queue and len(paths) < request_limits.max_paths:
            current, node_path, edge_path = queue.popleft()
            if current in target_ids:
                paths.append({"nodeElementIds": node_path, "edgeElementIds": edge_path})
                continue
            if len(edge_path) >= request_limits.max_depth:
                continue
            for neighbor, edge_id in adjacency.get(current, []):
                if neighbor not in node_path:
                    queue.append((neighbor, [*node_path, neighbor], [*edge_path, edge_id]))

        reasons = list(graph.get("truncation", {}).get("reasons", []))
        if queue and len(paths) >= request_limits.max_paths:
            reasons.append("path-limit")
        payload = {
            "fromId": from_id,
            "toId": to_id,
            "idProperty": id_property,
            "paths": paths,
            "pathCount": len(paths),
            "nodes": graph.get("nodes", []),
            "edges": graph.get("edges", []),
            "limits": request_limits.as_dict(),
            "truncation": {"truncated": bool(reasons), "reasons": list(dict.fromkeys(reasons))},
        }
        return enforce_output_budget(payload, request_limits.max_output_bytes)
