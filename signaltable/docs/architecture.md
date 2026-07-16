# SignalTable — Architecture (Canonical Source of Truth)

**Status**: Last consolidated **2026-07-13** (post full live E2E test cycle).
**VPS**: `ubuntu@43.156.46.66` (Tencent Cloud Singapore, Ubuntu).
**Hermes profile**: `~/.hermes/profiles/signaltable/`.
**Supersedes**: prior `architecture.md` (2026-07-05 PortEden-removal draft) for architecture intent. Complementary runbooks (`version-a-runbook.md`, `e2e-smoke-test-runbook.md`, `registration-gateway-runbook.md`, `calendar-write-runbook.md`, `luma-registration-smoke-runbook.md`, `event-discovery-runbook.md`, `luma-apify-schema.md`, `integrations.md`) remain authoritative for step-by-step operations and are NOT replaced by this file.

> **Why this document exists**: future coding sessions should not need to re-derive architecture from chat history. Read this first.

---

## 0. Historical context — PortEden (dropped, keep for root-cause memory)

PortEden was originally chosen as a calendar proxy (`Hermes → porteden-calendar MCP → PortEden API → Google Calendar`). It was **dropped** because the Google OAuth grant used a device/TV flow (`GOOGLE_TV_APP`) that only requested `calendar.readonly` scope — a hard ceiling Google's OAuth grant enforces, so dashboard permission changes never took effect. Every write failed with `Access denied: the calendar provider denied the operation`.

**Decision (standing):** Google Calendar is written **directly** via `gcal.py` + a **service account** (`signaltable-gcal`), not through any proxy. The `porteden-calendar` MCP entry and `PE_API_KEY`/`PORTEDEN_CALENDAR_ID` are removed. The `/usr/local/bin/porteden` binary may still exist on the VPS but is unused and must not be reintroduced.

---

## 1. High-level architecture

```
Cron Scheduler (8AM SGT, future) / ad-hoc agent run
  └─ Hermes signaltable agent (qwen-turbo primary; fallbacks deepseek-v4-flash-202605 → glm-5.2)
       │
       ├─ Discovery
       │    ├─ apify_luma.py          (Luma — Apify actor, Crawlee under the hood; preferred, read-only)
       │    │     → luma_normalize.py
       │    ├─ meetup_normalize.py    (Meetup export)
       │    └─ eventbrite_normalize.py (Eventbrite export)
       │         → discovery_pipeline.py + discovery_common.py (filter → dedupe → score → food)
       │
       ├─ Card formatting
       │    └─ version_a.py format_event_card
       │         → version_a.py send  (PRIMES pending_shortlist.json — see §2)
       │              → signaltable_bot → Telegram → kmsum (user 1697120790)
       │
       ├─ Reply routing (Telegram y/n/m)
       │    └─ signaltable-approval plugin (pre_gateway_dispatch)
       │         → telegram_reply_router.py → shortlist_reply.py
       │              → event_feedback.jsonl (PREFERENCE SIGNAL ONLY — no registration)
       │
       ├─ Registration (separate path, YES/NO approval)
       │    └─ approval_queue.py handle-reply --spawn-register
       │         → registration_gateway.py (assess_stop_conditions: Luma waitlist/wallet checks)
       │              → LobsterMail confirmation poll
       │
       ├─ Confirmation
       │    └─ lobstermail_poll.py (Luma confirmation emails: LUMA_SENDER_DOMAINS, find_luma_confirmation, poll_luma_confirmation)
       │
       └─ Calendar write (gated)
            └─ gcal.py (service account signaltable-gcal) → "SignalTable Events" calendar → iPhone sync
```

### Key boundaries

- **Hermes on Tencent VPS**, isolated `signaltable` profile. This profile is **separate from the default profile and from `nightdesk`**. Neither the default profile nor `nightdesk` should be touched by signaltable changes.
- **No-PortEden design**: direct Google Calendar via `gcal.py` + service account, dedicated **"SignalTable Events"** calendar.
- **Event sources**: Luma (Apify actor; Crawlee-based scraping under the hood), Meetup, Eventbrite.
- **Telegram gateway** is the delivery + reply channel. `TELEGRAM_ALLOWED_USERS` allowlist (`1697120790`) is the **security boundary** — owner-only. Do not loosen.

---

## 2. Data flow (confirmed via live E2E test 2026-07-13)

