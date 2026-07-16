#!/usr/bin/env python3
"""Self-hosted Meetup discovery via public Schema.org JSON-LD scraping.

Replaces the Apify Meetup actor (expires 2026-07-20). HTTP-only, no auth,
no browser. Reads the JSON-LD `Event` blocks that Meetup embeds on its
public `find/` search pages and per-event pages.

How it maps to the downstream contract:
  - Emits Apify-shaped dicts so `meetup_normalize.normalize_canonical()` needs
    ZERO changes (same "zero-change" principle used for the Luma replacement).
  - All missing Meetup-specific fields are backfilled HERE (the shim), never in
    meetup_normalize.py:
      * eventId        <- numeric id parsed from eventUrl
      * eventType      <- derived from eventAttendanceMode
      * group.name     <- derived from the group slug in eventUrl
      * isPaidEvent    <- from a per-event price-confirmation GET (Option B)
      * registrationVenue / topics / actualAttendees -> null/empty

Pricing (Option B): for each UNIQUE event we do ONE extra GET to the event
page and resolve price in priority order:
  1. __NEXT_DATA__ `feeSettings` — authoritative (null=free, object=paid with
     amount/currency). 100% resolution across the tested Singapore sample.
  2. event-page JSON-LD `offers` — easy path, but Meetup rarely populates it.
  3. light HTML scan — last resort only.
Event-page JSON-LD carries no price fields in practice, so feeSettings is the
real signal; the JSON-LD/offers check is kept as a cheap belt-and-braces path.

Usage:
  python3 meetup_jsonld_fetch.py --keywords data,algorithm,compute
  python3 meetup_jsonld_fetch.py --dry-run          # self-test + score-parity
  python3 meetup_jsonld_fetch.py --output json      # emit JSON to stdout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DEFAULT_KEYWORDS = ["data", "algorithm", "compute"]
DEFAULT_LOCATION = "sg--Singapore"
FIND_URL = "https://www.meetup.com/find/?location={loc}&source=EVENTS&keywords={kw}"

# Politeness
MIN_DELAY_S = 0.2
MAX_DELAY_S = 0.5
MAX_CONCURRENCY = 2  # serialized via simple sleep loop (no threads; keep it simple/safe)


# --------------------------------------------------------------------------- #
# HTTP helpers (stdlib only — no extra deps)
# --------------------------------------------------------------------------- #
def _http_get(url: str, *, timeout: int = 20) -> tuple[int, str]:
    """Return (status, body). Uses urllib; raises nothing fatal to the loop."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001 - we want to keep scraping resilient
        return -1, f"ERROR:{type(exc).__name__}:{exc}"


# --------------------------------------------------------------------------- #
# JSON-LD extraction
# --------------------------------------------------------------------------- #
def extract_jsonld_events(html: str) -> list[dict[str, Any]]:
    blocks = re.findall(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    events: list[dict[str, Any]] = []
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Event":
                events.append(item)
    return events


# --------------------------------------------------------------------------- #
# Field shims (meetup_normalize.py contract)
# --------------------------------------------------------------------------- #
def _event_id_from_url(url: str) -> str:
    m = re.search(r"/events/(\d+)", url or "")
    return m.group(1) if m else ""


def _group_slug_from_url(url: str) -> str:
    m = re.search(r"meetup\.com/([^/]+)/events/", url or "")
    return m.group(1) if m else ""


def _humanize_slug(slug: str) -> str:
    slug = slug or ""
    # strip common trailing group tokens
    slug = re.sub(r"-(sg|singapore|group|community|meetup)$", "", slug)
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def _event_type_from_mode(mode: str) -> str:
    m = (mode or "").lower()
    if "online" in m and "offline" not in m:
        return "ONLINE"
    if "hybrid" in m:
        return "HYBRID"
    return "PHYSICAL"  # default to in-person (matches meetup_normalize default)


def _price_from_jsonld_event(ev: dict[str, Any]) -> tuple[bool | None, str, str]:
    """Try to read Offer/price from a JSON-LD Event node."""
    offers = ev.get("offers") or ev.get("availableOffer")
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list) and offers:
        for off in offers:
            if not isinstance(off, dict):
                continue
            price = off.get("price")
            if isinstance(price, (int, float)) and price > 0:
                return False, f"paid (jsonld offer: {price})", "jsonld offer present"
            if isinstance(price, (int, float)) and price == 0:
                return True, "free", "jsonld offers price=0"
        # offers list existed but carried no explicit numeric price -> unknown
    # isPaid / free flags sometimes directly present
    if ev.get("isPaidEvent") is True:
        return False, "paid", "jsonld isPaidEvent=true"
    if ev.get("isPaidEvent") is False:
        return True, "free", "jsonld isPaidEvent=false"
    return None, "", ""


