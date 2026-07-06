# SignalTable — Event Discovery Runbook

## Overview

Luma discovery is **Apify-first** and production-verified on VPS. The deterministic script pipeline is the default path; browser discovery is fallback only. Meetup and Eventbrite flows are unchanged. Registration, email parsing, calendar writes, and Telegram reporting are separate steps — not part of this runbook.

**Platform order:** Luma → Meetup → Eventbrite

---

## Do

- Run Luma discovery through the Apify-backed script pipeline **first**.
- Use these absolute VPS paths:

  ```bash
  python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
    --location singapore \
    --queries data,algorithm,compute \
    --max-items 50 \
    | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
  ```

- Require `APIFY_TOKEN` in `~/.hermes/profiles/signaltable/.env`.
- Keep only **upcoming** events: event `start_at` ≥ now in **Asia/Singapore**.
- Keep only **Singapore** events: match on city, country, full address, or featured city.
- Keep only **Tech/AI-relevant** events: category `AI` / `Tech`, or keywords in title/summary/organizer — e.g. data, algorithm, compute, AI, ML, LLM, GenAI, developer, engineering, prompt, agent, model.
- **Deduplicate** by URL first, then normalized title + date.
- Use **`min_score=4`** in production (default in `luma_discovery_report.py`).
- Use **`min_score=2`** only for debugging or inspection.
- Preserve the output contract exactly (see below).
- Load skill via `skill_view(name="event-discovery")` before running discovery.
- Keep `skills/event-discovery.md` and `docs/architecture.md` aligned with this runbook.

---

## Don't

- Don't use `indexedDateAfter` as an event-freshness filter.
- Don't rely on scrape/index timestamps for “upcoming”.
- Don't use browser Luma discovery when Apify succeeds.
- Don't change Meetup or Eventbrite logic as part of Luma work.
- Don't modify gateway, cron, Google Calendar, Telegram, or LobsterMail for discovery changes.
- Don't treat `Luma: 0` after scoring as an Apify failure.
- Don't require signup, login, or registration for discovery.
- Don't call a tool named `event-discovery` — skills are not tools.
- Don't create a Luma account to work around Apify or browser issues.

---

## Fallback

Use browser Luma discovery **only if**:

- `APIFY_TOKEN` is missing,
- Apify request fails (non-zero exit),
- normalized output is empty (zero events from `apify_luma.py`),
- or there is an Apify HTTP/actor error.

**Do not fall back** if `Luma: 0` appears because scoring removed all rows (`min_score=4`).

If browser fallback is used:

- Read-only, discovery-only.
- One `browser_navigate` → `https://lu.ma/singapore`
- One `browser_snapshot` (compact)
- Parse snapshot text only — no clicks, no `browser_console`, no registration flows.

---

## Output Contract

First line exactly:

```
Luma: N
```

Then a markdown table:

```
| title | date | score | tier | source | URL |
| --- | --- | ---: | ---: | --- | --- |
```

Pass Apify pipeline stdout through unchanged. A blocker line after `Luma: 0` is valid when filters/scoring removed all rows.

**Debug filter trace** (stderr, optional):

```
filter_debug: raw=N -> upcoming=N -> singapore=N -> tech_ai=N -> deduped=N
```

---

## Notes

| Item | Detail |
|------|--------|
| Scripts | `apify_luma.py`, `luma_normalize.py`, `luma_discovery_report.py` |
| Optional env | `APIFY_ACTOR_ID` (default `solidcode/luma-scraper`), `APIFY_TASK_ID` |
| Skill | `~/.hermes/profiles/signaltable/skills/event-discovery/SKILL.md` |
| Replay raw JSON | `apify_luma.py --input dataset.json \| luma_discovery_report.py` |
| Meetup / Eventbrite | Unchanged — browser/scrapling per skill Steps 2–3 |
| Downstream (separate) | `event-register`, `email-parser`, `calendar-updater`, `telegram-reporter` |

**Typical filter trace (production):** `raw=34 → upcoming=34 → singapore=34 → tech_ai=7 → deduped=7 → scored=2`
