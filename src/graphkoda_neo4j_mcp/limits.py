from __future__ import annotations

from dataclasses import asdict, dataclass
import os


HARD_MAX_DEPTH = 8
HARD_MAX_PATHS = 100
HARD_MAX_NODES = 500
HARD_MAX_EDGES = 1_000
HARD_MAX_OUTPUT_BYTES = 512 * 1024
HARD_QUERY_TIMEOUT_SECONDS = 30.0
HARD_MAX_SEEDS = 20
HARD_MAX_PROPERTIES = 20


def _lowered_int(name: str, default: int, hard_max: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return min(value, hard_max)


def _lowered_float(name: str, default: float, hard_max: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return min(value, hard_max)


@dataclass(frozen=True)
class RequestLimits:
    max_depth: int
    max_paths: int
    max_nodes: int
    max_edges: int
    max_output_bytes: int
    query_timeout_seconds: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class ServerLimits:
    max_depth: int = 6
    max_paths: int = 50
    max_nodes: int = 300
    max_edges: int = 600
    max_output_bytes: int = 256 * 1024
    query_timeout_seconds: float = 15.0
    max_seeds: int = HARD_MAX_SEEDS
    max_properties: int = HARD_MAX_PROPERTIES

    @classmethod
    def from_env(cls) -> "ServerLimits":
        return cls(
            max_depth=_lowered_int("GRAPHKODA_MCP_MAX_DEPTH", 6, HARD_MAX_DEPTH),
            max_paths=_lowered_int("GRAPHKODA_MCP_MAX_PATHS", 50, HARD_MAX_PATHS),
            max_nodes=_lowered_int("GRAPHKODA_MCP_MAX_NODES", 300, HARD_MAX_NODES),
            max_edges=_lowered_int("GRAPHKODA_MCP_MAX_EDGES", 600, HARD_MAX_EDGES),
            max_output_bytes=_lowered_int(
                "GRAPHKODA_MCP_MAX_OUTPUT_BYTES", 256 * 1024, HARD_MAX_OUTPUT_BYTES
            ),
            query_timeout_seconds=_lowered_float(
                "GRAPHKODA_MCP_QUERY_TIMEOUT_SECONDS", 15.0, HARD_QUERY_TIMEOUT_SECONDS
            ),
        )

    def resolve(
        self,
        *,
        max_depth: int,
        max_paths: int = 1,
        max_nodes: int,
        max_edges: int,
    ) -> RequestLimits:
        requested = {
            "max_depth": (max_depth, self.max_depth),
            "max_paths": (max_paths, self.max_paths),
            "max_nodes": (max_nodes, self.max_nodes),
            "max_edges": (max_edges, self.max_edges),
        }
        for name, (value, ceiling) in requested.items():
            if value < 1 or value > ceiling:
                raise ValueError(f"{name} must be between 1 and {ceiling}")
        return RequestLimits(
            max_depth=max_depth,
            max_paths=max_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
            max_output_bytes=self.max_output_bytes,
            query_timeout_seconds=self.query_timeout_seconds,
        )

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)
