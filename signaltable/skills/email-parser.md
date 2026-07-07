# SignalTable: Email Parser Skill

## Purpose
Poll the LobsterMail inbox for KonfHub confirmation emails, notify the owner, and hand off to calendar-updater.

**LobsterMail is the source of truth.** Never invent confirmation JSON. Never use placeholder IDs from examples.

## Production rule (mandatory)
- **Only** run `lobstermail_poll.py` for confirmation handling.
- **Do not** use LobsterMail MCP tools (`check_inbox`, `list_inboxes`, `get_email`, etc.) for confirmation parsing.
- **Do not** write confirmation JSON by hand or from memory.
- **Do not** call `email_confirm_validate.py --input` on agent-built JSON.
- The user does not manually inspect the inbox.
- **No calendar write** unless poll returns `action=accepted_notified` with `owner_notified_at`.

## Production command (watch + notify — use after KonfHub registration)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/lobstermail_poll.py \
  --watch \
  --konfhub \
  --event-title "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026" \
  --source-url "https://konfhub.com/ksug-sg-2026-07-22" \
  --interval 30 \
  --output /tmp/konfhub-parsed-email.json
```

Behavior:
1. **Fetch first** — LobsterMail REST API every `--interval` seconds (default 30).
2. **Pending** — prints JSON each poll (`action=pending`, `poll_attempt`, `next_poll_in_sec`); keeps polling.
3. **Accepted** — validates fetched message, sends owner Telegram via `hermes send`, stamps `owner_notified_at`.
4. **Calendar** — only after `action=accepted_notified` and `calendar_write_allowed=true`.

Single poll when email may already be present:

```bash
python3 ~/.hermes/profiles/signaltable/scripts/lobstermail_poll.py \
  --konfhub \
  --event-title "<event title>" \
  --source-url "<konfhub url>" \
  --notify \
  --output /tmp/konfhub-parsed-email.json
```

Outcomes:
- `action=accepted_notified` → use `--output` JSON for `calendar_write.py --dry-run`
- `action=pending` / `pending_timeout` → stop; re-run `--watch`
- `action=rejected` / `notify_failed` → stop; do not fabricate JSON

## Disabled in production
- LobsterMail MCP inbox tools for confirmation
- Manual/freeform confirmation JSON files
- `email_confirm_validate.py --input` on non-poll payloads
- `lobstermail_poll.py --fixture` (fixture mode is self-test only)

## Required output fields (from poll script only)

```json
{
  "event_title": "...",
  "confirmation_status": "confirmed",
  "confirmation_source": "konfhub_email",
  "raw_email_id": "eml_...",
  "message_from": "...",
  "message_subject": "...",
  "message_received_at": "...",
  "inbox_fetched_at": "...",
  "confirmation_evidence": "lobstermail_poll inbox=... message_id=...",
  "registration_email": "signaltable-reg@lobstermail.ai",
  "owner_notified_at": "...",
  "source_url": "https://konfhub.com/..."
}
```

**Rejected by validator/calendar gate:**
- `EVT-12345`, `123456`, placeholder IDs
- `registration@konfhub.com` as `registration_email`
- Any evidence not containing `lobstermail_poll`
- Missing `owner_notified_at`

## Calendar handoff (after accepted_notified only)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py \
  --input /tmp/konfhub-parsed-email.json --dry-run
```

Then `--write` only when operator approves.

**Never write calendar on registration outcome alone.**

## Operator self-test (VPS, no Telegram)

```bash
python3 ~/.hermes/profiles/signaltable/scripts/lobstermail_poll.py --self-test
python3 ~/.hermes/profiles/signaltable/scripts/email_confirm_validate.py --self-test
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py --self-test
```

## Log

```
[2026-07-07 19:40 SGT] EMAIL_POLL pending attempt=3 next=30s event="KSUG.AI ..."
[2026-07-07 19:42 SGT] EMAIL_PARSED: "KSUG.AI ..." | raw_email_id: eml_... | owner_notified
```
