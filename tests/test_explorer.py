from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from graphkoda_neo4j_mcp.explorer import BoundedExplorer
from graphkoda_neo4j_mcp.limits import HARD_MAX_DEPTH, ServerLimits


def node(element_id: str, stable_id: str) -> dict:
    return {
        "elementId": element_id,
        "labels": ["Static", "Fn"],
        "properties": {"stableId": stable_id, "name": stable_id},
    }


class FakeStore:
    def __init__(self):
        self.nodes = {
            "1": node("1", "A"),
            "2": node("2", "B"),
            "3": node("3", "C"),
            "4": node("4", "D"),
        }
        self.edges = [
            {"elementId": "e1", "type": "STATIC_CALLS", "source": "1", "target": "2", "properties": {}},
            {"elementId": "e2", "type": "STATIC_CALLS", "source": "2", "target": "3", "properties": {}},
            {"elementId": "e3", "type": "STATIC_CALLS", "source": "1", "target": "4", "properties": {}},
            {"elementId": "e4", "type": "STATIC_CALLS", "source": "4", "target": "3", "properties": {}},
        ]

    def resolve_nodes(self, identifiers, id_property, property_names, limit, timeout_seconds):
        return [item for item in self.nodes.values() if item["properties"].get(id_property) in identifiers][:limit]

    def fetch_neighbors(self, frontier_element_ids, relationship_types, direction, property_names, node_filters, limit, timeout_seconds):
        rows = []
        for edge in self.edges:
            include = (
                direction == "outgoing" and edge["source"] in frontier_element_ids
                or direction == "incoming" and edge["target"] in frontier_element_ids
                or direction == "both" and (edge["source"] in frontier_element_ids or edge["target"] in frontier_element_ids)
            )
            if include and edge["type"] in relationship_types:
                rows.append({
                    "relationship": edge,
                    "source": self.nodes[edge["source"]],
                    "target": self.nodes[edge["target"]],
                })
        return rows[:limit]


class LimitsTest(unittest.TestCase):
    def test_environment_can_lower_but_not_raise_hard_limits(self):
        with patch.dict(os.environ, {"GRAPHKODA_MCP_MAX_DEPTH": "999"}):
            self.assertEqual(ServerLimits.from_env().max_depth, HARD_MAX_DEPTH)
        with patch.dict(os.environ, {"GRAPHKODA_MCP_MAX_DEPTH": "2"}):
            self.assertEqual(ServerLimits.from_env().max_depth, 2)

    def test_requests_above_server_ceiling_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_depth"):
            ServerLimits(max_depth=2).resolve(max_depth=3, max_nodes=10, max_edges=10)


class ExplorerTest(unittest.TestCase):
    def setUp(self):
        self.explorer = BoundedExplorer(
            FakeStore(),
            ServerLimits(max_depth=4, max_paths=3, max_nodes=10, max_edges=10, max_output_bytes=20_000),
            {"STATIC_CALLS"},
        )

    def test_neighborhood_is_bounded_by_depth_and_selected_types(self):
        result = self.explorer.inspect_neighborhood(
            start_ids=["A"], relationship_types=["STATIC_CALLS"], direction="outgoing",
            max_depth=1, max_nodes=10, max_edges=10,
        )
        self.assertEqual({item["properties"]["stableId"] for item in result["nodes"]}, {"A", "B", "D"})
        self.assertEqual(len(result["edges"]), 2)
        self.assertEqual(result["depthReached"], 1)

    def test_node_and_edge_limits_are_reported(self):
        result = self.explorer.inspect_neighborhood(
            start_ids=["A"], relationship_types=["STATIC_CALLS"], direction="outgoing",
            max_depth=3, max_nodes=2, max_edges=1,
        )
        self.assertLessEqual(len(result["nodes"]), 2)
        self.assertLessEqual(len(result["edges"]), 1)
        self.assertTrue(result["truncation"]["truncated"])

    def test_path_count_is_capped(self):
        result = self.explorer.find_paths(
            from_id="A", to_id="C", relationship_types=["STATIC_CALLS"],
            max_depth=3, max_paths=1, max_nodes=10, max_edges=10,
        )
        self.assertEqual(result["pathCount"], 1)
        self.assertIn("path-limit", result["truncation"]["reasons"])

    def test_relationship_allowlist_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            self.explorer.inspect_neighborhood(
                start_ids=["A"], relationship_types=["DELETE_ME"],
                max_depth=1, max_nodes=10, max_edges=10,
            )

    def test_serialized_output_respects_byte_ceiling(self):
        explorer = BoundedExplorer(
            FakeStore(),
            ServerLimits(max_depth=4, max_paths=3, max_nodes=10, max_edges=10, max_output_bytes=550),
            {"STATIC_CALLS"},
        )
        result = explorer.inspect_neighborhood(
            start_ids=["A"], relationship_types=["STATIC_CALLS"], direction="outgoing",
            max_depth=3, max_nodes=10, max_edges=10,
        )
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), 550)
        self.assertIn("output-byte-limit", result["truncation"]["reasons"])


if __name__ == "__main__":
    unittest.main()
