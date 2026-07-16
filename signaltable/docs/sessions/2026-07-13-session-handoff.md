# SignalTable Session Handoff — 2026-07-13

**Scope of this session:** (1) Luma E2E reply-routing test fix, (2) architecture doc consolidation, (3) Apify-replacement planning for Luma + Meetup fetch layers ahead of the **2026-07-20 Apify expiry**.

**VPS:** `ubuntu@43.156.46.66` (Tencent Cloud Singapore). Profile `~/.hermes/profiles/signaltable/`. Node v22.23.0, npm 10.9.8. RAM 1.9 GiB (1.3 GiB avail), 2 CPU cores. No global playwright/puppeteer/crawlee.

---

## 1. Luma Version A E2E test — COMPLETED (Steps 2 & 3)

### What happened
- Step 2 first attempt FAILED: card for event #1 (`https://lu.ma/l1d7um23`, "AI In The Wild…") was sent via **raw `hermes send --to telegram`**, which does NOT prime `pending_shortlist.json`. The `y` reply fell through to the default agent ("Hey KM! What can I help you with today?").
- Root cause proven: `telegram_reply_router` → `shortlist_reply.process_shortlist_reply` requires `has_awaiting_shortlist_reply()` = `replied_index < sent_index`. Raw send leaves `awaiting_reply_for` pointing at the old meetup event.
- **Fix (redo):** queued ONLY event #1 into `pending_shortlist.json` (backup `pending_shortlist.json.bak-20260713T143112` retained), then `python3 scripts/version_a.py send --to telegram`. This set `awaiting_reply_for: url:https://lu.ma/l1d7um23`.
- Step 3 PASSED: user replied `y` → bot acked `Got it — yes: AI In The Wild… · live`. Confirmed path: `signaltable-approval` plugin (`pre_gateway_dispatch`) → `telegram_reply_router.route_telegram_reply` → `shortlist_reply.process_shortlist_reply` → wrote `event_feedback.jsonl` (`capture_mode: live`, `queue_index:1/1`), advanced `replied_index`→1.

### registration_gateway.py finding (Step 3.3)
- Shortlist `y/n/m` is a **preference signal ONLY** — does NOT call `registration_gateway.py`. That module is reached only via `approval_queue.py handle-reply --spawn-register` (YES/NO) or `luma_registration_smoke.py`.
- `assess_stop_conditions` Luma checks verified in isolation (read-only `assess`): waitlist→`REGISTRATION_FAILED`; wallet_required→`REGISTRATION_MANUAL_REQUIRED`. Correct, just not on the shortlist path.
- Step 4 (real registration) was NOT executed — correct, needs separate approval.

### Safety note
No gateway restart, no nightdesk/allowlist/config change, no code modification. Only `pending_shortlist.json` data set (with backup).

---

## 2. Architecture doc consolidation — COMPLETED

- Consolidated into single canonical file: `signaltable/docs/architecture.md` (264 lines).
- Preserved PortEden historical root-cause as §0; added 6 confirmed sections (high-level, data flow, model config, deployment state A–F, known follow-ups, safety practices).
- Deployment table maps letters→real commits: A `90bd28b` (Luma schema hardening), B `b45317b` (y/n/m + YES/NO routing), C `ad01445` (food + Meetup venue precedence + URL/card), D `d188f11` (LobsterMail Luma polling), E `cdd9d0a` (Meetup KonfHub fixture), F `c7a0b88` (docs/fixtures). Verification standard = `git hash-object` vs `origin/main`.
- Other docs are operational runbooks, NOT superseded (version-a-runbook.md, e2e-smoke-test-runbook.md, registration-gateway-runbook.md, calendar-write-runbook.md, luma-registration-smoke-runbook.md, event-discovery-runbook.md, luma-apify-schema.md, integrations.md, hermes-vps-access-brief.md).
- A `plan-log.md` entry was also added noting the raw-`hermes send` test-sequencing lesson.

---

## 3. Apify replacement — Luma fetch layer (Crawlee/Playwright)

