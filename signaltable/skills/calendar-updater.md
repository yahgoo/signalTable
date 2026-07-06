# SignalTable: Calendar Updater Skill

## Purpose
Add a confirmed event to the owner's Google Calendar via `gcal.py` (direct Google Calendar API). Prevents duplicate entries.

## Pre-conditions
- `GOOGLE_CALENDAR_ID` and `GOOGLE_CREDENTIALS_FILE` are set in `~/.hermes/profiles/signaltable/.env`
- Service account JSON exists at the credentials path (default: `~/.hermes/profiles/signaltable/gcal-credentials.json`)
- Target calendar **"SignalTable Events"** is shared with the service account email (Make changes to events)
- Event has been confirmed (`confirmation_status == "confirmed"`)

## Script location

```
~/.hermes/profiles/signaltable/scripts/gcal.py
```

## Steps

### 1. Check for Existing Entry
Before creating, search for the event by title within ±1 day of the event date:

```bash
python3 ~/.hermes/profiles/signaltable/scripts/gcal.py list \
  --calendar "$GOOGLE_CALENDAR_ID" \
  --from "<date-1d>" \
  --to "<date+1d>" \
  --q "<event_title>"
```

Returns a JSON array. If a matching event is found (same title, same date), skip creation and log:

```
[2026-07-03T08:18 SGT] CALENDAR_SKIP: "Singapore AI Meetup" already in calendar (id: <id>)
```

### 2. Create Calendar Entry
If no duplicate found:

```bash
python3 ~/.hermes/profiles/signaltable/scripts/gcal.py create \
  --calendar "$GOOGLE_CALENDAR_ID" \
  --summary "<event_title>" \
  --start "<event_date_rfc3339>" \
  --end "<event_end_date_rfc3339>" \
  --description "Organizer: <organizer_name>
Ticket: <ticket_id>
Source: <source_url>
Registration email: <lobstermail_address>

Confirmation: <confirmation_status>"
```

Notes:
- If end time is unknown, default to start + 2 hours
- All times in SGT (UTC+8), formatted as RFC 3339 with timezone offset: `2026-07-10T19:00:00+08:00`
- Include the ticket ID and source URL in the description for traceability
- `create` runs an internal dedup check; if duplicate detected, stdout is `DUPLICATE_SKIPPED` — treat as CALENDAR_SKIP

### 3. Handle Errors
If `gcal.py` prints JSON to stderr or exits non-zero:
- Send Telegram: "⚠️ SignalTable: Google Calendar write failed. Check service account permissions and calendar sharing."
- Do NOT retry without verifying credentials and calendar ACL

Common fixes:
- Calendar not shared with service account email
- Wrong `GOOGLE_CALENDAR_ID`
- Missing or invalid credentials JSON
- Google Calendar API not enabled in Google Cloud project

### 4. Log
Append to `~/.hermes/profiles/signaltable/logs/signaltable.log`:

```
[2026-07-03 08:18 SGT] CALENDAR_ADDED: "Singapore AI Meetup" | 2026-07-10T19:00+08:00 | calendar: SignalTable Events | gcal_id: <id>
```
