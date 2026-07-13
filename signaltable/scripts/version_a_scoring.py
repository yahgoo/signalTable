#!/usr/bin/env python3
"""Transparent Version A scoring: base relevance + preference feedback."""

from __future__ import annotations

from collections import Counter
from typing import Any

from discovery_common import dedupe_key, keyword_matches, score_event
from feedback_store import load_feedback


def _organizer_key(event: dict[str, Any]) -> str:
    org = str(event.get("organizer_name") or "").strip().lower()
    group = str(event.get("group_name") or "").strip().lower()
    return org or group


def feedback_adjustment(
    event: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """Apply simple, explainable boosts/penalties from past y/n/m labels."""
    if not records:
        return 0, []

    adj = 0
    reasons: list[str] = []
    org = _organizer_key(event)
    platform = str(event.get("source") or event.get("platform") or "").lower()
    keywords = {k.lower() for k in keyword_matches(event)}

    yes_orgs = {r["organizer"].lower() for r in records if r.get("label") == "y" and r.get("organizer")}
    no_orgs = {r["organizer"].lower() for r in records if r.get("label") == "n" and r.get("organizer")}
    maybe_orgs = {r["organizer"].lower() for r in records if r.get("label") == "m" and r.get("organizer")}

    if org and org in yes_orgs:
        adj += 2
        reasons.append(f"feedback: you liked {event.get('organizer_name') or event.get('group_name')} before (+2)")
    elif org and org in no_orgs:
        adj -= 2
        reasons.append(f"feedback: you skipped {event.get('organizer_name') or event.get('group_name')} before (-2)")
    elif org and org in maybe_orgs:
        adj += 1
        reasons.append(f"feedback: maybe on similar organizer (+1)")

    yes_platforms = Counter(
        str(r.get("platform") or "").lower() for r in records if r.get("label") == "y" and r.get("platform")
    )
    no_platforms = Counter(
        str(r.get("platform") or "").lower() for r in records if r.get("label") == "n" and r.get("platform")
    )
    if platform and yes_platforms.get(platform, 0) >= 2:
        adj += 1
        reasons.append(f"feedback: you often say yes on {platform} (+1)")
    if platform and no_platforms.get(platform, 0) >= 2:
        adj -= 1
        reasons.append(f"feedback: you often skip {platform} (-1)")

    liked_kw: Counter[str] = Counter()
    skipped_kw: Counter[str] = Counter()
    for row in records:
        label = row.get("label")
        for kw in row.get("keywords") or []:
            kw_l = str(kw).lower()
            if label == "y":
                liked_kw[kw_l] += 1
            elif label == "n":
                skipped_kw[kw_l] += 1

    overlap_yes = [kw for kw in keywords if liked_kw.get(kw, 0) >= 1]
    overlap_no = [kw for kw in keywords if skipped_kw.get(kw, 0) >= 1]
    if len(overlap_yes) >= 2:
        adj += 1
        reasons.append(f"feedback: matches topics you liked ({', '.join(overlap_yes[:3])}) (+1)")
    if len(overlap_no) >= 2:
        adj -= 1
        reasons.append(f"feedback: matches topics you skipped ({', '.join(overlap_no[:3])}) (-1)")

    adj = max(-3, min(3, adj))
    return adj, reasons


def score_with_feedback(
    event: dict[str, Any],
    *,
    feedback_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base, base_why = score_event(event)
    records = feedback_records if feedback_records is not None else load_feedback()
    adj, adj_why = feedback_adjustment(event, records)
    final = max(0, min(10, base + adj))

    why = list(base_why)
    why.extend(adj_why)

    scored = dict(event)
    scored["base_score"] = base
    scored["feedback_adjustment"] = adj
    scored["relevance_score"] = final
    scored["why_selected"] = why
    scored["event_key"] = dedupe_key(event)
    return scored


def score_and_rank(
    events: list[dict[str, Any]],
    *,
    min_score: int = 4,
    feedback_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    records = feedback_records if feedback_records is not None else load_feedback()
    for event in events:
        scored = score_with_feedback(event, feedback_records=records)
        if int(scored.get("relevance_score") or 0) < min_score:
            continue
        rows.append(scored)
    rows.sort(
        key=lambda e: (
            -int(e.get("relevance_score") or 0),
            -int(e.get("base_score") or 0),
            e.get("source", ""),
            e.get("title", ""),
        )
    )
    return rows
