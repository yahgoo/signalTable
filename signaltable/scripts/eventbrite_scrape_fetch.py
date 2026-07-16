#!/usr/bin/env python3
"""Self-hosted Eventbrite discovery via public Schema.org JSON-LD scraping.

Replaces the Apify Eventbrite actor (expires 2026-07-20). HTTP-only, no
auth, no browser. Mirrors the Meetup/Luma replacements: the Apify actor it
self-hosts was a CheerioCrawler (plain HTTP/HTML), so a stdlib urllib rebuild
is a faithful, dependency-free substitute.

Investigation findings (2026-07-16, live):
  - Listing pages (eventbrite.sg/d/singapore--singapore/<category>/) embed a
    CollectionPage/ItemList JSON-LD with `itemListElement[].item` Event
    nodes. EVERY tested category/slug returned 200 + real items TODAY
    (free--events, data--events, computing--events, artificial-intelligence--events,
    science-and-tech--events, business-opportunities, ?q=<kw> search).
  - The 2026-07-07 actor log's "free--science-and-tech--events returned 0
    items" was STALE/TRANSIENT (category taxonomy or a transient hiccup on that
    date), NOT a structural listing-parse failure. Confirmed reproducible today.
  - Listing JSON-LD has NO `offers` (pricing absent) -> a per-event page
    fetch is REQUIRED to resolve is_free (same as the Apify actor's behavior).
  - Per-event pages (eventbrite.sg/e/<slug>-tickets-<id> OR .com/e/...) embed
    a schema.org `Event` JSON-LD node carrying the FULL contract:
      name, startDate(+08:00 SGT), endDate, eventAttendanceMode
      (OfflineEventAttendanceMode => in-person), description,
      location.{name, address.{streetAddress,addressLocality,addressCountry}},
      organizer.name, image, AND offers[] (AggregateOffer: lowPrice/highPrice/
      priceCurrency).
  - AUTHORITATIVE PRICING SIGNAL = offers[].AggregateOffer lowPrice/highPrice
    (strings, e.g. "0.0" or "58.73"; priceCurrency e.g. "SGD"/"GBP").
    Verified with a real PAID trap event (BNI Mastermind: low=high=58.73 SGD,
    isFree=false) and real FREE trap events (AIoTConf/APExpo: 0.0, isFree=true)
    -- event NAME does NOT predict price, so the offers blob is the only trusted
    signal (same trap discipline as Luma's misleading ticket-type names).
  - `.sg` vs `.com` duplication: the same event is reachable via both domains.
    Dedup is by EVENT ID parsed from the `-tickets-<id>` slug, NOT the URL string.

How it maps to the downstream contract:
  - Emits Apify-shaped dicts so `eventbrite_normalize.normalize_canonical()`
    needs ZERO changes (same "zero-change" principle as the Meetup/Luma
    replacements).
  - Missing fields are backfilled HERE (the shim), never in eventbrite_normalize.py.
  - Schema-drift guard (`eventbrite_pricing_schema_drift`) is built in from day
    one: if the offers structure changes/missing/renamed, it emits a loud warning
    and falls back to is_free=None (unknown) rather than guessing.

Usage:
  python3 eventbrite_scrape_fetch.py --categories science-and-tech,data,computing
  python3 eventbrite_scrape_fetch.py --keyword data          # search-URL mode
  python3 eventbrite_scrape_fetch.py --output json             # emit JSON to stdout
  python3 eventbrite_scrape_fetch.py --self-test             # free/paid/trap/drift
  python3 eventbrite_scrape_fetch.py --dry-run              # self-test + score-parity
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Tech-relevant Eventbrite category slugs (singapore) mapped to our discovery keywords.
# Mirrors the Meetup/Luma "data, algorithm, compute" intent.
DEFAULT_CATEGORIES = [
    ("science-and-tech", "science-tech"),
    ("data", "data"),
    ("computing", "compute"),
    ("technology", "algorithm"),
    ("artificial-intelligence", "ai"),
]
CITY_SLUG = "singapore--singapore"
LISTING_URL = "https://www.eventbrite.sg/d/{city}/{category}--events/"
SEARCH_URL = "https://www.eventbrite.sg/d/{city}/?q={kw}"

# Politeness (matches Meetup/Luma pattern; serialized, no threads).
MIN_DELAY_S = 0.3
MAX_DELAY_S = 0.7
MAX_CONCURRENCY = 1  # serialized via simple sleep loop (keep it simple/safe)


# --------------------------------------------------------------------------- #
# Schema-drift warning sink (built in from day one)
# --------------------------------------------------------------------------- #
_SCHEMA_WARNINGS: list[dict[str, str]] = []


def reset_schema_warnings() -> None:
    _SCHEMA_WARNINGS.clear()


def get_schema_warnings() -> list[dict[str, str]]:
    return list(_SCHEMA_WARNINGS)


def _warn_schema(code: str, detail: str, event_url: str = "") -> None:
    """Emit a loud schema-drift warning. Caller decides fallback behavior."""
    _SCHEMA_WARNINGS.append(
        {"code": code, "detail": detail, "event_url": event_url}
    )
    print(f"[schema-drift] {code}: {detail} ({event_url})", file=sys.stderr)


# --------------------------------------------------------------------------- #
# HTTP helpers (stdlib only)
# --------------------------------------------------------------------------- #
def _http_get(url: str, *, timeout: int = 25) -> tuple[int, str]:
    """Return (status, body). Uses urllib; never raises fatally to the loop."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001 - keep scraping resilient
        return -1, f"ERROR:{type(exc).__name__}:{exc}"


