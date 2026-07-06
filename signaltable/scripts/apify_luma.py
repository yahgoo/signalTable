#!/usr/bin/env python3
"""Apify-backed public Luma (lu.ma) event discovery for SignalTable.

Read-only: no signup, login, registration, or authenticated flows.

Environment:
  APIFY_TOKEN       Required Apify API token (not needed for --input)
  APIFY_ACTOR_ID    Actor ID (default: solidcode/luma-scraper)
  APIFY_TASK_ID     Optional Apify task ID/name (overrides actor when set)

Examples:
  python3 apify_luma.py --location singapore --queries data,algorithm,compute
  python3 apify_luma.py --input dataset.json --output json
  APIFY_TASK_ID=my-luma-task python3 apify_luma.py --location singapore
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from luma_normalize import dedupe_events, normalize_raw_item

DEFAULT_ACTOR = "solidcode/luma-scraper"
DEFAULT_LOCATION = "singapore"
DEFAULT_QUERIES = ["data", "algorithm", "compute"]
APIFY_BASE = "https://api.apify.com/v2"
SYNC_TIMEOUT_SECS = 300


def _die(message: str, code: int = 1) -> None:
    print(json.dumps({"error": message}), file=sys.stderr)
    raise SystemExit(code)


def _actor_path(actor_id: str) -> str:
    return actor_id.replace("/", "~")


def _request(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: int = SYNC_TIMEOUT_SECS,
) -> Any:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        _die(f"Apify HTTP {exc.code}: {detail[:500]}", code=exc.code if exc.code < 500 else 1)
    except urllib.error.URLError as exc:
        _die(f"Apify request failed: {exc.reason}", code=1)


def _build_actor_input(args: argparse.Namespace) -> dict[str, Any]:
    queries = args.queries or ([args.query] if args.query else DEFAULT_QUERIES)
    queries = [q.strip() for q in queries if q and q.strip()]

    payload: dict[str, Any] = {
        "discoverCity": args.location,
        "searchQueries": queries,
        "maxItems": args.max_items,
        "lumaUrls": [f"https://lu.ma/{args.location}"],
    }
    if args.category:
        payload["category"] = args.category
    return payload


def _run_sync_dataset(
    token: str,
    *,
    actor_id: str | None,
    task_id: str | None,
    actor_input: dict[str, Any],
    timeout: int,
) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"timeout": timeout})
    if task_id:
        path = f"actor-tasks/{_actor_path(task_id)}/run-sync-get-dataset-items?{params}"
    else:
        actor = actor_id or DEFAULT_ACTOR
        path = f"acts/{_actor_path(actor)}/run-sync-get-dataset-items?{params}"
    url = f"{APIFY_BASE}/{path}"
    result = _request("POST", url, token, actor_input, timeout=timeout + 30)
    if not isinstance(result, list):
        _die(f"Unexpected Apify response type: {type(result).__name__}")
    return result


def _load_input_file(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("events", "items", "data"):
            items = data.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    _die(f"Unsupported JSON shape in {path}")
    return []


def _normalize_many(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("platform") == "luma" and item.get("start_at") and item.get("title"):
            rows.append(item)
        else:
            rows.append(normalize_raw_item(item))
    return dedupe_events(rows)


def _to_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| title | start_at | location | source_url | organizer | raw_category |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        cells = [
            row.get("title", ""),
            row.get("start_at", row.get("date", "")),
            row.get("location", ""),
            row.get("source_url", ""),
            row.get("organizer", ""),
            row.get("raw_category", ""),
        ]
        escaped = [str(c).replace("|", "\\|") for c in cells]
        lines.append("| " + " | ".join(escaped) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch public Luma events via Apify")
    parser.add_argument("--query", help="Single search query")
    parser.add_argument(
        "--queries",
        help="Comma-separated search queries (default: data,algorithm,compute)",
    )
    parser.add_argument("--location", default=DEFAULT_LOCATION, help="Luma city slug")
    parser.add_argument("--category", help="Optional Luma category filter (actor-specific)")
    parser.add_argument("--max-items", type=int, default=50, dest="max_items")
    parser.add_argument("--output", choices=["json", "md"], default="json")
    parser.add_argument("--input", "-i", help="Read raw Apify JSON file instead of live fetch")
    parser.add_argument("--actor", help=f"Apify actor ID (default env or {DEFAULT_ACTOR})")
    parser.add_argument("--task-id", help="Apify task ID/name (overrides actor)")
    parser.add_argument("--timeout", type=int, default=SYNC_TIMEOUT_SECS, help="Sync run timeout")
    args = parser.parse_args()

    if args.queries:
        args.queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    else:
        args.queries = None

    if args.input:
        raw_items = _load_input_file(args.input)
        actor_label = f"file:{args.input}"
        actor_input = {}
    else:
        token = os.environ.get("APIFY_TOKEN", "").strip()
        if not token:
            _die("APIFY_TOKEN is not set (or pass --input)", code=2)
        actor_id = args.actor or os.environ.get("APIFY_ACTOR_ID", DEFAULT_ACTOR).strip()
        task_id = (args.task_id or os.environ.get("APIFY_TASK_ID") or "").strip() or None
        actor_input = _build_actor_input(args)
        raw_items = _run_sync_dataset(
            token,
            actor_id=actor_id,
            task_id=task_id,
            actor_input=actor_input,
            timeout=args.timeout,
        )
        actor_label = task_id or actor_id

    rows = _normalize_many(raw_items)

    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "location": args.location,
        "queries": actor_input.get("searchQueries", []),
        "category": args.category,
        "actor": actor_label,
        "raw_count": len(raw_items),
        "normalized_count": len(rows),
    }

    if args.output == "md":
        print(_to_markdown(rows))
        return

    print(json.dumps({"meta": meta, "events": rows}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
