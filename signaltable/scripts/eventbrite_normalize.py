#!/usr/bin/env python3
"""Normalize Eventbrite Apify export rows to the shared discovery schema.

Supports common flat export shapes (nexgendata, khadinakbar, oriented_wallpaper,
shahidirfan, parseforge actors). Field names vary — see EVENTBRITE_FIELD_NOTES.

Primary production task: eventbrite-science-tech-singapore-free
Default source_query label: science-tech
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from discovery_common import empty_event, _first_str

SGT = ZoneInfo("Asia/Singapore")

DEFAULT_SOURCE_QUERY = "science-tech"
DEFAULT_TASK_NAME = "eventbrite-science-tech-singapore-free"

# Documented for operators — verify against your Apify actor export.
EVENTBRITE_FIELD_NOTES = """
Supported shapes:
- Flat Apify rows (isFree, venueCity, priceMin, isOnline, category, ...)
- schema.org JSON-LD rows (@type SocialEvent, location Place, offers AggregateOffer)

JSON-LD mapping (verified against dataset_eventbrite-science-tech-biz-singapore-free):
- location.name -> venue_name
- location.address.streetAddress -> full_address
- location.address.addressLocality -> city
- location.address.addressCountry -> country
- eventAttendanceMode OfflineEventAttendanceMode -> in-person
- offers[].lowPrice/highPrice/priceCurrency -> free/paid inference
- organizer.name -> organizer_name

