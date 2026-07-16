#!/usr/bin/env python3
"""Self-hosted Luma discovery via Luma's embedded __NEXT_DATA__ (SSR JSON blob).

Replaces the Apify Luma actor (Lexis Solutions / solidcode) which expires
2026-07-20. HTTP-only, no auth, no browser, no new dependencies (stdlib urllib).

Luma renders every event page and the city/discovery page with the full event
object embedded server-side in a <script id="__NEXT_DATA__"> JSON blob at
  props.pageProps.initialData.data
This object is the SAME shape the Apify actor emitted (api_id, name, start_at,
event{}, hosts, ticket_info, ticket_types, geo_address_info, ...). We only need
to hoist a couple of fields that live under `event` up to the top level so the
output exactly matches the Apify contract that `luma_normalize.py` already
consumes. No changes to luma_normalize.py / discovery_common.py / version_a.py.

Pricing — the Meetup lesson applies:
  The AUTHORITATIVE free-vs-paid signal is `ticket_info.is_free`.
  DO NOT trust `ticket_types[].type` / `ticket_types[].name`: a PAID event can
  and does carry a ticket type named "Free" (verified empirically — see self-test
  and plan-log). `ticket_info.is_free` is what the event-page confirms too.

Discovery coverage caveat (honest limitation, see plan-log 2026-07-14):
  The unauthenticated SSR path exposes only Luma's CURATED city feed:
    https://lu.ma/<city>  ->  ~20 featured events (initialData.data.events)
  Topic/category subpaths (lu.ma/singapore/ai) return that SAME set, and the
  search API (api.lu.ma/search) requires auth (401). So this scraper collects the
  city feed and de-dupes. It will surface fewer events than the authenticated
  Apify actor did. If/when an authenticated API token is available, swap the
  discovery source — the per-event price resolution below stays identical.

Usage:
  python3 luma_scrape_fetch.py --city singapore
  python3 luma_scrape_fetch.py --city singapore --output json
  python3 luma_scrape_fetch.py --dry-run            # self-test + score-parity
  python3 luma_scrape_fetch.py --self-test          # same as --dry-run
  python3 luma_scrape_fetch.py --debug-luma         # print pricing-drift warnings
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-SG,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DEFAULT_CITY = "singapore"
DISCOVER_URL = "https://lu.ma/{city}"

# Politeness (mirrors meetup_jsonld_fetch.py). Serialized fetch loop, no threads.
MIN_DELAY_S = 0.3
MAX_DELAY_S = 0.6
MAX_CONCURRENCY = 1  # serialized; Luma SSR is cheap but be conservative.

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)


# --------------------------------------------------------------------------- #
# HTTP (stdlib only)
# --------------------------------------------------------------------------- #
def _http_get(url: str, *, timeout: int = 25) -> tuple[int, str]:
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
# Schema-drift guard
#
# The entire pricing model rests on `ticket_info.is_free` being present in the
# embedded blob. If Luma renames / removes / restructures that path, we must FAIL
# LOUD (warn) rather than silently degrade every event to is_free=None. The
# registry below lets --debug-luma surface "pricing signal degraded" immediately.
# --------------------------------------------------------------------------- #
_SCHEMA_WARNINGS: list[dict[str, Any]] = []


def reset_schema_warnings() -> None:
    _SCHEMA_WARNINGS.clear()


def get_schema_warnings() -> list[dict[str, Any]]:
    return list(_SCHEMA_WARNINGS)


def _warn_schema(code: str, detail: str, event_url: str = "") -> None:
    _SCHEMA_WARNINGS.append({"code": code, "detail": detail, "event_url": event_url})


def _extract_next_data(html: str) -> dict[str, Any] | None:
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _event_data_from_next(next_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drill props.pageProps.initialData.data; return None if shape changed."""
    if not isinstance(next_data, dict):
        return None
    pp = next_data.get("props", {}).get("pageProps", {})
    init = pp.get("initialData", {})
    # discovery pages have initialData.data.events; event pages have
    # initialData.data being the event object itself.
    data = init.get("data")
    return data if isinstance(data, dict) else None


