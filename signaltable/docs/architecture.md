# SignalTable — Architecture Review Document

**Prepared for**: LLM review  
**Date**: 2026-07-05  
**Status**: PortEden removed; awaiting Google Calendar replacement implementation  
**VPS**: `ubuntu@43.156.46.66` (Tencent Cloud Singapore, Ubuntu)  
**Hermes profile**: `~/.hermes/profiles/signaltable/`

---

## 1. Project Goal

SignalTable is an autonomous Hermes agent that:

1. Discovers Singapore tech/data/AI events daily from Eventbrite, Meetup, and Luma
2. Filters events by relevance (scoring 0–10) and classifies into approval tiers
3. Auto-registers for Tier 1 events using a headless browser
4. Reads confirmation emails from a dedicated LobsterMail inbox
5. Adds confirmed events to a Google Calendar (iPhone-synced)
6. Sends daily digests and approval requests to the owner via Telegram

---

## 2. PortEden — What It Was and Why It Was Dropped

### What PortEden was supposed to do

PortEden was chosen as a "data firewall" proxy between the Hermes agent and Google Calendar. The intended flow was:

```
Hermes agent → porteden-calendar MCP → PortEden API → Google Calendar API
```

Benefits claimed: token isolation, PII redaction, audit log, scoped permissions.

### What went wrong

**Root cause: Google OAuth scope was read-only (`GOOGLE_TV_APP`).**

When the PortEden account first connected to Google Calendar, it used a device/TV OAuth flow (`GOOGLE_TV_APP` provider type) which only requests `calendar.readonly` scope. All subsequent PortEden token permission changes in the dashboard had no effect because Google's OAuth grant is a hard ceiling — the PortEden API layer cannot upgrade it unilaterally.

**Error observed on every calendar write attempt:**

```
Error: Access denied: the calendar provider denied the operation.
The connected account may not have permission to perform this action.
```

**Debugging steps taken:**