### 2.1 Fetch
- **Luma**: `apify_luma.py` (Apify actor output, read-only). Raw events → Luma JSON.
- Meetup / Eventbrite: export JSON files.

### 2.2 Normalize → canonical schema
- `luma_normalize.py`, `meetup_normalize.py`, `eventbrite_normalize.py` → canonical event dict.
- **`event_page_url` precedence order**: `event_page_url` > `url` > `source_url` > `registration_url`.
  - **Meetup/KonfHub**: the **Meetup page URL wins** for `event_page_url`; the KonfHub URL stays **`registration_url` only** (it is a registration gateway, not the canonical page). `meetup_normalize.apply_meetup_venue_precedence()` ensures the Meetup `venue` populates `Where:` while an optional `registrationVenue` only populates `Registration venue:`.
  - **Card line uses `URL:`** (canonical `event_page_url`), **not** the legacy `Link:`.

### 2.3 Discovery pipeline → filter/dedupe/score/food
- `discovery_pipeline.py` + `discovery_common.py`: hard filters (Singapore, in-person, etc.) → dedupe → score (`version_a_scoring.py`).
- `food_detection.py` (`apply_food_status` / `food_score_delta`) adds `food_status` + `food_card_line`.

### 2.4 Card formatting
- `version_a.py format_event_card`:
  - **`URL:`** line (canonical, see §2.2).
  - **`Where:`** = primary venue; **`Registration venue:`** = separate line only when ticket/KonfHub venue differs.
  - Includes Platform / When / Price / Food / Agenda / Why it fits / Reply: y / n / m.

### 2.5 Send — **critical priming step**
- `version_a.py send`:
  - Sends the next queued card via `hermes send --to telegram`.
  - **Writes `pending_shortlist.json`** with:
    - `awaiting_reply_for` = `event_key`/`title` of the sent event,
    - `awaiting_reply_title`,
    - `sent_index` advanced.
  - **This priming is REQUIRED for reply routing to work.**
- ⚠️ **CONFIRMED BUG (2026-07-13):** sending via raw `hermes send --to telegram` (bypassing `version_a.py send`) does **NOT** prime `pending_shortlist.json` → `awaiting_reply_for`. The router then returns `no_awaiting_shortlist_reply` and the reply falls through to the default agent (the bot answers "Hey KM! What can I help you with today?" instead of routing). **Always use `version_a.py send` for any test that needs to exercise reply routing.**

### 2.6 Reply routing (Telegram y / n / m)
```
signaltable-approval plugin (pre_gateway_dispatch)
  → telegram_reply_router.route_telegram_reply(text, capture_mode=LIVE)
      → shortlist_reply.process_shortlist_reply(...)
          → writes event_feedback.jsonl
          → advances replied_index
          → sends live ack "Got it — <yes/no/maybe>: <title> · live"
```
- Matching requires `has_awaiting_shortlist_reply()` = `replied_index < sent_index`.
- **Confirmed live (2026-07-13):** event #1 (`l1d7um23`) `y` routed correctly end-to-end; ack returned; feedback row written with `capture_mode: live`, `queue_index: 1/1`.

### 2.7 Shortlist y/n/m is PREFERENCE ONLY
- A shortlist `y`/`n`/`m` is a **preference signal**. It does **NOT** call `registration_gateway.py` and does **NOT** trigger registration. (Distinct from the registration-approval `YES`/`NO` flow in §2.8.)

### 2.8 Registration path (separate from shortlist)
- Triggered by `approval_queue.py handle-reply --spawn-register` (when `pending_approvals.json` has items) for `YES`/`NO` registration approval, **or** by `luma_registration_smoke.py`.
- → `registration_gateway.py`:
  - `resolve_registration_target()` (platform + URLs),
  - `assess_stop_conditions(signals)`:
    - **Luma `waitlist: True`** → `REGISTRATION_FAILED` ("Luma waitlist is not confirmed registration").
    - **Luma `wallet_required: True`** → `REGISTRATION_MANUAL_REQUIRED` ("Luma wallet/token verification required").
    - konfhub custom fields / captcha → `REGISTRATION_MANUAL_REQUIRED`.
    - `submit_success` → `REGISTRATION_SUBMITTED` / `CONFIRMATION_PENDING`.