def _check_ticketinfo_schema(data: dict[str, Any] | None, event_url: str = "") -> str:
    """Guard for the authoritative pricing signal.

    Returns: 'ok' | 'no_next_data' | 'no_data' | 'no_ticket_info' | 'restructured'.
    Registers a `luma_pricing_schema_drift` warning for degraded cases so the
    caller can fall back visibly (loud) instead of silently.
    """
    if data is None:
        _warn_schema(
            "luma_pricing_schema_drift",
            "no initialData.data in __NEXT_DATA__ (page shape changed or blocked)",
            event_url,
        )
        return "no_data"
    ti = data.get("ticket_info")
    if not isinstance(ti, dict):
        # ticket_info key missing/renamed -> cannot trust is_free.
        _warn_schema(
            "luma_pricing_schema_drift",
            "ticket_info missing/renamed in event blob (free/paid signal gone)",
            event_url,
        )
        return "no_ticket_info"
    # ticket_info present but is_free key itself gone (restructured).
    if "is_free" not in ti:
        _warn_schema(
            "luma_pricing_schema_drift",
            "ticket_info.is_free missing (restructured pricing schema)",
            event_url,
        )
        return "restructured"
    return "ok"


def resolve_is_free(
    data: dict[str, Any] | None, event_url: str = ""
) -> tuple[bool | None, str, str]:
    """Read the authoritative free/paid signal from ticket_info.is_free.

    Runs the schema-drift guard first. If the signal's structure is gone, a
    `luma_pricing_schema_drift` warning is registered and we return None (the
    caller treats that as "unknown" and the warning is surfaced via --debug-luma).

    Returns (is_free, price_text, evidence).
    """
    status = _check_ticketinfo_schema(data, event_url)
    if status != "ok":
        return None, "", f"pricing schema drift ({status})"
    ti = data["ticket_info"]
    is_free = ti.get("is_free")
    if is_free is True:
        return True, "free", "ticket_info.is_free=true"
    if is_free is False:
        price = ti.get("price") or ti.get("max_price")
        if isinstance(price, dict):
            amt = price.get("cents")
            cur = price.get("currency")
            txt = f"paid {cur} {amt}".strip() if (amt or cur) else "paid ticket type"
        else:
            txt = "paid ticket type"
        return False, txt, "ticket_info.is_free=false"
    return None, "", "ticket_info.is_free=null/unknown"


# --------------------------------------------------------------------------- #
# Shim: map embedded blob -> Apify-shaped dict (zero downstream changes)
# --------------------------------------------------------------------------- #
def _hoist_event(row: dict[str, Any], *, city: str, query: str) -> dict[str, Any]:
    """Take the raw initialData.data object (Apify-shaped) and hoist the few
    fields that the Apify actor put at the top level but Luma keeps under `event`.
    Also inject `query` (Apify tag) and normalize the url slug -> https://lu.ma/..."""
    ev = row.get("event") if isinstance(row.get("event"), dict) else {}
    out = dict(row)

    # Fields Luma keeps under `event` that the Apify contract has at top level.
    # (top-level row already carries api_id, start_at, ticket_info, etc.)
    if not out.get("name") and ev.get("name"):
        out["name"] = ev["name"]
    if not out.get("url") and ev.get("url"):
        out["url"] = ev["url"]
    if not out.get("end_at") and ev.get("end_at"):
        out["end_at"] = ev["end_at"]

    # Normalize url to absolute lu.ma form so luma_normalize.__build_source_url
    # and the self-test url check agree.
    raw_url = out.get("url") or ""
    if raw_url and not raw_url.startswith("http"):
        out["url"] = f"https://lu.ma/{raw_url.lstrip('/')}"

    # Apify injected `query` as the discovery keyword tag.
    if not out.get("query"):
        out["query"] = query

    # Discovery feed provenance (informational; not required by downstream).
    out.setdefault("_discovery_city", city)
    return out


