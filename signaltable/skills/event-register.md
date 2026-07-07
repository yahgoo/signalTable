# SignalTable: Event Registration Skill

## Purpose
Register for a given event using Steel browser. Only call this skill after tier classification and (for Tier 2/3) owner approval via Telegram.

## Pre-conditions (verify before acting)
1. Event tier has been determined (Tier 1 only for auto-register; Tier 2/3 require explicit Telegram approval from user 1697120790).
2. Event is not already in the calendar — check with:
   ```bash
   python3 ~/.hermes/profiles/signaltable/scripts/gcal.py list \
     --calendar "$GOOGLE_CALENDAR_ID" \
     --from "<date-1d>" --to "<date+1d>" \
     --q "<event_title>"
   ```
3. LobsterMail inbox is ready for confirmation receipt.

## Steps

### 1. Get LobsterMail Registration Email
The dedicated registration email address is stored in `~/.hermes/profiles/signaltable/.env` as `LOBSTERMAIL_INBOX_ADDRESS`.

If not set, create it:
```
Use the lobstermail MCP tool: create_inbox with name "signaltable-reg"
Store the returned address in ~/.hermes/profiles/signaltable/.env as LOBSTERMAIL_INBOX_ADDRESS=<address>
```

### 2. Open Event Registration Page
Resolve the authoritative registration URL before navigating:

- **Meetup + KonfHub:** use `registration_url` (KonfHub link), NOT the Meetup event page.
- **Meetup native RSVP:** use Meetup event URL.
- Handoff JSON from approval queue includes `registration_platform` and `registration_url`.

Dry-run gateway resolution locally:
```bash
python3 ~/.hermes/profiles/signaltable/scripts/registration_gateway.py resolve \
  --input discovery_event.json --handoff
```

Use the Steel browser to navigate to `registration_url`:
```
browser_navigate(url=<registration_url>)
```

**KonfHub-specific:** KonfHub is the authoritative signup gateway. Fill only standard fields (name, email). Do not invent answers for custom questions.

Take a screenshot and **STOP** (outcome `REGISTRATION_MANUAL_REQUIRED`) if any of:
- Login wall / OAuth required
- CAPTCHA detected
- Price > 0 shown on registration page (even if listed as free in discovery)
- Phone OTP or non-standard required fields (company, LinkedIn, etc.)
- Form inaccessible (iframe/blocked)

Assess stop conditions without guessing (optional dry-run after page inspect):
```bash
python3 ~/.hermes/profiles/signaltable/scripts/registration_gateway.py assess \
  --input page_signals.json
```

### 3. Fill Registration Form
Standard fields:
- Name: use the value of `SIGNALTABLE_FULL_NAME` from .env (default: "kmsum")
- Email: use `LOBSTERMAIL_INBOX_ADDRESS`
- Any required fields: fill with sensible defaults, or Telegram-escalate if ambiguous

Do NOT:
- Accept paid add-ons or upgrades
- Subscribe to marketing newsletters (uncheck by default)
- Click any "Share with organizer" expanded permissions

### 4. Submit and Capture Confirmation
After submitting, capture:
- On-page confirmation text (screenshot)
- Order/ticket number if shown
- Any QR code shown (capture as image)

Record result using standard outcomes:
```json
{
  "event_title": "...",
  "registration_url": "...",
  "registration_platform": "konfhub",
  "outcome": "REGISTRATION_SUBMITTED",
  "reason": "Form submitted with on-page confirmation",
  "ticket_id": "...",
  "email_used": "signaltable-reg@lobstermail.ai",
  "registered_at": "2026-07-03T08:15:00+08:00"
}
```

Valid `outcome` values:
- `REGISTRATION_SUBMITTED` — form submitted; on-page success
- `CONFIRMATION_PENDING` — submitted; awaiting email (most KonfHub flows)
- `REGISTRATION_MANUAL_REQUIRED` — CAPTCHA/login/custom fields; owner must finish
- `REGISTRATION_FAILED` — submit error; do not retry unattended

Validate/normalize outcome record:
```bash
python3 ~/.hermes/profiles/signaltable/scripts/registration_gateway.py record \
  --input outcome.json
```

**Do NOT call `calendar_write.py --write` here.** Calendar write requires LobsterMail confirmation evidence.

### 5. Trigger Email Check
After registration, immediately trigger the email-parser skill with a 2-minute wait:
```
Wait 2 minutes, then run email-parser skill for this event's confirmation email.
```

### 6. Log
Append to `~/.hermes/profiles/signaltable/logs/signaltable.log`:
```
[2026-07-03 08:15 SGT] REGISTERED: "Singapore AI Meetup" (Tier 1) | ticket: <real-ticket-id> | email: signaltable-reg@lobstermail.ai
```
