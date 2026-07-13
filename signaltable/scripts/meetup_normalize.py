#!/usr/bin/env python3
"""Normalize Apify Meetup export rows to the shared discovery schema."""

from __future__ import annotations

import argparse
import json
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


def _registration_venue_block(item: dict[str, Any]) -> dict[str, Any]:
    """Optional external/ticket venue from export metadata (never overwrites Meetup venue)."""
    for key in ("registrationVenue", "registration_venue", "ticketVenue", "ticket_venue"):
        block = item.get(key)
        if isinstance(block, dict):
            return block
    return {}


def apply_meetup_venue_precedence(event: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Set card venue fields with explicit Meetup-first precedence.

    Precedence for `Where:` / venue_name / full_address:
      1. Meetup export `venue` (+ top-level `address`) — primary, authoritative
      2. registration_venue_* — separate optional fields for KonfHub/ticket venue
      3. Never derive primary venue from description text or registration URLs
    """
    venue = _venue(item)
    city = _first_str(venue.get("city"))
    country = _first_str(venue.get("country"))
    meetup_name = _first_str(venue.get("name"))
    meetup_address = _first_str(venue.get("address"))
    if city and meetup_address and city not in meetup_address:
        meetup_address = f"{meetup_address}, {city}"

    event["meetup_venue_name"] = meetup_name
    event["meetup_venue_address"] = meetup_address
    event["venue_name"] = meetup_name
    event["full_address"] = meetup_address
    event["city"] = city
    event["country"] = country
    event["location"] = meetup_address or meetup_name

    reg = _registration_venue_block(item)
    reg_name = _first_str(reg.get("name"))
    reg_address = _first_str(reg.get("address"))
    reg_city = _first_str(reg.get("city"))
    if reg_city and reg_address and reg_city not in reg_address:
        reg_address = f"{reg_address}, {reg_city}"
    reg_source = _first_str(reg.get("source"), "registration")

    if reg_name or reg_address:
        event["registration_venue_name"] = reg_name
        event["registration_venue_address"] = reg_address
        event["registration_venue_source"] = reg_source

    return event


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
    group = item.get("group") if isinstance(item.get("group"), dict) else {}
    hosts = item.get("hosts") if isinstance(item.get("hosts"), list) else []

    is_free, price_text, free_evidence = infer_meetup_free(item)
    is_in_person, in_person_evidence = infer_meetup_in_person(item)

    organizer = ""
    if hosts and isinstance(hosts[0], dict):
        organizer = _first_str(hosts[0].get("name"))
    if not organizer:
        organizer = _first_str(group.get("name"))

    matched = source_query.strip().lower()
    event = empty_event("meetup", source_query=matched, matched_keyword=matched)
    event.update(
        {
            "title": _first_str(item.get("eventName"), item.get("title")),
            "description": _first_str(item.get("eventDescription"), item.get("description"))[:800],
            "start_time": _first_str(item.get("date")),
            "end_time": _first_str(item.get("endDateTime")),
            "timezone": "Asia/Singapore",
            "is_in_person": is_in_person,
            "in_person_evidence": in_person_evidence,
            "is_free": is_free,
            "price_text": price_text,
            "free_evidence": free_evidence,
            "organizer_name": organizer,
            "group_name": _first_str(group.get("name")),
            "url": _first_str(item.get("eventUrl"), item.get("eventShortUrl")),
            "event_page_url": _first_str(item.get("eventUrl"), item.get("eventShortUrl")),
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
            "organizer": organizer,
            "summary": _first_str(item.get("eventDescription"))[:500],
        }
    )
    apply_meetup_venue_precedence(event, item)
    enrich_registration_fields(event)
    return event


def load_meetup_exports(paths: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Load one or more exports as (source_query, filepath) pairs."""
    from pathlib import Path

    rows: list[dict[str, Any]] = []
    for query, path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("events") or data.get("items") or []
        for item in items:
            if isinstance(item, dict):
                rows.append(normalize_canonical(item, source_query=query))
    return rows


def run_self_test() -> int:
    from version_a import format_event_card

    dbt_item = {
        "eventId": "315295343",
        "eventName": "Singapore dbt Meetup (in-person) - Jul 2026",
        "eventDescription": (
            "Talks on analytics engineering and data quality. "
            "Register on KonfHub: https://konfhub.com/e/sg-dbt-meetup-jul-2026 Free event; lunch provided."
        ),
        "eventUrl": "https://www.meetup.com/singapore-dbt-meetup/events/315295343/",
        "date": "2026-07-09T18:30:00+08:00",
        "eventType": "PHYSICAL",
        "isOnline": False,
        "isPaidEvent": False,
        "venue": {
            "name": "Monk's Brew Club",
            "city": "Singapore",
            "country": "SG",
            "address": "57 East Coast Road",
        },
        "registrationVenue": {
            "name": "Thoughtworks Singapore",
            "address": "182 Cecil Street, Frasers Tower",
            "source": "konfhub",
        },
        "group": {"name": "Singapore dbt Meetup"},
    }

    from event_url_check import canonical_event_url

    meetup_url = "https://www.meetup.com/singapore-dbt-meetup/events/315295343/"
    event = normalize_canonical(dbt_item, source_query="data")
    card = format_event_card(event, index=1)

    checks = {
        "primary_meetup_venue_name": event.get("meetup_venue_name") == "Monk's Brew Club",
        "primary_meetup_venue_address": "57 East Coast Road" in (event.get("meetup_venue_address") or ""),
        "card_where_uses_meetup_venue": "Monk's Brew Club, 57 East Coast Road" in card,
        "card_where_not_thoughtworks": "Thoughtworks Singapore" not in card.split("Registration venue:")[0],
        "registration_venue_separate": event.get("registration_venue_name") == "Thoughtworks Singapore",
        "registration_venue_on_card": "Registration venue: Thoughtworks Singapore, 182 Cecil Street, Frasers Tower" in card,
        "canonical_meetup_url": canonical_event_url(event) == meetup_url,
        "card_has_meetup_url_line": f"URL: {meetup_url}" in card,
        "card_url_not_konfhub": "konfhub.com" not in next(
            (line for line in card.splitlines() if line.startswith("URL:")), "URL:"
        ),
        "konfhub_url_preserved": event.get("registration_platform") == "konfhub",
        "venue_not_from_description": event.get("venue_name") == event.get("meetup_venue_name"),
    }
    payload = {
        "checks": checks,
        "pass": all(checks.values()),
        "card_where": [ln for ln in card.splitlines() if ln.startswith("Where:") or ln.startswith("Registration venue:")],
        "card_url": next((ln for ln in card.splitlines() if ln.startswith("URL:")), ""),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Meetup export normalizer")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    parser.error("--self-test required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
