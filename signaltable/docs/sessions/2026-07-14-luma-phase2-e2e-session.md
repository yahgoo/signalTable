# Session Handoff — Luma Scraper Replacement: Phase 1 → 1.5 → 2 (E2E complete, HOLD for deploy)

**Date:** 2026-07-14 (Tue)
**Apify account-wide expiry:** 2026-07-20 (6 days from this session). Both Luma and Meetup must cut over or have a working self-hosted path before then.
**VPS:** `ubuntu@43.156.46.66` (Tencent Cloud Singapore). Profile `~/.hermes/profiles/signaltable/`. Node v22, Python 3.12.3. RAM 1.3 GiB — headless browser NOT viable.

---

## 1. Goal
Replace the Apify-based Luma scraper (Lexis/solidcode actor) with a self-hosted scraper, phased like the Meetup replacement. This session completed **Phase 1 (feasibility), Phase 1.5 (coverage gap), and Phase 2 (local build + integration + live E2E)**. **HOLD before any VPS deployment of `luma_scrape_fetch.py`.**

## 2. Phase 1 — Feasibility (DONE)
- **Fetch mechanism: plain HTTP, NO browser.** Luma SSR-embeds the full event object in `<script id="__NEXT_DATA__">` at `props.pageProps.initialData.data`. Same shape the Apify actor emitted.
- **Authoritative pricing signal: `ticket_info.is_free`** (top-level). NOT `ticket_types[].type/name` (a PAID event carries a `("free",None)` ticket type — verified).
- New file `signaltable/scripts/luma_scrape_fetch.py` (stdlib-only, NO new deps). Hoists `name`/`url`/`end_at` from `event` to top level + injects `query`; shims to exact Apify shape so `luma_normalize.py`/`discovery_common.py`/`version_a.py` need ZERO changes.
- Schema-drift guard from day one: `_check_ticketinfo_schema()` emits `luma_pricing_schema_drift` (loud) if `ticket_info`/`is_free` missing/renamed → returns None (visible unknown), not silent.
- Self-test PASS; score-parity 6==6.

