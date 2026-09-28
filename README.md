# graphkoda-neo4j-mcp

Read-only MCP server for bounded exploration of static code graphs and runtime
flows in Neo4j.

This server deliberately does **not** expose arbitrary Cypher. Instead it offers
small domain operations whose cost and response size can be bounded before an
agent calls them. It complements the official Neo4j MCP when an agent-facing
production boundary needs stricter guarantees than a general `read-cypher` tool.

## Why a separate server

The Redis-to-Neo4j ingestion path remains a deterministic application pipeline.
This MCP sits after Neo4j and only reads the materialized graph:

```text
runtime logs -> Redis -> normalizer -> Neo4j
                                      ^
                                      |
                          graphkoda-neo4j-mcp
                                      ^
                                      |
                                    agent
```

The graphKoda preset understands the current overlay convention:

- static nodes are addressed by `stableId`;
- runtime nodes are addressed by `nodeid`;
- `STATIC_DEF` anchors runtime observations to static definitions;
- `CALLS_AT_RUNTIME` and `response` represent observed flow;
- `STATIC_CALLS` represents static call structure.

The generic neighborhood and path tools can also use other allowlisted
relationship types.

## Enforced limits

Every request is constrained independently by:

- traversal depth;
- number of returned paths;
- node count;
- relationship count;
- number of seed identifiers and requested properties;
- Neo4j query timeout;
- serialized UTF-8 response size.

Compiled hard ceilings cannot be raised through MCP arguments or environment
variables. Environment variables may only lower them. Traversal is implemented
as bounded one-hop reads followed by BFS in the server, so the server never sends
an agent-generated variable-depth query to Neo4j.

Default server ceilings:

| Limit | Default | Compiled maximum |
| --- | ---: | ---: |
| Depth | 6 | 8 |
| Paths | 50 | 100 |
| Nodes | 300 | 500 |
| Relationships | 600 | 1,000 |
| Output | 256 KiB | 512 KiB |
| Query timeout | 15 s | 30 s |
| Seeds | 20 | 20 |
| Properties | 20 | 20 |

Responses report the applied limits and explicit truncation reasons such as
`node-limit`, `edge-limit`, `path-limit`, and `output-byte-limit`.

## Tools

- `get_limits` returns the effective ceilings and relationship allowlist without
  connecting to Neo4j.
- `check_connection` verifies database connectivity.
- `inspect_neighborhood` expands from explicit `stableId` or `nodeid` seeds.
- `find_paths` enumerates simple paths inside a separately bounded subgraph.
- `inspect_runtime_overlay` follows only `STATIC_DEF`, `CALLS_AT_RUNTIME`, and
  `response` from supplied static IDs and can isolate one `session_id`.

All tools carry MCP read-only annotations. There is no write tool and no raw
query tool.

## Install and run

Requires Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
Copy-Item .env.example .env
```

Set the variables from `.env` in the MCP host environment, then run:

```powershell
.venv\Scripts\python -m graphkoda_neo4j_mcp.server
```

The server uses stdio. A VS Code configuration example is included in
`.vscode/mcp.json`; it prompts for credentials instead of storing them.

Minimal client configuration:

```json
{
  "mcpServers": {
    "graphkoda-neo4j": {
      "command": "C:/GitHub/graphkoda-neo4j-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "graphkoda_neo4j_mcp.server"],
      "env": {
        "NEO4J_URI": "bolt://127.0.0.1:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "use-a-secret-store",
        "NEO4J_DATABASE": "neo4j"
      }
    }
  }
}
```

Do not commit real credentials. Prefer a dedicated Neo4j user with database-level
read privileges; application-side read-only behavior is not a replacement for
database authorization.

## Examples

Inspect the static/runtime overlay around two definitions:

```json
{
  "static_stable_ids": [
    "screens/REPL.tsx:3142:31:3533:3",
    "hooks/useCommandKeybindings.tsx:81:8:83:10"
  ],
  "session_id": "runtime-session-42",
  "max_depth": 3,
  "max_nodes": 100,
  "max_edges": 180
}
```

Find bounded static call paths:

```json
{
  "from_id": "src/a.ts:10:1:20:2",
  "to_id": "src/b.ts:30:1:45:2",
  "relationship_types": ["STATIC_CALLS"],
  "max_depth": 4,
  "max_paths": 10,
  "max_nodes": 120,
  "max_edges": 240
}
```

Request arguments above the configured ceiling fail instead of being silently
expanded. Oversized result sets are truncated and marked in the response.

## Configuration

Copy `.env.example` and pass its values through the MCP host. Supported limit
variables are:

- `GRAPHKODA_MCP_MAX_DEPTH`
- `GRAPHKODA_MCP_MAX_PATHS`
- `GRAPHKODA_MCP_MAX_NODES`
- `GRAPHKODA_MCP_MAX_EDGES`
- `GRAPHKODA_MCP_MAX_OUTPUT_BYTES`
- `GRAPHKODA_MCP_QUERY_TIMEOUT_SECONDS`
- `GRAPHKODA_MCP_RELATIONSHIP_TYPES`

The relationship setting is a comma-separated allowlist. A request can select a
subset, but cannot traverse a relationship omitted from the server allowlist.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The test suite uses an in-memory fake graph for deterministic limit tests and a
real stdio MCP client for tool discovery. Neo4j is not required for unit tests.
The GitHub workflow runs the same suite on Python 3.12.
