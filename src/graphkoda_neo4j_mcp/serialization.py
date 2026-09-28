from __future__ import annotations

import json
from typing import Any


MAX_STRING_CHARS = 2_000
MAX_COLLECTION_ITEMS = 50
MAX_NESTING = 4


def normalize(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_STRING_CHARS]
    if depth >= MAX_NESTING:
        return str(value)[:MAX_STRING_CHARS]
    if isinstance(value, (list, tuple)):
        return [normalize(item, depth + 1) for item in value[:MAX_COLLECTION_ITEMS]]
    if isinstance(value, dict) or hasattr(value, "items"):
        return {
            str(key)[:200]: normalize(item, depth + 1)
            for key, item in list(value.items())[:MAX_COLLECTION_ITEMS]
        }
    return str(value)[:MAX_STRING_CHARS]


def json_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _finalize_size(payload: dict[str, Any]) -> int:
    payload["outputBytes"] = 0
    for _ in range(4):
        size = json_size(payload)
        if payload["outputBytes"] == size:
            return size
        payload["outputBytes"] = size
    return json_size(payload)


def enforce_output_budget(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    payload.setdefault("truncation", {"truncated": False, "reasons": []})
    if _finalize_size(payload) <= max_bytes:
        return payload

    truncation = payload["truncation"]
    truncation["truncated"] = True
    if "output-byte-limit" not in truncation["reasons"]:
        truncation["reasons"].append("output-byte-limit")

    for key in ("paths", "edges", "nodes"):
        values = payload.get(key)
        while isinstance(values, list) and values and _finalize_size(payload) > max_bytes:
            values.pop()

    if _finalize_size(payload) > max_bytes:
        payload = {
            "limits": payload.get("limits"),
            "truncation": truncation,
            "message": "Result metadata exceeded the output budget; graph data was omitted.",
        }
    _finalize_size(payload)
    return payload
