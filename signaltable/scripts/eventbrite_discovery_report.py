#!/usr/bin/env python3
"""Filter, score, and render Eventbrite discovery results for SignalTable."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from discovery_common import dominant_filter_drop, filter_pipeline, score_and_tier
from eventbrite_normalize import DEFAULT_SOURCE_QUERY, normalize_canonical


def _load_items(path: str, source_query: str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("events") or data.get("items") or []
    return [
        normalize_canonical(item, source_query=source_query)
        for item in items
        if isinstance(item, dict)
    ]


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| title | date | score | tier | source | matched | URL |",
        "| --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        matched = ",".join(row.get("matched_keywords") or [row.get("matched_keyword", "")])
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(row.get("title")),
                    _md_cell(row.get("start_time")),
                    _md_cell(row.get("relevance_score")),
                    _md_cell(row.get("tier")),
                    _md_cell(row.get("source")),
                    _md_cell(matched),
                    _md_cell(row.get("url")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render scored Eventbrite discovery report")
    parser.add_argument("--input", "-i", required=True, help="Eventbrite JSON export")
    parser.add_argument(
        "--query",
        default=DEFAULT_SOURCE_QUERY,
        help="Source query label (default: science-tech)",
    )
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument("--debug-filter", action="store_true")
    args = parser.parse_args()

    events = _load_items(args.input, args.query.strip().lower())
    filtered, counts = filter_pipeline(events)
    scored = score_and_tier(filtered, min_score=args.min_score)
    counts["scored"] = len(scored)

    if args.debug_filter:
        print(
            f"filter_debug: raw={counts.get('raw',0)} -> pass={counts.get('hard_filter_pass',0)} -> "
            f"deduped={counts.get('deduped',0)} -> scored={counts['scored']} (min_score={args.min_score})",
            file=sys.stderr,
        )

    print(f"Eventbrite: {len(scored)}")
    if scored:
        print()
        print(_render_table(scored))
    elif counts.get("raw", 0) > 0:
        print(dominant_filter_drop(counts))


if __name__ == "__main__":
    main()