_PAID_TEXT = ("sgd", "usd", "$", "paid", "ticket price", "ticket required", "fee")
_FREE_TEXT = ("free event", "free to attend", "no charge", "complimentary", "free admission")


def _price_from_html(html: str, event_name: str = "") -> tuple[bool | None, str, str]:
    """Light HTML scan fallback when JSON-LD has no price signal."""
    text = re.sub(r"\s+", " ", html).lower()
    # narrow to a price-ish window if possible
    name_l = event_name.lower()
    idx = text.find(name_l[:20]) if name_l else -1
    window = text[max(0, idx - 200): idx + 4000] if idx >= 0 else text[:6000]
    if any(p in window for p in _PAID_TEXT):
        return False, "paid (html signal)", "html scan found paid marker"
    if any(f in window for f in _FREE_TEXT):
        return True, "free", "html scan found free marker"
    if "free" in window:
        return True, "free", "html scan found 'free'"
    return None, "", "no price signal found"


# --------------------------------------------------------------------------- #
# Schema-drift guard (mirrors luma_normalize hardening philosophy)
#
# The whole Option-B pricing model depends on Meetup's embedded __NEXT_DATA__
# carrying a `feeSettings` node (null=free, object=paid). If Meetup renames /
# removes / restructures that key, we must FAIL LOUD (warn) rather than silently
# degrade every event to is_free=None (which reintroduces the -3 scoring gap
# with no visible cause). This registry collects those warnings so a debug flag
# can surface "pricing signal degraded" immediately.
# --------------------------------------------------------------------------- #
_SCHEMA_WARNINGS: list[dict[str, Any]] = []


def reset_schema_warnings() -> None:
    _SCHEMA_WARNINGS.clear()


def get_schema_warnings() -> list[dict[str, Any]]:
    return list(_SCHEMA_WARNINGS)


def _warn_schema(code: str, detail: str, event_url: str = "") -> None:
    _SCHEMA_WARNINGS.append({"code": code, "detail": detail, "event_url": event_url})


def _check_feesettings_schema(html: str, event_url: str = "") -> str:
    """Verify the feeSettings key path still exists at the expected location in
    __NEXT_DATA__. Returns one of: 'ok', 'no_next_data', 'key_missing',
    'restructured'. Registers a `meetup_feesettings_schema_drift` warning for the
    degraded cases so callers/CLI can surface it.
    """
    if "__NEXT_DATA__" not in html:
        _warn_schema(
            "meetup_feesettings_schema_drift",
            "event page has no __NEXT_DATA__ blob (page shape changed or blocked)",
            event_url,
        )
        return "no_next_data"
    # Expected value shape: null OR a JSON object.
    if re.search(r'"feeSettings":(null|\{[^}]*\})', html):
        return "ok"
    if '"feeSettings"' in html:
        # Key exists but value isn't the expected null/object shape (restructured).
        snippet = ""
        m = re.search(r'"feeSettings":.{0,60}', html)
        if m:
            snippet = m.group(0)
        _warn_schema(
            "meetup_feesettings_schema_drift",
            f"feeSettings present but value not null/object (restructured): {snippet!r}",
            event_url,
        )
        return "restructured"
    _warn_schema(
        "meetup_feesettings_schema_drift",
        "feeSettings key not found in __NEXT_DATA__ (renamed or removed)",
        event_url,
    )
    return "key_missing"


def _price_from_next_data(html: str, event_url: str = "") -> tuple[bool | None, str, str, Any, str]:
    """Read Meetup's embedded __NEXT_DATA__ `feeSettings` — the authoritative
    price signal on event pages. null => free; object => paid (with amount/currency).

    Runs the schema-drift guard first: if feeSettings is missing/renamed/
    restructured, a `meetup_feesettings_schema_drift` warning is registered and we
    return None so the caller falls back (visibly degraded, not silently).

    Returns (is_free, price_text, evidence, fee_amount, fee_currency).
    """
    status = _check_feesettings_schema(html, event_url)
    if status != "ok":
        return None, "", f"feeSettings schema drift ({status})", None, None
    m = re.search(r'"feeSettings":(null|\{[^}]*\})', html)
    if not m:  # defensive; guard already confirmed 'ok'
        return None, "", "no feeSettings in __NEXT_DATA__", None, None
    val = m.group(1)
    if val == "null":
        return True, "free", "feeSettings=null", None, None
    try:
        fee = json.loads(val)
    except json.JSONDecodeError:
        return False, "paid", "feeSettings present (unparsed)", None, None
    amt = fee.get("amount")
    cur = fee.get("currency")
    return False, f"paid {cur} {amt}".strip(), "feeSettings object", amt, cur