| Step | Result |
|------|--------|
| Updated token permissions in PortEden dashboard (Create Events ON) | No effect — Google still blocked writes |
| Revoked PortEden from Google ([myaccount.google.com/permissions](https://myaccount.google.com/permissions)) | Connection marked broken in PortEden (`authentication failed`) but no reconnect UI appeared |
| Tried `npx @porteden/cli connect google` | Package `@porteden/cli` does not exist on npm (404) |
| Tried `porteden connect google` CLI command | Command does not exist in porteden v0.4.0 |
| Tried `curl https://api.porteden.com/...` from Mac and VPS | `api.porteden.com` does not resolve (DNS 000); real endpoint is `cliv1b.porteden.com` |
| Looked for Connections/Reconnect in PortEden dashboard | No such UI element found; only "Disable" on the agent Apps tab |
| Tried `https://my.porteden.com/calendar-providers` | Not attempted (plan pending) |

**Verbose CLI output confirming root cause:**

```
[DEBUG] Request: GET https://cliv1b.porteden.com/api/access/calendar/calendars
[DEBUG] Response: 200 OK
...
Access: Calendar authentication with Google has failed.
The user should reconnect at https://my.porteden.com.
Provider: GOOGLE_TV_APP
```

**Why PortEden was dropped:**

- The reconnect flow is broken or inaccessible in the current PortEden UI
- For a personal single-user autonomous agent, PortEden's security benefits (PII redaction, audit log) add no meaningful value
- A direct Google Calendar API integration is simpler, more reliable, and has no proxy dependencies

---

## 3. Revised Architecture (PortEden Removed)

```
Cron Scheduler (8AM SGT)
  └─ Hermes signaltable agent (GLM-5.2 via Tencent TokenHub)
       │
       ├─ event-discovery skill
       │    ├─ apify_luma.py + luma_discovery_report.py (Luma — preferred, read-only)
       │    └─ Scrapling / browser fallback (Meetup, Eventbrite; Luma fallback only)
       │
       ├─ event-register skill
       │    └─ Steel Cloud Browser (form fill, CAPTCHA detection)
       │         └─ LobsterMail inbox (signaltable-reg@lobstermail.ai)
       │
       ├─ email-parser skill
       │    └─ LobsterMail MCP (inbox poll, injection risk scoring)
       │
       ├─ calendar-updater skill
       │    └─ gcal.py (Python helper script, Google Calendar API directly)
       │         └─ Google Calendar "SignalTable Events"
       │              └─ syncs to iPhone Google Calendar app
       │
       └─ telegram-reporter skill
            └─ signaltable_bot → Telegram → kmsum (user 1697120790)
```

### What stays the same

- SOUL.md (agent identity, approval tiers, behavior rules)
- event-discovery skill
- event-register skill
- email-parser skill
- telegram-reporter skill
- LobsterMail MCP
- Steel browser
- Telegram gateway (default Hermes profile, systemd)
- GLM-5.2 / TokenHub model config

### What changes

| Component | Old | New |
|-----------|-----|-----|
| Google Calendar write | PortEden MCP (`mcp-remote`) | `gcal.py` Python script (direct API) |
| Google auth | PortEden OAuth (broken, `GOOGLE_TV_APP`) | Google service account or OAuth desktop credentials |
| calendar-updater skill | calls PortEden MCP tools | calls `python3 gcal.py create ...` |
| `mcp_servers` config | `porteden-calendar` entry | removed |
| `.env` keys | `PE_API_KEY`, `PORTEDEN_CALENDAR_ID` | `GOOGLE_CALENDAR_ID`, `GOOGLE_CREDENTIALS_FILE` |
| porteden CLI | installed at `/usr/local/bin/porteden` | can be removed or left harmlessly |

---

## 4. Current State on VPS (as of 2026-07-05)

### What is deployed and working

| Component | Status |
|-----------|--------|
| Hermes v0.17.0 | Running |
| signaltable profile | Created at `~/.hermes/profiles/signaltable/` |
| `signaltable` CLI alias | Working (`~/.local/bin/signaltable`) |
| GLM-5.2 via TokenHub | Working (tested) |
| Telegram gateway (default profile) | Running (PID 316547, systemd) |
| SOUL.md | Deployed |
| 5 custom skills | Deployed (event-discovery, event-register, email-parser, calendar-updater, telegram-reporter) |
| Scrapling skill + Python package | Installed (v0.4.9) |
| LobsterMail MCP config | In config.yaml |
| Steel browser config | `browser.cloud_provider: steel` set |
| Backup | `~/hermes-backup-20260703-140158.tar.gz` |
| plan-log.md, integrations.md, comparison.csv | Deployed to profile dir |

### What is pending

| Component | Status | Blocker |
|-----------|--------|---------|
| Google Calendar write | Broken | PortEden OAuth scope (now being replaced) |
| `gcal.py` script | Not written | Needs Google Cloud credentials first |
| Steel browser | Configured but not tested | `STEEL_API_KEY` set but write not tested |
| LobsterMail inbox | Not provisioned | Needs first MCP call to auto-create |
| Cron job | Not created | Waiting for all integrations to pass smoke tests |

### Current `.env` keys on VPS

```
TELEGRAM_BOT_TOKEN=     # set (inherited from default profile)
TELEGRAM_ALLOWED_USERS= # 1697120790
TELEGRAM_HOME_CHANNEL=  # 1697120790
STEEL_API_KEY=          # set
SIGNALTABLE_FULL_NAME=  # set ("Sum Kok Meng")
PE_API_KEY=             # set but will be removed
PORTEDEN_CALENDAR_ID=   # placeholder, will be replaced
LOBSTERMAIL_INBOX_ADDRESS= # signaltable-reg@lobstermail.ai (placeholder until provisioned)
```

### Current `mcp_servers` in config.yaml

```yaml
mcp_servers:
  lobstermail:
    command: npx
    args: ["-y", "@lobsterkit/lobstermail-mcp@latest"]
  porteden-calendar:          # TO BE REMOVED
    command: npx
    args: ["-y", "mcp-remote", "https://mcp.porteden.com/calendar"]
```

---

## 5. Implementation Plan

### Step 1 — Google Cloud setup (manual, owner action)

**Option A: Service account (recommended for headless cron)**

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project (e.g. "SignalTable")
3. Enable **Google Calendar API**
4. Create a **Service Account** → download JSON key
5. In Google Calendar, create calendar named **"SignalTable Events"**
6. Share that calendar with the service account email (give it "Make changes to events" permission)
7. Note the calendar ID from Google Calendar settings (looks like `abc123@group.calendar.google.com`)
8. Copy the JSON key to VPS: `scp service-account.json ubuntu@43.156.46.66:~/.hermes/profiles/signaltable/gcal-credentials.json`

**Option B: OAuth desktop credentials**

1. Same steps 1–3 above
2. Create **OAuth 2.0 Client ID** → Desktop application
3. Download `credentials.json`
4. Run auth script once on a machine with a browser to generate `token.json`
5. Copy both to VPS

Service account (Option A) is preferred — no browser OAuth ever needed, ideal for cron.

### Step 2 — Write `gcal.py`

File location on VPS: `~/.hermes/profiles/signaltable/scripts/gcal.py`

Supported commands:

```bash
# List events for dedup check (returns JSON array)
python3 gcal.py list \
  --calendar "$GOOGLE_CALENDAR_ID" \
  --from "2026-07-09" --to "2026-07-11" \
  --q "event title keyword"

# Create event (returns JSON with event id, or prints "DUPLICATE_SKIPPED")
python3 gcal.py create \
  --calendar "$GOOGLE_CALENDAR_ID" \
  --summary "Event Title" \
  --start "2026-07-10T19:00:00+08:00" \
  --end "2026-07-10T21:00:00+08:00" \
  --description "Ticket: EVT-123 | Source: https://..."
```

Dependencies: `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib`
Install: `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`

### Step 3 — Update config and skills

**Files to change:**

- `~/.hermes/profiles/signaltable/config.yaml` — remove `porteden-calendar` from `mcp_servers`
- `~/.hermes/profiles/signaltable/skills/calendar-updater.md` — replace PortEden MCP calls with `gcal.py` shell calls
- `~/.hermes/profiles/signaltable/skills/event-register.md` — remove PortEden pre-condition check
- `~/.hermes/profiles/signaltable/.env` — replace `PE_API_KEY`/`PORTEDEN_CALENDAR_ID` with `GOOGLE_CALENDAR_ID`/`GOOGLE_CREDENTIALS_FILE`

**New `calendar-updater.md` flow:**

```
1. Run: python3 gcal.py list --calendar $GOOGLE_CALENDAR_ID --from <d-1> --to <d+1> --q "<title>"
   → If event found: log CALENDAR_SKIP, stop
2. Run: python3 gcal.py create --calendar $GOOGLE_CALENDAR_ID --summary "..." --start "..." --end "..." --description "..."
   → On success: log CALENDAR_ADDED
   → On error: send Telegram alert, log error
```

### Step 4 — Smoke tests

```bash
# On VPS
python3 ~/.hermes/profiles/signaltable/scripts/gcal.py list \
  --calendar "$GOOGLE_CALENDAR_ID" --from "2026-07-05" --to "2026-07-06"

python3 ~/.hermes/profiles/signaltable/scripts/gcal.py create \
  --calendar "$GOOGLE_CALENDAR_ID" \
  --summary "SignalTable gcal.py smoke test" \
  --start "2026-07-06T15:00:00+08:00" \
  --end "2026-07-06T15:30:00+08:00" \
  --description "Test event - safe to delete"
```

Verify event appears in Google Calendar (web or iPhone app), then delete it.

### Step 5 — LobsterMail provisioning

```bash
signaltable chat "Create a LobsterMail inbox named signaltable-reg and tell me the email address"
```

Record address in `.env` as `LOBSTERMAIL_INBOX_ADDRESS`.

### Step 6 — Steel browser smoke test

```bash
signaltable chat "Navigate to https://eventbrite.sg and tell me the page title"
```

Confirms Steel API key is valid and browser sessions work.

### Step 6b — Luma discovery via Apify (production path)

**Status (2026-07-06):** Apify-first Luma discovery is **live on VPS**. The deterministic filter pipeline (`luma_normalize.py` → `luma_discovery_report.py`) is the preferred production path; browser is fallback only.

Browser-based Luma discovery on qwen-turbo can loop on repeated clicks. Use Apify for structured, read-only Luma discovery first; Hermes passes through the script output unchanged.

```bash
python3 ~/.hermes/profiles/signaltable/scripts/apify_luma.py \
  --location singapore --queries data,algorithm,compute --max-items 50 \
  | python3 ~/.hermes/profiles/signaltable/scripts/luma_discovery_report.py
```

Expected output starts with `Luma: N` followed by a markdown table (`title | date | score | tier | source | URL`). Browser fallback remains in `skills/event-discovery.md` Step 1b if Apify fails or normalized output is empty.

### Step 7 — End-to-end dry run

```bash
signaltable chat "Run the event-discovery skill and list Singapore tech events this week"
```

Review output, verify relevance scoring and tier classification.

### Step 8 — Cron job setup

Once all smoke tests pass:

```bash
signaltable cron create "0 0 * * *" \
  "Run event-discovery, register Tier 1 events, parse confirmation emails, update Google Calendar, and send daily Telegram digest." \
  --skill event-discovery --skill event-register --skill email-parser \
  --skill calendar-updater --skill telegram-reporter \
  --name signaltable-daily
```

Verify: `signaltable cron list`  
Manual trigger: `signaltable cron run signaltable-daily`

---

## 6. Revised Integrations Table

| Integration | Purpose | Method | Status |
|-------------|---------|--------|--------|
| Hermes v0.17.0 | Agent runtime | pipx, native | active |
| GLM-5.2 / TokenHub | Main reasoning model | `config.yaml` custom provider | active |
| Telegram gateway | Owner notifications + approvals | systemd (default profile) | active |
| Scrapling | Web scraping | `hermes skills install official/research/scrapling` | installed |
| Steel Browser | Headless registration browser | `browser.cloud_provider: steel` | configured, untested |
| LobsterMail MCP | Agent email inbox + injection scan | `npx @lobsterkit/lobstermail-mcp@latest` | configured, inbox not provisioned |
| Google Calendar API | Calendar write/read | `gcal.py` + service account JSON | pending |
| ~~PortEden~~ | ~~Calendar proxy~~ | ~~removed~~ | dropped |

---

## 7. Secrets Required

| Key | Source | Location on VPS |
|-----|--------|-----------------|
| `STEEL_API_KEY` | [app.steel.dev](https://app.steel.dev) | `~/.hermes/profiles/signaltable/.env` |
| `SIGNALTABLE_FULL_NAME` | Owner's full name | `~/.hermes/profiles/signaltable/.env` |
| `GOOGLE_CALENDAR_ID` | Google Calendar settings → calendar ID | `~/.hermes/profiles/signaltable/.env` |
| `GOOGLE_CREDENTIALS_FILE` | Google Cloud Console (service account JSON path) | `~/.hermes/profiles/signaltable/.env` |
| Service account JSON | Google Cloud Console | `~/.hermes/profiles/signaltable/gcal-credentials.json` |

No longer needed: `PE_API_KEY`, `PORTEDEN_CALENDAR_ID`

---

## 8. File Map (local workspace)

```
/Users/kmsum/Downloads/signalTable/
├── step1.md                          # original project brief
├── signaltable-deploy.tar.gz         # Day 1 deployment archive
├── signaltable.env                   # copy of VPS .env (contains live keys — do not commit)
└── signaltable/
    ├── SOUL.md                       # agent identity and rules
    ├── config-overlay.yaml           # Hermes profile config (needs porteden-calendar removed)
    ├── env-template.env              # .env template (needs updating)
    ├── docs/
    │   ├── plan-log.md               # 20-day transition plan
    │   ├── integrations.md           # integration status table
    │   ├── comparison.csv            # Hermes vs Apify/MuleRun tracking
    │   └── architecture.md           # this file
    ├── scripts/
    │   ├── deploy.sh                 # initial deployment script
    │   ├── gcal.py                   # Google Calendar helper
    │   ├── apify_luma.py             # Apify Luma fetch (read-only)
    │   ├── luma_discovery_report.py  # filter/score/table renderer
    │   └── setup-ssh-key.sh          # SSH key authorization
    └── skills/
        ├── event-discovery.md        # scraping + relevance scoring
        ├── event-register.md         # Steel browser registration
        ├── email-parser.md           # LobsterMail inbox parser
        ├── calendar-updater.md       # Google Calendar write (needs gcal.py rewrite)
        └── telegram-reporter.md      # Telegram digest + approval messages
```

---

## 9. Rollback Instructions

```bash
# Pause cron job
signaltable cron pause signaltable-daily

# Stop signaltable gateway (if started)
signaltable gateway stop

# Restore full Hermes backup
tar -xzf ~/hermes-backup-20260703-140158.tar.gz -C ~ --strip-components=1 .hermes/config.yaml .hermes/.env
hermes gateway service install --replace
```

---

## 10. Notes for Reviewing LLM

- The VPS uses password SSH auth; the agent's local SSH key (`~/.ssh/id_ed25519`) has been added to VPS `authorized_keys` and key-based auth now works.
- The Hermes default profile gateway is running and should not be touched. The `signaltable` profile is isolated and does not have its own gateway running (uses Telegram via the default profile gateway).
- All times should use SGT (UTC+8) in logs and calendar events.
- The `porteden` CLI binary remains on the VPS at `/usr/local/bin/porteden` but is no longer used — it can be ignored or removed.
- `signaltable.env` in the local workspace contains live API keys. Do not commit, paste in chat, or push to any remote.
- The agent's Telegram bot is `signaltable_bot`, owner Telegram user ID `1697120790` (handle: kmsum).
