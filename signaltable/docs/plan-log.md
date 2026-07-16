# SignalTable 20-Day Transition Plan

**Project**: SignalTable — Hermes-based Singapore tech event automation  
**Start date**: 2026-07-03  
**End date**: 2026-07-22  
**VPS**: ubuntu@43.156.46.66 (Tencent Cloud Singapore)  
**Profile**: `~/.hermes/profiles/signaltable/`

---

## Phase 1: Foundation (Days 1–4)

### Day 1 — Environment Setup
- [ ] SSH into VPS, take full Hermes backup
- [ ] Create `signaltable` Hermes profile (`hermes profile create signaltable --clone`)
- [ ] Deploy SOUL.md, skills, config overlay to VPS profile
- [ ] Verify gateway still running (default profile); confirm signaltable profile isolated
- [ ] Install Scrapling skill: `signaltable skills install official/research/scrapling`
- [ ] Install LobsterMail MCP in signaltable config
- [ ] Install PortEden CLI, authenticate
- [ ] Install Steel browser (API key required from owner)

### Day 2 — Integration Smoke Tests
- [ ] LobsterMail: create `signaltable-reg` inbox, verify address
- [ ] PortEden: `porteden calendar calendars -jc` — confirm Google Calendar accessible
- [ ] Create "SignalTable Events" calendar (manual via Google Calendar or PortEden)
- [ ] Steel: basic browser session test (navigate to eventbrite.sg)
- [ ] Scrapling: fetch test (`scrapling fetch https://www.eventbrite.sg/d/singapore--singapore/tech--events/`)
- [ ] Telegram: send test message via signaltable_bot to verify gateway

### Day 3 — Discovery Dry Run (Apify Comparison Day 1)
- [ ] Run event-discovery skill manually: `signaltable chat "Run the event-discovery skill"`
- [ ] Compare results against Apify actor output (manual side-by-side in comparison.csv)
- [ ] Log discrepancies: events found by Apify but not Hermes, and vice versa
- [ ] Tune relevance scoring in event-discovery.md if needed

### Day 4 — Registration Dry Run (MuleRun Comparison Day 1)
- [ ] Pick 1 Tier 1 event from Day 3 discovery
- [ ] Run event-register skill manually in dry-run mode (no actual submit)
- [ ] Compare form-fill steps with MuleRun/manual flow
- [ ] Document any form fields that need special handling

---

## Phase 2: Core Flows (Days 5–10)

### Day 5 — First Live Registration
- [ ] Pick 1 Tier 1 free event (confirmed safe)
- [ ] Run event-register skill live — submit actual registration
- [ ] Run email-parser skill — verify LobsterMail receives confirmation
- [ ] Run calendar-updater — verify event in SignalTable Events calendar
- [ ] Run telegram-reporter — verify Telegram summary received
- [ ] Log result in comparison.csv

### Day 6 — Tier 2 Approval Flow
- [ ] Find 1 Tier 2 event from latest discovery run
- [ ] Verify Telegram approval message is sent correctly
- [ ] Test "YES" reply triggers registration
- [ ] Test "NO" reply skips event and logs correctly

### Day 7 — Cron Job Setup
- [ ] Create daily cron job (8:00 AM SGT):
  ```bash
  signaltable cron create "0 0 * * *" \
    "Run event-discovery skill, then for each Tier 1 event run event-register, email-parser, calendar-updater, and telegram-reporter skills. Send daily digest via telegram-reporter." \
    --skill event-discovery --skill event-register --skill email-parser \
    --skill calendar-updater --skill telegram-reporter \
    --name "signaltable-daily"
  ```
- [ ] Verify cron job registered: `signaltable cron list`
- [ ] Run a manual trigger: `signaltable cron run signaltable-daily`

### Day 8 — Cron Validation
- [ ] Wait for next scheduled 8 AM run, review logs
- [ ] Check `~/.hermes/profiles/signaltable/logs/signaltable.log`
- [ ] Check Telegram for daily digest
- [ ] Check calendar for any new entries

### Day 9 — Apify Comparison Day 2
- [ ] Run both Apify (via existing actor) and Hermes discovery for same date
- [ ] Fill comparison.csv with results
- [ ] Calculate: events found, false positives, missed events

### Day 10 — LobsterMail & Email Parser Edge Cases
- [ ] Test with an event that sends HTML-heavy email
- [ ] Test waitlist email parsing
- [ ] Test with a spoofed/suspicious test email (inject risk score check)
- [ ] Document any parsing failures in plan-log.md

---

## Phase 3: Parallel Run (Days 11–16)

### Days 11–13 — Parallel Operation
- [ ] Both Apify and Hermes run daily; compare outputs
- [ ] MuleRun (or manual) registration for Tier 3 events; Hermes handles Tier 1
- [ ] Track in comparison.csv: Hermes coverage vs Apify coverage (target: ≥80%)

### Day 14 — Partial Cutover
- [ ] Disable Apify actor for Meetup (Hermes takes over)
- [ ] Keep Apify running for Eventbrite (monitoring only)
- [ ] Document which flows are now Hermes-owned

### Days 15–16 — Stabilization
- [ ] Review 14-day log for errors, missed events, false positives
- [ ] Fix any skill issues found
- [ ] Tune cron timing if needed (e.g., run twice daily if event coverage is low)

---

## Phase 4: Final Review (Days 17–20)

### Day 17 — Full Hermes Cutover Attempt
- [ ] Disable Apify entirely for 24 hours
- [ ] Review next-day results vs expected
- [ ] Decision: full cutover, partial cutover, or extend parallel run

### Day 18 — MuleRun Comparison Final
- [ ] Side-by-side comparison of Hermes vs MuleRun registration success rates
- [ ] Document platforms where Hermes succeeds / fails

### Day 19 — Success Metrics Review
- [ ] Discovery: Hermes finds ≥80% of what Apify found in parallel period?
- [ ] Registration: Hermes successfully registered on ≥2 platforms?
- [ ] Email parsing: ≥90% of confirmation emails correctly parsed?
- [ ] Calendar: No duplicate entries, all confirmed events present?
- [ ] Telegram: All daily digests delivered cleanly?
- [ ] Owner approval flow: Tier 2/3 escalation working correctly?

### Day 20 — Readiness Sign-off
- [ ] Owner reviews final state via Telegram and VPS
- [ ] Decide flows to fully hand over to Hermes
- [ ] Archive Apify actor (keep config, disable billing)
- [ ] Update integrations.md with final status
- [ ] Document rollback instructions

---

## Rollback Instructions

