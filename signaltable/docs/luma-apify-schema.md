# Luma Apify schema — solidcode/luma-scraper field assumptions

**Production Actor:** `solidcode/luma-scraper` (pay-per-event, via `apify_luma.py`)  
**Normalizer:** `scripts/luma_normalize.py` → `normalize_raw_item()` → `normalize_canonical()`

This document records the field names the normalizer expects. It does **not** describe
`lexis-solutions/lu-ma-scraper` or other Actors. If the Actor changes, update this map and
the fallback chains in `luma_normalize.py`.

---

## Raw item shape (solidcode / lu.ma API export)

| Canonical field | Primary sources (in fallback order) |
|-----------------|-------------------------------------|
| **title** | `name`, `title`, `event.name`, `eventTitle`, `eventName` |
| **start_at** | `start_at`, `startAt`, `event.start_at`, `event.startAt`, `startDate`, `start_date` |
| **end_at** | `end_at`, `endAt`, `event.end_at`, `event.endAt`, `endDate`, `end_date` |
| **timezone** | `timezone`, `event.timezone` |
| **source_url** | `eventUrl`, `url`, `event.url`, `sourceUrl`, `link`, `pageUrl`, `page_url`, `slug` (→ `https://lu.ma/{slug}`) |
| **location / venue** | `event.geo_address_info.full_address`, `location.address`, `location.name`, `venueName`, `venue.name`, string `location`/`address` |
| **city** | `geo_address_info.city`, `location.city`, `featured_city.name` |
| **country** | `geo_address_info.country`, `location.country` |
| **description** | `description_mirror.text`, `guest_info.description`, `calendar.description_short`, `description`, `summary`, `subtitle`, `eventDescription`, `body` |
| **organizer** | `organizer.name`, `host_info.name`, `manager_info.name`, `hosts[0].name`, `hostName`, `organizerName` |
| **categories** | `categoryNames[]`, `categories[]`, `category` |
| **is_free / price** | `ticketing.isFree`, `ticket_info.is_free`, `ticket_types[]`, top-level `isFree`/`is_free`, `price` |
| **in_person** | `event.location_type`, `location_type` (`offline` / `zoom` / `virtual`) |
| **source_event_id** | `api_id`, `event.api_id` |

### solidcode shape markers (sanity check)

At least one of: `api_id`, nested `event` object, or (`name`/`title` + `start_at`/`startAt`).

### Foreign Actor markers (warn, do not silently accept)

Fields typical of other scrapers (e.g. lexis): `eventName`, `pageUrl`, `venueName`,
`startDate`, `eventDescription` **without** solidcode markers above.

---

## Compact / pre-normalized passthrough

Version A `_load_luma()` may pass items with `source=luma` + `start_time` unchanged, or
compact rows with `platform=luma` + `start_at` + `url` (not `source_url`).

| Canonical field | Compact sources |
|-----------------|-----------------|
| **url / event_page_url** | `event_page_url`, `url`, `source_url` |
| **start_time** | `start_time`, `start_at` |
| **description** | `description`, `summary` |

---

## Schema warnings

On ingest, `inspect_luma_schema()` emits warnings (stderr + `normalization_warnings` on
the event dict) when:

- Foreign Actor field names detected without solidcode markers
- Critical fields empty after normalization: `title`, `start_time`, `url`, `venue/location`, `description`, `price`
- Raw solidcode rows missing expected top-level fields (`title`, `start_at`) or wrong types (`start_at` not str)

Warnings do **not** drop events — they flag drift for operator review.

---

## Regression tests

```bash
python3 luma_normalize.py --self-test
```

- `solidcode_shape_ok` — representative solidcode row normalizes with no foreign-schema warnings
- `wrong_shape_warns` — lexis-like row triggers warnings, not silent blank output
