# SignalTable Working Session — 2026-07-08 (Version A / Live Luma)

**Status:** ACTIVE (Version A / Telegram / relevance only) — Luma schema topics superseded by `docs/sessions/2026-07-10-luma-schema-hardening-session-end.md`.  
**VPS:** `ubuntu@43.156.46.66` · profile `~/.hermes/profiles/signaltable/`  
**Local repo:** `/Users/kmsum/Downloads/signalTable`

---

## Branching point (resume here)

| Area | State |
|------|--------|
| Live Luma discover | **Working** on Hermes VPS via Apify |
| URL / venue / cards | **Stable** — deployment parity complete |
| Shortlist relevance | **Pending** — weak `data`-only matches pollute top ranks |
| Telegram | **Partial** — 3 approved e2e cards sent; quality batch not sent |

**Next work when resuming:**
1. Collect y/n/m replies for the 3 sent Luma cards (or manual `handle-reply` fallback).
2. Decide whether to send anything from the latest **quality review batch** (not yet queued/sent).
3. Plan separate scoring/filter work for loose `data` keyword matches (out of scope for URL/venue fixes).

---

## Version A — what works

### Discovery pipeline (live Luma)

```bash
export PATH="$HOME/.local/bin:$PATH"
set -a && source ~/.hermes/profiles/signaltable/.env && set +a
cd ~/.hermes/profiles/signaltable/scripts

# 1. Live fetch (no fixtures)
python3 apify_luma.py --location singapore --queries data,algorithm,compute --max-items 50 \
  > ../logs/luma-live-fetch.json

# 2. Version A shortlist + URL audit
python3 version_a.py discover \
  --luma-input ../logs/luma-live-fetch.json \
  --top 10 --debug-urls --probe-urls \
  -o ../logs/luma-live-discover.json

# 3. Manual eyeball → curate approved JSON → queue → send
python3 version_a.py --pending ../logs/luma-e2e-pending.json queue -i ../logs/luma-e2e-approved.json
python3 version_a.py --pending ../logs/luma-e2e-pending.json send --dry-run
python3 version_a.py --pending ../logs/luma-e2e-pending.json send   # real Telegram
```

Typical live batch: **44 raw → 12 scored → 7–10 shown**. All probed live `lu.ma/` URLs returned **HTTP 200**.

### Event card format (Telegram)

Standard Version A card — **`Link:` removed**, **`URL:` canonical**:

- Platform · When · Where · Price · Food · Agenda · Why it fits · **URL:** · Reply: y / n / m

Meetup-only: **`Registration venue:`** secondary line when KonfHub/ticket venue differs.

### URL review modes

| Mode | Command | Use |
|------|---------|-----|
| Normal | `discover ...` | Routine runs — no stderr noise |
| Debug | `discover ... --debug-urls` | Flag missing/duplicate/synthetic before send |
| Probe | `discover ... --debug-urls --probe-urls` | Live exports only — HTTP reachability |

**Synthetic fixtures** (`synthetic_fixture: true` in fixture JSON) → flag `synthetic_fixture`, **never** `unreachable`.  
**Real broken URLs** → `unreachable`. Events are **never auto-deleted**.

### Meetup venue precedence (closed)

- Primary **`Where:`** = Meetup export `venue`
- **`Registration venue:`** = optional `registrationVenue` metadata
- dbt Meetup regression: Monk's Brew Club primary; Thoughtworks secondary

### Deployment parity (closed 2026-07-08)

Local ↔ VPS match on venue, `URL:`, `--debug-urls`. Authoritative sync set:

- `scripts/version_a.py`
- `scripts/event_url_check.py`
- `scripts/meetup_normalize.py`
- `scripts/luma_normalize.py`
- `scripts/discovery_pipeline.py`
- `fixtures/meetup-konfhub-gateway.sample.json`
- `fixtures/version-a-live/luma.json` (fixture labels)

VPS rank/score may differ from fresh local runs due to `event_feedback.jsonl` history — not code drift.

---

## Luma URL debug (closed 2026-07-08)

**Root cause:** 404 fixture slugs (`llm-eval-night-sg`, `dev-prompt-lab-sg`) were **intentionally synthetic**, not stale real events or normalization corruption.

**Latent fix:** `luma_normalize.normalize_canonical()` now preserves `url` / `event_page_url` when compact items have `url` but not `source_url`. `_load_luma()` passthrough sets `event_page_url` from `url`.

**Fixture convention:** real event = `aic-si-7-8` (probes 200); synthetic rows have `"synthetic_fixture": true` + `_fixture_note`.

---

