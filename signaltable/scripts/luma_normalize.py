#!/usr/bin/env python3
"""Normalize and deterministically filter Apify Luma dataset items.

Handles solidcode/luma-scraper rows (primary) and compact pre-normalized exports.
Schema assumptions: see docs/luma-apify-schema.md

Read-only — no auth flows.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

# solidcode/luma-scraper raw shape markers (see docs/luma-apify-schema.md)
SOLIDCODE_MARKERS = frozenset(
    {"api_id", "event", "name", "title", "start_at", "startAt", "eventUrl", "categoryNames"}
)
FOREIGN_ACTOR_MARKERS = frozenset(
    {"eventName", "pageUrl", "venueName", "startDate", "eventDescription", "venueAddress"}
)
CRITICAL_OUTPUT_FIELDS = ("title", "start_time", "url", "full_address", "description")

TECH_AI_CATEGORIES = {"ai", "tech"}

KEYWORDS = (
    "data",
    "algorithm",
    "compute",
    " ai ",
    "ai/",
    "ai-",
    "ai,",
    "ml",
    "llm",
    "genai",
    "developer",
    "engineering",
    "prompt",
    " agent",
    "agents",
    " model",
    "machine learning",
    "mlops",
)

LOW_SIGNAL_CATEGORIES = {
    "wellness",
    "fitness",
    "climate",
    "food & drink",
    "food",
    "arts & culture",
    "arts",
    "crypto",
}

STRONG_KEYWORDS = (
    "ai",
    "llm",
    "genai",
    "machine learning",
    "mlops",
    "algorithm",
    "data science",
    "developer",
    "engineering",
)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _category_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("categoryNames", "categories"):
        raw = item.get(key)
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, str) and entry.strip():
                    names.append(entry.strip())
                elif isinstance(entry, dict):
                    name = _first_str(entry.get("name"))
                    if name:
                        names.append(name)
    single = _first_str(item.get("category"))
    if single:
        names.append(single)
    return names


def _build_source_url(item: dict[str, Any], event: dict[str, Any]) -> str:
    for candidate in (
        item.get("eventUrl"),
        item.get("url"),
        event.get("url"),
        item.get("sourceUrl"),
        item.get("link"),
        item.get("pageUrl"),
        item.get("page_url"),
        item.get("publicUrl"),
        item.get("slug"),
    ):
        text = _first_str(candidate)
        if not text:
            continue
        if text.startswith("http://") or text.startswith("https://"):
            return text.replace("luma.com", "lu.ma")
        slug = text.lstrip("/")
        return f"https://lu.ma/{slug}"
    return ""


def _location_parts(item: dict[str, Any], event: dict[str, Any]) -> tuple[str, str, str]:
    geo = event.get("geo_address_info") if isinstance(event.get("geo_address_info"), dict) else {}
    loc = item.get("location") if isinstance(item.get("location"), dict) else {}
    featured = item.get("featured_city") if isinstance(item.get("featured_city"), dict) else {}
    venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}

    city = _first_str(
        geo.get("city"),
        loc.get("city"),
        venue.get("city"),
        featured.get("name") if featured.get("slug") == "singapore" else "",
        featured.get("name"),
        item.get("city") if isinstance(item.get("city"), str) else "",
    )
    country = _first_str(geo.get("country"), loc.get("country"), venue.get("country"))
    full_address = _first_str(
        geo.get("full_address"),
        loc.get("address"),
        loc.get("name"),
        item.get("venueName"),
        item.get("venueAddress"),
        venue.get("name"),
        venue.get("address"),
        item.get("location") if isinstance(item.get("location"), str) else "",
        item.get("address") if isinstance(item.get("address"), str) else "",
    )
    if city and country and city not in full_address:
        location = ", ".join(p for p in (full_address or city, country) if p)
    else:
        location = full_address or ", ".join(p for p in (city, country) if p)
    return city, country, location


def _organizer(item: dict[str, Any]) -> str:
    org = item.get("organizer")
    if isinstance(org, dict):
        name = _first_str(org.get("name"))
        if name:
            return name
    for key in ("host_info", "manager_info"):
        info = item.get(key)
        if isinstance(info, dict):
            name = _first_str(info.get("name"))
            if name:
                return name
    hosts = item.get("hosts")
    if isinstance(hosts, list) and hosts:
        first = hosts[0]
        if isinstance(first, dict):
            return _first_str(first.get("name"))
    return _first_str(item.get("hostName"), item.get("organizerName"))


def _summary(item: dict[str, Any]) -> str:
    mirror = item.get("description_mirror")
    if isinstance(mirror, dict):
        text = _first_str(mirror.get("text"), mirror.get("content"))
    else:
        text = _first_str(mirror)
    if not text:
        guest = item.get("guest_info")
        if isinstance(guest, dict):
            text = _first_str(guest.get("description"))
    if not text:
        cal = item.get("calendar")
        if isinstance(cal, dict):
            text = _first_str(cal.get("description_short"))
    if not text:
        text = _first_str(item.get("description"), item.get("summary"), item.get("subtitle"))
    if not text:
        text = _first_str(item.get("eventDescription"), item.get("body"))
        if isinstance(item.get("details"), dict):
            text = text or _first_str(item["details"].get("text"), item["details"].get("description"))
    return text[:500]


def _ticketing(item: dict[str, Any]) -> tuple[bool | None, bool | None, bool | None]:
    ticketing = item.get("ticketing")
    ticket_info = item.get("ticket_info")
    is_free = requires_approval = is_sold_out = None

    if isinstance(ticketing, dict):
        if ticketing.get("isFree") is not None:
            is_free = bool(ticketing.get("isFree"))
        if ticketing.get("requiresApproval") is not None:
            requires_approval = bool(ticketing.get("requiresApproval"))
        if ticketing.get("isSoldOut") is not None:
            is_sold_out = bool(ticketing.get("isSoldOut"))

    if isinstance(ticket_info, dict):
        if ticket_info.get("is_free") is not None:
            is_free = bool(ticket_info.get("is_free"))
        if ticket_info.get("require_approval") is not None:
            requires_approval = bool(ticket_info.get("require_approval"))
        if ticket_info.get("is_sold_out") is not None:
            is_sold_out = bool(ticket_info.get("is_sold_out"))

    if item.get("isFree") is not None:
        is_free = bool(item.get("isFree"))
    if item.get("is_free") is not None and is_free is None:
        is_free = bool(item.get("is_free"))

    if item.get("sold_out") is not None:
        is_sold_out = bool(item.get("sold_out"))
    return is_free, requires_approval, is_sold_out


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SGT)
    return dt


def _has_solidcode_markers(item: dict[str, Any]) -> bool:
    return any(key in item for key in SOLIDCODE_MARKERS)


def _has_foreign_actor_markers(item: dict[str, Any]) -> bool:
    return any(key in item for key in FOREIGN_ACTOR_MARKERS)


def inspect_luma_schema(item: dict[str, Any], *, normalized: dict[str, Any] | None = None) -> list[str]:
    """Return schema drift warnings for a raw (and optional normalized) Luma row."""
    warns: list[str] = []

    if _has_foreign_actor_markers(item) and not _has_solidcode_markers(item):
        foreign = sorted(k for k in FOREIGN_ACTOR_MARKERS if k in item)
        warns.append(
            f"possible_non_solidcode_actor_schema: foreign fields {foreign} without solidcode markers"
        )

    if is_raw_apify_item(item):
        if not _has_solidcode_markers(item):
            warns.append("missing_solidcode_markers: expected api_id, event, or name/title + start_at")
        if not _first_str(item.get("name"), item.get("title"), (item.get("event") or {}).get("name")):
            warns.append("missing_expected_field:title")
        if not _first_str(
            item.get("start_at"),
            item.get("startAt"),
            (item.get("event") or {}).get("start_at"),
            (item.get("event") or {}).get("startAt"),
        ):
            warns.append("missing_expected_field:start_at")
        for key in ("start_at", "startAt", "end_at", "endAt", "name", "title"):
            if key in item and item[key] is not None and not isinstance(item[key], str):
                warns.append(f"unexpected_type:{key}")
        if isinstance(item.get("event"), dict):
            for key in ("start_at", "startAt"):
                val = item["event"].get(key)
                if val is not None and not isinstance(val, str):
                    warns.append(f"unexpected_type:event.{key}")
    elif not (
        (item.get("platform") == "luma" and item.get("start_at"))
        or (item.get("source") == "luma" and item.get("start_time"))
    ):
        if _has_foreign_actor_markers(item):
            warns.append("unexpected_item_shape: not raw solidcode, compact luma, or pre-normalized row")

    if normalized is not None:
        for field in CRITICAL_OUTPUT_FIELDS:
            value = normalized.get(field)
            if field == "full_address":
                value = value or normalized.get("venue_name") or normalized.get("location")
            if not _first_str(value):
                warns.append(f"missing_critical_field:{field}")
        if normalized.get("is_free") is None and not _first_str(normalized.get("price_text")):
            warns.append("missing_critical_field:price")

    return warns


def _emit_schema_warnings(item: dict[str, Any], msgs: list[str]) -> None:
    title = _first_str(item.get("name"), item.get("title"), item.get("eventName"), "(untitled)")
    for msg in msgs:
        warnings.warn(f"luma_schema[{title[:40]}]: {msg}", stacklevel=3)


def _coalesce_compact_item(item: dict[str, Any]) -> dict[str, Any]:
    """Map compact / pre-normalized rows onto fields normalize_canonical expects."""
    row = dict(item)
    if not row.get("source_url"):
        row["source_url"] = _first_str(row.get("event_page_url"), row.get("url"))
    if not row.get("start_at"):
        row["start_at"] = _first_str(row.get("start_time"), row.get("date"))
    if not row.get("summary"):
        row["summary"] = _first_str(row.get("description"))
    if not row.get("location"):
        row["location"] = _first_str(row.get("full_address"), row.get("venue_name"))
    return row


def normalize_canonical(item: dict[str, Any], *, source_query: str = "") -> dict[str, Any]:
    """Map raw or compact Luma row to the shared discovery schema."""
    from discovery_common import empty_event

    schema_warnings = inspect_luma_schema(item)

    if is_raw_apify_item(item) or item.get("event"):
        base = normalize_raw_item(item)
    elif item.get("platform") == "luma" and item.get("start_at"):
        base = _coalesce_compact_item(item)
    elif item.get("source") == "luma" and item.get("start_time"):
        base = _coalesce_compact_item(
            {
                **item,
                "platform": "luma",
                "start_at": item.get("start_time"),
                "end_at": item.get("end_time"),
            }
        )
    else:
        base = _coalesce_compact_item(normalize_raw_item(item))

    event_obj = item.get("event") if isinstance(item.get("event"), dict) else {}

    location_type = _first_str(event_obj.get("location_type"), item.get("location_type")).lower()
    is_in_person = False
    in_person_evidence = ""
    if location_type == "offline":
        is_in_person = True
        in_person_evidence = "location_type=offline"
    elif location_type in {"zoom", "online", "virtual"}:
        is_in_person = False
        in_person_evidence = f"location_type={location_type}"
    elif base.get("city") or base.get("location"):
        is_in_person = True
        in_person_evidence = "offline geo/address present"

    is_free, price_text, free_evidence = _infer_luma_free(item, base)
    waitlist = ""
    if event_obj.get("waitlist_enabled"):
        waitlist = _first_str(event_obj.get("waitlist_status"), "enabled")

    matched = source_query.strip().lower()
    if not matched and isinstance(item.get("source_query"), str):
        matched = item["source_query"].strip().lower()

    description = _first_str(base.get("summary"), base.get("description"))
    if not description and (is_raw_apify_item(item) or item.get("event")):
        description = _summary(item)

    page_url = _first_str(
        base.get("source_url"),
        item.get("url"),
        item.get("eventUrl"),
        item.get("pageUrl"),
        item.get("event_page_url"),
    )
    venue_label = _first_str(base.get("location"), base.get("venue_name"))
    if not venue_label and isinstance(event_obj.get("geo_address_info"), dict):
        venue_label = _first_str(event_obj["geo_address_info"].get("full_address"))

    event = empty_event("luma", source_query=matched, matched_keyword=matched)
    event.update(
        {
            "title": _first_str(base.get("title"), item.get("name"), item.get("eventName")),
            "description": description,
            "start_time": _first_str(base.get("start_at"), base.get("start_time"), item.get("startDate")),
            "end_time": _first_str(base.get("end_at"), base.get("end_time"), item.get("endDate")),
            "timezone": base.get("timezone") or "Asia/Singapore",
            "venue_name": venue_label,
            "full_address": venue_label,
            "city": base.get("city", ""),
            "country": base.get("country", ""),
            "featured_city": base.get("featured_city", ""),
            "is_in_person": is_in_person,
            "in_person_evidence": in_person_evidence,
            "is_free": is_free,
            "price_text": price_text,
            "free_evidence": free_evidence,
            "organizer_name": base.get("organizer", ""),
            "group_name": "",
            "url": page_url,
            "event_page_url": page_url,
            "source_event_id": _first_str(item.get("api_id"), event_obj.get("api_id")),
            "rsvp_count": item.get("guest_count"),
            "attendee_count": item.get("guest_count"),
            "approval_required": base.get("requires_approval"),
            "waitlist_status": waitlist,
            "raw_tags": list(base.get("categories") or []),
            "discovery_channel": "apify",
            "matched_keywords": [matched] if matched else [],
            **{k: base[k] for k in ("platform", "source_url", "start_at", "end_at", "summary", "location", "organizer", "categories", "raw_category", "requires_approval", "is_sold_out") if k in base},
        }
    )

    post_warnings = inspect_luma_schema(item, normalized=event)
    all_warnings = schema_warnings + [w for w in post_warnings if w not in schema_warnings]
    if all_warnings:
        event["normalization_warnings"] = all_warnings
        _emit_schema_warnings(item, all_warnings)

    return event


def _infer_luma_free(item: dict[str, Any], base: dict[str, Any]) -> tuple[bool | None, str, str]:
    ticket_info = item.get("ticket_info") if isinstance(item.get("ticket_info"), dict) else {}
    ticketing = item.get("ticketing") if isinstance(item.get("ticketing"), dict) else {}

    if ticket_info.get("is_free") is True or ticketing.get("isFree") is True:
        return True, "free", "ticket_info/ticketing is_free=true"
    if ticket_info.get("is_free") is False or ticketing.get("isFree") is False:
        price = ticket_info.get("price") or ticket_info.get("max_price") or ticketing.get("price")
        text = str(price) if price not in (None, "", 0) else "paid ticket type"
        return False, text, "ticket marked paid"

    ticket_types = item.get("ticket_types") or item.get("ticketTypes") or []
    if isinstance(ticket_types, list):
        names = [str(t.get("name", "")).lower() for t in ticket_types if isinstance(t, dict)]
        if any("free" in n for n in names):
            return True, "free", "ticket type name contains Free"
        if any(n for n in names if "free" not in n and n):
            return False, ", ".join(names[:2]), "non-free ticket type present"

    if base.get("is_free") is True:
        return True, "free", "normalized is_free=true"
    if base.get("is_free") is False:
        return False, "paid", "normalized is_free=false"

    text_blob = f" {base.get('summary','')} {base.get('description','')} ".lower()
    if "free" in text_blob and "free trial" not in text_blob:
        return True, "free", "summary/description mentions free"
    paid_markers = ("sgd", "usd", "$", "paid admission", "ticket price")
    if any(x in text_blob for x in paid_markers):
        return False, "paid (text)", "summary/description suggests paid"

    return None, "", "free status unknown"


def normalize_raw_item(item: dict[str, Any]) -> dict[str, Any]:
    """Map raw Apify/API row to compact canonical schema."""
    event = item.get("event") if isinstance(item.get("event"), dict) else {}
    categories = _category_names(item)
    city, country, location = _location_parts(item, event)
    is_free, requires_approval, is_sold_out = _ticketing(item)

    start_at = _first_str(
        item.get("start_at"),
        item.get("startAt"),
        event.get("start_at"),
        event.get("startAt"),
        item.get("startDate"),
        item.get("start_date"),
    )
    end_at = _first_str(
        item.get("end_at"),
        item.get("endAt"),
        event.get("end_at"),
        event.get("endAt"),
        item.get("endDate"),
        item.get("end_date"),
    )
    timezone = _first_str(item.get("timezone"), event.get("timezone"))

    featured = item.get("featured_city") if isinstance(item.get("featured_city"), dict) else {}
    featured_city = _first_str(featured.get("name"), featured.get("slug"))

    return {
        "platform": "luma",
        "title": _first_str(
            item.get("name"),
            item.get("title"),
            event.get("name"),
            item.get("eventTitle"),
            item.get("eventName"),
        ),
        "start_at": start_at,
        "end_at": end_at,
        "timezone": timezone,
        "city": city,
        "country": country,
        "location": location,
        "source_url": _build_source_url(item, event),
        "organizer": _organizer(item),
        "summary": _summary(item),
        "raw_category": ", ".join(categories),
        "categories": categories,
        "featured_city": featured_city,
        "is_free": is_free,
        "requires_approval": requires_approval,
        "is_sold_out": is_sold_out,
        # backward compat for report scoring
        "date": start_at,
    }


def is_raw_apify_item(item: dict[str, Any]) -> bool:
    if item.get("platform") == "luma" and item.get("start_at") and not item.get("api_id"):
        return False
    return bool(item.get("api_id") or isinstance(item.get("event"), dict))


def _text_blob(event: dict[str, Any]) -> str:
    parts = [
        event.get("title", ""),
        event.get("summary", ""),
        event.get("organizer", ""),
        event.get("raw_category", ""),
        " ".join(event.get("categories") or []),
    ]
    return f" {' '.join(str(p) for p in parts)} ".lower()


def _keyword_hit(text: str, keyword: str) -> bool:
    if keyword.startswith(" ") or keyword.endswith(" "):
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def has_strong_keyword_match(event: dict[str, Any]) -> bool:
    text = _text_blob(event)
    return any(_keyword_hit(text, kw) for kw in KEYWORDS) or any(
        _keyword_hit(text, kw) for kw in STRONG_KEYWORDS
    )


def has_tech_ai_category(event: dict[str, Any]) -> bool:
    for name in event.get("categories") or []:
        if str(name).strip().lower() in TECH_AI_CATEGORIES:
            return True
    return False


def is_irrelevant_category(event: dict[str, Any]) -> bool:
    cats = [str(c).strip().lower() for c in (event.get("categories") or [])]
    if not cats:
        return False
    return all(any(low in c for low in LOW_SIGNAL_CATEGORIES) for c in cats)


def is_singapore_event(event: dict[str, Any]) -> bool:
    city = str(event.get("city", "")).lower()
    country = str(event.get("country", "")).lower()
    location = str(event.get("location", "")).lower()
    featured = str(event.get("featured_city", "")).lower()

    positive = (
        "singapore" in city
        or country == "singapore"
        or "singapore" in country
        or "singapore" in location
        or featured in {"singapore", "sg"}
        or "singapore" in featured
    )
    if positive:
        return True

    negative_markers = (
        "united states",
        "denver",
        "san francisco",
        "new york",
        "london",
        "tokyo",
        "berlin",
        "paris",
        "australia",
        "canada",
        "germany",
        "france",
        "japan",
        "uk",
        "united kingdom",
    )
    if any(marker in location or marker in city or marker in country for marker in negative_markers):
        return False

    # Unknown location — reject (do not guess Singapore)
    return False


def is_upcoming_event(event: dict[str, Any], *, now: datetime | None = None) -> bool:
    start = parse_datetime(str(event.get("start_at") or event.get("date") or ""))
    if start is None:
        return False
    current = now or datetime.now(SGT)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SGT)
    return start.astimezone(SGT) >= current.astimezone(SGT)


def is_tech_ai_relevant(event: dict[str, Any]) -> bool:
    if has_tech_ai_category(event):
        return True
    if has_strong_keyword_match(event):
        return True
    if is_irrelevant_category(event):
        return False
    return False


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_fallback: set[str] = set()
    out: list[dict[str, Any]] = []

    for event in events:
        url = str(event.get("source_url") or "").strip().lower().rstrip("/")
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            out.append(event)
            continue

        title = re.sub(r"\s+", " ", str(event.get("title", "")).strip().lower())
        start = str(event.get("start_at") or event.get("date") or "")[:10]
        key = f"{title}|{start}"
        if not title or key in seen_fallback:
            continue
        seen_fallback.add(key)
        out.append(event)
    return out


def filter_pipeline(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return filtered events and stage counts for debug output."""
    counts = {"raw": len(events)}

    upcoming = [e for e in events if is_upcoming_event(e, now=now)]
    counts["upcoming"] = len(upcoming)

    singapore = [e for e in upcoming if is_singapore_event(e)]
    counts["singapore"] = len(singapore)

    tech_ai = [e for e in singapore if is_tech_ai_relevant(e)]
    counts["tech_ai"] = len(tech_ai)

    deduped = dedupe_events(tech_ai)
    counts["deduped"] = len(deduped)

    return deduped, counts