- These stop-condition checks are **verified working in isolation** (read-only `assess` on event #1 data, 2026-07-13); they simply are not on the shortlist `y` path.

### 2.9 Registration confirmation
- `lobstermail_poll.py` polls for Luma confirmation emails:
  - `LUMA_SENDER_DOMAINS`, `find_luma_confirmation`, `poll_luma_confirmation`.
  - Platform-agnostic `_poll_platform_confirmation` (konfhub or luma).
- Confirmation **unblocks the calendar write** (only write after confirmed).

### 2.10 Calendar write (gated)
- `gcal.py` (service account `signaltable-gcal`) → "SignalTable Events" calendar → iPhone sync.
- **Known pre-existing issue (needs separate follow-up):** `calendar_allows_confirmed` gating fails because of gcal credential / dry-run gating — **unrelated to registration logic**. Calendar write is therefore not yet production-verified end-to-end.

---

## 3. Model configuration

- **signaltable profile primary model**: `qwen-turbo` (`max_tokens: 8192`).
- **Fallbacks**: `deepseek-v4-flash-202605` → `glm-5.2`.
- **Default profile and `nightdesk` profile are separate** and must not be touched by signaltable changes.
- **Discovery/scoring pipeline is deterministic and model-independent** — the CLI scripts (`version_a.py discover`, `luma_normalize.py`, `discovery_common.py`, `version_a_scoring.py`, etc.) make **no LLM calls**. The LLM is only in the interactive agent / gateway layer (conversational replies, skill orchestration). This is why scoring/parity can be validated purely via `--self-test` and CLI runs.

---

## 4. Deployment state (as of 2026-07-13)

### 4.1 Deployed & hash-matched on VPS
Verification method: **`git hash-object` comparison of each file against `origin/main` blobs** (not assumption from prior parity notes). This is now the **standard practice** — always hash-compare before/after deploy.

| Letter | Commit | What it delivers |
|--------|--------|------------------|
| A | `90bd28b` | Harden Luma Apify normalization against schema drift (`luma_normalize.py`: `inspect_luma_schema`, fallback chains, loud warnings) |
| B | `b45317b` | Route Telegram y/n/m (Version A) + YES/NO (registration) — `telegram_reply_router.py`, `shortlist_reply.py`, `approval_dispatch.py`, `approval_reply.sh`, `signaltable-approval` plugin |
| C | `ad01445` | Food detection (`food_detection.py`) + Meetup venue precedence + URL/card fields |
| D | `d188f11` | Luma confirmation polling in LobsterMail (`lobstermail_poll.py`) + `luma_registration_smoke.py` |
| E | `cdd9d0a` | Meetup KonfHub fixture fix: Monk's Brew Club as primary venue |
| F | `c7a0b88` | SignalTable docs, session handoffs, regression fixtures |

> Note: the gateway plugin `signaltable-approval` is loaded by Hermes only from `~/.hermes/plugins/signaltable-approval/` (user-plugin dir), **not** from `~/.hermes/profiles/signaltable/plugins/`. Both copies are present on VPS and hash-match `origin/main`. Config `hooks: {}` in `config.yaml` is expected — hooks are registered via the plugin, not the `hooks:` key.

### 4.2 Verification standard (carry forward)
- Before deploy: `git hash-object <file>` locally vs VPS; compare to `git show origin/main:<path>` hash.
- After deploy: re-hash VPS file; confirm equality.
- This replaces any "parity assumed from notes" approach.

---

## 5. Known follow-ups (NOT yet fixed — logged for future work)

1. **Venue duplication bug** (`_location_parts` / `format_event_card`):
   - Occurs **both** when `full_address` already contains city/country (event #2 Sands Expo case: address rendered twice) **and** when there is **no venue name and location is city-only** (event #1 case: `Where: Singapore, Singapore, Singapore, Singapore` — quadrupled).
   - Broader than first estimated; needs a proper fix, not just a note.
2. **"Why it fits" stray double-space**: e.g. `keyword match:  ai , genai, data` (double space after colon). Cosmetic but visible on cards.
3. **`calendar_allows_confirmed` pre-existing failure**: tied to gcal credential / dry-run gating. Unblocks nothing until fixed; separate from registration logic.
4. **Test-sequencing lesson (2026-07-13)**: always use `version_a.py send` (not raw `hermes send`) for any test exercising reply routing — raw send does not prime `pending_shortlist.json`'s `awaiting_reply_for`.

---

## 6. Safety practices (established, carry forward)

- **Back up before overwriting on VPS**: timestamped `.bak` (e.g. `pending_shortlist.json.bak-20260713T143112`).
- **Verify via `git hash-object` before and after any deploy**; compare to `origin/main`.
- **Never touch `nightdesk`, Telegram allowlist, or gateway config** unless explicitly asked.
- **Never restart the gateway** without explicit approval.
- **Never commit `signaltable.env` or any file with real tokens/secrets.**
- **Test high-risk changes one file at a time** with `--self-test` verification; stop between steps for approval.
- **For live E2E tests: one event end-to-end** (discovery → card → reply → registration → confirmation), not a full sweep, to isolate failures precisely.

---

## 7. File map (local workspace)

```
/Users/kmsum/Downloads/signalTable/
├── signaltable.env                 # copy of VPS .env (live keys — DO NOT COMMIT)
└── signaltable/
    ├── SOUL.md
    ├── config-overlay.yaml
    ├── env-template.env
    ├── docs/
    │   ├── architecture.md         # THIS FILE (canonical)
    │   ├── plan-log.md             # 20-day transition plan + daily log
    │   ├── version-a-runbook.md    # Version A E2E operational runbook
    │   ├── e2e-smoke-test-runbook.md
    │   ├── registration-gateway-runbook.md
    │   ├── calendar-write-runbook.md
    │   ├── luma-registration-smoke-runbook.md
    │   ├── event-discovery-runbook.md
    │   ├── luma-apify-schema.md    # Luma schema assumptions + warning behavior
    │   ├── integrations.md
    │   └── hermes-vps-access-brief.md  # NightDesk reuse brief
    ├── scripts/
    │   ├── apify_luma.py
    │   ├── luma_normalize.py        # A: schema hardening
    │   ├── meetup_normalize.py      # C: venue precedence
    │   ├── eventbrite_normalize.py  # URL/card fields
    │   ├── discovery_pipeline.py
    │   ├── discovery_common.py      # filter/dedupe/merge + venue fields
    │   ├── version_a.py             # discover/queue/send/handle-reply/live-test
    │   ├── version_a_scoring.py
    │   ├── food_detection.py        # C
    │   ├── event_url_check.py
    │   ├── feedback_store.py        # y/n/m JSONL + pending queue
    │   ├── telegram_reply_router.py # B
    │   ├── shortlist_reply.py       # B
    │   ├── reply_capture.py         # B
    │   ├── approval_queue.py        # YES/NO registration approval
    │   ├── registration_gateway.py  # assess_stop_conditions (waitlist/wallet)
    │   ├── lobstermail_poll.py      # D: Luma confirmation polling
    │   ├── luma_registration_smoke.py # D
    │   └── gcal.py                  # direct Google Calendar (service account)
    ├── hooks/
    │   ├── approval_dispatch.py     # B: pre_gateway_dispatch hook
    │   └── approval_reply.sh        # B
    ├── plugins/signaltable-approval/
    │   ├── __init__.py             # B: pre_gateway_dispatch plugin (loaded from ~/.hermes/plugins)
    │   └── plugin.yaml
    └── fixtures/...                 # regression fixtures (E: meetup-konfhub-gateway.sample.json)
```

---

## 8. Rollback / recovery

```bash
# Pause cron (if active)
signaltable cron pause signaltable-daily

# Stop signaltable gateway (only if explicitly approved)
signaltable gateway stop

# Restore full Hermes backup
tar -xzf ~/hermes-backup-20260703-140158.tar.gz -C ~ --strip-components=1 .hermes/config.yaml .hermes/.env
hermes gateway service install --replace
```

---

## 9. Notes for reviewing LLM

- VPS uses password SSH auth; agent's local SSH key (`~/.ssh/id_ed25519`) is in VPS `authorized_keys`.
- The Hermes **default profile** gateway is running and must not be touched. The `signaltable` profile is isolated; on the VPS the `signaltable-approval` plugin is loaded by the gateway process that also serves Telegram.
- All times: SGT (UTC+8).
- `signaltable.env` in the local workspace contains live API keys — never commit, paste in chat, or push.
- Owner Telegram: `signalTable_bot`; owner user ID `1697120790` (handle: kmsum).
- The discovery/scoring pipeline is deterministic and model-independent (no LLM calls) — parity can be validated via `--self-test` and CLI runs alone.
