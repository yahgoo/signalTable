# SignalTable Session Summary — 2026-07-07 (Eventbrite integration)

## Completed this session

- Added **Eventbrite source adapter** into shared discovery pipeline (same schema as Luma/Meetup).
- New files:
  - `signaltable/scripts/eventbrite_normalize.py`
  - `signaltable/scripts/eventbrite_discovery_report.py`
  - `signaltable/fixtures/eventbrite-science-tech-singapore-free.sample.json`
- Updated:
  - `discovery_pipeline.py` — `--eventbrite query:path`, `--eventbrite-input`
  - `discovery_common.py` — Science & Tech category + `eventbrite.sg` URL for Singapore
  - `skills/event-discovery.md`, `docs/event-discovery-runbook.md`

## Local validation (sample fixture)

```
filter_debug: raw=6 -> pass=2 -> deduped=2 -> scored=2 (min_score=4)
```

Top candidates:
- Singapore AI Engineering Meetup (score 10, Tier 1)
- Algorithm Study Group Singapore (score 9, Tier 1)

Rejected in fixture: paid workshop, online summit, NYC event, sunrise hike.

## Pending

- **Tier 2 VPS deploy** of Eventbrite scripts (awaiting user approval).
- **Noise filter:** real export passes business/networking events; several titles say "Free Online" while JSON-LD `eventAttendanceMode` is Offline — smallest fix: title-based online rejection in `infer_eventbrite_in_person`.
- Git commit (awaiting user approval).

## JSON-LD fix validation (2026-07-07)

Real export: `dataset_eventbrite-science-tech-biz-singapore-free_2026-07-07_06-38-11-906.json`

| Stage | Before | After |
|-------|--------|-------|
| raw | 20 | 20 |
| pass | 0 | 6 |
| deduped | 0 | 6 |
| scored | 0 | 6 |

Fixture still passes: 6 raw → 2 scored.

## Exact next step

1. Export Apify dataset from `eventbrite-science-tech-singapore-free` task to:
   `dataset_eventbrite-science-tech-singapore-free_<timestamp>.json`
2. Run local dry-run:
   ```bash
   python3 signaltable/scripts/eventbrite_discovery_report.py \
     --input dataset_eventbrite-science-tech-singapore-free_....json \
     --debug-filter
   ```
3. If field mappings match, deploy to VPS (Tier 2) with backup.

## Not touched

Registration, Telegram, cron, default profile, calendar_write, discovery scoring thresholds.
