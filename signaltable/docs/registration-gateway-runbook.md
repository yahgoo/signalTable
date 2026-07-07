# SignalTable — Registration Gateway Runbook

## Flow (Meetup → KonfHub → LobsterMail → Calendar)

```
Discovery (Meetup)
  └─ meetup_normalize + registration_gateway.enrich_registration_fields
       ├─ event_page_url  = Meetup event page
       ├─ registration_url = KonfHub link when present, else Meetup page
       └─ registration_platform = konfhub | meetup_native | ...

Approval (Tier 2/3) — optional
  └─ approval_queue.py add → Telegram YES/NO
       └─ YES → event-register skill (Steel) at registration_url

Registration (Steel / event-register skill)
  └─ Fill name + email only when fields are standard
  └─ STOP → REGISTRATION_MANUAL_REQUIRED on CAPTCHA/login/paid/custom fields
  └─ Submit → REGISTRATION_SUBMITTED or CONFIRMATION_PENDING

Email parse (LobsterMail — fetch first, watch, notify)
  └─ lobstermail_poll.py --watch --konfhub (poll every 30s; print pending JSON)
  └─ email_confirm_validate.py (reject placeholders)
  └─ hermes send → owner Telegram on real confirmation
  └─ confirmation_status=confirmed + owner_notified_at only from fetched message

Calendar write (confirmation-gated)
  └─ calendar_write.py --write  (only after accepted_notified + owner_notified_at)
```

## Commands

```bash
# Self-test gateway + calendar gate integration (no API, no Steel)
python3 signaltable/scripts/registration_gateway.py --self-test

# Resolve KonfHub URL from discovery row
python3 signaltable/scripts/registration_gateway.py resolve \
  --input discovery_event.json --handoff

# Dry-run stop/outcome from page signals (no browser)
python3 signaltable/scripts/registration_gateway.py assess \
  --input page_signals.json

# Validate registration outcome record
python3 signaltable/scripts/registration_gateway.py record \
  --input outcome.json

# Email confirmation validation (required before calendar write)
python3 signaltable/scripts/email_confirm_validate.py --self-test
python3 signaltable/scripts/lobstermail_poll.py --self-test

# Watch KonfHub inbox (live — polls every 30s, notifies owner on match)
python3 signaltable/scripts/lobstermail_poll.py \
  --watch \
  --konfhub \
  --event-title "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026" \
  --source-url "https://konfhub.com/ksug-sg-2026-07-22" \
  --interval 30 \
  --output /tmp/konfhub-parsed-email.json

# Single poll + notify (when email already present)
python3 signaltable/scripts/lobstermail_poll.py \
  --konfhub \
  --event-title "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026" \
  --source-url "https://konfhub.com/ksug-sg-2026-07-22" \
  --notify \
  --output /tmp/konfhub-parsed-email.json

# Meetup fixture smoke (gateway extraction)
python3 - <<'PY'
import json
from pathlib import Path
from meetup_normalize import normalize_canonical
rows = json.loads(Path("signaltable/fixtures/meetup-konfhub-gateway.sample.json").read_text())
for item in rows:
    ev = normalize_canonical(item, source_query="data")
    print(ev["title"][:50], "|", ev["registration_platform"], "|", ev["registration_url"][:50])
PY

# Calendar gate still blocks unconfirmed registration outcomes
python3 signaltable/scripts/calendar_write.py --self-test
```

## Registration outcomes

| Outcome | Meaning | Calendar write? |
|---------|---------|---------------|
| `REGISTRATION_SUBMITTED` | Form submitted; on-page success | No — wait for email |
| `CONFIRMATION_PENDING` | Submitted; email expected | No — run email-parser |
| `REGISTRATION_MANUAL_REQUIRED` | CAPTCHA/login/custom fields | No — Telegram owner |
| `REGISTRATION_FAILED` | Submit error | No — stop |

## Stop / escalation conditions (do not guess)

| Signal | Outcome |
|--------|---------|
| CAPTCHA | `REGISTRATION_MANUAL_REQUIRED` |
| Login / OAuth wall | `REGISTRATION_MANUAL_REQUIRED` |
| Paid ticket shown | `REGISTRATION_MANUAL_REQUIRED` |
| Phone OTP | `REGISTRATION_MANUAL_REQUIRED` |
| Required fields beyond name/email | `REGISTRATION_MANUAL_REQUIRED` |
| Form blocked / manual-only | `REGISTRATION_MANUAL_REQUIRED` |

## Calendar confirmation gate (unchanged)

`calendar_write.py --write` requires:
- `confirmation_status` = `confirmed`
- At least one of: `confirmation_source`, `ticket_id`, `raw_email_id`, `confirmation_evidence`

Registration outcomes alone **must not** trigger calendar writes.

## Primary Eventbrite task

Keep `eventbrite-science-tech-biz-singapore-free` as primary Eventbrite Apify task. KonfHub gateway applies to Meetup rows with KonfHub links in description.

## Not in scope

- Cron / batch registration loops
- Telegram changes (approval queue already passes gateway handoff)
- Default profile changes
- Unattended mass registration