Note: JSON-LD exports may omit category/tags; tech filter may rely on title/description keywords.
"""


def _nested_dict(item: dict[str, Any], key: str) -> dict[str, Any]:
    val = item.get(key)
    return val if isinstance(val, dict) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _tags(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("tags", "categories"):
        for entry in _as_list(item.get(key)):
            if isinstance(entry, str) and entry.strip():
                out.append(entry.strip())
            elif isinstance(entry, dict):
                name = _first_str(entry.get("name"), entry.get("label"))
                if name:
                    out.append(name)
    for key in ("category", "subcategory", "format", "categorySlug"):
        val = _first_str(item.get(key))
        if val:
            out.append(val)
    return out


def _jsonld_location(item: dict[str, Any]) -> dict[str, str]:
    """Parse schema.org Place from top-level location."""
    location = _nested_dict(item, "location")
    if not location:
        return {"city": "", "country": "", "venue_name": "", "full_address": ""}

    ld_address = _nested_dict(location, "address")
    city = _first_str(ld_address.get("addressLocality"))
    country = _first_str(ld_address.get("addressCountry"))
    venue_name = _first_str(location.get("name"))
    full_address = _first_str(
        ld_address.get("streetAddress"),
        ld_address.get("addressLocality"),
    )
    if city and full_address and city.lower() not in full_address.lower():
        full_address = f"{full_address}, {city}"
    return {
        "city": city,
        "country": country,
        "venue_name": venue_name,
        "full_address": full_address,
    }


def _venue_fields(item: dict[str, Any]) -> dict[str, str]:
    jsonld = _jsonld_location(item)
    venue = _nested_dict(item, "venue")
    address = _nested_dict(venue, "address")
    if not address and isinstance(venue.get("address"), str):
        address = {"localized_address_display": venue.get("address")}

    city = _first_str(
        jsonld.get("city"),
        item.get("city"),
        item.get("venueCity"),
        venue.get("city"),
        address.get("city"),
        address.get("localized_area_display"),
    )
    country = _first_str(
        jsonld.get("country"),
        item.get("country"),
        item.get("venueCountry"),
        venue.get("country"),
        address.get("country"),
        address.get("country_code"),
    )
    venue_name = _first_str(
        jsonld.get("venue_name"),
        item.get("venue_name"),
        item.get("venueName"),
        venue.get("name"),
    )
    full_address = _first_str(
        jsonld.get("full_address"),
        item.get("venue_address"),
        item.get("venueAddress"),
        item.get("address"),
        venue.get("address"),
        address.get("localized_address_display"),
        address.get("address_1"),
    )
    if city and full_address and city.lower() not in full_address.lower():
        full_address = f"{full_address}, {city}"
    return {
        "city": city,
        "country": country,
        "venue_name": venue_name,
        "full_address": full_address,
    }


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"true", "1", "yes"}:
            return True
        if low in {"false", "0", "no"}:
            return False
    return None


def _numeric_price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
        return num
    except (TypeError, ValueError):
        return None


def _infer_free_from_offers(item: dict[str, Any]) -> tuple[bool | None, str, str]:
    """Parse schema.org AggregateOffer list from JSON-LD exports."""
    offers = item.get("offers")
    if not isinstance(offers, list) or not offers:
        return None, "", ""

    low_prices: list[float] = []
    high_prices: list[float] = []
    currency = ""
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        currency = currency or _first_str(offer.get("priceCurrency"))
        lp = _numeric_price(offer.get("lowPrice"))
        hp = _numeric_price(offer.get("highPrice"))
        if lp is not None:
            low_prices.append(lp)
        if hp is not None:
            high_prices.append(hp)

    if not low_prices and not high_prices:
        return None, "", ""

    min_price = min(low_prices) if low_prices else min(high_prices)
    max_price = max(high_prices) if high_prices else max(low_prices)
    cur = currency or "SGD"
    if max_price == 0 and min_price == 0:
        return True, "free", f"offers lowPrice/highPrice=0 ({cur})"
    if max_price > 0:
        text = f"{cur} {max_price}".strip()
        if min_price != max_price and min_price > 0:
            text = f"{cur} {min_price}-{max_price}"
        return False, text, f"offers highPrice={max_price}"
    return None, "", "offers present but price ambiguous"


def infer_eventbrite_free(item: dict[str, Any]) -> tuple[bool | None, str, str]:
    """Conservative free inference from explicit flags and price fields."""
    for key in ("is_free", "isFree"):
        flag = _parse_bool(item.get(key))
        if flag is True:
            return True, "free", f"{key}=true"
        if flag is False:
            pass  # may still have free tiers; check prices below

    offer_free, offer_price, offer_ev = _infer_free_from_offers(item)
    if offer_free is True:
        return True, offer_price or "free", offer_ev
    if offer_free is False:
        return False, offer_price, offer_ev

    price_text = _first_str(
        item.get("price"),
        item.get("priceDisplay"),
        item.get("priceRange"),
        item.get("price_display"),
    ).lower()
    if price_text in {"free", "$0", "sgd 0", "0"}:
        return True, "free", f"price text={price_text}"
    if "free" in price_text and "free trial" not in price_text:
        if not any(x in price_text for x in ("$", "sgd", "usd")) or "0" in price_text:
            return True, "free", f"price text mentions free: {price_text[:40]}"

    for key in ("priceMin", "priceMax", "lowest_price", "highest_price"):
        num = _numeric_price(item.get(key))
        if num is not None and num > 0:
            cur = _first_str(item.get("currency"), "SGD")
            return False, f"{cur} {num}".strip(), f"{key}={num}"

    tiers = item.get("ticket_tiers") or item.get("ticketTiers") or []
    if isinstance(tiers, list) and tiers:
        prices: list[float] = []
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            p = _numeric_price(tier.get("price"))
            if p is None:
                cost = tier.get("cost")
                if isinstance(cost, dict):
                    p = _numeric_price(cost.get("major_value") or cost.get("value"))
            if p is not None:
                prices.append(p)
        if prices and all(p == 0 for p in prices):
            return True, "free", "all ticket_tiers price=0"
        if prices and any(p > 0 for p in prices):
            return False, f"from {min(prices)}", "ticket_tiers include paid price"

    flag_false = _parse_bool(item.get("is_free")) is False or _parse_bool(item.get("isFree")) is False
    if flag_false and any(x in price_text for x in ("$", "sgd", "usd", "paid")):
        return False, price_text or "paid", "is_free=false with paid price text"
    if flag_false and price_text and "free" not in price_text:
        return False, price_text, "is_free=false"

    if _parse_bool(item.get("is_free")) is True or _parse_bool(item.get("isFree")) is True:
        return True, "free", "is_free/isFree=true"

    return None, price_text, "free status unknown"


def _attendance_mode_in_person(item: dict[str, Any]) -> tuple[bool | None, str]:
    mode = _first_str(item.get("eventAttendanceMode"))
    if not mode:
        return None, ""
    if "OfflineEventAttendanceMode" in mode:
        return True, "eventAttendanceMode=OfflineEventAttendanceMode"
    if "OnlineEventAttendanceMode" in mode:
        return False, "eventAttendanceMode=OnlineEventAttendanceMode"
    if "MixedEventAttendanceMode" in mode:
        return False, "eventAttendanceMode=MixedEventAttendanceMode (hybrid)"
    return None, f"unknown eventAttendanceMode={mode}"


ONLINE_TITLE_PHRASES = (
    "free online",
    "online event",
)

ONLINE_TITLE_TERMS = (
    "virtual",
    "webinar",
    "zoom",
)


def _eventbrite_online_only_text(item: dict[str, Any]) -> str:
    """Conservative online-only signal from Eventbrite title/description only."""
    text = f" {_first_str(item.get('name'), item.get('title'), item.get('eventName'))} {_first_str(item.get('description'), item.get('summary'))} ".lower()
    for phrase in ONLINE_TITLE_PHRASES:
        if phrase in text:
            return phrase
    for term in ONLINE_TITLE_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", text):
            return term
    return ""


def infer_eventbrite_in_person(item: dict[str, Any]) -> tuple[bool, str]:
    """In-person only policy — reject online/hybrid/virtual."""
    online_text = _eventbrite_online_only_text(item)
    if online_text:
        return False, f"title/description indicates online ({online_text})"

    mode_ok, mode_ev = _attendance_mode_in_person(item)
    if mode_ok is False:
        return False, mode_ev
    if mode_ok is True:
        return True, mode_ev

    for key in ("is_online", "isOnline", "is_online_event", "online_event"):
        flag = _parse_bool(item.get(key))
        if flag is True:
            return False, f"{key}=true"
        if flag is False:
            break

    fmt = _first_str(item.get("format")).lower()
    if "online" in fmt and "in person" not in fmt:
        return False, f"format={item.get('format')}"

    loc = _first_str(item.get("location")).lower()
    if loc == "online":
        return False, "location=online"

    venue = _venue_fields(item)
    if venue["venue_name"] or venue["full_address"]:
        online = any(
            _parse_bool(item.get(k)) is True
            for k in ("is_online", "isOnline", "is_online_event", "online_event")
        )
        if online:
            return False, "online flag with venue present (hybrid/online)"
        return True, "venue present and not online"

    return False, "missing venue / likely online-only"


def _combine_start_end(item: dict[str, Any]) -> tuple[str, str]:
    """Return (start_iso, end_iso) best-effort in SGT-compatible RFC3339."""
    start = _first_str(
        item.get("start_at"),
        item.get("startDate"),
        item.get("startDateTime"),
        item.get("start_date_time"),
    )
    end = _first_str(
        item.get("end_at"),
        item.get("endDate"),
        item.get("endDateTime"),
        item.get("end_date_time"),
    )

    start_date = _first_str(item.get("start_date"), item.get("startDate"))
    start_time = _first_str(item.get("start_time"), item.get("startTime"))
    end_date = _first_str(item.get("end_date"), item.get("endDate"))
    end_time = _first_str(item.get("end_time"), item.get("endTime"))

    tz_name = _first_str(item.get("timezone"), "Asia/Singapore")

    def _compose(date_part: str, time_part: str) -> str:
        if not date_part:
            return ""
        if "T" in date_part:
            return date_part
        if time_part:
            return f"{date_part}T{time_part}"
        return f"{date_part}T00:00:00"

    if not start:
        start = _compose(start_date, start_time)
    if not end:
        end = _compose(end_date, end_time)

    def _normalize_iso(text: str) -> str:
        if not text:
            return ""
        t = text.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            return t
        if dt.tzinfo is None:
            try:
                dt = dt.replace(tzinfo=ZoneInfo(tz_name))
            except Exception:
                dt = dt.replace(tzinfo=SGT)
        return dt.astimezone(SGT).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")

    start_iso = _normalize_iso(start)
    end_iso = _normalize_iso(end)
    if start_iso and not end_iso:
        try:
            dt = datetime.fromisoformat(start_iso)
            end_iso = (dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0800", "+08:00")
        except ValueError:
            pass
    return start_iso, end_iso


def normalize_canonical(item: dict[str, Any], *, source_query: str = "") -> dict[str, Any]:
    venue = _venue_fields(item)
    is_free, price_text, free_evidence = infer_eventbrite_free(item)
    is_in_person, in_person_evidence = infer_eventbrite_in_person(item)
    start_time, end_time = _combine_start_end(item)
    organizer = _first_str(
        item.get("organizer_name"),
        item.get("organizerName"),
        item.get("organizer"),
    )
    if isinstance(item.get("organizer"), dict):
        organizer = _first_str(item["organizer"].get("name")) or organizer

    matched = (source_query or DEFAULT_SOURCE_QUERY).strip().lower()
    url = _first_str(item.get("url"), item.get("eventUrl"), item.get("event_url"))
    event_id = _first_str(item.get("eventId"), item.get("event_id"), item.get("id"))

    event = empty_event("eventbrite", source_query=matched, matched_keyword=matched)
    event.update(
        {
            "title": _first_str(item.get("name"), item.get("title"), item.get("eventName")),
            "description": _first_str(item.get("description"), item.get("summary"))[:800],
            "start_time": start_time,
            "end_time": end_time,
            "timezone": _first_str(item.get("timezone"), "Asia/Singapore"),
            "venue_name": venue["venue_name"],
            "full_address": venue["full_address"],
            "city": venue["city"],
            "country": venue["country"],
            "is_in_person": is_in_person,
            "in_person_evidence": in_person_evidence,
            "is_free": is_free,
            "price_text": price_text,
            "free_evidence": free_evidence,
            "organizer_name": organizer,
            "group_name": organizer,
            "url": url,
            "source_event_id": event_id,
            "rsvp_count": None,
            "attendee_count": None,
            "approval_required": None,
            "waitlist_status": _first_str(item.get("status"), item.get("ticketAvailability")),
            "raw_tags": _tags(item),
            "discovery_channel": "apify",
            "discovery_task": DEFAULT_TASK_NAME,
            "matched_keywords": [matched] if matched else [],
            # backward compat
            "platform": "eventbrite",
            "source_url": url,
            "start_at": start_time,
            "end_at": end_time,
            "location": venue["full_address"] or venue["venue_name"],
            "organizer": organizer,
            "summary": _first_str(item.get("summary"), item.get("description"))[:500],
        }
    )
    return event


def load_eventbrite_exports(paths: list[tuple[str, str]]) -> list[dict[str, Any]]:
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