def dominant_filter_drop(counts: dict[str, int]) -> str:
    """Explain which filter removed the most rows."""
    stages = [
        ("upcoming", counts.get("raw", 0) - counts.get("upcoming", 0)),
        ("singapore", counts.get("upcoming", 0) - counts.get("singapore", 0)),
        ("tech_ai", counts.get("singapore", 0) - counts.get("tech_ai", 0)),
        ("deduped", counts.get("tech_ai", 0) - counts.get("deduped", 0)),
    ]
    stage, dropped = max(stages, key=lambda pair: pair[1])
    if dropped <= 0:
        return "blocker: no rows matched Singapore Tech/AI upcoming filters"
    return f"blocker: {stage} filter removed the most rows ({dropped})"


SOLIDCODE_SELF_TEST_ITEM: dict[str, Any] = {
    "api_id": "evt-selftest-solidcode",
    "name": "Singapore AI Builders Meetup",
    "url": "https://lu.ma/sg-ai-builders",
    "start_at": "2026-08-01T18:30:00+08:00",
    "end_at": "2026-08-01T20:00:00+08:00",
    "categories": [{"name": "AI"}, {"name": "Tech"}],
    "event": {
        "api_id": "evt-selftest-solidcode",
        "timezone": "Asia/Singapore",
        "location_type": "offline",
        "geo_address_info": {
            "city": "Singapore",
            "country": "Singapore",
            "full_address": "71 Ayer Rajah Crescent, Singapore",
        },
    },
    "ticket_info": {"is_free": True},
    "description_mirror": {"text": "Hands-on evening on eval harnesses and regression tests."},
    "hosts": [{"name": "Singapore AI Builders"}],
}