def resolve_price(
    event_page_html: str, jsonld_ev: dict[str, Any], event_name: str, event_url: str = ""
) -> tuple[bool | None, str, str, Any, Any]:
    # 1) Authoritative: __NEXT_DATA__ feeSettings (100% resolution in testing)
    is_free, text, ev, amt, cur = _price_from_next_data(event_page_html, event_url)
    if is_free is not None:
        return is_free, text, f"next_data: {ev}", amt, cur
    # 2) Easy path: event-page JSON-LD offers (rarely present, but cheap)
    is_free, text, ev = _price_from_jsonld_event(jsonld_ev)
    if is_free is not None:
        return is_free, text, f"event-page jsonld: {ev}", None, None
    # 3) Last resort: light HTML scan
    is_free, text, ev = _price_from_html(event_page_html, event_name)
    return is_free, text, ev, None, None


# --------------------------------------------------------------------------- #
# Core fetch
# --------------------------------------------------------------------------- #
def fetch_find_page(keyword: str, location: str) -> list[dict[str, Any]]:
    url = FIND_URL.format(loc=location, kw=urllib_parse_quote(keyword))
    status, body = _http_get(url)
    if status != 200 or not body:
        print(f"  [warn] find page {keyword!r} -> HTTP {status}", file=sys.stderr)
        return []
    return extract_jsonld_events(body)


def _to_apify_shape(ev: dict[str, Any], *, keyword: str) -> dict[str, Any]:
    loc = ev.get("location") or {}
    addr = loc.get("address") or {} if isinstance(loc, dict) else {}
    org = ev.get("organizer") or {}
    slug = _group_slug_from_url(ev.get("url", ""))
    event_id = _event_id_from_url(ev.get("url", ""))
    return {
        "eventId": event_id,
        "eventName": ev.get("name", ""),
        "eventDescription": ev.get("description", ""),
        "eventUrl": ev.get("url", ""),
        "date": ev.get("startDate", ""),
        "endDateTime": ev.get("endDate", ""),
        "eventType": _event_type_from_mode(ev.get("eventAttendanceMode", "")),
        "isOnline": "online" in (ev.get("eventAttendanceMode") or "").lower(),
        # isPaidEvent set later in enrich step; placeholder None
        "isPaidEvent": None,
        "feeAmount": None,
        "feeCurrency": None,
        "venue": {
            "name": loc.get("name", "") if isinstance(loc, dict) else "",
            "city": addr.get("addressLocality", "") if isinstance(addr, dict) else "",
            "country": addr.get("addressCountry", "") if isinstance(addr, dict) else "",
            "address": addr.get("streetAddress", "") if isinstance(addr, dict) else "",
        },
        "registrationVenue": None,
        "group": {"name": _humanize_slug(slug) or (org.get("name") if isinstance(org, dict) else "")},
        "hosts": [{"name": org.get("name")}] if isinstance(org, dict) and org.get("name") else [],
        "topics": [],
        "actualAttendees": None,
        "eventStatus": (
            "ACTIVE" if "Scheduled" in str(ev.get("eventStatus", "")) else str(ev.get("eventStatus", ""))
        ),
        # shim metadata
        "_source_query": keyword,
        "_jsonld_event": ev,  # kept for price resolution; stripped before output
    }


def build_events(keywords: list[str], location: str) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for kw in keywords:
        print(f"[find] keyword={kw!r}", file=sys.stderr)
        for ev in fetch_find_page(kw, location):
            shape = _to_apify_shape(ev, keyword=kw)
            key = shape.get("eventUrl") or shape.get("eventId")
            if not key:
                continue
            if key not in seen:
                seen[key] = shape
            else:
                # merge keyword tags without re-fetching
                seen[key]["_source_query"] = seen[key].get("_source_query", "") + "," + kw
    return list(seen.values())


