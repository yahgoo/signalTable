#!/usr/bin/env python3
"""Filter, score, and render Apify Luma discovery results for SignalTable.

Reads raw or normalized JSON and prints:
  Luma: N
  markdown table: title | date | score | tier | source | URL

Examples:
  python3 apify_luma.py --input dataset.json | python3 luma_discovery_report.py
  python3 luma_discovery_report.py --input dataset.json --debug-filter
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_common import dominant_filter_drop, filter_pipeline, score_and_tier
from luma_normalize import is_raw_apify_item, normalize_canonical


def _load_items(path: str | None, source_query: str = "") -> list[dict[str, Any]]:
    raw = sys.stdin.read() if path in (None, "-") else open(path, encoding="utf-8").read()
    data = json.loads(raw)
    if isinstance(data, list):
        items = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        items = None
        for key in ("events", "items", "data"):
            maybe = data.get(key)
            if isinstance(maybe, list):
                items = [e for e in maybe if isinstance(e, dict)]
                break
        if items is None:
            raise SystemExit(json.dumps({"error": "Expected JSON list or {events: [...]}"}))
    else:
        raise SystemExit(json.dumps({"error": "Expected JSON list or object"}))

    normalized: list[dict[str, Any]] = []
    for item in items:
        if item.get("source") == "luma" and item.get("start_time"):
            normalized.append(item)
        elif is_raw_apify_item(item) or item.get("event") or item.get("api_id"):
            normalized.append(normalize_canonical(item, source_query=source_query))
        elif item.get("platform") == "luma" and item.get("start_at"):
            normalized.append(normalize_canonical(item, source_query=source_query))
        else:
            normalized.append(normalize_canonical(item, source_query=source_query))
    return normalized


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| title | date | score | tier | source | URL |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(row.get("title")),
                    _md_cell(row.get("start_time") or row.get("start_at")),
                    _md_cell(row.get("relevance_score")),
                    _md_cell(row.get("tier")),
                    _md_cell(row.get("source") or row.get("platform")),
                    _md_cell(row.get("url") or row.get("source_url")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render scored Luma discovery report")
    parser.add_argument("--input", "-i", help="JSON file (default: stdin)")
    parser.add_argument(
        "--source-query",
        default="",
        help="Originating Luma query keyword for provenance",
    )
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument("--debug-filter", action="store_true")
    args = parser.parse_args()

    events = _load_items(args.input, source_query=args.source_query)
    filtered, counts = filter_pipeline(events)
    scored = score_and_tier(filtered, min_score=args.min_score)
    counts["scored"] = len(scored)

    if args.debug_filter:
        print(
            f"filter_debug: raw={counts.get('raw',0)} -> pass={counts.get('hard_filter_pass',0)} -> "
            f"deduped={counts.get('deduped',0)} -> scored={counts['scored']} (min_score={args.min_score})",
            file=sys.stderr,
        )

    print(f"Luma: {len(scored)}")
    if scored:
        print()
        print(_render_table(scored))
    elif counts.get("raw", 0) > 0:
        print(dominant_filter_drop(counts))


if __name__ == "__main__":
    main()