## 3. Phase 1.5 — Coverage gap (DONE)
- **Auth finding:** actor log (`lexis-solutions--lu-ma-scraper-Log.txt`) shows PuppeteerCrawler (headless Chromium) doing paginated keyword search + community pages. **NO API key/session/cookie anywhere** — breadth was JS-driven, not credentials.
- **43 vs 20 gap is mostly NOT real loss:** old 43-item dataset spans 2023–2026 (23 events in 2024, long expired); only 26/43 geo-Singapore. A 2026-07-14 live `lu.ma/singapore` feed (20 events, 100% geo-SG) shares 0 slugs — expected staleness, not regression.
- **No-auth cannot exceed ~20:** `?page=`/`?q=`/`?sort=`/`?tag=` all ignored (still 20); `lu.ma/search` 404; `lu.ma/lorong-ai` (live host calendar) returns 0 via SSR (events need JS hydration).
- **Decision (user-approved):** accept 20-event curated SG feed as Phase 2 baseline. Browser/auth fuller coverage deferred as documented future enhancement (both paths dead-end at headless-browser requirement VPS can't support).

## 4. Phase 2 — Local build + integration + live E2E (DONE, HOLD deploy)
### 4a. Field-contract verification (pre-integration)
- `_load_luma` does NOT read a `query` field — calls `_first_query(item, queries, default)` which substring-scans the whole serialized item for the `queries` list (default `["data","algorithm","compute"]`). Shim injects `query="data,algorithm,compute"` → every event resolves `source_query='data'`. MATCH.
- **FIX APPLIED (in `luma_scrape_fetch.py` only):** curated city listing omits `ticket_types`/`categories`/`description_mirror` (actor's full items had them). Rewrote `enrich_prices` to fetch each event page ONCE and backfill those fields from the richer per-event blob (price stays authoritative from listing `ticket_info`). No existing normalize/discovery file modified.
- Post-fix: 20/20 ticket_types, 20/20 description_mirror, 18/20 categories backfilled. Pricing path `ticket_info.is_free` confirmed correct. Self-test still PASS; score-parity 6==6.

### 4b. Live discover cycle (local, read-only)
- Feed: 20 events, 5 free / 15 paid / **0 unknown**, 0 schema-drift warnings.
- `version_a.py discover --luma-input luma_feed.json`: 20 raw → 5 filter-pass (tech/AI + SG + upcoming) → 5 scored → 5 shortlist. Scores 8–9.
- **Food-detection improvement:** before fix 0/20 had description text; after fix **13/20 have real description text** for food-detection (remaining 7 = Luma per-event page genuinely has no description → correctly `not_mentioned`). Categories/tags now populated (e.g. `['AI','Arts & Culture']`, `['Crypto']`).
- `normalization_warnings: missing_critical_field:description` appears only for the 7 events with no description text (expected, not a drift warning).

### 4c. Single-event live E2E (VPS gateway, via Meetup-discipline)
- **Code NOT deployed.** Only the generated feed JSON was scp'd to VPS as a data file (`shadow/luma_feed_e2e.json`). VPS `version_a.py` already had `--luma-input` (deployed during Meetup Phase 3).
- E2E event: **"Islands in the Net Opening Party | Everyday Life in the Age of AI, Data & Memes"** (score 9, free, AI/Arts tags, `url:https://lu.ma/urfk9ocj`).
- **First attempt FAILED** (same root cause as earlier Luma Step-3): I queued/sent against a throwaway `--pending /tmp/luma_e2e_pending.json`, but the live reply hook (`telegram_reply_router`) reads the REAL `pending_shortlist.json` by default. So `awaiting_reply_for` was never primed in the real file → user's `y` fell through to the default agent ("Hello! How can I help you today?").
- **Fix:** re-ran queue+send against the REAL pending path (no `--pending` override). Re-sent card; user replied `y` again.
- **SECOND attempt PASSED:** bot replied **"Got it — yes: Islands in the Net … · live"** (routing ack, NOT default agent).
- **Feedback row verified (read-only):** `event_feedback.jsonl` contains row `event_key=url:https://lu.ma/urfk9ocj`, `label=y`, **`capture_mode=live`**, `queue_index=1`, title matches. `pending_shortlist.json` advanced (`sent_index=1`, `replied_index` advanced).
- **No live registration triggered** — `y` is a preference signal only.
- Backups made: `pending_shortlist.json.before-luma-e2e.*.bak` and `.before-luma-e2e-retry.*.bak`.

## 5. Outstanding / next steps (awaiting user go)
- **User must approve VPS deployment + shadow-run (Phase 3 equivalent)** before flipping the default Luma source. Same cron-validation discipline as Meetup.
- After deploy: one real scheduled-cycle shadow validation (cron, isolated output, no Telegram send), then go/no-go for cutover.
- Meetup cutover also still pending user approval (its one-shot cron validation passed clean on 2026-07-14 15:00).
- Eventbrite is third in priority (not started).

## 6. Key file pointers
- New (local-only, NOT deployed): `signaltable/scripts/luma_scrape_fetch.py`
- Untouched: `luma_normalize.py`, `discovery_common.py`, `version_a.py` (already had `--luma-input`), `registration_gateway.py`, `meetup_jsonld_fetch.py`, `_load_luma` (discovery_pipeline.py).
- Docs updated: `signaltable/docs/plan-log.md` (Phase 1.5 + Phase 2 entries), this handoff.
- VPS data artifacts (should be cleaned up post-session): `shadow/luma_feed_e2e.json`, `/tmp/luma_e2e_shortlist.json`, `/tmp/luma_e2e_pending.json`, `pending_shortlist.json.before-luma-e2e*.bak`.

## 7. Hard lessons (carry forward)
- **Never use a throwaway `--pending` path for live reply-routing E2E.** The live Telegram hook reads the REAL `pending_shortlist.json`. Always queue+send against the default real path (or pass `--pending` = real path) so `awaiting_reply_for` primes where the router looks.
- **Never use raw `hermes send`** for reply-routing tests (bypasses `version_a.py send` priming).
- **Pricing signal discipline:** trust the authoritative aggregate flag (`ticket_info.is_free` for Luma, `feeSettings` for Meetup), never the name/type field — verified both can lie.
- **2026-07-20 expiry:** both Luma and Meetup self-hosted paths exist and are validated; cutover approval needed for each.
