# SignalTable — Calendar Write Runbook

## Flow

1. **Discovery** (`event-discovery`) — finds Singapore / in-person / free / tech candidates. **Never writes calendar.**
2. **Registration** (`event-register`) — optional; submits attendee form.
3. **Email parse** (`email-parser`) — reads LobsterMail confirmation; outputs `confirmation_status`.
4. **Calendar write** (`calendar_write.py`) — only if `confirmation_status == confirmed` with evidence fields.

## Commands (VPS)

```bash
# Gate + mapper self-test (no Google API)
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py --self-test

# Inspect mapping before write
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py \
  --input confirmed.json --dry-run

# Write after real confirmation
python3 ~/.hermes/profiles/signaltable/scripts/calendar_write.py \
  --input confirmed.json --write
```

## Confirmation gate

| Check | Required |
|-------|----------|
| `confirmation_status` | exactly `confirmed` |
| Evidence (≥1) | `confirmation_source`, `ticket_id`, `raw_email_id`, or `confirmation_evidence` |
| Inbox evidence | `email_confirm_validate.py` must accept payload (real `raw_email_id`, message linkage, no placeholders) |
| Owner notify | `owner_notified_at` required (set by `lobstermail_poll.py --watch` or `--notify`) |

Discovery rows without these fields **must** return `action: rejected`.

## Email confirmation validation

**Primary:** watch LobsterMail (fetch first, parse second, notify owner, then calendar):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/lobstermail_poll.py --self-test

python3 ~/.hermes/profiles/signaltable/scripts/lobstermail_poll.py \
  --watch \
  --konfhub \
  --event-title "KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026" \
  --source-url "https://konfhub.com/ksug-sg-2026-07-22" \
  --interval 30 \
  --output /tmp/konfhub-parsed-email.json
```

Each pending poll prints JSON (`action=pending`, `poll_attempt`, `next_poll_in_sec`). On match: Telegram notify → `owner_notified_at` → `calendar_write_allowed=true`.

**Secondary:** validate agent-built JSON (only after MCP fetch):

```bash
python3 ~/.hermes/profiles/signaltable/scripts/email_confirm_validate.py \
  --input candidate.json
```

**Operator rule:** Hermes polls LobsterMail directly; the user does not manually inspect the inbox. No `--write` unless poll returns `accepted_notified` with real fetched evidence and `owner_notified_at`.

Rejected placeholders: `EVT-12345`, `123456`, `registration@konfhub.com` as `registration_email`.

## Dedup

`calendar_write.py --write` delegates to `gcal.py create`, which dedupes by normalized title + event date (±1 day window). Duplicate → `duplicate_skipped`.

## Remaining before cron/batch

- Wire email-parser output JSON to `calendar_write.py --write` in Hermes skill flow
- Append `CALENDAR_ADDED` / `CALENDAR_SKIP` to `signaltable.log`
- Batch loop over multiple confirmations (not implemented)
- Cron trigger after email-parser (not implemented)
