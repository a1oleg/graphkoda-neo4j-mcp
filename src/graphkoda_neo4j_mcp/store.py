from __future__ import annotations

from typing import Any, Protocol

from neo4j import Query

from .serialization import normalize


class GraphStore(Protocol):
    def resolve_nodes(
        self,
        identifiers: list[str],
        id_property: str,
        property_names: list[str],
        limit: int,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]: ...

    def fetch_neighbors(
        self,
        frontier_element_ids: list[str],
        relationship_types: list[str],
        direction: str,
        property_names: list[str],
        node_filters: dict[str, str],
        limit: int,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]: ...


def _entry_map(entries: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {
        str(entry["key"]): normalize(entry.get("value"))
        for entry in entries or []
        if entry.get("value") is not None
    }


def _node(record: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "elementId": record[f"{prefix}ElementId"],
        "labels": list(record[f"{prefix}Labels"]),
        "properties": _entry_map(record.get(f"{prefix}Properties")),
    }


class Neo4jStore:
    def __init__(self, driver: Any, database: str):
        self.driver = driver
        self.database = database

    def _run(self, query: str, parameters: dict[str, Any], timeout_seconds: float) -> list[dict[str, Any]]:
        with self.driver.session(database=self.database, default_access_mode="READ") as session:
            result = session.run(Query(query, timeout=timeout_seconds), parameters)
            rows = [record.data() for record in result]
            summary = result.consume()
            if summary.query_type != "r":
                raise RuntimeError(f"Unexpected non-read query type: {summary.query_type}")
            return rows

    def resolve_nodes(
        self,
        identifiers: list[str],
        id_property: str,
        property_names: list[str],
        limit: int,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]:
        property_expression = "n.stableId" if id_property == "stableId" else "n.nodeid"
        rows = self._run(
            f"""
            UNWIND $identifiers AS requested
            MATCH (n)
            WHERE {property_expression} = requested
            RETURN elementId(n) AS nodeElementId,
                   labels(n) AS nodeLabels,
                   [key IN $propertyNames | {{key: key, value: n[key]}}] AS nodeProperties
            LIMIT $limit
            """,
            {
                "identifiers": identifiers,
                "propertyNames": property_names,
                "limit": limit,
            },
            timeout_seconds,
        )
        return [_node(row, "node") for row in rows]

    def fetch_neighbors(
        self,
        frontier_element_ids: list[str],
        relationship_types: list[str],
        direction: str,
        property_names: list[str],
        node_filters: dict[str, str],
        limit: int,
        timeout_seconds: float,
    ) -> list[dict[str, Any]]:
        patterns = {
            "outgoing": "(frontier)-[rel]->(neighbor)",
            "incoming": "(frontier)<-[rel]-(neighbor)",
            "both": "(frontier)-[rel]-(neighbor)",
        }
        pattern = patterns[direction]
        rows = self._run(
            f"""
            UNWIND $frontierElementIds AS frontierElementId
            MATCH (frontier)
            WHERE elementId(frontier) = frontierElementId
            MATCH {pattern}
            WHERE type(rel) IN $relationshipTypes
              AND all(filter IN $nodeFilters WHERE frontier[filter.key] IS NULL OR frontier[filter.key] = filter.value)
              AND all(filter IN $nodeFilters WHERE neighbor[filter.key] IS NULL OR neighbor[filter.key] = filter.value)
            WITH DISTINCT rel, startNode(rel) AS source, endNode(rel) AS target
            RETURN elementId(rel) AS relationshipElementId,
                   type(rel) AS relationshipType,
                   [key IN $propertyNames | {{key: key, value: rel[key]}}] AS relationshipProperties,
                   elementId(source) AS sourceElementId,
                   labels(source) AS sourceLabels,
                   [key IN $propertyNames | {{key: key, value: source[key]}}] AS sourceProperties,
                   elementId(target) AS targetElementId,
                   labels(target) AS targetLabels,
                   [key IN $propertyNames | {{key: key, value: target[key]}}] AS targetProperties
            LIMIT $limit
            """,
            {
                "frontierElementIds": frontier_element_ids,
                "relationshipTypes": relationship_types,
                "propertyNames": property_names,
                "nodeFilters": [{"key": key, "value": value} for key, value in node_filters.items()],
                "limit": limit,
            },
            timeout_seconds,
        )
        return [
            {
                "relationship": {
                    "elementId": row["relationshipElementId"],
                    "type": row["relationshipType"],
                    "source": row["sourceElementId"],
                    "target": row["targetElementId"],
                    "properties": _entry_map(row.get("relationshipProperties")),
                },
                "source": _node(row, "source"),
                "target": _node(row, "target"),
            }
            for row in rows
        ]