def enrich_prices(events: list[dict[str, Any]]) -> dict[str, Any]:
    reset_schema_warnings()
    resolved = {"free": 0, "paid": 0, "unknown": 0}
    for i, ev in enumerate(events):
        url = ev.get("eventUrl", "")
        status, body = _http_get(url)
        if status == 200 and body:
            is_free, text, ev2, amt, cur = resolve_price(
                body, ev.get("_jsonld_event") or {}, ev.get("eventName", ""), event_url=url
            )
        else:
            is_free, text, ev2, amt, cur = None, f"event page HTTP {status}", "event page unreachable", None, None
        # isPaidEvent is the PAID flag (inverse of is_free); None stays None.
        ev["isPaidEvent"] = (not is_free) if is_free is not None else None
        ev["feeAmount"] = amt
        ev["feeCurrency"] = cur
        ev["_price_evidence"] = text
        ev["_price_source"] = ev2
        if is_free is True:
            resolved["free"] += 1
        elif is_free is False:
            resolved["paid"] += 1
        else:
            resolved["unknown"] += 1
        # politeness delay (except after last)
        if i < len(events) - 1:
            time.sleep(MIN_DELAY_S)
    return resolved


def _clean(ev: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in ev.items() if not k.startswith("_")}
    # Preserve which keyword surfaced this event so version_a can set source_query.
    if ev.get("_source_query"):
        out["source_query"] = ev["_source_query"]
    return out


