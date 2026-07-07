# SignalTable: Event Discovery Skill

## Purpose
Discover Singapore **in-person, free** tech/data/AI events from Luma and Meetup (Eventbrite last), using a shared deterministic pipeline:

**fetch → normalize → hard-filter → dedupe → score → ranked output**

User preferences (hard):
- Singapore only
- In-person / physical only (no online-only, no hybrid)
- Free events only (clearly paid rows are rejected; uncertain free-ness is down-ranked, not rejected)
- Strongest interest: AI / data / compute / algorithm
- Search keywords: `data`, `algorithm`, `compute` (same for Luma and Meetup)

## Platform Priority

1. **Luma** (`lu.ma`) — highest priority
2. **Meetup** — second priority (Apify export JSON per keyword)
3. **Eventbrite** — third priority (Apify export JSON, Science & Tech category, free-only task)

Complete Luma before Meetup when time or quota is limited.

## Shared Pipeline (`discovery_common.py`)

All Luma and Meetup scripts normalize to the same schema, then call:

1. **`hard_filter`** — upcoming (SGT), Singapore, in-person, not clearly paid, tech-relevant, not off-topic
2. **`dedupe_events`** — merge keyword/source evidence across duplicates
3. **`score_and_tier`** — relevance 0–10, default `--min-score 4`

Evidence fields on every row: `why_selected`, `why_rejected`, `free_evidence`, `singapore_evidence`, `in_person_evidence`.

## Steps

### 1. Luma (priority 1) — Apify first, browser fallback

**Production path:** run scripts before any browser tool.

#### 1a. Preferred — Apify structured discovery

Requires `APIFY_TOKEN` in `~/.hermes/profiles/signaltable/.env`.

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore \
  --queries data,algorithm,compute \
  --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
```

Replay a saved export (dry-run / no live fetch):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py \
  --input /path/to/dataset_luma-....json \
  --debug-filter
```

**Required Luma output contract:**

```
Luma: N

| title | date | score | tier | source | URL |
| --- | --- | ---: | ---: | --- | --- |
...
```

- First line: exactly `Luma: N` (N may be 0).
- Default cutoff: `--min-score 4`.
- `Luma: 0` after scoring is a valid Apify result — **do not** fall back to browser.

#### 1b. Browser fallback (Apify failure only)

Use read-only browser only when Apify cannot produce normalized rows (missing token, HTTP error, empty normalized output — not merely zero scored candidates).

### 2. Meetup (priority 2) — Apify export JSON per keyword

Meetup discovery uses **three separate Apify exports**, one per search keyword:

| Keyword | Typical export filename pattern |
| --- | --- |
| `data` | `dataset_meetup-data-sg-physical_*.json` |
| `algorithm` | `dataset_meetup-algorithm-sg-physical_*.json` |
| `compute` | `dataset_meetup-compute-sg-physical_*.json` |

**Per-keyword report:**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/meetup_discovery_report.py \
  --input /path/to/dataset_meetup-data-sg-physical_....json \
  --query data \
  --debug-filter
```

**Unified Luma + Meetup dry-run (recommended for inspection):**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/discovery_pipeline.py \
  --luma-input /path/to/dataset_luma-....json \
  --meetup data:/path/to/dataset_meetup-data-....json \
  --meetup algorithm:/path/to/dataset_meetup-algorithm-....json \
  --meetup compute:/path/to/dataset_meetup-compute-....json \
  --debug-filter
```

Add `--json` for full normalized rows (approval queue / downstream use).

**Required Meetup output contract:**

```
Meetup: N

| title | date | score | tier | source | matched | URL |
...
```

Do **not** use browser scraping for Meetup when Apify export JSON is available.

### 3. Eventbrite (priority 3) — Apify export JSON

Primary production task: **`eventbrite-science-tech-singapore-free`** (Singapore, Science & Tech category, free events).

Optional backup category export: `business` (broader; noisier — use only if Science & Tech is sparse).

**Per-task report:**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/eventbrite_discovery_report.py \
  --input /path/to/dataset_eventbrite-science-tech-singapore-free_....json \
  --query science-tech \
  --debug-filter
```

**Unified dry-run (includes Eventbrite):**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/discovery_pipeline.py \
  --eventbrite-input /path/to/dataset_eventbrite-science-tech-singapore-free_....json \
  --debug-filter
```

Shorthand with explicit query label:

```bash
python3 ~/.hermes/profiles/signaltable/scripts/discovery_pipeline.py \
  --eventbrite science-tech:/path/to/export.json \
  --debug-filter
```

**Required Eventbrite output contract:**

```
Eventbrite: N

| title | date | score | tier | source | matched | URL |
...
```

Do **not** use browser scraping for Eventbrite when Apify export JSON is available.

Field mapping notes: see `eventbrite_normalize.py` (`EVENTBRITE_FIELD_NOTES`). Verify field names against your live Apify actor export.

### 4. Hard Filters (before scoring)

Applied in `discovery_common.hard_filter`:

