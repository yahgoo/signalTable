# SignalTable Session — LobsterMail Hardening & KSUG E2E Smoke (2026-07-07)

## Production hardening (deployed to VPS)

Scripts and skill synced to `~/.hermes/profiles/signaltable/`:

| Component | Path |
|-----------|------|
| LobsterMail poll/watch | `scripts/lobstermail_poll.py` |
| Confirmation validator | `scripts/email_confirm_validate.py` |
| Calendar gate | `scripts/calendar_write.py` |
| Email parser skill | `skills/email-parser/SKILL.md` |
| Self-test fixtures | `fixtures/lobstermail-inbox-*.sample.json` |

## Production rules (enforced in code + skill)

1. **Single read path:** `lobstermail_poll.py --watch --konfhub` (fetch first, parse second).
2. **No MCP/manual JSON:** `confirmation_evidence` must contain `lobstermail_poll`; MCP fallback disabled in skill.
3. **Placeholder rejection:** `EVT-12345`, `123456`, template `registration_email` rejected.
4. **Owner notify before calendar:** `owner_notified_at` required; poll sends Telegram on `accepted_notified`.
5. **No calendar write** unless dry-run approved by operator.

## LobsterMail REST fix (infra)

Cloudflare Error 1010 blocked Python `urllib` default User-Agent. Poll script sets `User-Agent: lobstermail-poll/1.0 signaltable`. Same VPS IP (`43.156.46.66`) returns HTTP 200 with that header.

## KSUG.AI #47 e2e smoke (one attempt)

| Step | Result |
|------|--------|
| Event | KSUG.AI Singapore #47 Meetup @Nutanix on 22 Jul 2026 |
| KonfHub URL | `https://konfhub.com/ksug-sg-2026-07-22` |
| Registration | **Failed** — `signaltable -z` exited after one `browser_click`; form not submitted |
| LobsterMail poll | **Works** — `action=pending`, `fetched_count=1`, inbox `ibx_kHa7R-nucb8M9V4M` |
| Calendar dry-run | **Not run** (no `accepted_notified`) |

Log: `~/.hermes/profiles/signaltable/logs/konfhub-e2e-2026-07-07.log`

## Next blocker

Interactive KonfHub registration — one-shot `-z` sessions die before submit. Options:

- `signaltable chat` with event-register skill (non `-z`)
- Fix Steel browser plugin registration on VPS
- Manual registration → run `lobstermail_poll.py --watch --konfhub`

## Not changed

Cron, default Hermes profile, Telegram gateway config.
