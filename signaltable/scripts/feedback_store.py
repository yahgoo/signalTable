#!/usr/bin/env python3
"""Preference feedback store for SignalTable Version A (y / n / m labels)."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

DEFAULT_FEEDBACK = Path.home() / ".hermes/profiles/signaltable/event_feedback.jsonl"
DEFAULT_PENDING = Path.home() / ".hermes/profiles/signaltable/pending_shortlist.json"

VALID_LABELS = frozenset({"y", "n", "m"})


def _now_iso() -> str:
    return datetime.now(SGT).isoformat()


def normalize_reply(text: str) -> str | None:
    token = text.strip().lower()
    if token in {"y", "yes"}:
        return "y"
    if token in {"n", "no", "skip"}:
        return "n"
    if token in {"m", "maybe"}:
        return "m"
    return None


def load_feedback(path: Path | None = None) -> list[dict[str, Any]]:
    fp = path or DEFAULT_FEEDBACK
    if not fp.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("label") in VALID_LABELS:
            rows.append(row)
    return rows


def append_feedback(record: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    fp = path or DEFAULT_FEEDBACK
    label = record.get("label")
    if label not in VALID_LABELS:
        raise ValueError(f"label must be one of {sorted(VALID_LABELS)}")

    row = {
        "id": record.get("id") or uuid.uuid4().hex[:12],
        "label": label,
        "event_key": record.get("event_key") or "",
        "title": record.get("title") or "",
        "platform": record.get("platform") or "",
        "organizer": record.get("organizer") or "",
        "keywords": list(record.get("keywords") or []),
        "base_score": record.get("base_score"),
        "final_score": record.get("final_score"),
        "queue_index": record.get("queue_index"),
        "queue_total": record.get("queue_total"),
        "reply_text": record.get("reply_text") or "",
        "capture_mode": record.get("capture_mode") or "",
        "recorded_at": record.get("recorded_at") or _now_iso(),
    }
    fp.parent.mkdir(parents=True, exist_ok=True)
    with fp.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def summarize_preferences(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(r["label"] for r in records)
    liked_orgs = [r["organizer"] for r in records if r.get("label") == "y" and r.get("organizer")]
    skipped_orgs = [r["organizer"] for r in records if r.get("label") == "n" and r.get("organizer")]
    liked_kw: Counter[str] = Counter()
    skipped_kw: Counter[str] = Counter()
    for row in records:
        kws = row.get("keywords") or []
        bucket = liked_kw if row.get("label") == "y" else skipped_kw if row.get("label") == "n" else None
        if bucket is not None:
            for kw in kws:
                bucket[str(kw).lower()] += 1
    return {
        "total": len(records),
        "counts": dict(counts),
        "liked_organizers": Counter(liked_orgs).most_common(5),
        "skipped_organizers": Counter(skipped_orgs).most_common(5),
        "liked_keywords": liked_kw.most_common(8),
        "skipped_keywords": skipped_kw.most_common(8),
    }


def load_pending(path: Path | None = None) -> dict[str, Any]:
    fp = path or DEFAULT_PENDING
    if not fp.is_file():
        return {"pending": [], "sent_index": 0}
    data = json.loads(fp.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"pending": [], "sent_index": 0}
    data.setdefault("pending", [])
    data.setdefault("sent_index", 0)
    data.setdefault("replied_index", 0)
    return data


def save_pending(data: dict[str, Any], path: Path | None = None) -> None:
    fp = path or DEFAULT_PENDING
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(fp)


def queue_shortlist(events: list[dict[str, Any]], path: Path | None = None) -> dict[str, Any]:
    pending = {
        "created_at": _now_iso(),
        "pending": events,
        "sent_index": 0,
    }
    save_pending(pending, path)
    return pending


def pop_current_event(path: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    data = load_pending(path)
    idx = int(data.get("sent_index") or 0)
    events = data.get("pending") or []
    if idx >= len(events):
        return None, data
    event = events[idx]
    data["sent_index"] = idx + 1
    save_pending(data, path)
    return event, data


def pending_remaining(path: Path | None = None) -> int:
    data = load_pending(path)
    sent = int(data.get("sent_index") or 0)
    replied = int(data.get("replied_index") or 0)
    return max(0, sent - replied)


def has_awaiting_shortlist_reply(path: Path | None = None) -> bool:
    data = load_pending(path)
    sent = int(data.get("sent_index") or 0)
    replied = int(data.get("replied_index") or 0)
    return replied < sent


def get_awaiting_shortlist_event(path: Path | None = None) -> dict[str, Any] | None:
    data = load_pending(path)
    replied = int(data.get("replied_index") or 0)
    events = data.get("pending") or []
    if replied >= len(events) or replied >= int(data.get("sent_index") or 0):
        return None
    event = events[replied]
    return event if isinstance(event, dict) else None