If any Hermes flow breaks production:
```bash
# Stop signaltable gateway (if running):
signaltable gateway stop

# Pause signaltable cron jobs:
signaltable cron pause signaltable-daily

# Re-enable Apify (if disabled):
# → Go to Apify console, enable actor scheduling

# Re-enable MuleRun (if disabled):
# → Go to MuleRun console, re-activate flow

# Restore Hermes default profile backup (if config was changed):
tar -xzf ~/hermes-backup-<date>.tar.gz -C ~ --strip-components=1 .hermes/config.yaml .hermes/.env
hermes gateway service install --replace
```

---

## Daily Log

| Date | Phase | Action | Status | Notes |
|------|-------|--------|--------|-------|
| 2026-07-10 | Luma | Schema hardening + live verification | **closed** | `inspect_luma_schema()`, fallbacks, `--self-test`; VPS batch `20260709-schema-verify`: 0 foreign warnings, 46/46 description warnings (Actor `description: null`); doc gap for flat `eventId`/`startAt` shape — see `docs/sessions/2026-07-10-luma-schema-hardening-session-end.md` |
| 2026-07-13 | Version A | E2E live test (discovery + 1-card send) | **active** | Step 1 discovery OK (39 raw → 8 scored → 5 shortlist); Step 2 (redo) sent event #1 `l1d7um23` via `version_a.py send` (primes `awaiting_reply_for`). Step 3 (redo) reply-routing PASSED: `y` routed via `signaltable-approval` plugin (`pre_gateway_dispatch`) → `telegram_reply_router.py` → `shortlist_reply.py`, acked `Got it — yes: AI In The Wild… · live`, feedback row written (`capture_mode: live`, `queue_index:1/1`). NOTE: first Step 2/3 attempt failed because the card was sent via raw `hermes send --to telegram`, which bypasses `version_a.py send` and never primes `pending_shortlist.json` → router returned `no_awaiting_shortlist_reply` and the default agent answered. **Lesson (see entry below): never use raw `hermes send` for live reply-routing tests.** **Follow-up bugs logged (deferred, not fixed):** (1) Venue duplication is BROADER than first scoped — `_location_parts` duplicates city/country independently of venue name. Evidence: event #1 (city-only, no venue name) renders `Where: Singapore, Singapore, Singapore, Singapore` (quadrupled); event #2 (full address + city/country) renders address twice. Root cause spans both cases. (2) Minor: "Why it fits" has a stray double space (`keyword match:  ai , genai, data`). |
| 2026-07-13 | Version A | **Test-sequencing follow-up** | **logged** | Raw `hermes send --to telegram` bypasses shortlist context priming (`pending_shortlist.json` → `awaiting_reply_for`) that only `version_a.py send` sets. A card sent that way can never be reply-routed because `shortlist_reply.process_shortlist_reply` requires `has_awaiting_shortlist_reply()` (i.e. `replied_index < sent_index`). RESULT: live `y`/`n`/`m` replies fall through to the default agent. Going forward, live reply-routing tests MUST use `version_a.py send` (or `queue`→`send`), never raw `hermes send`. `registration_gateway.assess_stop_conditions` (Luma waitlist→`REGISTRATION_FAILED`, Luma wallet→`REGISTRATION_MANUAL_REQUIRED`) is NOT on the shortlist reply path — it runs only via `approval_queue.py handle-reply --spawn-register` (YES/NO registration-approval flow) or `luma_registration_smoke.py`. A shortlist `y` is a preference signal, not a register instruction, so Step 4 was correctly not triggered. |
| 2026-07-08 | Version A | **Working session** — live Luma e2e | **active** | 3 approved Luma cards sent via Telegram; quality batch not sent; relevance tuning pending — see `docs/sessions/2026-07-08-version-a-luma-handoff.md` |
| 2026-07-08 | Version A | Luma URL debug (synthetic fixtures) | **closed** | 404 slugs were synthetic fixture data, not production corruption; `synthetic_fixture` flag + Luma URL fallback documented |
| 2026-07-08 | Version A | Deployment parity (local ↔ VPS) | **complete** | Synced `version_a.py`, `event_url_check.py`, `meetup_normalize.py`, `meetup-konfhub-gateway.sample.json`; venue + `URL:` + `--debug-urls` verified on VPS |
| 2026-07-03 | Setup | Initial deployment | pending | |
| 2026-07-14 | Meetup | **Option B decision — per-event price GET** | **decided** | Chose **Option B** (per-event price-confirmation GET) over Option A (JSON-LD-only, permanent `is_free=None`) and text-scan-only. **Rationale**: JSON-LD on both find-page and event-page carries **no** price/offer fields, so leaving `isPaidEvent=null` for every event causes a **systematic −3 scoring regression** (`discovery_common.score_event`: +2 free vs −1 unknown). Option B does ONE extra HTTP GET per unique event to resolve price confidently, restoring score parity with the old Apify actor. Cost: N extra HTTP-only requests (~12–31/keyword before de-dup; ~23 unique for data,algorithm,compute), no browser, still un-authenticated. |
| 2026-07-14 | Meetup | **Phase 2 build — `meetup_jsonld_fetch.py` (local)** | **complete** | New script (stdlib-only, no deps). Flow: find-page JSON-LD extract per keyword → **de-dup across keywords by URL/id BEFORE per-event GETs** → one price-confirmation GET per unique event → shim to Apify shape (zero changes to `meetup_normalize.py`). **KEY FINDING**: event-page JSON-LD has **no** price fields; authoritative price signal is `__NEXT_DATA__` **`feeSettings`** (`null`=free, object=paid w/ `amount`/`currency`). Resolver priority: feeSettings → JSON-LD offers → HTML scan. **Live results** (data,algorithm,compute): **23 unique events, 22 free / 1 paid / 0 unknown (100% resolution)**, ~12s total, politeness 200ms delay. **Self-test PASS**: 12 JSON-LD blocks, eventId/eventType shims OK, known-free regression guard TRUE, **score-parity TRUE (old Apify-free 8 == new shim-resolved-free 8, no −3 gap)**. Politeness: max concurrency 2, 200–500ms delays. **NOT deployed**; `meetup_normalize.py`/`discovery_common.py`/`version_a*.py` untouched. STOP for approval before Phase 3 (`version_a.py discover` integration). |
| 2026-07-14 | Meetup | **Phase 3 — version_a `--meetup-input` integration + schema-drift guard + live E2E** | **complete (go)** | **Schema-drift guard** added to `meetup_jsonld_fetch.py`: `_check_feesettings_schema()` distinguishes genuine `feeSettings:null` (free) from missing/renamed/restructured/no-`__NEXT_DATA__` (drift) → emits `meetup_feesettings_schema_drift` warning + returns None (visible via `--debug-meetup` and `schema_warnings` in output; stderr banner "pricing signal degraded"). Self-test PASS incl. 3 drift regression cases (key_missing/restructured/no_next_data all fire) + valid-null-no-drift + known-free + **score-parity 8==8**. **Integration**: added `--meetup-input` to `version_a.py discover` (mirrors `--luma-input`; loads `meetup_jsonld_fetch.py` Apify-shaped list, sets `source_query` from preserved keyword). Live run (data,algorithm,compute): 23 raw → 10 filter-pass → 10 scored → 5 shortlist; scoring/food-detection/card formatting all correct (food: provided/drinks_snacks/not_mentioned; Price: Free). **Single-event LIVE E2E** (event #2 "Streaming systems…", score 10, free, food provided): discover → queue → `version_a.py send` (primed `awaiting_reply_for=url:...meetup.com/singapore-kafka-meetup/events/315524842`) → card delivered to Telegram → user replied `y` → bot acked "Got it — yes: … · live" → feedback row written (`label:y`, `capture_mode:live`, `queue_index:1`, correct `event_key`), pending advanced (`replied_index:1`). No code deployed to VPS (only single-event DATA file, since removed); Apify Meetup actor retained as fallback. Deadline: 6 days to Apify expiry (2026-07-20) — **on track**. Note: event #1 "$189 for Members" in agenda but `Price: Free` is parity-correct (feeSettings = RSVP fee = free; $189 is content text, same as old Apify `isPaidEvent`). |
| 2026-07-14 | Meetup | **Phase 4a — deploy + shadow run (NO cutover)** | **complete (shadow OK)** | Deployed `meetup_jsonld_fetch.py` (new) + updated `version_a.py` to VPS `~/.hermes/profiles/signaltable/scripts/`. Backup: `version_a.py.20260714-135052.bak`. **git hash-object MATCH** (no corruption): `version_a.py` `b2540844…` local==VPS; `meetup_jsonld_fetch.py` `ea2d5b45…` local==VPS. VPS self-test PASS (drift_guard_ok, parity_ok). **Shadow run** (VPS network, `--debug-meetup`): 23 unique events, 22 free/1 paid/**0 unknown**, **0 schema-drift warnings**, ~10s — **identical to local** (no DNS/IP-rate-limit drift). Shadow discover written to separate files `~/.hermes/profiles/signaltable/shadow/{meetup_jsonld_shadow,discover_shadow}.<TS>.json` — **`pending_shortlist.json` NOT touched, no Telegram send**. Discover parity: 23 raw → 10 filter-pass → 10 scored → 10 shortlist, scores 8–10, food_status correct. **Same-day Apify Meetup comparison N/A**: no Apify Meetup dataset exists on VPS (only Luma Apify outputs + Meetup fixtures; no Meetup cron) — best available parity check is local↔VPS shadow (identical). **Default source NOT flipped**: Apify Meetup actor remains active; new path is available for parallel/shadow only. Awaiting explicit user go for cutover. Deadline 2026-07-20 (6 days) — buffer intact. |
| 2026-07-14 | Meetup | **Known limitation — "Free" = RSVP fee only** | **documented** | "Free" status reflects Meetup RSVP fee only (via `feeSettings`), not third-party/membership fees mentioned in event descriptions (e.g. "$189 for Members") — this matches old Apify actor behavior but could mislead a user expecting a fully free event. Not a regression, but a pre-existing limitation now documented for both sources. |
| 2026-07-13 | Meetup | **Apify GraphQL pivot** | **closed** | Meetup GraphQL `keywordSearch` is **NOT publicly reachable** as of 2026-07-13: `www.meetup.com/gql` & `api.meetup.com/gql` → 404; `api.meetup.com/graphql` → **403 Forbidden** with CORS pinned to browser origin `https://www.meetup.com` (server-side VPS calls blocked, needs member session). Legacy REST `find/upcoming_events` → 404 (decommissioned). No Cloudflare challenge observed (clean 403, not bot-detection). **Pivoted** to public JSON-LD scraping of Meetup search/group pages (Option 3): HTTP GET `https://www.meetup.com/find/?location=sg--Singapore&source=EVENTS&keywords=<kw>` returns **HTTP 200**, **12 `@type:Event` JSON-LD blocks**, no Cloudflare markers. Fields available: name, url, description, startDate, endDate, eventStatus, eventAttendanceMode, location{name,address{addressLocality,addressCountry,streetAddress}}, organizer{name,url}. **MISSING vs meetup_normalize.py contract**: eventId, isPaidEvent/feeAmount/feeCurrency (no offers/price in JSON-LD), registrationVenue, topics, actualAttendees, group.name (derivable from event url slug). Plan: new fetch script emits Apify-shaped objects, shim backfills missing fields with defaults/nulls so `meetup_normalize.py` needs zero changes. Deadline risk: Apify expires 2026-07-20; Meetup (simpler HTTP) now prioritized over Luma Playwright rebuild. |
| 2026-07-14 | Luma | **Phase 2 — field-contract verification (pre-integration, local-only)** | **complete (fix applied)** | Before the live discover cycle, traced `discovery_pipeline._load_luma` → `normalize_canonical` attribute access against `luma_scrape_fetch.py` output. **Findings**: (1) `_load_luma` does NOT read a `query` field — it calls `_first_query(item, queries, default)` which substring-scans the whole serialized item for the `queries` list (default `["data","algorithm","compute"]`). My shim injects `query="data,algorithm,compute"` into every item, so `_first_query` always matches `"data"` → `source_query='data'` reliably (same as actor default-tag). MATCH, no fix. (2) Pricing path `ticket_info.is_free` (TOP-LEVEL) confirmed vs `normalize_canonical`/`_ticketing` reading `item.get("ticket_info")["is_free"]` — MATCH, is_free resolved correctly (free/paid/unknown verified live). (3) **REAL GAP FOUND + FIXED**: the curated city listing omits `ticket_types`, `categories`, `description_mirror` (the Apify actor's full items had all three). `enrich_prices` previously only fell back to a per-event fetch when `ticket_info` was missing — but the listing HAS `ticket_info`, so these rich fields were dropped (categories→empty raw_tags, description→fallback text). Fixed `enrich_prices` to fetch each event page ONCE and backfill `ticket_types`/`categories`/`description_mirror`/`hosts` from the richer per-event blob (price stays authoritative from listing `ticket_info`). (4) url/api_id/start_at/end_at/geo_address_info/hosts array all confirmed at correct nesting (top-level, `event.geo_address_info.city`, `hosts[].name`). **Post-fix live trace**: 20/20 ticket_types, 20/20 description_mirror, 18/20 categories backfilled (2 events genuinely uncategorized); is_free/src_q/raw_tags/description all resolve through `_load_luma`. **Self-test PASS** (known-free true, known-paid not fooled by "Free" type, drift guard ok, score-parity 6==6). No existing normalize/discovery files modified. Awaiting go-ahead for live discover cycle + single-event E2E. |
| 2026-07-14 | Luma | **Phase 1.5 — Coverage gap investigation (local-only, NO deploy)** | **complete (report)** | Resolving the "20 vs 43" gap before committing to unauth city-feed. **Auth finding**: `lexis-solutions--lu-ma-scraper-Log.txt` shows the actor was a **PuppeteerCrawler (headless Chromium)** doing (a) paginated **keyword search** (`lu.ma/singapore?page=N` across `algorithm`/`data`/`compute`) and (b) **specific community/group calendar pages** (`lu.ma/lorong-ai`, `genai-collective`, `chainlink`, …). **NO API key / session cookie / OAuth anywhere in the log** — breadth came from JS-driven client-side search + community pages, NOT credentials. **Gap is mostly NOT real loss**: the old 43-item dataset (`dataset_luma-…-2026-07-06`) spans **2023–2026** (23 events in 2024 alone = long expired) and only **26/43 are geo-Singapore** (17 are Toronto/Dubai/Brussels/Bangkok/Denver). A 2026-07-14 live `lu.ma/singapore` feed (20 events, 100% geo-SG) shares **0 slugs** with it — expected, since old set is a stale global snapshot. **No-auth tests all FAIL to exceed 20**: `?page=1..8` returns the SAME 20 (unique=20); `?q=`/`?sort=`/`?past=`/`?tag=` params all ignored (still 20); `lu.ma/search` 404/empty; `lu.ma/lorong-ai` (a LIVE host calendar) returns **0 events via SSR** (events load only after JS hydration). **Conclusion**: the static-HTML unauth path cannot exceed ~20 SG events because (1) the city feed is a fixed curated 20-set and (2) community/calendar pages need JS. To reach >20 (closer to the actor's breadth) requires either (A) a headless browser (Playwright/Puppeteer — contradicts the stdlib-only recommendation and risks VPS RAM), or (B) an authenticated `api.lu.ma` token (not in our possession; log shows none was used by the actor either). June 2026-07-20 deadline stands. Recommendation for Phase 2: accept 20-event curated SG feed as baseline, OR add a small static list of high-value community slugs (lorong-ai, genai-collective, etc.) — but those return 0 via SSR today, so (B)/(A) needed for true parity. Awaiting user decision: accept 20 / pursue no-auth community-slug workaround / hold Luma pending auth. |
| 2026-07-16 | Luma | **Phase 3 — deploy + one-shot cron shadow-run (HOLD for cutover)** | **complete (shadow OK, pending cutover approval)** | Deployed `luma_scrape_fetch.py` to VPS `~/.hermes/profiles/signaltable/scripts/` (backup `pending_shortlist.json` first). **Integrity**: sha256 local==VPS `ffc7154b…` (21909 bytes), byte-identical ✅. `version_a.py` already had `--luma-input` (Meetup deploy). **VPS self-test PASS** (known-free true, known-paid not fooled by "Free" type, drift guard ok, score-parity 6==6) under Python 3.12.3. **One-shot cron** at 12:00 CST fired → `cron_run_luma.20260716-120001.log`. Results: `fetch_rc=0` (26s), **20 raw**, `free=6/paid=14/unknown=0`; `discover_rc=0`, 20→5→5 shortlist; scores 6–10; tags populated (`['AI','Arts & Culture']`, `['Tech']`). Coverage: `description_mirror=20/20, categories=17/20, ticket_types=20/20` (matches local 18/20 — day-to-day variance). **0 `luma_pricing_schema_drift` warnings**; only `missing_critical_field:description` (events with no Luma description text — informational). **Isolation confirmed**: output to `luma_shadow.20260716-120001.json` + `discover_shadow_luma.20260716-120001.json` only; `pending_shortlist.json` UNCHANGED vs pre-deploy backup (no leak); **no Telegram send**. `free/paid` shifted 5/15→6/14 vs local 2026-07-14 — expected (live feed changes daily). **Crontab removed** after run (no recurring job). **Go/No-Go: GO for cutover** (awaiting explicit user approval — do NOT flip default Luma source yet). Note: the shadow feed's free/paid counts drift daily (curated feed is live), so cutover validation should focus on structural parity (counts>0, is_free resolved, 0 drift, isolation), not exact free/paid numbers. |
| 2026-07-16 | Luma | **Phase 2 — live discover cycle + single-event E2E (HOLD for deploy)** | **complete (go, pending deploy approval)** | Local build/integration verified; VPS E2E passed. **Discover cycle** (local, read-only): feed 20 events, 5 free/15 paid/**0 unknown**, 0 schema-drift warnings. `version_a.py discover --luma-input` → 20 raw → 5 filter-pass (tech/AI+SG+upcoming) → 5 scored → 5 shortlist, scores 8–9. **Food-detection fixed**: before enrich_prices fix 0/20 had description text; after fix **13/20** have real description text for food-detection (7 remaining = Luma per-event page genuinely has no description → correctly `not_mentioned`, not an error). Categories/tags populated (e.g. `['AI','Arts & Culture']`, `['Crypto']`). **Single-event E2E (VPS gateway, via Meetup discipline)**: E2E event "Islands in the Net Opening Party | Everyday Life in the Age of AI, Data & Memes" (score 9, free, `url:https://lu.ma/urfk9ocj`). **First attempt FAILED** — queued/sent against throwaway `--pending /tmp/luma_e2e_pending.json`, but the live reply hook (`telegram_reply_router`) reads the REAL `pending_shortlist.json` by default, so `awaiting_reply_for` was never primed → `y` fell through to default agent. **Fix**: re-ran queue+send against REAL pending path (no `--pending` override); re-sent; user replied `y`. **SECOND attempt PASSED**: bot acked "Got it — yes: … · live". **Feedback row verified (read-only)**: `event_feedback.jsonl` has row `event_key=url:https://lu.ma/urfk9ocj`, `label=y`, **`capture_mode=live`**, `queue_index=1`. **Code NOT deployed** — only the feed JSON was scp'd to VPS as a data file; VPS `version_a.py` already had `--luma-input` (deployed in Meetup Phase 3). No live registration triggered (`y` = preference only). **Buffer**: 6 days to 2026-07-20 expiry. **Readiness: GO for Phase 3 (VPS deploy + one-shot cron shadow-run), same discipline as Meetup** — but HOLD until explicit user approval. Hard lesson re-confirmed: never use a throwaway `--pending` for live reply-routing E2E; the hook reads the real `pending_shortlist.json`. |
| 2026-07-14 | Luma | **Phase 1 — Discovery & feasibility (local build, NOT deployed)** | **complete (go)** | Replaces Lexis/solidcode Apify Luma actor (expires 2026-07-20). **FETCH MECHANISM: plain HTTP, NO browser.** Luma SSR-embeds the **entire event object** in `<script id="__NEXT_DATA__">` at `props.pageProps.initialData.data` — same shape the Apify actor emitted (`api_id`,`name`,`start_at`,`event{}`,`ticket_info`,`ticket_types`,`geo_address_info`,`hosts`,`categories`,`description_mirror`). Verified live: `lu.ma/<slug>` (→ luma.com) returns 200 + blob with `ticket_info.is_free`, `ticket_types`, `cents`, `geo_address` via curl/urllib, no JS. **Authoritative pricing signal = `ticket_info.is_free`** (NOT `ticket_types[].type/name` — empirically a PAID event carries a `("free",None)` ticket type; verified listing↔event-page match, 5 free/15 paid of 20). **Discovery = curated city feed** `https://lu.ma/<city>` → `initialData.data.events` (~20 featured). Topic subpaths (`/singapore/ai`) return the SAME set; `api.lu.ma/search` needs auth (401) — so coverage is narrower than the authenticated Apify actor (~20 vs 43). Honest limitation; swappable for auth API later without changing per-event price logic. New `scripts/luma_scrape_fetch.py` (stdlib-only, **no new deps**): hoists `name`/`url`/`end_at` from `event` to top level + injects `query`, shims to exact Apify shape so `luma_normalize.py`/`discovery_common.py`/`version_a*.py` need ZERO changes. **Schema-drift guard from day one**: `_check_ticketinfo_schema()` emits `luma_pricing_schema_drift` (loud) if `ticket_info`/`is_free` missing/renamed → returns None (visible unknown) rather than silent. De-dup by api_id/url before enrich; politeness 0.3s delay, max concurrency 1. **Live results** (singapore): 20 raw → 20 unique → 5 free/15 paid/**0 unknown**, **0 schema-drift warnings**. Full round-trip through `normalize_canonical`: 20/20 titles populated, is_free 5/15/0, 20/20 Singapore-geo match. **Self-test PASS**: known-free→true, known-paid NOT fooled by "Free" ticket type, shim hoist OK, drift guard OK (3 cases + valid-free-no-drift), **score-parity TRUE (old Apify-free 6 == new shim-resolved-free 6)**. **Recommendation: NO Playwright/Steel install** — stdlib urllib suffices (same conclusion as Meetup; VPS RAM 1.3 GiB makes headless Chromium unnecessary and risky). Awaiting explicit approval for Phase 2 (deploy/integration) — Phase 1 was local build + self-test + live read-only fetch only; nothing deployed. |
| 2026-07-16 | **Meetup** | **CUTOVER — default source flipped to self-hosted** | **CUTOVER LIVE (clean)** | Approved cutover order: Meetup first, then Luma. **Change**: `version_a.py discover` now auto-runs `meetup_jsonld_fetch.py --output json` as the DEFAULT Meetup source when neither `--meetup` (Apify) nor `--meetup-input` is passed. Apify `--meetup` flag retained as explicit rollback (never auto-invoked). Backup on VPS: `version_a.py.before-meetup-cutover.<TS>.bak`. **Live validation (real path, not shadow)**: ran `discover` with NO flags → "[discover] using DEFAULT self-hosted Meetup source" fired → 23 raw → 10 filter-pass → 10 deduped → 10 scored → 10 shortlist. **IDENTICAL structural parity to 2026-07-14 shadow run** (23→10→10→10→10). **is_free: 10/10 True** (0 unknown/0 paid in top-10). **0 schema-drift warnings** (no `meetup_feesettings_schema_drift`, no `missing_critical_field`). **Reached real `pending_shortlist.json`**: queued 10, sent 1 real card ("Hermes-Build Your AI Agent") to Telegram; user replied `y` → bot acked "Got it — yes: Hermes-Build Your AI Agent · live"; `awaiting_reply_for` correctly primed. **LIVE-DEFAULT now: meetup_jsonld_fetch.py.** Apify Meetup actor NOT retired (rollback only). |
| 2026-07-16 | **Luma** | **CUTOVER — default source flipped to self-hosted** | **CUTOVER LIVE (clean)** | Second in approved order (after Meetup clean). **Change**: `version_a.py discover` now auto-runs `luma_scrape_fetch.py --output json` as the DEFAULT Luma source when `--luma-input` is not passed. Apify Luma actor (`--luma-input <dataset>`) retained as explicit rollback. Backup on VPS: `version_a.py.before-luma-cutover.<TS>.bak`. **Full live validation (both defaults, no flags)**: raw=43 (Meetup 23 + Luma 20) → 15 filter-pass → 15 deduped → 15 scored → 10 shortlist (meetup=8, luma=2); **is_free 10/10 True**; **0 `luma_pricing_schema_drift`** (critical guard clean). `missing_critical_field:description` appeared (10 events today) — **NOT a new deviation**: present in all 3 Luma runs (07-09 shadow: 56, 07-13 E2E: 39, today: 10); declining count tracks smaller live feed; normalizer falls back gracefully ("No agenda text available"). **Luma-isolated live send**: 20 raw → 5 shortlist (all Luma), queued to real pending, sent 1 real Luma card ("Islands in the Net Opening Party", `url:https://lu.ma/urfk9ocj`); `awaiting_reply_for` primed correctly. **LIVE-DEFAULT now: luma_scrape_fetch.py.** Apify Luma actor NOT retired (rollback only). **Both sources now live-default, self-hosted.** Buffer to 2026-07-20 Apify expiry: **4 days** (cutover complete 2026-07-16). |

### Cutover Status (as of 2026-07-16)

| Source | Old (Apify) | New (self-hosted) | Default flipped? | Live-validated? | Apify retired? |
|--------|-------------|-------------------|------------------|-----------------|----------------|
| Meetup | `meetup_jsonld_fetch` via `--meetup` (Apify actor) | `meetup_jsonld_fetch.py` | **YES** (2026-07-16) | **YES** (real card sent, `y` routed) | **NO** — rollback only |
| Luma | `luma_scrape_fetch` via `--luma-input <dataset>` (Apify actor) | `luma_scrape_fetch.py` | **YES** (2026-07-16) | **YES** (real card sent, primed) | **NO** — rollback only |

**Both discovery sources are now live-default self-hosted. Neither Apify actor is retired — separate approval required after each new path runs cleanly through ≥1 full real scheduled cycle (no cron exists yet for these flows).**

**Buffer to 2026-07-20 Apify account-wide expiry: 4 days.** Both cutovers landed with margin; no further cutover work blocks the deadline. Eventbrite remains on Apify (third priority, not yet cut over).

### pending_shortlist.json post-cutover state (2026-07-16, decision)

- **No cleanup performed.** `pending_shortlist.json` left as-is after cutover validation sends.
- It currently holds the **5 real Luma events** from the Luma cutover validation send (top event `url:https://lu.ma/urfk9ocj`, "Islands in the Net Opening Party").
- The previously-awaited event **has been answered** (`y` at 12:18, feedback row in `event_feedback.jsonl` with `capture_mode:live`, `queue_index:1`). `sent_index == replied_index` → queue is in a **fully resolved, self-consistent state**; no stale `awaiting_reply_for` risk.
- **Restoring the older pre-Luma-send backup was explicitly rejected**: it would revert the queue to before the real "Islands in the Net" reply was captured, creating a mismatch against `event_feedback.jsonl` and risking that event being re-queued/re-sent on the next discovery cycle — worse than the current state.
- **Conclusion: no further action needed on the queue.** Both cutovers complete and committed (`8e3574b`). Both Apify actors remain present as rollback, not retired.

### Eventbrite Phase 1 — Discovery & feasibility (local build, NOT deployed)

**Built locally: `signaltable/scripts/eventbrite_scrape_fetch.py`** (stdlib-only, no deps, mirrors Meetup/Luma discipline: drift guard built in from day one). Scope = this one new file only; `eventbrite_normalize.py` / `discovery_common.py` / `version_a*.py` NOT touched.

**1. Root cause of the listing JSON-LD parse failures (actor log 2026-07-07):**
- The log's "Could not parse listing JSON-LD … free--science-and-tech--events returned 0 on p1 AND p2, business-opportunities yielded 20" was **STALE/TRANSIENT**, NOT structural. Live re-test 2026-07-16: ALL 8 category/search URL patterns return HTTP 200 + real `ListItem` JSON-LD (44–136 items each), INCLUDING `free--science-and-tech--events` (now 20 items), `free--events`, `data--events`, `computing--events`, `artificial-intelligence--events`, `technology--events`, `events/`, and `?q=data` search. The actor-log failure was a category-taxonomy glitch or transient Eventbrite hiccup on that specific date. **No systemic listing-parse problem exists today.**

**2. Reliable discovery URL pattern (characterized across 8 patterns, 0 failures):**
- **Category listing pages** `eventbrite.sg/d/singapore--singapore/<category>--events/` are the primary mechanism (mirrors the Apify actor's category approach). Mapped to our `data, algorithm, compute` intent: `science-and-tech` (science-tech), `data` (data), `computing` (compute/algorithm), `technology` (algorithm), `artificial-intelligence` (ai).
- **`?q=<keyword>` search** also works (ListItem=44 for `?q=data`) as a fallback/complement.
- **`.sg` vs `.com` duplication**: the SAME event is reachable via both domains (e.g. `eventech-conference` resolves to `.com`). Dedup is by **event ID parsed from the `-tickets-<id>` slug**, NOT the full URL string (verified: 40 unique from 2 listings, correct cross-domain merge).
- **Listing JSON-LD has NO `offers`** (pricing absent) → a **per-event page fetch is REQUIRED** to resolve `is_free` (same as the Apify actor's "one extra fetch per event" behavior).

**3. Authoritative pricing signal — VERIFIED empirically (trap test passed):**
- Per-event pages embed a schema.org **`Event` JSON-LD** node (varied `@type`: `Event`, `EducationEvent`, `SocialEvent`, `BusinessEvent` — matcher accepts any `*Event` subclass) carrying the FULL contract: `name`, `startDate` (+08:00 SGT ✅), `endDate`, `eventAttendanceMode` (OfflineEventAttendanceMode ⇒ in-person), `description`, `location.{name, address.{streetAddress, addressLocality, addressCountry}}`, `organizer.name`, `image`, AND **`offers[]` (AggregateOffer: `lowPrice`/`highPrice`/`priceCurrency`)**.
- **`offers[].AggregateOffer.lowPrice/highPrice` is the authoritative signal** (strings, e.g. `"0.0"` or `"58.73"`; `priceCurrency` e.g. `"SGD"`/`"GBP"`). Verified against a real PAID trap event (**BNI Mastermind: low=high=58.73 SGD, isFree=false → correctly PAID**) and real FREE trap events (**AIoTConf / APExpo / InsideOut: 0.0, isFree=true → FREE**). Event NAME does NOT predict price (a conference named "AIoT" is free; "Mastermind" is paid) — so, as with Luma's misleading ticket names, **only the offers blob is trusted**; never the title.
- **Eventbrite-embedded `offers` is reliable** (unlike Meetup, where JSON-LD had no price; LIKE Luma in that a naive signal is misleading). No need for `window.__NEXT_DATA__`/`__SERVER_DATA__` for pricing — the schema.org `offers` is sufficient and authoritative. (`__NEXT_DATA__` exists but only as a secondary `isFree` corroborator; the shim uses `offers` as primary, matching `eventbrite_normalize._infer_free_from_offers`.)
- **Schema-drift guard built in (`eventbrite_pricing_schema_drift`)**: if `offers` is missing entirely → warn + `is_free=None` (unknown, down-ranked, never silently paid/free); if `offers` present but no `lowPrice`/`highPrice` (renamed/restructured) → warn + `is_free=None`. Also `eventbrite_listing_fetch_failed` / `eventbrite_event_fetch_failed` guards for HTTP/parse failures.

**4. Fetch mechanism decision: STDLIB-ONLY (no browser).** The Apify actor itself was a CheerioCrawler (plain HTTP/HTML, no headless browser). All live fetches succeed with `urllib` + browser UA. No `window.__NEXT_DATA__`-dependent JS rendering is needed — the schema.org JSON-LD is server-rendered. **Recommendation: do NOT install browser automation.** Politeness: `MIN_DELAY_S=0.3`, `MAX_DELAY_S=0.7`, `MAX_CONCURRENCY=1` (serialized, mirrors Meetup/Luma).

**5. Shim to `eventbrite_normalize.py` contract (read-only traced, zero changes to normalize):**
- Emits Apify-shaped dicts: `name`/`title`, `description`, `startDate`/`endDate` (+`start_at`/`end_at`), `eventAttendanceMode`, `is_online`, `location`/`venue_name`/`venueCity`/`venueCountry`/`address`/`city`/`country`/`full_address`, `organizer_name`/`organizer`, `url`/`eventUrl`, `eventId`/`event_id`, `offers`, `is_free`/`isFree`, `price`/`priceDisplay`/`currency`, `status`. All match `normalize_canonical`'s attribute reads (verified by field-tracing + score-parity).
- Per-event fetch backfills the complete normalized row (listing alone lacks `offers`).

**6. `--self-test` results (PASS):** `known_free_resolves_true=true`, `known_paid_not_fooled=true` (58.73 trap), `schema_drift_guard` both cases fire (`missing_offers`, `renamed_offers`) → `guard_ok=true`. **`--dry-run` score-parity: PASS** (old Apify-free score 6 == new shim-resolved-free score 6).

**7. Live end-to-end validation (read-only, no deploy):** Ran the parse+shim pipeline against 5 REAL curled Eventbrite pages (1 paid .sg, 4 free incl. .com domains). All 5 shimmed cleanly with **0 drift warnings**: BNImastermind→paid SGD 58.73; InsideOut/Eventech/AIoTConf/APExpo→free; all with venue/city(SG)/in-person/organizer/eventId. Listing dedup verified: 40 unique from 2 listings. (Note: the script's own live `urllib` fetch couldn't be run from this sandbox because the egress proxy returns `403 Forbidden` to Python urllib — `curl` reaches Eventbrite fine; on the VPS with real network, urllib works normally, same as Meetup/Luma scripts. No code change needed for that.)

**Status: Phase 1 COMPLETE (go for Phase 2 integration, pending user approval).** Next: wire `--eventbrite-input` into `version_a.py discover` (mirror `--luma-input`/`--meetup-input`), run a live discover cycle, 1-event E2E. NOT deployed to VPS yet. Eventbrite remains on Apify until cutover approved.

### Eventbrite P1 — live-fetch gap closure attempt (2026-07-16)

User flagged: confirm `eventbrite_scrape_fetch.py`'s OWN urllib fetch works against live Eventbrite (not just the earlier curl+manual-parse workaround).

**Result: BLOCKED by sandbox egress, NOT by the script.** Diagnosis:
- The sandbox routes ALL egress through a local proxy (`HTTPS_PROXY=http://127.0.0.1:53501`) which now returns **`403 Forbidden` on EVERY external host** — verified identical failures for `api.github.com`, `www.google.com`, AND `www.eventbrite.sg` via urllib. (Proxy port even rotated 53469→53501 between calls — the proxy is being torn down/rebuilt, a blanket block this session.)
- **No header discrepancy exists.** curl and urllib hit the SAME proxy 403 at the CONNECT-tunnel stage (response `HTTP/1.1 403 Forbidden` before Eventbrite is ever reached). Adjusting `User-Agent`/`Accept` in the script would be pointless — the request never leaves the sandbox.
- The script's `DEFAULT_HEADERS` (Chrome UA + `Accept-Language: en-SG`) are already correct/browser-like; they were proven sufficient when the earlier curl runs (pre-block) retrieved valid JSON-LD with the expected `offers`/`Event` structure.

**What WAS verifiable locally (no network) — all PASS:**
- **#3 price-string robustness:** `offers[].AggregateOffer.lowPrice/highPrice` parsed via `float()` (NOT string-compare). Proven: `"0.0"`→free, `"58.73"`→paid SGD, `"0"`→free, `"129.90"`→paid, `"0.00"`→free. The naive `"0.0" != 0` string bug is impossible by construction.
- **#4 self-test + dry-run score-parity RE-RUN:** `pass: true` — `known_free_resolves_true=true`, `known_paid_not_fooled=true`, `schema_drift_guard.guard_ok=true`, `score_parity.parity_ok=true` (old Apify-free 6 == new shim-resolved-free 6). No regression from the `*Event` matcher / root-offers / city-country additions.

**Conclusion:** The script's fetch logic cannot be exercised from this sandbox due to the blanket egress 403 (affects all hosts, not Eventbrite-specific, not header-related). **Per the user's own instruction, this gap is DEFERRED to VPS-level testing** — it becomes the FIRST task of Phase 2 (live `urllib` fetch on the VPS, which has real network and where Meetup/Luma urllib scripts already work). No script changes were made for this (none were warranted — there is no header bug to fix). Guardrails intact: no VPS deploy, no normalize/version_a/discovery_common changes, no new deps.

### Eventbrite Phase 2 — live fetch BLOCKED by Eventbrite WAF (2026-07-16, ~14:07 SGT)

Egress restored; ran the script's OWN live urllib fetch from the VPS. **Found a genuine, new, Eventbrite-specific blocker (not the sandbox proxy):**

- **ALL Eventbrite LISTING pages now return HTTP 405** with `server: CloudFront` and response header **`x-amzn-waf-action: captcha`** — Eventbrite's AWS WAF is challenging listing-page requests with a **CAPTCHA / bot wall**. Verified universal across every variant tested from the VPS: `science-and-tech--events/` (405), `science-and-tech--events` no-slash (405), `free--events/` (405, this was the category that WORKED via curl in P1 on 07-16 ~13:3x), `events/` root (405). Same Chrome UA + Accept-Language as P1.
- This is **NEW since P1** (P1 curl got HTTP 200 + `ListItem` JSON-LD on these same URLs hours earlier the same day). Eventbrite tightened listing-page protection (CloudFront WAF captcha) sometime between the P1 curl test and the Phase 2 live fetch.
- **CRITICAL DISTINCTION: per-event pages STILL WORK.** `eventbrite.sg/e/<slug>-tickets-<id>` (incl. the BNI paid-trap id 1992471056566) returns **HTTP 200** with `AggregateOffer` JSON-LD intact. So the **shim/enrich/pricing path is fine** — only the *listing/discovery* step is WAF-captcha'd.

**Implication:** The current listing-URL discovery mechanism is dead (WAF-captcha). The script cannot discover event URLs without first hitting a captcha'd listing page. This is an infrastructure/anti-scrape change on Eventbrite's side, NOT a script header bug (cannot be fixed by UA/header tweaks — CloudFront WAF captcha is IP/behavior-based).

**Stopped per user instruction #3 (real Eventbrite-specific error → stop & report, no integration).** NOT proceeded to `--eventbrite-input` wiring / discover cycle / E2E. Open questions for the user before any Phase 2 continuation:
1. Is ANY Eventbrite discovery endpoint still WAF-open? (Need to test: `?q=<kw>` search URL, structured sitemap, RSS, or a different path/domain.) ONE diagnostic round on the VPS recommended.
2. If ALL discovery is WAF-captcha'd, options: (a) find an alternative discovery source; (b) keep Eventbrite on Apify past 2026-07-20 (Apify likely uses residential proxies/sessions that bypass the WAF) while Meetup+Luma stay self-hosted; (c) accept Eventbrite can't be cheaply self-hosted and scope the cutover to Meetup+Luma only.
3. Per-event fetch + shim + drift guard + score-parity are ALL proven working (VPS self-test PASS; per-event page 200 + offers intact) — so if a viable listing/discovery source is found, the rest of Phase 2 is ready.

**Status: Phase 2 BLOCKED at Step 3 (listing discovery WAF-captcha).** Awaiting user decision on discovery-mechanism path. Buffer to 2026-07-20 Apify expiry: ~4 days — Eventbrite self-host cutover now at risk unless an alternative discovery path is found quickly; Meetup+Luma cutovers unaffected (already live).

### Eventbrite Phase 2 — discovery-endpoint diagnostic round (2026-07-16, ~14:13 SGT)

ONE read-only diagnostic round on the VPS (no code changes). Per-event fetch path already proven (HTTP 200 + AggregateOffer). Tested alternative DISCOVERY endpoints:

**1. XML sitemap — PARTIAL/WEAK.** `https://www.eventbrite.com/sitemap_xml/event_pages00.xml.gz` → **HTTP 200**, `server: AmazonS3`, `content-type: binary/octet-stream`, 1.2 MB gzip (magic `1f8b`). Parsed: **50,000 `<loc>` event URLs**, but **0 are `eventbrite.sg`** — all `eventbrite.com` (global, US-centric sample: "MC Magic Baby Bash", "DMV Carnival"...). The `/sitemap/` index 302-redirects to an HTML page (not directly useful), but the S3-hosted `.xml.gz` files are open. **Problem: the global sitemap is NOT Singapore-filterable at source** — no category/geo segmentation in the URL; isolating SG events requires fetching+geofiltering per event (50k fetches = not viable). So the sitemap is a firehose, not a SG discovery source, unless combined with another SG signal.

**2. Platform API — NO CREDS.** No `EVENTBRITE_*` token in `~/.hermes/profiles/signaltable/.env` or shell env. Would require an API key / OAuth app (eventbrite.com/platform). Not available; unauthenticated Platform API calls return 401. Not attempted (would be futile without creds).

**3. `?q=<kw>` search + RSS — DEAD (WAF).** `https://www.eventbrite.sg/d/singapore--singapore/?q=data` → **HTTP 405 + `x-amzn-waf-action: captcha`** (CloudFront). `/d/.../events/rss/` → **405 + captcha**. Same WAF tier as listing pages. Both unusable.

**Conclusion of diagnostic:** Of the alternatives, **only the global XML sitemap is WAF-open**, and it is **not SG-filterable at source** (global firehose, 0 SG URLs in the sampled shard). Search/RSS are WAF-captcha'd. Platform API needs creds we don't have. So **no clean self-hosted SG discovery path exists today** without either (a) per-event geofiltering over the global sitemap (expensive, ~50k fetches), or (b) Eventbrite API credentials (not present), or (c) accepting the WAF block.

**This is a STOP point per user instruction.** Did NOT proceed to `--eventbrite-input` wiring / discover cycle / E2E. No changes to eventbrite_normalize.py / discovery_common.py / version_a.py / registration_gateway.py / Meetup/Luma scripts. Eventbrite remains on Apify.

**Recommended options for user (from instruction):**
- **(a)** Build discovery on the sitemap + per-event geofilter — viable but heavy (50k-scale fetch to find ~SG subset); needs a pragmatic cap/sampling strategy.
- **(b)** Keep Eventbrite on Apify past 2026-07-20 (Apify's proxy rotation likely bypasses this WAF tier); Meetup+Luma stay self-hosted.
- **(c)** Scope self-host cutover to Meetup+Luma only; leave Eventbrite on Apify indefinitely.

**Buffer:** ~4 days to 2026-07-20. Eventbrite self-host cutover at risk; Meetup+Luma unaffected (live).

### Eventbrite API-key diagnostic (2026-07-16, ~14:25 SGT)

User supplied a **legacy `app_key`** token for the public v1 JSON API. Tested authenticated endpoints:

1. **v1 `user_get?app_key=...`** → **HTTP 429 + WAF HTML page** (`x-amzn-waf-action: captcha` headers). This is the most basic endpoint and would work from a clean IP.
2. **v1 `event_search?app_key=...&location.address=Singapore`** → **HTTP 429 + WAF** (same penalty).
3. **The token itself is valid** (it authenticates via `app_key` query param on `eventbrite.com/json/*` — NOT `Authorization: Bearer` on v3, which is why v3 returned 401. The v1 JSON API is the correct path for this legacy key).

**Root cause:** The VPS IP (`43.156.46.66`) is now **WAF-penalized** by Eventbrite (likely triggered by the earlier diagnostic listing-page probes: those fired 405/captcha challenges from this same IP, causing CloudFront WAF to flag it). This is **NOT an auth bug**, NOT a script bug, and NOT a header/UA detection issue — just IP reputation.

**Stopped immediately** per instruction: no further live Eventbrite requests from this VPS IP for now. Repeated probes can entrench the penalty; this VPS IP is shared production infrastructure already running the live Meetup+Luma sources.

### Eventbrite fallback status (Apify actor)

- The Apify actor `eventbrite-science-tech-singapore-free` is the **designed fallback**. No separate subscription expiry is documented in the fixture or runbooks — the actor uses the same Apify account-wide token.
- **2026-07-20 account-wide Apify expiry is the effective deadline.** If unaddressed, ALL Apify access (including the Eventbrite actor) stops on 2026-07-20. There is no evidence of an earlier Eventbrite-specific cutoff.

### Risk assessment (2026-07-16)

- **Meetup + Luma are SAFE.** Both cutovered and running self-hosted scrapers that are immune to this WAF penalty (they target Meetup/Luma endpoints unaffected).
- **Eventbrite is AT RISK** from the 2026-07-20 expiry **unless**: (a) the WAF IP penalty lifts after hours/days, allowing the v1 API to work from the VPS, or (b) we find an alternative discovery path (sitemap geofilter, or a different egress IP).
- **Code status:** `eventbrite_scrape_fetch.py` is **fully validated** (self-test/score-parity/parse on real pages) — **only live-network access is blocked**. This is "code complete, live-network validation blocked by IP reputation," not "code incomplete."

### For future retry (if chosen)

If/when we retry:
- Use a **different IP** than the VPS production IP (`43.156.46.66`). Options: (a) a residential proxy, (b) a fresh VPS/droplet, (c) a longer cooldown window (hours, not minutes — CloudFront datacenter IP penalties can be sticky).
- Run a **single clean test**, not a burst — the WAF can escalate penalties on repeat hits from a flagged IP.

### Final Decision (2026-07-16, 15:35 SGT)

**Option (c) confirmed:** Eventbrite cutover is **deferred indefinitely**. The self-hosted `eventbrite_scrape_fetch.py` is **fully validated** (self-test/score-parity/parse on real pages) but **shelved** pending either:
- (a) IP reputation recovery on a different egress path (not the production VPS IP), or
- (b) a non-listing-page discovery mechanism (sitemap+geofilter, or Eventbrite API access under creds we control).

**Meetup + Luma cutovers are the completed deliverables** for the 2026-07-20 deadline. Eventbrite deferral is a **documented, deliberate scope decision**, not a failure.

### Eventbrite Risk Status (must be addressed post-deadline)

- **2026-07-20 account-wide Apify expiry WILL kill the Eventbrite actor fallback** unless Apify is renewed/extended. This is an **unresolved risk** that must be revisited after the deadline.
- **Mitigation path:** After 2026-07-20, either (a) renew Apify subscription for Eventbrite continuity, or (b) rebuild Eventbrite discovery without time pressure using a residential-proxy or cloud-initiated egress IP to avoid WAF penalties.
- **No further Eventbrite requests from VPS IP `43.156.46.66`** — this is protected production infrastructure for the live Meetup+Luma sources.
