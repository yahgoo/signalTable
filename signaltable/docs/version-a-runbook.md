# SignalTable Version A — End-to-End Live Test

Version A does **only** discovery → scoring → shortlist → y/n/m feedback.  
No registration, LobsterMail, confirmation email, or calendar write.

---

## What v1 does

| Step | Action |
|------|--------|
| 1 | Discover events from **Luma**, **Meetup**, **Eventbrite** |
| 2 | Read title, agenda, venue, date/time, price |
| 3 | Score and rank (base score + feedback adjustments) |
| 4 | Send you a shortlist |
| 5 | You reply **y** / **n** / **m** only |
| 6 | Save label as preference feedback |
| 7 | Use feedback to boost/penalize similar future events |

---

## Event card format (Telegram)

Each event shows:

- **title**
- **platform** (luma / meetup / eventbrite)
- **When:** date/time (SGT)
- **Where:** primary event venue
- **Registration venue:** (Meetup only, when ticket/KonfHub venue differs from Meetup venue)
- **Price**
- **Food**
- **Agenda** (short summary)
- **Why it fits** (transparent scoring reasons)
- **URL:** canonical source event page (`event_page_url` → `url` → `source_url`; not KonfHub unless that is the only URL)
- **Reply: y / n / m**

Cards use **`URL:`** — the legacy **`Link:`** line is removed.

Meetup venue precedence: Meetup export `venue` populates **`Where:`**; optional `registrationVenue` metadata populates **`Registration venue:`** only.

---

## Deployment parity (2026-07-08)

**Status: complete.** Local repo and VPS (`ubuntu@43.156.46.66`, profile `~/.hermes/profiles/signaltable/`) match on:

- Meetup venue precedence (`Where:` / `Registration venue:` split)
- `URL:` card field and canonical URL resolution
- `--debug-urls` / `--probe-urls` on `discover`

**Authoritative updated set** (keep local and VPS in sync):

| Path | Role |
|------|------|
| `scripts/version_a.py` | Cards, discover CLI, debug URL audit hooks |
| `scripts/event_url_check.py` | Canonical URL + URL review flags |
| `scripts/meetup_normalize.py` | Meetup venue precedence + self-test |
| `scripts/luma_normalize.py` | Luma normalize + compact `url` fallback |
| `scripts/discovery_pipeline.py` | `_load_luma` passthrough + `event_page_url` |
| `fixtures/meetup-konfhub-gateway.sample.json` | Singapore dbt Meetup regression fixture |
| `fixtures/version-a-live/luma.json` | Version A Luma fixtures (mix of real + synthetic) |

**Rank / score differences between local and VPS** are expected when `event_feedback.jsonl` differs (VPS accumulates live y/n/m history). That is feedback state, not code drift. Compare cards on venue, URL, and food lines — not rank order — when validating parity.

---

## Scoring (transparent)

**Base score (0–10)** — from `discovery_common.py`:

- Keyword match (data / AI / compute): +3
- Strong title alignment: +1
- Singapore in-person: +2/+1
- Free: +2
- Trusted organizer / hands-on format / food prefs: ±1
- Vague networking / missing venue / paid / low-signal: penalties

**Feedback adjustment (−3 to +3)** — from your past labels:

- Same organizer you liked before: **+2**
- Same organizer you skipped: **−2**
- Maybe on organizer: **+1**
- Repeated yes/no on platform or keyword topics: **±1**

Final score = clamp(base + feedback, 0–10). Reasons appear in **Why it fits**.

---

## Files

| File | Purpose |
|------|---------|
| `scripts/version_a.py` | Main CLI: discover, queue, send, handle-reply, live-test |
| `scripts/event_url_check.py` | Canonical event URL + `--debug-urls` audit |
| `scripts/meetup_normalize.py` | Meetup normalize + venue precedence |
| `scripts/version_a_scoring.py` | Base + feedback scoring |
| `scripts/feedback_store.py` | y/n/m JSONL store + pending shortlist queue |
| `fixtures/version-a-live/` | Controlled live-test inputs (real-shaped events) |
| `fixtures/meetup-konfhub-gateway.sample.json` | dbt Meetup venue/URL regression fixture |
| `~/.hermes/profiles/signaltable/event_feedback.jsonl` | Your preference labels (production) |
| `~/.hermes/profiles/signaltable/pending_shortlist.json` | Events awaiting y/n/m |