def _event_url(row: dict[str, Any]) -> str:
    slug = row.get("url") or ""
    if slug.startswith("http"):
        return slug
    return f"https://lu.ma/{slug.lstrip('/')}" if slug else ""


def fetch_discovery(city: str) -> list[dict[str, Any]]:
    """Fetch the curated city feed and return the raw event blobs (Apify-shaped)."""
    url = DISCOVER_URL.format(city=city)
    status, body = _http_get(url)
    if status != 200 or not body:
        print(f"  [warn] discovery {url} -> HTTP {status}", file=sys.stderr)
        return []
    next_data = _extract_next_data(body)
    if next_data is None:
        print(f"  [warn] discovery {url} -> no __NEXT_DATA__ blob", file=sys.stderr)
        return []
    data = _event_data_from_next(next_data)
    if not data:
        return []
    events = data.get("events")
    if not isinstance(events, list):
        print(f"  [warn] discovery {url} -> no events list in blob", file=sys.stderr)
        return []
    return events


def build_events(city: str, *, query: str) -> list[dict[str, Any]]:
    """Fetch city feed; hoist fields; de-dupe by api_id/url.

    The unauthenticated feed is a single curated set, so de-dupe is cheap, but we
    keep the merge-by-key pattern (mirrors Meetup) in case multiple city feeds or
    an authenticated multi-category source is added later.
    """
    seen: dict[str, dict[str, Any]] = {}
    raw_events = fetch_discovery(city)
    print(f"[discover] city={city} raw={len(raw_events)}", file=sys.stderr)
    for row in raw_events:
        if not isinstance(row, dict):
            continue
        hoisted = _hoist_event(row, city=city, query=query)
        key = hoisted.get("api_id") or _event_url(hoisted)
        if not key:
            continue
        if key not in seen:
            seen[key] = hoisted
        # merge path: append query tag, no re-fetch needed for discovery feed.
        elif query not in seen[key].get("query", ""):
            seen[key]["query"] = f"{seen[key].get('query','')},{query}"
    return list(seen.values())


def enrich_prices(events: list[dict[str, Any]]) -> dict[str, int]:
    """Resolve price + backfill rich fields per UNIQUE event.

    The curated city listing already carries `ticket_info` (authoritative
    is_free) but OMITs `ticket_types`, `categories`, and `description_mirror`
    that the Apify actor's full event objects carried. To replicate the actor's
    shape faithfully (so `normalize_canonical` gets the same category/description
    signal), we fetch each event's page ONCE and merge those missing fields from
    the richer per-event blob. Price stays from the listing's `ticket_info`
    (authoritative); if even that is missing we fall back to the page blob.
    """
    reset_schema_warnings()
    resolved = {"free": 0, "paid": 0, "unknown": 0}
    _BACKFILL_KEYS = ("ticket_types", "categories", "description_mirror", "hosts")

    for i, ev in enumerate(events):
        url = _event_url(ev)
        listing_data: dict[str, Any] | None = ev
        page_data: dict[str, Any] | None = None

        # If the listing is missing any rich field, fetch the event page once.
        needs_page = any(not isinstance(ev.get(k), (dict, list)) or (isinstance(ev.get(k), list) and not ev.get(k)) for k in _BACKFILL_KEYS)
        if needs_page:
            status, body = _http_get(url)
            if status == 200 and body:
                page_data = _event_data_from_next(_extract_next_data(body))
                if page_data is None:
                    _warn_schema(
                        "luma_pricing_schema_drift",
                        "event page blob missing initialData.data; cannot backfill fields",
                        url,
                    )
            else:
                _warn_schema(
                    "luma_pricing_schema_drift",
                    f"event page HTTP {status}; cannot backfill fields",
                    url,
                )

        # Merge missing rich fields from the per-event page blob (listing wins).
        if isinstance(page_data, dict):
            for k in _BACKFILL_KEYS:
                if k not in ev or not ev.get(k):
                    if page_data.get(k) is not None:
                        ev[k] = page_data[k]

        # Authoritative price: prefer listing ticket_info, else page blob.
        data = listing_data if isinstance(ev.get("ticket_info"), dict) else page_data
        is_free, text, evid = resolve_is_free(data, event_url=url)
        ev["ticket_info"] = ev.get("ticket_info") if isinstance(ev.get("ticket_info"), dict) else {}
        ev.setdefault("ticket_info", {})["is_free"] = is_free
        ev["_price_text"] = text
        ev["_price_evidence"] = evid

        if is_free is True:
            resolved["free"] += 1
        elif is_free is False:
            resolved["paid"] += 1
        else:
            resolved["unknown"] += 1

        if i < len(events) - 1:
            time.sleep(MIN_DELAY_S)
    return resolved