| Filter | Rule |
| --- | --- |
| Upcoming | `start_time` ≥ now (Asia/Singapore) |
| Singapore | city/country/address/venue or Luma `featured_city` |
| In-person | Meetup `PHYSICAL`; Luma offline; Eventbrite venue + not online; reject HYBRID/ONLINE |
| Free | Reject if clearly paid; uncertain allowed through |
| Tech relevance | AI/data/compute keywords, AI/Tech tag, or Eventbrite Science & Tech category |
| Off-topic | Reject hiking/travel/singles/fitness/social groups unless title is strongly technical |

### 5. Free-Event Logic

**Luma** (`luma_normalize._infer_luma_free`):
- `ticket_info.is_free` or `ticketing.isFree` → free / paid
- Ticket type names containing "Free" → free
- Non-free ticket types present → paid
- Summary mentions "free" (not "free trial") → free
- Summary price cues (`$`, SGD, "paid admission") → paid
- Unknown → `is_free=null`, down-ranked in scoring
- Approval-required or waitlist **does not** invalidate free events

**Meetup** (`meetup_normalize.infer_meetup_free`):
- `isPaidEvent=true` or `feeRequired=true` or non-zero `feeAmount` → paid
- `isPaidEvent=false` → free
- Unknown → `is_free=null`, down-ranked

**Eventbrite** (`eventbrite_normalize.infer_eventbrite_free`):
- `is_free` / `isFree` true → free; explicit false + paid price → paid
- `priceDisplay` / `price` == Free or zero tiers → free
- `priceMin` / `priceMax` / `ticket_tiers` > 0 → paid
- Unknown → `is_free=null`, down-ranked

### 6. Scoring (after hard filters)

`discovery_common.score_event` (0–10, keep ≥ `--min-score`):

- **+3** keyword/topic match (data, algorithm, compute, AI, ML, LLM, …)
- **+1** strong keyword in title
- **+2** Singapore evidence
- **+1** in-person confirmed
- **+2** confirmed free
- **+1** trusted organizer (Google, AWS, SingaDev, Div0, …)
- **+1** workshop/hands-on format
- **−2** vague networking with weak tech fit
- **−1** missing venue or start time
- **−1** uncertain free status
- **−3** low-signal terms (fitness, hiking, …)
- **−5** confirmed paid (should rarely reach scoring)

Tier classification (`classify_tier`):
- **Tier 1**: free + score ≥ 6 + no approval gate
- **Tier 2**: score 4–5, uncertain price, or approval-gated free with score ≥ 6
- **Tier 3**: paid or heavy approval friction

### 7. Deduplication

`discovery_common.dedupe_events`:
- Primary key: normalized URL (`lu.ma` / Meetup event URL)
- Fallback: normalized `title | start (16 chars) | venue`
- On merge: union `matched_keywords`, `sources`; keep richest evidence fields; highest score wins

Cross-source dedupe: run `discovery_pipeline.py` to merge Luma + Meetup before downstream approval.

Also check `~/.hermes/profiles/signaltable/logs/events-seen.jsonl` for events discovered in the past 30 days (operational dedupe, separate from pipeline dedupe).

### 8. Output Format

Production tables are markdown (see contracts above). Structured JSON (--json) uses the normalized schema:

```json
{
  "source": "meetup",
  "source_query": "data",
  "matched_keyword": "data",
  "matched_keywords": ["data", "compute"],
  "sources": ["meetup"],
  "title": "...",
  "start_time": "2026-07-18T14:00:00+08:00",
  "is_in_person": true,
  "is_free": true,
  "free_evidence": "isPaidEvent=false",
  "singapore_evidence": "country=sg",
  "in_person_evidence": "eventType=PHYSICAL",
  "relevance_score": 10,
  "tier": 1,
  "why_selected": ["keyword match: ...", "Singapore", "free"],
  "url": "https://www.meetup.com/..."
}
```

Sort: relevance score desc, then Luma before Meetup for ties.

### 9. Logging

Append discovery summary to `~/.hermes/profiles/signaltable/logs/signaltable.log`:

```
[2026-07-07 12:00 SGT] DISCOVERY: Luma:3 Meetup:14 Combined:14 (after dedupe). T1:10 T2:4. Hard-filter dropped 86.
```

### 10. Guardrails

- Read-only discovery — no signup, login, or registration during discovery
- No tool named `event-discovery` — load this skill with `skill_view`, then run scripts
- Never commit API keys or export datasets with secrets
- Prefer narrower filters over broader scraping when tradeoff exists

## Key Scripts

| Script | Role |
| --- | --- |
| `discovery_common.py` | Shared schema, filters, scoring, dedupe |
| `luma_normalize.py` | Luma → canonical schema |
| `meetup_normalize.py` | Meetup → canonical schema |
| `luma_discovery_report.py` | Luma-only pipeline + table |
| `meetup_discovery_report.py` | Meetup-only pipeline + table |
| `eventbrite_normalize.py` | Eventbrite → canonical schema |
| `eventbrite_discovery_report.py` | Eventbrite-only pipeline + table |
| `discovery_pipeline.py` | Combined Luma + Meetup + Eventbrite dry-run |
| `apify_luma.py` | Live Luma fetch via Apify |