### Auto-capture Telegram replies (v1)

Inbound **y / n / m** on Telegram is routed automatically:

1. `telegram_reply_router.py` tries Version A shortlist first when `replied_index < sent_index`
2. Hermes plugin `signaltable-approval` and hooks call the router on `pre_gateway_dispatch`
3. Feedback is saved to `event_feedback.jsonl`; **live** Telegram ack is sent only from Hermes hooks/plugin (`--live`)
4. Manual fallback: `python3 version_a.py handle-reply y` (JSON only) or `--notify` for a labeled `[MANUAL CLI]` Telegram ack

**Notify rules (strict):**

| Path | Flag | Telegram send | Ack label |
|------|------|---------------|-----------|
| Hermes plugin / hooks (real inbound) | `--live` | Yes | `Source: LIVE Telegram reply` |
| SSH / local router test | `--dry-run-notify` (default) | **No** | `[TEST] … Source: TEST (automated — not a human Telegram reply)` |
| `version_a.py handle-reply` | none | No | `[MANUAL CLI] …` in JSON `ack` only |
| `version_a.py handle-reply --notify` | `--notify` | Yes | `[MANUAL CLI] … Source: MANUAL CLI` |

**Do not** pass bare `--notify` to `telegram_reply_router.py` or `shortlist_reply.py` from SSH — it is rejected. Use `--dry-run-notify`.

Every ack includes: **event title**, **queue index** (`Queue: [i/n]`), **label** (`Label: y|n|m`), and **source** (live / test / manual).

Live ack example:

```
SignalTable v1 [2/3] No — recorded
Event: AI Builders Meetup
Queue: [2/3]
Label: n
Source: LIVE Telegram reply
Platform: luma
Feedback ID: abc123
```

Test ack example (JSON only, never sent to Telegram):

```
[TEST] SignalTable v1 [2/3] simulated No
Event: AI Builders Meetup
Queue: [2/3]
Label: n
Source: TEST (automated — not a human Telegram reply)
Platform: luma
```

Registration **YES/NO** still uses `approval_queue.py` only when `pending_approvals.json` has items.

---

## Controlled live test (recommended first run)

Uses fixture-backed events across three platforms (no Apify/API keys required):

```bash
cd signaltable/scripts

# 1. Self-test (scoring, card format, feedback boost)
python3 version_a.py --self-test

# 2. Generate shortlist + save JSON
python3 version_a.py live-test --top 3 \
  -o ../logs/version-a-live-test.json

# 3. Queue for Telegram replies
python3 version_a.py queue -i ../logs/version-a-live-test.json

# 4. Preview next Telegram card (no send)
python3 version_a.py send --dry-run

# 5. Send one event card (requires hermes + Telegram)
python3 version_a.py send

# 6. Record reply (MANUAL CLI — use only if auto-capture failed)
python3 version_a.py handle-reply y
# Optional: send labeled MANUAL ack to Telegram (not a live inbound reply)
python3 version_a.py handle-reply y --notify

# 7. Send next event, reply n or m, repeat until queue empty

# 8. Inspect learned preferences
python3 version_a.py feedback-summary
```

---

## Production discovery run (live inputs)

When Apify/export JSON files are available:

```bash
python3 version_a.py discover \
  --luma-input /path/to/luma-export.json \
  --meetup data:/path/to/meetup-data.json \
  --meetup algorithm:/path/to/meetup-algorithm.json \
  --eventbrite-input /path/to/eventbrite-export.json \
  --top 5 \
  --debug-urls \
  -o /tmp/version-a-shortlist.json

# Optional: HTTP reachability for live exports only (not needed for fixture-only runs)
python3 version_a.py discover ... --debug-urls --probe-urls

python3 version_a.py queue -i /tmp/version-a-shortlist.json
python3 version_a.py send
```

---

## URL debug mode (2026-07-08 — closed)

### Root cause (Luma 404 investigation)

The two Luma fixture URLs that returned HTTP 404 (`llm-eval-night-sg`, `dev-prompt-lab-sg`) were **intentionally synthetic fixture slugs**, not stale real events and not production URL corruption. Titles and venues were authored as controlled test data; the slugs were never live Luma pages.

