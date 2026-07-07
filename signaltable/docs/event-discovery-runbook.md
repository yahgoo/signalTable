# SignalTable — Event Discovery Runbook

## Overview

Luma and Meetup discovery share **`discovery_common.py`**: normalize → hard-filter → dedupe → score → tier. Luma is **Apify-first**; Meetup uses Apify export JSON per keyword (`data`, `algorithm`, `compute`). Browser discovery is Luma fallback only. Registration, calendar, Telegram are separate — not part of this runbook.

**Platform order:** Luma → Meetup → Eventbrite

**Deployed on VPS:** 2026-07-07 (`discovery-refactor` backup under profile `backups/`)

---

## Do

### Luma (production path)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore \
  --queries data,algorithm,compute \
  --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py --debug-filter
```

Requires `APIFY_TOKEN` in `~/.hermes/profiles/signaltable/.env`.

**Hard filters (before scoring):** upcoming (SGT), Singapore, in-person/offline, not clearly paid, tech-relevant, not off-topic.

**Defaults:** `--min-score 4` (use `--min-score 2` for inspection only).

### Meetup (export JSON per keyword)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/meetup_discovery_report.py \
  --input /path/to/dataset_meetup-data-sg-physical_....json \
  --query data \
  --debug-filter
```

Repeat for `algorithm` and `compute` exports.

### Eventbrite (export JSON — Science & Tech, free)

Primary Apify task: `eventbrite-science-tech-singapore-free`

```bash
python3 ~/.hermes/profiles/signaltable/scripts/eventbrite_discovery_report.py \
  --input /path/to/dataset_eventbrite-science-tech-singapore-free_....json \
  --query science-tech \
  --debug-filter
```

Local sample fixture (dev only):

```bash
python3 signaltable/scripts/eventbrite_discovery_report.py \
  --input signaltable/fixtures/eventbrite-science-tech-singapore-free.sample.json \
  --debug-filter
```

### Combined dry-run (inspection only)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/discovery_pipeline.py \
  --luma-input /tmp/signaltable_luma_live.json \
  --meetup data:/tmp/signaltable-meetup-exports/dataset_meetup-data-....json \
  --meetup algorithm:/tmp/signaltable-meetup-exports/dataset_meetup-algorithm-....json \
  --meetup compute:/tmp/signaltable-meetup-exports/dataset_meetup-compute-....json \
  --debug-filter
```

**Note:** `discovery_pipeline.py --luma-input` may pass more Luma rows than the production pipe because it injects search-query keyword provenance. Use the **Apify pipe + `luma_discovery_report.py`** path for production Luma until aligned.

---

## Don't

- Don't use browser Luma when Apify succeeds.
- Don't treat `Luma: 0` after scoring as Apify failure.
- Don't modify gateway, cron, calendar, Telegram for discovery deploys.
- Don't trigger registration or approval flows during discovery validation.

---

## Output contracts

**Luma:**

```
Luma: N
| title | date | score | tier | source | URL |
```

**Meetup:**

```
Meetup: N
| title | date | score | tier | source | matched | URL |
```

**Filter debug (stderr):**

```
filter_debug: raw=N -> pass=N -> deduped=N -> scored=N (min_score=4)
```

---

## Scripts (VPS)

| Script | Role |
|--------|------|
| `discovery_common.py` | Shared schema, filters, scoring, dedupe |
| `luma_normalize.py` | Luma → canonical schema |
| `meetup_normalize.py` | Meetup → canonical schema |
| `apify_luma.py` | Live Luma fetch |
| `luma_discovery_report.py` | Luma-only report |
| `meetup_discovery_report.py` | Meetup-only report |
| `eventbrite_normalize.py` | Eventbrite → canonical schema |
| `eventbrite_discovery_report.py` | Eventbrite-only report |
| `discovery_pipeline.py` | Combined dry-run CLI |

**Skill:** `~/.hermes/profiles/signaltable/skills/event-discovery/SKILL.md`

**Backup (pre-deploy):** `~/.hermes/profiles/signaltable/backups/discovery-refactor-2026-07-07_13-12-56/`

---

## Live validation snapshot (2026-07-07 VPS)

| Path | raw → pass → scored | min_score=4 | min_score=6 |
|------|---------------------|-------------|-------------|
| Luma (production pipe) | 45 → 3 → 3 | 3 | 3 |
| Meetup (3 exports) | 70 → 25 → 12 | 12 | 12 |
| Combined pipeline | 115 → 37 → 24 | 24 | 24 |

Production Luma top events (score 9, Tier 1): AI In The Wild (GenAI), Better Data Bolder AI, Singapore AI & Robotics Demo Night.

---

## Notes

- Meetup `approval_required` not mapped in Apify export (always null).
- HYBRID Meetup events hard-rejected (in-person-only policy).
- Replay Luma: `apify_luma.py --input dataset.json | luma_discovery_report.py`
