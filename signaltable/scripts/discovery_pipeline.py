#!/usr/bin/env python3
"""Unified Luma + Meetup + Eventbrite discovery pipeline (local dry-run or live inputs).

Pipeline: fetch/load -> normalize -> hard-filter -> dedupe -> score -> report

Examples:
  python3 discovery_pipeline.py \\
    --luma-query data,algorithm,compute \\
    --luma-input ../dataset_luma-singapore-data-search_2026-07-06_11-01-44-114.json \\
    --meetup data:../dataset_meetup-data-sg-physical_2026-07-07_04-43-44-790.json \\
    --meetup algorithm:../dataset_meetup-algorithm-sg-physical_2026-07-07_04-46-39-500.json \\
    --meetup compute:../dataset_meetup-compute-sg-physical_2026-07-07_04-48-44-165.json \\
    --debug-filter
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_common import (
    dominant_filter_drop,
    filter_pipeline,
    score_and_tier,
)
from eventbrite_normalize import DEFAULT_SOURCE_QUERY, normalize_canonical as normalize_eventbrite
from luma_normalize import is_raw_apify_item, normalize_canonical as normalize_luma
from meetup_normalize import normalize_canonical as normalize_meetup


def _load_json_list(path: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        for key in ("events", "items", "data"):
            maybe = data.get(key)
            if isinstance(maybe, list):
                return [e for e in maybe if isinstance(e, dict)]
    raise SystemExit(json.dumps({"error": f"unsupported JSON shape in {path}"}))


def _load_luma(path: str, queries: list[str]) -> list[dict[str, Any]]:
    items = _load_json_list(path)
    rows: list[dict[str, Any]] = []
    default_query = queries[0] if len(queries) == 1 else ""
    for item in items:
        q = _first_query(item, queries, default_query)
        if item.get("source") == "luma" and item.get("start_time"):
            rows.append(item)
        elif is_raw_apify_item(item) or item.get("event") or item.get("api_id"):
            rows.append(normalize_luma(item, source_query=q))
        elif item.get("platform") == "luma":
            rows.append(normalize_luma(item, source_query=q))
        else:
            rows.append(normalize_luma(item, source_query=q))
    return rows


def _first_query(item: dict[str, Any], queries: list[str], default: str) -> str:
    for q in queries:
        if q and q in json.dumps(item).lower():
            return q
    return default or (queries[0] if queries else "")


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| title | date | score | tier | source | free | URL |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
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
                    _md_cell(row.get("source")),
                    _md_cell(row.get("is_free")),
                    _md_cell(row.get("url") or row.get("source_url")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _print_filter_debug(label: str, counts: dict[str, int], scored: int, min_score: int) -> None:
    print(
        f"filter_debug[{label}]: raw={counts.get('raw', 0)} -> "
        f"pass={counts.get('hard_filter_pass', 0)} -> "
        f"deduped={counts.get('deduped', 0)} -> scored={scored} (min_score={min_score})",
        file=sys.stderr,
    )


def _run_source(
    events: list[dict[str, Any]],
    *,
    label: str,
    min_score: int,
    debug: bool,
) -> list[dict[str, Any]]:
    filtered, counts = filter_pipeline(events)
    scored = score_and_tier(filtered, min_score=min_score)
    counts["scored"] = len(scored)
    if debug:
        _print_filter_debug(label, counts, len(scored), min_score)
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified discovery pipeline")
    parser.add_argument("--luma-input", action="append", default=[], help="Luma JSON export path")
    parser.add_argument(
        "--luma-query",
        default="data,algorithm,compute",
        help="Comma-separated Luma source queries",
    )
    parser.add_argument(
        "--meetup",
        action="append",
        default=[],
        help="Meetup export as query:path (e.g. data:dataset_meetup-data....json)",
    )
    parser.add_argument(
        "--eventbrite",
        action="append",
        default=[],
        help="Eventbrite export as query:path (e.g. science-tech:dataset_eventbrite-....json)",
    )
    parser.add_argument(
        "--eventbrite-input",
        action="append",
        default=[],
        help=f"Eventbrite export path (uses default query {DEFAULT_SOURCE_QUERY})",
    )
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument("--debug-filter", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print scored rows as JSON")
    args = parser.parse_args()

    luma_queries = [q.strip().lower() for q in args.luma_query.split(",") if q.strip()]
    luma_rows: list[dict[str, Any]] = []
    for path in args.luma_input:
        luma_rows.extend(_load_luma(path, luma_queries))

    meetup_rows: list[dict[str, Any]] = []
    for spec in args.meetup:
        if ":" not in spec:
            raise SystemExit(f"invalid --meetup value (expected query:path): {spec}")
        query, path = spec.split(":", 1)
        for item in _load_json_list(path):
            meetup_rows.append(normalize_meetup(item, source_query=query.strip().lower()))

    eventbrite_rows: list[dict[str, Any]] = []
    for spec in args.eventbrite:
        if ":" not in spec:
            raise SystemExit(f"invalid --eventbrite value (expected query:path): {spec}")
        query, path = spec.split(":", 1)
        for item in _load_json_list(path):
            eventbrite_rows.append(normalize_eventbrite(item, source_query=query.strip().lower()))
    for path in args.eventbrite_input:
        for item in _load_json_list(path):
            eventbrite_rows.append(normalize_eventbrite(item, source_query=DEFAULT_SOURCE_QUERY))

    luma_scored = _run_source(luma_rows, label="luma", min_score=args.min_score, debug=args.debug_filter)
    meetup_scored = _run_source(
        meetup_rows, label="meetup", min_score=args.min_score, debug=args.debug_filter
    )
    eventbrite_scored = _run_source(
        eventbrite_rows, label="eventbrite", min_score=args.min_score, debug=args.debug_filter
    )

    combined_input = luma_rows + meetup_rows + eventbrite_rows
    combined_scored = _run_source(
        combined_input, label="combined", min_score=args.min_score, debug=args.debug_filter
    )

    if args.json:
        print(
            json.dumps(
                {
                    "luma": luma_scored,
                    "meetup": meetup_scored,
                    "eventbrite": eventbrite_scored,
                    "combined": combined_scored,
                },
                indent=2,
            )
        )
        return

    print(f"Luma: {len(luma_scored)}")
    if luma_scored:
        print()
        print(_render_table(luma_scored))

    print()
    print(f"Meetup: {len(meetup_scored)}")
    if meetup_scored:
        print()
        print(_render_table(meetup_scored))

    print()
    print(f"Eventbrite: {len(eventbrite_scored)}")
    if eventbrite_scored:
        print()
        print(_render_table(eventbrite_scored))

    print()
    print(f"Combined: {len(combined_scored)}")
    if combined_scored:
        print()
        print(_render_table(combined_scored))
    elif combined_input:
        _, counts = filter_pipeline(combined_input)
        print(dominant_filter_drop(counts))


if __name__ == "__main__":
    main()