WRONG_SHAPE_SELF_TEST_ITEM: dict[str, Any] = {
    "eventName": "Foreign Actor Schema Simulation",
    "pageUrl": "https://lu.ma/foreign-actor-schema-sim",
    "venueName": "Some Venue, Singapore",
    "startDate": "2026-08-15T19:00:00+08:00",
    "eventDescription": "Free event. Lexis-like row: foreign field names only, no solidcode markers.",
}


def _critical_fields_populated(event: dict[str, Any]) -> dict[str, bool]:
    venue = _first_str(event.get("full_address"), event.get("venue_name"), event.get("location"))
    price_ok = event.get("is_free") is not None or bool(_first_str(event.get("price_text")))
    return {
        "title": bool(_first_str(event.get("title"))),
        "start_time": bool(_first_str(event.get("start_time"))),
        "url": bool(_first_str(event.get("url"), event.get("event_page_url"))),
        "venue": bool(venue),
        "description": bool(_first_str(event.get("description"))),
        "price": price_ok,
    }


def run_self_test() -> int:
    import argparse

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        solid = normalize_canonical(SOLIDCODE_SELF_TEST_ITEM, source_query="ai")
        wrong = normalize_canonical(WRONG_SHAPE_SELF_TEST_ITEM, source_query="data")

    solid_warns = list(solid.get("normalization_warnings") or [])
    wrong_warns = list(wrong.get("normalization_warnings") or [])
    solid_critical = _critical_fields_populated(solid)
    wrong_critical = _critical_fields_populated(wrong)

    checks = {
        "solidcode_shape_ok": not any("possible_non_solidcode" in w for w in solid_warns),
        "solidcode_no_missing_critical": not any(
            w.startswith("missing_critical_field:") for w in solid_warns
        ),
        "solidcode_critical_populated": all(solid_critical.values()),
        "wrong_shape_warns_foreign_schema": any(
            "possible_non_solidcode_actor_schema" in w for w in wrong_warns
        ),
        "wrong_shape_has_normalization_warnings": bool(wrong_warns),
        "wrong_shape_critical_not_blank": all(wrong_critical.values()),
        "wrong_shape_title_from_eventName": solid.get("title") != "" and wrong.get("title") != "",
        "wrong_shape_url_from_pageUrl": wrong.get("url") == "https://lu.ma/foreign-actor-schema-sim",
    }

    payload = {
        "checks": checks,
        "pass": all(checks.values()),
        "solidcode_warnings": solid_warns,
        "wrong_shape_warnings": wrong_warns,
        "solidcode_critical": solid_critical,
        "wrong_shape_critical": wrong_critical,
        "stderr_warning_count": len(caught),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Luma Apify normalizer and filters")
    parser.add_argument("--self-test", action="store_true", help="Schema drift regression checks")
    args = parser.parse_args()
    if args.self_test:
        return run_self_test()
    parser.error("--self-test required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