The card pipeline behaved correctly: `_load_luma()` passes compact items through with their `url` field intact; `canonical_event_url()` reads it; cards show the expected `URL:` line.

A **separate latent bug** in `luma_normalize.normalize_canonical()` was fixed: compact items that have `url` but not `source_url` now preserve `url` and `event_page_url` when normalized directly (Apify path or future callers).

### URL audit flags

| Flag | Meaning | Events removed? |
|------|---------|---------------|
| `synthetic_fixture` | Known placeholder URL (`synthetic_fixture: true` in fixture JSON) | No |
| `unreachable` | Real URL probes HTTP 4xx/5xx or network error | No |
| `duplicate_url` | Same canonical URL appears twice in shortlist | No |
| `missing_url` | No canonical URL resolved | No |
| `registration_url_differs` | Meetup page URL differs from KonfHub registration URL | No |

**Synthetic fixtures are never flagged `unreachable`**, even with `--probe-urls`. A 404 on a known synthetic slug is expected and must not create false-alarm noise.

### Expected debug output

**Synthetic fixture (stderr):**
```
url_review #1 LLM Eval Night ...: synthetic_fixture [SYNTHETIC FIXTURE — placeholder URL not a real event] (https://luma.com/llm-eval-night-sg)
```

**Real broken URL (stderr):**
```
url_review #3 Some Real Event: unreachable (https://luma.com/missing-slug)
```

**Real URL, no issues:** no stderr line.

Cards are unchanged in both modes — debug flags go to stderr / JSON `url_review`, not to Telegram cards.

### Normal mode vs debug mode

| Mode | Command | Use when |
|------|---------|----------|
| **Normal** | `discover ...` (no flags) | Routine shortlist generation, queue, send |
| **Debug URLs** | `discover ... --debug-urls` | Reviewing a batch before send; flags missing/duplicate/synthetic URLs without HTTP probes |
| **Debug + probe** | `discover ... --debug-urls --probe-urls` | Validating **live Apify/export inputs** for reachability; skip on fixture-only runs unless you want to confirm synthetic labels |

Use **`--debug-urls` alone** for fixture-backed live tests. Add **`--probe-urls`** only when checking real production exports — not to re-probe known synthetic fixtures.

Fixture convention: mark intentional placeholders with `"synthetic_fixture": true` and a `_fixture_note` in `fixtures/version-a-live/luma.json`. Real fixture events (e.g. `aic-si-7-8`) omit the flag.

---

## Pass criteria

- Shortlist contains events from **≥2 platforms**
- Each card includes all required fields + **Reply: y / n / m**
- `handle-reply y|n|m` appends to `event_feedback.jsonl`
- Re-running discover shows **feedback_adjustment** on similar events
- No registration / LobsterMail / calendar scripts invoked

## Fail criteria

- Empty shortlist with no filter debug explanation
- Missing price, location, or agenda on card
- Replies other than y/n/m accepted as feedback
- Any auto-registration or calendar write triggered

---

## Out of scope (explicit)

Do **not** use in Version A:

- `registration_gateway.py`, `event-register` skill
- `lobstermail_poll.py`, `email_confirm_validate.py`
- `calendar_write.py`, `gcal.py`
- `approval_queue.py` YES/NO registration flow

Use `version_a.py handle-reply` for **y / n / m** only.

---

## Typical session trace

```
version_a.py live-test --top 3
  → 3 events scored (luma + meetup + eventbrite)

version_a.py send
  → Telegram: event #1 card + "Reply: y / n / m"

You: y
  → Hermes plugin routes with --live; ack says LIVE Telegram reply

# If auto-capture failed:
version_a.py handle-reply y
  → Saved to event_feedback.jsonl (MANUAL CLI, JSON ack only)

version_a.py handle-reply y --notify
  → Same + [MANUAL CLI] Telegram ack

version_a.py send
  → event #2 ...

You: n
  → auto-captured via --live, or version_a.py handle-reply n (manual)

version_a.py feedback-summary
  → counts: {y: 1, n: 1}
```

Next discover run applies feedback to similar organizers/topics automatically.