### Phase 1 (analysis) — COMPLETE, GO
- Evidence read: `lexis-solutions--lu-ma-scraper-Log.txt` (actor log) + `dataset_luma-singapore-data-search_2026-07-06_11-01-44-114.json` (43 real items, 73 fields).
- Actor: **PuppeteerCrawler** (headless Chromium), Crawlee 3.13.2, apify 3.4.0, Node 20. Workflow: 3 keyword streams (`algorithm,data,compute`) → paginate `lu.ma/singapore` search → collect slugs → visit each `lu.ma/<slug>` → stop at "Max results have been reached". 77 requests, 0 fail, ~55s, ~83 req/min.
- **KEY:** the dataset is ALREADY the exact shape `luma_normalize.py` expects. Ran normalizer over all 43: 43/43 parse with NO schema-drift warnings; 19/43 pass all critical-field checks; 24/43 emit `missing_critical_field:description` (because `description_mirror` is a ProseMirror doc with no `.text` — `_summary()` can't read it; same as live Apify today). **Zero-change to `luma_normalize.py` is achievable** if new scraper emits the same field names/nesting/types.
- Pre-existing bug surfaced (OUT OF SCOPE, do not fix): `ticket_info.is_free=False` with `price.cents=2900` → `price_text` = raw dict repr `{'cents': 2900, ...}` instead of "USD 29.00" (in `luma_normalize._infer_luma_free`). New scraper just preserves `ticket_info.price.cents`; fix later if desired.
- **VPS resource concern (flagged):** 1.3 GiB RAM, 2 cores. Headless Chromium needs 300–600 MiB/process. Recommend `maxConcurrency` 1–2, no xvfb, Playwright (preferred) OR Puppeteer (lighter, matches actor) if VPS libs fail.
- Awaiting user decision on crawler flavor (Playwright vs Puppeteer) before Phase 2 build. **Phase 2 not started.**

---

## 4. Apify replacement — Meetup fetch layer (JSON-LD scrape) — ACTIVE, Phase 1 GO

### GraphQL path ABANDONED (confirmed 2026-07-13)
- `www.meetup.com/gql`, `api.meetup.com/gql` → 404. `api.meetup.com/graphql` → **403 Forbidden** (CORS pins browser origin `https://www.meetup.com`; server-side blocked, needs member session). Legacy REST `find/upcoming_events` → 404. No Cloudflare challenge (clean 403 = auth gate, harder than rate-limit).
- Recorded in `plan-log.md`.

### Option 3 adopted: public JSON-LD scraping (HTTP-only, no auth, no browser) — Phase 1 GO
- Probe: `GET https://www.meetup.com/find/?location=sg--Singapore&source=EVENTS&keywords=data` → **HTTP 200**, **12 `@type:Event` JSON-LD blocks**, no Cloudflare markers.
- Available fields: `name, url, description, startDate, endDate, eventStatus, eventAttendanceMode, location{name, address{addressLocality, addressCountry, streetAddress}}, organizer{name,url}`. 12 events across 11 groups (good SG tech coverage).
- MISSING vs `meetup_normalize.py` contract (backfill in shim, NOT in normalize): `eventId` (derive from URL slug), `isPaidEvent/feeAmount/feeCurrency` (no offers/price in JSON-LD → default null/"unknown"), `registrationVenue`, `topics`, `actualAttendees`, `group.name` (derive from URL slug).
- `endDate` often empty (normalize tolerates). `eventStatus`/`eventAttendanceMode` need light normalization.
- **Shim plan:** new fetch script emits Apify-shaped dicts → `meetup_normalize.normalize_canonical()` runs with ZERO changes.
- Plan-log entry added.

### Phase 2 NOT STARTED — awaiting go-ahead
Planned: `meetup_gql_fetch.py` (JSON-LD-based despite name) with keyword loop (`data,algorithm,compute`), find-page fetch + any pagination, per-event JSON-LD extraction, shim to Apify shape, `--self-test`/`--dry-run` validating against captured find-page HTML. Then Phase 3 (version_a.py `--meetup-input` wiring + one-event E2E) and Phase 4 (VPS deploy, keep Apify fallback until one real cycle passes).

---

## 5. Deadline tracking
- **Apify expires 2026-07-20** (7 days from session date). Both Luma + Meetup actors share this expiry.
- Meetup (HTTP JSON-LD) is the fast win and is unblocked — prioritize over Luma Playwright rebuild per user direction.
- Risk: Luma Phase 2-4 (local build + integration + VPS deploy + 1 real run) is multi-day; if Meetup ships first, Luma may need to slip or accept shorter validation.

---

## 6. Outstanding user decisions
1. **Luma crawler flavor:** Playwright (preferred, heavier deps) vs Puppeteer (lighter, matches actor). Needed before Luma Phase 2.
2. **Meetup Phase 2 go-ahead:** confirmed GO in principle; awaiting explicit "proceed" to write `meetup_gql_fetch.py`.

## 7. Guardrails reaffirmed (all tasks)
- Never touch nightdesk, Telegram allowlist, or gateway config.
- Never restart Telegram gateway without approval.
- Do not modify `registration_gateway.py`, `lobstermail_poll.py`, `discovery_common.py`, `food_detection.py`, `luma_normalize.py`, `eventbrite_normalize.py`, `version_a.py` (except the planned `--meetup-input` wiring in Meetup Phase 3, which is additive).
- Do not remove/disable Apify actor calls until new paths proven in a real scheduled cycle.
- Back up before overwriting VPS files; verify via `git hash-object` vs `origin/main`.
- Test high-risk changes one file at a time; one-event E2E discipline.

## 8. Key file paths
- `signaltable/docs/architecture.md` — canonical architecture (264 lines)
- `signaltable/docs/plan-log.md` — daily log + follow-ups
- `signaltable/scripts/luma_normalize.py` — Luma normalizer (DO NOT MODIFY; confirmed compatible with dataset shape)
- `signaltable/scripts/meetup_normalize.py` — Meetup normalizer (DO NOT MODIFY; shim lives in new fetch script)
- `signaltable/scripts/version_a.py` — discover/send/handle-reply (additive `--meetup-input` only)
- `signaltable/scripts/food_detection.py`, `discovery_common.py` — shared (DO NOT MODIFY)
- Evidence: `/Users/kmsum/Downloads/signalTable/lexis-solutions--lu-ma-scraper-Log.txt`, `/Users/kmsum/Downloads/signalTable/dataset_luma-singapore-data-search_2026-07-06_11-01-44-114.json`
- Captured Meetup find-page HTML (local, for Phase 2 self-test): `/tmp/meetup_find.html`
