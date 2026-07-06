# SignalTable: Event Discovery Skill

## Purpose
Discover Singapore tech/data/AI events from Luma, Meetup, and Eventbrite, filter by relevance, and return a deduplicated scored list.

## Platform Priority

Always scrape and rank in this order:

1. **Luma** (`lu.ma`) — highest priority; scrape first and spend the most effort here
2. **Meetup** — second priority
3. **Eventbrite** — third priority; scrape last

If time, browser sessions, or API quota is limited, complete Luma fully before Meetup, and Meetup before Eventbrite. When delegating parallel scrapes, assign the most capable subagent to Luma and ensure Luma results are merged first in the final output.

## Steps

### 1. Luma Singapore Events (priority 1) — Apify first, browser fallback

**Production path (VPS verified):** Hermes must run the deterministic script pipeline for Luma **before** any browser tool. Do **not** open the browser for Luma when this pipeline succeeds.

#### 1a. Preferred — Apify structured discovery (run first)

Use `terminal` or `execute_code`. Requires `APIFY_TOKEN` in `~/.hermes/profiles/signaltable/.env`.

**Primary command (use these exact paths):**

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore \
  --queries data,algorithm,compute \
  --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
```

The pipeline normalizes Apify rows, applies deterministic filters (upcoming → Singapore → Tech/AI → dedupe), then scores and renders the table.

Optional debug (operator inspection only):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore --queries data,algorithm,compute --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py --debug-filter
```

Replay a saved Apify export (no live fetch):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py --input /path/to/dataset.json \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
```

**Required Luma output contract** (pass through to the user unchanged):

```
Luma: N

| title | date | score | tier | source | URL |
| --- | --- | ---: | ---: | --- | --- |
...
```

- First line must be exactly `Luma: N` (N may be 0).
- Table columns: `title | date | score | tier | source | URL`.
- Default scoring cutoff: `--min-score 4` (built into `luma_discovery_report.py`).
- Use `--min-score 2` **only** for debugging/inspection — not for production discovery.

**When Apify succeeds:** treat stdout as the Luma discovery result. **Do not** call `browser_navigate`, `browser_click`, `browser_snapshot`, or `browser_console` for Luma.

**Apify success criteria:** command exits 0, stdout contains a line starting with `Luma:`, and `apify_luma.py` returned at least one normalized event. A `Luma: 0` line with a blocker (e.g. all rows failed `min_score`) is still a valid Apify result — do **not** fall back to browser.

#### 1b. Fallback — read-only browser (only if Apify fails)

Use browser tools **only** when the script pipeline cannot produce normalized Luma output:

- `APIFY_TOKEN` missing from `~/.hermes/profiles/signaltable/.env`
- `apify_luma.py` exits non-zero or Apify HTTP / actor error on stderr
- Normalized output is empty (`apify_luma.py` returns zero events — not merely `Luma: 0` after filtering/scoring)
- Empty stdout or no `Luma:` line from the piped command

Fallback rules:

- One `browser_navigate` to `https://lu.ma/singapore`
- One `browser_snapshot` (compact)
- Parse the snapshot text only — **no clicks**, no `browser_console`, no registration flows
- Do **not** create a Luma account, sign up, log in, or use registration flows

```bash
# Browser targets (fallback only):
# https://lu.ma/singapore
# https://lu.ma/sg
```

Extract from snapshot:

- Event title
- Date and time (SGT)
- Location (physical or online)
- Price (free or paid)
- Organizer name
- Short description
- Registration URL
- Event URL

#### Luma guardrails (always)

- Read-only discovery — no signup, login, registration, or account creation
- There is **no** tool named `event-discovery` — load this skill with `skill_view`, then run the scripts or browser fallback
- Never create a Luma account to work around Apify or browser failures

### 2. Scrape Meetup Singapore Tech Events (priority 2)
```bash
# Target: https://www.meetup.com/find/?keywords=tech+AI+data&location=sg--Singapore&source=EVENTS
# Also check specific groups: Singapore Data Science, Singapore AI
```

Extract the same fields as step 1.

### 3. Scrape Eventbrite Singapore Tech Events (priority 3)
```bash
# Target URL patterns:
# https://www.eventbrite.sg/d/singapore--singapore/tech--events/
# https://www.eventbrite.sg/d/singapore--singapore/data--science--events/
# https://www.eventbrite.sg/d/singapore--singapore/artificial-intelligence--events/
```

Extract the same fields as step 1.

### 4. Relevance Scoring

Luma rows from `luma_discovery_report.py` are already scored and tiered. Apply the rules below only to Meetup/Eventbrite rows, or when using the Luma browser fallback.

For each event, score 0–10:
- **+3**: Tags match AI/ML/data/LLM/GenAI/MLOps
- **+2**: Singapore physical location
- **+2**: Free admission
- **+1**: Well-known organizer (Google, Meta, AWS, NUS, Stripe, etc.)
- **+1**: Practical/hands-on workshop format
- **-3**: Paid event (flag as Tier 2/3)
- **-5**: Off-topic (fitness, lifestyle, etc.)

Keep events with score >= 4.

### 5. Deduplication
Before returning results, check `~/.hermes/profiles/signaltable/logs/events-seen.jsonl` for events already discovered in the past 30 days. Skip duplicates.

Append new events to `events-seen.jsonl` with format:
```json
{"event_id": "<url-hash>", "title": "...", "date": "...", "url": "...", "seen_at": "2026-07-03T08:00:00+08:00"}
```

### 6. Output Format
Return a JSON array sorted by relevance score (desc), then platform priority (Luma before Meetup before Eventbrite for ties):
```json
[
  {
    "title": "Singapore AI Meetup: Building with LLMs",
    "date": "2026-07-10T19:00:00+08:00",
    "location": "WeWork Suntec City, Singapore",
    "format": "in-person",
    "price": "free",
    "organizer": "Singapore AI Community",
    "relevance_score": 8,
    "tier": 1,
    "registration_url": "https://lu.ma/...",
    "source": "luma",
    "description": "..."
  }
]
```

### 7. Tier Classification
- **Tier 1**: free + instant confirmation + score >= 6
- **Tier 2**: ambiguous price, ambiguous confirmation flow, or score 4–5
- **Tier 3**: paid, approval-gated, requires OAuth/CAPTCHA

### 8. Logging
Append discovery summary to `~/.hermes/profiles/signaltable/logs/signaltable.log`:
```
[2026-07-03 08:00 SGT] DISCOVERY: Found 12 events (Luma:5 Meetup:4 Eventbrite:3). T1:5 T2:4 T3:3. Deduped 2.
```
