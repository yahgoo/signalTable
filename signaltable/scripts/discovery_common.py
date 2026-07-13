"""Shared event-discovery pipeline: schema, hard filters, scoring, dedupe."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")

SEARCH_KEYWORDS = ("data", "algorithm", "compute")

TECH_KEYWORDS = (
    "data",
    "algorithm",
    "compute",
    " ai ",
    "ai/",
    "ai-",
    "ai,",
    "artificial intelligence",
    "machine learning",
    "ml",
    "llm",
    "genai",
    "mlops",
    "developer",
    "engineering",
    "prompt",
    " agent",
    "agents",
    " model",
    "analytics",
    "python",
    "cybersecurity",
    "computer security",
)

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
    "compute",
)

LOW_SIGNAL_TERMS = (
    "fitness",
    "yoga",
    "run club",
    "mindful run",
    "wellness",
    "food festival",
    "networking only",
    "speed dating",
    "franchise",
    "crypto meetup",
    "hiking",
    "sunrise hike",
    "durian",
    "singles",
    "speed dating",
    "bjj",
    "brazilian jiu",
    "walk + dinner",
    "walk dinner",
    "live music",
    "walking method",
    "travel meet",
    "talking to strangers",
)

OFFTOPIC_GROUP_MARKERS = (
    "hiking",
    "travelling",
    "travel",
    "tour",
    "singles",
    "dating",
    "sports class",
    "run to eat",
    "walk",
    "wellness",
    "friendship",
    "bjj",
    "durian",
    "warm spaces",
    "shut up and write",
)

VAGUE_NETWORKING = (
    "general networking",
    "casual networking",
    "meet new people",
    "social mixer",
)

KNOWN_ORGANIZERS = (
    "google",
    "meta",
    "aws",
    "amazon web services",
    "nus",
    "ntu",
    "stripe",
    "microsoft",
    "openai",
    "singadev",
    "division zero",
    "div0",
)

WORKSHOP_TERMS = ("workshop", "hands-on", "hackathon", "buildathon", "lab", "bootcamp")

NEGATIVE_LOCATIONS = (
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
    "united kingdom",
    "hong kong",
    "malaysia",
    "indonesia",
)


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


def empty_event(source: str, *, source_query: str = "", matched_keyword: str = "") -> dict[str, Any]:
    return {
        "source": source,
        "source_query": source_query,
        "matched_keyword": matched_keyword,
        "matched_keywords": [matched_keyword] if matched_keyword else [],
        "sources": [source] if source else [],
        "title": "",
        "description": "",
        "start_time": "",
        "end_time": "",
        "timezone": "Asia/Singapore",
        "venue_name": "",
        "full_address": "",
        "city": "",
        "country": "",
        "is_in_person": None,
        "is_free": None,
        "price_text": "",
        "free_evidence": "",
        "organizer_name": "",
        "group_name": "",
        "url": "",
        "source_event_id": "",
        "rsvp_count": None,
        "attendee_count": None,
        "approval_required": None,
        "waitlist_status": "",
        "raw_tags": [],
        "event_page_url": "",
        "registration_url": "",
        "registration_platform": "",
        "registration_gateway_evidence": "",
        "discovery_channel": "apify",
        "relevance_score": 0,
        "tier": 3,
        "rejection_reasons": [],
        "why_selected": [],
        "why_rejected": [],
        "singapore_evidence": "",
        "in_person_evidence": "",
        "food_status": "not_mentioned",
        "food_card_line": "Food: Not mentioned",
        "food_evidence": "",
        "meetup_venue_name": "",
        "meetup_venue_address": "",
        "registration_venue_name": "",
        "registration_venue_address": "",
        "registration_venue_source": "",
        # backward compat
        "platform": source,
        "source_url": "",
        "start_at": "",
        "end_at": "",
        "location": "",
        "summary": "",
    }


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _text_blob(event: dict[str, Any]) -> str:
    parts = [
        event.get("title", ""),
        event.get("description", ""),
        event.get("organizer_name", ""),
        event.get("group_name", ""),
        " ".join(event.get("raw_tags") or []),
        event.get("venue_name", ""),
        event.get("full_address", ""),
        event.get("city", ""),
        event.get("country", ""),
    ]
    return f" {' '.join(str(p) for p in parts)} ".lower()


def _keyword_hit(text: str, keyword: str) -> bool:
    kw = keyword.lower().strip()
    if kw.startswith(" ") or kw.endswith(" "):
        return kw in text
    return re.search(rf"\b{re.escape(kw)}\b", text) is not None


def keyword_matches(event: dict[str, Any]) -> list[str]:
    text = _text_blob(event)
    hits = [kw for kw in TECH_KEYWORDS if _keyword_hit(text, kw)]
    for kw in event.get("matched_keywords") or []:
        if kw and kw not in hits:
            hits.append(kw)
    return hits


def is_singapore_event(event: dict[str, Any]) -> tuple[bool, str]:
    city = str(event.get("city", "")).lower()
    country = str(event.get("country", "")).lower()
    address = str(event.get("full_address", "")).lower()
    venue = str(event.get("venue_name", "")).lower()

    if country in {"sg", "singapore"} or "singapore" in country:
        return True, f"country={event.get('country') or 'singapore'}"
    if "singapore" in city:
        return True, f"city={event.get('city')}"
    if "singapore" in address or "singapore" in venue:
        return True, "address/venue contains Singapore"
    url = str(event.get("url") or event.get("source_url") or "").lower()
    if event.get("source") == "eventbrite" and "eventbrite.sg" in url:
        return True, "eventbrite.sg URL"
    if event.get("source") == "luma":
        featured = str(event.get("featured_city", "")).lower()
        if featured in {"singapore", "sg"} or "singapore" in featured:
            return True, f"featured_city={event.get('featured_city')}"

    blob = f"{city} {country} {address} {venue}"
    if any(marker in blob for marker in NEGATIVE_LOCATIONS):
        return False, f"non-SG location marker in {blob[:80]}"
    return False, "no Singapore signal"


def is_in_person_event(event: dict[str, Any]) -> tuple[bool, str]:
    if event.get("is_in_person") is True:
        return True, event.get("in_person_evidence") or "is_in_person=true"
    if event.get("is_in_person") is False:
        return False, event.get("in_person_evidence") or "is_in_person=false"

    text = _text_blob(event)
    if any(x in text for x in ("online only", "virtual only", "zoom only", "livestream only")):
        return False, "text indicates online-only"
    return False, "missing in-person evidence"


def is_upcoming_event(event: dict[str, Any], *, now: datetime | None = None) -> bool:
    start = parse_datetime(str(event.get("start_time") or event.get("start_at") or ""))
    if start is None:
        return False
    current = now or datetime.now(SGT)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SGT)
    return start.astimezone(SGT) >= current.astimezone(SGT)


def _norm_match_text(value: str) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_offtopic_event(event: dict[str, Any]) -> tuple[bool, str]:
    """Reject obvious non-tech social/sports/travel events unless title is strongly technical."""
    title = _norm_match_text(event.get("title", ""))
    group = _norm_match_text(event.get("group_name", ""))
    text = _text_blob(event)
    hits = keyword_matches(event)
    strong_title = any(_keyword_hit(title, kw) for kw in STRONG_KEYWORDS)

    if strong_title and hits:
        return False, ""

    if any(marker in group for marker in OFFTOPIC_GROUP_MARKERS):
        return True, f"off-topic group: {event.get('group_name')}"
    if any(term in title for term in LOW_SIGNAL_TERMS):
        if not strong_title:
            return True, f"off-topic title: {event.get('title')}"
    if any(term in text for term in ("hike", "durian buffet", "speed dating", "singles social")) and not hits:
        return True, "social/travel event without tech keywords"
    return False, ""


def is_tech_relevant(event: dict[str, Any]) -> tuple[bool, str]:
    tags = [str(t).lower() for t in (event.get("raw_tags") or [])]
    if any(t in {"ai", "tech"} for t in tags):
        return True, "category AI/Tech"
    for t in tags:
        norm = t.replace("&", "and")
        if ("science" in norm and "tech" in norm) or norm in {
            "science and tech",
            "science-and-tech",
            "science & tech",
        }:
            return True, "Science & Tech category"
    hits = keyword_matches(event)
    if hits:
        return True, f"keywords: {', '.join(hits[:4])}"
    text = _text_blob(event)
    if any(term in text for term in LOW_SIGNAL_TERMS) and not hits:
        return False, "low-signal category without tech keywords"
    return False, "no tech/data/compute keyword match"


def is_free_enough(event: dict[str, Any]) -> tuple[bool, str]:
    """Hard reject only when clearly paid; uncertain cases handled in scoring."""
    is_free = event.get("is_free")
    evidence = str(event.get("free_evidence") or "")
    price_text = str(event.get("price_text") or "").lower()

    if is_free is True:
        return True, evidence or "marked free"
    if is_free is False:
        return False, evidence or price_text or "marked paid"
    if any(x in price_text for x in ("sgd", "usd", "$", "paid", "ticket price")):
        return False, f"price_text suggests paid: {price_text[:60]}"
    # uncertain — allow through hard filter; scoring will down-rank
    return True, "free status uncertain (not clearly paid)"


def hard_filter(event: dict[str, Any], *, now: datetime | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not is_upcoming_event(event, now=now):
        reasons.append("not upcoming")
    sg_ok, sg_ev = is_singapore_event(event)
    if not sg_ok:
        reasons.append(f"not Singapore ({sg_ev})")
    else:
        event["singapore_evidence"] = sg_ev

    ip_ok, ip_ev = is_in_person_event(event)
    if not ip_ok:
        reasons.append(f"not in-person ({ip_ev})")
    else:
        event["in_person_evidence"] = ip_ev

    free_ok, free_ev = is_free_enough(event)
    if not free_ok:
        reasons.append(f"paid ({free_ev})")
    else:
        event["free_evidence"] = free_ev

    rel_ok, rel_ev = is_tech_relevant(event)
    if not rel_ok:
        reasons.append(f"not tech relevant ({rel_ev})")

    off_ok, off_ev = is_offtopic_event(event)
    if off_ok:
        reasons.append(f"off-topic ({off_ev})")

    event["rejection_reasons"] = reasons
    event["why_rejected"] = reasons
    return len(reasons) == 0, reasons


def score_event(event: dict[str, Any]) -> tuple[int, list[str]]:
    text = _text_blob(event)
    why: list[str] = []
    score = 0

    hits = keyword_matches(event)
    if hits:
        score += 3
        why.append(f"keyword match: {', '.join(hits[:5])}")
    title = str(event.get("title", "")).lower()
    for kw in STRONG_KEYWORDS:
        if _keyword_hit(title, kw):
            score += 1
            why.append(f"title aligns with {kw}")
            break

    if event.get("singapore_evidence"):
        score += 2
        why.append("Singapore")
    if event.get("is_in_person") is True:
        score += 1
        why.append("in-person")

    if event.get("is_free") is True:
        score += 2
        why.append("free")
    elif event.get("is_free") is None:
        score -= 1
        why.append("free status uncertain (down-ranked)")

    org = f"{event.get('organizer_name','')} {event.get('group_name','')}".lower()
    if any(name in org for name in KNOWN_ORGANIZERS):
        score += 1
        why.append("trusted organizer/group")

    if any(term in text for term in WORKSHOP_TERMS):
        score += 1
        why.append("hands-on format")

    from food_detection import apply_food_status, food_score_delta

    if not event.get("food_status"):
        apply_food_status(event)
    food_delta, food_reason = food_score_delta(str(event.get("food_status") or ""))
    if food_delta:
        score += food_delta
        why.append(food_reason)

    if any(term in text for term in VAGUE_NETWORKING) and len(hits) < 2:
        score -= 2
        why.append("vague networking (down-ranked)")

    if not event.get("start_time") or not event.get("venue_name"):
        score -= 1
        why.append("missing time or venue clarity")

    if event.get("is_free") is False:
        score -= 5

    if any(term in text for term in LOW_SIGNAL_TERMS):
        score -= 3

    score = max(0, min(10, score))
    event["relevance_score"] = score
    event["why_selected"] = why
    return score, why


def classify_tier(event: dict[str, Any], score: int) -> int:
    if event.get("is_free") is False:
        return 3
    if event.get("approval_required") is True:
        if event.get("is_free") is True and score >= 6:
            return 2
        return 3
    if event.get("is_free") is True and score >= 6:
        return 1
    if 4 <= score <= 5:
        return 2
    if score >= 6:
        return 2
    return 3


def _norm_url(url: str) -> str:
    return str(url or "").strip().lower().rstrip("/").replace("luma.com", "lu.ma")


def dedupe_key(event: dict[str, Any]) -> str:
    url = _norm_url(event.get("url") or event.get("source_url") or "")
    if url:
        return f"url:{url}"
    title = re.sub(r"\s+", " ", str(event.get("title", "")).strip().lower())
    start = str(event.get("start_time") or event.get("start_at") or "")[:16]
    venue = re.sub(r"\s+", " ", str(event.get("venue_name", "")).strip().lower())
    return f"fallback:{title}|{start}|{venue}"


def merge_events(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key in ("matched_keywords", "sources"):
        vals = list(merged.get(key) or [])
        for v in incoming.get(key) or []:
            if v and v not in vals:
                vals.append(v)
        merged[key] = vals

    for field in ("source_query", "matched_keyword"):
        if not merged.get(field) and incoming.get(field):
            merged[field] = incoming[field]

    for field in ("description", "free_evidence", "singapore_evidence", "in_person_evidence", "food_evidence"):
        if len(str(incoming.get(field) or "")) > len(str(merged.get(field) or "")):
            merged[field] = incoming[field]

    for field in ("food_status", "food_card_line"):
        if merged.get("food_status") in (None, "", "not_mentioned") and incoming.get("food_status"):
            merged[field] = incoming[field]
        elif incoming.get("food_status") == "provided":
            merged[field] = incoming[field]

    # Meetup venue: never let a merge replace a populated primary Meetup venue.
    for field in ("meetup_venue_name", "meetup_venue_address", "venue_name", "full_address", "city", "country"):
        if not _first_str(merged.get(field)) and _first_str(incoming.get(field)):
            merged[field] = incoming[field]
    for field in ("registration_venue_name", "registration_venue_address", "registration_venue_source"):
        if not _first_str(merged.get(field)) and _first_str(incoming.get(field)):
            merged[field] = incoming[field]

    if int(incoming.get("relevance_score") or 0) > int(merged.get("relevance_score") or 0):
        merged["relevance_score"] = incoming["relevance_score"]
        merged["why_selected"] = incoming.get("why_selected") or merged.get("why_selected")

    return merged


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        key = dedupe_key(event)
        if key in by_key:
            by_key[key] = merge_events(by_key[key], event)
        else:
            by_key[key] = event
            order.append(key)
    return [by_key[k] for k in order]


def filter_pipeline(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from food_detection import apply_food_status

    counts = {"raw": len(events)}
    passed: list[dict[str, Any]] = []

    for event in events:
        ok, _ = hard_filter(event, now=now)
        if not ok:
            continue
        passed.append(apply_food_status(event))

    counts["hard_filter_pass"] = len(passed)

    deduped = dedupe_events(passed)
    counts["deduped"] = len(deduped)
    return deduped, counts


def dominant_filter_drop(counts: dict[str, int]) -> str:
    raw = counts.get("raw", 0)
    passed = counts.get("hard_filter_pass", 0)
    if raw == 0:
        return "blocker: no input rows"
    if passed == 0:
        return "blocker: hard filters removed all rows (Singapore/in-person/free/tech/upcoming)"
    deduped = counts.get("deduped", 0)
    if deduped == 0:
        return "blocker: dedupe removed all rows"
    return f"blocker: min_score removed all {deduped} deduped row(s)"


def score_and_tier(events: list[dict[str, Any]], *, min_score: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        score, _ = score_event(event)
        if score < min_score:
            continue
        tier = classify_tier(event, score)
        event["tier"] = tier
        rows.append(event)
    rows.sort(key=lambda e: (-int(e.get("relevance_score") or 0), e.get("source", ""), e.get("title", "")))
    return rows
