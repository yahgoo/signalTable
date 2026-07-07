#!/usr/bin/env python3
"""Normalize Apify Meetup export rows to the shared discovery schema."""

from __future__ import annotations

from typing import Any

from discovery_common import empty_event, _first_str
from registration_gateway import enrich_registration_fields


def _topics(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for topic in item.get("topics") or []:
        if isinstance(topic, dict):
            name = _first_str(topic.get("name"))
            if name:
                out.append(name)
        elif isinstance(topic, str) and topic.strip():
            out.append(topic.strip())
    return out


def _venue(item: dict[str, Any]) -> dict[str, Any]:
    venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    merged = {**address, **venue}
    return merged


def infer_meetup_free(item: dict[str, Any]) -> tuple[bool | None, str, str]:
    if item.get("isPaidEvent") is True:
        amt = item.get("feeAmount")
        cur = item.get("feeCurrency") or "USD"
        return False, f"fee {cur} {amt}".strip(), "isPaidEvent=true"
    if item.get("feeRequired") is True:
        amt = item.get("feeAmount")
        cur = item.get("feeCurrency") or ""
        text = f"{cur} {amt}".strip() if amt else "fee required"
        return False, text or "feeRequired=true", "feeRequired=true"
    if item.get("feeAmount") not in (None, "", 0, 0.0):
        cur = item.get("feeCurrency") or ""
        return False, f"{cur} {item.get('feeAmount')}".strip(), "feeAmount set"
    if item.get("isPaidEvent") is False:
        return True, "free", "isPaidEvent=false"
    return None, "", "free status unknown"


def infer_meetup_in_person(item: dict[str, Any]) -> tuple[bool, str]:
    if item.get("isOnline") is True:
        return False, "isOnline=true"
    event_type = str(item.get("eventType") or "").upper()
    if event_type == "ONLINE":
        return False, "eventType=ONLINE"
    if event_type == "HYBRID":
        return False, "eventType=HYBRID (in-person only policy)"
    if event_type == "PHYSICAL":
        return True, "eventType=PHYSICAL"
    return False, f"unknown eventType={event_type or 'missing'}"


def normalize_canonical(item: dict[str, Any], *, source_query: str = "") -> dict[str, Any]:
    venue = _venue(item)
    group = item.get("group") if isinstance(item.get("group"), dict) else {}
    hosts = item.get("hosts") if isinstance(item.get("hosts"), list) else []

    is_free, price_text, free_evidence = infer_meetup_free(item)
    is_in_person, in_person_evidence = infer_meetup_in_person(item)

    organizer = ""
    if hosts and isinstance(hosts[0], dict):
        organizer = _first_str(hosts[0].get("name"))
    if not organizer:
        organizer = _first_str(group.get("name"))

    city = _first_str(venue.get("city"))
    country = _first_str(venue.get("country"))
    venue_name = _first_str(venue.get("name"))
    full_address = _first_str(venue.get("address"))
    if city and full_address and city not in full_address:
        full_address = f"{full_address}, {city}"

    matched = source_query.strip().lower()
    event = empty_event("meetup", source_query=matched, matched_keyword=matched)
    event.update(
        {
            "title": _first_str(item.get("eventName"), item.get("title")),
            "description": _first_str(item.get("eventDescription"), item.get("description"))[:800],
            "start_time": _first_str(item.get("date")),
            "end_time": _first_str(item.get("endDateTime")),
            "timezone": "Asia/Singapore",
            "venue_name": venue_name,
            "full_address": full_address,
            "city": city,
            "country": country,
            "is_in_person": is_in_person,
            "in_person_evidence": in_person_evidence,
            "is_free": is_free,
            "price_text": price_text,
            "free_evidence": free_evidence,
            "organizer_name": organizer,
            "group_name": _first_str(group.get("name")),
            "url": _first_str(item.get("eventUrl"), item.get("eventShortUrl")),
            "source_event_id": _first_str(item.get("eventId")),
            "rsvp_count": item.get("actualAttendees"),
            "attendee_count": item.get("actualAttendees"),
            "approval_required": None,
            "waitlist_status": _first_str(item.get("eventStatus")),
            "raw_tags": _topics(item),
            "discovery_channel": "apify",
            "matched_keywords": [matched] if matched else [],
            # backward compat
            "platform": "meetup",
            "source_url": _first_str(item.get("eventUrl"), item.get("eventShortUrl")),
            "start_at": _first_str(item.get("date")),
            "end_at": _first_str(item.get("endDateTime")),
            "location": full_address or venue_name,
            "organizer": organizer,
            "summary": _first_str(item.get("eventDescription"))[:500],
        }
    )
    enrich_registration_fields(event)
    return event


def load_meetup_exports(paths: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Load one or more exports as (source_query, filepath) pairs."""
    import json
    from pathlib import Path

    rows: list[dict[str, Any]] = []
    for query, path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("events") or data.get("items") or []
        for item in items:
            if isinstance(item, dict):
                rows.append(normalize_canonical(item, source_query=query))
    return rows