## Live Luma quality findings (2026-07-08)

### Send-ready (strong AI/data fit)

| Event | URL |
|-------|-----|
| AI In The Wild: Building Software Factories… GenAI | `https://lu.ma/l1d7um23` |
| Better Data, Bolder AI - No SEA Language Left Behind | `https://lu.ma/vynme9pi` |
| Singapore AI & Robotics Demo Night (Jul 2026) | `https://lu.ma/0kbtspti` |

### Skip (weak `data`-only or off-topic)

NUS forum, OFF:FORM 10K run, SHELLGym (data-only match), National Day party, Joyous Rhapsody, art exhibition, ragebait pitch night, stroller/drun events — all score 8–9 via broad **`data`** substring in Apify metadata.

### Known display gaps (not blockers)

- **Agenda:** `No agenda text available` — Apify compact rows lack description on normalize path
- **Where:** venue text duplicated (venue_name == full_address)

---

## Telegram / queue state (VPS)

### E2E approved batch — **3/3 sent**

| File | Purpose |
|------|---------|
| `logs/luma-e2e-fetch.json` | Live Apify export used for e2e |
| `logs/luma-e2e-discover.json` | Full discover (top 10) |
| `logs/luma-e2e-approved.json` | Manual curated 3-event shortlist |
| `logs/luma-e2e-pending.json` | Queue state |

**Pending state at session save:**
- `sent_index`: **3 / 3**
- `replied_index`: **0** (replies not yet captured in this session)
- Awaiting reply title: Singapore AI & Robotics Demo Night (last sent)

Cards sent to Telegram:
1. AI In The Wild · `lu.ma/l1d7um23`
2. Better Data, Bolder AI · `lu.ma/vynme9pi`
3. Singapore AI & Robotics Demo Night · `lu.ma/0kbtspti`

**Weak-fit events from discover were NOT sent.**

### Quality review batch — **NOT sent to Telegram**

| File | Purpose |
|------|---------|
| `logs/luma-live-quality.json` / `luma-e2e-discover.json` | Discover output for eyeballed quality review |
| URL audit | Clean — all live URLs 200 |

Resume: decide whether to queue/send after manual review, or wait for scoring tuning.

---

## Decisions preserved

1. **`URL:` replaces `Link:`** — canonical order: `event_page_url` → `url` → `source_url` → `registration_url` (fallback only).
2. **Do not auto-delete** flagged URL events — review only.
3. **Manual curation gate** before Telegram for live Luma until relevance tuning lands.
4. **One card at a time** for replies; do not blast full shortlist.
5. **Out of scope (Version A):** registration, LobsterMail, calendar write, scoring changes during URL/venue work.

---

## Useful prompts / commands for resume

```bash
# Check queue
python3 -c "import json; d=json.load(open('~/.hermes/profiles/signaltable/logs/luma-e2e-pending.json')); print(d.get('sent_index'), d.get('replied_index'), d.get('awaiting_reply_title'))"

# Manual reply fallback (MANUAL CLI — not live Telegram capture)
python3 version_a.py --pending ../logs/luma-e2e-pending.json handle-reply y

# Feedback summary
python3 version_a.py feedback-summary

# Fresh live discover + quality review
python3 apify_luma.py --location singapore --queries data,algorithm,compute --max-items 50 > ../logs/luma-live-fetch.json
python3 version_a.py discover --luma-input ../logs/luma-live-fetch.json --top 10 --debug-urls --probe-urls
```

---

## Self-tests (should pass)

```bash
cd signaltable/scripts
python3 event_url_check.py --self-test
python3 meetup_normalize.py --self-test
python3 version_a.py --self-test
```

---

## Docs updated this session

- `docs/version-a-runbook.md` — deployment parity, URL debug mode, card format
- `docs/plan-log.md` — deployment parity + Luma URL debug closed
- `docs/sessions/2026-07-08-version-a-luma-handoff.md` — **this file (current working session)**

---

## Recommended next steps (priority order)

1. **Reply capture** — y/n/m on Telegram for 3 sent cards; verify `event_feedback.jsonl` + live acks.
2. **Quality batch** — re-run live discover if stale; manually approve before any new send.
3. **Relevance tuning (future PR)** — tighten `data` keyword matching in `discovery_common.py` / Luma filter; do not conflate with URL work.
4. **Optional VPS sync** — ensure latest `event_url_check.py`, `luma.json` fixture labels, `luma_normalize.py`, `discovery_pipeline.py` on VPS if stderr synthetic labels missing.

---

*Session saved: 2026-07-08. Resume from live Luma quality review and Telegram send preparation.*