# --------------------------------------------------------------------------- #
# JSON-LD extraction
# --------------------------------------------------------------------------- #
def _extract_jsonld(html: str) -> list[dict[str, Any]]:
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    docs: list[dict[str, Any]] = []
    for raw in blocks:
        try:
            docs.append(json.loads(raw.strip()))
        except json.JSONDecodeError:
            continue
    return docs


def _collect_listing_items(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unwrap CollectionPage/ItemList -> list of `item` Event nodes from listings."""
    items: list[dict[str, Any]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "itemListElement" in o and isinstance(o["itemListElement"], list):
                for n in o["itemListElement"]:
                    if isinstance(n, dict) and isinstance(n.get("item"), dict):
                        items.append(n["item"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for d in docs:
        walk(d)
    return items


def _collect_event_nodes(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find schema.org Event/SocialEvent nodes in a per-event page.

    Eventbrite is inconsistent about WHERE pricing lives:
      - sometimes `offers` is INSIDE the Event node (BNI-style pages),
      - sometimes `offers`/`isFree` sit at the JSON-LD DOCUMENT ROOT
        (sibling of the Event node), or anywhere else in the blob.
    A per-event page has exactly ONE event, so we gather the document-wide
    `offers`/`isFree` (first found, anywhere) and inject into every Event
    node, then return nodes richest-first so callers pick the real one.
    """
    events: list[dict[str, Any]] = []
    doc_offers: Any = None
    doc_is_free: Any = None

    def walk(o: Any) -> None:
        nonlocal doc_offers, doc_is_free
        if isinstance(o, dict):
            if "offers" in o and doc_offers is None:
                doc_offers = o["offers"]
            if "isFree" in o and doc_is_free is None:
                doc_is_free = o["isFree"]
            # Eventbrite uses varied schema.org Event subtypes:
            # "Event", "SocialEvent", "EducationEvent", "BusinessEvent", ...
            # Match any *Event (subclass of schema.org Event).
            t = o.get("@type")
            if isinstance(t, str) and t.endswith("Event"):
                events.append(o)
            elif isinstance(t, list) and any(
                isinstance(x, str) and x.endswith("Event") for x in t
            ):
                events.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for d in docs:
        walk(d)

    if doc_offers is not None or doc_is_free is not None:
        for ev in events:
            if doc_offers is not None and "offers" not in ev:
                ev["offers"] = doc_offers
            if doc_is_free is not None and "isFree" not in ev:
                ev["isFree"] = doc_is_free

    def _rich(ev: dict[str, Any]) -> int:
        return sum(1 for k in ("name", "startDate", "location", "offers") if ev.get(k))

    return sorted(events, key=_rich, reverse=True)


# --------------------------------------------------------------------------- #
# Field shims (eventbrite_normalize.py contract)
# --------------------------------------------------------------------------- #
def _event_id_from_url(url: str) -> str:
    """Eventbrite dedup key: numeric id from the `-tickets-<id>` slug.

    Same event is reachable via .sg and .com -> must NOT dedup on full URL.
    """
    m = re.search(r"-tickets-(\d+)", url or "")
    return m.group(1) if m else ""


def _first_str(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _numeric_price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_is_free(ev: dict[str, Any], *, event_url: str = "") -> tuple[bool | None, str, str]:
    """Authoritative pricing from offers[].AggregateOffer lowPrice/highPrice.

    Returns (is_free, price_text, evidence). is_free=None means genuinely no
    signal -> downstream down-ranks (never silently paid/free).
    """
    offers = ev.get("offers")
    if not isinstance(offers, list) or not offers:
        _warn_schema(
            "eventbrite_pricing_schema_drift",
            "no offers[] on event node (cannot resolve price)",
            event_url,
        )
        return None, "", "no offers[] present"

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
        _warn_schema(
            "eventbrite_pricing_schema_drift",
            "offers[] present but no lowPrice/highPrice (renamed/restructured?)",
            event_url,
        )
        return None, "", "offers present but price ambiguous"

    min_price = min(low_prices) if low_prices else min(high_prices)
    max_price = max(high_prices) if high_prices else max(low_prices)
    cur = currency or "SGD"
    if max_price == 0 and min_price == 0:
        return True, "free", f"offers lowPrice/highPrice=0 ({cur})"
    if max_price > 0:
        text = f"{cur} {max_price}".strip()
        if min_price != max_price and min_price > 0:
            text = f"{cur} {min_price}-{max_price}"
        return False, text, f"offers highPrice={max_price} ({cur})"
    return None, "", "offers price ambiguous"


def _venue_from_event(ev: dict[str, Any]) -> dict[str, str]:
    loc = ev.get("location") or {}
    addr = loc.get("address") if isinstance(loc, dict) else None
    if not isinstance(addr, dict):
        addr = {}
    city = _first_str(addr.get("addressLocality"))
    country = _first_str(addr.get("addressCountry"))
    venue_name = _first_str(loc.get("name")) if isinstance(loc, dict) else ""
    street = _first_str(addr.get("streetAddress"))
    full = street
    if city and full and city.lower() not in full.lower():
        full = f"{full}, {city}"
    return {
        "city": city,
        "country": country,
        "venue_name": venue_name,
        "full_address": full,
    }


def shim_event(
    ev: dict[str, Any],
    *,
    source_query: str,
    event_url: str,
) -> dict[str, Any]:
    """Build an Apify-shaped dict for eventbrite_normalize.normalize_canonical().

    `ev` is the per-event JSON-LD Event node (authoritative: has offers).
    """
    venue = _venue_from_event(ev)
    is_free, price_text, evidence = resolve_is_free(ev, event_url=event_url)
    organizer = ev.get("organizer") or {}
    org_name = (
        organizer.get("name")
        if isinstance(organizer, dict)
        else _first_str(organizer)
    )
    event_id = _event_id_from_url(event_url) or _first_str(
        ev.get("eventId"), ev.get("event_id"), ev.get("identifier")
    )
    mode = _first_str(ev.get("eventAttendanceMode"))
    in_person = "OfflineEventAttendanceMode" in mode

    return {
        # --- eventbrite_normalize.py reads these ---
        "name": _first_str(ev.get("name"), ev.get("headline")),
        "title": _first_str(ev.get("name")),
        "description": _first_str(ev.get("description"), ev.get("about")),
        "startDate": _first_str(ev.get("startDate")),
        "endDate": _first_str(ev.get("endDate")),
        "start_at": _first_str(ev.get("startDate")),
        "end_at": _first_str(ev.get("endDate")),
        "timezone": "Asia/Singapore",
        "eventAttendanceMode": mode or (
            "https://schema.org/OfflineEventAttendanceMode" if in_person else ""
        ),
        "is_online": (not in_person) if mode else None,
        "location": venue["full_address"] or venue["venue_name"],
        "venue_name": venue["venue_name"],
        "venueCity": venue["city"],
        "venueCountry": venue["country"],
        "city": venue["city"],
        "country": venue["country"],
        "full_address": venue["full_address"],
        "address": venue["full_address"],
        "organizer_name": org_name,
        "organizer": org_name,
        "url": event_url or _first_str(ev.get("url")),
        "eventUrl": event_url or _first_str(ev.get("url")),
        "eventId": event_id,
        "event_id": event_id,
        "offers": ev.get("offers") or [],
        "is_free": is_free,
        "isFree": is_free,
        "price": price_text,
        "priceDisplay": price_text,
        "currency": _first_str(
            (ev.get("offers") or [{}])[0].get("priceCurrency")
        )
        if isinstance(ev.get("offers"), list) and ev["offers"]
        else "",
        "status": _first_str(ev.get("eventStatus")),
        "image": _first_str(ev.get("image")),
        "source_query": source_query,
        "matched_keyword": source_query,
        # backward-compat sugar so it reads like an Apify row
        "discovery_channel": "self-hosted",
    }


# --------------------------------------------------------------------------- #
# Discovery: listing -> dedup -> per-event enrich
# --------------------------------------------------------------------------- #
def _listing_item_url(item: dict[str, Any]) -> str:
    return _first_str(item.get("url"), item.get("sameAs"))


def build_events(
    *,
    categories: list[tuple[str, str]],
    keywords: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Fetch listing pages, collect event URLs, dedup by event id, return items."""
    seen: set[str] = set()
    collected: list[tuple[str, str, str]] = []  # (url, source_query, name)
    stats = {"listing_pages": 0, "listing_items": 0, "unique": 0, "dup_dropped": 0}

    targets: list[tuple[str, str]] = []  # (url, source_query)
    for cat_slug, query in categories:
        targets.append(
            (LISTING_URL.format(city=CITY_SLUG, category=cat_slug), query)
        )
    for kw in keywords or []:
        targets.append((SEARCH_URL.format(city=CITY_SLUG, kw=kw), kw))

    for url, query in targets:
        status, body = _http_get(url)
        stats["listing_pages"] += 1
        if status != 200 or not body:
            _warn_schema(
                "eventbrite_listing_fetch_failed",
                f"listing HTTP {status}",
                url,
            )
            continue
        docs = _extract_jsonld(body)
        items = _collect_listing_items(docs)
        stats["listing_items"] += len(items)
        for item in items:
            u = _listing_item_url(item)
            if not u:
                continue
            eid = _event_id_from_url(u)
            key = eid or u
            if key in seen:
                stats["dup_dropped"] += 1
                continue
            seen.add(key)
            collected.append((u, query, _first_str(item.get("name"))))
            stats["unique"] += 1
        time.sleep(MIN_DELAY_S)
    return collected, stats


def enrich_events(
    collected: list[tuple[str, str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Per-event fetch for authoritative pricing; shim to Apify shape.

    Returns (shimmed_events, price_resolution_counts).
    """
    out: list[dict[str, Any]] = []
    resolved = {"free": 0, "paid": 0, "unknown": 0}

    for i, (url, query, _name) in enumerate(collected):
        status, body = _http_get(url)
        ev_node: dict[str, Any] | None = None
        if status == 200 and body:
            docs = _extract_jsonld(body)
            nodes = _collect_event_nodes(docs)
            ev_node = nodes[0] if nodes else None
        if ev_node is None:
            _warn_schema(
                "eventbrite_event_fetch_failed",
                f"event page HTTP {status} or no Event node",
                url,
            )
            # Still emit a minimal row so the event isn't silently lost.
            ev_node = {"url": url, "name": _name}
        shim = shim_event(ev_node, source_query=query, event_url=url)
        if shim.get("is_free") is True:
            resolved["free"] += 1
        elif shim.get("is_free") is False:
            resolved["paid"] += 1
        else:
            resolved["unknown"] += 1
        out.append(shim)
        if i < len(collected) - 1:
            time.sleep(MIN_DELAY_S)
    return out, resolved


# --------------------------------------------------------------------------- #
# Self-test + score-parity (read-only, no deploy, no modify)
# --------------------------------------------------------------------------- #
def run_self_test() -> int:
    reset_schema_warnings()

    # --- 1) Known-FREE regression: offers low=high=0.0 must resolve free ---
    free_blob = {
        "name": "Self-test Free Eventbrite Event",
        "url": "https://www.eventbrite.sg/e/selftest-free-tickets-1000000000001",
        "startDate": "2026-08-01T18:30:00+08:00",
        "endDate": "2026-08-01T20:30:00+08:00",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "description": "A free community tech meetup.",
        "location": {
            "name": "Test Venue",
            "address": {
                "streetAddress": "1 Test Rd",
                "addressLocality": "Singapore",
                "addressCountry": "SG",
            },
        },
        "organizer": {"name": "Test Org"},
        "offers": [
            {
                "@type": "AggregateOffer",
                "lowPrice": "0.0",
                "highPrice": "0.0",
                "priceCurrency": "SGD",
            }
        ],
    }
    shim_free = shim_event(free_blob, source_query="data", event_url=free_blob["url"])
    known_free_ok = shim_free["is_free"] is True

    # --- 2) Known-PAID trap: offers=58.73 must NOT be fooled into free ---
    paid_blob = {
        "name": "Self-test Paid Eventbrite Event",
        "url": "https://www.eventbrite.sg/e/selftest-paid-tickets-1000000000002",
        "startDate": "2026-08-02T09:00:00+08:00",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"name": "Paid Venue", "address": {"addressLocality": "Singapore"}},
        "organizer": {"name": "Paid Org"},
        "offers": [
            {
                "@type": "AggregateOffer",
                "lowPrice": "58.73",
                "highPrice": "58.73",
                "priceCurrency": "SGD",
            }
        ],
    }
    shim_paid = shim_event(paid_blob, source_query="data", event_url=paid_blob["url"])
    known_paid_ok = shim_paid["is_free"] is False and "58.73" in (shim_paid.get("price") or "")

    # --- 3) Schema-drift guard: malformed offers blob must warn + fall back ---
    drift_cases: dict[str, bool] = {}

    # 3a) offers missing entirely
    reset_schema_warnings()
    no_offers = {"name": "x", "url": "https://www.eventbrite.sg/e/x-tickets-3", "offers": None}
    shim_no = shim_event(no_offers, source_query="data", event_url=no_offers["url"])
    drift_cases["missing_offers"] = (
        shim_no["is_free"] is None
        and any(w["code"] == "eventbrite_pricing_schema_drift" for w in get_schema_warnings())
    )

    # 3b) offers present but no lowPrice/highPrice (renamed/restructured)
    reset_schema_warnings()
    renamed = {
        "name": "x",
        "url": "https://www.eventbrite.sg/e/x-tickets-4",
        "offers": [{"@type": "AggregateOffer", "cost": "10"}],
    }
    shim_ren = shim_event(renamed, source_query="data", event_url=renamed["url"])
    drift_cases["renamed_offers"] = (
        shim_ren["is_free"] is None
        and any(w["code"] == "eventbrite_pricing_schema_drift" for w in get_schema_warnings())
    )

    reset_schema_warnings()
    drift_guard_ok = all(drift_cases.values()) and known_free_ok and known_paid_ok

    # --- 4) Score-parity: old Apify is_free vs new shim-resolved ---
    # Isolate PRICING as the only variable: build the "old" row from the SAME
    # populated fields the shim produces, but with an explicit is_free=true flag
    # (how the old Apify actor emitted free rows). The new row uses the shim's
    # offers-derived is_free. If pricing resolution is faithful, scores match.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from eventbrite_normalize import normalize_canonical  # noqa: E402
    from discovery_common import score_event  # noqa: E402

    old_input = {
        **free_blob,
        "is_free": True,  # old actor explicit free flag
        "offers": free_blob["offers"],
    }
    old = normalize_canonical(old_input, source_query="data")
    score_old, _ = score_event(old)

    # New path: shim-resolved free (offers-derived)
    new = normalize_canonical(shim_free, source_query="data")
    score_new, _ = score_event(new)
    parity_ok = score_old == score_new

    payload = {
        "known_free_resolves_true": known_free_ok,
        "known_paid_not_fooled": known_paid_ok,
        "schema_drift_guard": {
            "cases": drift_cases,
            "guard_ok": drift_guard_ok,
        },
        "score_parity": {
            "old_apify_free_score": score_old,
            "new_shim_resolved_free_score": score_new,
            "parity_ok": parity_ok,
            "note": "compares old Apify-free vs new shim-resolved free",
        },
        "pass": bool(
            known_free_ok and known_paid_ok and drift_guard_ok and parity_ok
        ),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Eventbrite discovery via JSON-LD (Apify replacement)"
    )
    ap.add_argument(
        "--categories",
        default=",".join(c for c, _ in DEFAULT_CATEGORIES),
        help="Comma-separated Eventbrite category slugs (singapore)",
    )
    ap.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword for search-URL mode (repeatable); e.g. --keyword data",
    )
    ap.add_argument("--output", choices=["json", "count"], default="json")
    ap.add_argument("--dry-run", action="store_true", help="self-test + score-parity only")
    ap.add_argument("--self-test", action="store_true", help="self-test + score-parity checks")
    ap.add_argument(
        "--debug-eb",
        action="store_true",
        help="print schema-drift warnings to stderr",
    )
    args = ap.parse_args()

    if args.dry_run or args.self_test:
        return run_self_test()

    # Map chosen category slugs back to their discovery query labels.
    cat_map = {c: q for c, q in DEFAULT_CATEGORIES}
    chosen = [c.strip() for c in args.categories.split(",") if c.strip()]
    categories = [(c, cat_map.get(c, c)) for c in chosen]
    keywords = [k.strip().lower() for k in args.keyword if k.strip()]

    collected, stats = build_events(categories=categories, keywords=keywords)
    events, resolved = enrich_events(collected)

    print(f"[discover] {stats} -> {resolved}", file=sys.stderr)

    warnings = get_schema_warnings()
    if warnings:
        print(
            f"[schema-drift] {len(warnings)} warning(s) -- signal degraded",
            file=sys.stderr,
        )
        if args.debug_eb:
            for w in warnings:
                print(
                    f"  [drift] {w['code']}: {w['detail']} ({w['event_url']})",
                    file=sys.stderr,
                )

    if args.output == "count":
        print(
            json.dumps(
                {
                    "unique_events": len(events),
                    "price_resolution": resolved,
                    "schema_warnings": warnings,
                    "coverage_note": "category listing + per-event fetch (unauth SSR); "
                    "no browser",
                },
                indent=2,
            )
        )
    else:
        print(json.dumps(events, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