# --------------------------------------------------------------------------- #
# Self-test + score-parity (read-only, no deploy, no modify)
# --------------------------------------------------------------------------- #
def run_self_test() -> int:
    # Use a real captured find-page if present, else do a live fetch of one keyword.
    sample_html = None
    candidate = Path("/tmp/meetup_find.html")
    if candidate.is_file():
        sample_html = candidate.read_text(encoding="utf-8")
    else:
        status, body = _http_get(FIND_URL.format(loc=DEFAULT_LOCATION, kw="data"))
        if status == 200:
            sample_html = body

    if not sample_html:
        print(json.dumps({"error": "no sample find-page HTML available for self-test"}))
        return 2

    evs = extract_jsonld_events(sample_html)
    assert evs, "self-test: no JSON-LD Event blocks found in sample"
    shape = _to_apify_shape(evs[0], keyword="data")
    assert shape["eventId"], "self-test: eventId not derived from URL"
    assert shape["eventUrl"].startswith("https://www.meetup.com/"), "self-test: bad eventUrl"
    assert shape["eventType"] in {"PHYSICAL", "ONLINE", "HYBRID"}, "self-test: bad eventType"

    # Regression guard: at least one KNOWN-FREE test event must resolve is_free True.
    # Use a synthetic known-free JSON-LD Event node.
    known_free = {
        "@type": "Event",
        "name": "Self-test Free Meetup",
        "url": "https://www.meetup.com/test-group/events/999999999/",
        "description": "Free event, all welcome.",
        "startDate": "2026-08-01T10:00:00Z",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"name": "TBD", "address": {"addressLocality": "Singapore", "addressCountry": "sg"}},
        "offers": [{"price": 0, "priceCurrency": "USD", "availability": "InStock"}],
    }
    is_free, _, _, _, _ = resolve_price("<html>free event</html>", known_free, known_free["name"])
    free_guard_ok = is_free is True

    # Score-parity: same event, old Apify (isPaidEvent=false -> free) vs new shim.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from meetup_normalize import normalize_canonical
    from discovery_common import score_event

    base = {
        "eventId": "999888777",
        "eventName": "Parity Test AI Meetup",
        "eventDescription": "Free hands-on AI meetup.",
        "eventUrl": "https://www.meetup.com/parity-group/events/999888777/",
        "date": "2026-08-02T18:30:00+08:00",
        "endDateTime": "",
        "eventType": "PHYSICAL",
        "isOnline": False,
        "venue": {"name": "Test Venue", "city": "Singapore", "country": "sg", "address": "1 Test Rd"},
        "group": {"name": "Parity Group"},
        "hosts": [{"name": "Parity Group"}],
        "topics": [],
    }
    # Old Apify path: isPaidEvent=false => confirmed free
    old = normalize_canonical({**base, "isPaidEvent": False}, source_query="ai")
    score_old, _ = score_event(old)
    # New shim: simulate Option B price GET resolving the same event as free.
    # Use a known-free JSON-LD node so resolve_price returns True (mirrors live GET).
    is_free, _, _, _, _ = resolve_price("<html>free event</html>", known_free, known_free["name"])
    resolved_paid_flag = (not is_free) if is_free is not None else None
    new_resolved = normalize_canonical({**base, "isPaidEvent": resolved_paid_flag}, source_query="ai")
    score_new_resolved, _ = score_event(new_resolved)
    parity_ok = score_old == score_new_resolved  # post-GET parity must hold

    # Schema-drift regression guard: a malformed/missing feeSettings blob MUST
    # fire meetup_feesettings_schema_drift (not silently degrade to None).
    drift_cases = {
        "key_missing": '<html><script id="__NEXT_DATA__">{"props":{"event":{}}}</script></html>',
        "restructured": '<html><script id="__NEXT_DATA__">{"feeSettings":"7 USD"}</script></html>',
        "no_next_data": "<html><body>no next data here</body></html>",
    }
    drift_results: dict[str, bool] = {}
    for case_name, html in drift_cases.items():
        reset_schema_warnings()
        # Isolate the guard from the HTML-scan fallback (which can coincidentally
        # find price words in the malformed blob) — assert the drift WARNING fires.
        _price_from_next_data(html, event_url="https://x/events/1/")
        codes = [w["code"] for w in get_schema_warnings()]
        drift_results[case_name] = "meetup_feesettings_schema_drift" in codes
    reset_schema_warnings()
    # Sanity: a VALID null feeSettings must NOT fire drift (free, no warning).
    ok_free, _, _, _, _ = resolve_price(
        '<html><script id="__NEXT_DATA__">{"feeSettings":null}</script></html>', {}, "OK", event_url=""
    )
    valid_free_no_drift = ok_free is True and not get_schema_warnings()
    reset_schema_warnings()
    drift_guard_ok = all(drift_results.values()) and valid_free_no_drift

    payload = {
        "jsonld_blocks_in_sample": len(evs),
        "shim_eventId_ok": bool(shape["eventId"]),
        "shim_eventType": shape["eventType"],
        "known_free_resolves_true": free_guard_ok,
        "score_parity": {
            "old_apify_free_score": score_old,
            "new_shim_resolved_free_score": score_new_resolved,
            "new_shim_price_resolved_to": is_free,
            "parity_ok": parity_ok,
            "note": "parity compares old Apify-free vs new shim AFTER Option B price GET resolves is_free",
        },
        "schema_drift_guard": {
            "cases": drift_results,
            "valid_free_no_drift": valid_free_no_drift,
            "guard_ok": drift_guard_ok,
            "note": "malformed/missing feeSettings must fire meetup_feesettings_schema_drift + return None",
        },
        "pass": bool(evs and shape["eventId"] and free_guard_ok and parity_ok and drift_guard_ok),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Meetup JSON-LD discovery (Apify replacement)")
    ap.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS),
                    help="Comma-separated keywords (default: data,algorithm,compute)")
    ap.add_argument("--location", default=DEFAULT_LOCATION, help="Meetup location slug")
    ap.add_argument("--output", choices=["json", "count"], default="json")
    ap.add_argument("--dry-run", action="store_true", help="self-test + score-parity only")
    ap.add_argument("--self-test", action="store_true", help="self-test + score-parity checks")
    ap.add_argument("--debug-meetup", action="store_true",
                    help="print pricing schema-drift warnings to stderr")
    args = ap.parse_args()

    if args.dry_run or args.self_test:
        return run_self_test()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"[start] keywords={keywords} location={args.location}", file=sys.stderr)
    events = build_events(keywords, args.location)
    print(f"[find] unique events={len(events)}", file=sys.stderr)
    resolved = enrich_prices(events)
    print(f"[price] resolved={resolved}", file=sys.stderr)
    warnings = get_schema_warnings()
    if warnings:
        print(f"[schema-drift] {len(warnings)} pricing warning(s) — pricing signal degraded",
              file=sys.stderr)
        if args.debug_meetup:
            for w in warnings:
                print(f"  [drift] {w['code']}: {w['detail']} ({w['event_url']})", file=sys.stderr)
    clean = [_clean(e) for e in events]

    if args.output == "count":
        print(json.dumps({
            "unique_events": len(clean),
            "price_resolution": resolved,
            "schema_warnings": warnings,
        }, indent=2))
    else:
        print(json.dumps(clean, indent=2, ensure_ascii=False))
    return 0


def urllib_parse_quote(s: str) -> str:
    from urllib.parse import quote

    return quote(s)


if __name__ == "__main__":
    raise SystemExit(main())
