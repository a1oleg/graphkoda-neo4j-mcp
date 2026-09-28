from __future__ import annotations

import atexit
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from neo4j import GraphDatabase

from .explorer import BoundedExplorer
from .limits import ServerLimits
from .store import Neo4jStore


DEFAULT_RELATIONSHIP_TYPES = {
    "STATIC_CALLS",
    "STATIC_DEF",
    "CALLS_AT_RUNTIME",
    "response",
    "AST_CHILD",
    "CONTAINS_STEP",
    "NEXT_STEP",
}
RUNTIME_OVERLAY_TYPES = ["STATIC_DEF", "CALLS_AT_RUNTIME", "response"]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

app = FastMCP(
    name="graphkoda-neo4j-mcp",
    instructions=(
        "Read-only bounded exploration of static and runtime code graphs. "
        "There is no arbitrary Cypher tool; every traversal and response is capped."
    ),
)

_driver: Any | None = None
_explorer: BoundedExplorer | None = None


def _allowed_types() -> set[str]:
    configured = os.getenv("GRAPHKODA_MCP_RELATIONSHIP_TYPES")
    return (
        {value.strip() for value in configured.split(",") if value.strip()}
        if configured
        else DEFAULT_RELATIONSHIP_TYPES
    )


def _get_explorer() -> BoundedExplorer:
    global _driver, _explorer
    if _explorer is not None:
        return _explorer

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or "neo4j"
    missing = [name for name, value in {
        "NEO4J_URI": uri,
        "NEO4J_USER/NEO4J_USERNAME": username,
        "NEO4J_PASSWORD": password,
    }.items() if not value]
    if missing:
        raise RuntimeError(f"Missing Neo4j settings: {', '.join(missing)}")

    _driver = GraphDatabase.driver(uri, auth=(username, password))
    _explorer = BoundedExplorer(
        Neo4jStore(_driver, database),
        ServerLimits.from_env(),
        _allowed_types(),
    )
    return _explorer


def _close_driver() -> None:
    if _driver is not None:
        _driver.close()


atexit.register(_close_driver)


@app.tool(
    description="Return the hard server ceilings enforced for every traversal and response.",
    annotations=READ_ONLY,
)
def get_limits() -> dict[str, Any]:
    limits = ServerLimits.from_env()
    return {
        "limits": limits.as_dict(),
        "allowedRelationshipTypes": sorted(_allowed_types()),
        "arbitraryCypherEnabled": False,
        "readOnly": True,
    }


@app.tool(
    description="Verify Neo4j connectivity without modifying the database.",
    annotations=READ_ONLY,
)
def check_connection() -> dict[str, Any]:
    explorer = _get_explorer()
    explorer.store.driver.verify_connectivity()
    return {"status": "ok", "database": explorer.store.database, "readOnly": True}


@app.tool(
    description=(
        "Expand a bounded neighborhood from explicit stableId or nodeid seeds. "
        "Only allowlisted relationship types are traversed."
    ),
    annotations=READ_ONLY,
)
def inspect_neighborhood(
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
    return _get_explorer().inspect_neighborhood(
        start_ids=start_ids,
        id_property=id_property,
        relationship_types=relationship_types,
        direction=direction,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        property_names=property_names,
        node_filters=node_filters,
    )


@app.tool(
    description=(
        "Find simple paths inside a bounded explored subgraph. Path count, depth, "
        "nodes, edges, query time and serialized output are independently capped."
    ),
    annotations=READ_ONLY,
)
def find_paths(
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
    return _get_explorer().find_paths(
        from_id=from_id,
        to_id=to_id,
        id_property=id_property,
        relationship_types=relationship_types,
        direction=direction,
        max_depth=max_depth,
        max_paths=max_paths,
        max_nodes=max_nodes,
        max_edges=max_edges,
        property_names=property_names,
        node_filters=node_filters,
    )


@app.tool(
    description=(
        "Inspect runtime calls and responses anchored to static code nodes through "
        "STATIC_DEF, using the same hard traversal and output ceilings."
    ),
    annotations=READ_ONLY,
)
def inspect_runtime_overlay(
    static_stable_ids: list[str],
    session_id: str | None = None,
    max_depth: int = 3,
    max_nodes: int = 120,
    max_edges: int = 240,
    property_names: list[str] | None = None,
) -> dict[str, Any]:
    return _get_explorer().inspect_neighborhood(
        start_ids=static_stable_ids,
        id_property="stableId",
        relationship_types=RUNTIME_OVERLAY_TYPES,
        direction="both",
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        property_names=property_names,
        node_filters={"sessionId": session_id} if session_id else None,
    )


def main() -> None:
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
