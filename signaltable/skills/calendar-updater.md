# SignalTable: Calendar Updater Skill

## Purpose
Add a **confirmed** event to the owner's Google Calendar via `calendar_write.py` → `gcal.py`. Prevents duplicate entries and **blocks discovery-only rows**.

## Pipeline position

```
event-discovery  →  candidates only (never writes calendar)
       ↓
event-register   →  registration attempt (separate skill)
       ↓
email-parser     →  parses confirmation email; sets confirmation_status
       ↓
calendar_write   →  confirmation gate + map + gcal create
```

**Rule:** Discovery finds candidates. Registration + confirmation email (or equivalent registration proof) proves attendance. **Only then** may calendar write run.

## Pre-conditions
- `GOOGLE_CALENDAR_ID` and `GOOGLE_CREDENTIALS_FILE` in `~/.hermes/profiles/signaltable/.env`
- Service account JSON at credentials path (default: `~/.hermes/profiles/signaltable/gcal-credentials.json`)
- Target calendar **SignalTable Events** shared with service account (Make changes to events)
- Input event has:
  - `confirmation_status` == `"confirmed"`
  - At least one evidence field: `confirmation_source`, `ticket_id`, `raw_email_id`, or `confirmation_evidence`

## Scripts

| Script | Role |
|--------|------|
| `calendar_write.py` | Confirmation gate, field mapper, dry-run / write |
| `gcal.py` | Low-level Google Calendar list/create + dedup |

## Steps

### 1. Dry-run (recommended first)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py \
  --input /path/to/confirmed_event.json \
  --dry-run
```

Returns JSON with `action: dry_run` and `gcal_args` when allowed; `action: rejected` when unconfirmed.

Built-in gate test (no API, no secrets):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py --self-test
```

### 2. Write after confirmation

```bash
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py \
  --input /path/to/confirmed_event.json \
  --write
```

Outcomes:
- `created` — new calendar event JSON from Google
- `duplicate_skipped` — `gcal.py` dedup matched title+date (`DUPLICATE_SKIPPED`)
- `rejected` — confirmation gate failed (exit code 2)
- `error` — credentials/calendar/API failure (exit code 1)

### 3. Input schema (email-parser handoff)

```json
{
  "event_title": "Singapore AI Meetup",
  "event_date": "2026-07-10T19:00:00+08:00",
  "event_end": "2026-07-10T21:00:00+08:00",
  "event_location": "WeWork Suntec City, Singapore",
  "confirmation_status": "confirmed",
  "confirmation_source": "email",
  "raw_email_id": "lm-abc123",
  "ticket_id": "<real-ticket-id-from-email>",
  "organizer_name": "...",
  "source_url": "https://lu.ma/...",
  "registration_email": "signaltable-reg@lobstermail.ai"
}
```

Alias fields also accepted: `title`, `start_time`, `end_time`, `url`, `venue_name`, `full_address`.

If `event_end` / `end_time` missing, end defaults to **start + 2 hours** (SGT).

### 4. What is rejected

- Discovery-only JSON (no `confirmation_status`)
- `confirmation_status` of `pending`, `waitlisted`, etc.
- `confirmed` without evidence fields (prevents accidental writes)

### 5. Log (after successful write)

Append to `~/.hermes/profiles/signaltable/logs/signaltable.log`:

```
[2026-07-07 13:30 SGT] CALENDAR_ADDED: "Singapore AI Meetup" | 2026-07-10T19:00+08:00 | gcal_id: <id>
```

Skip log line on `duplicate_skipped`.

### 6. Errors

If `calendar_write.py` returns `action: error`:
- Verify calendar shared with service account
- Verify `GOOGLE_CALENDAR_ID`
- Verify credentials JSON and Calendar API enabled

Do **not** retry blindly on duplicate; `duplicate_skipped` is success-from-dedup perspective.

## Not in scope (this skill)

- Batch/cron automation
- Telegram notifications
- Registration flows
- Writing from discovery output directly
