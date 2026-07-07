#!/usr/bin/env python3
"""Normalize and deterministically filter Apify Luma dataset items.

Handles both solidcode/luma-scraper rows and nested lu.ma API-style exports.
Read-only — no auth flows.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

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

    city = _first_str(
        geo.get("city"),
        loc.get("city"),
        featured.get("name") if featured.get("slug") == "singapore" else "",
        featured.get("name"),
    )
    country = _first_str(geo.get("country"), loc.get("country"))
    full_address = _first_str(
        geo.get("full_address"),
        loc.get("address"),
        loc.get("name"),
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


def normalize_canonical(item: dict[str, Any], *, source_query: str = "") -> dict[str, Any]:
    """Map raw or compact Luma row to the shared discovery schema."""
    from discovery_common import empty_event

    base = normalize_raw_item(item) if is_raw_apify_item(item) or item.get("event") else dict(item)
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

    event = empty_event("luma", source_query=matched, matched_keyword=matched)
    event.update(
        {
            "title": base.get("title", ""),
            "description": base.get("summary", ""),
            "start_time": base.get("start_at", ""),
            "end_time": base.get("end_at", ""),
            "timezone": base.get("timezone") or "Asia/Singapore",
            "venue_name": _first_str(base.get("location"), event_obj.get("geo_address_info", {}).get("city") if isinstance(event_obj.get("geo_address_info"), dict) else ""),
            "full_address": base.get("location", ""),
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
            "url": base.get("source_url", ""),
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

    start_at = _first_str(item.get("start_at"), item.get("startAt"), event.get("start_at"), event.get("startAt"))
    end_at = _first_str(item.get("end_at"), item.get("endAt"), event.get("end_at"), event.get("endAt"))
    timezone = _first_str(item.get("timezone"), event.get("timezone"))

    featured = item.get("featured_city") if isinstance(item.get("featured_city"), dict) else {}
    featured_city = _first_str(featured.get("name"), featured.get("slug"))

    return {
        "platform": "luma",
        "title": _first_str(item.get("name"), item.get("title"), event.get("name"), item.get("eventTitle")),
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