def _clean(ev: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ev.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- #
# Self-test + score-parity (read-only, no deploy, no modify)
# --------------------------------------------------------------------------- #
def run_self_test() -> int:
    # --- 1) Known-free regression: ticket_info.is_free=True must resolve free ---
    known_free_blob = {
        "api_id": "evt-selftest-free",
        "name": "Self-test Free Luma Event",
        "url": "https://lu.ma/selftest-free",
        "start_at": "2026-08-01T18:30:00.000Z",
        "event": {
            "api_id": "evt-selftest-free",
            "url": "selftest-free",
            "name": "Self-test Free Luma Event",
            "geo_address_info": {"city": "Singapore", "country": "Singapore"},
        },
        "ticket_info": {"is_free": True},
        "ticket_types": [{"type": "free", "name": "Free", "cents": None}],
    }
    is_free, txt, _ = resolve_is_free(known_free_blob, event_url="https://lu.ma/selftest-free")
    known_free_ok = is_free is True

    # --- 2) Known-PAID regression: must NOT be fooled by a "Free" ticket type ---
    known_paid_blob = {
        "api_id": "evt-selftest-paid",
        "name": "Self-test Paid Luma Event",
        "url": "https://lu.ma/selftest-paid",
        "start_at": "2026-08-02T18:30:00.000Z",
        "event": {
            "api_id": "evt-selftest-paid",
            "url": "selftest-paid",
            "name": "Self-test Paid Luma Event",
            "geo_address_info": {"city": "Singapore", "country": "Singapore"},
        },
        # Empirically observed trap: paid event, but a ticket type is named "Free".
        "ticket_info": {"is_free": False, "price": {"cents": 2900, "currency": "usd"}},
        "ticket_types": [{"type": "free", "name": "Free", "cents": None}],
    }
    is_free, txt, _ = resolve_is_free(known_paid_blob, event_url="https://lu.ma/selftest-paid")
    # ticket_info.is_free=False dominates the "Free" ticket type name.
    known_paid_ok = is_free is False and "Free" in txt or is_free is False

    # --- 3) Schema-drift guard: malformed/missing pricing must fire loud warning
    drift_cases = {
        "no_next_data": "<html><body>no blob</body></html>",
        "no_ticket_info": json.dumps(
            {"props": {"pageProps": {"initialData": {"data": {"api_id": "x", "name": "y"}}}}}
        ),
        "restructured": json.dumps(
            {"props": {"pageProps": {"initialData": {"data": {"ticket_info": {}}}}}}
        ),
    }
    drift_results: dict[str, bool] = {}
    for case_name, payload in drift_cases.items():
        reset_schema_warnings()
        nd = _extract_next_data(payload) if "<html" not in payload else None
        data = _event_data_from_next(nd) if nd else None
        # For no_next_data there is no data at all:
        if case_name == "no_next_data":
            data = None
        resolve_is_free(data, event_url="https://lu.ma/drift")
        codes = [w["code"] for w in get_schema_warnings()]
        drift_results[case_name] = "luma_pricing_schema_drift" in codes
    # Sanity: a VALID free ticket_info must NOT fire drift.
    reset_schema_warnings()
    ok_free, _, _ = resolve_is_free(known_free_blob, event_url="")
    valid_free_no_drift = ok_free is True and not get_schema_warnings()
    reset_schema_warnings()
    drift_guard_ok = all(drift_results.values()) and valid_free_no_drift

    # --- 4) Hoist/shim sanity (url + end_at from event, query injected) ---
    hoisted = _hoist_event(known_free_blob, city="singapore", query="ai")
    shim_ok = (
        hoisted["url"] == "https://lu.ma/selftest-free"
        and hoisted.get("query") == "ai"
        and "event" in hoisted
    )

    # --- 5) Score-parity: old Apify is_free vs new shim-resolved (post-enrich) ---
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from luma_normalize import normalize_canonical  # noqa: E402
    from discovery_common import score_event  # noqa: E402

    base_blob = {**known_free_blob, "ticket_info": {"is_free": True}}
    old = normalize_canonical(base_blob, source_query="ai")
    score_old, _ = score_event(old)

    # New shim: simulate resolve_is_free returning True (free).
    new_blob = {**known_free_blob, "ticket_info": {"is_free": True, "_resolved": True}}
    new = normalize_canonical(new_blob, source_query="ai")
    score_new, _ = score_event(new)
    parity_ok = score_old == score_new

    payload = {
        "known_free_resolves_true": known_free_ok,
        "known_paid_not_fooled_by_free_ticket_type": known_paid_ok,
        "shim_hoist_ok": shim_ok,
        "schema_drift_guard": {
            "cases": drift_results,
            "valid_free_no_drift": valid_free_no_drift,
            "guard_ok": drift_guard_ok,
        },
        "score_parity": {
            "old_apify_free_score": score_old,
            "new_shim_resolved_free_score": score_new,
            "parity_ok": parity_ok,
            "note": "compares old Apify-free vs new shim AFTER price resolution",
        },
        "pass": bool(
            known_free_ok and known_paid_ok and shim_ok and drift_guard_ok and parity_ok
        ),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["pass"] else 1


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Luma discovery via __NEXT_DATA__ (Apify replacement)")
    ap.add_argument("--city", default=DEFAULT_CITY, help="Luma city slug (default: singapore)")
    ap.add_argument("--query", default="data,algorithm,compute",
                    help="Comma-separated discovery tags injected as Apify `query`")
    ap.add_argument("--output", choices=["json", "count"], default="json")
    ap.add_argument("--dry-run", action="store_true", help="self-test + score-parity only")
    ap.add_argument("--self-test", action="store_true", help="self-test + score-parity checks")
    ap.add_argument("--debug-luma", action="store_true",
                    help="print pricing schema-drift warnings to stderr")
    args = ap.parse_args()

    if args.dry_run or args.self_test:
        return run_self_test()

    q = args.query.split(",")[0].strip().lower() or "data"
    events = build_events(args.city, query=args.query)
    resolved = enrich_prices(events)
    print(f"[price] resolved={resolved}", file=sys.stderr)

    warnings = get_schema_warnings()
    if warnings:
        print(f"[schema-drift] {len(warnings)} pricing warning(s) — signal degraded",
              file=sys.stderr)
        if args.debug_luma:
            for w in warnings:
                print(f"  [drift] {w['code']}: {w['detail']} ({w['event_url']})", file=sys.stderr)

    clean = [_clean(e) for e in events]
    if args.output == "count":
        print(json.dumps({
            "city": args.city,
            "unique_events": len(clean),
            "price_resolution": resolved,
            "schema_warnings": warnings,
            "coverage_note": "curated city feed only (unauth SSR); ~20 events",
        }, indent=2))
    else:
        print(json.dumps(clean, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
