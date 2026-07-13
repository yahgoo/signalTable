# SignalTable Session — 2026-07-10 (Luma Schema Hardening + Live Verification)

**Status:** CLOSED — schema hardening shipped; live production verification complete with documented follow-ups.  
**VPS:** `ubuntu@43.156.46.66` · profile `~/.hermes/profiles/signaltable/`  
**Local repo:** `/Users/kmsum/Downloads/signalTable`  
**Supersedes:** `docs/sessions/2026-07-08-version-a-luma-handoff.md` for Luma normalization / schema topics

---

## Branching point (resume here)

| Area | State |
|------|--------|
| Luma schema hardening | **Complete** — `inspect_luma_schema()`, fallbacks, `--self-test` |
| Live production verification | **Complete** — `20260709-schema-verify` batch on VPS |
| Foreign Actor detection | **Verified** — 0 foreign-schema warnings on live solidcode data |
| Description field | **Open** — Actor returns `description: null` for all rows; 46/46 `missing_critical_field:description` warnings |
| Schema documentation | **Gap** — doc describes nested `api_id`/`event{}` shape; live Actor uses flat `eventId`/`startAt` |
| Version A relevance / Telegram | **Unchanged** — still pending from 2026-07-08 handoff |

**Next work when resuming:**
1. Update `docs/luma-apify-schema.md` for **flat solidcode production shape** (`eventId`, `startAt`, `eventUrl`, `location{}`, `ticketing{}`).
2. Decide description strategy: scrape another field (`sessions`, page fetch), downgrade warning when source `description` is explicitly null, or accept empty `Agenda:` on cards.
3. Optional: extend `is_raw_apify_item()` / `SOLIDCODE_MARKERS` to recognize `eventId` + `startAt` (classification only — pipeline already works).
4. Resume Version A quality/Telegram work from 2026-07-08 handoff if desired.

---

## Completed this session

### 1. Luma Apify schema hardening

**Goal:** Fail loudly on schema drift instead of silently dropping data (latent URL-drop class of bugs).

| Deliverable | Path |
|-------------|------|
| Field mapping documentation | `docs/luma-apify-schema.md` |
| Defensive fallback chains (title, when, url, venue, description, price) | `scripts/luma_normalize.py` |
| `inspect_luma_schema()` + stderr warnings + `normalization_warnings` on event dict | `scripts/luma_normalize.py` |
| Regression self-test (solidcode OK + wrong-shape warns) | `python3 luma_normalize.py --self-test` |

**Self-test (local + VPS after deploy):** all checks pass.

### 2. Live production verification (`20260709-schema-verify`)

Deployed hardened `luma_normalize.py` to VPS (was missing `inspect_luma_schema()`), then ran fresh live batch — no fixtures, no code changes during verification.

```bash
export PATH="$HOME/.local/bin:$PATH"
set -a && source ~/.hermes/profiles/signaltable/.env && set +a
cd ~/.hermes/profiles/signaltable/scripts

# Self-test (post-deploy)
python3 luma_normalize.py --self-test

# Live fetch + schema audit + Version A discover were run as one verification job
# Logs tagged 20260709-schema-verify (see below)
```

| Metric | Result |
|--------|--------|
| Actor | `solidcode/luma-scraper` |
| Raw count | 46 |
| Foreign-schema warnings | **0** |
| Missing-field warnings | **46** (all `missing_critical_field:description`) |
| Critical fields populated | title/start_time/url/venue/price **46/46**; description **0/46** |
| Version A discover | 46 → 12 scored → 10 shortlist (exit 0) |
| URL probes (shortlist) | 10/10 HTTP 200 |

**Verification logs** (separate from prior `luma-live-*`):

```
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-raw.json
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-fetch.json
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-schema-report.json
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-discover.json
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-discover.stderr
~/.hermes/profiles/signaltable/logs/20260709-schema-verify-summary.json
```

---

## Live solidcode shape (production truth)

Flat scraper row — **not** the nested lu.ma API export documented earlier:

| Field (46/46) | Maps to |
|---------------|---------|
| `eventId` | source event id (not `api_id`) |
| `eventUrl` | canonical URL (`https://lu.ma/...`) |
| `name` | title |
| `startAt` / `endAt` | when |
| `location{name,address,city,country}` | venue |
| `ticketing` / `ticketTypes` | price / free |
| `categoryNames` | categories |
| `description` | **always `null` in this batch** |

**`is_raw_apify_item()`:** 0/46 (expects `api_id` or nested `event`). Normalization still succeeds via `normalize_raw_item()` fallbacks.

---

## Warnings analysis

| Warning | Count | Cause | False positive? |
|---------|-------|-------|-----------------|
| `possible_non_solidcode_actor_schema` | 0 | — | — |
| `missing_critical_field:description` | 46 | Actor sends `description: null`; no `description_mirror` / `guest_info` in export | **No** — correct loud failure |

Venue note: 32/46 have `location.name` + `address`; 14 fall back to `"Singapore, Singapore"` from city/country only — source sparsity, not wrong-field mapping.

---

## Production verification verdict

| Check | Status |
|-------|--------|
| Zero foreign-schema warnings | **PASS** |
| Primary fields extracted without silent loss (except description) | **PASS** |
| Warnings fire on missing description (not silent blank cards) | **PASS** |
| Zero warnings on live data overall | **FAIL** (description only) |
| Doc matches live field map | **GAP** |

**Safe for production:** foreign-schema detection and non-silent missing-field behavior.  
**Not fully closed:** description population + doc sync for flat solidcode shape.

---

## Files touched this session

| File | Change |
|------|--------|
| `scripts/luma_normalize.py` | Schema hardening, `inspect_luma_schema()`, fallbacks, `--self-test` |
| `docs/luma-apify-schema.md` | Field mapping + warning behavior (needs flat-shape update) |
| VPS `~/.hermes/profiles/signaltable/scripts/luma_normalize.py` | Deployed hardened version |

**Not changed:** scoring, food detection, card format, registration, calendar.

---

## Quick commands

```bash
# Local self-test
cd signaltable/scripts && python3 luma_normalize.py --self-test

# VPS live discover (standard production path)
set -a && source ~/.hermes/profiles/signaltable/.env && set +a
cd ~/.hermes/profiles/signaltable/scripts
python3 apify_luma.py --location singapore --queries data,algorithm,compute --max-items 50 \
  > ../logs/luma-live-fetch.json
python3 version_a.py discover \
  --luma-input ../logs/luma-live-fetch.json \
  --top 10 --debug-urls --probe-urls \
  -o ../logs/luma-live-discover.json
# Expect stderr description warnings until description follow-up is resolved
```

---

## Carry-forward from 2026-07-08

- Shortlist relevance: weak `data`-only matches still pollute top ranks.
- Telegram: 3 approved e2e cards sent; quality batch not sent.
- Collect y/n/m replies or use `version_a.py handle-reply` fallback.

See `docs/sessions/2026-07-08-version-a-luma-handoff.md` for Version A card format, URL debug modes, and deployment parity details.
