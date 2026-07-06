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
from luma_normalize import (
    dominant_filter_drop,
    filter_pipeline,
    is_raw_apify_item,
    normalize_raw_item,
)

TOPIC_TERMS = (
    "ai",
    "ml",
    "data",
    "llm",
    "genai",
    "mlops",
    "machine learning",
    "developer",
    "tech",
    "algorithm",
    "compute",
    "engineering",
    "agent",
    "model",
)

OFFTOPIC_TERMS = (
    "fitness",
    "yoga",
    "run club",
    "mindful run",
    "wellness retreat",
    "food festival",
    "kitchen haus",
    "franchise",
)

KNOWN_ORGANIZERS = (
    "google",
    "meta",
    "aws",
    "amazon web services",
    "nus",
    "stripe",
    "microsoft",
    "openai",
)

WORKSHOP_TERMS = ("workshop", "hands-on", "hackathon", "buildathon", "lab")


def _load_items(path: str | None) -> list[dict[str, Any]]:
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
        if item.get("platform") == "luma" and item.get("start_at"):
            normalized.append(item)
        elif is_raw_apify_item(item) or item.get("event") or item.get("api_id"):
            normalized.append(normalize_raw_item(item))
        else:
            normalized.append(item)
    return normalized


def _haystack(event: dict[str, Any]) -> str:
    parts = [
        event.get("title", ""),
        event.get("summary", ""),
        event.get("raw_category", ""),
        " ".join(event.get("categories") or []),
        event.get("organizer", ""),
        event.get("location", ""),
        event.get("city", ""),
        event.get("country", ""),
    ]
    return " ".join(str(p) for p in parts).lower()


def _is_free(event: dict[str, Any]) -> bool | None:
    if event.get("is_free") is not None:
        return bool(event.get("is_free"))
    summary = _haystack(event)
    if "free" in summary and "free trial" not in summary:
        return True
    if any(x in summary for x in ("paid", "ticket", "usd", "sgd", "$")):
        return False
    return None


def _requires_approval(event: dict[str, Any]) -> bool | None:
    if event.get("requires_approval") is not None:
        return bool(event.get("requires_approval"))
    summary = _haystack(event)
    if "waitlist" in summary or "approval" in summary:
        return True
    return None


def _score_event(event: dict[str, Any]) -> int:
    text = _haystack(event)
    score = 0

    if any(term in text for term in TOPIC_TERMS):
        score += 3
    if "singapore" in text:
        score += 2
    free = _is_free(event)
    if free is True:
        score += 2
    if any(org in text for org in KNOWN_ORGANIZERS):
        score += 1
    if any(term in text for term in WORKSHOP_TERMS):
        score += 1
    if free is False:
        score -= 3
    if any(term in text for term in OFFTOPIC_TERMS):
        score -= 5

    return max(0, min(10, score))


def _tier(event: dict[str, Any], score: int) -> int:
    free = _is_free(event)
    approval = _requires_approval(event)
    if free is False or approval is True:
        return 3
    if free is True and approval is not True and score >= 6:
        return 1
    if 4 <= score <= 5:
        return 2
    if score >= 6:
        return 2
    return 3


def _display_date(event: dict[str, Any]) -> str:
    return str(event.get("start_at") or event.get("date") or "")


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
                    _md_cell(row.get("date")),
                    _md_cell(row.get("score")),
                    _md_cell(row.get("tier")),
                    _md_cell(row.get("source")),
                    _md_cell(row.get("URL")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _print_debug_counts(counts: dict[str, int]) -> None:
    print(
        "filter_debug: "
        f"raw={counts.get('raw', 0)} -> "
        f"upcoming={counts.get('upcoming', 0)} -> "
        f"singapore={counts.get('singapore', 0)} -> "
        f"tech_ai={counts.get('tech_ai', 0)} -> "
        f"deduped={counts.get('deduped', 0)}",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render scored Luma discovery report")
    parser.add_argument("--input", "-i", help="JSON file (default: stdin)")
    parser.add_argument("--min-score", type=int, default=4)
    parser.add_argument(
        "--debug-filter",
        action="store_true",
        help="Print filter stage counts to stderr",
    )
    args = parser.parse_args()

    events = _load_items(args.input)
    filtered, counts = filter_pipeline(events)

    if args.debug_filter:
        _print_debug_counts(counts)

    scored: list[dict[str, Any]] = []
    for event in filtered:
        score = _score_event(event)
        if score < args.min_score:
            continue
        scored.append(
            {
                "title": event.get("title", ""),
                "date": _display_date(event),
                "score": score,
                "tier": _tier(event, score),
                "source": event.get("platform", "luma"),
                "URL": event.get("source_url", ""),
            }
        )

    scored.sort(key=lambda r: (-int(r["score"]), r.get("title", "")))
    counts["scored"] = len(scored)

    if args.debug_filter:
        print(
            f"filter_debug: scored={counts['scored']} (min_score={args.min_score})",
            file=sys.stderr,
        )

    print(f"Luma: {len(scored)}")
    if scored:
        print()
        print(_render_table(scored))
    elif counts.get("deduped", 0) > 0:
        print(
            f"blocker: min_score={args.min_score} removed all "
            f"{counts['deduped']} row(s) that passed upcoming/singapore/tech_ai filters"
        )
    elif counts.get("raw", 0) > 0:
        print(dominant_filter_drop(counts))


if __name__ == "__main__":
    main()
